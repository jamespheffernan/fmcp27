"""All47 private fields against original UI selection and complete Range/H."""
from _knowledge_stream_fixture import native_stream_transport
import hashlib
import json
import struct

import pytest

from fm_live_mcp import knowledge_attribute_ui_caller as source
from test_knowledge_person_ui_caller import memory as passing_ui_memory,native_ui_selection
from test_knowledge_passing_state import full_subject_contract,low_K,report
from test_knowledge_context_score_source import SyntheticBridge
from _knowledge_state_native import execute


def memory():
    m=passing_ui_memory()
    for rva,n,digest in source.catalog.NATIVE_GUARDS+source.native_thresholds.NATIVE_GUARDS:
        raw=m.disk(rva,n);assert hashlib.sha256(raw).hexdigest()==digest;m.put(m.base+rva,raw)
    for name,_,rva in source.catalog.FIELDS:m.put(m.base+rva,m.disk(rva,len(name)+1))
    for field,(_,offset,_)in enumerate(source.catalog.FIELDS):m.put(m.primary+0x148+offset,bytes([field%20+1]))
    return m


@pytest.mark.parametrize('field',range(47))
@pytest.mark.parametrize('route',['exact','unknown','range'])
def test_every_field_matches_original_UI_prefix_and_full_range_H(field,route):
    m=memory();assessment=0
    if route=='exact':full_subject_contract(m)
    else:
        low_K(m)
        if route=='range':assessment=report(m,40);m.vec(m.human+0x128,[assessment])
    if route=='unknown':m.blocked=[(m.primary+0x148,m.primary+0x18d)]
    result=source.collect(SyntheticBridge(m),'synthetic',subject_person=m.person,
        subject_identity=m.person_ref,field=field,coach_name='Private Coach')
    selected,assessor,_,_=native_ui_selection(m)
    assert selected==assessment
    output=m.allocate(8)
    extra=(source.inherited.NATIVE_GUARDS+source.inherited.inherited.NATIVE_GUARDS+
        source.inherited.inherited.inherited.view.NATIVE_GUARDS+source.native_thresholds.NATIVE_GUARDS)
    _,raw,_,_,trace=execute(m,0x2386eac,[m.record,output,m.primary,field,assessor,selected,1],
        score_pointer=output,output_width=3,extra=extra)
    low,high,_=struct.unpack('bbb',raw)
    expected=({'state':'unknown'}if route=='unknown'else{'state':'exact','value':low}if route=='exact'
        else{'state':'range','minimum':low,'maximum':high})
    assert result['value']==expected and result['native_field_id']==field
    assert result['field']==source.catalog.FIELDS[field][0]
    assert result['manager_knowledge_verified']is False
    assert result['complete_search_population']is False and result['rendered_ui_verified']is False
    text=json.dumps(result)
    assert all(word not in text for word in('getter','private_score','native_values','primary','rawhex'))


@pytest.mark.parametrize('field',[-1,47,True,11.0,None])
def test_unsupported_fields_fail_before_getter_or_context(field):
    m=memory();m.blocked=[(m.primary+0x148,m.primary+0x18d)]
    with pytest.raises(source.inherited.core.SourceUnavailable,match='ordinary attribute'):
        source.collect(SyntheticBridge(m),'synthetic',subject_person=m.person,
            subject_identity=m.person_ref,field=field,coach_name='Private Coach')


def test_old_passing_offset_seed_diverges_from_original_field_one_range():
    m=memory();low_K(m);row=report(m,40);m.vec(m.human+0x128,[row])
    owner=source.AttributeUiCallerSource(SyntheticBridge(m),'synthetic',m.person,m.person_ref,'Private Coach',1)
    native_state,score,_=owner.state()
    assert native_state==1
    inputs=dict(age=owner.native_age(owner.subject),person_index=owner.subject.person.identity[0],
        private_knowledge_score=score,assessor_bytes=owner.assessor_bytes())
    old=source.ranges.permitted_passing_value(source.ranges.native_passing_projection(owner.getter(),1,**inputs))
    corrected=owner.permitted();output=m.allocate(8)
    extra=(source.inherited.NATIVE_GUARDS+source.inherited.inherited.NATIVE_GUARDS+
        source.inherited.inherited.inherited.view.NATIVE_GUARDS+source.native_thresholds.NATIVE_GUARDS)
    _,raw,_,_,_=execute(m,0x2386eac,[m.record,output,m.primary,1,0,row,1],
        score_pointer=output,output_width=3,extra=extra)
    low,high,_=struct.unpack('bbb',raw)
    assert corrected=={'state':'range','minimum':low,'maximum':high}
    assert old!=corrected


def test_generic_field_last_callback_getter_mutation_refuses():
    first=memory();full_subject_contract(first);baseline=SyntheticBridge(first)
    source.collect(baseline,'synthetic',subject_person=first.person,subject_identity=first.person_ref,field=46,coach_name='Private Coach')
    m=memory();full_subject_contract(m);bridge=SyntheticBridge(m)
    offset=source.catalog.field(46)['primary_offset']
    def mutate(count):
        if count==baseline.lifetimes:m.put(m.primary+offset,b'\x14')
    bridge.on_current=mutate
    with pytest.raises(ValueError,match='changed'):
        source.collect(bridge,'synthetic',subject_person=m.person,subject_identity=m.person_ref,field=46,coach_name='Private Coach')
    assert bridge._reader is None
