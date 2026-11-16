import struct

import pytest

from fm_live_mcp import players, staff
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import database_memory, bind, receipt
from test_players import memory
from test_world import world_memory


@pytest.fixture(params=list(staff.LAYOUTS))
def staff_record(request, database_memory):
    m = database_memory
    kind = request.param
    primary, person, offset, data_offset, name = staff.LAYOUTS[kind]
    shared = m['read'](0x1278, players.SIZE - 0x278)
    m['put'](0x1000, bytes(offset + 32))
    m['put'](0x1000 + offset - 0x110, shared)
    for field_offset, rva, displacement, rtti in ((0, primary, 0, name), (offset, person, -offset, name),
                         (data_offset, staff.NON_PLAYING_RVA, 0, b'N2db16NON_PLAYING_DATAE')):
        m['q'](0x1000 + field_offset, m['base'] + rva)
        info, text = m['allocate'](16), m['allocate'](len(rtti) + 1)
        m['put'](text, rtti + b'\0')
        m['q'](info + 8, text)
        m['put'](m['base'] + rva - 16, struct.pack('<qQ', displacement, info))
    for slot, adjustment in ((40, 0x150), (41, 0x158), (42, 0x160), (55, 0x1C8)):
        m['q'](m['base'] + players.RVA[2] + slot * 8, 0x8000 + slot * 8)
        m['q'](m['base'] + person + slot * 8, 0x8000 + slot * 8)
        m['put'](m['base'] + person - adjustment, struct.pack('<q', -0x110))
    m['vec'](m['headers']['people'], [0x1000 + offset])
    contract = m['typed']('full_contract', 32)
    m['q'](contract + 8, 0x1000 + offset)
    m['q'](contract + 16, m['team'])
    m['q'](contract + 24, m['team'])
    m['q'](0x1000 + offset - 0x98, contract)
    m.update(staff_kind=kind, staff_offset=offset, staff_contract=contract)
    return m


def setup(bridge, monkeypatch, m):
    bind(bridge, monkeypatch, m)
    monkeypatch.setattr(bridge, '_run', lambda *a: receipt(staff_examined=1))


def test_staff_search_and_fresh_contract(bridge, monkeypatch, staff_record):
    m = staff_record
    setup(bridge, monkeypatch, m)
    found = bridge.find_staff(bridge.session, 'Test')
    assert found['staff_examined'] == 1 and found['complete_table_scan']
    person = found['staff'][0]
    assert person['name'] == 'Test Müller' and person['birth_date'] == '2000-02-29'
    assert person['record_kind'] == m['staff_kind']
    ref = person['staff_ref']
    assert bridge.get_staff(bridge.session, ref, True)['staff']['contract']['club']['name'] == 'Test United'
    # References must recheck membership even while the pointed-to person is intact.
    m['vec'](m['headers']['people'], [m['club']])
    with pytest.raises(BridgeError, match='live table index'): bridge.get_staff(bridge.session, ref)
    assert ref not in bridge.staff_refs


@pytest.mark.parametrize('fault', ['data_type', 'person_type', 'getter', 'displacement', 'zero_id', 'non_table', 'birthday'])
def test_staff_bad_layout_never_publishes_refs(bridge, monkeypatch, staff_record, fault):
    m = staff_record
    setup(bridge, monkeypatch, m)
    primary, person, offset, data_offset, _ = staff.LAYOUTS[m['staff_kind']]
    if fault == 'data_type': m['q'](0x1000 + data_offset, 0)
    if fault == 'person_type': m['q'](0x1000 + offset, 0)
    if fault == 'getter': m['q'](m['base'] + person + 40*8, 0)
    if fault == 'displacement': m['q'](m['base'] + primary - 16, 1)
    if fault == 'zero_id': m['put'](0x1000 + offset + 12, bytes(4))
    if fault == 'non_table': m['put'](0x1000 + offset + 8, b'\xff'*4)
    if fault == 'birthday': m['put'](0x1000 + offset - 0xB8, bytes(4))
    with pytest.raises(BridgeError): bridge.find_staff(bridge.session, 'Test')
    assert bridge.staff_refs == {}


def test_staff_contract_owner_and_null_contract(bridge, monkeypatch, staff_record):
    m = staff_record
    setup(bridge, monkeypatch, m)
    ref = bridge.find_staff(bridge.session, 'Test')['staff'][0]['staff_ref']
    m['q'](m['staff_contract'] + 8, 0)
    with pytest.raises(BridgeError): bridge.get_staff(bridge.session, ref, True)
    ref = bridge.find_staff(bridge.session, 'Test')['staff'][0]['staff_ref']
    m['q'](0x1000 + m['staff_offset'] - 0x98, 0)
    assert bridge.get_staff(bridge.session, ref, True)['staff']['contract']['state'] == 'no_contract'
    bridge.detach()
    assert not bridge.staff_refs


@pytest.mark.parametrize('secondary', [0, 999])
def test_staff_independent_ids_are_accepted_and_bound(bridge, monkeypatch, staff_record, secondary):
    m = staff_record
    setup(bridge, monkeypatch, m)
    address = 0x1000 + m['staff_offset'] + 16
    m['put'](address, struct.pack('<I', secondary))
    ref = bridge.find_staff(bridge.session, 'Test')['staff'][0]['staff_ref']
    assert bridge.get_staff(bridge.session, ref)['staff']['name'] == 'Test Müller'
    m['put'](address, struct.pack('<I', secondary + 1))
    with pytest.raises(BridgeError, match='identity changed'):
        bridge.get_staff(bridge.session, ref)
    assert ref not in bridge.staff_refs


def test_staff_null_name_target_is_absent_but_not_unreadable(staff_record):
    m = staff_record
    handle = m['allocate'](8)
    m['q'](0x1000 + m['staff_offset'] - 0xF0, handle)
    assert staff.decode(m['read'], m['base'], 0x1000)[0]['name'] == 'Müller'
    m['q'](handle, 123)
    with pytest.raises(KeyError): staff.decode(m['read'], m['base'], 0x1000)


def test_staff_cursor_cannot_be_used_for_players(bridge, monkeypatch, staff_record):
    m = staff_record
    setup(bridge, monkeypatch, m)
    m['vec'](m['headers']['people'], [0x1000 + m['staff_offset'], m['manager']])
    monkeypatch.setattr(bridge, '_run', lambda *a: receipt(staff_examined=1, stop_reason='match_limit'))
    cursor = bridge.find_staff(bridge.session, 'Test', max_matches=1)['next_cursor']
    with pytest.raises(BridgeError, match='different query'):
        bridge.find_save_players(bridge.session, 'Test', cursor=cursor)


@pytest.mark.parametrize('contract_kind', ['basic_contract', 'full_contract'])
def test_staff_contract_allows_two_squads_with_same_club(staff_record, contract_kind):
    m = staff_record
    person = 0x1000 + m['staff_offset']
    contract = m['typed'](contract_kind, 32)
    youth = m['typed']('team', 0xB8)
    m['q'](youth + 0x30, m['club'])
    m['vec'](m['club'] + 0x18, [m['team'], youth])
    for offset, value in ((8, person), (16, youth), (24, m['team'])):
        m['q'](contract + offset, value)
    m['q'](person - 0x98, contract)
    assert staff.contract_club(m['read'], m['base'], person, m['club'])['state'] == contract_kind
    other = m['typed']('club', 0x170)
    m['q'](youth + 0x30, other)
    with pytest.raises(ValueError): staff.contract_club(m['read'], m['base'], person)


def club_fixture(bridge, monkeypatch, m):
    from fm_live_mcp import world
    setup(bridge, monkeypatch, m)
    for offset in (0x60, 0x78, 0x90):
        m['vec'](m['club'] + offset, [0x1000])
    m['q'](m['team'] + 0x80, 0x1000)
    record = {'coaches': [{'name': 'Test Coach', 'team_address': m['team'],
                           'club': {'name': 'Test United', 'short_name': 'Test'}}]}
    monkeypatch.setattr(bridge, '_world_state', lambda *a: (world.ReadSet(m['read']), record, ()))


def test_club_staff_deduplicates_vectors_and_managers(bridge, monkeypatch, staff_record):
    m = staff_record
    club_fixture(bridge, monkeypatch, m)
    roster = bridge.get_club_staff(bridge.session)
    assert roster['count'] == 1 and roster['native_vector_counts'] == [1, 1, 1]
    assert roster['team_manager_links'] == 1
    person = roster['staff'][0]
    fresh = bridge.get_staff(bridge.session, person['staff_ref'], True)['staff']
    assert fresh == {key: value for key, value in person.items() if key != 'staff_ref'}
    with pytest.raises(BridgeError, match='not both'):
        bridge.get_club_staff(bridge.session, coach_name='Test Coach', club_ref='invalid')


@pytest.mark.parametrize('fault', ['contract_owner', 'contract_null', 'membership', 'foreign_club', 'vector_mutation'])
def test_club_staff_rejects_broken_employment_without_refs(bridge, monkeypatch, staff_record, fault):
    m = staff_record
    club_fixture(bridge, monkeypatch, m)
    if fault == 'contract_owner': m['q'](m['staff_contract'] + 8, 0)
    if fault == 'contract_null': m['q'](0x1000 + m['staff_offset'] - 0x98, 0)
    if fault == 'membership': m['vec'](m['headers']['people'], [m['club']])
    if fault == 'foreign_club':
        other, team = m['typed']('club', 0x170), m['typed']('team', 0xB8)
        m['put'](other + 12, struct.pack('<II', 77, 77))
        m['q'](other + 0xC0, m['text']('Another Club'))
        m['q'](other + 0xC8, m['text']('Other'))
        m['q'](team + 0x30, other)
        m['vec'](other + 0x18, [team])
        m['q'](m['staff_contract'] + 16, team)
        m['q'](m['staff_contract'] + 24, team)
    if fault == 'vector_mutation':
        original = staff.decode
        def mutate(*a, **kw):
            result = original(*a, **kw)
            m['vec'](m['club'] + 0x60, [])
            return result
        monkeypatch.setattr(staff, 'decode', mutate)
    with pytest.raises(BridgeError): bridge.get_club_staff(bridge.session)
    assert not bridge.staff_refs
