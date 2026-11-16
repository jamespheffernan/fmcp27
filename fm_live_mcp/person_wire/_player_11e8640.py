"""Inline F0+30 subtree; caller consumes presence and owns following+38 marker.

Native reader11E8640..11E88DC, current writer11EA0F8..11EA31C.
No references are consumed; parent reference mode is not a wire-width oracle.
"""
CHUNKS = ((12, 4), (8, 4), (16, 4), (24, 4), (28, 4), (32, 4), (20, 4), (36, 2))
TAIL = ((39, 1), (4, 4), (38, 1), (0, 4), (40, 1))

def parse(data, start, *, source_major=3754, minor=9, reference_mode='raw64'):
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid inline F0+30 cursor')
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported inline F0+30 source')
    if reference_mode not in ('raw32', 'raw64'):
        raise ValueError('Unsupported parent reference context')
    at = start

    def take(n):
        nonlocal at
        if n > len(data) - at:
            raise ValueError(f'Truncated inline F0+30 at {at}')
        raw = bytes(data[at:at + n])
        at += n
        return raw
    version = take(1)[0]
    chunks = []
    for offset, width in CHUNKS:
        old = at
        raw = take(width)
        chunks.append({'native_offset': hex(offset), 'start': old, 'end': at, 'raw_hex': raw.hex()})
    discarded = take(1)[0] if version <= 3 else None
    for offset, width in TAIL:
        old = at
        raw = take(width)
        chunks.append({'native_offset': hex(offset), 'start': old, 'end': at, 'raw_hex': raw.hex()})
    return {'start': start, 'end': at, 'version': version, 'chunks': chunks, 'legacy_discarded_u8': discarded, 'raw_hex': bytes(data[start:at]).hex(), 'native_reader': '0x11e8640', 'native_continuation': '0x11e88e0', 'native_writer': '0x11ea0f8', 'references_consumed': False, 'complete_inline_wire': True, 'complete_player_body': False, 'semantic_fields_resolved': False, 'pending_bytes': 0}
