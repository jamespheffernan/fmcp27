"""Bounded original requirement26 operands, without an exemption verdict.

The caller binds current date, owner, fixture phase/rule and selector, verifies
all consumed bytes after its last callback, and never invokes a native method.
The full club TEAM/PLAYER slot order is retained, including nulls/repetitions.
"""
import hashlib
import struct

from . import assessment_people, competition_stages, database, fixtures, players, teams, virtual_identity, world
from . import player_registration_source

NATIVE_GUARDS = (
    (0x177AA7C, 0x290, 'a8bd4ad719836baae172d1d9c8d59c1ee86e135ee7792ce6434d0b851c226294'),
    (0xD56498, 0x298, 'e8ef518a6144c635fa8581ea471ad5d7f7dc991ad57eb827f64af2a13f15c02d'),
    (0xD5C5FC, 0x14, '62e50aff752959cc367e0ab72a4ea1286e80d2e70d5a58cc8796f16a3c89568d'),
    (0x1BDBC08, 8, '2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a'),
    (0x5387C10, 16, 'e0e4641f65e18a76108a16dd68edd04088dbf8fc022b8662554490beb2a89257'),
    (0x53002F0, 16, 'baed642339816affb3fe8719792d0e4ce82f12db72b7373d244eaa65445800fe'),
)


def verify_native(read, base):
    for rva, size, expected in NATIVE_GUARDS:
        if hashlib.sha256(read(base + rva, size)).hexdigest() != expected:
            raise ValueError(f'UCL requirement26 native source changed at {rva:#x}')


def _pointer(read, address):
    value = players.u64(read(address, 8))
    if value and (value < 4096 or value % 8):
        raise ValueError('Invalid requirement26 object pointer')
    return value


def _code(read, base, address, expected):
    value = players.u64(read(address, 8))
    if value != base + expected or value % 4:
        raise ValueError('Requirement26 native method dispatch changed')
    return value


def collect_operands(read, base, team, selector):
    """Diagnostic source packet only; no native-result or clearance shortcut."""
    if type(selector) is not int or selector != 0:
        raise ValueError('Only the proved UCL selector0 operand scope is supported')
    verify_native(read, base)
    assessment_people.verify_native(read, base)
    root = _pointer(read, base + 0x56D57D0)
    fixtures.typed(read, base, root, 'root')
    _code(read, base, _pointer(read, root) + 0x30, 0x1BDBC08)
    index = int.from_bytes(read(team + 8, 4), 'little')
    public_team, binding = teams.by_index(read, base, index)
    if binding['address'] != team or binding['owner_kind'] != 'club':
        raise ValueError('Requirement26 target TEAM/CLUB binding changed')
    club = binding['owner_address']
    world.typed(read, base, club, 'club')
    read(club, 0x180)
    club_teams, _ = competition_stages.vector(read, club + 0x18, 64)
    affiliations, _ = competition_stages.vector(read, club + 0x118, 128)
    for affiliation in affiliations:
        if affiliation:
            read(affiliation, 0x38)
    people = database.table(read, base, 'people')
    tables = tuple(base + rva for rva in players.RVA)
    result = dict(state='native_requirement26_operands_only_no_verdict', selector=selector,
                  team=public_team, team_address=team, club_address=club, teams=[],
                  unique_player_count=0, stored_player_slot_count=0,
                  native_requirement26=None, full_eligibility_evaluated=False)
    subjects = {}
    for team_slot, current_team in enumerate(club_teams):
        row = dict(team_slot=team_slot, address=current_team, player_slots=None)
        result['teams'].append(row)
        if not current_team:
            continue
        ix = int.from_bytes(read(current_team + 8, 4), 'little')
        public, current_binding = teams.by_index(read, base, ix)
        if current_binding['address'] != current_team or current_binding['owner_address'] != club:
            raise ValueError('Requirement26 club TEAM membership changed')
        read(current_team, 0x90)
        roster, _ = competition_stages.vector(read, current_team + 0x38, 512)
        result['stored_player_slot_count'] += len(roster)
        if result['stored_player_slot_count'] > 1024:
            raise ValueError('Requirement26 combined roster slots exceed bound')
        row.update(team=public, player_slots=[])
        for slot, primary in enumerate(roster):
            item = dict(slot=slot, primary=primary, person=None)
            row['player_slots'].append(item)
            if not primary:
                continue
            if primary in subjects:
                item['person'] = subjects[primary]
                continue
            vt = _pointer(read, primary)
            if vt == base + world.TYPES['virtual_player'][0]:
                compact = virtual_identity.inspect(read, primary, tables)
                subject = dict(record_kind='virtual', native_identity=compact['native_identity'],
                               source_state='unsupported_compact_native_aggregate_dispatch')
            else:
                offset = players.person_offset(read, primary, tables)
                person = primary + offset
                checked, _, public_identity, _, _ = assessment_people._person(read, base, people, person)
                if checked != primary:
                    raise ValueError('Requirement26 canonical PLAYER primary changed')
                subject = dict(public_identity, person_address=person)
                if public_identity['record_kind'] != 'actual':
                    subject['source_state'] = 'unsupported_combined_native_aggregate_dispatch'
                else:
                    database.player_membership(read, base, people,
                                               public_identity['native_identity']['database_index'], primary)
                    _code(read, base, _pointer(read, person) + 0x668, 0xD5C5FC)
                    _code(read, base, vt + 0x390, 0xD5B2A0)
                    rating = struct.unpack('<b', read(primary + 0x148, 1))[0]
                    subject.update(source_state='ordinary_native_goalkeeper_rating_captured',
                                   goalkeeper_position_rating=rating)
                    if rating >= 15:
                        read(primary, 0x400)
                        _code(read, base, vt + 0x250, 0xD56498)
                        _code(read, base, vt + 0xC8, 0xD09BD0)
                        medical = _pointer(read, primary + 0xF0)
                        injuries, _ = competition_stages.vector(read, medical, 64) if medical else ((), None)
                        subject['medical_records'] = [dict(address=at, raw40=read(at, 0x40).hex())
                                                      if at else None for at in injuries]
                        contract = _pointer(read, primary + 0x2F0)
                        if contract:
                            read(contract, 0x38)
                            read(_pointer(read, contract) + 0x90, 8)
                            employer = _pointer(read, contract + 0x10)
                            if employer:
                                read(employer + 0x30, 8)
                        current = _pointer(read, primary + 0x128)
                        subject['current_team_address'] = current
                        if current:
                            read(current, 0x90)
                            current_public, current_bound = teams.by_index(
                                read, base, int.from_bytes(read(current + 8, 4), 'little'))
                            if current_bound['address'] != current:
                                raise ValueError('Requirement26 PLAYER current TEAM membership changed')
                            subject['current_team'] = current_public
                        subject['registration_markers_by_team'] = [
                            dict(team_address=target, marker=player_registration_source.project(
                                read, primary, 'actual', target, selector))
                            for target in club_teams if target]
            subjects[primary] = subject
            item['person'] = subject
    result['unique_player_count'] = len(subjects)
    return result
