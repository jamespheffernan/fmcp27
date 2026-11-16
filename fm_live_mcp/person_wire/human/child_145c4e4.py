"""Current145C4E4 primitive/string record; string contents remain opaque."""

class Unsupported(ValueError):

    def __init__(self, version, offset):
        self.native, self.offset, self.parts = (21349604, offset, {'version': version})
        super().__init__(f'Unsupported145C4E4 version {version}')

def parse(data, start, *, source_major=3754, minor=9, limit=None):
    if (type(source_major), type(minor)) != (int, int) or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported145C4E4 source')
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or (not 0 <= start <= bound <= len(data)):
        raise ValueError('Invalid145C4E4 extent')
    at = start

    def take(n):
        nonlocal at
        if n > bound - at:
            raise ValueError('Truncated145C4E4')
        before = at
        at += n
        return before

    def number(n):
        before = take(n)
        return int.from_bytes(data[before:at], 'little')
    version = number(2)
    if version != 1:
        raise Unsupported(version, start)
    take(8)
    text_length = number(4)
    take(text_length)
    count = number(4)
    if count > (bound - at) // 4:
        raise ValueError('Truncated145C4E4 raw4 vector')
    take(count * 4)
    take(8)
    return {'start': start, 'end': at, 'version': version, 'stored_text_bytes': text_length, 'raw4_vector_count': count, 'complete_child_wire': True, 'native_reader': '0x145c4e4', 'field_meanings_resolved': False}
