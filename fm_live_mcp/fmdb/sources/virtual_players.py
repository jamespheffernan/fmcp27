"""Virtual players: every stored and every deterministic player field for the 12,739 VIRTUAL_PLAYER
records (youth and filler squad members the game materialises on demand).

How the game makes a virtual player stable (docs/fmdb/REFUSALS.md, "Virtual players")
--------------------------------------------------------------------------------------
A VIRTUAL_PLAYER is a 0x40-byte compact record (people-table entry = compact + 0x20). Its
property getter (0x18A7778, via thunk 0x18A83C8) asks VIRTUAL_MANAGER (global 0x56A68A8) for the
player's profile: 0x18A0ED0(manager, compact, create). The manager keeps a ring of 520 generated
ACTUAL_PLAYER profiles (vector at manager+8, next slot manager+0x20, capacity manager+0x28). The
profile is reused when compact+0x14 indexes a slot whose profile carries the player's id
(profile[virtual base]+0xC == compact+0x2C, the check at 0x18A0F24); otherwise the next ring
slot is overwritten with a newly generated profile and compact+0x14 is pointed at it.

Generation is a deterministic function of the player's stored data except for one draw site:
0x154B5F0 (inlined pcg32 on the thread-local generator 0x56C44F8) jitters the height. Evidence
on the reference save (Newcastle, 10 Dec 2030): regenerating three materialised players in the
VM (cache index forced to -1) reproduced 2,010 of 2,013 getter cells; the 3 that differed were
height (`Phei`), and the generator's only RNG accesses come from 0x18A384C -> 0x154B5F0.

So per record:
* `cached` (materialised, 408 at the time of writing): the getter reads the stored profile; no
  draws; every value is what the game shows.
* `generated` (cache index negative, 9,118, or the ring slot now holds another player, 3,213):
  the profile is generated in the VM exactly as the game will generate it, twice, with two
  different private generator seeds. A field is kept when its getter read no byte that differs
  between the two profiles, or when it gives the same value from both; otherwise it is
  unavailable ('value depends on random draws': the game will draw it when it first shows the
  player, and draws again after the profile is evicted from the ring).

Rows carry the player table's getter columns (same names and value conversion as `player`), plus
`profile_state`, `draw_dependent` (JSON list of codes) and `unavailable` (JSON {code: reason}).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import json
import struct
import time
from typing import Callable, Iterable

try:                                    # collections lane: fm_live_mcp/fmdb/sources/__init__.py
    from . import Column, SourceTable   # type: ignore[attr-defined]
except ImportError:                     # standalone (same dataclasses as COMMON.md)
    @dataclass
    class Column:
        name: str
        sql_type: str
        meaning: str
        enum: dict | None = None
        references: str | None = None

    @dataclass
    class SourceTable:
        name: str
        description: str
        columns: list
        rows: Callable[[], Iterable[tuple]]
        key: str = 'idx'
        cost_note: str = ''
        slow: bool = False
        source_note: str = ''
        indexes: tuple = ()
        manager: dict = field(default_factory=lambda: {'scope': 'never'})

from .. import bulkplans, snapshot
from ..vm import HEAP, PAGE, RNG_DEPENDS, RNG_SEEDS, Unavailable, _Stop

MANAGER_RVA = 0x56A68A8          # VIRTUAL_MANAGER pointer (virtual.py MANAGER_ROOT)
PROFILE_RVA = 0x18A0ED0          # VIRTUAL_MANAGER::profile(manager, compact, create)
COMPACT_OFFSET = 0x20            # people-table entry - compact record
CACHE_INDEX, IDENTITY = 0x14, 0x2C
PROFILE_ID = 0xC                 # profile (virtual base) + 0xC: the virtual player's id
GENERATE_BUDGET = 50_000_000
READ_BUDGET = 2_000_000
STATES = {0: 'cached', 1: 'generated', 2: 'unavailable'}


def compact_of(record: int) -> int:
    return record - COMPACT_OFFSET


def profile_state(read, base, record) -> tuple[str, int | None]:
    """('cached', profile) when the ring slot the record indexes holds its own profile (the
    generator's reuse test at 0x18A0F24), else ('generated', None)."""
    compact = compact_of(record)
    raw = read(compact, 0x40)
    index = struct.unpack_from('<h', raw, CACHE_INDEX)[0]
    if index < 0:
        return 'generated', None
    manager = struct.unpack('<Q', read(base + MANAGER_RVA, 8))[0]
    start, end = struct.unpack('<QQ', read(manager + 8, 16))
    if index >= (end - start) // 8:
        return 'generated', None
    profile = struct.unpack('<Q', read(start + index * 8, 8))[0]
    if not profile:
        return 'generated', None
    vbase = struct.unpack('<q', read(struct.unpack('<Q', read(profile, 8))[0] - 0x18, 8))[0]
    owner = struct.unpack('<I', read(profile + vbase + PROFILE_ID, 4))[0]
    return ('cached', profile) if owner == struct.unpack_from('<I', raw, IDENTITY)[0] else ('generated', None)


def _tracking_vm_class():
    from ..ui_vm import UiHandlerVM
    from unicorn import UC_HOOK_MEM_READ

    class TrackingVM(UiHandlerVM):
        """UiHandlerVM that notes whether emulated code or a model read any byte in `watch`."""

        def __init__(self, *args, **kwargs):
            self.watch, self.touched, self._watch_hooks = frozenset(), False, []
            super().__init__(*args, **kwargs)

        def set_watch(self, addresses):
            for handle in self._watch_hooks:
                self.uc.hook_del(handle)
            self._watch_hooks = []
            self.watch = frozenset(addresses)
            for page in sorted({a & ~(PAGE - 1) for a in self.watch}):
                self._watch_hooks.append(self.uc.hook_add(UC_HOOK_MEM_READ, self._on_watched_read,
                                                          begin=page, end=page + PAGE - 1))

        def _on_watched_read(self, uc, access, address, size, value, user):
            if not self.touched and any(a in self.watch for a in range(address, address + size)):
                self.touched = True

        def read(self, address, length):
            if self.watch and not self.touched and any(a in self.watch for a in range(address, address + length)):
                self.touched = True
            return super().read(address, length)

    return TrackingVM


def _difference(a, b) -> set[int]:
    """Addresses whose byte differs between two committed VM states (pages and heap)."""
    out = set()
    for page in set(a.pages) | set(b.pages):
        x = a.pages.get(page) or a.origin.get(page) or b.origin.get(page)
        y = b.pages.get(page) or b.origin.get(page) or a.origin.get(page)
        if x != y:
            out.update(page + i for i in range(PAGE) if x[i] != y[i])
    ha, hb = a.heap, b.heap
    n = max(len(ha), len(hb))
    ha, hb = ha.ljust(n, b'\0'), hb.ljust(n, b'\0')
    if ha != hb:
        out.update(HEAP + i for i in range(n) if ha[i] != hb[i])
    return out


@dataclass
class VirtualRow:
    idx: int
    uid: int | None
    state: str
    values: dict                      # code -> canonical value (or bulkplans.Missing)
    draw_dependent: list
    marks: list
    seconds: float
    cpu_seconds: float = 0.0
    generate_cpu_seconds: float = 0.0     # the two profile generations (generated rows)


class VirtualReader:
    """Reads virtual players through their own getter (see the module docstring)."""

    def __init__(self, engine, codes, *, vm=None):
        from ..engine import _VMReader
        self.engine, self.base, self.codes = engine, engine.base, list(codes)
        cls = _tracking_vm_class()
        self.vm = vm or cls(_VMReader(engine.memory), engine.base, engine.image, view='database',
                            thread='reader', budget=READ_BUDGET, timeout_us=60_000_000,
                            file_resolver=engine.file_resolver(), rng='isolate')
        self.manager = struct.unpack('<Q', engine.read(engine.base + MANAGER_RVA, 8))[0]
        self.stats = Counter()

    def _read_all(self, record, codes):
        vm = self.vm
        out, touched, marks = {}, set(), set()
        for code in codes:
            vm.touched = False
            result = vm.get_property(record, code)
            out[code] = bulkplans.canonical(result)
            marks.update(result.stats.marked)
            if vm.touched:
                touched.add(code)
        return out, touched, marks

    def _generate(self, record, seed):
        vm = self.vm
        vm.reset()
        vm.set_watch(())
        vm.rng_seed = seed
        rng, vm.rng = vm.rng, 'private'
        budget, vm.budget = vm.budget, GENERATE_BUDGET
        try:
            profile, _ = vm.call(self.base + PROFILE_RVA, (self.manager, compact_of(record), 1))
        finally:
            vm.rng, vm.budget = rng, budget
        if not profile:
            raise _Stop('VIRTUAL_MANAGER returned no profile')
        vm.commit()
        return vm._baseline

    def read(self, idx, record, uid=None, codes=None) -> VirtualRow:
        started, cpu = time.perf_counter(), time.process_time()
        codes = self.codes if codes is None else list(codes)
        state, _ = profile_state(self.engine.read, self.base, record)
        vm = self.vm
        if state == 'cached':
            vm.reset()
            vm.set_watch(())
            values, _, marks = self._read_all(record, codes)
            self.stats['cached'] += 1
            return VirtualRow(idx, uid, state, values, [], sorted(marks), time.perf_counter() - started,
                              time.process_time() - cpu)
        try:
            second = self._generate(record, RNG_SEEDS[1])
            first = self._generate(record, RNG_SEEDS[0])
        except _Stop as stop:
            self.stats['generation refused: ' + stop.reason] += 1
            missing = bulkplans.Missing(f'profile generation stopped: {stop.reason}')
            return VirtualRow(idx, uid, 'unavailable', {c: missing for c in codes}, [], [],
                              time.perf_counter() - started, time.process_time() - cpu)
        generated = time.process_time() - cpu
        vm.set_watch(_difference(first, second))
        values, touched, marks = self._read_all(record, codes)
        dependent = []
        if touched:
            vm._baseline = second
            vm.set_watch(())
            again, _, _ = self._read_all(record, sorted(touched))
            vm._baseline = first
            for code in sorted(touched):
                if not bulkplans.same(values[code], again[code]) and values[code] != again[code]:
                    values[code] = bulkplans.Missing(RNG_DEPENDS)
                    dependent.append(code)
        for code in NAME_CODES & set(values):
            if not isinstance(values[code], bulkplans.Missing):
                values[code] = bulkplans.Missing(NAME_REASON)
        vm.set_watch(())
        vm.reset()
        self.stats['generated'] += 1
        return VirtualRow(idx, uid, state, values, dependent, sorted(marks), time.perf_counter() - started,
                          time.process_time() - cpu, generated)


# Names are not part of profile generation: of the 408 materialised profiles on the reference save
# 30 carry a name, and regenerating those 30 in the VM reproduced 28,650 of 28,980 cells (1,099
# person and player codes each); the 330 that differed were these name codes (empty after
# generation) and the height (Phei, Phes, found per row by the two-seed test).
NAME_CODES = frozenset({'Pfna', 'Psna', 'Pcna', 'Pnna', 'PAfn', 'PAna', 'PnRV', 'Pfln', 'dbnm', 'dbnD', 'Pnam'})
NAME_REASON = ('virtual player name: names are attached to a materialised profile outside profile generation '
               '(0x18A0ED0); a generated profile has none')


def player_columns(engine):
    """The getter columns of the snapshot `player` table, then the `person` columns the player
    table does not have (names, birth date, nationality ...); derived `x:` columns excluded."""
    out = [c for c in snapshot.columns_for(engine.catalog, 'player') if not c.code.startswith('x:')]
    codes, names = {c.code for c in out}, {c.name for c in out}
    for c in snapshot.columns_for(engine.catalog, 'person'):
        if c.code.startswith('x:') or c.code in codes:
            continue
        if c.name in names:
            continue
        out.append(c)
        names.add(c.name)
    return out


def virtual_records(engine):
    """[(people idx, record pointer, uid)] for every VIRTUAL_PLAYER."""
    live = snapshot.enumerate_table(engine, 'people')
    return live, [(i, live.pointers[i], live.uids[i]) for i in range(len(live.pointers))
                  if live.pointers[i] and live.classes[i] == 'VIRTUAL_PLAYER']


FIXED = (Column('idx', 'INTEGER', 'people table index (= player.idx / person.idx)', references='person'),
         Column('uid', 'INTEGER', 'unique id'),
         Column('profile_state', 'TEXT', "'cached': the game's materialised profile was read; 'generated': the "
                'profile was generated in the VM the way the game generates it; '
                "'unavailable': generation stopped (see `unavailable`)"),
         Column('draw_dependent', 'TEXT', 'JSON list of getter codes whose value depends on random draws at '
                'generation (NULL in their columns)'),
         Column('unavailable', 'TEXT', 'JSON {code: reason} for columns left NULL for a reason other than unset'),
         Column('marks', 'TEXT', 'JSON list of modelled stand-ins that reached the reads (vm.mark)'))


INVALIDATION = ('per record: the 64 compact bytes, the ring slot it indexes and that slot\'s profile id '
                '(`row_key`); a generated row also depends on the template data the generator reads, so it is '
                'dropped when the game date changes')


def _source_table(**kwargs):
    """SourceTable with the keys this checkout's contract knows (mode / invalidation are added by the
    collections lane; older contracts ignore them)."""
    import dataclasses
    known = {f.name for f in dataclasses.fields(SourceTable)}
    return SourceTable(**{k: v for k, v in kwargs.items() if k in known})


def tables(engine) -> list[SourceTable]:
    """The `virtual_player` table, lazy: nothing is read until a query asks for rows (all rows are
    read only when the table is scanned whole; prefer `read_virtual` / `team_virtual`)."""
    columns = player_columns(engine)

    def rows():
        live, records = virtual_records(engine)
        yield from rows_for(engine, records, columns, live=live)

    meaning = {c.name: (c.field.comment if hasattr(c.field, 'comment') else '') for c in columns}
    sql_columns = list(FIXED) + [Column(c.name, c.sql_type, f'{c.code}: {meaning.get(c.name) or c.name}',
                                        enum=c.labels, references=c.references) for c in columns]
    return [_source_table(
        name='virtual_player',
        description='VIRTUAL_PLAYER records (youth and filler squad members) with the player getter columns: '
                    "the game's materialised profile where it has one, else the profile generated in the VM "
                    'exactly as the game generates it (values generated at read, i.e. that change with the '
                    'random draws, are NULL).',
        columns=sql_columns,
        rows=rows,
        cost_note=COST_NOTE,
        mode='lazy',
        invalidation=INVALIDATION,
        slow=True,
        source_note='getter emulation (0x18A7778) on the cached profile, or on a profile generated by '
                    '0x18A0ED0 in the VM; two-seed rule per column',
        indexes=('profile_state',),
        manager={'scope': 'never'},
    )]


COST_NOTE = ('on demand only. CPU per player at load average 250-300: see docs/fmdb/REFUSALS.md '
             '"Virtual players" (generation of two profiles plus one getter call per requested column)')

_ROW_CACHE: dict = {}          # row_key -> VirtualRow (all columns), bounded
_ROW_CACHE_MAX = 2048


def row_key(engine, record):
    """Invalidation key of one virtual row (INVALIDATION)."""
    read, base = engine.read, engine.base
    raw = read(compact_of(record), 0x40)
    state, profile = profile_state(read, base, record)
    date = engine.game_date() if state != 'cached' else None
    return (engine.pid, record, raw, state, profile, date)


def read_virtual(engine, records, codes=None, *, reader=None):
    """On demand: VirtualRow for each (idx, record, uid), reading only `codes` (default: every
    player column). Rows are cached under `row_key`."""
    if codes is None:
        codes = list(dict.fromkeys(c.code for c in player_columns(engine)))
    reader = reader or VirtualReader(engine, codes)
    out = []
    for idx, record, uid in records:
        key = (row_key(engine, record), tuple(codes))
        row = _ROW_CACHE.get(key)
        if row is None:
            row = reader.read(idx, record, uid, codes=codes)
            if len(_ROW_CACHE) >= _ROW_CACHE_MAX:
                _ROW_CACHE.pop(next(iter(_ROW_CACHE)))
            _ROW_CACHE[key] = row
        out.append(row)
    return out


def rows_for(engine, records, columns=None, *, live=None):
    """SQL row tuples (FIXED + columns) for the given virtual records, on demand."""
    columns = columns or player_columns(engine)
    if live is None:
        live, _ = virtual_records(engine)
    resolver = snapshot.Resolver(_live_tables(engine, columns, live))
    codes = list(dict.fromkeys(c.code for c in columns))
    for row in read_virtual(engine, records, codes):
        yield row_tuple(row, columns, resolver)


def team_virtual(engine, team_index, live=None):
    """[(idx, record, uid)] of the VIRTUAL_PLAYERs whose compact record names `team_index` (teams
    table index, compact+8): a squad's virtual members, for an on-demand read."""
    if live is None:
        live, _ = virtual_records(engine)
    out = []
    for i, (p, cls) in enumerate(zip(live.pointers, live.classes)):
        if p and cls == 'VIRTUAL_PLAYER' and struct.unpack('<i', engine.read(compact_of(p) + 8, 4))[0] == team_index:
            out.append((i, p, live.uids[i]))
    return out


def _live_tables(engine, columns, people):
    out = {'person': people, 'player': people}
    for c in columns:
        target = c.references
        if target and target not in out and target in snapshot.TABLES:
            kind = __import__('fm_live_mcp.fmdb.tables', fromlist=['RECORD_TYPES']).RECORD_TYPES[
                snapshot.TABLES[target]].table
            out[target] = snapshot.enumerate_table(engine, kind)
    return out


def row_tuple(row: VirtualRow, columns, resolver) -> tuple:
    unavailable = {c: v.reason for c, v in row.values.items()
                   if isinstance(v, bulkplans.Missing) and c not in row.draw_dependent}
    head = (row.idx, row.uid, row.state, json.dumps(row.draw_dependent) if row.draw_dependent else None,
            json.dumps(unavailable, sort_keys=True) if unavailable else None,
            json.dumps(row.marks) if row.marks else None)
    return head + tuple(snapshot.to_sql(c, row.idx, row.values.get(c.code), resolver) for c in columns)


# --------------------------------------------------------------------------- validation
def _main(argv=None):
    """Validation run: python -m fm_live_mcp.fmdb.sources.virtual_players [--managed] [--sample N]"""
    import argparse
    import random
    from .. import tables as T
    from ..engine import Engine
    ap = argparse.ArgumentParser()
    ap.add_argument('--sample', type=int, default=0)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--managed', action='store_true', help='every virtual player of the managed club teams')
    ap.add_argument('--codes', help='comma-separated getter codes (default: every player column)')
    ap.add_argument('--out', help='write JSON lines here')
    args = ap.parse_args(argv)
    engine = Engine.open()
    columns = player_columns(engine)
    codes = args.codes.split(',') if args.codes else list(dict.fromkeys(c.code for c in columns))
    live, records = virtual_records(engine)
    chosen = []
    if args.managed:
        chosen += managed_virtual(engine, live)
    if args.sample:
        rnd = random.Random(args.seed)
        chosen += rnd.sample(records, min(args.sample, len(records)))
    reader = VirtualReader(engine, codes)
    out = open(args.out, 'w') if args.out else None
    for idx, record, uid in chosen:
        row = reader.read(idx, record, uid)
        missing = Counter(v.reason for v in row.values.values() if isinstance(v, bulkplans.Missing))
        print(json.dumps({'idx': idx, 'state': row.state, 'seconds': round(row.seconds, 2),
                          'draw_dependent': row.draw_dependent, 'missing': dict(missing),
                          'name': [row.values.get(c) for c in ('Pfna', 'Psna', 'Pcna') if c in row.values]},
                         default=str), flush=True)
        if out:
            out.write(json.dumps({'idx': idx, 'uid': uid, 'state': row.state, 'draw_dependent': row.draw_dependent,
                                  'values': {c: (None if v is None else str(v) if isinstance(v, bulkplans.Missing)
                                                 else v) for c, v in row.values.items()}},
                                 default=lambda v: v.__dict__ if hasattr(v, '__dict__') else str(v)) + '\n')
    print(json.dumps(dict(reader.stats)))


def managed_virtual(engine, live=None):
    """[(idx, record, uid)] of every VIRTUAL_PLAYER in the managed clubs' team rosters (U18, U21 ...)."""
    from ... import world
    from ..tables import u64
    read, base = engine.read, engine.base
    if live is None:
        live, _ = virtual_records(engine)
    index = {p: i for i, p in enumerate(live.pointers) if p}
    record, _ = world.loaded(world.ReadSet(read), base)
    out, seen = [], set()
    for coach in record['coaches']:
        club = u64(read, coach['team_address'] + 0x30)
        begin, end = struct.unpack('<QQ', read(club + 0x18, 16))
        for slot in range(begin, min(end, begin + 8 * 64), 8):
            team = u64(read, slot)
            if not team:
                continue
            first, last = struct.unpack('<QQ', read(team + 0x38, 16))
            for p in range(first, min(last, first + 8 * 200), 8):
                primary = u64(read, p)
                if not primary or u64(read, primary) - base != world.TYPES['virtual_player'][0]:
                    continue
                person = primary + COMPACT_OFFSET
                i = index.get(person)
                if i is not None and i not in seen:
                    seen.add(i)
                    out.append((i, person, live.uids[i]))
    return out


if __name__ == '__main__':
    _main()
