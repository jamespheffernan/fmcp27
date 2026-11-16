"""Build-pinned live entity tables; offsets checked against runtime RTTI."""
import struct

from . import players, world, staff

TABLES = {
    'media_sources': (0x56D2D60, 0x55A17D8, b'N2db14DATABASE_TABLEINS_12MEDIA_SOURCEEEE'),
    'regions': (0x56D2D90, 0x55A1AA8, b'N2db14DATABASE_TABLEINS_6REGIONEEE'),
    'awards': (0x56D2D18, 0x55A1418, b'N2db14DATABASE_TABLEINS_5AWARDEEE'),
    'removed_records': (0x56D2DC0, 0x55A1D78, b'N2db14DATABASE_TABLEINS_14REMOVED_RECORDEEE'),
    'derbies': (0x56D2DC8, 0x55A1DF0, b'N2db14DATABASE_TABLEINS_5DERBYEEE'),
    'agreements': (0x56D2DD0, 0x55A1E68, b'N2db14DATABASE_TABLEINS_9AGREEMENTEEE'),
    'cities': (0x56D2D20, 0x55A1490, b'N2db14DATABASE_TABLEINS_4CITYEEE'),
    'people': (0x56D2D80, 0x55A19B8, b'N2db14DATABASE_TABLEINS_6PERSONEEE'),
    'clubs': (0x56D2D28, 0x55A1508, b'N2db14DATABASE_TABLEINS_4CLUBEEE'),
    'national_team_containers': (0x56D2D78, 0x55A1940, b'N2db14DATABASE_TABLEINS_23NATIONAL_TEAM_CONTAINEREEE'),
    'teams': (0x56D2DB0, 0x55A1C88, b'N2db14DATABASE_TABLEINS_9TEAM_BASEEEE'),
    'competitions': (0x56D2D30, 0x55A1580, b'N2db14DATABASE_TABLEINS_4COMPEEE'),
    'continents': (0x56D2D38, 0x55A15F8, b'N2db14DATABASE_TABLEINS_9CONTINENTEEE'),
    'player_types': (0x56D2D88, 0x55A1A30, b'N2db14DATABASE_TABLEINS_11PLAYER_TYPEEEE'),
    'nations': (0x56D2D40, 0x55A1670, b'N2db14DATABASE_TABLEINS_6NATIONEEE'),
    'stadiums': (0x56D2D98, 0x55A1B20, b'N2db14DATABASE_TABLEINS_7STADIUMEEE'),
    'stadium_changes': (0x56D2DA0, 0x55A1B98, b'N2db14DATABASE_TABLEINS_14STADIUM_CHANGEEEE'),
    'currencies': (0x56D2D48, 0x55A3678, b'N2db14DATABASE_TABLEINS_15CURRENCY_RECORDEEE'),
    'injuries': (0x56D2D58, 0x55A1760, b'N2db14DATABASE_TABLEINS_6INJURYEEE'),
    'languages': (0x56D2D68, 0x55A1850, b'N2db14DATABASE_TABLEINS_8LANGUAGEEEE'),
    'local_regions': (0x56D2D70, 0x55A18C8, b'N2db14DATABASE_TABLEINS_12LOCAL_REGIONEEE'),
    'weather': (0x56D2DB8, 0x55A1D00, b'N2db14DATABASE_TABLEINS_7WEATHEREEE'),
    'fixture_names': (0x56D2D50, 0x55A16E8, b'N2db14DATABASE_TABLEINS_12FIXTURE_NAMEEEE'),
    'stage_names': (0x56D2DA8, 0x55A1C10, b'N2db14DATABASE_TABLEINS_10STAGE_NAMEEEE'),
}


def table(read, base, kind):
    root_rva, table_rva, name = TABLES[kind]
    root = world.pointer(read, base + root_rva)
    vtable = base + table_rva
    if world.pointer(read, root) != vtable:
        raise ValueError(f'Unexpected {kind} database table type')
    metadata = read(vtable - 16, 16)
    if struct.unpack_from('<q', metadata)[0] != 0:
        raise ValueError('Unexpected database table displacement')
    info = players.u64(metadata, 8)
    name_pointer = players.u64(read(info + 8, 8))
    if read(name_pointer, len(name) + 1) != name + b'\0':
        raise ValueError('Unexpected database table RTTI')
    header = world.pointer(read, root + 0x88)
    start, end, capacity = struct.unpack('<QQQ', read(header, 24))
    if (start < 4096 or any(p % 8 for p in (start, end, capacity))
            or not start <= end <= capacity or capacity - start > 2000000 * 8):
        raise ValueError('Invalid database table bounds')
    return {'root': root, 'header': header, 'start': start, 'count': (end - start) // 8,
            'identity': (root, header, start, end, capacity)}


def player_membership(read, base, table_info, index, address):
    if not 0 <= index < table_info['count']:
        raise ValueError('Player index is outside the live person table')
    person = world.pointer(read, table_info['start'] + index * 8)
    tables = tuple(base + rva for rva in players.RVA)
    offset = players.person_offset(read, address, tables)
    if person != address + offset:
        raise ValueError('Player is no longer at its live table index')
    raw = read(person, 20)
    expected = players.STAFF_RVA[2] if offset == 0x480 else players.RVA[2]
    if players.u64(raw) != base + expected or int.from_bytes(raw[8:12], 'little') != index:
        raise ValueError('Player table type or index changed')


def club_membership(read, base, table_info, index, address):
    if not 0 <= index < table_info['count']:
        raise ValueError('Club index is outside the live club table')
    if world.pointer(read, table_info['start'] + index * 8) != address:
        raise ValueError('Club is no longer at its live table index')
    raw = read(address, 20)
    if players.u64(raw) != base + world.TYPES['club'][0] or int.from_bytes(raw[8:12], 'little') != index:
        raise ValueError('Club table type or index changed')


def staff_membership(read, base, table_info, index, address):
    if not 0 <= index < table_info['count']:
        raise ValueError('Staff index is outside the live person table')
    _, fields = staff.layout(read, base, address)
    person = address + fields[2]
    if world.pointer(read, table_info['start'] + index * 8) != person:
        raise ValueError('Staff is no longer at its live table index')
    raw = read(person, 20)
    if players.u64(raw) != base + fields[1] or int.from_bytes(raw[8:12], 'little') != index:
        raise ValueError('Staff table type or index changed')
