import asyncio
import struct

import pytest
from mcp.server.fastmcp import FastMCP

from fm_live_mcp import debt_obligation_tools, live_debt_obligations as query, world
from fm_live_mcp.bridge import BridgeError
from prepared_tactics_fixture import prepared_tactics_memory
from test_bridge import bridge
from test_club_debt_obligations import debt_memory
from test_club_finance import finance_memory
from test_database import database_memory
from test_players import memory
from test_teams import team_memory
from test_world import world_memory


@pytest.fixture
def live_debt(prepared_tactics_memory, debt_memory, bridge, monkeypatch):
    m = debt_memory
    assert m is prepared_tactics_memory
    m['bridge'], m['closed'] = bridge, []
    bridge.plugin_identity = ('synthetic_pinned_plugin',)
    class Stream:
        def __init__(self, helper, pid):
            self.pid = pid
        def close(self):
            m['closed'].append(True)
    monkeypatch.setattr(query, 'ReadStream', Stream)
    monkeypatch.setattr(bridge, '_player_layout', lambda process: m['tables'])
    monkeypatch.setattr(bridge, '_read_memory', lambda process,a,n: m['read'](a,n))
    monkeypatch.setattr(bridge, '_run', lambda *args: pytest.fail('Unexpected native helper command'))
    club, identity = world.club(m['read'], m['base'], m['club'])
    bridge.club_refs['club'] = {'address': m['club'], 'database_index': 0,
                               'identity': identity, 'tables': m['tables']}
    return m


@pytest.mark.parametrize('selection', ['managed', 'club_ref'])
def test_current_canonical_report_and_source_unknowns_use_read_only_adapter(live_debt, selection):
    m = live_debt
    before = dict(m['cells'])
    kwargs = {'coach_name': ' test COACH '} if selection == 'managed' else {'club_ref': 'club'}
    result = query.get_club_debt_obligations(m['bridge'], m['bridge'].session, **kwargs)
    assert result['club']['native_id'] == 688
    assert result['debt_obligations']['financial_owner'] == result['club']
    assert result['debt_obligations']['records'][0]['remaining_debt']['amount'] == 10800
    assert result['debt_obligations']['complete_liability_ledger'] is False
    assert result['atomic'] is result['native_calls'] is result['saved_file_fallback'] is False
    assert result['save_identity'] == 'native_binding_rechecked'
    assert m['cells'] == before
    assert m['closed'] == [True] and m['bridge']._reader is None


@pytest.mark.parametrize('mutation', ['final_current', 'public_save', 'second_layout', 'save_identity', 'club_ref'])
def test_post_projection_callbacks_cannot_publish_stale_amount(live_debt, monkeypatch, mutation):
    m, bridge = live_debt, live_debt['bridge']
    if mutation == 'final_current':
        original = bridge._current
        calls = []
        def current(session):
            calls.append(1)
            if len(calls) == 3:
                m['put'](m['loan'], b'\x01')
            return original(session)
        monkeypatch.setattr(bridge, '_current', current)
    elif mutation == 'public_save':
        original = bridge._public_save
        def public(save):
            m['q'](m['club'] + 0x100, 0)
            return original(save)
        monkeypatch.setattr(bridge, '_public_save', public)
    elif mutation == 'second_layout':
        original = bridge._player_layout
        calls = []
        def layout(process):
            calls.append(1)
            if len(calls) == 2:
                bridge.plugin_identity = ('changed_plugin',)
            return original(process)
        monkeypatch.setattr(bridge, '_player_layout', layout)
    elif mutation == 'save_identity':
        original = bridge._world_state
        calls = []
        def loaded(process, tables):
            result = original(process, tables)
            calls.append(1)
            if len(calls) == 2:
                return result[0], result[1], ('changed_save',)
            return result
        monkeypatch.setattr(bridge, '_world_state', loaded)
    else:
        original = bridge._public_save
        def public(save):
            m['put'](m['club'] + 12, struct.pack('<I', 999))
            return original(save)
        monkeypatch.setattr(bridge, '_public_save', public)
    with pytest.raises(BridgeError, match='rejected'):
        query.get_club_debt_obligations(bridge, bridge.session, club_ref='club')
    assert m['closed'] == [True] and bridge._reader is None


@pytest.mark.parametrize('arguments', [
    {'session_id': ''}, {'session_id': True}, {'coach_name': ''}, {'coach_name': True},
    {'club_ref': ''}, {'club_ref': True}, {'club_ref': 'club', 'coach_name': 'Test Coach'},
])
def test_invalid_selectors_fail_before_reader_creation(live_debt, arguments):
    m = live_debt
    kwargs = {'session_id': m['bridge'].session, **arguments}
    with pytest.raises(BridgeError):
        query.get_club_debt_obligations(m['bridge'], **kwargs)
    assert m['closed'] == [] and m['bridge']._reader is None


def test_registration_schema_exposes_read_only_selected_club_query():
    mcp = FastMCP('debt-obligation-unit-control')
    debt_obligation_tools.register_debt_obligation_tools(mcp, object())
    tools = asyncio.run(mcp.list_tools())
    assert len(tools) == 1 and tools[0].name == 'fm_get_club_debt_obligations'
    assert tools[0].annotations.readOnlyHint is True
    assert tools[0].annotations.destructiveHint is False
    schema = tools[0].inputSchema
    assert schema['required'] == ['session_id']
    assert set(schema['properties']) == {'session_id', 'coach_name', 'club_ref'}
    assert 'first-ten-physical-slot' in tools[0].description
    assert 'payment/arrears state' in tools[0].description
