"""Live-gated checks of `fmdb/sources/match_state.py` against the running career (read-only).

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


def _table(engine, name):
    from fm_live_mcp.fmdb.sources import match_state as ms
    return next(t for t in ms.tables(engine) if t.name == name)


def test_registration_markers_agree_with_hand_built_projection(engine):
    """Every marker of the managed first team equals player_registration_source.project for the
    same TEAM and selector (newest exact marker), and the committed Premier League set is a squad."""
    from fm_live_mcp import player_registration_source as prs
    from fm_live_mcp.fmdb.sources import _common as C
    rows = list(_table(engine, 'player_registration_marker').rows())
    assert len(rows) > 10_000
    managed = engine.save_info().managed_teams[0] if hasattr(engine.save_info(), 'managed_teams') else None
    teams = C.index_of(engine, 'teams')
    people = C.live(engine, 'people')
    counts = {}
    for r in rows:
        counts[r[2]] = counts.get(r[2], 0) + 1
    team_idx = teams.get(managed) if managed else max(counts, key=counts.get)
    team_ptr = next(p for p, i in teams.items() if i == team_idx)
    prs.verify_native(engine.read, engine.base)
    mine = [r for r in rows if r[2] == team_idx]
    assert mine
    newest = {}
    for r in mine:
        newest[(r[0], r[5])] = r if r[4] != 56 else newest.get((r[0], r[5]), r)
    checked = 0
    for (person, selector), r in newest.items():
        if r[4] == 56:
            continue
        primary = people.pointers[person] - 0x388
        got = prs.project(engine.read, primary, 'actual', team_ptr, selector)['selected_marker']
        assert got and got['native_kind'] == r[4] and got['native_selector'] == selector, (person, selector)
        checked += 1
    assert checked >= 10


def test_rules_name_premier_league_and_uefa_selectors(engine):
    from fm_live_mcp.fmdb.sources import _common as C
    rules = {r[0]: r for r in _table(engine, 'competition_registration_rule').rows()}
    pl = rules[7]                                   # Premier League (database index 7)
    assert pl[4] == 8 and pl[5] == 11               # selector 8, rule competition id 11 (PL native id)
    verdicts = list(_table(engine, 'registration_verdict').rows())
    assert verdicts and {r[4] for r in verdicts} <= {0, 1}
    cov = _table(engine, 'player_registration_marker')
    list(cov.rows())
    assert 'ACTUAL_PLAYER_AND_NON_PLAYER' in cov.coverage() and '0 in a class' in cov.coverage()


def test_squad_and_host_records_name_competitions(engine):
    squad = list(_table(engine, 'squad_manager_entry').rows())
    assert len(squad) > 500 and sum(1 for r in squad if r[5] is not None) > 100
    hosts = list(_table(engine, 'comp_host_record').rows())
    assert len(hosts) > 20 and all(r[1] is not None for r in hosts)
    assert all(1900 <= r[2] <= 2200 for r in hosts)


def test_engine_config_tables(engine):
    momentum = list(_table(engine, 'match_momentum_weight').rows())
    assert len(momentum) == 48 and {r[3] for r in momentum} == {0, 1, 2}
    ratings = list(_table(engine, 'match_rating_weight').rows())
    assert len(ratings) % 22 == 0 and ratings


def test_manager_census_resolves_every_root(engine):
    rows = list(_table(engine, 'native_manager').rows())
    assert all(r[4] in ('resident', 'root empty') for r in rows), [r for r in rows if r[4] not in ('resident', 'root empty')]
    assert next(r for r in rows if r[0] == 'GAME_SQUAD_MANAGER')[4] == 'resident'


def test_screen_statistics_available_or_reasoned(engine):
    from fm_live_mcp.fmdb.sources import match_state as ms
    try:
        rows = ms.screen_stats_rows(engine.read, engine.base)
    except ValueError as exc:
        assert str(exc).startswith('no match loaded') or 'changed' in str(exc)
        return
    assert len(rows) % 2 == 0 and {r[1] for r in rows} == {0, 1}
