"""Pure CA8B3C -> CA947C wire, modern3754 full body/raw64 context."""
import struct

def decode(data, start, *, source_version=3754, body_mode=1, read_base=0, reference_mode, max_rows=100000):
    if (source_version, body_mode, read_base, reference_mode) != (3754, 1, 0, 'raw64'):
        raise ValueError('Unsupported inherited person middle context')
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid person middle cursor')
    if type(max_rows) is not int or not 0 <= max_rows <= 100000:
        raise ValueError('Invalid person middle row budget')
    at = start

    def take(n):
        nonlocal at
        if n < 0 or n > len(data) - at:
            raise ValueError('Truncated person middle')
        raw = data[at:at + n]
        at += n
        return raw

    def number(code):
        return struct.unpack('<' + code, take(struct.calcsize('<' + code)))[0]
    count = number('B')
    first = []
    if count > max_rows:
        raise ValueError('Person middle first collection budget')
    for ordinal in range(count):
        row_start = at
        first.append({'start': row_start, 'ordinal': ordinal, 'reference_raw64_hex': take(8).hex(), 'object_8_raw_byte': number('B'), 'end': at})
    second_count = number('I')
    if second_count > max_rows - count:
        raise ValueError('Person middle second collection budget')
    second = []
    for ordinal in range(second_count):
        row_start = at
        field8 = number('B')
        fielda = number('H')
        field9 = number('B')
        selector = number('B')
        width = 4 if selector == 1 else 8
        payload = take(width)
        second.append({'start': row_start, 'end': at, 'ordinal': ordinal, 'object_8_raw_byte': field8, 'object_a_b_raw_u16': fielda, 'object_9_raw_byte': field9, 'object_c_payload_selector': selector, 'object_0_payload_width': width, 'object_0_payload_hex': payload.hex()})
    return {'start': start, 'end': at, 'first_count': count, 'first_rows': first, 'second_count': second_count, 'second_rows': second, 'next_native': 'CA947C', 'complete_segment': True, 'source_version': source_version, 'reference_mode': reference_mode}

def parse(data, start, **kwargs):
    return decode(data, start, **kwargs)['end']
