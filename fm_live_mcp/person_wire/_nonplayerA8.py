"""1462B9C NON_PLAYER+A8 two-byte source rows, before runtime filtering.

Raw key/value bytes remain unlabelled. Native14622B4 tests the signed key;
this source decoder preserves every row and its original order regardless.
"""
NATIVE_KEY_TABLE = bytes.fromhex('00000000000001010101010101010000000100000000010000010001010100010000000000000000010101010101010000000000000000010000000000000000000000010001010000010000000000000000010000010001000000000000000000000000')

def native_accepts_key(key):
    return 1 <= key <= 100 and NATIVE_KEY_TABLE[key - 1] == 0

def parse(data, start, *, source_major=3754, minor=9, max_rows=255):
    if (type(source_major), type(minor)) != (int, int) or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported NON_PLAYER+A8 source')
    if type(start) is not int or not 0 <= start < len(data):
        raise ValueError('Invalid or truncated NON_PLAYER+A8 count cursor')
    if type(max_rows) is not int or not 0 <= max_rows <= 255:
        raise ValueError('Invalid NON_PLAYER+A8 work budget')
    count = data[start]
    if count > max_rows:
        raise ValueError('NON_PLAYER+A8 count exceeds work budget')
    end = start + 1 + 2 * count
    if end > len(data):
        raise ValueError('Truncated NON_PLAYER+A8 rows')
    rows = []
    for index in range(count):
        at = start + 1 + 2 * index
        key = data[at]
        signed = key if key < 128 else key - 256
        rows.append({'native_index': index, 'start': at, 'end': at + 2, 'key_raw_u8': key, 'key_signed_i8': signed, 'value_raw_u8': data[at + 1], 'native_key_accepted': native_accepts_key(signed)})
    return {'start': start, 'end': end, 'native_reader': '0x1462b9c', 'native_writer_block': '0xc8abcc..0xc8ac68', 'native_owner_field': 'NON_PLAYER+0xa8', 'wire_count': count, 'rows': rows, 'runtime_retention_applied': False, 'native_key_predicate': '0x14622b4', 'pending_bytes': 0, 'complete_child_wire': True, 'semantic_fields_resolved': False}
