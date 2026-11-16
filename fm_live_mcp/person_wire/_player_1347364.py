"""Current writer-version31 PLAYER+118 child; explicit reference context."""
import struct

class UnsupportedChild(ValueError):

    def __init__(self, native, offset, parts):
        self.native, self.offset, self.parts = (native, offset, parts)
        super().__init__(f'Unsupported {native} at {offset}')

def parse(data, start, *, source_major=3754, minor=9, max_rows=4096, direct_references=None, row38_reader=None, embedded_reader=None, base_reader=None):
    if (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported source version')
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid child start')
    at = start
    parts = {}

    def take(n):
        nonlocal at
        if n < 0 or at + n > len(data):
            raise ValueError(f'Truncated1347364 at {at}')
        b = bytes(data[at:at + n])
        at += n
        return b

    def count():
        n = int.from_bytes(take(4), 'little')
        if n > max_rows:
            raise ValueError('1347364 row budget')
        return n

    def child(cb, native):
        nonlocal at
        if cb is None:
            raise UnsupportedChild(native, at, parts)
        r = cb(data, at)
        if not isinstance(r, dict) or type(r.get('end')) is not int or (not at < r['end'] <= len(data)):
            raise ValueError('Invalid1347364 callback cursor')
        at = r['end']
        return r
    version = struct.unpack('<h', take(2))[0]
    parts['version'] = version
    if version != 31:
        raise UnsupportedChild('1347364 legacy/future version', start, parts)
    parts['b6_raw'] = take(2).hex()
    n = count()
    parts['vector50_count'] = n
    parts['vector50'] = []
    for i in range(n):
        s = at
        v = struct.unpack('<h', take(2))[0]
        a = take(1).hex()
        b = take(4).hex()
        c = take(1).hex()
        if direct_references is not True:
            raise UnsupportedChild('1104908 reference profile (3522bit0 or3523==1 required)', at, parts)
        refs = take(8)
        tail = take(8)
        parts['vector50'].append({'start': s, 'end': at, 'version': v, 'field1c_raw': a, 'field18_raw': b, 'field1d_raw': c, 'references_raw': refs.hex(), 'tail_raw': tail.hex()})
    n = count()
    parts['vector38_count'] = n
    parts['vector38'] = []
    for i in range(n):
        parts['vector38'].append(child(row38_reader, '0x15739b8'))
    parts['scalar_tail_raw43'] = take(43).hex()
    parts['embedded68'] = child(embedded_reader, '0x13486e4')
    marker = take(1)[0]
    parts['optional80_presence'] = marker
    if marker == 1:
        parts['optional80'] = {'version': take(1)[0], 'raw16': take(16).hex()}
    parts['base'] = child(base_reader, '0xd8a570')
    return {'start': start, 'end': at, 'parts': parts, 'native_reader': '0x1347364', 'native_writer': '0x1348c40', 'native_reference_context_proved': False}
