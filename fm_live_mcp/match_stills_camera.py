"""Chosen photographic cameras, kept separate from decoded match coordinates."""
import math


def _unit(vector):
    size = math.sqrt(sum(v*v for v in vector))
    if not math.isfinite(size) or size == 0:
        raise ValueError('Camera basis must be finite and nonzero')
    return [v/size for v in vector]


def _cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def project(point, camera):
    """Pinhole projection; never alter the world points to improve the crop."""
    if len(point) != 3 or not all(type(v) in (int, float) and math.isfinite(v) for v in point):
        raise ValueError('Camera point must be finite XYZ')
    origin, target = camera['position_native'], camera['look_at_native']
    forward = _unit([t-o for t, o in zip(target, origin)])
    right = _unit(_cross(forward, [0, 0, 1]))
    up = _cross(right, forward)
    delta = [p-o for p, o in zip(point, origin)]
    dot = lambda a, b: sum(x*y for x, y in zip(a, b))
    depth = dot(delta, forward)
    if depth <= 0:
        return {'in_front': False, 'uv': None}
    half_width = depth*math.tan(math.radians(camera['horizontal_fov_degrees']/2))
    uv = [.5 + dot(delta, right)/(2*half_width),
          .5 - dot(delta, up)/(2*half_width/camera['aspect_ratio'])]
    return {'in_front': True, 'uv': uv, 'inside_image': all(0 <= v <= 1 for v in uv)}


# Goal and markings from the Laws of the Game, on the 105 x 68 basis the replay positions use.
POST, BAR, NET_DEPTH = 3.66, 2.44, 2.0
SIX_YARD, PENALTY_AREA, PENALTY_SPOT = 5.5, 16.5, 11.0


def goal_lines(sign, length, half_width=34.0):
    """Named 3D line segments of the attacked goal, its net and the markings in front of it."""
    line, back = sign*length, sign*(length+NET_DEPTH)
    out = lambda depth: sign*(length-depth)
    frame = [('post', [POST, line, 0], [POST, line, BAR]), ('post', [-POST, line, 0], [-POST, line, BAR]),
             ('crossbar', [-POST, line, BAR], [POST, line, BAR])]
    net = [(f'net {i}', a, b) for i, (a, b) in enumerate([
        ([POST, back, 0], [-POST, back, 0]), ([POST, back, BAR*.8], [-POST, back, BAR*.8]),
        *[([s*POST, line, 0], [s*POST, back, 0]) for s in (1, -1)],
        *[([s*POST, line, BAR], [s*POST, back, BAR*.8]) for s in (1, -1)],
        *[([s*POST, back, 0], [s*POST, back, BAR*.8]) for s in (1, -1)]])]
    marks = [('goal line', [-half_width, line, 0], [half_width, line, 0])]
    for name, depth, wide in (('six-yard box', SIX_YARD, POST+SIX_YARD), ('penalty area', PENALTY_AREA, POST+PENALTY_AREA)):
        marks += [(name, [-wide, out(depth), 0], [wide, out(depth), 0]),
                  *[(name, [s*wide, line, 0], [s*wide, out(depth), 0]) for s in (1, -1)]]
    return {'frame': frame, 'net': net, 'markings': marks, 'penalty_spot': [0, out(PENALTY_SPOT), 0]}


def _bearing(point, origin, reference):
    """Horizontal angle of `point` seen from `origin`, in degrees, relative to the `reference` point."""
    a = math.atan2(point[1]-origin[1], point[0]-origin[0])
    b = math.atan2(reference[1]-origin[1], reference[0]-origin[0])
    return math.degrees(math.atan2(math.sin(a-b), math.cos(a-b)))


# Sideways room a nearer player must leave the scorer and the ball. A penalty area is crowded:
# 0.45 leaves about half of the scorer's body in view.
CLEAR_BODY, CLEAR_BALL = 0.45, 0.3
TIGHT_MARGIN, TIGHT_WIDTH = 1.4, 4.8   # room either side of scorer and ball; narrowest frame at the scorer
GOAL_BEHIND = 0.6                      # share of a tight frame the goal must fill behind the players
LONGEST_REACH = 70


def _through_net(origin, point, sign, length):
    """Does the sight line from `origin` to `point` pass through the goal or its net?"""
    for i in range(1, 60):
        x, y = (origin[k]+(point[k]-origin[k])*i/60 for k in (0, 1))
        if abs(x) <= POST and 0 <= sign*y-length <= NET_DEPTH:
            return True
    return False


def _view(position, scorer, ball, others, sign, length):
    """What a photographer at `position` sees: two framings, and how clear the scorer and ball are.

    `fov` holds scorer, ball and the middle of the goal. `tight_fov` holds only scorer and ball,
    and `goal_behind` is the share of that tight frame with the goal or its net behind it.
    """
    reach = math.dist(position, scorer)
    subject = [0.0] + ([_bearing(ball[:2], position, scorer)] if ball else [])
    middle = _bearing([0, sign*length], position, scorer)
    low, high = min(subject+[middle]), max(subject+[middle])
    # Room for a body either side of the outermost thing held.
    margin = 2*math.degrees(math.atan2(1.6, reach))
    # A 3:2 frame must also be tall enough for a ball in the air above the players.
    width = max(TIGHT_WIDTH, 1.5*((ball[2] if ball else 0)+0.7))
    side = math.degrees(max(TIGHT_MARGIN, (width-math.radians(max(subject)-min(subject))*reach)/2)/reach)
    tight = [min(subject)-side, max(subject)+side]
    frame = [_bearing([x, sign*(length+d)], position, scorer) for x in (POST, -POST) for d in (0, NET_DEPTH)]
    behind = max(0.0, min(tight[1], max(frame))-max(tight[0], min(frame)))/(tight[1]-tight[0])

    def room(target, distance):
        gaps = [abs(math.radians(_bearing(o, position, target)))*math.dist(position, o)
                for o in others if math.dist(position, o) < distance]
        return min(gaps, default=99.0)
    ball_room = room(ball[:2], math.dist(position, ball[:2])) if ball and ball[2] < 1.9 else 99.0
    blocked = _through_net(position, scorer, sign, length) or bool(ball) and _through_net(position, ball[:2], sign, length)
    return {'position': position, 'reach': reach, 'low': low, 'high': high, 'fov': high-low+margin,
            'tight': tight, 'tight_fov': tight[1]-tight[0], 'goal_behind': behind,
            'pitch_side': sign*position[1] < length,
            'scorer_room': room(scorer, reach), 'ball_room': ball_room, 'through_net': blocked}


def editorial_camera(scene):
    """A low photographer's position on the edge of the pitch, with the goal in the frame.

    First choice is the press photograph from behind the play: a long lens on the scorer and the
    ball, a few players filling the frame and the goal and its net across the background. Every
    two units of both touchlines and every four of the far goal line is tried, and of those
    where the goal fills most of the tight frame the one with the scorer least covered by a
    nearer player is taken. When no position puts the goal behind the play, the camera goes to
    the attacked goal line or a touchline of the attacked half and takes the narrowest lens that
    holds scorer, ball and the middle of the goal. A view through the net is never taken.
    Height, lens and the choice among positions are artistic; players and ball are not moved.
    """
    replay = scene.get('replay')
    if replay is None:
        raise ValueError('An editorial camera requires a decoded replay frame')
    goal = scene['goal']
    pid = goal['actor']['canonical_person_id']
    scorer = next(p for p in replay['players'] if p['canonical_person_id'] == pid)['native_xy']
    sign = 1 if goal['attacked_goal_positive_native_y'] else -1
    length = (replay.get('retained_pitch_geometry') or {}).get('half_length_native')
    if type(length) not in (int, float) or not math.isfinite(length) or length <= 0:
        raise ValueError('Chosen camera requires recorded retained pitch extents')
    half_width = (replay.get('retained_pitch_geometry') or {}).get('half_width_native') or 34.0
    ball = replay.get('ball_native_xyz')
    others = [p['native_xy'] for p in replay['players'] if p.get('native_xy') is not None
              and p['canonical_person_id'] != pid and abs(p['native_xy'][0]) <= half_width]
    look = lambda spot: _view(spot, scorer, ball, others, sign, length)
    touchlines = [[s*(half_width+2.5), sign*(length-d)] for s in (1, -1) for d in range(0, int(2*length)+1, 2)]
    far_end = [[x, -sign*(length+2.5)] for x in range(-int(half_width), int(half_width)+1, 4)]
    behind = [v for v in map(look, touchlines+far_end) if v['goal_behind'] >= GOAL_BEHIND and not v['through_net']]
    # A long lens reaches about 70 before the players stop filling the frame; farther only when nothing nearer works.
    behind = [v for v in behind if v['reach'] <= LONGEST_REACH] or behind
    if behind:
        best = max(behind, key=lambda v: (round(min(v['scorer_room'], CLEAR_BODY), 2), v['goal_behind'], -v['reach']))
        low, high = best['tight']
        tried, clear, preset = len(touchlines+far_end), len(behind), 'behind_the_play'
        place = ('beside the touchline, behind the play, looking at the attacked goal' if abs(best['position'][0]) > half_width
                 else 'behind the far goal line, looking down the pitch at the attacked goal')
        policy = ('Tight frame on scorer and ball from the edge of the pitch, taken where the goal fills the background '
                  'and the scorer is least covered by a nearer player; never through the net.')
        fov = best['tight_fov']
    else:
        spots = [[s*x, sign*(length+2.5)] for s in (1, -1) for x in range(8, int(half_width)+3, 2)]
        spots += [[s*(half_width+2.5), sign*(length-d)] for s in (1, -1) for d in range(0, 46, 2)]
        views = [look(spot) for spot in spots]
        open_views = [v for v in views if not v['through_net']] or views
        ok = [v for v in open_views if v['scorer_room'] >= CLEAR_BODY and v['ball_room'] >= CLEAR_BALL]
        best = (min(ok, key=lambda v: v['fov']) if ok else
                max(open_views, key=lambda v: min(v['scorer_room']/CLEAR_BODY, v['ball_room']/CLEAR_BALL)))
        low, high, fov = best['low'], best['high'], best['fov']
        tried, clear, preset = len(views), len(ok), 'pitch_side_editorial'
        place = ('beside the touchline, looking toward the attacked goal' if best['pitch_side'] else
                 'behind the attacked goal line, to the side of the goal')
        policy = ('Narrowest lens that holds scorer, ball and the middle of the goal from the edge of the pitch, among positions '
                  'where no nearer player covers the scorer or the ball and the view is not through the net.')
    position = [*best['position'], 1.2]
    # Aim at chest height, or higher when the ball is above what that frame would hold.
    aim = max(1.3, (ball[2]+0.4 if ball else 0)-math.radians(fov)*best['reach']/3)
    centre = math.atan2(scorer[1]-position[1], scorer[0]-position[0]) + math.radians((low+high)/2)
    behind_goal_line = not best['pitch_side']
    camera = {'preset': preset, 'source': 'artistic_camera_choice_not_game_camera',
              'position_native': position, 'place': place,
              'look_at_native': [position[0]+best['reach']*math.cos(centre), position[1]+best['reach']*math.sin(centre), round(aim, 2)],
              'horizontal_fov_degrees': round(min(max(fov, 2), 60), 2), 'aspect_ratio': 1.5,
              'selection': {'policy': policy, 'positions_tried': tried, 'clear_positions': clear,
                            'goal_share_of_background': round(best['goal_behind'], 2),
                            'scorer_clear_of_nearer_players_by': round(best['scorer_room'], 2),
                            'ball_clear_of_nearer_players_by': round(best['ball_room'], 2)},
              'vertical_axis': 'native ball Z; ground chosen as zero',
              'height_and_lens_policy': 'Camera elevation, aim height, field of view and framing are chosen. Native units are not claimed as metres.',
              'occlusion_policy': 'Players may overlap or fall outside this crop; never move them to make them visible.',
              'pose_policy': 'Player XY is fixed. Player elevation, skeleton and pose are reconstructed from the replay screenshot.'}
    lines = goal_lines(sign, length, half_width)
    spot = lambda p: project(p, camera).get('uv')
    near = 1 if position[0] >= 0 else -1
    camera['goal'] = {
        'basis': 'Posts 7.32 apart, bar 2.44 high, six-yard box, penalty area and spot from the Laws of the Game, '
                 'placed on the goal line of the replay positions. The game\'s own goal and net model is not decoded.',
        'goal_line_native_y': sign*length,
        'seen': ('from behind the goal line: the net is beside the players' if behind_goal_line else
                 'from behind the play: the goal mouth and its net fill the background behind the players' if preset == 'behind_the_play' else
                 'from the pitch side of the goal line: the net is behind the players'),
        'projected_uv': {**{f'{name} post {end}': spot([s*near*POST, sign*length, z])
                            for name, s in (('near', 1), ('far', -1)) for end, z in (('base', 0), ('top', BAR))},
                         'penalty spot': spot(lines['penalty_spot'])}}
    camera['projected_ground_anchors'] = [
        {'canonical_person_id': p['canonical_person_id'], 'person_name': p['person_name'],
         **project([*p['native_xy'], 0], camera)}
        for p in replay['players'] if p.get('native_xy') is not None]
    camera['projected_ball'] = project(replay['ball_native_xyz'], camera) if replay.get('ball_native_xyz') else None
    return camera
