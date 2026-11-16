"""Native renderer's named shot-origin bins; raw units are intentionally unnamed."""
import math
import struct

LOCATION_NAMES = (
    'LocationSixYardBox', 'LocationPenaltyBoxNearSpot',
    'LocationPenaltyBoxLeftCorner', 'LocationPenaltyBoxRightCorner',
    'LocationPenaltyBoxLeftClose', 'LocationPenaltyBoxRightClose',
    'LocationOutsideBoxLeftCornerFlag', 'LocationOutsideBoxRightCornerFlag',
    'LocationOutsideBoxWideLeft', 'LocationOutsideBoxWideRight',
    'LocationOutsideBoxLeftCentral', 'LocationOutsideBoxRightCentral',
    'LocationOutsideBoxFarFromGoal',
)


def _f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def classify_location(x, y, attacked_goal_positive_y, half_length):
    """Project finite source float32 values using the renderer's strict boundaries.

    Left/right are official native labels. They do not establish a viewer's
    left/right. Bin12 is the renderer fallback, including exact boundary gaps.
    """
    if type(attacked_goal_positive_y) is not bool:
        raise ValueError('Attacked goal direction must be a known boolean')
    if any(type(v) not in (float, int) or not math.isfinite(v) for v in (x, y, half_length)) or half_length <= 0:
        raise ValueError('Finite native coordinates and positive pitch half-length required')
    try:
        x, y, length = map(_f32, (x, y, half_length))
    except (OverflowError, struct.error) as exc:
        raise ValueError('Native float32 coordinate range exceeded') from exc
    # Negation is exact float32. Compare source Y against separately rounded
    # native thresholds rather than subtracting a rounded distance from goal.
    forward_y = y if attacked_goal_positive_y else -y
    lateral = x if attacked_goal_positive_y else -x
    six = _f32(length + _f32(-5.4864))
    box = _f32(length + _f32(-16.459))
    far = _f32(length + _f32(-32.918))
    inner = _f32(9.144)
    outer = _f32(20.1168)
    ax = abs(x)
    index = 12
    if ax < inner and six < forward_y < length:
        index = 0
    elif ax < inner and box < forward_y < length:
        index = 1
    elif inner < ax < outer and box < forward_y < length:
        index = (2 if lateral < 0 else 3) if forward_y < six else (4 if lateral < 0 else 5)
    elif ax > outer and forward_y >= box:
        index = 6 if lateral < 0 else 7
    elif far <= forward_y < box:
        if lateral < -outer:
            index = 8
        elif lateral > outer:
            index = 9
        elif -outer <= lateral < 0:
            index = 10
        elif 0 < lateral <= outer:
            index = 11
    return {'native_location_bin': index, 'official_location': LOCATION_NAMES[index],
            'location_group': ('inside_area' if index < 6 else
                               'outside_area' if index < 12 else
                               'outside_area_or_native_fallback'),
            'location_state': 'native_renderer_predicate',
            'attacked_goal_positive_native_y': attacked_goal_positive_y,
            'coordinate_units': None, 'coordinate_viewpoint': None,
            'distance_to_goal': None}


def location_field_registry():
    return {
        'native_location_bin': {'source': 'native renderer1A366C predicate priority',
                                'predicates_rva': '0x4895ac8..0x48963dc',
                                'range': [0, 12]},
        'official_location': {'source': 'ordered property-key table0x52e0c5c and managed registrations',
                              'values': list(LOCATION_NAMES)},
        'direction': {'source': 'linked CBE event+0x30 bit8',
                      'meaning': 'attacked goal is positive native Y when set'},
        'pitch_geometry': {'source': 'CBE+0x100/+0x104 float32 half-width/half-length',
                           'renderer_rva': '0x1a47bc'},
        'limits': ['Native left/right labels do not establish human viewpoint.',
                   'Coordinate units and metric distance remain unavailable.',
                   'Bin12 is native fallback, including exact boundary gaps.',
                   'Own-goal markers are not statistical shots and receive no location class.'],
    }
