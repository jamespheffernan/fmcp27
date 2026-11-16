"""One read-only live observation of the next dated candidate and managed roster."""
from datetime import date, datetime, timedelta, timezone
from contextlib import contextmanager
import json
import secrets

from . import (assessment_people, database, fixtures, live_club_location,
               player_ban_source, players, world)

POSITIONS = {
    'goalkeeper': 'Goalkeeper', 'defender_left': 'Left back',
    'defender_central': 'Centre back', 'defender_right': 'Right back',
    'defensive_midfielder': 'Defensive midfield', 'midfielder_left': 'Left midfield',
    'midfielder_central': 'Central midfield', 'midfielder_right': 'Right midfield',
    'attacking_midfielder_left': 'Left wing', 'attacking_midfielder_central': 'Attacking midfield',
    'attacking_midfielder_right': 'Right wing', 'striker': 'Striker',
    'wing_back_left': 'Left wing-back', 'wing_back_right': 'Right wing-back',
}
SCOPE = ('Existing resident fixtures in the requested date window and the native managed-team roster. '
         'Stored health is not refreshed. Injury records, position ratings and personal bans do not '
         'establish fixture eligibility, medical clearance or a starting XI. Reads are non-atomic; '
         'all consumed native bytes are rechecked before references are published.')


class _PlanningReadSet(world.ReadSet):
    """One query's exact-region cache; final verify always reads native bytes.

    Sparse future calendars revisit the same guards, bucket routes and identities
    many times. Do not spend the bounded native transport budget rereading them.
    No entries survive this collect call and no source check is omitted at publish.
    """
    def __call__(self, address, length):
        key = address, length
        if key not in self.observed:
            return super().__call__(address, length)
        return self.observed[key]


def _fresh_world_bookend(snapshot, base):
    # Keep the original explicit fresh save/root bookend, independently of the
    # planning cache, then include its consumed bytes in the final verification.
    bookend = world.ReadSet(snapshot.read)
    result = world.loaded(bookend, base)
    for key, value in bookend.observed.items():
        if key in snapshot.observed and snapshot.observed[key] != value:
            raise ValueError('Game state changed during read; retry')
        snapshot.observed[key] = value
    return result


def select_fixture(rows, today, complete):
    """Calendar day first; scores and result types never prove completion."""
    eligible = [r for r in rows if r['date'] >= today]
    if not eligible:
        return {'state': 'none_observed' if complete else 'no_candidate_in_partial_search',
                'candidate': None, 'same_day_candidates': [], 'current_time_known': False,
                'match_completion_known': False}
    earliest = min(r['date'] for r in eligible)
    same_day = [r for r in eligible if r['date'] == earliest]
    # An unknown kickoff may precede any known kickoff; do not silently order it last.
    known_times = all(r.get('kickoff_time', {}).get('state') == 'decoded' for r in same_day)
    ordered = sorted(same_day, key=lambda r: r['kickoff_time']['time']) if known_times else same_day
    state = ('earliest_observed_candidate_unconfirmed' if not complete else
             'same_day_time_or_completion_unknown' if earliest == today else
             'same_day_kickoff_order_unknown' if len(same_day) > 1 and not known_times else
             'earliest_scheduled_candidate')
    return {'state': state, 'candidate': ordered[0], 'same_day_candidates': ordered,
            'current_time_known': False, 'match_completion_known': False}


def project_player(player, location, bans, minimum, player_ref):
    profile = player.get('profile') or {}
    ratings = profile.get('positions')
    positions = ([{'code': code, 'label': label, 'rating': ratings[code]}
                  for code, label in POSITIONS.items() if ratings.get(code, 0) >= minimum]
                 if ratings is not None else None)
    health = player.get('health')
    def percent(value):
        return None if value is None else value / 100
    stored_health = (None if health is None else {
        'condition_percent': percent(health.get('condition')),
        'sharpness_percent': percent(health.get('match_sharpness')),
        'fatigue': None if 'fatigue' in health.get('native_defaults', []) else health.get('fatigue'),
        'injury_record_count': None if 'injury_record_count' in health.get('native_defaults', []) else health.get('injury_record_count'),
        'injuries': None if 'injury_record_count' in health.get('native_defaults', []) else health.get('injuries'), 'state': health['state'],
        'unavailable_fields': health.get('unavailable_fields', []),
        'native_defaults': health.get('native_defaults', []), 'refreshed': False,
    })
    clubs = location.get('clubs') or {}
    return {'name': player.get('display_name') or player.get('name'), 'player_ref': player_ref,
            'native_identity': player['native_identity'], 'roster_index': player['roster_index'],
            'profile_state': player.get('profile_state'), 'positions': positions,
            'position_state': 'stored_ratings' if ratings is not None else 'unavailable',
            'clubs': {**{key: location[key] for key in ('location_state', 'at_managed_club',
                      'current_club_identity', 'contract_club_identity', 'loan_club_identity')},
                      'contract_club': clubs.get('contract_club'),
                      'current_club': clubs.get('current_club'), 'loan_club': clubs.get('loan_club'),
                      'on_loan': clubs.get('on_loan'), 'loan_status_reason': clubs.get('loan_status_reason')},
            'health': stored_health,
            'bans': {'source_state': bans['source_state'], 'count': bans['physical_record_count'],
                     'records': bans['records'], 'active_applicability': 'not_evaluated',
                     'fixture_applicability': 'unknown'},
            'fixture_eligibility': 'unknown'}


def _scan(snapshot, base, catalog, years, catalog_identity, team, today, end, max_pages):
    """Finish every group/slot of earlier days and the earliest candidate day."""
    pending, summaries, continuations = [], [], []
    pages_left, current = max_pages, today
    while current <= end:
        year = current.year
        hi_date = min(end, date(year, 12, 31))
        criteria = dict(year=year, team_native_id=team['native_id'], competition_native_id=None,
                        date_from=current.isoformat(), date_to=hi_date.isoformat(),
                        record_kind=None, include_stage=False)
        if year not in years:
            summaries.append({'year': year, 'state': 'resident_year_unavailable', 'complete': False,
                              'criteria': criteria, 'pages': 0, 'searched_through': None})
            current = hi_date + timedelta(days=1)
            continue
        binding = years[year]
        pages, scanned, buckets, aliases = 0, 0, 0, 0
        through, progress = None, None
        while current <= hi_date and pages_left:
            day = current.timetuple().tm_yday
            position, bucket_identity = (day, 0, 0), None
            day_complete = False
            day_matches = []
            while pages_left:
                found, progress = fixtures.scan(snapshot, base, binding, year, (day, day),
                    team['native_id'], None, None, position, bucket_identity, 100, 1000, 4096, False)
                for item in found:
                    row = item[0]
                    if any(t is not None and t['database_index'] == team['database_index']
                           and t['native_id'] == team['native_id']
                           for t in (row['home_team'], row['away_team'])):
                        day_matches.append(item)
                    else:
                        aliases += 1
                pages += 1; pages_left -= 1
                scanned += progress['scanned_records']; buckets += progress['examined_buckets']
                position, bucket_identity = progress['position'], progress['bucket_identity']
                day_complete = progress['finished']
                if day_complete:
                    through = current.isoformat()
                    break
            pending.extend(day_matches)
            if not day_complete or day_matches:
                break
            current += timedelta(days=1)
        finished_year = current > hi_date
        prefix_complete = (finished_year or progress is not None and progress['finished'])
        summaries.append({'year': year, 'state': 'searched' if prefix_complete else 'page_budget',
                          'complete': prefix_complete and binding['coverage']['all_groups_materialized'],
                          'coverage': binding['coverage'], 'criteria': criteria,
                          'pages': pages, 'scanned_records': scanned, 'examined_buckets': buckets,
                          'filtered_team_alias_records': aliases, 'searched_through': through,
                          'stop_reason': ('earliest_candidate_day_complete' if pending and prefix_complete
                                          else 'window_or_year_end' if finished_year else 'page_budget')})
        if not finished_year and (progress is None or position[0] <= hi_date.timetuple().tm_yday):
            if progress is None:
                position = (current.timetuple().tm_yday, 0, 0)
                bucket_identity = None
            continuations.append({'kind': 'fixtures', 'criteria': criteria, 'identity': catalog_identity,
                                  'position': position, 'bucket_identity': bucket_identity})
        if pending or not pages_left:
            break
    date_range_exhausted = current > end or bool(pending) and current == end and progress['finished']
    window_fully_scanned = date_range_exhausted and all(row['complete'] for row in summaries)
    return pending, summaries, continuations, bool(window_fully_scanned)



@contextmanager
def _reference_transaction(bridge):
    names = ('player_refs', 'fixture_refs', 'team_refs', 'competition_refs',
             'stage_refs', 'stadium_refs', 'database_cursors')
    previous = {name: dict(getattr(bridge, name)) for name in names}
    try:
        yield
    except BaseException:
        for name, saved in previous.items():
            target = getattr(bridge, name)
            target.clear()
            target.update(saved)
        raise


def collect(bridge, session_id, coach_name, window_days, position_minimum, max_fixture_pages):
    """Caller owns bridge.lock and one native read scope; no native functions run."""
    process = bridge._current(session_id)
    tables = bridge._player_layout(process)
    base = tables[0] - players.RVA[0]
    snapshot, save, identity = bridge._world_state(process, tables)
    original = snapshot
    snapshot = _PlanningReadSet(original.read)
    snapshot.observed.update(original.observed)
    coach = bridge._select_coach(save, coach_name)
    team, context = bridge._roster_team(snapshot, base, coach['team_address'])
    managed_club_address = world.pointer(snapshot, coach['team_address'] + 0x30)
    today = date.fromisoformat(save['current_date'])
    end = today + timedelta(days=window_days)
    catalog, years, catalog_identity = fixtures.catalog(snapshot, base)
    pending, search, continuations, window_fully_scanned = _scan(snapshot, base, catalog, years, catalog_identity,
                                         team, today, end, max_fixture_pages)
    addresses = world.vector(snapshot, coach['team_address'] + 0x38, 256)
    team_cache, people = {}, []
    person_table = database.table(snapshot, base, 'people') if addresses else None
    player_ban_source.verify_native(snapshot, base)
    for slot, address in enumerate(addresses):
        player, player_identity = bridge._roster_player(snapshot, address, tables, True, team_cache,
                                                        True, True, 'available')
        bridge._roster_available_context(snapshot, address, tables, player, player_identity, context, slot)
        binding = bridge._player_binding(address, player, player_identity, tables, 'available')
        if player['record_kind'] in ('actual', 'player_staff'):
            assessment_people.bound_player(snapshot, base, tables, person_table, binding)
        location = live_club_location.resolve(snapshot, base, address, player['record_kind'], managed_club_address)
        bans = player_ban_source.project(snapshot, address, player['record_kind'])
        people.append((player, binding, location, bans))
    # Re-read roots and all consumed data in this same scope. A reschedule, roster,
    # loan, health, personal-ban or materialization change must reject the observation.
    current_save, current_identity = _fresh_world_bookend(snapshot, base)
    if current_identity != identity or current_save != save:
        raise ValueError('Loaded career or current date changed during squad planning')
    snapshot.verify()
    bridge._current(session_id)
    with _reference_transaction(bridge):
        if len(bridge.player_refs) + len(people) > 1000:
            bridge.player_refs.clear()
        if len(bridge.fixture_refs) + len(pending) > 10000:
            bridge.fixture_refs.clear()
        if len(bridge.team_refs) + 2 * len(pending) > 10000:
            bridge.team_refs.clear()
        if len(bridge.competition_refs) + len(pending) > 10000:
            bridge.competition_refs.clear()
        if len(bridge.stadium_refs) + len(pending) > 10000:
            bridge.stadium_refs.clear()
        result_people = []
        for player, binding, location, bans in people:
            ref = secrets.token_urlsafe(12)
            bridge.player_refs[ref] = binding
            result_people.append(project_player(player, location, bans, position_minimum, ref))
        rows = [bridge._publish_fixture(row, linked, comp_address,
                    {**binding, 'catalog_identity': catalog_identity}, tables, today.isoformat(),
                    stage_binding=stage, stadium_binding=stadium)
                for row, linked, comp_address, stage, stadium, binding in pending]
        public_continuations = []
        for saved in continuations:
            if len(bridge.database_cursors) >= 100:
                bridge.database_cursors.clear()
            cursor = secrets.token_urlsafe(12)
            bridge.database_cursors[cursor] = saved
            public_continuations.append({'cursor': cursor, 'criteria': saved['criteria']})
        grouped = {'at_club': [], 'away': [], 'unknown_club': []}
        for row in result_people:
            key = {'at_managed_club': 'at_club', 'away_from_managed_club': 'away'}.get(
                row['clubs']['location_state'], 'unknown_club')
            grouped[key].append(row)
        cover = {code: {'label': label, 'players': []} for code, label in POSITIONS.items()}
        for row in grouped['at_club']:
            for position in row['positions'] or []:
                cover[position['code']]['players'].append({'name': row['name'], 'player_ref': row['player_ref'],
                                                           'rating': position['rating']})
        complete = all(row['complete'] for row in search) and (bool(rows) or window_fully_scanned)
        selection = select_fixture(rows, today.isoformat(), complete)
        selection['search'] = {'window': {'from': today.isoformat(), 'to': end.isoformat()},
            'complete': window_fully_scanned and complete, 'selection_complete': complete,
            'window_fully_scanned': window_fully_scanned,
            'searched_through': next((r['searched_through'] for r in reversed(search) if r.get('searched_through')), None),
            'years': search, 'pages': sum(r['pages'] for r in search),
            'scanned_records': sum(r.get('scanned_records', 0) for r in search),
            'continuations': public_continuations, 'fixture_scope': fixtures.SCOPE}
        result = {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
                  'save': bridge._public_save(save), 'coach': coach['name'], 'club': coach['club'],
                  'managed_team': team, 'fixture': selection,
                  'roster': {'native_count': len(result_people),
                             **{key+'_count':len(value) for key,value in grouped.items()}, **grouped},
                  'position_minimum': position_minimum, 'position_scale': '0–20', 'position_cover': cover,
                  'eligibility': {'state': 'unknown', 'registration': None,
                                  'fixture_suspension': None, 'medical_clearance': None},
                  'consistency': {'one_native_read_scope': True, 'consumed_bytes_rechecked': True,
                                  'atomic': False, 'native_functions_called': False}, 'limitations': SCOPE}
        if len(json.dumps(result, ensure_ascii=True).encode()) > 2 * 1024**2:
            raise ValueError('Next-match squad response exceeds the bounded response budget')
        return result
