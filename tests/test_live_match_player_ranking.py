from copy import deepcopy
from types import SimpleNamespace
import pytest

from fm_live_mcp.live_match_player_ranking import LiveMatchPlayerRanks, rank_capture, capture_rank_scope, metric_catalog


def fixture(key, home=(1,10), away=(2,20), day='2030-08-01'):
    def team(identity):return dict(native_id=identity[0],database_index=identity[1],native_type_code=0,owner={'name':f'Team {identity[0]}/{identity[1]}'})
    return dict(native_match_key=key,fixture={'date':day,'home_team':team(home),'away_team':team(away)})


def player(key,person=1,side=0,team=10,minutes=90,value=5,name='Known',**extra):
    return dict(fixture_key=key,canonical_person_id=person,person_index_word=person or 999,person_name=name,
                side_index=side,team_index_word=team,minutes=minutes,appearance_kind='initial_participant_candidate',
                progressive_passes=value,passes_attempted=100,**extra)


def data(fixtures,rows):
    return dict(capture={'save':{'current_date':'2030-11-02'},'fixtures':fixtures,
                         'fixture_coverage':{'years':[{'year':2030,'all_groups_materialized':True}]}},retained_players=rows)


def bridge():return SimpleNamespace(get_save=lambda s:{'save':{'current_date':'2030-11-02'}})


def test_zero_minute_actions_and_unused_bench_are_aggregated_before_threshold():
    rows=[player(1,minutes=50,value=2),player(2,minutes=0,value=3),player(3,minutes=None,value=0),player(1,person=2,side=1,team=20,minutes=50,value=5)]
    rows[2]['appearance_kind']='unused_substitute'
    result=rank_capture(data([fixture(1),fixture(2),fixture(3)],rows),'progressive_passes','per90',50,1)
    first=result['ranked'][0][1]
    assert first['observed_total']==5 and first['minutes']==50
    assert first['value']==9 and first['unused_bench_null_minute_rows']==1


def test_missing_metric_and_unknown_minutes_are_not_zero():
    rows=[player(1,person=1,value=None),player(1,person=2,minutes=None),player(1,person=3,minutes=90,value=0)]
    result=rank_capture(data([fixture(1)],rows),'progressive_passes','per90',0)
    assert [r['person_native_id'] for _,r in result['ranked']]==[3]
    assert result['counts']['unclassified_groups']==2
    assert result['unclassified_reason_counts']['missing_selected_metric']==1
    assert result['unclassified_reason_counts']['unknown_active_minutes']==1


def test_normal_threshold_and_zero_denominator_exclusions_are_not_partial():
    q=LiveMatchPlayerRanks(lambda *a,**k:data([fixture(1)],[player(1,minutes=90)]),epoch=lambda *a:1)
    out=q.rank(bridge(),'s',11,'2030-08-01','2030-10-28','progressive_passes',minimum_minutes=270,team_native_id=1)
    assert out['state']=='available_observed_scope' and out['rows']==[]
    assert out['counts']['defined_excluded_groups']==1
    zero=rank_capture(data([fixture(1)],[player(1,minutes=0)]),'progressive_passes','per90',0)
    assert zero['counts']['unclassified_groups']==0
    assert zero['unclassified_reason_counts']['zero_minutes_denominator']==1


def test_known_minute_lower_bound_qualifies_total_and_per100_not_per90():
    rows=[player(1,minutes=500,value=10),player(2,minutes=None,value=5)]
    d=data([fixture(1),fixture(2)],rows)
    for normalization in ('total','per_100_pass_attempts'):
        result=rank_capture(d,'progressive_passes',normalization,450)
        assert len(result['ranked'])==1
        assert result['ranked'][0][1]['minutes'] is None
        assert result['ranked'][0][1]['known_minutes']==500
    assert not rank_capture(d,'progressive_passes','per90',450)['ranked']


def test_ratio_of_sums_changes_order_and_unknown_zero_passes_are_withheld():
    rows=[player(1,person=1,minutes=100,value=10),player(2,person=1,minutes=100,value=1),player(1,person=2,minutes=100,value=5),player(2,person=2,minutes=100,value=5)]
    rows[0]['passes_attempted']=10;rows[1]['passes_attempted']=90
    rows[2]['passes_attempted']=20;rows[3]['passes_attempted']=20
    d=data([fixture(1),fixture(2)],rows)
    per90=rank_capture(d,'progressive_passes','per90',0)['ranked']
    per100=rank_capture(d,'progressive_passes','per_100_pass_attempts',0)['ranked']
    assert per90[0][1]['person_native_id']==1
    assert per100[0][1]['person_native_id']==2
    assert per100[1][1]['value']==11 #11 /100, not mean(100,1.11)
    rows[0]['passes_attempted']=None
    assert len(rank_capture(data([fixture(1),fixture(2)],rows),'progressive_passes','per_100_pass_attempts',0)['ranked'])==1
    rows[0]['passes_attempted']=rows[1]['passes_attempted']=0
    result=rank_capture(data([fixture(1),fixture(2)],rows),'progressive_passes','per_100_pass_attempts',0)
    assert result['counts']['unclassified_groups']==0
    assert result['unclassified_reason_counts']['zero_pass_attempts_denominator']==1


def test_historical_clubs_and_team_indices_are_not_merged_by_name_or_person():
    d=data([fixture(1),fixture(2,home=(3,30)),fixture(3,home=(1,11))],
           [player(1,person=1,value=3),player(2,person=1,team=30,value=5),player(3,person=1,team=11,value=7)])
    result=rank_capture(d,'progressive_passes','total',0)
    assert len(result['ranked'])==3
    assert {(r['historical_team_native_id'],r['historical_team_database_index']) for _,r in result['ranked']}=={(1,10),(3,30),(1,11)}


def test_names_do_not_control_grouping_and_known_id_without_name_survives():
    d=data([fixture(1),fixture(2)],[player(1,name='Alpha'),player(2,name='Changed'),player(1,person=2,name=None),player(1,person=None)])
    result=rank_capture(d,'progressive_passes','total',0)
    assert result['ranked'][0][1]['names']==['Alpha','Changed']
    assert result['ranked'][1][1]['name_state']=='canonical_id_name_unavailable'
    assert result['counts']['unresolved_identity_rows']==1


def test_missing_historical_side_withholds_only_affected_team_groups():
    d=data([fixture(1),fixture(2,away=(3,30))],[player(1),player(1,person=2,side=1,team=20)])
    result=rank_capture(d,'progressive_passes','per90',0)
    assert [r['person_native_id'] for _,r in result['ranked']]==[2]
    assert result['unclassified_reason_counts']['historical_team_side_coverage_missing']==1
    assert sum(t['missing_player_sides'] for t in result['team_coverage'])==2


def test_cutoff_ties_page_without_native_recapture_and_epoch_expires():
    calls=[];state=[1]
    rows=[player(1,person=i+1,value=0) for i in range(230)]
    def capture(*a,**k):calls.append(1);return data([fixture(1)],rows)
    q=LiveMatchPlayerRanks(capture,epoch=lambda *a:state[0]);b=bridge()
    args=(b,'s',11,'2030-08-01','2030-10-28','progressive_passes')
    first=q.rank(*args,normalization='total',limit=1)
    assert first['minimum_minutes']==0 and first['selected_with_cutoff_ties']==230
    assert len(first['rows'])==100 and {r['rank'] for r in first['rows']}=={1}
    second=q.rank(*args,normalization='total',limit=1,cursor=first['next_cursor'])
    third=q.rank(*args,normalization='total',limit=1,cursor=second['next_cursor'])
    assert len(third['rows'])==30 and third['next_cursor'] is None
    assert len(calls)==1 and first['capture_id']==third['capture_id']
    state[0]=2
    with pytest.raises(ValueError,match='epoch changed'):
        q.rank(*args,normalization='total',limit=1,cursor=first['next_cursor'])


def test_highlight_returns_outside_limit_rank_or_exact_exclusion():
    d=data([fixture(1)],[player(1,person=1,value=20,minutes=500),player(1,person=2,value=5,minutes=500),player(1,person=3,value=50,minutes=90)])
    q=LiveMatchPlayerRanks(lambda *a,**k:d,epoch=lambda *a:1)
    out=q.rank(bridge(),'s',11,'2030-08-01','2030-10-28','progressive_passes',limit=1,highlight_person_native_ids=[2,3,4])
    assert out['highlighted_players'][0]['ranked_groups'][0]['rank']==2
    assert out['highlighted_players'][1]['excluded_groups'][0]['reasons']==['below_minimum_minutes']
    assert out['highlighted_players'][2]['state']=='not_observed_in_captured_rows'


def test_empty_scope_and_catalog_do_not_invent_population():
    q=LiveMatchPlayerRanks(lambda *a,**k:data([],[]),epoch=lambda *a:1)
    out=q.rank(bridge(),'s',11,'2030-08-01','2030-10-28','progressive_passes')
    assert out['rows']==[] and out['cutoff'] is None and out['counts']['qualifying_groups']==0
    assert 'per_100_pass_attempts' in metric_catalog()['metrics']['progressive_passes']['normalizations']
    assert 'per_100_pass_attempts' not in metric_catalog()['metrics']['shots']['normalizations']


def test_duplicate_rows_or_wrong_team_word_are_rejected():
    r=player(1)
    with pytest.raises(ValueError,match='duplicate stored'):
        rank_capture(data([fixture(1)],[r,dict(r,progressive_passes=6)]),'progressive_passes','total',0)
    with pytest.raises(ValueError,match='TEAM word'):
        rank_capture(data([fixture(1)],[player(1,team=99)]),'progressive_passes','total',0)


@pytest.mark.parametrize('fixture_count',[380,512,513])
def test_full_season_uses_real_window_route_trims_and_enforces_budget(monkeypatch,fixture_count):
    from datetime import date,timedelta
    fs=[fixture(i+1,day=(date(2030,8,1)+timedelta(days=i//2)).isoformat()) for i in range(fixture_count)]
    byref={f'f{i}':f for i,f in enumerate(fs)};calls=[];windows=[]
    class FakeBridge:
        world_identity=('career',1)
        def get_save(self,s):return {'save':{'name':'Career','current_date':'2031-06-01'}}
        def get_fixture_coverage(self,s):return {'years':[{'year':y,'all_groups_materialized':True} for y in (2030,2031)]}
        def find_fixtures(self,s,**query):
            windows.append((query['date_from'],query['date_to']))
            rows=[dict(f['fixture'],fixture_ref=ref) for ref,f in byref.items() if query['date_from']<=f['fixture']['date']<=query['date_to']]
            return {'save':self.get_save(s)['save'],'fixtures':rows,'next_cursor':None}
    def native_capture(b,s,refs,**kwargs):
        calls.append(len(refs));selected=[byref[ref] for ref in refs]
        rows=[player(f['native_match_key'],person=side+1,side=side,team=10 if side==0 else 20,raw_child_hex='ff'*5000,unneeded_counter=999) for f in selected for side in (0,1)]
        return dict(capture={'save':b.get_save(s)['save'],'fixtures':selected},retained_players=rows,team_totals={'records':[{'unused':'heavy'}]},raw_frames=[{'raw':b'x'*10000}])
    monkeypatch.setattr('fm_live_mcp.live_match_player_ranking.capture_live',native_capture)
    if fixture_count>512:
        with pytest.raises(ValueError,match='Fixture match budget exceeded'):
            capture_rank_scope(FakeBridge(),'s',None,'2030-08-01','2031-05-31',11,metric='progressive_passes',normalization='per90')
        return
    out=capture_rank_scope(FakeBridge(),'s',None,'2030-08-01','2031-05-31',11,metric='progressive_passes',normalization='per90')
    assert len(out['capture']['fixtures'])==fixture_count and len(out['retained_players'])==2*fixture_count
    assert max(calls)<=16 and len(windows)>10
    assert out['raw_frames']==[] and out['team_totals']['records']==[]
    assert all('raw_child_hex' not in r and 'unneeded_counter' not in r for r in out['retained_players'])


def test_identical_aliases_deduplicate_but_changed_frames_reject():
    r=player(1)
    result=rank_capture(data([fixture(1),fixture(1)],[r,dict(r)]),'progressive_passes','total',0)
    assert result['counts']['selected_fixtures']==1
    assert result['counts']['selected_player_rows']==1
    assert result['counts']['deduplicated_fixture_rows']==1
    assert result['counts']['deduplicated_player_rows']==1
    assert result['ranked'][0][1]['observed_total']==5
    with pytest.raises(ValueError,match='Conflicting duplicate native'):
        rank_capture(data([fixture(1),fixture(1,home=(3,30))],[r]),'progressive_passes','total',0)


def test_runtime_metric_catalog_schema_is_bounded_and_discoverable():
    import asyncio
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp.live_match_rank_tools import register_live_match_rank_tools,Metric
    from fm_live_mcp.live_match_player_ranking import METRICS
    server=FastMCP('test-ranks');register_live_match_rank_tools(server,None)
    tools={tool.name:tool for tool in asyncio.run(server.list_tools())}
    schema=tools['fm_rank_live_match_players'].inputSchema['properties']
    assert set(schema['metric']['enum'])==set(METRICS)
    assert schema['limit']['maximum']==100
    assert schema['highlight_person_native_ids']['anyOf'][0]['maxItems']==8
    assert tools['fm_get_live_match_rank_metrics'].inputSchema['properties']=={}


def test_decisive_defined_exclusion_precedes_unknown_unused_metrics():
    d=data([fixture(1)],[player(1,minutes=90,value=None)])
    result=rank_capture(d,'progressive_passes','per90',270,1)
    assert result['counts']['unclassified_groups']==0
    assert result['excluded'][0]['reasons']==['below_minimum_minutes']


def test_capture_epoch_change_and_changed_cursor_selectors_reject():
    state=[1]
    def capture(*args,**kw):
        state[0]=2
        return data([fixture(1)],[player(1,minutes=500)])
    q=LiveMatchPlayerRanks(capture,epoch=lambda *a:state[0])
    with pytest.raises(ValueError,match='epoch changed during'):
        q.rank(bridge(),'s',11,'2030-08-01','2030-10-28','progressive_passes')
