import struct

import pytest

from fm_live_mcp import geography, world
from test_database import database_memory
from test_players import memory
from test_world import world_memory


def add_geography(m):
    locations = {}
    for kind, names in (('nation', [('England', 'ENG'), ('France', 'FRA')]),
                        ('continent', [('Europe', 'EUR')])):
        getter, table_kind, fields = geography.FIELDS[kind]
        addresses = []
        for index, values in enumerate(names):
            a = m['typed'](kind, 0x30)
            m['put'](a + 8, struct.pack('<III', index, index + 200, index + 200))
            for (_, offset), value in zip(fields, values):
                m['q'](a + offset, m['text'](value))
            addresses.append(a)
        m['q'](m['base'] + world.TYPES[kind][0] + 24, m['base'] + getter)
        m['vec'](m['headers'][table_kind], addresses)
        locations[kind] = addresses
    m['geography'] = locations
    return m


@pytest.fixture
def geo_memory(database_memory):
    return add_geography(database_memory)


def test_geography_names_and_membership(geo_memory):
    m = geo_memory
    row = geography.record(m['read'], m['base'], m['geography']['nation'][0], 'nation')
    assert row == {'native_id': 200, 'database_index': 0, 'short_name': 'England',
                   'abbreviation': 'ENG', 'name_source': 'stored_native_strings'}
    row = geography.record(m['read'], m['base'], m['geography']['continent'][0], 'continent')
    assert row['name'] == 'Europe' and row['abbreviation'] == 'EUR'


@pytest.mark.parametrize('kind', ['nation', 'continent'])
@pytest.mark.parametrize('fault', ['type', 'getter', 'id', 'index', 'membership', 'string', 'empty_string'])
def test_invalid_geography_fails(geo_memory, kind, fault):
    m = geo_memory
    a = m['geography'][kind][0]
    _, table_kind, fields = geography.FIELDS[kind]
    if fault == 'type':
        m['q'](a, m['base'] + world.TYPES['club'][0])
    elif fault == 'getter':
        m['q'](m['base'] + world.TYPES[kind][0] + 24, 0)
    elif fault == 'id':
        m['put'](a + 12, bytes(8))
    elif fault == 'index':
        m['put'](a + 8, struct.pack('<I', 999))
    elif fault == 'membership':
        m['vec'](m['headers'][table_kind], [m['club']])
    elif fault == 'string':
        m['q'](a + fields[0][1], m['text']('invalid\nname'))
    else:
        pointer = m['text']('')
        m['put'](pointer + 4, b'x')
        m['q'](a + fields[0][1], pointer)
    with pytest.raises(ValueError):
        geography.record(m['read'], m['base'], a, kind)


def test_null_and_empty_geography_strings(geo_memory):
    m = geo_memory
    a = m['geography']['nation'][0]
    m['q'](a + 0x20, 0)
    m['q'](a + 0x28, m['text'](''))
    row = geography.record(m['read'], m['base'], a, 'nation')
    assert row['short_name'] is None and row['abbreviation'] == ''
