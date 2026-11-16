"""The tactic writer's section of a build's address map (scripts/fm_update_build.py).

pi-fm's tactic writer (`adviser/pi/fm-tactic-files.py` and its `fm_tactic_*.py` siblings) runs
the game's own tactic code under Unicorn with the pinned build's addresses, guard hashes and
identity. `derive` resolves the adviser census on the new build with the reader's methods (the
same function match), re-derives the guards (hashes, bytes, and the length of a reviewed span),
checks the build facts that are not addresses against the new build's files, and lists the
writer's functions that must refuse there. `fm_live_mcp/adviser_book.py` applies the section
when the writer runs.

Build facts (`identity`):
  plugin        the new plugin's sha256 (the map is for that plugin)
  slice_offset  file offset of the arm64 slice in the plugin's fat file (the writer reads code
                from the file at slice offset + address)
  english       the language template example.ltf: verified when every English text the writer
                carries with a text id (the role names of the role catalog and of
                fm_live_mcp/prepared_tactic_roles.py, the texts of the fixed bits a stored role
                word carries beside its role, the role-matrix labels, and the 80 team
                instruction names under the text ids their native key routes load) is the new
                file's text for that id, and every text it carries without an id (mentalities,
                position names) is a text of the new file

A role in Football Manager 27 has a name and nothing else. The writer still holds the texts of the
fixed bits as internal data (the catalog's `duties` list, the reader's DUTY_BRANCHES, the second
text of each MATRIX_ROLE_LABELS entry) because its native checks compare stored words against
them; they are verified here like any other text and never reach a result of the writer.
  metadata      global-metadata.dat: verified when every enum that holds a metadata name of the
                role catalog has the same members and values in the new file
"""
from __future__ import annotations

import ast
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import struct

from . import address_census, address_map
from .. import adviser_book

ROOT = Path(__file__).resolve().parents[2]
FILES = adviser_book.FILES
PINNED_ENGLISH = ('3ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43', 155367178)
PINNED_METADATA = 'ff4780c66f37e088f363d0c4365110dd0d7968204cb36283a6262055badab21d'
ENGLISH_IN_APP = ('Contents/PlugIns/game_plugin.bundle/Contents/Resources/data/game_simulation/templates/'
                  'user_folder/languages/example.ltf')
METADATA_IN_APP = 'Contents/Resources/Data/il2cpp_data/Metadata/global-metadata.dat'
# reader modules whose English identity the writer imports (bound with the writer's texts)
READER_ENGLISH_FILES = ('prepared_tactic_roles.py',)


def build_census(reference) -> dict:
    """The adviser census on the pinned plugin (shipped as fmdb/data/adviser_census.json.gz)."""
    return address_census.build(reference, ROOT, only=FILES)


def slice_offset(path) -> int:
    """File offset of the arm64 slice of a (fat) Mach-O file."""
    from .image import CPU_ARM64, FAT_MAGIC, MH_MAGIC_64
    with open(path, 'rb') as stream:
        head = stream.read(4096)
    if struct.unpack('<I', head[:4])[0] == MH_MAGIC_64:
        return 0
    if struct.unpack('>I', head[:4])[0] != FAT_MAGIC:
        raise ValueError(f'{path}: not a Mach-O file')
    for i in range(struct.unpack('>I', head[4:8])[0]):
        cputype, _sub, offset, _size, _align = struct.unpack('>5I', head[8 + 20 * i:28 + 20 * i])
        if cputype == CPU_ARM64:
            return offset
    raise ValueError(f'{path}: no arm64 slice')


# --------------------------------------------------------------------------- derive
def derive(target, reference, plugin_path, *, app=None, functions=None, strict=False, log=print) -> dict:
    census = adviser_book.census()
    if census['pinned_sha256'] != reference.sha256:
        raise ValueError('the adviser census was taken on another pinned plugin')
    values = address_map.derive(target, reference, census, strict=strict, functions=functions)
    per_file = getattr(address_map.derive, 'per_file', {})
    fns = address_map.derive.functions
    match = fns.match() if getattr(fns, 'matched', False) else None
    guards = address_map.guard_rewrites(target, reference, census, values, ROOT, match=match,
                                        lengths_rewritten=True, review_key='adviser_guards')
    resolved = sum(1 for rel, e in census['files'].items() for k, row in e.items() if row['d'] == 'A'
                   and (per_file.get(rel, {}).get(int(k, 16)) or values[int(k, 16)]).value is not None)
    total = sum(1 for e in census['files'].values() for row in e.values() if row['d'] == 'A')
    log(f'  tactic writer: {resolved} of {total} address sites resolved; guards {guards["stats"]}')
    team = team_english(target, reference, values, app)
    english = english_check(app, team)
    metadata = metadata_check(app, plugin_path, Path(reference.path).with_name('global-metadata.dat'))
    sec = {
        'census_sha256': hashlib.sha256(adviser_book.CENSUS_PATH.read_bytes()).hexdigest(),
        'values': {f'{v:#x}': r.public() for v, r in sorted(values.items())},
        'per_file': {rel: {f'{v:#x}': r.public() for v, r in e.items()} for rel, e in per_file.items()},
        'guards': guards,
        'identity': {
            'plugin': {'pinned_sha256': census['pinned_sha256'], 'sha256': target.sha256},
            'slice_offset': {'pinned': adviser_book.PINNED_SLICE_OFFSET, 'value': slice_offset(plugin_path)},
            'english': english, 'metadata': metadata},
    }
    sec['disabled'] = disabled_functions(census, sec)
    sec['summary'] = {'address_sites': total, 'resolved': resolved, 'guards': guards['stats'],
                      'english_verified': bool(english.get('verified')),
                      'metadata_verified': bool(metadata.get('verified')),
                      'disabled': {rel: sorted(fns) for rel, fns in sec['disabled'].items()}}
    return sec


# --------------------------------------------------------------------------- refusing functions
def _function_ranges(tree):
    out = []

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = prefix + child.name
                out.append((child.lineno, child.end_lineno, q, child))
                walk(child, q + '.<locals>.')
            elif isinstance(child, ast.ClassDef):
                walk(child, prefix + child.name + '.')
            else:
                walk(child, prefix)
    walk(tree, '')
    return out


def disabled_functions(census: dict, sec: dict) -> dict:
    """{file: {function qualname: reason}}: the functions whose own code uses an address that did
    not resolve or checks a guard whose code changed (directly, or through a module-level table
    that holds one). Callers are not disabled: a caller that reaches such a function only for some
    requests keeps working for the others."""
    values, per_file = sec['values'], sec['per_file']
    failing_guards = defaultdict(dict)
    for span in sec['guards'].get('spans') or ():
        failing_guards[span['file']][span['address']] = (
            f'the native code guarded at {span["address"]:#x} ({span["length"]} bytes) differs on this build '
            f'({span["verdict"]}) and was not reviewed')
    out = {}
    for rel, entry in census['files'].items():
        tree = ast.parse((ROOT / rel).read_text())
        ranges = _function_ranges(tree)
        bad_lines = defaultdict(list)          # line -> reasons
        for key, row in entry.items():
            if row['d'] != 'A':
                continue
            res = per_file.get(rel, {}).get(key) or values.get(key) or {}
            if res.get('value') is None:
                # an address with no counterpart refuses wherever it is used
                reason = f'pinned address {key} has no counterpart ({res.get("detail") or res.get("method")})'
                for line, _col, _scope in row['sites']:
                    bad_lines[line].append(reason)
        # a guard whose code changed fails where it is checked: its own tuple (the address itself
        # may still be used elsewhere, e.g. as a call target, and is then judged by its own guard)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Tuple):
                continue
            consts = [address_map._guard_const(e) for e in node.elts]
            if sum(c is not None for c in consts) != 1:
                continue
            for e in node.elts:
                if isinstance(e, ast.Constant) and type(e.value) is int and e.value in failing_guards.get(rel, {}):
                    bad_lines[e.lineno].append(failing_guards[rel][e.value])
                    break
        # module-level names assigned on a failing line, and names derived from them
        bad_names = {}
        for stmt in tree.body:
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                lines = range(stmt.lineno, stmt.end_lineno + 1)
                reasons = [r for ln in lines for r in bad_lines.get(ln, ())]
                used = {n.id for n in ast.walk(stmt.value) if isinstance(n, ast.Name)} if stmt.value else set()
                reasons += [r for n in used if n in bad_names for r in bad_names[n]]
                if reasons:
                    targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                    for t in targets:
                        for n in ast.walk(t):
                            if isinstance(n, ast.Name):
                                bad_names[n.id] = sorted(set(reasons))
        fns = {}
        for start, end, qual, node in ranges:
            reasons = [r for ln in range(start, end + 1) for r in bad_lines.get(ln, ())]
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
            reasons += [r for n in sorted(names) if n in bad_names for r in bad_names[n]]
            if reasons:
                uniq = sorted(set(reasons))
                fns[qual] = '; '.join(uniq[:3]) + (f' (and {len(uniq) - 3} more)' if len(uniq) > 3 else '')
        # a nested function is reported through its outermost function only
        outer = {q: r for q, r in fns.items() if not any(q.startswith(o + '.<locals>.') for o in fns)}
        if outer:
            out[rel] = outer
    return out


# --------------------------------------------------------------------------- English
# A template text may carry hidden grammar arguments ("[%person#1-hidden]": the person a role name
# agrees with in languages that inflect it). They render as nothing; 27.0.1 added one to every
# role name and fixed-bit text. The visible text is what the writer compares.
HIDDEN = re.compile(r'\[%[^\]\[]*-hidden\]')


def visible(text):
    return HIDDEN.sub('', text) if text is not None else None


def _ltf_texts(path, wanted_ids=None):
    """({id: text} for the wanted ids (all when None), set of every text) of an .ltf template."""
    rx = re.compile(r'^KEY-(\d+): (.*)$')
    by_id, every = {}, set()
    with open(path, encoding='utf-8', errors='replace') as handle:
        for line in handle:
            m = rx.match(line)
            if not m:
                continue
            text = m.group(2).rstrip('\n')
            cut = text.find('[COMMENT')
            text = (text[:cut] if cut >= 0 else text).strip()
            every.add(text)
            k = int(m.group(1))
            if wanted_ids is None or k in wanted_ids:
                by_id[k] = text
    return by_id, every


def _module_literal(rel, name):
    tree = ast.parse((ROOT / rel).read_text())
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in stmt.targets):
            return ast.literal_eval(stmt.value)
    raise KeyError(f'{rel}: {name}')


def compiled_english() -> tuple[list, list]:
    """([(text id, text, where)], [(text, where)]) the writer carries: with a text id, and without."""
    keyed, unkeyed = [], []
    catalog = json.loads((ROOT / 'adviser/pi/fm_tactic_role_catalog.json').read_text())
    for phase, rows in catalog['roles'].items():
        keyed += [(r['native_resource_key'], r['compiled_english_name'], f'role catalog {phase}') for r in rows]
    keyed += [(r['native_resource_key'], r['compiled_english_name'], 'role catalog fixed bits') for r in catalog['duties']]
    roles = _module_literal('fm_live_mcp/prepared_tactic_roles.py', 'ROLE_BRANCHES')
    for phase, rows in roles.items():
        keyed += [(k, t, f'prepared_tactic_roles {phase}') for _bit, k, t in rows]
    keyed += [(k, t, 'prepared_tactic_roles fixed bits') for _bit, k, t in
              _module_literal('fm_live_mcp/prepared_tactic_roles.py', 'DUTY_BRANCHES')]
    for (_phase, _word), (role, fixed, rk, fk) in _module_literal('adviser/pi/fm-tactic-files.py', 'MATRIX_ROLE_LABELS').items():
        keyed += [(rk, role, 'fm-tactic-files MATRIX_ROLE_LABELS'), (fk, fixed, 'fm-tactic-files MATRIX_ROLE_LABELS')]
    unkeyed += [(t, 'fm-tactic-files MENTALITIES') for t in _module_literal('adviser/pi/fm-tactic-files.py', 'MENTALITIES').values()]
    return keyed, unkeyed


def _logical_imm32(w):
    """The value of a 32-bit ARM64 logical immediate (N:immr:imms of an orr/and/eor immediate)."""
    n, immr, imms = (w >> 22) & 1, (w >> 16) & 0x3F, (w >> 10) & 0x3F
    x = (~imms) & 0x3F
    if n or not x:
        return None
    esize = 1 << (x.bit_length() - 1)
    levels = esize - 1
    s, r = imms & levels, immr & levels
    if s == levels:
        return None
    welem = (1 << (s + 1)) - 1
    elem = ((welem >> r) | (welem << (esize - r))) & ((1 << esize) - 1)
    value = 0
    for i in range(0, 32, esize):
        value |= elem << i
    return value


def route_key(binary, addr, length, back=6):
    """The text id a team-instruction key route loads into w1 before its call, decoded from its
    instructions (movz, movk, add and orr immediate on w registers), looking up to `back`
    instructions before the span for a base register. None when the span holds no call (it is not
    a key route) or does not determine w1."""
    regs = {}
    for at in range(addr - 4 * back, addr + length, 4):
        w = binary.word(at)
        rd, rn = w & 31, (w >> 5) & 31
        if w & 0xFF800000 == 0x52800000:                           # movz w
            regs[rd] = ((w >> 5) & 0xFFFF) << (16 * ((w >> 21) & 3))
        elif w & 0xFF800000 == 0x72800000:                         # movk w
            hw = 16 * ((w >> 21) & 3)
            regs[rd] = (regs[rd] & ~(0xFFFF << hw)) | (((w >> 5) & 0xFFFF) << hw) if rd in regs else None
        elif w & 0xFF800000 == 0x11000000:                         # add w, w, #imm
            imm = ((w >> 10) & 0xFFF) << (12 if (w >> 22) & 1 else 0)
            regs[rd] = (regs[rn] + imm) & 0xFFFFFFFF if regs.get(rn) is not None else None
        elif w & 0xFF800000 == 0x32000000:                         # orr w, w, #imm
            imm = _logical_imm32(w)
            regs[rd] = regs[rn] | imm if regs.get(rn) is not None and imm is not None else None
        elif w & 0xFFE0FC00 == 0x2A000000:                         # orr w, w, w (no shift)
            rm = (w >> 16) & 31
            regs[rd] = regs[rn] | regs[rm] if regs.get(rn) is not None and regs.get(rm) is not None else None
        elif w & 0xFC000000 == 0x94000000:                         # bl
            if at >= addr:
                return regs.get(1)
            regs = {}
        elif w & 0xFC000000 == 0x14000000 or w == 0xD65F03C0:   # b, ret: what came before does not flow here
            regs = {}
    return None


def english_check(app, team: dict) -> dict:
    out = {'pinned_sha256': PINNED_ENGLISH[0], 'pinned_bytes': PINNED_ENGLISH[1],
           'reader_files': list(READER_ENGLISH_FILES), 'verified': False}
    if app is None:
        return {**out, 'skipped': 'no app bundle with a language template'}
    path = Path(app) / ENGLISH_IN_APP
    if not path.is_file():
        return {**out, 'skipped': f'no language template at {path}'}
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    out.update(path=str(path), sha256=digest, bytes=path.stat().st_size)
    keyed, unkeyed = compiled_english()
    keys = {k for k, _t, _w2 in keyed}
    by_id, every = _ltf_texts(path, None)
    differ = [{'id': k, 'compiled': t, 'new': by_id.get(k), 'where': w2} for k, t, w2 in keyed
              if visible(by_id.get(k)) != t]
    hidden = sum(1 for k, t, _w2 in keyed if by_id.get(k) != t and visible(by_id.get(k)) == t)
    every = every | {visible(t) for t in every}
    absent = sorted({(t, w2) for t, w2 in unkeyed if t not in every})
    out.update(checked_keyed=len(keyed), distinct_ids=len(keys), checked_unkeyed=len(unkeyed),
               equal_after_hidden_arguments=hidden,
               not_checked='position labels (D(R), AM(CL), ...): composed by the game, not template texts',
               differ=differ[:40], absent=[list(a) for a in absent[:40]], team=team,
               verified=not differ and not absent and team.get('verified') is True)
    return out


def team_english(target, reference, values, app) -> dict:
    """The 80 team-instruction names against the text ids their key routes load on the new build."""
    names = _module_literal('adviser/pi/fm_tactic_team_instructions.py', 'OPTION_NAMES')
    spans = _module_literal('adviser/pi/fm_tactic_team_instructions.py', 'NATIVE_SPANS')
    keys, undecided = {}, []
    for at, length, _sha in spans:
        if length not in (16, 20, 24):
            continue
        res = values.get(at)
        if res is None or res.value is None:
            undecided.append(f'{at:#x}: no counterpart')
            continue
        if not any(reference.word(a) & 0xFC000000 == 0x94000000 for a in range(at, at + length, 4)):
            continue                                       # no call: a guard of other code, not a key route
        old_key, new_key = route_key(reference, at, length), route_key(target, res.value, length)
        if old_key is None or new_key is None:
            undecided.append(f'{at:#x}: key not decoded')
            continue
        if old_key != new_key:
            undecided.append(f'{at:#x}: text id {old_key} on the pinned build, {new_key} on this build')
        keys[at] = new_key
    out = {'routes': len(keys), 'undecided': undecided[:20], 'names': len(names), 'verified': False}
    if app is None or not (Path(app) / ENGLISH_IN_APP).is_file():
        return {**out, 'skipped': 'no language template'}
    by_id, _every = _ltf_texts(Path(app) / ENGLISH_IN_APP, set(keys.values()))
    texts = sorted(visible(by_id.get(k)) or '' for k in keys.values())
    wanted = sorted(names.values())
    missing = sorted(set(wanted) - set(texts))
    extra = sorted(set(texts) - set(wanted))
    out.update(missing=missing, extra=extra[:20],
               verified=not undecided and len(keys) == len(names) and not missing and not extra
               and len(set(keys.values())) == len(names))
    return out


# --------------------------------------------------------------------------- metadata
def _enums(path) -> dict:
    from .ui_frontend import Metadata
    meta = Metadata(Path(path))
    out = {}
    for t in meta.types:
        fields = meta.type_fields(t)
        if any(f.name == 'value__' for f in fields):
            out.setdefault(t.full_name, meta.enum_values(t))
    return out


def catalog_metadata_names() -> set:
    catalog = json.loads((ROOT / 'adviser/pi/fm_tactic_role_catalog.json').read_text())
    names = {r['metadata_name'] for rows in catalog['roles'].values() for r in rows}
    names |= {r['metadata_name'] for r in catalog['duties']}
    names |= {c for r in catalog['positions'] for c in r['metadata_mask_components']}
    names |= {r['metadata_name'] for r in catalog['player_instructions']}
    names |= {r['metadata_name'] for r in catalog['team_instruction_phases']}
    return names


def metadata_check(app, plugin_path, pinned_path) -> dict:
    out = {'pinned_sha256': PINNED_METADATA, 'verified': False}
    candidates = [Path(app) / METADATA_IN_APP] if app else []
    candidates.append(Path(plugin_path).with_name('global-metadata.dat'))
    path = next((p for p in candidates if p.is_file()), None)
    pinned = Path(pinned_path)
    if path is None or not pinned.is_file():
        return {**out, 'skipped': 'no global-metadata.dat of this build or of the pinned build'}
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    out.update(path=str(path), sha256=digest)
    with pinned.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != PINNED_METADATA:
            return {**out, 'skipped': f'{pinned} is not the pinned build\'s metadata'}
    if digest == PINNED_METADATA:
        return {**out, 'verified': True, 'same_file': True}
    names = catalog_metadata_names()
    old, new = _enums(pinned), _enums(path)
    used = {name: members for name, members in old.items() if names & set(members)}
    covered = set().union(*(set(m) for m in used.values())) & names if used else set()
    differ = [{'enum': name, 'pinned': members, 'new': new.get(name)} for name, members in sorted(used.items())
              if new.get(name) != members]
    out.update(enums=sorted(used), names=len(names), names_covered=len(covered),
               uncovered=sorted(names - covered)[:20], differ=differ[:10],
               verified=not differ and covered == names)
    return out
