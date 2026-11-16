import asyncio
import struct

import pytest
from mcp.server.fastmcp import FastMCP

from fm_live_mcp import live_transfer_payment_schedule as query, transfer_payment_schedule_tools
from fm_live_mcp.bridge import BridgeError
from prepared_tactics_fixture import prepared_tactics_memory
from test_bridge import bridge
from test_club_debt_obligations import debt_memory
from test_club_finance import finance_memory
from test_database import database_memory
from test_live_transfer_debt_obligations import live_debt
from test_players import memory
from test_retained_transfer_debt import transfer_memory
from test_teams import team_memory
from test_transfer_payment_timing import timing_memory
from test_world import world_memory


@pytest.fixture
def live_schedule(live_debt, timing_memory):
    assert live_debt is timing_memory
    return live_debt


@pytest.mark.parametrize('selection', ['managed', 'club_ref'])
def test_guarded_query_separates_projected_cash_from_native_debt(live_schedule, selection):
    m = live_schedule
    before = dict(m['cells'])
    kwargs = {'coach_name': 'Test Coach'} if selection == 'managed' else {'club_ref': 'club'}
    result = query.get_club_transfer_payment_schedule(m['bridge'], m['bridge'].session, **kwargs)
    row = result['transfer_payment_schedule']['records'][0]
    assert row['native_cash_timing']['next_native_cash_branch']['date'] == '2031-07-01'
    assert row['native_cash_timing']['next_native_cash_branch']['call_argument_amount'] == 12000
    assert row['native_remaining_amount']['amount'] == 8000
    outgoing = result['projected_native_payment_schedule']['directions']['outgoing']
    assert outgoing['next_projected_native_payment_date'] == '2031-07-01'
    assert outgoing['next_native_call_argument_sum'] == outgoing['remaining_native_call_argument_sum'] == 12000
    assert result['native_debt_totals']['gross_outgoing']['amount'] == 8000
    assert result['projected_native_payment_schedule']['actual_payment_state'] == 'not_established'
    assert result['projected_native_payment_schedule']['arrears_state'] == 'not_established'
    assert result['atomic'] is result['native_calls'] is result['saved_file_fallback'] is False
    assert m['cells'] == before
    assert m['closed'] == [True] and m['bridge']._reader is None


@pytest.mark.parametrize('field', ['row', 'clock', 'nation', 'person_header', 'processing'])
@pytest.mark.parametrize('callback', ['public_save', 'final_current'])
def test_every_new_input_is_rechecked_after_final_callbacks(live_schedule, monkeypatch, field, callback):
    m, bridge = live_schedule, live_schedule['bridge']
    address = {'row': m['outgoing'] + 33, 'clock': m['base'] + query.transfer_payment_timing.world.CURRENT_DATE,
               'nation': m['club'] + 0xD8, 'person_header': m['headers']['people'],
               'processing': m['base'] + 0x56D4987}[field]
    def mutate():
        m['put'](address, bytes([m['read'](address, 1)[0] ^ 1]))
    if callback == 'public_save':
        original = bridge._public_save
        def public(save):
            mutate()
            return original(save)
        monkeypatch.setattr(bridge, '_public_save', public)
    else:
        original = bridge._current
        calls = []
        def current(session):
            calls.append(1)
            if len(calls) == 3:
                mutate()
            return original(session)
        monkeypatch.setattr(bridge, '_current', current)
    with pytest.raises(BridgeError, match='changed during read'):
        query.get_club_transfer_payment_schedule(bridge, bridge.session)
    assert m['closed'] == [True] and bridge._reader is None


def test_missing_or_partial_projection_never_becomes_next_payment_zero(live_schedule):
    m = live_schedule
    m['put'](m['outgoing'] + 33, b'\0')
    report = query.transfer_payment_timing.decode(m['read'], m['base'], m['club'])
    summary = query.payment_schedule_summary(report)
    outgoing = summary['directions']['outgoing']
    assert outgoing['state'] == 'partial_projection'
    assert outgoing['next_projected_native_payment_date'] is outgoing['remaining_native_call_argument_sum'] is None
    assert summary['directions']['incoming']['state'] == 'complete_projection'
    m['q'](m['base'] + query.transfer_payment_timing.retained.ROOT, 0)
    summary = query.payment_schedule_summary(query.transfer_payment_timing.decode(m['read'], m['base'], m['club']))
    assert summary['state'] == 'source_unavailable'
    assert summary['directions']['outgoing']['record_count'] is None
    assert summary['directions']['outgoing']['remaining_native_call_argument_sum'] is None


def test_observed_empty_prefix_is_complete_zero_with_no_next_date(live_schedule):
    m = live_schedule
    m['vec'](m['transfer_manager'] + 0xD8, [])
    result = query.get_club_transfer_payment_schedule(m['bridge'], m['bridge'].session)
    for direction in result['projected_native_payment_schedule']['directions'].values():
        assert direction['state'] == 'complete_projection'
        assert direction['record_count'] == 0
        assert direction['remaining_native_call_argument_sum'] == 0
        assert direction['next_projected_native_payment_date'] is None


def test_summary_callback_mutation_is_inside_final_physical_acceptance(live_schedule, monkeypatch):
    m = live_schedule
    original = query.payment_schedule_summary
    def summary(report):
        result = original(report)
        m['put'](m['base'] + 0x56D4987, b'\0')
        return result
    monkeypatch.setattr(query, 'payment_schedule_summary', summary)
    with pytest.raises(BridgeError, match='changed during read'):
        query.get_club_transfer_payment_schedule(m['bridge'], m['bridge'].session)


def test_read_only_schema_names_the_native_projection_and_distinct_amounts():
    mcp = FastMCP('transfer-native-calendar-control')
    transfer_payment_schedule_tools.register_transfer_payment_schedule_tools(mcp, object())
    tools = asyncio.run(mcp.list_tools())
    assert len(tools) == 1 and tools[0].name == 'fm_get_club_transfer_payment_schedule'
    assert tools[0].annotations.readOnlyHint is True and tools[0].annotations.destructiveHint is False
    assert tools[0].inputSchema['required'] == ['session_id']
    assert set(tools[0].inputSchema['properties']) == {'session_id', 'coach_name', 'club_ref'}
    assert 'unit times interval' in tools[0].description
    assert 'unit times remaining counter' in tools[0].description
    assert 'Actual paid/arrears state' in tools[0].description
