"""Current12BA224 wrapper and48947C8-v18 bounded forward orchestration.

Opaque variable children require real callbacks. Skipped rows are not retained.
"""

class Unsupported(ValueError):

    def __init__(self, native, offset, parts):
        self.native, self.offset, self.parts = (native, offset, parts)
        super().__init__(f'Unproved12BA224 child {native:#x} at {offset}')

class BudgetExceeded(ValueError):
    pass

def parse_aux_vector(data, start, *, limit=None, source_major=3754, minor=9):
    """493A9E4 fresh vector: signedi32 count and count*25 physical bytes."""
    bound = len(data) if limit is None else limit
    if (source_major, minor) != (3754, 9) or not 0 <= start <= bound <= len(data):
        raise ValueError('Unsupported493A9E4 extent/source')
    if bound - start < 4:
        raise ValueError('Truncated493A9E4 count')
    count = int.from_bytes(data[start:start + 4], 'little', signed=True)
    if count < 0:
        raise ValueError('493A9E4 negative count traps for fresh zero-capacity vector')
    if count > (bound - start - 4) // 25:
        raise ValueError('Truncated493A9E4 fixed25B rows')
    return {'start': start, 'end': start + 4 + count * 25, 'count': count, 'complete_child_wire': True, 'native_reader': '0x493a9e4', 'native_normalization_applied': False}

def parse_d0(data, start, *, limit=None, source_major=3754, minor=9, max_rows=65536):
    """4891648: u32 count; each row u8+raw4+u32 count+raw4[n]."""
    bound = len(data) if limit is None else limit
    if (source_major, minor) != (3754, 9) or not 0 <= start <= bound <= len(data):
        raise ValueError('Unsupported4891648 extent/source')
    at = start
    inner_total = 0

    def take(n):
        nonlocal at
        if n > bound - at:
            raise ValueError('Truncated4891648')
        before = at
        at += n
        return before

    def count():
        before = take(4)
        return int.from_bytes(data[before:at], 'little')
    n = count()
    if n > max_rows:
        raise BudgetExceeded('Offline4891648 outer-row budget; not native rejection')
    if n > (bound - at) // 9:
        raise ValueError('Truncated4891648 minimum row extent')
    for _ in range(n):
        take(5)
        inner = count()
        if inner > (bound - at) // 4:
            raise ValueError('Truncated4891648 raw4 vector')
        take(inner * 4)
        inner_total += inner
    return {'start': start, 'end': at, 'count': n, 'inner_wire_entries': inner_total, 'complete_child_wire': True, 'native_reader': '0x4891648', 'native_tree_dedup_applied': False}

def parse_e8(data, start, *, limit=None, source_major=3754, minor=9):
    """4892510: u32 byte count, then exactly that many opaque bytes."""
    bound = len(data) if limit is None else limit
    if (source_major, minor) != (3754, 9) or not 0 <= start <= bound <= len(data):
        raise ValueError('Unsupported4892510 extent/source')
    if bound - start < 4:
        raise ValueError('Truncated4892510 count')
    count = int.from_bytes(data[start:start + 4], 'little')
    if count > bound - start - 4:
        raise ValueError('Truncated4892510 byte vector')
    return {'start': start, 'end': start + 4 + count, 'count': count, 'complete_child_wire': True, 'native_reader': '0x4892510'}

def parse(data, start, *, limit=None, source_major=3754, minor=9, child_readers=None, max_rows=65536):
    if (type(source_major), type(minor)) != (int, int) or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported12BA224 source')
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or (not 0 <= start <= bound <= len(data)):
        raise ValueError('Invalid12BA224 extent')
    if type(max_rows) is not int or max_rows < 0:
        raise ValueError('Invalid12BA224 work bound')
    children = {} if child_readers is None else dict(child_readers)
    children.setdefault(76093000, parse_d0)
    children.setdefault(76096784, parse_e8)
    at = start
    parts = {'start': start}

    def take(n):
        nonlocal at
        if n > bound - at:
            raise ValueError('Truncated12BA224/48947C8')
        before = at
        at += n
        return before

    def u32():
        before = take(4)
        return int.from_bytes(data[before:at], 'little')

    def child(native, **kwargs):
        nonlocal at
        fn = children.get(native)
        if fn is None:
            raise Unsupported(native, at, dict(parts))
        result = fn(data, at, limit=bound, source_major=source_major, minor=minor, **kwargs)
        end = result.get('end')
        if result.get('complete_child_wire', result.get('complete_owned_child')) is not True or type(end) is not int or (not at < end <= bound):
            raise ValueError('Invalid progressing complete12BA224 child')
        previous = at
        at = end
        return {'native': hex(native), 'start': previous, 'end': end}
    outer = data[take(1)]
    if outer != 1:
        raise Unsupported(19636772, start, {'outer_version': outer})
    container_start = at
    version = u32()
    parts['container_start'] = container_start
    parts['container_version'] = version
    if version != 18:
        raise Unsupported(76105672, container_start, dict(parts))
    count = u32()
    parts['count'] = count
    parts['completed_rows'] = 0
    if count > max_rows:
        raise BudgetExceeded('Offline12BA224 row budget; not native rejection')
    row_start = at
    for _ in range(count):
        child(76068268, container_version=18)
        parts['completed_rows'] += 1
    parts['counted_rows_start'] = row_start
    parts['counted_rows_end'] = at
    vectors = []
    for _ in range(2):
        result = parse_aux_vector(data, at, limit=bound, source_major=source_major, minor=minor)
        vectors.append(result)
        at = result['end']
    parts['auxiliary_vectors'] = vectors
    take(20)
    parts['settings_50'] = child(76102004)
    parts['settings_90'] = child(76102004)
    take(1)
    parts['settings_d0'] = child(76093000)
    parts['settings_e8'] = child(76096784)
    take(2)
    parts['container_end'] = at
    take(9)
    return {'start': start, 'end': at, 'parts': parts, 'complete_child_wire': True, 'native_reader': '0x12ba224', 'container_reader': '0x48947c8', 'semantics_resolved': False}
