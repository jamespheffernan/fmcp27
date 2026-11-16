"""Stored STADIUM_CHANGE records, with explicit unknown scales and type codes."""
import struct

from . import database, players, stadiums, teams, world

PROPERTY_GETTER = 0x16D5C84
TYPES = {1: 'Stadium Move', 3: 'Training Ground Move',
         4: 'Youth Ground Move', 5: 'Reserve Stadium Move'}
STADIUM_LINKS = {'current_stadium': 0x20, 'new_stadium': 0x28, 'alternative_stadium': 0x48}
DATES = {'start': (0x30, 'Slea'), 'leave': (0x34, 'Ssta'), 'latest_move': (0x38, 'Slmd')}
INTEGERS = {
    'new_capacity': (0x3C, 'Scap', 'people'),
    'new_seated_capacity': (0x40, 'Sscp', 'people'),
    'future_development_fund': (0x44, 'Sceb', None),
    'expected_attendance': (0x50, 'Snxa', 'people'),
    'minimum_expected_attendance': (0x54, 'Snmn', 'people'),
    'maximum_expected_attendance': (0x58, 'Snmx', 'people'),
    'expected_season_tickets_sold': (0x5C, 'Stks', None),
    'rental_cash': (0x60, 'Scam', None),
}
SCOPE = ('Stored stadium-change records, including records without a team or current stadium. '
         'Type labels come from the installed editor; type 2 and other unknown codes remain unmapped. '
         'Start, leave and latest-move dates retain their native property meanings and years; '
         'no construction completion, active-project status or effective stadium allocation is inferred. '
         'Signed -1 means unspecified; zero remains stored. Rental cash, development fund and expected '
         'season tickets retain raw integers with unverified units/scales; no currency conversion is applied. '
         'Move likelihood is a stored level, not a verified probability. Potential move reads only its '
         'verified flag. Nullable team and stadium links carry independent usable references. '
         'Ordinary fields and links refresh; replaced identities, changed saves/builds, detach and cache '
         'eviction expire references. Reads are non-atomic with consumed-byte rechecks.')


def identity(read, base, address):
    if address < 4096 or address % 8:
        raise ValueError('Invalid stadium-change pointer')
    world.typed(read, base, address, 'stadium_change')
    if players.u64(read(base + world.TYPES['stadium_change'][0] + 24, 8)) != base + PROPERTY_GETTER:
        raise ValueError('Stadium-change property getter changed')
    raw = read(address + 8, 12)
    index, native_id, secondary = struct.unpack('<III', raw)
    info = database.table(read, base, 'stadium_changes')
    if (not native_id or index >= info['count']
            or world.pointer(read, info['start'] + index * 8) != address):
        raise ValueError('Stadium-change identity or membership changed')
    return {'address': address, 'database_index': index, 'native_id': native_id, 'identity': raw}


def _integer(value, prop, unit, bounds=None):
    state = ('not_specified' if value == -1 else 'unit_unverified' if unit is None else
             'out_of_range' if bounds is not None and not bounds[0] <= value <= bounds[1] else 'stored')
    return {'native_property': prop, 'native_value': value, 'value': None if value == -1 else value,
            'unit': unit, 'state': state}


def record(read, base, address):
    binding = identity(read, base, address)
    raw = read(address + 0x18, 0x52)
    links = {}
    team_address = players.u64(raw)
    if team_address:
        if team_address < 4096 or team_address % 8:
            raise ValueError('Invalid stadium-change team pointer')
        index = int.from_bytes(read(team_address + 8, 4), 'little')
        team = teams.by_index(read, base, index)
        if team[1]['address'] != team_address:
            raise ValueError('Stadium-change team membership changed')
        links['team'] = team
    else:
        links['team'] = None
    for field, offset in STADIUM_LINKS.items():
        pointer = players.u64(raw, offset - 0x18)
        links[field] = stadiums.record(read, base, pointer) if pointer else None
    type_code = struct.unpack_from('<b', raw, 0x64 - 0x18)[0]
    condition = struct.unpack_from('<b', raw, 0x69 - 0x18)[0]
    row = {'kind': 'stadium_change', 'native_id': binding['native_id'],
           'database_index': binding['database_index'],
           'type': {'native_property': 'Styp', **stadiums._enum(type_code, TYPES, -1)},
           'is_potential_move': bool(raw[0x65 - 0x18] & 4),
           'dates': {field: {'native_property': prop, **stadiums._date(raw[offset-0x18:offset-0x14])}
                     for field, (offset, prop) in DATES.items()},
           'stadium_condition': {'native_property': 'Scns', **stadiums._enum(condition, stadiums.CONDITIONS, -1)},
           **{field: linked[0] if linked else None for field, linked in links.items()}}
    for field, (offset, prop, unit) in INTEGERS.items():
        value = struct.unpack_from('<i', raw, offset - 0x18)[0]
        row[field] = _integer(value, prop, unit, (0, 0x7FFFFFFF))
    for field, offset, prop, bounds in (('move_likelihood', 0x66, 'Slhm', (1, 100)),
                                      ('new_training_level', 0x67, 'ScTL', (0, 20)),
                                      ('new_youth_level', 0x68, 'ScYL', (0, 20))):
        value = struct.unpack_from('<b', raw, offset - 0x18)[0]
        row[field] = _integer(value, prop, 'native_level', bounds)
    return row, binding, links


def by_index(read, base, index):
    info = database.table(read, base, 'stadium_changes')
    if type(index) is not int or not 0 <= index < info['count']:
        raise ValueError('Stadium-change index is outside the native table')
    result = record(read, base, world.pointer(read, info['start'] + index * 8))
    if result[1]['database_index'] != index:
        raise ValueError('Stadium-change database index changed')
    return result
