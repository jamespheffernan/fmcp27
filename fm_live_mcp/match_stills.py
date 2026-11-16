"""Evidence-backed, agent-assisted match photographs. No game writes or image API keys.

Capture through existing readers, prepare an imagegen request, then attach its result.
The capture is immutable; rendering is explicitly an artistic reconstruction.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import math
from pathlib import Path
import shutil

from .match_stills_review import ANATOMY_BRIEF, REVIEW_GUIDE, review_template, validate_review


VERSION = 1
KIT_FIELDS = ['dbnm', 'Tko1', 'Tko2', 'Tko3', 'Tkg1', 'Tkg2', 'Tkg3', 'Sscl']
APPEARANCE_FIELDS = ['dbnm', 'Phes', 'Phcl', 'Phln', 'Pske', 'Pskt', 'Phce']
KIT_KEYS = {'Tko1': 'colours_kits', **{k: f'colours_kits_{k}' for k in KIT_FIELDS[2:7]}}
PARTS = {1: 'shirt', 4: 'shorts', 5: 'socks'}
LIMITS = [
    'AI reconstruction of a Football Manager career event, not a photograph of a real match.',
    'Shot coordinates locate the attempt. They do not supply simultaneous player poses or a ball trajectory.',
    'Native coordinate units, human left/right and displayed goal minute remain unknown.',
    'Selected club kit definitions are current stored designs; actual fixture kit selection is unverified.',
    'Faces and stadium architecture use dated reference photos; those photos do not establish 2030 appearance.',
    'Crowd density, reactions, weather, pose, defenders and goalkeeper placement are artistic choices.',
    'Stadium capacity is not attendance. Current appearance and pitch condition are not historical match observations.',
]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text())


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def fixture_key(f: dict) -> tuple:
    return (f['date'], f['home_team']['native_id'], f['away_team']['native_id'],
            (f.get('stadium') or {}).get('native_id'), f['competition']['native_id'])


def select_goal(capture: dict, event_id: int) -> dict:
    shots = capture['shots']
    if shots.get('projection') != 'source_proven' or not shots.get('source_id'):
        raise ValueError('A source_proven retained shot capture with a source_id is required')
    if fixture_key(capture['fixture']['fixture']) != fixture_key(shots['fixture']):
        raise ValueError('Fixture and shot capture identities disagree')
    matches = [s for s in shots.get('attempts', []) if s.get('event_id') == event_id]
    if len(matches) != 1:
        raise ValueError('Select one unique event_id from this capture')
    goal = matches[0]
    if goal.get('outcome') != 'goal' or goal.get('outcome_state') != 'official_native_end_shot_category':
        raise ValueError('Selected event is not a verified goal')
    actor = goal.get('actor') or {}
    if goal.get('actor_identity_state') != 'same_snapshot_canonical_PERSON' or not actor.get('person_name'):
        raise ValueError('Goal scorer identity is unavailable')
    side = goal.get('side_index')
    if side not in (0, 1) or actor.get('canonical_team_id') != shots['fixture'][('home_team', 'away_team')[side]]['native_id']:
        raise ValueError('Scorer team does not match the goal side')
    return goal


def rgb(value) -> str | None:
    if not isinstance(value, dict) or any(type(value.get(k)) is not int or not 0 <= value[k] <= 255 for k in ('r', 'g', 'b')):
        return None
    return '#' + ''.join(f'{value[k]:02x}' for k in ('r', 'g', 'b'))


def kit(capture: dict, side: int, code: str) -> dict:
    f = capture['fixture']['fixture']
    club = f[('home_team', 'away_team')[side]]['owner']
    rows = [r for r in capture.get('kits', {}).get('records', [])
            if r.get('idx') == club['database_index'] and r.get('uid') == club['native_id']]
    if len(rows) != 1:
        return {'state': 'unavailable', 'club': club['name'], 'selected_definition': code}
    values = rows[0].get('values', {}).get(KIT_KEYS[code])
    if not isinstance(values, list):
        return {'state': 'unavailable', 'club': club['name'], 'selected_definition': code}
    # Competition/season/alternative variants must not silently override the base design.
    parts = []
    for row in values:
        if row.get('ktpr') not in PARTS or row.get('ktal', 0) != 0 or row.get('comp') is not None or row.get('year') is not None:
            continue
        parts.append({'part': PARTS[row['ktpr']], 'style_code': row.get('kits'),
                      'foreground': rgb(row.get('ksfg')), 'background': rgb(row.get('ksbg')),
                      'outline': rgb(row.get('ksou')), 'back_style_code': row.get('bost')})
    return {'state': 'stored_definition' if parts else 'unavailable', 'club': club['name'],
            'selected_definition': code, 'fixture_selection': 'artistic_choice_unverified',
            'parts': parts, 'style_code_meaning': 'unmapped; use a kit reference for pattern details'}


def composition(goal: dict, geometry: dict) -> dict:
    x, y = goal.get('native_x'), goal.get('native_y')
    w, length = geometry.get('half_width_native'), geometry.get('half_length_native')
    direction = goal.get('attacked_goal_positive_native_y')
    if not all(type(v) in (int, float) and math.isfinite(v) for v in (x, y, w, length)) or w <= 0 or length <= 0 or type(direction) is not bool:
        return {'state': 'unavailable', 'reason': 'Missing finite native position, pitch extent or attacked-goal direction'}
    if abs(x) > w or abs(y) > length:
        return {'state': 'unavailable', 'reason': 'Attempt lies outside supplied pitch extent'}
    # Normalise both axes together (180 degree turn) when attacking negative Y.
    sign = 1 if direction else -1
    return {'state': 'derived_composition', 'lateral_fraction': sign*x/w,
            'distance_from_attacked_goal_fraction': (length-sign*y)/(2*length),
            'native_x': x, 'native_y': y, 'attacked_goal_positive_native_y': direction,
            'meaning': 'Dimensionless ratios in a chosen camera orientation; not metres or human left/right'}


def prepare(capture: dict, event_id: int, refs: list[dict], home_kit='Tko1', away_kit='Tko1', replay=None,
            sequence=None, numbers=None) -> dict:
    goal = select_goal(capture, event_id)
    f = capture['fixture']['fixture']
    actor = goal['actor']
    people = [r for r in capture.get('appearance', {}).get('records', [])
              if r.get('idx') == actor['person_index_word'] and r.get('uid') == actor['canonical_person_id']]
    appearance = people[0].get('values', {}) if len(people) == 1 else None
    stadium = capture.get('stadium', {}).get('stadium')
    if stadium and stadium.get('native_id') != (f.get('stadium') or {}).get('native_id'):
        raise ValueError('Stadium evidence belongs to another venue')
    for ref in refs:
        if ref['role'] == 'identity':
            identities = ([p['canonical_person_id'] for p in replay['players']] if replay
                          else [actor['canonical_person_id']])
            if identities.count(ref.get('person_native_id')) != 1:
                raise ValueError('Identity image belongs to another player or ambiguous replay identity')
        if ref['role'] == 'stadium' and ref.get('stadium_native_id') != (f.get('stadium') or {}).get('native_id'):
            raise ValueError('Stadium image belongs to another venue')
        if ref['role'] == 'replay' and (ref.get('event_id') != event_id or
                ref.get('native_match_key') != capture['shots']['native_match_key'] or replay is None):
            raise ValueError('Replay image requires the same match, event and decoded frame')
    if replay is not None:
        from .match_stills_replay import match_key
        event = replay.get('event_binding', {})
        if (replay.get('state') != 'verified_historical_replay_frame' or
                match_key(replay['fixture']) != match_key(f) or replay.get('event_id') != event_id or
                replay.get('source_id') != capture['shots']['source_id'] or
                event.get('retained_shot_record_sha256') != goal.get('source_record_sha256') or
                event.get('state') != 'same_fixture_event_actor_type_xg_location_and_interval'):
            raise ValueError('Replay evidence belongs to another fixture, source or goal')
        start, end, tick = goal.get('native_clock_start_raw'), goal.get('native_clock_end_raw'), replay.get('frame_tick')
        # The frame after the interval is the one the game keeps for a goal: the ball in the net.
        if any(type(v) is not int for v in (start, end, tick)) or not start <= tick <= end+1:
            raise ValueError('Replay frame must be within the recorded goal interval or the frame after it')
        scorer = [p for p in replay['players'] if p['canonical_person_id'] == actor['canonical_person_id']]
        if len(scorer) != 1 or scorer[0].get('native_xy') is None:
            raise ValueError('Replay frame has no unique positioned scorer')
    scene = {'version': VERSION, 'event_id': event_id, 'source_id': capture['shots']['source_id'],
            'native_match_key': capture['shots']['native_match_key'], 'fixture': f, 'goal': goal,
            'appearance': appearance, 'stadium': stadium,
            'kits': [kit(capture, 0, home_kit), kit(capture, 1, away_kit)],
            'opponent_goalkeeper_kit': kit(capture, 1-goal['side_index'], 'Tkg1'),
            'composition': composition(goal, capture['shots'].get('pitch_geometry', {})),
            'references': refs, 'limitations': list(LIMITS), 'images': {}}
    if replay is not None:
        scene['replay'] = replay
        scene['limitations'] = [LIMITS[0], LIMITS[4],
            'Player XY and ball XYZ come from one decoded replay frame; rendered poses and interpolation are not decoded.',
            'Replay screenshots supply visible kit appearance. A native selected-kit ID is not decoded.',
            'Replay and retained CBE pitch extents can differ; neither is used to infer the active XI.',
            'Screenshot time and native frame time are recorded separately. Image generation does not guarantee pixel-perfect placement.',
            'Celebration remains imagined unless a separate celebration frame is supplied.']
    if replay is not None and (numbers or {}).get('state') == 'current_squad_numbers':
        people = {p['canonical_person_id'] for p in replay['players']}
        kept = [n for n in numbers['players'] if n['canonical_person_id'] in people]
        if len({n['canonical_person_id'] for n in kept}) != len(kept):
            raise ValueError('Squad numbers name a player twice')
        scene['shirt_numbers'] = {**numbers, 'players': kept}
        scene['limitations'].append('Squad numbers are those held on the read date; the number worn in this match is not decoded separately.')
    if sequence is not None:
        shown = [r for r in sequence.get('frames', []) if replay is not None and r['frame_tick'] == replay['frame_tick']]
        if len(shown) != 1:
            raise ValueError('The depicted replay frame must be one frame of its action sequence')
        scene['action_sequence'] = {**sequence, 'depicted_tick': shown[0]['frame_tick'], 'depicted_phase': shown[0]['phase']}
        if goal.get('body_part') == 'head':
            from .match_stills_replay import header_figure
            scene['action_sequence']['scorer_figure'] = header_figure(sequence)
        scene['limitations'].append('Action phase is ordered from ball-to-scorer distance at adjacent cached frames; the contact instant is not decoded.')
    return scene


def prompt(scene: dict, mode: str) -> str:
    if mode not in ('goal', 'celebration'):
        raise ValueError('Mode must be goal or celebration')
    if scene.get('replay'):
        return replay_prompt(scene, mode)
    g, f = scene['goal'], scene['fixture']
    subject = g['actor']['person_name']
    home, away = [f[k]['owner']['name'] for k in ('home_team', 'away_team')]
    stadium_name = (f.get('stadium') or {}).get('name', 'venue unknown')
    action = ('a headed goal, ball just leaving the forehead' if g.get('body_part') == 'head'
              else 'a scoring shot with the foot; the specific foot is not decoded' if g.get('body_part') == 'feet'
              else 'a scoring action; body part is unknown, choose a plausible pose')
    if mode == 'celebration':
        action = 'an imagined celebration after this recorded goal; scorer running toward the home fans' if g['side_index'] == 0 else 'an imagined celebration after this recorded goal; scorer celebrating with away teammates'
    refs = '\n'.join(f"Image {i+1}: {r['role']} reference. {r.get('instruction', '')}" for i, r in enumerate(scene['references']))
    return f'''Use case: photorealistic-natural
Asset: fictional Football Manager career sports photograph, landscape 3:2.
Create {subject} in {action}. Fixture: {home} versus {away}, {f['date']}, {f['competition']['name']}, {stadium_name}, stored kickoff {f.get('kickoff_time', {}).get('time')}.
This is an AI reconstruction, never an archival photograph. The save's clubs override real-world affiliations.
Input images:
{refs or 'No photographic references supplied; appearance is an artistic approximation.'}
Recorded scorer appearance (current save, not historical): {json.dumps(scene['appearance'], ensure_ascii=False)}.
Stored kit definitions: {json.dumps(scene['kits'], ensure_ascii=False)}.
Opposing goalkeeper definition: {json.dumps(scene['opponent_goalkeeper_kit'], ensure_ascii=False)}.
Use supplied kit colour values. Numeric style codes are unmapped; infer plausible club patterns or use explicit kit references. Selected kit variant is an artistic choice. Do not copy clothing from identity reference photographs. Avoid visible shirt numbers because this event has no verified shirt number. Keep sponsors unobtrusive; historical reference sponsors are not authoritative for this save.
Recorded action: {g.get('body_part')} shot, outcome goal, location class {g.get('official_location')}. Non-penalty does not prove open play: do not invent a specific cross or corner taker.
Spatial composition for goal mode: {json.dumps(scene['composition'])}. Use these dimensionless ratios to place the scorer relative to the pitch and attacked goal, NOT to invent metres, a shot trajectory or a minute. In celebration mode the position is freely reconstructed after the goal.
Venue facts: {json.dumps({'capacity': (scene['stadium'] or {}).get('capacities', {}).get('total'), 'pitch': (scene['stadium'] or {}).get('pitch')}, ensure_ascii=False)}.
Stadium architecture from its reference. Plausibly busy stands, home scarves and winter coats, smaller away section. Capacity is not verified attendance. Choose convincing evening floodlights when kickoff is at night. Weather, crowd arrangement, defender/keeper positions, body pose and camera angle are creative reconstruction.
Camera: field-level professional sports photography, realistic telephoto perspective, natural skin texture and fabric tension, believable anatomy, sharp subject with modest background separation. Keep enough stadium visible to recognise it. Single coherent instant, one ball, no duplicate limbs. No text overlays, scoreboards, watermarks, panel borders or UI. Do not put the final score into the action image.
Goal mode: physically coherent ball contact and goal orientation; avoid unsupported named defenders. Celebration mode: emotional candid moment, plausible teammates and supporters, not a posed portrait.
{ANATOMY_BRIEF}
'''


def number_brief(scene: dict) -> str:
    """What the photograph may show as shirt numbers."""
    numbers = scene.get('shirt_numbers')
    if not numbers or not numbers['players']:
        return ('Kit numbers are not decoded. Show a readable shirt or shorts number only where the replay reference shows that number '
                'on that player; leave every other shirt and shorts without readable numerals.')
    seen = {a['canonical_person_id'] for a in (scene.get('camera') or {}).get('projected_ground_anchors', []) if a.get('inside_image')}
    rows = [f"{n['person_name']} {n['number']}" for n in numbers['players'] if not seen or n['canonical_person_id'] in seen]
    return (f"SQUAD NUMBERS, read from the game on {numbers['read_at_game_date']} (the number each player holds; the number worn in this match "
            f"is not decoded separately): {'; '.join(rows)}. A player whose back is to the camera wears his number large on the back of his shirt, "
            'in the number colour the replay reference shows for his team. A player facing the camera wears it small on the front of his shorts. '
            'A shirt front carries no number. Never put a number on a player it does not belong to, and show no other numerals. '
            'Add a name above a number only if the replay reference shows names on shirts.')


def goal_brief(scene: dict) -> str:
    """Where the goal, its net and the pitch markings are in the chosen camera's frame."""
    goal = (scene.get('camera') or {}).get('goal')
    if not goal:
        return ''
    place = lambda uv: 'not in front of the camera' if uv is None else f'({uv[0]:.2f}, {uv[1]:.2f})'
    points = '; '.join(f'{name} {place(uv)}' for name, uv in goal['projected_uv'].items())
    return (f"THE GOAL IS IN THE PICTURE, seen {goal['seen']}. Show its white posts and crossbar and the net hanging behind them, where the "
            f'camera guide draws them in grey. Projected UV, top-left (0,0), bottom-right (1,1), values outside 0..1 beyond the frame edge: {points}. '
            'Show the white goal line, six-yard box and penalty-area lines on the grass where the guide draws them. Every player stands on the grass '
            'in the place the guide gives him relative to the goal and those lines: this is how the photograph is checked against the game. '
            f"{goal['basis']}")


def framing_brief(scene: dict) -> str:
    """How large the players are in the chosen frame and what a lens at that distance keeps sharp."""
    camera, replay = scene.get('camera') or {}, scene.get('replay') or {}
    if 'position_native' not in camera:
        return ''
    from .match_stills_camera import project
    pid = scene['goal']['actor']['canonical_person_id']
    scorer = next(p['native_xy'] for p in replay['players'] if p['canonical_person_id'] == pid)
    feet, head = (project([*scorer, z], camera)['uv'] for z in (0, 1.8))
    seen = {a['canonical_person_id'] for a in camera.get('projected_ground_anchors', []) if a.get('inside_image')}
    reach = [math.dist(p['native_xy'], camera['position_native'][:2]) for p in replay['players']
             if p.get('native_xy') and p['canonical_person_id'] in seen | {pid}]
    text = (f'SIZE IN THE FRAME: a standing player at the scorer\'s place is {abs(feet[1]-head[1])*100:.0f}% of the frame height, with his feet '
            f'{feet[1]*100:.0f}% of the way down the frame, as the camera guide draws him. Do not draw the players smaller than that or leave '
            'more empty grass below them than the guide does.')
    if max(reach)-min(reach) < 0.35*min(reach):
        text += (f' FOCUS: this is a long lens from {min(reach):.0f} away, and every player in the picture is between {min(reach):.0f} and '
                 f'{max(reach):.0f} from it. At that distance all of them are sharp. Only the crowd and stand behind them are soft, and the grass '
                 'in front of them is sharp or barely soft. This overrides any softer focus asked for below. No tilt-shift or miniature look, '
                 'and no blurred band across the foreground.')
    return text


def action_brief(scene: dict) -> str:
    """What each player in the frame is doing, so the photograph is a contested moment and not a line-up."""
    camera, replay, goal = scene.get('camera') or {}, scene.get('replay') or {}, scene['goal']
    seen = {a['canonical_person_id'] for a in camera.get('projected_ground_anchors', []) if a.get('inside_image')}
    if not seen or not replay.get('ball_native_xyz'):
        return ''
    ball, pid = replay['ball_native_xyz'], goal['actor']['canonical_person_id']
    people = {p['canonical_person_id']: p for p in replay['players'] if p.get('native_xy')}
    scorer = people[pid]
    moved = {m['canonical_person_id']: m['native_xy_per_tick']
             for m in ((scene.get('action_sequence') or {}).get('motion') or {}).get('players', [])}
    numbers = {n['canonical_person_id']: n['number'] for n in (scene.get('shirt_numbers') or {}).get('players', [])}
    rivals = [p for p in people.values() if p['side_index'] != scorer['side_index']]
    marker = min(rivals, key=lambda p: math.dist(p['native_xy'], scorer['native_xy']), default=None)
    if marker and math.dist(marker['native_xy'], scorer['native_xy']) > 1.2:
        marker = None
    keeper = next((p for p in rivals if p.get('stored_player_slot') == 0), None)
    rows = []
    for p in sorted((p for p in people.values() if p['canonical_person_id'] in seen | {pid}),
                    key=lambda p: math.dist(p['native_xy'], scorer['native_xy'])):
        step = moved.get(p['canonical_person_id'])
        rate = math.hypot(*step) if step else None
        to_ball = [ball[k]-p['native_xy'][k] for k in (0, 1)]
        if rate is None:
            going = 'movement not read'
        elif rate < 0.12:
            going = 'almost still, braced'
        else:
            along = (step[0]*to_ball[0]+step[1]*to_ball[1])/(rate*(math.hypot(*to_ball) or 1))
            going = (('stepping' if rate < 0.5 else 'running' if rate < 1.3 else 'sprinting') +
                     (' toward the ball' if along > 0.5 else ' away from the ball' if along < -0.5 else ' across the line of the ball'))
        if p is scorer:
            doing = 'the scorer, at the moment described under ACTION PHASE'
        elif marker and p is marker:
            doing = (f"his marker, {math.dist(p['native_xy'], scorer['native_xy']):.1f} from him: body against body, "
                     'contesting the ball with him, neck stretched, an arm across him or a hand on his shirt')
        elif keeper and p is keeper:
            doing = (f"the goalkeeper, {math.dist(p['native_xy'], ball[:2]):.1f} from the ball: he has seen it late and is reacting to it, "
                     'gloves coming up and weight going toward it, and he has not reached it')
        else:
            doing = 'head turned to the ball'
        team = scene['fixture']['home_team' if p['side_index'] == 0 else 'away_team']['owner']['name']
        number = f" {numbers[p['canonical_person_id']]}" if p['canonical_person_id'] in numbers else ''
        rows.append(f"{p['person_name']} ({team}{number}): {going}; {doing}.")
    return ('A CONTESTED MOMENT, NOT A LINE-UP. The camera guide gives places only: never copy the upright stance of its figures. Nobody in this '
            'photograph stands straight with arms hanging. Every head and pair of eyes is turned to the ball. Bodies are caught mid-movement: '
            'leaning, bracing, jostling, an arm across an opponent, weight on one leg, mouths open with effort. Players who are close together in '
            'the guide touch and overlap in the photograph; do not spread them into an evenly spaced row. '
            'Movement read from the frames either side of this one (direction and rate only; jumps, arms and heads are reconstruction): '
            + ' '.join(rows))


def replay_prompt(scene: dict, mode: str) -> str:
    r, g, f = scene['replay'], scene['goal'], scene['fixture']
    refs = '\n'.join(f"Image {i+1}: {ref['role']}. {ref.get('instruction', '')}" for i, ref in enumerate(scene['references']))
    if (scene.get('camera_guide') or {}).get('file'):
        refs += (f"\nImage {len(scene['references'])+1}: camera guide. Schematic projection of the decoded player and ball positions "
                 'from the chosen camera. Use it for layout and relative scale only; never render its stick figures, labels or colours.')
    positions = [{k: p[k] for k in ('person_name', 'side_index', 'native_xy')}
                 for p in r['players'] if p.get('native_xy') is not None]
    action = ('Recreate the goal instant shown in the replay as a photorealistic sports photograph. '
              'Preserve its camera, goal and pitch lines, each visible player position, relative scale and occlusion. '
              'Follow the visible replay pose and ball location for this phase of the recorded goal; use its decoded body part.'
              if mode == 'goal' else
              'Create an imagined celebration after this goal, using the replay kits and scorer likeness. '
              'The goal-frame positions do not establish a celebration formation.')
    text = f'''Use case: photorealistic-natural. Landscape sports photograph.
{action}
Fictional Football Manager career: {f['home_team']['owner']['name']} versus {f['away_team']['owner']['name']}, {f['date']}, {(f.get('stadium') or {}).get('name')}.
Scorer: {g['actor']['person_name']}. Save-game affiliations override real-world affiliations.
{refs}
The replay reference is authoritative for the visible kits, pitch geometry, camera, players and crowd arrangement. Replace game graphics with convincing photographic skin, fabric, grass, netting and spectators. Remove ALL game UI, labels, menus, title bar, score/time display and commentary. Do not reproduce the final score as a match-instant score.
Face reference establishes likeness only; never copy its clothing. Stadium photo, if supplied, supplies material/architectural detail without moving the replay's goal or players. Keep the replay's distinctive stand layout and fan sections.
Decoded shot: body part {g.get('body_part')}; native type {g.get('native_shot_type')}; outcome {g.get('outcome')}; shot origin ({g.get('native_x')}, {g.get('native_y')}); location {g.get('official_location')}; native UI xG {g.get('native_xg_value')}; start/end {g.get('native_clock_start_raw')}/{g.get('native_clock_end_raw')}.
Decoded frame {r['frame_tick']}. Ball XYZ {r['ball_native_xyz']}. Player XY in the shared native world basis (side 0 home, side 1 away): {json.dumps(positions, ensure_ascii=False)}.
These coordinates constrain relative positions; units are unclaimed. A tight cluster beside the touchline may be substitutes, not extra players to place in the penalty area. Only depict players visible within the screenshot's framing. Do not infer the active XI from CBE pitch bounds. Keep the goalkeeper and clustered defenders where the replay places them.
Stored club definitions, secondary to visible replay kit: {json.dumps(scene['kits'], ensure_ascii=False)}.
Use realistic sports optics and natural stadium lighting. One coherent instant and one ball. No extra people inserted in the action, no duplicate bodies, no fashion portrait, no generic isolated scorer. The photograph should be recognisable as this replay when laid over it.
This is an AI reconstruction of a game, not a real-world archival photograph. Exact pose/animation and left/right shooting foot are not decoded; do not claim otherwise.
{number_brief(scene)}
'''
    if scene.get('camera'):
        text = text.replace(action, f'Create a front-page sports photograph of this {g.get("body_part")} goal from the CHOSEN NEW CAMERA below.' if mode == 'goal' else action)
        text = text.replace('The replay reference is authoritative for the visible kits, pitch geometry, camera, players and crowd arrangement.',
                            'The replay reference establishes kits, relative world positions, action and stadium. Its broadcast camera is NOT the output camera.')
        text = text.replace('Only depict players visible within the screenshot\'s framing.',
                            'Depict only players visible from the NEW camera; natural occlusion and cropping are expected.')
        text = text.replace('The photograph should be recognisable as this replay when laid over it.',
                            'The photograph must depict the same event from a different viewing position, not an overlay or crop of the broadcast view.')
        text += f'''
CHOSEN EDITORIAL CAMERA (artistic, not decoded): {json.dumps(scene['camera'], ensure_ascii=False)}.
The photographer is {scene['camera'].get('place', 'beside and just beyond the attacked goal line')}, low, with a long lens. Use a landscape 3:2 telephoto sports-photo composition that holds {g['actor']['person_name']}, the ball, the closest opponents and the goal.
{goal_brief(scene)}
{framing_brief(scene)}
{action_brief(scene)}
Follow the decoded body part ({g.get('body_part')}) and replay pose; do not invent a jump or header for a finish with the foot. Natural foreshortening, overlapping bodies and a shallow stadium background. The scorer should be recognisable using the identity reference. Preserve both teams' visible kits from this replay.
This is a new CAMERA, not permission to restage the event. Hold every decoded player XY and ball XYZ fixed. Projected UV values use top-left (0,0), bottom-right (1,1); off-frame anchors may be cropped. Player anchors are feet on the chosen ground plane, not head positions. Player elevation and body articulation are reconstructed; no all-player 3D skeleton was decoded. Do not relocate the keeper to force him into frame or spread defenders apart for a cleaner view. Keep the ball at its decoded position relative to the scorer. Do not force contact with the forehead or foot, or infer movement from a single frame.
Photographic editorial quality: real human anatomy, effort in faces, skin and sweat, detailed fabric motion, subtle optical motion blur, convincing shallow depth of field: keep the scorer and all players in the immediate challenge in clear focus, with only gentle softness on teammates just behind them. Apply moderate defocus to distant players and let the crowd fall away gradually while retaining stadium structure. Preserve identity beneath the blur; avoid extreme portrait blur, uniform blur and cutout halos. The low angle should feel like a press photographer caught the decisive moment, not a simulation, overhead broadcast screenshot, or a posed advertising portrait. Remove UI and all source-image labels. Do not inherit invented jersey lettering from earlier generated images; the only inputs are the original replay and likeness reference.
'''
    if scene.get('action_sequence') and mode == 'goal':
        from .match_stills_replay import PHASE_BRIEFS, header_brief
        s = scene['action_sequence']
        rows = [{'tick': x['frame_tick'], 'phase': x['phase'], 'ball_xyz': x['ball_native_xyz'],
                 'ball_to_scorer': round(x['ball_to_scorer_native'], 2)} for x in s['frames']]
        text += f'''
ACTION PHASE, ordered from adjacent cached replay frames: {json.dumps(rows)}.
The depicted frame {s['depicted_tick']} is {s['depicted_phase'].upper().replace('_', ' ')}. {PHASE_BRIEFS[s['depicted_phase']]}
The ball's position and the scorer's pose must describe this same moment. A reference screenshot taken at another tick supplies kits, stadium and identities only, not the pose.
'''
        if g.get('body_part') == 'head':
            text += header_brief(s) + '\n'
    return text + '\n' + ANATOMY_BRIEF + '\n'


def pitch_svg(scene: dict) -> str:
    c = scene['composition']
    if c['state'] != 'derived_composition':
        return '<p>Shot position unavailable.</p>'
    x, y = 180 + c['lateral_fraction']*150, 25 + c['distance_from_attacked_goal_fraction']*460
    marks = f'<circle cx="{x:.2f}" cy="{y:.2f}" r="8" fill="#d9ff75"/>'
    if scene.get('replay'):
        marks = ''
        sign = 1 if c['attacked_goal_positive_native_y'] else -1
        for player in scene['replay']['players']:
            point = player.get('native_xy')
            if point is None:
                continue
            # Fixed labelled plotting scale, never an active-XI classifier.
            px, py = 180 + sign*point[0]*150/34, 255-sign*point[1]*460/105
            colour = '#f5f5f5' if player['side_index'] == 0 else '#f04444'
            if player['canonical_person_id'] == scene['goal']['actor']['canonical_person_id']:
                colour = '#d9ff75'
            marks += f'<circle cx="{px:.2f}" cy="{py:.2f}" r="4" fill="{colour}"><title>{html.escape(player["person_name"] or "Unnamed")} · {point}</title></circle>'
        ball = scene['replay'].get('ball_native_xyz')
        if ball:
            marks += f'<circle cx="{180+sign*ball[0]*150/34:.2f}" cy="{255-sign*ball[1]*460/105:.2f}" r="3" stroke="#111" fill="#ffb347"><title>Ball · {ball}</title></circle>'
    return f'<svg viewBox="0 0 360 510" role="img" aria-label="Recorded native positions; attacked goal at top"><rect x="30" y="25" width="300" height="460" fill="#173e2c" stroke="#9ab8a6"/><path d="M30 255H330 M120 25V95H240V25 M145 25V52H215V25" fill="none" stroke="#9ab8a6"/><circle cx="180" cy="255" r="38" fill="none" stroke="#9ab8a6"/>{marks}<text x="180" y="16" text-anchor="middle" fill="#ddd" font-size="10">ATTACKED GOAL</text></svg>'


def render_gallery(folder: Path, scene: dict) -> None:
    esc = html.escape
    f, g = scene['fixture'], scene['goal']
    home, away = [f[k]['owner']['name'] for k in ('home_team', 'away_team')]
    score = f['scores']['final_score']
    cards = []
    for mode in ('goal', 'celebration'):
        output = scene['images'].get(mode)
        if mode == 'celebration' and scene.get('replay') and not output:
            continue  # One goal frame does not establish a celebration scene.
        visual = f'<img src="{esc(output["file"], quote=True)}" alt="AI reconstructed {mode} by {esc(g["actor"]["person_name"], quote=True)}">' if output else '<div class="pending">Prompt ready · image not generated yet</div>'
        prompt_path = folder/f'{mode}.prompt.txt'
        used_prompt = prompt_path.read_text() if prompt_path.exists() else prompt(scene, mode)
        caption = 'AI reconstruction · replay-constrained goal' if scene.get('replay') and mode == 'goal' else 'AI reconstruction · recorded goal, imagined instant'
        if output:
            review_file = output.get('review_file')
            reviewed = False
            if review_file:
                try:
                    validate_review(read_json(folder/review_file), scene, mode,
                                    (folder/output['file']).read_bytes(), used_prompt.encode())
                    reviewed = digest((folder/review_file).read_bytes()) == output.get('review_sha256')
                except (ValueError, KeyError, TypeError, OSError):
                    pass
            caption += (' · visual review recorded' if reviewed else ' · visual review missing or stale')
            if reviewed:
                caption += f' · <a href="{esc(review_file, quote=True)}">Review findings</a>'
        cards.append(f'<section><h2>{mode.capitalize()}</h2>{visual}<p>{caption}</p><details><summary>Generation prompt</summary><pre>{esc(used_prompt)}</pre><a href="{mode}.request.json">Imagegen request</a></details></section>')
    refs = ''.join(f'<li><a href="{esc(r["path"] if r["source_url"].startswith(("fm-replay:", "fm-graphics:")) else r["source_url"], quote=True)}">{esc(r.get("credit", r["role"]))}</a> — {esc(r["role"])}</li>' for r in scene['references'])
    replay_ref = next((r for r in scene['references'] if r['role'] == 'replay'), None)
    if replay_ref:
        cards.append(f'<section><h2>Original replay</h2><img src="{esc(replay_ref["path"], quote=True)}" alt="Original game replay used for kit and composition reference"><p>{esc(replay_ref.get("instruction", ""))}</p></section>')
    position_note = ('Named replay entities; white Newcastle, red PSG, lime scorer, orange ball. Includes substitutes. Plotting scale uses retained pitch extents; replay CBE extents differ.'
                     if scene.get('replay') else 'Shot origin, rotated toward the attacked goal. Dimensionless native coordinates. Other players’ positions and celebration movement are reconstructed.')
    limits = ''.join(f'<li>{esc(s)}</li>' for s in scene['limitations'])
    page = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Match stills · {esc(home)} v {esc(away)}</title>
<style>*{{box-sizing:border-box}}body{{overflow-wrap:anywhere;margin:0;background:#111713;color:#edf1e9;font:16px/1.6 system-ui}}main{{max-width:1200px;margin:auto;padding:44px 24px}}small,.label{{color:#d9ff75;letter-spacing:.12em;text-transform:uppercase}}h1{{font-size:clamp(32px,5vw,64px);line-height:1.1;margin:18px 0}}h2{{font-size:24px}}a{{color:#d9ff75}}.meta{{color:#afbaae}}.layout{{display:grid;grid-template-columns:minmax(0,1fr) 260px;gap:40px}}img{{display:block;max-width:100%;width:100%;border-radius:6px}}section{{margin:32px 0}}.pending{{padding:90px 20px;background:#233029;text-align:center;color:#c1c9bf}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 monospace;background:#1c251f;padding:20px}}summary{{cursor:pointer}}aside{{padding-top:25px}}aside svg{{width:100%}}li{{margin-bottom:10px}}.tag{{border:1px solid #56704d;padding:3px 9px;border-radius:3px}}@media(max-width:760px){{.layout{{grid-template-columns:minmax(0,1fr)}}aside svg{{max-height:220px}}}}</style>
<main><small>FM27 / Match stills / MVP</small><h1>{esc(home)} {score['home']}–{score['away']}<br>{esc(away)}</h1><p class="meta">{esc(f['date'])} · {esc(f['competition']['name'])} · {esc((f.get('stadium') or {}).get('name', 'Unknown venue'))}</p><p><span class="tag">AI reconstruction</span> {esc(g['actor']['person_name'])} · {esc(str(g.get('body_part')))} · event {g['event_id']}</p>
<div class="layout"><div>{''.join(cards)}</div><aside><h2>Recorded positions</h2>{pitch_svg(scene)}<p>{position_note}</p><a href="scene.json">Scene & provenance</a><br><a href="capture.json">Original decoder capture</a></aside></div>
<details><summary>What is known and reconstructed</summary><ul>{limits}</ul></details><h2>Image references</h2><ul>{refs or '<li>No references supplied</li>'}</ul></main></html>'''
    (folder/'index.html').write_text(page)


def build_packet(capture_path: Path, references_path: Path | None, event_id: int,
                 out: Path, home_kit='Tko1', away_kit='Tko1', replay_path: Path | None = None,
                 camera='replay', sequence: dict | None = None, camera_guide: bool = False,
                 numbers: dict | None = None) -> dict:
    capture = read_json(capture_path)
    refs = read_json(references_path) if references_path else []
    if len(refs) > (4 if camera_guide else 5):
        raise ValueError('Imagegen accepts five inputs per call. Use staged edits with a target image and up to four portraits; retain every stage in provenance.')
    prepared_refs = []
    for i, ref in enumerate(refs):
        prefixes = (('fm-replay:',) if ref.get('role') == 'replay' else
                    ('http://', 'https://', 'fm-graphics:') if ref.get('role') == 'identity' else ('http://', 'https://'))
        if (ref.get('role') not in ('identity', 'stadium', 'kit', 'replay') or
                not ref.get('source_url', '').startswith(prefixes)):
            raise ValueError('References require a documented image role and source URL (fm-replay: for replay)')
        path = (references_path.parent / ref['path']).resolve()
        if not path.is_file() or path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
            raise ValueError(f'Image reference missing or unsupported: {path}')
        if path.stat().st_size > 20*1024*1024:
            raise ValueError('Reference exceeds 20 MiB')
        if ref['source_url'].startswith('fm-graphics:'):
            binding = ref.get('portrait_binding', {})
            pid = ref.get('person_native_id')
            if (binding.get('state') != 'exact_config_PERSON_mapping' or
                    binding.get('to') != f'graphics/pictures/person/{pid}/portrait' or
                    ref['source_url'] != f'fm-graphics:portrait/{pid}' or
                    binding.get('asset_sha256') != digest(path.read_bytes()) or
                    not binding.get('config_sha256')):
                raise ValueError('Local portrait lacks an intact PERSON mapping and asset hash')
        prepared_refs.append({**ref, 'original_path': str(path),
                              'path': f'references/{i+1}{path.suffix.lower()}', 'sha256': digest(path.read_bytes())})
    scene = prepare(capture, event_id, prepared_refs, home_kit, away_kit,
                    read_json(replay_path) if replay_path else None, sequence, numbers)
    if camera not in ('replay', 'goal-line'):
        raise ValueError('Unknown camera preset')
    if camera_guide and camera != 'goal-line':
        raise ValueError('A camera guide needs the goal-line camera')
    if camera == 'goal-line':
        from .match_stills_camera import editorial_camera
        scene['camera'] = editorial_camera(scene)
        scene['limitations'].append('Camera position, lens, player vertical poses and photographic lighting are artistic choices; decoded XY/ball XYZ are preserved as inputs.')
    # Refuse overwrite before any output is written; each packet is a separate reviewable run.
    out.mkdir(parents=True, exist_ok=False)
    (out/'references').mkdir()
    for ref in prepared_refs:
        shutil.copyfile(ref['original_path'], out/ref['path'])
    shutil.copyfile(capture_path, out/'capture.json')
    if replay_path:
        shutil.copyfile(replay_path, out/'replay.json')
        scene['replay_sha256'] = digest((out/'replay.json').read_bytes())
    scene['capture_sha256'] = digest((out/'capture.json').read_bytes())
    images = [str((out/r['path']).resolve()) for r in prepared_refs]
    if camera_guide:
        from .match_stills_camera_guide import render_file
        write_json(out/'scene.json', scene)
        problem = render_file(out/'scene.json', out/'camera-guide.png')
        scene['camera_guide'] = ({'state': 'unavailable', 'reason': problem} if problem else
                                 {'file': 'camera-guide.png', 'sha256': digest((out/'camera-guide.png').read_bytes()),
                                  'meaning': 'Schematic projection of decoded XY and ball XYZ; figure heights and poses are not decoded.'})
    for mode in ('goal', 'celebration'):
        text = prompt(scene, mode)
        (out/f'{mode}.prompt.txt').write_text(text)
        request = {'prompt': text, 'transparent_background': False}
        guide = [str((out/'camera-guide.png').resolve())] if mode == 'goal' and (scene.get('camera_guide') or {}).get('file') else []
        if images or guide:
            request['referenced_image_paths'] = images + guide
        write_json(out/f'{mode}.request.json', request)
    write_json(out/'scene.json', scene)
    (out/'visual-review.md').write_text(REVIEW_GUIDE)
    render_gallery(out, scene)
    return scene


def attach_image(folder: Path, mode: str, image: Path, review_path: Path | None = None) -> None:
    if mode not in ('goal', 'celebration') or image.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
        raise ValueError('Supply goal/celebration and a PNG, JPEG or WebP')
    scene = read_json(folder/'scene.json')
    if mode in scene['images']:
        raise ValueError('This mode already has an image; create a new packet for another revision')
    data = image.read_bytes()
    valid = data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff') or (data.startswith(b'RIFF') and data[8:12] == b'WEBP')
    if not valid:
        raise ValueError('Result is not a recognised raster image')
    if review_path is None:
        raise ValueError('A completed visual review is required; run review-template, inspect, then attach --review')
    review = read_json(review_path)
    validate_review(review, scene, mode, data, (folder/f'{mode}.prompt.txt').read_bytes())
    review_name = f'{mode}.review.json'
    if (folder/review_name).exists():
        raise ValueError('Review attachment already exists')
    name = f'{mode}{image.suffix.lower()}'
    with (folder/name).open('xb') as target:
        target.write(data)
    write_json(folder/review_name, review)
    scene['images'][mode] = {'file': name, 'sha256': digest(data), 'attached_at': datetime.now(timezone.utc).isoformat(),
                             'prompt_sha256': digest((folder/f'{mode}.prompt.txt').read_bytes()),
                             'review_file': review_name,
                             'review_sha256': digest((folder/review_name).read_bytes()),
                             'generation': 'agent-supplied imagegen result; recorded visual judgement, not automatic anatomy certification'}
    write_json(folder/'scene.json', scene)
    render_gallery(folder, scene)


def capture_live(match_key: int | None) -> dict:
    """Use existing public-reader implementations; never touch game memory writes."""
    from .bridge import Bridge
    from .retained_match_discovery import list_retained_match_data
    from .live_retained_shots import get_retained_shot_map
    from .fmdb import tools as db

    bridge = Bridge()
    sid = bridge.attach()['session_id']
    try:
        inventory, offset, pin = [], 0, None
        while True:
            page = list_retained_match_data(bridge, sid, scope='managed', offset=offset,
                                           expected_source_inventory_id=pin)
            inventory.extend(page['fixtures'])
            pin = page['source_inventory_id']
            offset = page['next_offset']
            if offset is None:
                break
        if match_key is None:
            return {'fixtures': inventory}
        matches = [f for f in inventory if f.get('native_match_key') == match_key]
        if len(matches) != 1:
            raise ValueError('Match key is absent or ambiguous in the current retained inventory; use list')
        ref = matches[0]['fixture_ref']
        fixture = bridge.get_fixture(sid, ref)
        shots = get_retained_shot_map(bridge, sid, ref, projection='source_proven')
        offset = shots.get('next_offset')
        while offset is not None:
            page = get_retained_shot_map(bridge, sid, ref, offset=offset,
                                        expected_source_id=shots['source_id'], projection='source_proven')
            shots['attempts'].extend(page['attempts'])
            offset = page['next_offset']
        shots['next_offset'] = None
        f = fixture['fixture']
        kits = db.db_read(bridge, sid, 'club', [f[k]['owner']['database_index'] for k in ('home_team', 'away_team')], KIT_FIELDS)
        indices = sorted({s['actor']['person_index_word'] for s in shots.get('attempts', [])
                          if s.get('outcome') == 'goal' and s.get('actor')})
        appearance = {'records': []}
        for start in range(0, len(indices), 50):
            page = db.db_read(bridge, sid, 'person', indices[start:start+50], APPEARANCE_FIELDS)
            appearance['records'].extend(page['records'])
            appearance['read_at_game_date'] = page['read_at_game_date']
        stadium = bridge.get_stadium(sid, f['stadium']['stadium_ref']) if f.get('stadium') else {'stadium': None}
        final = bridge.get_fixture(sid, ref)
        if fixture_key(final['fixture']) != fixture_key(f) or final['save'] != fixture['save']:
            raise ValueError('Career or fixture changed during capture; no packet published')
        return {'version': VERSION, 'captured_at': datetime.now(timezone.utc).isoformat(),
                'source': 'live retained match plus current generic database getters',
                'fixture': fixture, 'shots': shots, 'kits': kits, 'appearance': appearance, 'stadium': stadium}
    finally:
        bridge.detach()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list', help='Discover retained matches in the running career')
    cap = sub.add_parser('capture', help='Capture one retained match with kits and appearance')
    cap.add_argument('--match-key', type=int, required=True)
    cap.add_argument('--out', type=Path, required=True)
    replay = sub.add_parser('replay', help='Capture an exact cached historical replay frame; never seeks or writes the game')
    replay.add_argument('--capture', type=Path, required=True)
    replay.add_argument('--event-id', type=int, required=True)
    replay.add_argument('--tick', type=int, required=True)
    replay.add_argument('--wait-seconds', type=float, default=0)
    replay.add_argument('--out', type=Path, required=True)
    faces = sub.add_parser('faces', help='Resolve portraits by exact replay PERSON IDs and installed facepack config')
    faces.add_argument('--replay', type=Path, required=True)
    faces.add_argument('--facepack', type=Path, required=True)
    faces.add_argument('--person-id', type=int, action='append', required=True)
    faces.add_argument('--out', type=Path, required=True)
    build = sub.add_parser('build', help='Prepare imagegen requests and a portable gallery')
    build.add_argument('--capture', type=Path, required=True)
    build.add_argument('--references', type=Path)
    build.add_argument('--replay', type=Path)
    build.add_argument('--camera', choices=('replay', 'goal-line'), default='replay')
    build.add_argument('--event-id', type=int, required=True)
    build.add_argument('--out', type=Path, required=True)
    for side in ('home', 'away'):
        build.add_argument(f'--{side}-kit', choices=('Tko1', 'Tko2', 'Tko3'), default='Tko1')
    review = sub.add_parser('review-template', help='Prepare a pending visual review bound to one exact candidate')
    review.add_argument('--packet', type=Path, required=True)
    review.add_argument('--mode', choices=('goal', 'celebration'), required=True)
    review.add_argument('--image', type=Path, required=True)
    review.add_argument('--out', type=Path, required=True)
    attach = sub.add_parser('attach', help='Attach a visually reviewed image and refresh the gallery')
    attach.add_argument('--packet', type=Path, required=True)
    attach.add_argument('--mode', choices=('goal', 'celebration'), required=True)
    attach.add_argument('--image', type=Path, required=True)
    attach.add_argument('--review', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'list':
            print(json.dumps(capture_live(None), ensure_ascii=False, indent=2))
        elif args.command == 'capture':
            if args.out.exists():
                raise ValueError('Capture destination already exists')
            capture = capture_live(args.match_key)
            with args.out.open('x') as target:
                json.dump(capture, target, ensure_ascii=False, indent=2, allow_nan=False)
            print(args.out.resolve())
        elif args.command == 'build':
            build_packet(args.capture, args.references, args.event_id, args.out, args.home_kit, args.away_kit, args.replay, args.camera)
            print((args.out/'index.html').resolve())
        elif args.command == 'faces':
            from .match_stills_faces import face_references
            if args.out.exists():
                raise ValueError('Face manifest destination already exists')
            refs = face_references(read_json(args.replay), args.facepack, args.person_id)
            with args.out.open('x') as target:
                json.dump(refs, target, ensure_ascii=False, indent=2)
            print(args.out.resolve())
        elif args.command == 'replay':
            from .match_stills_replay import capture_replay
            if args.out.exists():
                raise ValueError('Replay destination already exists')
            result = capture_replay(read_json(args.capture), args.event_id, tick=args.tick, wait_seconds=args.wait_seconds)
            with args.out.open('x') as target:
                json.dump(result, target, indent=2, allow_nan=False)
            print(args.out.resolve())
        elif args.command == 'review-template':
            result = review_template(read_json(args.packet/'scene.json'), args.mode,
                                     args.image.read_bytes(),
                                     (args.packet/f'{args.mode}.prompt.txt').read_bytes())
            with args.out.open('x') as target:
                json.dump(result, target, ensure_ascii=False, indent=2, allow_nan=False)
            print(args.out.resolve())
        else:
            attach_image(args.packet, args.mode, args.image, args.review)
            print((args.packet/'index.html').resolve())
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f'match-stills: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
