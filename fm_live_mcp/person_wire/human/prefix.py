"""Current HUMAN_NON_PLAYER body prefix; stops on unassigned positive children.
No reference width is inferred from a common-suffix profile.
"""
from . import child_17e7c5c
import struct

class Unsupported(ValueError):

    def __init__(self, native, offset, parts):
        self.native = native
        self.offset = offset
        self.parts = parts
        super().__init__(f'unproved child {native:#x} at {offset}')

def parse(data, start, *, source_major=3754, minor=9, limit=None, children=None, max_rows=4096):
    if (source_major, minor) != (3754, 9):
        raise ValueError('unsupported source')
    end = len(data) if limit is None else limit
    if not 0 <= start <= end <= len(data):
        raise ValueError('invalid extent')
    c = start
    parts = {}
    children = {} if children is None else children

    def take(n):
        nonlocal c
        if n < 0 or n > end - c:
            raise ValueError(f'truncated at {c}')
        s = c
        c += n
        return data[s:c]

    def u(n):
        return int.from_bytes(take(n), 'little')

    def count(n, label):
        v = u(n)
        parts[label] = v
        if v > max_rows:
            raise ValueError('offline row budget')
        return v

    def child(native, **kwargs):
        nonlocal c
        fn = children.get(native)
        if fn is None:
            raise Unsupported(native, c, dict(parts))
        r = fn(data, c, **kwargs)
        if not isinstance(r, dict) or r.get('complete_child_wire') is False or r.get('state') == 'stopped':
            raise ValueError('Incomplete HUMAN child')
        n = r.get('end')
        parts.setdefault('children', []).append({'native': hex(native), 'start': c, 'end': n})
        if type(n) is not int or not c < n <= end:
            raise ValueError('invalid child end')
        c = n
    parts['cached_object_presence'] = u(1)
    take(1)
    take(44)
    n = count(4, 'national_reference_count')
    for _ in range(n):
        child(17924796)
    take(16)
    take(4)
    n = u(4)
    parts['stored_text_bytes'] = n
    take(n)
    parts['first_17e7c5c'] = c
    fn = child_17e7c5c.parse
    for _ in range(2):
        r = fn(data, c, source_major=source_major, minor=minor, limit=end)
        c = r['end']
    parts['after_17e7c5c_pair'] = c
    take(7)
    n = count(1, 'date_rows')
    take(8 * n)
    take(162)
    n = count(1, 'property_maps')
    for _ in range(n):
        child(71291360)
    n = count(2, 'pointer_records')
    for _ in range(n):
        child(22361480)
    for label in ('collection_110', 'collection_128'):
        n = count(2, label)
        for _ in range(n):
            child(23296716)
    for label in ('collection_170', 'collection_188', 'collection_1a0'):
        n = count(2, label)
        for _ in range(n):
            child(19636772)
    take(45)
    for label, native in [('collection_1d0', 21339936), ('collection_1e8', 21349604)]:
        n = count(4, label)
        for _ in range(n):
            child(native)
    parts['child_138eee4'] = c
    child(20508388)
    take(2)
    child(22376832)
    n = count(4, 'heap_10d8_references')
    for _ in range(n):
        child(17832956)
    parts['child_181d89c_version_word'] = u(4)
    parts['child_181d89c'] = c
    child(25286812)
    child(25784608)
    child(25784608)
    take(1)
    child(14194144)
    child(14194764)
    take(1)
    n = count(4, 'collection_2f0')
    for _ in range(n):
        child(20249672)
    take(34)
    take(1)
    presence = u(1)
    parts['property_348_presence'] = presence
    if presence not in (0, 1):
        raise ValueError('HUMAN property presence differs from current writer')
    if presence == 1:
        child(71291360)
    take(12)
    n = int.from_bytes(take(4), 'little', signed=True)
    parts['sparse_u16_count'] = n
    if n > max_rows:
        raise ValueError('offline sparse row budget')
    take(max(n, 0) * 2)
    parts['child_6e8330'] = c
    child(7242544)
    take(4)
    child(14489068)
    for label in ('heap_fe8', 'heap_1000'):
        n = int.from_bytes(take(1), 'little', signed=True)
        parts[label] = n
        for _ in range(max(n, 0)):
            take(1)
            child(19619928)
    take(16)
    n = int.from_bytes(take(4), 'little', signed=True)
    parts['heap_1078_count'] = n
    if n > max_rows:
        raise ValueError('offline vector budget')
    take(max(n, 0) * 4)
    for label in ('heap_1018', 'heap_1030'):
        n = int.from_bytes(take(1), 'little', signed=True)
        parts[label] = n
        for _ in range(max(n, 0)):
            take(1)
            child(19619928)
    n = int.from_bytes(take(1), 'little', signed=True)
    parts['compound_count'] = n
    if n > 0:
        child(19686488, count=n, limit=end, source_major=source_major, minor=minor)
    child(20006292)
    n = int.from_bytes(take(1), 'little', signed=True)
    parts['compound_property_rows'] = n
    if n > 0:
        raise Unsupported(19689596, c, dict(parts))
    n = count(4, 'fixed_u16_values')
    if n > 41:
        raise ValueError('native HUMAN count exceeds41')
    take(n * 2)
    take(4)
    child(23987108)
    take(3)
    n = count(4, 'heap_1048_count')
    for _ in range(n):
        take(4)
        child(24234184, limit=end, source_major=source_major, minor=minor)
    n = count(4, 'heap_1060_count')
    if n:
        child(19693192, count=n, limit=end, source_major=source_major, minor=minor)
    take(4)
    parts['fd0_auxiliary_u16'] = u(2)
    n = count(4, 'heap_fd0_count')
    if n:
        raise Unsupported(19694832, c, dict(parts))
    n = count(4, 'small_byte_values')
    if n > 3:
        raise ValueError('native HUMAN bytecount exceeds3')
    take(n)
    take(4 + 2 + 1)
    child(18627648)
    take(1)
    n = count(4, 'heap_f98_count')
    for _ in range(n):
        take(1)
        child(17846192)
        take(1)
    return {'end': c, 'parts': parts, 'complete_record': False, 'complete_human_specific_wire': True, 'next_native': 13141392}
    return {'end': c, 'parts': parts, 'complete_record': False}
