"""Complete scalar embedded13486E4 wire; no vectors or variable references.

The first u32 is a stored reference index (paired writer takes object+8),
not a native numeric ID. Its transport is always four bytes. Parent owns its
resolution and all subsequent fields. Current paired writer emits version2.
"""
import struct

def parse(data, start, *, source_major=3754, minor=9):
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid embedded13486E4 cursor')
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported embedded13486E4 source profile')
    at = start
    chunks = []

    def take(size, native_offset, *, discarded=False):
        nonlocal at
        if size > len(data) - at:
            raise ValueError('Truncated embedded13486E4 body')
        raw = bytes(data[at:at + size])
        chunks.append({'start': at, 'end': at + size, 'native_offset': native_offset, 'discarded_legacy': discarded, 'raw_hex': raw.hex()})
        at += size
        return raw
    version = take(1, None)[0]
    first = take(4, '0x0')
    second = take(4, '0x8')
    if version <= 1:
        take(4, None, discarded=True)
    field10 = take(1, '0x10')[0]
    if version <= 1:
        take(2, None, discarded=True)
    final = take(4, '0xc')
    if version <= 1:
        take(1, None, discarded=True)
    return {'start': start, 'end': at, 'consumed_bytes': at - start, 'version': version, 'matches_current_paired_writer_version': version == 2, 'stored_reference_index_i32': struct.unpack('<i', first)[0], 'native_00_raw_hex': first.hex(), 'native_08_raw_hex': second.hex(), 'native_10_u8': field10, 'native_0c_raw_hex': final.hex(), 'chunks': chunks, 'raw_hex': bytes(data[start:at]).hex(), 'native_reader': '0x13486e4', 'paired_writer_inline_span': '0x13490c4..0x13491ac', 'reference_transport': 'fixed4 original index; no helper-selected raw32/raw64 width', 'reference_resolution': 'requires parent fixup/container context', 'complete_embedded_wire': True, 'complete_parent_body': False, 'next_native_boundary': '0x1348024 optional parent+80 presence marker'}

def rebuild(result):
    return b''.join((bytes.fromhex(chunk['raw_hex']) for chunk in result['chunks']))
