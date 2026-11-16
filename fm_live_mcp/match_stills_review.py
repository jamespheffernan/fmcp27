"""Recorded visual review, not automatic anatomy or identity detection."""
from __future__ import annotations

import hashlib
import json


ANATOMY_BRIEF = """
Render each player as one continuous person. Build the head, neck, clavicles,
shoulders and torso together with believable adult athletic proportions for the
pose and camera distance. Portraits establish identity only: do not copy their
frontal pose, expression, lighting, sharpness or scale. Retain recognisable
features while orienting the gaze and neck naturally toward the action. Match
face and body skin texture, illumination, contrast and lens softness. A distant
face must not be clearer or disproportionately larger than its body. Treat each
player's scale individually; avoid blanket head reductions and fixed head/body
ratios that ignore crouching, foreshortening or individual build. Schematic head
markers are labels, not anatomical dimensions. Use recorded height when available
without inventing missing measurements.
Keep the scorer and immediate challenge clearly focused, recovering players
gently softer, distant players progressively softer and the crowd naturally
defocused with stadium structure retained. Never hide faulty anatomy with blur.
Preserve player ground anchors, ball position, kit colours, verified lettering
and rear-facing/occluded poses during identity corrections. Do not turn players
toward the camera to display their portraits. Keep uncertain kit details explicit
in provenance; do not silently erase or invent them during face edits.
Establish the action phase before choosing a pose: incoming ball, contact or
outgoing shot. A frame within a goal event does not prove post-contact flight.
Use adjacent replay observations to establish direction; never combine an
incoming ball position with an outgoing-shot follow-through. Keep phase and
direction uncertainty explicit if the available evidence cannot resolve them.
""".strip()

PLAYER_CHECKS = (
    'proportions_and_perspective', 'head_neck_shoulders_and_pose',
    'identity_and_gaze', 'lighting_texture_and_edges', 'depth_of_field', 'kit_details',
)
SCENE_CHECKS = ('visible_player_census', 'positions_and_ball', 'kits_and_lettering',
                'focus_falloff', 'identity_sources_and_limits')

REVIEW_GUIDE = """# Review before presentation

Generate a candidate, inspect it, and record the review before attaching it or
presenting it as ready. Do not ask the user to discover anatomy defects. The
image tool may expose its own preview; this workflow controls final attachment
and presentation, not tool-native preview behaviour.

1. Inspect the full frame for perspective, player spacing, grounded feet, ball,
   occlusion, kits and focus falloff. Compare with replay evidence and the chosen
   camera guide. Source coordinates do not guarantee correct generated pixels.
   For an imagined celebration, record that limitation in positions_and_ball;
   a goal frame cannot establish subsequent celebration positions.
   Establish incoming/contact/outgoing phase from replay sequence evidence and
   check that ball placement, shooting direction and body pose agree. A single
   endpoint or event interval is not motion evidence. Record this finding in
   positions_and_ball; leave it unresolved if the action phase is unproved.
   A goal is a contested moment. Players standing upright and evenly spaced
   like a line-up, with nobody contesting, moving or watching the ball, fail
   positions_and_ball however well their places match.
   Check the finish against its decoded body part. For a header, compare the
   ball's height with the scorer's head using the header height in the prompt:
   a ball level with his waist or legs, a leap higher than that height needs,
   or a kicking or volleying pose fails positions_and_ball.
   When the camera guide draws the goal, the photograph shows the goal frame
   and its net in that place, and the players stand in the guide's places
   relative to the goal and the pitch lines. A missing goal or net, or a goal
   on the wrong side of the players, fails positions_and_ball.
2. Inspect every visible player at original resolution, then in the full frame.
   Check head scale against that player's complete pose, shoulder breadth, neck,
   torso and camera depth. Account for crouching and foreshortening. Compare
   nearby players at similar depth; do not apply one percentage or head ratio.
3. Follow the jaw into the neck, collar, clavicles and shoulders. Check body
   articulation, gaze, skin lighting, texture, edge sharpness and facial contrast.
   A recognisable portrait pasted onto a body fails. Inspect rear-facing heads
   too; do not require a face to become visible.
4. Check each likeness against its ID-bound reference where visible. Preserve
   immediate-action clarity, gentle softness just behind, and progressively
   softer distant players/crowd. Face and torso must share the same optical depth.
   Where the prompt says a long lens keeps every player sharp, a blurred band
   across the foreground grass or a miniature (tilt-shift) look fails
   focus_falloff, and players drawn clearly smaller than the camera guide
   draws them fail positions_and_ball.
5. Check kit colours and lettering after every face edit, including goalkeeper
   backs. Where the prompt lists squad numbers, a back turned to the camera
   shows that player's own number; a wrong number, or a number on a shirt
   front, fails kits_and_lettering. Record unverified details. Keep accepted faces, scale and blur fixed
   when correcting another player. Never copy the previous goal's pose or sizes.
6. Reject any failing player. Repair connected anatomy, preserving positions,
   kits and identity, then inspect ALL players again for regressions. Keep every
   request and intermediate image with hashes. A changed image needs a new review.

Run `review-template` for the exact candidate and actual mode prompt. Complete
the JSON with observed findings, reviewer and inspection time, and verdict pass.
Every replay entity needs a visibility decision: visible, occluded or out_of_frame.
Substitutes are not automatically active players. Give a reason for hidden rows.
For visible rows every check needs status pass and concrete notes. Only
identity_and_gaze may use not_visible (for an obscured face), with a reason.
Add unidentified visible players with person_id null and a unique name/location;
the visible-player census must account for every rendered figure. All scene
checks need pass and notes. Leave unresolved checks pending/fail; never fill a
passing review without inspecting the image. This is a recorded visual judgement,
not biometric certification or an automatic anatomy score.

Attach with --review. Attachment refuses missing, incomplete, failed or stale
reviews. Image, prompt and scene hashes bind the review to this exact candidate.
"""


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def scene_digest(scene: dict) -> str:
    evidence = {k: v for k, v in scene.items() if k not in ('images', 'quality_review')}
    return _hash(json.dumps(evidence, sort_keys=True, ensure_ascii=False,
                            allow_nan=False).encode())


def review_people(scene: dict) -> dict[int, str]:
    players = (scene.get('replay') or {}).get('players')
    if players is None:
        actor = scene['goal']['actor']
        return {actor['canonical_person_id']: actor['person_name']}
    return {p['canonical_person_id']: p['person_name'] for p in players}


def review_template(scene: dict, mode: str, image: bytes, prompt: bytes) -> dict:
    if mode not in ('goal', 'celebration'):
        raise ValueError('Unknown review mode')
    pending = lambda keys: {k: {'status': 'pending', 'notes': ''} for k in keys}
    return {'version': 1, 'mode': mode, 'image_sha256': _hash(image),
            'prompt_sha256': _hash(prompt), 'scene_sha256': scene_digest(scene),
            'reviewer': '', 'inspected_at': '', 'verdict': 'pending',
            'scene_checks': pending(SCENE_CHECKS),
            'players': [{'person_id': pid, 'name': name, 'visibility': 'pending',
                         'notes': '', 'checks': pending(PLAYER_CHECKS)}
                        for pid, name in review_people(scene).items()]}


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _checks(value, keys, *, allow_hidden_identity=False) -> None:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError('Review must contain every required check')
    for key, check in value.items():
        allowed = {'pass'}
        if allow_hidden_identity and key == 'identity_and_gaze':
            allowed.add('not_visible')
        if (not isinstance(check, dict) or not isinstance(check.get('status'), str)
                or check.get('status') not in allowed
                or not _text(check.get('notes'))):
            raise ValueError(f'Review check {key} is incomplete or failed')


def validate_review(review: dict, scene: dict, mode: str, image: bytes, prompt: bytes) -> None:
    if not isinstance(review, dict) or type(review.get('version')) is not int:
        raise ValueError('A completed visual review is required')
    expected = review_template(scene, mode, image, prompt)
    for key in ('version', 'mode', 'image_sha256', 'prompt_sha256', 'scene_sha256'):
        if review.get(key) != expected[key]:
            raise ValueError(f'Visual review {key} is stale or belongs to another candidate')
    if (review.get('verdict') != 'pass' or not _text(review.get('reviewer'))
            or not _text(review.get('inspected_at'))):
        raise ValueError('Visual review requires a passing verdict, reviewer and inspection time')
    _checks(review.get('scene_checks'), SCENE_CHECKS)
    rows = review.get('players')
    if not isinstance(rows, list) or not rows:
        raise ValueError('Review requires a player census')
    expected_people, seen, labels, visible = review_people(scene), set(), set(), 0
    for row in rows:
        if not isinstance(row, dict) or not _text(row.get('name')):
            raise ValueError('Invalid player review row')
        pid = row.get('person_id')
        if pid is not None:
            if type(pid) is not int or pid not in expected_people or pid in seen:
                raise ValueError('Unknown or duplicate review player ID')
            if row['name'] != expected_people[pid]:
                raise ValueError('Review player name does not match its ID')
            seen.add(pid)
        elif row.get('visibility') != 'visible':
            raise ValueError('Unidentified extra rows must describe visible players')
        label = (pid, row['name'])
        if label in labels:
            raise ValueError('Review player labels must be unique')
        labels.add(label)
        if row.get('visibility') == 'visible':
            visible += 1
            _checks(row.get('checks'), PLAYER_CHECKS, allow_hidden_identity=True)
        elif row.get('visibility') not in ('occluded', 'out_of_frame') or not _text(row.get('notes')):
            raise ValueError('Every player needs a visibility decision and hidden-player reason')
    if seen != set(expected_people) or not visible:
        raise ValueError('Review omits known players or has no visible players')
