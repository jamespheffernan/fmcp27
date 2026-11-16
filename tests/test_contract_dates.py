import struct

import pytest

from fm_live_mcp import contract_dates, players, staff, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import database_memory
from test_players import memory
from test_staff import staff_record, setup, club_fixture
from test_world import world_memory


def packed(year, day, flags=0):
    return struct.pack('<I', year << 16 | flags << 9 | day)


@pytest.fixture
def dated_record(staff_record):
    m = staff_record
    person = 0x1000 + m['staff_offset']
    table = m['base'] + staff.LAYOUTS[m['staff_kind']][1]
    for slot, getter, adjustment in ((73, 0xCA4764, 0x258), (121, 0xCB3724, 0x3D8)):
        m['q'](table + slot * 8, m['base'] + getter)
        m['put'](table - adjustment, struct.pack('<q', -0x110))
    contract = m['typed']('full_contract', 0xC8)
    for offset, value in ((8, person), (16, m['team']), (24, m['team'])):
        m['q'](contract + offset, value)
    m['q'](person - 0x98, contract)
    m['put'](person - 0x24, packed(2028, 60, 127))
    m['put'](contract + 0x44, packed(2030, 151, 27))
    m['put'](contract + 0x48, packed(2033, 181))
    m['put'](m['base'] + 0x56B1DB8, packed(2030, 261))
    table = m['base'] + world.TYPES['full_contract'][0]
    m['q'](table + 29*8, m['base'] + 0x1005C68)
    m['q'](table + 30*8, m['base'] + 0x12920F8)
    m.update(staff_contract=contract, person=person)
    return m


def decode(m):
    return contract_dates.decode(m['read'], m['base'], m['person'])


def test_fixed_dates_mask_metadata_bits(dated_record):
    result = decode(dated_record)
    assert result == {'joined': '2028-02-29', 'last_signed': '2030-05-31',
                      'expires': '2033-06-30', 'state': 'fixed_expiry',
                      'evidence': 'native_person_and_full_contract_date_getters'}


def test_dynamic_branch_does_not_publish_stale_expiry(dated_record):
    m = dated_record
    m['put'](m['staff_contract'] + 0x2B, bytes([8]))
    m['put'](m['staff_contract'] + 0x48, bytes(4))
    result = decode(m)
    assert result['expires'] == '2031-09-18' and result['state'] == 'dynamic_expiry'
    assert result['expiry_anchor_date'] == '2030-09-18'
    assert result['last_signed'] == '2030-05-31'


def test_basic_and_absent_contract_are_distinct(dated_record):
    m = dated_record
    contract = m['typed']('basic_contract', 0x28)
    m['q'](contract + 8, m['person'])
    m['q'](m['person'] - 0x98, contract)
    result = decode(m)
    assert result['joined'] == '2028-02-29'
    assert result['last_signed'] is None and result['expires'] is None
    assert result['state'] == 'basic_contract_fields_unavailable'
    m['q'](m['person'] - 0x98, 0)
    result = decode(m)
    assert result['state'] == 'no_contract' and result['joined'] is None


@pytest.mark.parametrize('fault', ['owner', 'type', 'getter', 'join_getter', 'join_adjustment',
                                  'pointer_getter', 'pointer_adjustment', 'date', 'nonleap', 'signed'])
def test_bad_dates_or_dispatch_fail(dated_record, fault):
    m = dated_record
    table = m['base'] + staff.LAYOUTS[m['staff_kind']][1]
    if fault == 'owner': m['q'](m['staff_contract'] + 8, 0x2000)
    if fault == 'type': m['q'](m['staff_contract'], 0x8000)
    if fault == 'getter': m['q'](m['base'] + world.TYPES['full_contract'][0] + 30*8, 0)
    if fault == 'join_getter': m['q'](table + 73*8, 0)
    if fault == 'join_adjustment': m['q'](table - 0x258, 0)
    if fault == 'pointer_getter': m['q'](table + 121*8, 0)
    if fault == 'pointer_adjustment': m['q'](table - 0x3D8, 0)
    if fault == 'date': m['put'](m['staff_contract'] + 0x48, bytes(4))
    if fault == 'nonleap': m['put'](m['staff_contract'] + 0x48, packed(2033, 366))
    if fault == 'signed': m['put'](m['staff_contract'] + 0x44, bytes(4))
    with pytest.raises(ValueError): decode(m)


def test_optional_staff_dates_freshness_and_default_omission(bridge, monkeypatch, dated_record):
    m = dated_record
    club_fixture(bridge, monkeypatch, m)
    roster = bridge.get_club_staff(bridge.session, include_contract_dates=True)
    row = roster['staff'][0]
    assert row['contract']['dates']['expires'] == '2033-06-30'
    assert bridge.get_staff(bridge.session, row['staff_ref'], include_contract_dates=True)['staff']['contract'] == row['contract']
    assert 'dates' not in bridge.get_club_staff(bridge.session)['staff'][0]['contract']
    original = contract_dates.decode
    def mutate(*a, **kw):
        result = original(*a, **kw)
        m['put'](m['staff_contract'] + 0x48, packed(2034, 181))
        return result
    monkeypatch.setattr(contract_dates, 'decode', mutate)
    with pytest.raises(BridgeError, match='changed'):
        bridge.get_staff(bridge.session, row['staff_ref'], include_contract_dates=True)


def test_dates_flag_is_strict(bridge, monkeypatch, dated_record):
    setup(bridge, monkeypatch, dated_record)
    for value in (1, 'true', None):
        with pytest.raises(BridgeError, match='boolean'): bridge.get_club_staff(bridge.session, include_contract_dates=value)
        with pytest.raises(BridgeError, match='boolean'): bridge.get_staff(bridge.session, 'ref', include_contract_dates=value)
        with pytest.raises(BridgeError, match='boolean'): bridge.get_player(bridge.session, 'ref', include_contract_dates=value)


def test_expiry_query_boundary_truncation_and_unknowns(bridge, monkeypatch, dated_record):
    m = dated_record
    club_fixture(bridge, monkeypatch, m)
    assert bridge.query_club_staff_contracts(bridge.session, '2033-06-29')['matched_count'] == 0
    result = bridge.query_club_staff_contracts(bridge.session, '2033-06-30')
    assert result['matched_count'] == result['fixed_expiry_count'] == 1
    assert result['unclassified_count'] == 0 and not result['truncated']
    m['put'](m['staff_contract'] + 0x2B, bytes([8]))
    result = bridge.query_club_staff_contracts(bridge.session, '2033-06-30')
    assert result['fixed_expiry_count'] == result['matched_count'] == 0
    assert result['unclassified_count'] == 1
    assert result['unclassified_staff'][0]['contract_dates']['state'] == 'dynamic_expiry'
    # Verify sorting and limits independently of address order.
    rows = [{'staff_ref': str(i), 'display_name': name, 'birth_date': '2000-01-01',
             'contract': {'dates': {'state': 'fixed_expiry', 'expires': expiry}}}
            for i, (name, expiry) in enumerate([('Zed', '2033-06-30'), ('Ada', '2031-06-30')])]
    monkeypatch.setattr(bridge, 'get_club_staff', lambda *a, **kw: {
        'observed_at': 'now', 'save': {}, 'club': {}, 'count': 2, 'staff': rows, 'limitations': ''})
    result = bridge.query_club_staff_contracts(bridge.session, '2033-06-30', limit=1)
    assert result['matched_count'] == 2 and result['returned_count'] == 1 and result['truncated']
    assert result['staff'][0]['display_name'] == 'Ada'


@pytest.mark.parametrize('cutoff', ['20300630', '2030-02-30', '2030-6-30', '2201-01-01', None, 2030])
def test_expiry_query_rejects_bad_date(bridge, cutoff):
    with pytest.raises(BridgeError, match='YYYY-MM-DD'):
        bridge.query_club_staff_contracts(bridge.session, cutoff)


def test_regular_player_dates_and_changed_date_rejection(bridge, monkeypatch, database_memory):
    from test_database import bind, receipt
    m = database_memory
    bind(bridge, monkeypatch, m)
    monkeypatch.setattr(bridge, '_run', lambda *a: receipt())
    person, table = 0x1388, m['base'] + players.RVA[2]
    for slot, getter, adjustment in ((73, 0xCA4764, 0x258), (121, 0xCB3724, 0x3D8)):
        m['q'](table + slot * 8, m['base'] + getter)
        m['put'](table - adjustment, struct.pack('<q', -0x110))
    contract = m['typed']('full_contract', 0xC8)
    m['q'](contract + 8, person)
    m['q'](person - 0x98, contract)
    m['put'](person - 0x24, packed(2028, 60))
    m['put'](contract + 0x44, packed(2030, 151))
    m['put'](contract + 0x48, packed(2033, 181))
    table = m['base'] + world.TYPES['full_contract'][0]
    m['q'](table + 29*8, m['base'] + 0x1005C68)
    m['q'](table + 30*8, m['base'] + 0x12920F8)
    ref = bridge.find_save_players(bridge.session, 'Test')['players'][0]['player_ref']
    assert 'contract_dates' not in bridge.get_player(bridge.session, ref)['player']
    result = bridge.get_player(bridge.session, ref, include_contract_dates=True)
    assert result['player']['contract_dates']['expires'] == '2033-06-30'
    original = contract_dates.decode
    def mutate(*a, **kw):
        result = original(*a, **kw)
        m['put'](contract + 0x48, packed(2034, 181))
        return result
    monkeypatch.setattr(contract_dates, 'decode', mutate)
    with pytest.raises(BridgeError, match='changed'):
        bridge.get_player(bridge.session, ref, include_contract_dates=True)
    assert ref not in bridge.player_refs


def test_dynamic_expiry_exhaustive_calendar_days():
    from datetime import date, timedelta
    # Independent calendar oracle for all supported input years that can advance.
    for year in range(1850, 2200):
        this_days = (date(year + 1, 1, 1) - date(year, 1, 1)).days
        next_days = (date(year + 2, 1, 1) - date(year + 1, 1, 1)).days
        for day in range(1, this_days + 1):
            expected = date(year + 1, 1, 1) + timedelta(days=min(day, next_days) - 1)
            assert contract_dates.dynamic_expiry(packed(year, day, 127)) == expected.isoformat()
    assert contract_dates.dynamic_expiry(packed(2023, 60)) == '2024-02-29'
    assert contract_dates.dynamic_expiry(packed(2024, 60)) == '2025-03-01'
    assert contract_dates.dynamic_expiry(packed(2024, 366)) == '2025-12-31'


@pytest.mark.parametrize('raw', [packed(2030, 0), packed(2030, 366), packed(1849, 1), packed(2200, 1)])
def test_dynamic_expiry_rejects_invalid_or_out_of_range_dates(raw):
    with pytest.raises(ValueError): contract_dates.dynamic_expiry(raw)


def test_dynamic_anchor_mutation_rejects_read(bridge, monkeypatch, dated_record):
    m = dated_record
    club_fixture(bridge, monkeypatch, m)
    m['put'](m['staff_contract'] + 0x2B, bytes([8]))
    original = contract_dates.decode
    def mutate(*a, **kw):
        result = original(*a, **kw)
        m['put'](m['base'] + 0x56B1DB8, packed(2030, 262))
        return result
    monkeypatch.setattr(contract_dates, 'decode', mutate)
    with pytest.raises(BridgeError, match='changed'):
        bridge.get_club_staff(bridge.session, include_contract_dates=True)
