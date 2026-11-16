"""Stored PLAYER fitness words, with explicit source and refresh qualifications.

CFD388 and CFEFE4 transfer native PLAYER+248..255 as a single fourteen-byte
block in source3754/minor9. Under the caller-proved raw64 prefix transport,
that block starts104 bytes after the PLAYER body begins. Native getters select
signed words at+250/+252/+254. This helper does not establish the owning PERSON
class, identity, physical record start, current injury or medical availability.
"""

import struct

SOURCE_PROFILE = 'source3754_minor9_conditional_raw64_player_body'
_FIELDS = (
    ('match_sharpness', 112, '0x250', 'Pfit', 'native_0_to_10000'),
    ('fatigue', 114, '0x252', 'Pjad', 'native_signed_fatigue_higher_is_more_fatigued'),
    ('condition', 116, '0x254', 'Pcon', 'native_0_to_10000'),
)
MIN_BODY_BYTES = 118


def read_fitness(data, body_start, *, limit, source_major=3754, minor=9,
                 reference_mode='raw64'):
    """Read three bounded words at an independently checked PLAYER body start.

    Zero is a stored value. Negative condition/sharpness and values above10000
    remain raw evidence with an unavailable interpreted value. Fatigue is signed
    and is never clamped or treated as a percentage. The native refresh and the
    injury-dependent Pcon display override are deliberately not executed.
    """
    if (type(source_major) is not int or type(minor) is not int
            or (source_major, minor) != (3754, 9) or reference_mode != 'raw64'):
        raise ValueError('Unsupported saved PLAYER fitness source profile')
    if (type(body_start) is not int or type(limit) is not int
            or not 0 <= body_start <= limit <= len(data)
            or limit - body_start < MIN_BODY_BYTES):
        raise ValueError('Truncated or invalid bounded PLAYER fitness prefix')
    fields = {}
    for name, relative, native, prop, units in _FIELDS:
        offset = body_start + relative
        raw = bytes(data[offset:offset + 2])
        value, = struct.unpack('<h', raw)
        supported = name == 'fatigue' or 0 <= value <= 10000
        fields[name] = {
            'state': 'decoded' if supported else 'outside_verified_value_profile',
            'value': value if supported else None,
            'raw_signed16': value,
            'raw_hex': raw.hex(),
            'source_offset': offset,
            'native_offset': native,
            'native_property': prop,
            'units': units,
        }
    return {
        'state': 'decoded' if all(field['state'] == 'decoded' for field in fields.values()) else 'partial',
        'fields': fields,
        'source_profile': SOURCE_PROFILE,
        'wire_profile_is_conditional': True,
        'native_loader_globals_proved': False,
        'native_refresh_executed': False,
        'availability_assessed': False,
        'scope': 'stored_PLAYER_fitness_words_without_native_refresh_or_injury_display_override',
    }
