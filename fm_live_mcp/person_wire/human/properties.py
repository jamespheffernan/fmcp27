from ... import saved_properties

class Reader:

    def __init__(self, data, start, limit):
        self.data = data
        self.offset = start
        self.limit = limit

    def take(self, n):
        if n < 0 or n > self.limit - self.offset:
            raise ValueError('Truncated HUMAN property map')
        at = self.offset
        self.offset += n
        return bytes(self.data[at:self.offset])

    def skip(self, n):
        if n < 0 or n > self.limit - self.offset:
            raise ValueError('Truncated HUMAN property map')
        self.offset += n

    def u8(self):
        return int.from_bytes(self.take(1), 'little')

    def u32(self):
        return int.from_bytes(self.take(4), 'little')

def parse(data, start, *, limit=None):
    limit = len(data) if limit is None else limit
    if not 0 <= start <= limit <= len(data):
        raise ValueError('Invalid HUMAN property extent')
    r = Reader(data, start, limit)
    saved_properties.skip_property_map(r)
    return {'start': start, 'end': r.offset, 'native_reader': '0x43fd1e0', 'property_semantics_reported': False}

def parse_variant(data, start, *, limit=None):
    limit = len(data) if limit is None else limit
    if not 0 <= start <= limit <= len(data):
        raise ValueError('Invalid HUMAN property value extent')
    r = Reader(data, start, limit)
    saved_properties._Walker(r).variant(0)
    return {'start': start, 'end': r.offset, 'native_reader': '0x43fc9b4', 'property_semantics_reported': False, 'complete_child_wire': True}
