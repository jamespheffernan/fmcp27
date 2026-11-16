"""A synthetic game for the offline fmdb tests: a NATION table in a memory that tests can change.

`FakeMemory` is the game's memory with the page cache of `LiveMemory` in front of it: `load`
changes the game, readers keep the cached bytes until `invalidate` or `reread`. `FakeEngine`
gives what `snapshot.Build`, `ondemand.Session`, `freshness.refresh` and `audit.run` use of
`engine.Engine`. Its getter (`FakeEngine.getter`) answers every property from the record's
bytes, so a direct plan can be compared with it and a changed byte changes the answer.
`FakeTrackedVM` stands in for `fastvm.TrackingFastVM`: it keeps its own 4 KiB copies of the
pages it touched and reports the 8-byte words each getter call read, in the packed form
`FastVM.touch_end` documents.

Record layout (0x100 bytes, little-endian):

    0x00 u64 vtable          0x0C u32 unique id      0x10 u32 random id     0x18 i32 serial
    0x40 i32 code            direct  Ncod   (the getter adds the i32 at 0x44, zero at a build)
    0x48 u64 -> name         direct  Nnam, Ndup
    0x50 i32                 Nbad: the getter adds 1 when serial % 3 == 0 (the traced plan is wrong)
    0x58 u32 neighbour idx   direct  Nref
    0x5C u8  state           direct  Nsta
    0x60 i32 points          on demand  Nscr = points * 2 + 1
    0x70 u64 -> side object  on demand  Nfar = i32 at the side object + 7
    0xC0                     read by nothing
    Nemu = serial squared, Nslo = -serial (a slow call), Nnhd is not handled by the getter.
"""
from __future__ import annotations

import struct
import threading
from types import SimpleNamespace

from fm_live_mcp.fmdb import bulkplans, fastvm, ondemand, query, snapshot
from fm_live_mcp.fmdb.bulkplans import Observation
from fm_live_mcp.fmdb.engine import SaveInfo
from fm_live_mcp.fmdb.memory import ST_READ_FAILED, MemoryBase, MemoryReadError
from fm_live_mcp.fmdb.vm import CallStats, PropertyResult

BASE = 0x1_0000_0000
NATION_VTABLE = BASE + 0x55B5C40
HEAP = 0x2_0000_0000
STRINGS = 0x2_1000_0000
SIDE = 0x2_2000_0000
RECORD = 0x100
COUNT = 300
VM_PAGE = 4096

CODE, BONUS, NAME, BAD, NEIGHBOUR, STATE, POINTS, FAR, SPARE = 0x40, 0x44, 0x48, 0x50, 0x58, 0x5C, 0x60, 0x70, 0xC0


def field(code, name, type_, references=None, enum=None):
    return SimpleNamespace(code=code, name=name, type=type_, references=references, enum=enum, enum_ref=None,
                           comment=None)


FIELDS = [
    field('Ncod', 'Code', 'integer'),
    field('Nnam', 'Name', 'string'),
    field('Nbad', 'Badly Planned', 'integer'),
    field('Nemu', 'Computed', 'integer'),
    field('Nslo', 'Slow', 'integer'),
    field('Nnhd', 'Not Handled', 'integer'),
    field('Nref', 'Neighbour', 'database_record_unique_id', references='nation'),
    field('Nsta', 'State', 'enum', enum={0: 'poor', 1: 'rich'}),
    field('Ndup', 'Name', 'string'),      # duplicate name -> name_Ndup
    field('Nbtn', 'Press', 'button'),     # UI only -> skipped
    field('Nscr', 'Score', 'integer'),
    field('Nfar', 'Far', 'integer'),
]
# column name -> code of the on-demand columns the tests ask for
ON_DEMAND = {'score': 'Nscr', 'far': 'Nfar', 'computed': 'Nemu', 'slow': 'Nslo', 'badly_planned': 'Nbad'}


class FakeMemory(MemoryBase):
    """The game's memory (`process`, changed with `load`) behind a page cache (`_cache`)."""

    def __init__(self):
        self.process = {}               # page base -> bytearray
        self._cache = {}                # page base -> bytes, as LiveMemory keeps them
        self.faults = 0
        self.before_reread = None       # called with the bases before pages are read again

    # ---- the game
    def load(self, address, data):
        """Place `data` at `address` in the game (the page cache is not touched)."""
        end = address + len(data)
        for base in range(self.page_base(address), end, self.page_size):
            page = self.process.setdefault(base, bytearray(self.page_size))
            lo, hi = max(address, base), min(end, base + self.page_size)
            page[lo - base:hi - base] = data[lo - address:hi - address]

    def _bases(self, address, length):
        if length < 1 or address < 1:
            raise MemoryReadError(f'invalid read of {length!r} bytes at {address!r}')
        return range(self.page_base(address), address + length, self.page_size)

    def read(self, address, length):
        """Uncached: the game's bytes now."""
        bases = self._bases(address, length)
        for base in bases:
            if base not in self.process:
                raise MemoryReadError(f'cannot read {length} bytes at {address:#x}', ST_READ_FAILED)
        data = b''.join(bytes(self.process[base]) for base in bases)
        offset = address - bases[0]
        return data[offset:offset + length]

    def read_many(self, requests):
        out = []
        for address, length in requests:
            try:
                out.append(self.read(address, length))
            except MemoryReadError:
                out.append(None)
        return out

    # ---- the page cache
    def page(self, address):
        base = self.page_base(address)
        cached = self._cache.get(base)
        if cached is None:
            if base not in self.process:
                raise MemoryReadError(f'page {base:#x} is unreadable', ST_READ_FAILED)
            cached = self._cache[base] = bytes(self.process[base])
            self.faults += 1
        return cached

    def prefetch(self, ranges):
        fetched = 0
        for address, length in ranges:
            for base in range(self.page_base(address), address + length, self.page_size):
                if base not in self._cache and base in self.process:
                    self.page(base)
                    fetched += 1
        return fetched

    def cached_read(self, address, length):
        bases = self._bases(address, length)
        data = self.page(bases[0]) if len(bases) == 1 else b''.join(self.page(base) for base in bases)
        offset = address - bases[0]
        return data[offset:offset + length]

    def windows(self, addresses, length):
        """Fixed-stride windows sliced from the page cache (as LiveMemory.windows after a prefetch)."""
        parts, bad = [], []
        for k, address in enumerate(addresses):
            try:
                parts.append(self.cached_read(address, length))
            except MemoryReadError:
                parts.append(bytes(length))
                bad.append(k)
        return b''.join(parts), bad

    def invalidate(self):
        self._cache.clear()

    def reread(self, bases):
        """As LiveMemory.reread: read cached pages again, replace them, return those that changed."""
        if self.before_reread is not None:
            self.before_reread(sorted(set(bases)))
        changed = set()
        for base in sorted(b for b in set(bases) if b in self._cache):
            now = self.process.get(base)
            if now is None:
                del self._cache[base]
                changed.add(base)
            elif bytes(now) != self._cache[base]:
                self._cache[base] = bytes(now)
                changed.add(base)
        return changed

    def regions(self):
        return []


class FakeVM:
    """The main VM: getter calls on the cached bytes (no copies of its own)."""

    def __init__(self, engine):
        self.engine = engine
        self.calls = []                 # (record, code)
        self.live_pages = {}

    def get_property(self, record, code):
        self.calls.append((record, code))
        return self.engine.getter(self.engine.memory.cached_read, record, code)

    def drop_live_pages(self):
        pass

    invalidate = drop_live_pages

    def count(self, code=None):
        return len(self.calls) if code is None else sum(1 for _, c in self.calls if c == code)


class FakeTrackedVM(FakeVM):
    """What `ondemand.Session` uses of `fastvm.TrackingFastVM`.

    A page is copied (4 KiB) from the engine's page cache when it is first touched and kept
    until `drop_live_pages` / `invalidate`. Between `touch_begin` and `touch_end` every read
    marks the 8-byte words it covers; `touch_end` returns 9 little-endian u64 per page: the
    page address, then 8 masks (bit k of mask m: the word at offset (64 m + k) * 8 was read)."""

    def __init__(self, engine):
        super().__init__(engine)
        self._touched = None
        self.drops = 0

    def read(self, address, length):
        parts, at, end = [], address, address + length
        while at < end:
            page = at & ~(VM_PAGE - 1)
            data = self.live_pages.get(page)
            if data is None:
                data = self.live_pages[page] = self.engine.memory.cached_read(page, VM_PAGE)
            stop = min(end, page + VM_PAGE)
            parts.append(data[at - page:stop - page])
            if self._touched is not None:
                lo, hi = (at - page) >> 3, (stop - 1 - page) >> 3
                self._touched[page] = self._touched.get(page, 0) | (((1 << (hi - lo + 1)) - 1) << lo)
            at = stop
        return b''.join(parts)

    def get_property(self, record, code):
        self.calls.append((record, code))
        return self.engine.getter(self.read, record, code)

    def touch_begin(self):
        self._touched = {}

    def touch_end(self):
        touched, self._touched = self._touched or {}, None
        return b''.join(struct.pack('<Q', page) + mask.to_bytes(64, 'little') for page, mask in sorted(touched.items()))

    def settle(self):
        pass

    def drop_live_pages(self):
        self.live_pages.clear()
        self.drops += 1

    invalidate = drop_live_pages


class FakeTracer:
    """Claims the stored location for direct fields; the Nbad claim is wrong for 1 in 3 records."""
    LOCATIONS = {'Ncod': ((CODE,), 4, True, 'int', 'identity'), 'Nnam': ((NAME,), 8, False, 'string', 'identity'),
                 'Ndup': ((NAME,), 8, False, 'string', 'identity'), 'Nbad': ((BAD,), 4, True, 'int', 'identity'),
                 'Nref': ((NEIGHBOUR,), 4, False, 'int', 'identity'), 'Nsta': ((STATE,), 1, False, 'int', 'identity')}

    def __init__(self, engine):
        self.engine = engine

    def observe(self, record, code):
        result = self.engine.get_property(record, code)
        value = bulkplans.canonical(result)
        ms = result.stats.seconds * 1000
        if result.kind == 'null':
            return result, Observation(record, 'null', None, None, 'not handled', False, ms)
        loc = self.LOCATIONS.get(code)
        if loc is None:
            return result, Observation(record, result.kind, value, None, 'value not explained by a traced load',
                                       True, ms)
        return result, Observation(record, result.kind, value, frozenset({loc}), None, True, ms)

    def close(self):
        pass


class FakeEngine:
    """`count` NATION records; `tracking=False` gives an engine without the read-tracking VM
    (the default follows `fastvm.tracks_reads()`, because the read-set hashes come from the
    real accelerator library)."""

    def __init__(self, tmp_path=None, *, count=COUNT, tracking=None):
        self.base = BASE
        self.plugin_sha256 = 'f' * 64
        self.build = 'test'
        self.process_key = (1, 'fake', 'now')
        self.lock = threading.RLock()
        self.catalog = SimpleNamespace(record_types={'nati': SimpleNamespace(field_list=FIELDS)}, enums={})
        self.memory = FakeMemory()
        self.date = '2030-12-10'
        self.pointers = []
        self.generation = 0             # of the table vector: part of its identity
        self.allocated = 0
        for i in range(count):
            self.pointers.append(self.new_record(i, neighbour=(i + 1) % count))
        self.vm = FakeVM(self)
        tracking = fastvm.tracks_reads() if tracking is None else tracking
        self.tracked_vm = FakeTrackedVM(self) if tracking else None

    # ---- the game
    def new_record(self, serial, *, neighbour=0, uid=None):
        """Allocate one record (with its name and side object) and return its address."""
        n = self.allocated
        self.allocated += 1
        record, text, side = HEAP + n * RECORD, STRINGS + n * 0x40, SIDE + n * 0x20
        name = f'Nation {serial}'.encode()
        self.memory.load(text, struct.pack('<I', len(name)) + name)
        self.memory.load(side, struct.pack('<i', 5000 + serial) + bytes(0x1C))
        data = bytearray(RECORD)
        uid = 1000 + serial if uid is None else uid
        struct.pack_into('<Q', data, 0, NATION_VTABLE)
        struct.pack_into('<II', data, 0xC, uid, uid)
        struct.pack_into('<i', data, 0x18, serial)
        struct.pack_into('<i', data, CODE, serial * 3)
        struct.pack_into('<Q', data, NAME, text)
        struct.pack_into('<i', data, BAD, serial)
        struct.pack_into('<I', data, NEIGHBOUR, neighbour)
        data[STATE] = serial % 2
        struct.pack_into('<i', data, POINTS, 100 + serial)
        struct.pack_into('<Q', data, FAR, side)
        self.memory.load(record, bytes(data))
        return record

    def poke(self, idx, offset, fmt, value):
        """Change one field of the record at table index `idx` in the game."""
        self.memory.load(self.pointers[idx] + offset, struct.pack(fmt, value))

    def poke_side(self, idx, value):
        """Change the side object the record at `idx` points to (what Nfar reads through the pointer)."""
        pointer = struct.unpack('<Q', self.memory.read(self.pointers[idx] + FAR, 8))[0]
        self.memory.load(pointer, struct.pack('<i', value))

    def set_pointers(self, pointers):
        """A new table vector (a reallocation: new list, new identity)."""
        self.pointers = list(pointers)
        self.generation += 1

    @staticmethod
    def getter(load, record, code):
        """The game's property getter over `load(address, length)`."""
        stats = CallStats(seconds=0.00001)

        def i32(address):
            return struct.unpack('<i', load(address, 4))[0]

        if code == 'Ncod':
            return PropertyResult(code, i32(record + CODE) + i32(record + BONUS), 'int', True, stats)
        if code in ('Nnam', 'Ndup'):
            pointer = struct.unpack('<Q', load(record + NAME, 8))[0]
            n = struct.unpack('<I', load(pointer, 4))[0]
            return PropertyResult(code, load(pointer + 4, n).decode(), 'string', True, stats)
        if code == 'Nbad':
            return PropertyResult(code, i32(record + BAD) + (1 if i32(record + 0x18) % 3 == 0 else 0), 'int', True,
                                  stats)
        if code == 'Nemu':
            return PropertyResult(code, i32(record + 0x18) ** 2, 'int', True, stats)
        if code == 'Nslo':
            return PropertyResult(code, -i32(record + 0x18), 'int', True, CallStats(seconds=1.0))
        if code == 'Nref':
            return PropertyResult(code, struct.unpack('<I', load(record + NEIGHBOUR, 4))[0], 'int', True, stats)
        if code == 'Nsta':
            return PropertyResult(code, load(record + STATE, 1)[0], 'int', True, stats)
        if code == 'Nscr':
            return PropertyResult(code, i32(record + POINTS) * 2 + 1, 'int', True, stats)
        if code == 'Nfar':
            pointer = struct.unpack('<Q', load(record + FAR, 8))[0]
            return PropertyResult(code, i32(pointer) + 7, 'int', True, stats)
        return PropertyResult(code, None, 'null', False, stats)

    def expected(self, idx, code):
        """The getter's value for the record at `idx`, from the game's bytes now."""
        return bulkplans.canonical(self.getter(self.memory.read, self.pointers[idx], code))

    # ---- engine interface (engine.Engine)
    def fresh(self):
        self.refresh_memory()

    def refresh_memory(self):
        self.memory.invalidate()
        for vm in (self.vm, self.tracked_vm):
            if vm is not None:
                vm.invalidate()

    def save_info(self):
        return SaveInfo('Test Career', 'test-career', 1, '2025-01-01', self.date, (), ())

    def game_date(self):
        return self.date

    def table_entries(self, kind):
        if kind == 'nations':
            return list(self.pointers), ('nations', len(self.pointers), self.generation)
        return [], (kind, 0)

    def table_info(self, kind):
        return {'identity': self.table_entries(kind)[1]}

    def read(self, address, length):
        return self.memory.read(address, length)

    def read_many(self, requests):
        return self.memory.read_many(requests)

    def cached_read(self, address, length):
        return self.memory.cached_read(address, length)

    def windows(self, addresses, length):
        return self.memory.windows(addresses, length)

    def prefetch(self, records, before=0x400, after=0x800):
        self.memory.prefetch([(r - before, before + after) for r in records if r])

    def plan_tracer(self):
        return FakeTracer(self)

    def get_property(self, record, code):
        return self.vm.get_property(record, code)

    @property
    def calls(self):
        return len(self.vm.calls)


def use_cache(monkeypatch, tmp_path):
    """Make `tmp_path` the fmdb cache root (plan cache and snapshots) for one test."""
    from fm_live_mcp.fmdb import engine as engine_module, tools
    monkeypatch.setattr(engine_module, 'cache_root', lambda: tmp_path)
    monkeypatch.setattr(tools, 'cache_root', lambda: tmp_path)


def build(engine, tmp_path, **kwargs):
    """Build the nation snapshot under `tmp_path`; returns (path, builder)."""
    builder = snapshot.Build(engine, root=tmp_path, tables_wanted=['nation'], column_budget=20, **kwargs)
    return builder.run(), builder


def statement(engine, path, sql, params=None, **session_args):
    """One statement as `tools.db_query` runs it; returns (result, what `finish` reported)."""
    reads = query.referenced_columns(path, sql, params)
    with engine.lock:
        session = ondemand.Session(engine, path, **session_args)
        try:
            session.plan(reads, sql)
            result = query.run_session(path, sql, params, session=session, max_rows=5000)
        finally:
            computed = session.finish()
    return result, computed
