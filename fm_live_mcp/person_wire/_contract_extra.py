"""Pure FE4470 buffered-reader wire codec; paired writer FE40AC.

End is the logical cursor including the native pending tail. The caller must
not consume that tail again. Native FE4470 itself queues the final2/4bytes;
FULL_CONTRACT127A178..198 flushes them before FE4904. No field labels inferred.
"""
import struct

def parse(data, start, *, source_major=3754, minor=9, max_byte_count=4096):
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported FE4470 source profile')
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid FE4470 cursor')
    if type(max_byte_count) is not int or not 0 <= max_byte_count <= 4294967295:
        raise ValueError('Invalid FE4470 reader limit')
    if len(data) - start < 5:
        raise ValueError('Truncated FE4470 header')
    version, count = struct.unpack_from('<BI', data, start)
    if count > max_byte_count:
        raise ValueError(f'FE4470 reader limit exceeded: {count}>{max_byte_count}')
    tail_start = start + 5 + count
    pending_bytes = 4 if version > 2 else 2
    end = tail_start + pending_bytes
    if end > len(data):
        raise ValueError('Truncated FE4470 value bytes or pending tail')
    values = bytes(data[start + 5:tail_start])
    tail = bytes(data[tail_start:end])
    return {'start': start, 'end': end, 'version': version, 'byte_count': count, 'value_bytes_hex': values.hex(), 'native_00_03_stored_raw_hex': values[:4].hex(), 'discarded_value_bytes_hex': values[4:].hex(), 'native_04_u16_raw': int.from_bytes(tail[:2], 'little'), 'native_06_raw': tail[2] if version > 2 else None, 'native_07_raw': tail[3] if version > 2 else None, 'tail_hex': tail.hex(), 'raw_hex': bytes(data[start:end]).hex(), 'native_return_physical_offset': tail_start, 'native_pending_bytes': pending_bytes, 'end_includes_native_pending_tail': True, 'native_reader': '0xfe4470', 'native_writer': '0xfe40ac', 'source_major': source_major, 'minor': minor, 'complete_child_wire': True, 'semantic_fields_resolved': False}

def rebuild(result):
    values = bytes.fromhex(result['value_bytes_hex'])
    tail = bytes.fromhex(result['tail_hex'])
    if len(values) != result['byte_count'] or len(tail) != (4 if result['version'] > 2 else 2):
        raise ValueError('FE4470 reconstruction length mismatch')
    return struct.pack('<BI', result['version'], len(values)) + values + tail
