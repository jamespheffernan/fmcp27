"""Club finance ledger and affiliation view against the running game, through the registered db_query
tool function. Values move while the owner plays, so the checks are structural and internal.

Skipped unless a supported FM27 process and the native helper are available."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fmdb_managers_market_live import _live_available  # noqa: E402

pytestmark = pytest.mark.skipif(not _live_available(), reason='FM27 not running or helper missing')


@pytest.fixture(scope='module')
def q():
    from fm_live_mcp.bridge import Bridge
    from fm_live_mcp.fmdb import tools
    bridge = Bridge()
    session = bridge.attach(None)['session_id']

    def run(sql, n=5000):
        return tools.db_query(bridge, session, sql, max_rows=n)['rows']
    yield run
    bridge.detach()


def test_breakdown_has_every_period_and_category(q):
    rows = q('SELECT club_idx, direction, period, count(*), sum(amount IS NULL) FROM club_finance_breakdown '
             'GROUP BY 1, 2, 3')
    assert len(rows) == 8 * len({r[0] for r in rows}) and rows
    by = {(r[1], r[2]): r[3] for r in rows}
    assert by[('income', 'this_month')] >= 15 and by[('expenditure', 'this_month')] >= 15
    assert all(r[4] == 0 for r in rows)
    names = {r[0] for r in q("SELECT DISTINCT category FROM club_finance_breakdown WHERE direction = 'income'")}
    assert {'Gate Receipts', 'TV Revenue', 'Sponsorship', 'Players Sold'} <= names


def test_sponsorship_total_matches_the_breakdown_season(q):
    """The Sponsorship income this season is paid from the listed deals: it is positive whenever deals exist."""
    deals = q('SELECT count(*), sum(total_value) FROM club_sponsorship')[0]
    income = q("SELECT amount FROM club_finance_breakdown WHERE direction = 'income' AND period = 'this_season' "
               "AND category = 'Sponsorship'")
    if deals[0]:
        assert deals[1] > 0 and income and income[0][0] > 0


def test_monthly_series_cover_the_same_months(q):
    rows = q('SELECT series, count(*), min(month), max(month) FROM club_finance_month GROUP BY 1')
    assert {r[0] for r in rows} == {'balance', 'income', 'expenditure', 'wage_expenditure', 'scouting_expenditure',
                                    'transfer_budget_remaining'}
    assert len({(r[1], r[2], r[3]) for r in rows}) == 1


def test_affiliations_are_stored_on_both_clubs(q):
    total, parents, regional = q("SELECT count(*), sum(is_main_club), sum(type = 'Regional Academy') "
                                 "FROM club_affiliation")[0]
    assert total > 10000
    assert total - parents == parents - regional       # every link but Regional Academy is held on both sides
    # the editor enum CAfT has no label for code 21 (406 links on 13 Dec 2030); every other code is labelled
    assert {r[0] for r in q('SELECT DISTINCT type_code FROM club_affiliation WHERE type IS NULL')} <= {21}


def test_same_board_links_lie_in_feeder_groups(q):
    every, grouped = q('SELECT count(*), sum(feeder_group_idx IS NOT NULL) FROM club_affiliation '
                       'WHERE is_main_club AND type_code IN (1, 3) AND same_board')[0]
    assert every and grouped == every


def test_agent_demand_lines_agree_with_the_object(q):
    """The demand lines are the game's own wording of the object's amounts: the wage line shows
    wage_min and wage_max per annum (x 52, in millions with two decimals, truncated or rounded)."""
    rows = q("SELECT d.person_idx, d.wage_min, d.wage_max, d.contract_end, d.line_type, d.line FROM agent_demand d "
             "WHERE d.person_idx IN (SELECT idx FROM person WHERE name = 'Moisés Caicedo' LIMIT 1)")
    if not rows:
        pytest.skip('Moisés Caicedo not in this save')
    wage = [r for r in rows if r[5] and r[5].startswith('Would want a wage of between')]
    assert wage, rows
    _, lo, hi, end, _, line = wage[0]
    for amount in (lo, hi):
        m = amount * 52 / 1e6
        assert any(f'£{v:.2f}M' in line for v in (m, int(m * 100) / 100)), (amount, line)
    year = end[:4]
    assert any(year in r[5] for r in rows if r[5] and r[5].startswith('Would want a contract until')), rows


def test_agent_demand_refuses_a_whole_save_statement(q):
    with pytest.raises(Exception, match='name the people'):
        q('SELECT count(*) FROM agent_demand')
