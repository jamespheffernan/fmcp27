"""1862C00 child of typed LOAN_CONTRACT+68; opaque fields, no base identity.

All seven vector counts are native u8. Row markers are ignored by the reader.
Version>=2 adds16EF9D8. Its positive reference rows require an explicit codec;
no reference width is inherited from the surrounding loan's raw64 parameter.
"""

class UnsupportedChild(ValueError):

    def __init__(self, message, *, native, offset, parts):
        self.native, self.offset, self.parts = (native, offset, parts)
        super().__init__(message)

def parse(data, start, *, source_major=3754, minor=9, limit=None, vector_a8_reader=None):
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported1862C00 source context')
    limit = len(data) if limit is None else limit
    if type(start) is not int or type(limit) is not int or (not 0 <= start <= limit <= len(data)):
        raise ValueError('Invalid1862C00 checked span')
    at = start
    parts = {}

    def take(n):
        nonlocal at
        if n > limit - at:
            raise ValueError(f'Truncated1862C00 at {at}: need {n}')
        raw = bytes(data[at:at + n])
        at += n
        return raw
    version = take(1)[0]
    vectors = []
    for native_offset, width in ((0, 7), (24, 6), (48, 6), (72, 6), (96, 6), (120, 14), (144, 31)):
        count = take(1)[0]
        begin = at
        raw = take(count * width)
        vectors.append(dict(native_offset=hex(native_offset), count=count, row_width=width, start=begin, end=at, raw_hex=raw.hex()))
    parts['vectors'] = vectors
    if version >= 2:
        begin = at
        if limit - at < 4:
            raise ValueError('Truncated1862C00+A8 count')
        count = int.from_bytes(data[at:at + 4], 'little')
        if count == 0:
            take(4)
            parts['vector_a8'] = {'start': begin, 'end': at, 'count': 0}
        elif vector_a8_reader is None:
            raise UnsupportedChild('Positive16EF9D8 needs explicit reference codec', native=24050136, offset=at, parts=parts)
        else:
            result = vector_a8_reader(memoryview(data)[:limit], at)
            if not isinstance(result, dict) or type(result.get('end')) is not int or (not at + 4 <= result['end'] <= limit):
                raise ValueError('Invalid1862C00+A8 child boundary')
            at = result['end']
            parts['vector_a8'] = result
    parts['tail_c0_c6_raw_hex'] = take(7).hex()
    return dict(start=start, end=at, version=version, parts=parts, complete=True, native_reader='0x1862C00', native_writer='0x18624F0', source_major=source_major, minor=minor, pending_bytes=0, references_resolved=False, scope='typed LOAN_CONTRACT+68 child only')
