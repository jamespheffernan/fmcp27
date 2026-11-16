"""Saved 153E56C form groups and 153AA34 rows in the proved 3754/9 subset.

The caller establishes a PLAYER+F0+58 source boundary. This consumes only the
initial typed groups, stopping before the unrelated 151F710/155007C siblings.
References remain same-file words in an explicitly conditional direct32 profile.
Played minutes retain the native playing-duration byte, with current producer
values0..127. They do not identify starters, unused substitutes or completion.
"""

import struct

from . import world

SUPPORTED_SOURCE = (3754, 9)
REFERENCE_PROFILE = 'conditional_direct32'
MAX_GROUP_ROWS = 4096
MAX_TOTAL_ROWS = 20_000
# 153C870 version 3 destinations, in serialized order after raw00/raw04.
_STATS_BYTE_ORDER = (
    6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 36, 16, 17, 18, 19, 20,
    21, 22, 23, 24, 25, 27, 28, 29, 30, 31, 32, 34, 33, 35, 26,
)


def _date(raw):
    packed = int.from_bytes(raw, 'little')
    year, day = packed >> 16, packed & 511
    result = {
        'value': None, 'state': 'unmapped_packed_value', 'raw_hex': raw.hex(),
        'stored_year': year, 'stored_day_of_year': day,
        'unmapped_low_word_flags': packed & 0xFE00,
    }
    if year == 1900 and day == 1:
        result['state'] = 'native_default_sentinel'
        return result
    try:
        result['value'] = world.packed_date(raw)
    except ValueError:
        return result
    result['state'] = 'stored_form_row_date'
    return result


def _stats(reader):
    if reader.u8() != 3:
        raise ValueError('Unsupported saved form statistics version; expected current writer 3')
    discarded_encoding = reader.u8()
    raw = bytearray(37)
    raw[:6] = reader.take(6)
    for offset, value in zip(_STATS_BYTE_ORDER, reader.take(31), strict=True):
        raw[offset] = value
    # 32FC080 uses the same quantity in current compact PLAYER_STATS
    # and historical 153CE10 getters: goals 19/+07, assists 9/+0B, rating 23/+16.
    rating = raw[0x16]
    # Native153FB4C..153FC2C computes duration from labelled event-minute
    # clocks, clamps signed-byte negatives to zero and stores+15. Getter38
    # returns this byte; it does not identify starters or unused substitutes.
    played = raw[0x15]
    return {
        'state': 'stored', 'goals': raw[7], 'assists': raw[11],
        'played_minutes': played if played <= 127 else None,
        'played_minutes_state': 'stored' if played <= 127 else 'outside_current_producer_profile',
        'played_minutes_raw_u8': played,
        'rating_tenths': rating,
        'native_rating_nonzero_filter_passes': rating != 0,
        'rating_zero_reason': 'not_established' if rating == 0 else None,
        'raw_object_hex': raw.hex(), 'discarded_encoding_u8': discarded_encoding,
    }


def _row(reader, row_index):
    start = reader.offset
    if reader.u8() != 1:
        raise ValueError('Unsupported saved form row version; expected current writer 1')
    date = _date(reader.take(4))
    team_raw = reader.take(4)
    competition_index = struct.unpack('<i', reader.take(4))[0]
    raw18 = reader.u8()
    presence = reader.u8()
    if presence not in (0, 1):
        raise ValueError('Unsupported saved form statistics presence')
    stats = _stats(reader) if presence else {
        'state': 'not_stored', 'goals': None, 'assists': None,
        'played_minutes': None, 'played_minutes_state': 'not_stored',
        'played_minutes_raw_u8': None,
        'rating_tenths': None, 'native_rating_nonzero_filter_passes': None,
        'rating_zero_reason': None, 'raw_object_hex': None,
        'discarded_encoding_u8': None,
    }
    return {
        'row_index': row_index, 'start': start, 'end': reader.offset,
        'date': date, 'competition_index_word': competition_index,
        'team_reference_word': int.from_bytes(team_raw, 'little'),
        'team_reference_hex': team_raw.hex(), 'raw_18_u8': raw18,
        'stats': stats,
    }


def read_groups(reader, *, source_major=3754, source_minor=9,
                reference_profile=REFERENCE_PROFILE):
    """Read all serialized form groups, preserving wire order and duplicates.

    Current group/row versions 1 and statistics version 3 are supported. The
    type 20/60 resident ring capacities do not limit the serialized row counts.
    Resource limits are offline budgets, not native cardinality assertions.
    Unknown variants, truncation and exhausted budgets fail without returning a
    partial collection. ``end`` excludes the two unrelated trailing siblings.
    """
    if (type(source_major) is not int or type(source_minor) is not int
            or (source_major, source_minor) != SUPPORTED_SOURCE):
        raise ValueError('Unsupported saved form source version')
    if reference_profile != REFERENCE_PROFILE:
        raise ValueError('Unsupported saved form conditional reference profile')
    start = reader.offset
    group_count = reader.u8()
    groups = []
    total_rows = 0
    for group_index in range(group_count):
        group_start = reader.offset
        kind = reader.u8()
        if kind not in (20, 60):
            raise ValueError('Unsupported saved form group type')
        if reader.u8() != 1:
            raise ValueError('Unsupported saved form group version; expected current writer 1')
        owner_word = reader.u32()
        count = reader.u32()
        if count > MAX_GROUP_ROWS or count > MAX_TOTAL_ROWS - total_rows:
            raise ValueError('Saved form collection exceeds offline row budget')
        if count > (reader.size - reader.offset) // 15:
            raise ValueError('Truncated saved form minimum row extent')
        total_rows += count
        rows = [_row(reader, row_index) for row_index in range(count)]
        groups.append({
            'group_index': group_index, 'kind_code': kind,
            'owner_reference_word': owner_word, 'serialized_row_count': count,
            'start': group_start, 'end': reader.offset, 'rows': rows,
        })
    return {
        'start': start, 'end': reader.offset, 'group_count': group_count,
        'total_row_count': total_rows, 'groups': groups,
        'reference_profile': REFERENCE_PROFILE,
        'reference_profile_is_conditional': True,
        'identities_resolved': False, 'unread_suffix': True,
    }
