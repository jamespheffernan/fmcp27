"""Bounded current1459F20/1459C60 property record, no semantic ID projection."""

class Unsupported(ValueError):

    def __init__(self, native, offset, parts):
        self.native, self.offset, self.parts = (native, offset, parts)
        super().__init__(f'Unproved1459F20 child {native:#x} at {offset}')

def parse(data, start, *, source_major=3754, minor=9, limit=None, variant_reader=None):
    if (type(source_major), type(minor)) != (int, int) or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported1459F20 source')
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or (not 0 <= start <= bound <= len(data)):
        raise ValueError('Invalid1459F20 extent')
    at = start

    def take(n):
        nonlocal at
        if n > bound - at:
            raise ValueError('Truncated1459F20')
        before = at
        at += n
        return before

    def u32():
        before = take(4)
        return int.from_bytes(data[before:at], 'little')
    version = u32()
    if version != 10:
        raise Unsupported(21339936, start, {'version': version})
    marker = data[take(1)]
    flags = u32()
    variant = None
    if flags & 8388608:
        if variant_reader is None:
            raise Unsupported(71289268, at, {'version': version, 'flags': flags})
        variant = variant_reader(data, at, limit=bound)
        end = variant.get('end')
        if type(end) is not int or not at < end <= bound:
            raise ValueError('Invalid progressing property value')
        at = end
    counts = []
    n = u32()
    if n > (bound - at) // 4:
        raise ValueError('Truncated1459F20 first raw4 vector')
    take(n * 4)
    counts.append(n)
    take(6)
    n = u32()
    if n > (bound - at) // 4:
        raise ValueError('Truncated1459F20 second raw4 vector')
    take(n * 4)
    counts.append(n)
    take(5)
    return {'start': start, 'end': at, 'version': version, 'ignored_marker': marker, 'flags': flags, 'raw4_vector_counts': counts, 'variant_present': variant is not None, 'complete_child_wire': True, 'native_reader': '0x1459f20', 'native_field_meanings_resolved': False}
