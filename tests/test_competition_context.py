import struct

import pytest

from fm_live_mcp import competitions, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_competitions import competition_record
from test_database import bind, database_memory
from test_geography import add_geography
from test_players import memory
from test_world import world_memory


@pytest.fixture
def context_memory(competition_record):
    m = add_geography(competition_record)
    for index, a in enumerate(m['competitions']):
        m['q'](a + 0x58, m['geography']['continent'][0])
        m['q'](a + 0x60, m['geography']['nation'][index])
        m['put'](a + 0xF8, struct.pack('<bB', 0 if index == 0 else 2, index))
        m['put'](a + 0x188, struct.pack('<h', 200 - index))
        m['put'](a + 0x1A9, bytes([0 if index == 0 else 4, index]))
    m['q'](m['competitions'][1] + 0x68, m['competitions'][0])
    return m


def test_context_and_shallow_parent(bridge, monkeypatch, context_memory):
    m = context_memory
    bind(bridge, monkeypatch, m)
    rows = bridge.find_competitions(bridge.session)['competitions']
    first, second = (row['context'] for row in rows)
    assert first['nation']['short_name'] == 'England' and first['continent']['name'] == 'Europe'
    assert first['parent_competition'] is None and first['reputation'] == 200
    assert first['level'] == 1 and first['level_state'] == 'decoded'
    assert first['native_level_code'] == 0 and not first['is_extinct']
    assert first['competition_type'] == {'native_code': 0, 'name': 'Domestic Top Division', 'state': 'decoded'}
    assert first['gender'] == {'native_code': 0, 'name': 'Male', 'state': 'decoded'}
    assert second['is_extinct'] and second['level'] == 2 and second['gender']['name'] == 'Female'
    assert second['parent_competition']['native_id'] == rows[0]['native_id']
    assert 'context' not in second['parent_competition']
    assert bridge.get_competition(bridge.session, rows[1]['competition_ref'])['competition'] == rows[1]
    # Parent cycles are shallow links, never recursive traversals.
    m['q'](m['competitions'][0] + 0x68, m['competitions'][1])
    assert bridge.find_competitions(bridge.session)['count'] == 2


@pytest.mark.parametrize('code,state', [(-1, 'not_specified'), (30, 'unmapped'), (40, 'unmapped'), (41, 'unmapped'), (-128, 'unmapped')])
def test_missing_and_unmapped_type_codes(context_memory, code, state):
    m = context_memory
    m['put'](m['competitions'][0] + 0xF8, struct.pack('<b', code))
    row = competitions.by_index(m['read'], m['base'], 0, include_context=True)['context']
    assert row['competition_type'] == {'native_code': code, 'name': None, 'state': state}


@pytest.mark.parametrize('code,value', [(100, None), (-1, 0), (0, 1), (19, 20), (127, 128)])
def test_level_matches_native_property_including_sentinel(context_memory, code, value):
    m = context_memory
    m['put'](m['competitions'][0] + 0x1AA, struct.pack('<b', code))
    row = competitions.by_index(m['read'], m['base'], 0, include_context=True)['context']
    assert row['level'] == value and row['native_level_code'] == code
    assert row['level_state'] == ('not_specified' if code == 100 else 'decoded')


def test_null_links_unknown_gender_and_independent_flag_bits(context_memory):
    m = context_memory
    a = m['competitions'][0]
    m['put'](a + 0x58, bytes(24))
    m['put'](a + 0xF9, b'\xff')
    m['put'](a + 0x1A9, b'\xfb')
    row = competitions.by_index(m['read'], m['base'], 0, include_context=True)['context']
    assert all(row[k] is None for k in ('nation', 'continent', 'parent_competition'))
    assert row['gender'] == {'native_code': 255, 'name': None, 'state': 'unmapped'}
    assert not row['is_extinct']


@pytest.mark.parametrize('criteria,expected', [
    ({'nation': 'eng'}, [100]), ({'nation': 'fra'}, [101]), ({'continent': 'eur'}, [100, 101]),
    ({'type_code': 0}, [100]), ({'type_code': 2}, [101]), ({'type_code': 41}, []),
    ({'gender': 'male'}, [100]), ({'gender': 'female'}, [101]),
    ({'is_extinct': False}, [100]), ({'is_extinct': True}, [101]),
    ({'nation': 'England', 'continent': 'Europe', 'type_code': 0, 'gender': 'male', 'is_extinct': False}, [100]),
    ({'nation': 'England', 'gender': 'female'}, []),
])
def test_context_filters_combine(bridge, monkeypatch, context_memory, criteria, expected):
    bind(bridge, monkeypatch, context_memory)
    result = bridge.find_competitions(bridge.session, **criteria)
    assert [r['native_id'] for r in result['competitions']] == expected


@pytest.mark.parametrize('criteria', [{'nation': 'England'}, {'continent': 'Europe'}, {'type_code': 0}, {'gender': 'male'}, {'is_extinct': False}])
def test_context_filters_bound_to_cursor(bridge, monkeypatch, context_memory, criteria):
    bind(bridge, monkeypatch, context_memory)
    cursor = bridge.find_competitions(bridge.session, max_matches=1)['next_cursor']
    with pytest.raises(BridgeError, match='different query'):
        bridge.find_competitions(bridge.session, cursor=cursor, **criteria)


@pytest.mark.parametrize('criteria', [{'nation': ''}, {'continent': 'é' * 65}, {'nation': 'x\n'}, {'nation': '\ud800'}, {'type_code': True}, {'type_code': 128}, {'gender': 'unknown'}, {'gender': []}, {'is_extinct': 1}])
def test_invalid_context_filters(bridge, criteria):
    with pytest.raises(BridgeError):
        bridge.find_competitions(bridge.session, **criteria)


@pytest.mark.parametrize('offset', [0x58, 0x60, 0x68])
def test_invalid_link_pointers(context_memory, offset):
    m = context_memory
    m['q'](m['competitions'][0] + offset, 1)
    with pytest.raises(ValueError):
        competitions.by_index(m['read'], m['base'], 0, include_context=True)


@pytest.mark.parametrize('fault', ['nation_name', 'nation_table', 'parent_name', 'parent_link', 'reputation', 'level', 'type', 'gender', 'extinct'])
def test_context_mutation_rejects_whole_page(bridge, monkeypatch, context_memory, fault):
    m = context_memory
    bind(bridge, monkeypatch, m)
    original = competitions.by_index
    def changing(read, base, index, **kwargs):
        row = original(read, base, index, **kwargs)
        if index == 1 and kwargs.get('include_context'):
            a = m['competitions'][0]
            if fault == 'nation_name':
                m['q'](m['geography']['nation'][0] + 0x20, m['text']('Changed'))
            elif fault == 'nation_table':
                m['vec'](m['headers']['nations'], list(reversed(m['geography']['nation'])))
            elif fault == 'parent_name':
                m['q'](a + 0x40, m['text']('Changed parent'))
            elif fault == 'parent_link':
                m['q'](m['competitions'][1] + 0x68, 0)
            else:
                offset = {'reputation': 0x188, 'level': 0x1AA, 'type': 0xF8, 'gender': 0xF9, 'extinct': 0x1A9}[fault]
                m['put'](a + offset, b'\x04')
        return row
    monkeypatch.setattr(competitions, 'by_index', changing)
    with pytest.raises(BridgeError, match='changed during read'):
        bridge.find_competitions(bridge.session)
    assert not bridge.competition_refs


def test_context_cache_does_not_outlive_query(bridge, monkeypatch, context_memory):
    m = context_memory
    bind(bridge, monkeypatch, m)
    bridge.find_competitions(bridge.session)
    m['q'](m['geography']['nation'][0] + 0x20, m['text']('Changed nation'))
    row = bridge.find_competitions(bridge.session)['competitions'][0]
    assert row['context']['nation']['short_name'] == 'Changed nation'
