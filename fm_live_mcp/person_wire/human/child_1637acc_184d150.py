"""Opaque fixed-width native child; current paired-writer profile only."""
import struct
FIELDS = ((16, 4), (20, 4), (24, 4), (28, 4), (32, 4), (0, 8), (36, 1), (37, 1), (40, 4), (8, 8), (44, 4), (48, 1), (52, 4))
WIRE_BYTES = 53

def parse(data, start, *, limit=None, source_major=3754, minor=9, reference_context=None):
    if (source_major, minor) != (3754, 9):
        raise ValueError('184D150 unsupported source profile')
    if type(start) is not int or start < 0:
        raise ValueError('184D150 invalid start')
    bound = len(data) if limit is None else limit
    if type(bound) is not int or not start <= bound <= len(data):
        raise ValueError('184D150 invalid limit')
    if bound - start < 2:
        raise ValueError(f'184D150 truncated version at {start}')
    version = struct.unpack_from('<h', data, start)[0]
    if version != 3:
        raise ValueError(f'184D150 unsupported writer version {version} at {start}')
    if bound - start < WIRE_BYTES:
        raise ValueError(f'184D150 truncated fixed body at {start + 2}')
    cursor = start + 2
    fields = []
    for destination, width in FIELDS:
        wire = bytes(data[cursor:cursor + width])
        fields.append({'native_destination': hex(destination), 'start': cursor, 'end': cursor + width, 'raw_hex': wire.hex()})
        cursor += width
    return {'start': start, 'end': cursor, 'version': version, 'fields': fields, 'native_reader': '0x184d150', 'native_writer': '0x184cf14', 'state': 'current_writer_fixed_width_child', 'field_semantics': 'unresolved'}
