from copy import deepcopy
import pytest
from fm_live_mcp.frame_proximity import project_frame_proximity


def entity(i,side,person,xy):
    return dict(entity_index=i,side_index=side,canonical_person_id=person,
                person_name=f'Name {person}',team_native_id=100+side if side is not None else None,
                position_samples=[{'native_local_time':1.,'native_xy':xy}])


def packet():
    return {'frame_tick':42,'source_id':'one','same_session_fixed_frame_verified':True,
            'common_world_xy_verified':True,'coverage':{'typed_player_entities':5},
            'ball_samples':[dict(native_local_time=1.,native_xyz=[0.,4.,99.])],
            'typed_player_entities':[entity(1,0,11,[0,0]),entity(2,0,12,[0,0]),
                                     entity(3,1,13,[3,4]),entity(4,1,14,[-4,3]),entity(5,None,None,[6,0])]}


def run(p):return project_frame_proximity(p,11,visible_person_ids={11,12,13,14})


def test_planar_distance_all_ties_and_outside_unidentified():
    r=run(packet())
    assert r['ball_planar_separation_native']==4 and r['nearest_named_planar_separation_native']==5
    assert r['nearest_opponent_state']=='verified_nearest_opponents_among_typed_frame_players'
    assert [p['person_native_id'] for p in r['nearest_named_opponents']]==[13,14]
    assert r['on_pitch_population_verified'] is False and r['physical_units'] is None


@pytest.mark.parametrize('point', [[1,0],[5,0]])
def test_denies_unqualified_nearest_if_anonymous_could_be_closer_or_tied(point):
    p=packet();p['typed_player_entities'][-1]['position_samples'][0]['native_xy']=point
    assert run(p)['nearest_opponent_state']=='unknown_other_entity_as_close_or_closer'


def test_hidden_person_never_named_and_same_side_not_an_opponent():
    p=packet(); p['typed_player_entities'][3]['position_samples'][0]['native_xy']=[.1,0]
    r=project_frame_proximity(p,11,visible_person_ids={11,13})
    assert 'Name 14' not in str(r) and r['nearest_named_planar_separation_native']==5
    assert r['nearest_opponent_state']=='unknown_other_entity_as_close_or_closer'
    assert project_frame_proximity(p,14,visible_person_ids={11,13})=={'state':'unavailable_selected_person'}


def test_missing_and_ambiguous_endpoints_and_census_fail_closed():
    p=packet();p['typed_player_entities'][-1]['position_samples'][0]['native_local_time']=.999
    assert run(p)['nearest_opponent_state']=='unknown_other_endpoint_missing'
    p['ball_samples']*=2
    assert run(p)['ball_planar_separation_native'] is None
    p['typed_player_entities'][0]['position_samples']*=2
    assert run(p)['state']=='unavailable_selected_endpoint'
    p['coverage']['typed_player_entities']=6
    assert run(p)['state']=='unavailable_entity_census'


def test_duplicate_person_or_unchecked_frame_and_axes_never_publish():
    p=packet();p['typed_player_entities'][2]['canonical_person_id']=11
    assert run(p)['state']=='unavailable_duplicate_person'
    for field in ('same_session_fixed_frame_verified','common_world_xy_verified'):
        value=deepcopy(packet());value[field]=False
        assert run(value)['state']=='unavailable_frame_or_world_coordinates'
