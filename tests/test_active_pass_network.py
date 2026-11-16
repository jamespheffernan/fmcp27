import copy
from contextlib import nullcontext
import struct
from unittest.mock import Mock

import pytest
from fm_live_mcp import active_pass_network as passes


def event(identity=0, *, side=0, sender=0, receiver=1, start=10, end=20, category=7, flags=0):
    raw=bytearray(56);raw[39:43]=bytes((sender,side,receiver,category))
    struct.pack_into('<H',raw,34,start);struct.pack_into('<I',raw,44,identity)
    struct.pack_into('<HH',raw,48,flags,end)
    return bytes(raw)


def actors():
    return {'state':'validated_native_stored_slots','official_match_unique_id':42,
            'players':[{'side_index':side,'stored_player_slot':slot,
                        'canonical_person_id':100+10*side+slot,'person_index_word':500+10*side+slot,
                        'person_name':f'Person{side}-{slot}'}for side in (0,1)for slot in (0,1)],'unresolved':[]}


def fixture():
    return {'date':'2030-11-06','competition':{'native_id':9},
            'home_team':{'native_id':1,'database_index':101},'away_team':{'native_id':2,'database_index':102},
            'scores':{'normal_time':{'home':9,'away':8}}}


def bound(cursor=100):
    return {'current_time_slice':cursor,'buffered_max_time_slice':200,'official_match_unique_id':42,
            'playback_address':50000,'frame_provider_address':60000,'source_match_address':20000,'local_playback_handle':42}


def packet():
    return {'fixture':fixture(),'binding':{'client':10000,'engine':20000,'team_indices':[101,102]},
            'bound':bound(),'actors':actors(),'source':{'state':'available','events':passes.select_events(event(),100),
             'fixture_identity':('same',),'match_unique_id':42,'cbe':30000}}


def test_active_native_end_cursor_excludes_ties_future_and_crossed_actions():
    raw=event(0,start=0,end=99)+event(1,start=10,end=100)+event(2,start=99,end=101)
    assert [e['event_id']for e in passes.select_events(raw,100)]==[0]
    with pytest.raises(ValueError,match='reversed'):passes.select_events(event(start=99,end=90),100)
    with pytest.raises(ValueError,match='domain'):passes.select_events(raw,65536)


def test_future_actor_category_and_vector_pointer_changes_do_not_change_consumed_selection():
    raw=event(0)+event(1,start=110,end=120,sender=25,receiver=25)
    other=bytearray(raw);other[56:80]=b'x'*24;other[56+39]=22
    assert passes.select_events(raw,100)==passes.select_events(bytes(other),100)
    # Past point-vector relocation is not a graph input either.
    other[:24]=b'z'*24
    assert passes.select_events(raw,100)==passes.select_events(bytes(other),100)


def test_complete_named_side_pairs_conserve_selected_completed_events_without_denominator():
    raw=event(0)+event(1)+event(2,side=1)+event(3,flags=8)+event(4,category=10)
    result=passes.project(passes.select_events(raw,100),actors(),fixture(),cursor=100,match_unique_id=42)
    assert result['state']=='available'
    assert [s['source_completed_pass_event_count']for s in result['sides']]==[2,1]
    assert result['sides'][0]['pairs']==[{'from_person_native_id':100,'from_name':'Person0-0',
        'to_person_native_id':101,'to_name':'Person0-1','native_completed_pass_event_count':2}]
    assert all(s['passes_attempted'] is s['official_passes_completed'] is s['completion_percentage'] is None for s in result['sides'])
    assert 'scores'not in result['fixture']
    assert result['displayed_minute'] is result['coordinates'] is result['phase'] is None


def test_missing_actor_withholds_that_side_not_a_false_zero_or_weaker_top_pair():
    result=passes.project(passes.select_events(event()+event(1,receiver=7),100),actors(),fixture(),cursor=100,match_unique_id=42)
    side=result['sides'][0]
    assert side['state']=='unavailable_actor_coverage' and side['pairs']==[]
    assert side['source_completed_pass_event_count']==2 and side['named_completed_pass_event_count']==1
    assert side['unresolved_events']==[{'event_id':1,'state':'unresolved_same_side_original_slot_actor'}]
    assert result['sides'][1]['state']=='available' and result['sides'][1]['source_completed_pass_event_count']==0


def test_original_roster_slot_not_current_tactical_index_or_cross_side_guess():
    a=actors();a['players'][0]['tactics_index_raw']=17
    r=passes.project(passes.select_events(event(),100),a,fixture(),cursor=100,match_unique_id=42)
    assert r['sides'][0]['pairs'][0]['from_person_native_id']==100
    a['players']=[p for p in a['players']if not(p['side_index']==0 and p['stored_player_slot']==1)]
    r=passes.project(passes.select_events(event(),100),a,fixture(),cursor=100,match_unique_id=42)
    assert r['sides'][0]['pairs']==[]  # Away slot1 cannot fill absent home slot1.


def test_actor_duplicate_wrong_match_unknown_name_and_event_corruption_fail_closed():
    a=actors();a['players'].append(dict(a['players'][0]))
    with pytest.raises(ValueError,match='duplicate'):passes.project([],a,fixture(),cursor=100,match_unique_id=42)
    with pytest.raises(ValueError,match='another match'):passes.project([],actors(),fixture(),cursor=100,match_unique_id=43)
    a=actors();a['players'][0]['person_name']=None
    assert passes.project(passes.select_events(event(),100),a,fixture(),cursor=100,match_unique_id=42)['sides'][0]['pairs']==[]
    with pytest.raises(ValueError,match='Duplicate'):passes.select_events(event()+event(),100)
    with pytest.raises(ValueError,match='side'):passes.select_events(event(side=2),100)
    with pytest.raises(ValueError,match='extent'):passes.select_events(b'x',100)


def mock_verify(monkeypatch, p):
    monkeypatch.setattr(passes.active_match_playback,'capture',lambda *a,**kw:{'state':'bound_playback_cursor','bound_playback':bound(105)})
    monkeypatch.setattr(passes.active_match_source,'inspect_context',lambda *a,**kw:({'bound_active_fixture':p['fixture']},p['binding']))
    monkeypatch.setattr(passes,'capture_source',lambda *a,**kw:copy.deepcopy(p['source']))
    monkeypatch.setattr(passes.active_match_people,'inspect_actor_bindings',lambda *a,**kw:copy.deepcopy(p['actors']))
    q={20000+0x154dc:200,20000+0x20:42,10000+0x138:42,20000+0x14e98:30000,10000+0xf8:40000,40000+0x18:20000}
    return lambda address,n:struct.pack('<I'if n==4 else'<Q',q[address])


def test_monotonic_same_match_prefix_reprojection_allows_progression(monkeypatch):
    p=packet();read=mock_verify(monkeypatch,p)
    result=passes._verify_components(read,0,'2030-11-06',p)
    assert result['fixed_time_slice']==100 and result['verified_at_time_slice']==105


@pytest.mark.parametrize('mutation',['late_past_event','past_actor','side','owner','backward','new_match'])
def test_changed_consumed_prefix_actor_owner_and_seek_reject(monkeypatch,mutation):
    p=packet();read=mock_verify(monkeypatch,p)
    if mutation=='late_past_event':
        changed=copy.deepcopy(p['source']);changed['events']=passes.select_events(event()+event(1),100)
        monkeypatch.setattr(passes,'capture_source',lambda *a,**kw:changed)
    elif mutation=='past_actor':
        changed=actors();changed['players'][0]['canonical_person_id']=999
        monkeypatch.setattr(passes.active_match_people,'inspect_actor_bindings',lambda *a,**kw:changed)
    elif mutation=='side':
        changed=copy.deepcopy(p['source']);changed['events'][0]['side_index']=1
        monkeypatch.setattr(passes,'capture_source',lambda *a,**kw:changed)
    elif mutation=='owner':
        monkeypatch.setattr(passes.active_match_source,'inspect_context',lambda *a,**kw:({'reason':'gone'},None))
    else:
        b=bound(99 if mutation=='backward' else 105)
        if mutation=='new_match':b['official_match_unique_id']=43
        monkeypatch.setattr(passes.active_match_playback,'capture',lambda *a,**kw:{'state':'bound_playback_cursor','bound_playback':b})
    with pytest.raises(ValueError):passes._verify_components(read,0,'2030-11-06',p)


def test_unconsumed_future_actor_change_does_not_reject_prefix(monkeypatch):
    p=packet();read=mock_verify(monkeypatch,p)
    a=actors();a['players'][2]['canonical_person_id']=999
    monkeypatch.setattr(passes.active_match_people,'inspect_actor_bindings',lambda *args,**kw:a)
    assert passes._verify_components(read,0,'2030-11-06',p)['state'].startswith('verified')


def test_empty_current_client_never_falls_back_to_old_engine_or_retained_source(monkeypatch):
    monkeypatch.setattr(passes.active_match_source,'inspect_context',lambda *a,**kw:({'source_state':'inactive','reason':'checked_empty_viewable_client_inventory'},None))
    monkeypatch.setattr(passes.active_match_playback,'capture',Mock(side_effect=AssertionError))
    result,p=passes._capture_components(Mock(),0,'2030-11-06')
    assert result['state']=='unavailable'and result['sides']is None and p is None


def test_native_pass_specific_common_constructor_drift_rejected():
    with pytest.raises(ValueError,match='native source changed'):
        passes.capture_source(lambda a,n:bytes(n),0,10000,20000,fixed_cursor=100)


def test_optional_tool_schema_dispatch_and_honest_count_scope(monkeypatch):
    import asyncio
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp import active_pass_tools as tools
    calls=[]
    monkeypatch.setattr(tools,'current_pass_network',lambda *a:(calls.append(a)or {'state':'unavailable'}))
    async def check():
        mcp=FastMCP('test');tools.register_active_pass_tools(mcp,None)
        tool=next(t for t in await mcp.list_tools() if t.name=='fm_get_current_match_pass_network')
        assert tool.name=='fm_get_current_match_pass_network'
        assert tool.outputSchema is not None
        assert set(tool.inputSchema['properties'])=={'session_id'}
        assert tool.annotations.readOnlyHint and 'denominators'in tool.description
        await mcp.call_tool(tool.name,{'session_id':'s'})
        assert calls==[(None,'s')]
    asyncio.run(check())


def test_real_active_newcastle_forest_native_bytes_conserve_all_named_pairs():
    import gzip,json
    from pathlib import Path
    p=json.load(gzip.open(Path(__file__).parent/'fixtures/active_newcastle_forest_pass_network.json.gz','rt'))
    selected=passes.select_events(bytes.fromhex(p['raw_events_hex']),p['bound']['current_time_slice'])
    out=passes.project(selected,p['actors'],p['fixture'],cursor=p['bound']['current_time_slice'],match_unique_id=p['bound']['official_match_unique_id'])
    assert out==p['expected_projection']
    assert [r['source_completed_pass_event_count']for r in out['sides']]==[113,83]
    assert [len(r['pairs'])for r in out['sides']]==[49,39]
    assert all(sum(x['native_completed_pass_event_count']for x in r['pairs'])==r['source_completed_pass_event_count']for r in out['sides'])
    assert [sum(e['side_index']==side and e['category']==7 and bool(e['flags_word']&8)for e in selected)for side in(0,1)]==[3,4]


def test_real_active_raw_future_append_does_not_change_fixed_network():
    import gzip,json
    from pathlib import Path
    p=json.load(gzip.open(Path(__file__).parent/'fixtures/active_newcastle_forest_pass_network.json.gz','rt'))
    raw=bytes.fromhex(p['raw_events_hex']);cursor=p['bound']['current_time_slice']
    future=event(999999,start=cursor+1,end=cursor+10,sender=25,receiver=25)
    assert passes.select_events(raw,cursor)==passes.select_events(raw+future,cursor)


@pytest.mark.parametrize('wrong_source',[False,True])
def test_source_statistics_fixture_must_match_independent_current_context(monkeypatch,wrong_source):
    f=fixture();binding={'client':10000,'engine':20000,'team_indices':[101,102]}
    monkeypatch.setattr(passes.active_match_source,'inspect_context',lambda *a,**k:({'source_state':'available_fixture_bound','bound_active_fixture':f},binding))
    monkeypatch.setattr(passes.active_match_playback,'capture',lambda *a,**k:{'state':'bound_playback_cursor','bound_playback':bound()})
    monkeypatch.setattr(passes.active_match_people,'inspect_actor_bindings',lambda *a,**k:actors())
    identity=(f['date'],f['competition']['native_id'],(101,1),(102,2))
    if wrong_source:identity=(f['date'],99,(101,1),(102,2))
    monkeypatch.setattr(passes,'capture_source',lambda *a,**k:{'state':'available','events':[],
        'match_unique_id':42,'fixture_identity':identity})
    if wrong_source:
        with pytest.raises(ValueError,match='statistics fixture differs'):passes._capture_components(Mock(),0,'2030-11-06')
    else:
        result,p=passes._capture_components(Mock(),0,'2030-11-06')
        assert result['state']=='available'and p['source']['fixture_identity']==identity


def test_final_engine_frontier_must_still_cover_fixed_prefix(monkeypatch):
    p=packet();original=mock_verify(monkeypatch,p)
    def read(address,n):
        if address==20000+0x154dc:return struct.pack('<I',99)
        return original(address,n)
    with pytest.raises(ValueError,match='owner changed after'):
        passes._verify_components(read,0,'2030-11-06',p)
