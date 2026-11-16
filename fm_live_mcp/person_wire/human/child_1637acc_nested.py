"""17F090C typed-value vector at SCOUTED_PERSON_TAG extra+148.

Transport only. Generic typed values require an explicit 43FC9B4 callback.
"""
import struct

class UnsupportedNested(ValueError):

    def __init__(self, offset, partial):
        self.native = 71289268
        self.offset = offset
        self.partial = partial
        super().__init__(f'Unresolved typed value 0x43fc9b4 at {offset}')

def parse(data, start, *, limit=None, source_major=3754, minor=9, variant_reader=None, max_rows=4096, current_writer=True):
    if (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported explicit source version')
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or (not 0 <= start <= bound <= len(data)):
        raise ValueError('Invalid child bounds')
    if type(max_rows) is not int or not 0 <= max_rows <= 100000 or type(current_writer) is not bool:
        raise ValueError('Invalid research work/profile guard')
    at = start

    def take(size):
        nonlocal at
        if size > bound - at:
            raise ValueError('Truncated 17F090C child')
        old = at
        at += size
        return bytes(data[old:at])
    version = take(1)[0]
    if current_writer and version != 1:
        raise ValueError('Collection marker differs from paired current writer literal1')
    count = struct.unpack('<i', take(4))[0]
    if count > max_rows or max(count, 0) > (bound - at) // 6:
        raise ValueError('Typed-value collection exceeds work/input bound')
    rows = []
    for ordinal in range(max(count, 0)):
        row_start = at
        row_version = take(1)[0]
        if current_writer and row_version != 5:
            raise ValueError('Typed-value marker differs from paired current writer literal5')
        flag = take(1)[0]
        raw = take(4)
        row = {'native_index': ordinal, 'start': row_start, 'version': row_version, 'native_0x14_u8': flag, 'native_0x10_0x13_raw_hex': raw.hex(), 'native_0x10_u16': struct.unpack_from('<H', raw)[0], 'native_0x12_u16': struct.unpack_from('<H', raw, 2)[0]}
        if variant_reader is None:
            raise UnsupportedNested(at, {'start': start, 'version': version, 'serialized_count_signed32': count, 'rows': rows, 'pending_row': row})
        value = variant_reader(data, at, limit=bound)
        end = value.get('end') if isinstance(value, dict) else None
        if type(end) is not int or not at < end <= bound or value.get('complete') is False or (value.get('complete_child_wire') is False) or (value.get('state') not in (None, 'complete', 'decoded')):
            raise ValueError('Typed-value callback did not return a complete bounded child')
        at = end
        rows.append({**row, 'end': at, 'value': value})
    return {'start': start, 'end': at, 'version': version, 'serialized_count_signed32': count, 'iterated_count': max(count, 0), 'rows': rows, 'native_reader': '0x17f090c', 'native_writer': '0x17f06c4', 'leaf_reader': '0x17f0db4', 'leaf_writer': '0x17f0834', 'complete_child_wire': True, 'current_writer_markers_checked': current_writer, 'native_resource_limit_proved': False, 'values_semantically_interpreted': False}
