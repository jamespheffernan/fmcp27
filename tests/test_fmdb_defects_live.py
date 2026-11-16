"""Live checks of the adviser's verification defects (round 6) through the real tool path.

Skipped unless FM27 is attached (FM_LIVE_REGRESSION=0 skips too). Read-only against the game.
Checked on the Newcastle career (13 Dec 2030); assertions are structural so the owner may play on.
"""
import os

import pytest

from fm_live_mcp import bridge as bridge_module
from fm_live_mcp.fmdb import tools

NEWCASTLE_CLUB = 414


@pytest.fixture(scope='module')
def live():
    if os.environ.get('FM_LIVE_REGRESSION') == '0':
        pytest.skip('FM_LIVE_REGRESSION=0')
    bridge = bridge_module.Bridge()
    if not bridge.helper.is_file():
        pytest.skip('native helper not built')
    try:
        session_id = bridge.attach()['session_id']
    except Exception as exc:   # no FM27 process, permission, or unsupported build
        pytest.skip(f'FM27 is not attached: {exc}')
    yield bridge, session_id


def q(live, sql, view='full'):
    bridge, session_id = live
    return tools.db_query(bridge, session_id, sql, max_rows=500, view=view)


def own_club(live):
    return q(live, 'SELECT club_idx FROM _managed')['rows'][0][0]


def test_squad_status_is_the_contracts_agreed_playing_time(live):
    """player_view and contract_view squad_status: FULL_CONTRACT +0x54, as playing_time.decode
    (the player-status screen tool) reads it, for every player of the user's club."""
    from fm_live_mcp import playing_time
    club = own_club(live)
    rows = q(live, 'SELECT v.idx, v.squad_status, k.squad_status FROM player_view v JOIN contract_view k '
                   f"ON k.person_idx = v.idx AND k.role = 'main' WHERE v.club_idx = {club}")['rows']
    assert rows and all(a is not None and a == b for _, a, b in rows), rows
    labels = {v[2] for v in playing_time.LABELS.values()}
    assert {a for _, a, _ in rows} <= labels
    bridge, session_id = live
    sample = [f'person:{r[0]}' for r in rows[:4]]
    got = playing_time.get_player_playing_time(bridge, session_id, sample)['players']
    assert [p['agreed_playing_time']['title'] for p in got] == [r[1] for r in rows[:4]]
    # manager view: own club shown, another club's withheld
    mine = q(live, f'SELECT count(*), count(squad_status) FROM m_player_view WHERE club_idx = {club}', 'manager')
    assert mine['rows'][0][0] == mine['rows'][0][1] > 0
    other = q(live, f'SELECT count(squad_status) FROM m_player_view WHERE club_idx = 1', 'manager')
    assert other['rows'][0][0] == 0


def test_is_injured_follows_the_days_still_out(live):
    """player_view.is_injured is the game's rule for a player who is out: his injuries leave
    days still out, which is also when the game's condition getter returns -1 (ORACLE.md, M1).
    Until 0.174.1 it came from Phij, a table that is empty in a running career, and was 0 for
    every player."""
    rows = q(live, 'SELECT is_injured, injury_days_remaining > 0, condition = -1, count(*) FROM player_view '
                   'GROUP BY 1, 2, 3')['rows']
    assert all(injured == out == hidden for injured, out, hidden, _ in rows), rows
    assert sum(n for injured, _, _, n in rows if injured) > 0, rows      # a career always has someone out


def test_fresh_read_and_base_table_agree_with_the_view_on_is_injured(live):
    """fm_db_read answers is_injured for a player as player_view does, and the base table no longer
    has a column of that name that is false for everyone (the catalog key Phij is
    starting_injury_listed there)."""
    bridge, session_id = live
    rows = q(live, 'SELECT idx, is_injured, injury_days_remaining FROM player_view WHERE club_idx = '
                   '(SELECT club_idx FROM _managed) ORDER BY is_injured DESC, idx LIMIT 6')['rows']
    assert rows
    read = tools.db_read(bridge, session_id, 'player', [r[0] for r in rows], ['is_injured'])
    for (idx, injured, days), record in zip(rows, read['records']):
        assert record['idx'] == idx and set(record['values']) == {'is_injured'}, record
        assert record['values']['is_injured'] == bool(injured) == (days > 0), (record, injured, days)
    both = tools.db_read(bridge, session_id, 'player', [rows[0][0]], ['is_injured', 'injury_days_remaining'])
    assert set(both['records'][0]['values']) == {'is_injured', 'injury_days_remaining'}
    with pytest.raises(Exception, match='no such column'):
        q(live, 'SELECT is_injured FROM player LIMIT 1')
    assert q(live, 'SELECT count(*) FROM player WHERE starting_injury_listed = 1')['rows'][0][0] == 0


def test_person_index_references_reach_the_hand_built_player_tools(live):
    bridge, session_id = live
    club = own_club(live)
    idx, name = q(live, f'SELECT idx, name FROM player_view WHERE club_idx = {club} LIMIT 1')['rows'][0]
    out = bridge.get_player(session_id, f'person:{idx}')
    assert name in (out['player'].get('name'), out['player'].get('display_name')), out['player']
    with pytest.raises(bridge_module.BridgeError, match='Unknown or expired player reference'):
        bridge.get_player(session_id, 'person:999999999')


def test_managed_is_readable_in_the_manager_view(live):
    full = q(live, 'SELECT team_idx, club_idx, coach FROM _managed')['rows']
    assert q(live, 'SELECT team_idx, club_idx, coach FROM _managed', 'manager')['rows'] == full
    assert q(live, 'SELECT team_idx, club_idx, coach FROM m__managed', 'manager')['rows'] == full


def test_staff_job_is_the_hand_built_contract_job_title(live):
    """staff_view.job equals staff_jobs.decode (contract +0x26 converted on the contract team's
    type) for every staff member of the user's club whose contract that decoder reads."""
    import struct
    from fm_live_mcp import staff_jobs
    club = own_club(live)
    rows = q(live, f'SELECT idx, job FROM staff_view WHERE club_idx = {club}')['rows']
    bridge, session_id = live
    eng = tools.engine_for(bridge, session_id)
    ptrs, _ = eng.table_entries('people')

    def u64(a):
        return struct.unpack('<Q', eng.read(a, 8))[0]
    checked = 0
    for idx, job in rows:
        contract = u64(ptrs[idx] - 0x98)
        try:
            d = staff_jobs.decode(eng.read, eng.base, contract, u64(contract), u64(contract + 0x10))
        except ValueError:
            continue
        assert d['title'] == job, (idx, job, d)
        checked += 1
    assert checked >= len(rows) * 0.8 and any(job for _, job in rows)


def test_finance_breakdown_percent_is_of_the_operating_total(live):
    """club_finance_breakdown.percent_of_operating_total: income rows of the turnover (all income
    less Players Sold and Investments), expenditure rows of all expenditure less Transfer
    Expenditure; the screen truncates."""
    club = own_club(live)
    rows = q(live, 'SELECT direction, period, category, amount, percent_of_operating_total FROM '
                   f"club_finance_breakdown WHERE club_idx = {club} AND period IN ('this_month', 'this_season')")['rows']
    excluded = {'income': {'Players Sold', 'Investments'}, 'expenditure': {'Transfer Expenditure'}}
    groups = {}
    for d, p, cat, amount, pct in rows:
        groups.setdefault((d, p), []).append((cat, amount, pct))
    assert groups
    for (d, p), items in groups.items():
        base = sum(a for c, a, _ in items if c not in excluded[d])
        if base <= 0:
            continue
        for cat, amount, pct in items:
            assert pct == amount * 100 // base, (d, p, cat, amount, pct, base)


def test_history_text_columns_hold_values(live):
    """club_transfer_history keeps only selling_team_text (filled where no selling team) and
    competition_history only missing_history (wartime seasons of a cup)."""
    club = own_club(live)
    t = q(live, f'SELECT * FROM club_transfer_history WHERE club_idx = {club}')
    assert 'buying_team_text' not in t['columns']
    rows = [dict(zip(t['columns'], r)) for r in t['rows']]
    assert rows and all((r['selling_team_text'] is None) == (r['selling_team_idx'] is not None) for r in rows)
    c = q(live, "SELECT * FROM competition_history WHERE competition_idx IN (SELECT idx FROM competition "
                "WHERE name IN ('Emirates FA Cup', 'FA Cup', 'DFB-Pokal'))")
    assert 'stage_name' not in c['columns']
    assert any(r[c['columns'].index('missing_history')] for r in c['rows'])


def test_squad_happiness_skips_virtual_players_and_gives_reasons(live):
    """fm_get_squad_happiness: roster VIRTUAL_PLAYER placeholders are listed as skipped, not failed,
    and every unhappy player carries the Happiness panel's lines (player_happiness_reason)."""
    from fm_live_mcp.fmdb import ui_recipes_screens as screens, ui_tools
    bridge, session_id = live
    out = ui_tools.recipe_read(bridge, session_id, 'squad_happiness', screens.squad_happiness,
                               {'club': None, 'reasons': 'unhappy'}, True, pass_read=True)
    result = out['result']
    ui_tools._happiness_reasons(bridge, session_id, result)
    assert result['failed'] == [], result['failed']
    unhappy = [p for p in result['players'] if p['unhappy']]
    assert all(p.get('reasons') for p in unhappy), [p['name'] for p in unhappy if not p.get('reasons')]
    assert all(r['sign'] in ('positive', 'negative', 'playing_time') for p in unhappy for r in p['reasons'])


def test_transfer_offer_roles_match_the_transfer_history_screen(live):
    """transfer_offer_view.buying_team_idx / selling_team_idx (team +0x40 / +0x50 of full transfers
    and loans; for loans the borrowing and the loaning team) agree with club_transfer_history
    (CLUB_UI_HANDLER PTin/PTou) on every transfer that is both an offer and a history row."""
    club = own_club(live)
    rows = q(live, "SELECT h.person_idx, h.buying_team_idx, h.selling_team_idx, "
                   "EXISTS (SELECT 1 FROM transfer_offer_view o WHERE o.person_idx = h.person_idx "
                   "AND o.buying_team_idx = h.buying_team_idx AND o.selling_team_idx = h.selling_team_idx), "
                   "EXISTS (SELECT 1 FROM transfer_offer_view o WHERE o.person_idx = h.person_idx "
                   "AND o.buying_team_idx = h.selling_team_idx AND o.selling_team_idx = h.buying_team_idx) "
                   f"FROM club_transfer_history h WHERE h.club_idx = {club} AND h.selling_team_idx IS NOT NULL")['rows']
    # How many transfers are both an offer the game still holds and a history row moves with the
    # career (28 of 139 on 18 Jan 2031: 19 of season 2025, 9 of 2030), so the count is not asserted:
    # some must be compared, and none may have the roles the other way round.
    assert rows, 'the club has no transfer history rows with a selling team'
    matched = sum(r[3] for r in rows)
    assert matched, 'no transfer is both an offer and a history row: nothing was compared'
    assert not any(r[4] and not r[3] for r in rows)       # never the other way round
