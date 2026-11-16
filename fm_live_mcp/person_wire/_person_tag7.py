"""VIRTUAL_PLAYER source tag7; native18A4644/18A485C, no generation."""
import struct

def parse(data, start, *, ordinal, reference_mode='raw64', source_major=3754, minor=9, body_mode=1, read_base=1, limit=None):
    if (source_major, minor, body_mode, read_base, reference_mode) != (3754, 9, 1, 1, 'raw64') or any((type(v) is not int for v in (source_major, minor, body_mode, read_base))):
        raise ValueError('Unsupported explicit tag7 source context')
    limit = len(data) if limit is None else limit
    if type(start) is not int or type(limit) is not int or (not 0 <= start <= limit <= len(data)):
        raise ValueError('Invalid tag7 cursor/limit')
    if type(ordinal) is not int or not 0 <= ordinal < 10000000:
        raise ValueError('Invalid original PERSON ordinal')
    at = start

    def take(n):
        nonlocal at
        if n > limit - at:
            raise ValueError('Truncated tag7 record')
        r = bytes(data[at:at + n])
        at += n
        return r
    flags = struct.unpack('<H', take(2))[0]
    raw10 = take(4)
    raw18 = struct.unpack('<H', take(2))[0]
    raw1a = take(1)[0]
    raw08 = struct.unpack('<I', take(4))[0]
    optional_start = at
    raw0c = struct.unpack('<I', take(4))[0] if flags & 1 << 9 else None
    canonical_start = at
    opaque = take(8)
    identity_start = at
    stored, native, secondary = struct.unpack('<III', take(12))
    if stored != ordinal:
        raise ValueError('Tag7 original PERSON ordinal mismatch')
    identity = {'offset': identity_start, 'stored_index': stored, 'native_id_word': native, 'secondary_word': secondary}
    return {'start': start, 'end': at, 'source_record_kind': 'VIRTUAL_PLAYER', 'native_reader': '0x18a4644', 'native_writer': '0x18a485c', 'identity': identity, 'names': None, 'native_fields': {'0x16_u16_flags_raw': flags, '0x10_13_raw_hex': raw10.hex(), '0x18_u16': raw18, '0x1a_u8': raw1a, '0x08_u32_raw': raw08}, 'optional_0c': {'present': bool(flags & 1 << 9), 'start': optional_start, 'end': canonical_start, 'raw_word_u32': raw0c}, 'parts': {'canonical': {'start': canonical_start, 'end': at, 'object_18_1f_raw': opaque.hex(), 'identity': identity}}, 'complete_person': True, 'shared_canonical_occurrences': 1, 'actual_person_body_present': False, 'common_person_body_present': False, 'generated_profile_read_or_created': False, 'native_loader_globals_observed': False, 'source_profile': {'source_major': source_major, 'minor': minor, 'body_mode': body_mode, 'read_base': read_base}, 'post_load_flag_mutation_applied': False, 'semantic_fields_resolved': False, 'reference_identity_resolved': False}
