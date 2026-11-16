"""Build-independent discovery of the plugin addresses the reader pins.

Every fmdb module locates game data through RVAs of one plugin binary (build
27.0.0.2493426). This module finds them again on an arbitrary build of the plugin from
things that survive a patch, and records how each one was found:

* RTTI (`rtti`): Itanium type_info objects are found through the binds to the three
  `__cxxabiv1` type_info vtables; their mangled names are stable strings. Vtables are the
  rebased words that point at a type_info, with the offset-to-top before them, so a class
  name gives its primary vtable and every secondary vtable (the PERSON subobject vtable of
  ACTUAL_PLAYER is the one with offset-to-top -0x388). Vtable slots give functions by
  (class, slot); `__vmi_class_type_info` base lists give subobject offsets.
* code shape (`pattern`): a property getter is a comparison tree on FourCC constants; the
  game-layer interceptors are globals used as `ldr x0,[G]; ldr x8,[x0]; ldr x8,[x8,#0x38];
  blr x8; tbz/tbnz w0,#0`; the owning-thread globals are the two stores of `pthread_self()`
  around a `strb #1` flag; the date global is the global with the most halfword loads;
  `mov w0,#1; ret` is any shipped function with those two instructions.
* live type scan (`live`): with the game running, every pointer-sized word of the plugin's
  writable data segment is followed once and the object's vtable named through RTTI, which
  gives singletons by type (the 24 DATABASE_TABLE<T> roots, GAME_UI, SAVE_SYSTEM, the 15
  GAME_* interceptor objects, NEWS_MANAGER ...).
* function fingerprints (`fingerprint`): a function is hashed with every address-dependent
  field masked (ADRP pages, the page offsets paired with them, branch/call targets leaving
  the function, literal loads) and with calls to imports replaced by the import name. A
  function that a patch did not change has the same fingerprint; an anchor inside it keeps
  its offset. Data and globals are found through the n-th ADRP reference of an unchanged
  referencing function (`xref`).

Everything specific to the binary format, the C++ ABI and the instruction set sits behind
platform_model.py (implementation: platform_macos_arm64.py); the recipes below ask it questions such
as "vtable of this type", "globals asked a yes/no virtual question in slot 7" or "globals that
store the result of pthread_self()". `resolve(binary, ...)` returns {anchor name: Anchor}; `pinned()`
lists the values the modules carry for build 27.0.0.2493426 under the same names, and
`compare()` sets one against the other. Nothing here reads or writes the game except the
optional live scan, which only reads.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import re
import struct
from pathlib import Path

from .platform_model import load_binary  # noqa: F401  (the entry point for any platform)
# The macOS ARM64 model, re-exported for callers that predate platform_model.py.
from .platform_macos_arm64 import (Binary, MIN_RANKED, MIN_UNIQUE, TypeInfo, adrp_page,  # noqa: F401
                                   bl_target, find_plugin_base, is_adrp, is_fourcc, movz_movk_value,
                                   open_live, page_use, slice_uuid)

# --------------------------------------------------------------------------- anchors
@dataclass
class Anchor:
    name: str
    value: object                   # int RVA, or a structured value (tuple/dict) for group anchors
    method: str                     # rtti | pattern | live | fingerprint | xref | derived
    detail: str = ''

    def public(self):
        v = self.value
        return {'value': hex(v) if isinstance(v, int) else v, 'method': self.method, 'detail': self.detail}


def _demangled_db(name):
    """'N2db13ACTUAL_PLAYERE' -> 'ACTUAL_PLAYER' (the class names tables.CLASSES uses)."""
    m = re.fullmatch(r'N2db(\d+)([A-Z0-9_]+)E', name)
    return m.group(2) if m else None


def _db_mangled(cls):
    """Canonical type key of a `db::` record class (Itanium mangling; platform.type_key maps it)."""
    return f'N2db{len(cls)}{cls}E'


def _plain_mangled(name):
    """'11GAME_PERSON' style names are already mangled; 'GAME_PERSON' -> '11GAME_PERSON'."""
    return name if name[:1].isdigit() or name.startswith('N') else f'{len(name)}{name}'


def getter_shape(binary, start, limit=4096):
    """Number of distinct FourCC constants a function compares against (0: not a getter)."""
    return len(binary.fourcc_constants(start, limit))


def discover_rtti(binary, out: dict):
    """Vtables, slot-3 getters and primary offsets of the record classes; table vtables;
    the world/players/ui/interceptor vtables (all by RTTI name)."""
    from .. import database, players, world
    from . import tables, ui_vm
    key = binary.type_key
    person = key(_db_mangled('PERSON'))
    for _rva, (cls, _getter, _primary) in tables.CLASSES.items():
        mangled = key(_db_mangled(cls))
        if mangled not in binary.vtables:
            continue
        offset = binary.base_offset(mangled, person) if cls not in ('RETIRED_PERSON_NAME_STRINGS',
                                                                    'RETIRED_PERSON_NAME_POINTERS') else None
        if offset is None or offset == 0:
            vt = binary.vtable(mangled, 0)
            offset_note = 'primary vtable'
        else:
            vt = binary.vtable(mangled, offset)
            offset_note = f'PERSON subobject at +{offset:#x} (vmi base list)'
        if vt is None:
            continue
        out[f'tables.CLASSES.{cls}.vtable'] = Anchor(f'tables.CLASSES.{cls}.vtable', vt, 'rtti', offset_note)
        getter = binary.slot(vt, 3)
        if getter is not None:
            shape = getter_shape(binary, getter)
            thunk = ''
            if not shape:
                # PERSON subobject thunks adjust `this` and branch to the class getter
                inner = binary.first_branch_target(getter)
                thunk = f'; thunk to {inner:#x} ({getter_shape(binary, inner)} FourCCs)' if inner else ''
            out[f'tables.CLASSES.{cls}.getter'] = Anchor(f'tables.CLASSES.{cls}.getter', getter, 'rtti',
                                                         f'vtable slot 3; {shape} FourCC constants{thunk}')
        primary = offset if offset else 0
        out[f'tables.CLASSES.{cls}.primary'] = Anchor(f'tables.CLASSES.{cls}.primary', primary, 'rtti',
                                                      'offset-to-top of the table vtable')
    for kind, (_root, _vt, name) in database.TABLES.items():
        vt = binary.vtable(binary.type_key(name.decode()), 0)
        if vt is not None:
            out[f'database.TABLES.{kind}.vtable'] = Anchor(f'database.TABLES.{kind}.vtable', vt, 'rtti', name.decode())
    for kind, (_vt, name) in world.TYPES.items() if hasattr(world, 'TYPES') else []:
        vt = binary.vtable(binary.type_key(name.decode()), 0)
        if vt is not None:
            out[f'world.TYPES.{kind}'] = Anchor(f'world.TYPES.{kind}', vt, 'rtti', name.decode())
    names = (b'N2db13ACTUAL_PLAYERE', b'N2db12PLAYING_DATAE', b'N2db13ACTUAL_PLAYERE')
    ap = binary.base_offset(key('N2db13ACTUAL_PLAYERE'), person)
    apnp = binary.base_offset(key('N2db28ACTUAL_PLAYER_AND_NON_PLAYERE'), person)
    for i, (name, off) in enumerate(zip(names, (0, 0, ap))):
        vt = binary.vtable(key(name.decode()), off or 0)
        if vt is not None:
            out[f'players.RVA[{i}]'] = Anchor(f'players.RVA[{i}]', vt, 'rtti', f'{name.decode()} +{off or 0:#x}')
    for i, (name, off) in enumerate(zip((b'N2db28ACTUAL_PLAYER_AND_NON_PLAYERE', b'N2db12PLAYING_DATAE',
                                         b'N2db28ACTUAL_PLAYER_AND_NON_PLAYERE'), (0, 0, apnp))):
        vt = binary.vtable(key(name.decode()), off or 0)
        if vt is not None:
            out[f'players.STAFF_RVA[{i}]'] = Anchor(f'players.STAFF_RVA[{i}]', vt, 'rtti',
                                                    f'{name.decode()} +{off or 0:#x}')
    factory = binary.vtable(key('N11game_plugin23GAME_UI_HANDLER_FACTORYE'), 0)
    if factory is not None:
        out['ui_vm.FACTORY_VTABLE_RVA'] = Anchor('ui_vm.FACTORY_VTABLE_RVA', factory, 'rtti',
                                                 'game_plugin::GAME_UI_HANDLER_FACTORY')
        for slot, label in ((ui_vm.CLIENT_FACTORY_SLOT, 'client'), (ui_vm.SERVER_FACTORY_SLOT, 'server')):
            fn = binary.slot(factory, slot)
            if fn is not None:
                out[f'ui_vm.factory.{label}'] = Anchor(f'ui_vm.factory.{label}', fn, 'rtti',
                                                       f'factory vtable slot {slot}')
    handler = binary.vtable(key('N11siuihandler10UI_HANDLERE'), 0)
    if handler is not None:
        out['ui_vm.UI_HANDLER_BASE_VTABLE_RVA'] = Anchor('ui_vm.UI_HANDLER_BASE_VTABLE_RVA', handler, 'rtti',
                                                         binary.class_name(handler) or '')


def discover_patterns(binary, out: dict):
    """Globals and helpers found by code shape (no RTTI), through the platform's shape queries."""
    hits = binary.constant_return_functions(1)
    if hits:
        out['vm.RETURN_TRUE_RVA'] = Anchor('vm.RETURN_TRUE_RVA', hits[0], 'pattern',
                                           'first function that only returns 1')
    for target, count in sorted(binary.virtual_bool_check_globals(7).items()):
        out[f'vm.interceptor_global.{target:#x}'] = Anchor(
            f'vm.interceptor_global.{target:#x}', target, 'pattern',
            f'{count} yes/no virtual checks in slot 7 of the object at the global')
    stores = binary.call_result_stores('_pthread_self')
    flagged = [(g, f, site) for site, g, f in stores if f is not None]
    plain = [(g, f, site) for site, g, f in stores if f is None]
    if len({g for g, _, _ in flagged}) == 1:
        glob, flag, site = flagged[0]
        out['vm.THREAD_MAIN_RVA'] = Anchor('vm.THREAD_MAIN_RVA', glob, 'pattern',
                                           f'pthread_self() stored at {site:#x}, next to a flag set to 1')
        out['vm.THREAD_FLAG_RVA'] = Anchor('vm.THREAD_FLAG_RVA', flag, 'pattern', 'flag set next to the store')
        # the fallback thread word: the other pthread_self() global that the flag's readers load
        readers = {binary.function_of(use)[0] for _, use, kind in binary.refs.get(flag, ()) if kind == 'ldr8'}
        score = Counter()
        for g in {g for g, _, _ in plain if g != glob}:
            score[g] = len(readers & {binary.function_of(use)[0] for _, use, _ in binary.refs.get(g, ())})
        best = score.most_common(2)
        if best and best[0][1] and (len(best) == 1 or best[0][1] > 2 * best[1][1]):
            out['vm.THREAD_OTHER_RVA'] = Anchor('vm.THREAD_OTHER_RVA', best[0][0], 'pattern',
                                                f'pthread_self() global read with the flag in {best[0][1]} '
                                                f'of {len(readers)} functions')
    # current game date {u16 day, u16 year}: the two most halfword-loaded globals, adjacent
    top = binary.loads_by_width(16).most_common(3)
    if len(top) == 3 and abs(top[0][0] - top[1][0]) == 2 and top[1][1] > 2 * top[2][1]:
        target = min(top[0][0], top[1][0])
        out['world.CURRENT_DATE'] = Anchor('world.CURRENT_DATE', target, 'pattern',
                                           f'{{u16 day, u16 year}}: the two most halfword-loaded globals are '
                                           f'adjacent ({top[0][1]} and {top[1][1]} loads; next {top[2][1]})')


def scan_live_globals(binary, read, base, read_many=None):
    """{global RVA: type name} for every word of the plugin's writable data that points
    to an object whose first word is a vtable of this binary. Reads only."""
    lo, hi = binary.data_range()
    data = read(base + lo, hi - lo)
    words = struct.unpack(f'<{len(data) // 8}Q', data)
    image_end = binary.image_end()
    candidates = [(lo + 8 * i, w) for i, w in enumerate(words)
                  if w >= 0x1_0000_0000 and not base <= w < base + image_end and w % 8 == 0 and w < 1 << 48]
    names = {}
    vt_names = {}
    for name, entries in binary.vtables.items():
        for ap, off in entries:
            vt_names[ap] = (name, off)
    chunk = 4096
    for c in range(0, len(candidates), chunk):
        batch = candidates[c:c + chunk]
        if read_many is not None:
            values = read_many([(p, 8) for _, p in batch])
        else:
            values = []
            for _, p in batch:
                try:
                    values.append(read(p, 8))
                except Exception:  # noqa: BLE001 - unreadable pointer: not an object
                    values.append(None)
        for (slot, _p), value in zip(batch, values):
            if not value or len(value) < 8:
                continue
            vt = struct.unpack('<Q', value[:8])[0] - base
            hit = vt_names.get(vt)
            if hit and hit[1] == 0:
                names[slot] = hit[0]
    return names


def discover_live(binary, typed: dict, out: dict):
    """Typed singleton globals from a live scan (`scan_live_globals` result)."""
    from .. import database
    by_type = defaultdict(list)
    for slot, name in typed.items():
        by_type[name].append(slot)
    for kind, (_root, _vt, name) in database.TABLES.items():
        slots = by_type.get(name.decode(), [])
        if len(slots) == 1:
            out[f'database.TABLES.{kind}.root'] = Anchor(f'database.TABLES.{kind}.root', slots[0], 'live',
                                                         f'only global holding a {name.decode()}')
    for label, mangled in (('world.GAME_ROOT', 'N11game_plugin7GAME_UIE'), ('world.SAVE_ROOT', '11SAVE_SYSTEM'),
                           ('ui_recipes_news.NEWS_MANAGER_RVA', '12NEWS_MANAGER')):
        slots = by_type.get(mangled, [])
        if len(slots) == 1:
            out[label] = Anchor(label, slots[0], 'live', f'only global holding a {mangled}')
    for key, anchor in list(out.items()):
        if key.startswith('vm.interceptor_global.'):
            name = typed.get(anchor.value)
            if name:
                vt = binary.vtable(name, 0)
                original = binary.slot(vt, 7) if vt else None
                out[f'vm.INTERCEPTORS.{name}'] = Anchor(f'vm.INTERCEPTORS.{name}', (anchor.value, name, 7, original),
                                                        'pattern+live', 'global by bypass pattern, type by live scan,'
                                                        ' original = vtable slot 7')
    app = [g for g, n in typed.items() if n == '11GAME_PLAYER']
    if len(app) == 1:
        out['vm.APP_GLOBAL_RVA'] = Anchor('vm.APP_GLOBAL_RVA', app[0], 'live', 'only global holding a GAME_PLAYER')


def reference_entry(reference, rva):
    """What a later build needs to find `rva` again without the reference binary: for code,
    the containing function's fingerprint, the offset and its rank among identical functions;
    for data, up to five unique referencing functions with the number of the reference."""
    if reference.is_code(rva):
        bounds = reference.function_of(rva)
        if bounds is None:
            return None
        start, end = bounds
        fp = reference.fingerprint(start, end)
        same = reference.find_fingerprint(fp)
        return {'kind': 'code', 'fp': list(fp), 'offset': rva - start, 'rank': same.index(start),
                'count': len(same), 'at': start}
    via = []
    seen = set()
    for _adrp, use, _kind in sorted(reference.refs.get(rva, ()), key=lambda u: u[1]):
        bounds = reference.function_of(use)
        if bounds is None or bounds[0] in seen:
            continue
        seen.add(bounds[0])
        start, end = bounds
        fp = reference.fingerprint(start, end)
        if len(reference.find_fingerprint(fp)) != 1:
            continue
        mine = reference.refs_in(start, end)
        index = [i for i, (_u, t, _k) in enumerate(mine) if t == rva]
        if index:
            via.append([list(fp), index[0], len(mine)])
        if len(via) >= 5:
            break
    return {'kind': 'data', 'via': via} if via else None


# True while proving the procedure on the pinned build itself: a short function is not accepted
# merely because it sits at the pinned address (address_map.derive(strict=True)).
STRICT = False


def locate_entry(binary, entry):
    """(RVA, method, detail) of a `reference_entry` in `binary`, or None."""
    if not entry:
        return None
    if entry['kind'] == 'code':
        theirs = binary.find_fingerprint(tuple(entry['fp']))
        if len(theirs) == 1 and entry['count'] == 1 and (entry['fp'][0] >= MIN_UNIQUE or
                                                         (not STRICT and theirs[0] == entry.get('at'))):
            return theirs[0] + entry['offset'], 'fingerprint', f'function +{entry["offset"]:#x}'
        if theirs and len(theirs) == entry['count'] and entry['fp'][0] >= MIN_RANKED:
            return theirs[entry['rank']] + entry['offset'], 'fingerprint', \
                f'function +{entry["offset"]:#x}, rank {entry["rank"]} of {entry["count"]} identical'
        return None
    found = []
    for fp, index, count in entry['via']:
        theirs = binary.find_fingerprint(tuple(fp))
        if len(theirs) != 1:
            continue
        refs = binary.refs_in(theirs[0], theirs[0] + 4 * fp[0])
        if len(refs) == count:
            found.append(refs[index][1])
    values = set(found)
    if len(values) == 1:
        return values.pop(), 'xref', f'ADRP reference in {len(found)} unchanged function(s)'
    return None


def locate(binary, reference, rva):
    """`locate_entry` of `reference_entry(reference, rva)` (both binaries at hand)."""
    return locate_entry(binary, reference_entry(reference, rva))


def reference_index(reference, values: dict) -> dict:
    """{name: reference_entry} for the scalar anchors of `values` (tuples: global and original)."""
    out = {}
    for name, value in values.items():
        if isinstance(value, tuple):
            out[name + '#global'] = reference_entry(reference, value[0])
            out[name + '#original'] = reference_entry(reference, value[3])
        else:
            out[name] = reference_entry(reference, value)
    return {k: v for k, v in out.items() if v}


def reference_path(sha256: str) -> Path:
    return Path(__file__).with_name('data') / f'anchors-reference-{sha256}.json.gz'


def load_reference(sha256: str | None = None) -> dict | None:
    """The shipped reference index of the pinned build (fingerprints of every pinned anchor)."""
    import gzip
    import json
    if sha256 is None:
        from .. import players
        sha256 = players.SHA256
    path = reference_path(sha256)
    if not path.exists():
        return None
    return json.loads(gzip.decompress(path.read_bytes()))


def _tables():
    from .. import database
    return database.TABLES


# --------------------------------------------------------------------------- pinned values
def pinned() -> dict:
    """{anchor name: value} the modules carry for the pinned build (27.0.0.2493426)."""
    from .. import database, players, world
    from . import extras, tables, ui_recipes_more, ui_recipes_news, ui_recipes_person, ui_vm, vm
    out = {}
    for rva, (cls, getter, primary) in tables.CLASSES.items():
        out[f'tables.CLASSES.{cls}.vtable'] = rva
        out[f'tables.CLASSES.{cls}.getter'] = getter
        if primary is not None:
            out[f'tables.CLASSES.{cls}.primary'] = primary
    for kind, (root, vt, _name) in database.TABLES.items():
        out[f'database.TABLES.{kind}.root'] = root
        out[f'database.TABLES.{kind}.vtable'] = vt
    for i, v in enumerate(players.RVA):
        out[f'players.RVA[{i}]'] = v
    for i, v in enumerate(players.STAFF_RVA):
        out[f'players.STAFF_RVA[{i}]'] = v
    for name in ('GAME_ROOT', 'SAVE_ROOT', 'CURRENT_DATE'):
        out[f'world.{name}'] = getattr(world, name)
    for kind, (vt, _name) in world.TYPES.items():
        out[f'world.TYPES.{kind}'] = vt
    for name in ('VARIANT_REGISTRY_RVA', 'APP_GLOBAL_RVA', 'APP_BYPASS_ORIGINAL_RVA', 'RETURN_TRUE_RVA',
                 'THREAD_FLAG_RVA', 'THREAD_MAIN_RVA', 'THREAD_OTHER_RVA'):
        out[f'vm.{name}'] = getattr(vm, name)
    for global_rva, rtti, slot, original in vm.INTERCEPTORS:
        out[f'vm.INTERCEPTORS.{rtti}'] = (global_rva, rtti, slot, original)
    for i, desc in enumerate(sorted(vm.TLV_REFUSED)):
        out[f'vm.TLV_REFUSED[{i}]'] = desc
    out['ui_vm.FACTORY_VTABLE_RVA'] = ui_vm.FACTORY_VTABLE_RVA
    out['ui_vm.UI_HANDLER_BASE_VTABLE_RVA'] = ui_vm.UI_HANDLER_BASE_VTABLE_RVA
    for rva, (name, _fn) in ui_vm.INTERCEPTS.items():
        out[f'ui_vm.INTERCEPTS.{name}'] = rva
    for module, names in ((ui_recipes_person, ('BAG_INSERT_RVA', 'PARAM_LOOKUP_RVA', 'PARAM_HOOK_RVA',
                                               'PARAM_FOUND_RVA', 'INT32_VARIANT_RVA', 'VISION_OWNER',
                                               'VISION_FILTER', 'VISION_FLAG')),
                          (ui_recipes_more, ('PARAM_LOOKUP_RVA', 'INT32_VARIANT_RVA')),
                          (ui_recipes_news, ('NEWS_MANAGER_RVA', 'RESOLVE_RVA', 'SI_DATE_TRAITS_RVA'))):
        for name in names:
            out[f'{module.__name__.rsplit(".", 1)[1]}.{name}'] = getattr(module, name)
    for slot, (regular, virtual) in extras.PLAYER_SLOTS.items():
        out[f'extras.PLAYER_SLOTS.{slot}.regular'] = regular
        if virtual is not None:
            out[f'extras.PLAYER_SLOTS.{slot}.virtual'] = virtual
    return out


def discover_slots(binary, out: dict):
    """extras.PLAYER_SLOTS: ACTUAL_PLAYER / VIRTUAL_PLAYER primary vtable slots by index."""
    from . import extras
    regular = binary.vtable(binary.type_key('N2db13ACTUAL_PLAYERE'), 0)
    virtual = binary.vtable(binary.type_key('N2db14VIRTUAL_PLAYERE'), 0)
    for slot, (_reg, virt) in extras.PLAYER_SLOTS.items():
        if regular is not None and binary.slot(regular, slot):
            out[f'extras.PLAYER_SLOTS.{slot}.regular'] = Anchor(
                f'extras.PLAYER_SLOTS.{slot}.regular', binary.slot(regular, slot), 'rtti',
                f'ACTUAL_PLAYER primary vtable slot {slot}')
        if virt is not None and virtual is not None and binary.slot(virtual, slot):
            out[f'extras.PLAYER_SLOTS.{slot}.virtual'] = Anchor(
                f'extras.PLAYER_SLOTS.{slot}.virtual', binary.slot(virtual, slot), 'rtti',
                f'VIRTUAL_PLAYER primary vtable slot {slot}')


def resolve(binary, *, reference = None, index: dict | None = None,
            typed: dict | None = None) -> dict:
    """Every pinned anchor name -> Anchor for `binary`, by the strongest method that finds it.

    Order: RTTI, code pattern, live type scan (`typed`, from `scan_live_globals`), then
    fingerprint/xref for what is left, from `index` (the shipped `reference_index` of the
    pinned build) or computed from `reference` (the pinned binary itself). Where two
    methods find a value and disagree, the anchor is withheld (`conflicts`)."""
    out = {}
    discover_rtti(binary, out)
    discover_slots(binary, out)
    discover_patterns(binary, out)
    want = pinned()
    if typed is not None:
        discover_live(binary, typed, out)
        reg = [g for g, n in typed.items() if n == 'N6sicore20TYPED_TRAITS_MANAGERE']
        if len(reg) == 1:
            out['vm.VARIANT_REGISTRY_RVA'] = Anchor('vm.VARIANT_REGISTRY_RVA', reg[0], 'live',
                                                    'only global holding a sicore::TYPED_TRAITS_MANAGER')
    # interceptor tuples: pattern globals + live types; the APP_* triplet follows GAME_PLAYER
    app = out.get('vm.INTERCEPTORS.11GAME_PLAYER')
    if app is not None:
        out.setdefault('vm.APP_GLOBAL_RVA', Anchor('vm.APP_GLOBAL_RVA', app.value[0], app.method, app.detail))
        out['vm.APP_BYPASS_ORIGINAL_RVA'] = Anchor('vm.APP_BYPASS_ORIGINAL_RVA', app.value[3], app.method,
                                                   'GAME_PLAYER vtable slot 7')
    fingerprints = {}
    if index is None and reference is not None:
        index = reference_index(reference, want)
    for key, entry in (index or {}).items():
        name = key.split('#', 1)[0]
        if name not in want or key.endswith('#original'):
            continue
        if key.endswith('#global'):
            # interceptor: the global by its ADRP references, the bypass function by RTTI (slot of
            # the GAME_* class vtable; the shipped `mov w0,#0; ret` bodies are not unique)
            value = want[name]
            g = locate_entry(binary, entry)
            vt = binary.vtable(binary.type_key(value[1]), 0)
            o = binary.slot(vt, value[2]) if vt else None
            if g and o:
                fingerprints[name] = Anchor(name, (g[0], value[1], value[2], o), 'xref+rtti',
                                            f'global: {g[2]}; original: {value[1]} vtable slot {value[2]}')
            continue
        hit = locate_entry(binary, entry)
        if hit is not None:
            fingerprints[name] = Anchor(name, hit[0], hit[1], hit[2])
    app = fingerprints.get('vm.INTERCEPTORS.11GAME_PLAYER')
    if app is not None and 'vm.APP_BYPASS_ORIGINAL_RVA' not in out:
        fingerprints['vm.APP_GLOBAL_RVA'] = Anchor('vm.APP_GLOBAL_RVA', app.value[0], app.method, app.detail)
        fingerprints['vm.APP_BYPASS_ORIGINAL_RVA'] = Anchor('vm.APP_BYPASS_ORIGINAL_RVA', app.value[3], 'rtti',
                                                            'GAME_PLAYER vtable slot 7')
    # a live-typed anchor that the live scan found ambiguous: accept the fingerprint/xref
    # value when the live scan says that global holds an object of the expected type
    expected = {f'database.TABLES.{k}.root': n.decode() for k, (_r, _v, n) in _tables().items()}
    expected.update({'world.GAME_ROOT': 'N11game_plugin7GAME_UIE', 'world.SAVE_ROOT': '11SAVE_SYSTEM',
                     'ui_recipes_news.NEWS_MANAGER_RVA': '12NEWS_MANAGER',
                     'vm.VARIANT_REGISTRY_RVA': 'N6sicore20TYPED_TRAITS_MANAGERE'})
    for name, mangled in expected.items():
        hit = fingerprints.get(name)
        if typed is not None and hit is not None and typed.get(hit.value) == mangled:
            fingerprints[name] = Anchor(name, hit.value, hit.method + '+live', hit.detail + f'; holds a {mangled}')
    conflicts = {}
    for name, anchor in fingerprints.items():
        if name not in out or name == 'vm.RETURN_TRUE_RVA':
            out[name] = anchor          # the exact shipped helper when it is unchanged
        elif out[name].value != anchor.value:
            conflicts[name] = (out[name], anchor)
    for name in conflicts:
        out.pop(name, None)             # two methods disagree: the anchor is withheld
    out = {k: v for k, v in out.items() if k in want or k.startswith(('ui_vm.factory', 'vm.interceptor_global'))}
    resolve.conflicts = conflicts
    return out


def compare(found: dict, want: dict | None = None, *, same_build: bool = True) -> dict:
    """Per-anchor verdict against the pinned values: match | equivalent | mismatch | missing;
    for another build (`same_build=False`) only found | missing."""
    want = pinned() if want is None else want
    rows = {}
    for name, value in want.items():
        anchor = found.get(name)
        if anchor is None:
            rows[name] = ('missing', None, value)
        elif not same_build:
            rows[name] = ('found', anchor, value)
        elif anchor.value == value:
            rows[name] = ('match', anchor, value)
        elif name == 'vm.RETURN_TRUE_RVA':
            rows[name] = ('equivalent', anchor, value)      # any shipped `mov w0,#1; ret` serves
        else:
            rows[name] = ('mismatch', anchor, value)
    return rows


# --------------------------------------------------------------------------- repository census
def census_literals(root: Path, image_end: int) -> dict:
    """{integer literal: [(file, line)]} of every int constant in executable Python code under
    `root` (docstrings and comments excluded) whose value could be a plugin RVA."""
    import ast
    out = defaultdict(list)
    for path in sorted(Path(root).rglob('*.py')):
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and type(node.value) is int and 0x10000 <= node.value < image_end:
                out[node.value].append((str(path.relative_to(root)), node.lineno))
    return dict(out)


def classify(binary, rva) -> str:
    """vtable | typeinfo | function | code | data-referenced | data | not-an-address."""
    if binary.class_name(rva):
        return 'vtable'
    if binary.typeinfo_at(rva):
        return 'typeinfo'
    if binary.is_code(rva):
        if rva % 4:
            return 'not-an-address'
        bounds = binary.function_of(rva)
        return 'function' if bounds and bounds[0] == rva else 'code'
    seg = binary.image.segment_for(rva)
    if seg is None or seg.name in ('__TEXT', '__LINKEDIT') and not binary.refs.get(rva):
        return 'not-an-address'
    return 'data-referenced' if binary.refs.get(rva) else 'data'


# --------------------------------------------------------------------------- anchor files
ANCHOR_FORMAT = 'fmdb-anchors/1'


def anchor_document(binary, found: dict, *, live: bool, rows: dict | None = None) -> dict:
    return {
        'format': ANCHOR_FORMAT, 'plugin_sha256': binary.sha256, 'plugin_path': str(binary.path),
        'version': binary.version(), 'uuid': slice_uuid(binary).hex(), 'live_scan': live,
        'anchors': {name: _json_value(a) for name, a in sorted(found.items())},
        'compare': {name: verdict for name, (verdict, _a, _v) in sorted((rows or {}).items())},
    }


def _json_value(anchor: Anchor):
    v = anchor.value
    value = list(v) if isinstance(v, tuple) else v
    return {'value': value, 'method': anchor.method, 'detail': anchor.detail}


def anchor_dir() -> Path:
    from .engine import cache_root
    return cache_root() / 'anchors'


def load_anchor_file(sha256: str, directory: Path | None = None) -> dict | None:
    import json
    path = (directory or anchor_dir()) / f'{sha256}.json'
    if not path.exists():
        return None
    doc = json.loads(path.read_text())
    if doc.get('format') != ANCHOR_FORMAT or doc.get('plugin_sha256') != sha256:
        return None
    return doc


# --------------------------------------------------------------------------- GameAssembly
def registry_function(game_assembly):
    """The IL2CPP function that registers the UI property keys and labels (ui_registry.py;
    0xA296BC in 27.0.0.2493426): the largest function of GameAssembly.dylib, by a wide margin
    (FM27: 182,917 instructions, next 81,791; FM26: 165,625, next 93,409)."""
    ends = game_assembly.starts[1:] + [game_assembly.text_start + game_assembly.text_size]
    sizes = sorted(((e - s) // 4, s) for s, e in zip(game_assembly.starts, ends))
    (n1, s1), (n2, _s2) = sizes[-1], sizes[-2]
    if n1 < 1.5 * n2:
        return None
    return Anchor('ui_registry.REGISTRATION_FN', s1, 'pattern',
                  f'largest GameAssembly function ({n1} instructions; next {n2})')


def handler_classes(binary, registry: dict) -> tuple[int, int, int, int]:
    """(classes found, classes, slots equal, slots) of a ui_registry document on `binary`:
    every UI handler class by its demangled RTTI name (c++filt), slot functions compared."""
    import subprocess
    names = sorted(binary.vtables)
    demangled = subprocess.run(['c++filt', '-t'], input='\n'.join(names), capture_output=True,
                               text=True).stdout.splitlines()
    by_name = {}
    for mangled, plain in zip(names, demangled):
        by_name.setdefault(plain, mangled)
        by_name.setdefault(plain.split('::')[-1], mangled)
    found = equal = total = 0
    for cls, info in registry['classes'].items():
        mangled = by_name.get(cls) or by_name.get(cls.split('::')[-1])
        vt = binary.vtable(mangled, 0) if mangled else None
        total += len(info['slots'])
        if vt is None:
            continue
        found += 1
        equal += sum(1 for slot, s in info['slots'].items() if binary.slot(vt, int(slot)) == s['fn'])
    return found, len(registry['classes']), equal, total
