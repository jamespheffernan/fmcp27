"""Current171C8C8 wrapper +171BE5C body, paired parent/171BAC0 writer.

The enclosing heap row owns its preceding raw4. Current literals outer2/core7
avoid legacy property maps. Native packed bit23 values require a checked callback.
"""
import struct
CTX = {'stream_flags': 2, 'root80a': 0, 'root80b': 1, 'switch3523': 1, 'local_c98': 1, 'w4': 0}

class Unsupported(ValueError):

    def __init__(self, native, offset, partial):
        self.native = hex(native)
        self.offset = offset
        self.partial = partial
        super().__init__(f'Unproved171C8C8 child{native:#x} at{offset}')

def parse(data, start, *, limit=None, source_major=3754, minor=9, reference_context=CTX, variant_reader=None, max_items=4096):
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported171C8C8 source')
    if not isinstance(reference_context, dict) or any((type(reference_context.get(k)) is not int or not 0 <= reference_context[k] <= 255 for k in ('stream_flags', 'switch3523', 'local_c98'))) or (not reference_context.get('stream_flags', 0) & 2) or (reference_context.get('switch3523') != 1) or (reference_context.get('local_c98') != 1):
        raise ValueError('Explicit171C8C8 direct32 site witness required')
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or (not 0 <= start <= bound <= len(data)):
        raise ValueError('Invalid171C8C8 extent')
    if type(max_items) is not int or not 0 <= max_items <= 65536:
        raise ValueError('Invalid171C8C8 work bound')
    at = start
    remaining = max_items
    groups = []

    def take(n):
        nonlocal at
        if n < 0 or n > bound - at:
            raise ValueError(f'Truncated171C8C8 at{at}')
        old = at
        at += n
        return bytes(data[old:at])

    def number(code):
        return struct.unpack('<' + code, take(struct.calcsize('<' + code)))[0]
    outer = number('b')
    if outer != 2:
        raise Unsupported(24234184, at, {'outer_version': outer})
    core = number('b')
    if core != 7:
        raise Unsupported(24231516, at, {'outer_version': outer, 'core_version': core})
    for group_ordinal in range(2):
        count_start = at
        count = number('I')
        if count > remaining or count > (bound - at) // 5:
            raise ValueError('171C8C8 vector exceeds work/input bounds')
        remaining -= count
        rows = []
        for ordinal in range(count):
            begin = at
            marker = number('B')
            if marker != 1:
                raise ValueError('171C8C8 row marker differs from current paired writer')
            packed = number('I')
            value = None
            if packed & 1 << 23:
                if variant_reader is None:
                    raise Unsupported(71289268, at, {'group': group_ordinal, 'ordinal': ordinal, 'packed_word': packed})
                value = variant_reader(data, at, limit=bound)
                end = value.get('end') if isinstance(value, dict) else None
                if type(end) is not int or not at < end <= bound or value.get('complete_child_wire') is False or (value.get('state') == 'stopped'):
                    raise ValueError('Invalid171C8C8 typed-value endpoint')
                at = end
            rows.append({'ordinal': ordinal, 'start': begin, 'end': at, 'marker': marker, 'packed_word_u32': packed, 'native_word_without_bit23': packed & 4286578687, 'value': value})
        groups.append({'ordinal': group_ordinal, 'count_start': count_start, 'count': count, 'rows': rows})
    reference_start = at
    reference = number('I')
    fields_start = at
    fields = take(8)
    tail = number('B')
    return {'start': start, 'end': at, 'complete_child_wire': True, 'outer_version': outer, 'core_version': core, 'groups': groups, 'reference30': {'start': reference_start, 'end': reference_start + 4, 'raw_unsigned32': reference, 'native_reader': '0x1101bfc', 'site_w2_override': 1, 'identity_resolved': False}, 'native_38_3f_source_offset': fields_start, 'native_38_3f_raw_hex': fields.hex(), 'native_40_u8': tail, 'reference_context': dict(reference_context), 'runtime_globals_observed': False, 'native_collection_limit_observed': False, 'native_limit_condition': 'group counts < [global56C1628]'}
