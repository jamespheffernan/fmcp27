"""Stored COMP crgt records, decoded from native registration properties."""
import struct

from . import geography, players, teams, world

SCOPE = ('Stored competition Registered Teams records from the native crgt list. '
         'These records do not establish current-season participation, squad registration or eligibility. '
         'Year codes 0 and 65535 are unspecified; other codes are preserved without inferring a season. '
         'Info identifies the registration; its competition-specific use is not decoded. '
         'Negative values are unspecified. Null record slots are counted and skipped; repeated records and teams '
         'remain separate rows in native order. Team references open native rosters and player queries. '
         'Continue every next_cursor with the same competition and year filter, including empty pages. '
         'Reads are non-atomic within and across pages; linked identities and consumed bytes are rechecked.')
MAX_RECORDS = 100000


def vector(read, competition_address):
    start, end, capacity = struct.unpack('<QQQ', read(competition_address + 0x18, 24))
    if (start, end, capacity) != (0, 0, 0):
        if (start < 4096 or any(x % 8 for x in (start, end, capacity))
                or not start <= end <= capacity or capacity-start > MAX_RECORDS*8):
            raise ValueError('Invalid competition registration vector')
    return {'start': start, 'count': (end-start)//8, 'identity': (start, end, capacity)}


def fields(read, address):
    if address < 4096 or address % 8:
        raise ValueError('Invalid competition registration pointer')
    return struct.unpack('<QHb', read(address, 11))


def record(read, base, address, *, team_info=None):
    team_address, year, info = fields(read, address)
    team, binding, nation = None, None, None
    if team_address:
        if team_address < 4096 or team_address % 8:
            raise ValueError('Invalid registered team pointer')
        index = int.from_bytes(read(team_address + 8, 4), 'little')
        team, binding = teams.by_index(read, base, index, info=team_info)
        if binding['address'] != team_address:
            raise ValueError('Registered team table membership changed')
        owner = binding['owner_address']
        if owner:
            # Native nati selects ordinary-club +D8 or national-container +170
            # from the stored team flag, rather than from inferred team labels.
            offset = 0xD8 if read(team_address + 0x2F, 1)[0] == 0 else 0x170
            nation_address = players.u64(read(owner + offset, 8))
            if nation_address:
                if nation_address < 4096 or nation_address % 8:
                    raise ValueError('Invalid registered team nation pointer')
                nation = geography.record(read, base, nation_address, 'nation')
    return {'team': team, 'nation': nation,
            'year': None if year in (0, 65535) else year, 'native_year_code': year,
            'year_state': 'unspecified' if year in (0, 65535) else 'stored',
            'registration_identifier': None if info < 0 else info, 'native_info_code': info,
            'registration_identifier_state': 'unspecified' if info < 0 else 'stored'}, binding
