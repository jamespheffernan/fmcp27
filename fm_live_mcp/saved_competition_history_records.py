"""Fixed v3 COMP_HISTORY fields from native3B94DF4/3B948F4.

Codec provenance: game_plugin SHA256
774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1.
GAME_COMP_MANAGER1AC58F4 uses signed COMP+F0, not its ordinal/native ID.
DB COMP_HISTORY_RECORD readerF15F7C passes record+18 to3B93C1C;
F16948 exposes that shared layout as pla1/pla2/pla3,year,chsy,chey,dtdc.
Only version3/55B is supported. Contextual canonical joins belong to the caller.
"""
from datetime import date, timedelta
import struct

WIDTH = 55
VERSION = 3


def date_decided(raw):
    value = int.from_bytes(raw, 'little')
    year, day = value >> 16, value & 511
    out = {'value': None, 'state': 'unmapped_native_date', 'raw_hex': bytes(raw).hex(),
           'native_year': year, 'native_day_low9': day, 'unmapped_high7': value >> 9 & 127}
    if year == 1900 and day == 1:
        return {**out, 'state': 'native_unset'}
    if 1850 <= year <= 2200 and 1 <= day <= 366:
        projected = date(year, 1, 1) + timedelta(days=day-1)
        if projected.year == year:
            out.update(value=projected.isoformat(), state='stored_Date_Decided')
    return out


def decode(raw):
    if len(raw) != WIDTH:
        raise ValueError('Expected exact 55-byte version3 competition-history row')
    competition, year, field56 = struct.unpack_from('<ihH', raw)
    teams = struct.unpack_from('<7i', raw, 8)
    stadium, stage = struct.unpack_from('<ii', raw, 36)
    order, flags, start, end = struct.unpack_from('<BHhh', raw, 44)
    # 3B954F8: exact sentinel1900 comparison, then signed EndYear < Year.
    corrected = end != 1900 and end < year
    return {'year': year, 'start_year': start, 'end_year': end,
            'native_effective_start_year': year if corrected else start,
            'native_effective_end_year': year if corrected else end,
            'native_year_correction_applied': corrected,
            'date_decided': date_decided(raw[51:55]),
            'competition_index_word': competition,
            'first_placed_team_index': teams[0], 'second_placed_team_index': teams[1],
            'third_placed_team_index': teams[2],
            'unmapped_fields': {'other_TEAM_index_words': list(teams[3:]),
                                'STADIUM_index_word': stadium, 'STAGE_NAME_index_word': stage,
                                'native_0x56_unsigned16': field56, 'native_0x5E_byte': order,
                                'history_flags_unsigned16': flags},
            'raw_record_hex': bytes(raw).hex()}
