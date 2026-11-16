"""Bounded siblings following saved form groups (153E56C/F0+58).

151F710 rows use current writer151F4F0 version2/parameter7/tail0.
155007C rows use tagged TEAM marker0+u32 and PERSON u32 under the declared
conditional full-loader profile. No references, field meanings or native
runtime globals are resolved. No evidence modules are imported.
"""
import struct

REFERENCE_PROFILE = 'full_loader_tagged_team_index32_person_index32'
MAX_ROWS = 4096
MAX_NESTED_ITEMS = 32768


class _Reader:
    def __init__(self, data, start, limit):
        if (type(start) is not int or type(limit) is not int or
                not 0 <= start <= limit <= len(data)):
            raise ValueError('Invalid bounded saved form tail')
        self.data, self.offset, self.limit = data, start, limit

    def skip(self, size):
        if size < 0 or size > self.limit - self.offset:
            raise ValueError('Truncated saved form tail inside caller bound')
        self.offset += size

    def number(self, code):
        start = self.offset
        self.skip(struct.calcsize('<' + code))
        return struct.unpack_from('<' + code, self.data, start)[0]


class _Unsupported(Exception):
    def __init__(self, native, offset, reason):
        self.native, self.offset, self.reason = native, offset, reason


def read_tail(data, start, limit, *, source_major=3754, source_minor=9,
              reference_profile=REFERENCE_PROFILE):
    """Consume both optional siblings after ``read_groups`` and stop at F0 end.

    ``start`` precedes the native+18 presence byte. ``limit`` is exclusive.
    Unsupported positive branches return state=stopped at their first unknown
    field, never a claimed absent/complete tail. Truncation or count overflow
    raises ValueError. Returned collection counts describe source geometry.
    """
    if (type(source_major) is not int or type(source_minor) is not int or
            (source_major, source_minor) != (3754, 9)):
        raise ValueError('Unsupported saved form tail source profile')
    if reference_profile != REFERENCE_PROFILE:
        raise ValueError('Unsupported saved form tail reference profile')
    reader = _Reader(data, start, limit)
    result = {'start': start, 'end': start, 'state': 'complete',
              'siblings_complete': False, 'complete_person': False,
              'native_loader_acceptance': False,
              'reference_profile': reference_profile,
              'reference_profile_is_conditional': True,
              'reference_identities_resolved': False, 'siblings': []}

    def marker():
        at = reader.offset
        value = reader.number('B')
        if value not in (0, 1):
            raise _Unsupported('0x153E56C', at, 'unsupported_current_writer_presence')
        return value

    def require(value, native, reason):
        at = reader.offset
        if reader.number('B') != value:
            raise _Unsupported(native, at, reason)

    try:
        sibling = {'native_reader': '0x151F710', 'presence_offset': reader.offset,
                   'present': bool(marker()), 'count': None}
        result['siblings'].append(sibling)
        if sibling['present']:
            sibling['start'] = reader.offset
            count = reader.number('I')
            if count > MAX_ROWS:
                raise ValueError('151F710 saved form tail row budget exceeded')
            sibling['count'] = count
            for _ in range(count):
                require(2, '0x151FC68', 'unsupported_row_version')
                reader.skip(47)
                require(7, '0x17EDD50', 'unsupported_parameter_version')
                reader.skip(19)
                require(0, '0x151FC68', 'unsupported_legacy_tail_presence')
            sibling['end'] = reader.offset
        sibling = {'native_reader': '0x155007C', 'presence_offset': reader.offset,
                   'present': bool(marker()), 'count': None, 'nested_item_count': 0}
        result['siblings'].append(sibling)
        if sibling['present']:
            sibling['start'] = reader.offset
            count = reader.number('h')
            if count < 0:
                raise ValueError('Negative155007C count reaches native reserve overflow')
            if count > MAX_ROWS:
                raise ValueError('155007C saved form tail row budget exceeded')
            sibling['count'] = count
            for _ in range(count):
                require(1, '0x15505D8', 'unsupported_row_version')
                reader.skip(4)
                for _ in range(2):
                    require(0, '0x11019A0/mode4', 'unsupported_TEAM_reference_marker')
                    reader.skip(4)
                reader.skip(6)  # PERSON u32 and two raw byte fields
                nested = reader.number('I')
                if nested > MAX_NESTED_ITEMS - sibling['nested_item_count']:
                    raise ValueError('155007C saved form tail nested-item budget exceeded')
                sibling['nested_item_count'] += nested
                for _ in range(nested):
                    require(1, '0x15505D8/nested', 'unsupported_nested_row_version')
                    reader.skip(10)
            sibling['end'] = reader.offset
    except _Unsupported as gap:
        result.update(end=gap.offset, state='stopped', next_native_reader=gap.native,
                      stop_reason=gap.reason)
        return result
    result.update(end=reader.offset, siblings_complete=True,
                  native_end='0x153E56C/F0_return')
    return result
