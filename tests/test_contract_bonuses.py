import struct

import pytest

from fm_live_mcp import contract_bonuses as bonuses, players, staff, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_contract_dates import dated_record
from test_database import database_memory
from test_players import memory
from test_staff import staff_record, setup, club_fixture
from test_virtual import virtual_memory
from test_wages import wage_record
from test_world import world_memory


def put_entries(m, entries):
    raw = b''.join(struct.pack('<ihBB', *entry) for entry in entries)
    address = m['allocate'](max(8, len(raw)))
    m['put'](address, raw)
    m['put'](m['staff_contract'] + 0x68, struct.pack('<QQQ', address, address + len(raw), address + len(raw)))
    return address


@pytest.fixture
def bonus_record(wage_record):
    m = wage_record
    for slot, rva in bonuses.GETTERS.items():
        m['q'](m['base'] + world.TYPES['full_contract'][0] + slot * 8, m['base'] + rva)
    put_entries(m, [(70000 + code, -1, code, 0) for code, *_ in bonuses.BONUSES.values()])
    return m


def decode(m):
    return bonuses.decode(m['read'], m['base'], m['person'])


def test_six_bonuses_first_matching_entry_and_opaque_other_kinds(bonus_record):
    m = bonus_record
    values = [(70000 + code, -1, code, 0) for code, *_ in bonuses.BONUSES.values()]
    # None of these kinds uses the signed parameter to select between duplicates.
    values += [(1, -32768, 32, 255), (-100, 1, 20, 0)]
    put_entries(m, values)
    result = decode(m)
    assert result['currency'] == 'GBP' and result['state'] == 'decoded'
    assert result['native_entry_count'] == 8 and result['other_entry_count'] == 1
    for name, (code, *_) in bonuses.BONUSES.items():
        assert result['bonuses'][name] == {'amount': 70000 + code, 'state': 'stored',
                                         'matching_entry_count': 2 if code == 32 else 1}


def test_missing_zero_empty_basic_and_no_contract_are_distinct(bonus_record):
    m = bonus_record
    put_entries(m, [(0, -1, 32, 0)])
    result = decode(m)
    assert result['bonuses']['appearance_fee']['amount'] == 0
    assert result['bonuses']['goal_bonus'] == {'amount': None, 'state': 'not_present', 'matching_entry_count': 0}
    for empty in ('allocated', 'null'):
        put_entries(m, [])
        if empty == 'null': m['put'](m['staff_contract'] + 0x68, bytes(24))
        result = decode(m)
        assert result['native_entry_count'] == 0 and all(b['state'] == 'not_present' for b in result['bonuses'].values())
    basic = m['typed']('basic_contract', 0x28)
    m['q'](basic + 8, m['person'])
    m['q'](m['person'] - 0x98, basic)
    result = decode(m)
    assert result['state'] == 'basic_contract_bonuses_unavailable' and result['bonuses'] is None
    m['q'](m['person'] - 0x98, 0)
    assert decode(m)['state'] == 'no_contract'


@pytest.mark.parametrize('fault', ['owner', 'type', 'getter', 'property_getter', 'person_getter',
                                  'adjustment', 'alignment', 'order', 'partial_null', 'bound',
                                  'negative', 'negative_duplicate', 'currency'])
def test_invalid_layout_units_vector_and_amount_fail(bonus_record, fault):
    m = bonus_record
    vtable = m['base'] + world.TYPES['full_contract'][0]
    person_table = m['base'] + staff.LAYOUTS[m['staff_kind']][1]
    if fault == 'owner': m['q'](m['staff_contract'] + 8, 0x8000)
    if fault == 'type': m['q'](m['staff_contract'], m['base'] + world.TYPES['loan_contract'][0])
    if fault == 'getter': m['q'](vtable + 52 * 8, 0)
    if fault == 'property_getter': m['q'](vtable + 3 * 8, 0)
    if fault == 'person_getter': m['q'](person_table + 121 * 8, 0)
    if fault == 'adjustment': m['q'](person_table - 0x3D8, 0)
    vectors = {'alignment': (4097, 4105, 4105), 'order': (4104, 4096, 4104),
               'partial_null': (0, 0, 4096), 'bound': (4096, 4096, 4096 + 257 * 8)}
    if fault in vectors: m['put'](m['staff_contract'] + 0x68, struct.pack('<QQQ', *vectors[fault]))
    if fault == 'negative': put_entries(m, [(-1, -1, 32, 0)])
    if fault == 'negative_duplicate': put_entries(m, [(1, -1, 32, 0), (-1, 0, 32, 0)])
    if fault == 'currency': m['put'](m['currency'] + 0x38, struct.pack('<f', 2))
    with pytest.raises(ValueError): decode(m)


def test_capacity_bound_and_signed_cash_range(bonus_record):
    m = bonus_record
    put_entries(m, [(2147483647, -1, 32, 0)] + [(0, -1, 99, 0)] * 255)
    assert decode(m)['bonuses']['appearance_fee']['amount'] == 2147483647
    assert decode(m)['native_entry_count'] == 256


@pytest.mark.parametrize('fault', ['amount', 'vector', 'owner'])
def test_staff_readback_and_mutation_rejects_reference(bridge, monkeypatch, bonus_record, fault):
    m = bonus_record
    club_fixture(bridge, monkeypatch, m)
    assert 'bonuses' not in bridge.get_club_staff(bridge.session)['staff'][0]['contract']
    row = bridge.get_club_staff(bridge.session, include_contract_bonuses=True)['staff'][0]
    result = bridge.get_staff(bridge.session, row['staff_ref'], include_contract_bonuses=True)['staff']
    assert result['contract'] == row['contract']
    original = bonuses.decode
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        if fault == 'amount':
            start = players.u64(m['read'](m['staff_contract'] + 0x68, 8))
            m['put'](start, struct.pack('<i', 1))
        elif fault == 'vector': m['q'](m['staff_contract'] + 0x70, 0)
        else: m['q'](m['staff_contract'] + 8, 0x8000)
        return result
    monkeypatch.setattr(bonuses, 'decode', mutate)
    with pytest.raises(BridgeError, match='changed'):
        bridge.get_staff(bridge.session, row['staff_ref'], include_contract_bonuses=True)
    assert row['staff_ref'] not in bridge.staff_refs


def test_club_mutation_publishes_no_refs(bridge, monkeypatch, bonus_record):
    m = bonus_record
    club_fixture(bridge, monkeypatch, m)
    original = bonuses.decode
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        m['q'](m['staff_contract'] + 0x70, 0)
        return result
    monkeypatch.setattr(bonuses, 'decode', mutate)
    with pytest.raises(BridgeError, match='changed'):
        bridge.get_club_staff(bridge.session, include_contract_bonuses=True)
    assert not bridge.staff_refs


def test_strict_option(bridge, monkeypatch, bonus_record):
    setup(bridge, monkeypatch, bonus_record)
    for value in (1, 'true', None):
        with pytest.raises(BridgeError, match='boolean'): bridge.get_staff(bridge.session, 'bad', include_contract_bonuses=value)
        with pytest.raises(BridgeError, match='boolean'): bridge.get_player(bridge.session, 'bad', include_contract_bonuses=value)
        with pytest.raises(BridgeError, match='boolean'): bridge.get_club_staff(bridge.session, include_contract_bonuses=value)


def test_regular_player_bonus_and_mutation(bridge, monkeypatch, database_memory):
    from test_database import bind, receipt
    m = database_memory
    bind(bridge, monkeypatch, m)
    monkeypatch.setattr(bridge, '_run', lambda *a: receipt())
    person, table = 0x1388, m['base'] + players.RVA[2]
    m['q'](table + 121 * 8, m['base'] + 0xCB3724)
    m['put'](table - 0x3D8, struct.pack('<q', -0x110))
    contract = m['typed']('full_contract', 0xC8)
    m['q'](contract + 8, person)
    m['q'](person - 0x98, contract)
    m['staff_contract'] = contract
    for slot, rva in bonuses.GETTERS.items():
        m['q'](m['base'] + world.TYPES['full_contract'][0] + slot * 8, m['base'] + rva)
    put_entries(m, [(5000, -1, 33, 0)])
    # Currency-table validation is covered through the staff fixtures and live gate.
    monkeypatch.setattr(bonuses.wages, 'base_currency', lambda *a: 'GBP')
    ref = bridge.find_save_players(bridge.session, 'Test')['players'][0]['player_ref']
    assert 'contract_bonuses' not in bridge.get_player(bridge.session, ref)['player']
    assert bridge.get_player(bridge.session, ref, include_contract_bonuses=True)['player']['contract_bonuses']['bonuses']['goal_bonus']['amount'] == 5000
    original = bonuses.decode
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        m['q'](contract + 0x70, 0)
        return result
    monkeypatch.setattr(bonuses, 'decode', mutate)
    with pytest.raises(BridgeError, match='changed'):
        bridge.get_player(bridge.session, ref, include_contract_bonuses=True)
    assert ref not in bridge.player_refs


def test_virtual_bonus_unsupported(bridge, monkeypatch, virtual_memory):
    from test_virtual import bind
    bind(bridge, monkeypatch, virtual_memory)
    team = bridge.get_club_squads(bridge.session)['squads'][0]
    rows = bridge.get_team_squad(bridge.session, team['team_ref'])['players']
    ref = next(p['player_ref'] for p in rows if p.get('record_kind') == 'virtual')
    with pytest.raises(BridgeError, match='unsupported'):
        bridge.get_player(bridge.session, ref, include_contract_bonuses=True)
