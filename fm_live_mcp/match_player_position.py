"""The stored Position property on a boundary-checked retained player record."""
import struct

from .prepared_tactics_fields import POSITION_NAMES


def read_position(child: bytes, person_reference_bytes: int) -> dict:
    if person_reference_bytes not in (4, 8) or len(child) < person_reference_bytes + 13:
        raise ValueError('Incomplete retained player position')
    # After the person reference, two status bytes and the first POSITION,
    # the second POSITION consists of a version byte followed by its mask.
    offset = person_reference_bytes + 8
    if child[offset] != 2:
        return {'stored_match_position_mask': None, 'stored_match_position': None,
                'stored_match_position_state': 'unsupported_position_encoding'}
    mask = struct.unpack_from('<I', child, offset + 1)[0]
    label = POSITION_NAMES.get(mask)
    state = 'named' if label is not None else 'unmapped_mask'
    if mask == 0:
        state = 'zero_mask'
    return {'stored_match_position_mask': mask, 'stored_match_position': label,
            'stored_match_position_state': state}


def field_registry() -> dict:
    position = {
        'frontend_label': 'Position', 'property_key': '0x506f7369',
        'native_property_getter_rva': '0x266e60', 'native_member': 'MATCH_STATS_INPUT+0x70',
        'wire_reader_rva': '0x4ad29d0', 'wire_offset_u32_person': 13, 'wire_offset_u64_person': 17,
        'scope': 'Stored match-row position. Check participation separately. Players with positive minutes may have a zero mask. Timing within the match, minutes at position, phase and positions of individual actions are unresolved.',
    }
    return {field: position for field in ('stored_match_position', 'stored_match_position_mask', 'stored_match_position_state')}
