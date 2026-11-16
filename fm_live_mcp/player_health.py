"""Stored fitness values and native player injury vectors; no refresh execution."""
import struct

from . import database, players, world

GETTERS = {21: 0xD09BB0, 138: 0xD3012C, 139: 0xD19E70, 141: 0xD3016C}
FIELDS = {'condition': (0x254, 0, 10000), 'match_sharpness': (0x250, 0, 10000),
          'fatigue': (0x252, -32768, 32767)}
LIMITATIONS = ('Condition, sharpness and fatigue are stored readings without executing the native refresh. '
               'Condition and sharpness use native 0–10000 units; fatigue uses a signed native value, higher meaning more fatigued. '
               'Injury records describe the native injury vector, including records that may allow participation. '
               'They do not establish match eligibility, training clearance or a recovery forecast.')


def verify_getters(read, base, table, virtual=False):
    expected = {21: 0xD5BEA8, 141: 0xD5C1A4} if virtual else GETTERS
    for slot, getter in expected.items():
        if players.u64(read(table + slot*8, 8)) != base + getter:
            raise ValueError('Player health getter changed')


def injury(read, base, address, info):
    # Injury instances are non-polymorphic. Their owning vector and definition
    # membership supply the checked links; do not interpret their first word as RTTI.
    raw = read(address, 0x38)
    definition = players.u64(raw, 8)
    world.typed(read, base, definition, 'injury')
    data = read(definition, 0x28)
    index, identity, secondary = struct.unpack_from('<III', data, 8)
    if (not identity or index >= info['count']
            or world.pointer(read, info['start'] + index*8) != definition):
        raise ValueError('Injury definition is no longer at its live table index')
    if players.u64(read(base + world.TYPES['injury'][0] + 3*8, 8)) != base + 0x1329D64:
        raise ValueError('Injury property getter changed')
    return {'name': world.string(read, players.u64(data, 0x18)),
            'sentence_name': world.string(read, players.u64(data, 0x20)),
            'started': world.packed_date(raw[0x20:0x24]),
            'evidence': 'native_player_injury_vector_and_typed_definition'}


def decode(read, base, address, virtual=False):
    table = world.pointer(read, address)
    verify_getters(read, base, table, virtual)
    if virtual:
        return {'condition': None, 'match_sharpness': None, 'fatigue': 0,
                'injury_record_count': 0, 'injuries': [], 'state': 'partial_virtual',
                'unavailable_fields': ['condition', 'match_sharpness'],
                'native_defaults': ['fatigue', 'injury_record_count'],
                'evidence': 'native_virtual_constant_getters', 'limitations': LIMITATIONS}
    values = {name: struct.unpack('<h', read(address + offset, 2))[0] for name, (offset, _, _) in FIELDS.items()}
    for name, (_, lower, upper) in FIELDS.items():
        if not lower <= values[name] <= upper:
            raise ValueError(f'Stored player health outside verified range: {name}')
    header = players.u64(read(address + 0xF0, 8))
    addresses = world.vector(read, header, 128) if header else ()
    info = database.table(read, base, 'injuries') if addresses else None
    injuries = [injury(read, base, a, info) for a in addresses]
    return {**values, 'injury_record_count': len(injuries), 'injuries': injuries,
            'state': 'stored_without_refresh', 'unavailable_fields': [], 'native_defaults': [],
            'evidence': 'native_player_health_getters_and_injury_vector', 'limitations': LIMITATIONS}
