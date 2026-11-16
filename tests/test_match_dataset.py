import sqlite3
import pytest
from fm_live_mcp.match_dataset import build_connection, export_dataset


def fixture(key=1):
    return {'native_match_key':key,'fixture':{'date':'2030-10-23','fixture_ref':'ref',
        'home_team':{'database_index':545,'native_id':688},
        'away_team':{'database_index':3,'native_id':99},'competition':{'native_id':11}}}


def player():
    return {'person_index':'4','player':'Name','team_index':'545','date':'2030-10-23',
        'opponent_id':'99','competition_id':'11','minutes':'','goals':'0'}


def test_nulls_and_unique_identity_join():
    db=build_connection({'fixtures':[fixture()]},[player()])
    assert db.execute('select minutes,goals,join_state from player_matches').fetchone()==(None,0,'unique_candidate')
    assert db.execute('select fixture_ref from fixtures').fetchone()==('ref',)
    assert db.execute('select count(*) from joined_player_matches').fetchone()==(1,)
    assert db.execute('pragma integrity_check').fetchone()==('ok',)
    db.close()


def test_ambiguous_and_unmatched_preserved():
    db=build_connection({'fixtures':[fixture(1),fixture(2)]},[player()])
    assert db.execute('select join_state from player_matches').fetchone()==('ambiguous',)
    assert db.execute('select count(*) from player_fixture_candidates').fetchone()==(2,)
    assert db.execute('select count(*) from joined_player_matches').fetchone()==(0,)
    db.close()
    db=build_connection({'fixtures':[]},[player()])
    assert db.execute('select join_state from player_matches').fetchone()==('unmatched',)
    db.close()


def test_no_clobber_and_filter(tmp_path):
    path=tmp_path/'matches.sqlite'
    export_dataset(path,{'fixtures':[fixture()]},date_from='2031-01-01')
    assert sqlite3.connect(path).execute('select count(*) from fixtures').fetchone()==(0,)
    with pytest.raises(FileExistsError): export_dataset(path,{'fixtures':[]})


def test_totals_only_unique_native_key():
    totals={'records':[{'result_key':1,'teams':[{'side_index':0,'shots':10,'expected_goals':1.5}]}]}
    db=build_connection({'fixtures':[fixture()]},team_totals=totals)
    assert db.execute('select shots,expected_goals from team_totals').fetchone()==(10,1.5)
    db.close()


def test_identical_duplicate_fixtures_remain_ambiguous():
    db=build_connection({'fixtures':[fixture(),fixture()]},[player()])
    assert db.execute('select count(*) from fixtures').fetchone()==(2,)
    assert db.execute('select join_state from player_matches').fetchone()==('ambiguous',)
    db.close()


def test_bad_raw_frame_removes_incomplete_output(tmp_path):
    path=tmp_path/'bad.sqlite'
    with pytest.raises(ValueError,match='receipt'):
        export_dataset(path,{'fixtures':[fixture()]},raw_frames=[{'key':1,'raw':b'bad','raw_sha256':'wrong'}])
    assert not path.exists()


def test_named_action_view_exact_join_and_unknown_minutes():
    p={'fixture_key':1,'side_index':0,'person_index_word':7,'stored_player_slot':2,
       'person_name':'Player','minutes':None}
    metrics=[dict(p,shots=3),dict(p,stored_player_slot=3,shots=99)]
    db=build_connection({'fixtures':[fixture()]},retained_players=[p],player_metrics=metrics)
    assert db.execute('select person_name,shots,minutes,minutes_state,action_source_state from player_match_analysis').fetchone()==('Player',3,None,'unknown','captured')
    db.close()


def test_inline_zero_actions_are_captured_for_unused_rows():
    p={'fixture_key':1,'side_index':0,'person_index_word':7,'stored_player_slot':2,
       'minutes':0,'shots':0,'passes_attempted':0}
    db=build_connection({'fixtures':[fixture()]},retained_players=[p])
    assert db.execute('select shots,passes_attempted,minutes_state,action_source_state from player_match_analysis').fetchone()==(0,0,'zero_stored_minutes','captured')
    db.close()


def test_player_xg_direct_optional_metric_and_null():
    p={'fixture_key':1,'side_index':0,'person_index_word':7,'stored_player_slot':2,'expected_goals':0.0}
    db=build_connection({'fixtures':[fixture()]},retained_players=[p])
    assert db.execute('select expected_goals from player_match_analysis').fetchone()==(0.0,)
    db.close()
    metric=dict(p,expected_goals=0.375)
    db=build_connection({'fixtures':[fixture()]},retained_players=[p],player_metrics=[metric])
    assert db.execute('select expected_goals from player_match_analysis').fetchone()==(0.375,)
    db.close()
    p.pop('expected_goals')
    db=build_connection({'fixtures':[fixture()]},retained_players=[p])
    assert db.execute('select expected_goals from player_match_analysis').fetchone()==(None,)
    db.close()


def test_team_action_and_possession_unknowns_preserved():
    team={'side_index':0,'passes_attempted':0,'passes_completed':0,'corners':2,
          'possession_time_raw':-1,'possession_share_percentage_computed':None,
          'possession_share_state':'unavailable_negative_raw_counter'}
    db=build_connection({'fixtures':[fixture()]},team_totals={'records':[{'result_key':1,'teams':[team]}]})
    assert db.execute('select passes_attempted,passes_completed,corners,possession_time_raw,possession_share_percentage_computed,possession_share_state,pass_completion_percentage_derived from team_totals').fetchone()==(0,0,2,-1,None,'unavailable_negative_raw_counter',None)
    db.close()


def test_creation_participation_and_goal_coverage():
    p={'fixture_key':1,'side_index':0,'person_index_word':7,'stored_player_slot':2,
       'expected_assists':0.125,'key_passes':3,'open_play_key_passes':4,'chances_created':2,
       'appearance_kind':'entered_during_match','native_on_minute':65,'entry_minute':65,
       'exit_minute':90,'participation_state':'reconciled_native_minute_interval',
       'simultaneous_event_order_known':False}
    crossings=[{'fixture_key':1,'source_state':'available','goal_crossings':[],
                'coverage':{'all_attempts':False,'complete_scoreline_goals':False}}]
    db=build_connection({'fixtures':[fixture()]},retained_players=[p],goal_crossings=crossings)
    assert db.execute('select expected_assists,key_passes,open_play_key_passes,chances_created,entry_minute,exit_minute from player_match_analysis').fetchone()==(0.125,3,4,2,65,90)
    assert db.execute('select action_source_state from player_match_analysis').fetchone()==('captured',)
    assert db.execute('select count(*) from goal_crossings').fetchone()==(0,)
    assert db.execute("select count(*) from coverage where source='goal_crossings'").fetchone()==(1,)
    db.close()


def test_goal_crossings_exact_fixture_and_unknown_geometry_units():
    crossing={'record_index':0,'side_index':1,'team_index':3,'scorer_person_index':7,
       'stored_player_slot':2,'canonical_scorer_id':123,'scorer_name':'Player',
       'native_horizontal':-0.25,'native_height':1.0,'coordinate_units':None,'wire24':'ab'}
    db=build_connection({'fixtures':[fixture()]},goal_crossings=[{'fixture_key':1,'goal_crossings':[crossing]}])
    assert db.execute('select canonical_scorer_id,native_horizontal,native_height,coordinate_units from goal_crossings').fetchone()==(123,-0.25,1.0,None)
    db.close()


def test_sub_entry_context_requires_explicit_policy(monkeypatch):
    import sys
    import types
    calls=[]
    def query(db,source_policy):
        calls.append(source_policy)
        return [{'fixture_id':db.execute('select fixture_id from fixtures').fetchone()[0],
                 'native_match_key':1,'entry_state':'unknown','evidence_state':'same_minute_boundary'}]
    monkeypatch.setitem(sys.modules,'fm_live_mcp.match_entry_state',types.SimpleNamespace(query_entry_context=query))
    db=build_connection({'fixtures':[fixture()]})
    assert calls==[]
    db.close()
    db=build_connection({'fixtures':[fixture()]},entry_state_policy='explicit_verified_policy')
    assert calls==['explicit_verified_policy']
    assert db.execute('select entry_state,evidence_state from sub_entry_context').fetchone()==('unknown','same_minute_boundary')
    db.close()


def test_team_crossing_native_aggregate_and_unavailable_state():
    totals={'records':[{'result_key':1,'teams':[
        {'side_index':0,'crosses_attempted':20,'crosses_completed':4,
         'cross_completion_percentage_derived':20.0,'crossing_counts_state':'native_aggregate_available'},
        {'side_index':1,'crosses_attempted':None,'crosses_completed':None,
         'cross_completion_percentage_derived':None,'crossing_counts_state':'unavailable_inconsistent_player_counters'}]}]}
    db=build_connection({'fixtures':[fixture()]},team_totals=totals)
    assert db.execute('select crosses_attempted,crosses_completed,cross_completion_percentage_derived,crossing_counts_state from team_totals order by side_index').fetchall()==[
        (20,4,20.0,'native_aggregate_available'),(None,None,None,'unavailable_inconsistent_player_counters')]
    db.close()
