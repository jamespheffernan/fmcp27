"""Canonical current-club comparison for checked live player bindings.

Call with one request-local ReadSet and verify it before publishing. The caller
owns canonical player-reference validation. This reads club links, never match
eligibility, loan recall rights, selection or bench membership.
"""
import struct

from . import database, players, world


def resolve(read, base, primary_address, record_kind, managed_club_address):
    """Return checked identities and current-club location, independent of names.

    Actual and combined players use the existing native club-link decoder. A
    virtual record has no supported contract/current-club route here. Caches are
    local to this invocation; malformed or noncanonical links raise ValueError.
    """
    if record_kind not in ('actual', 'player_staff', 'virtual'):
        raise ValueError('Unsupported player record kind for club location')
    clubs_table = database.table(read, base, 'clubs')
    identities = {}

    def club_identity(address):
        if address not in identities:
            world.typed(read, base, address, 'club')
            raw = read(address + 8, 12)
            index, native_id, random_id = struct.unpack('<III', raw)
            if not native_id:
                raise ValueError('Club primary identity is missing')
            database.club_membership(read, base, clubs_table, index, address)
            identities[address] = ({'database_index': index, 'native_id': native_id,
                                    'random_id': None if random_id == native_id else random_id}, raw)
        return identities[address]

    managed, managed_raw = club_identity(managed_club_address)
    result = {'location_state': 'unsupported_record_kind', 'at_managed_club': None,
              'managed_club_identity': managed, 'current_club_identity': None,
              'contract_club_identity': None, 'loan_club_identity': None, 'clubs': None}
    if record_kind == 'virtual':
        return result
    cache = {}
    clubs = world.player_clubs(read, base, primary_address, cache,
                               player_staff=record_kind == 'player_staff')
    teams_table = database.table(read, base, 'teams')

    def team_club(team):
        if not team:
            return None, None
        # The existing decoder checked type, owner pointer and reverse club-team
        # membership. Add current database membership, never trusting just an ID.
        if team not in cache:
            raise ValueError('Unverified player club-team link')
        index = int.from_bytes(read(team + 8, 4), 'little')
        if (index >= teams_table['count']
                or world.pointer(read, teams_table['start'] + index * 8) != team):
            raise ValueError('Player team is no longer at its live table index')
        address, old_identity = cache[team][1]
        identity, raw = club_identity(address)
        if struct.unpack('<II', raw[4:]) != old_identity:
            raise ValueError('Player club identity changed during comparison')
        return identity, (address, raw)

    # Validate every team visited by the native club decoder, including both
    # contract team pointers, even when only one determines an output identity.
    for team in cache:
        team_club(team)
    current, binding = team_club(players.u64(read(primary_address + 0x128, 8)))
    person = primary_address + (0x480 if record_kind == 'player_staff' else 0x388)
    contract = players.u64(read(person - 0x98, 8))
    parent, _ = team_club(players.u64(read(contract + 0x10, 8))) if contract else (None, None)
    loan = None
    if clubs['loan_club'] is not None:
        holder = world.pointer(read, person - 0x90)
        auxiliary = world.pointer(read, holder)
        loan, _ = team_club(players.u64(read(auxiliary + 0x10, 8)))
    at_club = None if binding is None else binding == (managed_club_address, managed_raw)
    result.update(location_state=('current_club_unavailable' if at_club is None else
                                  'at_managed_club' if at_club else 'away_from_managed_club'),
                  at_managed_club=at_club, current_club_identity=current,
                  contract_club_identity=parent, loan_club_identity=loan, clubs=clubs)
    return result
