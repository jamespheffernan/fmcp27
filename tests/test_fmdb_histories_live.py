"""Live checks of the history tables through the real tool path (`tools.db_query`).

Skipped unless FM27 is attached (FM_LIVE_REGRESSION=0 skips too). Read-only against the game.
Uses the snapshot under $FMCP_CACHE_DIR. Checked on the Newcastle career (13 Dec 2030); the
people below are chosen by kind, the assertions are structural so the owner may play on.
"""
import os

import pytest

from fm_live_mcp import bridge as bridge_module
from fm_live_mcp.fmdb import tools
from fm_live_mcp.fmdb.tools import FmdbError

GORDON, KOBEL, VITAL, REGEN = 13009, 35795, 370, 136908


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


def q(live, sql):
    bridge, session_id = live
    return tools.db_query(bridge, session_id, sql, max_rows=500)


def test_unnamed_statement_is_refused(live):
    with pytest.raises(FmdbError, match='name the people'):
        q(live, 'SELECT * FROM person_playing_history')
    with pytest.raises(FmdbError, match='name the clubs'):
        q(live, 'SELECT count(*) FROM club_league_history')


def test_starting_history_and_spells(live):
    rows = q(live, f'SELECT year, apps, goals, on_loan, transfer_fee FROM person_playing_history '
                   f'WHERE person_idx = {GORDON} ORDER BY entry')['rows']
    assert len(rows) >= 10 and any(r[3] == 1 for r in rows)          # a loan spell
    assert any(r[4] and r[4] > 0 for r in rows)                      # a recorded fee
    spells = q(live, f'SELECT team_idx, started, job FROM person_career_spells WHERE person_idx = {KOBEL}')['rows']
    assert len(spells) >= 8 and all(r[2] == 'Player' for r in spells)
    staff = q(live, f'SELECT job FROM person_career_spells WHERE person_idx = {VITAL}')['rows']
    assert {'Player'} < {r[0] for r in staff}                        # player and staff jobs
    regen = q(live, f'SELECT count(*) FROM person_career_spells WHERE person_idx = {REGEN}')['rows'][0][0]
    assert regen >= 1


def test_totals_and_injuries(live):
    tot = q(live, f'SELECT total_apps, league_apps, injuries FROM person_career_totals '
                  f'WHERE person_idx = {GORDON}')['rows'][0]
    assert tot[0] >= tot[1] > 0
    inj = q(live, f'SELECT injury_idx, duration_days FROM player_injury_history WHERE person_idx = {GORDON}')['rows']
    assert len(inj) == tot[2] and all(r[0] is not None for r in inj)


def test_squad_join_reads_only_the_squad(live):
    got = q(live, 'SELECT count(DISTINCT t.person_idx) FROM person_career_totals t JOIN person p '
                  'ON p.idx = t.person_idx WHERE p.club_idx = 545 AND p.person_type = 2')
    assert 15 <= got['rows'][0][0] <= 80


def test_club_league_history(live):
    rows = q(live, 'SELECT year, position, teams FROM club_league_history WHERE club_idx = 414')['rows']
    assert len(rows) >= 10 and all(1 <= r[1] <= r[2] for r in rows if r[1])


def test_season_statistics(live):
    rows = q(live, f'SELECT year, scope, team_idx, appearances, goals FROM person_season_statistics '
                   f'WHERE person_idx = {GORDON} ORDER BY career_row, scope')['rows']
    overall = [r for r in rows if r[1] == 5]
    start = q(live, f'SELECT year, team_idx, apps, goals FROM person_playing_history WHERE person_idx = {GORDON} '
                    f'ORDER BY entry')['rows']
    # seasons before the save: the career rows carry the starting history's apps and goals
    assert [tuple(r[0:1]) + tuple(r[2:5]) for r in overall[:len(start)]] == [tuple(r) for r in start]
    assert len(overall) > len(start)                                 # this save's seasons follow
    by = {}
    for year, scope, _, apps, goals in rows:
        by.setdefault(year, {})[scope] = (apps or 0, goals or 0)
    for year, s in by.items():                                       # Overall (Club) = League + Cup + Continental
        if year > start[-1][0] and 1 in s:
            assert s[5][0] == sum(s.get(k, (0, 0))[0] for k in (1, 2, 3)), year


def test_competition_and_award_history(live):
    rows = q(live, 'SELECT season, first_team_idx, second_team_idx FROM competition_history '
                   'WHERE competition_idx = 7 ORDER BY entry')['rows']          # Premier League
    assert len(rows) >= 100 and all(r[1] is not None and r[1] != r[2] for r in rows)
    assert rows[0][0] > rows[-1][0]                                             # newest first
    won = q(live, 'SELECT season, place, person_idx, team_idx FROM award_history WHERE award_idx = 0 ORDER BY entry')['rows']
    assert len(won) >= 50 and won[0][1] == 0
    assert sum(r[2] is not None for r in won) >= 0.95 * len(won)              # 2019-2020: not awarded
    with pytest.raises(FmdbError, match='name the competitions'):
        q(live, 'SELECT count(*) FROM competition_history')


def test_club_transfer_history(live):
    got = q(live, 'SELECT year, direction, person_idx, fee, buying_team_idx, selling_team_idx '
                  'FROM club_transfer_history WHERE club_idx = 414')                        # Newcastle
    # a season the game did not answer makes the club unavailable with a note, never an empty answer
    assert not [n for n in got['notes'] if 'club_transfer_history' in n], got['notes']
    assert 'not_read' not in (got.get('collections') or {}).get('club_transfer_history', {})
    rows = got['rows']
    years = {r[0] for r in rows}
    assert len(years) >= 5 and {'in', 'out'} == {r[1] for r in rows}
    assert all(r[2] is not None and r[3] for r in rows)
    assert all(r[4] == 545 for r in rows if r[1] == 'in')                                # bought by Newcastle
    assert all(r[5] == 545 for r in rows if r[1] == 'out')
