"""One inline PLAYER+F0/+50 body beginning at native11E9524.

The parent owns presence and subsequent +58 parsing. This is not a callable
native function: pool-allocation branches join immediately before the payload.
Only the explicit bit1-set stream, locally forced56D2C98=1 profile is closed.
Parent raw64 is deliberately not used to select these reference widths.
"""
import struct

def parse(data, start, *, source_major=3754, minor=9, reference_mode='raw64', stream_bit1=True):
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid PLAYER+F0/+50 cursor')
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported PLAYER+F0/+50 source profile')
    if reference_mode not in ('raw32', 'raw64'):
        raise ValueError('Unsupported parent reference profile')
    if stream_bit1 is not True:
        raise ValueError('Unclosed tagged/inline1117820 stream profile')
    if 17 > len(data) - start:
        raise ValueError('Truncated PLAYER+F0/+50 body')
    raw = bytes(data[start:start + 17])
    version = raw[0]
    return {'start': start, 'end': start + 17, 'consumed_bytes': 17, 'version': version, 'version_native_use': 'read_then_discarded', 'matches_current_paired_writer_version': version == 1, 'native_04_raw_hex': raw[1:5].hex(), 'references': [{'native_offset': '0x8', 'start': start + 5, 'end': start + 9, 'raw_hex': raw[5:9].hex(), 'raw_word_u32': struct.unpack_from('<I', raw, 5)[0]}, {'native_offset': '0x10', 'start': start + 9, 'end': start + 13, 'raw_hex': raw[9:13].hex(), 'raw_word_u32': struct.unpack_from('<I', raw, 9)[0]}], 'native_00_03_raw_hex': raw[13:17].hex(), 'native_00_03_raw_u16': list(struct.unpack_from('<HH', raw, 13)), 'raw_hex': raw.hex(), 'parent_reference_mode': reference_mode, 'local_reference_wire_bytes': 4, 'local_reference_switch': 1, 'stream_bit1': True, 'compact_vs_index_reference_mode': 'not_selected_by_this_codec', 'reference_identity_resolution': 'opaque stored words; no numeric ID interpretation', 'native_reader_span': '0x11e9524..0x11e9620', 'native_writer_span': '0x11eaa78..0x11eab54', 'complete_child_wire': True, 'complete_player_body': False, 'next_native_boundary': '0x11e9434 reads following optional+58 marker'}

def rebuild(result):
    """Reproduce reader-consumed bytes without normalizing version or fields."""
    return bytes([result['version']]) + bytes.fromhex(result['native_04_raw_hex']) + b''.join((bytes.fromhex(r['raw_hex']) for r in result['references'])) + bytes.fromhex(result['native_00_03_raw_hex'])
