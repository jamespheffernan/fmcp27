"""GAME_COMP_STATS+1260 inline rows, current paired tagged TEAM subset only.

F3AFF0..F3B3D0 reads TEAM then21 u16 fields. F396B8..F39A20 writes
TEAM(mode0) then the same memory+08..30 words. No RTTI-backed row class,
field names, date semantics or resolved TEAM identities are inferred.
"""
import struct

CTX = {'stream_bit1': True, 'global_3522': 0, 'global_3523': 1, 'global_2c98': 1}
NATIVE_OFFSETS = tuple(range(8, 0x32, 2))
CURRENT_ROW_BYTES = 47


class UnsupportedRow(ValueError):
    def __init__(self, native, offset, reason):
        self.native, self.offset = native, offset
        super().__init__(f'Unsupported +1260 inline row {hex(native)} at {offset}: {reason}')


def bounds(data, start, limit, reference_context):
    if reference_context != CTX or any(type(reference_context.get(k)) is not type(v) for k, v in CTX.items()):
        raise ValueError('Explicit conditional +1260 reference profile required')
    limit = len(data) if limit is None else limit
    if type(start) is not int or type(limit) is not int or not 0 <= start <= limit <= len(data):
        raise ValueError('Invalid bounded +1260 row')
    return limit


def parse(data, start, *, limit=None, reference_context):
    limit = bounds(data, start, limit, reference_context)
    if start == limit:
        raise ValueError('Truncated +1260 TEAM marker')
    marker = data[start]
    if marker != 0:
        raise UnsupportedRow(0x11073A8 if marker == 2 else 0x11019A0, start,
                             'Only current paired-writer mode0 TEAM marker0 is supported')
    if CURRENT_ROW_BYTES > limit - start:
        raise ValueError('Truncated +1260 inline row')
    index = struct.unpack_from('<i', data, start + 1)[0]
    if index < -1:
        raise UnsupportedRow(0x11019A0, start, 'Native negative original TEAM index rejects')
    raw = bytes(data[start + 5:start + CURRENT_ROW_BYTES])
    words = struct.unpack('<21H', raw)
    return {'start': start, 'end': start + CURRENT_ROW_BYTES,
            'team': {'start': start, 'end': start + 5, 'marker': marker, 'original_index': index,
                     'native_reader': '0x11019a0', 'reference_resolved': False},
            'raw_fields': [{'native_offset': hex(offset), 'raw_u16': value,
                            'raw_hex': raw[i * 2:i * 2 + 2].hex()}
                           for i, (offset, value) in enumerate(zip(NATIVE_OFFSETS, words, strict=True))],
            'raw42_hex': raw.hex(), 'complete_row_wire': True,
            'native_reader_inline': '0xf3aff0..0xf3b3d0',
            'native_writer_inline': '0xf396b8..0xf39a20',
            'native_allocation_bytes': 0x38, 'reference_profile_is_conditional': True,
            'native_loader_acceptance': False, 'field_meanings_resolved': False}


def parse_rows(data, start, count, *, limit=None, reference_context, max_rows=4096):
    limit = bounds(data, start, limit, reference_context)
    if type(count) is not int or count < 0 or type(max_rows) is not int or not 0 <= max_rows <= 4096:
        raise ValueError('Invalid +1260 row budget/count')
    if count > max_rows:
        raise UnsupportedRow(0xF3AD30, start, 'Offline row work budget exceeded')
    if count * CURRENT_ROW_BYTES > limit - start:
        raise ValueError('Bounded +1260 population exceeds source extent')
    at = start
    rows = []
    for ordinal in range(count):
        row = parse(data, at, limit=limit, reference_context=reference_context)
        rows.append({'ordinal': ordinal, **row})
        at = row['end']
    return {'start': start, 'end': at, 'count': count, 'rows': rows,
            'complete_collection_wire': True, 'native_loader_acceptance': False}
