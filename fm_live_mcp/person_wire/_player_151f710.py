"""Pure151F710 collection geometry for checked3754/9 current-writer rows.

151FC68 accepts older versions/legacy tail data; this codec deliberately supports
only the paired151F4F0 writer profile(version2, parameter7, finalpresence0).
Native scalar values remain raw. No player meaning, references or record-end
claim beyond this child collection is inferred.
"""
import struct
STRIDE = 69
MAX_COUNT = 4096

def parse(data, start, *, limit=None, source_major=3754, minor=9, max_count=MAX_COUNT):
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported151F710 source context')
    if not isinstance(data, (bytes, bytearray, memoryview)) and (not hasattr(data, 'find')):
        raise ValueError('Invalid151F710 source buffer')
    limit = len(data) if limit is None else limit
    if type(start) is not int or type(limit) is not int or (not 0 <= start <= limit <= len(data)):
        raise ValueError('Invalid151F710 checked span')
    if type(max_count) is not int or not 0 <= max_count <= MAX_COUNT:
        raise ValueError('Invalid151F710 offline count budget')
    if limit - start < 4:
        raise ValueError('Truncated151F710 count')
    count = struct.unpack_from('<I', data, start)[0]
    if count > max_count:
        raise ValueError('151F710 count exceeds offline budget')
    at = start + 4
    if count > (limit - at) // STRIDE:
        raise ValueError('Truncated151F710 current-writer rows')
    rows = []
    for _ in range(count):
        row_start = at
        if data[at] != 2:
            raise ValueError('Unsupported151FC68 version outside current-writer2 profile')
        if data[at + 48] != 7:
            raise ValueError('Unsupported151FC68 parameter version outside current-writer7 profile')
        if data[at + 68] != 0:
            raise ValueError('Unsupported151FC68 legacy tail outside current-writer0 profile')
        a, b, c = struct.unpack_from('<IIH', data, at + 58)
        rows.append({'start': row_start, 'end': row_start + STRIDE, 'version': 2, 'raw_native_00_2e_hex': bytes(data[at + 1:at + 48]).hex(), 'parameter': {'version': 7, 'raw_native_2f_37_hex': bytes(data[at + 49:at + 58]).hex()}, 'raw_native_3c_u32': a, 'raw_native_40_u32': b, 'raw_native_38_u16': c, 'legacy_tail_presence': 0})
        at += STRIDE
    return {'start': start, 'end': at, 'count': count, 'row_stride': STRIDE, 'rows': rows, 'native_reader': '0x151F710', 'native_item_reader': '0x151FC68', 'native_item_writer': '0x151F4F0', 'wire_scope': 'source3754_minor9_current_writer_row2_parameter7_tail0', 'whole_player_record': False}
