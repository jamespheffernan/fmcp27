"""Bounded145D2C8 NON_PLAYER+98 vector; writer145D170.

145D84C row version controls byte-position retention; all source bytes/order are
preserved. Raw fields remain unmapped. No references or nested child calls.
"""
import struct

def parse(data, start, *, source_major=3754, minor=9, max_count=4096):
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid145D2C8 cursor')
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported145D2C8 source profile')
    if type(max_count) is not int or not 0 <= max_count <= 1000000:
        raise ValueError('Invalid145D2C8 reader limit')
    at = start

    def take(n):
        nonlocal at
        if n > len(data) - at:
            raise ValueError(f'Truncated145D2C8 at{at}: need{n}')
        raw = bytes(data[at:at + n])
        at += n
        return raw
    count = struct.unpack('<I', take(4))[0]
    if count > max_count:
        raise ValueError(f'145D2C8 count{count} exceeds readerlimit{max_count}')
    if count > (len(data) - at) // 48:
        raise ValueError('Truncated145D2C8 minimum row extent')
    rows = []
    for index in range(count):
        row_start = at
        version = take(1)[0]
        logical_positions = 47 if version < 4 else 45
        fields = []
        discarded = []
        wire_fields = bytearray()
        removed = 0
        for position in range(logical_positions):
            if version <= 2 and (position == 9 or 31 <= position <= 37):
                continue
            raw = take(1)[0]
            wire_fields.append(raw)
            if version == 3 and position in (1, 2):
                discarded.append({'logical_index': position, 'raw_u8': raw})
                removed += 1
            else:
                native = position - removed if version == 3 else position
                fields.append({'native_offset': native, 'raw_u8': raw})
        tail30 = take(4)
        tail34 = take(4)
        rows.append({'native_index': index, 'start': row_start, 'end': at, 'version': version, 'logical_byte_positions': logical_positions, 'native_byte_fields': fields, 'discarded_byte_fields': discarded, 'wire_byte_fields_hex': wire_fields.hex(), 'raw_30_hex': tail30.hex(), 'raw_34_hex': tail34.hex(), 'raw_hex': bytes(data[row_start:at]).hex()})
    return {'start': start, 'end': at, 'count': count, 'rows': rows, 'native_reader': '0x145d2c8', 'native_row_reader': '0x145d84c', 'native_writer': '0x145d170', 'source_major': source_major, 'minor': minor, 'complete_child_wire': True, 'matches_current_writer_versions': all((r['version'] == 4 for r in rows)), 'references_consumed': False, 'semantic_fields_resolved': False}

def rebuild(result):
    if result['count'] != len(result['rows']):
        raise ValueError('145D2C8 reconstruction count mismatch')
    return struct.pack('<I', result['count']) + b''.join((bytes((row['version'],)) + bytes.fromhex(row['wire_byte_fields_hex']) + bytes.fromhex(row['raw_30_hex']) + bytes.fromhex(row['raw_34_hex']) for row in result['rows']))
