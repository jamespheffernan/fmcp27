"""Private permitted endpoints and hidden-byte boundary; no public-mode claim."""
from _knowledge_stream_fixture import native_stream_transport
import hashlib
import json
import struct

import pytest
from fm_live_mcp import knowledge_passing_view as view
from test_knowledge_passing_state import memory as state_memory,full_subject_contract,low_K,report
from test_knowledge_context_score_source import SyntheticBridge


def memory(combined=False):
    m=state_memory(combined)
    for rva,n,digest in view.NATIVE_GUARDS:
        raw=m.disk(rva,n);assert hashlib.sha256(raw).hexdigest()==digest;m.put(m.base+rva,raw)
    for person in (m.person,m.human_person):
        table=int.from_bytes(m.read(person,8),'little');rva=table-m.base
        target=int.from_bytes(m.disk(rva+0x658,8),'little')&0xffffffff
        m.q(table+0x658,m.base+target);m.put(table-0x668,m.disk(rva-0x668,8))
    m.put(m.primary+0x15e,b'\x0a');m.put(m.primary+0x270,b'\0')
    m.put(m.common+0x58,struct.pack('<HH',200,2000));m.put(m.base+0x56d4951,b'\0')
    return m


def run(m,b=None):
    return view.collect(b or SyntheticBridge(m),'synthetic',subject_person=m.person,
                        subject_identity=m.person_ref,coach_name='Private Coach')


def range_report(m,score=40,assessor=0,club=False):
    low_K(m);row=report(m,score,assessor)
    m.vec(m.human+(0x110 if club else 0x128),[row]);return row


def assert_public_shape(r):
    assert set(r)=={'scope','field','native_field_id','observer_identity','subject_identity',
                    'current_date','value','non_atomic','assessment_freshness'}
    v=r['value']
    assert set(v)=={'state','value'}if v['state']=='exact'else set(v)=={'state','minimum','maximum'}if v['state']=='range'else set(v)<= {'state','reason'}
    assert r['field']=='Passing' and r['native_field_id']==18
    encoded=json.dumps(r)
    for forbidden in ('getter','private_score','native_values','native_assessment','raw_code','rawhex','debug','primary'):
        assert forbidden not in encoded


@pytest.mark.parametrize('combined',[False,True])
def test_exact_own_context_emits_only_verified_exact_value(combined):
    m=memory(combined);full_subject_contract(m);r=run(m)
    assert r['value']=={'state':'exact','value':10};assert_public_shape(r)


def test_unknown_never_reads_any_subject_attribute_for_all256_hidden_bytes():
    m=memory();low_K(m);m.blocked=[(m.primary+0x148,m.primary+0x18d)];expected=None
    for raw in range(256):
        m.put(m.primary+0x15e,bytes([raw]));r=run(m)
        assert r['value']=={'state':'unknown'};assert_public_shape(r)
        if expected is None:expected=r
        assert r==expected


@pytest.mark.parametrize('combined',[False,True])
def test_range_keeps_only_native_endpoints_and_remains_range(combined):
    m=memory(combined);range_report(m);r=run(m)
    assert r['value']=={'state':'range','minimum':8,'maximum':12};assert_public_shape(r)


@pytest.mark.parametrize('score',[39,40,50,76])
@pytest.mark.parametrize('judgements',[None,(0,0),(50,60),(100,100)])
def test_assessor_rating_source_is_separate_from_subject_values(score,judgements):
    m=memory();assessor=m.human_person if judgements else 0
    if judgements:m.put(m.human+0x2c,bytes(judgements))
    range_report(m,score,assessor,club=bool(assessor));r=run(m)
    assert r['value']['state']=='range';assert_public_shape(r)


@pytest.mark.parametrize('combined',[False,True])
def test_actual_null_or_combined_NON_PLAYER_assessor_cast_is_typed(combined):
    m=memory(combined);m.put(m.primary+(0x278 if combined else 0)+0x2c,b'\x32\x32')
    range_report(m,40,m.person);r=run(m)
    assert r['value']['state']=='range';assert_public_shape(r)


def test_unavailable_native_state_is_not_unknown_and_never_copies_exception_numbers():
    m=memory();low_K(m);row=m.allocate(16);m.put(row,struct.pack('<IIB',1,2001,100));m.vec(m.primary+0xc8,[row]);m.vec(m.record,[row])
    r=run(m);assert r['value']=={'state':'unavailable','reason':'unavailable_source'};assert_public_shape(r)


def test_zero_and_out_of_domain_exact_values_are_withheld():
    m=memory();full_subject_contract(m)
    for raw in (0,21,100,127,128,255):
        m.put(m.primary+0x15e,bytes([raw]));r=run(m)
        assert r['value']=={'state':'unavailable','reason':'unsupported_native_projection'};assert_public_shape(r)


def test_invalid_native_interval_is_not_repaired_or_leaked():
    m=memory();range_report(m);m.put(m.primary+0x15e,b'\0')
    r=run(m);assert r['value']['state']=='unavailable';assert_public_shape(r)


@pytest.mark.parametrize('field',['getter','scale','assessor','DOB'])
def test_final_lifetime_mutation_rejects_private_consumed_projection_inputs(field):
    m=memory();range_report(m,40,m.human_person,club=True);b=SyntheticBridge(m);seen=False
    addresses={'getter':(m.primary+0x15e,b'\x0b'),'scale':(m.primary+0x270,b'\x80'),
               'assessor':(m.human+0x2c,b'\x64'),'DOB':(m.common+0x58,struct.pack('<HH',200,2010))}
    at,raw=addresses[field]
    def observe(a,n):
        nonlocal seen
        if a<=at<a+n:seen=True
    def mutate(n):
        if seen:m.put(at,raw)
    m.on_read=observe;b.on_current=mutate
    with pytest.raises(ValueError,match='changed'):run(m,b)


@pytest.mark.parametrize('which',['assessor_dispatch','assessor_displacement'])
def test_unknown_assessor_dispatch_stays_unavailable(which):
    m=memory();range_report(m,40,m.human_person,club=True);table=int.from_bytes(m.read(m.human_person,8),'little')
    m.q(table+(0x658 if which=='assessor_dispatch'else -0x668),0)
    r=run(m);assert r['value']=={'state':'unavailable','reason':'unavailable_source'}


def literal_range(m,assessment=0,assessor=0):
    from _knowledge_state_native import execute
    output=m.allocate(8)
    _,raw,reads,writes,code=execute(m,0x2386eac,[m.record,output,m.primary,18,assessor,assessment,1],
                                  score_pointer=output,output_width=3,extra=view.NATIVE_GUARDS)
    return struct.unpack('<bbb',raw),reads,code


@pytest.mark.parametrize('combined',[False,True])
@pytest.mark.parametrize('route',['exact','unknown','range','human_assessor','subject_assessor'])
def test_whole_original_range_H_and_reached_callees_match_permitted_view(combined,route):
    m=memory(combined);assessment=assessor=0
    if route=='exact':full_subject_contract(m)
    elif route=='unknown':low_K(m)
    else:
        assessor=m.human_person if route=='human_assessor'else m.person if route=='subject_assessor'else 0
        assessment=range_report(m,40,assessor,club=route=='human_assessor')
    m.reads.clear();actual=run(m);consumed={a+i for a,n in m.reads for i in range(n)}
    raw,reads,code=literal_range(m,assessment,assessor)
    if route=='unknown':
        assert actual['value']=={'state':'unknown'} and raw[:2]==(-1,-1)
        # The original hidden third byte is deliberately absent from the typed
        # source; only this synthetic VM executes its unused native getter.
        assert all(a+i in consumed for a,n in reads for i in range(n)if not m.primary+0x148<=a+i<m.primary+0x18d and a+i!=m.primary+0x270)
    else:
        assert all(a+i in consumed for a,n in reads for i in range(n))
        expected={'state':'exact','value':raw[0]}if route=='exact'else {'state':'range','minimum':raw[0],'maximum':raw[1]}
        assert actual['value']==expected
    assert_public_shape(actual)


@pytest.mark.parametrize('ordinal',range(7))
def test_all_original_signed_remainder_routes_match_endpoints(ordinal):
    m=memory();m.person_ref=(ordinal,1001,1002);m.identity(m.person,*m.person_ref);m.identity(m.human_person,7,2001,2002)
    slots=[0]*8;slots[ordinal]=m.person;slots[7]=m.human_person;m.vec(m.tables['people'][1],slots)
    row=range_report(m);actual=run(m);raw,_,_=literal_range(m,row,0)
    assert actual['value']=={'state':'range','minimum':raw[0],'maximum':raw[1]}


def test_equal_native_range_endpoints_never_promote_to_exact():
    m=memory();ordinal=6;m.person_ref=(ordinal,1001,1002);m.identity(m.person,*m.person_ref);m.identity(m.human_person,7,2001,2002)
    slots=[0]*8;slots[ordinal]=m.person;slots[7]=m.human_person;m.vec(m.tables['people'][1],slots)
    row=range_report(m,76);m.put(m.primary+0x15e,b'\x14');actual=run(m);raw,_,_=literal_range(m,row,0)
    assert raw[:2]==(20,20) and actual['value']=={'state':'range','minimum':20,'maximum':20}


@pytest.mark.parametrize('mode',[0,128])
def test_all256_native_getter_bytes_match_private_conversion(mode):
    from _knowledge_state_native import execute
    m=memory();m.put(m.primary+0x270,bytes([mode]))
    for raw in range(256):
        m.put(m.primary+0x15e,bytes([raw]))
        literal,*_=execute(m,0xd19eb0,[m.primary,18],extra=view.NATIVE_GUARDS)
        assert view.ranges.passing_getter(raw,mode)==view.core._signed(literal,32)
