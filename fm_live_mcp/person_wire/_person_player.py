"""Partial regular ACTUAL_PLAYER body wire, source3754/minor9 only.

Input starts at CFD388's first player body byte, after the PERSON factory tag.
This is not a complete PERSON decoder and never reports a physical file cursor
as a real player without an owning table traversal. The 10FF49C word width must
be supplied from a separately proved loader context.
"""
import struct

class Reader:

    def __init__(self, data, start):
        if not isinstance(data, (bytes, bytearray, memoryview)) or type(start) is not int or (not 0 <= start <= len(data)):
            raise ValueError('Invalid player body source cursor')
        self.data, self.offset = (data, start)
        self.chunks = []

    def chunk(self, target, size, *, meaning='unmapped_native_field'):
        if size < 0 or size > len(self.data) - self.offset:
            raise ValueError('Truncated initial ACTUAL_PLAYER body')
        at = self.offset
        raw = bytes(self.data[at:at + size])
        self.offset += size
        self.chunks.append({'source_offset': at, 'size': size, 'native_player_offset': hex(target), 'raw_hex': raw.hex(), 'meaning': meaning})
        return raw

def context(source_major, minor, body_mode):
    if type(source_major) is not int or type(minor) is not int or type(body_mode) is not int or ((source_major, minor, body_mode) != (3754, 9, 1)):
        raise ValueError('Unsupported ACTUAL_PLAYER body context')

def _fixed_prefix(reader):
    raw = reader.chunk(598, 10, meaning='includes_signed_CA_and_PA')
    current, potential = struct.unpack_from('<hh', raw, 6)
    reader.chunk(621, 1)
    reader.chunk(616, 5)
    reader.chunk(622, 2)
    reader.chunk(288, 4, meaning='native_u32_zero_extended_from_stack')
    return {'current_ability_native_signed16': current, 'potential_ability_native_signed16': potential}

def parse_fixed_prefix(data, start, *, source_major=3754, minor=9, body_mode=1):
    context(source_major, minor, body_mode)
    reader = Reader(data, start)
    ability = _fixed_prefix(reader)
    return {'start': start, 'end': reader.offset, 'consumed_bytes': reader.offset - start, 'native_chunks': reader.chunks, 'ability_inputs': ability, 'complete_player_body': False, 'complete_person': False, 'next_reader': '0x10ff49c', 'next_native_player_offset': '0x128', 'next_width_state': 'requires_proved_global_context_4_or_8_bytes'}

def parse_initial(data, start, *, reference_word_bytes, source_major=3754, minor=9, body_mode=1):
    context(source_major, minor, body_mode)
    if type(reference_word_bytes) is not int or reference_word_bytes not in (4, 8):
        raise ValueError('10FF49C requires an explicit proved4-or8-byte transport width')
    reader = Reader(data, start)
    ability = _fixed_prefix(reader)
    reader.chunk(296, reference_word_bytes, meaning='10ff49c_raw_stored_word_no_reference_resolution')
    attributes_at = reader.offset
    inputs = reader.chunk(328, 69, meaning='stored_attribute_and_position_input_bytes')
    for target, size in ((556, 4), (612, 1), (584, 14), (554, 2), (608, 2), (614, 2), (610, 2)):
        raw = reader.chunk(target, size)
        if target == 610:
            effective_262 = [raw[0] or ability['current_ability_native_signed16'] & 255, raw[1] or ability['potential_ability_native_signed16'] & 255]
    return {'start': start, 'end': reader.offset, 'consumed_bytes': reader.offset - start, 'reference_word_bytes': reference_word_bytes, 'native_chunks': reader.chunks, 'ability_inputs': ability, 'attribute_inputs': {'source_offset': attributes_at, 'native_player_offset': '0x148', 'size': 69, 'raw_hex': inputs.hex(), 'unsigned_bytes': list(inputs), 'goalkeeper_position_native_signed8': struct.unpack_from('<b', inputs, 0)[0], 'defender_left_position_native_signed8': struct.unpack_from('<b', inputs, 2)[0], 'decoded_technical_mental_physical_ratings': None, 'scale_state': 'unavailable_until_later_stored_player_0x270_bit7_consumed'}, 'effective_unmapped_0x262_0x263_after_native_zero_fallback': effective_262, 'complete_player_body': False, 'complete_person': False, 'next_reader': '0x1526598', 'next_native_player_offset': '0x226'}
