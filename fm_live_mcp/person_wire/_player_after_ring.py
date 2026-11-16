"""Bounded modern17F1BB8 wire and immediate regular-player caller seam.

PLAYER+190 is an embedded composite, not an array of native pointers on disk.
This parser retains serialized fields/order, not a reconstructed native heap.
Positive typed values and unproved INDIVIDUAL_TRAINING_INFO stop explicitly.
"""
import struct
MAX_ROWS = 4096
MAX_TEXT_BYTES = 8192

class UnsupportedChild(ValueError):

    def __init__(self, reader, offset, partial):
        self.reader, self.offset, self.partial = (reader, offset, partial)
        super().__init__(f'Unproved positive child0x{reader:x} at{offset}')

class Reader:

    def __init__(self, data, start):
        if not isinstance(data, (bytes, bytearray, memoryview)) or type(start) is not int or (not 0 <= start <= len(data)):
            raise ValueError('Invalid player-after-ring source/cursor')
        self.data, self.pos = (data, start)

    def take(self, size):
        if size < 0 or size > len(self.data) - self.pos:
            raise ValueError('Truncated player-after-ring wire')
        raw = bytes(self.data[self.pos:self.pos + size])
        self.pos += size
        return raw

    def number(self, code):
        return struct.unpack('<' + code, self.take(struct.calcsize('<' + code)))[0]

    def raw(self, size):
        at = self.pos
        raw = self.take(size)
        return {'source_offset': at, 'size': size, 'raw_hex': raw.hex()}

def _context(source_major, minor, body_mode):
    if any((type(v) is not int for v in (source_major, minor, body_mode))) or (source_major, minor, body_mode) != (3754, 9, 1):
        raise ValueError('Unsupported player-after-ring source context')

def _delegate(r, reader, native, partial, **kwargs):
    if reader is None:
        raise UnsupportedChild(native, r.pos, partial)
    start = r.pos
    result = reader(r.data, start, **kwargs)
    if not isinstance(result, dict) or type(result.get('end')) is not int or (not start < result['end'] <= len(r.data)):
        raise ValueError('Invalid progressing child cursor')
    r.pos = result['end']
    return result

def _parameters(r):
    start = r.pos
    version = r.number('B')
    stored = r.raw(9)
    discarded = r.raw(1 if version <= 5 else 2 if version == 6 else 0)
    return {'start': start, 'end': r.pos, 'version': version, 'native_target': 'composite+0x5c', 'serialized_nine_bytes': stored, 'discarded_legacy_bytes': discarded}

def _position_row(r):
    start = r.pos
    version, encoding = (r.number('B'), r.number('B'))
    fields = {'0x08': r.raw(2), '0x00': r.raw(4), '0x0a': r.raw(2), '0x0e': r.raw(4)}
    if version >= 2:
        fields['0x14'] = r.raw(4)
        if version >= 3:
            fields['0x12'] = r.raw(2)
            fields['0x04'] = r.raw(4)
        else:
            fields['0x12'] = r.raw(2)
    else:
        fields['0x14'] = r.raw(4)
    return {'start': start, 'end': r.pos, 'version': version, 'encoding': encoding, 'raw_fields': fields, 'native_effective_0x08': None, 'state': 'serialized_values_before_encoding_normalization'}

def _position_history(r):
    start = r.pos
    version, count = (r.number('B'), r.number('b'))
    if count < 0:
        raise ValueError('Negative15778F4 population reaches native reserve length error')
    rows = [_position_row(r) for _ in range(count)]
    return {'start': start, 'end': r.pos, 'version': version, 'serialized_count': count, 'rows': rows, 'resident_retention_state': 'all_appended' if version > 1 else 'unproved_legacy_filter_result'}

def _typed_vector(r, variant_reader):
    start = r.pos
    version, count = (r.number('B'), r.number('i'))
    if count > MAX_ROWS:
        raise ValueError('Typed vector exceeds research count bound')
    rows = []
    for index in range(max(count, 0)):
        row = {'start': r.pos, 'native_index': index, 'version': r.number('B'), 'native_0x14_u8': r.number('B'), 'native_0x10_0x13_raw': r.raw(4)}
        row['value'] = _delegate(r, variant_reader, 71289268, row)
        row['end'] = r.pos
        rows.append(row)
    return {'start': start, 'end': r.pos, 'version': version, 'serialized_count_signed32': count, 'rows': rows, 'representation': 'typed_value_objects_serialized_not_raw_heap_pointers'}

def _fixed_138e158(r):
    start = r.pos
    version = r.number('B')
    fields = {hex(offset): r.raw(size) for offset, size in ((13, 1), (0, 2), (12, 1), (2, 2), (14, 1), (15, 1))}
    if version >= 2:
        fields.update({hex(offset): r.raw(2) for offset in (4, 6, 8, 10)})
    return {'start': start, 'end': r.pos, 'version': version, 'raw_fields': fields}

def _composite(r, variant_reader, individual_training_reader):
    start = r.pos
    version = r.number('B')
    if version != 12:
        raise ValueError('Unsupported17F1BB8 record version; current paired writer emits12')
    result = {'start': start, 'version': version, 'parameters': _parameters(r), 'optional_markers': {}}
    marker = r.number('B')
    result['optional_markers']['0x10'] = marker
    result['position_history'] = _position_history(r) if marker == 1 else None
    marker = r.number('B')
    result['optional_markers']['0x18'] = marker
    result['typed_vector'] = _typed_vector(r, variant_reader) if marker == 1 else None
    count = r.number('i')
    if count > MAX_ROWS:
        raise ValueError('Pair vector exceeds research count bound')
    result['pair_vector'] = {'serialized_count_signed32': count, 'rows': [list(r.take(2)) for _ in range(max(count, 0))]}
    marker = r.number('B')
    result['optional_markers']['0x28'] = marker
    if marker == 1:
        result['fixed_0x28'] = {'version': r.number('B'), 'raw_fields': {'0x04': r.raw(1), '0x00_0x03': r.raw(4), '0x05': r.raw(1)}}
    else:
        result['fixed_0x28'] = None
    marker = r.number('B')
    result['optional_markers']['0x00'] = marker
    result['individual_training'] = _delegate(r, individual_training_reader, 20082372, result) if marker == 1 else None
    marker = r.number('B')
    result['optional_markers']['0x08'] = marker
    result['individual_oop_training'] = {'marker': r.number('B'), 'raw_payload': r.raw(12)} if marker == 1 else None
    result['fixed_0x46'] = _fixed_138e158(r)
    result['tail_fields'] = {hex(offset): r.raw(size) for offset, size in ((91, 1), (48, 4), (86, 2), (68, 2), (89, 1), (64, 4), (90, 1), (52, 4), (88, 1), (56, 8), (101, 2))}
    result.update(end=r.pos, complete_190_wire=True, native_target='PLAYER+0x190', resident_heap_reconstruction=False)
    return result

def parse_composite(data, start, *, source_major=3754, minor=9, body_mode=1, variant_reader=None, individual_training_reader=None):
    _context(source_major, minor, body_mode)
    return _composite(Reader(data, start), variant_reader, individual_training_reader)

def parse(data, start, *, source_major=3754, minor=9, body_mode=1, variant_reader=None, individual_training_reader=None):
    _context(source_major, minor, body_mode)
    r = Reader(data, start)
    composite = _composite(r, variant_reader, individual_training_reader)
    string_start = r.pos
    size = r.number('I')
    if size > MAX_TEXT_BYTES:
        raise ValueError('PLAYER+E8 string exceeds research bound')
    raw_text = r.take(size)
    string = {'source_offset': string_start, 'native_player_offset': '0xe8', 'byte_length': size, 'value': raw_text.decode('utf8'), 'raw_hex': raw_text.hex(), 'meaning': 'unmapped_stored_string'}
    final = r.raw(12)
    return {'start': start, 'end': r.pos, 'consumed_bytes': r.pos - start, 'composite': composite, 'stored_0xe8_string': string, 'raw_player_0x238_0x243': final, 'next_native': '0xcfda74 optional PLAYER+108 marker', 'complete_player_body': False, 'complete_person': False, 'attribute_scale_state': 'still_requires_laterPLAYER+270bit7'}
