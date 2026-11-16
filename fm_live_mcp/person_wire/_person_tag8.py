"""Tag8 SUPPORT_STAFF; native172E5BC/172E94C plus existing common codec."""
from . import _actual64_parse, _identity
import struct

def parse(data, start, *, ordinal, reference_mode='raw64', source_major=3754, minor=9, body_mode=1, read_base=1, limit=None):
    if (source_major, minor, body_mode, read_base, reference_mode) != (3754, 9, 1, 1, 'raw64') or any((type(v) is not int for v in (source_major, minor, body_mode, read_base))):
        raise ValueError('Unsupported explicit tag8 source context')
    limit = len(data) if limit is None else limit
    if type(start) is not int or type(limit) is not int or (not 0 <= start <= limit <= len(data)):
        raise ValueError('Invalid tag8 cursor/limit')
    if type(ordinal) is not int or not 0 <= ordinal < 10000000:
        raise ValueError('Invalid original PERSON ordinal')
    if limit - start < 6:
        raise ValueError('Truncated tag8 prefix')
    bounded = data if limit == len(data) else data[:limit]
    raw68, raw71, raw70 = struct.unpack_from('<IBB', bounded, start)
    shared = _actual64_parse
    common = shared.parse_common(bounded, start + 6, reference_mode='raw64', language_mode=0)
    common['prefix'].update(language_mode=None, language_string_retained=None, language_retention_state='unproved_runtime_mode_same_wire')
    canonical = _identity.parse_identity_base(bounded, common['end'], ordinal=ordinal)
    return {'start': start, 'end': canonical['end'], 'source_record_kind': 'SUPPORT_STAFF', 'native_reader': '0x172e5bc', 'native_writer': '0x172e94c', 'identity': canonical['identity'], 'names': [{k: n[k] for k in ('root_offset', 'original_reference_index', 'inline_marker', 'inline_record')} for n in common['prefix']['names']], 'native_fields': {'0x68_raw_reference_word_u32': raw68, '0x71_u8': raw71, '0x70_u8': raw70}, 'parts': {'specific_prefix': {'start': start, 'end': start + 6, 'raw_hex': bytes(bounded[start:start + 6]).hex()}, 'common': common, 'canonical': canonical}, 'complete_person': True, 'shared_common_occurrences': 1, 'shared_canonical_occurrences': 1, 'actual_person_body_present': False, 'reference_identity_resolved': False, 'native_loader_globals_observed': False, 'source_profile': {'source_major': source_major, 'minor': minor, 'body_mode': body_mode, 'read_base': read_base, 'common_reference_mode': 'raw64', 'prefix_native_local_2c98': 1}}
