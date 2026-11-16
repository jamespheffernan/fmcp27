import copy
import json
import sqlite3

import pytest

from fm_live_mcp.match_dataset import build_connection, export_dataset


def fixture(ref='ref', key=1, day='2030-10-23'):
    return {'native_match_key': key, 'fixture': {'fixture_ref': ref, 'date': day,
            'competition': {'native_id': 11},
            'home_team': {'native_id': 688, 'database_index': 545, 'native_type_code': 0},
            'away_team': {'native_id': 99, 'database_index': 3, 'native_type_code': 0}}}


def packet(f=None):
    f=f or fixture()
    return {'fixture_ref': f['fixture']['fixture_ref'], 'fixture': copy.deepcopy(f['fixture']),
            'native_match_key': f['native_match_key'], 'source_id': 'verified-source', 'state': 'available_partial',
            'side_coverage': [
                {'side_index': 0, 'state': 'available', 'shot_count': 0,
                 'shots_on_target': 0, 'expected_goals': 0.0, 'own_goal_marker_count': 0},
                {'side_index': 1, 'state': 'not_retained', 'shot_count': None,
                 'shots_on_target': None, 'expected_goals': None, 'own_goal_marker_count': None}],
            'shots': [], 'own_goal_markers': []}


def test_true_zero_is_distinct_from_unretained_unknown():
    db=build_connection({'fixtures': [fixture()]},shot_maps=[packet()])
    assert db.execute('SELECT side_index,state,shot_count,expected_goals FROM shot_map_coverage ORDER BY side_index').fetchall()==[
        (0,'available',0,0.0),(1,'not_retained',None,None)]
    assert db.execute('SELECT count(*) FROM shots').fetchone()==(0,)
    assert json.loads(db.execute("SELECT value_json FROM metadata WHERE key='schema_version'").fetchone()[0])==2
    assert db.execute('PRAGMA foreign_key_check').fetchall()==[]
    db.close()


def test_rows_and_own_goal_markers_have_separate_counts_and_raw_coordinates():
    p=packet()
    p['side_coverage'][0].update(shot_count=1,shots_on_target=1,expected_goals=0.25,own_goal_marker_count=1)
    p['shots']=[{'side_index':0,'record_index':3,'native_x':-12.5,'native_y':4.25,'expected_goals':0.25,'unproved_word':123}]
    p['own_goal_markers']=[{'beneficiary_side_index':0,'event_side_index':1,'record_index':4,
                            'native_x':0.0,'native_y':0.0,'native_expected_goals':0.0,'native_code':49}]
    db=build_connection({'fixtures':[fixture()]},shot_maps=[p])
    assert db.execute('SELECT side_index,record_index,native_x,native_y,expected_goals FROM shots').fetchone()==(0,3,-12.5,4.25,0.25)
    assert db.execute('SELECT beneficiary_side_index,event_side_index,record_index,native_expected_goals FROM own_goal_markers').fetchone()==(0,1,4,0.0)
    assert json.loads(db.execute('SELECT raw_json FROM shots').fetchone()[0])['unproved_word']==123
    db.close()


def test_no_packet_is_not_captured_not_zero_and_default_schema_is_unchanged():
    db=build_connection({'fixtures':[fixture()]},shot_maps=[])
    assert db.execute('SELECT state,shot_count FROM shot_map_coverage').fetchall()==[('not_captured',None),('not_captured',None)]
    db.close()
    db=build_connection({'fixtures':[fixture()]})
    assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='shots'").fetchone()==(0,)
    assert json.loads(db.execute("SELECT value_json FROM metadata WHERE key='schema_version'").fetchone()[0])==1
    db.close()


@pytest.mark.parametrize('mutation', ['ref','key','date','competition','team_id','team_index','type'])
def test_source_must_match_complete_selected_fixture_identity(mutation):
    p=packet()
    if mutation=='ref':p['fixture_ref']='foreign'
    elif mutation=='key':p['native_match_key']=42
    elif mutation=='date':p['fixture']['date']='2030-10-24'
    elif mutation=='competition':p['fixture']['competition']['native_id']=1
    elif mutation=='team_id':p['fixture']['home_team']['native_id']=1
    elif mutation=='team_index':p['fixture']['home_team']['database_index']=1
    elif mutation=='type':p['fixture']['home_team']['native_type_code']=1
    with pytest.raises(ValueError,match='fixture'):
        build_connection({'fixtures':[fixture()]},shot_maps=[p])


def test_native_key_duplicates_are_joined_by_the_verified_fixture_ref_not_key_alone():
    first=fixture('a',key=1)
    second=fixture('b',key=1,day='2030-10-24')
    db=build_connection({'fixtures':[first,second]},shot_maps=[packet(first),packet(second)])
    assert db.execute('SELECT count(DISTINCT fixture_id),count(*) FROM shot_map_coverage').fetchone()==(2,4)
    db.close()
    with pytest.raises(ValueError,match='one exact'):
        build_connection({'fixtures':[first,first]},shot_maps=[packet(first)])


def test_unknown_source_never_acquires_a_zero_or_unverified_rows():
    p=packet()
    p['side_coverage'][1]['shot_count']=0
    with pytest.raises(ValueError,match='null counts'):
        build_connection({'fixtures':[fixture()]},shot_maps=[p])
    p=packet();p['side_coverage'][0]['shot_count']=1
    with pytest.raises(ValueError,match='disagree'):
        build_connection({'fixtures':[fixture()]},shot_maps=[p])


def test_export_publication_is_atomic_and_preserves_a_concurrent_destination(tmp_path,monkeypatch):
    import fm_live_mcp.match_dataset as module
    output=tmp_path/'new.sqlite'
    original=module.os.link
    def racing_publish(source,target):
        assert not output.exists()
        output.write_bytes(b'other writer')
        return original(source,target)
    monkeypatch.setattr(module.os,'link',racing_publish)
    with pytest.raises(FileExistsError):export_dataset(output,{'fixtures':[fixture()]},shot_maps=[packet()])
    assert output.read_bytes()==b'other writer'
    assert list(tmp_path.glob('*.sqlite.tmp'))==[]


def test_invalid_shot_packet_leaves_no_partial_file(tmp_path):
    output=tmp_path/'bad.sqlite'
    p=packet();p['native_match_key']=42
    with pytest.raises(ValueError):export_dataset(output,{'fixtures':[fixture()]},shot_maps=[p])
    assert not output.exists()
    assert list(tmp_path.iterdir())==[]


def test_unavailable_packet_preserves_unknown_canonical_identity_without_inventing_counts():
    f=fixture();f['fixture']['away_team']['native_id']=None
    p=packet(f)
    p['side_coverage'][0].update(state='unavailable_fixture_identity',shot_count=None,shots_on_target=None,expected_goals=None,own_goal_marker_count=None)
    db=build_connection({'fixtures':[f]},shot_maps=[p])
    assert db.execute('SELECT state,shot_count FROM shot_map_coverage ORDER BY side_index').fetchall()==[
        ('unavailable_fixture_identity',None),('not_retained',None)]
    db.close()
    p['side_coverage'][0].update(state='available',shot_count=0,shots_on_target=0,expected_goals=0.0,own_goal_marker_count=0)
    with pytest.raises(ValueError,match='fully bound'):
        build_connection({'fixtures':[f]},shot_maps=[p])


def test_wrong_side_team_and_own_goal_attempt_are_rejected():
    p=packet();p['side_coverage'][0]['team_native_id']=999
    with pytest.raises(ValueError,match='TEAM identity'):
        build_connection({'fixtures':[fixture()]},shot_maps=[p])
    p=packet();p['side_coverage'][0].update(shot_count=1,shots_on_target=0,expected_goals=0.0)
    p['shots']=[{'side_index':0,'record_index':0,'native_category_code':49,'expected_goals':0.0}]
    with pytest.raises(ValueError,match='separate from statistical'):
        build_connection({'fixtures':[fixture()]},shot_maps=[p])


@pytest.mark.parametrize('shot_maps',[None,[]])
def test_99_position_columns_keep_their_ordinals_and_values_in_both_schema_modes(shot_maps):
    from fm_live_mcp.match_dataset import PLAYER_ADDITIONAL_FIELDS
    assert PLAYER_ADDITIONAL_FIELDS[35:39]==('progressive_passes','stored_match_position_mask','stored_match_position','stored_match_position_state')
    row={'fixture_key':1,'side_index':0,'person_index_word':7,'stored_player_slot':2,
         'minutes':90,'progressive_passes':4,'stored_match_position_mask':128,
         'stored_match_position':'DM(C)','stored_match_position_state':'named'}
    db=build_connection({'fixtures':[fixture()]},retained_players=[row],shot_maps=shot_maps)
    columns=[column[1] for column in db.execute('PRAGMA table_info(retained_players)')]
    assert columns[59:63]==['progressive_passes','stored_match_position_mask','stored_match_position','stored_match_position_state']
    for table in ('retained_players','player_match_analysis'):
        assert db.execute('SELECT minutes,progressive_passes,stored_match_position_mask,stored_match_position,stored_match_position_state FROM '+table).fetchone()==(90,4,128,'DM(C)','named')
    db.close()


@pytest.mark.parametrize('fields,expected',[
    ({},(None,None,None,None)),
    ({'native_shot_type':7,'is_penalty':True,'shot_situation':'penalty','shot_situation_state':'checked_native_enum'},(7,1,'penalty','checked_native_enum')),
    ({'native_shot_type':1,'is_penalty':False,'shot_situation':'non_penalty_unspecified','shot_situation_state':'checked_native_enum'},(1,0,'non_penalty_unspecified','checked_native_enum')),
])
def test_checked_penalty_columns_preserve_null_false_and_true(fields,expected):
    p=packet();p['side_coverage'][0].update(shot_count=1,shots_on_target=1,expected_goals=0.5)
    p['shots']=[{'side_index':0,'record_index':0,'expected_goals':0.5,**fields}]
    db=build_connection({'fixtures':[fixture()]},shot_maps=[p])
    assert db.execute('SELECT native_shot_type,is_penalty,shot_situation,shot_situation_state FROM shots').fetchone()==expected
    db.close()


def detailed_packet():
    p=packet()
    p['side_coverage'][0].update(shot_count=2, shots_on_target=1, expected_goals=0.5)
    p.update(pitch_geometry={'half_width_native':34.,'half_length_native':52.5},
             location_provenance={'checked':True},body_part_policy='checked groups',outcome_policy='exclusive checked states')
    p['shots']=[
        {'side_index':0,'record_index':0,'event_id':0,'native_category_code':4,'expected_goals':0.5,
         'body_part':'feet','is_header':False,'body_part_state':'native_shotmap_group_proved',
         'outcome':'saved','native_outcome_label':'CBE_END_SHOT_SAVED','outcome_state':'official_native_end_shot_category',
         'native_location_bin':1,'official_location':'LocationPenaltyBoxNearSpot','location_group':'inside_area',
         'location_state':'native_renderer_predicate','attacked_goal_positive_native_y':False},
        {'side_index':0,'record_index':3,'event_id':7,'native_category_code':3,'expected_goals':0.,
         'body_part':None,'is_header':None,'body_part_state':'native_type_unclassified',
         'outcome':'hit_woodwork','native_outcome_label':'CBE_END_SHOT_HIT_WOODWORK','outcome_state':'official_native_end_shot_category',
         'native_location_bin':12,'official_location':'LocationOutsideBoxFarFromGoal',
         'location_group':'outside_area_or_native_fallback','location_state':'native_renderer_predicate',
         'attacked_goal_positive_native_y':True},
    ]
    return p


def test_detail_columns_are_additive_and_preserve_false_zero_unknown_and_ordinals():
    p=detailed_packet();db=build_connection({'fixtures':[fixture()]},shot_maps=[p])
    columns=[r[1]for r in db.execute('PRAGMA table_info(shots)')]
    assert columns[:13]==['fixture_id','native_match_key','side_index','record_index','source_id','native_x','native_y',
                         'expected_goals','native_shot_type','is_penalty','shot_situation','shot_situation_state','raw_json']
    assert db.execute('SELECT event_id,body_part,is_header,outcome,native_location_bin,location_group,attacked_goal_positive_native_y FROM shots ORDER BY record_index').fetchall()==[
        (0,'feet',0,'saved',1,'inside_area',0),(7,None,None,'hit_woodwork',12,'outside_area_or_native_fallback',1)]
    assert db.execute('SELECT field_group,state,known_attempt_count,unknown_attempt_count FROM shot_field_coverage WHERE side_index=0 ORDER BY field_group').fetchall()==[
        ('body_part','partial',1,1),('location','complete',2,0),('outcome','complete',2,0)]
    assert db.execute('SELECT known_attempt_count,unknown_attempt_count FROM shot_field_coverage WHERE side_index=1').fetchall()==[(None,None)]*3
    assert db.execute('SELECT pitch_half_width_native,pitch_half_length_native FROM shot_map_coverage ORDER BY side_index').fetchall()==[(34.,52.5),(None,None)]
    assert db.execute('SELECT count(*)FROM shot_attempt_analysis').fetchone()==(2,)
    assert json.loads(db.execute("SELECT value_json FROM metadata WHERE key='shot_map_schema_revision'").fetchone()[0])==2
    db.close()


def test_old_packet_never_acquires_details_from_existing_native_codes():
    p=packet();p['side_coverage'][0].update(shot_count=1,shots_on_target=1,expected_goals=0.5)
    p['shots']=[{'side_index':0,'record_index':0,'native_shot_type':2,'native_category_code':1,'expected_goals':0.5}]
    db=build_connection({'fixtures':[fixture()]},shot_maps=[p])
    assert db.execute('SELECT body_part,is_header,outcome,native_outcome_label,outcome_state,native_location_bin,official_location,location_group,location_state,attacked_goal_positive_native_y FROM shots').fetchone()==(None,)*10
    assert db.execute('SELECT state,known_attempt_count,unknown_attempt_count FROM shot_field_coverage WHERE side_index=0').fetchall()==[('not_captured',0,1)]*3
    db.close()


@pytest.mark.parametrize('change',[{'is_header':1},{'native_location_bin':13},{'native_location_bin':1,'official_location':'LocationSixYardBox'},{'outcome':'blocked'},{'body_part':'head','is_header':False}])
def test_contradictory_detail_fields_reject_export(change):
    p=detailed_packet();p['shots'][0].update(change)
    with pytest.raises(ValueError):build_connection({'fixtures':[fixture()]},shot_maps=[p])


def test_true_zero_detail_coverage_needs_explicit_feature_capture_policy():
    p=packet();db=build_connection({'fixtures':[fixture()]},shot_maps=[p])
    assert db.execute('SELECT state,known_attempt_count FROM shot_field_coverage WHERE side_index=0').fetchall()==[('not_captured',None)]*3
    db.close()
    p.update(location_provenance={'checked':True},pitch_geometry={'half_length_native':52.5},body_part_policy='checked',outcome_policy='checked')
    db=build_connection({'fixtures':[fixture()]},shot_maps=[p])
    assert db.execute('SELECT state,known_attempt_count,unknown_attempt_count FROM shot_field_coverage WHERE side_index=0').fetchall()==[('complete',0,0)]*3
    db.close()
