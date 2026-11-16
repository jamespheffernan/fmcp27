"""Current writer geometry for the two HUMAN profile vectors at native 1897120."""
import struct
_DETAIL_PREFIX = struct.Struct('<hIBIIIIIBBBH')
_DETAIL_TAIL = struct.Struct('<IBBIIIQHIIHIQ')
_DETAIL_SIZE = _DETAIL_PREFIX.size + 10 + _DETAIL_TAIL.size
_SECOND = struct.Struct('<hIII4H')

def parse(data, start, *, limit=None, source_major=3754, minor=9):
    if (type(source_major), type(minor)) != (int, int) or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported 1897120 source profile')
    limit = len(data) if limit is None else limit
    if type(start) is not int or type(limit) is not int or (not 0 <= start <= limit <= len(data)):
        raise ValueError('Invalid 1897120 cursor or exclusive bound')
    at = start

    def take(n):
        nonlocal at
        if n > limit - at:
            raise ValueError('Truncated 1897120 source')
        old = at
        at += n
        return old

    def u32():
        return struct.unpack_from('<I', data, take(4))[0]
    if u32() != 2:
        raise ValueError('Unsupported 1897120 container version')
    tables = []
    for name, width in [('first', _DETAIL_SIZE), ('second', _SECOND.size)]:
        count = u32()
        if count > 1000000:
            raise ValueError('1897120 offline row budget exceeded')
        head = take(count * width)
        for row in range(head, at, width):
            version, = struct.unpack_from('<h', data, row)
            if name == 'first':
                if version != 13 or data[row + _DETAIL_PREFIX.size] != 4:
                    raise ValueError('Unsupported 1894EB0 nested version')
            elif version != 2:
                raise ValueError('Unsupported 1898A10 second row version')
        tables.append(dict(vector=name, count=count, start=head, end=at, item_bytes=width))
    return dict(start=start, end=at, version=2, tables=tables, native_reader='0x1897120', native_writer='0x1896fe8', complete_component=True, native_allocation_limit_known=False)
