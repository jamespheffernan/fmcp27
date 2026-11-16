"""The gate validates review coverage and freshness, never image anatomy."""
from copy import deepcopy
import base64
import json

import pytest

from fm_live_mcp.match_stills import attach_image, build_packet, prepare, prompt, render_gallery, main
from fm_live_mcp.match_stills_review import review_template, validate_review
from test_match_stills import capture


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j0r8AAAAASUVORK5CYII=')


def completed_review(scene, image=PNG, text=b'prompt', mode='goal'):
    """Synthetic attestation for gate tests; not a real image review."""
    review = review_template(scene, mode, image, text)
    review.update(reviewer='Test fixture', inspected_at='2026-11-11T12:00:00Z', verdict='pass')
    for check in review['scene_checks'].values():
        check.update(status='pass', notes='Synthetic test finding')
    for row in review['players']:
        row['visibility'] = 'visible'
        for check in row['checks'].values():
            check.update(status='pass', notes='Synthetic test finding')
    return review


@pytest.fixture
def scene(capture):
    scene = prepare(capture, 1454, [])
    scene['replay'] = {'players': [
        {'canonical_person_id': 28124573, 'person_name': 'Levi Colwill'},
        {'canonical_person_id': 49048357, 'person_name': 'Lucas Chevalier'},
        {'canonical_person_id': 123, 'person_name': 'Occluded teammate'},
    ]}
    return scene


def test_pending_template_cannot_be_promoted(scene):
    review = review_template(scene, 'goal', PNG, b'prompt')
    with pytest.raises(ValueError, match='passing verdict'):
        validate_review(review, scene, 'goal', PNG, b'prompt')


@pytest.mark.parametrize('change', ['image', 'prompt', 'scene', 'mode'])
def test_review_cannot_survive_changed_inputs(scene, change):
    review = completed_review(scene)
    image, text, mode = PNG, b'prompt', 'goal'
    if change == 'image':
        image += b'edited'
    elif change == 'prompt':
        text += b'changed face request'
    elif change == 'scene':
        scene['replay']['players'][1]['person_name'] = 'Another keeper'
    else:
        mode = 'celebration'
    with pytest.raises(ValueError, match='stale'):
        validate_review(review, scene, mode, image, text)


@pytest.mark.parametrize('change', ['omit', 'duplicate', 'wrong_id', 'failed_face',
                                   'blank_notes', 'missing_check', 'hidden_without_reason',
                                   'hidden_anatomy', 'failed_census'])
def test_all_players_and_checks_are_required(scene, change):
    review = completed_review(scene)
    row = review['players'][1]
    if change == 'omit':
        review['players'].pop()
    elif change == 'duplicate':
        review['players'].append(deepcopy(row))
    elif change == 'wrong_id':
        row['person_id'] = 999
    elif change == 'failed_face':
        row['checks']['identity_and_gaze']['status'] = 'fail'
    elif change == 'blank_notes':
        row['checks']['head_neck_shoulders_and_pose']['notes'] = ' '
    elif change == 'missing_check':
        del row['checks']['proportions_and_perspective']
    elif change == 'hidden_without_reason':
        row['visibility'] = 'out_of_frame'
    elif change == 'hidden_anatomy':
        row['checks']['proportions_and_perspective']['status'] = 'not_visible'
    else:
        review['scene_checks']['visible_player_census']['status'] = 'fail'
    with pytest.raises(ValueError):
        validate_review(review, scene, 'goal', PNG, b'prompt')


def test_back_facing_and_occluded_players_keep_honest_limits(scene):
    review = completed_review(scene)
    review['players'][1]['checks']['identity_and_gaze'].update(
        status='not_visible', notes='Keeper faces away; head orientation retained, face obscured.')
    review['players'][2].update(visibility='occluded', notes='Behind scorer; do not expose him.')
    validate_review(review, scene, 'goal', PNG, b'prompt')


def test_unknown_visible_player_needs_its_own_checks(scene):
    review = completed_review(scene)
    extra = deepcopy(review['players'][0])
    extra.update(person_id=None, name='Unidentified player, far left')
    review['players'].append(extra)
    validate_review(review, scene, 'goal', PNG, b'prompt')
    extra['checks']['kit_details']['status'] = 'pending'
    with pytest.raises(ValueError):
        validate_review(review, scene, 'goal', PNG, b'prompt')


@pytest.mark.parametrize('tamper', ['image', 'prompt', 'review', 'scene'])
def test_attachment_and_gallery_require_fresh_review(capture, tmp_path, tamper):
    source = tmp_path/'capture.json'
    source.write_text(json.dumps(capture))
    packet = tmp_path/'packet'
    scene = build_packet(source, None, 1454, packet)
    assert (packet/'visual-review.md').is_file()
    candidate = tmp_path/'candidate.png'
    candidate.write_bytes(PNG)
    with pytest.raises(ValueError, match='visual review'):
        attach_image(packet, 'goal', candidate)
    assert not (packet/'goal.png').exists()
    review_path = tmp_path/'review.json'
    assert main(['review-template', '--packet', str(packet), '--mode', 'goal',
                 '--image', str(candidate), '--out', str(review_path)]) == 0
    with pytest.raises(ValueError, match='passing verdict'):
        attach_image(packet, 'goal', candidate, review_path)
    text = (packet/'goal.prompt.txt').read_bytes()
    review_path.write_text(json.dumps(completed_review(scene, text=text)))
    attach_image(packet, 'goal', candidate, review_path)
    assert 'visual review recorded' in (packet/'index.html').read_text()
    stored = json.loads((packet/'scene.json').read_text())
    assert stored['images']['goal']['review_file'] == 'goal.review.json'
    if tamper == 'image':
        (packet/'goal.png').write_bytes(PNG+b'changed')
    elif tamper == 'prompt':
        (packet/'goal.prompt.txt').write_bytes(text+b'changed')
    elif tamper == 'review':
        with (packet/'goal.review.json').open('a') as target:
            target.write('\n')
    else:
        stored['goal']['native_x'] = 20
    render_gallery(packet, stored)
    assert 'visual review missing or stale' in (packet/'index.html').read_text()


@pytest.mark.parametrize('mode', ['goal', 'celebration'])
def test_initial_prompts_prevent_pasted_portraits(capture, mode):
    text = prompt(prepare(capture, 1454, []), mode)
    assert 'head, neck, clavicles' in text
    assert 'Portraits establish identity only' in text
    assert 'Never hide faulty anatomy with blur' in text
