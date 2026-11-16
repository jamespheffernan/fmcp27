"""Discover HUMAN-retained match data before selected-fixture projection."""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import struct

from . import fixtures, players, prepared_tactics_source
from . import live_retained_shots as shots
from .match_data_query import capture_epoch, capture_live
from .next_match_squad import select_fixture

SCOPES = ('managed', 'next_opponent', 'managed_and_next_opponent', 'team')
MAX_QUERY_PAGES = 16


def _inventory(bridge, session_id, coach_index):
    with bridge.lock, bridge._read_scope(session_id):
        process = bridge._current(session_id)
        tables = bridge._player_layout(process)
        read, save, _ = bridge._world_state(process, tables)
        base = tables[0] - players.RVA[0]
        shots._verify_native(read, base)
        _, years, catalog_identity = fixtures.catalog(read, base)
        coaches = save['coaches']
        if coach_index is not None and not 0 <= coach_index < len(coaches):
            raise ValueError('Coach index is outside the current active coach roster')
        entries, owners, material = [], [], []
        for ci, coach in enumerate(coaches):
            if coach_index is not None and ci != coach_index:
                continue
            team, human = prepared_tactics_source._team_and_human(read, base, coach)
            owners.append({'coach_index': ci, 'coach_name': coach['name'], 'team': team})
            for offset in (0x188, 0x1a0, 0x170, 0x1b8):
                pointers = shots._records(read, human + offset, 8, shots.MAX_ENTRIES)
                material.append((ci, offset, pointers.hex()))
                for ordinal, (ptr,) in enumerate(struct.iter_unpack('<Q', pointers)):
                    if ptr < 4096 or ptr % 8:
                        raise ValueError('Invalid retained owner entry')
                    raw = read(ptr, 24)
                    material.append((ci, offset, ordinal, raw.hex()))
                    packed = struct.unpack_from('<I', raw, 4)[0]
                    year, day = packed >> 16, packed & 511
                    when = None
                    if 1 <= year <= 9999 and day:
                        candidate = date(year, 1, 1) + timedelta(days=day - 1)
                        if candidate.year == year:
                            when = candidate.isoformat()
                    entries.append({'coach_index': ci, 'coach_name': coach['name'],
                                    'native_collection': hex(offset), 'entry_index': ordinal,
                                    'date': when, 'packed_date_raw': packed,
                                    'owner_team_native_id': struct.unpack_from('<i', raw, 16)[0],
                                    'nonnull_source': bool(players.u64(raw, 8))})
        read.verify()
        bridge._current(session_id)
        digest = hashlib.sha256(json.dumps([save, catalog_identity, material], sort_keys=True, default=str).encode()).hexdigest()
        return {'save': bridge._public_save(save), 'owners': owners, 'entries': entries,
                'source_inventory_id': digest, 'resident_fixture_years': sorted(years)}


def _fixture_query(bridge, session_id, team_id, start, end, kind):
    rows, queries, cursor = [], [], None
    for _ in range(MAX_QUERY_PAGES):
        result = bridge.find_fixtures(session_id, year=date.fromisoformat(start).year,
                                     team_native_id=team_id, date_from=start, date_to=end,
                                     record_kind=kind, max_matches=100, record_budget=1000,
                                     bucket_budget=4096, selector_prefilter=True, cursor=cursor)
        for row in result['fixtures']:
            binding = bridge.fixture_refs.get(row['fixture_ref'])
            if binding is None:
                raise ValueError('Discovered canonical fixture reference expired')
            key = (binding['address'], binding['identity'])
            rows.append(dict(row, _discovery_binding=repr(key)))
        queries.append({key: result.get(key) for key in
                        ('year', 'criteria', 'coverage', 'stop_reason', 'reached_resident_range_end')})
        cursor = result['next_cursor']
        if cursor is None:
            break
    return rows, {'queries': queries, 'complete': cursor is None,
                  'continuation_required': cursor is not None}


def _targets(bridge, session_id, inventory, scope, team_native_id):
    if scope == 'team':
        return [{'native_id': team_native_id, 'selection': 'explicit_team'}], None
    if len(inventory['owners']) != 1:
        raise ValueError('Select one active coach_index for managed or next-opponent discovery')
    managed = inventory['owners'][0]['team']
    targets = []
    if scope in ('managed', 'managed_and_next_opponent'):
        targets.append({'native_id': managed['native_id'], 'database_index': managed['database_index'],
                        'selection': 'managed_team', 'club': managed.get('owner')})
    opponent = None
    if scope in ('next_opponent', 'managed_and_next_opponent'):
        today = date.fromisoformat(inventory['save']['current_date'])
        end = today + timedelta(days=60)
        found, searches, complete = [], [], True
        for year in range(today.year, end.year + 1):
            start = max(today, date(year, 1, 1)); stop = min(end, date(year, 12, 31))
            if year not in inventory.get('resident_fixture_years', [year]):
                searches.append({'year': year, 'complete': False,
                                 'state': 'resident_fixture_year_unavailable'})
                complete = False
                continue
            rows, coverage = _fixture_query(bridge, session_id, managed['native_id'],
                                             start.isoformat(), stop.isoformat(), None)
            found.extend(row for row in rows if any(
                row.get(side) and row[side].get('database_index') == managed['database_index']
                for side in ('home_team', 'away_team')))
            searches.append(coverage); complete = complete and coverage['complete']
            if found and coverage['complete']:
                break
        opponent = select_fixture(found, today.isoformat(), complete)
        opponent['search'] = searches
        same_day = opponent['same_day_candidates']
        ids = set()
        for row in same_day:
            for side in ('home_team', 'away_team'):
                team = row.get(side)
                if team and team.get('database_index') != managed['database_index']:
                    ids.add(team['native_id'])
        if len(ids) == 1:
            targets.append({'native_id': ids.pop(), 'selection': 'earliest_observed_opponent_candidate',
                            'selection_state': opponent['state']})
        elif same_day:
            opponent['opponent_state'] = 'ambiguous_earliest_day_opponents'
    return targets, opponent


def bind_candidates(entries, fixture_rows, complete=True):
    """Resolve date/team entries without selecting one of several same-day matches."""
    groups = defaultdict(list)
    for row in entries:
        groups[(row['date'], row['owner_team_native_id'])].append(row)
    output = []
    for (when, owner), sources in groups.items():
        matches = {row.get('_discovery_binding', row['fixture_ref']): row for row in fixture_rows
                   if when is not None and row.get('date') == when and any(
                       (row.get(side) or {}).get('native_id') == owner
                       for side in ('home_team', 'away_team'))}
        if len(matches) == 1 and complete:
            fixture = next(iter(matches.values()))
            output.append({'state': 'resolved_candidate', 'fixture_ref': fixture['fixture_ref'],
                           'fixture': fixture, 'source_candidates': sources})
        else:
            output.append({'state': 'incomplete_fixture_search' if not complete else
                           'ambiguous_fixture_binding' if matches else 'unavailable_fixture_binding',
                           'date': when, 'owner_team_native_id': owner,
                           'candidate_fixtures': list(matches.values()), 'source_candidates': sources})
    # A fixture may be retained under both participating teams; query it once.
    unique, unresolved = {}, []
    for row in output:
        if 'fixture_ref' not in row:
            unresolved.append(row); continue
        ref = row['fixture_ref']
        if ref in unique:
            unique[ref]['source_candidates'].extend(row['source_candidates'])
        else:
            unique[ref] = row
    return list(unique.values()) + unresolved


def _summary(fixture):
    def team(side):
        value = fixture.get(side) or {}
        owner = value.get('owner') or {}
        return {'name': value.get('name') or owner.get('name'),
                'native_id': value.get('native_id'),
                'native_type_code': value.get('native_type_code')}
    return {'date': fixture.get('date'), 'competition': fixture.get('competition'),
            'home_team': team('home_team'), 'away_team': team('away_team')}


def _status(record, field):
    if record is None:
        return {'state': 'not_checked'}
    sides = record.get('side_coverage', []) if field == 'shots' else record.get('sides', [])
    projected = []
    for row in sides:
        projected.append({key: row[key] for key in
                          ('side_index', 'state', 'shot_count', 'statistical_shot_count',
                           'counter_reconciled_completed_passes', 'official_map_record_count') if key in row})
    return {'state': record['state'], 'source_id': record.get('source_id'), 'sides': projected}


def list_retained_match_data(bridge, session_id, scope='managed_and_next_opponent',
                             team_native_id=None, coach_index=None, offset=0, limit=16,
                             expected_source_inventory_id=None):
    if scope not in SCOPES:
        raise ValueError('Unsupported retained-match discovery scope')
    if scope == 'team':
        if type(team_native_id) is not int or not 1 <= team_native_id <= 0xffffffff:
            raise ValueError('Explicit team scope requires a positive team_native_id')
    elif team_native_id is not None:
        raise ValueError('team_native_id requires scope=team')
    if coach_index is not None and (type(coach_index) is not int or not 0 <= coach_index < 64):
        raise ValueError('Invalid active coach_index')
    if type(offset) is not int or not 0 <= offset <= 16384 or type(limit) is not int or not 1 <= limit <= 16:
        raise ValueError('Discovery page requires offset0..16384 and limit1..16')
    if offset and expected_source_inventory_id is None:
        raise ValueError('Discovery continuation requires expected_source_inventory_id')
    epoch = capture_epoch(bridge, session_id)
    inventory = _inventory(bridge, session_id, coach_index)
    page_source_id = hashlib.sha256(json.dumps([inventory['source_inventory_id'], scope, team_native_id, coach_index]).encode()).hexdigest()
    if expected_source_inventory_id is not None and expected_source_inventory_id != page_source_id:
        raise ValueError('Retained source inventory changed; restart discovery')
    targets, opponent = _targets(bridge, session_id, inventory, scope, team_native_id)
    selected = {t['native_id'] for t in targets}
    entries = [row for row in inventory['entries'] if row['owner_team_native_id'] in selected]
    windows = defaultdict(list)
    for row in entries:
        if row['date'] is not None:
            windows[(row['owner_team_native_id'], date.fromisoformat(row['date']).year)].append(row['date'])
    fixture_rows, searches, complete = [], [], True
    for (team_id, year), dates in sorted(windows.items()):
        if year not in inventory['resident_fixture_years']:
            searches.append({'team_native_id': team_id, 'year': year, 'complete': False,
                             'state': 'resident_fixture_year_unavailable'})
            complete = False
            continue
        rows, coverage = _fixture_query(bridge, session_id, team_id, min(dates), max(dates), 'result')
        fixture_rows.extend(rows); searches.append(coverage); complete = complete and coverage['complete']
    candidates = bind_candidates(entries, fixture_rows, complete)
    def order(row):
        fixture = row.get('fixture', {})
        return (fixture.get('date') or row.get('date') or '',
                (fixture.get('competition') or {}).get('native_id', -1),
                (fixture.get('home_team') or {}).get('native_id', -1),
                (fixture.get('away_team') or {}).get('native_id', -1),
                row.get('owner_team_native_id', -1))
    candidates.sort(key=order, reverse=True)
    page = candidates[offset:offset+limit]
    refs = [r['fixture_ref'] for r in page if r['state'] == 'resolved_candidate']
    shot_records, pass_records = {}, {}
    if refs:
        packet = capture_live(bridge, session_id, refs, include_players=True)
        shot_records = {r['fixture_ref']: r for r in shots.capture_retained_shot_maps(
            bridge, session_id, refs, fixture_captures=packet, coach_index=coach_index)['records']}
        from .live_retained_passes import capture_retained_pass_networks
        pass_records = {r['fixture_ref']: r for r in capture_retained_pass_networks(
            bridge, session_id, refs, fixture_captures=packet, coach_index=coach_index)['records']}
    for row in page:
        ref = row.get('fixture_ref')
        row['shot_map'] = _status(shot_records.get(ref), 'shots')
        row['pass_network'] = _status(pass_records.get(ref), 'passes')
        if ref:
            row['fixture_summary'] = _summary(row.pop('fixture'))
            row['native_match_key'] = (shot_records.get(ref) or pass_records.get(ref) or {}).get('native_match_key')
            row['state'] = 'verified_available' if row['shot_map']['state'] == row['pass_network']['state'] == 'available' else 'availability_checked'
    if _inventory(bridge, session_id, coach_index)['source_inventory_id'] != inventory['source_inventory_id']:
        raise ValueError('Retained source inventory changed during discovery')
    if capture_epoch(bridge, session_id) != epoch:
        raise ValueError('Career/load epoch changed during retained-match discovery')
    for row in page:
        if 'candidate_fixtures' in row:
            row['candidate_fixtures'] = [dict(fixture_ref=f['fixture_ref'], **_summary(f))
                                         for f in row['candidate_fixtures']]
    if opponent is not None:
        opponent = dict(opponent)
        if opponent['candidate'] is not None:
            opponent['candidate'] = dict(fixture_ref=opponent['candidate']['fixture_ref'],
                                          **_summary(opponent['candidate']))
        opponent['same_day_candidates'] = [dict(fixture_ref=f['fixture_ref'], **_summary(f))
                                            for f in opponent['same_day_candidates']]
    end = min(offset+limit, len(candidates))
    return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
            'save': inventory['save'], 'scope': scope, 'targets': targets,
            'opponent_selection': opponent, 'source_kind': 'active_human_retained_cbe',
            'source_inventory_id': page_source_id, 'source_entry_count': len(entries),
            'matched_fixture_count': sum('fixture_ref' in r for r in candidates),
            'candidate_count': len(candidates), 'offset': offset, 'returned': len(page),
            'next_offset': end if end < len(candidates) else None,
            'fixtures': page, 'fixture_search': searches, 'saved_file_fallback': False,
            'atomic': False, 'coverage': 'Current checked active-coach retained entries only; absence is not zero data or whole-career coverage.',
            'limits': ['Same-day next-opponent selection does not prove match completion or kickoff order.',
                       'Availability is verified per projection; unavailable or unresolved candidates remain explicit.',
                       'Source retention may expire; archive checked rows before they disappear.']}
