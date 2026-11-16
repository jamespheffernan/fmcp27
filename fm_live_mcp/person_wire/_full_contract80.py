"""One native132418C row; incoming count and outgoing presence belong to caller."""
import struct

def parse(data, start, *, source_major=3754, minor=9):
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported FULL_CONTRACT+80 source')
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid FULL_CONTRACT+80 cursor')
    if len(data) - start < 31:
        raise ValueError('Truncated FULL_CONTRACT+80 row')
    raw = bytes(data[start:start + 31])
    version, field00, field14, field18, field1c, discarded, field08, field0c, field10, field04, field1e = struct.unpack('<HIIIHB IIBIB'.replace(' ', ''), raw)
    return {'start': start, 'end': start + 31, 'native_reader': '0x132418c', 'stored_header_u16': version, 'discarded_wire_u8': discarded, 'fields': {'00_u32': field00, '14_u32': field14, '18_u32': field18, '1c_u16': field1c, '08_u32': field08, '0c_u32': field0c, '10_u8': field10, '04_u32': field04, '1e_u8': field1e}, 'raw_hex': raw.hex(), 'pending_bytes': 0, 'scope': 'wire only; no field labels, identities or native retention filtering'}
