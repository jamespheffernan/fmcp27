"""Stored COMP identities resolved through the native indexed lookup path."""
import struct

from . import database, geography, players, world

LOOKUP_MODE = 0x56D34E0
PROPERTY_GETTER = 0xEFD3B8
SCOPE = ('Stored competition identity, names, geographic links, parent competition, reputation, '
         'level, type, gender and extinct flag. Localized or generated display names, '
         'active-season status and broader competition rules are not decoded. Use fm_find_fixtures for resident fixtures. '
         'Use fm_get_competition_teams for direct stored division assignments, and fm_get_competition_stages with fm_get_standings for stored league tables. '
         'Type labels do not establish current activity; unmapped codes remain explicit. '
         'Level is the native property value, including zero; stored code 100 means unspecified. '
         'Null and empty names remain distinct. Name search uses Unicode case-insensitive substrings '
         'across name, short_name and abbreviation; omit name to include unnamed records. '
         'Continue every next_cursor with identical criteria, including after empty pages. '
         'Reads are non-atomic within and across pages. References expire after detach, save/build '
         'changes or cache eviction; repeat the search to obtain a fresh reference.')


COMPETITION_TYPES = {
    0: 'Domestic Top Division', 1: 'Domestic Division', 2: 'Domestic Main Cup',
    3: 'Domestic League Cup', 4: 'Domestic Cup', 5: 'Super Cup',
    6: 'International Finals', 7: 'International Qualifiers', 8: 'Reserve Division',
    9: 'Club Friendly', 10: 'Main Continental International Finals',
    11: 'Main Continental International Qualifiers', 12: 'Club Finals', 13: 'Friendly',
    14: 'Domestic Other Division', 15: 'U21 International Finals',
    16: 'U21 International Qualifiers', 17: 'U19 International Finals',
    18: 'U19 International Qualifiers', 19: 'U23 International Finals',
    20: 'U23 International Qualifiers', 21: 'Club Champions Cup', 22: 'Cup Winners Cup',
    23: 'Reserve Cup', 24: 'International Friendly', 25: 'U20 International Finals',
    26: 'All Stars Cup', 27: 'U20 International Qualifiers', 28: 'Inactive Competition',
    29: 'Inactive Other Division', 31: 'U22 International Finals',
    32: 'U22 International Qualifiers', 33: 'U23 Division', 34: 'U22 Division',
    35: 'U21 Division', 36: 'U20 Division', 37: 'U19 Division', 38: 'U18 Division',
    39: 'Youth Cup',
}
GENDERS = {0: 'Male', 1: 'Female'}


def _context(read, base, address, cache):
    # This cache belongs to the caller's ReadSet and never outlives that query.
    cache = {} if cache is None else cache
    linked = {}
    for field, offset in (('continent', 0x58), ('nation', 0x60), ('parent_competition', 0x68)):
        pointer = players.u64(read(address + offset, 8))
        if not pointer:
            linked[field] = None
            continue
        if pointer < 4096 or pointer % 8:
            raise ValueError(f'Invalid {field} pointer')
        key = (field, pointer)
        if key not in cache:
            if field == 'parent_competition':
                parent_index = int.from_bytes(read(pointer + 8, 4), 'little')
                parent = by_index(read, base, parent_index)
                info = database.table(read, base, 'competitions')
                if world.pointer(read, info['start'] + parent_index * 8) != pointer:
                    raise ValueError('Parent competition table membership changed')
                cache[key] = parent
            else:
                cache[key] = geography.record(read, base, pointer, field)
        linked[field] = cache[key]
    kind, gender = struct.unpack('<bB', read(address + 0xF8, 2))
    reputation = struct.unpack('<h', read(address + 0x188, 2))[0]
    level = struct.unpack('<b', read(address + 0x1AA, 1))[0]
    return {**linked,
            'reputation': reputation,
            'level': None if level == 100 else level + 1,
            'level_state': 'not_specified' if level == 100 else 'decoded',
            'native_level_code': level,
            'is_extinct': bool(read(address + 0x1A9, 1)[0] & 4),
            'competition_type': {'native_code': kind, 'name': COMPETITION_TYPES.get(kind),
                'state': 'not_specified' if kind == -1 else 'decoded' if kind in COMPETITION_TYPES else 'unmapped'},
            'gender': {'native_code': gender, 'name': GENDERS.get(gender),
                'state': 'decoded' if gender in GENDERS else 'unmapped'}}


def by_index(read, base, index, *, include_context=False, context_cache=None):
    if type(index) is not int or index < 0:
        raise ValueError('Invalid competition index')
    info = database.table(read, base, 'competitions')
    if index >= info['count']:
        raise ValueError('Competition index is outside its native table')
    address = world.pointer(read, info['start'] + index * 8)
    # Native getters prefer the primary vector when mode bit zero is clear.
    # Require that selected object to agree with the canonical table membership.
    if not read(base + LOOKUP_MODE, 1)[0] & 1:
        start, end, capacity = struct.unpack('<QQQ', read(info['root'] + 0x68, 24))
        if start == end == capacity == 0:
            count = 0
        else:
            if (start < 4096 or any(p % 8 for p in (start, end, capacity))
                    or not start <= end <= capacity or capacity-start > 2000000*8):
                raise ValueError('Invalid primary competition table bounds')
            count = (end-start)//8
        if index < count and world.pointer(read, start + index*8) != address:
            raise ValueError('Primary and canonical competition identities disagree')
    world.typed(read, base, address, 'competition')
    table = world.pointer(read, address)
    if players.u64(read(table + 3*8, 8)) != base + PROPERTY_GETTER:
        raise ValueError('Competition property getter changed')
    native_index, identity, secondary = struct.unpack('<III', read(address+8, 12))
    if native_index != index or not identity:
        raise ValueError('Competition identity fields disagree')
    names = {}
    for field, offset in (('name',0x40),('short_name',0x48),('abbreviation',0x50)):
        pointer = players.u64(read(address+offset, 8))
        if not pointer:
            names[field] = None
        elif read(pointer,4) == bytes(4):
            if read(pointer+4,1) != b'\0':
                raise ValueError('Invalid empty competition string')
            names[field] = ''
        else:
            names[field] = world.string(read,pointer)
    return {'native_id': identity, 'random_id': None if secondary == identity else secondary, 'database_index': index, **names,
            'name_source': 'stored_native_strings',
            **({'context': _context(read, base, address, context_cache)} if include_context else {})}
