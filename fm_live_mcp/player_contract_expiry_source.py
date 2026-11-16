"""Selected TEAM membership slots and existing main-contract date sources.

The caller owns the ReadSet and its final fence. No profile or attributes are
decoded. Null and repeated membership slots retain their native positions.
"""
import struct

from . import assessment_people, contract_dates, database, players, teams
from . import prepared_tactics_source, world
from .live_international_duty import _named_identity

MAX_SLOTS = 256
STATES = ('fixed_expiry', 'dynamic_expiry', 'no_contract',
          'basic_contract_fields_unavailable', 'virtual_unsupported',
          'unsupported_person_kind', 'null_slot')
SCOPE = ('All stored membership slots on one selected HUMAN/TEAM native roster, '
         'including duplicates, nulls and loaned-out players. This is not whole-club '
         'coverage. Only fixed main-contract expiries are classified against the inclusive '
         'cutoff; already expired dates are included. Dynamic dates, basic contracts, '
         'missing contracts and unsupported records remain unclassified. Main-contract '
         'and current-club identities are separate; loan expiry, future agreements, '
         'extension/clause activation, renewals and departure are not evaluated.')


def roster(read, team_address):
    return prepared_tactics_source._vector(read, team_address + 0x38, MAX_SLOTS)


def _club_team(read, base, address):
    if not address:
        return None
    assessment_people._address(address, 20)
    index = int.from_bytes(read(address + 8, 4), 'little')
    row, binding = teams.by_index(read, base, index)
    if (binding['address'] != address or row['kind'] != 'team'
            or row['owner'] is None or row['owner']['kind'] not in ('club', 'league_body_club')):
        raise ValueError('Player expiry club TEAM ownership changed')
    return row


def inspect_slot(read, base, tables, people, address, slot_index):
    """Return an address-free row and an optional stock player_ref binding."""
    row = {'roster_index': slot_index, 'state': 'null_slot', 'record_kind': None,
           'native_identity': None, 'name': None, 'display_name': None,
           'birth_date': None, 'contract_dates': None,
           'main_contract_teams': None, 'main_contract_club': None,
           'current_club_team': None, 'current_club': None}
    if not address:
        return row, None
    assessment_people._address(address, 20)
    vtable = world.pointer(read, address)
    fields = next((fields for fields in assessment_people._PERSON_TYPES.values()
                   if vtable == base + fields[1]), None)
    if fields is None:
        raise ValueError('Unrecognised player expiry roster primary type')
    kind, _, offset, _ = fields
    found, found_offset, public, uid, secondary = assessment_people._person(
        read, base, people, address + offset)
    if found != address or found_offset != offset or public['record_kind'] != kind:
        raise ValueError('Player expiry canonical PERSON relation changed')
    row.update(state='virtual_unsupported' if kind == 'virtual' else 'unsupported_person_kind',
               record_kind=kind, native_identity=public['native_identity'])
    if kind not in ('actual', 'player_staff'):
        return row, None
    person = address + offset
    person_table = base + (players.STAFF_RVA[2] if kind == 'player_staff' else players.RVA[2])
    if (players.u64(read(person_table + 0x668, 8)) != base + 0xD5C5FC
            or struct.unpack('<q', read(person_table - 0x678, 8))[0] != -offset):
        raise ValueError('Player expiry PERSON cast changed')
    index = public['native_identity']['database_index']
    database.player_membership(read, base, people, index, address)
    identity, name, display = _named_identity(read, address, offset, kind, uid, secondary)
    dates = contract_dates.decode(read, base, person)
    if dates['state'] not in STATES[:4]:
        raise ValueError('Unsupported player expiry date state')
    current_team = _club_team(read, base, players.u64(read(address + 0x128, 8)))
    main = players.u64(read(person - 0x98, 8))
    main_teams, main_club = None, None
    if main:
        # decode() has checked contract type, RTTI, PERSON owner and dispatch.
        first, second = struct.unpack('<QQ', read(main + 0x10, 16))
        if bool(first) != bool(second):
            raise ValueError('Player expiry main-contract TEAM links disagree')
        main_teams = [_club_team(read, base, team) for team in (first, second)]
        if first:
            if main_teams[0]['owner'] != main_teams[1]['owner']:
                raise ValueError('Player expiry main-contract club identities disagree')
            main_club = main_teams[0]['owner']
    row.update(state=dates['state'], name=name, display_name=display,
               birth_date=identity[-2], contract_dates=dates,
               main_contract_teams=main_teams, main_contract_club=main_club,
               current_club_team=current_team,
               current_club=current_team['owner'] if current_team else None)
    binding = {'address': address, 'tables': tables, 'identity': identity,
               'database_index': index, 'record_kind': kind, 'world_bound': True}
    return row, binding


def summarize(rows, cutoff, offset, limit, unclassified_limit):
    counts = {state: 0 for state in STATES}
    matches, unclassified = [], []
    for row in rows:
        counts[row['state']] += 1
        if row['state'] == 'fixed_expiry':
            if row['contract_dates']['expires'] <= cutoff:
                matches.append(row)
        else:
            unclassified.append(row)
    matches.sort(key=lambda row: (row['contract_dates']['expires'],
        row['display_name'].casefold(), row['birth_date'],
        row['native_identity']['database_index'], row['native_identity']['native_id'],
        row['roster_index']))
    returned = matches[offset:offset + limit]
    manifest = [{'roster_index': row['roster_index'], 'native_identity': row['native_identity'],
                 'record_kind': row['record_kind'], 'classification': row['state'],
                 'matches_cutoff': (row['contract_dates']['expires'] <= cutoff
                                    if row['state'] == 'fixed_expiry' else None)} for row in rows]
    return {'native_slot_count': len(rows), 'scanned_count': len(rows), 'slot_manifest': manifest,
            'classified_count': counts['fixed_expiry'], 'fixed_expiry_count': counts['fixed_expiry'],
            'fixed_nonmatch_count': counts['fixed_expiry'] - len(matches),
            'unclassified_count': len(unclassified), 'state_counts': counts,
            'matched_count': len(matches), 'returned_count': len(returned),
            'truncated': len(matches) > len(returned), 'truncated_count': len(matches) - len(returned),
            'has_more': offset + len(returned) < len(matches),
            'next_offset': offset + len(returned) if offset + len(returned) < len(matches) else None,
            'players': returned,
            'unclassified_returned_count': min(unclassified_limit, len(unclassified)),
            'unclassified_truncated_count': max(0, len(unclassified) - unclassified_limit),
            'unclassified_players': unclassified[:unclassified_limit]}
