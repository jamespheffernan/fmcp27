import struct

import pytest

from fm_live_mcp import club_finance, transfer_budget, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import database_memory, bind
from test_players import memory
from test_world import world_memory


@pytest.fixture
def finance_memory(database_memory):
    m = database_memory
    finance = m['typed']('club_finance', 0x840)
    m['q'](m['club'] + 0x150, finance)
    m['q'](m['base'] + world.TYPES['club'][0] + 24, m['base'] + 0xE476C4)
    for slot, getter in club_finance.GETTERS.items():
        m['q'](m['base'] + world.TYPES['club_finance'][0] + slot*8, m['base'] + getter)
    for name, value in [('balance', -1000000), ('weekly_wage_budget', 6000000), ('stored_transfer_budget', 20000000)]:
        m['put'](finance + club_finance.FIELDS[name], struct.pack('<i', value))
    currency = m['typed']('currency', 0x58)
    m['put'](currency + 8, struct.pack('<III', 0, 86, 86))
    m['q'](currency + 0x18, m['text']('United Kingdom Pound'))
    m['put'](currency + 0x38, struct.pack('<f', 1.0))
    m['vec'](m['headers']['currencies'], [currency])
    m['put'](m['base'] + 0x538EF50, struct.pack('<I', 86))
    for kind, root, getters in [('game_club', transfer_budget.GAME_CLUB_ROOT, {7: 0x1FC7914, 22: 0x1FAF4D8}),
                                ('game_club_finance', transfer_budget.GAME_FINANCE_ROOT, {9: 0x1FFD5F0})]:
        service = m['typed'](kind, 8)
        m['q'](m['base'] + root, service)
        for slot, getter in getters.items():
            m['q'](m['base'] + world.TYPES[kind][0] + slot*8, m['base'] + getter)
    for offset, value in [(0x56D34E0, 1), (0x56D4951, 0), (0x56D4972, 1), (0x56D4987, 1), (0x56D4999, 0)]:
        m['put'](m['base'] + offset, bytes([value]))
    m['q'](m['base'] + world.TYPES['club_finance'][0] + 8*8, m['base'] + 0xEB8174)
    m['q'](m['base'] + world.TYPES['club_finance'][0] + 40*8, m['base'] + 0xE83ED0)
    m['put'](finance + 0x814, struct.pack('<i', 4500000))
    m['put'](m['club'] + 0x163, b'\x10')
    m['vec'](m['club'] + 0x118, [])
    m.update(finance=finance, currency=currency)
    return m


def test_finances_signed_balance_and_full_native_budget_range(bridge, monkeypatch, finance_memory):
    m = finance_memory
    bind(bridge, monkeypatch, m)
    result = bridge.get_club_finances(bridge.session)
    assert result['finances'] == {'state': 'stored', 'currency': 'GBP', 'balance': -1000000,
        'weekly_wage_budget': 6000000, 'stored_transfer_budget': 20000000,
        'unavailable_fields': [],
        'current_transfer_budget': {'amount': 20000000, 'state': 'decoded', 'reason': 'native_current_budget',
                                    'evidence': 'native_current_transfer_budget_property'},
        'remaining_weekly_wage_budget': {'amount': 1500000, 'state': 'stored',
            'reason': 'native_budget_less_stored_spending', 'weekly_spending_used': 4500000,
            'evidence': 'native_remaining_wage_budget_property', 'freshness': 'stored_without_refresh'},
        'evidence': 'native_cash_properties_and_base_currency'}
    assert 'not remaining wage room' in result['limitations']
    assert 'availability rules' in result['limitations']
    m['put'](m['finance'] + 0x7C4, struct.pack('<i', -1))
    m['put'](m['finance'] + 0x808, bytes(4))
    fresh = bridge.get_club_finances(bridge.session)['finances']
    assert fresh['stored_transfer_budget'] == -1 and fresh['weekly_wage_budget'] == 0
    assert 'available_transfer_budget' not in fresh


def test_null_finance_record_is_unavailable_not_zero(bridge, monkeypatch, finance_memory):
    m = finance_memory
    bind(bridge, monkeypatch, m)
    m['q'](m['club'] + 0x150, 0)
    result = bridge.get_club_finances(bridge.session)['finances']
    assert result['state'] == 'no_finance_record'
    assert all(result[key] is None for key in (*club_finance.FIELDS, 'currency'))


def test_base_finance_reads_only_balance(bridge, monkeypatch, finance_memory):
    m = finance_memory
    basic = m['typed']('club_finance_base', 0x38)
    m['q'](m['club'] + 0x150, basic)
    m['put'](basic + 12, struct.pack('<i', -2700))
    for slot, getter in club_finance.BASE_GETTERS.items():
        m['q'](m['base'] + world.TYPES['club_finance_base'][0] + slot*8, m['base'] + getter)
    m['q'](m['base'] + world.TYPES['club_finance_base'][0] + 8*8, m['base'] + 0xE648D4)
    bind(bridge, monkeypatch, m)
    result = bridge.get_club_finances(bridge.session)['finances']
    assert result['state'] == 'partial_base_record' and result['balance'] == -2700
    assert result['currency'] == 'GBP'
    assert result['weekly_wage_budget'] is None and result['stored_transfer_budget'] is None
    assert result['unavailable_fields'] == ['weekly_wage_budget', 'stored_transfer_budget', 'current_transfer_budget', 'remaining_weekly_wage_budget']
    assert result['current_transfer_budget']['state'] == 'not_applicable'
    m['q'](m['base'] + world.TYPES['club_finance_base'][0] + 54*8, 0)
    with pytest.raises(BridgeError, match='getter'): bridge.get_club_finances(bridge.session)


@pytest.mark.parametrize('fault', ['type', 'rtti', 'club_getter', 'finance_getter', 'negative_wage', 'currency'])
def test_invalid_finance_fails_whole_query(bridge, monkeypatch, finance_memory, fault):
    m = finance_memory
    bind(bridge, monkeypatch, m)
    if fault == 'type': m['q'](m['finance'], m['base'] + world.TYPES['club'][0])
    if fault == 'rtti': m['put'](m['base'] + world.TYPES['club_finance'][0] - 16, struct.pack('<q', 8))
    if fault == 'club_getter': m['q'](m['base'] + world.TYPES['club'][0] + 24, 0)
    if fault == 'finance_getter': m['q'](m['base'] + world.TYPES['club_finance'][0] + 54*8, 0)
    if fault == 'negative_wage': m['put'](m['finance'] + 0x808, struct.pack('<i', -1))
    if fault == 'currency': m['put'](m['currency'] + 0x38, struct.pack('<f', 1.1))
    with pytest.raises(BridgeError, match='finances rejected'):
        bridge.get_club_finances(bridge.session)


@pytest.mark.parametrize('changed', ['balance', 'weekly_wage_budget', 'stored_transfer_budget', 'pointer'])
def test_finance_mutation_rejected(bridge, monkeypatch, finance_memory, changed):
    m = finance_memory
    bind(bridge, monkeypatch, m)
    original = club_finance.decode
    def mutate(*args):
        result = original(*args)
        if changed == 'pointer': m['q'](m['club'] + 0x150, 0)
        else: m['put'](m['finance'] + club_finance.FIELDS[changed], struct.pack('<i', 123))
        return result
    monkeypatch.setattr(club_finance, 'decode', mutate)
    with pytest.raises(BridgeError, match='changed'): bridge.get_club_finances(bridge.session)


def test_selected_club_rechecks_membership_and_selector(bridge, monkeypatch, finance_memory):
    m = finance_memory
    bind(bridge, monkeypatch, m)
    bridge.club_refs['selected'] = {'address': m['club'], 'database_index': 0,
                                   'identity': (688, 688), 'tables': m['tables']}
    expected = bridge.get_club_finances(bridge.session)['finances']
    assert bridge.get_club_finances(bridge.session, club_ref='selected')['finances'] == expected
    with pytest.raises(BridgeError, match='either'):
        bridge.get_club_finances(bridge.session, club_ref='selected', coach_name='Test Coach')
    m['vec'](m['headers']['clubs'], [])
    with pytest.raises(BridgeError, match='reference rejected'):
        bridge.get_club_finances(bridge.session, club_ref='selected')
    assert 'selected' not in bridge.club_refs
