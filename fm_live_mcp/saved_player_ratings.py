"""Pure projection of the 69 stored PLAYER+148..18C rating bytes.

The caller supplies the separately decoded PLAYER+270 byte. D1414C uses its
bit7; direct position getters use signed bytes and ignore that flag. This
module does not establish a record boundary, identity or archive loader mode.
"""
from .players import ATTRIBUTES
from .player_profile import FEET, GOALKEEPING, HIDDEN, POSITIONS as PROFILE_POSITIONS

BLOCK_SIZE = 69
BLOCK_NATIVE_OFFSET = 0x148
EXTRAS = {
    group: {name: entry[0] - BLOCK_NATIVE_OFFSET for name, entry in fields.items()}
    for group, fields in (
        ('goalkeeping', GOALKEEPING), ('hidden_attributes', HIDDEN), ('feet', FEET)
    )
}
POSITIONS = {name: entry[0] - BLOCK_NATIVE_OFFSET for name, entry in PROFILE_POSITIONS.items()}
_MAPPED_OFFSETS = frozenset(ATTRIBUTES.values()) | frozenset(POSITIONS.values()) | frozenset(
    offset for fields in EXTRAS.values() for offset in fields.values()
)


def _u8(value, label):
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError(f'{label} must be an exact u8')


def signed_byte(raw):
    """Return the signed load used by the pinned native getters."""
    _u8(raw, 'raw byte')
    return raw if raw < 128 else raw - 256


def native_attribute_getter(raw, scale_byte):
    """D1414C result, including inputs outside the supported stored domain."""
    _u8(raw, 'raw byte')
    _u8(scale_byte, 'scale byte')
    signed = signed_byte(raw)
    if not scale_byte & 0x80:
        return signed
    # Native signed division differs for negative inputs, but all such results
    # are clamped to1. Positive inputs round fifths before the1..20 clamp.
    return min(20, max(1, (signed + 2) // 5))


def decode(raw69, scale_byte=None):
    """Return named values, raw bytes and explicit availability for the block.

    Supported stored domains are0..100 with bit7 set and0..20 otherwise.
    Unsupported bytes retain their signed native result without advertising a
    valid rating. Zero is preserved according to the getter, never guessed to
    mean Unknown. Missing scale leaves ratings unavailable and positions usable.
    """
    if not isinstance(raw69, (bytes, bytearray, memoryview)):
        raise ValueError('Expected exactly 69 stored PLAYER+148 bytes')
    raw = bytes(raw69)
    if len(raw) != BLOCK_SIZE:
        raise ValueError('Expected exactly 69 stored PLAYER+148 bytes')
    if scale_byte is not None:
        _u8(scale_byte, 'scale byte')
    fifths = None if scale_byte is None else bool(scale_byte & 0x80)

    def rating(offset):
        value = raw[offset]
        supported = fifths is not None and value <= (100 if fifths else 20)
        getter = None if fifths is None else native_attribute_getter(value, scale_byte)
        return {
            'raw_u8': value, 'raw_signed8': signed_byte(value),
            'native_getter_value': getter, 'value': getter if supported else None,
            'state': ('scale_unavailable' if fifths is None else 'decoded' if supported
                      else 'raw_outside_supported_domain'),
        }

    def position(offset):
        value = raw[offset]
        getter = signed_byte(value)
        return {
            'raw_u8': value, 'native_getter_value': getter,
            'value': getter if value <= 20 else None,
            'state': 'decoded' if value <= 20 else 'raw_outside_supported_domain',
        }

    return {
        'attributes': {name: rating(offset) for name, offset in ATTRIBUTES.items()},
        **{group: {name: rating(offset) for name, offset in fields.items()}
           for group, fields in EXTRAS.items()},
        'positions': {name: position(offset) for name, offset in POSITIONS.items()},
        'raw_hex': raw.hex(), 'stored_scale_byte': scale_byte, 'scale_flag_bit7': fifths,
        'attribute_scale': None if fifths is None else '1-20' if fifths else '0-20',
        'position_scale': '0-20',
        'unmapped_bytes': [
            {'block_offset': offset, 'native_offset': hex(BLOCK_NATIVE_OFFSET + offset),
             'raw_u8': raw[offset]}
            for offset in range(BLOCK_SIZE) if offset not in _MAPPED_OFFSETS
        ],
    }
