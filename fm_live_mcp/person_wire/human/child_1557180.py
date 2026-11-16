"""1557180 outer vector and bounded current writer-v6 1554AFC rows."""
import struct
RAW64 = {'stream_bit1': True, 'global_3522': 0, 'global_3523': 1, 'global_2c98': 0}
RAW32 = {**RAW64, 'global_2c98': 1}

class UnsupportedChild(ValueError):

    def __init__(self, native, offset):
        self.native = hex(native)
        self.offset = offset
        super().__init__(f'Unsupported nested {native:#x} at {offset}')

def parse(data, start, *, source_major=3754, minor=9, limit=None, reference_context=RAW64, max_rows=4096, max_refs=4096):
    if (source_major, minor) != (3754, 9) or reference_context not in (RAW64, RAW32):
        raise ValueError('Unsupported explicit source/reference context')
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or (not 0 <= start <= bound <= len(data)):
        raise ValueError('Invalid child bounds')
    if any((type(v) is not int or not 0 <= v <= 100000 for v in (max_rows, max_refs))):
        raise ValueError('Invalid work bound')
    at = start

    def take(n):
        nonlocal at
        if n > bound - at:
            raise ValueError('Truncated1557180/1554AFC')
        old = at
        at += n
        return bytes(data[old:at])

    def number(code):
        return struct.unpack('<' + code, take(struct.calcsize('<' + code)))[0]
    count = number('I')
    if count > max_rows or count > (bound - at) // 58:
        raise ValueError('1557180outer count exceeds bound')
    width = 8 if reference_context == RAW64 else 4
    rows = []
    refs_used = 0
    for ordinal in range(count):
        p = at
        version = number('h')
        if version != 6:
            raise ValueError('Only paired current writer rowversion6 supported')
        marker = number('B')
        if marker != 1:
            raise ValueError('Unsupported current writer rowmarker')
        packed = number('I')
        if packed & 8388608:
            raise UnsupportedChild(71289268, at)
        fields = {}
        for target, code in [(114, 'B'), (108, 'I'), (115, 'B'), (116, 'B'), (96, 'I'), (80, 'Q'), (100, 'I'), (88, 'Q'), (117, 'B'), (118, 'B'), (112, 'H'), (104, 'I')]:
            fields[hex(target)] = number(code)
        vectors = []
        for target in [0, 24, 48]:
            n = number('I')
            refs_used += n
            if refs_used > max_refs or n > (bound - at) // width:
                raise ValueError('1554AFCreference count exceeds bound')
            vectors.append({'native_field': hex(target), 'count': n, 'reference_raw_hex': [take(width).hex() for _ in range(n)]})
        rows.append({'ordinal': ordinal, 'start': p, 'end': at, 'version': version, 'discarded_marker': marker, 'packed_word_raw': packed, 'fields_raw': fields, 'reference_vectors': vectors})
    return {'start': start, 'end': at, 'count': count, 'rows': rows, 'native_reader': '0x1557180', 'row_reader': '0x1554afc', 'row_writer': '0x15545ac', 'reference_context': dict(reference_context), 'runtime_globals_proved': False, 'complete_child_wire': True, 'global_native_resource_limit_proved': False}
