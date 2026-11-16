import copy,gzip,hashlib,json,struct
from pathlib import Path
import pytest
from fm_live_mcp.retained_possession_events import decode_possession_events,verify_native,NATIVE_SPANS


def packet():
    with gzip.open(Path(__file__).parent/'fixtures/possession_events_forest_2030_11_11.json.gz','rt')as f:return json.load(f)


def decode(p):
    return decode_possession_events(bytes.fromhex(p['events_hex']),p['players'],p['fixture'],native_match_key=p['native_match_key'],pitch_geometry=p['pitch_geometry'])


def test_genuine_forest_complete_both_sides_every_player_including_zeros():
    out=decode(packet());assert out['state']=='available'
    assert out['native_event_count']==1965 and len(out['events'])==354
    assert [(s['possession_won'],s['possession_lost'],s['captured_player_counter_checks'])for s in out['sides']]==[(92,89,20),(75,98,20)]
    assert all(c['counts_match']for s in out['sides']for c in s['player_checks'])
    assert any(c['possession_won']==c['possession_lost']==0 for s in out['sides']for c in s['player_checks'])
    assert all(r['transition_location']is r['pressure_regain']is r['press_played_through']is r['other_player_native_id']is None for r in out['events'])
    assert all(r['source_native_anchor']is not None for r in out['events'])


@pytest.mark.parametrize('mutation',['counter','team','fixture','hash','slot','person','name'])
def test_incorrect_source_identity_or_counter_rejects(mutation):
    p=packet();r=p['players'][0]
    if mutation=='counter':r['possession_won']+=1
    elif mutation=='team':r['canonical_team_id']+=1
    elif mutation=='fixture':r['fixture_key']+=1
    elif mutation=='hash':r['row_sha256']='0'*64
    elif mutation=='slot':p['players'].append(copy.deepcopy(r))
    elif mutation=='name':r['person_name']=None
    else:r['person_index_word']+=1
    with pytest.raises(ValueError):decode(p)


def test_missing_event_withholds_only_affected_side_no_zero_fill():
    p=packet();raw=bytes.fromhex(p['events_hex']);records=[raw[i:i+56]for i in range(0,len(raw),56)]
    index=next(i for i,e in enumerate(records)if e[42]==52 and e[40]==0)
    del records[index];p['events_hex']=b''.join(records).hex();out=decode(p)
    assert out['state']=='partial'and out['sides'][0]['possession_won']is None
    assert out['sides'][1]['possession_won']==75 and all(r['side_index']==1 for r in out['events'])


def test_missing_actor_withholds_side_and_duplicate_ids_reject():
    p=packet();out=decode(p);actor=out['events'][0]
    p['players']=[x for x in p['players']if(x['side_index'],x['stored_player_slot'])!=(actor['side_index'],actor['stored_player_slot'])]
    assert decode(p)['sides'][actor['side_index']]['possession_won']is None
    p=packet();p['events_hex']+=p['events_hex'][:112]
    with pytest.raises(ValueError,match='Duplicate'):decode(p)


def test_native_span_changes_reject():
    spans=dict(NATIVE_SPANS)
    verify_native(lambda a,n:spans[a],0)
    with pytest.raises(ValueError):verify_native(lambda a,n:b'\0'*n,0)


def test_geometry_is_raw_anchor_not_transition_or_bins():
    out=decode(packet());assert all('analytical_pitch_third'not in r for r in out['events'])
    p=packet();p['pitch_geometry']=None
    assert all(r['source_native_anchor']['inside_native_pitch_extents']is None for r in decode(p)['events'])
    p=packet();p['pitch_geometry']['half_width_native']=float('nan')
    with pytest.raises(ValueError):decode(p)


def test_sdk_schema_structured_output_and_readonly():
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp.retained_possession_tools import register_retained_possession_tools
    import asyncio
    m=FastMCP();register_retained_possession_tools(m,object())
    tool=asyncio.run(m.list_tools())[0]
    assert tool.name=='fm_get_retained_possession_events'and tool.outputSchema
    assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint


def service(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from fm_live_mcp import retained_possession_events as q,match_data_query,live_match_backing,live_match_team_totals,live_match_players,live_retained_shots
    p=packet();f={**p['fixture'],'fixture_ref':'f'}
    bridge=SimpleNamespace(lock=nullcontext(),_read_scope=lambda s:nullcontext(),_current=lambda s:None,
       _player_layout=lambda p:(0,),_world_state=lambda *a:(SimpleNamespace(verify=lambda:None),{},None),get_save=lambda s:{'save':{'current_date':'2030-11-11'}})
    monkeypatch.setattr(match_data_query,'capture_epoch',lambda *a:('epoch',))
    monkeypatch.setattr(q,'verify_native',lambda *a:None)
    monkeypatch.setattr(live_match_backing,'read_selected_matches',lambda *a,**k:{'records':[{'state':'available','fixture_ref':'f','fixture_native':f,'key':p['native_match_key'],'raw':b'raw'}]})
    teams=[{'team_index':f[k]['database_index'],'team_identity_word':f[k]['native_id']}for k in('home_team','away_team')]
    monkeypatch.setattr(live_match_team_totals,'decode_team_totals',lambda raw:{'result_key':p['native_match_key'],'teams':teams})
    monkeypatch.setattr(live_match_players,'project_frame',lambda *a:{'coverage':{'complete_side_sections':True,'stored_rows_per_side':[20,20]}})
    monkeypatch.setattr(live_retained_shots,'_actor_rows',lambda *a:p['players'])
    source={'state':'available','events':bytes.fromhex(p['events_hex']),'pitch_geometry':p['pitch_geometry']}
    monkeypatch.setattr(live_retained_shots,'capture_source',lambda *a,**k:source)
    return q,bridge,source



def test_getter_paging_scopes_pin_and_reload(monkeypatch):
    q,b,source=service(monkeypatch)
    full=q.get_retained_possession_events(b,'s','f')
    assert full['state']=='available' and full['total_count']==354
    first=q.get_retained_possession_events(b,'s','f',team_native_id=688,limit=2)
    assert first['total_count']==181 and first['next_offset']==2
    second=q.get_retained_possession_events(b,'s','f',team_native_id=688,limit=2,offset=2,expected_source_id=first['source_id'])
    assert not {r['event_id'] for r in first['events']} & {r['event_id'] for r in second['events']}
    with pytest.raises(ValueError,match='continuation'):q.get_retained_possession_events(b,'s','f',offset=1)
    with pytest.raises(ValueError,match='not in'):q.get_retained_possession_events(b,'s','f',team_native_id=123)
    source['pitch_geometry']={**source['pitch_geometry'],'half_width_native':35.}
    with pytest.raises(ValueError,match='source or selectors changed'):
        q.get_retained_possession_events(b,'s','f',team_native_id=688,offset=2,expected_source_id=first['source_id'])
    from fm_live_mcp import match_data_query,live_match_players
    q,b,_=service(monkeypatch)
    monkeypatch.setattr(live_match_players,'project_frame',lambda *a:{'coverage':{'complete_side_sections':True,'stored_rows_per_side':[20,19]}})
    with pytest.raises(ValueError,match='full roster count'):q.get_retained_possession_events(b,'s','f')
    q,b,_=service(monkeypatch);epochs=iter([('epoch',),('reloaded',)])
    monkeypatch.setattr(match_data_query,'capture_epoch',lambda *a:next(epochs))
    with pytest.raises(ValueError,match='epoch changed'):q.get_retained_possession_events(b,'s','f')


def test_unretained_source_preserves_unknown_counts(monkeypatch):
    q,b,source=service(monkeypatch);source['state']='unavailable_no_retained_cbe'
    out=q.get_retained_possession_events(b,'s','f')
    assert out['state']=='unavailable_no_retained_cbe' and out['total_count']is None and out['events']==[]


# --- orientation: the retained record's own profile, published where tracking agrees ---------------
from fm_live_mcp.retained_possession_events import decode_orientation,THIRDS  # noqa: E402

# Newcastle's away match of 4 January 2031 (first boundary 11492, second 23606, side 0 starts positive)
# and the home match of 21 December 2030 (side 1 starts positive), as read on 13 November 2026.
PROFILE_SIDE0_POSITIVE=bytes.fromhex('e42c0000365c0000ffffffff00010000')
PROFILE_SIDE1_POSITIVE=bytes.fromhex('622c0000e95e0000ffffffff00000000')


def tracking(profile,keeper_y,*,ticks=23000,outfield_y=12.0):
    """Two tracked players a side: a goalkeeper at keeper_y[side][period] and an outfield player."""
    first=struct.unpack_from('<i',profile)[0];rows=[]
    for side in(0,1):
        for slot,depth in((0,None),(5,outfield_y)):
            samples=b''
            for tick in range(0,ticks,24):
                y=keeper_y[side][tick>=first]if depth is None else depth
                samples+=struct.pack('<hh',100,int(y*100))
            rows.append(dict(side_index=side,stored_player_slot=slot,start_tick=0,samples=samples))
    return dict(state='available',orientation_profile=profile,possession_samples=b'',players=rows)


def test_orientation_periods_and_defended_ends_from_profile_with_tracking_witness():
    out=decode_orientation(tracking(PROFILE_SIDE0_POSITIVE,{0:(-44.0,44.0),1:(44.0,-44.0)}))
    assert out['state']=='available'and out['ends_change_ticks']==[11492,23606,-1]and out['clock_domain']=='native_playback_time_slice'
    # the second boundary ends normal time: no extra-time period without tracking after it
    assert [(p['period'],p['start_tick'],p['end_tick_exclusive'])for p in out['periods']]==[('first_half',0,11492),('second_half',11492,23606)]
    ends=[[s['defended_end']for s in p['sides']]for p in out['periods']]
    assert ends==[['negative_native_y','positive_native_y'],['positive_native_y','negative_native_y']]
    assert all(s['state']=='verified_tracking_witness'and s['deepest_tracked_player']['stored_player_slot']==0 for p in out['periods']for s in p['sides'])
    other=decode_orientation(tracking(PROFILE_SIDE1_POSITIVE,{0:(44.0,-44.0),1:(-44.0,44.0)}))
    assert [[s['defended_end']for s in p['sides']]for p in other['periods']]==[['positive_native_y','negative_native_y'],['negative_native_y','positive_native_y']]


def test_orientation_is_withheld_when_the_witness_disagrees_is_shallow_or_missing():
    wrong=decode_orientation(tracking(PROFILE_SIDE0_POSITIVE,{0:(44.0,44.0),1:(44.0,-44.0)}))
    side0=[p['sides'][0]for p in wrong['periods']]
    assert [s['state']for s in side0]==['unverified_tracking_witness_disagrees','verified_tracking_witness']
    assert side0[0]['defended_end']is None and side0[0]['profile_defended_end']=='negative_native_y'
    shallow=decode_orientation(tracking(PROFILE_SIDE0_POSITIVE,{0:(-20.0,20.0),1:(44.0,-44.0)}))
    assert [p['sides'][0]['defended_end']for p in shallow['periods']]==[None,None]
    empty=dict(state='unavailable_no_retained_tracking',orientation_profile=PROFILE_SIDE0_POSITIVE,possession_samples=b'',players=[])
    assert {s['state']for p in decode_orientation(empty)['periods']for s in p['sides']}=={'unverified_no_tracking_witness'}
    assert decode_orientation(None)['state']=='unavailable_no_orientation_profile'
    assert decode_orientation(dict(orientation_profile=b'\xff'*12+bytes(4),players=[]))['state']=='unavailable_no_period_boundary'
    with pytest.raises(ValueError):decode_orientation(dict(orientation_profile=struct.pack('<iii',500,400,-1)+bytes(4),players=[]))
    with pytest.raises(ValueError):decode_orientation(dict(orientation_profile=bytes(15),players=[]))
    extra=decode_orientation(tracking(PROFILE_SIDE0_POSITIVE,{0:(-44.0,44.0),1:(44.0,-44.0)},ticks=30000))
    assert [p['period']for p in extra['periods']]==['first_half','second_half','extra_time_first_half']


def test_events_are_placed_along_the_length_by_period_and_thirds_close():
    p=packet();raw=bytes.fromhex(p['events_hex']);half=p['pitch_geometry']['half_length_native']
    # Forest v Newcastle, 11 November 2030: native half time 11655 (HOST_PERIOD_EVIDENCE.md)
    profile=struct.pack('<iii',11655,30000,-1)+bytes([0,1,0,0])
    out=decode_possession_events(raw,p['players'],p['fixture'],native_match_key=p['native_match_key'],pitch_geometry=p['pitch_geometry'],
        orientation=decode_orientation(tracking(profile,{0:(-44.0,44.0),1:(44.0,-44.0)})))
    assert out['orientation']['state']=='available'
    for side in out['sides']:
        assert [(r['period'],r['defended_end'])for r in side['defended_end_by_period']]==[
            ('first_half','negative_native_y'if side['side_index']==0 else'positive_native_y'),
            ('second_half','positive_native_y'if side['side_index']==0 else'negative_native_y')]
        thirds=side['anchor_thirds']
        assert sum(thirds['possession_won'].values())==side['possession_won']and sum(thirds['possession_lost'].values())==side['possession_lost']
        assert set(thirds['possession_won'])==set(THIRDS)|{'unplaced'}
    for row in out['events']:
        y=row['source_native_anchor']['native_y'];fraction=row['length_fraction_from_own_goal']
        assert row['period']in('first_half','second_half',None)
        if row['period']is None:assert fraction is None and row['defended_end']is None
        elif fraction is not None:
            forward=y if row['defended_end']=='negative_native_y'else -y
            assert fraction==round(min(1.0,max(0.0,(forward+half)/(2*half))),4)and 0<=fraction<=1
    placed=[r for r in out['events']if r['length_fraction_from_own_goal']is not None]
    assert len(placed)>=0.97*len(out['events'])
    # turning both sides round mirrors the thirds; without a profile nothing is placed and nothing is invented
    flipped=decode_possession_events(raw,p['players'],p['fixture'],native_match_key=p['native_match_key'],pitch_geometry=p['pitch_geometry'],
        orientation=decode_orientation(tracking(profile[:12]+bytes([0,0,0,0]),{0:(44.0,-44.0),1:(-44.0,44.0)})))
    for a,b in zip(out['sides'],flipped['sides']):
        assert a['anchor_thirds']['possession_won']['defensive_third']==b['anchor_thirds']['possession_won']['final_third']
    plain=decode(p)
    assert plain['orientation']=={'state':'not_read','periods':[]}
    assert all(s['anchor_thirds']is None and s['defended_end_by_period']is None for s in plain['sides'])
    assert all(r['period']is r['defended_end']is r['length_fraction_from_own_goal']is None for r in plain['events'])
