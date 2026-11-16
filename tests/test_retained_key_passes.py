import copy,gzip,hashlib,json,struct
from pathlib import Path
import pytest
from fm_live_mcp.retained_key_passes import decode_key_pass_annotations


def packet():return json.load(gzip.open(Path(__file__).parent/'fixtures/retained_key_passes_lille_136941.json.gz','rt'))


def decode(p):return decode_key_pass_annotations(bytes.fromhex(p['events_hex']),p['players'],p['fixture'],native_match_key=p['native_match_key'],pitch_geometry=p['pitch_geometry'])


def test_actual_all_categories_close_all_newcastle_rows_but_lille_missing_three():
    p=packet();out=decode(p);home,away=out['sides']
    assert out['native_event_count']==1697 and out['all_event_category_marker_count']==25
    assert(home['matched_player_counter_checks'],home['captured_player_counter_checks'],home['source_annotation_count'],home['official_key_pass_total'])==(20,23,15,18)
    assert(away['matched_player_counter_checks'],away['captured_player_counter_checks'],away['source_annotation_count'],away['official_key_pass_total'])==(20,20,10,10)
    assert away['full_side_key_pass_counter_closure']and not home['full_side_key_pass_counter_closure']
    assert home['individually_reconciled_annotation_count']==11 and home['withheld_unreconciled_actor_annotation_count']==4
    assert(home['official_pass_map_location_count'],away['official_pass_map_location_count'])==(6,5)
    assert away['source_annotation_category_counts']=={'7':5,'12':5}
    assert {r['person_name']for r in home['player_checks']if not r['counts_match']}=={'Tiago Santos','André','Hamza Igamane'}
    assert sum(r['official_key_passes']==0 for r in away['player_checks'])==away['zero_counter_players_checked']


def test_actual_supported_exact_id_recipient_join_never_leaks_other_category_recipient():
    out=decode(packet());away=out['sides'][1]
    assert next(x for x in away['supplied_pairs']if x['from_name']=='Luiz Henrique')['to_name']=='Nick Woltemade'
    assert next(x for x in away['supplied_pairs']if x['from_name']=='Luiz Henrique')['key_pass_annotated_completed_pass_events']==2
    other=[r for r in out['annotations']if r['native_category_code']!=7]
    assert other and all(r['recipient_name']is None and r['field_position']is None for r in other)
    assert all(r['shot_event_id']is r['goal_event_id']is r['assist']is None for r in out['annotations'])
    assert all(r['field_position']['location_semantics']=='official_pass_map_event_location; pass_origin_proved'for r in out['annotations']if r['field_position'])


def test_pass_only_marker_count_is_not_promoted_to_full_key_pass_denominator():
    p=packet();b=bytearray.fromhex(p['events_hex'])
    for at in range(0,len(b),56):
        if b[at+42]!=7:b[at+48]&=~2
    p['events_hex']=b.hex();out=decode(p)
    assert not out['sides'][1]['full_side_key_pass_counter_closure']
    assert out['sides'][1]['source_annotation_count']==5 and out['sides'][1]['official_key_pass_total']==10


@pytest.mark.parametrize('mutation',['person','team','fixture','hash','counter','slot'])
def test_wrong_actor_wire_team_scope_and_counter_metadata_reject(mutation):
    p=packet();r=p['players'][0]
    if mutation=='person':r['person_index_word']+=1
    elif mutation=='team':r['canonical_team_id']=999
    elif mutation=='fixture':r['fixture_key']=999
    elif mutation=='hash':r['row_sha256']='0'*64
    elif mutation=='counter':r['key_passes']+=1
    else:p['players'].append(copy.deepcopy(r))
    with pytest.raises(ValueError):decode(p)


def test_duplicate_event_ids_and_bad_marker_side_reject():
    p=packet();p['events_hex']+=p['events_hex'][:112]
    with pytest.raises(ValueError,match='Duplicate'):decode(p)
    p=packet();b=bytearray.fromhex(p['events_hex']);b[48]|=2;b[40]=9;p['events_hex']=b.hex()
    with pytest.raises(ValueError,match='side'):decode(p)


def test_extra_unknown_marked_actor_keeps_side_missing_instead_of_zero():
    p=packet();b=bytearray.fromhex(p['events_hex']);b[48]|=2;b[40]=1;b[39]=25;p['events_hex']=b.hex();out=decode(p)
    assert out['sides'][1]['unresolved_annotation_slots']==[25]
    assert not out['sides'][1]['full_side_key_pass_counter_closure']
    assert out['sides'][1]['withheld_unreconciled_actor_annotation_count']>=1


def test_missing_pitch_geometry_preserves_creator_counts_but_withholds_location():
    p=packet();p['pitch_geometry']=None;out=decode(p)
    assert out['sides'][1]['full_side_key_pass_counter_closure']
    assert all(r['field_position']is None and r['recipient_name']is None for r in out['annotations'])


def test_native_producer_counter_and_pass_map_guard_drift_rejects():
    from fm_live_mcp.retained_key_passes import verify_native
    with pytest.raises(ValueError,match='binding changed'):verify_native(lambda at,n:bytes(n),0)


def test_readonly_tool_schema_requires_only_exact_fixture_and_supports_source_pin(monkeypatch):
    import asyncio
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp import retained_key_pass_tools as tools
    calls=[]
    monkeypatch.setattr(tools,'get_retained_key_pass_annotations',lambda *a,**kw:(calls.append((a,kw))or{'state':'unavailable'}))
    async def check():
        mcp=FastMCP('test');tools.register_retained_key_pass_tools(mcp,None);tool,=await mcp.list_tools()
        assert tool.name=='fm_get_retained_key_pass_annotations'and tool.outputSchema is not None
        assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint
        assert set(tool.inputSchema['required'])=={'session_id','fixture_ref'}
        assert 'ALL CBE event categories'in tool.description and 'NOT a uniquely linked shot'in tool.description
        await mcp.call_tool(tool.name,{'session_id':'s','fixture_ref':'f'})
        assert calls[0][0]==(None,'s','f')and calls[0][1]['offset']==0 and calls[0][1]['limit']==100
    asyncio.run(check())


def service(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from fm_live_mcp import retained_key_passes as q,match_data_query,live_match_backing,live_match_team_totals,live_match_players,live_retained_shots
    p=packet();f={**p['fixture'],'fixture_ref':'f'}
    bridge=SimpleNamespace(lock=nullcontext(),_read_scope=lambda s:nullcontext(),_current=lambda s:None,
       _player_layout=lambda p:(0,),_world_state=lambda *a:(SimpleNamespace(verify=lambda:None),{},None),get_save=lambda s:{'save':{'current_date':'2030-11-11'}})
    monkeypatch.setattr(match_data_query,'capture_epoch',lambda *a:('epoch',))
    monkeypatch.setattr(q,'verify_native',lambda *a:None)
    monkeypatch.setattr(live_match_backing,'read_selected_matches',lambda *a,**k:{'records':[{'state':'available','fixture_ref':'f','fixture_native':f,'key':p['native_match_key'],'raw':b'raw'}]})
    teams=[{'team_index':f[k]['database_index'],'team_identity_word':f[k]['native_id']}for k in('home_team','away_team')]
    monkeypatch.setattr(live_match_team_totals,'decode_team_totals',lambda raw:{'result_key':p['native_match_key'],'teams':teams})
    monkeypatch.setattr(live_match_players,'project_frame',lambda *a:{'coverage':{'complete_side_sections':True,'stored_rows_per_side':[23,20]}})
    monkeypatch.setattr(live_retained_shots,'_actor_rows',lambda *a:p['players'])
    source={'state':'available','events':bytes.fromhex(p['events_hex']),'pitch_geometry':p['pitch_geometry']}
    monkeypatch.setattr(live_retained_shots,'capture_source',lambda *a,**k:source)
    return q,bridge,source


def test_selector_scoped_denominators_paging_and_source_pin(monkeypatch):
    q,b,source=service(monkeypatch)
    full=q.get_retained_key_pass_annotations(b,'s','f')
    assert full['state']=='available_partial'and full['total_count']is None and full['available_row_count']==21
    first=q.get_retained_key_pass_annotations(b,'s','f',team_native_id=688,limit=2)
    assert first['state']=='available'and first['total_count']==10 and first['next_offset']==2
    second=q.get_retained_key_pass_annotations(b,'s','f',team_native_id=688,limit=2,offset=2,expected_source_id=first['source_id'])
    assert not{r['event_id']for r in first['annotations']}&{r['event_id']for r in second['annotations']}
    bobb=q.get_retained_key_pass_annotations(b,'s','f',team_native_id=858,person_native_id=28126241)
    assert bobb['state']=='available'and bobb['total_count']==3 and not bobb['sides'][0]['full_side_key_pass_counter_closure']
    with pytest.raises(ValueError,match='continuation'):q.get_retained_key_pass_annotations(b,'s','f',offset=1)
    source['pitch_geometry']={**source['pitch_geometry'],'half_width_native':35.}
    with pytest.raises(ValueError,match='source or selectors changed'):
        q.get_retained_key_pass_annotations(b,'s','f',team_native_id=688,offset=2,expected_source_id=first['source_id'])


def test_incomplete_full_native_roster_and_reload_cannot_publish(monkeypatch):
    from fm_live_mcp import live_match_players,match_data_query
    q,b,_=service(monkeypatch)
    monkeypatch.setattr(live_match_players,'project_frame',lambda *a:{'coverage':{'complete_side_sections':True,'stored_rows_per_side':[23,19]}})
    with pytest.raises(ValueError,match='full roster count'):q.get_retained_key_pass_annotations(b,'s','f')
    q,b,_=service(monkeypatch);calls=iter([('epoch',),('reloaded',)])
    monkeypatch.setattr(match_data_query,'capture_epoch',lambda *a:next(calls))
    with pytest.raises(ValueError,match='epoch changed'):q.get_retained_key_pass_annotations(b,'s','f')
