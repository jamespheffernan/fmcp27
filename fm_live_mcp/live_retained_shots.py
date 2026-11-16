"""Checked retained CBE shot origins; no pitch normalization or player inference."""
from collections import defaultdict, Counter
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import math
import json
import struct

from . import fixtures, players, prepared_tactics_source, world
from .live_match_backing import read_selected_matches
from .live_match_team_totals import decode_team_totals
from .match_data_query import capture_epoch
from .retained_shot_outcomes import outcome_fields, outcome_counts, outcome_policy
from .retained_shot_location import classify_location, location_field_registry

MAX_SHOTS_PER_SIDE = 1024
MAX_EVENTS = 30000
MAX_ENTRIES = 4096
OWN_GOAL = 49
HEADER_SHOT_TYPES = frozenset((2, 7, 10))
FEET_SHOT_TYPES = frozenset((0, 1, 5, 6, 8, 9))


def _body_part(native_type):
    if native_type in HEADER_SHOT_TYPES:
        return 'head'
    if native_type in FEET_SHOT_TYPES:
        return 'feet'
    return None


def _chunks(read, start, size):
    return b''.join(read(at, min(8192, start + size - at))
                    for at in range(start, start + size, 8192))


def _records(read, address, width, limit):
    start, end, capacity = struct.unpack('<QQQ', read(address, 24))
    if (start, end, capacity) == (0, 0, 0):
        return b''
    if (start < 4096 or any(p % 8 for p in (start, end, capacity))
            or not start <= end <= capacity or (end-start) % width
            or (capacity-start) % width or capacity-start > width * limit):
        raise ValueError('Unsupported retained record vector geometry or budget')
    return _chunks(read, start, end-start)


def _f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def _ulp_distance(a, b):
    if not all(math.isfinite(v) and v >= 0 for v in (a, b)):
        return None
    return abs(struct.unpack('<I', struct.pack('<f', a))[0]
               - struct.unpack('<I', struct.pack('<f', b))[0])


def decode_attempts(shot_vectors, event_bytes, teams, *, pitch_geometry=None, _retain_candidates=False):
    """Pure bounded projection; release each side only after reconciliation."""
    if len(shot_vectors) != 2 or len(teams) != 2 or len(event_bytes) % 56:
        raise ValueError('Unsupported retained shot/event profile')
    if len(event_bytes)//56 > MAX_EVENTS:
        raise ValueError('Retained event budget exceeded')
    for raw in shot_vectors:
        if len(raw) % 48 or len(raw)//48 > MAX_SHOTS_PER_SIDE:
            raise ValueError('Retained shot vector budget or width differs')
    references = Counter(struct.unpack_from('<I', raw, at+36)[0]
                         for raw in shot_vectors for at in range(0, len(raw), 48))
    events = defaultdict(list)
    for at in range(0, len(event_bytes), 56):
        event = event_bytes[at:at+56]
        events[struct.unpack_from('<I', event, 44)[0]].append(event)
    sides, shots, markers = [], [], []
    candidates_by_side = {}
    marker_candidates_by_side = {}
    for side, (raw, team) in enumerate(zip(shot_vectors, teams)):
        if len(raw) % 48 or len(raw)//48 > MAX_SHOTS_PER_SIDE:
            raise ValueError('Retained shot vector budget or width differs')
        attempts, own_goals, errors = [], [], []
        total_xg = 0.0; target = 0
        for at in range(0, len(raw), 48):
            record = raw[at:at+48]; event_id = struct.unpack_from('<I', record, 36)[0]
            if references[event_id] != 1:
                errors.append({'event_id': event_id, 'reason': 'duplicate_retained_event_reference'})
                continue
            linked = events.get(event_id, [])
            if len(linked) != 1:
                errors.append({'event_id': event_id, 'reason': 'missing_or_ambiguous_linked_event'})
                continue
            event = linked[0]; actor_side, category = event[40], event[42]
            xg = struct.unpack_from('<f', record, 32)[0]
            x, y = struct.unpack_from('<ff', event, 24)
            if not all(math.isfinite(v) for v in (xg, x, y)) or not 0 <= xg <= 1:
                errors.append({'event_id': event_id, 'reason': 'nonfinite_or_invalid_native_values'})
                continue
            marker = category == OWN_GOAL
            expected_side = 1-side if marker else side
            if actor_side != expected_side:
                errors.append({'event_id': event_id, 'native_category_code': category,
                               'event_side_index': actor_side, 'reason': 'native_side_link_disagrees'})
                continue
            row = {'record_index': at//48, 'event_id': event_id,
                   'native_x': x, 'native_y': y, 'coordinate_units': None,
                   'coordinate_viewpoint': None, 'native_category_code': category, 'native_shot_type': record[44], 'event_side_index': actor_side,
                   'stored_player_slot': event[39],
                   'native_clock_start_raw': struct.unpack_from('<H', event, 34)[0],
                   'native_clock_end_raw': struct.unpack_from('<H', event, 50)[0],
                   'source_record_sha256': hashlib.sha256(record).hexdigest()}
            location = {'native_location_bin': None, 'official_location': None,
                        'location_group': None, 'location_state': 'unavailable_pitch_geometry',
                        'attacked_goal_positive_native_y': bool(struct.unpack_from('<H', event, 48)[0] & 256),
                        'distance_to_goal': None}
            if not marker and pitch_geometry is not None:
                location = classify_location(x, y, location['attacked_goal_positive_native_y'],
                                             pitch_geometry['half_length_native'])
            if marker:
                location['location_state'] = 'not_a_statistical_attempt'
                own_goals.append(dict(row, **location, event_side_index=actor_side, actor_side_index=actor_side,
                                      beneficiary_side_index=side, native_expected_goals=xg,
                                      kind='own_goal_marker', statistical_shot=False,
                                      body_part=None, is_header=None,
                                      body_part_state='not_a_statistical_attempt',
                                      is_penalty=None, shot_situation=None, shot_situation_state='not_a_statistical_attempt'))
            else:
                body_part = _body_part(record[44])
                attempts.append(dict(row, **location, side_index=side, expected_goals=xg,
                                     body_part=body_part,
                                     is_header=None if body_part is None else body_part == 'head',
                                     body_part_state='native_shotmap_group_proved' if body_part else 'native_type_unclassified',
                                     is_penalty=record[44] == 4,
                                     shot_situation='penalty' if record[44] == 4 else 'non_penalty_unspecified',
                                     shot_situation_state='native_penalty_exclusion_proved_other_types_unmapped',
                                     clock=None, outcome=None))
                total_xg = _f32(total_xg+xg)
                target += category in (1, 4)
        ulps = _ulp_distance(total_xg, team.get('expected_goals', float('nan')))
        checks = {'shot_count_matches': len(attempts) == team.get('shots'),
                  'shots_on_target_matches': target == team.get('shots_on_target'),
                  'xg_sum_within_one_float32_ulp': ulps is not None and ulps <= 1}
        available = not errors and all(checks.values())
        body_parts = Counter(row['body_part'] or 'unclassified' for row in attempts)
        if available:
            for attempt in attempts:
                attempt.update(outcome_fields(attempt['native_category_code']))
        outcomes = outcome_counts(attempts) if available else None
        sides.append({'side_index': side, 'team_index': team.get('team_index'),
                      'team_native_id': team.get('team_identity_word'),
                      'state': 'available' if available else 'unavailable_unreconciled_retained_side',
                      'retained_record_count': len(raw)//48, 'statistical_shot_count': len(attempts),
                      'own_goal_marker_count': len(own_goals) if available else None,
                      'outcome_counts': outcomes,
                      'outcome_coverage': 'complete_known_end_states' if outcomes is not None and not outcomes['unknown'] else 'partial_unmapped_categories' if outcomes is not None else 'unavailable_side',
                      'shot_count': len(attempts) if available else None,
                      'shots_on_target': target if available else None,
                      'body_part_counts': {part: body_parts[part] if available else None
                                           for part in ('head', 'feet', 'unclassified')},
                      'expected_goals': total_xg if available else None, 'official_shots': team.get('shots'),
                      'official_shots_on_target': team.get('shots_on_target'),
                      'official_expected_goals': team.get('expected_goals'),
                      'native_float32_attempt_xg_sum': total_xg, 'xg_float32_ulp_distance': ulps,
                      'checks': checks, 'link_errors': errors})
        if _retain_candidates:
            candidates_by_side[side] = attempts
            marker_candidates_by_side[side] = own_goals
        if available:
            shots.extend(attempts); markers.extend(own_goals)
    result = {'state': 'available' if all(s['state']=='available' for s in sides) else 'available_partial',
              'side_coverage': sides, 'shots': shots, 'own_goal_markers': markers}
    if _retain_candidates:
        result['_candidates_by_side'] = candidates_by_side
        result['_marker_candidates_by_side'] = marker_candidates_by_side
    return result


def _verify_native(read, base):
    for rva, expected in NATIVE_SPANS:
        if read(base+rva, len(expected)) != expected:
            raise ValueError('Retained shot native binding changed')


def _fixture_signature(f):
    return (f.get('date'), (f.get('competition') or {}).get('native_id'),
            tuple(((f.get(s) or {}).get('database_index'), (f.get(s) or {}).get('native_id'))
                  for s in ('home_team', 'away_team')), f.get('scores'))


def capture_source(bridge, session_id, fixture_ref, expected_key, fixture, coach_index=None, *, include_tracking=False, include_native_heat_map=False, verify_xg_value=False):
    """Read one native retained owner source and seal its final publication lifetime."""
    fixture = deepcopy(fixture)
    def check_fixture():
        if not saved or saved['tables'] != tables:
            raise ValueError('Selected fixture reference expired')
        _, years, identity = fixtures.catalog(read, base)
        if saved['catalog_identity'] != identity:
            raise ValueError('Selected fixture inventory changed')
        entries, route = fixtures.bucket(read, years[saved['year']], saved['day'], saved['group'])
        if route != saved['route'] or entries[saved['slot']] != saved['address']:
            raise ValueError('Selected fixture membership changed')
        decoded = fixtures.record(read, base, saved['address'], saved['year'], saved['day'], {})
        if decoded['identity'] != saved['identity'] or decoded['kind'] != 'result':
            raise ValueError('Select a checked result fixture')
        if struct.unpack('<i', read(saved['address']+0x58, 4))[0] != expected_key:
            raise ValueError('Selected native match key changed')
        native_fixture = fixtures.detail(read, base, saved['address'], saved['year'], saved['day'], decoded, {}, False)[0]
        if _fixture_signature(native_fixture) != _fixture_signature(fixture):
            raise ValueError('Selected fixture metadata differs from canonical native binding')

    def seal():
        # Bridge performs its hidden post-yield process callback before this hook.
        # Enrol final context reads into the original consumed-byte set, then run
        # every remaining callback/cache check before its last physical fence.
        current = bridge._current(session_id)
        if current != process:
            raise ValueError('Retained shot process lifetime changed')
        after_tables = bridge._player_layout(current)
        if after_tables != tables or bridge.plugin_identity != plugin_identity:
            raise ValueError('Retained shot loaded plugin/build changed')
        after_read, after_save, after_identity = bridge._world_state(current, after_tables)
        if (after_save != save or after_identity != world_identity
                or bridge.world_identity != world_identity):
            raise ValueError('Retained shot loaded save/date context changed')
        for (address, length), expected in list(after_read.observed.items()):
            if read(address, length) != expected:
                raise ValueError('Retained shot final source context changed')
        if bridge.fixture_refs.get(fixture_ref) != saved:
            raise ValueError('Selected fixture reference changed')
        check_fixture()
        if bridge._current(session_id) != process:
            raise ValueError('Retained shot final process lifetime changed')
        if (bridge.session != session_id or bridge.process != process
                or bridge.plugin_identity != plugin_identity or bridge.world_identity != world_identity
                or bridge.fixture_refs.get(fixture_ref) != saved):
            raise ValueError('Retained shot final context/reference binding changed')
        read.verify()

    with bridge.lock, bridge._read_scope(session_id, final_verify=seal):
        process = bridge._current(session_id); tables = bridge._player_layout(process)
        plugin_identity = deepcopy(bridge.plugin_identity)
        read, loaded, world_identity = bridge._world_state(process, tables)
        save, world_identity = deepcopy(loaded), deepcopy(world_identity)
        if bridge.world_identity != world_identity:
            raise ValueError('Retained shot initial world binding differs')
        saved = deepcopy(bridge.fixture_refs.get(fixture_ref))
        base = tables[0]-players.RVA[0]
        if players.verify_runtime(read, base, plugin_identity[1]) != tables:
            raise ValueError('Retained shot runtime layout binding differs')
        _verify_native(read, base)
        if type(verify_xg_value) is not bool:
            raise ValueError('verify_xg_value must be boolean')
        if verify_xg_value:
            from .retained_shot_values import verify_native_xg_value
            verify_native_xg_value(read, base)
        if type(include_tracking) is not bool:
            raise ValueError('include_tracking must be boolean')
        if include_native_heat_map:
            if not include_tracking:
                raise ValueError('Native heat maps require tracking.')
            from .live_tracking_heatmaps import verify_native_heatmap
            verify_native_heatmap(read, base)
        if include_tracking:
            from .live_average_positions import TRACKING_NATIVE_SPANS
            for rva, expected in TRACKING_NATIVE_SPANS:
                if read(base + rva, len(expected)) != expected:
                    raise ValueError('Average-position native binding changed')
        check_fixture()
        wanted = date.fromisoformat(fixture['date'])
        team_ids = {(fixture.get(side) or {}).get('native_id') for side in ('home_team','away_team')}
        coaches = save['coaches']
        if coach_index is not None and not 0 <= coach_index < len(coaches):
            raise ValueError('Coach index is outside the current active coach roster')
        candidates = []; null_seen = False
        for ci, coach in enumerate(coaches):
            if coach_index is not None and ci != coach_index:
                continue
            _, human = prepared_tactics_source._team_and_human(read, base, coach)
            for off in (0x188, 0x1a0, 0x170, 0x1b8):
                pointers = _records(read, human+off, 8, MAX_ENTRIES)
                matches = []
                for (ptr,) in struct.iter_unpack('<Q', pointers):
                    if ptr < 4096 or ptr % 8:
                        raise ValueError('Invalid retained owner entry')
                    header = read(ptr, 24); packed = struct.unpack_from('<I', header, 4)[0]
                    owner_id = struct.unpack_from('<i', header, 16)[0]
                    if packed>>16 == wanted.year and packed&511 == wanted.timetuple().tm_yday and owner_id in team_ids:
                        matches.append((players.u64(header, 8), owner_id))
                if len(matches) > 1:
                    bridge._current(session_id)
                    return {'state': 'unavailable_ambiguous_owner_date_entries'}
                if matches:
                    cbe, owner_id = matches[0]
                    if not cbe:
                        null_seen = True; continue
                    if cbe < 4096 or cbe % 8:
                        raise ValueError('Invalid retained CBE pointer')
                    candidates.append((cbe, ci, coach['name'], owner_id)); break
        unique = {c[0] for c in candidates}
        if len(unique) > 1:
            bridge._current(session_id)
            return {'state': 'unavailable_ambiguous_coach_sources'}
        if not candidates:
            result = {'state': 'unavailable_null_retained_source' if null_seen else 'unavailable_not_retained'}
        else:
            cbe, ci, name, owner_id = candidates[0]
            geometry_bytes = read(cbe+0x100, 8)
            half_width, half_length = struct.unpack('<ff', geometry_bytes)
            geometry = ({'half_width_native': half_width, 'half_length_native': half_length}
                        if all(math.isfinite(v) and v > 0 for v in (half_width, half_length)) else None)
            result = {'state': 'available', 'coach_index': ci, 'coach_name': name,
                      'pitch_geometry': geometry, 'pitch_geometry_raw': geometry_bytes,
                      'owner_team_native_id': owner_id,
                      'events': _records(read, cbe+8, 56, MAX_EVENTS),
                      'vectors': [_records(read, cbe+off, 48, MAX_SHOTS_PER_SIDE) for off in (0x20, 0x38)]}
        if include_tracking and result['state'] == 'available':
            from .live_average_positions import read_tracking_source
            result['tracking'] = read_tracking_source(read, cbe)
        bridge._current(session_id)
        return result


def _empty_sides(fixture, state):
    return [{'side_index': i, 'state': state, 'team_index': (fixture.get(side) or {}).get('database_index'),
             'team_native_id': (fixture.get(side) or {}).get('native_id'),
             'shot_count': None, 'shots_on_target': None, 'expected_goals': None,
             'body_part_counts': {part: None for part in ('head', 'feet', 'unclassified')},
             'own_goal_marker_count': None, 'outcome_counts': None, 'outcome_coverage': 'unavailable_side'} for i, side in enumerate(('home_team', 'away_team'))]


def _validate_team_oracle(fixture, teams):
    expected = [((fixture.get(side) or {}).get('database_index'),
                 (fixture.get(side) or {}).get('native_id')) for side in ('home_team', 'away_team')]
    actual = [(row.get('team_index'), row.get('team_identity_word')) for row in teams]
    if len(actual) != 2 or actual != expected or any(None in pair for pair in expected):
        raise ValueError('Decoded team oracle differs from canonical fixture TEAM identity')


def _validated_actors(rows, teams):
    actors = {}; seen = set()
    for row in rows:
        side, slot = row['side_index'], row['stored_player_slot']
        if type(side) is not int or side not in (0, 1) or type(slot) is not int or not 0 <= slot <= 255:
            raise ValueError('Invalid stored actor side or slot')
        identity = side, slot
        if identity in seen:
            raise ValueError('Ambiguous stored actor slot')
        seen.add(identity)
        expected = teams[side]
        if (row.get('team_index_word') != expected['team_index']
                or row.get('canonical_team_id') != expected['team_identity_word']):
            continue
        actors[identity] = {'person_index_word': row['person_index_word'],
                            'canonical_person_id': row.get('canonical_person_id'),
                            'person_name': row.get('person_name'),
                            'identity_state': row.get('identity_state', 'unresolved'),
                            'canonical_team_id': row.get('canonical_team_id'),
                            'team_index_word': row.get('team_index_word')}
    return actors


def _actor_rows(record, reused):
    if reused is not None:
        return [r for r in reused.get('retained_players', []) if r.get('native_match_key', r.get('fixture_key')) == record['key']]
    if not record.get('identities'):
        return []
    from .live_match_players import decode_retained_players
    from .live_match_identities import join
    return join(decode_retained_players(record['raw'], record['key']), record['identities'])


def capture_retained_shot_maps(bridge, session_id, fixture_refs, *, fixture_captures=None, coach_index=None, include_source_observed=False, projection='legacy_reconciled'):
    """Capture1..64 selected fixtures, optionally reusing one epoch-stamped private packet."""
    if (not isinstance(fixture_refs, (list, tuple)) or not 1 <= len(fixture_refs) <= 64
            or any(not isinstance(r, str) or not r for r in fixture_refs)
            or len(set(fixture_refs)) != len(fixture_refs)):
        raise ValueError('Select1–64 distinct live fixture references')
    if coach_index is not None and (type(coach_index) is not int or not 0 <= coach_index < 64):
        raise ValueError('Invalid active coach index')
    if type(include_source_observed) is not bool:
        raise ValueError('include_source_observed must be a boolean')
    if projection not in ('legacy_reconciled', 'source_proven'):
        raise ValueError('Unsupported retained shot projection')
    native_projection = projection == 'source_proven'
    if native_projection and include_source_observed:
        raise ValueError('source_proven uses one attempts collection; include_source_observed is legacy-only')
    primary = 'attempts' if native_projection else 'shots'
    epoch = capture_epoch(bridge, session_id)
    if fixture_captures is not None and fixture_captures.get('_live_capture_epoch') != epoch:
        raise ValueError('Reused fixture capture is unstamped or belongs to another native load epoch')
    observed_first = bridge.get_save(session_id)['save']
    if fixture_captures is None:
        backing = read_selected_matches(bridge, session_id, list(fixture_refs), include_players=True)
        records = backing['records']
    else:
        if fixture_captures.get('_live_capture_epoch') != epoch:
            raise ValueError('Reused fixture capture is unstamped or belongs to another native load epoch')
        items = fixture_captures.get('capture', {}).get('fixtures', [])
        if {i['fixture'].get('fixture_ref') for i in items} != set(fixture_refs) or len(items) != len(fixture_refs):
            raise ValueError('Reused fixture capture scope differs')
        raw_list = fixture_captures.get('raw_frames', [])
        raw_rows = {r['fixture_ref']: r for r in raw_list}
        if len(raw_rows) != len(raw_list):
            raise ValueError('Reused fixture raw references are ambiguous')
        records = []
        for item in items:
            fixture = item['fixture']; ref = fixture['fixture_ref']; raw = raw_rows.get(ref)
            if raw is not None:
                if raw.get('key') != item['native_match_key']:
                    raise ValueError('Reused fixture raw key differs')
                if not isinstance(raw.get('raw'), bytes) or hashlib.sha256(raw['raw']).hexdigest() != raw.get('raw_sha256'):
                    raise ValueError('Reused fixture raw byte hash differs')
            records.append(dict(fixture_ref=ref, fixture_native=fixture, key=item['native_match_key'],
                                state=raw.get('state', 'available') if raw else (item.get('source') or {}).get('state', 'unavailable_backing'),
                                raw=raw.get('raw') if raw else None))
    if len(records) != len(fixture_refs) or {r['fixture_ref'] for r in records} != set(fixture_refs):
        raise ValueError('Live backing did not preserve every selected fixture')
    output = []
    for record in records:
        fixture = record['fixture_native']; key = record['key']; ref = record['fixture_ref']
        base = {'source_kind': 'active_human_retained_cbe', 'fixture_ref': ref, 'fixture': fixture,
                'native_match_key': key, 'saved_file_fallback': False,
                'observed_save_first': observed_first,
                'coordinate_policy': 'Raw native X/Y; units, metric distances and human viewpoint remain unresolved. Native attacked-goal direction and official location bins are separately verified.',
                'shot_quality_policy': 'Native per-attempt xG; own-goal markers are separate, not statistical attempts.',
                'body_part_policy': 'Official WithHeadShotType/WithFeetShotType native groups; other types remain unclassified. Header counts are shots, not aerial duels.',
                'outcome_policy': outcome_policy(),
                'reconciliation_policy': {'shot_count': 'exact', 'shots_on_target': 'exact native goal/saved category sum',
                                          'expected_goals_max_float32_ulps': 1, 'own_goal_markers_are_statistical_shots': False},
                'atomic': False}
        if native_projection:
            from .retained_shot_values import value_definition
            base.update(projection='source_proven', projection_version=1,
                native_xg_value_definition=value_definition(),
                shot_quality_policy='Source-proven native UI XgValue per attempt; independent credited aggregate xG is separate.',
                reconciliation_policy={'shot_count': 'exact independent counter closure; partial valid rows remain explicit',
                    'shots_on_target': 'exact native goal/saved category sum',
                    'native_xg_value': 'native source and field validity; no aggregate-conservation admission',
                    'legacy_aggregate_comparison_max_float32_ulps': 1,
                    'own_goal_markers_are_statistical_shots': False})
        if record['state'] != 'available':
            output.append(dict(base, state='unavailable_team_oracle', unavailable_reason=record['state'],
                               **{primary: []}, own_goal_markers=[], side_coverage=_empty_sides(fixture, 'unavailable_team_oracle')))
            continue
        team = decode_team_totals(record['raw'])
        if team['result_key'] != key:
            raise ValueError('Team oracle inner key differs')
        _validate_team_oracle(fixture, team['teams'])
        source_options = {'verify_xg_value': True} if native_projection else {}
        source = capture_source(bridge, session_id, ref, key, fixture, coach_index, **source_options)
        if source['state'] != 'available':
            output.append(dict(base, **source, **{primary: []}, own_goal_markers=[], side_coverage=_empty_sides(fixture, source['state'])))
            continue
        if native_projection:
            from .retained_shot_source_projection import project_source_attempts
            result = project_source_attempts(source['vectors'], source['events'], team['teams'],
                                             pitch_geometry=source.get('pitch_geometry'))
        else:
            result = decode_attempts(source['vectors'], source['events'], team['teams'],
                                     pitch_geometry=source.get('pitch_geometry'), _retain_candidates=include_source_observed)
        candidates = result.pop('_candidates_by_side', {})
        result.pop('_marker_candidates_by_side', None)
        actor_rows = _actor_rows(record, fixture_captures)
        if native_projection:
            from .retained_shot_source_projection import source_actor_bindings
            actors, actor_errors = source_actor_bindings(actor_rows, team['teams'])
            result['actor_binding_errors'] = actor_errors
        else:
            actors = _validated_actors(actor_rows, team['teams'])
        if include_source_observed:
            from .live_match_players import decode_retained_players
            from .retained_shot_observations import verify_observed_side
            roster = decode_retained_players(record['raw'], key)
            observed = []; observed_coverage = []
            for diagnostic in result['side_coverage']:
                if diagnostic['state'] == 'available':
                    continue
                side = diagnostic['side_index']
                rows, coverage = verify_observed_side(candidates.get(side, []), roster, actors,
                                                     team['teams'][side], diagnostic)
                observed.extend(rows); observed_coverage.append(coverage)
            result['source_observed_shots'] = observed
            result['source_observed_coverage'] = observed_coverage
            result['source_observed_policy'] = 'Opt-in separate collection. Counts/actors independently verified; native xG values are observed, NOT aggregate-reconciled. Verified rows/totals/ranks and1ULP policy unchanged.'
        for row in result[primary] + result['own_goal_markers']:
            row['actor'] = actors.get((row['event_side_index'], row['stored_player_slot']))
            row['actor_identity_state'] = row['actor']['identity_state'] if row['actor'] else 'unresolved_actor_or_team_binding'
        digest = hashlib.sha256(repr(epoch).encode()+struct.pack('<i', key)
                                + json.dumps(_fixture_signature(fixture), sort_keys=True).encode()
                                + hashlib.sha256(record['raw']).digest()+source['events']+b''.join(source['vectors'])
                                + source.get('pitch_geometry_raw', b'')
                                + json.dumps(sorted((list(k), v) for k, v in actors.items()), sort_keys=True).encode()).hexdigest()
        source_identity = {'source_id': digest}
        if native_projection:
            source_identity = {'native_source_id': digest,
                'source_id': hashlib.sha256(b'source_proven:v1\0' + bytes.fromhex(digest)
                    + (json.dumps(actor_errors, sort_keys=True).encode() if actor_errors else b'')).hexdigest()}
        output.append(dict(base, **result, **source_identity, pitch_geometry=source.get('pitch_geometry'),
                           location_provenance=location_field_registry(),
                           coach_index=source['coach_index'],
                           coach_name=source['coach_name'], owner_team_native_id=source['owner_team_native_id'],
                           unknown_fields=['clock_units', 'normalized_coordinates'] + (['outcome_for_unmapped_native_categories'] if any(row['outcome'] is None for row in result[primary]) else [])))
    if capture_epoch(bridge, session_id) != epoch:
        raise ValueError('Career/load epoch changed during retained shot capture')
    observed_last = bridge.get_save(session_id)['save']
    if capture_epoch(bridge, session_id) != epoch:
        raise ValueError('Career/load epoch changed before retained shot publication')
    for packet in output:
        packet['observed_save_last'] = observed_last
        packet['observed_at'] = datetime.now(timezone.utc).isoformat()
    return {'records': output, 'source_kind': 'active_human_retained_cbe', 'saved_file_fallback': False}


def get_retained_shot_map(bridge, session_id, fixture_ref, coach_index=None,
                          offset=0, limit=100, expected_source_id=None, include_source_observed=False,
                          projection='legacy_reconciled'):
    if type(offset) is not int or not 0 <= offset <= MAX_SHOTS_PER_SIDE*2:
        raise ValueError('Invalid shot page offset')
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Shot page limit must be1–100')
    if offset and expected_source_id is None:
        raise ValueError('Continuation requires expected_source_id')
    if projection not in ('legacy_reconciled', 'source_proven'):
        raise ValueError('Unsupported retained shot projection')
    if projection == 'source_proven' and include_source_observed:
        raise ValueError('source_proven uses one attempts collection; include_source_observed is legacy-only')
    options = {'projection': projection} if projection == 'source_proven' else {}
    result, = capture_retained_shot_maps(bridge, session_id, [fixture_ref], coach_index=coach_index,
        include_source_observed=include_source_observed, **options)['records']
    if expected_source_id is not None and expected_source_id != result.get('source_id'):
        raise ValueError('Retained shot source changed; restart paging')
    primary = 'attempts' if projection == 'source_proven' else 'shots'
    rows = result.pop(primary); end = min(offset+limit, len(rows))
    markers = result.pop('own_goal_markers')
    if include_source_observed:
        observed = result.pop('source_observed_shots', [])
        result['source_observed_shots'] = observed[:100]
        result['total_source_observed_shots'] = len(observed)
        result['source_observed_shots_truncated'] = len(observed) > 100
    page = {primary: rows[offset:end],
            ('total_available_attempts' if projection == 'source_proven' else 'total_available_shots'): len(rows)}
    return dict(result, **page,
                own_goal_markers=markers[:100], total_own_goal_markers=len(markers),
                own_goal_markers_truncated=len(markers) > 100,
                next_offset=end if end < len(rows) else None)


NATIVE_SPANS = (
    (0x12ffbf8, bytes.fromhex('6a0040b908ac58a9497d10531f010beb400400544c3d00125f040031200200540d0140f9ae1140b9df01016bc411427a01010054ae094079ce010c4adf21007281000054ae0d4079df01096bc00c0054082100911f010beb41feff540f0000140d0140f9ae1140b9df01016b01010054ae094079ce010c4adf21007281000054ae0d4079df01096be00a0054082100911f010beb61feff54082c5aa91f010beb400400544c3d00125f040031200200540d0140f9ae1140b9df01016bc411427a01010054ae094079ce010c4adf21007281000054ae0d4079df01096ba0080054082100911f010beb41feff540f0000140d0140f9ae1140b9df01016b01010054ae094079ce010c4adf21007281000054ae0d4079df01096bc0060054082100911f010beb61feff54082c57a91f010beb800200544c3d00125f0400310d0140f9ae1140b9c011427aef179f1adf01016be019407a00010054ae094079ce010c4adf21007281000054ae0d4079df01096b60040054082100911f010bebe1fdff5408ac5ba91f010beb800200544a3d00125f0400310c0140f98d1140b9a011427aee179f1abf01016bc019407a000100548d094079ad010a4abf210072810000548d0d4079bf01096b00020054082100911f010bebe1fdff54080080d2e00308aac0035fd6a80540f9a8ffffb5abffff17a80540f948ffffb5ccffff17a80540f9e8feffb5dfffff17880540f9f4ffff17')),
    (0x1f8088, bytes.fromhex('e8e68a5208a9a872bf02086bc1530154e00316aa214c8a52a1c9a8723e020895b6320895f40300aad9ff079520c40137e00314aa816c8852c10cae720b020895f60300aae0030791e10314aae20316aaf416009476000037e81f41f9288d01b4e00315aa6f170094e8ef40f9a88c01b408cd208b140540f9548c01b4e8ab4e391f01206bf5079f1af60300aae0e30191ab17009428008052e8cf0239f7030791ff030039e8430191e0420391e1030791e3e30191e20316aae40314aa0500805206008052e70315aaddadfe97a08303d1')),
    (0x1f7aa8, bytes.fromhex('a8098d526866ad72bf02086b202f0054')),
    (0x1a3990, bytes.fromhex('88c7228be28709a9293c40f908f17dd32a01088b0800088bff331039cbda62f8088100913f0100f1e05700f917018a9a7a814539e00317aa115e1e950840201ee20e40a9f75740f9f5b30e91a00302d1')),
    (0x4895390, bytes.fromhex('08a440a91f0109ebc00000540a2d40b95f01016b6000005408e10091faffff171f0109ebe003889ac0035fd6')),
    (0x1a36b8, bytes.fromhex('a02240bd010540bd0028211e000500bdb5c20091bf0214ebe00e0054a8b28039e96a683829050011e96a2838a12640b9e00313aa29c71b95c00000b408600091081c40bd096040793821085305000014a8420091a81640bd0821201ef8d79f1a090140bde00313aa2041201e0141201ee10318aae7c81b95')),
    (0x4895ac8, bytes.fromhex('00c0201ee85700d0021d45bd0020221e4101003445020054000441bde85700d0021945bd0228221e0020211e40c4211e650100540c00001425010054000441bde85700d0022145bd4238201e0040211e0020211e4444211e6c00005400008052c0035fd620008052c0035fd6')),
    (0x493b20c, bytes.fromhex('082440a900e4002f1f0109eba0000054012140bd0028211e08c10091fbffff17c0035fd6')),
    (0x48954a0, bytes.fromhex('2aa940390880009129a180395fc50071200600540a038052202c40bd20212a9b28d04039e20300b9ff7f01a9e02300bde28f0429e8b30039')),
    (0x4895224, bytes.fromhex('6aa940392b0080526b01084b5fc500716801881a081d40930a03805200012a9b')),
    (0x1a221c, bytes.fromhex('08a840391f050071e1179f1a1fc50071f8179f1a29000014')),
    (0x1a22f8, bytes.fromhex('e0230091e10318aae3860995e0630091e223009101a78c52e1ecad72f4530995')),
    (0x1a47bc, bytes.fromhex('a00641bd0028201ee0c30191f07d0995a00241bd0028201ee0830191ec7d0995')),
    (0x489b1b0, bytes.fromhex('28008052e8a30039ff1b00f9e15100f021280e91a0a20091020080124bb7eb97b6c2009148008052e8e30039ff2300f9e15100f0217c0e91a0e200910200801242b7eb97f5230091b702019168008052e8230139ff2b00f9e15100f021e80e91a02201910200801238b7eb97b842019188008052e8630139ff3300f9e15100f021500f91a0620191020080122fb7eb97e823009115810191a9008052e9a30139ff3b00f9e15100f0219c0f9100a101910200801225b7eb97')),
)

# Official NonPenaltyExpectedGoals key0x644e524f and native penalty-type exclusion.
NATIVE_SPANS += (
    (0x48954c0, bytes.fromhex('28d04039')),
    (0x48954d4, bytes.fromhex('e8b30039')),
    (0x493eb08, bytes.fromhex('c8d24039')),
    (0x493eb0c, bytes.fromhex('1f110071')),
    (0x493eb10, bytes.fromhex('80000054')),
    (0x493eb14, bytes.fromhex('e12240bd')),
    (0x493eb18, bytes.fromhex('0128211e')),
    (0x493eb1c, bytes.fromhex('e12200bd')),
    (0x205694, bytes.fromhex('e02240bd')),
    (0x2056a8, bytes.fromhex('e1498a52')),
    (0x2056ac, bytes.fromhex('c189ac72')),
    (0x2056b0, bytes.fromhex('0dc70795')),
    (0x266f98, bytes.fromhex('002040bd')),
    (0x4ad2f10, bytes.fromhex('c1820091')),
    (0x4ad2f14, bytes.fromhex('6e06e297')),
)

# Official WithHeadShotType/WithFeetShotType raw-type counts and output binding.
NATIVE_SPANS += (
    (0x1a39dc, bytes.fromhex('a00302d1e1b30e91e40317aa21ffff97')),
    (0x1a3b70, bytes.fromhex('a9035838a8135838e8a70e29b5235838a9335838a8435838e8a70f29a9535838aa635838ab735838a8835838e8a70c29a8935838e8ab0b29a8a35838e8af0d29')),
    (0x1a3c00, bytes.fromhex('f55b00b9')),
    (0x1a3f20, bytes.fromhex('e9a34f293901080be0e30591211f0012f17f0995e9a34e290801090be96b40b9eaaf4b2929010b0b0801090be96740b929010a0b1501090be85b40b9e9ab4d294801080b3701080be81e00120801390be0a305910101150bd27f0995')),
    (0x1a3fe8, bytes.fromhex('e0030391e10315aab47f0995f3c30291e0c30291e11e0012bd7f0995e8030391e84f04a9e8430391e9a30391e92303a9e8e30391e9430491ea830491ebc30491ec030591e92302a9e8430591e0430891e1030791eb2b01a9e83300a9e2c30691e3a30691e4630691e5230691e6e30591e7a30591d7290094')),
    (0x1ae7b8, bytes.fromhex('ff8301d1fa6701a9f85f02a9f65703a9f44f04a9fd7b05a9fd430191f40307aa')),
    (0x1ae97c, bytes.fromhex('b42b40f9e00300918b540995e00313aaa10e8952814dab72e20314aa53220995a22f40f9e00313aa214c8952c14aae724e220995')),
)
