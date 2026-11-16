"""Current-v57 1637ACC prefix through its typed 17F090C child boundary."""
import struct
CTX = {'stream_flags': 2, 'root80a': 0, 'root80b': 1, 'switch3523': 1, 'local_c98': 1, 'w4': 0}

class Unsupported(ValueError):

    def __init__(self, native, offset, parts):
        self.native = hex(native)
        self.offset = offset
        self.parts = parts
        super().__init__(f'Unproved current1637ACC child {native:#x} at {offset}')

def parse_prefix(data, start, *, source_major=3754, minor=9, limit=None, reference_context=CTX, max_items=4096):
    if type(max_items) is not int or not 0 <= max_items <= 65536:
        raise ValueError('Invalid offline work bound')
    if (source_major, minor) != (3754, 9) or reference_context != CTX:
        raise ValueError('Unsupported explicit1637ACC source/context')
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or (not 0 <= start <= bound <= len(data)):
        raise ValueError('Invalid1637ACC extent')
    at = start
    reads = []
    parts = {}

    def take(n, label):
        nonlocal at
        if n > bound - at:
            raise ValueError('Truncated1637ACC')
        p = at
        at += n
        raw = bytes(data[p:at])
        reads.append({'start': p, 'end': at, 'label': label, 'raw_hex': raw.hex()})
        return raw

    def num(code, label):
        return struct.unpack('<' + code, take(struct.calcsize('<' + code), label))[0]
    version = num('h', 'version')
    if version != 57:
        raise Unsupported(23296716, at, {'version': version})
    for label, n in [('3f', 1), ('1c', 4), ('41', 1), ('3c', 1), ('17ee9ac', 3), ('43', 1), ('reference08', 4), ('18_1a', 4), ('team10', 4)]:
        take(n, label)
    presence = num('B', '30presence')
    parts['presence30'] = presence
    if presence not in (0, 1):
        raise ValueError('Current writer1637ACCpresence mismatch')
    take(4, 'reference00')
    if presence != 1:
        for field in ('20', '24', '28', '2c'):
            take(4, field)
        take(1, '42')
        take(1, '40')
        return {'start': start, 'end': at, 'version': version, 'parts': parts, 'reads': reads, 'reference_context': dict(reference_context), 'complete_child_wire': True}
    for label, n in [('30.team18', 4), ('30.85', 1), ('30.78', 4), ('4acf738', 5), ('30.3c', 4), ('30.40', 4), ('30.44', 4), ('30.4c', 4), ('30.50', 4), ('30.comp54', 4), ('30.86', 1), ('30.87', 1), ('30.comp58', 4), ('30.88', 1), ('30.89', 1), ('30.reference20', 4), ('30.7e', 2)]:
        take(n, label)
    for field in ('20', '24', '28', '2c'):
        take(4, field)
    for label, n in [('30.5c', 4), ('30.60', 4), ('30.64', 4), ('30.80', 2), ('30.68', 4), ('30.6c', 4), ('30.70', 4), ('30.74', 4), ('30.8e', 1), ('30.8d', 1), ('30.48', 4), ('42', 1)]:
        take(n, label)
    n = num('I', '30.190count')
    parts['vector190_count'] = n
    if n > max_items or n > (bound - at) // 12:
        raise ValueError('1637ACCvector190 count exceeds bound')
    for index in range(n):
        if num('H', '190.version') != 1:
            raise Unsupported(23311752, at, parts)
        take(10, '190.ref32_and_three_u16')
    return {'start': start, 'end': at, 'complete_child_wire': False, 'next_native_reader': '0x17f090c', 'version': version, 'parts': parts, 'reads': reads, 'reference_context': dict(reference_context)}

def before_tail_child(data, start, *, nested_reader, source_major=3754, minor=9, limit=None, reference_context=CTX, max_items=4096):
    prefix = parse_prefix(data, start, source_major=source_major, minor=minor, limit=limit, reference_context=reference_context, max_items=max_items)
    bound = len(data) if limit is None else limit
    at = prefix['end']
    nested = nested_reader(data, at, limit=bound, source_major=source_major, minor=minor)
    if type(nested.get('end')) is not int or not at < nested['end'] <= bound:
        raise ValueError('Invalid17F090Cchild handoff')
    at = nested['end']
    reads = []

    def take(n, label):
        nonlocal at
        if n > bound - at:
            raise ValueError('Truncated1637ACCafter17F090C')
        p = at
        at += n
        raw = bytes(data[p:at])
        reads.append({'start': p, 'end': at, 'label': label, 'raw_hex': raw.hex()})
        return raw
    take(8, '30.10')
    take(4, '30.38')
    take(1, '30.8a')
    for field in ['90_92', '96_98', '9c_9e', 'a2_a4']:
        marker = take(1, 'discarded_marker_' + field)[0]
        if marker != 1:
            raise ValueError('1637ACCcurrent buffered marker mismatch')
        take(1, '30.' + field[:2])
        take(4, '30.' + field[3:])
    for label, n in [('17ee9ac_82', 3), ('30.00', 8), ('30.08', 8), ('30.84', 1), ('30.7c', 2)]:
        take(n, label)
    return {'start': start, 'end': at, 'prefix': prefix, 'nested17f090c': nested, 'reads_after_nested': reads, 'next_native_reader': '0x4ad0c70', 'complete_child_wire': False}

def before_rows(data, start, *, nested_reader, tail_reader, source_major=3754, minor=9, limit=None, reference_context=CTX, max_items=4096):
    p = before_tail_child(data, start, nested_reader=nested_reader, source_major=source_major, minor=minor, limit=limit, reference_context=reference_context, max_items=max_items)
    bound = len(data) if limit is None else limit
    child = tail_reader(data, p['end'], limit=bound, source_major=source_major, minor=minor)
    at = child.get('end')
    if type(at) is not int or not p['end'] < at <= bound:
        raise ValueError('Invalid4AD0C70child handoff')
    if bound - at < 4:
        raise ValueError('Truncated1637ACC A8 count')
    count = struct.unpack_from('<I', data, at)[0]
    at += 4
    if count > max_items:
        raise ValueError('1637ACC A8 count exceeds offline work bound')
    return {'start': start, 'end': at, 'prefix': p, 'child4ad0c70': child, 'a8_count': count, 'next_native_reader': '0x15162f0' if count else '0x163ac20', 'complete_child_wire': False, 'native_collection_limit': 'unobserved; conditional count < global56C1628'}

def parse_a8_row(data, start, *, limit=None, vector_reader=None, max_items=4096):
    """One current15162F0 row; vector callback consumes rows, not its count."""
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or (not 0 <= start <= bound <= len(data)):
        raise ValueError('Invalid15162F0 extent')
    if bound - start < 16:
        raise ValueError('Truncated15162F0 prefix')
    version = data[start]
    if version != 2:
        raise Unsupported(22110960, start, {'version': version})
    at = start + 12
    vectors = []
    for ordinal in range(2):
        if bound - at < 4:
            raise ValueError('Truncated15162F0 count')
        count = struct.unpack_from('<I', data, at)[0]
        at += 4
        if count > max_items:
            raise ValueError('15162F0 vector count exceeds offline work bound')
        if count:
            if vector_reader is None:
                raise Unsupported(22128052, at, {'count': count, 'vector_ordinal': ordinal, 'row_start': start})
            child = vector_reader(data, at, count=count, limit=bound)
            end = child.get('end')
            if type(end) is not int or not at < end <= bound:
                raise ValueError('Invalid151A5B4 handoff')
            at = end
        else:
            child = None
        vectors.append({'count': count, 'child': child})
    return {'start': start, 'end': at, 'version': version, 'raw8_hex': bytes(data[start + 1:start + 9]).hex(), 'raw17ee9ac_hex': bytes(data[start + 9:start + 12]).hex(), 'vectors': vectors, 'complete_child_wire': True, 'native_collection_limit': 'unobserved; conditional counts < global56C1628'}

def before_variant_vectors(data, start, *, nested_reader, tail_reader, vector_reader, source_major=3754, minor=9, limit=None, reference_context=CTX, max_items=4096):
    p = before_rows(data, start, nested_reader=nested_reader, tail_reader=tail_reader, source_major=source_major, minor=minor, limit=limit, reference_context=reference_context, max_items=max_items)
    bound = len(data) if limit is None else limit
    at = p['end']
    rows = []
    for ordinal in range(p['a8_count']):
        row = parse_a8_row(data, at, limit=bound, vector_reader=vector_reader, max_items=max_items)
        rows.append(row)
        at = row['end']
    vectors = []
    for field in ('c0', 'd8'):
        if bound - at < 4:
            raise ValueError('Truncated163BD6C count')
        count = struct.unpack_from('<I', data, at)[0]
        at += 4
        if count > max_items:
            raise ValueError('163BD6C count exceeds offline work bound')
        child = None
        if count:
            child = vector_reader(data, at, count=count, limit=bound)
            end = child.get('end')
            if type(end) is not int or not at < end <= bound:
                raise ValueError('Invalid163BD6C handoff')
            at = end
        vectors.append({'field': field, 'count': count, 'child': child})
    return {'start': start, 'end': at, 'prefix': p, 'a8_rows': rows, 'c0_d8_vectors': vectors, 'next_native_reader': '0x15815a0', 'complete_child_wire': False}

def parse(data, start, *, child_readers=None, source_major=3754, minor=9, limit=None, reference_context=CTX, max_items=4096, variant_switch3522=None):
    """Fail closed at the first unavailable positively reached native child."""
    children = {} if child_readers is None else child_readers
    prefix = parse_prefix(data, start, source_major=source_major, minor=minor, limit=limit, reference_context=reference_context, max_items=max_items)
    if prefix['complete_child_wire']:
        return prefix
    kwargs = dict(source_major=source_major, minor=minor, limit=limit, reference_context=reference_context, max_items=max_items)
    if 25102604 not in children:
        p = parse_prefix(data, start, **kwargs)
        raise Unsupported(25102604, p['end'], p)
    if 78449776 not in children:
        p = before_tail_child(data, start, nested_reader=children[25102604], **kwargs)
        raise Unsupported(78449776, p['end'], p)
    if 22128052 not in children:
        p = before_rows(data, start, nested_reader=children[25102604], tail_reader=children[78449776], **kwargs)
        raise Unsupported(22110960, p['end'], p)
    p = before_variant_vectors(data, start, nested_reader=children[25102604], tail_reader=children[78449776], vector_reader=children[22128052], **kwargs)
    first = parse_variant_vector(data, p['end'], limit=limit, max_items=max_items, switch3522=variant_switch3522)
    second = parse_variant_vector(data, first['end'], limit=limit, max_items=max_items, switch3522=variant_switch3522)
    p['variant_vectors'] = [first, second]
    p['end'] = second['end']
    p['next_native_reader'] = '0x184d150'
    if 25481552 not in children:
        raise Unsupported(25481552, p['end'], p)
    child = children[25481552](data, p['end'], limit=limit, source_major=source_major, minor=minor, reference_context=reference_context)
    bound = len(data) if limit is None else limit
    end = child.get('end')
    if type(end) is not int or not p['end'] < end <= bound:
        raise ValueError('Invalid184D150 handoff')
    p['child184d150'] = child
    p['end'] = end
    p['next_native_reader'] = '0x111988c'
    if 17930380 not in children:
        raise Unsupported(17930380, end, p)
    reference = children[17930380](data, end, limit=limit, source_major=source_major, minor=minor, reference_context=reference_context)
    at = reference.get('end')
    if type(at) is not int or not end < at <= bound:
        raise ValueError('Invalid111988C handoff')
    if bound - at < 14:
        raise ValueError('Truncated1637ACC final fields')
    final = []
    for label, n in [('40', 1), ('30.reference28', 4), ('30.8b', 1), ('30.8c', 1), ('30.1a8', 4), ('30.1ac', 1), ('30.1ae', 2)]:
        final.append({'label': label, 'start': at, 'end': at + n, 'raw_hex': bytes(data[at:at + n]).hex()})
        at += n
    p['reference111988c'] = reference
    p['final_fields'] = final
    p['end'] = at
    p['complete_child_wire'] = True
    p.pop('next_native_reader', None)
    return p

def parse_variant_vector(data, start, *, limit=None, max_items=4096, switch3522=None):
    """Current15815A0 v5/v4 wire; kind8 requires an explicit switch3522."""
    bound = len(data) if limit is None else limit
    if not 0 <= start <= bound <= len(data) or bound - start < 5:
        raise ValueError('Truncated15815A0 header')
    version = data[start]
    count = struct.unpack_from('<i', data, start + 1)[0]
    if version != 5:
        raise Unsupported(22549920, start, {'version': version})
    if count < 0:
        raise ValueError('Negative15815A0 count')
    if count > max_items:
        raise ValueError('15815A0 count exceeds offline work bound')
    at = start + 5
    rows = []
    for ordinal in range(count):
        if bound - at < 12:
            raise ValueError('Truncated15815A0 row prefix')
        row_start = at
        row_version = data[at]
        code = data[at + 1]
        kind = data[at + 11]
        if row_version != 4:
            raise Unsupported(22550436, at, {'row_version': row_version})
        at += 12

        def skip(n):
            nonlocal at
            if n > bound - at:
                raise ValueError('Truncated15815A0 typed payload')
            at += n
        if kind in (0, 1):
            skip(4)
        elif kind in (2, 3):
            skip(1)
        elif kind == 4:
            skip(3)
        elif kind in (5, 6):
            for _ in range(1 if kind == 5 else 3):
                if bound - at < 4:
                    raise ValueError('Truncated15815A0 reference-vector count')
                n = struct.unpack_from('<I', data, at)[0]
                at += 4
                if n > max_items or n > (bound - at) // 4:
                    raise ValueError('15815A0 reference-vector bound exceeded')
                skip(n * 4)
        elif kind == 7:
            skip(13)
        elif kind == 8:
            if type(switch3522) is not int or switch3522 not in (0, 1):
                raise Unsupported(17832956, at, {'reason': 'Explicit switch3522 witness required', 'ordinal': ordinal})
            if switch3522:
                skip(4)
            else:
                if bound - at < 2:
                    raise ValueError('Truncated15815A0 compact reference')
                value = struct.unpack_from('<h', data, at)[0]
                at += 2
                if value == -2:
                    if bound - at < 4:
                        raise ValueError('Truncated15815A0 escaped reference')
                    value = struct.unpack_from('<i', data, at)[0]
                    at += 4
                    if value < 0:
                        raise ValueError('Negative escaped15815A0 reference')
                elif value < -1:
                    raise ValueError('Negative15815A0 reference')
        elif kind != 255:
            raise Unsupported(22550732, at, {'kind': kind, 'ordinal': ordinal})
        skip(8)
        if code in (76, 77, 79, 83, 86, 87, 92, 93, 94):
            skip(4)
        rows.append({'start': row_start, 'end': at, 'row_version': row_version, 'field60': code, 'kind': kind, 'raw_hex': bytes(data[row_start:at]).hex()})
    return {'start': start, 'end': at, 'version': version, 'count': count, 'rows': rows, 'complete_child_wire': True}
