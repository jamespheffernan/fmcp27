"""Decode FM27 v68 position records; caller supplies verified first boundary.

Wire structure follows 4ADE568/4ADE64C; paired phase order follows 4A8D834.
No formation, defaults, player overrides, or general writable roles are inferred.
"""
import struct
from fm_live_mcp.prepared_tactics_fields import POSITION_NAMES
from fm_live_mcp.prepared_tactic_roles import decode_word


def decode_position_records(raw, first_record_offset):
    if type(first_record_offset) is not int or first_record_offset < 0:
        raise ValueError('Invalid first record boundary')
    at = first_record_offset
    phases = {'in_possession': [], 'out_of_possession': []}
    def need(offset, size):
        if offset < 0 or offset + size > len(raw):
            raise ValueError('Truncated native position record')
    for slot in range(11):
        for phase in phases:
            start = at
            need(at, 14)
            if raw[at:at+3] != b'\x44\x00\x02' or raw[at+8] != 1:
                raise ValueError('Unsupported native position record version')
            position = struct.unpack_from('<I', raw, at+3)[0]
            count = struct.unpack_from('<I', raw, at+10)[0]
            instruction_vector_offset = at + 14
            at += 14 + 24 * count
            need(at, 4)
            second = struct.unpack_from('<I', raw, at)[0]
            at += 4 + 12 * second
            need(at, 8)
            word = struct.unpack_from('<Q', raw, at)[0]
            role_word_offset = at
            at += 8
            phases[phase].append({
                'position_index': slot, 'position_mask': position,
                'position_name': POSITION_NAMES.get(position),
                'native_role_word': f'{word:016x}',
                'role': decode_word(word, phase),
                'record_offset': start, 'record_end_exclusive': at,
                'role_word_offset': role_word_offset,
                'instruction_vector_offset': instruction_vector_offset,
                'instruction_entry_count': count,
            })
        need(at, 1)
        at += 1  # parent creator byte after each IP/OOP pair
    return {'phases': phases, 'records_end_exclusive': at,
            'formation': None, 'effective_player_overrides': None}
