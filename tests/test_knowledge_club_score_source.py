"""Whole original score wrapper/service in owned synthetic RAM only."""
from _knowledge_stream_fixture import native_stream_transport
import hashlib
import struct

import pytest

from fm_live_mcp import knowledge_club_score_source as source
from fm_live_mcp import knowledge_competition_context_source as context_source
from test_knowledge_context_score_source import Memory
from test_knowledge_context_score_source import run,copied_K
from test_knowledge_search_preliminary_source import identity,restore_metadata
from _knowledge_state_native import execute


def inline(m,header,width,rows):
    start=m.allocate(max(8,width*len(rows)))
    for index,raw in enumerate(rows):assert len(raw)==width;m.put(start+index*width,raw)
    m.put(header,struct.pack('<QQQ',start,start+len(rows)*width,start+len(rows)*width))
    return start


def row(raw,key,low=14,high=45):return bytes((raw,high,low))+bytes(5)+struct.pack('<Q',key)


def memory_fixture(combined=False):
    m=Memory(combined)
    for rva,n,digest in source.NATIVE_GUARDS+context_source.NATIVE_GUARDS:
        raw=m.disk(rva,n);assert hashlib.sha256(raw).hexdigest()==digest;m.put(m.base+rva,raw)
    m.target=m.typed('nation',0x220);m.identity(m.target,1,4001,4002)
    m.target_projection=m.typed('national_team_container',0x600);m.identity(m.target_projection,1,5001,5002)
    m.database('nations',[m.nation,m.target]);m.database('national_team_containers',[m.container,m.target_projection])
    m.q(m.target+0x110,m.target_projection);m.q(m.target+0x118,m.target_projection);m.q(m.target_projection+0x170,m.target)
    m.region=m.allocate(0x180);m.native_type(m.region,0x55ba7b8);m.identity(m.region,0,14,14)
    m.database('regions',[m.region]);m.q(m.target+0x100,m.region)
    m.continent=m.typed('continent',0x80);m.identity(m.continent,2,3,3)
    m.database('continents',[0,0,m.continent])
    m.manager=m.allocate(0x680);m.native_type(m.manager,0x55f80a0);m.q(m.base+0x56a4be0,m.manager)
    m.q(m.base+0x55df850+0xf0,m.base+0x1fa64d8)
    for table in (0x558a780,0x55908e0):m.q(m.base+table+0x4d8,m.base+0xd5c344)
    m.store=m.allocate(0x40);m.q(m.club+0x100,m.store)
    m.put(m.common+0x58,struct.pack('<HH',100,2000));m.put(m.base+0x52efdf0,struct.pack('<HH',317,2030))
    restore_metadata(m)
    return m


@pytest.fixture
def memory():return memory_fixture()


def actual(m,nation=None,person=True,**kwargs):
    nation=m.target if nation is None else nation;person=m.person if person else 0
    result=source.observe(m.read,m.base,m.club,identity(m,m.club),nation,identity(m,nation)if nation else None,
        person,identity(m,person)if person else None,check_current=kwargs.pop('check_current',lambda:('process','save','build')),**kwargs)
    assert set(result)=={'scope','native_score','lower_age_raw','upper_age_raw','complete_search_population_evaluated','field_visibility_evaluated','non_atomic'}
    return result['native_score'],result['lower_age_raw'],result['upper_age_raw']


def native(m,nation=None,person=True):
    out=m.allocate(8);m.put(out,b'\x0e\x2d');nation=m.target if nation is None else nation
    value,outputs,reads,writes,trace=execute(m,0xe076bc,[m.club,nation,out,out+1,m.person if person else 0],
        score_pointer=out,output_width=2,extra=source.NATIVE_GUARDS+context_source.NATIVE_GUARDS)
    assert all(0x200000000<=at<at+n<=0x200010000 or out<=at<at+n<=out+2 for _,at,n in writes)
    return (source.signed(value,32),*outputs),reads,trace


def install_stage(m,stage,raw,low=14,high=45):
    if stage=='override':
        values=m.allocate(8);m.put(values,struct.pack('<IB3x',identity(m,m.target)[1],raw))
        entry=struct.pack('<I4xQQQ',identity(m,m.club)[1],values,values+8,values+8)
        return inline(m,m.manager+0x650,32,[entry])
    header,key={'national':(m.container+0xf0,m.target_projection),
                'region':(m.container+0x120,m.region),'continent':(m.container+0x108,m.continent)}[stage]
    return inline(m,header,16,[row(raw,key,low,high)])


@pytest.mark.parametrize('stage',['override','national','region','continent'])
def test_every_signed_score_byte_matches_complete_original_wrapper_and_service(memory,stage):
    m=memory;address=install_stage(m,stage,0)
    score_at=address if stage!='override'else int.from_bytes(m.read(address+8,8),'little')+4
    for raw in range(256):
        m.put(score_at,bytes([raw]));expected,_,trace=native(m)
        assert actual(m)==expected
        assert 0xe076bc in trace and 0x1fa64d8 in trace


@pytest.mark.parametrize('combined',[False,True])
@pytest.mark.parametrize('stage',['national','region','continent'])
@pytest.mark.parametrize('low,high',[(14,45),(30,30),(31,45),(14,29),(255,31),(128,127),(14,255)])
def test_age_bounds_and_both_ordinary_layouts_match_full_native(combined,stage,low,high):
    m=memory_fixture(combined);install_stage(m,stage,20,low,high)
    assert actual(m)==native(m)[0]


@pytest.mark.parametrize('stage',['override','national','region','continent'])
def test_sentinel_gate_is_wrapped_native_uid_arithmetic_with_and_without_subject(memory,stage):
    m=memory;install_stage(m,stage,254)
    for uid in (1,2,3,4,5,0x7fffffff,0x80000000,0xfffffffe):
        m.identity(m.person,0,uid,uid);m.person_ref=(0,uid,uid)
        assert actual(m)==native(m)[0]
    assert actual(m,person=False)==native(m,person=False)[0]


def retained(m,raw,*,key=None):
    projection=m.allocate(0x520);m.q(m.competition+0xb0,projection)
    m.put(m.base+0x56d3518,struct.pack('<I',0xffffffff))
    header=m.allocate(24);entry=m.allocate(0x28);m.q(entry,m.target_projection if key is None else key)
    m.put(entry+0x24,bytes([raw]));m.vec(header,[entry]);m.q(m.store+0x38,header)
    return entry


def test_all_retained_bytes_are_returned_signed_without_game_service(memory):
    m=memory;entry=retained(m,0)
    for raw in range(256):
        m.put(entry+0x24,bytes([raw]));expected,_,trace=native(m)
        assert actual(m)==expected==(source.signed(raw),14,45)
        assert 0xf0f038 in trace and 0x1fa64d8 not in trace


def test_retained_miss_does_not_take_same_nation_100_shortcut(memory):
    m=memory;retained(m,99,key=m.target_projection)
    assert actual(m,nation=m.nation)==native(m,nation=m.nation)[0]==(0,14,45)
    m.q(m.store+0x38,0)
    assert actual(m,nation=m.nation)==native(m,nation=m.nation)[0]==(100,14,45)


def test_nation_then_region_then_continent_fallbacks_preserve_age_outputs(memory):
    m=memory
    install_stage(m,'national',0,31,32);install_stage(m,'region',255,33,34);install_stage(m,'continent',20,18,40)
    assert actual(m)==native(m)[0]==(25,18,40)
    m.q(m.target+0x100,0)
    assert actual(m)==native(m)[0]==(0,31,32)


@pytest.mark.parametrize('source_kind',['header','home','target','home_projection'])
def test_native_empty_or_null_sources_are_distinct_from_missing_read(memory,source_kind):
    m=memory;nation=None
    if source_kind=='header':m.q(m.store+0x38,0)
    if source_kind=='home':m.q(m.club+0xd8,0)
    if source_kind=='target':nation=0
    if source_kind=='home_projection':m.q(m.nation+0x110,0)
    assert actual(m,nation=nation)==native(m,nation=nation)[0]==(0,14,45)


@pytest.mark.parametrize('fault',['code','club','manager','manager_bounds','region','continent','service_route','store','person_route'])
def test_unproved_sources_are_unavailable_not_fabricated_scores(memory,fault):
    m=memory;install_stage(m,'national',20,30,30)
    if fault=='code':m.put(m.base+0x1fa64d8,b'\0')
    if fault=='club':m.q(m.club,0)
    if fault=='manager':m.q(m.manager,0)
    if fault=='manager_bounds':m.q(m.manager+0x650,8)
    if fault in ('region','continent'):install_stage(m,'national',0)
    if fault=='region':m.q(m.region,0)
    if fault=='continent':m.q(m.continent,0)
    if fault=='service_route':m.q(m.base+0x55df850+0xf0,m.base+0x1fa64dc)
    if fault=='store':m.q(m.club+0x100,0)
    if fault=='person_route':m.q(m.base+0x558a780+0x4d8,0)
    with pytest.raises(ValueError):actual(m)


def test_final_callback_changes_to_consumed_score_are_rejected(memory):
    m=memory;entry=install_stage(m,'national',20);calls=[]
    def lifetime():
        calls.append(1)
        if len(calls)==2:m.put(entry,b'\x13')
        return ('process','save','build')
    with pytest.raises(ValueError,match='changed'):actual(m,check_current=lifetime)


def test_lower_bound_preserves_null_keys_and_first_duplicate_not_maximum_score(memory):
    m=memory
    inline(m,m.container+0xf0,16,[row(99,0),row(12,m.target_projection),row(24,m.target_projection),row(33,m.container)])
    assert actual(m)==native(m)[0]==(30,14,45)
    inline(m,m.container+0xf0,16,[row(99,0),row(33,m.container)])
    assert actual(m)==native(m)[0]==(0,14,45)


def test_override_uses_sorted_club_lower_bound_and_first_native_nation_row(memory):
    m=memory;uid=identity(m,m.club)[1];target=identity(m,m.target)[1]
    values=m.allocate(24);m.put(values,struct.pack('<IB3xIB3xIB3x',target+1,100,target,30,target,60))
    rows=[struct.pack('<I4xQQQ',club_uid,values,values+24,values+24)for club_uid in (uid-1,uid,uid+1)]
    inline(m,m.manager+0x650,32,rows)
    assert actual(m)==native(m)[0]==(75,14,45)
    inline(m,m.manager+0x650,32,[rows[0],rows[2]])
    assert actual(m)==native(m)[0]==(0,14,45)


def test_default_birth_date_returns_zero_without_loading_asof_context(memory):
    m=memory;install_stage(m,'national',20,0,0);m.put(m.common+0x58,struct.pack('<HH',1,1900))
    m.blocked.append((m.base+0x52efdf0,m.base+0x52efdf0+4))
    assert actual(m)==native(m)[0]==(50,0,0)


def test_default_asof_date_uses_current_date_in_mode_zero(memory):
    m=memory;install_stage(m,'national',20,30,30)
    m.put(m.base+0x52efdf0,struct.pack('<HH',1,1900));m.put(m.base+0x56d4951,b'\0')
    assert actual(m)==native(m)[0]==(50,30,30)


def score_K_fixture(combined=False):
    m=memory_fixture(combined)
    other_competition=m.typed('competition',0x180);m.identity(other_competition,1,6001,6002)
    m.database('competitions',[m.competition,other_competition])
    alternate=m.typed('team',0x180);m.identity(alternate,2,7001,7002)
    m.database('teams',[m.team,m.national,alternate]);m.q(alternate+0x30,m.club);m.q(alternate+0x50,other_competition)
    m.vec(m.club+0x18,[m.team,alternate]);m.q(m.primary+0x128,alternate)
    m.put(m.primary+0x25a,struct.pack('<h',4999))
    restore_metadata(m)
    return m


@pytest.mark.parametrize('combined',[False,True])
def test_real_K_collector_reaches_new_score_and_matches_complete_original_K(combined):
    m=score_K_fixture(combined);result=run(m)
    assert result['unavailable_reason']is None
    assert result['score']==copied_K(m)==40
    assert (m.store+0x38,8)in m.reads
