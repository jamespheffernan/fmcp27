from copy import deepcopy
from types import SimpleNamespace
import pytest

from fm_live_mcp.live_match_window_comparison import compare_capture,LiveMatchWindowComparisons,capture_windows,_merged_intervals


def fixture(key,day,home=(1,10),away=(2,20)):
    def team(identity):return {'native_id':identity[0],'database_index':identity[1],'native_type_code':0,'owner':{'name':f'Team {identity[0]}'}}
    return {'native_match_key':key,'fixture':{'date':day,'home_team':team(home),'away_team':team(away)}}


def player(key,person=1,side=0,index=10,minutes=90,value=2):
    return dict(fixture_key=key,side_index=side,team_index_word=index,canonical_person_id=person,
                person_index_word=person,person_name=f'Person {person}',minutes=minutes,appearance_kind='initial_participant_candidate',
                shots=2,shots_on_target=1,expected_goals=.2,expected_assists=.1,key_passes=value,
                open_play_key_passes=value,chances_created=1,progressive_passes=value,passes_attempted=50)


def data(fs,rows):
    totals=[]
    for f in fs:
        teams=[]
        for side in (0,1):
            ps=[p for p in rows if p['fixture_key']==f['native_match_key'] and p['side_index']==side]
            teams.append(dict(side_index=side,team_index=(f['fixture'][('home_team','away_team')[side]] or {}).get('database_index'),**{k:sum(p[k] for p in ps) if ps and all(p[k] is not None for p in ps) else None for k in ('shots','shots_on_target','expected_goals','passes_attempted')}))
        totals.append({'result_key':f['native_match_key'],'teams':teams})
    return {'capture':{'fixtures':fs},'retained_players':rows,'team_totals':{'records':totals}}


def sample():
    fs=[fixture(1,'2029-08-01'),fixture(2,'2029-08-08'),fixture(3,'2030-08-01')]
    rows=[player(1,value=4),player(2,value=4),player(3,value=1),player(1,person=2,value=0),player(2,person=2,value=0),player(3,person=2,value=3)]
    rows += [player(f['native_match_key'],person=99,side=1,index=20) for f in fs]
    return data(fs,rows)


def compare(d,**args):
    options=dict(team_id=1,baseline=('2029-08-01','2029-08-31'),comparison=('2030-08-01','2030-08-31'),metric='open_play_key_passes',baseline_minimum=90,comparison_minimum=90,minimum_team_matches=5,direction='decrease')
    options.update(args);return compare_capture(d,**options)


def bridge():return SimpleNamespace(get_save=lambda s:{'save':{'current_date':'2030-11-02'}})


def test_team_match_denominators_and_exact_returning_changes():
    result=compare(sample())
    assert result['team_windows']['baseline']['observed_fixtures']==2
    assert result['team_windows']['comparison']['observed_fixtures']==1
    assert result['counts']['qualifying_returning_groups']==2
    delta,row=result['ranked'][0]
    assert row['person_native_id']==1 and row['change_per90']==-3
    assert row['baseline']['per90']==4 and row['comparison']['per90']==1
    assert result['ranked'][1][1]['change_per90']==3
    assert result['team_windows']['baseline']['teams'][0]['sample_state']=='small_observed_sample'
    increasing=compare(sample(),direction='increase')
    assert increasing['ranked'][0][1]['person_native_id']==2


def test_pooled_xg_per_shot_not_mean_of_match_ratios():
    d=sample()
    ps=[r for r in d['retained_players'] if r['side_index']==0 and r['fixture_key'] in (1,2)]
    for p in ps:
        p['shots']=1 if p['fixture_key']==1 else 9
        p['expected_goals']=.5 if p['fixture_key']==1 else 2.5
    d=data(d['capture']['fixtures'],d['retained_players'])
    summary=compare(d)['team_windows']['baseline']['teams'][0]['chance_creation']['for']
    assert summary['expected_goals_per_shot']==pytest.approx(6/20)
    assert summary['shots']['per_match']==10


def test_zero_minute_actions_survive_and_unused_null_minutes_are_known():
    d=sample();own=[p for p in d['retained_players'] if p['side_index']==0 and p['canonical_person_id']==1]
    own[0]['minutes']=90;own[1]['minutes']=0
    result=compare(d)
    row=next(r for _,r in result['ranked'] if r['person_native_id']==1)
    assert row['baseline']['observed_total']==8 and row['baseline']['minutes']==90
    own[1]['minutes']=None;own[1]['appearance_kind']='unused_substitute'
    assert next(r for _,r in compare(d)['ranked'] if r['person_native_id']==1)['baseline']['minutes']==90


def test_unknown_minutes_missing_metric_and_one_window_only_are_explicit():
    d=sample();d['retained_players'][0]['minutes']=None
    d['retained_players'].append(player(3,person=3))
    # Counter sums are recomputed because this is a distinct verified fixture control.
    d=data(d['capture']['fixtures'],d['retained_players'])
    result=compare(d)
    assert result['counts']['uncertain_returners']==1
    assert result['counts']['comparison_only_groups']==1
    assert result['returner_exclusions'][0]['reasons']['baseline']==['unknown_active_minutes']
    assert result['state']=='available_partial'
    d=sample();d['retained_players'][0]['open_play_key_passes']=None
    assert compare(d)['counts']['uncertain_returners']==1


def test_defined_threshold_exclusions_are_not_unknown():
    result=compare(sample(),baseline_minimum=500)
    assert result['counts']['defined_excluded_returners']==2
    assert result['counts']['uncertain_returners']==0


def test_missing_team_or_player_side_never_becomes_zero():
    d=sample();d['team_totals']['records']=[r for r in d['team_totals']['records'] if r['result_key']!=3]
    result=compare(d)
    assert result['team_windows']['comparison']['teams'][0]['chance_creation']['for']['shots']['total'] is None
    assert result['state']=='available_partial'
    d=sample();d['retained_players']=[p for p in d['retained_players'] if not(p['fixture_key']==3 and p['side_index']==0)]
    result=compare(d)
    assert result['team_windows']['comparison']['teams'][0]['creation_context']['key_passes']['total'] is None
    assert result['counts']['baseline_only_groups']==2


def test_overlap_is_explicit_and_union_routing_merges_only_overlap_or_adjacent():
    result=compare(sample(),baseline=('2029-08-01','2030-08-31'))
    assert result['counts']['overlapping_fixtures']==1
    assert _merged_intervals([('2029-01-01','2029-02-01'),('2029-02-01','2029-03-01')])==[('2029-01-01','2029-03-01')]
    assert len(_merged_intervals([('2029-01-01','2029-02-01'),('2030-02-01','2030-03-01')]))==2


def test_player_current_club_is_not_used_and_different_historical_index_is_not_returner():
    d=sample();d['capture']['fixtures'][2]['fixture']['home_team']['database_index']=11
    for p in d['retained_players']:
        if p['fixture_key']==3 and p['side_index']==0:p['team_index_word']=11
    d=data(d['capture']['fixtures'],d['retained_players'])
    result=compare(d)
    assert result['counts']['qualifying_returning_groups']==0
    assert result['counts']['baseline_only_groups']==2 and result['counts']['comparison_only_groups']==2


def test_contradictory_team_player_stats_reject_instead_of_advising():
    d=sample();d['team_totals']['records'][0]['teams'][0]['shots']=999
    with pytest.raises(ValueError,match='do not reconcile'):compare(d)


def test_cached_ties_complete_across_pages_no_recapture_and_reload_rejects():
    fs=[fixture(1,'2029-08-01'),fixture(2,'2030-08-01')]
    rows=[player(key,person=i+1,value=1) for key in (1,2) for i in range(220)]
    d=data(fs,rows);d['capture']['union_scopes']=[{'selectors':{'date_from':'2029-08-01','date_to':'2030-08-31'},'fixture_coverage':{'years':[{'year':2029,'all_groups_materialized':True},{'year':2030,'all_groups_materialized':True}]}}];calls=[];epoch=[1]
    def capture(*args):calls.append(1);return d
    q=LiveMatchWindowComparisons(capture,epoch=lambda *a:epoch[0]);b=bridge()
    args=(b,'s',1,11,'2029-08-01','2029-08-31','2030-08-01','2030-08-31')
    first=q.compare(*args,baseline_minimum_minutes=90,comparison_minimum_minutes=90,limit=1)
    second=q.compare(*args,baseline_minimum_minutes=90,comparison_minimum_minutes=90,limit=1,cursor=first['next_cursor'])
    third=q.compare(*args,baseline_minimum_minutes=90,comparison_minimum_minutes=90,limit=1,cursor=second['next_cursor'])
    assert len(first['rows'])==100 and len(second['rows'])==100 and len(third['rows'])==20
    assert first['capture_id']==third['capture_id'] and len(calls)==1
    epoch[0]=2
    with pytest.raises(ValueError,match='epoch changed'):
        q.compare(*args,baseline_minimum_minutes=90,comparison_minimum_minutes=90,limit=1,cursor=first['next_cursor'])


def test_empty_windows_and_compact_iso_are_not_misclassified():
    result=compare(data([],[]))
    assert result['counts']['qualifying_returning_groups']==0 and result['team_windows']['baseline']['teams']==[]
    q=LiveMatchWindowComparisons(lambda *a:sample(),epoch=lambda *a:1)
    with pytest.raises(ValueError,match='canonical'):
        q.compare(bridge(),'s',1,11,'20290801','2029-08-31','2030-08-01','2030-08-31')


def test_opponent_team_word_and_total_owner_are_rechecked():
    d=sample();d['retained_players'][-1]['team_index_word']=123
    with pytest.raises(ValueError,match='Player TEAM word'):
        compare(d)
    d=sample();d['team_totals']['records'][0]['teams'][1]['team_index']=123
    with pytest.raises(ValueError,match='total TEAM index'):
        compare(d)


def test_verified_side_counter_requires_every_advertised_check():
    d=sample();expected=compare(d)['team_windows']['baseline']['verified_player_team_sides']
    assert expected==4
    d['retained_players'][0]['shots_on_target']=None
    actual=compare(d)['team_windows']['baseline']['verified_player_team_sides']
    assert actual==3


def test_capture_union_routes_only_requested_intervals_and_trims_before_accumulation(monkeypatch):
    import fm_live_mcp.export_live_matches as exporter
    scopes=[];batch_payloads=[]
    def native(b,s,refs,**kwargs):
        f=fixture(int(refs[0]),'2029-08-01' if refs[0]=='1' else '2030-08-01')
        rows=[dict(player(int(refs[0])),raw_child_hex='ff'*5000,unrelated=999)]
        result=data([f],rows);result['capture']['save']={'current_date':'2030-11-02'}
        result['raw_frames']=[{'raw':b'x'*10000}]
        return result
    def scope(b,s,team,first,last,comp,**options):
        scopes.append((first,last,options['max_matches']))
        key='1' if first.startswith('2029') else '2'
        result=options['capture'](b,s,[key]);batch_payloads.append(result)
        result['capture'].update(selectors={'date_from':first,'date_to':last})
        return result
    monkeypatch.setattr('fm_live_mcp.live_match_window_comparison.capture_live',native)
    monkeypatch.setattr(exporter,'capture_scope',scope)
    out=capture_windows(None,'s',1,11,[('2029-08-01','2029-08-31'),('2030-08-01','2030-08-31')],'open_play_key_passes')
    assert scopes==[('2029-08-01','2029-08-31',512),('2030-08-01','2030-08-31',511)]
    assert len(out['capture']['fixtures'])==2 and out['raw_frames']==[]
    assert all('raw_child_hex' not in row and 'unrelated' not in row for row in out['retained_players'])
    assert all(batch['raw_frames']==[] for batch in batch_payloads)
    scopes.clear()
    capture_windows(None,'s',1,11,[('2029-08-01','2029-08-31'),('2029-08-20','2029-09-30')],'open_play_key_passes')
    assert len(scopes)==1 and scopes[0][:2]==('2029-08-01','2029-09-30')


def test_capture_reload_and_real_source_cursor_selector_pinning():
    epoch=[1]
    def capture(*args):
        epoch[0]=2
        return sample()
    q=LiveMatchWindowComparisons(capture,epoch=lambda *a:epoch[0])
    with pytest.raises(ValueError,match='epoch changed during'):
        q.compare(bridge(),'s',1,11,'2029-08-01','2029-08-31','2030-08-01','2030-08-31')


def test_tool_schema_defaults_dates_and_fixed_metric_catalog():
    import asyncio
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp.live_match_window_tools import register_live_match_window_tools
    from fm_live_mcp.live_match_window_comparison import PLAYER_METRICS
    server=FastMCP('windows');register_live_match_window_tools(server,None)
    tools=asyncio.run(server.list_tools());assert len(tools)==1
    schema=tools[0].inputSchema['properties']
    assert set(schema['player_metric']['enum'])==set(PLAYER_METRICS)
    assert schema['baseline_minimum_minutes']['default']==450
    assert schema['comparison_minimum_minutes']['default']==450
    assert schema['limit']['maximum']==100
    assert schema['baseline_from']['pattern'].startswith('^')


def test_empty_overlap_is_not_claimed_as_disjoint_date_windows():
    result=compare(data([],[]),baseline=('2030-01-01','2030-02-28'),comparison=('2030-02-01','2030-03-31'))
    assert result['counts']['overlapping_fixtures']==0
    assert not result['counts']['windows_disjoint']
    assert result['counts']['observed_fixture_sets_disjoint']
