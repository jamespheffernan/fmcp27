"""Offline tests for the club finance ledger and affiliation view (no game)."""
import sqlite3

from fm_live_mcp.fmdb.sources import market_state as M


def test_breakdown_rows_shape_every_period():
    item = {'qvJ6': '£425K', 'id  ': 0, 'Zf6i': -5, 'name': 'Gate Receipts', 'iSzq': 3, 'ptvl': 425140}
    values = {name: [item] for name in M.BREAKDOWN_KEYS}
    rows = M.breakdown_rows(414, values)
    assert len(rows) == 8
    assert rows[0] == (414, 'income', 'this_month', 0, 'Gate Receipts', 425140, 3, -5, '£425K')
    assert {(r[1], r[2]) for r in rows} == {(d, p) for d in ('income', 'expenditure') for p, _ in M.PERIODS}


def test_month_rows_and_unavailable_values_are_skipped():
    values = {'balance': [{'H gt': '2025-12-01', 'dEkT': -35279380}], 'income': object()}
    assert M.month_rows(1, values) == [(1, 'balance', '2025-12-01', -35279380)]


def test_sponsorship_and_debt_dates():
    s = M.sponsorship_rows(2, {'sponsorships': [
        {'pd6h': '£25M', '6sdl': '5 Years', 'Pced': {'date': '2034-05-27', 'low': 25}, 'name': 'Main Kit',
         'ptvl': 125000000},
        {'pd6h': '£5M', '6sdl': '-', 'Pced': '1900-01-01', 'name': 'Partners', 'ptvl': 1}]})
    assert s[0] == (2, 0, 'Main Kit', '£25M', '5 Years', '2034-05-27', 125000000)
    assert s[1][5] is None
    d = M.debt_rows(2, {'debts': [{'namf': 'Mortgage Loan', 'ptvl': 40805050, 'AZI2': '£40.8M', 'hmEy': '£11.17M',
                                   'KWKt': '£586K', ' juQ': '£2.31M', 'PcSd': {'date': '2025-12-01'},
                                   'Pced': '2032-11-29'}]})
    assert d == [(2, 0, 'Mortgage Loan', 40805050, '£40.8M', '£11.17M', '£586K', '£2.31M', '2025-12-01',
                  '2032-11-29')]


def test_tables_declare_own_club_policy():
    names = {t.name: t for t in M.tables(object())}
    assert set(names) == {'club_finance_breakdown', 'club_finance_month', 'club_sponsorship', 'club_debt_loan',
                          'club_affiliation_detail', 'agent_demand'}
    demand = names.pop('agent_demand')
    assert demand.manager['scope'] == 'public' and demand.columns[0].name == 'person_idx'
    assert demand.mode == 'lazy' and demand.invalidation == 'append'
    for t in names.values():
        assert t.manager['scope'] == 'own_club' and t.manager['own_club_column'] == 'club_idx'
        assert t.columns[0].name == 'club_idx'


def test_affiliation_view_runs_on_a_tiny_schema():
    template = M.views(None)['club_affiliation'][1]
    sql = template.replace('{club.Cafl}', 'Cafl')
    con = sqlite3.connect(':memory:')
    con.execute('CREATE TABLE club(idx INTEGER, uid INTEGER, Cafl TEXT)')
    con.execute('CREATE TABLE feeder_club_group(group_idx INTEGER, position INTEGER, club_idx INTEGER)')
    item = ('{"affl":{"unique_id":20},"ismc":true,"type":3,"stdt":"2022-05-18","endt":"1900-01-01","yfee":0,'
            '"smbo":true,"fri%":5}')
    con.execute("INSERT INTO club VALUES (0, 10, ?), (1, 20, '[]')", (f'[{item}]',))
    con.execute('INSERT INTO feeder_club_group VALUES (7, 0, 0), (7, 1, 1)')
    con.execute(f'CREATE VIEW club_affiliation AS {sql}')
    row = con.execute('SELECT club_idx, affiliated_club_idx, side, type, start_date, end_date, same_board, '
                      'friendly_chance_percent, feeder_group_idx FROM club_affiliation').fetchone()
    assert row == (0, 1, 'parent', 'Feeder Team', '2022-05-18', None, 1, 5, 7)


def test_affiliation_enum_matches_the_editor_catalog():
    import pytest
    try:
        from fm_live_mcp.fmdb import catalog
        cat = catalog.load_catalog()
    except Exception as exc:  # noqa: BLE001  (editor.fmf not installed)
        pytest.skip(f'editor catalog unavailable: {exc}')
    scopes = {s.scope: s.field for s in cat.iter_fields()}
    f = scopes['club/Cafl/type']
    enum = f.enum or cat.enums.get(f.enum_ref)
    assert {int(k): v for k, v in enum.items()} == M.AFFILIATION_TYPES
    for _, code, label in M.AFFILIATION_TERMS:
        assert scopes[f'club/Cafl/{code}'].name == label


def test_affiliation_detail_rows():
    item = {'16  ': {'110 ': 28, 'dref': 3 << 24 | 1234}, 'PcSd': '2022-05-12', 'ERNL': 0,
            'GFy ': 'A local partnership in which players are loaned.', 'Z13B': ['a', 'b']}
    assert M.affiliation_detail_rows(39, {'affiliations': [item]}) == [
        (39, 0, 1234, '2022-05-12', 'A local partnership in which players are loaned.', 0, 'a\nb')]


def test_agent_demand_rows_shape(monkeypatch):
    got = {31944: {'fields': {'agent_idx': 100708, 'person_idx': 31944, 'player_club_idx': 357, 'fee_min': 180166140,
                              'fee_max': 241444840, 'wage_min': 417563, 'wage_max': 512239},
                   'dates': {'offer_date': '2030-12-13', 'contract_end': '2033-06-30'}, 'interest': 'Interested',
                   'renewal': False, 'agent_idx': 100708, 'random_draws': 379,
                   'lines': [{'fPst': 4, '3mae': 'I believe Chelsea will want ...', 'gLl5': 0, 'H5oC': 0},
                             {'fPst': 5, '3mae': 'Would want a contract until 6/30/2033.', 'gLl5': 0, 'H5oC': 0}]},
           13009: {'unavailable': 'no demands'}}
    monkeypatch.setattr(M, 'managed_clubs', lambda engine: [414])
    monkeypatch.setattr(M, 'compute_agent_demands', lambda engine, people, club: got)
    rows, notes = M.agent_demand_rows(None, [31944, 13009], '2030-12-13')
    assert notes == ['13009: no demands']
    assert rows[1] == (31944, 414, 2, 'Interested', 0, 100708, 357, 180166140, 241444840, 417563, 512239,
                       '2033-06-30', 379, 1, 5, 'Would want a contract until 6/30/2033.', 0, 0, '2030-12-13')
    table = {t.name: t for t in M.tables(object())}['agent_demand']
    assert len(table.columns) == len(rows[0])
