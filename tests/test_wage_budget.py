import struct

import pytest

from fm_live_mcp import wage_budget, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_club_finance import finance_memory
from test_database import database_memory, bind
from test_players import memory
from test_world import world_memory


@pytest.mark.parametrize('budget,spending,amount,reason', [
    (100, 50, 50, 'native_budget_less_stored_spending'),
    (100, 100, 0, 'native_budget_less_stored_spending'),
    (100, 101, -1, 'native_budget_less_stored_spending'),
    (100, 0, 100, 'native_budget_less_stored_spending'),
    (100, -1000, 1100, 'native_budget_less_stored_spending'),
    (100, -1001, None, 'native_spending_requires_refresh'),
    (100, -2147483648, None, 'native_spending_requires_refresh'),
    (2147483647, -1, None, 'native_arithmetic_overflow'),
    (1, 2147483647, -2147483646, 'native_budget_less_stored_spending'),
    (0, 9000, 0, 'native_zero_wage_budget'),
    (0, -1001, 0, 'native_zero_wage_budget'),
])
def test_native_arithmetic_and_refresh_boundary(bridge, monkeypatch, finance_memory, budget, spending, amount, reason):
    m = finance_memory
    bind(bridge, monkeypatch, m)
    m['put'](m['finance'] + 0x808, struct.pack('<i', budget))
    m['put'](m['finance'] + 0x814, struct.pack('<i', spending))
    result = bridge.get_club_finances(bridge.session)['finances']
    wage = result['remaining_weekly_wage_budget']
    assert wage['amount'] == amount and wage['reason'] == reason
    assert wage['state'] == ('unavailable' if amount is None else 'stored')
    assert ('remaining_weekly_wage_budget' in result['unavailable_fields']) == (amount is None)


@pytest.mark.parametrize('fault', ['inactive', 'null', 'base', 'getter', 'spending_getter'])
def test_unavailable_and_changed_routes(finance_memory, fault):
    m = finance_memory
    if fault == 'inactive': m['put'](m['base'] + 0x56D34E0, b'\0')
    if fault == 'null': m['finance'] = 0
    if fault == 'base':
        m['finance'] = m['typed']('club_finance_base', 0x38)
        m['q'](m['base'] + world.TYPES['club_finance_base'][0] + 64, m['base'] + 0xE648D4)
    if fault in ('getter', 'spending_getter'):
        m['q'](m['base'] + world.TYPES['club_finance'][0] + (64 if fault == 'getter' else 320), 0)
        with pytest.raises(ValueError, match='changed'):
            wage_budget.decode(m['read'], m['base'], m['finance'], 6000000)
    else:
        result = wage_budget.decode(m['read'], m['base'], m['finance'], 6000000)
        assert result['amount'] is None
        assert result['state'] == ('not_applicable' if fault == 'base' else 'unavailable')


def test_spending_mutation_rejects_result(bridge, monkeypatch, finance_memory):
    m = finance_memory
    bind(bridge, monkeypatch, m)
    original = wage_budget.decode
    def mutate(*args):
        result = original(*args)
        m['put'](m['finance'] + 0x814, struct.pack('<i', 1))
        return result
    monkeypatch.setattr(wage_budget, 'decode', mutate)
    with pytest.raises(BridgeError, match='changed'):
        bridge.check_wage_budget(bridge.session, 500)


@pytest.mark.parametrize('additional,fits,remaining', [(0, True, 1500000),
    (1500000, True, 0), (1500001, False, -1), (2147483647, False, -2145983647)])
def test_comparison_boundaries(bridge, monkeypatch, finance_memory, additional, fits, remaining):
    bind(bridge, monkeypatch, finance_memory)
    result = bridge.check_wage_budget(bridge.session, additional)
    assert result['fits_remaining_wage_budget'] is fits
    assert result['budget_after_additional_wage'] == remaining
    assert result['currency'] == 'GBP' and result['period'] == 'week'


def test_unknown_comparison_stays_unknown(bridge, monkeypatch, finance_memory):
    bind(bridge, monkeypatch, finance_memory)
    finance_memory['put'](finance_memory['finance'] + 0x814, struct.pack('<i', -1001))
    result = bridge.check_wage_budget(bridge.session, 0)
    assert result['fits_remaining_wage_budget'] is None
    assert result['budget_after_additional_wage'] is None


@pytest.mark.parametrize('amount', [True, -1, 2147483648, 1.1, '1', None])
def test_invalid_comparison_never_reads(bridge, monkeypatch, amount):
    monkeypatch.setattr(bridge, 'get_club_finances', lambda *a, **kw: pytest.fail('read before validation'))
    with pytest.raises(BridgeError, match='additional_weekly_wage_gbp'):
        bridge.check_wage_budget(bridge.session, amount)
