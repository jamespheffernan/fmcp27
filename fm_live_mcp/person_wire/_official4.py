"""Bounded OFFICIAL source-tag4 body, supported full-writer raw64 profile.

Native PERSON+0x128 thunks target146C350/146CD84. The full-body branch ends
with CE96F0 common fields and1474F98 canonical identity; no ACTUAL_PERSON body
is inserted. Reference values and official-specific fields remain opaque.
"""
from . import _actual64_parse, _identity
import struct
MAX_VECTOR_WORDS = 65536
MAX_RECORD_BYTES = 1 << 20
_shared = _actual64_parse
_identity = _identity

class Cursor:

    def __init__(self, data, start):
        if type(start) is not int or not 0 <= start <= len(data):
            raise ValueError('Invalid OFFICIAL cursor')
        self.data, self.offset, self.start = (data, start, start)

    def take(self, size):
        if type(size) is not int or not 0 <= size <= len(self.data) - self.offset:
            raise ValueError(f'Truncated OFFICIAL at {self.offset}')
        if self.offset - self.start + size > MAX_RECORD_BYTES:
            raise ValueError('OFFICIAL record byte budget exhausted')
        start = self.offset
        self.offset += size
        return bytes(self.data[start:self.offset])

    def number(self, code):
        return struct.unpack('<' + code, self.take(struct.calcsize('<' + code)))[0]

def prefix(data, start, *, reference_mode='raw64'):
    if reference_mode != 'raw64':
        raise ValueError('Unproved OFFICIAL reference source profile')
    reader = Cursor(data, start)
    fields = {'0x68_reference_raw64': reader.take(8).hex()}
    for field in ('0x114', '0x116', '0x118'):
        fields[field] = reader.number('H')
    for field in range(282, 291):
        fields[hex(field)] = reader.number('B')
    ring_start = reader.offset
    count = reader.number('B')
    rows = []
    for index in range(count):
        at = reader.offset
        raw = reader.take(24)
        rows.append({'wire_ordinal': index, 'start': at, 'end': reader.offset, 'marker': raw[0], 'raw_payload23_hex': raw[1:].hex()})
    ring = {'start': ring_start, 'end': reader.offset, 'count': count, 'rows': rows}
    vectors = []
    for field in ('0x80', '0x98'):
        at = reader.offset
        size = reader.number('I')
        if size > MAX_VECTOR_WORDS:
            raise ValueError('OFFICIAL vector work budget exhausted')
        raw = reader.take(size * 4)
        vectors.append({'field': field, 'start': at, 'end': reader.offset, 'count': size, 'raw_u32_words': [value[0] for value in struct.iter_unpack('<I', raw)]})
    fields['0x110_raw4'] = reader.take(4).hex()
    fields['0x123'] = reader.number('B')
    return {'start': start, 'end': reader.offset, 'fields': fields, 'ring_b0': ring, 'vectors': vectors, 'pending_bytes': 0, 'native_reader': '0x146c350', 'next_native_reader': '0xce96f0'}

def parse(data, start, *, ordinal, reference_mode='raw64'):
    if type(ordinal) is not int or not 0 <= ordinal < 2000000:
        raise ValueError('Invalid OFFICIAL original ordinal')
    body = prefix(data, start, reference_mode=reference_mode)
    common = _shared.parse_common(data, body['end'], reference_mode='raw64', language_mode=0)
    common['prefix']['language_mode'] = None
    common['prefix']['language_string_retained'] = None
    common['prefix']['language_retention_state'] = 'unproved_runtime_mode_same_wire'
    canonical = _identity.parse_identity_base(data, common['end'], ordinal=ordinal)
    if canonical['end'] - start > MAX_RECORD_BYTES:
        raise ValueError('OFFICIAL record byte budget exhausted')
    return {'start': start, 'end': canonical['end'], 'source_record_kind': 'OFFICIAL', 'identity': canonical['identity'], 'names': [{key: name[key] for key in ('root_offset', 'original_reference_index', 'inline_marker', 'inline_record')} for name in common['prefix']['names']], 'parts': {'official': body, 'common': common, 'canonical': canonical}, 'source_profile': {'body_mode': 1, 'read_base': 1, 'reference_mode': reference_mode, 'runtime_factory_globals': 'unbound'}}
