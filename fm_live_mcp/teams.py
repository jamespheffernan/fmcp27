"""Build-pinned TEAM_BASE identities and direct competition assignments."""
import struct

from . import database, geography, players, world

# Installed editor team.xml field Ttyp uses the tmty enum in db enums.xml.
EDITOR_TYPE_NAMES = {
    0: 'First Team',
    1: 'Reserve Team',
    3: 'B Team',
    9: 'U23 Team',
    10: 'U21 Team',
    11: 'U19 Team',
    12: 'U18 Team',
    13: 'C Team',
    14: 'Amateur Team',
    15: 'II Team',
    16: '2 Team',
    17: '3 Team',
    18: 'U20 Team',
    19: 'First Team If Available',
    21: 'Youth U21 Team',
    30: "Dutch 'Jung' Team",
    33: 'U22 Team',
    36: 'U19 B Team',
    37: 'U18 B Team',
}

LOOKUP_MODE = 0x56D34E0
ASSIGNMENTS = {'current': 0x50, 'next': 0x58, 'secondary': 0x68, 'next_secondary': 0x70}
GETTERS = {'team': 0x177580C, 'national_team': 0x13D746C,
           'club': 0xE476C4, 'league_body_club': 0xE476C4,
           'national_team_container': 0x13EC530}
SCOPE = ('Direct stored division assignments, following native ctms/cntm/otms/nsod selection. '
         'Next-season queries fall back to the current assignment when the next pointer is null. '
         'Includes club and national teams. Does not aggregate child competitions or establish '
         'current cup/stage participants, registration, fixtures, standings or eligibility. '
         'An empty result does not prove that a competition has no participants. '
         'Continue every next_cursor with the same competition and assignment, including empty pages. '
         'Reads are non-atomic within and across pages; references expire after save/build changes or eviction.')


def lookup(read, base):
    info = database.table(read, base, 'teams')
    mode = read(base + LOOKUP_MODE, 1)[0]
    # This scanner uses equality to one, unlike COMP's bit-zero lookup test.
    header = info['header'] if mode == 1 else info['root'] + 0x68
    start, end, capacity = struct.unpack('<QQQ', read(header, 24))
    if (start, end, capacity) != (0, 0, 0):
        if (start < 4096 or any(x % 8 for x in (start, end, capacity))
                or not start <= end <= capacity or capacity-start > 2000000*8):
            raise ValueError('Invalid selected team lookup bounds')
    return {**info, 'lookup_header': header, 'lookup_start': start, 'lookup_count': (end-start)//8,
            'lookup_identity': (mode, header, start, end, capacity)}


def selection(read, address, assignment):
    offset = ASSIGNMENTS[assignment]
    pointer = players.u64(read(address + offset, 8))
    fallback = assignment in ('next', 'next_secondary') and not pointer
    if fallback:
        offset -= 8
        pointer = players.u64(read(address + offset, 8))
    if pointer and (pointer < 4096 or pointer % 8):
        raise ValueError('Invalid team competition pointer')
    return pointer, fallback


def _typed(read, base, address, kinds):
    vtable = world.pointer(read, address)
    kind = next((kind for kind in kinds if vtable == base + world.TYPES[kind][0]), None)
    if kind is None:
        raise ValueError('Unexpected team or owner type')
    world.typed(read, base, address, kind)
    if players.u64(read(vtable + 24, 8)) != base + GETTERS[kind]:
        raise ValueError('Team or owner property getter changed')
    return kind


def _identity(read, address):
    raw = read(address + 8, 12)
    index, native_id, random_id = struct.unpack('<III', raw)
    if not native_id:
        raise ValueError('Invalid native team or owner ID')
    return {'database_index': index, 'native_id': native_id,
            'random_id': None if native_id == random_id else random_id}, raw


def _string(read, address):
    pointer = players.u64(read(address, 8))
    if not pointer:
        return None
    if pointer < 4096:
        raise ValueError('Invalid team owner string pointer')
    if read(pointer, 4) == bytes(4):
        if read(pointer + 4, 1) != b'\0':
            raise ValueError('Invalid empty team owner string')
        return ''
    return world.string(read, pointer)


def by_index(read, base, index, *, info=None):
    if type(index) is not int or index < 0:
        raise ValueError('Invalid team index')
    info = lookup(read, base) if info is None else info
    if index >= info['count'] or index >= info['lookup_count']:
        raise ValueError('Team index is outside the selected native lookup')
    address = world.pointer(read, info['start'] + index*8)
    if world.pointer(read, info['lookup_start'] + index*8) != address:
        raise ValueError('Primary and canonical team identities disagree')
    kind = _typed(read, base, address, ('team', 'national_team'))
    row, identity = _identity(read, address)
    if row['database_index'] != index:
        raise ValueError('Team database index changed')
    native_type = struct.unpack('<b', read(address + 0x28, 1))[0]
    owner_address = players.u64(read(address + 0x30, 8))
    owner, owner_identity, owner_kind = None, None, None
    if owner_address:
        if owner_address < 4096 or owner_address % 8:
            raise ValueError('Invalid team owner pointer')
        owner_kind = _typed(read, base, owner_address,
                            ('club', 'league_body_club', 'national_team_container'))
        owner, owner_identity = _identity(read, owner_address)
        table_kind = 'national_team_containers' if owner_kind == 'national_team_container' else 'clubs'
        club_table = database.table(read, base, table_kind)
        if (owner['database_index'] >= club_table['count']
                or world.pointer(read, club_table['start'] + owner['database_index']*8) != owner_address):
            raise ValueError('Team owner table membership changed')
        if address not in world.vector(read, owner_address + 0x18, 64):
            raise ValueError('Team owner backlink disagrees')
        owner['kind'] = owner_kind
        if owner_kind == 'national_team_container':
            nation = players.u64(read(owner_address + 0x170, 8))
            owner['nation'] = geography.record(read, base, nation, 'nation') if nation else None
        else:
            owner.update(name=_string(read, owner_address + 0xC0),
                         short_name=_string(read, owner_address + 0xC8),
                         name_source='stored_native_strings')
    row.update(kind=kind, native_type_code=native_type, owner=owner)
    binding = {'address': address, 'identity': identity, 'database_index': index, 'kind': kind,
               'owner_kind': owner_kind,
               'owner_address': owner_address, 'owner_identity': owner_identity}
    return row, binding
