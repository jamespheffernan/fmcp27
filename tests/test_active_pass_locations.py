from contextlib import nullcontext
from copy import deepcopy
import struct
from unittest.mock import Mock

import pytest
from fm_live_mcp import active_pass_locations as locations, active_pass_network as network
from test_active_pass_network import event, actors, fixture, packet


def located_event(identity=0, **kwargs):
    e=bytearray(event(identity, **kwargs));struct.pack_into('<ff',e,24,10.0,20.0);return bytes(e)


def source(n=3):
    p=packet();p['source']['events']=network.select_events(b''.join(located_event(i) for i in range(n)),100,include_locations=True)
    p['source']['pitch_geometry']={'half_width_native':32.5,'half_length_native':50.0}
    r=network.project(p['source']['events'],p['actors'],p['fixture'],cursor=100,match_unique_id=42)
    r.update(source_id='fixed',observed_at='now',prefix_verification={'verified_at_time_slice':101})
    return r,p,('epoch',)


def test_locations_use_same_canonical_completed_actor_and_native_location_only():
    r,p,_=source();rows=locations.project(p,r)
    assert len(rows)==3 and rows[0]['from_person_native_id']==100 and rows[0]['to_person_native_id']==101
    assert rows[0]['native_pass_map_location']=={'native_x':10.0,'native_y':20.0}
    assert rows[0]['attack_relative_longitudinal_coordinate']==-20.0
    assert rows[0]['analytical_pitch_third']=='defensive'
    assert not any(k in rows[0]for k in ('reception_location','trajectory','ball_release_location'))


def test_future_geometry_ignored_but_consumed_geometry_changes_comparison():
    a=located_event()+located_event(1,start=100,end=110)
    b=bytearray(a);struct.pack_into('<ff',b,56+24,float('nan'),99)
    assert network.select_events(a,100,include_locations=True)==network.select_events(bytes(b),100,include_locations=True)
    struct.pack_into('<ff',b,24,11,20)
    assert network.select_events(a,100,include_locations=True)!=network.select_events(bytes(b),100,include_locations=True)
    assert network.select_events(a,100)==network.select_events(bytes(b),100)


def test_unresolved_side_events_withheld_not_zero_or_invented_locations():
    r,p,_=source();r['sides'][0]['state']='unavailable_actor_coverage'
    assert locations.project(p,r)==[]


def test_mask8_incomplete_and_cursor_ties_never_gain_locations():
    raw=located_event(0,flags=8)+located_event(1,category=6)+located_event(2,end=100)+located_event(3)
    selected=network.select_events(raw,100,include_locations=True)
    assert [e['event_id']for e in selected if 'location_xy_hex'in e]==[3]


def test_nonfinite_consumed_coordinates_fail_closed():
    r,p,_=source();p['source']['events'][0]['location_xy_hex']=struct.pack('<ff',float('nan'),1).hex()
    with pytest.raises(ValueError,match='Nonfinite'):locations.project(p,r)


def test_pages_immutable_all_numbered_rows_and_same_capture_without_recapture(monkeypatch):
    locations._CACHE.clear();r,p,e=source(205);capture=Mock(return_value=(r,p,e));monkeypatch.setattr(network,'current_pass_network',capture)
    verify=Mock();monkeypatch.setattr(locations,'_verify_page',verify);bridge=Mock();bridge.lock=nullcontext()
    first=locations.current_pass_events(bridge,'s',limit=100);second=locations.current_pass_events(bridge,'s',limit=100,cursor=first['next_cursor']);third=locations.current_pass_events(bridge,'s',limit=100,cursor=second['next_cursor'])
    assert [len(x['events'])for x in (first,second,third)]==[100,100,5]
    assert [x['event_id']for page in (first,second,third)for x in page['events']]==list(range(205))
    assert capture.call_count==1 and verify.call_count==2 and third['next_cursor']is None
    assert first['capture_id']==third['capture_id']=='fixed' and first['captured_observed_at']==third['captured_observed_at']=='now'
    first['events'][0]['from_name']='edited'
    replay=locations.current_pass_events(bridge,'s',limit=100,cursor=second['next_cursor'])
    assert replay['events'][0]['from_name']!='edited'
    with pytest.raises(ValueError,match='session or selectors'):locations.current_pass_events(bridge,'other',limit=100,cursor=second['next_cursor'])
    with pytest.raises(ValueError,match='session or selectors'):locations.current_pass_events(bridge,'s',limit=99,cursor=second['next_cursor'])


def test_validation_before_read_and_expired_cursor(monkeypatch):
    locations._CACHE.clear();bridge=Mock();bridge.lock=nullcontext()
    for kw in ({'limit':101},{'team_native_id':True},{'from_person_native_id':-1}):
        with pytest.raises(ValueError):locations.current_pass_events(bridge,'s',**kw)
    with pytest.raises(ValueError,match='expired'):locations.current_pass_events(bridge,'s',cursor='unknown')
    assert not bridge._current.called


def test_filters_exact_direction_and_team(monkeypatch):
    r,p,e=source();capture=Mock(return_value=(r,p,e));monkeypatch.setattr(network,'current_pass_network',capture);bridge=Mock();bridge.lock=nullcontext()
    result=locations.current_pass_events(bridge,'s',team_native_id=1,from_person_native_id=100,to_person_native_id=101)
    assert result['total_selected_events']==3
    assert locations.current_pass_events(bridge,'s',from_person_native_id=101,to_person_native_id=100)['events']==[]
    with pytest.raises(ValueError,match='participate'):locations.current_pass_events(bridge,'s',team_native_id=99)


@pytest.mark.parametrize('field',['location','geometry'])
def test_changed_consumed_location_or_geometry_rejects_fixed_prefix(monkeypatch,field):
    from test_active_pass_network import mock_verify
    _,p,_=source();read=mock_verify(monkeypatch,p);changed=deepcopy(p['source'])
    if field=='location':changed['events'][0]['location_xy_hex']=struct.pack('<ff',11,20).hex()
    else:changed['pitch_geometry']['half_width_native']=33
    monkeypatch.setattr(network,'capture_source',lambda *a,**kw:changed)
    with pytest.raises(ValueError,match='prefix changed|geometry changed'):network._verify_components(read,0,'2030-11-06',p)


def test_actual_same_playthrough_1020_events_and_earlier815_prefix_geometry_exact():
    import gzip,json
    from pathlib import Path
    from collections import Counter
    f=json.loads(gzip.decompress((Path(__file__).parent/'fixtures/active_pass_locations_185.json.gz').read_bytes()))
    raw=bytes.fromhex(f['raw_event_hex']);earlier=bytes.fromhex(f['raw184_event_hex'])
    assert network.select_events(raw,f['prefix_cursor'],include_locations=True)==network.select_events(earlier,f['prefix_cursor'],include_locations=True)
    events=network.select_events(raw,f['cursor'],include_locations=True)
    r=network.project(events,f['actors'],f['fixture'],cursor=f['cursor'],match_unique_id=f['match_unique_id'])
    p={'actors':f['actors'],'source':{'events':events,'pitch_geometry':f['pitch_geometry']}}
    rows=locations.project(p,r);assert len(rows)==1020
    by_id={x['event_id']:x for x in rows};independent=Counter()
    width,length=f['pitch_geometry']['half_width_native'],f['pitch_geometry']['half_length_native']
    for offset in range(0,len(raw),56):
        e=raw[offset:offset+56]
        if e[42]!=7 or int.from_bytes(e[48:50],'little')&8 or int.from_bytes(e[50:52],'little')>=f['cursor']:continue
        i=int.from_bytes(e[44:48],'little');x,y=struct.unpack_from('<ff',e,24);row=by_id[i]
        assert row['native_pass_map_location']=={'native_x':x,'native_y':y}
        assert row['stored_player_slot']==e[39]and row['recipient_slot']==e[41]and row['native_flags_word']==int.from_bytes(e[48:50],'little')
        forward=y if int.from_bytes(e[48:50],'little')&256 else -y
        third=('defensive'if forward < -length/3 else 'middle'if forward < length/3 else 'attacking')if abs(x)<=width and abs(y)<=length else None
        assert row['analytical_pitch_third']==third;independent[row['team_native_id']]+=1
    assert dict(independent)=={688:508,692:512}
    pair=[r for r in rows if r['from_person_native_id']==37076141 and r['to_person_native_id']==79034187]
    assert len(pair)==28


def test_requested_unresolved_side_is_unknown_not_empty(monkeypatch):
    r,p,e=source();r['state']='available_partial';r['sides'][0]['state']='unavailable_actor_coverage'
    monkeypatch.setattr(network,'current_pass_network',Mock(return_value=(r,p,e)));bridge=Mock();bridge.lock=nullcontext()
    result=locations.current_pass_events(bridge,'s',team_native_id=1)
    assert result['events']is None and result['total_selected_events']is None and result['state']=='unavailable_actor_coverage'


def test_page_guard_checks_epoch_and_late_world_change(monkeypatch):
    from fm_live_mcp import players
    bridge=Mock();bridge.lock=nullcontext();bridge._read_scope.return_value=nullcontext();process=Mock(pid=1,version='v',executable='binary');layout=(players.RVA[0],);bridge.world_identity='career'
    bridge._current.return_value=process;bridge._player_layout.return_value=layout;bridge._world_state.return_value=(Mock(),{'current_date':'2030-11-06'},None)
    r,p,_=source();snap={'packet':p,'epoch':(1,'v','binary',layout,'career'),'last_cursor':101}
    verify=Mock(return_value={'verified_at_time_slice':105});monkeypatch.setattr(network,'_verify_components',verify)
    locations._verify_page(bridge,'s',snap);assert snap['last_cursor']==105
    verify.return_value={'verified_at_time_slice':104}
    with pytest.raises(ValueError,match='rewind'):locations._verify_page(bridge,'s',snap)
    bridge.world_identity='newcareer'
    with pytest.raises(ValueError,match='career change'):locations._verify_page(bridge,'s',snap)
    bridge.world_identity='career';verify.return_value={'verified_at_time_slice':106}
    bridge._player_layout.side_effect=[layout,(players.RVA[0]+8,)]
    with pytest.raises(ValueError,match='epoch changed'):locations._verify_page(bridge,'s',snap)


def test_new_tool_catalog_keeps_network_inputs_and_bounded_events(monkeypatch):
    import asyncio
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp import active_pass_tools as tools
    seen=[];monkeypatch.setattr(tools,'current_pass_events',lambda *a,**kw:(seen.append((a,kw))or{'state':'unavailable'}))
    async def check():
        mcp=FastMCP('locations');tools.register_active_pass_tools(mcp,None);catalog={t.name:t for t in await mcp.list_tools()}
        assert set(catalog['fm_get_current_match_pass_network'].inputSchema['properties'])=={'session_id'}
        t=catalog['fm_get_current_match_pass_events'];assert t.annotations.readOnlyHint
        assert set(t.inputSchema['properties'])=={'session_id','team_native_id','from_person_native_id','to_person_native_id','limit','cursor','pass_outcome'}
        assert t.inputSchema['properties']['pass_outcome']['default']=='completed'
        assert t.inputSchema['properties']['pass_outcome']['enum']==['completed','not_completed','all']
        await mcp.call_tool(t.name,{'session_id':'s','team_native_id':2,'limit':10})
        assert seen[0][1]['team_native_id']==2 and seen[0][1]['limit']==10
    asyncio.run(check())


def test_actual_1020_event_pagination_routes_every_row_once_without_new_capture(monkeypatch):
    import gzip,json
    from pathlib import Path
    f=json.loads(gzip.decompress((Path(__file__).parent/'fixtures/active_pass_locations_185.json.gz').read_bytes()))
    events=network.select_events(bytes.fromhex(f['raw_event_hex']),f['cursor'],include_locations=True)
    r=network.project(events,f['actors'],f['fixture'],cursor=f['cursor'],match_unique_id=f['match_unique_id'])
    r.update(source_id='actual-fixed',observed_at='original-observation',prefix_verification={'verified_at_time_slice':f['cursor']})
    p={'actors':f['actors'],'source':{'events':events,'pitch_geometry':f['pitch_geometry']}}
    capture=Mock(return_value=(r,p,('epoch',)));monkeypatch.setattr(network,'current_pass_network',capture)
    guard=Mock();monkeypatch.setattr(locations,'_verify_page',guard);locations._CACHE.clear();bridge=Mock();bridge.lock=nullcontext()
    pages=[locations.current_pass_events(bridge,'s',limit=100)]
    while pages[-1]['next_cursor']:pages.append(locations.current_pass_events(bridge,'s',limit=100,cursor=pages[-1]['next_cursor']))
    rows=[r for page in pages for r in page['events']]
    assert len(pages)==11 and len(rows)==len({r['event_id']for r in rows})==1020
    assert capture.call_count==1 and guard.call_count==10
    assert all(p['capture_id']=='actual-fixed'and p['captured_observed_at']=='original-observation'for p in pages)
