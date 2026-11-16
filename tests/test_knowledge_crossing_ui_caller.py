"""Original UI prefix plus original Crossing Range/H; no game or UI reads."""
from _knowledge_stream_fixture import native_stream_transport
import hashlib
import struct

import pytest

from fm_live_mcp import knowledge_crossing_ui_caller as source
from test_knowledge_person_ui_caller import memory as passing_ui_memory,native_ui_selection
from test_knowledge_passing_state import low_K,report,full_subject_contract
from test_knowledge_context_score_source import SyntheticBridge
from _knowledge_state_native import execute


def memory():
    m=passing_ui_memory()
    catalog=source.crossing.state.catalog
    for rva,n,digest in catalog.NATIVE_GUARDS:
        raw=m.disk(rva,n);assert hashlib.sha256(raw).hexdigest()==digest;m.put(m.base+rva,raw)
    for name,_,rva in catalog.FIELDS:m.put(m.base+rva,m.disk(rva,len(name)+1))
    for rva,value in source.crossing.state.thresholds.TABLE_BRANCHES:m.put(m.base+rva,bytes([value]))
    m.put(m.primary+0x157,b'\x0c')
    return m


@pytest.mark.parametrize('case',['none','club_first','club_null_assessor','alternate_reverse','alternate_range','alternate_negative','alternate_assessor','crossing_specific_unknown'])
def test_original_UI_report_prefix_and_original_Crossing_range(case):
    m=memory();low_K(m);expected=0
    if case=='club_first':
        expected=report(m,40,m.human_person);m.vec(m.human+0x110,[expected]);m.vec(m.human+0x128,[report(m,100)])
    elif case=='club_null_assessor':
        m.vec(m.human+0x110,[report(m,100)]);expected=report(m,40);m.vec(m.human+0x128,[expected])
    elif case=='alternate_reverse':
        first=report(m,40);expected=report(m,100);m.vec(m.human+0x128,[first,expected])
    elif case!='none':
        score=128 if case=='alternate_negative' else 20 if case=='crossing_specific_unknown' else 40
        expected=report(m,score,m.human_person if case=='alternate_assessor' else 0)
        m.vec(m.human+0x128,[expected])
        if case=='crossing_specific_unknown':m.put(m.primary+0x268,b'\3')
    owner=source.CrossingUiCallerSource(SyntheticBridge(m),'synthetic',m.person,m.person_ref,'Private Coach',11)
    assert (owner.ui_report() or 0)==expected
    native_row,assessor,_,_=native_ui_selection(m)
    assert native_row==expected
    m.blocked=[(m.primary+0x15e,m.primary+0x15f)]
    result=source.collect(SyntheticBridge(m),'synthetic',subject_person=m.person,
        subject_identity=m.person_ref,coach_name='Private Coach')
    output=m.allocate(8)
    extra=source.inherited.NATIVE_GUARDS+source.inherited.inherited.NATIVE_GUARDS+source.crossing.inherited.NATIVE_GUARDS+source.crossing.state.thresholds.NATIVE_GUARDS
    _,raw,_,_,trace=execute(m,0x2386eac,[m.record,output,m.primary,11,assessor,native_row,1],
        score_pointer=output,output_width=3,extra=extra)
    low,high,_=struct.unpack('bbb',raw);state=result['value']['state']
    expected_value=({'state':'unknown'}if low==high==-1 else{'state':'exact','value':low}if state=='exact'
        else{'state':'range','minimum':low,'maximum':high})
    assert result['value']==expected_value
    assert state==('unknown'if case in('none','alternate_negative','crossing_specific_unknown')else'exact'if case=='alternate_reverse'else'range')
    assert result['manager_knowledge_verified']is False and result['rendered_ui_verified']is False


def test_Crossing_UI_report_selection_occurs_even_before_own_context_early_return():
    m=memory();full_subject_contract(m)
    row=report(m,40);m.vec(m.human+0x128,[row])
    owner=source.CrossingUiCallerSource(SyntheticBridge(m),'synthetic',m.person,m.person_ref,'Private Coach',11)
    assert owner.permitted()=={'state':'exact','value':12}
    assert owner.assessment_record==row and owner.assessment_selected
