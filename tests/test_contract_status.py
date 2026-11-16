import struct

import pytest

from fm_live_mcp import contract_status, players, staff, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_contract_dates import dated_record
from test_database import database_memory
from test_players import memory
from test_staff import staff_record, setup, club_fixture
from test_world import world_memory
from test_virtual import virtual_memory


@pytest.fixture
def status_record(dated_record):
    m = dated_record
    m['q'](m['base'] + world.TYPES['full_contract'][0] + 27*8, m['base'] + 0x127BE34)
    m['put'](m['staff_contract'] + 0xC3, bytes([1]))
    return m


def decode(m):
    return contract_status.decode(m['read'], m['base'], m['person'])


def test_status_labels_and_unmapped_codes(status_record):
    m = status_record
    for code, label in [(0, 'Part Time'), (1, 'Full Time'), (2, 'Amateur'), (3, 'Youth'), (4, 'Non-Contract')]:
        m['put'](m['staff_contract'] + 0xC3, bytes([code]))
        result = decode(m)
        assert result['title'] == label and result['native_code'] == code and result['state'] == 'decoded'
    for code in (-128, -1, 5, 10, 127):
        m['put'](m['staff_contract'] + 0xC3, struct.pack('<b', code))
        result = decode(m)
        assert result['title'] is None and result['native_code'] == code
        assert result['state'] == 'unmapped_native_status'


def test_basic_and_null_status_are_distinct(status_record):
    m = status_record
    contract = m['typed']('basic_contract', 0x28)
    m['q'](contract + 8, m['person'])
    m['q'](m['person'] - 0x98, contract)
    result = decode(m)
    assert result['state'] == 'basic_contract_status_unavailable' and result['title'] is None
    m['q'](m['person'] - 0x98, 0)
    result = decode(m)
    assert result['state'] == 'no_contract' and result['native_code'] is None


@pytest.mark.parametrize('fault', ['owner', 'type', 'getter', 'person_getter', 'adjustment'])
def test_status_rejects_bad_dispatch_and_ownership(status_record, fault):
    m = status_record
    table = m['base'] + staff.LAYOUTS[m['staff_kind']][1]
    if fault == 'owner': m['q'](m['staff_contract'] + 8, 0x8000)
    if fault == 'type': m['q'](m['staff_contract'], m['base'] + world.TYPES['club'][0])
    if fault == 'getter': m['q'](m['base'] + world.TYPES['full_contract'][0] + 27*8, 0)
    if fault == 'person_getter': m['q'](table + 121*8, 0)
    if fault == 'adjustment': m['q'](table - 0x3D8, 0)
    with pytest.raises(ValueError): decode(m)


def test_staff_options_omission_and_mutation(bridge, monkeypatch, status_record):
    m = status_record
    club_fixture(bridge, monkeypatch, m)
    assert 'status' not in bridge.get_club_staff(bridge.session)['staff'][0]['contract']
    row = bridge.get_club_staff(bridge.session, include_contract_status=True)['staff'][0]
    fresh = bridge.get_staff(bridge.session, row['staff_ref'], include_contract_status=True)['staff']
    assert fresh['contract'] == row['contract']
    assert fresh['contract']['status']['title'] == 'Full Time'
    original = contract_status.decode
    def mutate(*a, **kw):
        result = original(*a, **kw)
        m['put'](m['staff_contract'] + 0xC3, bytes([2]))
        return result
    monkeypatch.setattr(contract_status, 'decode', mutate)
    with pytest.raises(BridgeError, match='changed'):
        bridge.get_staff(bridge.session, row['staff_ref'], include_contract_status=True)
    assert row['staff_ref'] not in bridge.staff_refs


def test_status_arguments_strict(bridge, monkeypatch, status_record):
    setup(bridge, monkeypatch, status_record)
    for value in (1, 'true', None):
        with pytest.raises(BridgeError, match='boolean'): bridge.get_staff(bridge.session, 'invalid', include_contract_status=value)
        with pytest.raises(BridgeError, match='boolean'): bridge.get_player(bridge.session, 'invalid', include_contract_status=value)
        with pytest.raises(BridgeError, match='boolean'): bridge.get_club_staff(bridge.session, include_contract_status=value)


def test_regular_player_status_and_mutation(bridge, monkeypatch, database_memory):
    from test_database import bind, receipt
    m = database_memory
    bind(bridge, monkeypatch, m)
    monkeypatch.setattr(bridge, '_run', lambda *a: receipt())
    person, table = 0x1388, m['base'] + players.RVA[2]
    m['q'](table + 121*8, m['base'] + 0xCB3724)
    m['put'](table - 0x3D8, struct.pack('<q', -0x110))
    contract = m['typed']('full_contract', 0xC8)
    m['q'](contract + 8, person)
    m['q'](person - 0x98, contract)
    m['q'](m['base'] + world.TYPES['full_contract'][0] + 27*8, m['base'] + 0x127BE34)
    m['put'](contract + 0xC3, bytes([3]))
    ref = bridge.find_save_players(bridge.session, 'Test')['players'][0]['player_ref']
    assert 'contract_status' not in bridge.get_player(bridge.session, ref)['player']
    assert bridge.get_player(bridge.session, ref, include_contract_status=True)['player']['contract_status']['title'] == 'Youth'
    original = contract_status.decode
    def mutate(*a, **kw):
        result = original(*a, **kw)
        m['put'](contract + 0xC3, bytes([4]))
        return result
    monkeypatch.setattr(contract_status, 'decode', mutate)
    with pytest.raises(BridgeError, match='changed'):
        bridge.get_player(bridge.session, ref, include_contract_status=True)
    assert ref not in bridge.player_refs


def test_virtual_status_is_explicitly_unsupported(bridge, monkeypatch, virtual_memory):
    from test_virtual import bind
    bind(bridge, monkeypatch, virtual_memory)
    team = bridge.get_club_squads(bridge.session)['squads'][0]
    roster = bridge.get_team_squad(bridge.session, team['team_ref'])['players']
    ref = next(p['player_ref'] for p in roster if p.get('record_kind') == 'virtual')
    with pytest.raises(BridgeError, match='unsupported'):
        bridge.get_player(bridge.session, ref, include_contract_status=True)
