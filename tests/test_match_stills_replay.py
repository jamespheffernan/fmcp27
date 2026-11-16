"""Historical frame joins must fail closed on another event or clock."""
from copy import deepcopy
import hashlib
import json
import struct

import pytest

from fm_live_mcp.match_stills import prepare, prompt, build_packet
from fm_live_mcp.match_stills_replay import check_event, project_frame
from test_match_stills import capture


@pytest.fixture
def source(capture):
    goal = capture['shots']['attempts'][0]
    goal.update(native_x=6.5, native_y=47.5, native_shot_type=10, native_xg_value=.125,
                native_clock_start_raw=15327, native_clock_end_raw=15330,
                stored_player_slot=3, native_category_code=1)
    shot, event = bytearray(48), bytearray(56)
    struct.pack_into('<fI', shot, 32, .125, 1454)
    shot[44] = 10
    struct.pack_into('<ff', event, 24, 6.5, 47.5)
    struct.pack_into('<H', event, 34, 15327)
    event[39], event[40], event[42] = 3, 0, 1
    struct.pack_into('<I', event, 44, 1454)
    struct.pack_into('<H', event, 50, 15330)
    goal['source_record_sha256'] = hashlib.sha256(shot).hexdigest()
    return capture, goal, bytes(shot), bytes(event)


def test_replay_opaque_fields_may_change_without_changing_shot(source):
    _, goal, shot, event = source
    opaque = bytearray(shot)
    opaque[0] = 9
    joined = check_event([bytes(opaque), b''], event, goal)
    assert joined['opaque_record_bytes_equal'] is False
    assert joined['native_clock_start_raw'] == 15327
    assert joined['retained_shot_record_sha256'] == goal['source_record_sha256']


@pytest.mark.parametrize('field,value', [
    ('native_x', 7), ('native_clock_start_raw', 15326), ('stored_player_slot', 4),
    ('native_shot_type', 0), ('native_xg_value', .25), ('side_index', 1),
    ('native_category_code', 4),
])
def test_rejects_changed_shot_meaning(source, field, value):
    _, goal, shot, event = source
    goal[field] = value
    with pytest.raises(ValueError, match='differ'):
        check_event([shot, b''], event, goal)


def test_rejects_duplicate_replay_event(source):
    _, goal, shot, event = source
    with pytest.raises(ValueError, match='ambiguous'):
        check_event([shot, b''], event*2, goal)
    with pytest.raises(ValueError, match='ambiguous'):
        check_event([shot, shot], event, goal)


def replay_for(source):
    cap, goal, shot, event = source
    return {'state': 'verified_historical_replay_frame', 'fixture': deepcopy(cap['fixture']['fixture']),
            'event_id': 1454, 'source_id': cap['shots']['source_id'],
            'event_binding': check_event([shot, b''], event, goal), 'frame_tick': 15330,
            'ball_native_xyz': [2.3, 54.5, 1.3],
            'players': [{'canonical_person_id': 28124573, 'person_name': 'Levi Colwill',
                         'native_xy': [5.5, 47.8], 'side_index': 0}]}


def test_editorial_foot_goal_does_not_inherit_previous_scorer_or_header(source):
    cap = source[0]
    cap['shots']['attempts'][0]['body_part'] = 'feet'
    cap['shots']['attempts'][0]['actor']['person_name'] = 'Konstantinos Karetsas'
    replay = replay_for(source)
    scene = prepare(cap, 1454, [], replay=replay)
    scene['camera'] = {'preset': 'goal_line_editorial'}
    text = prompt(scene, 'goal')
    assert 'Konstantinos Karetsas' in text
    assert 'Colwill' not in text.split('CHOSEN EDITORIAL CAMERA')[1]
    assert 'this headed goal' not in text
    assert 'aerial challenge' not in text
    assert 'decoded body part (feet)' in text


@pytest.mark.parametrize('change', ['fixture', 'source', 'hash', 'event', 'time', 'scorer'])
def test_build_rejects_misjoined_replay(source, change):
    cap = source[0]
    r = replay_for(source)
    if change == 'fixture': r['fixture']['date'] = '2030-11-27'
    if change == 'source': r['source_id'] = 'other'
    if change == 'hash': r['event_binding']['retained_shot_record_sha256'] = 'other'
    if change == 'event': r['event_id'] = 443
    if change == 'time': r['frame_tick'] = 15358
    if change == 'scorer': r['players'][0]['native_xy'] = None
    with pytest.raises(ValueError):
        prepare(cap, 1454, [], replay=r)


def test_replay_prompt_uses_positions_without_inventing_shooting_foot(source):
    scene = prepare(source[0], 1454, [], replay=replay_for(source))
    text = prompt(scene, 'goal')
    assert '15330' in text and '[5.5, 47.8]' in text
    assert 'left/right shooting foot are not decoded' in text
    assert 'authoritative for the visible kits' in text
    assert 'imagined celebration' in prompt(scene, 'celebration')


def test_frame_keeps_off_pitch_and_unavailable_samples_distinct():
    actors = {'actors': [{'side_index': 0, 'stored_player_slot': 0,
                         'canonical_person_id': 7, 'engine_playback_uid': 9}]}
    frame = {'player_bases': [0, -1], 'setup': [{'entity_index': 0, 'kind_raw': 0,
              'team_index': 0, 'playback_uid': 9}], 'entities': [{'entity_index': 0,
              'kind': 'player', 'playback_uid': 9, 'position_samples': [
                  {'native_xy': [-39, 10], 'native_local_time': 1.0}]}],
              'frame_tick': 100, 'ball_samples': []}
    geometry = {'half_width_native': 34, 'half_length_native': 52.5}
    out = project_frame(frame, actors, geometry)
    assert out['players'][0]['native_xy'] == [-39, 10]
    assert out['players'][0]['inside_cbe_pitch_extents'] is False
    assert out['players'][0]['on_pitch'] is None
    assert out['ball_native_xyz'] is None
    frame['entities'][0]['position_samples'][0]['native_local_time'] = .5
    assert project_frame(frame, actors, geometry)['players'][0]['native_xy'] is None


def test_replay_reference_is_portable_and_wrong_match_rejected(source, tmp_path):
    cap, replay = tmp_path/'capture.json', tmp_path/'replay.json'
    cap.write_text(json.dumps(source[0]))
    replay.write_text(json.dumps(replay_for(source)))
    (tmp_path/'source.png').write_bytes(b'\x89PNG\r\n\x1a\n')
    refs = tmp_path/'refs.json'
    ref = {'role':'replay', 'path':'source.png', 'source_url':'fm-replay:138641/1454',
           'native_match_key':138641, 'event_id':1454, 'instruction':'<unsafe>'}
    refs.write_text(json.dumps([ref]))
    out = tmp_path/'packet'
    build_packet(cap, refs, 1454, out, replay_path=replay)
    assert (out/'references/1.png').read_bytes() == (tmp_path/'source.png').read_bytes()
    assert '&lt;unsafe&gt;' in (out/'index.html').read_text()
    assert (out/'replay.json').read_bytes() == replay.read_bytes()
    ref['native_match_key'] = 99
    refs.write_text(json.dumps([ref]))
    with pytest.raises(ValueError, match='same match'):
        build_packet(cap, refs, 1454, tmp_path/'wrong', replay_path=replay)
    assert not (tmp_path/'wrong').exists()
