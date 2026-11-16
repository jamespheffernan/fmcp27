"""Adversarial non-interference tests for the manager view.

Two snapshots hold the same players and the same public data and differ in every value the
manager view must hide: CA/PA, hidden attributes, raw reputation, personality, the stored
attribute values behind unknown and range cells, and, for players of other clubs, wage,
contract, value and condition. The manager's knowledge is the same for both. A statement that
goes through the manager view must return the same columns, the same rows and the same row
order on both, and must ask for knowledge of the same players (the on-demand need set), or
the statement would tell the two saves apart. Indexes on hidden columns are present in both
snapshots so that a scan in index order would show.
"""
import importlib.util
import itertools
import random
import sqlite3
from pathlib import Path

import pytest

from fm_live_mcp.fmdb import knowledge_store as ks
from fm_live_mcp.fmdb import manager_view as mv

_spec = importlib.util.spec_from_file_location('manager_view_base', Path(__file__).with_name('test_fmdb_manager_view.py'))
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

N = 40                       # players 1..N; 1..4 own club, 5..12 scouted, the rest strangers
OWN, SCOUTED = range(1, 5), range(5, 13)
HIDDEN_INDEXES = ('CREATE INDEX hidden_ca ON player(current_ability)',
                  'CREATE INDEX hidden_pa ON player(potential_ability, idx)',
                  'CREATE INDEX hidden_value ON player(transfer_value)',
                  'CREATE INDEX hidden_wage ON person(wage)',
                  'CREATE INDEX hidden_expiry ON person(contract_expires, idx)')


def knowledge_kind(idx):
    if idx in OWN:
        return 'exact'
    if idx in SCOUTED:
        return 'range'
    return 'unknown' if idx % 5 else 'unavailable'


def build(path, seed):
    """Snapshot whose public data does not depend on `seed` and whose hidden data does."""
    rng = random.Random(seed)
    base.make_snapshot(path, people=range(1, N + 1))
    con = sqlite3.connect(path)
    for idx in range(1, N + 1):
        own = idx in OWN
        club = 10 if own else 11
        # public: name, birth date, nationality, club; knowledge cells decide the 1..20 attributes
        con.execute('UPDATE person SET first_name=?, date_of_birth=?, nationality=?, club=? WHERE idx=?',
                    (f'P{idx:02d}', f'{1995 + idx % 12}-0{1 + idx % 9}-1{idx % 9}', idx % 6, club, idx))
        # hidden everywhere: CA/PA, consistency, reputation, personality, 1..100 attributes
        con.execute('UPDATE player SET current_ability=?, potential_ability=?, consistency=?, current_reputation=?, '
                    'acceleration_pdac=? WHERE idx=?',
                    (rng.randrange(1, 200), rng.randrange(1, 200), rng.randrange(1, 21), rng.randrange(1, 10000),
                     rng.randrange(1, 101), idx))
        con.execute('UPDATE person SET adaptability=? WHERE idx=?', (rng.randrange(1, 21), idx))
        # stored 1..20 attributes: fixed for own players (their cells are exact and say the same),
        # hidden behind range/unknown cells for everyone else
        if not own:
            con.execute('UPDATE player SET passing=?, acceleration_pacc=? WHERE idx=?',
                        (rng.randrange(1, 21), rng.randrange(1, 21), idx))
            # own-club-only fields of other clubs' players
            con.execute('UPDATE person SET wage=?, contract_expires=?, squad_status=? WHERE idx=?',
                        (rng.randrange(500, 400000), f'20{rng.randrange(31, 40)}-06-30', rng.choice((1, 2, 3)), idx))
            con.execute('UPDATE player SET transfer_value=?, overall_physical_condition=?, goalkeeper=? WHERE idx=?',
                        (rng.randrange(10_000, 90_000_000), rng.randrange(40, 101), rng.randrange(1, 21), idx))
        else:
            con.execute('UPDATE player SET passing=16, acceleration_pacc=14 WHERE idx=?', (idx,))
    con.execute('UPDATE team SET reputation=? WHERE idx=11', (rng.randrange(1, 10000),))
    # a rival club's finances: own-club columns of the core club table (m_club)
    con.execute('CREATE TABLE club(idx INTEGER PRIMARY KEY, name TEXT, cash_balance INTEGER, wage_budget INTEGER, '
                'reputation INTEGER)')
    con.execute('INSERT INTO club VALUES (10, ?, 50000000, 2000000, 7000), (11, ?, ?, ?, ?)',
                ('Club A', 'Club B', rng.randrange(-90_000_000, 400_000_000), rng.randrange(100_000, 5_000_000),
                 rng.randrange(1, 10000)))
    add_collections(con, rng)
    for sql in HIDDEN_INDEXES + COLLECTION_HIDDEN_INDEXES:
        con.execute(sql)
    con.execute('ANALYZE')
    con.commit()
    con.close()


COLLECTION_HIDDEN_INDEXES = ('CREATE INDEX hidden_loan_fee ON contract(loan_fee, idx)',
                             'CREATE INDEX hidden_clause_amount ON contract_clause(amount)',
                             'CREATE INDEX hidden_offer_amount ON transfer_offer(amount_raw)',
                             'CREATE INDEX hidden_balance ON club(cash_balance)')
OWN_CLUB, OTHER_CLUB = 10, 11


def _policy(con, table, module, policy, views=()):
    import json
    con.execute('INSERT INTO _source_tables(table_name, module, status, manager_scope, manager_json, views_json) '
                'VALUES (?, ?, ?, ?, ?, ?)', (table, module, 'ready', policy['scope'], json.dumps(policy),
                                              json.dumps({v: '' for v in views})))
    con.execute('INSERT INTO _tables VALUES (?, ?, 0, ?)', (table, f'collection:{module}', '{}'))


def add_collections(con, rng):
    """Collection tables of every policy kind, core club/team links and `_managed`, with the rows
    and columns the manager may see equal on both saves and everything else drawn from `rng`."""
    from fm_live_mcp.fmdb import sources
    con.executescript(sources.SOURCE_SQL)
    con.execute('CREATE TABLE _managed(team_idx INTEGER, club_idx INTEGER, coach TEXT)')
    con.execute("INSERT INTO _managed VALUES (10, 10, 'Coach')")
    con.execute('ALTER TABLE team ADD COLUMN club_idx INTEGER')
    con.execute('UPDATE team SET club_idx = idx')
    con.executemany('INSERT INTO _fields(table_name, column_name, code, record_type, references_table) VALUES '
                    '(?, ?, ?, ?, ?)', [('team', 'club_idx', 'c:club_idx', 'team', 'club'),
                                        ('club', 'name', 'Cnam', 'club', None),
                                        ('club', 'cash_balance', 'Cbal', 'club', None),
                                        ('club', 'wage_budget', 'Cwgb', 'club', None),
                                        ('club', 'reputation', 'Crep', 'club', None)])
    con.executemany('INSERT INTO _tables VALUES (?, ?, 2, ?)', [('club', 'club', '{}'), ('team', 'team', '{}')])
    own = lambda **kw: dict(scope='own_club', **kw)   # noqa: E731
    # public: fixtures (identical on both saves), a statement-dependent history table
    con.execute('CREATE TABLE fixture(idx INTEGER PRIMARY KEY, date TEXT, home_team_idx INTEGER, '
                'away_team_idx INTEGER, home_goals INTEGER, away_goals INTEGER)')
    con.executemany('INSERT INTO fixture VALUES (?, ?, ?, ?, ?, ?)',
                    [(i, f'2030-0{1 + i % 9}-1{i % 9}', 10 + i % 2, 11 - i % 2, i % 4, i % 3) for i in range(12)])
    con.execute('CREATE VIEW fixture_view AS SELECT f.idx, f.date, ht."long_name" AS home_team, '
                'at."long_name" AS away_team, f.home_goals, f.away_goals FROM fixture f '
                'LEFT JOIN team ht ON ht.idx = f.home_team_idx LEFT JOIN team at ON at.idx = f.away_team_idx')
    _policy(con, 'fixture', 'fixture_tables', {'scope': 'public'}, ['fixture_view'])
    con.execute('CREATE TABLE career(idx INTEGER PRIMARY KEY, person_idx INTEGER, entry INTEGER, team_idx INTEGER)')
    con.executemany('INSERT INTO career VALUES (?, ?, ?, ?)', [(i, 1 + i % N, i // N, 10 + i % 2) for i in range(60)])
    _policy(con, 'career', 'histories', {'scope': 'public'})
    # own club with public columns: contracts (loan fee withheld on other clubs' rows)
    con.execute('CREATE TABLE contract(idx INTEGER PRIMARY KEY, person_idx INTEGER, role TEXT, club_idx INTEGER, '
                'team_idx INTEGER, weekly_wage INTEGER, expires_date TEXT, squad_number INTEGER, loan_fee INTEGER)')
    for idx in range(1, N + 1):
        mine = idx in OWN
        con.execute('INSERT INTO contract VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (idx, idx, 'main', OWN_CLUB if mine else OTHER_CLUB, 10 if mine else 11, 1000 * idx,
                     f'20{30 + idx % 7}-06-30', idx % 30, 5000 if mine else rng.randrange(1, 10_000_000)))
    con.execute('CREATE VIEW contract_view AS SELECT k.idx, k.person_idx, pe."first_name" AS person_name, '
                'k.club_idx, t."long_name" AS team_name, k.weekly_wage, k.expires_date, k.loan_fee, '
                'k.loan_fee * 2 AS double_fee FROM contract k LEFT JOIN person pe ON pe.idx = k.person_idx '
                'LEFT JOIN team t ON t.idx = k.team_idx')
    _policy(con, 'contract', 'contracts', own(own_club_column='club_idx', public_columns=[
        'idx', 'person_idx', 'role', 'club_idx', 'team_idx', 'weekly_wage', 'expires_date', 'squad_number']),
        ['contract_view'])
    # own rows only: clauses (through the contract), offers, inbox, club finance
    con.execute('CREATE TABLE contract_clause(idx INTEGER PRIMARY KEY, contract_idx INTEGER, kind_code INTEGER, '
                'amount INTEGER)')
    rows = [(i, c, 1, 100 * i) for i, c in enumerate(OWN)]
    rows += [(len(rows) + j, 5 + rng.randrange(0, N - 5), rng.randrange(1, 9), rng.randrange(1, 10 ** 7))
             for j in range(rng.randrange(5, 30))]
    con.executemany('INSERT INTO contract_clause VALUES (?, ?, ?, ?)', rows)
    _policy(con, 'contract_clause', 'contracts', own(own_club_via='contract.club_idx'))
    con.execute('CREATE TABLE transfer_offer(idx INTEGER PRIMARY KEY, person_idx INTEGER, team1_idx INTEGER, '
                'team1_club_idx INTEGER, team2_idx INTEGER, team2_club_idx INTEGER, amount_raw INTEGER)')
    rows = [(0, 2, 10, OWN_CLUB, 11, OTHER_CLUB, 1_000_000), (1, 7, 11, OTHER_CLUB, 10, OWN_CLUB, 2_000_000)]
    rows += [(2 + j, rng.randrange(5, N), 11, OTHER_CLUB, 11, OTHER_CLUB, rng.randrange(1, 10 ** 8))
             for j in range(rng.randrange(3, 20))]
    con.executemany('INSERT INTO transfer_offer VALUES (?, ?, ?, ?, ?, ?, ?)', rows)
    con.execute('CREATE VIEW transfer_offer_view AS SELECT o.idx, o.person_idx, t1."long_name" AS team1, '
                'o.amount_raw FROM transfer_offer o LEFT JOIN team t1 ON t1.idx = o.team1_idx')
    _policy(con, 'transfer_offer', 'live_state', own(own_club_columns=['team1_club_idx', 'team2_club_idx']),
            ['transfer_offer_view'])
    con.execute('CREATE TABLE news_item(idx INTEGER PRIMARY KEY, source TEXT, subject INTEGER)')
    rows = [(0, 'inbox', 1), (1, 'inbox', 2)] + [(2 + j, 'world', rng.randrange(1, 999))
                                                 for j in range(rng.randrange(2, 15))]
    con.executemany('INSERT INTO news_item VALUES (?, ?, ?)', rows)
    _policy(con, 'news_item', 'live_state', own(own_club_rule="source = 'inbox'"))
    con.execute('CREATE TABLE club_finance(idx INTEGER PRIMARY KEY, balance INTEGER, wage_bill INTEGER)')
    con.execute('INSERT INTO club_finance VALUES (10, 1, 2), (11, ?, ?)', (rng.randrange(1, 10 ** 9), rng.randrange(1, 9)))
    _policy(con, 'club_finance', 'club_finance', own(own_club_column='idx'))
    # never: internal state
    con.execute('CREATE TABLE engine_state(idx INTEGER PRIMARY KEY, value INTEGER)')
    con.execute('INSERT INTO engine_state VALUES (1, ?)', (rng.randrange(1, 10 ** 9),))
    _policy(con, 'engine_state', 'match_state', {'scope': 'never'})
    # declared public but reading a withheld person column: must be refused
    con.execute('CREATE TABLE note_table(idx INTEGER PRIMARY KEY, person_idx INTEGER)')
    con.executemany('INSERT INTO note_table VALUES (?, ?)', [(i, i) for i in range(1, N + 1)])
    con.execute('CREATE VIEW leaky_view AS SELECT n.idx, n.person_idx, pe.adaptability FROM note_table n '
                'JOIN person pe ON pe.idx = n.person_idx WHERE pe.wage > 1000')
    _policy(con, 'note_table', 'notes', {'scope': 'public'}, ['leaky_view'])


def knowledge(path, covered):
    store = ks.KnowledgeStore(path)
    store.ensure_identity(base.IDENT)
    store.set_seeds(dict(fow_nodes=list(SCOUTED), report_primary=[], own_club_rosters=list(OWN)))
    store.set_universe(list(range(1, N + 1)), source='test')
    rows = []
    for idx in covered:
        kind = knowledge_kind(idx)
        rows.append(base.row(idx, kind, own=idx in OWN, value=16 if idx in OWN else 8 + idx % 9,
                             node=40 if idx in SCOUTED else None,
                             stars=(2.0, 3.0, 2.5, 4.0) if idx in SCOUTED else None,
                             search=1 if idx in SCOUTED else None))
    store.write_rows(rows, tier=1, ident=base.IDENT)
    store.close()


@pytest.fixture(scope='module')
def saves(tmp_path_factory):
    root = tmp_path_factory.mktemp('leaks')
    out = []
    for name, seed in (('a', 1), ('b', 2)):
        folder = root / name
        folder.mkdir()
        build(folder / 'snapshot.sqlite', seed)
        knowledge(folder / 'knowledge.sqlite', range(1, N + 1))            # everything computed
        knowledge(folder / 'partial.sqlite', list(OWN) + list(SCOUTED))    # strangers not computed yet
        out.append(folder)
    # the two snapshots really differ where it matters
    a, b = (sqlite3.connect(f / 'snapshot.sqlite') for f in out)
    assert a.execute('SELECT idx, current_ability, transfer_value FROM player ORDER BY idx').fetchall() != \
        b.execute('SELECT idx, current_ability, transfer_value FROM player ORDER BY idx').fetchall()
    assert a.execute('SELECT idx, first_name, club FROM person ORDER BY idx').fetchall() == \
        b.execute('SELECT idx, first_name, club FROM person ORDER BY idx').fetchall()
    a.close()
    b.close()
    return out


_CONNECTIONS = {}


def run(folder, sql, *, store='knowledge.sqlite', need=None):
    """(columns, rows) of one statement through the manager view, or ('error', class).

    One masked connection per (save, store, on-demand or not) serves every statement; with
    `need`, the connection's need set is emptied first and copied into `need` afterwards."""
    mv.check_sql(sql)
    key = (folder, store, need is not None)
    if key not in _CONNECTIONS:
        asked = set() if need is not None else None
        _CONNECTIONS[key] = (mv.open_manager_connection(folder / 'snapshot.sqlite', folder / store, need=asked),
                             asked)
    con, asked = _CONNECTIONS[key]
    if asked is not None:
        asked.clear()
    try:
        cur = con.execute(sql)
        out = [d[0] for d in cur.description], cur.fetchall()
    except sqlite3.DatabaseError as exc:
        out = 'error', type(exc).__name__
    if need is not None:
        need.update(asked)
    return out


@pytest.fixture(scope='module', autouse=True)
def _close_connections():
    yield
    for con, _ in _CONNECTIONS.values():
        con.close()
    _CONNECTIONS.clear()


def view_columns(folder):
    con = mv.open_manager_connection(folder / 'snapshot.sqlite', folder / 'knowledge.sqlite')
    try:
        generic = [r[0] for r in con.execute("SELECT view FROM m_tables WHERE scope != 'never' ORDER BY view")]
        return {v: [d[0] for d in con.execute(f'SELECT * FROM {v} LIMIT 0').description]
                for v in ('m_player_view', 'm_player', 'm_person', 'm_scouted_player_view', *generic)}
    finally:
        con.close()


def test_every_collection_and_core_object_is_served_or_withheld(saves):
    a, _ = saves
    con = mv.open_manager_connection(a / 'snapshot.sqlite', a / 'knowledge.sqlite')
    try:
        listed = {v: (s, r) for v, s, r in con.execute('SELECT view, scope, reason FROM m_tables')}
    finally:
        con.close()
    assert {v: s for v, (s, _) in listed.items()} == {
        'm_career': 'public', 'm_fixture': 'public', 'm_fixture_view': 'public', 'm_contract': 'own_club',
        'm_contract_view': 'own_club', 'm_contract_clause': 'own_rows', 'm_transfer_offer': 'own_rows',
        'm_transfer_offer_view': 'own_rows', 'm_news_item': 'own_rows', 'm_club_finance': 'own_rows',
        'm_engine_state': 'never', 'm_note_table': 'public', 'm_leaky_view': 'never', 'm_club': 'core',
        'm_team': 'core', 'm__managed': 'public'}
    assert 'person.adaptability' in listed['m_leaky_view'][1]


def statements(columns):
    """Every way of making a column decide which rows come back, in which order, or how many."""
    out = []
    for view, names in columns.items():
        out += [f'SELECT * FROM {view}', f'SELECT idx FROM {view}', f'SELECT count(*) FROM {view}',
                f'SELECT idx FROM {view} LIMIT 5', f'SELECT idx FROM {view} LIMIT 3 OFFSET 7',
                f'SELECT a.idx, b.idx FROM {view} a, {view} b WHERE a.idx < b.idx AND a.idx + b.idx = 17',
                f'SELECT rowid, idx FROM {view}' if False else f'SELECT idx, row_number() OVER () FROM {view}']
        for c in names:
            q = f'"{c}"'
            out += [
                f'SELECT idx FROM {view} WHERE {q} > 50',
                f'SELECT idx FROM {view} WHERE {q} >= 100 AND {q} < 150',
                f'SELECT idx FROM {view} WHERE {q} = (SELECT max({q}) FROM {view})',
                f'SELECT idx FROM {view} WHERE {q} IN (SELECT {q} FROM {view} ORDER BY {q} DESC LIMIT 3)',
                f'SELECT idx FROM {view} WHERE {q} IS NULL',
                f'SELECT idx FROM {view} WHERE {q} LIKE \'2%\' OR {q} GLOB \'*9\'',
                f'SELECT idx FROM {view} ORDER BY {q}',
                f'SELECT idx FROM {view} ORDER BY {q} DESC, idx LIMIT 5',
                f'SELECT {q}, count(*) FROM {view} GROUP BY {q}',
                f'SELECT idx FROM {view} GROUP BY idx HAVING max({q}) > 60',
                f'SELECT min({q}), max({q}), avg({q}), sum({q}), count({q}), count(DISTINCT {q}), '
                f'group_concat({q}) FROM {view}',
                f'SELECT idx, rank() OVER (ORDER BY {q}), ntile(4) OVER (ORDER BY {q} DESC), '
                f'lag({q}) OVER (ORDER BY idx) FROM {view}',
                f'SELECT a.idx, b.idx FROM {view} a JOIN {view} b ON a.{q} = b.{q} AND a.idx < b.idx',
                f'SELECT a.idx, count(*) FROM {view} a JOIN {view} b ON a.{q} < b.{q} GROUP BY a.idx',
                f'SELECT idx, typeof({q}), length({q}), quote({q}), hex({q}), coalesce({q}, -1), '
                f'CASE WHEN {q} > 100 THEN 1 WHEN {q} > 10 THEN 2 ELSE 0 END, iif({q} % 2, 1, 0), '
                f'nullif({q}, 0), {q} IS NOT NULL, abs({q}), {q} + 0, {q} || \'\' FROM {view}',
                f'SELECT idx FROM {view} a WHERE EXISTS (SELECT 1 FROM {view} b WHERE b.{q} > a.{q})',
                f'WITH t AS (SELECT idx, {q} AS v FROM {view}) SELECT idx FROM t WHERE v > 20 ORDER BY v',
                f'SELECT idx FROM {view} WHERE {q} > 20 UNION SELECT idx FROM {view} WHERE {q} < 5',
                f'SELECT DISTINCT {q} FROM {view}',
                f'SELECT idx FROM {view} WHERE {q} BETWEEN 1 AND 20 EXCEPT SELECT idx FROM {view} WHERE {q} > 10',
                f'SELECT total({q}) FILTER (WHERE {q} > 30), count(*) FILTER (WHERE {q} IS NULL) FROM {view}',
                f'SELECT idx FROM {view} ORDER BY {q} IS NULL, {q} * -1',
                f'SELECT (SELECT count(*) FROM {view} b WHERE b.{q} <= a.{q}) FROM {view} a',
            ]
    out += ['SELECT * FROM m_columns', 'SELECT * FROM m_attribute_columns', 'SELECT * FROM _fields',
            'SELECT * FROM _tables', 'SELECT * FROM _snapshot',
            'SELECT a.idx FROM m_player_view a JOIN m_person b ON b.idx = a.idx WHERE b.wage > a.wage',
            'SELECT club, count(*), avg(wage), max(transfer_value) FROM m_player_view GROUP BY club',
            'SELECT idx FROM m_player_view WHERE wage > 100000 OR transfer_value > 1000000 OR condition < 80',
            'SELECT idx FROM m_player_view WHERE current_ability > potential_ability - 20',
            'SELECT idx FROM m_player_view ORDER BY current_ability DESC LIMIT 10',
            'SELECT idx FROM m_person ORDER BY wage DESC LIMIT 10',
            'SELECT idx FROM m_player ORDER BY transfer_value DESC LIMIT 10',
            'SELECT idx, passing, passing_min, passing_max, passing_state FROM m_player_view WHERE passing_max >= 12',
            'SELECT idx FROM m_player_view WHERE club_reputation > 6000']
    return out


def test_statements_cannot_tell_the_saves_apart(saves):
    a, b = saves
    columns = view_columns(a)
    assert columns == view_columns(b)
    sqls = statements(columns)
    different, errors = [], 0
    for sql in sqls:
        ra, rb = run(a, sql), run(b, sql)
        errors += ra[0] == 'error'
        if ra != rb:
            different.append(sql)
    assert not different, f'{len(different)} of {len(sqls)} statements differ, e.g. {different[:5]}'
    assert errors < len(sqls) // 10          # the battery mostly runs (some functions reject some types)
    assert len(sqls) > 3000


def test_on_demand_need_set_does_not_depend_on_hidden_values(saves):
    """With knowledge stored for the named population only, which other players a statement
    asks knowledge for (and what it returns meanwhile) is the same on both saves."""
    a, b = saves
    columns = view_columns(a)
    sqls = [s for s in statements(columns) if 'FROM m_' in s]
    rng = random.Random(5)
    sample = rng.sample(sqls, 700) + [s for s in sqls if 'wage' in s or 'current_ability' in s][:300]
    asked = 0
    for sql in sample:
        na, nb = set(), set()
        ra, rb = run(a, sql, store='partial.sqlite', need=na), run(b, sql, store='partial.sqlite', need=nb)
        assert ra == rb and na == nb, sql
        asked += bool(na)
    assert asked > 100                       # the on-demand path was exercised


def test_hidden_values_never_appear(saves):
    """Direct check on one save: no hidden value of a stranger reaches any masked view."""
    a, _ = saves
    con = sqlite3.connect(a / 'snapshot.sqlite')
    hidden = {}
    for idx, ca, pa, value, rep in con.execute(
            'SELECT idx, current_ability, potential_ability, transfer_value, current_reputation FROM player'):
        hidden[idx] = {ca * 1000 + 7, value, rep * 100 + 3}       # distinctive encodings below
    wages = dict(con.execute('SELECT idx, wage FROM person'))
    con.close()
    cols, rows = run(a, 'SELECT * FROM m_player_view')
    by_idx = {r[cols.index('idx')]: dict(zip(cols, r)) for r in rows}
    for idx, r in by_idx.items():
        assert r['current_ability'] is None and r['potential_ability'] is None and r['consistency'] is None
        assert r['current_reputation'] is None and r['adaptability'] is None and r['acceleration_pdac'] is None
        if idx in OWN:
            assert r['wage'] == wages[idx] and r['transfer_value'] is not None
        else:
            assert r['wage'] is None and r['transfer_value'] is None and r['condition'] is None
            assert r['contract_expires'] is None and r['double_wage'] is None
        if knowledge_kind(idx) != 'exact':
            assert r['passing'] is None
    assert len(by_idx) == N


@pytest.mark.parametrize('sql', [
    'SELECT idx FROM player ORDER BY current_ability',
    'SELECT idx FROM person WHERE wage > 1000',
    'SELECT * FROM player_view',
    'SELECT idx FROM m_player_view WHERE idx IN (SELECT idx FROM player WHERE current_ability > 100)',
    'SELECT (SELECT current_ability FROM player p WHERE p.idx = v.idx) FROM m_player_view v',
    'SELECT idx FROM m_player_view v JOIN person p USING (idx) WHERE p.wage > 1000',
    'SELECT cash_balance FROM club WHERE idx = 11',
    'SELECT idx FROM m_player_view WHERE club_idx IN (SELECT idx FROM club WHERE cash_balance > 100000000)',
    'SELECT v.idx FROM m_player_view v JOIN club c ON c.idx = v.club_idx ORDER BY c.wage_budget',
    'SELECT name FROM pragma_index_list(\'player\')',
    'SELECT * FROM pragma_index_xinfo(\'hidden_ca\')',
    'SELECT * FROM sqlite_stat1',
    'SELECT stat FROM main.sqlite_stat1 WHERE idx = \'hidden_ca\'',
    'SELECT * FROM kn.knowledge_player',
    'SELECT * FROM kn.knowledge_input',
    'SELECT key, outcome FROM kn.knowledge_group',
    'SELECT value FROM kn._knowledge_meta',
    'SELECT sql FROM sqlite_master',
    'SELECT * FROM dbstat',
    # collection and core tables: the bare names, CTEs named like the masked views, subqueries, joins
    'SELECT loan_fee FROM contract',
    'SELECT * FROM contract_view',
    'SELECT * FROM fixture',
    'WITH m_contract AS (SELECT * FROM contract) SELECT loan_fee FROM m_contract',
    'WITH m_contract_view AS (SELECT loan_fee FROM main.contract) SELECT * FROM m_contract_view',
    'SELECT idx FROM m_contract WHERE idx IN (SELECT idx FROM contract WHERE loan_fee > 5000)',
    'SELECT c.idx FROM m_contract c JOIN contract k ON k.idx = c.idx ORDER BY k.loan_fee',
    'SELECT (SELECT amount FROM contract_clause q WHERE q.idx = 9) FROM m_fixture LIMIT 1',
    'SELECT * FROM m_fixture UNION ALL SELECT idx, amount_raw, 0, 0, 0, 0 FROM transfer_offer',
    'SELECT * FROM transfer_offer WHERE team1_club_idx = 11',
    'SELECT * FROM club_finance WHERE idx = 11',
    'SELECT * FROM engine_state',
    'SELECT * FROM m_engine_state',
    'SELECT * FROM m_leaky_view',
    'SELECT * FROM leaky_view',
    'SELECT * FROM _source_tables',
    'SELECT manager_json FROM _source_views',
    'SELECT * FROM _managed',
    'SELECT * FROM m__managed',
    'SELECT m.club_idx FROM _managed m JOIN club c ON c.idx = m.club_idx WHERE c.cash_balance > 0',
    'SELECT cash_balance FROM m_club WHERE idx IN (SELECT idx FROM club WHERE cash_balance > 0)',
    'SELECT name FROM sqlite_temp_master',
    'SELECT * FROM pragma_index_list(\'contract\')',
])
def test_bypasses_are_denied_or_blind(saves, sql):
    a, b = saves
    try:
        ra, rb = run(a, sql), run(b, sql)
    except mv.ManagerViewError:
        return
    if sql in ('SELECT * FROM kn.knowledge_player', 'SELECT * FROM _managed', 'SELECT * FROM m__managed'):
        assert ra == rb and ra[0] != 'error'      # the manager's own knowledge and career, identical on both
        return
    assert ra[0] == 'error' and rb[0] == 'error', sql
