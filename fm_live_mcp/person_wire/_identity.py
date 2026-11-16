import struct

class Reader:

    def __init__(self, data, start):
        if type(start) is not int or not 0 <= start <= len(data):
            raise ValueError('invalid start')
        self.data = data
        self.offset = start

    def take(self, n):
        if n < 0 or n > len(self.data) - self.offset:
            raise ValueError('truncated PERSON common body')
        b = self.data[self.offset:self.offset + n]
        self.offset += n
        return b

    def num(self, c):
        return struct.unpack('<' + c, self.take(struct.calcsize('<' + c)))[0]

    def text(self):
        n = self.num('I')
        if n > 8192:
            raise ValueError('name/text research bound')
        b = self.take(n)
        return {'raw_hex': b.hex(), 'text': bytes(b).decode('utf8')}

def parse_identity_base(data, start, *, ordinal):
    """1474F98: opaque8 then three canonical identity words,20 wire bytes."""
    if type(ordinal) is not int or not 0 <= ordinal < 10000000:
        raise ValueError('invalid ordinal')
    r = Reader(data, start)
    opaque = r.take(8)
    at = r.offset
    index, primary, secondary = struct.unpack('<III', r.take(12))
    if index != ordinal:
        raise ValueError('original PERSON ordinal mismatch')
    return {'start': start, 'end': r.offset, 'object_18_1f_raw': opaque.hex(), 'identity': {'offset': at, 'stored_index': index, 'native_id_word': primary, 'secondary_word': secondary}}
