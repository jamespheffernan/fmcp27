import asyncio

import pytest
from mcp.server.fastmcp import FastMCP

from fm_live_mcp import sell_on_transfer_clause_tools, live_sell_on_transfer_clauses as query
from fm_live_mcp.bridge import BridgeError
from prepared_tactics_fixture import prepared_tactics_memory
from test_bridge import bridge
from test_club_debt_obligations import debt_memory
from test_club_finance import finance_memory
from test_contingent_transfer_appearance import appearance_memory
from test_contingent_transfer_sell_on import sell_on_memory
from test_database import database_memory
from test_live_transfer_debt_obligations import live_debt
from test_players import memory
from test_retained_transfer_debt import transfer_memory
from test_teams import team_memory
from test_world import world_memory


@pytest.fixture
def live_clauses(live_debt, sell_on_memory):
    assert live_debt is sell_on_memory
    return live_debt


@pytest.mark.parametrize('selection', ['managed', 'club_ref'])
def test_read_only_selected_payer_query_exposes_conditional_progress(live_clauses, selection):
    m = live_clauses
    before = dict(m['cells'])
    kwargs = {'coach_name': 'Test Coach'} if selection == 'managed' else {'club_ref': 'club'}
    result = query.get_club_sell_on_transfer_clauses(m['bridge'], m['bridge'].session, **kwargs)
    report = result['sell_on_transfer_clauses']
    assert report['selected_club'] == result['club']
    assert len(report['records']) == 3
    assert report['records'][0]['native_percentage'] == 20
    assert report['records'][0]['native_basis_used']['native_signed32'] == 40000
    assert report['incoming_scanned'] is report['complete_liability_ledger'] is False
    assert result['atomic'] is result['native_calls'] is result['saved_file_fallback'] is False
    assert m['cells'] == before
    assert m['closed'] == [True] and m['bridge']._reader is None


@pytest.mark.parametrize('field', ['row', 'container', 'owner_link', 'recipient', 'type'])
@pytest.mark.parametrize('callback', ['public_save', 'final_current'])
def test_final_callbacks_cannot_publish_stale_contingent_terms(live_clauses, monkeypatch, field, callback):
    m, bridge = live_clauses, live_clauses['bridge']
    address = {'row': m['first_clause'] + 30, 'container': m['clause_holder'],
               'owner_link': m['club'] + 0xB0, 'recipient': m['other_club'] + 12,
               'type': m['base'] + query.contingent_transfer_sell_on.TABLE + 0x28}[field]
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
        query.get_club_sell_on_transfer_clauses(bridge, bridge.session)
    assert m['closed'] == [True] and bridge._reader is None


def test_missing_source_and_observed_empty_remain_distinct_in_public_result(live_clauses):
    m = live_clauses
    m['q'](m['club'] + 0xB0, 0)
    result = query.get_club_sell_on_transfer_clauses(m['bridge'], m['bridge'].session)
    assert result['sell_on_transfer_clauses']['records'] is None
    m['q'](m['club'] + 0xB0, m['clause_holder'])
    m['vec'](m['clause_holder'], [])
    result = query.get_club_sell_on_transfer_clauses(m['bridge'], m['bridge'].session)
    assert result['sell_on_transfer_clauses']['records'] == []


def test_read_only_tool_schema_qualifies_supported_family_and_unknown_state():
    mcp = FastMCP('retained-contingent-clause-control')
    sell_on_transfer_clause_tools.register_sell_on_transfer_clause_tools(mcp, object())
    tools = asyncio.run(mcp.list_tools())
    assert len(tools) == 1 and tools[0].name == 'fm_get_club_sell_on_transfer_clauses'
    assert tools[0].annotations.readOnlyHint is True and tools[0].annotations.destructiveHint is False
    assert tools[0].inputSchema['required'] == ['session_id']
    assert set(tools[0].inputSchema['properties']) == {'session_id', 'coach_name', 'club_ref'}
    assert 'NEXT_SALE_PERCENTAGE_INFO' in tools[0].description
    assert 'Incoming records in other clubs' in tools[0].description
    assert 'Basis-used never establishes settlement' in tools[0].description
