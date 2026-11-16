"""Walk native manager singletons (plugin globals) and their containers, read-only.

Shared by `sources/managers_market.py`. A manager is reached through its global root (a pointer in the
plugin's __DATA): the object's first word must be the plugin base plus the manager's primary vtable, or the
walk refuses. Containers are libc++ `std::vector`s ({begin, end, capacity}); element layouts are declared by
the caller as (column, offset, kind, meaning) and decoded here with bounds and type checks:

    'ref:<table>'  8-byte pointer to a live database record of that snapshot table (person, club, team,
                   competition, nation, city, local_region, stadium, continent); NULL when 0, `bad` when the
                   pointer is not a record of that table
    'pidx'         u32 index into the live PERSON table (checked: the slot holds a record)
    'date'         u32 packed game date (year << 16 | flags << 9 | day of year); ISO text
    'u8' 'u16' 'u32' 'i32' 'u64' 'f32'  plain little-endian values
    'vcount'       element count of a std::vector<8-byte> whose header starts at the offset
    'class'        RTTI class of the object an 8-byte pointer points at (or of the word itself when it is a
                   vtable)

Nothing here writes to the game or runs game code.
"""
from __future__ import annotations

import bisect
import datetime as _dt
import struct

from .sources import _common as C

# snapshot table -> live DATABASE_TABLE kind
REF_KINDS = {'person': 'people', 'club': 'clubs', 'team': 'teams', 'competition': 'competitions',
             'nation': 'nations', 'city': 'cities', 'local_region': 'local_regions', 'stadium': 'stadiums',
             'continent': 'continents'}
MAX_ELEMENTS = 1 << 20


class WalkError(ValueError):
    pass


def u64(raw, off):
    return struct.unpack_from('<Q', raw, off)[0]


def packed_date(v: int) -> str | None:
    """ISO date of a packed game date; the 7 bits above the day (9..15) are not part of the day."""
    year, day = v >> 16, v & 511
    if not 1850 <= year <= 2200 or not 1 <= day <= 366:
        return None
    d = _dt.date(year, 1, 1) + _dt.timedelta(days=day - 1)
    return d.isoformat() if d.year == year else None


def root(engine, rva: int, vtable: int) -> int:
    """The manager object at global `rva`, checked by its primary vtable."""
    p = C.u64s(engine, [engine.base + rva])[0]
    if not p:
        raise WalkError(f'manager root {rva:#x} is null (no career loaded?)')
    head = C.u64s(engine, [p])[0]
    if head != engine.base + vtable:
        raise WalkError(f'manager root {rva:#x}: object vtable {head - engine.base:#x}, expected {vtable:#x}')
    return p


def vector(engine, address: int, stride: int = 8) -> tuple[int, int]:
    """(begin, count) of a std::vector header at `address`, checked."""
    raw = C.blobs(engine, [(address, 24)])[0]
    if raw is None:
        raise WalkError(f'vector header {address:#x} unreadable')
    b, e, c = struct.unpack('<QQQ', raw)
    if b == 0 and e == 0:
        return 0, 0
    if not (b <= e <= c) or (e - b) % stride or (e - b) // stride > MAX_ELEMENTS:
        raise WalkError(f'not a vector of {stride}-byte elements at {address:#x}: {b:#x} {e:#x} {c:#x}')
    return b, (e - b) // stride


def pointers(engine, address: int) -> list[int]:
    """Elements of a std::vector<T*> at `address`."""
    b, n = vector(engine, address)
    if not n:
        return []
    raw = C.blobs(engine, [(b, 8 * n)])[0]
    if raw is None:
        raise WalkError(f'vector body {b:#x} unreadable')
    return list(struct.unpack(f'<{n}Q', raw))


def inline(engine, address: int, stride: int) -> list[int]:
    """Element addresses of a std::vector<T> (sizeof T == stride) at `address`."""
    b, n = vector(engine, address, stride)
    return [b + stride * i for i in range(n)]


class Refs:
    """pointer -> idx per snapshot table, built on first use of each table."""

    def __init__(self, engine):
        self.engine = engine
        self._maps = {}

    def table(self, name):
        if name not in self._maps:
            self._maps[name] = C.index_of(self.engine, REF_KINDS[name])
        return self._maps[name]

    def any(self, pointer):
        for name in REF_KINDS:
            i = self.table(name).get(pointer)
            if i is not None:
                return name, i
        return None, None


class Classes:
    """vtable address -> class name (RTTI of the on-disk plugin, plus the database record classes)."""

    def __init__(self, engine):
        from . import ledger, tables
        self.base = engine.base
        rtti = ledger.rtti_inventory(engine.image)
        self.names = {info['vt']: name for name, info in rtti.items() if info.get('vt')}
        for vt, entry in tables.CLASSES.items():
            self.names.setdefault(vt, entry[0])
        self.keys = sorted(self.names)

    def of_vtable(self, absolute: int) -> str | None:
        rva = absolute - self.base
        if rva in self.names:
            return self.names[rva]
        k = bisect.bisect_right(self.keys, rva) - 1
        if k >= 0 and 0 < rva - self.keys[k] < 0x200:
            return f'{self.names[self.keys[k]]}+{rva - self.keys[k]:#x}'
        return None


def _classes(engine):
    c = C.cache(engine)
    if 'mgr_classes' not in c:
        c['mgr_classes'] = Classes(engine)
    return c['mgr_classes']


def _refs(engine):
    c = C.cache(engine)
    if 'mgr_refs' not in c:
        c['mgr_refs'] = Refs(engine)
    return c['mgr_refs']


SIZES = {'u8': (1, '<B'), 'u16': (2, '<H'), 'u32': (4, '<I'), 'i32': (4, '<i'), 'u64': (8, '<Q'),
         'f32': (4, '<f'), 'date': (4, '<I'), 'pidx': (4, '<I')}


def layout_span(fields) -> int:
    end = 0
    for _, off, kind, _ in fields:
        width = 8 if kind.startswith('ref:') or kind == 'class' else 24 if kind == 'vcount' else SIZES[kind][0]
        end = max(end, off + width)
    return end


def decode(engine, addresses, fields, *, size=None) -> list[list]:
    """One list of decoded values per element address (fields as in the module docstring)."""
    size = size or layout_span(fields)
    blobs = C.blobs(engine, [(a, size) for a in addresses])
    refs, classes = _refs(engine), None
    people = None
    out = []
    # pointer targets for 'class' fields and vector counts are read in one batch
    wanted, vecs = set(), set()
    for raw in blobs:
        if raw is None:
            continue
        for _, off, kind, _ in fields:
            if kind == 'class':
                wanted.add(u64(raw, off))
            elif kind == 'vcount':
                vecs.add(off)
    heads = {}
    if wanted:
        classes = _classes(engine)
        ws = sorted(w for w in wanted if C._valid(w))
        heads = dict(zip(ws, C.u64s(engine, ws)))
    for raw in blobs:
        if raw is None:
            out.append(None)
            continue
        row = []
        for _, off, kind, _ in fields:
            if kind.startswith('ref:'):
                p = u64(raw, off)
                if not p:
                    row.append(None)
                else:
                    i = refs.table(kind[4:]).get(p)
                    row.append(i if i is not None else -1)        # -1: not a record of that table
            elif kind == 'class':
                p = u64(raw, off)
                name = classes.of_vtable(p)
                if name is None and p in heads:
                    name = classes.of_vtable(heads[p])
                row.append(name)
            elif kind == 'vcount':
                b, e, c = struct.unpack_from('<QQQ', raw, off)
                row.append((e - b) // 8 if b <= e <= c and (e - b) % 8 == 0 else None)
            elif kind == 'date':
                row.append(packed_date(struct.unpack_from('<I', raw, off)[0]))
            elif kind == 'pidx':
                v = struct.unpack_from('<I', raw, off)[0]
                if people is None:
                    people = C.live(engine, 'people').pointers
                row.append(v if v < len(people) and people[v] else None)
            else:
                v = struct.unpack_from(SIZES[kind][1], raw, off)[0]
                row.append(round(v, 6) if kind == 'f32' else v)
        out.append(row)
    return out


def fingerprint_bytes(engine, headers, elements, size) -> list:
    """Parts for a content fingerprint: the vector headers and every element's first `size` bytes."""
    parts = C.blobs(engine, [(h, 24) for h in headers])
    parts += C.blobs(engine, [(a, size) for a in elements])
    return parts
