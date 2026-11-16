"""Staff identity and contract club links through shared native PERSON_DATA."""
from datetime import date, timedelta
import struct

from . import players, world, staff_attributes, staff_jobs, contract_dates, wages, contract_status, contract_bonuses, contract_terms, personality

# primary table, person table, person offset, NON_PLAYING_DATA offset, RTTI
LAYOUTS = {
    'staff': (0x5583660, 0x55849D8, 0x208, 8, b'N2db17ACTUAL_NON_PLAYERE'),
    'human_manager': (0x55AC480, 0x55AD820, 0x548, 8, b'N2db16HUMAN_NON_PLAYERE'),
    'player_staff': (0x558EF38, 0x55908E0, 0x480, 0x280, b'N2db28ACTUAL_PLAYER_AND_NON_PLAYERE'),
}
NON_PLAYING_RVA = 0x55B66F8


def layout(read, base, address):
    primary = players.u64(read(address, 8))
    for kind, fields in LAYOUTS.items():
        if primary == base + fields[0]:
            return kind, fields
    raise ValueError('Unsupported staff primary type')


def name_part(read, handle):
    if not handle or not players.u64(read(handle, 8)):
        return ''
    return players.common_name(read, handle) or ''


def decode(read, base, address, include_club=False, include_attributes=False, include_job=False,
           include_contract_dates=False, include_wage=False, include_contract_status=False,
           include_contract_bonuses=False, include_contract_terms=False):
    kind, (primary, person_table, person_offset, data_offset, name) = layout(read, base, address)
    raw = read(address, person_offset + 32)
    for offset, rva, displacement, expected in (
        (0, primary, 0, name), (person_offset, person_table, -person_offset, name),
        (data_offset, NON_PLAYING_RVA, 0, b'N2db16NON_PLAYING_DATAE'),
    ):
        table = base + rva
        if players.u64(raw, offset) != table:
            raise ValueError('Staff runtime type changed')
        metadata = read(table - 16, 16)
        if struct.unpack_from('<q', metadata)[0] != displacement:
            raise ValueError('Staff vtable displacement changed')
        info = players.u64(metadata, 8)
        text = players.u64(read(info + 8, 8))
        if read(text, len(expected) + 1) != expected + b'\0':
            raise ValueError('Staff runtime type name changed')
    reference, table = base + players.RVA[2], base + person_table
    for slot, adjustment in ((40, 0x150), (41, 0x158), (42, 0x160), (55, 0x1C8)):
        if (read(reference + slot * 8, 8) != read(table + slot * 8, 8)
                or struct.unpack('<q', read(table - adjustment, 8))[0] != -0x110):
            raise ValueError('Staff shared person getter changed')
    identity, secondary = struct.unpack_from('<II', raw, person_offset + 12)
    if not identity or int.from_bytes(raw[person_offset+8:person_offset+12], 'little') == 0xFFFFFFFF:
        raise ValueError('Invalid staff identity or non-table record')
    handles = struct.unpack_from('<QQQ', raw, person_offset - 0xF0)
    first, last = (name_part(read, h) for h in handles[:2])
    common = (name_part(read, handles[2]) or None)
    full_name = ' '.join(part for part in (first, last) if part) or common
    if not full_name:
        raise ValueError('Staff record has no readable name')
    day, year = struct.unpack_from('<HH', raw, person_offset - 0xB8)
    if not 1850 <= year <= 2200 or not 1 <= day <= 366:
        raise ValueError('Invalid staff birth date')
    birthday = date(year, 1, 1) + timedelta(days=day - 1)
    if birthday.year != year:
        raise ValueError('Invalid staff birth day')
    result = {'name': full_name, 'display_name': common or full_name, 'birth_date': birthday.isoformat(),
              'record_kind': kind, 'evidence': 'native_staff_shared_person_data'}
    if include_attributes:
        result.update(staff_attributes.decode(read, base, raw, kind, person_offset, data_offset))
        result['personality'] = personality.decode(read, base, raw, person_offset)
    if include_club or include_job or include_contract_dates or include_wage or include_contract_status or include_contract_bonuses or include_contract_terms:
        result['contract'] = contract_club(read, base, address + person_offset, include_job=include_job)
    if include_contract_dates:
        result['contract']['dates'] = contract_dates.decode(read, base, address + person_offset)
    if include_contract_status:
        result['contract']['status'] = contract_status.decode(read, base, address + person_offset)
    if include_wage:
        result['contract']['wage'] = wages.decode(read, base, address + person_offset)
    if include_contract_bonuses:
        result['contract']['bonuses'] = contract_bonuses.decode(read, base, address + person_offset)
    if include_contract_terms:
        result['contract']['terms'] = contract_terms.decode(read, base, address + person_offset)
    if (read(address, len(raw)) != raw
            or first != name_part(read, handles[0]) or last != name_part(read, handles[1])
            or common != (name_part(read, handles[2]) or None)):
        raise ValueError('Staff record changed during read')
    return result, (kind, identity, first, last, birthday.isoformat(), secondary)


def contract_club(read, base, person, expected_club=None, include_job=False):
    contract = players.u64(read(person - 0x98, 8))
    if not contract:
        if expected_club is not None:
            raise ValueError('Club staff member has no contract')
        return {'club': None, 'state': 'no_contract', 'evidence': 'null_native_contract',
                **({'job': {'title': None, 'state': 'no_contract'}} if include_job else {})}
    vtable = players.u64(read(contract, 8))
    kind = next((kind for kind in ('full_contract', 'basic_contract')
                 if vtable == base + world.TYPES[kind][0]), None)
    if kind is None:
        raise ValueError('Unsupported staff contract type')
    world.typed(read, base, contract, kind)
    if world.pointer(read, contract + 8) != person:
        raise ValueError('Staff contract owner changed')
    teams = (world.pointer(read, contract + 0x10), world.pointer(read, contract + 0x18))
    club_address = None
    for team in set(teams):
        world.typed(read, base, team, 'team')
        linked_club = world.pointer(read, team + 0x30)
        if club_address is not None and linked_club != club_address:
            raise ValueError('Staff contract teams belong to different clubs')
        club_address = linked_club
        club, _ = world.club(read, base, club_address)
        if team not in world.vector(read, club_address + 0x18, 64):
            raise ValueError('Staff contract team is absent from club')
    if expected_club is not None and club_address != expected_club:
        raise ValueError('Staff contract belongs to another club')
    result = {'club': club, 'state': kind, 'evidence': 'native_contract_owner_and_club_backlinks'}
    if include_job:
        result['job'] = staff_jobs.decode(read, base, contract, vtable, teams[0])
    return result
