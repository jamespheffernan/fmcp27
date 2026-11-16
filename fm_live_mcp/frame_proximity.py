"""Distances between exact endpoint samples in one verified playback world frame."""
import math


def _endpoint(samples, coordinate, width):
    """Keep a unique sample at local parameter 1. No interpolation or time tolerance."""
    matches = [s.get(coordinate) for s in samples if s.get('native_local_time') == 1.0
               and type(s.get('native_local_time')) in (float, int)]
    if len(matches) != 1:
        return None
    point = matches[0]
    if (not isinstance(point, (list, tuple)) or len(point) != width or
            not all(type(v) in (float, int) and math.isfinite(v) for v in point)):
        return None
    return point[:2]


def project_frame_proximity(packet, person_native_id, *, visible_person_ids):
    """Name only allowed actors. Unnamed/hidden actors can still invalidate a nearest claim."""
    if packet.get('same_session_fixed_frame_verified') is not True or packet.get('common_world_xy_verified') is not True:
        return {'state': 'unavailable_frame_or_world_coordinates'}
    if type(person_native_id) is not int or person_native_id <= 0 or person_native_id not in visible_person_ids:
        return {'state': 'unavailable_selected_person'}
    entities = packet['typed_player_entities']
    entity_count = packet['coverage']['typed_player_entities']
    if len(entities) != entity_count or len({e['entity_index'] for e in entities}) != entity_count:
        return {'state': 'unavailable_entity_census'}
    people = [e['canonical_person_id'] for e in entities if e.get('canonical_person_id') is not None]
    if len(people) != len(set(people)):
        return {'state': 'unavailable_duplicate_person'}
    subject = next((e for e in entities if e.get('canonical_person_id') == person_native_id), None)
    if subject is None or subject.get('side_index') not in (0, 1):
        return {'state': 'unavailable_selected_person'}
    point = _endpoint(subject['position_samples'], 'native_xy', 2)
    if point is None:
        return {'state': 'unavailable_selected_endpoint'}
    ball = _endpoint(packet['ball_samples'], 'native_xyz', 3)
    scored = []
    missing = 0
    for entity in entities:
        side = entity.get('side_index')
        if side == subject['side_index']:
            continue
        other = _endpoint(entity['position_samples'], 'native_xy', 2)
        if other is None:
            missing += 1
            continue
        # An unclassified entity is a possible opponent. Its distance must be
        # checked even when the projection is not allowed to reveal its identity.
        person = entity.get('canonical_person_id')
        named_opponent = side in (0, 1) and person in visible_person_ids and person is not None
        scored.append((math.dist(point, other), entity if named_opponent else None))
    observed = [distance for distance, entity in scored if entity is not None]
    nearest_named = min(observed, default=None)
    leaders = [{'person_native_id': entity['canonical_person_id'], 'name': entity['person_name'],
                'team_native_id': entity['team_native_id']} for distance, entity in scored
               if entity is not None and distance == nearest_named]
    if not leaders:
        nearest_state = 'no_named_opponent_at_endpoint'
    elif missing:
        nearest_state = 'unknown_other_endpoint_missing'
    elif any(entity is None and distance <= nearest_named for distance, entity in scored):
        nearest_state = 'unknown_other_entity_as_close_or_closer'
    else:
        nearest_state = 'verified_nearest_opponents_among_typed_frame_players'
    return {'state': 'available', 'frame_tick': packet['frame_tick'], 'native_local_time': 1.0,
            'source_id': packet['source_id'], 'person_native_id': person_native_id,
            'ball_planar_separation_native': math.dist(point, ball) if ball is not None else None,
            'ball_state': 'available' if ball is not None else 'unavailable_unique_ball_endpoint',
            'nearest_opponent_state': nearest_state, 'nearest_named_opponents': leaders,
            'nearest_named_planar_separation_native': nearest_named,
            'typed_player_entity_count': entity_count, 'missing_possible_opponent_endpoints': missing,
            'physical_units': None, 'on_pitch_population_verified': False,
            'interpretation': 'Euclidean separation in the native XY plane at one frame endpoint. The census includes '
            'typed player entities and may include substitutes. Distance alone cannot establish possession, reception or marking.'}
