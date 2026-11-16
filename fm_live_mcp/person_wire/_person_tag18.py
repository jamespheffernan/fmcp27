"""Source tag18 AGENT; conditional current full-loader raw32 references."""
from . import _actual64_parse, _identity
import struct

def parse(data, start, *, ordinal, reference_mode='raw64', source_major=3754, minor=9, body_mode=1, read_base=1, limit=None, nation_reference_mode='raw32', max_rows=100000):
    if (source_major, minor, body_mode, read_base, reference_mode, nation_reference_mode) != (3754, 9, 1, 1, 'raw64', 'raw32') or any((type(v) is not int for v in (source_major, minor, body_mode, read_base))):
        raise ValueError('Unsupported explicit tag18 source/reference context')
    limit = len(data) if limit is None else limit
    if type(start) is not int or type(limit) is not int or (not 0 <= start <= limit <= len(data)):
        raise ValueError('Invalid tag18 cursor/limit')
    if type(ordinal) is not int or not 0 <= ordinal < 10000000:
        raise ValueError('Invalid original PERSON ordinal')
    if type(max_rows) is not int or not 0 <= max_rows <= 1000000:
        raise ValueError('Invalid tag18 vector work budget')
    bounded = data if limit == len(data) else data[:limit]
    at = start

    def take(n):
        nonlocal at
        if n > limit - at:
            raise ValueError('Truncated tag18 record')
        r = bytes(bounded[at:at + n])
        at += n
        return r

    def u32():
        return struct.unpack('<I', take(4))[0]
    raw_a0 = struct.unpack('<b', take(1))[0]
    scalars = take(6)
    raw_date = take(4)
    nation_start = at
    raw_nation = u32()
    count_at = at
    count = u32()
    if count > max_rows:
        raise ValueError('Tag18 PERSON vector exceeds explicit work budget')
    take(4 * count)
    people = None
    second_at = at
    second_count = u32()
    if second_count > max_rows or count + second_count > max_rows:
        raise ValueError('Tag18 combined vectors exceed explicit work budget')
    take(8 * second_count)
    second = None
    raw_ae = take(1)[0]
    specific_end = at
    shared = _actual64_parse
    common = shared.parse_common(bounded, at, reference_mode='raw64', language_mode=0)
    common['prefix'].update(language_mode=None, language_string_retained=None, language_retention_state='unproved_runtime_mode_same_wire')
    canonical = _identity.parse_identity_base(bounded, common['end'], ordinal=ordinal)
    return {'start': start, 'end': canonical['end'], 'source_record_kind': 'AGENT', 'native_reader': '0xd67980', 'native_writer': '0xd67ff8', 'identity': canonical['identity'], 'names': [{k: n[k] for k in ('root_offset', 'original_reference_index', 'inline_marker', 'inline_record')} for n in common['prefix']['names']], 'native_fields': {'0xa0_i8': raw_a0, '0xa8_ad_raw_hex': scalars.hex(), '0xa4_a7_raw_date_hex': raw_date.hex(), '0xae_u8': raw_ae}, 'nation_reference': {'start': nation_start, 'end': nation_start + 4, 'namespace': 'NATION', 'transport': 'conditional_full_loader_raw32', 'raw_word_u32': raw_nation, 'identity_resolved': False}, 'person_vector': {'count_offset': count_at, 'count': count, 'transport': 'PERSONraw32_scoped_local2c98_1', 'raw_reference_words': people, 'identities_resolved': False}, 'date_word_vector': {'count_offset': second_at, 'count': second_count, 'rows': second}, 'parts': {'specific_prefix': {'start': start, 'end': specific_end}, 'common': common, 'canonical': canonical}, 'complete_person': True, 'shared_common_occurrences': 1, 'shared_canonical_occurrences': 1, 'actual_person_body_present': False, 'native_loader_globals_observed': False, 'source_profile': {'source_major': source_major, 'minor': minor, 'body_mode': body_mode, 'read_base': read_base, 'common_reference_mode': 'raw64', 'specific_local2c98': 1, 'nation_reference_mode': nation_reference_mode}, 'reference_conditions': 'NATION11182BC fullstream flagsbit1 and(root80A bit0 OR root80B bit0), local2C98=1. Writer root808/809 raw-index branch separately requires global2AF8!=1 for4B. Runtime globals are unobserved.'}
