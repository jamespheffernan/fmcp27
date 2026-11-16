"""Standalone adapter, real decoder, and synthetic typed native memory controls."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import json
import struct

import pytest
from mcp.server.fastmcp import FastMCP

from fm_live_mcp import contract_wage_step_tools as tools
from fm_live_mcp import contract_bonuses, contract_terms
from fm_live_mcp import live_contract_wage_steps as query, players, virtual_identity, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_contract_bonuses import put_entries
from test_database import database_memory
from test_player_staff import staff_memory
from test_players import memory
from test_world import world_memory


@pytest.fixture(params=['actual', 'player_staff'])
def live_record(request, database_memory, bridge, monkeypatch):
    m = database_memory if request.param == 'actual' else request.getfixturevalue('staff_memory')
    offset = 0x388 if request.param == 'actual' else 0x480
    person = 0x1000 + offset
    table = m['base'] + (players.RVA[2] if offset == 0x388 else players.STAFF_RVA[2])
    m['q'](table + 121 * 8, m['base'] + 0xCB3724)
    m['put'](table - 0x3D8, struct.pack('<q', -0x110))
    contract = m['typed']('full_contract', 0xC8)
    m['q'](contract + 8, person)
    m['q'](person - 0x98, contract)
    m['put'](contract + 0x20, struct.pack('<i', 12121))
    for slot, getter in {9: 0xD8C3C0, **contract_bonuses.GETTERS, **contract_terms.GETTERS}.items():
        m['q'](m['base'] + world.TYPES['full_contract'][0] + slot * 8, m['base'] + getter)
    m['put'](m['base'] + 0x56D4950, b'\0')
    currency = m['typed']('currency', 0x58)
    m['put'](currency + 8, struct.pack('<III', 0, 86, 86))
    m['q'](currency + 0x18, m['text']('United Kingdom Pound'))
    m['put'](currency + 0x38, struct.pack('<f', 1.0))
    m['vec'](m['headers']['currencies'], [currency])
    m['put'](m['base'] + 0x538EF50, struct.pack('<I', 86))
    m.update(staff_contract=contract, person=person)
    entry = put_entries(m, [(20612, 15, 13, 0), (32979, 25, 13, 128)])
    record, identity = players.decode(m['read'], 0x1000, m['tables'])
    binding = {'address': 0x1000, 'tables': m['tables'], 'identity': identity,
               'database_index': 0, 'record_kind': request.param, 'world_bound': True}
    bridge.player_refs['p1'] = deepcopy(binding)
    bridge.plugin_identity = ('synthetic verified plugin stamp', 'synthetic binary UUID')
    m['scopes'] = []
    @contextmanager
    def scope(session):
        m['scopes'].append(('enter', session))
        try: yield
        finally: m['scopes'].append(('exit', session))
    monkeypatch.setattr(bridge, '_read_scope', scope)
    m['layout_calls'] = []
    def layout(process):
        m['layout_calls'].append(process)
        return m['tables']
    monkeypatch.setattr(bridge, '_player_layout', layout)
    monkeypatch.setattr(bridge, '_read_memory', lambda process, a, n: m['read'](a, n))
    monkeypatch.setattr(bridge, '_run', lambda *a: pytest.fail('Unexpected native helper command'))
    m.update(bridge=bridge, binding=binding, entry=entry, currency=currency)
    return m


def get(m, ref='p1'):
    return query.get_contract_wage_steps(m['bridge'], m['bridge'].session, ref)


def test_positive_regular_and_combined_owned_scenarios_and_outer_checks(live_record):
    m = live_record;before = dict(m['cells'])
    result = get(m)
    assert result['save']['current_date'] == '2030-09-19'
    assert result['save_identity'] == 'native_binding_rechecked'
    assert result['player']['name'] == 'Test Müller'
    assert result['player']['native_identity'] == {'database_index': 0, 'native_id': 12345, 'random_id': None}
    assert result['player'].get('record_kind', 'actual') == m['binding']['record_kind']
    source = result['contract_wage_steps']
    assert source['current_weekly_main_wage']['amount'] == 12121
    assert [r['difference_from_current_weekly_main_wage_gbp'] for r in source['steps']] == [8491, 20858]
    assert source['largest_stored_target_increase_gbp'] == 20858
    assert [r['selected_by_native_property'] for r in source['steps']] == [True, False]
    assert not source['activation_evaluated'] and not source['progress_evaluated']
    assert result['atomic'] is result['saved_file_fallback'] is False
    assert m['cells'] == before and len(m['layout_calls']) == 2
    assert m['scopes'] == [('enter', m['bridge'].session), ('exit', m['bridge'].session)]
    public = json.dumps(result)
    assert 'attributes' not in public and 'address' not in public and 'team_address' not in public


def test_complete_empty_scope_and_no_contract_remain_distinct(live_record):
    m = live_record;put_entries(m, [])
    source = get(m)['contract_wage_steps']
    assert source['steps'] == [] and source['complete_current_term_vector']
    m['q'](m['person'] - 0x98, 0)
    source = get(m)['contract_wage_steps']
    assert source['state'] == 'no_contract' and source['steps'] is None
    assert source['largest_stored_target_increase_gbp'] is None


@pytest.mark.parametrize('value', ['', None, True, 1, [], {}])
def test_invalid_reference_rejected_before_process_scope(live_record, monkeypatch, value):
    m = live_record
    monkeypatch.setattr(m['bridge'], '_read_scope', lambda *_: pytest.fail('Invalid input reached source'))
    with pytest.raises(BridgeError, match='nonempty'): get(m, value)


def test_unknown_reference_and_session_reject(live_record):
    m = live_record
    with pytest.raises(BridgeError, match='Unknown or expired'): get(m, 'missing')
    with pytest.raises(BridgeError, match='Unknown session'):
        query.get_contract_wage_steps(m['bridge'], 'another-session', 'p1')
    assert m['bridge'].player_refs['p1'] == m['binding']


@pytest.mark.parametrize('fault', ['binding_kind', 'virtual', 'primary', 'person', 'membership', 'index',
                                  'saved_index', 'identity', 'saved_layout', 'owner', 'negative', 'getter'])
def test_bad_canonical_sources_and_virtuals_fail_before_publication(live_record, monkeypatch, fault):
    m = live_record
    if fault == 'binding_kind': m['bridge'].player_refs['p1']['binding_kind'] = 'unsupported'
    if fault == 'virtual':
        m['bridge'].player_refs['p1']['binding_kind'] = virtual_identity.BINDING_KIND
        monkeypatch.setattr(m['bridge'], '_roster_player', lambda *a: pytest.fail('Virtual profile expansion'))
    if fault == 'primary': m['q'](0x1000, m['base'] + world.TYPES['virtual_player'][0])
    if fault == 'person': m['q'](m['person'], m['base'] + world.TYPES['club'][0])
    if fault == 'membership': m['vec'](m['headers']['people'], [m['club']])
    if fault == 'index': m['put'](m['person'] + 8, struct.pack('<I', 1))
    if fault == 'saved_index': m['bridge'].player_refs['p1']['database_index'] = 1
    if fault == 'identity': m['bridge'].player_refs['p1']['identity'] = ('changed',)
    if fault == 'saved_layout': m['bridge'].player_refs['p1']['tables'] = (1, 2, 3)
    if fault == 'owner': m['q'](m['staff_contract'] + 8, 0)
    if fault == 'negative': m['put'](m['entry'], struct.pack('<i', -1))
    if fault == 'getter': m['q'](m['base'] + world.TYPES['full_contract'][0] + 52 * 8, 0)
    with pytest.raises(BridgeError, match='no partial result'): get(m)
    assert 'p1' not in m['bridge'].player_refs
    assert m['scopes'][-1][0] == 'exit'


@pytest.mark.parametrize('fault', ['layout', 'plugin', 'date', 'save_count', 'career', 'membership', 'native_id',
                                  'name', 'wage', 'target', 'threshold', 'flags', 'reference'])
def test_fresh_after_context_rejects_change_without_publication(live_record, monkeypatch, fault):
    m = live_record;original = m['bridge']._player_layout;calls = 0
    def layout(process):
        nonlocal calls
        calls += 1;tables = original(process)
        if calls == 2:
            if fault == 'layout': return (tables[0] + 8, *tables[1:])
            if fault == 'plugin': m['bridge'].plugin_identity = ('changed',)
            if fault == 'date': m['put'](m['base'] + world.CURRENT_DATE, struct.pack('<I', 2030 << 16 | 263))
            if fault == 'save_count': m['put'](m['game'] + 0xC8, struct.pack('<I', 419))
            if fault == 'career': m['q'](m['save'] + 0x28, m['text']('Another career'))
            if fault == 'membership': m['vec'](m['headers']['people'], [m['club']])
            if fault == 'native_id': m['put'](m['person'] + 12, struct.pack('<I', 999))
            if fault == 'name': m['q'](m['person'] - 0xf0, 0)
            if fault == 'wage': m['put'](m['staff_contract'] + 0x20, struct.pack('<i', 12122))
            if fault == 'target': m['put'](m['entry'], struct.pack('<i', 20613))
            if fault == 'threshold': m['put'](m['entry'] + 4, struct.pack('<h', 16))
            if fault == 'flags': m['put'](m['entry'] + 7, b'\x01')
            if fault == 'reference': m['bridge'].player_refs['p1']['identity'] = ('changed',)
        return tables
    monkeypatch.setattr(m['bridge'], '_player_layout', layout)
    with pytest.raises(BridgeError, match='no partial result'): get(m)
    assert 'p1' not in m['bridge'].player_refs


@pytest.mark.parametrize('fault', ['process', 'wage', 'reference', 'plugin', 'world'])
def test_final_lifetime_callback_cannot_hide_source_or_binding_change(live_record, monkeypatch, fault):
    m = live_record;original = m['bridge']._current;calls = 0
    def current(session):
        nonlocal calls
        calls += 1;process = original(session)
        if calls == 3:
            if fault == 'process': return replace(process, started='replacement')
            if fault == 'wage': m['put'](m['staff_contract'] + 0x20, struct.pack('<i', 12122))
            if fault == 'reference': m['bridge'].player_refs['p1']['identity'] = ('changed',)
            if fault == 'plugin': m['bridge'].plugin_identity = ('changed',)
            if fault == 'world': m['bridge'].world_identity = ('changed',)
        return process
    monkeypatch.setattr(m['bridge'], '_current', current)
    with pytest.raises(BridgeError, match='no partial result'): get(m)
    assert 'p1' not in m['bridge'].player_refs


def test_read_scope_exit_error_discards_result(live_record, monkeypatch):
    m = live_record
    @contextmanager
    def scope(session):
        yield
        raise BridgeError('Read scope close detected process change')
    monkeypatch.setattr(m['bridge'], '_read_scope', scope)
    with pytest.raises(BridgeError, match='close detected'): get(m)
    assert 'p1' not in m['bridge'].player_refs


def test_registration_schema_and_actual_adapter_dispatch(live_record):
    m = live_record
    async def check():
        mcp = FastMCP('Contract wage-step controls')
        tools.register_contract_wage_step_tools(mcp, m['bridge'])
        tool, = await mcp.list_tools()
        assert tool.name == 'fm_get_contract_wage_steps'
        assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint
        assert not tool.annotations.openWorldHint
        assert set(tool.inputSchema['required']) == {'session_id', 'player_ref'}
        assert set(tool.inputSchema['properties']) == {'session_id', 'player_ref'}
        assert tool.inputSchema['properties']['player_ref']['minLength'] == 1
        assert 'not additive' in tool.description and 'activation' in tool.description
        content, result = await mcp.call_tool(tool.name,
            {'session_id': m['bridge'].session, 'player_ref': 'p1'})
        assert result['contract_wage_steps']['largest_stored_target_increase_gbp'] == 20858
        assert result['player']['native_identity']['native_id'] == 12345
        assert '8491' in content[0].text
    asyncio.run(check())
