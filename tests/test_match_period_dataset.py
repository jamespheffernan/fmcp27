import copy
import pytest
from fm_live_mcp.match_dataset import build_connection,export_dataset


def inputs():
    fixture={'fixture_ref':'r','date':'2030-11-02','competition':{'native_id':11},
             'home_team':{'native_id':688,'database_index':545},'away_team':{'native_id':713,'database_index':570}}
    rows=[dict(side_index=0,record_index=i,event_id=i+1,native_clock_start_raw=start,native_clock_end_raw=end,
               native_x=1.,native_y=2.,expected_goals=xg,native_category_code=kind,native_shot_type=0,stored_player_slot=7,
               outcome='saved'if kind==4 else'missed_target',body_part='feet',actor={'canonical_person_id':99,'person_name':'Name'})
          for i,(start,end,xg,kind)in enumerate(((2,5,.1,4),(13,15,.2,2)))]
    packet={'fixture':fixture,'native_match_key':1,'state':'available','source_id':'source',
            'side_coverage':[dict(side_index=0,state='available',shot_count=2,shots_on_target=1,expected_goals=.3,own_goal_marker_count=0),
                             dict(side_index=1,state='available',shot_count=0,shots_on_target=0,expected_goals=0.,own_goal_marker_count=0)],
            'shots':rows,'own_goal_markers':[]}
    capture={'save':{'name':'Career','created_date':'2025-10-23','save_count':7},'fixtures':[{'fixture':fixture,'native_match_key':1}]}
    evidence=dict(fixture=fixture,native_match_key=1,capture_id='host-evidence',source_kind='host_captured_period_observation',
                  confidence='verified_retrospective_continuity',link_state='verified_retrospective_continuity',
                  observed_save={'name':'Career','created_date':'2025-10-23','save_count':6},
                  time_slice_domain='native_playback_time_slice',official_match_unique_id=123,
                  provenance={'proof':'native bound period ledger and semantic prefix'},
                  intervals=[dict(period='FirstHalf',start_tick=1,end_tick=10),dict(period='SecondHalf',start_tick=12,end_tick=20)],
                  shot_periods=[dict(row,period=period)for row,period in zip(rows,('FirstHalf','SecondHalf'))])
    return capture,packet,evidence


def test_periods_join_real_shots_and_preserve_names_and_computed_scope():
    capture,packet,evidence=inputs()
    db=build_connection(capture,shot_maps=[packet],period_evidence=[evidence])
    assert db.execute('select period,shooter_name from shot_periods order by event_id').fetchall()==[('FirstHalf','Name'),('SecondHalf','Name')]
    assert db.execute('select period,shots,expected_goals_sum_computed from match_period_team_totals where side_index=0 order by period').fetchall()==[('FirstHalf',1,.1),('SecondHalf',1,.2)]
    assert db.execute('select sum(shots) from match_period_team_totals where side_index=1').fetchone()==(0,)
    assert db.execute('pragma foreign_key_check').fetchall()==[]


def test_boundary_equality_is_unknown_not_assigned_to_either_half():
    capture,packet,evidence=inputs();packet['shots'][0]['native_clock_end_raw']=10
    evidence['shot_periods'][0].update(native_clock_end_raw=10,period=None)
    db=build_connection(capture,shot_maps=[packet],period_evidence=[evidence])
    assert db.execute('select period,assignment_state from shot_periods where event_id=1').fetchone()==(None,'unknown_boundary_or_unavailable_interval')


@pytest.mark.parametrize('failure',['career','event','clock','wrong_period','unverified','overlap','payload'])
def test_invalid_host_link_or_semantics_never_write_output(tmp_path,failure):
    capture,packet,evidence=inputs()
    if failure=='career':evidence['observed_save']['name']='Other'
    if failure=='event':evidence['shot_periods'][0]['event_id']=99
    if failure=='clock':evidence['shot_periods'][0]['native_clock_end_raw']=4
    if failure=='wrong_period':evidence['shot_periods'][0]['period']='SecondHalf'
    if failure=='unverified':evidence['confidence']='guess'
    if failure=='overlap':evidence['intervals'][1]['start_tick']=9
    if failure=='payload':evidence['shot_periods'][0]['native_x']=3.
    output=tmp_path/'match.sqlite'
    with pytest.raises(ValueError):export_dataset(output,capture,shot_maps=[packet],period_evidence=[evidence])
    assert not output.exists()


def test_period_optional_input_requires_shot_source_and_default_unchanged():
    capture,packet,evidence=inputs()
    with pytest.raises(ValueError,match='shot maps'):
        build_connection(capture,period_evidence=[evidence])
    db=build_connection(capture,shot_maps=[packet])
    assert not db.execute("select name from sqlite_master where name='match_periods'").fetchall()
