"""Adapter controls using the frozen real duty core and typed synthetic memory.

No live game, native execution or profile generation; root owns live acceptance.
"""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import json
import struct

import pytest
from mcp.server.fastmcp import FastMCP

from fm_live_mcp import assessment_people, international_duty_source as duty
from fm_live_mcp import international_duty_tools as tools, live_international_duty as query
from fm_live_mcp import players, virtual_identity, world
from fm_live_mcp.bridge import BridgeError
from prepared_tactics_fixture import prepared_tactics_memory
from test_bridge import bridge
from test_database import database_memory
from test_international_duty_source import packed
from test_players import memory
from test_shortlist_members import member_memory
from test_teams import team_memory
from test_world import world_memory


@pytest.fixture
def live_duty(prepared_tactics_memory, member_memory, bridge, monkeypatch):
    m = prepared_tactics_memory
    assert m is member_memory
    base = m['base']
    for module in (duty, assessment_people):
        for rva, raw in module.NATIVE_SPANS:
            m['put'](base + rva, raw)
    for slot, target in ((0x55DF1E8, 0x1F8DB6C), (0x55BA230, 0x153AD48)):
        m['q'](base + slot, base + target)
    national = m['typed']('national_team', 0x1000)
    m['put'](national + 8, struct.pack('<III', 1, 333, 0))
    m['put'](national + 0x2F, b'\1')
    m['q'](national + 0x30, m['owners'][1])
    m['vec'](m['owners'][1] + 0x18, [national])
    m['vec'](m['headers']['teams'], [m['team'], national, m['team_addresses'][2]])
    m['put'](national + 0xE2, b'\1')
    m['put'](national + 0xB8, packed('2030-09-25'))
    m['put'](national + 0xDC, packed('2030-09-17'))
    international = m['allocate'](0xC0)
    m['typed_at'](international, duty.INTDATA[0], duty.INTDATA[1])
    m['put'](international + 0xA4, packed('1900-01-01'))
    m['put'](international + 0xA8, packed('1900-01-01'))
    m['put'](international + 0xBB, bytes([0, 0]))
    provider = m['allocate'](16)
    m['typed_at'](provider, duty.PROVIDER[0], duty.PROVIDER[1])
    m['q'](base + 0x56D2B30, provider)
    m['q'](base + duty.PROVIDER[0] + 0x38, base + 0x204F5C0)
    people, roster = [0x1388], [0x1000]

    def player_fields(primary, person, kind):
        offset = person - primary
        rva = players.STAFF_RVA[2] if kind == 'player_staff' else players.RVA[2]
        m['put'](base + (players.STAFF_RVA[0] if kind == 'player_staff' else players.RVA[0]) - 0x18,
                 struct.pack('<q', offset))
        for slot, adjustment, fn in ((0x668, 0x678, 0xD5C5FC), (0x220, 0x230, 0xD5C560),
                                     (0x230, 0x240, 0xD5C578)):
            m['q'](base + rva + slot, base + fn)
            m['put'](base + rva - adjustment, struct.pack('<q', -offset))
        m['q'](primary + 0x128, m['team'])
        m['q'](primary + 0x120, national)
        m['q'](primary + 0x118, international)

    m['seed_type']('actual')
    player_fields(0x1000, 0x1388, 'actual')
    bridge.player_refs['p1'] = {'address': 0x1000, 'tables': m['tables'],
        'database_index': 0, 'record_kind': 'actual', 'world_bound': True,
        'identity': (12345, 'Test', 'Müller', '2000-02-29', 12345)}

    def add(kind='actual', name='Another Player', secondary=0):
        index = len(people)
        primary, person = m['add_person'](kind, index, 700 + index, secondary, name)
        people.append(person)
        roster.append(primary)
        m['vec'](m['headers']['people'], people)
        m['vec'](m['team'] + 0x38, roster)
        binding = dict(address=primary, tables=m['tables'], database_index=index, record_kind=kind)
        if kind == 'virtual':
            binding.update(binding_kind=virtual_identity.BINDING_KIND,
                           identity=(virtual_identity.BINDING_KIND, index, 700 + index, secondary))
        else:
            player_fields(primary, person, kind)
            identity = (700 + index, name, '', '2000-02-29', secondary)
            binding['identity'] = ('player_staff', *identity) if kind == 'player_staff' else identity
        ref = f'p{index + 1}'
        bridge.player_refs[ref] = binding
        return ref, primary, person

    scope_entries = []
    @contextmanager
    def scope(session):
        assert not scope_entries or scope_entries[-1] == 'exited', 'Nested native read scope'
        scope_entries.append('entered')
        try:
            yield
        finally:
            scope_entries.append('exited')

    monkeypatch.setattr(bridge, '_read_scope', scope)
    bridge.plugin_identity = ('synthetic verified plugin', duty.PLUGIN_SHA256)
    layout_calls = []
    def layout(process):
        layout_calls.append(process)
        return m['tables']
    monkeypatch.setattr(bridge, '_player_layout', layout)
    reads = []
    def read(process, address, size):
        reads.append((address, size))
        for primary in roster:
            if address < primary + 0x18D and address + size > primary + 0x148:
                pytest.fail('Adapter read player attributes')
        return m['read'](address, size)
    monkeypatch.setattr(bridge, '_read_memory', read)
    monkeypatch.setattr(bridge, '_decode_player', lambda *a, **k: pytest.fail('Rich decoder'))
    monkeypatch.setattr(players, 'decode', lambda *a, **k: pytest.fail('Rich decoder'))
    m.update(bridge=bridge, national=national, international=international, add=add,
             roster=roster, scope_entries=scope_entries, adapter_reads=reads, layout_calls=layout_calls)
    return m


def get(m, refs=None, **kwargs):
    return query.get_player_international_duty(m['bridge'], m['bridge'].session,
                                              ['p1'] if refs is None else refs, **kwargs)


def test_real_core_same_item_and_scoped_b8_estimate_without_profile_or_writes(live_duty):
    m = live_duty
    before = dict(m['cells'])
    result = get(m, coach_name=' test COACH ')
    row, = result['players']
    assert row['native_identity'] == {'database_index': 0, 'native_id': 12345, 'random_id': None}
    assert (row['name'], row['display_name'], row['record_kind']) == ('Test Müller', 'Test Müller', 'actual')
    assert row['name_state'] == 'stored_native_name_fields'
    assert row['state'] == 'available' and row['national_assignment_gate'] is True
    assert row['reason'] == 'native_duty_window'
    assert row['native_gate_reason'] == {'code': 4, 'key': 242665, 'text': 'On international duty',
                                        'scope': 'input_to_final_availability'}
    assert row['national_team_identity'] == {'database_index': 1, 'native_id': 333, 'random_id': 0}
    assert (row['return_date'], row['return_date_state']) == ('2030-09-25', 'native_estimated_return')
    assert row['native_estimated_return_source'] == 'NATIONAL_TEAM_plus_0xb8'
    assert row['eligibility_state'] == 'not_evaluated' and row['current_date'] == '2030-09-19'
    assert result['count'] == 1 and result['coach'] == 'Test Coach'
    assert result['club']['name'] == 'Test United' and result['team']['native_id'] == 50
    assert result['atomic'] is result['saved_file_fallback'] is False
    assert 'loaned-out' in result['scope'] and 'guaranteed' in result['scope']
    assert len(m['layout_calls']) == 2 and m['scope_entries'] == ['entered', 'exited']
    assert not any(k in json.dumps(result) for k in ('team_address', 'manager_address', 'attributes'))
    assert m['cells'] == before


@pytest.mark.parametrize('phase,mode,code', [(0, 0, 16), (1, 1, 15)])
def test_adapter_keeps_native_travel_reasons_and_b8_not_a8(live_duty, phase, mode, code):
    m = live_duty
    m['put'](m['international'] + 0xA4, packed('2030-09-18'))
    m['put'](m['international'] + 0xA8, packed('2030-09-21'))
    m['put'](m['international'] + 0xBB, bytes([phase, mode]))
    # phase1/mode1 with sentinel start avoids the core's fixture-override path.
    if mode: m['put'](m['international'] + 0xA4, packed('1900-01-01'))
    row = get(m)['players'][0]
    assert row['national_assignment_gate'] is True and row['native_gate_reason']['code'] == code
    assert row['return_date'] == '2030-09-25'


@pytest.mark.parametrize('branch', ['no_assignment', 'inactive', 'expired', 'unavailable'])
def test_false_and_unavailable_are_distinct_and_never_supply_return_date(live_duty, branch):
    m = live_duty
    if branch == 'no_assignment': m['q'](0x1120, 0)
    elif branch == 'inactive': m['put'](m['national'] + 0xE2, b'\0')
    elif branch == 'expired': m['put'](m['national'] + 0xB8, packed('2030-09-19'))
    else: m['put'](m['international'] + 0xBB, b'\xff')
    row = get(m)['players'][0]
    unknown = branch == 'unavailable'
    assert row['state'] == ('unavailable' if unknown else 'available')
    assert row['national_assignment_gate'] is (None if unknown else False)
    assert row['return_date'] is row['native_gate_reason'] is None
    assert row['return_date_state'] == ('not_proved' if unknown else 'not_applicable')


def test_combined_is_supported_with_full_stock_tuple_and_raw_secondary_zero(live_duty):
    m = live_duty
    ref, primary, person = m['add']('player_staff', 'Combined Player')
    rows = get(m, [ref, 'p1'])['players']
    assert [r['player_ref'] for r in rows] == [ref, 'p1']
    assert rows[0]['record_kind'] == 'player_staff' and rows[0]['name'] == 'Combined Player'
    assert rows[0]['national_assignment_gate'] is True
    assert rows[0]['native_identity'] == {'database_index': 1, 'native_id': 701, 'random_id': 0}
    assert rows[0]['return_date_state'] == 'native_estimated_return'


def test_compact_retains_identity_without_generation_or_gate_reads(live_duty, monkeypatch):
    m = live_duty
    ref, primary, person = m['add']('virtual')
    original = m['bridge']._read_memory
    def read(process, address, size):
        if address < primary + 0x130 and address + size > primary + 0x118:
            pytest.fail('Compact PLAYER child/gate read')
        return original(process, address, size)
    monkeypatch.setattr(m['bridge'], '_read_memory', read)
    row = get(m, [ref])['players'][0]
    assert row['state'] == 'unsupported_type' and row['record_kind'] == 'virtual'
    assert row['native_identity'] == {'database_index': 1, 'native_id': 701, 'random_id': 0}
    assert row['name'] is row['display_name'] is row['national_assignment_gate'] is row['return_date'] is None
    assert row['name_state'] == 'unavailable_without_generated_profile'


@pytest.mark.parametrize('current', ['other_team', 'null'])
def test_native_roster_loans_outside_current_team_keep_null_gate_and_identity(live_duty, current):
    m = live_duty
    ref, primary, _ = m['add']('actual', 'Roster Loan')
    # Use another canonical kind0 TEAM owned by the club; no inferred loan status.
    m['q'](primary + 0x128, m['team_addresses'][2] if current == 'other_team' else 0)
    row = get(m, [ref])['players'][0]
    assert row['state'] == 'outside_scope' and row['name'] == 'Roster Loan'
    assert row['national_assignment_gate'] is row['return_date'] is row['native_gate_reason'] is None
    assert row['return_date_state'] == 'not_proved'
    assert row['current_club_team'] is None if current == 'null' else row['current_club_team']['database_index'] == 2


@pytest.mark.parametrize('refs', [[], ['x'] * 101, ['p1', 'p1'], ('p1',), 'p1', [None], [True], [''], None])
def test_invalid_ref_inputs_fail_before_scope(live_duty, monkeypatch, refs):
    m = live_duty
    monkeypatch.setattr(m['bridge'], '_read_scope', lambda *_: pytest.fail('Invalid input reached scope'))
    with pytest.raises(BridgeError, match='distinct nonempty'):
        query.get_player_international_duty(m['bridge'], m['bridge'].session, refs)


@pytest.mark.parametrize('coach', ['', True, 1, 'x' * 257])
def test_invalid_coach_inputs_fail_before_scope(live_duty, monkeypatch, coach):
    monkeypatch.setattr(live_duty['bridge'], '_read_scope', lambda *_: pytest.fail('Invalid input reached scope'))
    with pytest.raises(BridgeError, match='coach_name'):
        get(live_duty, coach_name=coach)


def test_unknown_ref_and_coach_reject_whole_batch(live_duty):
    with pytest.raises(BridgeError, match='no partial result.*Unknown or expired'):
        get(live_duty, ['p1', 'missing'])
    with pytest.raises(BridgeError, match='Select one active coach'):
        get(live_duty, coach_name='Not the selected coach')


def test_valid_savewide_reference_outside_native_roster_is_rejected(live_duty):
    m = live_duty
    ref, primary, _ = m['add']()
    m['vec'](m['team'] + 0x38, [0x1000])
    with pytest.raises(BridgeError, match='outside the selected native TEAM roster'):
        get(m, ['p1', ref])


@pytest.mark.parametrize('kind', ['actual', 'player_staff', 'virtual'])
def test_wrong_stock_reference_identity_rejects_without_partial_rows(live_duty, kind):
    m = live_duty
    ref, primary, _ = m['add'](kind)
    saved = list(m['bridge'].player_refs[ref]['identity'])
    saved[-1] = 77
    m['bridge'].player_refs[ref]['identity'] = tuple(saved)
    with pytest.raises(BridgeError, match='identity'):
        get(m, ['p1', ref])


@pytest.mark.parametrize('fault', ['name', 'birthday', 'index', 'person_slot', 'cast', 'national_owner', 'b8_date'])
def test_typed_corrupt_identity_gate_and_return_sources_reject_batch(live_duty, fault):
    m = live_duty
    if fault == 'name': m['q'](0x1298, 0)
    elif fault == 'birthday': m['put'](0x12D0, packed('2001-01-01'))
    elif fault == 'index': m['bridge'].player_refs['p1']['database_index'] = 1
    elif fault == 'person_slot': m['vec'](m['headers']['people'], [m['manager']])
    elif fault == 'cast': m['q'](m['tables'][2] + 0x668, 0)
    elif fault == 'national_owner': m['vec'](m['owners'][1] + 0x18, [])
    else: m['put'](m['national'] + 0xB8, struct.pack('<HH', 366, 2030))
    with pytest.raises(BridgeError, match='no partial result'):
        get(m)


@pytest.mark.parametrize('fault', ['team_human', 'contract_owner', 'contract_team', 'human_cast', 'human_displacement'])
def test_selected_human_team_contract_context_is_real_checked_source(live_duty, fault):
    m = live_duty
    if fault == 'team_human': m['q'](m['team'] + 0x80, m['manager'] + 8)
    elif fault == 'contract_owner': m['q'](m['contract'] + 8, m['manager'])
    elif fault == 'contract_team': m['q'](m['contract'] + 0x18, m['team'] + 8)
    elif fault == 'human_cast': m['q'](m['base'] + 0x55AD820 + 0x6F0, 0)
    else: m['put'](m['base'] + world.TYPES['manager'][0] - 0x20, bytes(8))
    with pytest.raises(BridgeError, match='no partial result'):
        get(m)


@pytest.mark.parametrize('change', ['layout', 'plugin', 'date', 'save_count', 'loaded_save', 'team_human', 'roster', 'binding'])
def test_fresh_after_context_rejects_changed_build_save_date_roster_and_refs(live_duty, monkeypatch, change):
    m = live_duty
    original = m['bridge']._player_layout
    calls = 0
    def layout(process):
        nonlocal calls
        calls += 1
        result = original(process)
        if calls == 2:
            if change == 'layout': return (result[0] + 8, *result[1:])
            if change == 'plugin': m['bridge'].plugin_identity = ('changed', duty.PLUGIN_SHA256)
            elif change == 'date': m['put'](m['base'] + world.CURRENT_DATE, packed('2030-09-20'))
            elif change == 'save_count': m['put'](m['game'] + 0xC8, struct.pack('<I', 419))
            elif change == 'loaded_save': m['q'](m['save'] + 0x28, m['text']('Another career'))
            elif change == 'team_human': m['q'](m['team'] + 0x80, m['manager'] + 8)
            elif change == 'roster': m['vec'](m['team'] + 0x38, [])
            else: m['bridge'].player_refs['p1']['identity'] = (77, 'Other', '', '2000-02-29', 77)
        return result
    monkeypatch.setattr(m['bridge'], '_player_layout', layout)
    with pytest.raises(BridgeError, match='no partial result'):
        get(m)
    assert calls == 2, 'Must reach the fresh after-context check'


@pytest.mark.parametrize('change', ['process', 'byte', 'roster', 'binding', 'plugin', 'world'])
def test_final_callback_cannot_escape_source_and_context_rechecks(live_duty, monkeypatch, change):
    m = live_duty
    original = m['bridge']._current
    calls = 0
    def current(session):
        nonlocal calls
        calls += 1
        value = original(session)
        if calls == 3:
            if change == 'process': return replace(value, started='another epoch')
            if change == 'byte': m['put'](m['national'] + 0xB8, packed('2030-09-26'))
            elif change == 'roster': m['vec'](m['team'] + 0x38, [])
            elif change == 'binding': m['bridge'].player_refs['p1']['identity'] = ('stale',)
            elif change == 'plugin': m['bridge'].plugin_identity = ('changed', duty.PLUGIN_SHA256)
            else: m['bridge'].world_identity = ('changed',)
        return value
    monkeypatch.setattr(m['bridge'], '_current', current)
    with pytest.raises(BridgeError, match='no partial result'):
        get(m)
    assert calls == 3, 'Must reach the final lifetime callback'


def test_late_nested_core_byte_change_is_caught_by_outer_readset(live_duty, monkeypatch):
    m = live_duty
    original = duty.read_current
    def current(*args, **kwargs):
        result = original(*args, **kwargs)
        m['put'](m['international'] + 0xBB, b'\3')
        return result
    monkeypatch.setattr(duty, 'read_current', current)
    with pytest.raises(BridgeError, match='changed during read'):
        get(m)


def test_100_distinct_aliases_preserve_requested_order_and_bounded_fields(live_duty):
    m = live_duty
    refs = [f'alias-{i}' for i in range(100)]
    m['bridge'].player_refs.update({ref: deepcopy(m['bridge'].player_refs['p1']) for ref in refs})
    result = get(m, refs)
    assert result['count'] == 100 and [r['player_ref'] for r in result['players']] == refs
    assert all(r['national_assignment_gate'] is True for r in result['players'])


def test_standalone_schema_and_mcp_call_use_same_adapter(live_duty):
    m = live_duty
    async def check():
        mcp = FastMCP('International-duty test')
        tools.register_international_duty_tools(mcp, m['bridge'])
        tool, = await mcp.list_tools()
        assert tool.name == 'fm_get_player_international_duty'
        assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint
        assert not tool.annotations.openWorldHint
        schema = tool.inputSchema
        assert set(schema['required']) == {'session_id', 'player_refs'}
        assert set(schema['properties']) == {'session_id', 'player_refs', 'coach_name'}
        refs = schema['properties']['player_refs']
        assert (refs['minItems'], refs['maxItems'], refs['uniqueItems']) == (1, 100, True)
        assert refs['items']['minLength'] == 1
        content, result = await mcp.call_tool(tool.name,
            {'session_id': m['bridge'].session, 'player_refs': ['p1']})
        assert result['players'][0]['national_assignment_gate'] is True
        assert result['players'][0]['return_date'] == '2030-09-25'
        assert 'native_estimated_return' in content[0].text
    asyncio.run(check())


@pytest.mark.parametrize('fault', ['tables', 'record_kind', 'binding_kind', 'world_bound', 'index_bool', 'identity_bool'])
def test_invalid_reference_shape_cannot_supply_a_gate(live_duty, fault):
    m = live_duty
    binding = m['bridge'].player_refs['p1']
    if fault == 'tables': binding['tables'] = list(binding['tables'])
    elif fault == 'record_kind': binding['record_kind'] = 'player_staff'
    elif fault == 'binding_kind': binding['binding_kind'] = 'generated_profile'
    elif fault == 'world_bound': binding['world_bound'] = 1
    elif fault == 'index_bool': binding['database_index'] = False
    else: binding['identity'] = (True, *binding['identity'][1:])
    with pytest.raises(BridgeError, match='no partial result'):
        get(m)


def test_mixed_batch_retains_false_unavailable_outside_and_compact_rows(live_duty):
    m = live_duty
    outside, primary, _ = m['add']('actual', 'Outside Current Team')
    m['q'](primary + 0x128, 0)
    compact, _, _ = m['add']('virtual')
    combined, _, _ = m['add']('player_staff', 'Combined Player')
    # Both materialized in-scope rows share the unknown provider phase.
    m['put'](m['international'] + 0xBB, b'\xff')
    # The first materialized row is checked native absence rather than unknown.
    m['q'](0x1120, 0)
    refs = [outside, 'p1', compact, combined]
    result = get(m, refs)
    assert [row['player_ref'] for row in result['players']] == refs
    assert [row['state'] for row in result['players']] == [
        'outside_scope', 'available', 'unsupported_type', 'unavailable']
    assert [row['national_assignment_gate'] for row in result['players']] == [None, False, None, None]
    assert all(row['return_date'] is None for row in result['players'])
    assert result['count'] == 4
