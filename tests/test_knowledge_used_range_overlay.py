"""Whole original H parity and finite vector controls; owned fixtures only."""
import ast
import importlib.util
import inspect
import json
from pathlib import Path
import struct
import sys
import textwrap

import pytest

from fm_live_mcp import knowledge_passing_state as state
from test_knowledge_passing_state import memory,low_K
from test_knowledge_context_score_source import SyntheticBridge
from _knowledge_state_native import native_state

from fm_live_mcp import knowledge_used_range_overlay as candidate
Source=candidate.source_type(state.StateSource,state.core)


def bound(m,new=True):
    Type=Source if new else state.StateSource
    return Type(SyntheticBridge(m),'synthetic',m.person,m.person_ref,'Private Coach',18)


def vector(m,header,rows,capacity):
    # Reserve unused address space without populating or mapping spare bytes.
    start=m.allocate(max(8,len(rows)*8))
    m.next+=max(0,capacity-len(rows))*8
    for i,row in enumerate(rows):m.q(start+8*i,row)
    m.put(header,struct.pack('<QQQ',start,start+8*len(rows),start+8*capacity))
    return start


def fixture(combined=False,scores=(100,40),capacity=66070,which='owner'):
    m=memory(combined);low_K(m);nodes=[]
    for score in scores:
        node=m.allocate(16);m.put(node,struct.pack('<IIB',m.person_ref[0],2001,score));nodes.append(node)
    subject=vector(m,m.primary+0xc8,nodes,capacity if which in('subject','both')else len(nodes))
    owner=vector(m,m.record,nodes,capacity if which in('owner','both')else len(nodes))
    m.blocked=[(m.primary+0x148,m.primary+0x18d)]
    return m,subject,owner,nodes


@pytest.mark.parametrize('combined',[False,True])
@pytest.mark.parametrize('which',['owner','subject','both'])
@pytest.mark.parametrize('capacity',[6316,66070,2000000])
def test_old_capacity_refusal_new_used_range_matches_full_original_H(combined,which,capacity):
    m,subject,owner,nodes=fixture(combined,capacity=capacity,which=which)
    with pytest.raises(ValueError,match='vector geometry or reader budget'):bound(m,False).state()
    m.reads.clear();s=bound(m);actual=s.state();s.verify()
    typed_reads=list(m.reads)
    native,score,reads,writes,trace=native_state(m)
    assert actual[:2]==(native,score)==(1,40)
    assert 0x23871f0 in trace and 0x2387364 in trace
    subject_capacity=capacity if which in('subject','both')else 2
    owner_capacity=capacity if which in('owner','both')else 2
    unused=[(subject+16,subject+subject_capacity*8),(owner+16,owner+owner_capacity*8)]
    assert not any(a<last and first<a+n for a,n in typed_reads for first,last in unused)
    assert not any(a<last and first<a+n for a,n in reads for first,last in unused)


@pytest.mark.parametrize('scores,expected',[((40,100),(2,100)),((100,40),(1,40)),((40,255),(0,0)),((40,128),(0,0))])
def test_reverse_last_match_and_signed_values_match_original(scores,expected):
    m,*_=fixture(scores=scores,which='both');s=bound(m);actual=s.state();s.verify()
    native,score,*_=native_state(m)
    assert actual[:2]==(native,score)==expected


@pytest.mark.parametrize('header_kind',['subject','owner'])
def test_used_budget_still_rejects4097_before_any_payload_traversal(header_kind):
    m,*_=fixture();header=m.primary+0xc8 if header_kind=='subject'else m.record
    start=m.allocate(8);m.put(header,struct.pack('<QQQ',start,start+4097*8,start+66070*8));s=bound(m)
    m.reads.clear()
    with pytest.raises(state.core.SourceUnavailable,match='used-entry reader budget'):s.reciprocal_score()
    assert not any(start<=a<start+4097*8 for a,n in m.reads)


@pytest.mark.parametrize('fault',['unaligned','end_before_start','capacity_before_end','capacity_budget'])
def test_malformed_geometry_and_finite_allocation_ceiling_still_refuse(fault):
    m,*_=fixture();s=bound(m);start=m.allocate(16);first,last,capacity=start,start+8,start+16
    if fault=='unaligned':first+=1
    elif fault=='end_before_start':last=start-8
    elif fault=='capacity_before_end':capacity=start
    elif fault=='capacity_budget':capacity=start+(candidate.CAPACITY_LIMIT+1)*8
    m.put(m.primary+0xc8,struct.pack('<QQQ',first,last,capacity))
    with pytest.raises(ValueError,match='vector geometry or reader budget'):s.reciprocal_score()


def test_candidate_method_only_changes_the_two_vector_bound_calls():
    old=ast.parse(textwrap.dedent(inspect.getsource(state.StateSource.reciprocal_score))).body[0]
    new=ast.parse(Path(candidate.__file__).read_text())
    method=next(n for n in ast.walk(new)if isinstance(n,ast.FunctionDef)and n.name=='reciprocal_score')
    class Normalize(ast.NodeTransformer):
        def visit_Call(self,node):
            if isinstance(node.func,ast.Attribute)and node.func.attr=='bounds':
                node.func=ast.Attribute(value=ast.Name(id='self',ctx=ast.Load()),attr='_reciprocal_used_bounds',ctx=ast.Load())
                node.args=node.args[:1]
            return self.generic_visit(node)
    assert ast.dump(Normalize().visit(old),include_attributes=False)==ast.dump(method,include_attributes=False)
