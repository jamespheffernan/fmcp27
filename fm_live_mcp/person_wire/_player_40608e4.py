"""Type0 factory40608E4 wire, concrete vtable567CA68 reader+10."""

class UnsupportedChild(ValueError):

    def __init__(self, subtype, offset):
        self.native = '0x40608e4/type' + str(subtype)
        self.offset = offset
        super().__init__(f'Unsupported polymorphic PLAYER subtype{subtype} at{offset}')

def parse(data, start, *, subtype, source_major=3754, minor=9):
    if (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported source')
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid cursor')
    if type(subtype) is not int or subtype != 0:
        raise UnsupportedChild(subtype, start)
    if len(data) - start < 4:
        raise ValueError('Truncated type0 PLAYER child')
    b = bytes(data[start:start + 4])
    return {'start': start, 'end': start + 4, 'subtype': 0, 'native_reader': '0x406129c', 'native_writer': '0x406135c', 'vtable': '0x567ca68', 'field08_signed16': int.from_bytes(b[:2], 'little', signed=True), 'field0a_raw_u8': b[2], 'field0b_raw_u8': b[3], 'raw_hex': b.hex()}
