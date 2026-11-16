"""Canonical personal-list source, physical ordering, selectors and unavailable data."""
import struct

import pytest

from fm_live_mcp import shortlist_source as source, world
from prepared_tactics_fixture import (prepared_tactics_memory, team_memory,
                                     database_memory, memory, world_memory)


def add_shortlists(m):
    """Seed real source structures; caller may replace members for composed tests."""
    for rva, raw in source.NATIVE_SPANS:
        m['put'](m['base']+rva, raw)
    human=m['manager']
    m['put'](m['base']+source.MODE_FLAG,b'\x01')
    m['put'](human+0x422,b'\x01')

    def new_list(kind=0, name=None, members=(), owner=None):
        address=m['allocate'](0x140)
        m['put'](address+0x4C,bytes([kind]))
        m['q'](address+0xD0,human if owner is None else owner)
        m['q'](address+0xE8,0 if name is None else m['text'](name))
        m['vec'](address+0x80,list(members))
        return address

    def set_lists(addresses):
        m['vec'](human+0x230,list(addresses))

    def set_selector(value=0,container=3):
        m['put'](human+0x42A,struct.pack('<b',value))
        m['put'](human+0x41F,bytes([container]))

    entries=[]
    for _ in range(10):
        entry=m['allocate'](0x38)
        m['q'](entry,0x1388)
        entries.append(entry)
    addresses=[new_list(members=entries),new_list(8),new_list(6)]
    set_lists(addresses);set_selector()
    m.update(shortlist_addresses=addresses,shortlist_entries=entries,new_list=new_list,
             set_lists=set_lists,set_selector=set_selector)
    return m


@pytest.fixture
def shortlist_memory(prepared_tactics_memory):
    return add_shortlists(prepared_tactics_memory)


def inspect(m,index=None,read=None):
    return source.inspect(read or m['read'],m['base'],m['coach'],index)


def test_current_personal_selection_and_complete_ordinary_headers(shortlist_memory):
    m=shortlist_memory;summary,address,total=inspect(m)
    assert summary=={
        'lists':[{'list_index':0,'stored_name':None,'entry_count':10}],
        'personal_list_count':3,'selected_list_index':0,'selection_state':'selected',
        'source_state':'available','unavailable_reason':None,
        'selection_source':'current_personal_selection','current_container_code':3,
        'stored_selected_index':0,'effective_personal_selected_index':0,
        'selector_negative_clamped':False,'null_list_indices':[]}
    assert address==m['shortlist_addresses'][0] and total==10
    assert '0x' not in repr(summary) and 'address' not in repr(summary)


@pytest.mark.parametrize('flag',[1,3,127,255])
def test_native_mode_checks_bit_zero_not_equality(shortlist_memory,flag):
    m=shortlist_memory;m['put'](m['base']+source.MODE_FLAG,bytes([flag]))
    assert inspect(m)[0]['source_state']=='available'


@pytest.mark.parametrize('fault,reason',[(0,'unsupported_shortlist_mode'),(2,'unsupported_shortlist_mode'),
                                       (4,'unsupported_shortlist_mode'),(254,'unsupported_shortlist_mode')])
def test_unsupported_mode_does_not_read_vector_or_invent_counts(shortlist_memory,fault,reason):
    m=shortlist_memory;m['put'](m['base']+source.MODE_FLAG,bytes([fault]))
    def read(a,n):
        assert a!=m['manager']+0x230
        return m['read'](a,n)
    summary,pointer,total=inspect(m,read=read)
    assert summary['source_state']=='unavailable' and summary['unavailable_reason']==reason
    assert summary['personal_list_count'] is None and summary['lists']==[]
    assert summary['selected_list_index'] is None and pointer is None and total is None


@pytest.mark.parametrize('flag',[0,2,3,255])
def test_human_mode_requires_exact_one(shortlist_memory,flag):
    m=shortlist_memory;m['put'](m['manager']+0x422,bytes([flag]))
    assert inspect(m)[0]['unavailable_reason']=='human_shortlists_unavailable'
    assert inspect(m)[1:]==(None,None)


@pytest.mark.parametrize('container',[0,1,2,4,255])
def test_default_never_substitutes_other_container_or_first_personal(shortlist_memory,container):
    m=shortlist_memory;m['set_selector'](0,container)
    summary,pointer,total=inspect(m)
    assert summary['lists'][0]['entry_count']==10
    assert summary['selection_state']=='current_selection_not_personal'
    assert pointer is total is None
    explicit=inspect(m,0)
    assert explicit[0]['selection_source']=='explicit_native_index'
    assert explicit[1]==m['shortlist_addresses'][0] and explicit[2]==10


@pytest.mark.parametrize('selector',[-128,-2,-1])
def test_negative_signed_selector_uses_native_zero_clamp(shortlist_memory,selector):
    m=shortlist_memory;m['set_selector'](selector)
    summary,pointer,total=inspect(m)
    assert summary['stored_selected_index']==selector
    assert summary['effective_personal_selected_index']==0 and summary['selector_negative_clamped']
    assert summary['selected_list_index']==0 and pointer==m['shortlist_addresses'][0] and total==10


@pytest.mark.parametrize('selector',[3,10,127])
def test_default_outside_vector_is_unavailable_not_empty(shortlist_memory,selector):
    m=shortlist_memory;m['set_selector'](selector)
    summary,pointer,total=inspect(m)
    assert summary['selection_state']=='selected_index_beyond_count'
    assert summary['selected_list_index'] is None and pointer is total is None


@pytest.mark.parametrize('selector',[1,2])
def test_selected_nonordinary_list_is_not_substituted(shortlist_memory,selector):
    m=shortlist_memory;m['set_selector'](selector)
    assert inspect(m)[0]['selection_state']=='selected_list_not_ordinary'
    assert inspect(m)[1:]==(None,None)
    with pytest.raises(ValueError,match='ordinary'):inspect(m,selector)


@pytest.mark.parametrize('index',[True,False,-1,1.0,'0',[],{}])
def test_invalid_explicit_index_rejects_before_reads(index):
    with pytest.raises(ValueError,match='index'):
        source.inspect(lambda *_:pytest.fail('unexpected read'),0x10000000,{},index)


@pytest.mark.parametrize('index',[3,1000000])
def test_explicit_index_out_of_range_rejects(shortlist_memory,index):
    with pytest.raises(IndexError,match='outside'):inspect(shortlist_memory,index)


@pytest.mark.parametrize('zero', [False,True])
def test_empty_personal_vector_is_distinct_from_source_unavailable(shortlist_memory,zero):
    m=shortlist_memory;m['set_lists']([])
    if zero:m['put'](m['manager']+0x230,bytes(24))
    summary,pointer,total=inspect(m)
    assert summary['source_state']=='available' and summary['personal_list_count']==0
    assert summary['selection_state']=='personal_list_vector_empty' and summary['lists']==[]
    assert pointer is total is None
    with pytest.raises(IndexError):inspect(m,0)


def test_selected_empty_ordinary_list_has_known_zero_count(shortlist_memory):
    m=shortlist_memory;empty=m['new_list']()
    m['set_lists']([empty])
    summary,pointer,total=inspect(m)
    assert summary['lists']==[{'list_index':0,'stored_name':None,'entry_count':0}]
    assert pointer==empty and total==0 and summary['selection_state']=='selected'


def test_null_physical_slots_preserve_ordinals_and_are_never_zero_members(shortlist_memory):
    m=shortlist_memory;normal=m['shortlist_addresses'][0]
    m['set_lists']([0,normal]);summary,pointer,total=inspect(m)
    assert summary['personal_list_count']==2 and summary['null_list_indices']==[0]
    assert summary['lists'][0]['list_index']==1
    assert summary['selection_state']=='selected_list_null' and pointer is total is None
    with pytest.raises(ValueError,match='ordinary'):inspect(m,0)
    assert inspect(m,1)[1:]==(normal,10)


def test_duplicate_list_pointers_and_names_keep_native_physical_order(shortlist_memory):
    m=shortlist_memory;a=m['new_list'](name='Same',members=[0,0]);b=m['new_list'](name='Same',members=[])
    m['set_lists']([b,a,a]);m['set_selector'](2)
    summary,pointer,total=inspect(m)
    assert summary['lists']==[{'list_index':0,'stored_name':'Same','entry_count':0},
                              {'list_index':1,'stored_name':'Same','entry_count':2},
                              {'list_index':2,'stored_name':'Same','entry_count':2}]
    assert summary['selected_list_index']==2 and pointer==a and total==2


@pytest.mark.parametrize('name',[None,'',' ','Named  ','São Paulo 日本','é'*1024])
def test_null_empty_unicode_and_whitespace_names_are_distinct(shortlist_memory,name):
    m=shortlist_memory;address=m['new_list'](name=name);m['set_lists']([address])
    assert inspect(m)[0]['lists'][0]['stored_name']==name


def test_native_name_pointer_can_be_unaligned(shortlist_memory):
    m=shortlist_memory;address=m['shortlist_addresses'][0];text=m['allocate'](16)+1
    m['put'](text,struct.pack('<I',3)+b'abc\0');m['q'](address+0xE8,text)
    assert inspect(m)[0]['lists'][0]['stored_name']=='abc'


@pytest.mark.parametrize('fault',['too_long','invalid_utf8','missing_terminator','embedded_nul','control','pointer'])
def test_malformed_name_rejects_whole_source(shortlist_memory,fault):
    m=shortlist_memory;address=m['shortlist_addresses'][0];text=m['text']('abc')
    m['q'](address+0xE8,text)
    if fault=='too_long':m['put'](text,struct.pack('<I',source.NAME_LIMIT+1))
    elif fault=='invalid_utf8':m['put'](text+4,b'\xff')
    elif fault=='missing_terminator':m['put'](text+7,b'x')
    elif fault=='embedded_nul':m['put'](text+4,b'\0')
    elif fault=='control':m['put'](text+4,b'\n')
    elif fault=='pointer':m['q'](address+0xE8,(1<<64)-1)
    with pytest.raises(ValueError):inspect(m)


@pytest.mark.parametrize('slot',[0,1,2])
def test_every_nonnull_personal_list_must_belong_to_canonical_human(shortlist_memory,slot):
    m=shortlist_memory;m['q'](m['shortlist_addresses'][slot]+0xD0,m['manager']+8)
    with pytest.raises(ValueError,match='ownership'):inspect(m)


@pytest.mark.parametrize('which',['personal','members'])
@pytest.mark.parametrize('fault',['backwards','bad_capacity','unaligned_start','unaligned_end','budget','nonzero_end_null_start'])
def test_corrupt_vector_geometry_and_budgets_reject(shortlist_memory,which,fault):
    m=shortlist_memory
    address=m['manager']+0x230 if which=='personal' else m['shortlist_addresses'][0]+0x80
    limit=source.LIST_LIMIT if which=='personal' else source.MEMBER_LIMIT
    start,end,cap=struct.unpack('<QQQ',m['read'](address,24))
    if fault=='backwards':end=start-8
    elif fault=='bad_capacity':cap=start
    elif fault=='unaligned_start':start+=1
    elif fault=='unaligned_end':end-=1
    elif fault=='budget':cap=start+(limit+1)*8
    elif fault=='nonzero_end_null_start':start=0
    m['put'](address,struct.pack('<QQQ',start,end,cap))
    with pytest.raises(ValueError):inspect(m)


def test_source_does_not_read_member_payloads_or_global_pools(shortlist_memory):
    m=shortlist_memory
    member_spans=[(int.from_bytes(m['read'](p+0x80,8),'little'),10*8) for p in m['shortlist_addresses'][:1]]
    def read(address,size):
        assert address!=m['base']+0x56A4BE0
        assert not any(a<=address<a+n for a,n in member_spans)
        return m['read'](address,size)
    assert inspect(m,read=read)[2]==10


@pytest.mark.parametrize('fault',['selector','container','vector','owner','kind','name','count','gate'])
def test_all_consumed_source_bytes_are_stale_checked(shortlist_memory,fault):
    m=shortlist_memory;snapshot=world.ReadSet(m['read']);inspect(m,read=snapshot);snapshot.verify()
    p=m['shortlist_addresses'][0]
    if fault=='selector':m['set_selector'](1)
    elif fault=='container':m['set_selector'](0,1)
    elif fault=='vector':m['set_lists'](m['shortlist_addresses'][:1])
    elif fault=='owner':m['q'](p+0xD0,0)
    elif fault=='kind':m['put'](p+0x4C,b'\x08')
    elif fault=='name':m['q'](p+0xE8,m['text']('Changed'))
    elif fault=='count':m['q'](p+0x88,0)
    elif fault=='gate':m['put'](m['base']+source.MODE_FLAG,b'\0')
    with pytest.raises(ValueError,match='changed'):snapshot.verify()


@pytest.mark.parametrize('index',range(len(source.NATIVE_SPANS)))
def test_every_native_guard_rejects_changed_byte(shortlist_memory,index):
    m=shortlist_memory;rva,raw=source.NATIVE_SPANS[index];m['put'](m['base']+rva,bytes([raw[0]^1]))
    with pytest.raises(ValueError,match='native source changed'):inspect(m)


@pytest.mark.parametrize('base',[None,True,0,4095,4097,(1<<64)-8])
def test_invalid_base_rejects_before_reads(base):
    with pytest.raises(ValueError,match='address'):
        source.inspect(lambda *_:pytest.fail('unexpected read'),base,{},None)


def test_truncated_canonical_read_fails_as_value_error(shortlist_memory):
    m=shortlist_memory
    def read(a,n):
        raw=m['read'](a,n)
        return raw[:-1] if a==m['team']+8 else raw
    with pytest.raises(ValueError,match='Incomplete'):inspect(m,read=read)
