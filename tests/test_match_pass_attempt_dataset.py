import pytest
from fm_live_mcp.match_dataset import build_connection,export_dataset


def inputs():
    fixture={'date':'2030-11-02','competition':{'native_id':11},'home_team':{'native_id':688,'database_index':545},'away_team':{'native_id':713,'database_index':570}}
    capture={'fixtures':[{'fixture':fixture,'native_match_key':1}]}
    players=[dict(fixture_key=1,side_index=side,stored_player_slot=slot,canonical_person_id=person,person_name=name,
                  passes_attempted=attempts,passes_completed=completed)
             for side,slot,person,name,attempts,completed in[(0,0,100,'One',1,1),(0,1,101,'Two',0,0),(1,0,200,'Other',0,0)]]
    row=dict(event_id=0,record_index=0,side_index=0,stored_player_slot=0,person_native_id=100,person_name='One',
             native_category_code=7,completed=True,outcome='completed',specific_failure_reason=None,
             recipient_person_native_id=101,recipient_name='Two',recipient_state='canonical_completed_pass_recipient',native_flags_word=256,
             native_event_x=1.,native_event_y=2.,native_path_start_x=1.,native_path_start_y=2.,native_path_end_x=3.,native_path_end_y=4.,
             native_path_points=[{'x':1.,'y':2.},{'x':3.,'y':4.}],geometry_state='raw_native_sampled_path',origin_destination_state='not_proved',
             coordinate_units=None,phase=None,displayed_time=None)
    packet=dict(fixture=fixture,native_match_key=1,state='available',attempts=[row],side_coverage=[
        dict(side_index=side,state='available',attempt_count=n,completed_count=n,not_completed_count=0,
             all_captured_player_attempt_counters_match=True,all_captured_player_completion_counters_match=True)
        for side,n in((0,1),(1,0))])
    return capture,players,packet


def test_lossless_named_attempt_and_uninterpreted_path_points():
    capture,players,packet=inputs();db=build_connection(capture,retained_players=players,pass_attempts=[packet])
    assert db.execute('select person_name,recipient_name,completed,origin_destination_state from pass_attempts').fetchone()==('One','Two',1,'not_proved')
    assert db.execute('select point_index,native_x,native_y from pass_path_points').fetchall()==[(0,1.,2.),(1,3.,4.)]
    assert db.execute('pragma foreign_key_check').fetchall()==[]


@pytest.mark.parametrize('failure',['person','counter','phase','mask','duplicate'])
def test_pass_source_mismatch_cannot_create_output(tmp_path,failure):
    capture,players,packet=inputs();row=packet['attempts'][0]
    if failure=='person':row['person_native_id']=999
    if failure=='counter':players[0]['passes_attempted']=2
    if failure=='phase':row['phase']='FirstHalf'
    if failure=='mask':row['native_flags_word']|=8
    if failure=='duplicate':packet['attempts']*=2
    output=tmp_path/'data.sqlite'
    with pytest.raises(ValueError):export_dataset(output,capture,retained_players=players,pass_attempts=[packet])
    assert not output.exists()
