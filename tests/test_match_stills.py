"""Adversarial evidence joins and portable packet acceptance for match stills."""
from copy import deepcopy
import json

import pytest

from fm_live_mcp.match_stills import (
    attach_image, build_packet, composition, kit, prepare, prompt, select_goal,
)


@pytest.fixture
def capture():
    f = {'date': '2030-11-26', 'home_team': {'native_id': 688, 'owner': {
        'native_id': 688, 'database_index': 414, 'name': 'Newcastle United'}},
        'away_team': {'native_id': 868, 'owner': {
            'native_id': 868, 'database_index': 521, 'name': 'Paris Saint-Germain'}},
        'stadium': {'native_id': 688, 'name': "St. James' Park"},
        'competition': {'native_id': 1, 'name': 'Champions League'},
        'scores': {'final_score': {'home': 4, 'away': 2}}}
    goal = {'event_id': 1454, 'outcome': 'goal', 'outcome_state': 'official_native_end_shot_category',
            'actor_identity_state': 'same_snapshot_canonical_PERSON', 'side_index': 0, 'body_part': 'head',
            'native_x': 6.6, 'native_y': 47.6, 'attacked_goal_positive_native_y': True,
            'actor': {'person_name': 'Levi Colwill', 'canonical_person_id': 28124573,
                      'person_index_word': 13250, 'canonical_team_id': 688}}
    return {'fixture': {'fixture': f}, 'shots': {'fixture': deepcopy(f), 'projection': 'source_proven',
            'source_id': 'a'*64, 'native_match_key': 138641, 'attempts': [goal],
            'pitch_geometry': {'half_width_native': 34, 'half_length_native': 52.5}},
            'kits': {'records': []}, 'appearance': {'records': []}, 'stadium': {'stadium': None}}


@pytest.mark.parametrize('field,value', [('outcome', 'saved'), ('outcome_state', 'unknown'),
    ('actor_identity_state', 'candidate'), ('side_index', 1)])
def test_does_not_promote_uncertain_or_other_events_to_goals(capture, field, value):
    capture['shots']['attempts'][0][field] = value
    with pytest.raises(ValueError):
        select_goal(capture, 1454)


def test_rejects_fixture_from_another_match(capture):
    capture['fixture']['fixture']['date'] = '2030-12-07'
    with pytest.raises(ValueError, match='identities disagree'):
        select_goal(capture, 1454)


def test_rejects_duplicate_event_ids(capture):
    capture['shots']['attempts'] *= 2
    with pytest.raises(ValueError, match='unique'):
        select_goal(capture, 1454)


@pytest.mark.parametrize('ref', [
    {'role': 'identity', 'person_native_id': 999},
    {'role': 'stadium', 'stadium_native_id': 999},
])
def test_reference_identity_cannot_leak_between_packets(capture, ref):
    with pytest.raises(ValueError, match='another'):
        prepare(capture, 1454, [ref])


def test_rotates_both_axes_without_inventing_metric_units(capture):
    g = capture['shots']['attempts'][0]
    c = composition(g, capture['shots']['pitch_geometry'])
    g.update(native_x=-g['native_x'], native_y=-g['native_y'], attacked_goal_positive_native_y=False)
    flipped = composition(g, capture['shots']['pitch_geometry'])
    assert flipped['lateral_fraction'] == c['lateral_fraction']
    assert flipped['distance_from_attacked_goal_fraction'] == c['distance_from_attacked_goal_fraction']
    assert 'metres' in flipped['meaning']


@pytest.mark.parametrize('value', [None, float('nan'), float('inf'), 999])
def test_invalid_coordinates_stay_unavailable(capture, value):
    g = capture['shots']['attempts'][0]
    g['native_x'] = value
    assert composition(g, capture['shots']['pitch_geometry'])['state'] == 'unavailable'


def test_zero_coordinate_is_available(capture):
    g = capture['shots']['attempts'][0]
    g['native_x'] = 0
    assert composition(g, capture['shots']['pitch_geometry'])['lateral_fraction'] == 0


def test_kit_does_not_mix_alternative_or_competition_parts(capture):
    colour = {'r': 248, 'g': 248, 'b': 248}
    part = {'ktpr': 1, 'ktal': 0, 'year': None, 'comp': None, 'ksfg': colour, 'kits': 3}
    capture['kits']['records'] = [{'idx': 414, 'uid': 688, 'values': {'colours_kits': [part,
        {**part, 'ktal': 1}, {**part, 'year': 2030}, {**part, 'comp': {'id': 1}}]}}]
    k = kit(capture, 0, 'Tko1')
    assert len(k['parts']) == 1
    assert k['parts'][0]['foreground'] == '#f8f8f8'
    assert k['parts'][0]['background'] is None
    assert k['fixture_selection'] == 'artistic_choice_unverified'
    capture['kits']['records'][0]['uid'] = 999
    assert kit(capture, 0, 'Tko1')['state'] == 'unavailable'


def test_goal_and_celebration_keep_evidence_and_unknowns_distinct(capture):
    scene = prepare(capture, 1454, [])
    assert scene['appearance'] is None
    assert scene['kits'][0]['state'] == 'unavailable'
    assert 'headed goal' in prompt(scene, 'goal')
    assert 'imagined celebration' in prompt(scene, 'celebration')
    assert 'specific cross or corner taker' in prompt(scene, 'goal')


def test_portable_gallery_escapes_names_and_refuses_overwrite(capture, tmp_path):
    capture['shots']['attempts'][0]['actor']['person_name'] = '<script>alert(1)</script>'
    source = tmp_path/'capture.json'
    source.write_text(json.dumps(capture))
    packet = tmp_path/'packet'
    build_packet(source, None, 1454, packet)
    page = (packet/'index.html').read_text()
    assert '<script>' not in page
    assert '&lt;script&gt;' in page
    request = json.loads((packet/'goal.request.json').read_text())
    assert 'referenced_image_paths' not in request
    assert (packet/'capture.json').read_bytes() == source.read_bytes()
    with pytest.raises(FileExistsError):
        build_packet(source, None, 1454, packet)
    fake = tmp_path/'fake.png'
    fake.write_text('not an image')
    with pytest.raises(ValueError, match='raster'):
        attach_image(packet, 'goal', fake)
    assert json.loads((packet/'scene.json').read_text())['images'] == {}
