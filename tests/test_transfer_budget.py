import struct

import pytest

from fm_live_mcp import transfer_budget, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_club_finance import finance_memory
from test_database import database_memory, bind
from test_players import memory
from test_world import world_memory


def decoded(m, stored=1000000):
    return transfer_budget.decode(m['read'], m['base'], m['club'], m['finance'], stored)


@pytest.mark.parametrize('stored,expected', [(-2147483648, -2147483648), (-1, -1), (0, 0),
    (1, 0), (499, 0), (500, 500), (2147483647, 2147483647)])
def test_native_small_budget_clamp_and_signed_boundaries(finance_memory, stored, expected):
    result = decoded(finance_memory, stored)
    assert result['amount'] == expected and result['state'] == 'decoded'


@pytest.mark.parametrize('offset,value,reason', [(0x56D34E0, 0, 'inactive_game_property_route'),
    (0x56D4951, 1, 'alternate_game_mode'), (0x56D4999, 1, 'manager_budget_adjustment_not_decoded')])
def test_unsupported_modes_never_substitute_stored_budget(finance_memory, offset, value, reason):
    m = finance_memory
    m['put'](m['base'] + offset, bytes([value]))
    result = decoded(m)
    assert result['amount'] is None and result['state'] == 'unavailable' and result['reason'] == reason


def test_global_rule_and_dated_unknown(finance_memory):
    m = finance_memory
    m['put'](m['base'] + 0x56D4972, b'\0')
    assert decoded(m)['reason'] == 'dated_global_rule_not_decoded'
    assert decoded(m)['amount'] is None
    m['put'](m['base'] + 0x56D4987, b'\0')
    assert decoded(m)['amount'] == 0 and decoded(m)['reason'] == 'native_global_rule_zero'
    # Global zero returns before the unsupported manager-adjustment branch.
    m['put'](m['base'] + 0x56D4999, b'\1')
    assert decoded(m)['state'] == 'decoded'


@pytest.mark.parametrize('identity', [False, True])
def test_native_unavailable_sentinel_is_not_money(finance_memory, identity):
    m = finance_memory
    if identity: m['put'](m['club'] + 12, struct.pack('<I', 0xD70DD0))
    else: m['put'](m['club'] + 0x161, b'\x40')
    result = decoded(m)
    assert result['amount'] is None and result['state'] == 'not_applicable'


@pytest.mark.parametrize('code', range(256))
def test_relationship_rule_native_bitmask(finance_memory, code):
    m = finance_memory
    row = m['allocate'](0x38)
    m['q'](row, m['club'] + 8)
    m['q'](row + 8, m['club'])
    m['put'](row + 0x30, bytes([code]))
    m['vec'](m['club'] + 0x118, [row])
    m['put'](m['club'] + 0x163, b'\0')
    assert decoded(m)['amount'] == (0 if code in (4, 5, 6, 7, 8, 20) else 1000000)
    m['q'](row + 8, m['club'] + 8)
    assert decoded(m)['amount'] == 1000000
    m['q'](row + 8, m['club'])
    m['q'](row, 0)
    assert decoded(m)['amount'] == 1000000
    m['q'](row, m['club'] + 8)
    m['put'](m['club'] + 0x163, b'\x10')
    assert decoded(m)['amount'] == 1000000


@pytest.mark.parametrize('kind,slot', [('game_club', 7), ('game_club', 22), ('game_club_finance', 9), ('club_finance', 8)])
def test_changed_native_routes_fail(finance_memory, kind, slot):
    m = finance_memory
    m['q'](m['base'] + world.TYPES[kind][0] + slot*8, 0)
    with pytest.raises(ValueError, match='changed'): decoded(m)


@pytest.mark.parametrize('offset', [0x56D34E0, 0x56D4951, 0x56D4972, 0x56D4999])
def test_consumed_mode_changes_reject_whole_query(bridge, monkeypatch, finance_memory, offset):
    m = finance_memory
    bind(bridge, monkeypatch, m)
    original = transfer_budget.decode
    def mutate(*args):
        result = original(*args)
        m['put'](m['base'] + offset, b'\x03')
        return result
    monkeypatch.setattr(transfer_budget, 'decode', mutate)
    with pytest.raises(BridgeError, match='changed'): bridge.get_club_finances(bridge.session)


def test_unknown_current_budget_is_listed(bridge, monkeypatch, finance_memory):
    m = finance_memory
    bind(bridge, monkeypatch, m)
    m['put'](m['base'] + 0x56D4999, b'\1')
    result = bridge.get_club_finances(bridge.session)['finances']
    assert result['stored_transfer_budget'] == 20000000
    assert result['current_transfer_budget']['amount'] is None
    assert result['unavailable_fields'] == ['current_transfer_budget']


@pytest.mark.parametrize('fee,fits,remaining', [(0, True, 20000000), (20000000, True, 0),
    (20000001, False, -1), (2147483647, False, -2127483647)])
def test_fee_comparison_exact_boundaries(bridge, monkeypatch, finance_memory, fee, fits, remaining):
    bind(bridge, monkeypatch, finance_memory)
    result = bridge.check_transfer_budget(bridge.session, fee)
    assert result['fits_current_transfer_budget'] is fits
    assert result['budget_after_upfront_fee'] == remaining
    assert result['currency'] == 'GBP'


def test_fee_comparison_unknown_and_negative_budget(bridge, monkeypatch, finance_memory):
    m = finance_memory
    bind(bridge, monkeypatch, m)
    m['put'](m['finance'] + 0x7C4, struct.pack('<i', -100))
    result = bridge.check_transfer_budget(bridge.session, 0)
    assert result['fits_current_transfer_budget'] is False and result['budget_after_upfront_fee'] == -100
    m['put'](m['base'] + 0x56D4999, b'\1')
    result = bridge.check_transfer_budget(bridge.session, 0)
    assert result['fits_current_transfer_budget'] is None and result['budget_after_upfront_fee'] is None


@pytest.mark.parametrize('fee', [True, -1, 2147483648, 1.1, '1', None])
def test_fee_validation_precedes_reads(bridge, monkeypatch, fee):
    monkeypatch.setattr(bridge, 'get_club_finances', lambda *a, **kw: pytest.fail('read before validation'))
    with pytest.raises(BridgeError, match='upfront_fee_gbp'): bridge.check_transfer_budget(bridge.session, fee)
