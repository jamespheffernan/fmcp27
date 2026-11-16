"""Fixtures, results, league tables and competition stages held in live memory.

Fixtures and results (`fm_live_mcp.fixtures`, docs/research.md): GAME_RULE_GROUP_MANAGER at
global 0x56D57D0, +0x158 the GAME_COMP_MANAGER store; the store's main calendar year plus its
linked years (+8) and archived years (+0x10) each hold 66 groups of 366 day buckets (group +
(day - 1) * 8 -> entry vector). A group whose +0xB70 bit 0 is clear is not materialised in
memory (the game keeps it compressed in the save); its fixtures are not here and
`fixture_coverage` says so. Records are `sicomps::FIXTURE` or `FIXTURE_RESULT` (vtable checked):
teams +0x8/+0x10, FIXTURE_NAME +0x20 (competition +0x18, three STAGE_NAME slots +0x20..+0x30,
secondary competition +0x40), stadium +0x28, season code u16 +0x30, stage index i8 +0x38, packed
date and kickoff code u32 +0x4C; results hold home/away score bytes at +0x64/+0x69 (normal time,
extra time, penalties, aggregate; 255 = none).

League tables (`fm_live_mcp.competition_stages`): every competition's runtime (+0xB0), its stage
vector (+0x1D8, group children +0xD0) and each league stage's table rows (+0xC0), read by the
hand-built decoder unchanged.
"""
from __future__ import annotations

from datetime import date, timedelta
import struct

from ... import competition_stages, competitions, fixtures
from . import Column, SourceTable
from . import _common as C

ROOT = 0x56D57D0
SCORE_NAMES = ('normal', 'extra_time', 'penalties', 'aggregate')


def _years(engine):
    """[(year, source, group addresses, flags)] through the hand-built catalog (type-checked)."""
    cat, bindings, _ = fixtures.catalog(engine.read, engine.base)
    return [(row['year'], row['source'], bindings[row['year']]['groups'], bindings[row['year']]['flags'])
            for row in cat['years']]


def _resident(engine, wanted_sources):
    """(located, coverage) for the materialised groups of the resident years whose source is in
    `wanted_sources` ('main', 'linked', 'archived')."""
    coverage, located = [], []          # located: (year, source, group, day, record pointer)
    for year, source, groups, flags in _years(engine):
        if source not in wanted_sources:
            continue
        loaded = [g for g in range(len(groups)) if flags[g] & 1]
        heads = C.blobs(engine, [(groups[g], 366 * 8) for g in loaded])
        cells = []
        for g, raw in zip(loaded, heads):
            if not raw:
                continue
            for day, header in enumerate(struct.unpack('<366Q', raw), 1):
                if header:
                    cells.append((g, day, header))
        vecs = C.blobs(engine, [(h, 24) for _, _, h in cells])
        reqs, owners = [], []
        for (g, day, _), raw in zip(cells, vecs):
            if not raw:
                continue
            start, end, cap = struct.unpack('<QQQ', raw)
            if start == end or start % 8 or not start <= end <= cap or end - start > 4000 * 8:
                continue
            reqs.append((start, end - start))
            owners.append((g, day))
        count = 0
        for (g, day), raw in zip(owners, C.blobs(engine, reqs)):
            if raw:
                for p in struct.unpack(f'<{len(raw) // 8}Q', raw):
                    if p:
                        located.append((year, source, g, day, p))
                        count += 1
        coverage.append((year, source, len(groups), len(loaded), count))
    return located, coverage


def fingerprint(engine):
    """Hash of the main/linked years' record pointers (a played match replaces its FIXTURE record
    by a FIXTURE_RESULT, a rescheduled one moves bucket) and of the resident archived groups.
    Reads the bucket vectors only, not the records."""
    from . import digest
    located, coverage = _resident(engine, ('main', 'linked'))
    return digest(repr(coverage), *(x[4] for x in located))


def _collect(engine):
    """The main and linked calendar years (current, previous and future seasons). Archived years
    move between memory and the archive file as the game pages them, so they are read together
    with the archive by `_archived` (fixture_history)."""
    c = C.cache(engine)
    if 'fixtures' in c:
        return c['fixtures']
    located, coverage = _resident(engine, ('main', 'linked'))
    _, archived_coverage = _resident(engine, ('archived',))
    raws = C.blobs(engine, [(x[4], 0x70) for x in located])
    rows, rejected = _decode(engine, located, raws)
    rows.sort(key=lambda r: (r[0], r[-1]))
    out = {'rows': rows, 'coverage': coverage + archived_coverage, 'rejected': rejected}
    c['fixtures'] = out
    return out


def _decode(engine, located, raws):
    """Rows for fixture/result records (`located`: (year, source, group, day, pointer); `raws`: 0x70
    bytes each). Record vtable and packed date (against its bucket) are checked."""
    base = engine.base
    vt = {base + fixtures.TYPES['fixture'][0]: 'fixture', base + fixtures.TYPES['result'][0]: 'result'}
    teams = C.index_of(engine, 'teams')
    comps = C.index_of(engine, 'competitions')
    stadiums = C.index_of(engine, 'stadiums')
    stage_names = C.index_of(engine, 'stage_names')
    fixture_names = C.index_of(engine, 'fixture_names')
    names = C.cache(engine).setdefault('fixture_name_links', {})
    new = sorted({struct.unpack_from('<Q', r, 0x20)[0] for r in raws if r} - {0} - set(names))
    for p, raw in zip(new, C.blobs(engine, [(p, 0x48) for p in new])):
        if raw:
            comp, s1, s2, s3 = struct.unpack_from('<4Q', raw, 0x18)
            sec = struct.unpack_from('<Q', raw, 0x40)[0]
            names[p] = (fixture_names.get(p), comps.get(comp), stage_names.get(s1), stage_names.get(s2),
                        stage_names.get(s3), comps.get(sec))
    rows, rejected = [], 0
    for (year, source, g, day, p), raw in zip(located, raws):
        kind = vt.get(struct.unpack_from('<Q', raw, 0)[0]) if raw else None
        if kind is None:
            rejected += 1
            continue
        packed = struct.unpack_from('<I', raw, 0x4C)[0]
        if packed >> 16 != year or packed & 511 != day:
            rejected += 1
            continue
        home, away, _, name, stadium, season = struct.unpack_from('<QQQQQH', raw, 8)
        stage_index = struct.unpack_from('<b', raw, 0x38)[0]
        kick = fixtures.kickoff_time(packed)
        scores = [None] * 8
        if kind == 'result':
            sc = raw[0x64:0x6E]
            scores = [None if sc[s + i] == 255 else sc[s + i] for i in range(4) for s in (0, 5)]
        nm = names.get(name, (None,) * 6)
        final_home = scores[2] if scores[2] is not None else scores[0]
        final_away = scores[3] if scores[3] is not None else scores[1]
        rows.append((
            (date(year, 1, 1) + timedelta(days=day - 1)).isoformat(), kick['time'], kick['state'], kind,
            teams.get(home), teams.get(away), nm[1], final_home, final_away, *scores,
            stadiums.get(stadium), season, stage_index, nm[0], nm[2], nm[3], nm[4], nm[5], year, source, g))
    return rows, rejected


# --------------------------------------------------------------------------- archived groups
ARCHIVE_OFFSET = 0xAD00          # GAME_COMP_MANAGER -> group archive (entries vector +0x30/+0x38)
LOAD_SLOT = 0x2C0                # GAME_COMP_MANAGER vtable slot: load one archived group (0x1ACD00C)
GROUP_BYTES = 0xC00              # 366 day vectors + the materialised flag at +0xB70


def _archive_keys(engine):
    """[(year, group)] the game's group archive holds, in native order (first key match wins)."""
    base = engine.base
    root = C.u64s(engine, [base + ROOT])[0]
    store = C.u64s(engine, [root + 0x158])[0]
    arch = C.u64s(engine, [store + ARCHIVE_OFFSET])[0]
    if not arch:
        return store, []
    start, end = C.u64s(engine, [arch + 0x30, arch + 0x38])
    if start % 8 or not start <= end or end - start > 4096 * 8:
        raise ValueError('invalid fixture group archive vector')
    entries = C.u64s(engine, [start + 8 * i for i in range((end - start) // 8)])
    keys, seen = [], set()
    for raw in C.blobs(engine, [(e, 0x18) for e in entries]):
        if raw:
            size = struct.unpack_from('<i', raw, 0xC)[0]
            g, y = struct.unpack_from('<IH', raw, 0x10)
            if (y, g) not in seen:
                seen.add((y, g))
                keys.append((y, g, size))
    return store, keys


EMPTY_GROUP_BYTES = 0x10        # archive entry size of a group with no fixtures


def _load_group(engine, vm, fn, store, key, blank, y, g):
    """([located], [raw records]) of one archived group loaded into the VM-private blank group, or
    the failure reason."""
    vm.uc.mem_write(key, struct.pack('<IHH', g, y, 0))
    vm.uc.mem_write(blank, b'\0' * GROUP_BYTES)
    try:
        vm.call(fn, (store, blank, key))
        located, raws = [], []
        for day, header in enumerate(struct.unpack('<366Q', vm.read(blank, 366 * 8)), 1):
            if not header:
                continue
            start, end, cap = struct.unpack('<QQQ', vm.read(header, 24))
            if start == end or start % 8 or not start <= end <= cap or end - start > 4000 * 8:
                continue
            for p in struct.unpack(f'<{(end - start) // 8}Q', vm.read(start, end - start)):
                if p:
                    located.append((y, 'archive_file', g, day, p))
                    raws.append(vm.read(p, 0x70))
        return located, raws
    except Exception as exc:  # noqa: BLE001 - one group never stops the table
        return f'{type(exc).__name__}: {exc}'


def _archived(engine, log=None, skip=frozenset()):
    """Rows of every archived fixture group not materialised in memory, loaded by emulating the
    game's own loader (GAME_COMP_MANAGER vt+0x2C0) into a VM-private group object. The loader reads
    `Temporary/fixture_group_archive.obs` through the game's FILE*, read-only."""
    c = C.cache(engine)
    if 'fixture_archive' in c and not skip:
        return c['fixture_archive']
    for attempt in range(2):
        state_before = _archive_state(engine)
        out = _archived_pass(engine, skip)
        moved = _archive_state(engine) != state_before
        if not moved:
            break
    out['moved'] = moved
    if not skip:
        c['fixture_archive'] = out
    return out


def _archive_state(engine):
    """(materialised archived groups, archive index keys): what the game holds where right now."""
    resident = frozenset((y, g) for y, source, groups, flags in _years(engine) if source == 'archived'
                         for g in range(len(groups)) if flags[g] & 1)
    return resident, frozenset((y, g) for y, g, _ in _archive_keys(engine)[1])


def _archived_pass(engine, skip=frozenset()):
    """`skip`: (calendar_year, group) pairs already stored (append refresh): not read again."""
    from ._archive_vm import archive_vm
    located_mem, _ = _resident(engine, ('archived',))
    located_mem = [x for x in located_mem if (x[0], x[2]) not in skip]
    resident = {(y, g) for y, _, g, _, _ in located_mem}
    resident |= {(y, g) for y, source, groups, flags in _years(engine) if source == 'archived'
                 for g in range(len(groups)) if flags[g] & 1}
    store, keys = _archive_keys(engine)
    todo = [(y, g, size) for y, g, size in keys if (y, g) not in resident and (y, g) not in skip]
    # the loader reads game memory that the game keeps changing: start from current pages (the
    # engine's page cache may be minutes old after other tables) and retry a failed group once
    memory = getattr(engine, 'memory', None)
    if memory is not None and hasattr(memory, 'invalidate'):
        memory.invalidate()
    vm = archive_vm(engine, budget=500_000_000, timeout_us=300_000_000)
    key = vm._static(b'\0' * 8)
    blank = vm._static(b'\0' * GROUP_BYTES)
    fn = C.u64s(engine, [C.u64s(engine, [store])[0] + LOAD_SLOT])[0]
    rows, rejected, failures, per_year = [], 0, [], {}
    loaded = {}
    def fresh_vm():
        if memory is not None and hasattr(memory, 'invalidate'):
            memory.invalidate()
        v = archive_vm(engine, budget=500_000_000, timeout_us=300_000_000)
        return v, v._static(b'\0' * 8), v._static(b'\0' * GROUP_BYTES)

    for y, g, size in todo:
        # The loader reads the archive through game state that changes while the game pages it
        # (11 Nov 2026: loads that had matched the resident groups byte for byte later failed or
        # came back short). A group is kept only when two loads in fresh VMs agree and every
        # record passes the vtable and bucket-date checks; otherwise it is retried next time.
        first = _load_group(engine, vm, fn, store, key, blank, y, g)
        if isinstance(first, str):
            failures.append((y, g, first))
            vm, key, blank = fresh_vm()
            continue
        vm, key, blank = fresh_vm()
        second = _load_group(engine, vm, fn, store, key, blank, y, g)
        if isinstance(second, str) or second[1] != first[1]:
            failures.append((y, g, second if isinstance(second, str) else 'two loads disagreed'))
            continue
        if size > EMPTY_GROUP_BYTES and not first[0]:
            failures.append((y, g, 'archive entry has data but the load gave no records'))
            continue
        loaded[(y, g)] = first
    mem_raws = C.blobs(engine, [(x[4], 0x70) for x in located_mem])
    got, bad = _decode(engine, located_mem, mem_raws)
    rows += got
    rejected += bad
    for y in {x[0] for x in located_mem}:
        n = per_year.setdefault(y, [0, 0, 0, 0])
        n[3] = sum(1 for r in got if r[-3] == y)
    for y, g in resident:
        per_year.setdefault(y, [0, 0, 0, 0])
    for (y, g), (located, raws) in loaded.items():
        got, bad = _decode(engine, located, raws)
        if bad:
            failures.append((y, g, f'{bad} records failed the vtable/date checks'))
            continue
        rows += got
        n = per_year.setdefault(y, [0, 0, 0, 0])
        n[0] += 1
        n[2] += len(got)
    for y, g, _ in failures:
        per_year.setdefault(y, [0, 0, 0, 0])[1] += 1
    resident_groups = {}
    for y, g in resident:
        resident_groups[y] = resident_groups.get(y, 0) + 1
    rows.sort(key=lambda r: (r[0], r[-1]))
    return {'rows': rows, 'rejected': rejected, 'failures': failures, 'groups': len(todo),
            'coverage': [(y, resident_groups.get(y, 0), n[3], n[0] + n[1], n[0], n[2])
                         for y, n in sorted(per_year.items())],
            'files': sorted(vm.files_read)}


def _standings(engine):
    """(stage rows, standing rows) for every competition with a runtime, by the hand-built decoder."""
    read, base = engine.read, engine.base
    comps = C.live(engine, 'competitions')
    index = C.index_of(engine, 'competitions')
    team_index = C.index_of(engine, 'teams')
    runtimes = C.u64s(engine, [p + 0xB0 if p else 0 for p in comps.pointers])
    stages, table_rows, failures = [], [], []
    seen_runtime = {}
    for idx, (p, runtime) in enumerate(zip(comps.pointers, runtimes)):
        if not p or not runtime:
            continue
        try:
            row = competitions.by_index(read, base, idx)
            saved = {'address': p, 'database_index': idx, 'native_id': row['native_id'],
                     'random_id': row.get('random_id')}
            context, results = competition_stages.catalog(read, base, saved)
        except Exception as exc:  # noqa: BLE001 - one competition never stops the table
            failures.append((idx, f'{type(exc).__name__}: {exc}'))
            continue
        owner = context.get('runtime_competition') or {}
        owner_idx = owner.get('database_index')
        shared = runtime in seen_runtime
        seen_runtime.setdefault(runtime, idx)
        for stage_row, binding in results:
            path = '.'.join(map(str, stage_row['path']))
            rules, count, view = {}, None, None
            if stage_row['kind'] == 'league' and binding is not None and not shared:
                try:
                    meta, entries = competition_stages.standings(read, base, binding)
                except Exception as exc:  # noqa: BLE001
                    failures.append((idx, f'stage {path}: {type(exc).__name__}: {exc}'))
                    meta, entries = None, []
                if meta:
                    rules, count, view = meta['point_rules'], meta['count'], meta['native_order_view_code']
                for e, tb in entries:
                    team = team_index.get(tb['address']) if tb else None
                    table_rows.append((idx, owner_idx, path, e['row_index'], e['position'], team,
                                       *(e[side][k] for side in ('overall', 'home', 'away')
                                         for k in ('played', 'wins', 'draws_or_penalty_wins', 'losses',
                                                   'penalty_losses', 'goals_for', 'goals_against',
                                                   'goal_difference', 'points'))))
            stages.append((idx, owner_idx, int(bool(context.get('shared_runtime'))),
                           context.get('native_season_code'), path, stage_row['kind'], stage_row['state'],
                           stage_row.get('child_slots'), count, view,
                           *(rules.get(k) for k in ('win', 'extra_time_win', 'penalty_win', 'draw', 'loss',
                                                    'penalty_loss')),
                           int(shared) if stage_row['kind'] == 'league' else None))
    return stages, table_rows, failures


def _stand_cache(engine):
    c = C.cache(engine)
    if 'standings' not in c:
        c['standings'] = _standings(engine)
    return c['standings']


SCORE_COLUMNS = []
for _name in SCORE_NAMES:
    for _side in ('home', 'away'):
        SCORE_COLUMNS.append(Column(f'{_side}_{_name}', 'INTEGER', f'{_side} side {_name.replace("_", " ")} score '
                                    f'byte (results only; NULL when the game stored none)'))

FIXTURE_COLUMNS = [
    Column('date', 'TEXT', 'match date (ISO; the calendar bucket and the packed date agree)'),
    Column('kickoff_time', 'TEXT', 'kickoff clock time HH:MM as stored (no verified timezone); NULL when unset'),
    Column('kickoff_state', 'TEXT', "'decoded', 'no_time_code', 'unset_date' or 'unmapped_time_code'"),
    Column('kind', 'TEXT', "'fixture' (FIXTURE record: not played yet) or 'result' (FIXTURE_RESULT: has scores; "
           "presence alone does not prove the match finished normally)"),
    Column('home_team_idx', 'INTEGER', 'first (home) side', references='team'),
    Column('away_team_idx', 'INTEGER', 'second (away) side', references='team'),
    Column('competition_idx', 'INTEGER', 'competition of the fixture name', references='competition'),
    Column('home_goals', 'INTEGER', 'home score after extra time when played, else normal time (excludes '
           'penalties); NULL for fixtures'),
    Column('away_goals', 'INTEGER', 'away score, same rule as home_goals'),
    *SCORE_COLUMNS,
    Column('stadium_idx', 'INTEGER', 'stored venue', references='stadium'),
    Column('season_code', 'INTEGER', 'native fixture season code (+0x30; a discriminator, not a decoded season)'),
    Column('stage_index', 'INTEGER', 'native stage slot (+0x38; -1 unassigned); competition_stage.path for top-level '
           'stages when season_code matches the competition runtime'),
    Column('fixture_name_index', 'INTEGER', 'FIXTURE_NAME database index (the name record the game formats the '
           'round from)'),
    Column('stage_name_idx', 'INTEGER', 'first stored stage-name component', references='stage_name'),
    Column('stage_name2_idx', 'INTEGER', 'second stored stage-name component', references='stage_name'),
    Column('stage_name3_idx', 'INTEGER', 'third stored stage-name component', references='stage_name'),
    Column('secondary_competition_idx', 'INTEGER', 'secondary competition of the fixture name',
           references='competition'),
    Column('calendar_year', 'INTEGER', 'resident calendar-year bucket that holds the record'),
    Column('year_source', 'TEXT', "'main' or 'linked' calendar year in GAME_COMP_MANAGER; in fixture_history "
           "'archived' (an archived year's group held in memory) or 'archive_file' (loaded from the game's archive)"),
    Column('group_index', 'INTEGER', 'native fixture group (0-65) within the year'),
]
COVERAGE_COLUMNS = [
    Column('calendar_year', 'INTEGER', 'calendar year held by GAME_COMP_MANAGER'),
    Column('year_source', 'TEXT', "'main', 'linked' or 'archived'"),
    Column('groups', 'INTEGER', 'fixture groups in the year'),
    Column('loaded_groups', 'INTEGER', 'groups materialised in memory (+0xB70 bit 0); the others are compressed in '
           'the save and their fixtures are not in the fixture table'),
    Column('records', 'INTEGER', 'fixture and result records read for the year'),
]
STAGE_COLUMNS = [
    Column('competition_idx', 'INTEGER', 'competition whose runtime holds the stage', references='competition'),
    Column('runtime_competition_idx', 'INTEGER', 'competition that owns the runtime (several competitions may share '
           'one)', references='competition'),
    Column('shared_runtime', 'INTEGER', '1 when the runtime belongs to another competition'),
    Column('season_code', 'INTEGER', 'runtime season code (+0x3B0); fixture.season_code matches it for this season'),
    Column('path', 'TEXT', "zero-based stage slot path: '2' top-level stage, '2.3' fourth league of group stage 2"),
    Column('kind', 'TEXT', "'league', 'group', 'cup', 'cup_group', 'empty' or NULL (null slot)"),
    Column('state', 'TEXT', "'decoded' or 'null_slot'"),
    Column('child_slots', 'INTEGER', 'group stages: number of child league slots'),
    Column('table_rows', 'INTEGER', 'league stages: rows in the stored table (standing rows)'),
    Column('order_view_code', 'INTEGER', 'league stages: native ordering view code (0 = stored overall order, '
           'positions given)'),
    *(Column(f'points_{k}', 'INTEGER', f'league points for a {k.replace("_", " ")}')
      for k in ('win', 'extra_time_win', 'penalty_win', 'draw', 'loss', 'penalty_loss')),
    Column('table_owned_elsewhere', 'INTEGER', 'league stages of a shared runtime: 1 when the table rows are '
           'listed under the runtime owner instead'),
]
STAT_NAMES = ('played', 'won', 'drawn', 'lost', 'penalty_lost', 'goals_for', 'goals_against', 'goal_difference',
              'points')
STANDING_COLUMNS = [
    Column('competition_idx', 'INTEGER', 'competition', references='competition'),
    Column('runtime_competition_idx', 'INTEGER', 'competition owning the runtime', references='competition'),
    Column('stage_path', 'TEXT', 'league stage path (competition_stage.path)'),
    Column('row_index', 'INTEGER', 'stored row order (0-based)'),
    Column('position', 'INTEGER', 'league position (row_index + 1 when the stored view is the overall order, '
           'else NULL)'),
    Column('team_idx', 'INTEGER', 'team in the row (NULL: unassigned slot)', references='team'),
    *(Column(f'{side}_{k}' if side != 'overall' else k, 'INTEGER',
             f'{side} {k.replace("_", " ")}' + (' (drawn includes penalty wins in the stored counter)'
                                                if k == 'drawn' else ''))
      for side in ('overall', 'home', 'away') for k in STAT_NAMES),
]


def _fixture_view(source):
    """The resolved fixture view over `source` (a table or view with the fixture columns and `held`)."""
    return (
        "SELECT f.held, f.idx, f.date, f.kickoff_time, f.kind, f.competition_idx, c.{competition.Cnam|Csna|dbnm} AS "
        "competition_name, f.home_team_idx, ht.{team.Tlna|Tsna|dbnm} AS home_team, f.away_team_idx, "
        "at.{team.Tlna|Tsna|dbnm} AS away_team, f.home_goals, f.away_goals, f.home_penalties, f.away_penalties, "
        "f.stadium_idx, s.{stadium.Snam|dbnm} AS stadium_name, sn.{stage_name.SNnm|dbnm} AS stage_name "
        f"FROM {source} f LEFT JOIN competition c ON c.idx = f.competition_idx "
        "LEFT JOIN team ht ON ht.idx = f.home_team_idx LEFT JOIN team at ON at.idx = f.away_team_idx "
        "LEFT JOIN stadium s ON s.idx = f.stadium_idx LEFT JOIN stage_name sn ON sn.idx = f.stage_name_idx")


def tables(engine):
    # fixture_view and fixture_result read the calendar years the game holds in memory (the
    # current, previous and next seasons): a reference costs a fingerprint check. The archived
    # years (fixture_history: the game's own group loader, minutes the first time) are read only
    # by a statement that names fixture_history, fixture_history_view or fixture_all.
    fixture_view = _fixture_view("(SELECT 'memory' AS held, * FROM fixture)")
    fixture_history_view = _fixture_view("(SELECT 'archive' AS held, * FROM fixture_history)")
    fixture_all = ("SELECT 'memory' AS held, f.* FROM fixture f UNION ALL "
                   "SELECT 'archive' AS held, h.* FROM fixture_history h")
    standing_view = (
        "SELECT st.competition_idx, c.{competition.Cnam|Csna|dbnm} AS competition_name, st.stage_path, st.position, "
        "st.team_idx, t.{team.Tlna|Tsna|dbnm} AS team_name, st.played, st.won, st.drawn, st.lost, st.goals_for, "
        "st.goals_against, st.goal_difference, st.points FROM standing st "
        "LEFT JOIN competition c ON c.idx = st.competition_idx LEFT JOIN team t ON t.idx = st.team_idx")
    def fixture_cov():
        d = _collect(engine)
        years = [f'{y} ({s}): {n} records' for y, s, g, lg, n in d['coverage'] if s != 'archived']
        return '; '.join(years + ([f'{d["rejected"]} records rejected (vtable or date check)'] if d['rejected'] else []))

    def history_cov():
        d = _archived(engine)
        parts = [f'{y}: {rg} groups in memory ({rn} records) + {lo} of {ag} archived groups loaded ({n} records)'
                 for y, rg, rn, ag, lo, n in d['coverage']]
        if d.get('moved'):
            parts.append('the game moved groups between memory and its archive during both reads: a group may be '
                         'missing or doubled')
        if d['failures']:
            parts.append(f'{len(d["failures"])} groups failed: ' + '; '.join(f'{y}/{g}: {r}' for y, g, r in
                                                                            d['failures'][:5]))
        if d['rejected']:
            parts.append(f'{d["rejected"]} records rejected (vtable or date check)')
        return '; '.join(parts)

    def stand_cov():
        fails = _stand_cache(engine)[2]
        return (f'{len(fails)} competitions or stages not read: ' + '; '.join(f'competition {i}: {r}' for i, r in fails[:8])
                ) if fails else ''

    public = {'scope': 'public', 'reason': 'fixtures, results and league tables are public in the game\'s UI'}
    return [
        SourceTable('fixture', 'every fixture and result of the main and linked calendar years (the current, '
                    'previous and future seasons), every competition: date, kickoff, teams, competition, venue, '
                    'scores (normal, extra time, penalties, aggregate). fixture_view (names joined) and '
                    'fixture_result read these years only, at the cost of a check. Older seasons are in '
                    'fixture_history / fixture_history_view; fixture_all covers both (the archived years take '
                    'minutes the first time)',
                    FIXTURE_COLUMNS, lambda: _collect(engine)['rows'],
                    mode='lazy', invalidation='content', fingerprint=lambda: fingerprint(engine),
                    cost_note='bulk reads; a few seconds',
                    source_note='GAME_COMP_MANAGER calendar buckets (fm_live_mcp.fixtures layout, record vtables '
                                'checked, packed date checked against its bucket)',
                    indexes=('date', 'competition_idx', 'home_team_idx', 'away_team_idx'), manager=public,
                    coverage=fixture_cov,
                    views={'fixture_all': fixture_all, 'fixture_view': fixture_view,
                           'fixture_result': "SELECT 'memory' AS held, * FROM fixture WHERE kind = 'result'"}),
        SourceTable('fixture_history', 'every fixture and result of the archived calendar years (from the start of '
                    'the save): the groups the game holds in memory (year_source archived) and every group it keeps '
                    'in its fixture group archive (year_source archive_file), read together; same columns as '
                    'fixture', FIXTURE_COLUMNS, lambda: _archived(engine)['rows'],
                    mode='lazy', invalidation='append', identity=('calendar_year', 'group_index'),
                    new_rows=lambda existing: _archived(engine, skip=frozenset(existing))['rows'],
                    cost_note='the game\'s own group loader emulated per archived group: minutes the first time, then only groups not stored yet',
                    source_note='archived groups in memory as fixture; the others through GAME_COMP_MANAGER vt+0x2C0 '
                                '(0x1ACD00C) emulated into a VM-private group; it reads '
                                'Temporary/fixture_group_archive.obs through the game\'s FILE*, read-only; record '
                                'layout as fixture. Loading a group that is also in memory reproduces it byte for byte',
                    indexes=('date', 'competition_idx', 'home_team_idx', 'away_team_idx'), manager=public,
                    coverage=history_cov,
                    views={'fixture_history_view': fixture_history_view}),
        SourceTable('fixture_coverage', 'which calendar years and fixture groups are in memory at build time (the '
                    'fixture table holds the main and linked years; fixture_history the archived years, see its '
                    '_source_tables note)',
                    COVERAGE_COLUMNS,
                    lambda: _collect(engine)['coverage'], source_note='GAME_COMP_MANAGER main/linked/archived years',
                    mode='lazy', invalidation='content', fingerprint=lambda: fingerprint(engine),
                    manager=public),
        SourceTable('competition_stage', 'every runtime stage of every competition with a live runtime: kind, '
                    'season code, league point rules', STAGE_COLUMNS, lambda: _stand_cache(engine)[0],
                    mode='lazy', invalidation='content', fingerprint=lambda: fingerprint(engine),
                    cost_note='hand-built decoder, one competition at a time',
                    source_note='competition +0xB0 runtime, stage vector +0x1D8 (fm_live_mcp.competition_stages)',
                    indexes=('competition_idx',), manager=public, coverage=stand_cov),
        SourceTable('standing', 'every stored league table row (league stages and group-stage leagues): played, '
                    'won, drawn, lost, goals, points overall/home/away', STANDING_COLUMNS,
                    lambda: _stand_cache(engine)[1],
                    mode='lazy', invalidation='content', fingerprint=lambda: fingerprint(engine),
                    cost_note='hand-built decoder, one league stage at a time',
                    source_note='league stage rows +0xC0 (fm_live_mcp.competition_stages.standings)',
                    indexes=('competition_idx', 'team_idx'), manager=public, coverage=stand_cov,
                    views={'standing_view': standing_view}),
    ]
