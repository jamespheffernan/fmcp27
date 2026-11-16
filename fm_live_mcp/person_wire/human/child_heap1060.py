"""Current HUMAN heap1060 inline rows,12C7F50/12CF3CC; raw namespaces only."""

class Unsupported(ValueError):

    def __init__(self, native, offset):
        self.native, self.offset = (native, offset)
        super().__init__(f'Unproved heap1060 child {native:#x} at{offset}')

def parse(data, start, *, count, limit=None, source_major=3754, minor=9, variant_reader=None, max_rows=4096):
    if (type(source_major), type(minor)) != (int, int) or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported source')
    if type(count) is not int or not 0 <= count <= max_rows:
        raise ValueError('Offline row work budget')
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or (not 0 <= start <= bound <= len(data)):
        raise ValueError('Invalid bounds')
    at = start
    variants = 0
    word_count = 0

    def take(n):
        nonlocal at
        if n < 0 or n > bound - at:
            raise ValueError('Truncated heap1060')
        a = at
        at += n
        return data[a:at]

    def number(n):
        return int.from_bytes(take(n), 'little')
    for _ in range(count):
        take(2)
        packed = number(4)
        if packed & 1 << 23:
            if variant_reader is None:
                raise Unsupported(71289268, at)
            r = variant_reader(data, at, limit=bound)
            end = r.get('end')
            if type(end) is not int or not at < end <= bound:
                raise ValueError('Invalid bounded variant')
            at = end
            variants += 1
        n = number(4)
        if n > (bound - at) // 4:
            raise ValueError('Truncated counted raw4 vector')
        take(n * 4)
        word_count += n
    return dict(start=start, end=at, complete_child_wire=True, count=count, variant_count=variants, raw_word_count=word_count, field_namespaces_resolved=False, runtime_global_capacity_observed=False)
