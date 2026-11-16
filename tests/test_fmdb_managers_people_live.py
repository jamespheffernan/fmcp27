"""People-side manager tables against the running game.

Skipped unless a supported FM27 process and the native helper are available."""
import struct
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


@pytest.fixture(scope='module')
def tabs(engine):
    from fm_live_mcp.fmdb import sources
    found, failures = sources.discover(engine, only=['managers_people'])
    assert not failures
    return {t.name: t for _, t in found}


def test_every_manager_object_carries_its_vtable(engine):
    from fm_live_mcp.fmdb import mgr_walk_people as MW
    w = MW.walk(engine)
    assert w.problems == {}
    assert set(w.heads) == {m.name for m in MW.MANAGERS}
    for m in MW.MANAGERS:
        assert struct.unpack_from('<Q', w.heads[m.name], 0)[0] == engine.base + m.vtable


def test_containers_pass_their_header_checks_and_classify(engine, tabs):
    rows = list(tabs['people_manager_container'].rows())
    assert not [r for r in rows if r[4].startswith('invalid')]
    by = {(r[0], r[1]): r for r in rows}
    # award periods are AWARD_DATA objects, the +0x30 list is db::AWARD records
    assert set(__import__('json').loads(by[('AWARD_MANAGER', 0x18)][8])) <= {
        'YEAR_AWARD_DATA', 'MONTH_AWARD_DATA', 'TEAM_AWARD_DATA', 'GOAL_AWARD_DATA', 'CLUB_AWARD_DATA'}
    assert by[('AWARD_MANAGER', 0x30)][9] == 'awards'
    assert by[('SIMULATED_STATS_MANAGER', 0x48)][9] == 'teams'
    assert by[('INTERACTION_MANAGER', 0xF8)][5] > 100


def test_interaction_items_reference_people_and_teams(tabs):
    rows = list(tabs['interaction_item'].rows())
    assert len(rows) > 100
    resolved = sum(1 for r in rows if r[3] is not None and r[4] is not None)
    assert resolved >= 0.95 * len(rows)
    assert all(r[1] in (1, 2, 3, 4, 5, 6) for r in rows)       # reference counts
    dated = [r for r in rows if r[9] and r[10]]
    assert dated and sum(1 for r in dated if r[10] >= r[9]) >= 0.95 * len(dated)


def test_award_schedule_awards_resolve(tabs):
    rows = list(tabs['award_schedule'].rows())
    assert len(rows) > 50
    assert all(r[2] is not None for r in rows)
    assert {r[1] for r in rows} <= {'YEAR_AWARD_DATA', 'MONTH_AWARD_DATA', 'TEAM_AWARD_DATA', 'GOAL_AWARD_DATA',
                                    'CLUB_AWARD_DATA'}


def test_hall_of_fame_has_points_and_birth_dates(engine, tabs):
    rows = list(tabs['hall_of_fame_entry'].rows())
    hof = [r for r in rows if r[0] == 'hall_of_fame']
    assert len(hof) > 1000
    assert len([r for r in rows if r[0] == 'human_managers']) >= 1
    top = sorted(hof, key=lambda r: -r[9])[:20]
    assert all(r[5] and '1920' < r[5] < '2000' for r in top)        # birth dates of senior managers
    assert sum(1 for r in top if r[2] is not None) >= 10                 # most still in the database
    assert all(r[4] is not None for r in hof)


def test_fingerprints_are_stable_without_change(tabs):
    for t in tabs.values():
        assert t.fingerprint() == t.fingerprint(), t.name


def test_injury_cases_are_people_with_a_current_injury(engine, tabs):
    from fm_live_mcp.fmdb.sources import live_state
    rows = list(tabs['injury_case'].rows())
    assert len(rows) > 100
    injured = {r[0] for r in live_state._injuries(engine)}
    assert sum(1 for r in rows if r[1] in injured) >= 0.95 * len(rows)
    assert len({r[1] for r in rows}) == len(rows)


def test_retirement_entries_name_people_and_season_bounds(tabs):
    rows = list(tabs['retirement_entry'].rows())
    assert {r[0] for r in rows} == {'list_18', 'list_30'}
    assert all(r[2] is not None for r in rows)
    bounded = [r for r in rows if r[4] and r[5]]
    assert sum(1 for r in bounded if r[4] < r[5]) >= 0.95 * len(bounded)
