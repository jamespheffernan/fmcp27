"""Owning Bridge composition checks; typed native acceptance lives separately."""
from contextlib import contextmanager
from copy import deepcopy
import json
import struct

import pytest

from fm_live_mcp import bridge as module, players, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import bind
from prepared_tactics_fixture import (database_memory, memory, prepared_tactics_memory,
                                     team_memory, world_memory)


def test_status_advertises_prepared_scope_and_limits(bridge):
    result = bridge.status()
    assert result['capabilities']['managed_prepared_tactics'] is True
    limits = ' '.join(result['limitations'])
    assert 'stored primary trained tactic' in limits
    assert result['capabilities']['prepared_formation_ids'] is True
    assert result['capabilities']['prepared_team_instructions'] is True
    assert 'official formation names, roles, familiarity and player assignments' in limits


@pytest.fixture
def tactics_context(bridge, monkeypatch):
    memory = {0x100: b's', 0x200: b'p'}
    snapshot = world.ReadSet(lambda address, length: memory[address][:length])
    coach = {'name': 'Cesar  Jules', 'club': {'name': 'Newcastle United'},
             'team_address': 0x8000, 'manager_address': 0x9000}
    save = {'name': 'Career', 'current_date': '2030-10-28', 'coaches': [coach]}
    source = {'team': {'database_index': 545, 'native_id': 688}, 'source_state': 'available',
              'unavailable_reason': None, 'complete_stored_slots': True, 'slot_count': 3,
              'nonnull_slot_count': 2, 'null_slot_count': 1,
              'primary_trained_tactic': {'state': 'selected', 'native_index': 0,
                  'slot_index': 0, 'meaning': 'primary_trained_tactic'}}
    phase = {'positions': [{'position_index': index, 'native_mask': 99, 'name': None,
                           'state': 'unmapped_native_mask'} for index in range(11)], 'formation': None}
    fields = {'name': 'Stored Unicode \u00e9 ', 'name_state': 'stored',
              'phases': {'in_possession': phase, 'out_of_possession': deepcopy(phase)}}
    calls = {'scopes': 0, 'closed': 0, 'inspect': [], 'decode': []}
    @contextmanager
    def scope(session):
        assert bridge.lock._is_owned()
        assert calls['scopes'] == calls['closed']
        calls['scopes'] += 1
        try:
            yield
        finally:
            calls['closed'] += 1
    def inspect(read, base, selected):
        assert bridge.lock._is_owned()
        assert read is snapshot and base == 0x100000 and selected is coach
        read(0x100, 1)
        calls['inspect'].append(selected)
        return deepcopy(source), (0x10000, 0, 0x10000)
    def decode(read, base, address):
        assert read is snapshot and base == 0x100000 and address == 0x10000
        assert bridge.lock._is_owned()
        read(0x200, 1)
        calls['decode'].append(address)
        return deepcopy(fields)
    monkeypatch.setattr(bridge, '_read_scope', scope)
    monkeypatch.setattr(bridge, '_player_layout', lambda process: tuple(0x100000 + value for value in players.RVA))
    monkeypatch.setattr(bridge, '_world_state', lambda process, tables: (snapshot, save, ('save',)))
    monkeypatch.setattr(module.prepared_tactics_source, 'inspect', inspect)
    monkeypatch.setattr(module.prepared_tactics_fields, 'decode', decode)
    return {'source': source, 'fields': fields, 'memory': memory, 'snapshot': snapshot,
            'save': save, 'coach': coach, 'calls': calls, 'inspect': inspect, 'decode': decode}


def test_complete_ordered_slots_and_private_context_not_published(bridge, tactics_context):
    context = tactics_context
    bridge.player_refs['old'] = {'address': 0xdead}
    before = deepcopy(bridge.player_refs)
    result = bridge.get_managed_tactics(bridge.session)
    assert result['save'] == {'name': 'Career', 'current_date': '2030-10-28',
        'coaches': [{'name': 'Cesar  Jules', 'club': {'name': 'Newcastle United'}}]}
    assert result['coach'] == 'Cesar  Jules'
    assert result['club'] == {'name': 'Newcastle United'}
    for key, value in context['source'].items():
        assert result[key] == value
    assert result['slots'] == [
        {'slot_index': 0, 'state': 'stored', **context['fields']},
        {'slot_index': 1, 'state': 'null_slot', 'name': None, 'name_state': 'unavailable', 'phases': None},
        {'slot_index': 2, 'state': 'stored', **context['fields']},
    ]
    assert result['unavailable_fields'] == ['current_match_assignment', 'official_formation', 'roles',
        'instructions', 'familiarity', 'player_assignments']
    assert context['calls']['decode'] == [0x10000, 0x10000]
    assert context['calls']['scopes'] == context['calls']['closed'] == 1
    assert bridge.player_refs == before and bridge.team_refs == {}
    public = json.dumps(result)
    assert 'team_address' not in public and 'manager_address' not in public and 'player_ref' not in public
    assert '32768' not in public and '36864' not in public and '65536' not in public


@pytest.mark.parametrize('reason', ['tactics_manager_missing', 'owner_container_missing', 'team_entry_missing'])
def test_proven_source_unavailability_remains_explicit(bridge, monkeypatch, tactics_context, reason):
    context = tactics_context
    source = context['source']
    source.update(source_state='unavailable', unavailable_reason=reason, complete_stored_slots=False,
                  slot_count=None, nonnull_slot_count=None, null_slot_count=None,
                  primary_trained_tactic={'state': 'source_unavailable', 'native_index': None,
                                         'slot_index': None, 'meaning': 'primary_trained_tactic'})
    def inspect(read, base, coach):
        read(0x100, 1)
        return deepcopy(source), ()
    monkeypatch.setattr(module.prepared_tactics_source, 'inspect', inspect)
    result = bridge.get_managed_tactics(bridge.session)
    assert result['source_state'] == 'unavailable' and result['unavailable_reason'] == reason
    assert result['slot_count'] is None and result['complete_stored_slots'] is False
    assert result['slots'] == [] and result['primary_trained_tactic']['state'] == 'source_unavailable'
    assert context['calls']['decode'] == []


@pytest.mark.parametrize('phase', ['source', 'field', 'source_mutation', 'field_mutation', 'process'])
def test_failures_reject_complete_response_and_close_scope(bridge, monkeypatch, tactics_context, phase):
    context = tactics_context
    bridge.player_refs['kept'] = {'identity': 'kept'}
    if phase == 'source':
        def inspect(*args):
            raise ValueError('malformed native source')
        monkeypatch.setattr(module.prepared_tactics_source, 'inspect', inspect)
    elif phase in ('field', 'source_mutation', 'field_mutation'):
        def decode(*args):
            value = context['decode'](*args)
            if phase == 'field':
                raise ValueError('invalid UTF-8 native tactic name')
            if len(context['calls']['decode']) == 2:
                context['memory'][0x100 if phase == 'source_mutation' else 0x200] = b'X'
            return value
        monkeypatch.setattr(module.prepared_tactics_fields, 'decode', decode)
    else:
        original = bridge._current
        calls = []
        def current(session):
            calls.append(session)
            if len(calls) == 2:
                raise BridgeError('process changed')
            return original(session)
        monkeypatch.setattr(bridge, '_current', current)
    with pytest.raises(BridgeError, match='no partial result'):
        bridge.get_managed_tactics(bridge.session)
    assert context['calls']['scopes'] == context['calls']['closed'] == 1
    assert bridge.player_refs == {'kept': {'identity': 'kept'}}
    assert bridge.team_refs == {}


def test_active_coach_name_uses_existing_normalization(bridge, tactics_context):
    assert bridge.get_managed_tactics(bridge.session, '  CESAR Jules  ')['coach'] == 'Cesar  Jules'


@pytest.mark.parametrize('name', ['', 'Other Coach', [], 1, 'X' * 257])
def test_invalid_coach_never_reaches_tactic_source(bridge, tactics_context, name):
    with pytest.raises(BridgeError):
        bridge.get_managed_tactics(bridge.session, name)
    assert tactics_context['calls']['inspect'] == []


def test_multiple_active_coaches_require_selection(bridge, tactics_context):
    context = tactics_context
    context['save']['coaches'].append({**context['coach'], 'name': 'Other Coach'})
    with pytest.raises(BridgeError, match='Select one active coach'):
        bridge.get_managed_tactics(bridge.session)
    assert context['calls']['inspect'] == []


def test_real_typed_source_and_fields_keep_null_slot_and_unmapped_mask(bridge, monkeypatch, prepared_tactics_memory):
    m = prepared_tactics_memory
    bind(bridge, monkeypatch, m)
    creators = m['creator_addresses']
    m['vec'](m['tactics_payload'] + 0x1000, [creators[0], 0, creators[2]])
    m['put'](m['tactics_payload'] + 0x1018, b'\x01')
    m['put'](creators[2] + 0x440, struct.pack('<I', 0xFFFFFFFF))
    result = bridge.get_managed_tactics(bridge.session)
    assert (result['slot_count'], result['nonnull_slot_count'], result['null_slot_count']) == (3, 2, 1)
    assert result['primary_trained_tactic'] == {'state': 'selected_slot_null', 'native_index': 1,
        'slot_index': None, 'meaning': 'primary_trained_tactic'}
    assert [slot['state'] for slot in result['slots']] == ['stored', 'null_slot', 'stored']
    first = result['slots'][0]
    assert first['name'] == 'Same tactic' and first['name_state'] == 'stored'
    assert first['phases']['in_possession']['positions'][0] == {
        'position_index': 0, 'native_mask': 1, 'name': 'GK', 'state': 'named'}
    assert len(first['phases']['in_possession']['positions']) == 11
    assert len(first['phases']['out_of_possession']['positions']) == 11
    assert first['phases']['in_possession']['formation'] is None
    assert result['slots'][2]['phases']['out_of_possession']['positions'][0] == {
        'position_index': 0, 'native_mask': 0xFFFFFFFF, 'name': None, 'state': 'unmapped_native_mask'}
    assert bridge.player_refs == {} and bridge.team_refs == {}
    assert 'address' not in json.dumps(result) and 'player_ref' not in json.dumps(result)
