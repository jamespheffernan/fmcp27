"""Physical assessment source paging, qualified fields and fail-closed reads."""
import struct

import pytest

from fm_live_mcp import assessment_source as source, world
from prepared_tactics_fixture import (prepared_tactics_memory, team_memory,
                                     database_memory, memory, world_memory)


def add_assessments(m):
    """Compose real source structures; private subject/assessor identity is caller-owned."""
    for rva, raw in source.NATIVE_SPANS:
        m['put'](m['base']+rva, raw)
    m['put'](m['team']+0x2F,b'\0')

    def new_assessment(subject=0x1388, assessor=0, raw_date=None, child=0):
        record=m['allocate'](0x48)
        m['q'](record,subject);m['q'](record+8,assessor)
        m['put'](record+0x18,raw_date if raw_date is not None else struct.pack('<HH',301|0x1A00,2030))
        m['q'](record+0x30,child)
        return record

    def set_assessments(records,offset=0x110,capacity=None,null=False):
        if null:m['put'](m['manager']+offset,bytes(24));return
        m['vec'](m['manager']+offset,list(records))
        if capacity is not None:
            start=struct.unpack('<Q',m['read'](m['manager']+offset,8))[0]
            m['q'](m['manager']+offset+16,start+capacity*8)

    other=m['allocate'](0x20);assessor=m['allocate'](0x20);child=m['allocate'](8)
    first=new_assessment(assessor=assessor,child=child)
    second=new_assessment(subject=other)
    set_assessments([first,0,second,first],capacity=6074)
    set_assessments([],offset=0x128,null=True)
    m.update(new_assessment=new_assessment,set_assessments=set_assessments,
             assessment_records=[first,0,second,first],assessment_subject=0x1388,
             assessment_other_subject=other,assessment_assessor=assessor,assessment_child=child)
    return m


@pytest.fixture
def assessment_memory(prepared_tactics_memory):
    return add_assessments(prepared_tactics_memory)


def project(m,offset=0,limit=4096,wanted=None,read=None):
    return source.project(read or m['read'],m['base'],m['coach'],
                          {m['assessment_subject']} if wanted is None else wanted,offset,limit)


def test_complete_physical_scan_preserves_nulls_duplicates_and_qualified_values(assessment_memory):
    m=assessment_memory;summary,rows=project(m)
    assert summary=={'source_state':'available','unavailable_reason':None,
                     'team':summary['team'],'team_context_marker':0,'population':source.POPULATION,
                     'source_total':4,'source_offset':0,'scanned_count':4,
                     'next_source_offset':None,'complete_source':True}
    assert [row[0] for row in rows]==[0,3]
    assert [row[1:3] for row in rows]==[(0x1388,m['assessment_assessor'])]*2
    assert rows[0][3]=={'stored_population_date':{'value':'2030-10-28',
                       'state':'stored_base_population_date','raw_hex':'2d1bee07'},
                       'assessment_payload_state':'stored_assessment_extra_data_present'}
    assert rows[0][3] is not rows[1][3]
    rows[0][3]['stored_population_date']['state']='changed'
    assert rows[1][3]['stored_population_date']['state']=='stored_base_population_date'
    assert '0x' not in str(summary) and 'address' not in str(summary)


@pytest.mark.parametrize('offset,limit,indices,next_offset,complete',[
    (0,1,[0],1,False),(1,2,[],3,False),(2,2,[3],None,False),
    (3,4096,[3],None,False),(4,4096,[],None,False)])
def test_pages_count_every_physical_slot(assessment_memory,offset,limit,indices,next_offset,complete):
    summary,rows=project(assessment_memory,offset,limit)
    assert [row[0] for row in rows]==indices
    assert summary['scanned_count']==min(limit,4-offset)
    assert summary['next_source_offset']==next_offset and summary['complete_source']==complete


def test_page_union_equals_whole_projection(assessment_memory):
    m=assessment_memory;whole=project(m)[1];rows=[];offset=0
    while True:
        summary,page=project(m,offset,1);rows.extend(page)
        assert not summary['complete_source']
        if summary['next_source_offset'] is None:break
        offset=summary['next_source_offset']
    assert rows==whole


@pytest.mark.parametrize('null',[True,False])
def test_actual_empty_sources_are_available_and_complete(assessment_memory,null):
    m=assessment_memory;m['set_assessments']([],null=null)
    summary,rows=project(m)
    assert summary['source_state']=='available' and summary['source_total']==0
    assert summary['scanned_count']==0 and summary['complete_source'] and rows==[]
    assert summary['next_source_offset'] is None
    with pytest.raises(IndexError):project(m,1)


@pytest.mark.parametrize('marker',[1,2,255])
def test_exact_nonzero_native_branch_has_no_national_coverage_inference(assessment_memory,marker):
    m=assessment_memory;m['put'](m['team']+0x2F,bytes([marker]))
    m['set_assessments']([m['assessment_records'][0]],offset=0x128)
    summary,rows=project(m)
    assert summary['team_context_marker']==marker and summary['source_total']==1
    assert [row[0] for row in rows]==[0] and 'national' not in str(summary)


def test_capacity_is_not_length_or_page_limit(assessment_memory):
    m=assessment_memory;m['set_assessments']([0]*3121,capacity=6074)
    summary,rows=project(m)
    assert summary['source_total']==3121 and summary['scanned_count']==3121
    assert summary['complete_source'] and rows==[]
    m['set_assessments']([0]*5000,capacity=1000000)
    summary,rows=project(m)
    assert summary['source_total']==5000 and summary['scanned_count']==4096
    assert summary['next_source_offset']==4096 and not summary['complete_source']


def test_empty_wanted_set_does_not_invent_complete_report_absence(assessment_memory):
    summary,rows=project(assessment_memory,wanted=set())
    assert summary['source_total']==4 and summary['complete_source'] and rows==[]


@pytest.mark.parametrize('offset,limit',[(-1,1),(True,1),(1.5,1),('1',1),
                                       (0,0),(0,4097),(0,True),(0,1.5)])
def test_bad_paging_fails_before_reads(offset,limit):
    with pytest.raises(ValueError):
        source.project(lambda *_:pytest.fail('read'),0x10000000,{},set(),offset,limit)


@pytest.mark.parametrize('wanted',[[0x1388],{0},{True},{0x1389},{1<<64},None])
def test_bad_wanted_person_addresses_fail_before_reads(wanted):
    with pytest.raises(ValueError):
        source.project(lambda *_:pytest.fail('read'),0x10000000,{},wanted,0,1)


def test_offset_beyond_source_rejects(assessment_memory):
    with pytest.raises(IndexError,match='offset'):project(assessment_memory,5)


@pytest.mark.parametrize('header',[(0,8,8),(8,8,8),(0x10000,0x10008,0x10000),
                                   (0x10000,0xFFF8,0x10000),(0x10001,0x10001,0x10001),
                                   (0x10000,0x10001,0x10008),(0x10000,0x10008,0x10009)])
def test_corrupt_vector_geometry_is_not_unavailable_or_empty(assessment_memory,header):
    m=assessment_memory;m['put'](m['manager']+0x110,struct.pack('<QQQ',*header))
    with pytest.raises(ValueError):project(m)


@pytest.mark.parametrize('field,value',[('record',8),('record',0x10001),
                                       ('record',(1<<64)-8),('subject',8),('subject',0x1389),
                                       ('assessor',8),('assessor',0x1389),('child',8),('child',0x1389)])
def test_malformed_selected_pointers_fail_closed(assessment_memory,field,value):
    m=assessment_memory;record=m['assessment_records'][0]
    if field=='record':m['set_assessments']([value])
    else:m['q'](record+{'subject':0,'assessor':8,'child':0x30}[field],value)
    with pytest.raises(ValueError):project(m)


def test_null_assessor_and_absent_extra_data_are_valid(assessment_memory):
    m=assessment_memory;record=m['new_assessment']();m['set_assessments']([record])
    _,rows=project(m)
    assert rows[0][2]==0 and rows[0][3]['assessment_payload_state']=='assessment_extra_data_absent'


def test_null_subject_is_unmatched_not_fabricated_identity(assessment_memory):
    m=assessment_memory;record=m['new_assessment'](subject=0);m['set_assessments']([record])
    summary,rows=project(m)
    assert summary['scanned_count']==1 and rows==[]


def test_nonmatches_read_only_pointer_fields_and_child_contents_are_never_read(assessment_memory):
    m=assessment_memory;record=m['assessment_records'][2];calls=[]
    def read(address,size):
        if record<=address<record+0x48:assert (address,size)==(record,16)
        assert address!=m['assessment_child']
        calls.append((address,size));return m['read'](address,size)
    project(m,read=read)
    assert calls.count((m['assessment_records'][0],16))==1
    assert calls.count((record,16))==1


@pytest.mark.parametrize('raw,value,state',[
    (struct.pack('<HH',1,1900),None,'native_default_sentinel'),
    (struct.pack('<HH',1|0xFE00,1900),None,'native_default_sentinel'),
    (struct.pack('<HH',60|0xFE00,2000),'2000-02-29','stored_base_population_date'),
    (struct.pack('<HH',366,2000),'2000-12-31','stored_base_population_date'),
    (struct.pack('<HH',366,2001),None,'unmapped_packed_value'),
    (struct.pack('<HH',0,2030),None,'unmapped_packed_value'),
    (struct.pack('<HH',511,2030),None,'unmapped_packed_value'),
    (struct.pack('<HH',1,0),None,'unmapped_packed_value'),
    (struct.pack('<HH',1,65535),None,'unmapped_packed_value'),
])
def test_packed_population_date_mask_defaults_and_unmapped_values(assessment_memory,raw,value,state):
    m=assessment_memory;record=m['new_assessment'](raw_date=raw);m['set_assessments']([record])
    date=project(m)[1][0][3]['stored_population_date']
    assert date=={'value':value,'state':state,'raw_hex':raw.hex()}


@pytest.mark.parametrize('rva,raw',source.NATIVE_SPANS)
def test_every_selected_native_guard_rejects_drift(assessment_memory,rva,raw):
    m=assessment_memory;m['put'](m['base']+rva,bytes([raw[0]^1]))
    with pytest.raises(ValueError,match='native source changed'):project(m)


@pytest.mark.parametrize('fault',['human_type','human_rtti','team_type','team_index','team_backlink','contract','club'])
def test_canonical_owner_context_failures_are_never_empty(assessment_memory,fault):
    m=assessment_memory
    if fault=='human_type':m['q'](m['manager'],0)
    elif fault=='human_rtti':m['put'](m['base']+world.TYPES['manager'][0]-16,struct.pack('<q',1))
    elif fault=='team_type':m['q'](m['team'],0)
    elif fault=='team_index':m['put'](m['team']+8,struct.pack('<I',99999))
    elif fault=='team_backlink':m['q'](m['team']+0x80,0)
    elif fault=='contract':m['q'](m['contract']+0x10,0)
    else:m['coach']={**m['coach'],'club':{'name':'Wrong'}}
    with pytest.raises(ValueError):project(m)


def test_header_change_during_projection_rejects_even_plain_reader(assessment_memory):
    m=assessment_memory;record=m['assessment_records'][0]
    def read(address,size):
        raw=m['read'](address,size)
        if (address,size)==(record,16):m['q'](m['manager']+0x118,0)
        return raw
    with pytest.raises(ValueError,match='changed during read'):project(m,read=read)


@pytest.mark.parametrize('changed',['header','page','pair','date','child','native'])
def test_caller_readset_recheck_detects_consumed_changes(assessment_memory,changed):
    m=assessment_memory;read=world.ReadSet(m['read']);project(m,read=read)
    record=m['assessment_records'][0]
    address={'header':m['manager']+0x110,
             'page':struct.unpack('<Q',m['read'](m['manager']+0x110,8))[0],
             'pair':record,'date':record+0x18,'child':record+0x30,
             'native':m['base']+source.NATIVE_SPANS[0][0]}[changed]
    m['put'](address,bytes([m['read'](address,1)[0]^1]))
    with pytest.raises(ValueError,match='changed during read'):read.verify()


def test_short_reads_fail_as_a_whole(assessment_memory):
    m=assessment_memory;record=m['assessment_records'][0]
    def read(address,size):
        raw=m['read'](address,size)
        return raw[:-1] if (address,size)==(record,16) else raw
    with pytest.raises(ValueError,match='Incomplete'):project(m,read=read)


def test_pointer_pages_respect_real_helper_transport_limit(assessment_memory):
    m=assessment_memory;m['set_assessments']([0]*5000,capacity=6074);calls=[]
    def read(address,size):
        assert size<=16384
        calls.append((address,size));return m['read'](address,size)
    summary,rows=project(m,500,4096,read=read)
    assert summary['scanned_count']==4096 and summary['next_source_offset']==4596
    assert sum(size==16384 for _,size in calls)==2 and rows==[]
