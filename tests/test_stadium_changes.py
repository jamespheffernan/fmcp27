import struct

import pytest

from fm_live_mcp import stadium_changes, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import bind, database_memory
from test_players import memory
from test_stadiums import stadium_memory
from test_teams import team_memory
from test_world import world_memory


@pytest.fixture
def changes_memory(stadium_memory, team_memory):
    m = stadium_memory
    addresses = []
    for i in range(3):
        a = m['typed']('stadium_change', 0x70)
        m['put'](a + 8, struct.pack('<III', i, 500+i, 500+i))
        m['q'](a + 0x18, m['team_addresses'][i] if i < 2 else 0)
        for field, off in stadium_changes.STADIUM_LINKS.items():
            m['q'](a + off, m['stadium_addresses'][(i+1) % 3] if field == 'new_stadium' else m['stadium_addresses'][i])
        for field, (off, _) in stadium_changes.DATES.items():
            packed = (1900 << 16 | 1) if field == 'latest_move' else (2032 << 16 | 366)
            m['put'](a + off, struct.pack('<I', packed))
        for j, (off, _, _) in enumerate(stadium_changes.INTEGERS.values()):
            m['put'](a + off, struct.pack('<i', j * 1000 if i == 0 else -1))
        m['put'](a + 0x64, struct.pack('<bB4b', i+1, 4 if i == 0 else 3, 75, 20, 0, 5))
        addresses.append(a)
    m['vec'](m['headers']['stadium_changes'], addresses)
    m['q'](m['base'] + world.TYPES['stadium_change'][0] + 24, m['base'] + stadium_changes.PROPERTY_GETTER)
    m['change_addresses'] = addresses
    return m


def test_complete_records_links_and_missing_values(bridge, monkeypatch, changes_memory):
    m = changes_memory; bind(bridge, monkeypatch, m)
    page = bridge.find_stadium_changes(bridge.session)
    assert page['count'] == page['total_records'] == 3 and page['complete_table_scan']
    first, second, third = page['stadium_changes']
    assert first['type']['name'] == 'Stadium Move' and second['type']['state'] == 'unmapped'
    assert third['type']['name'] == 'Training Ground Move' and third['team'] is None
    assert first['is_potential_move'] is True and second['is_potential_move'] is False
    assert first['dates']['start']['date'] == '2032-12-31'
    assert first['dates']['leave']['native_property'] == 'Ssta'
    assert first['dates']['latest_move']['state'] == 'not_specified'
    assert first['new_capacity']['value'] == 0 and second['new_capacity']['value'] is None
    assert first['new_training_level']['value'] == 20 and first['new_youth_level']['value'] == 0
    assert first['move_likelihood']['value'] == 75 and first['move_likelihood']['unit'] == 'native_level'
    assert first['stadium_condition']['name'] == 'Very Poor'
    for field in ('future_development_fund', 'expected_season_tickets_sold', 'rental_cash'):
        assert first[field]['unit'] is None and first[field]['state'] == 'unit_unverified'
        assert first[field]['native_value'] == first[field]['value']
        assert second[field]['value'] is None and second[field]['native_value'] == -1
    for row in page['stadium_changes']:
        if row['team']:
            team = bridge.get_team_squad(bridge.session, row['team']['team_ref'])['team']
            assert team['native_id'] == row['team']['native_id']
        for field in stadium_changes.STADIUM_LINKS:
            fresh = bridge.get_stadium(bridge.session, row[field]['stadium_ref'])['stadium']
            assert fresh['native_id'] == row[field]['native_id']
        fresh = bridge.get_stadium_change(bridge.session, row['stadium_change_ref'])['stadium_change']
        assert fresh['native_id'] == row['native_id']


@pytest.mark.parametrize('criteria,ids', [({}, [500, 501, 502]), ({'native_id': 501}, [501]),
    ({'team_native_id': 50}, [500]), ({'type_code': 2}, [501]),
    ({'stadium_native_id': 688}, [500, 502]), ({'stadium_native_id': 690, 'type_code': 2}, [501]),
    ({'native_id': 500, 'team_native_id': 51}, []), ({'type_code': -1}, [])])
def test_combined_filters(bridge, monkeypatch, changes_memory, criteria, ids):
    bind(bridge, monkeypatch, changes_memory)
    page = bridge.find_stadium_changes(bridge.session, **criteria)
    assert [r['native_id'] for r in page['stadium_changes']] == ids


def test_empty_pages_and_query_bound_cursors(bridge, monkeypatch, changes_memory):
    m = changes_memory; bind(bridge, monkeypatch, m)
    page = bridge.find_stadium_changes(bridge.session, type_code=3, record_budget=1)
    assert page['count'] == 0 and page['next_cursor'] and page['stop_reason'] == 'record_budget'
    with pytest.raises(BridgeError, match='different query'):
        bridge.find_stadium_changes(bridge.session, type_code=2, cursor=page['next_cursor'])
    fresh = bridge.find_stadium_changes(bridge.session, type_code=3, cursor=page['next_cursor'], record_budget=2, max_matches=1)
    assert fresh['count'] == 1 and fresh['next_cursor'] is None and not fresh['complete_table_scan']
    m['vec'](m['headers']['stadium_changes'], m['change_addresses'])
    with pytest.raises(BridgeError, match='expired'):
        bridge.find_stadium_changes(bridge.session, type_code=3, cursor=page['next_cursor'])


@pytest.mark.parametrize('criteria', [{'native_id': True}, {'team_native_id': 0}, {'stadium_native_id': 2**32},
    {'type_code': True}, {'type_code': -129}, {'type_code': 128}, {'max_matches': 101},
    {'record_budget': 0}, {'record_budget': 1001}, {'cursor': False}, {'cursor': ''}])
def test_invalid_selectors(bridge, criteria):
    with pytest.raises(BridgeError):
        bridge.find_stadium_changes(bridge.session, **criteria)


@pytest.mark.parametrize('value,state', [(-1, 'not_specified'), (0, 'unmapped'), (1, 'decoded'),
    (2, 'unmapped'), (3, 'decoded'), (4, 'decoded'), (5, 'decoded'), (6, 'unmapped'), (-128, 'unmapped'), (127, 'unmapped')])
def test_signed_types_preserve_unmapped_codes(changes_memory, value, state):
    m = changes_memory; a = m['change_addresses'][0]
    m['put'](a + 0x64, struct.pack('<b', value))
    row, _, _ = stadium_changes.record(m['read'], m['base'], a)
    assert row['type']['native_code'] == value and row['type']['state'] == state


@pytest.mark.parametrize('flags,expected', [(0, False), (1, False), (2, False), (4, True), (7, True), (248, False), (255, True)])
def test_only_verified_flag_bit(changes_memory, flags, expected):
    m = changes_memory; a = m['change_addresses'][0]
    m['put'](a + 0x65, bytes([flags]))
    assert stadium_changes.record(m['read'], m['base'], a)[0]['is_potential_move'] is expected


@pytest.mark.parametrize('raw,state', [(0, 'invalid_native_date'), (1900<<16|1, 'not_specified'),
    (2030<<16|366, 'invalid_native_date'), (2032<<16|366, 'stored'), (9999<<16|365, 'stored')])
def test_dates_keep_unset_invalid_and_native_year(changes_memory, raw, state):
    m = changes_memory; a = m['change_addresses'][0]
    for off, _ in stadium_changes.DATES.values():
        m['put'](a + off, struct.pack('<I', raw))
    row, _, _ = stadium_changes.record(m['read'], m['base'], a)
    assert all(d['state'] == state for d in row['dates'].values())


@pytest.mark.parametrize('value', [-2147483648, -2, -1, 0, 2147483647])
def test_signed_integers_do_not_clamp_or_scale(changes_memory, value):
    m = changes_memory; a = m['change_addresses'][0]
    for off, _, _ in stadium_changes.INTEGERS.values():
        m['put'](a + off, struct.pack('<i', value))
    row, _, _ = stadium_changes.record(m['read'], m['base'], a)
    for field in stadium_changes.INTEGERS:
        assert row[field]['native_value'] == value and row[field]['value'] == (None if value == -1 else value)


@pytest.mark.parametrize('fault', ['type', 'getter', 'index', 'id', 'membership', 'rtti',
    'team_pointer', 'team_membership', 'team_type', 'stadium_pointer', 'stadium_type', 'table_rtti'])
def test_bad_records_never_publish_partial_refs(bridge, monkeypatch, changes_memory, fault):
    m = changes_memory; bind(bridge, monkeypatch, m); a = m['change_addresses'][1]
    vt = m['base'] + world.TYPES['stadium_change'][0]
    if fault == 'type': m['q'](a, m['base'] + world.TYPES['club'][0])
    elif fault == 'getter': m['q'](vt + 24, 0)
    elif fault == 'index': m['put'](a + 8, struct.pack('<I', 0))
    elif fault == 'id': m['put'](a + 12, bytes(8))
    elif fault == 'membership': m['vec'](m['headers']['stadium_changes'], list(reversed(m['change_addresses'])))
    elif fault == 'rtti': m['q'](vt - 16, 8)
    elif fault == 'team_pointer': m['q'](a + 0x18, 101)
    elif fault == 'team_membership': m['put'](m['team_addresses'][1] + 8, struct.pack('<I', 0))
    elif fault == 'team_type': m['q'](m['team_addresses'][1], m['base'] + world.TYPES['club'][0])
    elif fault == 'stadium_pointer': m['q'](a + 0x28, 101)
    elif fault == 'stadium_type': m['q'](a + 0x28, m['club'])
    else: m['q'](m['roots']['stadium_changes'], 0)
    with pytest.raises(BridgeError): bridge.find_stadium_changes(bridge.session)
    assert not bridge.stadium_change_refs and not bridge.stadium_refs and not bridge.team_refs


@pytest.mark.parametrize('fault', ['identity', 'membership', 'save', 'detach', 'cache'])
def test_parent_reference_expiry(bridge, monkeypatch, changes_memory, fault):
    m = changes_memory; bind(bridge, monkeypatch, m)
    ref = bridge.find_stadium_changes(bridge.session)['stadium_changes'][0]['stadium_change_ref']
    if fault == 'identity': m['put'](m['change_addresses'][0] + 12, struct.pack('<II', 70, 70))
    elif fault == 'membership': m['vec'](m['headers']['stadium_changes'], list(reversed(m['change_addresses'])))
    elif fault == 'save': m['q'](m['save'] + 0x28, m['text']('Another career'))
    elif fault == 'detach': bridge.detach()
    else: bridge.stadium_change_refs.clear()
    with pytest.raises(BridgeError): bridge.get_stadium_change(bridge.session, ref)
    assert ref not in bridge.stadium_change_refs


def test_fields_and_links_refresh_with_independent_child_refs(bridge, monkeypatch, changes_memory):
    m = changes_memory; bind(bridge, monkeypatch, m)
    row = bridge.find_stadium_changes(bridge.session)['stadium_changes'][0]; a = m['change_addresses'][0]
    m['q'](a + 0x18, 0); m['q'](a + 0x20, 0); m['q'](a + 0x28, m['stadium_addresses'][2]); m['q'](a + 0x48, 0)
    m['put'](a + 0x3C, struct.pack('<i', 65000))
    fresh = bridge.get_stadium_change(bridge.session, row['stadium_change_ref'])['stadium_change']
    assert fresh['team'] is None and fresh['current_stadium'] is None and fresh['alternative_stadium'] is None
    assert fresh['new_stadium']['native_id'] == 690 and fresh['new_capacity']['value'] == 65000
    assert bridge.get_stadium(bridge.session, row['new_stadium']['stadium_ref'])['stadium']['native_id'] == 689
    assert bridge.get_team_squad(bridge.session, row['team']['team_ref'])['team']['native_id'] == 50


def test_cache_reservation_retains_every_returned_reference(bridge, monkeypatch, changes_memory):
    bind(bridge, monkeypatch, changes_memory)
    for cache in (bridge.stadium_change_refs, bridge.stadium_refs, bridge.team_refs):
        cache.update({str(i): {} for i in range(10000)})
    rows = bridge.find_stadium_changes(bridge.session)['stadium_changes']
    for row in rows:
        assert row['stadium_change_ref'] in bridge.stadium_change_refs
        if row['team']: assert row['team']['team_ref'] in bridge.team_refs
        for field in stadium_changes.STADIUM_LINKS:
            assert row[field]['stadium_ref'] in bridge.stadium_refs


def test_concurrent_field_change_rejects_every_result(bridge, monkeypatch, changes_memory):
    m = changes_memory; bind(bridge, monkeypatch, m); target = m['change_addresses'][1] + 0x18; hits = 0
    def read(address, size):
        nonlocal hits
        if (address, size) == (target, 0x52):
            hits += 1
            if hits == 2: m['put'](target + 0x24, struct.pack('<i', 12345))
        return m['read'](address, size)
    monkeypatch.setattr(bridge, '_read_memory', lambda p, a, n: read(a, n))
    with pytest.raises(BridgeError, match='changed during read'): bridge.find_stadium_changes(bridge.session)
    assert not bridge.stadium_change_refs and not bridge.stadium_refs and not bridge.team_refs
