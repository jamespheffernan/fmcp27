from unittest.mock import Mock
import pytest
from fm_live_mcp import retained_goal_combinations as goals


def sample():
    h, a = {'native_id':10,'database_index':5}, {'native_id':11,'database_index':6}
    fixture = dict(fixture_ref='f', date='2030-11-06', home_team=h, away_team=a, scores={'final_score':{'home':2,'away':0}})
    rows = []
    for index, side, score, assists in [(0,0,1,0),(2,0,1,0),(3,0,0,1),(4,0,0,1),(8,1,0,0)]:
        team = (h,a)[side]
        rows.append(dict(fixture_key=1, side_index=side, goals=score, assists=assists, canonical_person_id=index+100,
                         person_index_word=index, canonical_team_id=team['native_id'], team_index_word=team['database_index'],
                         identity_state='same_snapshot_canonical_PERSON', person_name=f'Player {index}'))
    events = [dict(source_index=i,side12=0,kind13=0,person_index=first,second_index_word=second)
              for i,(first,second) in enumerate([(0,3),(2,4)])]
    return dict(fixture=fixture,native_match_key=1, source={'state':'available'}, event_array={'state':'present_records','count':2,'rows':events}), rows


def test_same_record_second_person_does_not_narrow_independent_assist_bounds():
    item, rows = sample()
    r = goals._fixture_bounds(item, rows, 10, 100)
    assert r['state'] == 'available_conditional_exact_bounds'
    assert [(x['supplier_person_id'],x['minimum'],x['maximum']) for x in r['bounds']] == [(103,0,1),(104,0,1)]
    assert len(r['timeline']['records']) == 1
    assert r['timeline']['records'][0]['timeline_player2']['person_native_id'] == 103
    assert 'credited_assister' not in r['timeline']['records'][0]
    del item['event_array']['rows'][0]
    r = goals._fixture_bounds(item, rows, 10, 100)
    assert r['timeline'] == {'state':'unavailable_event_coverage','records':None}
    assert len(r['bounds']) == 2


def test_canonical_person_index_zero_is_valid_and_minus_one_is_unset():
    item,rows=sample()
    rows[0]['assists'], rows[3]['assists'] = 1,0
    item['event_array']['rows'][1]['second_index_word']=0
    assert goals.project_goal_timeline(item, rows)['goal_records'][1]['timeline_player2']['person_native_id'] == 100
    rows[0]['assists']=0
    item['event_array']['rows'][1]['second_index_word']=-1
    assert goals.project_goal_timeline(item, rows)['goal_records'][1]['timeline_player2'] is None


@pytest.mark.parametrize(('field','value','state'), [
    ('kind13',1,'unavailable_result_event_subtype'),('person_index',99,'unavailable_goal_actor'),
    ('second_index_word',8,'unavailable_assist_actor'),('second_index_word',-2,'unavailable_assist_actor'),
    ('second_index_word',0,'unavailable_assist_actor'),('second_index_word',-1,'unavailable_individual_counter_reconciliation')])
def test_unproven_subtypes_foreign_self_or_inconsistent_references_withhold_timeline(field,value,state):
    item,rows=sample()
    item['event_array']['rows'][0][field]=value
    result=goals._fixture_bounds(item,rows,10,100)
    assert result['timeline']['state']==state and result['timeline']['records'] is None
    assert result['state']=='available_conditional_exact_bounds'


def test_score_and_foreign_roster_protection():
    item,rows=sample()
    rows[-1]['canonical_person_id']=None
    result=goals._fixture_bounds(item,rows,10,100)
    assert result['state']=='available_conditional_exact_bounds'
    assert result['timeline']['state']=='unavailable_player_roster'
    item['fixture']['scores']['final_score']['home']=3
    result=goals._fixture_bounds(item,rows,10,100)
    assert result['bounds'] is None and result['state']=='unavailable_goal_total_mismatch'
    rows[0]['canonical_team_id']=11
    assert goals._fixture_bounds(item,rows,10,100)['state']=='unavailable_roster_identity_or_counters'


def test_ref_reuse_and_epoch_changes_reject(monkeypatch):
    item,rows=sample()
    packet={'capture':{'fixtures':[item],'save':{}},'retained_players':rows,'_live_capture_epoch':1}
    monkeypatch.setattr(goals,'capture_live',Mock(return_value=packet))
    monkeypatch.setattr(goals,'_verify_timeline',Mock())
    monkeypatch.setattr(goals,'capture_epoch',Mock(side_effect=[1,2,1,1]))
    with pytest.raises(ValueError,match='distinct'):
        goals.report_goal_combinations(None,'s',['f','f'],10,100)
    with pytest.raises(ValueError,match='changed career'):
        goals.report_goal_combinations(None,'s',['f'],10,100)
    with pytest.raises(ValueError,match='differ'):
        goals.report_goal_combinations(None,'s',['another'],10,100)


def test_multi_fixture_summary_preserves_unknowns_and_does_not_count_possible_as_confirmed():
    item,rows=sample()
    measured=goals._fixture_bounds(item,rows,10,100)
    missing=dict(bounds=None)
    result=goals._summarize([measured,missing,measured])
    assert (result['selected_fixture_count'],result['covered_fixture_count'])==(3,2)
    assert result['coverage']=='covered_fixtures_only'
    assert [(s['minimum'],s['maximum']) for s in result['suppliers']]==[(0,2),(0,2)]
    assert goals._summarize([missing])['suppliers'] is None
    result=goals._summarize([dict(bounds=[],goals=0)])
    assert result['scorer_goals_in_covered_fixtures']==0 and result['suppliers']==[]


def test_unbound_timeline_does_not_block_independent_bounds():
    item,rows=sample()
    value=goals._fixture_bounds(item,rows,10,100,timeline_verified=False)
    assert value['timeline']=={'state':'unavailable_goal_timeline_binding','records':None}
    assert value['state']=='available_conditional_exact_bounds'
