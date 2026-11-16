import copy
import asyncio
import struct
from types import SimpleNamespace
import pytest

from fm_live_mcp.match_entry_state import SOURCE_POLICY
from fm_live_mcp.match_pair_overlap import MatchPairOverlapReports, pair_overlap


def player(identity, start=0, stop=90, *, side=0, unused=False, fixture='f'):
    flag=start>0 or unused
    return dict(fixture_id=fixture,side_index=side,canonical_person_id=identity,
                person_index_word=identity+100,person_name=str(identity),goals=0,
                minutes=None if unused else stop-start,
                appearance_kind='unused_substitute' if unused else 'entered_during_match' if flag else 'initial_participant_candidate',
                native_substitute_duration_flag=flag,native_on_minute=start,native_off_minute=stop if stop<90 else 0,
                native_injury_minute=0,native_sent_off_minute=0,native_end_clock=90)


def rows(a=None,b=None,events=()):
    players=[player(1) if a is None else a,player(2,60) if b is None else b,player(3,side=1)]
    players=[p for p in players if p]
    for p in players:p['goals']=sum(e['person_index']==p['person_index_word'] and e['side_code']==p['side_index'] and e['kind_code'] in (0,2) for e in events)
    f=dict(fixture_id='f',native_match_key=7,date='2030-10-01',competition_id=11,
           competition='League',home_team_id=688,away_team_id=10,home_team='Own',away_team='Other',
           home_score=sum(e['side_code']==0 for e in events),away_score=sum(e['side_code']==1 for e in events),event_state='present_records')
    return [{'table':'fixtures','row':f}]+[{'table':'retained_players','row':p} for p in players]+[{'table':'events','row':e} for e in events]


def event(minute, *, side=0, extra=0, kind=0, actor=101):
    return dict(fixture_id='f',source_index=minute,side_code=side,kind_code=kind,byte14=minute,byte15=extra,person_index=actor)


def compute(data,goals=False,policy=SOURCE_POLICY):
    return pair_overlap(data,688,1,2,include_goals=goals,source_policy=policy)


def test_overlap_and_pair_symmetry():
    data=rows();r=compute(data)
    assert r['native_overlap_minutes_lower']==r['native_overlap_minutes_upper']==30
    assert r['observed_overlap_fixture_count']==1
    assert pair_overlap(data,688,2,1)['native_overlap_minutes_lower']==30
    assert r['fixtures'][0]['both_initial_participant_candidates'] is False


def test_adjacent_ranges_are_not_simultaneous_and_unused_is_definitive_zero():
    r=compute(rows(player(1,0,63),player(2,63)))['fixtures'][0]
    assert r['overlap_minutes']==0 and r['state']=='verified_no_overlap_adjacent_or_disjoint'
    r=compute(rows(player(1),player(2,unused=True)))['fixtures'][0]
    assert r['state']=='verified_no_overlap_unused_player' and r['overlap_upper']==0


def test_missing_person_stays_unknown_with_bounded_exposure_and_shared_initial_unknown():
    r=compute(rows(player(1,0,66),{}))
    assert r['native_overlap_minutes_lower']==0 and r['native_overlap_minutes_upper']==66
    assert r['unknown_shared_initial_fixture_count']==1
    assert r['fixtures'][0]['second']['state']=='missing_retained_person'


def test_duplicate_identity_and_inconsistent_clocks_do_not_produce_overlap():
    data=rows();data.append(copy.deepcopy(data[1]))
    assert compute(data)['fixtures'][0]['state']=='ambiguous_fixture_or_person_identity'
    data=rows();data[2]['row']['native_end_clock']=100
    assert compute(data)['fixtures'][0]['state']=='unknown_individual_interval'


def test_native_terminal_precedence_and_duration_mismatch_fail_closed():
    a=player(1,0,70);a['native_injury_minute']=80
    assert compute(rows(a,player(2,60)))['native_overlap_minutes_lower']==10
    a['minutes']=71
    assert compute(rows(a,player(2,60)))['fixtures'][0]['first']['state']=='unresolved_native_clock_or_duration'


def test_same_nominal_minute_and_stoppage_boundaries_are_bounded():
    data=rows(player(1),player(2,45),[event(45,extra=2),event(54),event(90,extra=4)])
    scoring=compute(data,True)['fixtures'][0]['scoring']
    assert scoring['goals_for_lower']==2 and scoring['goals_for_upper']==3
    assert scoring['ambiguous_boundary_events'][0]['byte15']==2
    assert any(e['byte14']==90 and e['byte15']==4 for e in scoring['certain_scoring_events'])
    assert scoring['exact_elapsed_stoppage_minutes'] is None


def test_explicit_exit_minute_event_is_uncertain():
    r=compute(rows(player(1,0,70),player(2,60),[event(70)]),True)['fixtures'][0]['scoring']
    assert (r['goals_for_lower'],r['goals_for_upper'])==(0,1)


def test_untrusted_goal_sources_never_gain_named_scoring_counts():
    assert compute(rows(),True,None)['fixtures'][0]['scoring']['state']=='unverified_source_policy'
    data=rows(events=[event(70,kind=3)])
    assert compute(data,True)['fixtures'][0]['scoring']['state']=='unknown_scoring_code_or_clock'
    data=rows(events=[event(70)]);data[0]['row']['home_score']=2
    assert compute(data,True)['fixtures'][0]['scoring']['state']=='score_reconciliation_failed'
    data=rows(events=[event(70)]);data[1]['row']['goals']=0
    assert compute(data,True)['fixtures'][0]['scoring']['state']=='fixture_player_goals_reconciliation_failed'


def test_missing_goalless_array_with_complete_zero_tallies_is_not_unknown_score():
    data=rows();data[0]['row']['event_state']='absent_array'
    assert compute(data,True)['fixtures'][0]['scoring']['goals_for_lower']==0
    data[0]['row']['home_score']=1
    assert compute(data,True)['fixtures'][0]['scoring']['state']=='missing_scoring_events'


class Queries:
    def __init__(self):self.calls=[]
    def query(self,*args,**kwargs):
        self.calls.append((args,kwargs));data=rows()
        return dict(rows=data[:1] if not kwargs.get('cursor') else data[1:],next_cursor='next' if not kwargs.get('cursor') else None,
                    capture_id='capture',captured_save={'current_date':'2030-11-02'},observed_at='now',metadata={'entry_state_policy':SOURCE_POLICY})


def test_live_report_consumes_same_capture_and_validates_identity_before_capture():
    q=Queries();report=MatchPairOverlapReports(q)
    result=report.report(None,'s',688,1,2,'2030-08-01','2030-10-28',11)
    assert result['native_overlap_minutes_lower']==30 and result['capture_id']=='capture'
    assert len(q.calls)==2 and q.calls[1][1]['cursor']=='next'
    assert 'events' not in q.calls[0][1]['tables']
    with pytest.raises(ValueError,match='different'):report.report(None,'s',688,1,1,'a','b')
    with pytest.raises(ValueError,match='uint32'):report.report(None,'s',True,1,2,'a','b')
    assert len(q.calls)==2


def test_tool_schema_explains_canonical_ids_and_optional_goals():
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp.live_pair_overlap_tools import register_live_pair_overlap_tools
    async def check():
        mcp=FastMCP('test');register_live_pair_overlap_tools(mcp,None)
        tool,=await mcp.list_tools()
        assert tool.name=='fm_report_live_player_pair_overlap'
        schema=tool.inputSchema
        assert {'session_id','team_native_id','first_person_native_id','second_person_native_id','date_from','date_to'}<=set(schema['required'])
        assert 'canonical PERSON' in schema['properties']['first_person_native_id']['description']
        assert schema['properties']['include_goals']['default'] is False
        assert tool.annotations.readOnlyHint is True
        assert not {'path','sql','source_id'}&schema['properties'].keys()
    asyncio.run(check())


def test_empty_selection_is_explicit_and_changed_capture_rejected():
    assert compute([])['state']=='no_selected_retained_results'
    class ChangedQueries(Queries):
        def query(self,*args,**kwargs):
            page=super().query(*args,**kwargs)
            if kwargs.get('cursor'):page['capture_id']='changed'
            return page
    with pytest.raises(ValueError,match='capture changed'):
        MatchPairOverlapReports(ChangedQueries()).report(None,'s',688,1,2,'2030-08-01','2030-10-28')


def test_captured_names_scores_and_matching_refs_survive_unknown_player_rows():
    data=rows(player(1,0,66),{})
    fixture=data[0]['row']
    fixture.update(fixture_ref='fixture-token',home_team_index=545,away_team_index=10,
                   raw_json={'fixture':{'home_team':{'native_id':688,'database_index':545,'team_ref':'home-token'},
                                        'away_team':{'native_id':10,'database_index':10,'team_ref':'away-token'}}})
    refs={(545,688,688):'home-token',(10,10,10):'away-token'}
    result=pair_overlap(data,688,1,2,team_references=refs)['fixtures'][0]
    assert result['state']=='unknown_individual_interval'
    assert (result['home_team'],result['away_team'])==('Own','Other')
    assert (result['home_team_id'],result['away_team_id'])==(688,10)
    assert (result['home_score'],result['away_score'])==(0,0)
    assert result['fixture_ref']=='fixture-token'
    assert result['home_team_ref']=='home-token' and result['away_team_ref']=='away-token'
    assert result['home_team_ref_state']=='same_capture_fixture_identity'
    assert result['overlap_upper']==66


def test_missing_labels_and_mismatched_reference_identities_stay_null():
    data=rows();fixture=data[0]['row']
    fixture.update(home_team=None,home_team_index=545,away_team_index=10,
                   raw_json={'fixture':{'home_team':{'native_id':999,'database_index':545,'team_ref':'wrong-team'},
                                        'away_team':{'native_id':10,'database_index':999,'team_ref':'wrong-index'}}})
    result=compute(data)['fixtures'][0]
    assert result['home_team'] is None
    assert result['home_team_ref'] is None and result['away_team_ref'] is None
    assert result['home_team_ref_state']=='unavailable_or_unmatched_fixture_identity'
    assert result['overlap_minutes']==30


def test_existing_session_refs_bind_only_full_native_fixture_identity():
    data=rows();fixture=data[0]['row']
    fixture.update(home_team_index=545,away_team_index=10,
                   raw_json={'fixture':{'home_team':{'native_id':688,'database_index':545,'random_id':None},
                                        'away_team':{'native_id':10,'database_index':10,'random_id':77}}})
    refs={(545,688,688):'cached-home',(10,10,10):'stale-away'}
    result=pair_overlap(data,688,1,2,team_references=refs)['fixtures'][0]
    assert result['home_team_ref']=='cached-home'
    assert result['away_team_ref'] is None
    assert result['home_team_identity']==dict(native_id=688,database_index=545,random_id=None)
    refs[(10,10,77)]='cached-away'
    assert pair_overlap(data,688,1,2,team_references=refs)['fixtures'][0]['away_team_ref']=='cached-away'


def test_live_report_reuses_existing_refs_without_fixture_or_team_calls():
    class FixtureQueries(Queries):
        def query(self,*args,**kwargs):
            page=super().query(*args,**kwargs)
            for item in page['rows']:
                if item['table']=='fixtures':
                    item['row'].update(home_team_index=545,away_team_index=10,
                        raw_json={'fixture':{'home_team':{'native_id':688,'database_index':545},
                                             'away_team':{'native_id':10,'database_index':10}}})
            return page
    bridge=SimpleNamespace(team_refs={'home':{'identity':struct.pack('<III',545,688,688)},
                                      'away':{'identity':struct.pack('<III',10,10,10)}})
    queries=FixtureQueries()
    report=MatchPairOverlapReports(queries).report(bridge,'s',688,1,2,'2030-08-01','2030-10-28')
    assert report['fixtures'][0]['home_team_ref']=='home'
    assert report['fixtures'][0]['away_team_ref']=='away'
    assert len(queries.calls)==2


def test_reference_cache_from_another_session_is_not_published():
    class FixtureQueries(Queries):
        def query(self,*args,**kwargs):
            page=super().query(*args,**kwargs)
            for item in page['rows']:
                if item['table']=='fixtures':
                    item['row'].update(home_team_index=545,away_team_index=10,
                        raw_json={'fixture':{'home_team':{'native_id':688,'database_index':545},
                                             'away_team':{'native_id':10,'database_index':10}}})
            return page
    bridge=SimpleNamespace(session='new-session',team_refs={
        'foreign-home':{'identity':struct.pack('<III',545,688,688)},
        'foreign-away':{'identity':struct.pack('<III',10,10,10)}})
    result=MatchPairOverlapReports(FixtureQueries()).report(bridge,'s',688,1,2,'2030-08-01','2030-10-28')
    fixture=result['fixtures'][0]
    assert fixture['home_team_ref'] is None and fixture['away_team_ref'] is None
    assert fixture['home_team']=='Own' and fixture['away_team']=='Other'
    assert fixture['overlap_minutes']==30
    class ChangingBridge:
        session='s'
        @property
        def team_refs(self):
            self.session='new-session'
            return bridge.team_refs
    changed=MatchPairOverlapReports(FixtureQueries()).report(ChangingBridge(),'s',688,1,2,'2030-08-01','2030-10-28')
    assert changed['fixtures'][0]['home_team_ref'] is None
    assert changed['fixtures'][0]['away_team_ref'] is None
