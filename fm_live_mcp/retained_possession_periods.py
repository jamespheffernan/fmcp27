"""Counter-qualified retained possession events by independently witnessed period.

No cursor PLAYER totals, guessed minutes, pressure attribution or transition map.
The report consumes only event IDs/actors/categories/clocks; its witness never
certifies coordinates, other annotations or full native flag equality.
"""
from collections import Counter
import hashlib
import struct

from .match_period_observations import digest, fixture_identity
from .retained_possession_events import CATEGORIES, decode_possession_events

REPORT_POLICY = 'possession_period_actor_category_clocks_v1'


def possession_period_fingerprint(event_bytes, cursor=65536):
    if type(event_bytes) is not bytes or len(event_bytes) % 56 or len(event_bytes) > 30000 * 56:
        raise ValueError('Invalid complete possession period event source')
    if type(cursor) is not int or not 0 < cursor <= 65536:
        raise ValueError('Invalid possession period witness cutoff')
    rows = []
    seen = set()
    for at in range(0, len(event_bytes), 56):
        event = event_bytes[at:at + 56]
        if event[42] not in CATEGORIES:
            continue
        start, end = (struct.unpack_from('<H', event, offset)[0] for offset in (34, 50))
        if end >= cursor:
            continue
        event_id = struct.unpack_from('<I', event, 44)[0]
        if event_id in seen or event[40] not in (0, 1) or event[39] >= 26 or start > end:
            raise ValueError('Invalid or ambiguous possession period event identity/clock')
        seen.add(event_id)
        rows.append(dict(event_id=event_id, side_index=event[40], stored_player_slot=event[39],
                         native_category_code=event[42], start_tick=start, end_tick=end))
    return dict(schema=1, report_policy=REPORT_POLICY, semantic_sha256=digest(sorted(rows, key=lambda row: row['event_id'])),
                event_count=len(rows), cutoff_exclusive=cursor)


def validate_fingerprint(value, cursor):
    if (type(value) is not dict or set(value) != {'schema', 'report_policy', 'semantic_sha256', 'event_count', 'cutoff_exclusive'}
            or type(value['schema']) is not int or value['schema'] != 1 or value['report_policy'] != REPORT_POLICY
            or type(value['event_count']) is not int or not 0 <= value['event_count'] <= 30000
            or type(value['cutoff_exclusive']) is not int or value['cutoff_exclusive'] != cursor
            or not isinstance(value['semantic_sha256'], str) or len(value['semantic_sha256']) != 64
            or any(c not in '0123456789abcdef' for c in value['semantic_sha256'])):
        raise ValueError('Invalid possession period report witness')


def _intervals(link):
    intervals = []
    for row in link.get('intervals', []):
        period, start, end = (row.get(key) for key in ('period', 'start_tick', 'end_tick'))
        if (period not in ('FirstHalf', 'SecondHalf') or type(start) is not int or type(end) is not int
                or not 0 <= start < end < 65536 or any(other['period'] == period for other in intervals)):
            raise ValueError('Invalid or ambiguous witnessed possession periods')
        intervals.append(dict(period=period, start_tick=start, end_tick=end))
    if any(max(a['start_tick'], b['start_tick']) < min(a['end_tick'], b['end_tick'])
           for i, a in enumerate(intervals) for b in intervals[i + 1:]):
        raise ValueError('Overlapping witnessed possession periods')
    return intervals


def project(event_bytes, players, fixture, native_match_key, period_link, observation, *, pitch_geometry=None, attestation=None):
    unavailable = dict(state='unavailable_possession_period_source', sides=None, periods=None)
    if period_link.get('state') != 'verified_retrospective_continuity':
        return dict(unavailable, reason='verified_host_period_link_required')
    if digest(observation) != period_link.get('capture_id'):
        raise ValueError('Possession period observation identity differs')
    if (observation.get('fixture') != fixture_identity(fixture)
            or period_link.get('native_match_key') != native_match_key
            or period_link.get('official_match_unique_id') != observation.get('official_match_unique_id')
            or period_link.get('clock_domain') != 'native_playback_time_slice'):
        raise ValueError('Possession period fixture/UID/native clock binding differs')
    intervals = _intervals(period_link)
    if not intervals:
        return dict(unavailable, reason='no_closed_observed_periods')
    witness = observation.get('possession_period_report_fingerprint')
    if attestation is not None:
        from .possession_period_attestations import validate
        derived = validate(attestation, observation)
        if witness is not None and witness != derived:
            raise ValueError('Captured and derived possession witnesses disagree')
        witness = derived
    raw_match = hashlib.sha256(event_bytes).hexdigest() == observation.get('source_hashes', {}).get('events')
    if witness is not None:
        validate_fingerprint(witness, observation.get('fingerprint_cursor'))
        if witness != possession_period_fingerprint(event_bytes, witness['cutoff_exclusive']):
            return dict(unavailable, reason='possession_period_event_semantics_differ',
                        possession_period_report_continuity='mismatch')
        if any(row['end_tick'] > witness['cutoff_exclusive'] for row in intervals):
            return dict(unavailable, reason='period_exceeds_possession_witness_prefix')
        binding = 'matched_possession_event_ids_actors_categories_clocks'
    elif raw_match:
        if any(row['end_tick'] > observation.get('fingerprint_cursor', 0) for row in intervals):
            return dict(unavailable, reason='period_exceeds_observed_source_prefix')
        binding = 'exact_complete_observed_event_vector'
    else:
        return dict(unavailable, reason='independent_possession_event_witness_required')
    decoded = decode_possession_events(event_bytes, players, fixture, native_match_key=native_match_key,
                                       pitch_geometry=pitch_geometry)
    sides = []
    for coverage in decoded['sides']:
        side = coverage['side_index']
        if coverage['state'] != 'available_complete_player_counter_closure':
            sides.append(dict(side_index=side, team_native_id=coverage['team_native_id'],
                state='unavailable_possession_counter_closure', periods=None,
                unknown_interval_event_count=None, player_checks=coverage['player_checks']))
            continue
        own = [row for row in decoded['events'] if row['side_index'] == side]
        groups = {row['period']: Counter() for row in intervals}
        unknown = Counter()
        for row in own:
            start, end = row['native_start_clock_word'], row['native_end_clock_word']
            if start > end:
                raise ValueError('Wrapped or reversed retained possession event clocks')
            periods = [interval['period'] for interval in intervals if interval['start_tick'] <= start <= end < interval['end_tick']]
            target = groups[periods[0]] if len(periods) == 1 else unknown
            target[row['person_native_id'], row['event_kind']] += 1

        def population(counts):
            rows = []
            for player in coverage['player_checks']:
                person = player['person_native_id']
                won, lost = counts[person, 'possession_won'], counts[person, 'possession_lost']
                rows.append(dict(person_native_id=person, person_name=player['person_name'],
                    stored_player_slot=player['stored_player_slot'], possession_won_events=won, possession_lost_events=lost))
            return sorted(rows, key=lambda row: (-row['possession_lost_events'], -row['possession_won_events'], row['person_native_id']))

        periods = []
        for interval in intervals:
            rows = population(groups[interval['period']])
            periods.append(dict(**interval, possession_won_events=sum(row['possession_won_events'] for row in rows),
                possession_lost_events=sum(row['possession_lost_events'] for row in rows), players=rows))
        sides.append(dict(side_index=side, team_native_id=coverage['team_native_id'], state='available', periods=periods,
            full_fixture_possession_won=coverage['possession_won'], full_fixture_possession_lost=coverage['possession_lost'],
            full_fixture_player_counter_checks=len(coverage['player_checks']),
            unknown_interval_event_count=sum(unknown.values()), unknown_interval_players=population(unknown)))
    return dict(state='available' if all(side['state'] == 'available' for side in sides) else 'partial',
        sides=sides, periods=intervals, period_provenance=period_link['provenance'],
        possession_period_binding=binding, possession_period_report_continuity='matched' if witness is not None else 'not_captured',
        metric_attestation_id=attestation['attestation_id'] if attestation is not None else None,
        complete_event_vector_continuity='matched' if raw_match else 'mismatch',
        native_event_vector_sha256=hashlib.sha256(event_bytes).hexdigest(),
        time_domain='native_playback_time_slice',
        boundary_policy='period_start<=event_start<=event_end<period_end; ties/crossings/unobserved intervals unassigned',
        count_policy='Whole-fixture per-player won/lost counters including zero players close per side before period rows publish. Period totals are sums of those qualified events, not independent native period counters.',
        limits=['Historical original-roster actors, not current on-pitch membership or minutes.',
                'Possession wins/losses are not completed pressures, press success or a paired opposing turnover.',
                'No transition locations, pitch bins, native physical units, displayed-minute conversion or tactical cause.',
                'Report continuity does not certify unconsumed coordinates, flags or annotations.'])


def report(bridge, session_id, fixture_ref, *, team_native_id=None, person_native_id=None, store=None):
    from . import live_retained_shots as retained, players as layout
    from .active_pass_network import PASS_CLOCK_SPANS
    from .match_data_query import capture_epoch, capture_live
    from .match_period_observations import ObservationStore, link_retained, process_epoch
    from .retained_possession_events import verify_native
    from .saved_match_player_recoveries import decode_player_recoveries
    from .live_match_players import project_frame
    if not isinstance(fixture_ref, str) or not fixture_ref:
        raise ValueError('Select one retained RESULT fixture reference')
    if any(value is not None and (type(value) is not int or value <= 0) for value in (team_native_id, person_native_id)):
        raise ValueError('Invalid canonical possession period selector')
    if person_native_id is not None and team_native_id is None:
        raise ValueError('A possession period player requires its team')
    epoch = capture_epoch(bridge, session_id)
    capture = capture_live(bridge, session_id, [fixture_ref], include_players=True)
    if capture.get('_live_capture_epoch') != epoch:
        raise ValueError('Possession period frame epoch differs')
    items = capture['capture']['fixtures']
    if len(items) != 1 or items[0]['fixture']['fixture_ref'] != fixture_ref:
        raise ValueError('Exact retained possession period fixture required')
    fixture, key = items[0]['fixture'], items[0]['native_match_key']
    selected = [side for side, field in enumerate(('home_team', 'away_team'))
                if team_native_id is None or fixture[field]['native_id'] == team_native_id]
    if not selected:
        raise ValueError('Selected team is not in the retained fixture')
    records = [record for record in capture['team_totals']['records'] if record['result_key'] == key]
    if len(records) != 1:
        raise ValueError('Exact retained possession team oracle required')
    teams = records[0]['teams']
    retained._validate_team_oracle(fixture, teams)
    players = [{**row, **decode_player_recoveries(bytes.fromhex(row['raw_child_hex']))}
               for row in capture['retained_players'] if row.get('fixture_key', row.get('native_match_key')) == key]
    frames = [frame for frame in capture['raw_frames'] if frame['key'] == key]
    if len(frames) != 1:
        raise ValueError('Exact complete possession player frame required')
    complete = project_frame(frames[0]['raw'], key)
    source_rows = {(row['side_index'], row['stored_player_slot'], row['row_sha256'], row['person_index_word'])
                   for row in complete['rows']}
    supplied_rows = {(row['side_index'], row['stored_player_slot'], row['row_sha256'], row['person_index_word'])
                     for row in players}
    if (not complete['coverage']['complete_side_sections'] or len(players) != sum(complete['coverage']['stored_rows_per_side'])
            or len(source_rows) != len(players) or source_rows != supplied_rows):
        raise ValueError('Complete possession player roster differs, including zero actors')
    if len(retained._validated_actors(players, teams)) != len(players):
        raise ValueError('Canonical possession period actors differ')
    with bridge.lock, bridge._read_scope(session_id):
        process = bridge._current(session_id)
        tables = bridge._player_layout(process)
        read, _, _ = bridge._world_state(process, tables)
        base = tables[0] - layout.RVA[0]
        verify_native(read, base)
        for rva, expected in PASS_CLOCK_SPANS:
            if read(base + rva, len(expected)) != expected:
                raise ValueError('Possession native clock source changed')
        read.verify()
        bridge._current(session_id)
    source = retained.capture_source(bridge, session_id, fixture_ref, key, fixture)
    if source['state'] != 'available':
        return dict(state=source['state'], fixture=fixture, sides=None, periods=None)
    shots = retained.decode_attempts(source['vectors'], source['events'], teams)
    if any(side['state'] != 'available' for side in shots['side_coverage']):
        return dict(state='unavailable_retained_period_continuity', fixture=fixture, sides=None, periods=None)
    save = bridge.get_save(session_id)['save']
    store = store or ObservationStore()
    link = link_retained(store, save, fixture, key, source, shots['shots'], process_epoch(bridge))
    document = store.observations(save, fixture)
    observation = document['observations'].get(link.get('capture_id'), {})
    # This follows, never substitutes for, normal epoch/finalized-pin selection.
    from .possession_period_attestations import load
    attestation = load(store.root, observation) if link.get('state') == 'verified_retrospective_continuity' else None
    result = project(source['events'], players, fixture, key, link, observation,
                     pitch_geometry=source.get('pitch_geometry'), attestation=attestation)
    fresh = retained.capture_source(bridge, session_id, fixture_ref, key, fixture)
    if (fresh.get('state') != 'available' or fresh['events'] != source['events'] or fresh['vectors'] != source['vectors']
            or capture_epoch(bridge, session_id) != epoch):
        raise ValueError('Retained possession period source changed')
    if result.get('sides') is not None:
        result['sides'] = [side for side in result['sides'] if side['side_index'] in selected]
        if person_native_id is not None:
            actors = [row for row in players if row['side_index'] in selected and row['canonical_person_id'] == person_native_id]
            if len(actors) != 1:
                return dict(state='unavailable_selected_possession_actor', fixture=fixture, sides=None, periods=None)
            for side in result['sides']:
                if side['periods'] is None:
                    continue
                for period in side['periods']:
                    period['players'] = [row for row in period['players'] if row['person_native_id'] == person_native_id]
                side['unknown_interval_players'] = [row for row in side['unknown_interval_players'] if row['person_native_id'] == person_native_id]
        result['state'] = 'available' if all(side['state'] == 'available' for side in result['sides']) else 'partial'
    return dict(result, fixture=fixture, native_match_key=key, team_native_id=team_native_id,
                person_native_id=person_native_id, saved_file_fallback=False, atomic=False,
                source_kind='current_session_retained_RESULT_CBE_with_host_period_witness',
                temporal_scope='retrospective_closed_native_period_intervals_not_active_cursor_PLAYER_totals',
                complete_native_roster_rows_per_side=complete['coverage']['stored_rows_per_side'],
                period_totals_scope='full_selected_side_all_original_roster_actors_even_with_person_filter')
