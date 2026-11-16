"""Independent composed public acceptance for stored managed-team training."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import date,timedelta
import json
import struct

import pytest

from fm_live_mcp import bridge as bridge_module,training_calendar as calendar,training_sessions as sessions,training_source as source,world
from fm_live_mcp.bridge import BridgeError
from training_source_fixture import (training_source_memory,prepared_tactics_memory,team_memory,database_memory,memory,world_memory)
from training_session_fixture import training_resource_bundle,RESOURCE_BYTES
from test_bridge import bridge,PROCESS
from test_database import bind

NAMES={108:'Penalties',101:'Ball Progression',104:'Defensive Positioning',300:'Rest',500:'Match',301:'Recovery',
       3:'In Possession Shape',1:'Build Up',2:'Chance Creation',4:'Line of Engagement',7:'Out Of Possession Shape',5:'Pressing Intensity'}
CODES=[[108,101,104],[300,500,300],[301,300,300],[3,1,2],[4,7,5],[300,500,300],[301,300,300]]


@pytest.fixture
def composed(bridge,monkeypatch,tmp_path,training_source_memory):
    m=training_source_memory
    for module in (calendar,sessions):
        for rva,raw in module.NATIVE_SPANS:m['put'](m['base']+rva,raw)
    m['put'](m['base']+world.CURRENT_DATE,struct.pack('<I',(2030<<16)|(17<<9)|301))
    bundle=training_resource_bundle(tmp_path)
    process=replace(PROCESS,executable=str(bundle['executable']))
    bridge.detach();monkeypatch.setattr(bridge_module,'process_info',lambda pid:process if pid==42 else None);bridge.attach(42)
    bind(bridge,monkeypatch,m)
    m.update(resource_bundle=bundle,fixture_process=process)
    for cache in (bridge.player_refs,bridge.team_refs,bridge.competition_refs):cache['preexisting']={'opaque':'untouched'}
    assert sessions.resource_matches(process.executable) is True
    return m


def query(bridge,**kw):return bridge.get_managed_training(bridge.session,**kw)
def refs(bridge):return deepcopy((bridge.player_refs,bridge.team_refs,bridge.competition_refs))


def assert_missing(days,state):
    for row in days:
        assert row['state']==state and row['slots'] is None and row['native_wrapper_index'] is None
        assert row['unmapped_row_byte'] is None and row['native_weekday'] in range(1,8) and row['storage_row'] in range(7)


def test_real_default_seven_dates_21_exact_source_labels_and_no_refs(bridge,composed):
    before=refs(bridge);result=query(bridge)
    assert result['source_state']=='available' and result['unavailable_reason'] is None
    assert result['save']['current_date']=='2030-10-28'
    assert result['window']=={'start_date':'2030-10-28','end_date':'2030-11-03','day_count':7}
    assert result['team_type']=={'native_code':0,'name':'First Team','source':'build_editor_team_type_enum'}
    assert result['complete_stored_window'] is True and len(result['days'])==7
    for index,row in enumerate(result['days']):
        assert row['date']==str(date(2030,10,28)+timedelta(days=index)) and row['week_start']=='2030-10-28'
        assert row['storage_row']==index and row['native_weekday']==[2,3,4,5,6,7,1][index]
        assert row['native_wrapper_index']==0 and row['unmapped_row_byte']==0
        assert row['slots']==[{'slot_index':slot,'native_code':code,'english_definition_name':NAMES[code],
            'name_state':'named_installed_definition'} for slot,code in enumerate(CODES[index])]
    assert refs(bridge)==before
    def visit(value):
        if isinstance(value,dict):
            assert not any(k=='address' or k.endswith(('_address','_pointer','_ref')) for k in value)
            for item in value.values():visit(item)
        elif isinstance(value,list):
            for item in value:visit(item)
    visit(result)


def test_explicit_default_equivalence_and_sunday_monday_select_different_body(bridge,composed):
    m=composed
    next_codes=[[106,105,100]]+[[300,300,300] for _ in range(6)]
    next_week=m['training_wrapper'](308,codes=next_codes)
    m['set_training_weeks']([m['training_wrapper_addresses'][0],next_week])
    left=query(bridge);right=query(bridge,start_date='2030-10-28',day_count=7)
    for value in (left,right):value.pop('observed_at')
    assert left==right
    rows=query(bridge,start_date='2030-11-03',day_count=2)['days']
    assert [r['native_wrapper_index'] for r in rows]==[0,1]
    assert [r['storage_row'] for r in rows]==[6,0] and [r['native_weekday'] for r in rows]==[1,2]
    assert [[s['native_code'] for s in r['slots']] for r in rows]==[[301,300,300],[106,105,100]]


@pytest.mark.parametrize('kw',[
    {'day_count':v} for v in (None,True,False,0,367,7.0,'7',[])
]+[{'start_date':v} for v in ('2030-1-01','2030-02-30','2030-10-28T00:00:00',' 2030-10-28','1849-12-31','2201-01-01',0,True)]
 +[{'start_date':'2200-12-31','day_count':2}])
def test_strict_window_validation_before_training_source(bridge,monkeypatch,composed,kw):
    def forbidden(*args):pytest.fail('Invalid window accessed training source')
    monkeypatch.setattr(source,'inspect',forbidden)
    before=refs(bridge)
    with pytest.raises(BridgeError):query(bridge,**kw)
    assert refs(bridge)==before


@pytest.mark.parametrize('count',[1,366])
def test_inclusive_day_count_bounds_keep_all_missing_dates(bridge,composed,count):
    result=query(bridge,day_count=count)
    assert len(result['days'])==count and result['days'][-1]['date']==str(date(2030,10,28)+timedelta(days=count-1))
    assert result['complete_stored_window'] is (count==1)
    if count==366:assert_missing(result['days'][14:],'unavailable_resident_week')


@pytest.mark.parametrize('kind,reason',[
    ('root','training_manager_missing'),('gate','unsupported_training_assignment_mode'),
    ('owner','owner_entry_missing'),('team','direct_team_entry_missing_native_fallback_unsupported')])
def test_absent_source_distinct_from_empty_weeks_and_rest(bridge,composed,kind,reason):
    m=composed
    if kind=='root':m['q'](m['training_source_root'],0)
    elif kind=='gate':m['put'](m['training_source_gate'],b'\0')
    elif kind=='owner':m['vec'](m['training_manager']+0x38,[])
    else:
        m['q'](m['training_owner']+0x48,m['training_owner']+0x50)
        m['q'](m['training_owner']+0x50,0);m['q'](m['training_owner']+0x58,0)
    result=query(bridge)
    assert result['source_state']=='unavailable' and result['unavailable_reason']==reason
    assert result['complete_stored_window'] is False and len(result['days'])==7
    assert_missing(result['days'],'unavailable_source')


@pytest.mark.parametrize('kind',['empty','nearest'])
def test_available_source_missing_week_never_uses_default_or_nearest(bridge,composed,kind):
    m=composed;m['set_training_weeks']([] if kind=='empty' else [m['training_wrapper'](294),m['training_wrapper'](308)])
    result=query(bridge)
    assert result['source_state']=='available' and result['unavailable_reason'] is None and not result['complete_stored_window']
    assert_missing(result['days'],'unavailable_resident_week')


@pytest.mark.parametrize('code,name',[(-32768,None),(-1,None),(0,'Passing Style'),(300,'Rest'),(600,'Not Available'),(32767,None)])
def test_signed_codes_zero_rest_notavailable_and_unknown_are_distinct(bridge,composed,code,name):
    m=composed;m['put'](m['training_wrapper_addresses'][0]+0x12,struct.pack('<h',code))
    result=query(bridge,day_count=1);slot=result['days'][0]['slots'][0]
    assert result['complete_stored_window'] and result['days'][0]['state']=='stored_assigned'
    assert slot=={'slot_index':0,'native_code':code,'english_definition_name':name,
                  'name_state':'named_installed_definition' if name else 'unmapped_native_code'}


@pytest.mark.parametrize('mode',['missing','different'])
def test_definition_resource_unavailable_preserves_raw_complete_week(bridge,composed,mode):
    resource=composed['resource_bundle']['resource']
    if mode=='missing':resource.unlink()
    else:resource.write_bytes(b'x'*len(RESOURCE_BYTES))
    result=query(bridge)
    assert result['complete_stored_window'] and result['source_state']=='available'
    for day,codes in zip(result['days'],CODES,strict=True):
        assert [s['native_code'] for s in day['slots']]==codes
        assert all(s['english_definition_name'] is None and s['name_state']=='unavailable_definition_resource' for s in day['slots'])


def test_first_native_duplicate_ignores_upper_bits_and_other_year(bridge,composed):
    m=composed;first=m['training_wrapper'](301,upper_bits=7,codes=[[300,300,300] for _ in range(7)])
    other=m['training_wrapper'](301,year=2031)
    m['set_training_weeks']([other,first,m['training_wrapper_addresses'][0]])
    result=query(bridge)
    assert all(d['native_wrapper_index']==1 and [s['native_code'] for s in d['slots']]==[300,300,300] for d in result['days'])


def test_only_selected_bodies_read_once_then_rechecked_and_cache_not_persistent(bridge,monkeypatch,composed):
    m=composed;unused=m['training_wrapper'](294);selected=m['training_wrapper_addresses'][0]
    m['set_training_weeks']([unused,selected]);reads=[];original=bridge._read_memory
    def checked(process,address,size):
        assert not (address<unused+0x48 and address+size>unused+0x10),'Unselected training body read'
        if address==selected+0x10 and size==56:reads.append(address)
        return original(process,address,size)
    monkeypatch.setattr(bridge,'_read_memory',checked)
    assert query(bridge)['days'][0]['slots'][0]['native_code']==108 and len(reads)==2
    m['put'](selected+0x12,struct.pack('<h',0))
    assert query(bridge)['days'][0]['slots'][0]['english_definition_name']=='Passing Style' and len(reads)==4


@pytest.mark.parametrize('fault',['owner_null','week_null','club_mismatch','tree_cycle','tree_count','vector_bounds','canonical_team'])
def test_malformed_owned_source_rejects_without_publishing_refs(bridge,composed,fault):
    m=composed
    if fault=='owner_null':m['vec'](m['training_manager']+0x38,[0])
    if fault=='week_null':m['set_training_weeks']([0])
    if fault=='club_mismatch':m['q'](m['training_owner']+0x98,m['club']+8)
    if fault=='tree_cycle':m['q'](m['training_team_node'],m['training_team_node'])
    if fault=='tree_count':m['q'](m['training_owner']+0x58,2)
    if fault=='vector_bounds':m['q'](m['training_team_node']+0x50,1)
    if fault=='canonical_team':
        start=struct.unpack('<Q',m['read'](m['headers']['teams'],8))[0];m['q'](start,m['team_addresses'][1])
    before=refs(bridge)
    with pytest.raises(BridgeError):query(bridge)
    assert refs(bridge)==before


@pytest.mark.parametrize('target',['gate','owner','club','team_key','wrapper_key','body','source_native','calendar_native','labels_native','current_date'])
def test_late_consumed_source_drift_rejects_whole_window(bridge,monkeypatch,composed,target):
    m=composed;original=calendar.decode
    def changing(*a,**kw):
        result=original(*a,**kw)
        address={'gate':m['training_source_gate'],'owner':m['training_owner']+0x90,'club':m['training_owner']+0x98,
          'team_key':m['training_team_node']+0x20,'wrapper_key':m['training_wrapper_addresses'][0]+0xC,
          'body':m['training_wrapper_addresses'][0]+0x12,'source_native':m['base']+source.NATIVE_SPANS[0][0],
          'calendar_native':m['base']+calendar.NATIVE_SPANS[0][0],'labels_native':m['base']+sessions.NATIVE_SPANS[0][0],
          'current_date':m['base']+world.CURRENT_DATE}[target]
        old=m['read'](address,1)[0];m['put'](address,bytes([old^1]));return result
    monkeypatch.setattr(calendar,'decode',changing);before=refs(bridge)
    with pytest.raises(BridgeError,match='changed|rejected'):query(bridge)
    assert refs(bridge)==before


@pytest.mark.parametrize('direction',['disappears','appears'])
def test_resource_availability_change_after_decode_rejects(bridge,monkeypatch,composed,direction):
    path=composed['resource_bundle']['resource'];original=calendar.decode
    if direction=='appears':path.unlink()
    def changing(*a,**kw):
        result=original(*a,**kw)
        if direction=='appears':path.write_bytes(RESOURCE_BYTES)
        else:path.unlink()
        return result
    monkeypatch.setattr(calendar,'decode',changing);before=refs(bridge)
    with pytest.raises(BridgeError,match='resource changed'):query(bridge)
    assert refs(bridge)==before


def test_late_process_restart_invalidates_session_and_refs(bridge,monkeypatch,composed):
    original=calendar.decode
    def restarting(*a,**kw):
        result=original(*a,**kw)
        monkeypatch.setattr(bridge_module,'process_info',lambda pid:replace(composed['fixture_process'],started='restarted'))
        return result
    monkeypatch.setattr(calendar,'decode',restarting)
    with pytest.raises(BridgeError,match='restart|changed|rejected'):query(bridge)
    assert bridge.session is None and not bridge.player_refs and not bridge.team_refs and not bridge.competition_refs


def test_team_and_club_native_ids_are_independent(bridge,composed):
    composed['put'](composed['team']+0xC,struct.pack('<I',900001))
    result=query(bridge,day_count=1)
    assert result['team']['native_id']==900001 and result['team']['owner']['native_id']!=900001
    assert result['days'][0]['slots'][0]['native_code']==108


def test_mcp_strict_window_schema_and_readonly():
    from fm_live_mcp.server import mcp
    tool=next(t for t in asyncio.run(mcp.list_tools()) if t.name=='fm_get_managed_training')
    assert tool.inputSchema['required']==['session_id']
    assert set(tool.inputSchema['properties'])=={'session_id','coach_name','start_date','day_count'}
    count=tool.inputSchema['properties']['day_count'];assert count['type']=='integer' and count['default']==7
    assert count['minimum']==1 and count['maximum']==366
    assert tool.annotations.readOnlyHint is True and tool.annotations.destructiveHint is False and tool.annotations.openWorldHint is False
