"""JOURNALIST tag6 under the checked source3754/minor9 writer profile.

1361738/1361C08 serialize a class-specific eight-byte prefix, followed by the
shared PERSON common body and canonical base exactly once. The local reference
uses the independently checked direct32/local1 geometry; the common body keeps
its separate conditional raw64 profile. Ambient loader globals are unobserved.
"""
import struct

from . import _actual64_common, _identity


def parse(data, start, *, ordinal, limit=None, source_major=3754, minor=9,
          reference_mode='raw64', local_reference_profile='direct32_local1'):
    if (type(source_major) is not int or type(minor) is not int
            or (source_major, minor, reference_mode) != (3754, 9, 'raw64')
            or local_reference_profile != 'direct32_local1'):
        raise ValueError('Unsupported JOURNALIST reference/source profile')
    limit = len(data) if limit is None else limit
    if (type(start) is not int or type(limit) is not int
            or not 0 <= start <= limit <= len(data)):
        raise ValueError('Invalid JOURNALIST cursor or exclusive limit')
    if type(ordinal) is not int or not 0 <= ordinal < 2_000_000:
        raise ValueError('Invalid original JOURNALIST ordinal')
    if limit - start < 8:
        raise ValueError('Truncated JOURNALIST class prefix')
    bounded = data if limit == len(data) else data[:limit]
    raw_fields = bytes(bounded[start:start + 3])
    local_word = struct.unpack_from('<I', bounded, start + 3)[0]
    raw71 = bounded[start + 7]
    common = _actual64_common.parse_common_body(
        bounded, start + 8, source_version=3754, global_source_version=3754,
        global_minor=9, body_mode=1, read_base=0, reference_mode='raw64',
        language_mode=0,
    )
    if (common['prefix']['optional_48_presence'] not in (0, 1)
            or common['tail']['optional_08_presence'] not in (0, 1)):
        raise ValueError('JOURNALIST common presence differs from current writer')
    common['prefix'].update(
        language_mode=None, language_string_retained=None,
        language_retention_state='unproved_runtime_mode_same_wire',
    )
    base = _identity.parse_identity_base(bounded, common['end'], ordinal=ordinal)
    return {
        'start': start, 'end': base['end'], 'identity': base['identity'],
        'source_record_kind': 'JOURNALIST',
        'names': [{key: row[key] for key in (
            'root_offset', 'original_reference_index', 'inline_marker', 'inline_record')}
            for row in common['prefix']['names']],
        'native_fields': {
            'native70_72_73_raw_hex': raw_fields.hex(),
            'native71_raw_u8': raw71,
            'local_reference_word_u32': local_word,
        },
        'reference_conditions': {
            'class_local': 'conditional_direct32_local1',
            'common': 'conditional_raw64', 'identities_resolved': False,
            'ambient_loader_globals_observed': False,
        },
        'parts': {'specific_prefix': {'start': start, 'end': start + 8},
                  'common': common, 'canonical': base},
    }
