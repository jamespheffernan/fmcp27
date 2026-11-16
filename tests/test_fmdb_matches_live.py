"""Live-gated checks of the match tables against the running career (read-only, emulation only).

Skipped unless a supported FM27 process and the native helper are available."""
import sys

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


@pytest.fixture(scope='module')
def engine():
    from fm_live_mcp.fmdb.engine import Engine
    e = Engine.open()
    yield e
    e.close()


def test_results_save_wide_and_goal_vectors_close(engine):
    from fm_live_mcp.fmdb import match_archive as ma
    rows, _ = ma.results(engine)
    assert len(rows) > 50_000
    events = ma.goal_events(engine, rows)
    checked = bad = 0
    for i, (state, evs) in events.items():
        if state != 'present':
            continue
        goals = [0, 0]
        for e in evs:
            if e['kind'] in (0, 1, 2):
                goals[e['side']] += 1
        checked += 1
        bad += tuple(goals) != (rows[i]['home_goals'], rows[i]['away_goals'])
    assert checked > 10_000 and bad <= checked // 1000


def test_competition_labels_and_plans_agree_with_getter(engine):
    from fm_live_mcp.fmdb import match_compstats as mc
    labels = mc.labels(engine)
    assert labels[1] == 'Appearances' and labels[2] == 'Goals' and labels[27] == 'Average Rating'
    objects = mc.stats_objects(engine)
    rows = mc.rows(engine, objects[:20])
    good, bad = mc.verify_plans(engine, rows, sample=24)
    assert not bad, bad


def test_frames_decode_and_team_totals_close(engine):
    from fm_live_mcp.fmdb import match_archive as ma
    bank = ma.banks(engine)[0]
    keys = {k for k, _, _ in bank['entries'][:5]}
    decoded = [x for x in ma.frame_records(engine, keys=keys) if x[0] in keys and not x[5]]
    assert decoded
    for key, _, header, totals, players, _ in decoded:
        for side in (0, 1):
            team = totals['teams'][side]
            assert sum(p['shots'] for p in players if p['side_index'] == side) == team['shots']
