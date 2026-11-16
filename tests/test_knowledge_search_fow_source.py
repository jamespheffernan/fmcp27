"""Full original1F9AA0C and reached callees in owned synthetic memory only."""
from _knowledge_stream_fixture import native_stream_transport
import hashlib
import struct

import pytest
from unicorn.arm64_const import UC_CPU_ARM64_MAX

from fm_live_mcp import knowledge_search_fow_source as source
from fm_live_mcp import knowledge_search_preliminary_source as preliminary
from fm_live_mcp import knowledge_search_association_source as association
from test_knowledge_search_preliminary_source import memory as preliminary_memory,association_memory,alternate_context,identity,restore_metadata
from _knowledge_state_native import execute


@pytest.fixture
def memory(preliminary_memory):
    m=preliminary_memory
    for rva,n,digest in source.NATIVE_GUARDS:
        raw=m.disk(rva,n);assert hashlib.sha256(raw).hexdigest()==digest;m.put(m.base+rva,raw)
    other=m.typed('nation',0x220);m.identity(other,1,110,110)
    m.database('nations',[m.nation,other]);m.other_nation=other
    m.search_context=alternate_context(m,nation=other)
    m.service=m.allocate(16);m.native_type(m.service,0x55def88)
    m.q(m.base+0x56d2d08,m.service);m.q(m.base+0x55def88+0x348,m.base+0x1f9aa0c)
    m.q(m.base+0x55ad820+0x678,m.base+0x1300060)
    m.put(m.base+0x55ad820-0x688,struct.pack('<q',-0x548))
    m.q(m.base+0x558a780+0x668,m.base+0xd5c5fc)
    m.q(m.base+0x55908e0+0x668,m.base+0xd5c5fc)
    m.put(m.primary+0x25a,struct.pack('<h',0))
    m.put(m.human+0x3fc,b'\0');m.vec(m.primary+0xc8,[])
    restore_metadata(m)
    return m


def evaluate(m,**kwargs):
    return source.evaluate(m.read,m.base,m.person,m.person_ref,m.search_context,identity(m,m.search_context),
                           m.human,identity(m,m.human_person),
                           check_current=kwargs.pop('check_current',lambda:('process','save','build')),**kwargs)


def native(m):
    value,_,reads,writes,instructions=execute(m,0x1f9aa0c,[m.service,m.primary,m.search_context,m.human],
        extra=source.NATIVE_GUARDS+preliminary.NATIVE_GUARDS+association.NATIVE_GUARDS,cpu_model=UC_CPU_ARM64_MAX)
    assert 0x1f9aa0c in instructions
    assert all(0x200000000<=at<at+n<=0x200010000 for _,at,n in writes)
    return bool(value),reads,instructions


def node(m,owner_uid,raw,*,four_aligned=False):
    at=m.allocate(16)+(4 if four_aligned else 0)
    m.put(at,struct.pack('<II',m.person_ref[0],owner_uid)+bytes([raw])+bytes(3))
    return at


def test_every_signed_knowledge_byte_matches_complete_native_and_four_byte_pool_stride(memory):
    m=memory;owner=identity(m,m.human_person)[1];row=node(m,owner,0,four_aligned=True)
    assert row%8==4;m.vec(m.primary+0xc8,[row]);cells=dict(m.cells)
    for raw in range(256):
        m.put(row+8,bytes([raw]))
        actual=evaluate(m);expected,reads,instructions=native(m)
        assert actual['native_result'] is expected is (1<=raw<=127)
        assert 0x238816c in instructions and (row+8,1) in reads
        assert set(actual)=={'scope','native_result','complete_search_population_evaluated','field_visibility_evaluated','non_atomic'}
    cells[row+8]=255;assert m.cells==cells


def test_reverse_order_uses_last_matching_owner_not_maximum_score(memory):
    m=memory;owner=identity(m,m.human_person)[1]
    one=node(m,owner,1);zero=node(m,owner,0,four_aligned=True);foreign=node(m,owner+1,127)
    for listing,want in (([],False),([one,foreign,zero],False),([zero,foreign,one],True),([foreign],False)):
        m.vec(m.primary+0xc8,listing)
        assert evaluate(m)['native_result'] is native(m)[0] is want


@pytest.mark.parametrize('field',[0x56d4980,'owner_flag'])
def test_all_native_enable_and_owner_flag_bytes_preserve_bypass_results(memory,field):
    m=memory;at=m.human+0x3fc if field=='owner_flag' else m.base+field
    for raw in range(256):
        m.put(at,bytes([raw]));expected=bool(raw&16)if field=='owner_flag'else raw!=1
        assert evaluate(m)['native_result'] is native(m)[0] is expected


@pytest.mark.parametrize('raw',[-32768,0,5248,5249,5250,32767])
def test_signed_scalar_threshold_has_exact_strict_boundary(memory,raw):
    m=memory;m.put(m.primary+0x25a,struct.pack('<h',raw))
    assert evaluate(m)['native_result'] is native(m)[0] is (raw>5249)


@pytest.mark.parametrize('ordinal',[-2147483648,-1,0,1,2147483647])
def test_out_of_range_owner_ordinal_is_native_bypass_not_knowledge(memory,ordinal):
    m=memory;m.put(m.human+0x3e4,struct.pack('<i',ordinal))
    assert evaluate(m)['native_result'] is native(m)[0] is (ordinal!=0)


def test_null_owner_slot_bypasses_but_wrong_owner_backlink_is_unavailable(memory):
    m=memory;m.vec(m.fow+0x18,[0])
    assert evaluate(m)['native_result'] is native(m)[0] is True
    m.vec(m.fow+0x18,[m.record]);m.q(m.record+0x18,m.person)
    with pytest.raises(ValueError,match='another HUMAN'):evaluate(m)


def test_same_normalized_association_admits_except_special_distinct_pointers(memory):
    m=memory
    m.identity(m.nation,0,380,380);m.identity(m.other_nation,1,784,784)
    m.identity(m.search_context,1,380,9999)
    assert evaluate(m)['native_result'] is native(m)[0] is True
    m.identity(m.nation,0,129514,129514);m.identity(m.other_nation,1,363,363)
    m.identity(m.search_context,1,129514,9999)
    assert evaluate(m)['native_result'] is native(m)[0] is False
    row=node(m,identity(m,m.human_person)[1],1);m.vec(m.primary+0xc8,[row])
    assert evaluate(m)['native_result'] is native(m)[0] is True
    m.q(m.search_context+0x170,m.nation)
    assert evaluate(m)['native_result'] is native(m)[0] is True


def test_preliminary_rejection_does_not_become_a_fow_bypass(memory):
    m=memory;m.put(m.primary+0x266,b'\x53');m.put(m.base+0x56d4980,b'\0')
    assert evaluate(m)['native_result'] is native(m)[0] is False


def test_null_native_selected_context_rejects_before_any_fow_bypass(memory):
    m=memory;m.search_context=0;m.put(m.base+0x56d4980,b'\0')
    actual=source.evaluate(m.read,m.base,m.person,m.person_ref,0,None,m.human,
                          identity(m,m.human_person),check_current=lambda:('process','save','build'))
    assert actual['native_result'] is native(m)[0] is False
    with pytest.raises(ValueError,match='Null search context'):
        source.evaluate(m.read,m.base,m.person,m.person_ref,0,(1,2,3),m.human,
                        identity(m,m.human_person),check_current=lambda:('process','save','build'))


@pytest.mark.parametrize('fault',['service','route','source','owner_type','node_alignment','null_node','manager'])
def test_invalid_sources_are_unavailable_instead_of_a_discovery_answer(memory,fault):
    m=memory
    if fault=='service':m.q(m.service,0)
    if fault=='route':m.q(m.base+0x55def88+0x348,0)
    if fault=='source':m.put(m.base+0x1f9aa0c,b'\0')
    if fault=='owner_type':m.q(m.human_person,0)
    if fault in ('node_alignment','null_node'):
        row=node(m,identity(m,m.human_person)[1],1);m.vec(m.primary+0xc8,[row+2 if fault=='node_alignment'else 0])
    if fault=='manager':m.q(m.base+0x56a8430,0)
    with pytest.raises(ValueError):evaluate(m)


def test_final_callback_must_not_change_the_stored_knowledge_byte(memory):
    m=memory;row=node(m,identity(m,m.human_person)[1],1);m.vec(m.primary+0xc8,[row]);calls=[]
    def lifetime():
        calls.append(1)
        if len(calls)==2:m.put(row+8,b'\0')
        return ('bound','save','process')
    with pytest.raises(ValueError,match='changed'):evaluate(m,check_current=lifetime)
