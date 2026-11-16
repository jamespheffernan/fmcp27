"""Adapter controls using the real frozen core and synthetic typed memory.

No live process, UI or native game function is used. These tests do not replace
root's separate configured current-career acceptance.
"""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import json
import struct

import pytest
from mcp.server.fastmcp import FastMCP

from fm_live_mcp import individual_training_focus as focus, individual_training_tools as tools
from fm_live_mcp import live_individual_training as query, players, virtual_identity, world
from fm_live_mcp.bridge import BridgeError
from prepared_tactics_fixture import prepared_tactics_memory
from test_bridge import bridge
from test_database import database_memory
from test_individual_training_focus import focus_memory, native_image
from test_players import memory
from test_shortlist_members import member_memory
from test_teams import team_memory
from test_world import world_memory


@pytest.fixture
def live_focus(focus_memory, prepared_tactics_memory, bridge, monkeypatch):
    m = focus_memory
    assert m is prepared_tactics_memory
    # Keep actual Bridge context/selection methods; replace only host/process I/O.
    @contextmanager
    def scope(session_id, *, final_verify=None):
        yield
        if final_verify is not None:
            final_verify()
    monkeypatch.setattr(bridge, '_read_scope', scope)
    bridge.plugin_identity = ('synthetic verified plugin stamp', focus.PLUGIN_SHA256)
    m['layout_calls'] = []

    def layout(process):
        m['layout_calls'].append(process)
        return m['tables']

    monkeypatch.setattr(bridge, '_player_layout', layout)
    # This older field/adapter fixture intentionally has no Mach-O image.
    # Strict actual Bridge/native runtime coverage lives in test_runtime_publication_seal.
    monkeypatch.setattr(players, 'verify_runtime', lambda read, base, uuid: m['tables'])
    m['adapter_reads'] = []

    def read(process, address, size):
        m['adapter_reads'].append((address, size))
        if address < 0x118D and address + size > 0x1148:
            pytest.fail('Adapter/core read player attribute bytes')
        return m['read'](address, size)

    monkeypatch.setattr(bridge, '_read_memory', read)
    monkeypatch.setattr(bridge, '_decode_player', lambda *a, **kw: pytest.fail('Rich player decoder'))
    monkeypatch.setattr(players, 'decode', lambda *a, **kw: pytest.fail('Rich player decoder'))
    bridge.player_refs['p1'] = deepcopy(m['focus_binding'])
    m['bridge'] = bridge
    return m


def get(m, refs=None, **kwargs):
    bridge = m['bridge']
    return query.get_player_individual_training(bridge, bridge.session,
                                               ['p1'] if refs is None else refs, **kwargs)


def test_same_item_core_result_with_complete_outer_context_and_no_profile_reads(live_focus):
    m = live_focus
    before = dict(m['cells'])
    result = get(m, coach_name=' test  COACH ')
    row, = result['players']
    assert row == {
        'player_ref': 'p1', 'source_state': 'present_child', 'record_kind': 'actual',
        'native_identity': {'database_index': 0, 'native_id': 12345, 'random_id': None},
        'name': 'Test Müller', 'display_name': 'Test Müller', 'name_state': 'available',
        'additional_focus': {'raw_code': 24, 'native_code': 24, 'state': 'stored_named_focus',
                             'english_definition_name': 'Crossing', 'english_resource_key': 227798},
        'club_training_intensity': {'raw_code': 0, 'native_code': 0, 'state': 'stored_named_intensity',
                                    'english_definition_name': 'Half Intensity', 'english_resource_key': 466612,
                                    'explicit_intensity': True, 'source': 'stored_regular_player_club_training_intensity',
                                    'applied_intensity': None, 'workload': None,
                                    'scope': 'Stored club individual-training selection only. RawFF requests native default resolution; its applied value is not calculated. No medical override, workload, attendance, training control or development outcome.'},
        'scope': focus.SCOPE,
    }
    assert result['count'] == 1 and result['coach'] == 'Test Coach'
    assert result['club']['name'] == 'Test United'
    assert result['save']['current_date'] == '2030-09-19'
    assert result['team']['native_id'] == 50
    assert result['atomic'] is False and result['saved_file_fallback'] is False
    assert 'loaned-out' in result['scope'] and 'training control' in result['scope']
    assert len(m['layout_calls']) == 2
    assert m['cells'] == before
    assert not any(key in json.dumps(result) for key in ('team_address', 'manager_address', 'attributes'))


@pytest.mark.parametrize('raw, expected', [(0, 'Quickness Rehab'), (24, 'Crossing'), (32, 'GK Distribution'),
                                         (33, None), (128, None), (255, None)])
def test_adapter_preserves_named_unset_and_unknown_native_codes(live_focus, raw, expected):
    m = live_focus
    m['put'](m['focus_child'] + 6, bytes([raw]))
    row = get(m)['players'][0]
    assert row['source_state'] == 'present_child'
    assert row['additional_focus']['raw_code'] == raw
    assert row['additional_focus']['native_code'] == (raw if raw < 128 else raw - 256)
    assert row['additional_focus']['english_definition_name'] == expected
    assert row['additional_focus']['state'] == ('unset' if raw == 255 else
                                               'stored_named_focus' if raw <= 32 else 'unknown_native_code')


def test_adapter_keeps_missing_child_distinct_from_explicit_unset(live_focus):
    m = live_focus
    m['q'](0x1190, 0)
    missing = get(m)['players'][0]
    m['q'](0x1190, m['focus_child'])
    m['put'](m['focus_child'] + 6, b'\xff')
    unset = get(m)['players'][0]
    assert missing['source_state'] == 'missing_child'
    assert unset['source_state'] == 'present_child'
    assert missing['additional_focus'] == unset['additional_focus']


def test_requested_order_and_distinct_reference_aliases_are_preserved(live_focus):
    m = live_focus
    m['bridge'].player_refs['p2'] = deepcopy(m['focus_binding'])
    result = get(m, ['p2', 'p1'])
    assert [r['player_ref'] for r in result['players']] == ['p2', 'p1']
    assert result['players'][0]['native_identity'] == result['players'][1]['native_identity']


def test_maximum_100_distinct_refs_is_bounded_without_profile_expansion(live_focus):
    m = live_focus
    refs = [f'alias-{i}' for i in range(100)]
    m['bridge'].player_refs.update({ref: deepcopy(m['focus_binding']) for ref in refs})
    result = get(m, refs)
    assert result['count'] == 100
    assert [r['player_ref'] for r in result['players']] == refs
    assert all(r['additional_focus']['english_definition_name'] == 'Crossing' for r in result['players'])


@pytest.mark.parametrize('refs', [[], ['x'] * 101, ['p1', 'p1'], ('p1',), 'p1', [None], [True], [''], None])
def test_invalid_ref_requests_fail_before_context_reads(live_focus, monkeypatch, refs):
    m = live_focus
    monkeypatch.setattr(m['bridge'], '_read_scope', lambda *_: pytest.fail('Invalid input reached process scope'))
    with pytest.raises(BridgeError, match='distinct nonempty'):
        query.get_player_individual_training(m['bridge'], m['bridge'].session, refs)


@pytest.mark.parametrize('coach', ['', True, 1, 'x' * 257])
def test_invalid_coach_input_fails_before_context_reads(live_focus, monkeypatch, coach):
    m = live_focus
    monkeypatch.setattr(m['bridge'], '_read_scope', lambda *_: pytest.fail('Invalid input reached process scope'))
    with pytest.raises(BridgeError, match='coach_name'):
        get(m, coach_name=coach)


def test_unknown_coach_and_unknown_reference_reject_without_partial_rows(live_focus):
    m = live_focus
    with pytest.raises(BridgeError, match='Select one active coach'):
        get(m, coach_name='Another Coach')
    with pytest.raises(BridgeError, match='no partial result.*Unknown or expired'):
        get(m, ['p1', 'missing'])


def test_selected_roster_membership_is_required_even_for_a_valid_savewide_ref(live_focus):
    m = live_focus
    primary, person = m['add_person']('actual', 1, 77, 77, 'Outside Player')
    m['vec'](m['headers']['people'], [0x1388, person])
    m['bridge'].player_refs['outside'] = {'address': primary, 'tables': m['tables'],
        'database_index': 1, 'record_kind': 'actual', 'world_bound': True,
        'identity': (77, 'Outside Player', '', '2000-02-29', 77)}
    with pytest.raises(BridgeError, match='outside the selected native TEAM roster'):
        get(m, ['p1', 'outside'])


@pytest.mark.parametrize('kind', ['player_staff', 'virtual'])
def test_unsupported_records_keep_identity_without_training_child_or_profile_reads(live_focus, monkeypatch, kind):
    m = live_focus
    primary, person = m['add_person'](kind, 1, 77, 0, 'Combined')
    m['vec'](m['headers']['people'], [0x1388, person])
    m['vec'](m['team_addresses'][0] + 0x38, [0x1000, primary])
    binding = {'address': primary, 'tables': m['tables'], 'record_kind': kind, 'database_index': 1}
    if kind == 'player_staff':
        binding['identity'] = ('player_staff', 77, 'Combined', '', '2000-02-29', 0)
    else:
        binding.update(binding_kind=virtual_identity.BINDING_KIND,
                       identity=(virtual_identity.BINDING_KIND, 1, 77, 0))
    m['bridge'].player_refs['other'] = binding
    original = m['bridge']._read_memory

    def read(process, address, size):
        if address <= primary + 0x190 < address + size:
            pytest.fail('Unsupported record training child was inspected')
        return original(process, address, size)

    monkeypatch.setattr(m['bridge'], '_read_memory', read)
    result = get(m, ['p1', 'other'])
    assert result['count'] == 2 and result['players'][0]['source_state'] == 'present_child'
    row = result['players'][1]
    assert row['source_state'] == row['name_state'] == 'unsupported_record_kind'
    assert row['native_identity'] == {'database_index': 1, 'native_id': 77, 'random_id': 0}
    assert row['record_kind'] == kind
    assert row['name'] is row['display_name'] is row['additional_focus'] is None


@pytest.mark.parametrize('fault', ['team_human', 'contract_owner', 'contract_team', 'human_person',
                                  'human_cast', 'human_displacement', 'canonical_team'])
def test_canonical_selected_human_team_and_contract_context_is_checked(live_focus, fault):
    m = live_focus
    if fault == 'team_human': m['q'](m['team'] + 0x80, m['manager'] + 8)
    elif fault == 'contract_owner': m['q'](m['contract'] + 8, m['manager'])
    elif fault == 'contract_team': m['q'](m['contract'] + 0x18, m['team'] + 8)
    elif fault == 'human_person': m['q'](m['manager'] + 0x548, 0)
    elif fault == 'human_cast': m['q'](m['base'] + 0x55AD820 + 0x6F0, 0)
    elif fault == 'human_displacement': m['put'](m['base'] + world.TYPES['manager'][0] - 0x20, bytes(8))
    else: m['vec'](m['headers']['teams'], list(reversed(m['team_addresses'])))
    with pytest.raises(BridgeError, match='no partial result'):
        get(m)


@pytest.mark.parametrize('change', ['layout', 'plugin_stamp', 'date', 'save_count', 'loaded_career', 'team_human'])
def test_fresh_after_context_rejects_build_save_date_and_coaching_changes(live_focus, monkeypatch, change):
    m = live_focus
    original = m['bridge']._player_layout
    calls = 0

    def layout(process):
        nonlocal calls
        calls += 1
        tables = original(process)
        if calls == 2:
            if change == 'layout': return (tables[0] + 8, *tables[1:])
            if change == 'plugin_stamp': m['bridge'].plugin_identity = ('changed', focus.PLUGIN_SHA256)
            elif change == 'date': m['put'](m['base'] + world.CURRENT_DATE, struct.pack('<I', 2030 << 16 | 263))
            elif change == 'save_count': m['put'](m['game'] + 0xC8, struct.pack('<I', 419))
            elif change == 'loaded_career': m['q'](m['save'] + 0x28, m['text']('Another career'))
            elif change == 'team_human': m['q'](m['team'] + 0x80, m['manager'] + 8)
        return tables

    monkeypatch.setattr(m['bridge'], '_player_layout', layout)
    with pytest.raises(BridgeError, match='no partial result'):
        get(m)


def test_late_core_byte_drift_is_caught_by_outer_readset(live_focus, monkeypatch):
    m = live_focus
    original = focus.inspect

    def inspect(*args, **kwargs):
        row = original(*args, **kwargs)
        m['put'](m['focus_child'] + 9, b'\x01')
        return row

    monkeypatch.setattr(focus, 'inspect', inspect)
    with pytest.raises(BridgeError, match='changed during read'):
        get(m)


def test_reference_binding_change_after_core_read_is_rejected(live_focus, monkeypatch):
    m = live_focus
    original = focus.inspect

    def inspect(*args, **kwargs):
        row = original(*args, **kwargs)
        m['bridge'].player_refs['p1']['identity'] = (77, 'Another', '', '2000-02-29', 77)
        return row

    monkeypatch.setattr(focus, 'inspect', inspect)
    with pytest.raises(BridgeError, match='reference binding changed'):
        get(m)


@pytest.mark.parametrize('change', ['process', 'last_byte', 'roster'])
def test_final_process_check_and_subsequent_byte_rechecks_reject_late_drift(live_focus, monkeypatch, change):
    m = live_focus
    original = m['bridge']._current
    calls = 0

    def current(session):
        nonlocal calls
        calls += 1
        process = original(session)
        if calls == 3:
            if change == 'process': return replace(process, started='another process epoch')
            if change == 'last_byte': m['put'](m['focus_child'] + 9, b'\x01')
            else: m['vec'](m['team'] + 0x38, [])
        return process

    monkeypatch.setattr(m['bridge'], '_current', current)
    with pytest.raises(BridgeError, match='lifetime changed|changed during read'):
        get(m)


def test_stale_regular_player_identity_rejects_whole_batch(live_focus):
    m = live_focus
    m['bridge'].player_refs['bad'] = {**m['focus_binding'],
                                     'identity': (77, 'Other', '', '2000-02-29', 77)}
    with pytest.raises(BridgeError, match='reference identity changed'):
        get(m, ['p1', 'bad'])


def test_standalone_tool_schema_and_call_use_the_same_checked_adapter(live_focus):
    m = live_focus

    async def check():
        mcp = FastMCP('Individual training test')
        tools.register_individual_training_tools(mcp, m['bridge'])
        tool, = await mcp.list_tools()
        assert tool.name == 'fm_get_player_individual_training'
        assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint
        assert not tool.annotations.openWorldHint
        schema = tool.inputSchema
        assert set(schema['required']) == {'session_id', 'player_refs'}
        assert set(schema['properties']) == {'session_id', 'player_refs', 'coach_name', 'include_default_resolution', 'include_role_position'}
        assert schema['properties']['include_default_resolution']['default'] is False
        assert schema['properties']['include_role_position']['default'] is False
        refs = schema['properties']['player_refs']
        assert (refs['minItems'], refs['maxItems'], refs['uniqueItems']) == (1, 100, True)
        assert refs['items']['minLength'] == 1
        content, structured = await mcp.call_tool(tool.name,
            {'session_id': m['bridge'].session, 'player_refs': ['p1']})
        assert structured['players'][0]['additional_focus']['english_definition_name'] == 'Crossing'
        assert structured['players'][0]['native_identity']['native_id'] == 12345
        assert 'Crossing' in content[0].text

    asyncio.run(check())
