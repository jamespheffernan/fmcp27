"""Read a loaded historical replay without requiring a current-career match client.

The GAME_MATCH statistics fixture, canonical sides, retained shot bytes and actor
must agree. This never seeks, executes a game function, or writes game memory.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import struct
import time

from . import active_frame_source as frames
from . import active_match_entity_identity as identities
from . import active_match_people, active_match_playback as playback
from . import active_match_shot_timeline, active_match_shots, active_match_source
from . import frame_world_basis, live_retained_shots as shots, players, world
from .match_stills import digest, select_goal


def match_key(fixture: dict) -> tuple:
    return (fixture['date'], fixture['home_team']['native_id'],
            fixture['away_team']['native_id'], fixture['competition']['native_id'])


def check_event(vectors: list[bytes], events: bytes, goal: dict) -> dict:
    """Join decoded fields; replay reconstruction changes opaque record bytes."""
    records = [(side, raw[at:at+48]) for side, raw in enumerate(vectors)
               for at in range(0, len(raw), 48)
               if struct.unpack_from('<I', raw, at+36)[0] == goal['event_id']]
    linked = [events[at:at+56] for at in range(0, len(events), 56)
              if struct.unpack_from('<I', events, at+44)[0] == goal['event_id']]
    if len(records) != 1 or len(linked) != 1:
        raise ValueError('Replay shot/event is absent or ambiguous')
    side, record = records[0]
    event = linked[0]
    if (side != goal['side_index'] or record[44] != goal['native_shot_type']
            or struct.unpack_from('<f', record, 32)[0] != goal['native_xg_value']):
        raise ValueError('Replay shot fields differ from retained shot')
    fields = {'native_clock_start_raw': struct.unpack_from('<H', event, 34)[0],
              'native_clock_end_raw': struct.unpack_from('<H', event, 50)[0],
              'stored_player_slot': event[39], 'side_index': event[40],
              'native_category_code': event[42],
              'native_x': struct.unpack_from('<f', event, 24)[0],
              'native_y': struct.unpack_from('<f', event, 28)[0]}
    if any(goal.get(k) != v for k, v in fields.items()):
        raise ValueError('Replay event fields differ from the selected retained goal')
    return {'shot_record_sha256': digest(record), 'event_record_sha256': digest(event),
            'retained_shot_record_sha256': goal['source_record_sha256'],
            'opaque_record_bytes_equal': digest(record) == goal['source_record_sha256'],
            'state': 'same_fixture_event_actor_type_xg_location_and_interval', **fields}


def project_frame(frame: dict, actors: dict, geometry: dict) -> dict:
    joined = identities.project(frame['player_bases'], frame['setup'],
                                frame['entities'], actors['actors'])
    entities = {e['entity_index']: e for e in frame['entities']}
    result = []
    for actor in joined['players']:
        samples = entities[actor['entity_index']]['position_samples']
        endpoints = [s['native_xy'] for s in samples if s['native_local_time'] == 1.0]
        point = endpoints[0] if len(endpoints) == 1 else None
        if point is not None and not all(math.isfinite(v) for v in point):
            raise ValueError('Nonfinite replay position')
        inside = (abs(point[0]) <= geometry['half_width_native'] and
                  abs(point[1]) <= geometry['half_length_native']) if point else None
        result.append({**actor, 'native_xy': point, 'inside_cbe_pitch_extents': inside})
    balls = [s['native_xyz'] for s in frame['ball_samples'] if s['native_local_time'] == 1.0]
    return {'frame_tick': frame['frame_tick'], 'players': result,
            'ball_native_xyz': balls[0] if len(balls) == 1 else None,
            'unresolved_player_entities': joined['unresolved_player_entities'],
            'non_player_entities': joined['non_player_entities'],
            'active_xi_verified': False,
            'position_policy': 'Exact local-time 1 endpoints; pitch bounds are geometry, not participation.',
            'coordinate_units': None}


PHASE_BRIEFS = {
    'outgoing': 'The ball has already left the scorer and is travelling away from him. Show the follow-through of the finish with the ball at its decoded position, clear of the foot or head. Do not show contact.',
    'incoming': 'The ball is still arriving. Show the scorer shaping to meet it. Do not show a follow-through or a ball leaving the scorer.',
    'nearest_to_strike': 'This is the cached frame nearest the strike. Show the scorer meeting the ball at its decoded position. Contact itself is not proved.',
    'strike_or_earlier': 'The ball has not been observed leaving the scorer by this frame. Do not show a completed follow-through.',
    'in_net': 'The ball has crossed the goal line and is in the net at its decoded position. Show the instant the goal is scored: the scorer after the finish at his decoded position, the goalkeeper beaten. Do not show contact or a ball still short of the line.',
    'unresolved': 'The available frames do not establish the phase. Keep the ball at its decoded position with a neutral striking pose; do not imply contact or a flight direction.',
}


STRIKE_REACH = 1.0     # ball this near the scorer's ground position is within his reach
STANDING_HEAD = 1.8    # the camera guide's standing figure, in the units of the decoded coordinates
HIGHEST_LIFT = 0.8     # no schematic scorer leaves the ground by more than this


def header_figure(sequence: dict | None) -> dict:
    """Feet and head heights for the scorer of a headed goal, from the height the ball was met at.

    A ball met at or below a standing head leaves him on the ground. With no frame near the
    strike the height is unknown and he is drawn standing: a leap is never assumed.
    """
    strike = (sequence or {}).get('strike')
    lift = 0.0
    if strike:
        # The ball's centre meets the forehead about 0.1 below the top of the head.
        lift = min(max(strike['ball_height_native']+0.1-STANDING_HEAD, 0.0), HIGHEST_LIFT)
    return {'state': 'from_ball_height_near_strike' if strike else 'height_of_header_unknown',
            'foot_z': round(lift, 2), 'head_z': round(lift+STANDING_HEAD, 2)}


def header_brief(sequence: dict) -> str:
    """What the photograph must show about the height of a headed goal."""
    figure, strike = header_figure(sequence), sequence.get('strike')
    shown = next(r for r in sequence['frames'] if r['frame_tick'] == sequence['depicted_tick'])
    if not strike:
        text = ('HEADER HEIGHT: no frame read shows the ball within reach of the scorer, so the height it was met at is unknown. '
                'Do not show a high leap: keep him within a small jump of the grass.')
    else:
        text = (f"HEADER HEIGHT: at frame {strike['frame_tick']}, the frame nearest the strike, the ball was "
                f"{strike['ball_height_native']:.2f} above the pitch and {strike['ball_to_scorer_native']:.2f} from the scorer's position, "
                f'in the units of the decoded coordinates. A standing figure in the camera guide is {STANDING_HEAD} tall in those units. ')
        text += ('He met the ball at or below the height of a standing head: his boots are on or just above the grass and his neck and trunk bend to the ball. Do not show a leap.'
                 if not figure['foot_z'] else
                 f"He was off the ground by about {figure['foot_z']:.1f} when he met it. Do not lift him higher than that.")
    return (f"{text} In the depicted frame the ball is {shown['ball_native_xyz'][2]:.2f} above the pitch, measured from the grass as the players are: "
            f'a ball near {STANDING_HEAD} is level with the head of a standing player beside it, never with a waist or a knee. '
            'His head, eyes and shoulders follow the ball along its path. His legs are not swinging at it: this is not a volley or a kick.')


def player_motion(frames: list[dict], tick: int) -> dict | None:
    """How far each player moved per tick across the frames either side of `tick`.

    Positions at adjacent cached frames give a direction and a rate. They say nothing of the
    pose: a jump, a turn of the head or an arm is not decoded.
    """
    ordered = sorted(frames, key=lambda f: f['frame_tick'])
    here = [f for f in ordered if f['frame_tick'] == tick]
    if not here:
        return None
    first = ([f for f in ordered if f['frame_tick'] < tick] or here)[-1]
    last = ([f for f in ordered if f['frame_tick'] > tick] or here)[0]
    span = last['frame_tick']-first['frame_tick']
    if not span:
        return None
    start = {p['canonical_person_id']: p['native_xy'] for p in first['players'] if p.get('native_xy')}
    moved = [{'canonical_person_id': p['canonical_person_id'],
              'native_xy_per_tick': [(p['native_xy'][k]-start[p['canonical_person_id']][k])/span for k in (0, 1)]}
             for p in last['players'] if p.get('native_xy') and p['canonical_person_id'] in start]
    return {'from_tick': first['frame_tick'], 'to_tick': last['frame_tick'], 'players': moved}


def action_sequence(frames: list[dict], goal: dict) -> dict:
    """Order cached endpoints around one goal and say which side of the strike each lies on.

    The measure is the ball's distance from the scorer at adjacent endpoints. It orders
    arrival and departure; it does not prove the contact instant or a trajectory.
    """
    pid = goal['actor']['canonical_person_id']
    sign = 1 if goal['attacked_goal_positive_native_y'] else -1
    rows = []
    for frame in sorted(frames, key=lambda f: f['frame_tick']):
        scorer = [p for p in frame['players'] if p['canonical_person_id'] == pid and p.get('native_xy')]
        ball = frame.get('ball_native_xyz')
        if len(scorer) != 1 or not ball:
            continue
        line = max(((frame.get(k) or {}).get('half_length_native') or 0
                    for k in ('pitch_geometry', 'retained_pitch_geometry')), default=0)
        rows.append({'frame_tick': frame['frame_tick'], 'scorer_native_xy': scorer[0]['native_xy'],
                     'ball_native_xyz': ball, 'ball_to_scorer_native': math.dist(ball[:2], scorer[0]['native_xy']),
                     'ball_beyond_attacked_goal_line': bool(line) and sign*ball[1] > line})
    if len({r['frame_tick'] for r in rows}) != len(rows):
        raise ValueError('Replay sequence repeats a tick')
    if not rows:
        raise ValueError('No replay frame positions both the scorer and the ball')
    for i, row in enumerate(rows):
        before = rows[i-1] if i else None
        after = rows[i+1] if i+1 < len(rows) else None
        leaving = before is not None and row['ball_to_scorer_native'] > before['ball_to_scorer_native']
        arriving = after is not None and after['ball_to_scorer_native'] < row['ball_to_scorer_native']
        row['ball_toward_attacked_goal_since_previous'] = (
            None if before is None else sign*(row['ball_native_xyz'][1]-before['ball_native_xyz'][1]) > 0)
        row['phase'] = ('in_net' if row['ball_beyond_attacked_goal_line']
                        else 'unresolved' if (before is None and after is None) or (leaving and arriving)
                        else 'outgoing' if leaving else 'incoming' if arriving
                        else 'nearest_to_strike' if before is not None and after is not None
                        else 'strike_or_earlier')
    # A photograph just after the strike reads best and cannot contradict the pose. The ball
    # in the net is the frame the game keeps for a goal, and the choice when no other was read.
    chosen = next((r for r in rows if r['phase'] == 'outgoing' and r['ball_toward_attacked_goal_since_previous']), None)
    for phase in ('nearest_to_strike', 'strike_or_earlier', 'outgoing', 'in_net'):
        chosen = chosen or next((r for r in reversed(rows) if r['phase'] == phase), None)
    chosen = chosen or rows[0]
    # The frame with the ball nearest the scorer shows the height it was met at, when it is within his reach.
    near = min((r for r in rows if r['phase'] != 'in_net'), key=lambda r: r['ball_to_scorer_native'], default=None)
    strike = None
    if near is not None and near['ball_to_scorer_native'] <= STRIKE_REACH:
        strike = {'frame_tick': near['frame_tick'], 'ball_height_native': near['ball_native_xyz'][2],
                  'ball_to_scorer_native': near['ball_to_scorer_native']}
    return {'state': 'ordered_cached_endpoints', 'frames': rows, 'selected_tick': chosen['frame_tick'],
            'selected_phase': chosen['phase'], 'strike': strike, 'motion': player_motion(frames, chosen['frame_tick']),
            'selection_policy': 'First frame after the ball leaves the scorer toward the attacked goal; otherwise the frame nearest the strike; otherwise the ball in the net.',
            'meaning': 'Phase is inferred from ball-to-scorer distance at adjacent cached endpoints. It is not a decoded contact instant.'}


def open_replay() -> dict:
    """Name the one historical replay open in the game and its cursor, with no capture to compare.

    Enhance Mode uses this to work on the goal the user is looking at. It applies the frame-source
    guards of capture_replay and reads no frame.
    """
    from .bridge import Bridge
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    try:
        with bridge.lock, bridge._read_scope(sid):
            process = bridge._current(sid)
            layout = bridge._player_layout(process)
            base = layout[0] - players.RVA[0]
            fresh = lambda a, n: bridge._read_memory(process, a, n)
            metadata = world.ReadSet(fresh)
            frames.verify_native(metadata, base)
            owners = playback.capture(fresh, base)['matches']
            if len(owners) != 1:
                return {'state': 'none' if not owners else 'several', 'count': len(owners)}
            q = lambda a: players.u64(metadata(a, 8))
            stats = q(owners[0]['source_match_address']+0x14E90)
            active_match_people._type(metadata, base, stats, 0x55FA850, b'16GAME_MATCH_STATS')
            fixture = active_match_source._fixture(metadata, base, q(stats+0x18))[1]
            metadata.verify()
            return {'state': 'open', 'fixture': fixture, 'cursor_tick': owners[0]['current_time_slice']}
    finally:
        bridge.detach()


def capture_replay(capture: dict, event_id: int, *, tick: int | None = None,
                   wait_seconds: float = 0) -> dict:
    """Wait for an already-cached tick while the user/agent plays the replay in UI."""
    return _read_replay(capture, event_id, None if tick is None else [tick], wait_seconds, strict=True)[0]


def watch_replay(capture: dict, event_id: int, ticks: list[int], *, wait_seconds: float = 0,
                 core: list[int] | None = None, on_cursor=None) -> list[dict]:
    """Collect each listed tick as it passes through the game's cache while the replay plays.

    One attachment polls every 25 ms, so a goal that lasts a second of replay is read whole.
    Returns the frames it read in tick order: fewer than asked, or none, when the wait ran out.
    The watch ends early once a `core` tick (default: any listed tick) has been read and the
    replay has played past the last one. `on_cursor` receives the replay cursor on every poll.
    """
    return _read_replay(capture, event_id, sorted(set(ticks)), wait_seconds, strict=False,
                        core=set(ticks if core is None else core), on_cursor=on_cursor)


def _read_replay(capture: dict, event_id: int, ticks: list[int] | None, wait_seconds: float, *,
                 strict: bool, core: set[int] = frozenset(), on_cursor=None) -> list[dict]:
    from .bridge import Bridge
    goal = select_goal(capture, event_id)
    expected = capture['fixture']['fixture']
    if any(type(tick) is not int or not 0 <= tick < 65536 for tick in ticks or []):
        raise ValueError('Replay tick must be an integer below 65536')
    if not 0 <= wait_seconds <= 300:
        raise ValueError('Wait must be between 0 and 300 seconds')
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    try:
        with bridge.lock, bridge._read_scope(sid):
            process = bridge._current(sid)
            layout = bridge._player_layout(process)
            world_read, save, _ = bridge._world_state(process, layout)
            base = layout[0] - players.RVA[0]
            fresh = lambda a, n: bridge._read_memory(process, a, n)
            metadata = world.ReadSet(fresh)
            frames.verify_native(metadata, base)
            frame_world_basis.verify_native(metadata, base)
            for rva, raw in active_match_shots.NATIVE_SPANS + active_match_shot_timeline.DOMAIN_SPANS:
                if metadata(base+rva, len(raw)) != raw:
                    raise ValueError('Replay CBE ownership or event clock source changed')
            shots._verify_native(metadata, base)
            owners = playback.capture(fresh, base)['matches']
            if len(owners) != 1:
                raise ValueError('Open exactly one historical replay')
            before = owners[0]
            engine = before['source_match_address']
            q = lambda a: players.u64(metadata(a, 8))
            stats = q(engine+0x14E90)
            active_match_people._type(metadata, base, stats, 0x55FA850, b'16GAME_MATCH_STATS')
            signature, fixture, decoded, year, day = active_match_source._fixture(metadata, base, q(stats+0x18))
            if match_key(fixture) != match_key(expected):
                raise ValueError('Loaded replay is a different fixture')
            resident, address = active_match_source._resident_day(metadata, base, signature, year, day, tuple(decoded['teams']))
            if address is None:
                raise ValueError('Replay fixture is not uniquely bound to the resident fixture catalog')
            for side in range(2):
                if q(q(engine+0x15370+side*8)+0xB8) != decoded['teams'][side]:
                    raise ValueError('Replay ordered sides differ from its fixture')
            cbe = q(engine+0x14E98)
            if cbe < 4096:
                raise ValueError('Replay CBE absent')
            vectors = [shots._records(metadata, cbe+offset, 48, 1024) for offset in (0x20, 0x38)]
            events = shots._records(metadata, cbe+8, 56, shots.MAX_EVENTS)
            event = check_event(vectors, events, goal)
            width, length = struct.unpack('<ff', metadata(cbe+0x100, 8))
            if not all(math.isfinite(v) and v > 0 for v in (width, length)):
                raise ValueError('Replay pitch dimensions unavailable')
            geometry = {'half_width_native': width, 'half_length_native': length}
            actors = identities.capture_actor_source(metadata, base, engine, engine, before['official_match_unique_id'])
            scorer = [a for a in actors['actors'] if a['side_index'] == goal['side_index']
                      and a['stored_player_slot'] == goal['stored_player_slot']]
            if len(scorer) != 1 or scorer[0]['canonical_person_id'] != goal['actor']['canonical_person_id']:
                raise ValueError('Replay scorer identity differs from retained goal')
            deadline = time.monotonic() + wait_seconds
            fields = ('playback_address', 'frame_provider_address', 'source_match_address',
                      'local_playback_handle', 'official_match_unique_id')
            found, state = {}, 'unavailable'
            while True:
                current = playback.capture(fresh, base)['matches']
                if len(current) != 1 or any(current[0][k] != before[k] for k in fields):
                    raise ValueError('Replay owner changed during capture')
                current = current[0]
                cursor = current['current_time_slice']
                if on_cursor:
                    on_cursor(cursor)
                for tick in [None] if ticks is None else [t for t in ticks if t not in found]:
                    frame = (frames.read_frame(fresh, base, current, fixed_tick=tick)
                             if tick is None or tick <= cursor else {'state': 'tick_not_reached'})
                    state = frame['state']
                    if state == 'available' and frames.read_frame(
                            fresh, base, current, fixed_tick=frame['frame_tick']) == frame:
                        found[frame['frame_tick']] = frame
                # A watch ends early once the replay has played well past the last tick it wanted.
                passed = not strict and core & set(found) and cursor > ticks[-1] + 8
                if len(found) == len(ticks or [None]) or passed or time.monotonic() >= deadline:
                    break
                time.sleep(.025)
            if strict and not found:
                raise ValueError(f'Exact replay tick unavailable ({state}); seek/play its goal and retry')
            metadata.verify()
            world_read.verify()
            bridge._current(sid)
            if bridge._player_layout(process) != layout:
                raise ValueError('Game process layout changed')
            final = playback.capture(fresh, base)['matches']
            if len(final) != 1 or any(final[0][k] != before[k] for k in fields):
                raise ValueError('Replay owner changed at publication')
            return [{'version': 1, 'state': 'verified_historical_replay_frame',
                    'captured_at': datetime.now(timezone.utc).isoformat(), 'fixture': fixture,
                    'event_id': event_id, 'source_id': capture['shots']['source_id'],
                    'event_binding': event, 'official_match_unique_id': before['official_match_unique_id'],
                    'pitch_geometry': geometry, **project_frame(frame, actors, geometry),
                    'save': bridge._public_save(save),
                    'retained_pitch_geometry': capture['shots'].get('pitch_geometry'),
                    'shot_interval_contains_frame': event['native_clock_start_raw'] <= frame['frame_tick'] <= event['native_clock_end_raw'],
                    'raw_frame_sha256': digest(json.dumps(frame, sort_keys=True).encode()),
                    'verification': 'Native guards, unique resident fixture, ordered sides, same shot/event fields, canonical scorer, repeated frame and metadata bytes.',
                    'kit_selection': None, 'pose_and_animation': None,
                    'limitations': ['Frame endpoints are decoded, not proof of the rendered interpolation instant.',
                                    'No native kit selection, pose, shirt-number or left/right shot-foot decode yet.',
                                    'Goal interval alignment is not exact forehead/foot contact proof.']}
                    for frame in (found[tick] for tick in sorted(found))]
    finally:
        bridge.detach()
