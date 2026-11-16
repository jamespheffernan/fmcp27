"""Independent composed Bridge acceptance using typed, canonical memory."""
from copy import deepcopy
from dataclasses import replace
import asyncio
import struct

import pytest

from fm_live_mcp import prepared_tactics_fields as fields, prepared_tactics_source as source, world
from fm_live_mcp.bridge import BridgeError
from prepared_tactics_fixture import prepared_tactics_memory
from test_bridge import bridge, PROCESS
from test_database import bind, database_memory
from test_players import memory
from test_teams import team_memory
from test_world import world_memory


NAMES = ['GK', 'D(R)', 'D(CR)', 'D(CL)', 'D(L)', 'DM(CR)', 'DM(CL)',
         'AM(R)', 'AM(C)', 'AM(L)', 'ST(C)']
UNAVAILABLE = ['current_match_assignment', 'official_formation', 'roles',
               'instructions', 'familiarity', 'player_assignments']


@pytest.fixture
def composed(bridge, monkeypatch, prepared_tactics_memory):
    bind(bridge, monkeypatch, prepared_tactics_memory)
    for name in ('player_refs', 'team_refs', 'club_refs', 'staff_refs', 'competition_refs'):
        getattr(bridge, name)['unrelated-existing'] = {'identity':'preexisting'}
    return prepared_tactics_memory


def read(bridge):
    return bridge.get_managed_tactics(bridge.session)


def set_name(m, creator, raw, *, length=None, terminator=b'\0', unaligned=False):
    address = m['allocate'](len(raw)+16) + int(unaligned)
    m['put'](address, struct.pack('<I', len(raw) if length is None else length)+raw+terminator)
    m['q'](creator+0x790, address)
    return address


def caches(bridge):
    return {name:deepcopy(getattr(bridge, name)) for name in
            ('player_refs', 'team_refs', 'club_refs', 'staff_refs', 'competition_refs')}


def assert_no_private_bindings(value):
    if isinstance(value, dict):
        assert not ({'address', '_bindings', 'binding', 'creator_address', 'manager_address',
                     'owner_container_address', 'team_address', 'native_address'} & value.keys())
        assert not any(key.endswith('_ref') for key in value)
        for child in value.values(): assert_no_private_bindings(child)
    elif isinstance(value, list):
        for child in value: assert_no_private_bindings(child)


def test_real_source_fields_bridge_complete_order_identity_and_semantics(bridge, composed):
    before = caches(bridge)
    result = read(bridge)
    assert result['source_state'] == 'available' and result['unavailable_reason'] is None
    assert result['complete_stored_slots'] is True
    assert (result['slot_count'], result['nonnull_slot_count'], result['null_slot_count']) == (3, 3, 0)
    assert result['primary_trained_tactic'] == {'state':'selected', 'native_index':0,
        'slot_index':0, 'meaning':'primary_trained_tactic'}
    assert [r['slot_index'] for r in result['slots']] == [0, 1, 2]
    assert [r['name'] for r in result['slots']] == ['Same tactic', 'Same tactic', 'Attacking']
    assert all(r['state']=='stored' and r['name_state']=='stored' for r in result['slots'])
    for slot in result['slots']:
        assert set(slot['phases']) == {'in_possession', 'out_of_possession'}
        for phase in slot['phases'].values():
            assert phase['formation'] is None
            assert [p['position_index'] for p in phase['positions']] == list(range(11))
            assert [p['name'] for p in phase['positions']] == NAMES
            assert all(p['state']=='named' for p in phase['positions'])
    assert result['unavailable_fields'] == UNAVAILABLE
    assert 'primary' in result['limitations'].lower() and 'match' in result['limitations'].lower()
    assert_no_private_bindings(result)
    assert caches(bridge) == before


@pytest.mark.parametrize('count', [0, 1, 2, 3, 4])
@pytest.mark.parametrize('selector', [0, 1, 2, 3, 255])
def test_unsigned_selector_all_bounds_full_accounting_no_fallback(bridge, composed, count, selector):
    m = composed
    creators = m['creator_addresses']
    m['vec'](m['tactics_payload']+0x1000, [creators[i % 3] for i in range(count)])
    m['put'](m['tactics_payload']+0x1018, bytes([selector]))
    result = read(bridge)
    state = 'selector_out_of_range' if selector > 2 else 'selector_beyond_count' if selector >= count else 'selected'
    assert result['primary_trained_tactic'] == {'state':state, 'native_index':selector,
        'slot_index':selector if state=='selected' else None, 'meaning':'primary_trained_tactic'}
    assert result['complete_stored_slots'] is True and result['source_state'] == 'available'
    assert result['slot_count'] == result['nonnull_slot_count'] == len(result['slots']) == count
    assert result['null_slot_count'] == 0
    assert [s['slot_index'] for s in result['slots']] == list(range(count))
    assert [s['name'] for s in result['slots']] == [['Same tactic', 'Same tactic', 'Attacking'][i % 3] for i in range(count)]


@pytest.mark.parametrize('selector,expected', [(0, 'selected_slot_null'), (1, 'selected'), (2, 'selected_slot_null'), (3, 'selector_out_of_range')])
def test_null_slots_retained_and_selector_distinguished(bridge, composed, selector, expected):
    m = composed
    m['vec'](m['tactics_payload']+0x1000, [0, m['creator_addresses'][1], 0])
    m['put'](m['tactics_payload']+0x1018, bytes([selector]))
    result = read(bridge)
    assert (result['slot_count'], result['nonnull_slot_count'], result['null_slot_count']) == (3, 1, 2)
    assert result['primary_trained_tactic'] == {'state':expected, 'native_index':selector,
        'slot_index':1 if expected=='selected' else None, 'meaning':'primary_trained_tactic'}
    for index in (0, 2):
        assert result['slots'][index] == {'slot_index':index,'state':'null_slot','name':None,
                                         'name_state':'unavailable','phases':None}


@pytest.mark.parametrize('which,reason', [('manager', 'tactics_manager_missing'),
    ('owner', 'owner_container_missing'), ('team', 'team_entry_missing')])
def test_proven_source_absence_is_explicit_unavailable(bridge, composed, which, reason):
    m = composed
    if which == 'manager': m['q'](m['base']+source.MANAGER_ROOT, 0)
    if which == 'owner': m['vec'](m['tactics_manager']+0x20, [])
    if which == 'team':
        m['q'](m['owner_container'], m['owner_container']+8)
        m['q'](m['owner_container']+8, 0)
        m['q'](m['owner_container']+0x10, 0)
    result = read(bridge)
    assert result['source_state'] == 'unavailable' and result['unavailable_reason'] == reason
    assert result['complete_stored_slots'] is False and result['slots'] == []
    assert result['slot_count'] is result['nonnull_slot_count'] is result['null_slot_count'] is None
    assert result['primary_trained_tactic'] == {'state':'source_unavailable','native_index':None,
        'slot_index':None,'meaning':'primary_trained_tactic'}
    assert_no_private_bindings(result)


def test_unavailable_source_still_requires_valid_native_owner(bridge, composed):
    m = composed
    m['q'](m['base']+source.MANAGER_ROOT, 0)
    m['q'](m['team']+0x80, m['manager']+8)
    with pytest.raises(BridgeError): read(bridge)


def test_independent_team_secondary_id_zero_is_valid(bridge, composed):
    m = composed
    m['put'](m['team']+0x10, struct.pack('<I', 0))
    result = read(bridge)
    assert result['team']['random_id'] == 0
    assert result['slot_count'] == 3


@pytest.mark.parametrize('raw,expected,state,unaligned', [
    (b'', '', 'empty', False), (b'Name  ', 'Name  ', 'stored', False),
    ('Táctica 日本'.encode(), 'Táctica 日本', 'stored', False),
    (b'Unaligned', 'Unaligned', 'stored', True), (b'x'*512, 'x'*512, 'stored', False),
])
def test_stored_names_preserve_exact_native_values(bridge, composed, raw, expected, state, unaligned):
    m = composed
    set_name(m, m['creator_addresses'][0], raw, unaligned=unaligned)
    slot = read(bridge)['slots'][0]
    assert slot['name'] == expected and slot['name_state'] == state


def test_null_native_name_differs_from_null_slot(bridge, composed):
    m = composed
    m['q'](m['creator_addresses'][0]+0x790, 0)
    slot = read(bridge)['slots'][0]
    assert slot['state'] == 'stored' and slot['name'] is None and slot['name_state']=='null_native_string'
    assert slot['phases'] is not None


@pytest.mark.parametrize('mask', [0, 2, 0xFFFFFFFF])
def test_unknown_masks_retain_u32_and_named_gk_is_not_negative_sentinel(bridge, composed, mask):
    m = composed
    m['put'](m['creator_addresses'][0]+0x440+0x48, struct.pack('<I', mask))
    slot = read(bridge)['slots'][0]
    assert slot['phases']['out_of_possession']['positions'][1] == {
        'position_index':1,'native_mask':mask,'name':None,'state':'unmapped_native_mask'}
    assert slot['phases']['in_possession']['positions'][0] == {
        'position_index':0,'native_mask':1,'name':'GK','state':'named'}
    assert slot['phases']['in_possession']['positions'][1]['name'] == 'D(R)'


@pytest.mark.parametrize('fault', ['manager_type', 'manager_rtti', 'cast_displacement', 'cast_getter',
    'team_membership', 'contract', 'duplicate_owner', 'owner_budget', 'slot_budget', 'wrapper_type',
    'wrapper_rtti', 'cycle', 'child_alignment', 'tree_size', 'tree_empty', 'slot_alignment',
    'vector_order', 'source_native', 'fields_native', 'bad_utf8', 'bad_terminator', 'control',
    'embedded_nul', 'long_name', 'name_pointer'])
def test_malformed_real_source_rejects_whole_result_without_ref_changes(bridge, composed, fault):
    m = composed
    base = m['base']; payload = m['tactics_payload']; creator = m['creator_addresses'][2]
    if fault == 'manager_type': m['q'](m['tactics_manager'], 0)
    if fault == 'manager_rtti': m['put'](base+source.MANAGER_VTABLE-16, struct.pack('<q', 8))
    if fault == 'cast_displacement': m['put'](base+source.PERSON_VTABLE-0x700, struct.pack('<q', 0))
    if fault == 'cast_getter': m['q'](base+source.PERSON_VTABLE+0x6F0, base+0x1300070)
    if fault == 'team_membership': m['put'](m['team']+8, struct.pack('<I', 1))
    if fault == 'contract': m['q'](m['contract']+0x10, m['team']+8)
    if fault == 'duplicate_owner': m['vec'](m['tactics_manager']+0x20, [m['owner_container']]*2)
    if fault == 'owner_budget': m['vec'](m['tactics_manager']+0x20, [m['owner_container']]*257)
    if fault == 'slot_budget': m['vec'](payload+0x1000, [creator]*65)
    if fault == 'wrapper_type': m['q'](payload+0xFF8, 0)
    if fault == 'wrapper_rtti': m['put'](base+source.PREPARED_VTABLE-16, struct.pack('<q', -8))
    if fault == 'cycle': m['q'](m['team_node'], m['team_node'])
    if fault == 'child_alignment': m['q'](m['team_node'], m['team_node']+1)
    if fault == 'tree_size': m['q'](m['owner_container']+0x10, 0)
    if fault == 'tree_empty': m['q'](m['owner_container']+8, 0)
    if fault == 'slot_alignment': m['vec'](payload+0x1000, [creator+1])
    if fault == 'vector_order': m['put'](payload+0x1000, struct.pack('<QQQ', 0x5000, 0x4000, 0x5000))
    if fault == 'source_native': m['put'](base+source.NATIVE_SPANS[0][0], b'\0')
    if fault == 'fields_native': m['put'](base+fields.NATIVE_SPANS[0][0], b'\0')
    if fault == 'bad_utf8': set_name(m, creator, b'\xff')
    if fault == 'bad_terminator': set_name(m, creator, b'name', terminator=b'x')
    if fault == 'control': set_name(m, creator, b'bad\nname')
    if fault == 'embedded_nul': set_name(m, creator, b'bad\0name')
    if fault == 'long_name': set_name(m, creator, b'x'*513)
    if fault == 'name_pointer': m['q'](creator+0x790, 17)
    before = caches(bridge)
    with pytest.raises(BridgeError): read(bridge)
    assert caches(bridge) == before


@pytest.mark.parametrize('target', ['selector', 'slot_pointer', 'wrapper_header', 'tree_key', 'owner',
                                    'name', 'phase', 'native', 'canonical_identity', 'save_date'])
def test_late_lifetime_changes_fail_after_real_decode(bridge, monkeypatch, composed, target):
    m = composed
    original = fields.decode
    calls = []
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(args[2])
        if len(calls) == 3:
            if target == 'selector': m['put'](m['tactics_payload']+0x1018, b'\x01')
            if target == 'slot_pointer':
                start = struct.unpack('<Q', m['read'](m['tactics_payload']+0x1000, 8))[0]
                m['q'](start, m['creator_addresses'][1])
            if target == 'wrapper_header': m['q'](m['tactics_payload']+0x1010, 0)
            if target == 'tree_key': m['put'](m['team_node']+0x20, struct.pack('<i', 1))
            if target == 'owner': m['q'](m['owner_container']+0x98, m['manager']+8)
            if target == 'name': set_name(m, m['creator_addresses'][0], b'changed')
            if target == 'phase': m['put'](m['creator_addresses'][0]+0x120, struct.pack('<I', 4))
            if target == 'native': m['put'](m['base']+fields.NATIVE_SPANS[0][0], b'\0')
            if target == 'canonical_identity': m['put'](m['team']+0x10, struct.pack('<I', 0))
            if target == 'save_date': m['put'](m['base']+world.CURRENT_DATE, struct.pack('<I', (2030<<16)|263))
        return result
    monkeypatch.setattr(fields, 'decode', mutate)
    before = caches(bridge)
    with pytest.raises(BridgeError, match='changed|rejected'): read(bridge)
    assert len(calls) == 3 and caches(bridge) == before


def test_process_restart_after_decoding_rejects_and_does_not_restore_expired_refs(bridge, monkeypatch, composed):
    from fm_live_mcp import bridge as module
    original = fields.decode
    calls = []
    def restarting(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(args[2])
        if len(calls) == 3:
            monkeypatch.setattr(module, 'process_info', lambda pid: replace(PROCESS, started='restarted'))
        return result
    monkeypatch.setattr(fields, 'decode', restarting)
    with pytest.raises(BridgeError, match='restarted|changed'):
        read(bridge)
    assert len(calls) == 3 and bridge.session is None
    assert all(not refs for refs in caches(bridge).values())


def test_short_transport_read_rejects_after_two_valid_slots(bridge, monkeypatch, composed):
    original = bridge._read_memory
    target = composed['creator_addresses'][2]+0x790
    def short(process, address, length):
        raw = original(process, address, length)
        return raw[:-1] if address == target else raw
    monkeypatch.setattr(bridge, '_read_memory', short)
    before = caches(bridge)
    with pytest.raises(BridgeError, match='Incomplete|incomplete'):
        read(bridge)
    assert caches(bridge) == before


@pytest.mark.parametrize('coach_name', ['', True, 1, [], {}, 'Different coach'])
def test_invalid_or_unknown_coach_rejects_before_tactics_source(bridge, monkeypatch, composed, coach_name):
    monkeypatch.setattr(source, 'inspect', lambda *args: pytest.fail('Invalid coach reached tactics source'))
    with pytest.raises(BridgeError): bridge.get_managed_tactics(bridge.session, coach_name=coach_name)


def test_existing_coach_name_selection_is_case_and_space_normalized(bridge, composed):
    name = composed['coach']['name']
    selected = bridge.get_managed_tactics(bridge.session, coach_name='  '+name.upper()+'  ')
    assert selected['coach'] == name and selected['slot_count'] == 3


def test_mcp_schema_read_only_with_optional_details():
    from fm_live_mcp.server import mcp
    tool = next(t for t in asyncio.run(mcp.list_tools()) if t.name=='fm_get_managed_tactics')
    assert set(tool.inputSchema['required']) == {'session_id'}
    assert set(tool.inputSchema['properties']) == {'session_id','coach_name','include_instructions','include_formation','include_roles'}
    assert tool.inputSchema['properties']['coach_name']['default'] is None
    assert tool.annotations.readOnlyHint is True and tool.annotations.destructiveHint is False
    assert tool.annotations.openWorldHint is False
    assert 'primary trained' in tool.description.lower() and 'match' in tool.description.lower()
