"""FULL_CONTRACT+98 vector, current writer 127A970, bounded inline reader at 1279E3C."""
import struct

def parse(data, start, *, reference_mode, max_rows=4096):
    if type(start) is not int or not 0 <= start <= len(data) - 4:
        raise ValueError('Truncated FULL_CONTRACT+98 row count')
    widths = {'direct64': 8, 'index32': 4, 'compact16': 2}
    if reference_mode not in widths:
        raise ValueError('Unsupported explicit contract vector reference profile')
    width = widths[reference_mode]
    count, = struct.unpack_from('<I', data, start)
    if count > max_rows:
        raise ValueError('Contract vector exceeds work budget')
    at = start + 4
    rows = []
    for _ in range(count):
        if at + 7 + width > len(data):
            raise ValueError('Truncated FULL_CONTRACT+98 row')
        version, = struct.unpack_from('<H', data, at)
        if version != 1:
            raise ValueError('Contract vector row differs from paired current writer')
        reference = data[at + 2:at + 2 + width]
        if reference_mode == 'compact16' and reference == b'\xfe\xff':
            raise ValueError('Extended compact reference is unsupported')
        scalar, flag = struct.unpack_from('<IB', data, at + 2 + width)
        rows.append({'start': at, 'reference_raw_hex': reference.hex(), 'scalar_raw_u32': scalar, 'field_raw_u8': flag})
        at += 7 + width
    return {'start': start, 'end': at, 'count': count, 'rows': rows, 'reference_mode': reference_mode, 'reference_identity_resolved': False, 'native_runtime_acceptance': False}
