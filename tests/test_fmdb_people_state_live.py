"""People-state tables against the running game (reference save: Newcastle, 13 Dec 2030).

Skipped unless a supported FM27 process and the native helper are available."""
import json
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


def test_kind_titles_come_from_the_dispatch_and_the_language_file(engine):
    from fm_live_mcp.fmdb.sources import people_state as PS
    titles = PS.promise_kind_titles(engine)
    assert titles[1] == (491277, 'Fair increase in playing time')
    assert titles[25] == (377014, 'Find loan move for player')
    assert titles[7] == (None, None) and titles[9] == (None, None)
    assert sum(1 for t in titles.values() if t[0]) >= 100


def test_promises_match_their_interaction_items(engine):
    from fm_live_mcp.fmdb.sources import people_state as PS
    rows = PS._promise_rows(engine)
    assert rows, 'the reference save has active promises'
    for r in rows:
        assert r[5] is not None and r[7] is not None, 'every screen row has one stored item'
        assert r[8] == r[6], 'screen title equals the dispatch title of the item kind'
        assert r[10] <= r[11]


def test_attribute_history_newest_snapshot_equals_the_editor_getter(engine):
    from fm_live_mcp.fmdb import knowledge_codes as K
    from fm_live_mcp.fmdb.sources import people_state as PS, _common as C
    promises = PS._promise_rows(engine)
    if not promises:
        pytest.skip('no promised player to sample')
    player = promises[0][3]
    rows, notes = PS._attribute_batch(engine)([player])
    assert rows, notes
    newest = bytes.fromhex(max(rows, key=lambda r: r[1])[5])
    record = C.live(engine, 'people').pointers[player]
    for f in K.FIELDS:
        assert engine.get_property(record, f['code_100']).value == newest[f['field_id']], f['name']
    assert json.loads(rows[0][7]).keys() == {f['column'] for f in K.FIELDS}


def test_squad_hierarchy_matches_the_dynamics_tool(engine):
    from fm_live_mcp.fmdb.sources import people_state as PS
    from fm_live_mcp.fmdb import ui_recipes_more as M
    from fm_live_mcp.fmdb.ui_vm import UiHandlerVM
    rows = PS._hierarchy_rows(engine)
    if not rows:
        pytest.skip('no human-managed team')
    vm = UiHandlerVM(engine.memory, engine.base, engine.image, file_resolver=engine.file_resolver(), rng='copy')
    tool = M.squad_dynamics(vm)

    def ids(v):
        return sorted((x.get('id') if isinstance(x, dict) else x) & 0xFFFFFF for x in v)
    for tier, key in (('team_leader', 'team_leaders'), ('highly_influential', 'highly_influential'),
                      ('other', 'other')):
        assert sorted(r[2] for r in rows if r[3] == tier) == ids(tool[key]), tier
    assert sum(1 for r in rows if r[3] == 'influential') == tool['influential_count']
    for r in rows:
        assert r[5] is not None, 'every listed player has a stored influence'
        if not r[10]:
            assert r[6] == r[3], 'a fresh stored list gives the tier the screen shows'


def test_social_groups_match_the_dynamics_tool(engine):
    from fm_live_mcp.fmdb.sources import people_state as PS
    from fm_live_mcp.fmdb import ui_recipes_more as M
    from fm_live_mcp.fmdb.ui_vm import UiHandlerVM
    rows = PS._social_rows(engine)
    if not rows:
        pytest.skip('no human-managed team')
    vm = UiHandlerVM(engine.memory, engine.base, engine.image, file_resolver=engine.file_resolver(), rng='copy')
    groups = M.squad_dynamics(vm)['social_groups']
    for name in ('core', 'secondary_1', 'secondary_2', 'other'):
        want = sorted((x.get('id') if isinstance(x, dict) else x) & 0xFFFFFF for x in groups.get(name) or [])
        assert sorted(r[5] for r in rows if r[3] == name) == want, name
        assert all(r[9] for r in rows if r[3] == name), 'each group has its reasons text'


def test_concerns_equal_the_hand_built_decoder(engine):
    from fm_live_mcp import player_concern_history_source as S
    from fm_live_mcp.fmdb.sources import people_state as PS, _common as C
    players = [r[3] for r in PS._promise_rows(engine)] or [13248]
    rows, _ = PS._concern_batch(engine)(players)
    compared = 0
    for p in players:
        got = S.inspect(engine.read, engine.base, C.live(engine, 'people').pointers[p] - 0x388, 'actual')
        mine = [r for r in rows if r[0] == p]
        if got['records'] is None:
            # The hand-built decoder answers only in the player's current TEAM/CLUB context; a player
            # out on loan (main contract at another club than the team he is with: 47009 on 21 Jan
            # 2031) is outside it. The table reads the main contract's ring either way.
            assert got['state'] == 'main_contract_outside_current_CLUB_context', (p, got['state'])
            continue
        compared += 1
        assert len(mine) == (got['native_ring_entry_count'] or 0)
        for m, g in zip(mine, got['records']):
            rec = g['record']
            assert (m[3], m[6], m[7], m[5]) == (rec['stored_start_date']['value'], rec['native_reason_code'],
                                                rec['native_stored_category_code'], int(rec['matches_native_unset_end_date']))
    assert compared, 'no player with a promise is in his current club context: nothing was compared'


def test_happiness_reasons_equal_the_player_status_tool(engine):
    from fm_live_mcp.fmdb import ui_recipes_person as RP
    from fm_live_mcp.fmdb.sources import people_state as PS
    from fm_live_mcp.fmdb.ui_vm import UiHandlerVM
    players = [r[3] for r in PS._promise_rows(engine)][:2]
    if not players:
        pytest.skip('no promised player to sample')
    rows, notes = PS._happiness_batch(engine)(players)
    vm = UiHandlerVM(engine.memory, engine.base, engine.image, file_resolver=engine.file_resolver(), rng='copy')
    for p in players:
        f = RP.player_status(vm, (1 << 24) | p)
        f = f.get('fields', f)
        want = [x['name'] for x in f['happiness_positives'] if x.get('2   ') != -1]
        assert [r[4] for r in rows if r[0] == p and r[2] == 'positive'] == want
        assert [r[4] for r in rows if r[0] == p and r[2] == 'negative'] == [x['name'] for x in f['happiness_negatives']]
        assert [r[4] for r in rows if r[0] == p and r[2] == 'playing_time'] == [f['playing_time_happiness']]
