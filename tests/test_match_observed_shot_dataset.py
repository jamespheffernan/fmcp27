import copy
import json
import pytest
from fm_live_mcp.match_dataset import build_connection
from fm_live_mcp.match_observed_shot_dataset import SCOPE, AVAILABLE
from test_match_shot_dataset import packet, fixture, detailed_packet


def observed_packet():
    p=packet()
    p.update(source_observed_policy='independent player count closure; xG unreconciled',
             location_provenance={'checked':True},body_part_policy='checked groups',outcome_policy='exclusive')
    p['side_coverage'][1]['state']='unavailable_unreconciled_retained_side'
    r=copy.deepcopy(detailed_packet()['shots'][0]);r.update(side_index=1,event_side_index=1,stored_player_slot=2,
        native_expected_goals=r.pop('expected_goals'),verification_scope=SCOPE,
        actor={'canonical_person_id':42,'person_name':'Checked actor','canonical_team_id':99},
        xg_reconciliation={'team_float32_ulp_distance':2,'player_float32_ulp_distance':0,'player_nonpenalty_float32_ulp_distance':2})
    p['source_observed_shots']=[r]
    p['source_observed_coverage']=[{'side_index':1,'state':AVAILABLE,'observed_shot_count':1,
        'rostered_players_checked':20,'zero_shot_players_checked':19,'verified_shots_promoted':False,
        'xg_tolerance_widened':False,'team_xg_diagnostic':{'xg_float32_ulp_distance':2}}]
    return p


def test_source_observations_never_enter_strict_shots_or_counts():
    p=observed_packet();db=build_connection({'fixtures':[fixture()]},shot_maps=[p])
    assert db.execute('SELECT count(*)FROM shots').fetchone()==(0,)
    assert db.execute('SELECT state,shot_count,expected_goals FROM shot_map_coverage WHERE side_index=1').fetchone()==('unavailable_unreconciled_retained_side',None,None)
    assert db.execute('SELECT native_expected_goals,canonical_person_id,person_name,verification_scope,team_xg_ulp_distance,player_xg_ulp_distance FROM source_observed_shots').fetchone()==(.5,42,'Checked actor',SCOPE,2,0)
    columns=[r[1]for r in db.execute('PRAGMA table_info(source_observed_shots)')]
    assert 'expected_goals' not in columns
    assert db.execute('SELECT state,observed_shot_count,verified_shots_promoted,xg_tolerance_widened FROM source_observed_shot_coverage WHERE side_index=1').fetchone()==(AVAILABLE,1,0,0)
    assert db.execute('SELECT field_group,state,known_attempt_count FROM source_observed_field_coverage WHERE side_index=1 ORDER BY field_group').fetchall()==[('body_part','complete',1),('location','complete',1),('outcome','complete',1)]
    assert json.loads(db.execute("SELECT value_json FROM metadata WHERE key='shot_map_schema_revision'").fetchone()[0])==3
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    db.close()


@pytest.mark.parametrize('mutation',['promotion','widening','missing_coverage','strict_duplicate','wrong_actor','wrong_scope','wrong_team_xg','ambiguous_xg'])
def test_observed_export_rejects_unverified_or_mixed_scope(mutation):
    p=observed_packet();r=p['source_observed_shots'][0];c=p['source_observed_coverage'][0]
    if mutation=='promotion':c['verified_shots_promoted']=True
    elif mutation=='widening':c['xg_tolerance_widened']=True
    elif mutation=='missing_coverage':p['source_observed_coverage']=[]
    elif mutation=='strict_duplicate':r['side_index']=r['event_side_index']=0
    elif mutation=='wrong_actor':r['actor']['canonical_team_id']=688
    elif mutation=='wrong_scope':r['verification_scope']='strict'
    elif mutation=='wrong_team_xg':r['xg_reconciliation']['team_float32_ulp_distance']=1
    else:r['expected_goals']=.5
    with pytest.raises(ValueError):build_connection({'fixtures':[fixture()]},shot_maps=[p])


def test_explicit_missing_source_preserves_null_observed_counts():
    db=build_connection({'fixtures':[fixture()],'source_observed_shots_requested':True},shot_maps=[packet()])
    assert db.execute('SELECT state,observed_shot_count,rostered_players_checked FROM source_observed_shot_coverage ORDER BY side_index').fetchall()==[('not_needed_strict_side_available',0,None),('unavailable_source_observed_verification',None,None)]
    db.close()
    db=build_connection({'fixtures':[fixture()]},shot_maps=[packet()])
    assert db.execute("SELECT count(*)FROM sqlite_master WHERE name='source_observed_shots'").fetchone()==(0,)
    db.close()
