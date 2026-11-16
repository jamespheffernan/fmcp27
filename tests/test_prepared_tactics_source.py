import copy
import struct

import pytest

from fm_live_mcp import prepared_tactics_source as source, world
from prepared_tactics_fixture import (database_memory, memory, prepared_tactics_memory,
                                     team_memory, world_memory)


def inspect(m, read=None, coach=None):
    return source.inspect(read or m['read'], m['base'], coach or m['coach'])


def test_available_source_and_private_addresses(prepared_tactics_memory):
    m = prepared_tactics_memory
    result, pointers = inspect(m)
    assert pointers == tuple(m['creator_addresses'])
    assert result['source_state'] == 'available'
    assert result['complete_stored_slots'] is True
    assert (result['slot_count'], result['nonnull_slot_count'], result['null_slot_count']) == (3, 3, 0)
    assert result['primary_trained_tactic'] == {
        'state':'selected', 'native_index':0, 'slot_index':0, 'meaning':'primary_trained_tactic'}
    assert result['team']['database_index'] == 0
    assert '0x' not in str(result) and 'address' not in str(result)


@pytest.mark.parametrize('index,count,null,state,selected', [
    (0,3,False,'selected',0), (1,3,False,'selected',1), (2,3,False,'selected',2),
    (3,3,False,'selector_out_of_range',None), (255,0,False,'selector_out_of_range',None),
    (0,0,False,'selector_beyond_count',None), (1,1,False,'selector_beyond_count',None),
    (2,2,False,'selector_beyond_count',None), (0,1,True,'selected_slot_null',None)])
def test_selection_exact_unsigned_precedence(prepared_tactics_memory,index,count,null,state,selected):
    m = prepared_tactics_memory
    creators = m['creator_addresses'][:count]
    if null: creators[0] = 0
    m['vec'](m['tactics_payload']+0x1000, creators)
    m['put'](m['tactics_payload']+0x1018, bytes([index]))
    result, pointers = inspect(m)
    assert len(pointers) == count and result['complete_stored_slots']
    assert result['primary_trained_tactic'] == {
        'state':state, 'native_index':index, 'slot_index':selected, 'meaning':'primary_trained_tactic'}


def test_all_slots_null_duplicates_and_more_than_three_remain_complete(prepared_tactics_memory):
    m = prepared_tactics_memory
    values = [m['creator_addresses'][0], 0, m['creator_addresses'][0], 0]
    m['vec'](m['tactics_payload']+0x1000, values)
    result, pointers = inspect(m)
    assert pointers == tuple(values)
    assert (result['slot_count'], result['nonnull_slot_count'], result['null_slot_count']) == (4,2,2)


@pytest.mark.parametrize('reason', ['tactics_manager_missing','owner_container_missing','team_entry_missing'])
def test_proved_source_absence_is_unavailable_not_empty(prepared_tactics_memory,reason):
    m = prepared_tactics_memory
    if reason == 'tactics_manager_missing': m['q'](m['base']+source.MANAGER_ROOT, 0)
    elif reason == 'owner_container_missing': m['vec'](m['tactics_manager']+0x20, [])
    else: m['put'](m['team_node']+0x20, struct.pack('<i', 4))
    result, pointers = inspect(m)
    assert pointers == () and result['source_state'] == 'unavailable'
    assert result['unavailable_reason'] == reason and not result['complete_stored_slots']
    assert result['slot_count'] is result['nonnull_slot_count'] is result['null_slot_count'] is None
    assert result['primary_trained_tactic']['state'] == 'source_unavailable'


def test_valid_empty_tree_and_null_vector_are_distinct(prepared_tactics_memory):
    m = prepared_tactics_memory
    m['put'](m['tactics_payload']+0x1000, bytes(24))
    result, pointers = inspect(m)
    assert pointers == () and result['slot_count'] == 0 and result['complete_stored_slots']
    m['put'](m['owner_container'], struct.pack('<QQQ',m['owner_container']+8,0,0))
    assert inspect(m)[0]['unavailable_reason'] == 'team_entry_missing'


@pytest.mark.parametrize('fault', ['team_binding','team_id','team_owner','owner_membership',
    'club_backlink','coach_club','human_type','human_person_type','human_person_rtti',
    'human_displacement','person_displacement','cast_displacement','predicate','cast_getter',
    'team_human','contract_owner','contract_team','contract_other_team',
    'manager_pointer','manager_type','manager_rtti','wrapper_type','wrapper_rtti',
    'tree_alignment','tree_cycle','tree_size','tree_begin','tree_order','native'])
def test_corrupt_source_rejected(prepared_tactics_memory,fault):
    m = prepared_tactics_memory
    base, team, human = m['base'], m['team'], m['manager']
    coach = copy.deepcopy(m['coach'])
    if fault == 'team_binding': m['vec'](m['headers']['teams'], list(reversed(m['team_addresses'])))
    elif fault == 'team_id': m['put'](team+12,bytes(4))
    elif fault == 'team_owner': m['q'](team+0x30,0)
    elif fault == 'owner_membership': m['vec'](m['headers']['clubs'],m['owners'][1:])
    elif fault == 'club_backlink': m['vec'](m['club']+0x18,[])
    elif fault == 'coach_club': coach['club']['name']='Other'
    elif fault == 'human_type': m['q'](human,base+world.TYPES['club'][0])
    elif fault == 'human_person_type': m['q'](human+0x548,0)
    elif fault == 'human_person_rtti': m['q'](base+source.PERSON_VTABLE-16,0)
    elif fault == 'human_displacement': m['q'](base+world.TYPES['manager'][0]-0x20,0)
    elif fault == 'person_displacement': m['q'](base+source.PERSON_VTABLE-16,0)
    elif fault == 'cast_displacement': m['q'](base+source.PERSON_VTABLE-0x700,0)
    elif fault == 'predicate': m['q'](base+source.PERSON_VTABLE+0x1B0,0)
    elif fault == 'cast_getter': m['q'](base+source.PERSON_VTABLE+0x6F0,0)
    elif fault == 'team_human': m['q'](team+0x80,0)
    elif fault == 'contract_owner': m['q'](m['contract']+8,team)
    elif fault == 'contract_team': m['q'](m['contract']+0x10,human)
    elif fault == 'contract_other_team': m['q'](m['contract']+0x18,human)
    elif fault == 'manager_pointer': m['q'](base+source.MANAGER_ROOT,3)
    elif fault == 'manager_type': m['q'](m['tactics_manager'],base+world.TYPES['club'][0])
    elif fault == 'manager_rtti': m['q'](base+source.MANAGER_VTABLE-16,8)
    elif fault == 'wrapper_type': m['q'](m['prepared_wrapper'],base+source.MANAGER_VTABLE)
    elif fault == 'wrapper_rtti': m['q'](base+source.PREPARED_VTABLE-16,8)
    elif fault == 'tree_alignment': m['q'](m['owner_container']+8,3)
    elif fault == 'tree_cycle': m['q'](m['team_node'],m['team_node'])
    elif fault == 'tree_size': m['q'](m['owner_container']+0x10,0)
    elif fault == 'tree_begin': m['q'](m['owner_container'],m['owner_container']+8)
    elif fault == 'tree_order':
        child=m['allocate'](0x28)
        m['q'](m['team_node'],child)
        m['put'](child+0x20,struct.pack('<i',1))
        m['q'](m['owner_container']+0x10,2)
    else:
        rva,raw=source.NATIVE_SPANS[-1]
        m['put'](base+rva,bytes([raw[0]^1]))
    with pytest.raises(ValueError): inspect(m,coach=coach)


def test_duplicate_matching_owners_ambiguous_and_unmatched_null_owners_skipped(prepared_tactics_memory):
    m=prepared_tactics_memory
    m['vec'](m['tactics_manager']+0x20,[0,m['owner_container'],m['owner_container']])
    with pytest.raises(ValueError,match='ambiguous'): inspect(m)
    m['vec'](m['tactics_manager']+0x20,[0,m['owner_container']])
    assert inspect(m)[0]['source_state']=='available'


@pytest.mark.parametrize('vector,limit', [('owners',256),('slots',64)])
@pytest.mark.parametrize('fault', ['count','capacity','reverse','unaligned','null_start','bad_entry'])
def test_vector_bounds_are_explicit_implementation_budgets(prepared_tactics_memory,vector,limit,fault):
    m=prepared_tactics_memory
    header=m['tactics_manager']+0x20 if vector=='owners' else m['tactics_payload']+0x1000
    start=m['allocate']((limit+1)*8)
    if fault=='count': values=(start,start+(limit+1)*8,start+(limit+1)*8)
    elif fault=='capacity': values=(start,start,start+(limit+1)*8)
    elif fault=='reverse': values=(start,start-8,start)
    elif fault=='unaligned': values=(start,start+1,start+8)
    elif fault=='null_start': values=(0,8,8)
    else:
        values=(start,start+8,start+8)
        m['q'](start,3)
    m['put'](header,struct.pack('<QQQ',*values))
    with pytest.raises(ValueError): inspect(m)


def test_signed_tree_lower_bound_finds_exact_key_not_first_node(prepared_tactics_memory):
    m=prepared_tactics_memory
    original=m['team_node']
    root=m['allocate'](0x28)
    m['put'](root+0x20,struct.pack('<i',-1))
    m['q'](root+8,original)
    m['q'](m['owner_container'],root)
    m['q'](m['owner_container']+8,root)
    m['q'](m['owner_container']+0x10,2)
    assert inspect(m)[1]==tuple(m['creator_addresses'])


def test_tree_depth_budget_is_not_a_native_cardinality_claim(prepared_tactics_memory):
    m=prepared_tactics_memory
    previous=None
    for key in range(-65,0):
        node=m['allocate'](0x28)
        m['put'](node+0x20,struct.pack('<i',key))
        if previous:m['q'](previous+8,node)
        else:
            m['q'](m['owner_container'],node)
            m['q'](m['owner_container']+8,node)
        previous=node
    m['q'](previous+8,m['team_node'])
    m['q'](m['owner_container']+0x10,66)
    with pytest.raises(ValueError,match='depth budget'): inspect(m)


@pytest.mark.parametrize('target', ['root','owner_header','owner','tree_header','key','child',
    'wrapper','slot_header','slot','selector','team_id','human_cast','native'])
def test_caller_readset_detects_lifetime_changes(prepared_tactics_memory,target):
    m=prepared_tactics_memory
    read=world.ReadSet(m['read'])
    inspect(m,read)
    addresses={'root':m['base']+source.MANAGER_ROOT,
        'owner_header':m['tactics_manager']+0x20,'owner':m['owner_container']+0x98,
        'tree_header':m['owner_container']+8,'key':m['team_node']+0x20,'child':m['team_node'],
        'wrapper':m['prepared_wrapper'],'slot_header':m['tactics_payload']+0x1000,
        'slot':int.from_bytes(m['read'](m['tactics_payload']+0x1000,8),'little'),
        'selector':m['tactics_payload']+0x1018,'team_id':m['team']+12,
        'human_cast':m['base']+source.PERSON_VTABLE+0x6F0,
        'native':m['base']+source.NATIVE_SPANS[-1][0]}
    address=addresses[target]
    old=m['read'](address,1)
    m['put'](address,bytes([old[0]^1]))
    with pytest.raises(ValueError,match='changed'): read.verify()


def test_equal_independent_secondary_id_is_not_normalized_to_primary(prepared_tactics_memory):
    m=prepared_tactics_memory
    m['put'](m['team']+16,struct.pack('<I',0))
    assert inspect(m)[0]['team']['random_id']==0
