"""1279724 FULL_CONTRACT current-source raw64 candidate branch.

The caller independently establishes source3754/minor9 and the raw64 reference
profile. Nonempty derived vectors requiring further helpers fail explicitly;
no runtime clause filtering, reference resolution or contract labels are used.
"""
import struct

class UnsupportedFullContract(ValueError):

    def __init__(self, message, *, native=None, offset=None):
        super().__init__(message)
        if native is not None:
            self.native = native
        if offset is not None:
            self.offset = offset

def parse_prefix(data, start, *, reference_mode, source_major=3754, minor=9, max_discarded_rows=10000, row80_reader=None, vector98_reader=None):
    if (type(source_major), type(minor)) != (int, int) or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported FULL_CONTRACT source')
    if reference_mode != 'raw64':
        raise ValueError('FULL_CONTRACT requires separately established raw64 reference profile')
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid FULL_CONTRACT cursor')
    if type(max_discarded_rows) is not int or max_discarded_rows < 0:
        raise ValueError('Invalid FULL_CONTRACT work budget')
    at = start

    def take(n):
        nonlocal at
        if n > len(data) - at:
            raise ValueError(f'Truncated FULL_CONTRACT at {at}: need {n}')
        raw = bytes(data[at:at + n])
        at += n
        return raw

    def u(n):
        return int.from_bytes(take(n), 'little')
    c3 = u(1)
    a8 = take(16)
    refstart = at
    reference = take(8)
    c2 = u(1)
    c0 = u(2)
    clauses = u(1)
    clause_rows = [take(8).hex() for _ in range(clauses)]
    count80 = u(1)
    rows80 = []
    if count80 and row80_reader is None:
        raise UnsupportedFullContract(f'Nonempty FULL_CONTRACT+80 requires132418C at {at}', native=20070796, offset=at)
    for index in range(count80):
        child_start = at
        row = row80_reader(data, at)
        if not isinstance(row, dict) or type(row.get('end')) is not int or (not at < row['end'] <= len(data)):
            raise ValueError('Invalid FULL_CONTRACT+80 row progress')
        at = row['end']
        rows80.append({'native_index': index, 'start': child_start, 'end': at, 'parsed': row})
    presence98 = u(1)
    vector98 = None
    if presence98 == 1:
        if vector98_reader is None:
            raise UnsupportedFullContract(f'Present FULL_CONTRACT+98 requires1279E3C/1116FA4 at {at}', native=19373628, offset=at)
        vector98 = vector98_reader(data, at)
        if type(vector98.get('end')) is not int or not at < vector98['end'] <= len(data):
            raise ValueError('Invalid FULL_CONTRACT+98 vector boundary')
        at = vector98['end']
    discarded = u(4)
    if discarded > max_discarded_rows:
        raise ValueError('FULL_CONTRACT discarded-row work budget')
    discard_raw = take(discarded * 31).hex()
    c4 = u(1)
    a8words = struct.unpack('<IIIHH', a8)
    result = {'start': start, 'end': at, 'native_reader': '0x1279724', 'reference_mode': reference_mode, 'fields': {'c3_raw_u8': c3, 'a8_raw_u32': a8words[0], 'ac_raw_u32': a8words[1], 'b0_raw_u32': a8words[2], 'b4_raw_u16': a8words[3], 'b6_raw_u16': a8words[4], 'a0_reference_wire': {'start': refstart, 'end': refstart + 8, 'hex': reference.hex(), 'resolution_state': 'unresolved_raw64_transport'}, 'c2_raw_u8': c2, 'c0_raw_u16': c0, 'c4_raw_u8': c4}, 'clause_wire_count': clauses, 'clause_raw_rows': clause_rows, 'runtime_clause_normalization_applied': False, 'count_80': count80, 'presence_98': presence98, 'discarded_31byte_count': discarded, 'discarded_raw_hex': discard_raw, 'next_native': '0xfe4470', 'complete_full_contract': False}
    if vector98 is not None:
        result['vector98'] = vector98
    if count80:
        result['rows80_raw'] = rows80
        result['runtime_rows80_retention_state'] = 'unproved_native_post_read_filter'
    return result

def parse(data, start, *, reference_mode, extra_reader=None, base_reader=None, row80_reader=None, vector98_reader=None, source_major=3754, minor=9):
    prefix = parse_prefix(data, start, reference_mode=reference_mode, source_major=source_major, minor=minor, row80_reader=row80_reader, vector98_reader=vector98_reader)
    if extra_reader is None and base_reader is None:
        return prefix
    if extra_reader is None or base_reader is None:
        raise ValueError('Both FULL_CONTRACT child callbacks are required')
    extra = extra_reader(data, prefix['end'])
    if type(extra.get('end')) is not int or not prefix['end'] <= extra['end'] <= len(data):
        raise ValueError('Invalid FE4470 callback boundary')
    base = base_reader(data, extra['end'])
    if type(base.get('end')) is not int or not extra['end'] <= base['end'] <= len(data):
        raise ValueError('Invalid FE4904 callback boundary')
    return {'start': start, 'end': base['end'], 'native_reader': '0x1279724', 'reference_mode': reference_mode, 'prefix': prefix, 'extra': extra, 'base': base, 'pending_bytes': 0, 'complete_full_contract': True, 'next_native': '0xca8220_slot_continuation', 'references_resolved': False}
