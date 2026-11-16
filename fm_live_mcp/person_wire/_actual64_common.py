"""Partial common PERSON transport readers. No inferred starting cursor."""
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
        try:
            text = bytes(b).decode('utf8')
        except UnicodeDecodeError:
            text = None
        return {'raw_hex': b.hex(), 'text': text, 'valid_utf8': text is not None}

def _context(source_version, global_source_version, global_minor, body_mode, read_base, reference_mode):
    if (source_version, global_source_version, global_minor, body_mode, read_base, reference_mode) != (3754, 3754, 9, 1, 0, 'raw64'):
        raise ValueError('unsupported explicit PERSON context')

def _name(r, mode):
    start = r.offset
    index = r.num('i')
    marker = r.num('B')
    inline = None
    if marker == 1:
        text = r.text()
        stored_index, nation_raw, field_0e, local_region_raw, field_12, field_13 = struct.unpack('<IiHIBB', r.take(16))
        inline = {'name': text, 'stored_index': stored_index, 'nation_reference_raw': nation_raw, 'object_0e': field_0e, 'local_region_reference_raw': local_region_raw, 'object_12': field_12, 'object_13': field_13}
    return {'start': start, 'end': r.offset, 'mode': mode, 'root_offset': ['0xc8', '0xd0', '0xd8'][mode], 'original_reference_index': index, 'inline_marker': marker, 'inline_record': inline, 'resolved_name': None, 'resolution_state': 'requires same-file name collection state and native inline deduplication'}

def parse_prefix(data, start, *, source_version, global_source_version, global_minor, body_mode, read_base, reference_mode, language_mode):
    """CE96F0 entry through optional14CD728 marker; child remains unconsumed."""
    _context(source_version, global_source_version, global_minor, body_mode, read_base, reference_mode)
    if type(language_mode) is not int or not 0 <= language_mode <= 255:
        raise ValueError('explicit language mode required')
    r = Reader(data, start)
    names = [_name(r, i) for i in range(3)]
    language = r.text()
    scalar = r.take(14)
    ref38 = r.take(8).hex()
    attributes = r.take(8)
    ref50 = r.take(8).hex()
    marker = r.num('B')
    return {'start': start, 'end': r.offset, 'complete_body': False, 'names': names, 'language_string': language, 'language_mode': language_mode, 'language_string_retained': language_mode not in range(1, 5), 'object_58_65_raw': scalar.hex(), 'object_38_reference_raw64_hex': ref38, 'object_40_47_attributes_raw': attributes.hex(), 'object_50_reference_raw64_hex': ref50, 'optional_48_presence': marker, 'next_native_reader': '0x14cd728' if marker == 1 else 'CE9ACC (read optional+8 marker)'}

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

def parse_after_optional48(data, start, *, source_version=3754, optional48_complete=False):
    """CE9A9C/CE9ACC continuation, only after child completion or absent marker."""
    if source_version != 3754 or optional48_complete is not True:
        raise ValueError('explicit completed optional48 handoff required')
    r = Reader(data, start)
    marker = r.num('B')
    rows = []
    count = None
    if marker == 1:
        count = r.num('b')
        for _ in range(max(0, count)):
            rows.append({'tag': r.num('B'), 'text': r.text(), 'raw_word': r.num('I')})
    return {'start': start, 'end': r.offset, 'optional_08_presence': marker, 'native_signed_row_count': count, 'rows': rows, 'complete_common_body': True, 'next_native_reader': 'caller or1474F98 if read_base is enabled'}

def parse_optional48(data, start, *, global_source_version=3754, retention_mode=None):
    """Complete14CD728 modern callback, independent of retain/discard mode."""
    if global_source_version != 3754 or retention_mode not in [None, 0, 1]:
        raise ValueError('unsupported optional48 context')
    r = Reader(data, start)
    n = r.num('B')
    if n > 125:
        raise ValueError('native optional48 first count limit')
    first = [r.take(16).hex() for _ in range(n)]
    m = r.num('i')
    if not 0 <= m <= 100000:
        raise ValueError('optional48 second count research bound')
    second = [r.take(7).hex() for _ in range(m)]
    scalar = r.take(3).hex()
    k = r.num('B')
    last = []
    for _ in range(k):
        at = r.offset
        tag = r.num('B')
        word = r.num('H')
        byte = r.num('B')
        raw = r.take(4)
        last.append({'start': at, 'tag': tag, 'object_08_u16': word, 'object_0a_u8': byte, 'payload_raw_hex': raw.hex(), 'payload_kind': 'raw4' if tag & 1 else 'u32', 'payload_u32': struct.unpack('<I', raw)[0]})
    final = r.num('B')
    return {'start': start, 'end': r.offset, 'first_count': n, 'first_16byte_raw_rows': first, 'second_count': m, 'second_7byte_raw_rows': second, 'object_49_4a_48_raw': scalar, 'third_count': k, 'third_rows': last, 'object_4b_u8': final, 'retention_mode': retention_mode, 'native_third_rows_retained': None if retention_mode is None else retention_mode == 1, 'complete_callback': True}

def parse_common_body(data, start, **context):
    """Complete body for explicit modern context; canonical base stays separate."""
    prefix = parse_prefix(data, start, **context)
    at = prefix['end']
    child = None
    if prefix['optional_48_presence'] == 1:
        child = parse_optional48(data, at)
        at = child['end']
    tail = parse_after_optional48(data, at, optional48_complete=True)
    return {'start': start, 'end': tail['end'], 'prefix': prefix, 'optional48': child, 'tail': tail, 'complete_common_body': True, 'canonical_identity_included': False}
