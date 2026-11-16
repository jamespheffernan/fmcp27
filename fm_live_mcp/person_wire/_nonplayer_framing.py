"""Conditional ACTUAL_NON_PLAYER wire, never establishes loader mode by itself."""
import struct

class UnsupportedChild(ValueError):

    def __init__(self, native, offset, partial):
        self.native, self.offset, self.partial = (native, offset, partial)
        super().__init__(f'Unproved child {native:#x} at {offset}')

class Reader:

    def __init__(self, data, start):
        if type(start) is not int or not 0 <= start <= len(data):
            raise ValueError('Invalid cursor')
        self.data, self.at = (data, start)

    def raw(self, n):
        if n < 0 or n > len(self.data) - self.at:
            raise ValueError('Truncated conditional nonplayer')
        at = self.at
        b = bytes(self.data[at:at + n])
        self.at += n
        return {'start': at, 'end': self.at, 'raw_hex': b.hex()}

    def num(self, c):
        return struct.unpack('<' + c, bytes.fromhex(self.raw(struct.calcsize('<' + c))['raw_hex']))[0]

def prefix(data, start, *, reference_word_bytes, source_major=3754):
    if type(reference_word_bytes) is not int or reference_word_bytes not in (4, 8) or source_major != 3754:
        raise ValueError('Explicit source3754/reference width required')
    r = Reader(data, start)
    count = r.num('h')
    if count > 4096:
        raise ValueError('Role pair research bound')
    rows = [r.raw(7) for _ in range(max(count, 0))]
    fixed = r.raw(19)
    version = r.num('B')
    attributes = r.raw(52 if version > 9 else 51)
    fixed_b8 = r.raw(8)
    refs = [r.raw(reference_word_bytes) for _ in range(2)]
    fixed_c0 = r.raw(8)
    fixed_e7 = r.raw(7)
    fixed_c8 = r.raw(8)
    at = r.at
    marker = r.num('B')
    return {'start': start, 'end': r.at, 'source_major': source_major, 'reference_word_bytes': reference_word_bytes, 'conditional_type': 'ACTUAL_NON_PLAYER', 'first_role_pair_count': count, 'role_pair_rows': rows, 'native_d4_e6_raw': fixed, 'attributes_version': version, 'raw_attribute_inputs': attributes, 'native_b8_bf_raw': fixed_b8, 'raw_10ff49c_words': refs, 'native_c0_c7_raw': fixed_c0, 'native_e7_ed_raw': fixed_e7, 'native_c8_cf_raw': fixed_c8, 'b0_marker': marker, 'b0_marker_offset': at, 'next_native': '0x1363ea4' if marker == 1 else 'next optional+78 marker', 'complete_body': False, 'complete_person': False}

def remainder(data, start, *, children):
    """Starts after+B0 child; each supplied child is separately proved."""
    r = Reader(data, start)
    rows = []
    for target, native in ((120, 15652944), (144, 14145428), (168, 21375900), (88, 21371048), (112, 14198128), (152, 21353160)):
        at = r.at
        marker = r.num('B')
        row = {'target': hex(target), 'marker_offset': at, 'marker': marker}
        if marker == 1:
            child = children.get(native)
            if child is None:
                raise UnsupportedChild(native, r.at, rows + [row])
            result = child(data, r.at)
            if not isinstance(result, dict) or type(result.get('end')) is not int or (not r.at < result['end'] <= len(data)):
                raise ValueError('Invalid child progress')
            r.at = result['end']
            row['child'] = result
        rows.append(row)
    final = r.raw(7)
    return {'start': start, 'end': r.at, 'optionals': rows, 'raw_ee_f4': final, 'next_native': '0xca7d88', 'complete_nonplayer_specific_wire': True, 'complete_person': False}
