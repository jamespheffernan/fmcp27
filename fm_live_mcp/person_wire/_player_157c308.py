"""157C308/132F410 wire with two explicit locally-forced reference profiles.

Count/row transports are complete. The final1101BFC mode is not inferred from
outer raw64: direct32_local1 and compressed index16_local1 are separate bounded
alternatives. Native post-read filtering and reference resolution are not
applied to the preserved source rows.
"""
import struct

class BudgetExceeded(ValueError):

    def __init__(self, offset, count, max_rows):
        self.offset = offset
        self.reader = 22528776
        self.native = '0x157c308'
        self.partial = {'count': count, 'max_rows': max_rows, 'offline_budget': True}
        self.count = count
        self.max_rows = max_rows
        super().__init__('157C308 row work budget exhausted; source branch remains unresolved')

class Reader:

    def __init__(self, data, start):
        if type(start) is not int or not 0 <= start <= len(data):
            raise ValueError('Invalid157C308 cursor')
        self.data, self.at = (data, start)

    def take(self, count):
        if count < 0 or count > len(self.data) - self.at:
            raise ValueError('Truncated157C308 child')
        raw = bytes(self.data[self.at:self.at + count])
        self.at += count
        return raw

    def number(self, fmt):
        return struct.unpack('<' + fmt, self.take(struct.calcsize('<' + fmt)))[0]

def parse_row(data, start):
    """132F410; all256 version bytes, preserving legacy pre-normalization byte."""
    r = Reader(data, start)
    version = r.number('B')
    fields = {}
    fields['0xc'] = r.take(2).hex()
    fields['0x0'] = r.take(4).hex()
    legacy = None
    if version >= 2:
        fields['0x4'] = r.take(4).hex()
        if version >= 5:
            fields['0x8'] = r.take(4).hex()
        if version >= 3:
            fields['0xe'] = r.take(1).hex()
            fields['0xf'] = r.take(1).hex()
        else:
            legacy = r.number('b')
        if version >= 4:
            fields['0x10'] = r.take(1).hex()
    return {'start': start, 'end': r.at, 'version': version, 'matches_current_paired_writer_version': version == 5, 'native_fields_raw': fields, 'stored_tag_u16': struct.unpack('<H', bytes.fromhex(fields['0xc']))[0], 'legacy_signed_byte': legacy, 'legacy_normalization': '1342824/134284C not applied; preserve source byte' if legacy is not None else None, 'raw_hex': bytes(data[start:r.at]).hex(), 'complete_row_wire': True}

def parse(data, start, *, source_version=3754, global_source_version=3754, minor=9, body_mode=1, read_base=0, reference_mode='raw64', person_reference_profile='direct32_local1', stream_bit1=True, max_rows=4096):
    expected = (3754, 3754, 9, 1, 0)
    values = (source_version, global_source_version, minor, body_mode, read_base)
    if any((type(v) is not int for v in values)) or values != expected:
        raise ValueError('Unsupported157C308 source profile')
    if reference_mode not in ('raw64', 'raw32', 'index32'):
        raise ValueError('Unsupported157C308 outer reference context')
    if stream_bit1 is not True:
        raise ValueError('Unclosed157C308 tagged/inline reference profile')
    if person_reference_profile not in ('direct32_local1', 'index16_local1'):
        raise ValueError('Explicit157C308 local reference profile required')
    if type(max_rows) is not int or max_rows < 0:
        raise ValueError('Invalid157C308 work budget')
    r = Reader(data, start)
    version = r.number('B')
    count = r.number('I')
    minimum_ref = 4 if person_reference_profile == 'direct32_local1' else 2
    if count * 7 + minimum_ref > len(data) - r.at:
        raise ValueError('157C308 population exceeds physical remaining source')
    if count > max_rows:
        raise BudgetExceeded(r.at, count, max_rows)
    rows = []
    for _ in range(count):
        row = parse_row(data, r.at)
        r.at = row['end']
        rows.append(row)
    reference_start = r.at
    if person_reference_profile == 'direct32_local1':
        word = r.number('I')
        reference = {'raw_word_u32': word, 'stored_index': None, 'meaning': 'opaque direct stored4; no numeric ID interpretation', 'conditions': 'streambit1 set, localC98=1, and3522==1 or3523bit0 set'}
    else:
        short = r.number('h')
        index = r.number('i') if short == -2 else short
        if short == -2 and index < 0 or (short != -2 and index < 0 and (index != -1)):
            raise ValueError('Native11031C0 rejects negative original index other than null-1')
        reference = {'stored_index': index, 'short_marker': short, 'meaning': 'compressed original index; lookup/container validity remains unresolved', 'conditions': 'streambit1 set,3522!=1 and3523bit0 clear;11031C0 w4=0'}
    reference.update(start=reference_start, end=r.at, raw_hex=bytes(data[reference_start:r.at]).hex(), resolved=False)
    return {'start': start, 'end': r.at, 'consumed_bytes': r.at - start, 'version': version, 'matches_current_paired_writer_version': version == 1, 'count': count, 'rows': rows, 'person_reference': reference, 'person_reference_profile': person_reference_profile, 'local_reference_switch': 1, 'parent_reference_mode': reference_mode, 'raw_hex': bytes(data[start:r.at]).hex(), 'complete_child_wire': True, 'complete_parent_body': False, 'native_reader': '0x157c308', 'native_writer': '0x157c14c', 'native_object_normalization': 'post-read tag filtering/remapping and legacy transforms not applied', 'native_allocation_limit': '56C1628 count guard not inferred; physical bounds and explicit offline work budget used', 'writer_width_limit': '1101624 compact route1101350 has additionalAF8 override; writer equivalence conditional', 'next_parent_field': 'CONTRACT_OFFER1007F6C array-presence byte'}

def rebuild(result):
    return bytes([result['version']]) + struct.pack('<I', result['count']) + b''.join((bytes.fromhex(row['raw_hex']) for row in result['rows'])) + bytes.fromhex(result['person_reference']['raw_hex'])
