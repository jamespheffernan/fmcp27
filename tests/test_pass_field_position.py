import struct
import pytest
from fm_live_mcp.pass_field_position import project_event_location,verify_native


def event(x=0,y=0,positive=True,category=8):
    b=bytearray(56);struct.pack_into('<ff',b,24,x,y);b[39]=4;b[40]=1;b[42]=category
    struct.pack_into('<I',b,44,99);struct.pack_into('<H',b,48,256 if positive else 0)
    return bytes(b)


def project(e,**kw):
    return project_event_location(e,{'half_width_native':30,'half_length_native':45},
        expected_event_id=99,expected_side_index=1,expected_player_slot=4,**kw)


@pytest.mark.parametrize('y,third',[(-45,'defensive'),(-15,'middle'),(0,'middle'),(15,'attacking'),(45,'attacking')])
def test_explicit_thirds_and_boundaries(y,third):
    r=project(event(y=y));assert r['analytical_pitch_third']==third
    assert r['ball_release_location']=={'native_x':0,'native_y':y} and r['intended_destination'] is None
    assert r['location_semantics']=='official_pass_map_event_location; pass_origin_proved'


def test_half_change_and_side_do_not_reverse_forward_location():
    a=project(event(x=12,y=20,positive=True));b=project(event(x=-12,y=-20,positive=False))
    assert a['attack_relative_longitudinal_coordinate']==b['attack_relative_longitudinal_coordinate']==20
    assert a['analytical_pitch_third']==b['analytical_pitch_third']=='attacking'
    assert a['analytical_lateral_channel']==b['analytical_lateral_channel']=='outer'
    assert a['absolute_lateral_centerline_distance']==b['absolute_lateral_centerline_distance']==12


def test_zero_location_preserved_and_outside_pitch_not_binned():
    r=project(event());assert r['native_pass_map_location']=={'native_x':0,'native_y':0}
    assert r['analytical_pitch_third']=='middle'
    assert project(event(x=31))['analytical_lateral_channel'] is None


def test_bound_path_endpoint_is_not_an_intended_destination():
    e=event(2,3);raw=e[24:32]+struct.pack('<ff',10,20)
    r=project(e,path={'event_id':99,'raw_xy_pairs':raw})
    assert r['sampled_path_endpoint']['native_y']==20
    assert r['intended_destination'] is None
    end=r['sampled_path_endpoint']
    assert (end['analytical_pitch_third'],end['analytical_lateral_channel'],end['semantics'])==('attacking','central','opponent_won_ball')


def test_completed_pass_endpoint_is_the_reception_with_its_own_third_and_channel():
    # played from the defensive third on the centre line, taken in the middle third out wide
    e=event(0,-40,category=7);raw=e[24:32]+struct.pack('<ff',8,-30)+struct.pack('<ff',25,5)
    r=project(e,path={'event_id':99,'raw_xy_pairs':raw})
    assert (r['analytical_pitch_third'],r['analytical_lateral_channel'])==('defensive','central')
    end=r['sampled_path_endpoint']
    assert end['semantics']=='reception_by_named_recipient' and end['inside_native_pitch_extents'] is True
    assert (end['analytical_pitch_third'],end['analytical_lateral_channel'])==('middle','outer')
    # attacking the negative end, the same points mirror
    e=event(0,40,positive=False,category=7);raw=e[24:32]+struct.pack('<ff',-25,-5)
    end=project(e,path={'event_id':99,'raw_xy_pairs':raw})['sampled_path_endpoint']
    assert (end['attack_relative_longitudinal_coordinate'],end['analytical_pitch_third'])==(5,'middle')
    # an end point beyond the pitch is not binned
    e=event(0,0,category=11);raw=e[24:32]+struct.pack('<ff',31,0)
    end=project(e,path={'event_id':99,'raw_xy_pairs':raw})['sampled_path_endpoint']
    assert end['semantics']=='out_of_play' and end['analytical_pitch_third'] is None
    with pytest.raises(ValueError,match='first position differs'):
        project(e,path={'event_id':99,'raw_xy_pairs':struct.pack('<ff',4,5)})


def test_wrong_event_actor_nonpass_and_mask_fail_closed():
    for offset,value in [(39,5),(40,0),(42,5),(48,8)]:
        e=bytearray(event());e[offset]=value
        with pytest.raises(ValueError):project(bytes(e))
    with pytest.raises(ValueError):project(event(x=float('nan')))
    with pytest.raises(ValueError,match='native source changed'):verify_native(lambda a,n:b'\0'*n,0)
