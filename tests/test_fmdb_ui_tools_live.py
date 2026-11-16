"""Live-gated checks of the UI tools (skipped unless one supported FM27 process and the helper
run). Ground truth: the owner's Board > Confidence screens for the Newcastle United career on
10 Dec 2030; the equality test skips on any other save or date."""
import sys
import time

import pytest


def _live_available():
    if sys.platform != 'darwin':
        return False
    try:
        from fm_live_mcp.bridge import Bridge, discover_processes
        return Bridge().helper.is_file() and len(discover_processes()) == 1
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _live_available(), reason='FM27 not running or helper missing')

GROUND_TRUTH = {
    'overall': ('B', 'To summarise, the board are very pleased with your overall leadership of the team.'),
    'areas': {'club_vision': 'C+', 'match': 'C', 'recruitment': 'B', 'tactics': 'C+', 'squad': 'B+'},
    'signings': {'Huber': 'B+', 'Colwill': 'B+', 'Diouf': 'B-', 'Fabbian': 'B+', 'Riad': 'A'},
}


@pytest.fixture(scope='module')
def live(tmp_path_factory):
    import os
    from fm_live_mcp.bridge import Bridge
    from fm_live_mcp.fmdb import ui_tools
    old = os.environ.get('FMCP_CACHE_DIR')
    os.environ['FMCP_CACHE_DIR'] = str(tmp_path_factory.mktemp('fmcp-cache'))
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    yield bridge, sid, ui_tools
    bridge.detach()
    if old is None:
        os.environ.pop('FMCP_CACHE_DIR', None)
    else:
        os.environ['FMCP_CACHE_DIR'] = old


def test_board_confidence_matches_screens_and_caches(live):
    bridge, sid, ui_tools = live
    started = time.perf_counter()
    answer = ui_tools.board_confidence(bridge, sid, fresh=True)
    cold = time.perf_counter() - started
    if answer['game_date'] != '2030-12-10' or answer['team']['name'] != 'Newcastle United':
        pytest.skip(f'ground truth is for Newcastle on 2030-12-10, not {answer["team"]["name"]} on {answer["game_date"]}')
    assert 'warning' not in answer and answer['cache']['hit'] is False
    letter, sentence = GROUND_TRUTH['overall']
    assert answer['overall']['grade']['letter'] == letter and answer['overall']['sentence'] == sentence
    assert {k: v['grade']['letter'] for k, v in answer['areas'].items()} == GROUND_TRUTH['areas']
    signings = {s['name'].split()[-1]: s['board']['grade']['letter'] for s in answer['signings']}
    assert signings == GROUND_TRUTH['signings']
    assert all(s['supporters']['reaction'] and s['wage'] for s in answer['signings'])
    assert answer['rng']['draws'] == 8 and answer['rng']['fields_depending_on_draws'] == []
    assert isinstance(answer['job_security']['value'], int)
    started = time.perf_counter()
    again = ui_tools.board_confidence(bridge, sid)
    warm = time.perf_counter() - started
    assert again['cache']['hit'] is True and again['cache']['computed_at'] == answer['cache']['computed_at']
    assert again['overall'] == answer['overall'] and again['signings'] == answer['signings']
    assert warm < 3.0 and warm < cold, (warm, cold)


def test_ui_read_generic_and_guard_rails(live):
    bridge, sid, ui_tools = live
    training = ui_tools.ui_read(bridge, sid, 'TEAM_TRAINING', {'Ttea': 'managed_team'}, keys=['TrainingIntensities'])
    assert training['rows'][0]['value'][2]['qvJ6'] == 'Normal Intensity'
    stopped = ui_tools.ui_read(bridge, sid, 114, {'Ttea': 'managed_team'}, keys=['4zmg'], fresh=True,
                               max_instructions=5_000_000)
    assert 'instruction or time budget' in stopped['input_status']['Tcnf']
    assert stopped['cache']['stored'] is False
    with pytest.raises(ui_tools.UiToolError, match='not buildable'):
        ui_tools.ui_read(bridge, sid, 28)
