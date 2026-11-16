"""Enhance Mode: the job is resumable, pauses honestly, and never attaches an unreviewed image."""
import asyncio
from copy import deepcopy
import json
import os
import stat

import pytest

from fm_live_mcp import enhance, enhance_codex
from fm_live_mcp.match_stills import prepare, prompt, read_json, write_json
from fm_live_mcp.match_stills_replay import action_sequence, header_brief, header_figure
from fm_live_mcp.match_stills_review import review_template
from test_match_stills import capture  # noqa: F401
from test_match_stills_replay import replay_for, source  # noqa: F401
from test_match_stills_review import PNG, completed_review


@pytest.fixture(autouse=True)
def no_drawing(monkeypatch):
    """The camera guide needs matplotlib; these tests are about the job, not the drawing."""
    monkeypatch.setattr('fm_live_mcp.match_stills_camera_guide.render_file', lambda scene, out: 'not drawn in tests')


def frame(source, tick, ball):
    data = replay_for(source)
    data.update(frame_tick=tick, ball_native_xyz=ball, raw_frame_sha256=f'{tick:064x}',
                retained_pitch_geometry={'half_width_native': 34, 'half_length_native': 52.5})
    return data


class FakeCodex:
    def __init__(self, ready=True, complete=lambda turn: True):
        self.ready, self.complete, self.turns = ready, complete, []

    def doctor(self):
        return {'ready': self.ready, 'codex': '/fake/codex', 'version': 'test', 'login': 'Logged in using ChatGPT',
                'problem': 'Codex is not signed in with a ChatGPT account.', 'fix': 'Run `codex login`.'}

    def run(self, text, folder, log, *, resume=None, timeout=0):
        self.turns.append({'text': text, 'resume': resume})
        scene, words = read_json(folder/'scene.json'), (folder/'goal.prompt.txt').read_bytes()
        (folder/'generation'/'final.png').write_bytes(PNG)
        review = (completed_review(scene, PNG, words) if self.complete(len(self.turns))
                  else review_template(scene, 'goal', PNG, words))
        write_json(folder/'generation'/'final.review.json', review)
        write_json(folder/'generation'/'result.json', {'status': 'pass', 'image': 'generation/final.png',
                   'review': 'generation/final.review.json', 'stages': 1, 'notes': 'Synthetic.'})
        log.write_text('')
        return {'ok': True, 'thread_id': 'thread-1', 'usage': None, 'error': None, 'final_message': 'pass'}


class FakeLive(enhance.Live):
    def __init__(self, source, tmp_path, frames=(), codex=None):
        self.source, self.frames, self.codex = source, {f['frame_tick']: f for f in frames}, codex or FakeCodex()
        self.empty, self.captures = tmp_path/'no-graphics', 0
        self.open, self.cursors, self.window, self.numbers = {'state': 'none', 'count': 0}, [], False, 2

    def fixtures(self):
        f = self.source[0]['fixture']['fixture']
        return [{'native_match_key': 138641, 'shot_map': {'state': 'available'}, 'fixture_summary': {
            'date': f['date'], **{k: {'native_id': f[k]['native_id']} for k in ('home_team', 'away_team', 'competition')}}}]

    def capture(self, match_key):
        self.captures += 1
        return deepcopy(self.source[0])

    def open_replay(self):
        return deepcopy(self.open)

    def watch(self, capture, event_id, ticks, wait_seconds, core, on_cursor):
        for tick in self.cursors:
            on_cursor and on_cursor(tick)
        return [deepcopy(self.frames[tick]) for tick in ticks if tick in self.frames]

    def graphics(self):
        return self.empty

    def squad_numbers(self, capture, players):
        if self.numbers is None:
            raise RuntimeError('game closed')
        return {'state': 'current_squad_numbers', 'read_at_game_date': '2030-12-01', 'meaning': 'Synthetic.',
                'players': [{'canonical_person_id': p['canonical_person_id'], 'person_name': p['person_name'],
                             'side_index': p['side_index'], 'number': self.numbers+i} for i, p in enumerate(players)]}

    def screenshot(self, destination):
        if self.window:
            destination.write_bytes(PNG)
        return self.window


def both_frames(source):
    return [frame(source, 15327, [5.6, 47.9, 1.8]), frame(source, 15330, [2.3, 51.5, 1.3])]


def start(tmp_path, **params):
    return enhance.create_job({'scorer': 'Colwill', 'wait_seconds': 0, **params}, tmp_path/'jobs')


def test_sequence_orders_arrival_strike_and_departure(source):
    goal = source[1]
    balls = {1: [5.5, 41.8, 1], 2: [5.5, 47.4, 1], 3: [4.5, 50.6, 1], 4: [3.0, 56.0, 1]}
    result = action_sequence([frame(source, t, b) for t, b in balls.items()], goal)
    assert [r['phase'] for r in result['frames']] == ['incoming', 'nearest_to_strike', 'outgoing', 'in_net']
    assert result['selected_tick'] == 3 and result['selected_phase'] == 'outgoing'
    alone = action_sequence([frame(source, 1, balls[1])], goal)
    assert alone['selected_phase'] == 'unresolved'
    # The ball past the goal line is the frame the game keeps; it is shown only when nothing nearer the strike was read.
    assert action_sequence([frame(source, 4, balls[4])], goal)['selected_phase'] == 'in_net'


def test_header_is_drawn_at_the_height_the_ball_was_met(source):
    goal = source[1]
    at = action_sequence([frame(source, 1, [0, 0, 1])], goal)['frames'][0]['scorer_native_xy']

    def met(height, away=0.4):
        frames = [frame(source, 1, [at[0], at[1]+away, height]), frame(source, 2, [at[0]-1, at[1]+away+3, height+0.2])]
        return {**action_sequence(frames, goal), 'depicted_tick': 2}

    low = met(1.66)
    assert low['strike'] == {'frame_tick': 1, 'ball_height_native': 1.66, 'ball_to_scorer_native': pytest.approx(0.4)}
    # A ball met below a standing head leaves the scorer on the ground: no leap, and no ball at his waist.
    assert header_figure(low) == {'state': 'from_ball_height_near_strike', 'foot_z': 0.0, 'head_z': 1.8}
    assert 'Do not show a leap' in header_brief(low) and 'not a volley' in header_brief(low)
    assert 'the ball is 1.86 above the pitch' in header_brief(low)
    high = met(2.4)
    assert header_figure(high)['foot_z'] == 0.7 and 'off the ground by about 0.7' in header_brief(high)
    assert header_figure(met(4.0))['foot_z'] == 0.8
    far = met(2.4, away=3)
    assert far['strike'] is None and header_figure(far) == {'state': 'height_of_header_unknown', 'foot_z': 0.0, 'head_z': 1.8}
    assert 'unknown' in header_brief(far) and 'Do not show a high leap' in header_brief(far)


def test_arriving_ball_is_never_described_as_a_finished_shot(source):
    cap, goal = source[0], source[1]
    arriving = action_sequence([frame(source, 15327, [5.5, 41.8, 1]), frame(source, 15328, [5.5, 45.0, 1])], goal)
    assert {r['phase'] for r in arriving['frames']} == {'incoming', 'strike_or_earlier'}
    shown = frame(source, 15328, [5.5, 45.0, 1])
    text = prompt(prepare(cap, 1454, [], replay=shown, sequence=arriving), 'goal')
    assert 'STRIKE OR EARLIER' in text and 'Do not show a completed follow-through' in text
    with pytest.raises(ValueError, match='one frame of its action sequence'):
        prepare(cap, 1454, [], replay=frame(source, 15329, [5, 46, 1]), sequence=arriving)


def test_goal_becomes_a_reviewed_photograph(source, tmp_path):
    live = FakeLive(source, tmp_path, both_frames(source))
    folder = start(tmp_path)
    job = enhance.run_job(folder, live)
    assert job['state'] == 'done', job['message']
    packet = folder/'packet'
    assert (packet/'goal.png').read_bytes() == PNG
    assert 'visual review recorded' in (packet/'index.html').read_text()
    scene = read_json(packet/'scene.json')
    assert scene['action_sequence']['depicted_tick'] == 15330 and scene['action_sequence']['depicted_phase'] == 'outgoing'
    # The camera sits on the edge of the pitch, holds the goal in its frame and never looks through the net.
    camera = scene['camera']
    # and takes the tight view from behind the play, with the goal filling the background.
    assert camera['preset'] == 'behind_the_play' and camera['selection']['positions_tried'] > 50
    assert camera['selection']['goal_share_of_background'] >= 0.6 and camera['horizontal_fov_degrees'] < 12
    text = (packet/'goal.prompt.txt').read_text()
    assert 'THE GOAL IS IN THE PICTURE' in text and 'net hanging behind them' in text
    assert 'SIZE IN THE FRAME: a standing player' in text
    # Each player in the frame is given something to do, from his movement across the frames.
    assert 'A CONTESTED MOMENT, NOT A LINE-UP' in text and 'the goalkeeper' in text
    assert read_json(folder/'sequence.json')['motion']['players']
    # Squad numbers read from the game reach the scene, the prompt and the Codex brief.
    scorer = scene['goal']['actor']
    number = next(n['number'] for n in scene['shirt_numbers']['players'] if n['canonical_person_id'] == scorer['canonical_person_id'])
    assert f"{scorer['person_name']} {number}" in text and 'SQUAD NUMBERS, read from the game on 2030-12-01' in text
    assert "own number" in live.codex.turns[0]['text']
    for name in ('goal', 'celebration'):  # the request must name files that exist where the packet stays
        assert all(os.path.isfile(p) for p in read_json(packet/f'{name}.request.json').get('referenced_image_paths', []))
    assert len(live.codex.turns) == 1 and 'review-template' in live.codex.turns[0]['text']
    report = enhance.status(folder)
    assert report['result']['image'].endswith('packet/goal.png') and report['goal']['scorer'] == 'Levi Colwill'
    # A finished job is not run twice.
    assert enhance.run_job(folder, live)['state'] == 'done' and len(live.codex.turns) == 1


def test_installed_portraits_reach_the_request_and_the_correction_passes(source, tmp_path):
    live = FakeLive(source, tmp_path, both_frames(source))
    pack = live.empty/'megapack'/'faces'
    pack.mkdir(parents=True)
    (pack/'face_28124573.png').write_bytes(PNG)
    (pack/'config.xml').write_text('<record><list id="maps">'
                                   '<record from="face_28124573" to="graphics/pictures/person/28124573/portrait"/>'
                                   '<record from="face_missing" to="graphics/pictures/person/999/portrait"/></list></record>')
    folder = start(tmp_path)
    assert enhance.run_job(folder, live)['state'] == 'done'
    packet = folder/'packet'
    assert [(f['person_id'], f['in_first_request'], f['in_camera_view']) for f in read_json(packet/'faces.json')] == [(28124573, True, True)]
    assert (packet/'faces'/'28124573.png').read_bytes() == PNG
    scene = read_json(packet/'scene.json')
    assert [r['source_url'] for r in scene['references']] == ['fm-graphics:portrait/28124573']
    assert 'faces/ and faces.json' in live.codex.turns[0]['text'] and 'no portrait passes identity_and_gaze' in live.codex.turns[0]['text']


def test_job_waits_for_the_replay_and_resumes_where_it_stopped(source, tmp_path):
    live = FakeLive(source, tmp_path)
    folder = start(tmp_path)
    job = enhance.run_job(folder, live)
    assert job['state'] == 'capture_needed' and 'match review' in job['next_step']
    assert not (folder/'packet').exists() and not live.codex.turns
    live.frames = {f['frame_tick']: f for f in both_frames(source)}
    assert enhance.run_job(folder, live)['state'] == 'done'
    assert live.captures == 1


def test_job_follows_the_replay_open_in_the_game_and_photographs_the_goal_as_it_plays(source, tmp_path):
    second = deepcopy(source[1])
    second.update(event_id=1500, native_clock_start_raw=16000, native_clock_end_raw=16003)
    source[0]['shots']['attempts'].append(second)
    start_tick = source[1]['native_clock_start_raw']
    live = FakeLive(source, tmp_path, both_frames(source))
    live.open = {'state': 'open', 'fixture': source[0]['fixture']['fixture'], 'cursor_tick': start_tick+5}
    live.cursors, live.window = [start_tick-40, start_tick], True
    folder = enhance.create_job({'wait_seconds': 0}, tmp_path/'jobs')   # no scorer: the goal on screen
    job = enhance.run_job(folder, live)
    assert job['state'] == 'done', job['message']
    assert job['event']['event_id'] == 1454 and job['open_replay']['native_match_key'] == 138641
    assert job['screenshot'] == {'state': 'taken_with_replay_cursor_on_goal', 'observed_cursor_tick': start_tick,
                                 'cursor_tick_after': start_tick+5, 'replay_paused': False}
    assert any(r['role'] == 'replay' for r in read_json(folder/'references.json'))
    # A replay that cut away while the window was photographed gives no kit reference.
    live.open['cursor_tick'] = 2
    other = enhance.create_job({'wait_seconds': 0, 'event_id': 1454, 'name': 'cut'}, tmp_path/'jobs')
    cut = enhance.run_job(other, live)
    assert cut['screenshot']['state'] == 'unavailable' and not (other/'screenshot.png').exists()
    # With the cursor on neither goal and no scorer named, the job asks.
    live.open['cursor_tick'] = 30000
    asked = enhance.run_job(enhance.create_job({'wait_seconds': 0, 'name': 'ask'}, tmp_path/'jobs'), live)
    assert asked['state'] == 'choose_goal'


def test_ball_in_the_net_is_photographed_when_it_is_the_only_frame_the_game_kept(source, tmp_path):
    kept = frame(source, source[1]['native_clock_end_raw']+1, [2.3, 54.5, 1.3])
    live = FakeLive(source, tmp_path, [kept])
    folder = start(tmp_path)
    assert enhance.run_job(folder, live)['state'] == 'done'
    assert read_json(folder/'packet'/'scene.json')['action_sequence']['depicted_phase'] == 'in_net'
    assert 'crossed the goal line' in (folder/'packet'/'goal.prompt.txt').read_text()


def test_photograph_is_made_without_numbers_when_the_game_cannot_give_them(source, tmp_path):
    live = FakeLive(source, tmp_path, both_frames(source))
    live.numbers = None
    job = enhance.run_job(start(tmp_path), live)
    assert job['state'] == 'done', job['message']
    folder = tmp_path/'jobs'/job['id']
    assert read_json(folder/'numbers.json') == {'state': 'unavailable', 'reason': 'game closed'}
    assert 'shirt_numbers' not in read_json(folder/'packet'/'scene.json')
    assert 'Kit numbers are not decoded' in (folder/'packet'/'goal.prompt.txt').read_text()
    assert 'no shirt or shorts number is decoded' in live.codex.turns[0]['text']


def test_game_that_cannot_be_read_is_a_pause_not_a_crash(source, tmp_path):
    live = FakeLive(source, tmp_path)
    live.fixtures = lambda: (_ for _ in ()).throw(RuntimeError('task_for_pid failed'))
    job = enhance.run_job(start(tmp_path), live)
    assert job['state'] == 'capture_needed' and 'task_for_pid failed' in job['message']


def test_scorer_match_ignores_accents_and_asks_when_two_goals_match(source, tmp_path):
    second = deepcopy(source[1])
    second.update(event_id=1500, native_clock_start_raw=16000, native_clock_end_raw=16003)
    source[0]['shots']['attempts'].append(second)
    live = FakeLive(source, tmp_path, both_frames(source))
    folder = start(tmp_path, scorer='COLWÍLL')
    job = enhance.run_job(folder, live)
    assert job['state'] == 'choose_goal' and [c['event_id'] for c in job['goal_choices']] == [1454, 1500]
    enhance.update_params(folder, {'event_id': 1454})
    assert enhance.run_job(folder, live)['state'] == 'done'


def test_incomplete_review_is_never_attached(source, tmp_path):
    codex = FakeCodex(complete=lambda turn: False)
    live = FakeLive(source, tmp_path, both_frames(source), codex)
    folder = start(tmp_path)
    job = enhance.run_job(folder, live)
    assert job['state'] == 'review_failed' and 'requires a passing verdict' in job['message']
    assert [t['resume'] for t in codex.turns] == [None, 'thread-1']
    assert not (folder/'packet'/'goal.png').exists() and read_json(folder/'packet'/'scene.json')['images'] == {}
    report = enhance.status(folder)   # the rejected candidate is reported with what it failed, never as the result
    assert report['rejected_candidate'].endswith('generation/final.png') and 'result' not in report
    assert any(line.startswith('scene · positions_and_ball') for line in report['failed_checks'])
    codex.complete = lambda turn: True
    assert enhance.run_job(folder, live)['state'] == 'done'
    assert 'FMCP refused the result' in codex.turns[-1]['text']


def test_codex_outside_the_packet_or_without_chatgpt_is_refused(source, tmp_path):
    live = FakeLive(source, tmp_path, both_frames(source), FakeCodex(ready=False))
    job = enhance.run_job(start(tmp_path), live)
    assert job['state'] == 'codex_needed' and 'ChatGPT' in job['message'] and not live.codex.turns

    class Escaping(FakeCodex):
        def run(self, text, folder, log, **kw):
            result = super().run(text, folder, log, **kw)
            write_json(folder/'generation'/'result.json', {'status': 'pass', 'image': '../capture.json',
                                                            'review': 'generation/final.review.json'})
            return result
    live = FakeLive(source, tmp_path, both_frames(source), Escaping())
    job = enhance.run_job(start(tmp_path, name='escape'), live)
    assert job['state'] == 'review_failed' and 'outside the packet' in job['message']


def test_another_photograph_reuses_the_captured_goal(source, tmp_path):
    live = FakeLive(source, tmp_path, both_frames(source))
    first = start(tmp_path)
    enhance.run_job(first, live)
    # A job made by an earlier version: its sequence has no record of the height the ball was met at.
    write_json(first/'sequence.json', {k: v for k, v in read_json(first/'sequence.json').items() if k != 'strike'})
    offline = FakeLive(source, tmp_path)
    offline.capture = offline.fixtures = lambda *a: (_ for _ in ()).throw(RuntimeError('game closed'))
    second = enhance.create_job({'from_job': first.name, 'direction': 'camera behind the keeper', 'name': 'keeper'}, tmp_path/'jobs')
    job = enhance.run_job(second, offline)
    assert job['state'] == 'done', job['message']
    assert 'strike' in read_json(second/'sequence.json')   # worked out again from the copied frames
    assert 'camera behind the keeper' in (second/'packet'/'goal.prompt.txt').read_text()
    assert 'never moves a player or the ball' in read_json(second/'packet'/'goal.request.json')['prompt']


def fake_codex(tmp_path, login):
    script = tmp_path/'codex'
    script.write_text(f'''#!/bin/sh
case "$1" in
  --version) echo "codex-cli test";;
  login) echo "{login}";;
  features) echo "image_generation    stable    true";;
  exec)
    cat > stdin.txt
    echo "$@" > args.txt
    env | grep -c "API_KEY" > keys.txt
    echo '{{"type":"thread.started","thread_id":"t-9"}}'
    echo '{{"type":"item.completed","item":{{"type":"error","message":"skills budget"}}}}'
    echo '{{"type":"item.completed","item":{{"type":"agent_message","text":"pass: checked"}}}}'
    echo '{{"type":"turn.completed","usage":{{"input_tokens":7}}}}';;
esac
''')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def test_codex_runs_on_the_chatgpt_login_without_api_keys(tmp_path, monkeypatch):
    monkeypatch.setenv('FMCP_CODEX_BIN', str(fake_codex(tmp_path, 'Logged in using ChatGPT')))
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-should-not-travel')
    monkeypatch.setenv('CODEX_API_KEY', 'sk-should-not-travel')
    assert enhance_codex.doctor()['ready'] is True
    packet = tmp_path/'packet'
    packet.mkdir()
    result = enhance_codex.run('the brief', packet, tmp_path/'codex.jsonl')
    assert result == {'ok': True, 'thread_id': 't-9', 'final_message': 'pass: checked', 'usage': {'input_tokens': 7}, 'error': None}
    assert (packet/'stdin.txt').read_text() == 'the brief' and (packet/'keys.txt').read_text().strip() == '0'
    args = (packet/'args.txt').read_text()
    assert 'exec --json' in args and 'workspace-write' in args and 'image_generation' in args
    enhance_codex.run('again', packet, tmp_path/'codex-2.jsonl', resume='t-9')
    assert (packet/'args.txt').read_text().startswith('exec resume') and 't-9' in (packet/'args.txt').read_text()


def test_api_key_login_or_missing_codex_is_not_ready(tmp_path, monkeypatch):
    monkeypatch.setenv('FMCP_CODEX_BIN', str(fake_codex(tmp_path, 'Logged in using an API key')))
    report = enhance_codex.doctor()
    assert report['ready'] is False and 'ChatGPT' in report['fix']
    monkeypatch.setenv('FMCP_CODEX_BIN', str(tmp_path/'absent'))
    assert enhance_codex.doctor()['ready'] is False


def test_tools_start_a_job_and_report_it(tmp_path, monkeypatch):
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp.enhance_tools import register_enhance_tools
    monkeypatch.setenv('FMCP_ENHANCE_DIR', str(tmp_path/'jobs'))
    started = []
    monkeypatch.setattr(enhance, 'spawn', lambda folder: started.append(folder))
    server = FastMCP('test')
    assert register_enhance_tools(server, None) == ['fm_enhance_goal', 'fm_enhance_status']
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert tools['fm_enhance_goal'].annotations.readOnlyHint is False
    assert tools['fm_enhance_status'].annotations.readOnlyHint is True
    asyncio.run(server.call_tool('fm_enhance_goal', {'scorer': 'Henrique', 'direction': 'low and wide'}))
    assert len(started) == 1 and started[0].name.endswith('-henrique')
    job = enhance.load(started[0])
    assert job['params'] == {'scorer': 'Henrique', 'direction': 'low and wide'}
    listed = enhance.recent(tmp_path/'jobs')
    assert [j['job_id'] for j in listed] == [started[0].name] and listed[0]['state'] == 'created'
