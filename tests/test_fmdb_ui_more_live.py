"""Live-gated checks of the ui_recipes_more screens (skipped unless FM27 runs).

Structural checks always run; values seen on the owner's screens (Newcastle, 10 Dec 2030)
are checked only with FMDB_REFERENCE_SAVE=1, because the save moves on.
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fmdb_ui_live import _live_available  # noqa: E402

pytestmark = pytest.mark.skipif(not _live_available(), reason='FM27 not running or helper missing')
REFERENCE = os.environ.get('FMDB_REFERENCE_SAVE') == '1'
# Unavailable on the reference save, with the reason (std::random_device is refused by the VM).
EXPECTED_UNAVAILABLE = {'youth_intake': {'youth_intake_level', 'youth_intake_feedback'}}


@pytest.fixture(scope='module')
def live():
    sys.path.insert(0, str(ROOT / 'scripts'))
    from fmdb_ui_read import open_vm
    session, memory, vm = open_vm()
    yield session, vm
    memory.close()
    session.close()


@pytest.mark.parametrize('name', ['scouting', 'transfers', 'squad_dynamics', 'training', 'medical', 'finances',
                                  'youth_intake', 'league_table', 'manager_profile', 'season_expectations'])
def test_screen_reads_and_is_json(live, name):
    from fm_live_mcp.fmdb import ui_recipes_more as M
    session, vm = live
    out = M.SCREENS[name](vm)
    json.dumps(out)
    assert out['coverage']['value'] > 0
    unavailable = set()
    for source in out['sources'].values():
        unavailable |= set(source['unavailable'])
    assert unavailable <= EXPECTED_UNAVAILABLE.get(name, set()), unavailable
    if not REFERENCE:
        return
    if name == 'league_table':
        top = out['table'][0]
        assert (top['team']['name'], top['played'], top['points']) == ('Arsenal', 16, 38)
        assert len(out['table']) == 20
    if name == 'training':
        assert out['input_status']['TiSc'].startswith('ok')
        assert [u['name'] for u in out['units'].values()] == ['Goalkeeping Unit', 'Defensive Unit',
                                                              'Midfield Unit', 'Attacking Unit']
        assert out['schedule'][1] == {'day': 'Tuesday', 'sessions': ['Travel', 'Match', 'Travel']}
    if name == 'season_expectations':
        rows = {r['competition']['name']: (r['expected_stage'], r['importance']) for r in out['competitions']}
        assert rows['Emirates FA Cup'] == ('Final', 'Preferred')


def test_fixture_result_for_the_last_match(live):
    from datetime import date, timedelta
    from fm_live_mcp.fmdb import ui_recipes_more as M, ui_recipes_news as N
    session, vm = live
    view = M.viewer(vm)
    today = date.fromisoformat(view.game_date)
    rows = [r for r in N.calendar(vm, days=21, start=today - timedelta(days=21), fixture_details=False)
            if r['kind'] == 'fixture' and (r.get('team') or {}).get('id') == view.team_id and r['date'] < view.game_date]
    if not rows:
        pytest.skip('no played fixture in the last three weeks')
    row = rows[-1]
    mine, theirs = row['team']['id'], row['opponent']['id']
    home, away = (mine, theirs) if row.get('is_home') else (theirs, mine)
    ref = row['fixture_ref']['dcnt']
    out = M.fixture_result(vm, home, away, N.si_date(date.fromisoformat(ref.iso), ref.low))
    assert all(str(s).startswith('ok') for s in out['input_status'].values())
    assert out['has_result'] is True and isinstance(out['result'], str) and ' - ' in out['result']
    assert isinstance(out['result_type'], int)
    if REFERENCE and row['date'] == '2030-12-07':
        assert (out['home_score'], out['away_score'], out['result']) == ('0', '0', '0 - 0')
