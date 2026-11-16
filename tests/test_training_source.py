"""Resident source identity, native ordering, absence and structural corruption."""
import struct

import pytest

from fm_live_mcp import training_source as source, world
from training_source_fixture import (training_source_memory, prepared_tactics_memory,
                                     team_memory, database_memory, memory, world_memory)


def inspect(m, read=None):
    return source.inspect(read or m['read'], m['base'], m['coach'])


def test_real_typed_fixture_preserves_keys_order_and_private_pointers(training_source_memory):
    m = training_source_memory
    team, reason, weeks = inspect(m)
    assert team['native_id'] == 50 and team['native_type_code'] == 0
    assert reason is None
    assert weeks == ((2030, 301, m['training_wrapper_addresses'][0]),
                     (2030, 308, m['training_wrapper_addresses'][1]))
    assert 'address' not in repr(team) and '0x' not in repr(team)


def test_empty_resident_vector_is_available_not_missing_source(training_source_memory):
    m = training_source_memory
    m['set_training_weeks']([])
    assert inspect(m)[1:] == (None, ())


def test_null_manager_is_unavailable_not_empty(training_source_memory):
    m = training_source_memory
    m['q'](m['training_source_root'], 0)
    assert inspect(m)[1:] == ('training_manager_missing', None)


@pytest.mark.parametrize('mode', [0,2,3,255])
def test_alternate_mode_stops_before_manager_read(training_source_memory, mode):
    m = training_source_memory
    m['put'](m['training_source_gate'], bytes([mode]))

    def read(address, size):
        assert address != m['training_source_root']
        return m['read'](address, size)

    assert inspect(m, read)[1:] == ('unsupported_training_assignment_mode', None)


def test_absent_owner_and_absent_direct_team_preserve_fallback_boundary(training_source_memory):
    m = training_source_memory
    owner, manager = m['training_owner'], m['training_manager']
    m['vec'](manager+0x38, [])
    assert inspect(m)[1:] == ('owner_entry_missing', None)
    m['vec'](manager+0x38, [owner])
    m['q'](owner+0x90, m['manager']+0x550)
    assert inspect(m)[1:] == ('owner_entry_missing', None)
    m['q'](owner+0x90, m['manager']+0x548)
    m['q'](owner+0x48, owner+0x50)
    m['q'](owner+0x50, 0)
    m['q'](owner+0x58, 0)
    assert inspect(m)[1:] == ('direct_team_entry_missing_native_fallback_unsupported', None)


def test_first_matching_owner_is_native_order_not_ambiguous(training_source_memory):
    m = training_source_memory
    original = m['training_owner']
    second = m['allocate'](0xA8)
    node = m['allocate'](0xC0)
    m['q'](second+0x90, m['manager']+0x548)
    m['q'](second+0x98, m['club'])
    m['q'](second+0x48, node)
    m['q'](second+0x50, node)
    m['q'](second+0x58, 1)
    m['q'](node+0x10, second+0x50)
    m['q'](node+0x20, m['team'])
    other = m['training_wrapper'](315, 2030)
    m['vec'](node+0x48, [other])
    m['vec'](m['training_manager']+0x38, [second, original])
    assert inspect(m)[2] == ((2030,315,other),)
    m['vec'](m['training_manager']+0x38, [original, second])
    assert inspect(m)[2][0][1] == 301


def test_same_person_without_team_does_not_hide_later_exact_owner(training_source_memory):
    m = training_source_memory
    empty = m['allocate'](0xA8)
    m['q'](empty+0x90, m['manager']+0x548)
    m['q'](empty+0x48, empty+0x50)
    m['vec'](m['training_manager']+0x38, [empty,m['training_owner']])
    assert inspect(m)[1] is None


def test_duplicate_unsorted_wrappers_upper_flags_and_unknown_keys_are_retained(training_source_memory):
    m = training_source_memory
    a,b = m['training_wrapper_addresses']
    odd = m['training_wrapper'](0, 0, upper_bits=127)
    m['set_training_weeks']([b,a,odd,a])
    assert inspect(m)[2] == ((2030,308,b),(2030,301,a),(0,0,odd),(2030,301,a))


@pytest.mark.parametrize('fault', ['manager_type','manager_rtti','manager_displacement','club',
                                  'null_owner','null_week','unaligned_manager','unaligned_owner','unaligned_week'])
def test_wrong_bindings_and_illegal_null_entries_reject(training_source_memory, fault):
    m = training_source_memory
    if fault == 'manager_type':m['q'](m['training_manager'],0)
    elif fault == 'manager_rtti':
        ti = struct.unpack('<Q',m['read'](m['base']+source.MANAGER_VTABLE-8,8))[0]
        p = struct.unpack('<Q',m['read'](ti+8,8))[0]
        m['put'](p,b'X')
    elif fault == 'manager_displacement':m['put'](m['base']+source.MANAGER_VTABLE-16,struct.pack('<q',8))
    elif fault == 'club':m['q'](m['training_owner']+0x98,m['owners'][1])
    elif fault == 'null_owner':m['vec'](m['training_manager']+0x38,[0])
    elif fault == 'null_week':m['set_training_weeks']([0])
    elif fault == 'unaligned_manager':m['q'](m['training_source_root'],4097)
    elif fault == 'unaligned_owner':m['vec'](m['training_manager']+0x38,[4097])
    elif fault == 'unaligned_week':m['set_training_weeks']([4097])
    with pytest.raises(ValueError):inspect(m)


@pytest.mark.parametrize('fault', ['cycle','wrong_parent','wrong_count','wrong_begin','empty_bad_begin',
                                  'empty_bad_count','too_many','unaligned_key','zero_key','child_order'])
def test_complete_tree_validation_rejects_corruption(training_source_memory, fault):
    m = training_source_memory
    owner,node=m['training_owner'],m['training_team_node']
    if fault == 'cycle':m['q'](node,node)
    elif fault == 'wrong_parent':m['q'](node+0x10,owner)
    elif fault == 'wrong_count':m['q'](owner+0x58,2)
    elif fault == 'wrong_begin':m['q'](owner+0x48,owner)
    elif fault == 'empty_bad_begin':m['q'](owner+0x50,0);m['q'](owner+0x58,0)
    elif fault == 'empty_bad_count':m['q'](owner+0x50,0)
    elif fault == 'too_many':m['q'](owner+0x58,source.TREE_NODE_LIMIT+1)
    elif fault == 'unaligned_key':m['q'](node+0x20,4097)
    elif fault == 'zero_key':m['q'](node+0x20,0)
    elif fault == 'child_order':
        child=m['allocate'](0x28)
        m['q'](node,child);m['q'](child+0x10,node);m['q'](child+0x20,m['team']+8)
        m['q'](owner+0x48,child);m['q'](owner+0x58,2)
    with pytest.raises(ValueError):inspect(m)


def test_valid_three_node_pointer_order_and_backlinks(training_source_memory):
    m=training_source_memory;owner,node=m['training_owner'],m['training_team_node']
    left,right=m['allocate'](0x28),m['allocate'](0x28)
    m['q'](node,left);m['q'](node+8,right)
    for child,key in [(left,m['team']-8),(right,m['team']+8)]:
        m['q'](child+0x10,node);m['q'](child+0x20,key)
    m['q'](owner+0x48,left);m['q'](owner+0x58,3)
    assert inspect(m)[1] is None


@pytest.mark.parametrize('vector_kind', ['owner','week'])
@pytest.mark.parametrize('fault', ['backwards','bad_capacity','unaligned','budget'])
def test_bounded_vectors_reject_before_payload_read(training_source_memory, vector_kind, fault):
    m=training_source_memory
    address=m['training_manager']+0x38 if vector_kind=='owner' else m['training_team_node']+0x48
    start,end,cap=struct.unpack('<QQQ',m['read'](address,24))
    limit=source.OWNER_LIMIT if vector_kind=='owner' else source.WEEK_LIMIT
    if fault=='backwards':end=start-8
    elif fault=='bad_capacity':cap=start
    elif fault=='unaligned':start+=1
    elif fault=='budget':cap=start+(limit+1)*8
    m['put'](address,struct.pack('<QQQ',start,end,cap))
    with pytest.raises(ValueError):inspect(m)


def test_only_headers_are_read_and_source_mutation_is_tracked(training_source_memory):
    m=training_source_memory
    wrappers=set(m['training_wrapper_addresses'])
    def read(address,size):
        assert not any(p+0x10<=address<p+0x48 for p in wrappers)
        return m['read'](address,size)
    snapshot=world.ReadSet(read)
    assert inspect(m,snapshot)[1] is None
    snapshot.verify()
    m['put'](m['training_wrapper_addresses'][0]+0xC,struct.pack('<H',302))
    with pytest.raises(ValueError):snapshot.verify()


@pytest.mark.parametrize('index',range(len(source.NATIVE_SPANS)))
def test_every_native_guard_fails_closed(training_source_memory,index):
    m=training_source_memory;rva,raw=source.NATIVE_SPANS[index]
    m['put'](m['base']+rva,bytes([raw[0]^1]))
    with pytest.raises(ValueError,match='native source changed'):inspect(m)


@pytest.mark.parametrize('base',[None,True,0,4095,4097,(1<<64)-8])
def test_invalid_base_rejects_without_reads(base):
    with pytest.raises(ValueError,match='address'):
        source.inspect(lambda *_:pytest.fail('unexpected read'),base,{})


def test_truncated_native_read_rejects(training_source_memory):
    with pytest.raises(ValueError,match='Incomplete'):
        inspect(training_source_memory,lambda *_:b'')


def test_truncated_shared_identity_read_is_value_error(training_source_memory):
    m=training_source_memory
    def read(address,size):
        value=m['read'](address,size)
        return value[:-1] if address==m['team']+8 else value
    with pytest.raises(ValueError,match='Incomplete'):
        inspect(m,read)


def test_full_tree_depth_budget_rejects_even_after_root_team_match(training_source_memory):
    m=training_source_memory;owner,node=m['training_owner'],m['training_team_node']
    last=node
    for index in range(1,source.TREE_DEPTH_LIMIT+1):
        child=m['allocate'](0x28)
        m['q'](last+8,child);m['q'](child+0x10,last)
        m['q'](child+0x20,m['team']+index*8)
        last=child
    m['q'](owner+0x58,source.TREE_DEPTH_LIMIT+1)
    with pytest.raises(ValueError,match='depth budget'):inspect(m)
