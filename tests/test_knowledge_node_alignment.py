"""Causal four-byte FOW node controls, including complete original H/Range."""
from _knowledge_stream_fixture import native_stream_transport
import hashlib
import struct

import pytest

from fm_live_mcp import knowledge_passing_state as state,knowledge_person_ui_caller as ui
from fm_live_mcp import knowledge_retained_person as retained
from test_knowledge_passing_state import memory,low_K,run
from test_knowledge_person_ui_caller import memory as ui_memory
from test_knowledge_passing_view import assert_public_shape
from test_knowledge_context_score_source import SyntheticBridge
from _knowledge_state_native import execute


def nodes(m,scores):
    result=[]
    for raw in scores:
        at=m.allocate(16)+4
        assert at%8==4
        m.put(at,struct.pack('<IIB',m.person_ref[0],2001,raw)+bytes(3));result.append(at)
    m.vec(m.primary+0xc8,result);m.vec(m.record,result)
    return result


@pytest.mark.parametrize('combined',[False,True])
def test_four_byte_nodes_match_original_H_and_preserve_last_match(combined):
    m=memory(combined);low_K(m);addresses=nodes(m,[100,40])
    before=dict(m.cells);actual=run(m)
    assert (actual['native_state'],actual['private_score'])==(1,40)
    output=m.allocate(8)
    native,score,reads,writes,instructions=execute(m,0x23871f0,[m.record,m.person,18,output,0,1],score_pointer=output)
    assert native==1 and score==40 and (addresses[-1]+8,1) in reads
    assert all(m.cells[k]==v for k,v in before.items())


@pytest.mark.parametrize('raw,expected_state',[(0,0),(38,0),(39,1),(76,1),(77,2),(127,2),(128,0),(255,0)])
def test_signed_threshold_boundaries_with_four_byte_nodes_match_original(raw,expected_state):
    m=memory();low_K(m);nodes(m,[raw])
    actual=run(m);output=m.allocate(8)
    native,_,_,_,_=execute(m,0x23871f0,[m.record,m.person,18,output,0,1],score_pointer=output)
    assert actual['native_state']==native==expected_state


def test_ui_endpoint_view_matches_original_Range_without_exposing_native_transport():
    m=ui_memory();low_K(m);nodes(m,[100,40]);before=dict(m.cells)
    actual=ui.collect(SyntheticBridge(m),'synthetic',subject_person=m.person,subject_identity=m.person_ref,coach_name='Private Coach')
    assert_public_shape(actual);assert actual['value']['state']=='range'
    output=m.allocate(8)
    _,raw,_,_,_=execute(m,0x2386eac,[m.record,output,m.primary,18,0,0,1],score_pointer=output,output_width=3,
        extra=ui.inherited.inherited.NATIVE_GUARDS+ui.inherited.NATIVE_GUARDS+retained.NATIVE_GUARDS+ui.inherited.inherited.view.NATIVE_GUARDS)
    lower,upper,_=struct.unpack('bbb',raw)
    assert actual['value']=={'state':'range','minimum':lower,'maximum':upper}
    assert all(m.cells[k]==v for k,v in before.items())


@pytest.mark.parametrize('fault',['two_byte','null_visited','owner_vector','wrong_ordinal','wrap'])
def test_node_alignment_fix_keeps_invalid_and_unowned_sources_unavailable(fault):
    m=memory();low_K(m);row,=nodes(m,[40])
    if fault=='two_byte':m.vec(m.primary+0xc8,[row+2])
    if fault=='null_visited':m.vec(m.primary+0xc8,[0])
    if fault=='owner_vector':m.vec(m.record,[0])
    if fault=='wrong_ordinal':m.put(row,struct.pack('<I',1))
    if fault=='wrap':m.vec(m.primary+0xc8,[(1<<64)-4])
    actual=run(m)
    assert actual['native_state'] is None and actual['unavailable_reason']
