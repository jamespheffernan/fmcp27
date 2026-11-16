"""Inline PLAYER+F0/+48 payload;13-byte explicit local-source profile.

11E9354 is an interior payload entry, not a standalone callable function.
The parent consumes the bit0 presence marker and resumes at following+50.
No native function, allocation, date conversion or reference resolution occurs.
"""
import struct

def parse(data, start, *, source_major=3754, minor=9, reference_mode='raw64', stream_bit1=True, limit=None):
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported PLAYER+F0/+48 source profile')
    if reference_mode not in ('raw32', 'raw64'):
        raise ValueError('Unsupported parent reference profile')
    if stream_bit1 is not True:
        raise ValueError('Unproved tagged/inline1117820 stream profile')
    limit = len(data) if limit is None else limit
    if type(start) is not int or type(limit) is not int or (not 0 <= start <= limit <= len(data)):
        raise ValueError('Invalid bounded PLAYER+F0/+48 cursor')
    if limit - start < 13:
        raise ValueError('Truncated PLAYER+F0/+48 payload')
    raw = bytes(data[start:start + 13])
    version = raw[0]
    return {'start': start, 'end': start + 13, 'consumed_bytes': 13, 'version': version, 'version_native_use': 'read_then_discarded', 'matches_current_paired_writer_version': version == 1, 'native_04_raw_hex': raw[1:5].hex(), 'native_04_raw_u32': struct.unpack_from('<I', raw, 1)[0], 'reference': {'native_offset': '0x8', 'start': start + 5, 'end': start + 9, 'raw_hex': raw[5:9].hex(), 'raw_word_u32': struct.unpack_from('<I', raw, 5)[0]}, 'native_00_03_raw_hex': raw[9:13].hex(), 'native_00_03_raw_u16': list(struct.unpack_from('<HH', raw, 9)), 'raw_hex': raw.hex(), 'parent_reference_mode': reference_mode, 'stream_bit1': True, 'local_reference_switch': 1, 'local_reference_wire_bytes': 4, 'reference_identity_resolution': 'opaque stored word; no native ID or table membership assigned', 'native_payload_entry': '0x11e9354', 'native_reader_span': '0x11e9354..0x11e9428', 'native_writer_span': '0x11ea980..0x11eaa3c', 'next_native_boundary': '0x11e926c reads following optional+50 presence', 'native_globals_observed': False, 'complete_child_wire': True, 'complete_player_body': False, 'semantic_fields_resolved': False}

def rebuild(result):
    return bytes([result['version']]) + bytes.fromhex(result['native_04_raw_hex']) + bytes.fromhex(result['reference']['raw_hex']) + bytes.fromhex(result['native_00_03_raw_hex'])
