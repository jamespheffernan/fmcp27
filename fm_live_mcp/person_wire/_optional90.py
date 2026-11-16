"""Bounded read-only D7D794 wire codec for NON_PLAYER optional native+90.

Reader ignores both container version and per-row marker. It rejects negative
signed i16 count. Writer D7D5FC emits version1 and row marker1, then two raw
bytes per native2-byte value. Preserve original wire order/duplicates; native
insertion behavior and semantic labels are outside this wire codec.
"""
import struct

def parse(data, start, *, source_major=3754, max_entries=4096):
    if type(source_major) is not int or source_major != 3754:
        raise ValueError('Unsupported D7D794 source profile')
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid D7D794 cursor')
    if type(max_entries) is not int or not 0 <= max_entries <= 32767:
        raise ValueError('Invalid D7D794 parser limit')
    if len(data) - start < 3:
        raise ValueError(f'Truncated D7D794 header at {start}')
    version, count = struct.unpack_from('<Bh', data, start)
    if count < 0:
        raise ValueError(f'Native D7D794 rejects negative count {count}')
    if count > max_entries:
        raise ValueError(f'D7D794 reader limit exceeded: {count}>{max_entries}')
    end = start + 3 + count * 3
    if end > len(data):
        raise ValueError(f'Truncated D7D794 rows at {start + 3}: need {count * 3}')
    rows = []
    for index in range(count):
        at = start + 3 + index * 3
        marker, byte0, byte1 = struct.unpack_from('<BBB', data, at)
        rows.append({'native_index': index, 'start': at, 'end': at + 3, 'marker': marker, 'raw_hex': bytes((byte0, byte1)).hex(), 'byte0': byte0, 'byte1': byte1})
    return {'start': start, 'end': end, 'version': version, 'count': count, 'rows': rows, 'native_reader': '0xd7d794', 'native_writer': '0xd7d5fc', 'native_owner_offset': '0x90', 'source_major': source_major, 'complete_child_wire': True, 'complete_person': False, 'semantic_fields_resolved': False}

def rebuild(result):
    """Rebuild exact consumed source bytes, including ignored source markers."""
    if result['count'] != len(result['rows']):
        raise ValueError('D7D794 row count mismatch')
    return struct.pack('<Bh', result['version'], result['count']) + b''.join((bytes((row['marker'], row['byte0'], row['byte1'])) for row in result['rows']))
