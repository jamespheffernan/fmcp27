"""Walker for the people-side native managers (lane mgr-people, docs/fmdb/MANAGERS_PEOPLE.md).

Each manager is a singleton the world constructor 0x250FE84 allocates (`operator new(size)` then the
constructor, or the vtable stores inline) and whose pointer it stores in a global of the plugin's
data segment. The object size is that allocation size: nothing past it belongs to the manager. The
first three words of every manager are its primary vtable, a second vtable (the base at +8) and a
32-bit manager id at +0x10.

Containers are declared per manager from the observed layout and the code that addresses them
(offsets in MANAGERS); each is checked live before use: a libc++ vector is (begin, end, capacity)
with begin <= end <= capacity and 8-aligned non-image pointers, a libc++ map/set is (begin node,
root, size) with the begin node pointing into the object when empty. Elements of pointer vectors
are classified by the vtable of the object they point at (Itanium RTTI name) or, for database
records, by the table whose pointer list holds them. Plain reads, no emulation.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import struct

from .. import address_book
from .sources import _common as C

IMAGE_SPAN = 0x6000000          # plugin image size bound for "points into the image"
MAX_VECTOR_BYTES = 64 << 20     # a declared vector larger than this is reported invalid
MAX_ELEMENTS = 200_000          # per pointer vector, elements classified


@dataclass(frozen=True)
class Manager:
    name: str
    root: int                   # data RVA of the global holding the object pointer
    vtable: int                 # primary vtable address point (RVA)
    size: int                   # allocation size (bytes) at `alloc_site`
    alloc_site: int             # the `mov w0, #size` before operator new (or the inline ctor)
    vectors: tuple = ()         # offsets of libc++ vectors
    maps: tuple = ()            # offsets of libc++ maps/sets
    pointers: tuple = ()        # offsets of single object pointers worth classifying
    holds: str = ''             # what the manager holds (established / inferred, see the doc)


INTERACTION_VECTORS = (0x18, 0x30, 0x48, 0x60, 0x78, 0x90, 0xA8, 0xC0, 0xD8, 0xF8, 0x110, 0x128, 0x140)
MANAGERS = (
    Manager('INTERACTION_MANAGER', 0x56A5688, 0x55F62F8, 0x160, 0x2510508, INTERACTION_VECTORS,
            holds='interaction items (+0xF8, refcounted, shared with per-person lists; read by the person '
                  'screen promise and happiness getters), eight lists of 0x90-byte records (+0x18..+0xC0), '
                  'the team-meeting comment rules (+0xD8), 0x78-byte records read by the transfer-confidence '
                  'and supporter-feedback getters (+0x110)'),
    Manager('MORALE_MANAGER', 0x56B5038, 0x55F6BD8, 0x30, 0x2510044,
            holds='five 32-bit values at +0x18..+0x28 (meaning not established); no containers'),
    Manager('DISPUTE_MANAGER', 0x56B7680, 0x55F5710, 0x30, 0x251020C,
            holds='three words at +0x18..+0x28 (zero on the reference save); no containers'),
    Manager('DYNAMICS_PIVOTAL_MOMENTS_MANAGER', 0x56A8438, 0x55F57D8, 0x50, 0x25106F0, maps=(0x18, 0x30),
            holds='two maps (+0x18, +0x30) and a packed date at +0x4C'),
    Manager('TEAM_TALK_MANAGER', 0x56B6770, 0x55F9328, 0x48, 0x2510394, maps=(0x18, 0x30),
            holds='two maps (+0x18, +0x30), built inline by the world constructor'),
    Manager('TEAM_BLEND_MANAGER', 0x5734810, 0x55F9260, 0x18, 0x25102F0,
            holds='no instance state (vtables and id only)'),
    Manager('AWOL_MANAGER', 0x56A82B0, 0x55F5260, 0x60, 0x2510124, vectors=(0x18, 0x30, 0x48),
            holds='three vectors (+0x18 24-byte-stride pointers, +0x48)'),
    Manager('PERSON_PROGRESSION_MANAGER', 0x56B7688, 0x55F73F0, 0x18, 0x2510450,
            holds='no instance state (vtables and id only): progression is computed, not stored here'),
    Manager('INJURY_MANAGER', 0x56A82A0, 0x55F61A0, 0x150, 0x25100A4,
            vectors=(0x70, 0x88, 0xA0, 0xB8, 0xD0, 0x100),
            holds='injury-risk records (+0xB8, read by the person screen InjuryRiskFactors getter) and five '
                  'other vectors; +0x31 is read by MatchLoadDescription'),
    Manager('REGENERATION_MANAGER', 0x56A8428, 0x55F7C28, 0x1B0, 0x2510064,
            vectors=(0x20, 0x38, 0x50, 0x68, 0x80, 0xA8, 0xC0), maps=(0x150,),
            holds='newgen templates: PLAYER_HEIGHTS_TEMPLATE lists (+0x20, +0x38), NON_PLAYER_TENDENCY_TEMPLATE '
                  'list (+0x68) and other generation tables'),
    Manager('RETIREMENT_MANAGER', 0x56A82A8, 0x55F7DA0, 0x118, 0x2510664,
            vectors=(0x18, 0x30, 0x48, 0x60, 0x78, 0x90, 0xA8, 0xC0, 0xD8, 0xF0), pointers=(0x108,),
            holds='retirement schedules (+0x18, +0x30: 24-byte entries with packed dates), sorted '
                  '(id, pointer) lookups (+0x78, +0x90, binary-searched by the person screen) and the '
                  'OBJECT_STORAGE<RETIRED_PERSON_DATA> (+0x108)'),
    Manager('AWARD_MANAGER', 0x56A6218, 0x55F5008, 0xD8, 0x25101AC, vectors=(0x18, 0x30, 0x48, 0x60, 0x78, 0x90),
            pointers=(0xA8,),
            holds='award schedule: one AWARD_DATA object per award period (+0x18: YEAR/MONTH/TEAM/GOAL/'
                  'CLUB_AWARD_DATA), the db::AWARD records it handles (+0x30) and four other vectors'),
    Manager('HALL_OF_FAME_MANAGER', 0x56A7F10, 0x55F5F30, 0x48, 0x251024C, vectors=(0x18, 0x30),
            holds='hall-of-fame entries (+0x18, 0x60 bytes each: person, nation, packed date) and the human '
                  'managers\' own entries (+0x30)'),
    Manager('ACHIEVEMENTS_MANAGER', 0x5734820, 0x55CC518, 0x20, 0x2510470,
            holds='no containers: +0x18 points into the image (static achievement table)'),
    Manager('OFFICIAL_STATS_MANAGER', 0x56B5560, 0x55DE580, 0x20, 0x1AC4358,
            holds='no containers (created by 0x1AC400C, not the world constructor)'),
    Manager('SIMULATED_STATS_MANAGER', 0x56B54E0, 0x55F8278, 0x78, 0x251022C, vectors=(0x18, 0x30, 0x48, 0x60),
            holds='two vectors of db::TEAM pointers (+0x48, +0x60) and two record vectors (+0x18, +0x30)'),
    Manager('STATS_OUTPUT_MANAGER', 0x56B76A8, 0x55F8340, 0x8, 0x251026C,
            holds='no instance state (vtable only)'),
)
BY_NAME = {m.name: m for m in MANAGERS}
DB_KINDS = ('people', 'clubs', 'teams', 'competitions', 'nations', 'awards', 'injuries', 'stadiums', 'cities',
            'player_types', 'regions', 'continents')


@dataclass
class Container:
    manager: str
    offset: int
    kind: str                   # 'vector' | 'map' | 'pointer'
    status: str                 # 'ok' | 'empty' | 'invalid: ...'
    begin: int = 0
    end: int = 0
    capacity: int = 0
    count: int | None = None    # elements (pointer vectors: pointers; maps: size; other vectors: None)
    byte_size: int | None = None
    element_kind: str | None = None   # 'pointer' | 'inline' | None
    classes: Counter = field(default_factory=Counter)   # element class -> count
    pointers: list = field(default_factory=list)        # element pointers (pointer vectors)
    element_class: list = field(default_factory=list)   # class per element (pointer vectors)


@dataclass
class Walk:
    objects: dict               # name -> object address (0 when the root is null)
    heads: dict                 # name -> object bytes
    containers: list            # [Container]
    problems: dict              # name -> reason


def _in_image(engine, v):
    return engine.base <= v < engine.base + IMAGE_SPAN


def record_index(engine) -> dict:
    """{record pointer: (table kind, idx)} over the database tables records commonly point at."""
    c = C.cache(engine)
    if 'mgr_people_records' not in c:
        out = {}
        for kind in DB_KINDS:
            try:
                for p, i in C.index_of(engine, kind).items():
                    out.setdefault(p, (kind, i))
            except Exception:  # noqa: BLE001 - a missing table only loses the labels
                continue
        c['mgr_people_records'] = out
    return c['mgr_people_records']


def rtti_name(engine, vtable: int) -> str:
    """Demangled-enough class name of a vtable (Itanium: vtable[-1] -> type_info, +8 -> name)."""
    names = C.cache(engine).setdefault('mgr_people_rtti', {})
    if vtable not in names:
        info = C.u64s(engine, [vtable - 8])[0]
        nm = C.u64s(engine, [info + 8])[0] if info else 0
        raw = C.blobs(engine, [(nm, 160)])[0] if nm else None
        text = raw.split(b'\0', 1)[0].decode('ascii', 'replace') if raw else ''
        import re
        # an Itanium type name: length-prefixed or nested (N...E); anything else is not RTTI
        ok = re.fullmatch(r'(?:\d+|N)[A-Za-z0-9_]+', text) is not None and len(text) > 3
        names[vtable] = _demangle_simple(text) if ok else ''
    return names[vtable]


def _demangle_simple(text: str) -> str:
    """'15YEAR_AWARD_DATA' -> YEAR_AWARD_DATA, 'N2db5AWARDE' -> db::AWARD; other forms kept as stored."""
    import re
    if not text:
        return ''
    m = re.fullmatch(r'(\d+)([A-Za-z_]\w*)', text)
    if m and int(m.group(1)) == len(m.group(2)):
        return m.group(2)
    m = re.fullmatch(r'N((?:\d+[A-Za-z_]\w*?)+)E', text)
    if m:
        parts, s = [], m.group(1)
        while s:
            n = re.match(r'\d+', s)
            if not n:
                return text
            k = int(n.group(0))
            parts.append(s[n.end():n.end() + k])
            s = s[n.end() + k:]
        return '::'.join(parts)
    return text


def classify(engine, pointers) -> list:
    """Class of each pointed object: 'table:<kind>' for database records, the RTTI name for objects
    with a vtable in the image, None otherwise."""
    recs = record_index(engine)
    out = [None] * len(pointers)
    todo = []
    for i, p in enumerate(pointers):
        if p in recs:
            out[i] = 'table:' + recs[p][0]
        elif p and 4096 <= p < 1 << 48 and not p & 7 and not _in_image(engine, p):
            todo.append(i)
    firsts = C.u64s(engine, [pointers[i] for i in todo])
    for i, vt in zip(todo, firsts):
        if _in_image(engine, vt):
            out[i] = rtti_name(engine, vt) or None    # an image word without RTTI is not a vtable claim
    return out


def walk(engine, only=None) -> Walk:
    """Every manager's object and declared containers, checked live (cached per engine build)."""
    key = ('mgr_people_walk', tuple(only) if only else None)
    c = C.cache(engine)
    if key in c:
        return c[key]
    base = engine.base
    mgrs = [m for m in MANAGERS if not only or m.name in only]
    objs = dict(zip((m.name for m in mgrs), C.u64s(engine, [base + m.root for m in mgrs])))
    heads, containers, problems = {}, [], {}
    for m in mgrs:
        disabled = address_book.disabled_manager(m.name)
        if disabled:
            problems[m.name] = disabled
            continue
        obj = objs[m.name]
        raw = C.blobs(engine, [(obj, m.size)])[0] if obj else None
        if not raw:
            problems[m.name] = 'root pointer null or object unreadable'
            continue
        vt = struct.unpack_from('<Q', raw, 0)[0]
        if vt != base + m.vtable:
            problems[m.name] = f'object vtable {vt - base:#x} is not {m.vtable:#x}'
            continue
        heads[m.name] = raw
        for off in m.vectors:
            containers.append(_vector(engine, m, obj, raw, off))
        for off in m.maps:
            containers.append(_map(m, obj, raw, off))
        for off in m.pointers:
            p = struct.unpack_from('<Q', raw, off)[0]
            cls = classify(engine, [p])[0] if p else None
            containers.append(Container(m.name, off, 'pointer', 'ok' if p else 'empty', begin=p,
                                        count=1 if p else 0, element_kind='pointer',
                                        classes=Counter({cls: 1}) if p else Counter(),
                                        pointers=[p] if p else [], element_class=[cls] if p else []))
    out = Walk(objs, heads, containers, problems)
    c[key] = out
    return out


def _vector(engine, m, obj, raw, off) -> Container:
    begin, end, cap = struct.unpack_from('<3Q', raw, off)
    c = Container(m.name, off, 'vector', 'ok', begin, end, cap)
    if begin == end == cap == 0:
        c.status, c.count, c.byte_size = 'empty', 0, 0
        return c
    if not (begin <= end <= cap) or begin % 8 or _in_image(engine, begin) or not 4096 <= begin < 1 << 48:
        c.status = 'invalid: not a (begin <= end <= capacity) heap vector'
        return c
    c.byte_size = end - begin
    if c.byte_size > MAX_VECTOR_BYTES or cap - begin > 2 * MAX_VECTOR_BYTES:
        c.status = f'invalid: {c.byte_size} bytes exceeds the bound'
        return c
    if c.byte_size == 0:
        c.status, c.count = 'empty', 0
        return c
    if c.byte_size % 8 == 0:
        n = c.byte_size // 8
        words = struct.unpack(f'<{min(n, MAX_ELEMENTS)}Q', engine.read(begin, min(n, MAX_ELEMENTS) * 8))
        heapish = [w for w in words if w]
        if heapish and all(4096 <= w < 1 << 48 and not w & 7 and not _in_image(engine, w) for w in heapish) \
                and len(heapish) >= len(words) * 0.9:
            c.element_kind, c.count, c.pointers = 'pointer', n, list(words)
            c.element_class = classify(engine, c.pointers)
            c.classes = Counter(c.element_class)
            return c
    c.element_kind = 'inline'
    return c


def _map(m, obj, raw, off) -> Container:
    begin, root, size = struct.unpack_from('<3Q', raw, off)
    c = Container(m.name, off, 'map', 'ok', begin, root, 0, count=size)
    if size == 0 and root == 0 and begin == obj + off + 8:
        c.status = 'empty'
    elif size and root and begin:
        c.status = 'ok'
    else:
        c.status = 'invalid: not a libc++ map header'
        c.count = None
    return c


def fingerprint_parts(engine, only=None) -> list:
    """Manager object bytes (vector bounds, map sizes, scalars): a cheap change detector."""
    base = engine.base
    mgrs = [m for m in MANAGERS if not only or m.name in only]
    objs = C.u64s(engine, [base + m.root for m in mgrs])
    return [*objs, *(b or b'' for b in C.blobs(engine, [(o, m.size) for o, m in zip(objs, mgrs)]))]
