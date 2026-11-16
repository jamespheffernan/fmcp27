"""Checked native goal-end area rectangles for one exact playback frame.

This combines orientation and pitch geometry only. It does not classify player
participation or count box support. The original strip and pitch intersection
retain separate boundary policies, including the native strip's missing cap.
"""
from . import frame_attacked_goal_basis as goals
from . import frame_native_pitch_bounds as pitch
from . import native_penalty_geometry as geometry


def capture(read, base, bound, *, fixed_tick):
    geometry.verify_native(read, base)
    return {'_goal': goals.capture(read, base, bound, fixed_tick=fixed_tick),
        '_pitch': pitch.capture(read, base, bound, fixed_tick=fixed_tick)}


def verify_capture(read, base, captured, bound):
    goal = goals.verify_capture(read, base, captured['_goal'], bound)
    bounds = pitch.verify_capture(read, base, captured['_pitch'], bound)
    geometry.verify_native(read, base)
    return {'_goal': goal, '_pitch': bounds, 'same_session_exact_frame_goal_area_reselected': True}


def _rectangle(positive, half_width, half_length):
    area = geometry.classify(0, 0, selected_goal_positive_y=positive,
        half_width=half_width, half_length=half_length)
    lateral = area['native_lateral_strict_limits'][1]
    forward_floor = max(0.0, area['native_forward_strict_threshold'])
    return {'x_min': max(-half_width, -lateral), 'x_max': min(half_width, lateral),
        'x_min_inclusive': half_width < lateral, 'x_max_inclusive': half_width < lateral,
        'y_min': forward_floor if positive else -half_length,
        'y_max': half_length if positive else -forward_floor,
        'y_min_inclusive': not positive, 'y_max_inclusive': positive}


def project(verified):
    if verified.get('same_session_exact_frame_goal_area_reselected') is not True:
        raise ValueError('Final exact-frame native goal-area verification required')
    goal = goals.project(verified['_goal'])
    bounds = pitch.project(verified['_pitch'])
    if goal['frame_tick'] != bounds['frame_tick']:
        raise ValueError('Native goal area belongs to different playback frames')
    common = {'frame_tick': goal['frame_tick'], 'native_period_code': goal['native_period_code'],
        'attacked_goal_basis_state': goal['state'], 'native_pitch_geometry_state': bounds['state'],
        'native_xy_bounds': bounds['native_xy_bounds'], 'teams': None,
        'physical_units': None, 'active_participation_verified': False,
        'penalty_area_occupation': None, 'sustained_box_support': None,
        'same_session_exact_frame_goal_area_reselected': True,
        'observed_cursor': goal['observed_cursor'], 'verification_cursor': goal['verification_cursor']}
    if goal['state'] != 'available_native_attacked_goal_basis' or bounds['state'] != 'available_native_xy_pitch_geometry':
        return common | {'state': 'unavailable_native_attacked_goal_area'}
    half_width, half_length = bounds['native_xy_bounds']['x_max'], bounds['native_xy_bounds']['y_max']
    teams = []
    for side in goal['teams']:
        positive = side['attacked_end_positive_native_y']
        area = geometry.classify(0, 0, selected_goal_positive_y=positive,
            half_width=half_width, half_length=half_length)
        teams.append({'side_index': side['side_index'],
            'attacked_end_positive_native_y': positive,
            'native_goal_centre_xyz': [0.0, half_length if positive else -half_length, 0.0],
            'native_goal_end_strip': {
                'x_strict_limits': area['native_lateral_strict_limits'],
                'goalward_y_sign': 1 if positive else -1,
                'goalward_y_strict_lower_limits': [0.0, area['native_forward_strict_threshold']],
                'goal_line_cap_in_native_predicate': False},
            'native_pitch_intersection_rectangle': _rectangle(positive, half_width, half_length)})
    return common | {'state': 'available_native_attacked_goal_area', 'teams': teams,
        'interpretation': 'Native selected-goal-end geometry at this exact frame. '
            'The unbounded native strip is separate from its pitch-bounds intersection. '
            'Coordinate membership does not establish active playing membership or sustained box support.'}
