"""6E8330 counted typed-value vector, preserving source words before runtime conversion."""
import struct

def parse(data, start, *, source_major=3754, minor=9, limit=None, max_rows=65535):
    if (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported source3754/minor9 context')
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or (not 0 <= start <= bound <= len(data)):
        raise ValueError('Invalid6E8330 bounds')
    if type(max_rows) is not int or not 0 <= max_rows <= 65535:
        raise ValueError('Invalid6E8330 row bound')
    at = start

    def take(n):
        nonlocal at
        if n > bound - at:
            raise ValueError('Truncated6E8330')
        old = at
        at += n
        return bytes(data[old:at])
    count, format_code = struct.unpack('<HH', take(4))
    stride = 9 if format_code else 12
    if count > max_rows or count > (bound - at) // stride:
        raise ValueError('6E8330 count exceeds bounded extent')
    # Key/value words have no per-row wire predicates. Runtime conversion is
    # deliberately absent; only the exact checked extent is needed for walking.
    at += count * stride
    rows = None
    return {'start': start, 'end': at, 'count': count, 'format_code': format_code, 'rows': rows, 'native_reader': '0x6e8330', 'native_writer': '0x6e81cc', 'complete_child_wire': True, 'runtime_key_value_conversion_applied': False, 'semantic_labels': None}
