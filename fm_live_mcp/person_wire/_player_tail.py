"""Player-specific wire after CFDD44, bounded at the first unsupported child."""
import struct

class UnsupportedTail(ValueError):

    def __init__(self, native, offset, parts):
        self.native, self.offset, self.parts = (native, offset, parts)
        super().__init__(f'Unsupported PLAYER tail {native} at {offset}')

def parse_e0(data, start):
    at = start

    def take(n):
        nonlocal at
        if at + n > len(data):
            raise ValueError('Truncated13AC958 playerE0 child')
        b = data[at:at + n]
        at += n
        return b
    version = take(1)[0]
    raw_prefix = take(23).hex()
    extra = take(1).hex() if version >= 4 else None
    raw30 = take(4 if version >= 3 else 2).hex()
    dates = take(8).hex()
    raw_tail = take(21).hex()
    return {'start': start, 'end': at, 'version': version, 'raw_prefix': raw_prefix, 'extra36': extra, 'raw30': raw30, 'raw_dates': dates, 'raw_tail': raw_tail, 'native_reader': '0x13ac958'}

def parse(data, start, *, optional118_reader=None, polymorphic_reader=None, optional_f8_reader=None):
    at = start
    parts = {}

    def take(n):
        nonlocal at
        if at + n > len(data):
            raise ValueError('Truncated PLAYER optional tail')
        b = data[at:at + n]
        at += n
        return b

    def delegate(callback, native, **kwargs):
        nonlocal at
        if callback is None:
            raise UnsupportedTail(native, at, parts)
        r = callback(data, at, **kwargs)
        if not isinstance(r, dict) or type(r.get('end')) is not int or (not at < r['end'] <= len(data)):
            raise ValueError('Invalid PLAYER tail child cursor')
        at = r['end']
        return r
    marker = take(1)[0]
    parts['optional_e0_presence'] = marker
    if marker == 1:
        r = parse_e0(data, at)
        at = r['end']
        parts['optional_e0'] = r
    marker = take(1)[0]
    parts['optional118_presence'] = marker
    if marker == 1:
        parts['optional118'] = delegate(optional118_reader, '0x1347364')
    count = struct.unpack('<b', take(1))[0]
    parts['polymorphic_count'] = count
    parts['polymorphic_rows'] = []
    for ordinal in range(max(count, 0)):
        subtype = struct.unpack('<b', take(1))[0]
        if subtype == -1:
            parts['polymorphic_rows'].append({'subtype': -1, 'state': 'serialized_null'})
            continue
        parts['polymorphic_rows'].append(delegate(polymorphic_reader, '0x40608e4/vslot10', subtype=subtype))
    flag = take(1)[0]
    parts['optional_f8_flag'] = flag
    if flag & 1:
        parts['optional_f8'] = delegate(optional_f8_reader, '0x138ebe4')
    parts['field130_raw'] = take(4).hex()
    parts['field138_raw'] = take(4).hex()
    embedded_start = at
    fixed = take(14).hex()
    variant_marker = int.from_bytes(take(4), 'little')
    parts['embedded1f8_prefix'] = {'start': embedded_start, 'end': at, 'raw14': fixed, '15944c0_marker': variant_marker}
    if variant_marker > 10000:
        raise ValueError('15944C0 serialized row budget')
    parts['embedded1f8_rows'] = [take(6).hex() for _ in range(variant_marker)]
    parts['embedded1f8_tail_raw8'] = take(8).hex()
    late = take(8)
    parts['player270_277_raw'] = late.hex()
    parts['stored_attribute_scale_flag_bit7'] = bool(late[0] & 128)
    return {'start': start, 'end': at, 'parts': parts, 'native_stop': '0xcfe600', 'complete_player_specific_wire': True}
