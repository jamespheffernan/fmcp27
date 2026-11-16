"""NON_PLAYER+78 collection EED850, excluding parent presence byte.

Parent establishes source3754/minor9, body1/read-base1 and its reference profile.
This subtree stores packed words only; it never selects or resolves a reference
mode. Bit23 inline-value transport43FC9B4 remains an explicit unsupported edge.
"""

class Reader:

    def __init__(self, data, start):
        if type(start) is not int or not 0 <= start <= len(data):
            raise ValueError('Invalid nonplayer78 start')
        self.data = data
        self.pos = start

    def take(self, n):
        if n < 0 or n > len(self.data) - self.pos:
            raise ValueError(f'Truncated nonplayer78 at{self.pos} need{n}')
        b = self.data[self.pos:self.pos + n]
        self.pos += n
        return b

    def u(self, n):
        return int.from_bytes(self.take(n), 'little')

def _leaf(r):
    start = r.pos
    version = r.u(1)
    field2c = r.u(1)
    field2d = r.u(1)
    marker = r.u(1)
    word = r.u(4)
    if word & 1 << 23:
        raise ValueError(f'Unsupported nonplayer78 inline43FC9B4 at{r.pos}')
    fields = {'0x20_23_raw': r.take(4).hex(), '0x24_raw4': r.take(4).hex(), '0x28_raw_u32': r.u(4)}
    return {'start': start, 'end': r.pos, 'version': version, 'field2c_raw': field2c, 'field2d_raw': field2d, 'packed_marker': marker, 'packed_word': word, 'inline_bit23': False, 'fields': fields, 'native_reader': '0xeed0d0'}

def parse(data, start, *, source_major=3754, minor=9):
    if (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported nonplayer78 source')
    r = Reader(data, start)
    count = r.u(1)
    rows = [_leaf(r) for _ in range(count)]
    return {'start': start, 'end': r.pos, 'count': count, 'rows': rows, 'native_reader': '0xeed850', 'native_leaf_reader': '0xeed0d0', 'paired_leaf_writer': '0xeececc', 'next_parent_field': 'NON_PLAYER+90 presence (not consumed)', 'reference_identity_resolved': False}
