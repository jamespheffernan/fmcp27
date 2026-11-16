"""Tag5 RETIRED_PERSON_NAME_STRINGS, source3754/body1/read_base1.

15C3D3C reads two43836A4 strings then1474F98 once. No ACTUAL_PERSON or
CE96F0 body exists in this subtype. References are not read or resolved.
"""
import struct

def parse(data, start, *, ordinal, reference_mode='raw64', source_major=3754, minor=9, body_mode=1, read_base=1, limit=None, max_string_bytes=8192):
    if (source_major, minor, body_mode, read_base, reference_mode) != (3754, 9, 1, 1, 'raw64'):
        raise ValueError('Unsupported explicit tag5 source context')
    if any((type(v) is not int for v in (source_major, minor, body_mode, read_base))):
        raise ValueError('Strict integer tag5 source context required')
    limit = len(data) if limit is None else limit
    if type(start) is not int or type(limit) is not int or (not 0 <= start <= limit <= len(data)):
        raise ValueError('Invalid tag5 cursor/limit')
    if type(ordinal) is not int or not 0 <= ordinal < 10000000:
        raise ValueError('Invalid original PERSON ordinal')
    if type(max_string_bytes) is not int or not 0 <= max_string_bytes <= 1000000:
        raise ValueError('Invalid tag5 string work budget')
    at = start

    def take(n):
        nonlocal at
        if n > limit - at:
            raise ValueError('Truncated tag5 record')
        raw = bytes(data[at:at + n])
        at += n
        return raw

    def text(native_offset):
        p = at
        n = struct.unpack('<I', take(4))[0]
        if n > max_string_bytes:
            raise ValueError('Tag5 string exceeds explicit work budget')
        raw = take(n)
        try:
            value = raw.decode('utf8')
            state = 'utf8'
        except UnicodeDecodeError:
            value = None
            state = 'unmapped_bytes'
        return {'start': p, 'end': at, 'native_offset': native_offset, 'byte_count': n, 'raw_hex': raw.hex(), 'text': value, 'text_state': state, 'null_vs_empty_distinguished': False}
    names = [text('0x20'), text('0x28')]
    canonical_start = at
    opaque = take(8)
    identity_start = at
    stored, native, secondary = struct.unpack('<III', take(12))
    if stored != ordinal:
        raise ValueError('Tag5 original PERSON ordinal mismatch')
    identity = {'offset': identity_start, 'stored_index': stored, 'native_id_word': native, 'secondary_word': secondary}
    return {'start': start, 'end': at, 'source_record_kind': 'RETIRED_PERSON_NAME_STRINGS', 'native_reader': '0x15c3d3c', 'native_writer': '0x15c3f48', 'identity': identity, 'stored_name_strings': names, 'names': None, 'parts': {'canonical': {'start': canonical_start, 'end': at, 'object_18_1f_raw': opaque.hex(), 'identity': identity}}, 'complete_person': True, 'shared_canonical_occurrences': 1, 'actual_person_body_present': False, 'common_person_body_present': False, 'source_profile': {'source_major': source_major, 'minor': minor, 'body_mode': body_mode, 'read_base': read_base}, 'reference_fields_present': False, 'native_loader_globals_observed': False}
