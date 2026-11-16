"""488B5AC row wire under48947C8 current container18; no per-row version.

The complete native reader has one count loop and no version/type dispatch.
Raw8 vector elements and native-offset scalar bytes remain uninterpreted.
"""
import struct
TAIL_FIELDS = (('0x2a', 1), ('0x27', 1), ('0x28', 1), ('0x22', 2), ('0x24', 1), ('0x25', 1), ('0x26', 1), ('0x30', 2), ('0x29', 1), ('0x2c', 4), ('0x32', 2))

def parse(data, start, *, container_version=18, limit=None, source_major=3754, minor=9, max_entries=100000):
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Explicit3754/9 source profile required')
    if type(container_version) is not int or container_version != 18:
        raise ValueError('Explicit current container18 source scope required')
    if type(max_entries) is not int or not 0 <= max_entries <= 1000000:
        raise ValueError('Invalid offline vector budget')
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or (not 0 <= start <= bound <= len(data)):
        raise ValueError('Invalid bounded488B5AC cursor')
    at = start

    def take(n):
        nonlocal at
        if n > bound - at:
            raise ValueError(f'Truncated488B5AC at{at}')
        raw = bytes(data[at:at + n])
        at += n
        return raw
    prefix = take(10)
    count_raw = take(4)
    count = struct.unpack('<i', count_raw)[0]
    if count < 0:
        raise ValueError('Negative native vector count traps for fresh constructor capacity0')
    if count > max_entries:
        raise ValueError('Offline488B5AC vector budget exceeded')
    if count * 8 + 17 > bound - at:
        raise ValueError(f'Truncated488B5AC vector/tail at{at}')
    # Opaque fixed raw8 entries have no per-entry markers or constraints.
    at += count * 8
    vector = None
    fields = {'0x18': prefix[:4].hex(), '0x1c': prefix[4:8].hex(), '0x20': prefix[8:10].hex()}
    for field, width in TAIL_FIELDS:
        fields[field] = take(width).hex()
    return {'start': start, 'end': at, 'native_reader': '0x488b5ac', 'paired_writer': '0x488b3b0', 'container_version': container_version, 'row_version_consumed': False, 'native_fields': fields, 'vector_native_offset': '0x0', 'vector_count': count, 'vector_count_raw_hex': count_raw.hex(), 'vector_stride': 8, 'vector_raw_hex': vector, 'vector_payload_projected': False, 'complete_owned_child': True, 'field_meanings_resolved': False, 'reference_context_consumed': False}
