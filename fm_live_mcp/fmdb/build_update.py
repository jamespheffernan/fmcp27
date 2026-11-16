"""The static half of a game update: from a new plugin binary to an address map and a report.

scripts/fm_update_build.py drives this. Nothing here reads a running game. The pieces:

* `derive_all` the fmdb core's named anchors (anchors.resolve) and the address map of every
  address literal (address_map.derive), the guard rewrites, and the map document the
  address book loads (`map_document`).
* `explain` what each unresolved address was on the pinned build (its function, its kind) and
  which module and scope use it.
* `imports_diff` the import symbols of both builds, and which modelled externals of the VM
  (vm.EXTERNALS) the new build no longer imports or newly imports unmodelled.
* `allocation_sizes` the constant size passed to `operator new` right before a vtable of a
  class is stored, per class, on both builds: a record class whose allocation size changed
  has moved fields, which the address map cannot see.
* `editor_diff` the editor.fmf schema of both builds: record types, field codes, field types
  and enum values added or removed.
* `structure_changes` every load, store or add whose offset differs between the aligned
  instructions of matched changed functions (function_match.offset_changes), with global page
  offsets and stack slots left out; the ones aligned between matching calls and references in
  near-identical functions are 'confirmed', and those inside a function the reader's source
  names are listed with the files.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import time

from . import address_census, address_map, anchors

MAP_FORMAT = 'fmcp-address-map/1'


def derive_all(target, reference, *, strict=False, typed=None, census=None, log=print) -> dict:
    """{'named': {name: Anchor}, 'values': {pinned: Resolution}, 'per_file': ..., 'guards': ...}"""
    census = census or address_census.load()
    t = time.time()
    anchors.STRICT = strict
    try:
        found = anchors.resolve(target, reference=reference, typed=typed)
    finally:
        anchors.STRICT = False
    want = anchors.pinned()
    log(f'  named anchors: {sum(1 for n in want if n in found)} of {len(want)} ({time.time() - t:.0f}s)')
    t = time.time()
    named = address_map.named_values(found, want)
    values = address_map.derive(target, reference, census, named=named, strict=strict, log=log)
    per_file = getattr(address_map.derive, 'per_file', {})
    if typed:
        n = address_map.live_partners(values, census, reference, typed)
        log(f'  live type scan resolved {n} more')
    filled = fill_named(found, want, values, target)
    if filled:
        log(f'  named anchors filled from the address map: {", ".join(sorted(filled))}')
    log(f'  address literals: {sum(1 for r in values.values() if r.value is not None)} of {len(values)} '
        f'resolved ({time.time() - t:.0f}s)')
    t = time.time()
    fns = getattr(address_map.derive, 'functions', None)
    match = fns.match() if fns is not None and getattr(fns, 'matched', False) else None
    guards = address_map.guard_rewrites(target, reference, census, values, address_census.PACKAGE, match=match)
    log(f'  native guards: {guards["stats"]} ({time.time() - t:.0f}s)')
    return {'named': found, 'want': want, 'values': values, 'per_file': per_file, 'guards': guards,
            'census': census, 'match': match}


def fill_named(found: dict, want: dict, values: dict, target) -> list:
    """Named anchors that `anchors.resolve` did not find (their referencing functions changed),
    taken from the address map's resolution of the same pinned value, with a second check per
    kind: an interceptor global must also be one of the globals the bypass pattern finds on the
    new build (`virtual_bool_check_globals(7)`), with the original from its class vtable slot;
    any other anchor is taken as the address map resolved it. Returns the names filled."""
    filled = []
    pattern = None
    for name, value in want.items():
        if name in found:
            continue
        if isinstance(value, tuple):
            res = values.get(value[0])
            if res is None or res.value is None:
                continue
            if pattern is None:
                pattern = set(target.virtual_bool_check_globals(7))
            if res.value not in pattern:
                continue
            vt = target.vtable(target.type_key(value[1]), 0)
            original = target.slot(vt, value[2]) if vt else None
            if original is None:
                continue
            found[name] = anchors.Anchor(name, (res.value, value[1], value[2], original), 'address-map+pattern+rtti',
                                         f'global: {res.method} ({res.detail}), and a bypass-pattern global; '
                                         f'original: {value[1]} vtable slot {value[2]}')
            filled.append(name)
        elif isinstance(value, int):
            res = values.get(value)
            if res is not None and res.value is not None:
                found[name] = anchors.Anchor(name, res.value, f'address-map:{res.method}', res.detail)
                filled.append(name)
    return filled


def structure_offsets(sha256: str) -> dict:
    """The proven field moves of one build ({structure: {hex pinned offset: new offset | None}}),
    kept in fmdb/data/structure_offsets.json by plugin sha256. A move enters that file only with
    its proof (the aligned instructions on both builds, or a live comparison against the getter);
    the static candidates of `structure_changes` are not proof."""
    import json
    from pathlib import Path
    path = Path(__file__).with_name('data') / 'structure_offsets.json'
    if not path.exists():
        return {}
    doc = json.loads(path.read_text())
    return {k: dict(v) for k, v in (doc.get('builds', {}).get(sha256, {}).get('offsets') or {}).items()}


def map_document(target, reference, derived: dict, *, strict: bool, live: bool, version: str | None) -> dict:
    from .platform_macos_arm64 import slice_uuid
    required = [n for n in derived['want'] if n.startswith(('tables.CLASSES.', 'database.TABLES.', 'players.',
                                                              'world.', 'vm.')) and n not in derived['named']]
    return {
        'format': MAP_FORMAT, 'plugin_sha256': target.sha256, 'version': version, 'uuid': slice_uuid(target).hex(),
        'reference_sha256': reference.sha256, 'reference_path': str(reference.path),
        'strict': strict, 'live_scan': live, 'created': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'values': {f'{v:#x}': r.public() for v, r in sorted(derived['values'].items())},
        'per_file': {rel: {f'{v:#x}': r.public() for v, r in entries.items()}
                     for rel, entries in derived['per_file'].items()},
        'guards': derived['guards'],
        'disabled': {},
        # proven structure changes the hand-built decoders read through address_book.field():
        # {structure: {hex pinned offset: new offset or None}} (data/structure_offsets.json, per sha256)
        'offsets': structure_offsets(target.sha256),
        'missing_required_anchors': sorted(required),
        'verified': {'static': True, 'live': False, 'checks': {}},
    }


def explain(derived: dict, reference) -> dict:
    """Per group and module: resolved/unresolved counts, and each unresolved address with what
    it was on the pinned build and where the source uses it."""
    census = derived['census']
    values = derived['values']
    groups = defaultdict(Counter)
    modules = defaultdict(Counter)
    methods = Counter()
    unresolved = {}
    for rel, entry in census['files'].items():
        g = address_census.group_of(rel)
        for key, row in entry.items():
            if row['d'] != 'A':
                continue
            v = int(key, 16)
            res = derived['per_file'].get(rel, {}).get(v) or values[v]
            ok = res.value is not None
            groups[g]['resolved' if ok else 'unresolved'] += 1
            modules[rel]['resolved' if ok else 'unresolved'] += 1
            methods[res.method] += 1
            if not ok:
                u = unresolved.setdefault(key, {'kind': row['kind'], 'why': res.detail, 'uses': []})
                u['was'] = _was(reference, v)
                u['uses'].extend(f'{rel}:{line} ({scope})' for line, _c, scope in row['sites'][:3])
    return {'groups': {g: dict(c) for g, c in groups.items()},
            'modules': {m: dict(c) for m, c in sorted(modules.items()) if c['unresolved']},
            'methods': dict(methods.most_common()), 'unresolved': unresolved}


def _was(reference, v):
    if reference.is_code(v):
        start, end = reference.function_of(v)
        return f'code in function {start:#x} (+{v - start:#x}, {(end - start) // 4} instructions)'
    name = reference.class_name(v)
    if name:
        return f'vtable of {name}'
    where = address_map._section_of(reference, v)
    return f'data in {where[0]},{where[1]}' if where else 'outside every section'


def imports_diff(target, reference) -> dict:
    from . import vm
    mine, theirs = set(reference.image.stubs.values()), set(target.image.stubs.values())
    modelled = set(vm.EXTERNALS) | set(getattr(vm, 'FILE_EXTERNALS', ()))
    return {'imports': len(theirs), 'added': sorted(theirs - mine), 'removed': sorted(mine - theirs),
            'modelled_no_longer_imported': sorted((mine - theirs) & modelled),
            'new_imports_not_modelled': sorted((theirs - mine) - modelled)}


def _movz_x0(word):
    """Value of `movz w0/x0, #imm, lsl #hw` or None."""
    if word & 0x7F80001F == 0x52800000:      # movz (32 or 64 bit), rd = 0
        return ((word >> 5) & 0xFFFF) << (16 * ((word >> 21) & 3))
    return None


def allocation_sizes(binary, window=48) -> dict:
    """{class name: sorted sizes} of `operator new(size)` calls followed by a vtable store."""
    new_stubs = {rva for rva, name in binary.image.stubs.items() if name in ('__Znwm', '__Znam')}
    vt_names = {}
    for name, entries in binary.vtables.items():
        for ap, off in entries:
            if off == 0:
                vt_names[ap] = name
    out = defaultdict(set)
    for stub in new_stubs:
        for site in binary.calls.get(stub, ()):
            size = None
            for back in range(1, 6):
                w = binary.word(site - 4 * back)
                size = _movz_x0(w)
                if size is not None:
                    break
            if size is None:
                continue
            bounds = binary.function_of(site)
            if bounds is None:
                continue
            for use, target, kind in binary.refs_in(site, min(site + 4 * window, bounds[1])):
                name = vt_names.get(target)
                if name and kind == 'add':
                    out[name].add(size)
                    break
    return {k: sorted(v) for k, v in out.items()}


def allocation_diff(target, reference) -> dict:
    mine, theirs = allocation_sizes(reference), allocation_sizes(target)
    changed = {k: {'pinned': mine[k], 'new': theirs[k]} for k in sorted(set(mine) & set(theirs))
               if mine[k] != theirs[k]}
    db = {k: v for k, v in changed.items() if k.startswith('N2db')}
    return {'classes_with_sizes': len(theirs), 'changed': len(changed), 'changed_db_records': db,
            'changed_other': dict(list({k: v for k, v in changed.items() if k not in db}.items())[:40])}


def editor_diff(new_fmf, old_fmf) -> dict:
    from . import catalog
    a, b = catalog.load_catalog(old_fmf), catalog.load_catalog(new_fmf)
    if a.sha256 == b.sha256:
        return {'same_file': True}

    def fields(cat):
        return {s.scope: (s.field.type, s.field.enum_ref) for s in cat.iter_fields()}
    fa, fb = fields(a), fields(b)
    enums = {}
    for name in sorted(set(a.enums) | set(b.enums)):
        ea, eb = a.enums.get(name, {}), b.enums.get(name, {})
        if ea != eb:
            enums[name] = {'added': {k: eb[k] for k in sorted(set(eb) - set(ea))},
                           'removed': {k: ea[k] for k in sorted(set(ea) - set(eb))},
                           'renamed': {k: [ea[k], eb[k]] for k in sorted(set(ea) & set(eb)) if ea[k] != eb[k]}}
    return {'same_file': False, 'record_types_added': sorted(set(b.record_types) - set(a.record_types)),
            'record_types_removed': sorted(set(a.record_types) - set(b.record_types)),
            'fields_added': sorted(set(fb) - set(fa)), 'fields_removed': sorted(set(fa) - set(fb)),
            'fields_retyped': {k: [fa[k], fb[k]] for k in sorted(set(fa) & set(fb)) if fa[k] != fb[k]},
            'enums_changed': enums}


ENGLISH_TEMPLATE_IN_APP = ('Contents/PlugIns/game_plugin.bundle/Contents/Resources/data/game_simulation/templates/'
                           'user_folder/languages/example.ltf')
PINNED_ENGLISH = ('3ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43', 155367178)
# Modules that carry English text compiled from the pinned build's example.ltf and bind it to that
# file's identity: the sha256 literal (and the size the concern-history query checks). The update
# re-binds them to the new build's file only when every compiled text is the new file's text.
ENGLISH_BOUND_FILES = ('_concern_template_definitions.py', 'promise_kind_definitions.py',
                       'live_player_concern_history.py')


def _compiled_english() -> list:
    """[(translation id, compiled text)] of the modules in ENGLISH_BOUND_FILES."""
    from .. import _concern_template_definitions as concern, promise_kind_definitions as kinds
    pairs = list(concern.FIRST_KEYS.values()) + [(concern.WRAPPER_OVERRIDE_KEY, concern.WRAPPER_OVERRIDE_TEMPLATE)]
    return pairs + list(kinds.DEFINITIONS.values())


def english_template(app) -> dict:
    """Re-bind the compiled English texts to the new build's language template.

    The concern-history query reads the installed example.ltf and refuses any file other than the
    pinned build's (sha256 and size); the compiled texts it serves came from that file. When every
    compiled text (concern first templates, the wrapper override, promise kind titles) is the new
    file's text for the same id, the map records the new file's identity under `english_template`
    and the address book binds those modules to it (`files`); otherwise `verified` is False and the
    differing ids are listed (those modules keep the pinned identity, so the query keeps refusing)."""
    import hashlib
    import re
    from pathlib import Path
    path = Path(app) / ENGLISH_TEMPLATE_IN_APP
    if not path.is_file():
        return {'skipped': f'no language template at {path}'}
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    size = path.stat().st_size
    out = {'path': str(path), 'pinned_sha256': PINNED_ENGLISH[0], 'pinned_bytes': PINNED_ENGLISH[1],
           'sha256': digest, 'bytes': size, 'files': list(ENGLISH_BOUND_FILES)}
    if (digest, size) == PINNED_ENGLISH:
        return {**out, 'verified': True, 'checked': 0, 'differ': [], 'same_file': True}
    wanted = dict(_compiled_english())
    found = {}
    rx = re.compile(r'^KEY-(\d+): (.*)$')
    with open(path, encoding='utf-8', errors='replace') as handle:
        for line in handle:
            m = rx.match(line)
            if m and int(m.group(1)) in wanted:
                text = m.group(2).rstrip('\n')
                cut = text.find('[COMMENT')
                found[int(m.group(1))] = (text[:cut] if cut >= 0 else text).strip()
    differ = [{'id': k, 'compiled': v, 'new': found.get(k)} for k, v in sorted(wanted.items())
              if found.get(k) != v.strip()]
    return {**out, 'verified': not differ, 'checked': len(wanted), 'differ': differ[:40]}


def manager_checks(target, reference, values: dict) -> dict:
    """The static self-check of the manager walkers: {manager: reason} for every native manager
    whose object layout may have moved on the new build. A walker reads a manager object up to
    its allocation size and at fixed container offsets; when the allocation size of the
    manager's class (operator new before its vtable store), or the `mov w0, #size` at the
    walker's recorded allocation site, differs on the new build, that walker is disabled."""
    from . import mgr_walk_people
    from .sources import managers_market
    old_sizes, new_sizes = allocation_sizes(reference), allocation_sizes(target)
    entries = [(m.name, m.vtable, m.size, m.alloc_site) for m in mgr_walk_people.MANAGERS]
    entries += [(name, vt, size, None) for name, (_root, vt, size, _ctor) in managers_market.MANAGERS.items()]
    out = {}
    for name, vtable, size, site in entries:
        cls = reference.class_name(vtable)
        old, new = old_sizes.get(cls), new_sizes.get(cls)
        if old and new and old != new:
            out[name] = f'allocation size of {cls} changed from {old} to {new}'
            continue
        if site is not None:
            mapped = values.get(site)
            if mapped is None or mapped.value is None:
                out[name] = f'allocation site {site:#x} did not resolve'
                continue
            got = _movz_x0(target.word(mapped.value))
            if got is not None and got != size:
                out[name] = f'allocation size at the walker\'s site is {got:#x}, pinned {size:#x}'
    return out


def structure_changes(match, census, *, min_confidence=0.9) -> dict:
    """Moved structure offsets the static update can see (see the module docstring)."""
    from . import function_match as fm
    r, t = match.r, match.t
    used = defaultdict(set)
    for rel, entry in census['files'].items():
        for key, row in entry.items():
            v = int(key, 16)
            if row['d'] == 'A' and r.is_code(v):
                used[r.function_of(v)[0]].add(rel)
    raw = fm.offset_changes(match)
    confirmed, in_source = [], []
    for c in raw:
        a, b = c['function'], c['new_function']
        conf = match.how[a][1]
        i, j = (c['at'] - a) // 4, (c['new_at'] - b) // 4
        pairs = fm.align(r, a, t, b, sites=[i], match=match)
        ok = conf >= min_confidence and pairs.get(i) == j and fm.bracketed(match, a, b, pairs, i, j)[0]
        row = {'function': f'{a:#x}', 'new_function': f'{b:#x}', 'at': f'{c["at"]:#x}', 'new_at': f'{c["new_at"]:#x}',
               'kind': c['kind'], 'old': c['old'], 'new': c['new'], 'base': f'x{c["base"]}',
               'this_of': fm.owners(match, a) if c['this'] else [], 'match': match.how[a][0],
               'confidence': conf, 'confirmed': ok}
        if ok:
            confirmed.append(row)
        if a in used:
            in_source.append({**row, 'files': sorted(used[a])})
    families = Counter((c['old'], c['new']) for c in confirmed if c['kind'] in ('ldst', 'pair'))
    return {'candidates': len(raw), 'confirmed': len(confirmed),
            'confirmed_load_store_families': [{'old': o, 'new': n, 'sites': k} for (o, n), k in families.most_common(40)],
            'in_functions_the_source_names': in_source}



def emulated_functions(match) -> dict:
    """Every function the emulator calls by address, per kind (record getters, interceptor
    originals, player slots, UI handler slot functions, save routes, other fmdb code addresses):
    how many are unchanged on the new build (same masked fingerprint as their match), changed
    (matched, code differs; listed with the match method and confidence) or unmatched."""
    import gzip
    import json
    from pathlib import Path
    from . import extras, tables, vm
    data = Path(__file__).with_name('data')
    r = match.r
    kinds = defaultdict(set)
    kinds['record getters'] = {getter for _vt, (_cls, getter, _p) in tables.CLASSES.items()}
    kinds['interceptor originals'] = {original for _g, _n, _s, original in vm.INTERCEPTORS}
    kinds['player slots'] = {x for reg, virt in extras.PLAYER_SLOTS.values() for x in (reg, virt) if x}
    ui = json.loads(gzip.decompress((data / 'ui_registry.json.gz').read_bytes()))
    kinds['UI handler slot functions'] = {s['fn'] for c in ui['classes'].values() for s in c['slots'].values()
                                          if s.get('fn') and r.is_code(s['fn'])}
    routes = json.loads((data / 'persist_routes.json').read_text())
    kinds['save routes'] = {int(x['function'], 16) for x in routes['routes']} | \
        {int(routes[k], 16) for k in ('walker', 'slot_function')}
    census = address_census.load()
    kinds['other fmdb code addresses'] = {r.function_of(int(k, 16))[0] for rel, e in census['files'].items()
                                          if rel.startswith('fmdb/') for k, row in e.items()
                                          if row['d'] == 'A' and r.is_code(int(k, 16))}
    out = {}
    for kind, fns in kinds.items():
        counts, changed = Counter(), []
        for f in fns:
            start = (r.function_of(f) or (f,))[0]
            b = match.fwd.get(start)
            if b is None:
                counts['unmatched'] += 1
                changed.append({'function': f'{start:#x}', 'new': None})
            elif match.R.fp[start] == match.T.fp[b]:
                counts['unchanged'] += 1
            else:
                counts['changed'] += 1
                changed.append({'function': f'{start:#x}', 'new': f'{b:#x}', 'match': match.how[start][0],
                                'confidence': match.how[start][1]})
        out[kind] = {'functions': len(fns), **counts, 'changed_or_unmatched': sorted(changed, key=lambda c: c['function'])}
    return out
