"""Bounded raw current-writer child shared by HUMAN_NON_PLAYER objects."""
import struct

def parse(data, start, *, limit=None, source_major=3754, minor=9):
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported source profile')
    limit = len(data) if limit is None else limit
    if type(start) is not int or type(limit) is not int or (not 0 <= start <= limit <= len(data)):
        raise ValueError('Invalid child cursor')
    if limit - start < 13:
        raise ValueError('Truncated 16E03A4 header')
    if data[start] != 7:
        raise ValueError('Unsupported 16E03A4 current source version')
    present = data[start + 12]
    if present not in (0, 1):
        raise ValueError('Invalid 16DFF34 current writer presence')
    at = start + 13
    count = None
    if present:
        if limit - at < 4:
            raise ValueError('Truncated 16E03A4 count')
        count, = struct.unpack_from('<I', data, at)
        at += 4
        if count > 1000000:
            raise ValueError('Offline 16E03A4 row budget exceeded')
        size = 14 * count
        if size > limit - at:
            raise ValueError('Truncated 16E03A4 items')
        for row in range(at, at + size, 14):
            if data[row] != 4:
                raise ValueError('Unsupported 16DFF34 item version')
        at += size
    return dict(start=start, end=at, version=7, stored_fields_hex=bytes(data[start + 1:start + 12]).hex(), optional_present=bool(present), count=count, row_wire_size=14, native_reader='0x16e03a4', native_writer='0x16dff34')
