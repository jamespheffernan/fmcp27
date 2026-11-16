"""Complete final relation/main/K/H/Range comparisons in owned synthetic RAM."""
from _knowledge_stream_fixture import native_stream_transport
import struct
import pytest
from fm_live_mcp import knowledge_person_selector as selector,knowledge_retained_person as retained
from test_knowledge_retained_selector import memory as retained_memory,source
from test_knowledge_relation_mask_source import native_node
from test_knowledge_passing_state import report
from test_knowledge_passing_view import assert_public_shape
from test_knowledge_context_score_source import SyntheticBridge
from _knowledge_state_native import execute


def memory():
    m=retained_memory();node=native_node(m,0x55bd358,m.external_team);m.put(node+0x48,struct.pack('<II',10,40));m.vec(m.nodes,[node])
    return m


def compare(m,expected):
    m.blocked=[(m.primary+0x148,m.primary+0x18d)];m.reads.clear();s=source(m);assert s.relation_mask()==expected;s.verify()
    consumed={p for at,n in m.reads for p in range(at,at+n)}
    value,_,reads,_,code=execute(m,0x20ee608,[m.human,m.primary],extra=selector.inherited.NATIVE_GUARDS+selector.NATIVE_GUARDS+retained.NATIVE_GUARDS)
    assert value==expected
    assert all(p in consumed for at,n in reads for p in range(at,at+n)),[(hex(at),n)for at,n in reads if not all(p in consumed for p in range(at,at+n))]
    assert 0x20efa74 in code and 0x17bb4c0 in code


def test_absent_club_assessment_has_native_mask0e_without_invented_zero_score():
    compare(memory(),0x0e)


@pytest.mark.parametrize('raw,expected',[(0,4),(40,4),(41,14),(60,14),(61,30),(70,30),(71,62),(80,62),
 (81,126),(90,126),(91,254),(99,254),(100,510),(101,254),(127,254),(128,4),(255,4)])
def test_native_assessment_signed_thresholds_exact100_and_above100(raw,expected):
    m=memory();row=report(m,raw,m.human_person);m.vec(m.human+0x110,[row]);compare(m,expected)


def test_final_fanout_excludes_alternate_raw_UID_assessment_fallback():
    m=memory();alternate=report(m,100);m.vec(m.human+0x128,[alternate]);compare(m,14)


def test_first_sorted_club_assessment_wins_not_maximum():
    m=memory();a=report(m,40,m.human_person);b=report(m,100,m.human_person);m.vec(m.human+0x110,[a,b]);compare(m,4)


@pytest.mark.parametrize('scalar,state',[(8000,'exact'),(6500,'range')])
def test_new_relation_path_composes_into_complete_original_K_H_and_permitted_Range(scalar,state):
    m=memory();m.put(m.primary+0x25a,struct.pack('<h',scalar));m.reads.clear()
    actual=selector.collect(SyntheticBridge(m),'synthetic',subject_person=m.person,subject_identity=m.person_ref,coach_name='Private Coach')
    assert actual['value']['state']==state;assert_public_shape(actual)
    consumed={p for at,n in m.reads for p in range(at,at+n)};output=m.allocate(8)
    _,raw,reads,_,code=execute(m,0x2386eac,[m.record,output,m.primary,18,0,0,1],score_pointer=output,output_width=3,
        extra=selector.inherited.NATIVE_GUARDS+selector.NATIVE_GUARDS+retained.NATIVE_GUARDS+selector.inherited.view.NATIVE_GUARDS)
    low,high,_=struct.unpack('bbb',raw)
    assert actual['value']==({'state':'exact','value':low}if state=='exact'else {'state':'range','minimum':low,'maximum':high})
    assert 0x2386548 in code and 0x20efa74 in code and 0x17bb4c0 in code
    assert all(p in consumed for at,n in reads for p in range(at,at+n))


@pytest.mark.parametrize('consumer',['relation','H'])
def test_large_unused_assessment_capacity_keeps_native_used_entries(consumer):
    m=memory();row=report(m,40,m.human_person);reserved=m.allocate(6316*8);m.q(reserved,row)
    m.put(m.human+0x110,struct.pack('<QQQ',reserved,reserved+8,reserved+6316*8))
    if consumer=='relation':compare(m,4)
    else:
        from test_knowledge_passing_view import assert_public_shape
        m.put(m.primary+0x25a,struct.pack('<h',6500));actual=selector.collect(SyntheticBridge(m),'synthetic',subject_person=m.person,subject_identity=m.person_ref,coach_name='Private Coach')
        assert actual['value']['state']=='range';assert_public_shape(actual)
        output=m.allocate(8);_,raw,_,_,_=execute(m,0x2386eac,[m.record,output,m.primary,18,0,0,1],score_pointer=output,output_width=3,
            extra=selector.inherited.NATIVE_GUARDS+selector.NATIVE_GUARDS+retained.NATIVE_GUARDS+selector.inherited.view.NATIVE_GUARDS)
        low,high,_=struct.unpack('bbb',raw);assert actual['value']=={'state':'range','minimum':low,'maximum':high}


def test_assessment_used_entry_limit_is_still_enforced():
    m=memory();reserved=m.allocate(4097*8);m.put(m.human+0x110,struct.pack('<QQQ',reserved,reserved+4097*8,reserved+4097*8))
    with pytest.raises(selector.core.SourceUnavailable,match='used-entry reader budget'):source(m).relation_mask()


@pytest.mark.parametrize('raw',[40,100])
def test_fixed_native_null_report_mode_ignores_alternate_assessment(raw):
    state='range'
    m=memory();m.put(m.primary+0x25a,struct.pack('<h',6500));row=report(m,raw)
    reserved=m.allocate(6316*8);m.q(reserved,row);m.put(m.human+0x128,struct.pack('<QQQ',reserved,reserved+8,reserved+6316*8))
    m.blocked=[(m.human+0x128,m.human+0x140)]
    actual=selector.collect(SyntheticBridge(m),'synthetic',subject_person=m.person,subject_identity=m.person_ref,coach_name='Private Coach')
    assert actual['value']['state']==state;assert_public_shape(actual)
    output=m.allocate(8);_,transport,_,_,_=execute(m,0x2386eac,[m.record,output,m.primary,18,0,0,1],score_pointer=output,output_width=3,
        extra=selector.inherited.NATIVE_GUARDS+selector.NATIVE_GUARDS+retained.NATIVE_GUARDS+selector.inherited.view.NATIVE_GUARDS)
    low,high,_=struct.unpack('bbb',transport)
    assert actual['value']==({'state':'exact','value':low}if state=='exact'else {'state':'range','minimum':low,'maximum':high})



def test_fixed_null_report_mode_keeps_unknown_without_reading_hidden_attribute_or_alternate():
    from test_knowledge_passing_state import low_K
    m=memory();low_K(m);row=report(m,100);m.vec(m.human+0x128,[row]);m.blocked=[(m.human+0x128,m.human+0x140),(m.primary+0x148,m.primary+0x18d)]
    actual=selector.collect(SyntheticBridge(m),'synthetic',subject_person=m.person,subject_identity=m.person_ref,coach_name='Private Coach')
    assert actual['value']=={'state':'unknown'};assert_public_shape(actual)
    output=m.allocate(8);_,transport,_,_,_=execute(m,0x2386eac,[m.record,output,m.primary,18,0,0,1],score_pointer=output,output_width=3,
        extra=selector.inherited.NATIVE_GUARDS+selector.NATIVE_GUARDS+retained.NATIVE_GUARDS+selector.inherited.view.NATIVE_GUARDS)
    assert struct.unpack('bbb',transport)[:2]==(-1,-1)
