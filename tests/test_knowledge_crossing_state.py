"""Crossing H/K source against full original H and callees, without attributes."""
from _knowledge_stream_fixture import native_stream_transport
import hashlib

import pytest

from fm_live_mcp import knowledge_crossing_state as source
from fm_live_mcp import knowledge_context_score_source as context
from test_knowledge_passing_state import memory as passing_memory,report,low_K,full_subject_contract
from test_knowledge_context_score_source import SyntheticBridge
from _knowledge_state_native import execute


def memory(combined=False):
    m=passing_memory(combined)
    for rva,n,digest in source.catalog.NATIVE_GUARDS:
        raw=m.disk(rva,n);assert hashlib.sha256(raw).hexdigest()==digest;m.put(m.base+rva,raw)
    for name,_,rva in source.catalog.FIELDS:m.put(m.base+rva,m.disk(rva,len(name)+1))
    for rva,value in source.thresholds.TABLE_BRANCHES:m.put(m.base+rva,bytes([value]))
    m.blocked=[(m.primary+0x148,m.primary+0x18d)]
    return m


def collect(m,bridge=None):
    return source.collect(bridge or SyntheticBridge(m),'synthetic',subject_person=m.person,
        subject_identity=m.person_ref,coach_name='Private Coach')


@pytest.mark.parametrize('combined',[False,True])
@pytest.mark.parametrize('category,assessment',[ (0,0),(0,39),(0,77),(3,20),(3,36),(3,74),(5,22),(5,23),(5,61),(1,100),(128,100)])
def test_crossing_H_state_and_shared_K_match_full_original(combined,category,assessment):
    m=memory(combined);low_K(m);m.put(m.primary+0x268,bytes([category]))
    row=report(m,assessment);m.vec(m.human+0x128,[row])
    result=collect(m)
    selected=0
    if source.thresholds.crossing_thresholds(category)[0]:
        selected,_,_,_,_=execute(m,0x12da3d0,[m.human,m.primary,0,0])
        assert selected==row
    output=m.allocate(8)
    native,_,reads,writes,trace=execute(m,0x23871f0,[m.record,m.person,11,output,selected,1],score_pointer=output,
        extra=source.thresholds.NATIVE_GUARDS)
    assert result['value']=={'state':('unknown','range','exact')[native]}
    assert 0x14e98e4 in trace
    assert not any(a<m.primary+0x18d and a+n>m.primary+0x148 for a,n in reads)
    assert result['field_value_evaluated']is False and result['person_ui_caller_evaluated']is False
    assert result['manager_knowledge_verified']is False
    assert 'private_score'not in result


@pytest.mark.parametrize('combined',[False,True])
def test_crossing_own_context_is_exact_without_attribute_or_assessment_read(combined):
    m=memory(combined);full_subject_contract(m)
    m.blocked.append((m.human+0x110,m.human+0x140))
    assert collect(m)['value']=={'state':'exact'}


def test_passing_entry_point_does_not_accept_crossing_after_hook_extraction():
    m=memory()
    with pytest.raises(source.core.SourceUnavailable,match='Only the proved Passing18'):
        context.collect(SyntheticBridge(m),'synthetic',subject_person=m.person,
            subject_identity=m.person_ref,coach_name='Private Coach',field=11)


def test_last_context_callback_subject_mutation_rejects_crossing_state():
    baseline=memory();bridge=SyntheticBridge(baseline);collect(baseline,bridge)
    m=memory();changed=SyntheticBridge(m)
    def mutate(count):
        if count==bridge.lifetimes:m.identity(m.person,m.person_ref[0],m.person_ref[1]+1,m.person_ref[2])
    changed.on_current=mutate
    with pytest.raises(ValueError,match='changed|differs'):collect(m,changed)
    assert changed._reader is None
