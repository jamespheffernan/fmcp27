"""Pinned v2 injury-history fields. Names, event meaning and units stay explicit."""
from datetime import date, timedelta
import struct

WIDTH = 16
VERSION = 2
DATE_SCOPE = 'stored injury-history DATE; onset, recovery and end-date meaning unproved'


def date_filter(value, label):
    if value is None:
        return None
    if type(value) is not str or len(value) != 10:
        raise ValueError(f'{label} must be an exact ISO date')
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f'{label} must be an exact ISO date') from error
    if parsed.isoformat() != value or not 1850 <= parsed.year <= 2200:
        raise ValueError(f'{label} is outside the supported native date range')
    return value


def stored_date(raw):
    value = int.from_bytes(raw, 'little')
    year, day = value >> 16, value & 511
    out = {'value': None, 'state': 'unmapped_native_date', 'raw_hex': raw.hex(),
           'native_year': year, 'native_day_low9': day, 'unmapped_high7': (value >> 9) & 127}
    if year == 1900 and day == 1:
        return {**out, 'state': 'native_unset'}
    if 1850 <= year <= 2200 and 1 <= day <= 366:
        projected = date(year, 1, 1) + timedelta(days=day - 1)
        if projected.year == year:
            out.update(value=projected.isoformat(), state='stored')
    return out


def decode(raw):
    """132D1A0/132CFD0 ordering; preserve each raw native bit."""
    if len(raw) != WIDTH:
        raise ValueError('Expected exact 16-byte version2 injury-history row')
    injury, team, byte_e, byte_c, _, raw_a, byte_d, byte_f = struct.unpack('<hiBBIHBB', raw)
    return {'stored_date': stored_date(raw[8:12]),
            'injury_reference': {'table': 'INJURY', 'stored_index': injury,
                                 'state': 'native_null_reference' if injury < 0 else 'pending_same_snapshot_index'},
            'team_reference': {'table': 'TEAM_BASE', 'stored_index': team,
                               'state': 'native_null_reference' if team < 0 else 'unresolved_same_snapshot_index'},
            'unmapped_fields': {'native_0xA_unsigned16': raw_a, 'native_0xC_byte': byte_c,
                                'native_0xD_byte': byte_d, 'native_0xE_byte': byte_e,
                                'native_0xF_byte': byte_f},
            'raw_record_hex': bytes(raw).hex()}


def owner(data, row):
    """Reparse one checked regular PLAYER; bind its+200 word independently."""
    from .person_wire import _bindings
    if row['signed_tag'] != 2:
        raise ValueError('Unsupported PERSON class for injury-history owner')
    bounded = memoryview(data)[:row['end']]
    value = _bindings.player(bounded, row['body_offset'], ordinal=row['ordinal'])
    if value['end'] != row['end'] or value['identity'] != row['identity']:
        raise ValueError('Injury owner PLAYER identity or boundary differs')
    prefix = value['parts']['remaining_tail']['parts']['embedded1f8_prefix']
    start = prefix['start']
    if bytes(bounded[start:start + 14]).hex() != prefix['raw14']:
        raise ValueError('Injury owner prefix differs from source')
    offset = start + 10
    return {'owner_index': struct.unpack_from('<i', bounded, offset)[0],
            'source_offset': offset, 'source_field': 'PLAYER+0x200'}
