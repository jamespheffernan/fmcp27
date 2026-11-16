"""Market manager tables against the running game, through the registered db_query tool function.

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
def q():
    from fm_live_mcp.bridge import Bridge
    from fm_live_mcp.fmdb import tools
    bridge = Bridge()
    session = bridge.attach(None)['session_id']

    def run(sql, n=5000):
        r = tools.db_query(bridge, session, sql, max_rows=n)
        return r['rows']
    yield run
    bridge.detach()


def test_every_manager_root_walks(q):
    rows = q('SELECT manager, offset, elements, note FROM market_manager_container')
    assert {r[0] for r in rows} >= {'AGENT_MANAGER', 'CONTRACT_MANAGER', 'PLAYER_BUYIN_MANAGER', 'SCOUT_MANAGER',
                                    'JOB_CENTRE_MANAGER', 'FEEDER_CLUB_MANAGER', 'BOARD_TAKEOVER_MANAGER',
                                    'FINANCE_MANAGER', 'FAN_DAY_MANAGER', 'PITCH_CONDITION_MANAGER',
                                    'TRAINING_CAMP_MANAGER', 'BACKROOM_ADVICE_MANAGER', 'HUMAN_NON_PLAYER_MANAGER'}
    assert not [r for r in rows if r[3]], 'walk errors'
    assert all(r[2] is not None for r in rows if r[1] is not None)


def test_job_adverts_resolve_and_manager_vacancies_are_vacant(q):
    ads = q('SELECT team_idx, club_idx, job_code, job_title, created FROM job_advert')
    assert ads and all(a[0] is not None and a[0] >= 0 and a[1] is not None for a in ads)
    assert all(a[4] for a in ads)
    managers = sorted({a[0] for a in ads if a[2] == 16})
    if managers:
        assert all(a[3] == 'Manager First Team' for a in ads if a[2] == 16)
        held = q(f"SELECT DISTINCT team_idx FROM contract_view WHERE role = 'main' AND job_code = 16 "
                 f"AND team_idx IN ({','.join(map(str, managers))})")
        assert len(held) <= len(managers) // 10        # observed 0 of 50


def test_scout_assignments_equal_the_scout_players_screen(q):
    from fm_live_mcp.fmdb import ui_recipes_more
    from fm_live_mcp.fmdb.engine import Engine
    rows = q('SELECT person_idx, scout_idx, club_idx FROM scout_player_assignment ORDER BY entry')
    engine = Engine.open()           # the screen recipe opens its UI VM over the engine's process
    try:
        screen = ui_recipes_more.scouting(engine, focuses=False)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f'scouting screen not readable: {exc}')
    finally:
        # The recipe's UI VM (ui_recipes_news.open_vm, cached as engine._ui_news_vm) owns a second
        # fm_fast_reader that Engine.close does not stop; left to the garbage collector it outlived
        # the module in complete runs.
        vm = getattr(engine, '_ui_news_vm', None)
        if vm is not None:
            vm.reader.close()
        engine.close()
    names = [p.get('name') for p in screen['scouted']['specifically_scouted_players'] or []]
    if not rows:
        assert not names
        return
    ours = q('SELECT TRIM(COALESCE(NULLIF(p.common_name, \'\'), p.first_name || \' \' || p.second_name)) '
             'FROM scout_player_assignment s JOIN person p ON p.idx = s.person_idx ORDER BY s.entry')
    assert [r[0] for r in ours] == names
    assert len({r[2] for r in rows}) == 1


def test_feeder_groups_are_affiliations_of_their_first_club(q):
    import json
    groups = q('SELECT group_idx, position, club_idx FROM feeder_club_group')
    assert groups and all(g[2] is not None and g[2] >= 0 for g in groups)
    first = {}
    members = []
    for g, pos, club in groups:
        if pos == 0:
            first[g] = club
        else:
            members.append((g, club))
    aff = q(f"SELECT club_idx, item_json FROM club_affiliate WHERE club_idx IN "
            f"({','.join(map(str, sorted(set(first.values()))))})")
    uids = sorted({json.loads(i)['affl']['unique_id'] for _, i in aff})
    by_uid = {u: i for i, u in q(f"SELECT idx, uid FROM club WHERE uid IN ({','.join(map(str, uids))})")}
    linked = {(c, by_uid.get(json.loads(i)['affl']['unique_id'])) for c, i in aff}
    listed = sum((first[g], club) in linked for g, club in members)
    assert listed >= 0.9 * len(members)          # observed 182 of 193


def test_other_tables_resolve_their_records(q):
    for sql in ('SELECT club_idx FROM board_takeover_entry', 'SELECT team_idx FROM training_camp',
                'SELECT club_idx FROM backroom_advice_entry', 'SELECT club_idx FROM facility_upgrade',
                'SELECT person_idx FROM contract_manager_entry'):
        rows = q(sql)
        assert all(r[0] is None or r[0] >= 0 for r in rows), sql
    human = q('SELECT person_idx, class FROM human_non_player')
    assert human and all(h[0] is not None and h[1] == 'db::HUMAN_NON_PLAYER' for h in human)
