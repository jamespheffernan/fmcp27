import struct

import pytest

from fm_live_mcp import wage_contributions, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_club_finance import finance_memory
from test_database import database_memory, bind
from test_players import memory
from test_player_staff import staff_memory
from test_staff import staff_record
from test_world import world_memory


@pytest.fixture
def contribution_memory(finance_memory):
    m = finance_memory
    manager = m['typed']('transfer_manager', 0x108)
    m['q'](m['base'] + wage_contributions.ROOT, manager)
    for slot, getter in ((0, 0x2D10D10), (1, 0x2D10D24)):
        m['q'](m['base'] + world.TYPES['transfer_manager'][0] + slot*8, m['base'] + getter)
    m['q'](m['base'] + world.TYPES['game_club_finance'][0] + 80, m['base'] + 0x1FFE24C)
    other = m['typed']('club', 0x170)
    m['put'](other + 8, struct.pack('<III', 1, 700, 700))
    m['q'](other + 0xC0, m['text']('Other Club'))
    m['q'](other + 0xC8, m['text']('Other'))
    m['vec'](m['headers']['clubs'], [m['club'], other])
    def contribution(recipient, payer, amount):
        row = m['allocate'](32)
        m['put'](row, struct.pack('<QQiiI', recipient, payer, 0, amount, (2031 << 16) | 181))
        return row
    outgoing = contribution(other, m['club'], 1500)
    incoming = contribution(m['club'], other, 400)
    m['vec'](manager + 0xF0, [incoming, outgoing])
    m.update(transfer_manager=manager, other_club=other, outgoing=outgoing, incoming=incoming,
             make_contribution=contribution)
    return m


def test_contributions_both_directions_totals_and_fresh_references(bridge, monkeypatch, contribution_memory):
    m = contribution_memory
    bind(bridge, monkeypatch, m)
    result = bridge.get_wage_contributions(bridge.session)
    assert result['currency'] == 'GBP' and result['period'] == 'week'
    assert result['count'] == result['native_records_examined'] == 2
    assert result['outgoing_weekly_total'] == 1500 and result['incoming_weekly_total'] == 400
    assert result['net_outgoing_weekly_total'] == 1100 and result['total_weekly_contributions'] == 1900
    rows = result['contributions']
    assert [row['direction'] for row in rows] == ['outgoing', 'incoming']
    assert rows[0]['paid_until'] == '2031-06-30'
    assert rows[0]['payer']['name'] == 'Test United' and rows[0]['recipient']['name'] == 'Other Club'
    assert bridge.get_player(bridge.session, rows[0]['person']['player_ref'])['player']['name'] == 'Test Müller'
    selected = bridge.get_wage_contributions(bridge.session, club_ref=rows[0]['recipient']['club_ref'])
    assert selected['outgoing_weekly_total'] == 400 and selected['net_outgoing_weekly_total'] == -1100
    all_rows = bridge.get_wage_contributions(bridge.session, all_clubs=True)
    assert all_rows['club'] is None and all_rows['scope'] == 'all_clubs'
    assert all_rows['outgoing_weekly_total'] is None and all_rows['net_outgoing_weekly_total'] is None
    assert all(row['direction'] is None for row in all_rows['contributions'])
    assert all_rows['total_weekly_contributions'] == 1900
    m['vec'](m['headers']['people'], [m['club']])
    with pytest.raises(BridgeError, match='membership changed'):
        bridge.get_player(bridge.session, rows[0]['person']['player_ref'])


def test_selected_empty_is_complete_only_for_native_list(bridge, monkeypatch, contribution_memory):
    m = contribution_memory
    m['vec'](m['transfer_manager'] + 0xF0, [])
    bind(bridge, monkeypatch, m)
    result = bridge.get_wage_contributions(bridge.session)
    assert result['count'] == result['native_records_examined'] == 0
    assert result['complete_native_list'] and result['total_weekly_contributions'] == 0
    assert 'not a complete' in result['limitations']


def test_same_club_and_zero_amount_are_retained(bridge, monkeypatch, contribution_memory):
    m = contribution_memory
    row = m['make_contribution'](m['club'], m['club'], 0)
    m['vec'](m['transfer_manager'] + 0xF0, [row])
    bind(bridge, monkeypatch, m)
    result = bridge.get_wage_contributions(bridge.session)
    assert result['count'] == 1 and result['contributions'][0]['direction'] == 'both'
    assert result['net_outgoing_weekly_total'] == 0


@pytest.mark.parametrize('fault', ['manager_type', 'manager_getter', 'spending_getter', 'inactive',
    'negative', 'bad_date', 'missing_club', 'club_index', 'person_index', 'null_person', 'duplicate', 'bounds', 'currency'])
def test_bad_contributions_fail_without_references(bridge, monkeypatch, contribution_memory, fault):
    m = contribution_memory
    bind(bridge, monkeypatch, m)
    if fault == 'manager_type': m['q'](m['transfer_manager'], m['base'] + world.TYPES['club'][0])
    if fault == 'manager_getter': m['q'](m['base'] + world.TYPES['transfer_manager'][0], 0)
    if fault == 'spending_getter': m['q'](m['base'] + world.TYPES['game_club_finance'][0] + 80, 0)
    if fault == 'inactive': m['put'](m['base'] + 0x56D34E0, b'\0')
    if fault == 'negative': m['put'](m['outgoing'] + 20, struct.pack('<i', -1))
    if fault == 'bad_date': m['put'](m['outgoing'] + 24, bytes(4))
    if fault == 'missing_club': m['vec'](m['headers']['clubs'], [m['club']])
    if fault == 'club_index': m['put'](m['other_club'] + 8, struct.pack('<I', 0))
    if fault == 'person_index': m['put'](m['outgoing'] + 16, struct.pack('<i', 10))
    if fault == 'null_person': m['vec'](m['headers']['people'], [0])
    if fault == 'duplicate': m['vec'](m['transfer_manager'] + 0xF0, [m['outgoing']]*2)
    if fault == 'bounds': m['vec'](m['transfer_manager'] + 0xF0, [m['outgoing']] * 1025)
    if fault == 'currency': m['put'](m['currency'] + 0x38, struct.pack('<f', 1.1))
    with pytest.raises(BridgeError, match='contributions rejected'):
        bridge.get_wage_contributions(bridge.session)
    assert not bridge.player_refs and not bridge.club_refs and not bridge.staff_refs


def test_unsupported_person_keeps_money_and_unknown_identity(bridge, monkeypatch, contribution_memory):
    m = contribution_memory
    unknown = m['allocate'](24)
    m['q'](unknown, m['base'] + 0x100)
    m['vec'](m['headers']['people'], [unknown])
    bind(bridge, monkeypatch, m)
    result = bridge.get_wage_contributions(bridge.session)
    assert result['unresolved_person_count'] == 2 and result['net_outgoing_weekly_total'] == 1100
    assert result['contributions'][0]['person'] == {'name': None, 'state': 'unsupported_person_type', 'database_index': 0}


@pytest.mark.parametrize('field', ['amount', 'date', 'membership', 'vector', 'root'])
def test_detected_mutation_rejects_whole_result(bridge, monkeypatch, contribution_memory, field):
    m = contribution_memory
    bind(bridge, monkeypatch, m)
    original = wage_contributions.decode
    def mutate(*args):
        result = original(*args)
        if field == 'amount': m['put'](m['outgoing'] + 20, struct.pack('<i', 1))
        if field == 'date': m['put'](m['outgoing'] + 24, struct.pack('<I', (2031 << 16) | 182))
        if field == 'membership': m['vec'](m['headers']['people'], [m['club']])
        if field == 'vector': m['vec'](m['transfer_manager'] + 0xF0, [])
        if field == 'root': m['q'](m['base'] + wage_contributions.ROOT, 0)
        return result
    monkeypatch.setattr(wage_contributions, 'decode', mutate)
    with pytest.raises(BridgeError, match='changed'):
        bridge.get_wage_contributions(bridge.session)
    assert not bridge.player_refs and not bridge.club_refs


@pytest.mark.parametrize('args', [{'all_clubs': 1}, {'all_clubs': True, 'club_ref': 'x'},
    {'all_clubs': True, 'coach_name': 'x'}, {'coach_name': 'x', 'club_ref': 'y'}])
def test_bad_selectors_precede_reads(bridge, monkeypatch, args):
    monkeypatch.setattr(bridge, '_current', lambda *a: pytest.fail('read before selector validation'))
    with pytest.raises(BridgeError): bridge.get_wage_contributions(bridge.session, **args)


@pytest.mark.parametrize('staff_record', ['staff', 'human_manager'], indirect=True)
def test_former_player_staff_record_is_named_and_reusable(bridge, monkeypatch, contribution_memory, staff_record):
    bind(bridge, monkeypatch, contribution_memory)
    result = bridge.get_wage_contributions(bridge.session)
    person = result['contributions'][0]['person']
    assert person['state'] == 'decoded' and person['record_kind'] == staff_record['staff_kind']
    assert bridge.get_staff(bridge.session, person['staff_ref'])['staff']['name'] == person['name']


def test_combined_player_staff_record_uses_player_reference(bridge, monkeypatch, contribution_memory, staff_memory):
    bind(bridge, monkeypatch, contribution_memory)
    result = bridge.get_wage_contributions(bridge.session)
    person = result['contributions'][0]['person']
    assert person['record_kind'] == 'player_staff' and person['state'] == 'decoded'
    assert bridge.get_player(bridge.session, person['player_ref'])['player']['name'] == person['name']
