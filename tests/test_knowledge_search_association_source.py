"""Typed synthetic source and complete original CF3C90/getter reexecution.

No attachment, live native function or public Manager mode is exercised.
"""
from _knowledge_stream_fixture import native_stream_transport
from copy import deepcopy
import hashlib
import struct

import pytest

from fm_live_mcp import knowledge_search_association_source as source
from test_knowledge_context_score_source import Memory
from _knowledge_state_native import execute


@pytest.fixture(params=[False,True],ids=['actual','combined'])
def memory(request):
    m = Memory(combined=request.param)
    for rva,n,digest in source.NATIVE_GUARDS:
        raw=m.disk(rva,n);assert hashlib.sha256(raw).hexdigest()==digest
        m.put(m.base+rva,raw)
    table=int.from_bytes(m.read(m.person,8),'little')
    for offset in (-0x300,-0x568):
        m.put(table+offset,m.disk(table-m.base+offset,8))
    for slot,rva in ((0x2f0,0xcf3c90),(0x558,0xd5c590)):
        m.q(table+slot,m.base+rva)
    m.q(m.common+0x48,0)
    m.put(m.primary+0x266,b'\0')
    return m


def evaluate(m,target=None,**kwargs):
    uid=int.from_bytes(m.read(m.nation+0xc,4),'little') if target is None else target
    return source.evaluate(m.read,m.base,m.person,m.person_ref,uid,
                          check_current=kwargs.pop('check_current',lambda:('save','process','build')),**kwargs)


def native(m,target):
    result,_,reads,writes,instructions=execute(m,0xcf3c90,[m.person,target],extra=source.NATIVE_GUARDS)
    assert 0xcf3c90 in instructions
    assert all(0x200000000<=at<at+n<=0x200010000 for _,at,n in writes)
    return bool(result),reads,instructions


def test_all_256_direct_status_bytes_match_complete_original_predicate(memory):
    m=memory;target=int.from_bytes(m.read(m.nation+0xc,4),'little')
    before=deepcopy(m.cells)
    for raw in range(256):
        m.put(m.primary+0x266,bytes([raw]))
        actual=evaluate(m);expected,reads,instructions=native(m,target)
        assert actual['native_result'] is expected
        assert expected is (raw in (0,0x50,0x54,0x55))
        assert 0xd5c590 in instructions
        assert (m.primary+0x266,1) in reads
        assert not actual['search_admission_evaluated'] and not actual['field_visibility_evaluated']
    before[m.primary+0x266]=255
    assert m.cells==before


def rows(m,specs):
    at=m.allocate(max(16,len(specs)*16));holder=m.allocate(24)
    for index,(owner,kind,category,status) in enumerate(specs):
        row=at+16*index;m.q(row,owner)
        m.put(row+0xa,bytes([kind,category,0,status]))
    m.put(holder,struct.pack('<QQQ',at,at+16*len(specs),at+16*len(specs)))
    m.q(m.common+0x48,holder)
    return at,holder


@pytest.mark.parametrize('kind',[2,8])
def test_all_row_subtype_bytes_match_original_and_reject_near_misses(memory,kind):
    m=memory;target=int.from_bytes(m.read(m.nation+0xc,4),'little');m.q(m.common+0x38,0)
    at,_=rows(m,[(m.container if kind==2 else m.nation,kind,9,0)])
    for subtype in range(256):
        m.put(at+0xd,bytes([subtype]))
        expected,_,_=native(m,target)
        assert evaluate(m)['native_result'] is expected is (subtype in (0x50,0x54,0x55))


def test_empty_null_duplicates_nonmatching_and_later_matching_rows(memory):
    m=memory;target=int.from_bytes(m.read(m.nation+0xc,4),'little');m.q(m.common+0x38,0)
    for specs in ([],[(0,8,9,0x50)],[(m.nation,8,8,0x50)],[(m.nation,7,9,0x50)],
                  [(m.nation,8,9,0x54)]*2,[(0,8,9,0x50),(m.nation,8,9,0x55)]):
        rows(m,specs)
        assert evaluate(m)['native_result'] is native(m,target)[0]
    assert evaluate(m,target+1)['native_result'] is native(m,target+1)[0] is False


@pytest.mark.parametrize('fault',['identity','cast','getter','source','geometry','nation_membership'])
def test_invalid_native_sources_reject_instead_of_returning_false(memory,fault):
    m=memory
    if fault=='identity':m.identity(m.person,0,9999,1002)
    if fault=='cast':m.put(int.from_bytes(m.read(m.person,8),'little')-0x300,struct.pack('<q',0))
    if fault=='getter':m.q(int.from_bytes(m.read(m.person,8),'little')+0x558,0)
    if fault=='source':m.put(m.base+0xcf3c90,b'\0')
    if fault=='geometry':
        m.q(m.common+0x38,0);at,holder=rows(m,[]);m.q(holder+8,at+1)
    if fault=='nation_membership':m.identity(m.nation,9999,12345,12345)
    with pytest.raises(ValueError):evaluate(m)


def test_final_lifetime_callback_cannot_mutate_a_consumed_operand(memory):
    m=memory;calls=[]
    def lifetime():
        calls.append(1)
        if len(calls)==2:m.put(m.primary+0x266,b'\x01')
        return ('save','process','build')
    with pytest.raises(ValueError,match='changed'):evaluate(m,check_current=lifetime)
