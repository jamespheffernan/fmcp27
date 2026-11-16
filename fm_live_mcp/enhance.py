"""Enhance Mode: one resumable job from a recorded goal to a reviewed photograph.

"Send that Henrique goal to Enhance Mode." The job captures the retained match, finds the
goal, reads the replay frames around the strike, gathers the kits and faces, builds the
match-stills packet, has the user's own Codex CLI (signed in with ChatGPT) generate and
inspect the photograph, and attaches it only when the recorded review passes.

Every stage writes its result into the job folder and is skipped when that result exists,
so a job that stops for the game, a goal choice or Codex continues from where it stopped.
Nothing is written to the game. No API key is used.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import threading
import unicodedata

from . import enhance_codex
from .match_stills import attach_image, build_packet, read_json, select_goal, write_json
from .match_stills_camera import editorial_camera
from .match_stills_faces import face_references, find_facepacks
from .match_stills_replay import action_sequence

VERSION = 1
MATCHES_SEARCHED = 6      # most recent retained matches looked through for a scorer
GENERATION_ATTEMPTS = 2   # Codex turns per run: the first, then one correction of a refused review
MAX_STAGES = 6            # image generations Codex may spend in one turn
GAME_ERRORS = (RuntimeError, ValueError, OSError, KeyError)
WAIT_SECONDS = 20         # how long a job watches the replay for the goal's frames unless told otherwise
TICKS_PER_SECOND = 4      # replay ticks in a second of match time, as measured on FM27


class Pause(Exception):
    """The job cannot go further without something outside it. Resume continues from this stage."""

    def __init__(self, state: str, message: str, next_step: str):
        super().__init__(message)
        self.state, self.message, self.next_step = state, message, next_step


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def root() -> Path:
    return Path(os.environ.get('FMCP_ENHANCE_DIR') or Path.home()/'Pictures'/'FMCP 27 Enhance')


def fold(text: str) -> str:
    plain = unicodedata.normalize('NFKD', text or '')
    return ''.join(c for c in plain if not unicodedata.combining(c)).casefold().strip()


def load(folder: Path) -> dict:
    return read_json(folder/'job.json')


def save(folder: Path, job: dict) -> None:
    job['updated_at'] = now()
    temporary = folder/'job.json.writing'
    write_json(temporary, job)
    os.replace(temporary, folder/'job.json')


def alive(pid) -> bool:
    if type(pid) is not int:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Live:
    """Everything that touches the game, the screen or Codex. Tests replace it."""
    codex = enhance_codex

    def fixtures(self) -> list[dict]:
        from .match_stills import capture_live
        return capture_live(None)['fixtures']

    def capture(self, match_key: int) -> dict:
        from .match_stills import capture_live
        return capture_live(match_key)

    def open_replay(self) -> dict:
        from .match_stills_replay import open_replay
        return open_replay()

    def watch(self, capture: dict, event_id: int, ticks: list[int], wait_seconds: float,
              core: list[int], on_cursor) -> list[dict]:
        from .match_stills_replay import watch_replay
        return watch_replay(capture, event_id, ticks, wait_seconds=wait_seconds, core=core, on_cursor=on_cursor)

    def squad_numbers(self, capture: dict, players: list[dict]) -> dict:
        """The squad number each listed player holds now, from the career the capture came from."""
        from .bridge import Bridge
        from .fmdb import tools as db
        same = lambda save: [save.get(k) for k in ('name', 'created_date', 'created_version')]
        bridge = Bridge()
        sid = bridge.attach()['session_id']
        try:
            if same(bridge.get_save(sid)['save']) != same(capture['fixture']['save']):
                return {'state': 'unavailable', 'reason': 'the game has another career open than the one this goal came from'}
            wanted = {p['person_index_word']: p for p in players}
            found, date = [], None
            for start in range(0, len(wanted), 50):
                page = db.db_read(bridge, sid, 'person', sorted(wanted)[start:start+50], ['dbnm', 'Psnu'])
                date = page.get('read_at_game_date')
                for record in page['records']:
                    player, number = wanted.get(record.get('idx')), (record.get('values') or {}).get('squad_number')
                    # Index and unique ID must both be the player's: a number is never taken from a neighbour.
                    if player and record.get('uid') == player['canonical_person_id'] and type(number) is int and number > 0:
                        found.append({'canonical_person_id': player['canonical_person_id'], 'person_name': player['person_name'],
                                      'side_index': player['side_index'], 'number': number})
            return {'state': 'current_squad_numbers', 'read_at_game_date': date, 'players': found,
                    'meaning': 'The squad number each player holds on the read date, from his person record. '
                               'The number worn in this match is not decoded separately.'}
        finally:
            bridge.detach()

    def graphics(self) -> Path:
        return Path.home()/'Library/Application Support/Sports Interactive/Football Manager 27/graphics'

    def screenshot(self, destination: Path) -> bool:
        """Photograph the game window. Needs macOS screen-recording permission; False when it cannot."""
        if sys.platform != 'darwin':
            return False
        script = ('ObjC.import("CoreGraphics");'
                  'const l=ObjC.deepUnwrap(ObjC.castRefToObject($.CGWindowListCopyWindowInfo('
                  '$.kCGWindowListOptionOnScreenOnly|$.kCGWindowListExcludeDesktopElements,0)));'
                  'const w=l.filter(w=>/Football Manager/.test(w.kCGWindowOwnerName||"")&&w.kCGWindowLayer===0)'
                  '.sort((a,b)=>b.kCGWindowBounds.Width*b.kCGWindowBounds.Height-a.kCGWindowBounds.Width*a.kCGWindowBounds.Height)[0];'
                  'w?String(w.kCGWindowNumber):""')
        try:
            window = subprocess.run(['osascript', '-l', 'JavaScript', '-e', script], capture_output=True,
                                    text=True, timeout=20).stdout.strip()
            if not window.isdigit():
                return False
            subprocess.run(['screencapture', '-x', '-o', '-l', window, str(destination)],
                           capture_output=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return False
        # A refused capture leaves no file or an almost empty one.
        return destination.is_file() and destination.stat().st_size > 50_000


# ---------------------------------------------------------------- stages

def goals(capture: dict, scorer: str | None = None) -> list[dict]:
    """Verified goals of a capture in match order, optionally those whose scorer's name contains `scorer`."""
    found = []
    for attempt in capture['shots'].get('attempts', []):
        if attempt.get('outcome') != 'goal':
            continue
        try:
            goal = select_goal(capture, attempt['event_id'])
        except (ValueError, KeyError):
            continue
        if scorer is None or fold(scorer) in fold(goal['actor']['person_name']):
            found.append(goal)
    return sorted(found, key=lambda g: (g.get('native_clock_start_raw') or 0, g['event_id']))


def describe(goal: dict, number: int) -> dict:
    return {'goal_number': number, 'event_id': goal['event_id'], 'scorer': goal['actor']['person_name'],
            'body_part': goal.get('body_part'), 'location': goal.get('official_location')}


def fixture_line(capture: dict) -> str:
    f = capture['fixture']['fixture']
    return f"{f['home_team']['owner']['name']} v {f['away_team']['owner']['name']}, {f['date']}"


def _followed(job: dict, live: Live) -> dict | None:
    """The capture of the match whose replay is open in the game, unless a named scorer has no goal in it."""
    try:
        replay = live.open_replay()
        if replay.get('state') != 'open':
            return None
        fixture = replay['fixture']
        wanted = (fixture['date'], *(fixture[k]['native_id'] for k in ('home_team', 'away_team', 'competition')))
        keys = []
        for row in live.fixtures():
            s = row.get('fixture_summary') or {}
            if row.get('native_match_key') is not None and wanted == (
                    s.get('date'), *((s.get(k) or {}).get('native_id') for k in ('home_team', 'away_team', 'competition'))):
                keys.append(row['native_match_key'])
        if len(keys) != 1:
            return None
        capture = live.capture(keys[0])
    except GAME_ERRORS:
        return None
    if job['params'].get('scorer') and not goals(capture, job['params']['scorer']):
        return None
    job['open_replay'] = {'native_match_key': keys[0], 'cursor_tick': replay['cursor_tick']}
    return capture


def _capture(folder: Path, job: dict, live: Live) -> None:
    target = folder/'capture.json'
    if target.exists():
        return
    p = job['params']
    if p.get('capture'):
        shutil.copyfile(p['capture'], target)
        return
    try:
        if p.get('match_key') is not None:
            capture = live.capture(p['match_key'])
        elif capture := _followed(job, live):
            pass
        else:
            keys = sorted((f['native_match_key'] for f in live.fixtures() if f.get('native_match_key') is not None
                           and (f.get('shot_map') or {}).get('state') in ('available', 'available_partial')), reverse=True)
            if not keys:
                raise Pause('capture_needed', 'The running career has no retained match with shot data.',
                            'Play or load a match, then resume this job.')
            capture = None
            for key in keys[:MATCHES_SEARCHED]:
                candidate = live.capture(key)
                if not p.get('scorer') or goals(candidate, p['scorer']):
                    capture = candidate
                    break
            if capture is None:
                raise Pause('choose_goal', f"No goal by {p['scorer']!r} in the {min(len(keys), MATCHES_SEARCHED)} most recent retained matches.",
                            'Start again with another scorer name or an exact match_key.')
    except GAME_ERRORS as exc:
        raise Pause('capture_needed', f'Football Manager could not be read: {exc}',
                    'Open Football Manager with the career loaded, then resume this job.') from exc
    write_json(target, capture)


def _under_cursor(candidates: list[dict], followed: dict | None) -> list[dict]:
    """Goals the open replay was showing when the job started: cursor from 10 s before to 20 s after."""
    cursor = (followed or {}).get('cursor_tick')
    return [g for g in candidates if type(cursor) is int and type(g.get('native_clock_start_raw')) is int
            and type(g.get('native_clock_end_raw')) is int
            and g['native_clock_start_raw']-TICKS_PER_SECOND*10 <= cursor <= g['native_clock_end_raw']+TICKS_PER_SECOND*20]


def _goal(folder: Path, job: dict, live: Live) -> None:
    if job.get('event'):
        return
    p, capture = job['params'], read_json(folder/'capture.json')
    everything = goals(capture)
    if p.get('event_id') is not None:
        goal = select_goal(capture, p['event_id'])
    else:
        matching = goals(capture, p.get('scorer'))
        number = p.get('goal_number')
        if number is not None:
            if not 1 <= number <= len(matching):
                raise Pause('choose_goal', f'goal_number {number} is outside the {len(matching)} matching goals.',
                            'Resume with a goal_number from the list, or an event_id.')
            goal = matching[number-1]
        elif len(matching) == 1:
            goal = matching[0]
        elif len(under := _under_cursor(matching, job.get('open_replay'))) == 1:
            goal = under[0]
        else:
            job['goal_choices'] = [describe(g, i+1) for i, g in enumerate(matching or everything)]
            raise Pause('choose_goal',
                        (f"{len(matching)} goals match in {fixture_line(capture)}." if matching else
                         f"No goal matches {p.get('scorer')!r} in {fixture_line(capture)}."),
                        'Resume with event_id set to one of goal_choices.')
    job.pop('goal_choices', None)
    job['event'] = {'event_id': goal['event_id'], 'scorer': goal['actor']['person_name'],
                    'person_id': goal['actor']['canonical_person_id'], 'body_part': goal.get('body_part'),
                    'start_tick': goal.get('native_clock_start_raw'), 'end_tick': goal.get('native_clock_end_raw'),
                    'fixture': fixture_line(capture), 'native_match_key': capture['shots']['native_match_key']}


def frame_files(folder: Path) -> dict[int, Path]:
    return {int(f.stem.split('-')[1]): f for f in (folder/'frames').glob('replay-*.json')}


def _frames(folder: Path, job: dict, live: Live) -> None:
    if (folder/'sequence.json').exists():
        return
    p, event = job['params'], job['event']
    capture = read_json(folder/'capture.json')
    (folder/'frames').mkdir(exist_ok=True)
    for source in p.get('replay_files') or []:
        frame = read_json(Path(source))
        if frame.get('state') != 'verified_historical_replay_frame' or frame.get('event_id') != event['event_id']:
            raise ValueError(f'{source} is not a verified replay frame of this goal')
        write_json(folder/'frames'/f"replay-{frame['frame_tick']}.json", frame)
    start, end = event['start_tick'], event['end_tick']
    interval = list(range(start, end+1)) if type(start) is int and type(end) is int else []
    # The frame after the interval is the one the game keeps for a goal it has shown: the ball in the net.
    wanted = set(interval) | ({end+1} if interval else set())
    reason = 'the goal has no recorded tick interval' if not interval else 'the replay did not play the goal while the job watched'
    missing = sorted(wanted - set(frame_files(folder)))
    if missing and not (p.get('offline') or p.get('replay_files')):
        # The game decodes a goal's frames only while its replay plays them, and the job cannot
        # seek. Watch for as long as the caller allows, and photograph the window as the goal passes.
        photo = (ReplayPhoto(live, folder/'screenshot.png', start-1, end+1)
                 if not p.get('screenshot') and not (folder/'screenshot.png').exists() else None)
        try:
            for frame in live.watch(capture, event['event_id'], missing, float(p.get('wait_seconds', WAIT_SECONDS)),
                                    interval, photo.cursor if photo else None):
                write_json(folder/'frames'/f"replay-{frame['frame_tick']}.json", frame)
        except GAME_ERRORS as exc:
            reason = str(exc)
        if photo:
            job['screenshot'] = photo.finish()
    files = frame_files(folder)
    if not files:
        if p.get('allow_no_replay'):
            write_json(folder/'sequence.json', {'state': 'no_replay_frames', 'reason': reason})
            return
        raise Pause('capture_needed', f"None of this goal's replay frames is in the game's cache ({reason}).",
                    f"In Football Manager open {event['fixture']} in the match review and play {event['scorer']}'s goal, "
                    'then resume this job. For the moment of the strike, resume first and play the goal while the job watches.')
    goal = select_goal(capture, event['event_id'])
    sequence = action_sequence([read_json(f) for f in files.values()], goal)
    sequence['missing_ticks'] = sorted(set(interval) - set(files))
    write_json(folder/'sequence.json', sequence)


class ReplayPhoto:
    """Photographs the game window the first time the watched replay cursor is on the goal.

    The picture is kept only if the cursor was still on the goal, or within three seconds
    after it, once the capture had finished: a replay that cut away shows something else.
    """

    def __init__(self, live: Live, shot: Path, first: int, last: int):
        self.live, self.shot, self.first, self.last = live, shot, first, last
        self.thread = self.before = self.taken = None

    def cursor(self, tick: int) -> None:
        if self.thread is None and self.first <= tick <= self.last:
            self.before = tick
            self.thread = threading.Thread(target=self._take, daemon=True)
            self.thread.start()

    def _take(self) -> None:
        self.taken = self.live.screenshot(self.shot)

    def finish(self) -> dict:
        if self.thread is None:
            return {'state': 'unavailable', 'reason': 'the replay cursor was not on the goal while the job watched'}
        self.thread.join(40)
        try:
            after = self.live.open_replay().get('cursor_tick')
        except GAME_ERRORS:
            after = None
        if self.taken and type(after) is int and self.first <= after <= self.last + TICKS_PER_SECOND*3:
            return {'state': 'taken_with_replay_cursor_on_goal', 'observed_cursor_tick': self.before,
                    'cursor_tick_after': after, 'replay_paused': after == self.before}
        self.shot.unlink(missing_ok=True)
        return {'state': 'unavailable', 'reason': (
            'the game window could not be photographed (screen-recording permission)' if not self.taken else
            f'the replay left the goal during the screenshot (cursor {self.before}, then {after})')}


def selected_frame(folder: Path) -> tuple[dict | None, Path | None, dict]:
    sequence = read_json(folder/'sequence.json')
    if sequence.get('state') != 'ordered_cached_endpoints':
        return None, None, sequence
    path = frame_files(folder)[sequence['selected_tick']]
    return read_json(path), path, sequence


def _references(folder: Path, job: dict, live: Live) -> None:
    target = folder/'references.json'
    if target.exists():
        return
    p, event = job['params'], job['event']
    if p.get('references'):
        manifest = Path(p['references'])
        refs = read_json(manifest)
        for ref in refs:
            ref['path'] = str((manifest.parent/ref['path']).resolve())
        write_json(target, refs)
        return
    frame, _, sequence = selected_frame(folder)
    refs, notes = [], []
    shot = Path(p['screenshot']) if p.get('screenshot') else folder/'screenshot.png'
    if frame and shot.is_file():
        tick = p.get('screenshot_tick') if p.get('screenshot') else (job.get('screenshot') or {}).get('observed_cursor_tick')
        same = tick == sequence['selected_tick']
        refs.append({'role': 'replay', 'path': str(shot.resolve()),
                     'source_url': f"fm-replay:{event['native_match_key']}/{event['event_id']}",
                     'native_match_key': event['native_match_key'], 'event_id': event['event_id'],
                     'observed_cursor_tick': tick, 'credit': 'Local game replay',
                     'instruction': 'Game replay of this goal' + (f', replay cursor at tick {tick}' if tick is not None else '')
                     + '. It establishes the kits both teams wore, the stadium and the players involved. '
                     + ('It shows the depicted frame. ' if same else
                        'It is NOT the depicted moment: take the pose and the ball position from the decoded frame and the action phase, never from this image. ')
                     + 'Its broadcast camera is not the output camera. Remove all game interface.'})
    if frame:
        here = next(q['native_xy'] for q in frame['players']
                    if q['canonical_person_id'] == event['person_id'] and q.get('native_xy'))
        # Portraits go first to the players the chosen camera will show, nearest the scorer first.
        try:
            goal = select_goal(read_json(folder/'capture.json'), event['event_id'])
            seen = {a['canonical_person_id'] for a in editorial_camera({'replay': frame, 'goal': goal})['projected_ground_anchors']
                    if a.get('inside_image')}
        except (ValueError, KeyError):
            seen = set()
        near = sorted((q for q in frame['players'] if q.get('native_xy') and q['canonical_person_id'] != event['person_id']),
                      key=lambda q: (q['canonical_person_id'] not in seen, math.dist(q['native_xy'], here)))
        wanted = [event['person_id']] + [q['canonical_person_id'] for q in near[:14]]
        packs = [Path(x) for x in p.get('facepacks') or []] or find_facepacks(live.graphics())
        faces = []
        for pack in packs:
            missing = [i for i in wanted if i not in {f['person_native_id'] for f in faces}]
            if not missing:
                break
            try:
                faces += face_references(frame, pack, missing, skip_missing=True)
            except (ValueError, OSError, SyntaxError) as exc:
                notes.append(f'{pack.name}: {exc}')
        faces.sort(key=lambda f: wanted.index(f['person_native_id']))
        for face in faces:
            face['in_camera_view'] = face['person_native_id'] in seen or face['person_native_id'] == event['person_id']
        # Five inputs per image call: the camera guide takes one, the replay screenshot one.
        # Every portrait found is kept for the correction passes, which take four at a time.
        write_json(folder/'faces.json', faces)
        refs += faces[:4-len(refs)]
        if not packs:
            notes.append('No installed facepack was found; likeness is not reference-backed.')
    job['reference_notes'] = notes
    write_json(target, refs)


def _numbers(folder: Path, job: dict, live: Live) -> None:
    """Squad numbers for the players of the depicted frame. The game is asked even for a job made
    from an earlier one: the numbers are the one thing such a job may still be missing."""
    target = folder/'numbers.json'
    frame = selected_frame(folder)[0]
    if target.exists() or not frame:
        return
    try:
        numbers = live.squad_numbers(read_json(folder/'capture.json'), [p for p in frame['players'] if p.get('native_xy')])
    except GAME_ERRORS as exc:
        numbers = {'state': 'unavailable', 'reason': str(exc)}
    write_json(target, numbers)


def _packet(folder: Path, job: dict, live: Live) -> None:
    packet = folder/'packet'
    if job.get('packet_built') and (packet/'index.html').exists():
        return
    p, event = job['params'], job['event']
    frame, frame_path, sequence = selected_frame(folder)
    # The request files hold absolute image paths, so the packet is built where it will stay.
    # A packet left half-built by an interrupted run is built again from the start.
    if packet.exists():
        shutil.rmtree(packet)
    references = folder/'references.json'
    build_packet(folder/'capture.json', references if read_json(references) else None, event['event_id'], packet,
                 p.get('home_kit') or 'Tko1', p.get('away_kit') or 'Tko1', frame_path,
                 camera='goal-line' if frame else 'replay', sequence=sequence if frame else None,
                 camera_guide=bool(frame),
                 numbers=read_json(folder/'numbers.json') if (folder/'numbers.json').exists() else None)
    if p.get('direction'):
        text = ((packet/'goal.prompt.txt').read_text() +
                f"\nART DIRECTION from the user. It may change camera, framing, light and mood. It never moves a player or the ball, "
                f"changes a kit or replaces an identity: {p['direction'].strip()}\n")
        (packet/'goal.prompt.txt').write_text(text)
        request = read_json(packet/'goal.request.json')
        request['prompt'] = text
        write_json(packet/'goal.request.json', request)
    if (folder/'faces.json').exists():
        (packet/'faces').mkdir()
        listing = []
        for face in read_json(folder/'faces.json'):
            name = f"{face['person_native_id']}.png"
            shutil.copyfile(face['path'], packet/'faces'/name)
            listing.append({'person_id': face['person_native_id'], 'name': face['person_name'], 'file': f'faces/{name}',
                            'sha256': face['portrait_binding']['asset_sha256'], 'source': face['source_url'],
                            'in_camera_view': face.get('in_camera_view'),
                            'in_first_request': any(r.get('person_native_id') == face['person_native_id']
                                                    for r in read_json(references))})
        write_json(packet/'faces.json', listing)
    job['packet_built'] = True
    save(folder, job)


def brief(packet: Path) -> str:
    package = Path(__file__).resolve().parents[1]
    template = (f'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH={shlex.quote(str(package))} {shlex.quote(sys.executable)} '
                '-m fm_live_mcp.match_stills review-template --packet . --mode goal '
                '--image generation/final.png --out generation/final.review.json')
    scene = read_json(packet/'scene.json') if (packet/'scene.json').exists() else {}
    numbers = ('the prompt lists each player\'s squad number, read from the game. A back turned to the camera carries that player\'s own number, '
               'readable when he is near enough; a facing player may carry it small on his shorts. A wrong number, a number on a shirt front, '
               'or a numeral on a player the list does not cover fails: correct it with an edit pass.'
               if (scene.get('shirt_numbers') or {}).get('players') else
               'no shirt or shorts number is decoded. A readable number passes only where the replay screenshot shows that number on that '
               'player. Any other readable numeral is invented and fails: remove it, or let pose, a fold or distance make it unreadable.')
    return f'''You are running FMCP 27 Enhance Mode. The job: turn one recorded Football Manager goal into a photorealistic press photograph, and check it properly before the user ever sees it. The user is not watching this run and cannot answer questions, so decide and continue. Work only inside the current folder, the packet.

What is in the packet
- goal.request.json: the image request. `prompt` is the full brief; `referenced_image_paths` are the input images, in the order the prompt numbers them.
- references/ and camera-guide.png: those inputs. scene.json: the decoded evidence (player positions, ball, kits, action phase).
- faces/ and faces.json: portraits of the players nearest the scorer, each bound to an exact person ID. One image call takes five inputs, so the first request carries only a few of them. The rest are for your correction passes.
- visual-review.md: the review every candidate has to pass. Read it before generating.

What passes
- Positions: the arrangement seen from this camera matches the decoded frame and camera-guide.png, which also draws the goal, its net and the pitch lines. The goal frame and net are in the photograph where the guide has them. That means left-to-right order, who is nearer the camera, which side of the scorer the ball and the goalkeeper are on, rough spacing, and size that falls with distance. The image model cannot hit pixel anchors: a figure some tens of pixels from its projected anchor passes, with the deviation noted. A player on the wrong side of another, or the ball on the wrong side of the scorer, fails.
- Likeness: judged against a portrait only where one exists in references/ or faces/. A visible player with no portrait passes identity_and_gaze when the face is natural and the gaze fits the action; say in the note that no reference exists and the likeness is unverified, and say it again in identity_sources_and_limits.
- Numbers: {numbers}
- Everything else exactly as visual-review.md says. Anatomy, kit colours, action phase and focus are not relaxed.

Steps
1. Read visual-review.md and goal.prompt.txt. Open every image in referenced_image_paths with view_image so you know what each one shows.
2. Generate the photograph with the built-in image generation tool (image_gen). Use the prompt from goal.request.json as written and give the tool the referenced images. Use only the built-in tool: no API key, no imagegen CLI fallback, no other image service.
3. The tool saves under $CODEX_HOME/generated_images. Copy each result into generation/ as stage-N.png and write the request you used to generation/stage-N.request.json as {{"prompt": ..., "referenced_image_paths": [...]}}.
4. Inspect the candidate at full size the way visual-review.md describes: the action phase and the ball first, then each visible player's proportions, the join of head, neck and shoulders, likeness, kit and focus. The failures that have come up before: heads too large for their bodies, a portrait pasted onto a body, a player drawn larger than his distance allows, the ball on the wrong side of the scorer, a pose from a different moment than the ball, a kit or back-of-shirt detail lost during a face edit, and the same blur on everything.
5. If anything fails, correct it with an edit pass: one targeted change, the previous stage as the edit target plus at most four other images, everything already accepted held fixed. For a visible player whose face does not follow his portrait in faces/, pass that portrait in the edit, up to four portraits a pass. Inspect ALL players again after every pass. Spend at most {MAX_STAGES} generations in total.
6. When a candidate passes, copy it to generation/final.png and overwrite goal.prompt.txt with the prompt that produced it. For a chain of edits that is the first-stage prompt followed by each edit prompt under a "Correction pass N" heading. Then delete any old generation/final.review.json and run:
   {template}
   Complete generation/final.review.json from what you see in final.png: reviewer "Codex (Enhance Mode)", inspected_at as the current UTC time in ISO 8601, a visibility for every listed person (visible, occluded or out_of_frame, with a note for the hidden ones), the six checks for every visible player, the five scene checks, and verdict "pass". A check you did not inspect stays pending. If no candidate passes within the limit, do the same for the best one, leave its failing checks as "fail" and set the verdict to "fail".
7. Write generation/result.json: {{"status": "pass" or "fail", "image": "generation/final.png", "review": "generation/final.review.json", "stages": N, "notes": "one or two sentences: what was corrected, what remains uncertain"}}.

FMCP checks the review against the hashes of final.png, goal.prompt.txt and the scene after you finish, and refuses anything stale or incomplete. So finish final.png and goal.prompt.txt first, make the template after that, and change neither file again.

End with one line: pass or fail, and why.'''


def _generate(folder: Path, job: dict, live: Live) -> None:
    packet = folder/'packet'
    if 'goal' in read_json(packet/'scene.json')['images']:
        return
    ready = live.codex.doctor()
    job['codex'] = {k: ready.get(k) for k in ('codex', 'version', 'login')}
    if not ready['ready']:
        raise Pause('codex_needed', ready['problem'], ready['fix'])
    (packet/'generation').mkdir(exist_ok=True)
    error = job.get('review_error')
    for _ in range(GENERATION_ATTEMPTS):
        thread = job.get('codex_thread')
        text = brief(packet) if thread is None else (
            f'FMCP refused the result: {error}\nCorrect that, keeping everything already accepted. If the review was '
            'incomplete or stale, make a fresh template for the final image and complete it. Then rewrite generation/result.json.')
        run_number = len(job.setdefault('codex_runs', [])) + 1
        job.update(state='running', message=f'Codex is generating and reviewing the photograph (turn {run_number}).')
        save(folder, job)
        run = live.codex.run(text, packet, folder/f'codex-{run_number}.jsonl', resume=thread,
                             timeout=float(job['params'].get('codex_timeout', 2700)))
        job['codex_thread'] = run.get('thread_id') or thread
        job['codex_runs'].append({'at': now(), 'ok': run['ok'], 'usage': run.get('usage'), 'error': run.get('error'),
                                  'final_message': run.get('final_message')})
        if not run['ok']:
            error = run['error']
            if job['codex_thread'] is None:
                break
            continue
        try:
            result = read_json(packet/'generation'/'result.json')
            image, review = [(packet/result[k]).resolve() for k in ('image', 'review')]
            if not all(path.is_relative_to(packet.resolve()) for path in (image, review)):
                raise ValueError('Codex named a file outside the packet')
            if result.get('status') != 'pass':
                raise ValueError(f"no candidate passed Codex's own review: {result.get('notes')}")
            attach_image(packet, 'goal', image, review)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            error = str(exc)
            continue
        job.pop('review_error', None)
        job['result_notes'] = result.get('notes')
        return
    job['review_error'] = error
    raise Pause('review_failed', f'No photograph passed the review gate: {error}',
                'Resume this job for another correction turn. Rejected candidates are in packet/generation.')


STAGES = (('capture', _capture), ('goal', _goal), ('frames', _frames), ('references', _references),
          ('numbers', _numbers), ('packet', _packet), ('generate', _generate))


# ---------------------------------------------------------------- jobs

def create_job(params: dict, base: Path | None = None) -> Path:
    base = base or root()
    params = {k: v for k, v in params.items() if v not in (None, [], '')}
    source = resolve(params['from_job'], base) if params.get('from_job') else None
    label = params.get('name') or params.get('scorer') or (load(source)['event']['scorer'] if source else None) or 'goal'
    slug = re.sub(r'[^a-z0-9]+', '-', fold(str(label))).strip('-')[:40] or 'goal'
    folder = base/f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{slug}"
    folder.mkdir(parents=True, exist_ok=False)
    job = {'version': VERSION, 'id': folder.name, 'created_at': now(), 'state': 'created', 'stage': None,
           'message': '', 'next_step': '', 'params': params, 'history': []}
    if source:
        # Another photograph of the same captured goal: reuse the evidence, build a new packet.
        earlier = load(source)
        if not earlier.get('event'):
            raise ValueError('The earlier job never reached a goal; start a new one instead')
        frames = (source/'frames').is_dir() and any((source/'frames').glob('replay-*.json'))
        # The sequence is worked out again from the copied frames, so a job made by an earlier
        # version gains what this version reads from them. With no frames its record is kept.
        for name in ('capture.json', 'references.json', 'faces.json', 'screenshot.png', 'numbers.json') + (() if frames else ('sequence.json',)):
            if (source/name).exists():
                shutil.copyfile(source/name, folder/name)
        if (source/'frames').is_dir():
            shutil.copytree(source/'frames', folder/'frames')
        references = folder/'references.json'
        if references.exists():  # the copied screenshot is this job's own file now
            refs = read_json(references)
            for ref in refs:
                if ref['path'] == str((source/'screenshot.png').resolve()):
                    ref['path'] = str((folder/'screenshot.png').resolve())
            write_json(references, refs)
        job['event'], job['screenshot'] = earlier['event'], earlier.get('screenshot')
        params['offline'] = True
    save(folder, job)
    return folder


def resolve(reference: str, base: Path | None = None) -> Path:
    folder = Path(reference).expanduser()
    if not (folder/'job.json').is_file():
        folder = (base or root())/reference
    if not (folder/'job.json').is_file():
        raise ValueError(f'No Enhance Mode job at {reference}')
    return folder


def run_job(folder: Path, live: Live | None = None) -> dict:
    live = live or Live()
    job = load(folder)
    if job['state'] == 'done':
        return job
    if job['state'] == 'running' and job.get('pid') != os.getpid() and alive(job.get('pid')):
        raise ValueError('This job is already running')
    job.update(state='running', pid=os.getpid(), message='', next_step='')
    try:
        for name, stage in STAGES:
            job['stage'] = name
            save(folder, job)
            stage(folder, job, live)
            job['history'].append({'at': now(), 'stage': name, 'state': 'done'})
        packet = folder/'packet'
        image = read_json(packet/'scene.json')['images']['goal']
        job.update(state='done', stage=None, message='The photograph passed its review.', next_step='',
                   result={'image': str(packet/image['file']), 'gallery': str(packet/'index.html'),
                           'review': str(packet/image['review_file']), 'notes': job.get('result_notes')})
    except Pause as pause:
        job.update(state=pause.state, message=pause.message, next_step=pause.next_step)
        job['history'].append({'at': now(), 'stage': job['stage'], 'state': pause.state, 'message': pause.message})
    except Exception as exc:  # the job file is the only place a detached run can report to
        job.update(state='failed', message=f'{type(exc).__name__}: {exc}', next_step='Resume to retry this stage.')
        job['history'].append({'at': now(), 'stage': job['stage'], 'state': 'failed', 'message': job['message']})
    job.pop('pid', None)
    save(folder, job)
    return job


def update_params(folder: Path, changes: dict) -> None:
    """Answers to a paused job: a goal choice, a longer wait, permission to go on without a replay."""
    changes = {k: v for k, v in changes.items() if v is not None}
    if not changes:
        return
    job = load(folder)
    job['params'].update(changes)
    save(folder, job)


def spawn(folder: Path) -> int:
    """Continue a job in a process of its own, so a tool call can return while Codex works."""
    job = load(folder)
    if job['state'] == 'running' and alive(job.get('pid')):
        return job['pid']
    package = str(Path(__file__).resolve().parents[1])
    with (folder/'run.log').open('ab') as log:
        process = subprocess.Popen(
            [sys.executable, '-m', 'fm_live_mcp.enhance', 'resume', str(folder)], stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True, cwd=package,
            env={**os.environ, 'PYTHONPATH': os.pathsep.join(filter(None, [package, os.environ.get('PYTHONPATH')]))})
    job.update(state='running', pid=process.pid, message='Started.', next_step='')
    save(folder, job)
    return process.pid


def status(folder: Path) -> dict:
    job = load(folder)
    state = job['state']
    if state == 'running' and not alive(job.get('pid')):
        state, job['message'], job['next_step'] = 'interrupted', 'The run stopped before finishing.', 'Resume this job.'
    report = {'job_id': job['id'], 'folder': str(folder), 'state': state, 'stage': job.get('stage'),
              'message': job.get('message'), 'next_step': job.get('next_step'), 'goal': job.get('event'),
              'updated_at': job.get('updated_at')}
    for key in ('goal_choices', 'result', 'screenshot', 'reference_notes', 'codex'):
        if job.get(key):
            report[key] = job[key]
    if (folder/'sequence.json').exists():
        sequence = read_json(folder/'sequence.json')
        report['action_phase'] = {k: sequence.get(k) for k in ('state', 'selected_tick', 'selected_phase', 'missing_ticks')}
    report['codex_turns'] = len(job.get('codex_runs', []))
    if state == 'review_failed':
        report.update(rejected(folder/'packet'))
    return report


def rejected(packet: Path) -> dict:
    """The best candidate a failed run left behind, and the checks it failed. It is not attached."""
    image, review = packet/'generation'/'final.png', packet/'generation'/'final.review.json'
    if not image.is_file():
        return {}
    failed = []
    try:
        data = read_json(review)
        failed += [f"scene · {name}: {check.get('notes')}" for name, check in data.get('scene_checks', {}).items()
                   if check.get('status') != 'pass']
        for row in data.get('players', []):
            failed += [f"{row.get('name')} · {name}: {check.get('notes')}" for name, check in (row.get('checks') or {}).items()
                       if row.get('visibility') == 'visible' and check.get('status') not in ('pass', 'not_visible')]
    except (OSError, ValueError, AttributeError):
        pass
    return {'rejected_candidate': str(image), 'failed_checks': failed}


def recent(base: Path | None = None, limit: int = 10) -> list[dict]:
    base = base or root()
    folders = sorted((f.parent for f in base.glob('*/job.json')), reverse=True) if base.is_dir() else []
    return [status(folder) for folder in folders[:limit]]


# ---------------------------------------------------------------- command line

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='fm-enhance', description=__doc__.split('\n\n')[0])
    parser.add_argument('--root', type=Path, help='Folder that holds the jobs (default: FMCP_ENHANCE_DIR or ~/Pictures/FMCP 27 Enhance)')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor', help='Check that Codex is installed and signed in with ChatGPT')
    start = sub.add_parser('start', help='Send a goal to Enhance Mode')
    resume = sub.add_parser('resume', help='Continue a job that stopped')
    resume.add_argument('job')
    for command in (start, resume):
        command.add_argument('--event-id', type=int, help='Exact goal event')
        command.add_argument('--goal-number', type=int, help='Which of the matching goals, counted from 1 in match order')
        command.add_argument('--wait-seconds', type=float, help='How long to watch the replay for the goal to be played (default 20, at most 300)')
        command.add_argument('--allow-no-replay', action='store_true', default=None,
                             help='Go on from the shot origin alone when no replay frame can be read')
        command.add_argument('--detach', action='store_true', help='Return at once; follow with status')
    start.add_argument('--scorer', help='Part of the scorer\'s name')
    start.add_argument('--match-key', type=int, help='Exact retained match; default: the most recent with a matching goal')
    start.add_argument('--direction', help='Art direction for the photograph, e.g. "camera behind the keeper"')
    start.add_argument('--from-job', help='Reuse the captured goal of an earlier job for another photograph')
    start.add_argument('--capture', type=Path, help='A saved capture instead of the running game')
    start.add_argument('--replay', type=Path, action='append', dest='replay_files', help='Saved replay frame(s) of the goal')
    start.add_argument('--references', type=Path, help='A reference manifest instead of automatic faces and screenshot')
    start.add_argument('--screenshot', type=Path, help='A replay screenshot of this goal')
    start.add_argument('--screenshot-tick', type=int, help='Replay tick the screenshot was taken at')
    start.add_argument('--facepack', type=Path, action='append', dest='facepacks', help='Facepack folder(s); default: installed ones')
    start.add_argument('--home-kit', choices=('Tko1', 'Tko2', 'Tko3'))
    start.add_argument('--away-kit', choices=('Tko1', 'Tko2', 'Tko3'))
    start.add_argument('--name', help='Label for the job folder')
    state = sub.add_parser('status', help='Show one job, or the recent ones')
    state.add_argument('job', nargs='?')
    args = parser.parse_args(argv)
    base = args.root or root()
    try:
        if args.command == 'doctor':
            report = enhance_codex.doctor()
            print(json.dumps(report, indent=2))
            return 0 if report['ready'] else 1
        if args.command == 'status':
            print(json.dumps(status(resolve(args.job, base)) if args.job else recent(base), ensure_ascii=False, indent=2))
            return 0
        if args.command == 'start':
            params = {k: (str(v.resolve()) if isinstance(v, Path) else [str(x.resolve()) for x in v] if isinstance(v, list) else v)
                      for k, v in vars(args).items() if k not in ('command', 'root', 'detach')}
            folder = create_job(params, base)
        else:
            folder = resolve(args.job, base)
            update_params(folder, {'event_id': args.event_id, 'goal_number': args.goal_number,
                                   'wait_seconds': args.wait_seconds, 'allow_no_replay': args.allow_no_replay})
        if args.detach:
            spawn(folder)
        else:
            run_job(folder)
        report = status(folder)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report['state'] in ('done', 'running') else 2
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f'fm-enhance: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
