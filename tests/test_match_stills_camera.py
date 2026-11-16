from copy import deepcopy

import pytest

from fm_live_mcp.match_stills_camera import editorial_camera, project


def scene():
    return {'goal': {'actor': {'canonical_person_id': 7}, 'attacked_goal_positive_native_y': True},
            'replay': {'players': [{'canonical_person_id': 7, 'person_name': 'Scorer', 'native_xy': [6.6, 47.6]}],
                       'ball_native_xyz': [3.7, 46.9, 3.4],
                       'retained_pitch_geometry': {'half_length_native': 52.5}}}


def test_camera_is_artistic_without_mutating_decoded_positions():
    data = scene()
    original = deepcopy(data)
    camera = editorial_camera(data)
    assert data == original
    assert camera['source'] == 'artistic_camera_choice_not_game_camera'
    assert camera['projected_ball']['inside_image']
    assert camera['projected_ground_anchors'][0]['canonical_person_id'] == 7


def test_aim_point_is_image_centre_and_behind_camera_is_not_visible():
    camera = editorial_camera(scene())
    assert project(camera['look_at_native'], camera)['uv'] == pytest.approx([.5, .5])
    behind = [2*p-t for p, t in zip(camera['position_native'], camera['look_at_native'])]
    assert project(behind, camera) == {'in_front': False, 'uv': None}


def test_reversing_attacking_direction_rotates_camera_with_players():
    data = scene()
    before = editorial_camera(data)
    data['goal']['attacked_goal_positive_native_y'] = False
    data['replay']['players'][0]['native_xy'] = [-6.6, -47.6]
    data['replay']['ball_native_xyz'] = [-3.7, -46.9, 3.4]
    after = editorial_camera(data)
    assert before['projected_ball']['uv'] == pytest.approx(after['projected_ball']['uv'])
    assert before['projected_ground_anchors'][0]['uv'] == pytest.approx(after['projected_ground_anchors'][0]['uv'])


def test_camera_requires_replay_extent_and_finite_point():
    with pytest.raises(ValueError, match='decoded replay'):
        editorial_camera({})
    data = scene()
    del data['replay']['retained_pitch_geometry']
    with pytest.raises(ValueError, match='pitch extents'):
        editorial_camera(data)
    with pytest.raises(ValueError, match='finite XYZ'):
        project([float('nan'), 0, 0], editorial_camera(scene()))
