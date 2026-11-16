"""Pure bounded continuation after the regular-player122/126-byte prefix.

Caller supplies checked initial ring count and, for a positive population, the
native generic collection limit. No primary-player/type or same-file identity is
established by this segment. Native offsets stay raw; physical units and names
are not assigned. The attribute scale flag+270 is still later and unconsumed.
"""
import math
import struct

class Reader:

    def __init__(self, data, start):
        if not isinstance(data, (bytes, bytearray, memoryview)) or type(start) is not int or (not 0 <= start <= len(data)):
            raise ValueError('Invalid player continuation source/cursor')
        self.data, self.offset = (data, start)

    def take(self, n):
        if n > len(self.data) - self.offset:
            raise ValueError('Truncated player continuation')
        raw = bytes(self.data[self.offset:self.offset + n])
        self.offset += n
        return raw

    def number(self, code):
        return struct.unpack('<' + code, self.take(struct.calcsize('<' + code)))[0]

def _f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]

def _s16(value):
    return value if value < 32768 else value - 65536

def _legacy_228(word, target, raw_float, initial):
    retained = (initial, 'retained_unavailable' if initial is None else 'retained_checked_input')
    if _s16(word) >= 1:
        if target == 0:
            return retained
        absolute = _s16(abs(_s16(target)) & 65535)
        if absolute < 1:
            return (3, 'derived_native_code')
        ratio = _f32(_f32(float(absolute)) / _f32(100.0))
        ratio = _f32(ratio * ratio)
        value = _f32(_f32(float(word)) / ratio)
        return (1 if value < 19 else 2 if value < 22 else 3 if value < 25 else 4 if value < 28 else 5, 'derived_native_code')
    if word & 32768:
        value = {65473: 1, 65465: 2, 65461: 3, 65459: 4, 65456: 5}.get(word)
        return retained if value is None else (value, 'derived_native_code')
    value = struct.unpack('<f', raw_float)[0]
    if value == 0:
        return retained
    if math.isnan(value):
        return (5, 'derived_native_code')
    low = struct.unpack('<f', bytes.fromhex('3333733f'))[0]
    middle = struct.unpack('<f', bytes.fromhex('3333933f'))[0]
    upper = struct.unpack('<f', bytes.fromhex('6666a63f'))[0]
    return (1 if value < low else 2 if value < 1 else 3 if value < middle else 4 if value <= upper else 5, 'derived_native_code')

def _measurement(r, initial_228):
    if initial_228 is not None and (type(initial_228) is not int or not 0 <= initial_228 <= 255):
        raise ValueError('Invalid retained native+228 byte')
    start = r.offset
    marker = r.number('B')
    word = r.number('H') if marker <= 1 else None
    target = r.number('H')
    raw_float = None
    raw_byte = None
    if marker <= 1:
        raw_float = r.take(4)
        byte, state = _legacy_228(word, target, raw_float, initial_228)
    else:
        raw_byte = r.number('B')
        byte, state = (raw_byte, 'serialized')
    return {'start': start, 'end': r.offset, 'marker': marker, 'legacy_u16': word, 'legacy_float32_hex': None if raw_float is None else raw_float.hex(), 'raw_native_0x226_u16': target, 'serialized_native_0x228_u8': raw_byte, 'effective_native_0x228_u8': byte, 'native_0x228_state': state}

def parse_measurement(data, start, *, initial_228=None):
    return _measurement(Reader(data, start), initial_228)

def parse(data, start, *, initial_ring_count, collection_limit=None, initial_228=None, source_major=3754, minor=9, body_mode=1):
    if any((type(x) is not int for x in (source_major, minor, body_mode))) or (source_major, minor, body_mode) != (3754, 9, 1):
        raise ValueError('Unchecked regular-player continuation context')
    if type(initial_ring_count) is not int or initial_ring_count != 0:
        raise ValueError('Native player+218 must initially be0')
    if collection_limit is not None and (type(collection_limit) is not int or not 0 <= collection_limit <= 18446744073709551615):
        raise ValueError('Invalid native collection limit')
    r = Reader(data, start)
    measurement = _measurement(r, initial_228)
    value244 = r.number('I')
    value265 = r.number('B')
    count = r.number('I')
    if count > 12:
        raise ValueError('Native player ring count exceeds12')
    if count and collection_limit is None:
        raise ValueError('Positive ring requires independently checked native collection limit56C1628')
    if count and count >= collection_limit:
        raise ValueError('Native player ring count reaches generic collection limit')
    ring_at = r.offset
    ring = r.take(count)
    value230 = r.number('I')
    return {'start': start, 'end': r.offset, 'consumed_bytes': r.offset - start, 'measurement': measurement, 'native_fields': {'0x244': value244, '0x265': value265, '0x230': value230}, 'ring': {'count': count, 'source_offset': ring_at, 'raw_hex': ring.hex(), 'serialized_order': list(ring), 'initial_0x218': initial_ring_count, 'checked_native_collection_limit': collection_limit, 'native_slot_projection': None, 'projection_gap': 'PriorPLAYER+225 ringhead not supplied; onlywireorder projected.'}, 'complete_player_body': False, 'complete_person': False, 'next_reader': '0x17f1bb8', 'next_native_player_offset': '0x190', 'attribute_scale_state': 'still_requires_laterPLAYER+270bit7'}
