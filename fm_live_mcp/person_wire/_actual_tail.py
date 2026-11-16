"""Pure CA947C→CA9964 modern actual-person tail."""
import struct

def parse(data, start, *, source_version=3754, global_source_version=3754, body_mode=1, read_base=0):
    if (source_version, global_source_version, body_mode, read_base) != (3754, 3754, 1, 0):
        raise ValueError('unsupported actual-person tail context')
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('invalid start')
    at = start

    def take(n):
        nonlocal at
        if n < 0 or n > len(data) - at:
            raise ValueError('truncated actual-person tail')
        b = data[at:at + n]
        at += n
        return b
    marker = take(1)[0]
    child = None
    if marker & 1:
        raw = take(15)
        obj = bytearray(15)
        obj[:7] = raw[:7]
        obj[8:12] = raw[7:11]
        obj[14] = raw[11]
        obj[12:14] = raw[12:14]
        obj[7] = raw[14]
        child = {'wire_hex': raw.hex(), 'object_a0_15bytes_hex': obj.hex()}
    count = struct.unpack('<h', take(2))[0]
    if count < 0:
        raise ValueError('negative tail vector research constraint')
    vals = list(struct.unpack('<' + 'I' * count, take(4 * count)))
    fields = {}
    for name, width in [('object_100', 2), ('object_f0', 4), ('object_10a', 1), ('object_f4', 8), ('object_bc', 4), ('object_e0', 4), ('object_fc', 4), ('object_10c', 1), ('object_90', 8)]:
        fields[name] = take(width).hex()
    return {'start': start, 'end': at, 'marker': marker, 'optional_a0': child, 'object_88_count': count, 'object_88_u32_source_values': vals, 'fixed_fields_raw': fields, 'next_native': 'CA9964', 'complete_actual_tail': True, 'common_body_included': False}
