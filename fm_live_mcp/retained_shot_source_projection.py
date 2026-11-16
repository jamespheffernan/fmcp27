"""Source-proven attempt fields; native XgValue is distinct from credited xG."""
from collections import Counter, defaultdict
import hashlib
import math
import struct

from .retained_shot_location import classify_location
from .retained_shot_outcomes import outcome_fields, outcome_counts
from .retained_shot_values import value_definition


def project_source_attempts(shot_vectors, event_bytes, teams, *, pitch_geometry=None):
    from .live_retained_shots import MAX_EVENTS, MAX_SHOTS_PER_SIDE, _body_part, _f32, _ulp_distance
    if (len(shot_vectors) != 2 or len(teams) != 2 or not isinstance(event_bytes, bytes)
            or len(event_bytes) % 56 or len(event_bytes) // 56 > MAX_EVENTS):
        raise ValueError('Unsupported source-proven shot/event profile or budget')
    if any(not isinstance(raw, bytes) or len(raw) % 48 or len(raw) // 48 > MAX_SHOTS_PER_SIDE
           for raw in shot_vectors):
        raise ValueError('Unsupported source-proven shot vector width or budget')
    references = Counter(struct.unpack_from('<I', raw, at + 36)[0]
                         for raw in shot_vectors for at in range(0, len(raw), 48))
    events = defaultdict(list)
    for at in range(0, len(event_bytes), 56):
        event = event_bytes[at:at + 56]
        events[struct.unpack_from('<I', event, 44)[0]].append(event)
    attempts, markers, coverage = [], [], []
    for side, (raw, team) in enumerate(zip(shot_vectors, teams)):
        rows, own_goals, errors, field_errors = [], [], [], []
        for at in range(0, len(raw), 48):
            record = raw[at:at + 48]
            event_id = struct.unpack_from('<I', record, 36)[0]
            identity = {'record_index': at // 48, 'event_id': event_id,
                        'source_record_sha256': hashlib.sha256(record).hexdigest()}
            value = struct.unpack_from('<f', record, 32)[0]
            value_known = math.isfinite(value) and 0 <= value <= 1
            rejected = dict(identity, stored_native_xg_value=value if value_known else None,
                stored_native_xg_value_state='verified_stored_value_unresolved_event' if value_known else
                'unavailable_invalid_native_value')
            if references[event_id] != 1:
                errors.append(dict(rejected, reason='duplicate_retained_event_reference'))
                continue
            linked = events[event_id]
            if len(linked) != 1:
                errors.append(dict(rejected, reason='missing_or_ambiguous_linked_event'))
                continue
            event = linked[0]
            category, actor_side = event[42], event[40]
            marker = category == 49
            if actor_side != (1 - side if marker else side):
                errors.append(dict(rejected, reason='native_side_link_disagrees'))
                continue
            x, y = struct.unpack_from('<ff', event, 24)
            x_known, y_known = math.isfinite(x), math.isfinite(y)
            field_states = {'native_xg_value': 'not_a_statistical_attempt' if marker else
                            'verified_native_ui_xg_value' if value_known else 'unavailable_invalid_native_value',
                            'native_x': 'verified_native_coordinate' if x_known else 'unavailable_nonfinite_coordinate',
                            'native_y': 'verified_native_coordinate' if y_known else 'unavailable_nonfinite_coordinate'}
            if not marker and not value_known:
                field_errors.append(dict(identity, field='native_xg_value', reason='nonfinite_or_out_of_domain'))
            for name, valid in [('native_x', x_known), ('native_y', y_known)]:
                if not valid:
                    field_errors.append(dict(identity, field=name, reason='nonfinite_coordinate'))
            direction = bool(struct.unpack_from('<H', event, 48)[0] & 256)
            location = {'native_location_bin': None, 'official_location': None, 'location_group': None,
                        'location_state': 'not_a_statistical_attempt' if marker else
                        'unavailable_coordinate' if not (x_known and y_known) else 'unavailable_pitch_geometry',
                        'attacked_goal_positive_native_y': direction, 'distance_to_goal': None}
            if not marker and x_known and y_known and pitch_geometry is not None:
                location = classify_location(x, y, direction, pitch_geometry['half_length_native'])
            row = dict({**identity, **location}, native_x=x if x_known else None, native_y=y if y_known else None,
                       coordinate_units=None, coordinate_viewpoint=None, native_category_code=category,
                       native_shot_type=record[44], event_side_index=actor_side, stored_player_slot=event[39],
                       native_clock_start_raw=struct.unpack_from('<H', event, 34)[0],
                       native_clock_end_raw=struct.unpack_from('<H', event, 50)[0], clock=None,
                       native_xg_value=value if value_known and not marker else None,
                       native_xg_value_state=field_states['native_xg_value'], field_states=field_states,
                       credited_expected_goals_contribution=None,
                       credited_expected_goals_contribution_state='not_a_statistical_attempt' if marker else
                       'not_retained_in_checked_shot_representation')
            if marker:
                own_goals.append(dict(row, kind='own_goal_marker', statistical_shot=False,
                    actor_side_index=actor_side, beneficiary_side_index=side, body_part=None, is_header=None,
                    body_part_state='not_a_statistical_attempt', is_penalty=None, shot_situation=None,
                    shot_situation_state='not_a_statistical_attempt'))
            else:
                body = _body_part(record[44])
                rows.append(dict(row, **outcome_fields(category), side_index=side,
                    body_part=body, is_header=None if body is None else body == 'head',
                    body_part_state='native_shotmap_group_proved' if body else 'native_type_unclassified',
                    is_penalty=record[44] == 4,
                    shot_situation='penalty' if record[44] == 4 else 'non_penalty_unspecified',
                    shot_situation_state='native_penalty_exclusion_proved_other_types_unmapped'))
        target = sum(row['native_category_code'] in (1, 4) for row in rows)
        checks = {'shot_count_matches': type(team.get('shots')) is int and len(rows) == team['shots'],
                  'shots_on_target_matches': type(team.get('shots_on_target')) is int and target == team['shots_on_target']}
        complete = not errors and all(checks.values())
        known = [row['native_xg_value'] for row in rows if row['native_xg_value'] is not None]
        subtotal = 0.
        for value in known:
            subtotal = _f32(subtotal + value)
        all_values = len(known) == len(rows)
        total = subtotal if all_values else None
        official = team.get('expected_goals')
        official_known = type(official) in (int, float) and math.isfinite(official) and official >= 0
        ulps = _ulp_distance(total, official) if total is not None and official_known else None
        bodies = Counter(row['body_part'] or 'unclassified' for row in rows)
        coverage.append({'side_index': side, 'team_index': team.get('team_index'),
            'team_native_id': team.get('team_identity_word'),
            'state': 'available_source_proven_attempts' if complete else 'partial_source_proven_attempts',
            'retained_record_count': len(raw) // 48, 'statistical_shot_count': len(rows),
            'complete_side': complete, 'shot_count': len(rows) if complete else None,
            'shots_on_target': target if complete else None,
            'own_goal_marker_count': len(own_goals) if not errors else None,
            'known_own_goal_marker_count': len(own_goals), 'checks': checks,
            'outcome_counts': outcome_counts(rows), 'outcome_counts_scope': 'source_proven_rows_before_paging',
            'body_part_counts': {name: bodies[name] for name in ('head', 'feet', 'unclassified')},
            'body_part_counts_scope': 'source_proven_rows_before_paging',
            'official_shots': team.get('shots'), 'official_shots_on_target': team.get('shots_on_target'),
            'official_expected_goals': official if official_known else None,
            'official_expected_goals_state': 'independent_native_aggregate' if official_known else 'unavailable',
            'native_xg_values_available': len(known),
            'native_xg_value_coverage': 'complete_for_source_proven_rows' if all_values else 'partial_unavailable_values',
            'native_float32_xg_value_sum': total, 'known_native_float32_xg_value_subtotal': subtotal,
            'native_xg_value_sum_scope': 'source_proven_rows_before_paging; not official aggregate',
            'legacy_aggregate_comparison': {'float32_ulp_distance': ulps, 'max_float32_ulps': 1,
                'within_legacy_guard': ulps <= 1 if ulps is not None else None,
                'comparison_state': 'available' if ulps is not None else 'unavailable',
                'admits_source_proven_value': False, 'compared_quantities_equivalent': False},
            'link_errors': errors, 'field_errors': field_errors})
        attempts.extend(rows)
        markers.extend(own_goals)
    return {'projection': 'source_proven', 'projection_version': 1,
            'state': 'available' if all(row['complete_side'] for row in coverage) else 'available_partial',
            'native_xg_value_definition': value_definition(), 'side_coverage': coverage,
            'attempts': attempts, 'own_goal_markers': markers}


def source_actor_bindings(rows, teams):
    """Qualify identities independently; ambiguous actors do not erase native fields."""
    keys = [(row.get('side_index'), row.get('stored_player_slot')) for row in rows]
    valid_keys = [key for key in keys if type(key[0]) is int and key[0] in (0, 1)
                  and type(key[1]) is int and 0 <= key[1] <= 255]
    key_counts = Counter(valid_keys)
    people = Counter(row.get('canonical_person_id') for row in rows
                     if type(row.get('canonical_person_id')) is int and row['canonical_person_id'] > 0)
    actors, errors = {}, []
    for index, (row, key) in enumerate(zip(rows, keys)):
        if (type(key[0]) is not int or key[0] not in (0, 1)
                or type(key[1]) is not int or not 0 <= key[1] <= 255):
            errors.append({'roster_row_index': index, 'reason': 'invalid_actor_side_or_slot'})
            continue
        side, slot = key
        reason = None
        person = row.get('canonical_person_id')
        if key_counts[key] != 1:
            reason = 'ambiguous_actor_slot'
        elif type(person) is not int or person <= 0 or people[person] != 1:
            reason = 'unresolved_or_ambiguous_canonical_PERSON'
        elif (type(row.get('person_index_word')) is not int or row['person_index_word'] < 0
              or row.get('identity_state') != 'same_snapshot_canonical_PERSON'):
            reason = 'unresolved_canonical_PERSON_membership'
        elif (type(row.get('team_index_word')) is not int or type(row.get('canonical_team_id')) is not int
              or row['team_index_word'] != teams[side]['team_index']
              or row['canonical_team_id'] != teams[side]['team_identity_word']):
            reason = 'actor_TEAM_differs_from_fixture_side'
        if reason:
            errors.append({'roster_row_index': index, 'side_index': side,
                           'stored_player_slot': slot, 'reason': reason})
        else:
            actors[key] = {name: row.get(name) for name in ('person_index_word', 'canonical_person_id',
                'person_name', 'identity_state', 'canonical_team_id', 'team_index_word')}
    return actors, errors
