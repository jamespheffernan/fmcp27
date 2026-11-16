"""Build-pinned wire reader for verified17FB938 subtype50.

No native execution. Preserve wire order/duplicate keys, opaque scalar bits and
source encodings. Registered variant callbacks are deliberately unsupported.
Budgets are parser limits, not native cardinalities. Parent source3754/minor9.
"""
SUBTYPES = frozenset((50,))
DIRECT_WIDTHS = {0: 0, 1: 4, 2: 4, 3: 1, 5: 8, 6: 0, 7: 0, 15: 8, 17: 1, 18: 2, 19: 1, 20: 2, 21: 4, 24: 8, 25: 4, 27: 8}

class UnsupportedVariant(ValueError):
    pass

class _Reader:

    def __init__(self, data, start, max_items, max_depth, max_text_bytes):
        self.data = data
        self.offset = start
        self.remaining = max_items
        self.max_items = max_items
        self.max_depth = max_depth
        self.max_text_bytes = max_text_bytes

    def take(self, n):
        if n > len(self.data) - self.offset:
            raise ValueError(f'Truncated180F218 at {self.offset}: need {n}')
        raw = bytes(self.data[self.offset:self.offset + n])
        self.offset += n
        return raw

    def u32(self):
        return int.from_bytes(self.take(4), 'little')

    def count(self):
        n = self.u32()
        if n > self.remaining:
            raise ValueError(f'180F218 item budget exceeded at {self.offset - 4}: {n}')
        self.remaining -= n
        return n

    def map(self, depth):
        if depth > self.max_depth:
            raise ValueError('180F218 recursion budget exceeded')
        start = self.offset
        n = self.count()
        rows = []
        for i in range(n):
            key = self.u32()
            value = self.variant(depth + 1)
            rows.append({'native_index': i, 'key_u32': key, 'value': value})
        return {'start': start, 'end': self.offset, 'count': n, 'rows': rows, 'native_reader': '0x43fd1e0'}

    def vector(self, depth):
        if depth > self.max_depth:
            raise ValueError('180F218 recursion budget exceeded')
        start = self.offset
        n = self.count()
        values = [self.variant(depth + 1) for _ in range(n)]
        return {'start': start, 'end': self.offset, 'count': n, 'values': values, 'native_reader': '0x43fd35c'}

    def variant(self, depth):
        if depth > self.max_depth:
            raise ValueError('180F218 recursion budget exceeded')
        start = self.offset
        version, tag = self.take(2)
        out = {'start': start, 'version': version, 'tag': tag, 'native_reader': '0x43fc9b4'}
        if tag in DIRECT_WIDTHS:
            out['payload_hex'] = self.take(DIRECT_WIDTHS[tag]).hex()
        elif tag == 10:
            out['map'] = self.map(depth + 1)
        elif tag == 11:
            out['vector'] = self.vector(depth + 1)
        elif tag == 26:
            n = self.u32()
            if n > self.max_text_bytes:
                raise ValueError(f'180F218 text budget exceeded: {n}')
            out['raw_bytes_hex'] = self.take(n).hex()
            out['byte_length'] = n
        else:
            raise UnsupportedVariant(f'Unsupported180F218 variant tag {tag} version {version} at {start}: native registered/atom callback required')
        out['end'] = self.offset
        return out

def parse(data, start, *, subtype, source_major=3754, minor=9, max_items=10000, max_depth=32, max_text_bytes=1048576):
    if (type(source_major), type(minor)) != (int, int) or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported180F218 source version')
    if type(subtype) is not int or subtype not in SUBTYPES:
        raise ValueError(f'Unsupported180F218 subtype {subtype}')
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid180F218 cursor')
    for value in (max_items, max_depth, max_text_bytes):
        if type(value) is not int or value < 0:
            raise ValueError('Invalid180F218 parser budget')
    reader = _Reader(data, start, max_items, max_depth, max_text_bytes)
    body = reader.map(0)
    return {'start': start, 'end': reader.offset, 'subtype': subtype, 'native_reader': '0x180f218', 'body': body, 'references_resolved': False}
