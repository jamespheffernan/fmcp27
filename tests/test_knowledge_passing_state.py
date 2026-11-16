"""Private typed state controls; no live, public mode or attribute values."""
from _knowledge_stream_fixture import native_stream_transport
from contextlib import contextmanager
import hashlib
import struct

import pytest
from fm_live_mcp import knowledge_passing_state as state
from test_knowledge_context_score_source import Memory,SyntheticBridge


def memory(combined=False):
    m=Memory(combined)
    for rva,size,digest in state.NATIVE_GUARDS:
        raw=m.disk(rva,size);assert hashlib.sha256(raw).hexdigest()==digest;m.put(m.base+rva,raw)
    table=m.read(m.primary,8);at=int.from_bytes(table,'little')+0x518
    m.q(at,m.base+0xd5c4bc)
    return m


def run(m,b=None):
    return state.collect(b or SyntheticBridge(m),'synthetic',subject_person=m.person,
                         subject_identity=m.person_ref,coach_name='Private Coach')


def report(m,score,assessor=0,subject=None):
    row=m.allocate(0x48);m.q(row,m.person if subject is None else subject);m.q(row+8,assessor)
    m.put(row+0x3f,bytes([score]));return row


def full_subject_contract(m):
    # The inherited fixture already seeds FULL_CONTRACT relocated metadata for
    # the owner's contract. Reuse that table rather than reseeding overlapping
    # native vtable/RTTI fixture regions after its final metadata restoration.
    at=m.allocate(0x100)
    m.q(at,m.base+state.inherited.world.TYPES['full_contract'][0])
    m.q(at+8,m.person);m.q(at+0x10,m.team);m.q(at+0x18,m.team)
    m.put(at+0x26,b'\x02');m.q(m.common+0x78,at);m.main=at
    return at


def low_K(m):
    m.put(m.common+0x102,struct.pack('<H',128))


@pytest.mark.parametrize('combined',[False,True])
def test_own_context_is_exact_without_K_getter_or_assessment_sources(combined):
    m=memory(combined)
    full_subject_contract(m)
    m.blocked=[(m.primary+0x148,m.primary+0x18d),(m.human+0x110,m.human+0x140)]
    r=run(m)
    assert (r['native_state'],r['private_score'],r['route'])==(2,0,'own_context')
    assert not r['assessment_selected'] and not r['attribute_getter_read']


@pytest.mark.parametrize('combined',[False,True])
def test_trial_own_context_does_not_bypass_real_K_threshold(combined):
    m=memory(combined);r=run(m)
    assert (r['native_state'],r['private_score'],r['route'])==(2,90,'threshold')
    assert r['assessment_selected'] and r['native_assessment_selection'] is None


@pytest.mark.parametrize('value,expected',[(0,0),(38,0),(39,1),(76,1),(77,2),(127,2),(128,0),(255,0)])
def test_alternate_assessment_signed_byte_is_used_without_invented_freshness(value,expected):
    m=memory();low_K(m);row=report(m,value);m.vec(m.human+0x128,[row]);r=run(m)
    assert r['native_state']==expected
    assert r['private_score']==max(0,value if value<128 else value-256)
    assert r['native_assessment_selection']==row and r['assessment_selected']
    assert r['assessment_freshness']=='not_evaluated_by_native_selectors'


def test_reverse_assessment_order_not_maximum_and_no_assessor_requirement():
    m=memory();low_K(m);high=report(m,100);low=report(m,40);m.vec(m.human+0x128,[high,0,low]);r=run(m)
    assert r['native_assessment_selection']==low and (r['native_state'],r['private_score'])==(1,40)


def test_sorted_club_selector_precedes_alternate_and_preserves_physical_order():
    m=memory();low_K(m);first=report(m,40,m.human_person);second=report(m,100,m.human_person)
    alternate=report(m,120);m.vec(m.human+0x110,[first,second]);m.vec(m.human+0x128,[alternate]);r=run(m)
    assert r['native_assessment_selection']==first and (r['native_state'],r['private_score'])==(1,40)


def test_null_assessor_in_club_selector_falls_back_to_alternate():
    m=memory();low_K(m);first=report(m,100);last=report(m,39);m.vec(m.human+0x110,[first]);m.vec(m.human+0x128,[last]);r=run(m)
    assert r['native_assessment_selection']==last and r['native_state']==1


def test_reciprocal_uses_last_owned_match_and_preserves_signed_value():
    m=memory();low_K(m);nodes=[]
    for score in (100,40):
        row=m.allocate(16);m.put(row,struct.pack('<IIB',m.person_ref[0],2001,score));nodes.append(row)
    m.vec(m.primary+0xc8,nodes);m.vec(m.record,nodes);r=run(m)
    assert (r['native_state'],r['private_score'])==(1,40)


@pytest.mark.parametrize('fault',['node_ordinal','owner_vector','null_node'])
def test_wrong_reciprocal_provenance_is_unavailable_not_native_zero(fault):
    m=memory();low_K(m);row=m.allocate(16);m.put(row,struct.pack('<IIB',0,2001,40))
    m.vec(m.primary+0xc8,[row]);m.vec(m.record,[row])
    if fault=='node_ordinal':m.put(row,struct.pack('<I',1))
    elif fault=='owner_vector':m.vec(m.record,[])
    else:m.vec(m.primary+0xc8,[0])
    r=run(m);assert r['native_state'] is None and r['unavailable_reason']


@pytest.mark.parametrize('category',range(256))
def test_zero_threshold_categories_short_circuit_K_and_assessment(category):
    m=memory();m.put(m.primary+0x268,bytes([category]));low,high=state.ranges.passing_thresholds(category)
    if not low or not high:
        m.blocked=[(m.common+0x102,m.common+0x104),(m.human+0x110,m.human+0x140)]
    r=run(m)
    assert r['native_state']==(2 if low else 0)
    assert r['route']==('threshold'if low else'zero_threshold')


@pytest.mark.parametrize('flag,day,year',[(0,318,2030),(1,316,2030),(1,317,2030),(1,1,2029),(1,318,2030)])
def test_checked_national_auxiliary_is_local_and_read_only(flag,day,year):
    m=memory();full_subject_contract(m)
    m.q(m.primary+0x120,m.national);m.put(m.national+0xe2,bytes([flag]));m.put(m.national+0xb8,struct.pack('<HH',day,year))
    before=dict(m.cells);r=run(m);assert r['native_state']==2 and m.cells==before


def test_final_lifetime_drift_rejects_consumed_state_bytes():
    m=memory();b=SyntheticBridge(m)
    def changed(n):
        if n>=5:m.put(m.primary+0x268,b'\xff')
    b.on_current=changed
    with pytest.raises(ValueError,match='changed'):run(m,b)


@pytest.mark.parametrize('index',range(len(state.NATIVE_GUARDS)))
def test_new_native_state_and_selector_guards_reject(index):
    m=memory();rva,_,_=state.NATIVE_GUARDS[index];at=m.base+rva;m.put(at,bytes([m.read(at,1)[0]^1]))
    with pytest.raises(ValueError,match='(native|source).*changed'):run(m)



@pytest.mark.parametrize('case,expected', [('both_null',0),('national_null',2),('equal_nonnull',2)])
def test_auxiliary_equality_can_erase_own_context_and_is_not_a_generic_null_boost(case,expected):
    m=memory();full_subject_contract(m);low_K(m)
    m.q(m.primary+0x120,m.national);m.put(m.national+0xe2,b'\x01');m.put(m.national+0xb8,struct.pack('<HH',318,2030))
    holder=m.allocate(32);m.q(holder+0x10,m.owner_contract);m.q(m.human_common+0x80,holder)
    m.put(m.base+0x56d4993,b'\x01')
    if case=='both_null':m.q(m.club+0xd8,0);m.q(m.container+0x170,0)
    elif case=='national_null':m.q(m.container+0x170,0)
    before=dict(m.cells);r=run(m);assert r['native_state']==expected and m.cells==before


@pytest.mark.parametrize('combined',[False,True])
@pytest.mark.parametrize('route',['own','K','unknown','report_range','report_exact','stored_range','auxiliary_equal','auxiliary_null'])
def test_whole_original_H_and_all_reached_callees_match_without_result_stubs(combined,route):
    from _knowledge_state_native import native_state
    m=memory(combined);assessment=0
    if route=='own':full_subject_contract(m)
    elif route=='unknown':low_K(m)
    elif route.startswith('report'):
        low_K(m);assessment=report(m,40 if route=='report_range' else 77);m.vec(m.human+0x128,[assessment])
    elif route=='stored_range':
        low_K(m);row=m.allocate(16);m.put(row,struct.pack('<IIB',m.person_ref[0],2001,40));m.vec(m.primary+0xc8,[row]);m.vec(m.record,[row])
    elif route.startswith('auxiliary'):
        full_subject_contract(m);low_K(m);m.q(m.primary+0x120,m.national);m.put(m.national+0xe2,b'\x01');m.put(m.national+0xb8,struct.pack('<HH',318,2030))
        holder=m.allocate(32);m.q(holder+0x10,m.owner_contract);m.q(m.human_common+0x80,holder);m.put(m.base+0x56d4993,b'\x01')
        if route=='auxiliary_null':m.q(m.club+0xd8,0);m.q(m.container+0x170,0)
    m.reads.clear()
    result=run(m);assert result['native_state'] is not None,result
    consumed={a+i for a,n in m.reads for i in range(n)}
    literal,score,reads,writes,code=native_state(m,assessment)
    assert all(a+i in consumed for a,n in reads for i in range(n)),[(hex(a),n)for a,n in reads if any(a+i not in consumed for i in range(n))]
    assert (result['native_state'],result['private_score'])==(literal,score)
    assert 0x2387c40 not in code and not any(0x2387890<=a<0x2387930 for a in code)


@pytest.mark.parametrize('scores',[(100,40),(40,100),(0,255)])
def test_original_alternate_selector_uses_reverse_raw_UID_order(scores):
    from _knowledge_state_native import execute
    m=memory();first,last=(report(m,n)for n in scores);m.vec(m.human+0x128,[first,0,last])
    literal,*_=execute(m,0x12da3d0,[m.human,m.primary,0,0])
    assert literal==last
    assert run(m)['native_assessment_selection']==last


@pytest.mark.parametrize('scores',[(40,100),(100,40)])
def test_whole_original_club_selector_precedes_alternate_with_no_result_stubs(scores):
    from _knowledge_state_native import execute
    m=memory();low_K(m);first,last=(report(m,n,m.human_person)for n in scores)
    alternate=report(m,120);m.vec(m.human+0x110,[first,last]);m.vec(m.human+0x128,[alternate])
    m.reads.clear();result=run(m)
    consumed={a+i for a,n in m.reads for i in range(n)}
    literal,_,reads,_,_=execute(m,0x12d9e40,[m.human,m.primary,0,0])
    assert literal==first and result['native_assessment_selection']==literal
    assert all(a+i in consumed for a,n in reads for i in range(n))


@pytest.mark.parametrize('fault',['wrong_exact_state','wrong_report_max'])
def test_changed_original_state_instructions_cannot_support_the_same_result(fault):
    from _knowledge_state_native import native_state
    m=memory();assessment=0
    if fault=='wrong_exact_state':
        full_subject_contract(m);at=m.base+0x238758c
    else:
        low_K(m);assessment=report(m,40);m.vec(m.human+0x128,[assessment]);at=m.base+0x238794c
    result=run(m);word=int.from_bytes(m.read(at,4),'little')
    word=((word&~(65535<<5))|(1<<5)) if fault=='wrong_exact_state' else ((word&~(15<<12))|(11<<12))
    m.put(at,word.to_bytes(4,'little'))
    literal,score,*_=native_state(m,assessment)
    assert (literal,score)!=(result['native_state'],result['private_score'])
