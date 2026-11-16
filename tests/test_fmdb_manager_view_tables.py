"""Manager view over every table of the reader: collection tables, core tables and curated views.

Offline: the snapshot is the leak tests' two-save fixture (test_fmdb_manager_view_leaks.py), which
holds a collection table of every policy kind, the core club/team tables and `_managed`."""
import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from fm_live_mcp.fmdb import knowledge_store as ks
from fm_live_mcp.fmdb import manager_view as mv
from fm_live_mcp.fmdb import sources, tools

_spec = importlib.util.spec_from_file_location('manager_view_leaks', Path(__file__).with_name(
    'test_fmdb_manager_view_leaks.py'))
leaks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(leaks)


@pytest.fixture(scope='module')
def saves(tmp_path_factory):
    root = tmp_path_factory.mktemp('tables')
    out = []
    for name, seed in (('a', 1), ('b', 2)):
        folder = root / name
        folder.mkdir()
        leaks.build(folder / 'snapshot.sqlite', seed)
        leaks.knowledge(folder / 'knowledge.sqlite', range(1, leaks.N + 1))
        out.append(folder)
    return out


def fetch(con, sql):
    cur = con.execute(sql)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


@pytest.fixture
def con(saves):
    c = mv.open_manager_connection(saves[0] / 'snapshot.sqlite', saves[0] / 'knowledge.sqlite')
    yield c
    c.close()


def test_collection_rows_and_columns_follow_the_policy(con):
    rows = fetch(con, 'SELECT * FROM m_contract_view ORDER BY idx')
    assert len(rows) == leaks.N                                     # every row: the policy has public columns
    for r in rows:
        own = r['idx'] in leaks.OWN
        assert r['person_name'] == f'P{r["idx"]:02d}' and r['team_name'] in ('Club A', 'Club B')
        assert r['weekly_wage'] == 1000 * r['idx']                  # public column
        assert (r['loan_fee'], r['double_fee']) == ((5000, 10000) if own else (None, None))
    assert [r['contract_idx'] for r in fetch(con, 'SELECT * FROM m_contract_clause')] == list(leaks.OWN)
    assert [r['idx'] for r in fetch(con, 'SELECT idx FROM m_transfer_offer ORDER BY idx')] == [0, 1]
    assert [r['idx'] for r in fetch(con, 'SELECT idx FROM m_transfer_offer_view ORDER BY idx')] == [0, 1]
    assert [r['source'] for r in fetch(con, 'SELECT * FROM m_news_item')] == ['inbox', 'inbox']
    assert fetch(con, 'SELECT * FROM m_club_finance') == [{'idx': 10, 'balance': 1, 'wage_bill': 2}]
    assert len(fetch(con, 'SELECT * FROM m_fixture_view')) == 12
    clubs = {r['idx']: r for r in fetch(con, 'SELECT * FROM m_club')}
    assert clubs[10]['cash_balance'] == 50000000 and clubs[11]['cash_balance'] is None
    assert clubs[11]['name'] == 'Club B' and clubs[10]['reputation'] is None   # raw reputation: never
    policy = {(r['view'], r['column_name']): r['policy'] for r in fetch(con, 'SELECT * FROM m_columns')}
    assert policy[('m_contract_view', 'loan_fee')] == 'own_club'
    assert policy[('m_contract_view', 'person_name')] == 'public'
    assert policy[('m_contract_view', 'double_fee')] == 'own_club'
    assert policy[('m_club', 'reputation')] == 'never'


@pytest.mark.parametrize('sql', ['SELECT * FROM m_engine_state', 'SELECT * FROM m_leaky_view',
                                 'SELECT * FROM contract', 'SELECT * FROM fixture_view'])
def test_withheld_and_bare_objects_are_not_readable(con, sql):
    with pytest.raises(sqlite3.DatabaseError):
        con.execute(sql).fetchall()


def test_audited_codes():
    for code in ('Pcwg', 'Pcex', 'Pcww', 'Pced', 'Pfvp', 'Pfvc', 'injr'):
        assert mv._policy_for_code(code) == mv.PUBLIC, code
    for code in ('PCAB', 'PPAB', 'Pada', 'PCRP'):
        assert mv._policy_for_code(code) == mv.NEVER, code
    assert mv._policy_for_code('PMsq') == mv.OWN_CLUB and mv._policy_for_code('Pmor') == mv.OWN_CLUB
    ctx = {'names': set(), 'links': set(), 'own_table': None}
    fields = {('non_player', 'coaching_attacking'): ('Ncha', 'nnpl'), ('non_player', 'current_ability'): ('Ncra', 'nnpl'),
              ('non_player', 'interference'): ('Nint', 'nnpl'), ('non_player', 'world_reputation'): ('Nwrr', 'nnpl')}
    policy = {c: mv._ref_policy('non_player', c, fields, derived=False, ctx=ctx)[0] for _, c in fields}
    assert policy == {'coaching_attacking': mv.PUBLIC, 'current_ability': mv.NEVER, 'interference': mv.OWN_CLUB,
                      'world_reputation': mv.NEVER}


def test_only_the_named_views_are_built_but_every_object_is_listed(saves):
    c = mv.open_manager_connection(saves[0] / 'snapshot.sqlite', saves[0] / 'knowledge.sqlite',
                                   only=mv.referenced_names('SELECT * FROM m_fixture_view'))
    try:
        assert 'm_fixture_view' in c.manager_info['public_views']
        assert not {'m_contract', 'm_player_view', 'm_club'} & set(c.manager_info['public_views'])
        assert c.execute('SELECT count(*) FROM m_tables').fetchone()[0] == 15
        with pytest.raises(sqlite3.OperationalError):
            c.execute('SELECT * FROM m_contract').fetchall()
    finally:
        c.close()


def test_statement_without_player_knowledge_computes_none(saves, tmp_path, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError('the knowledge builder must not run for this statement')
    monkeypatch.setattr(ks, 'KnowledgeBuilder', refuse)
    q = mv.prepare_manager_query((saves[0] / 'snapshot.sqlite', tmp_path / 'missing.sqlite'),
                                 'SELECT home_team, home_goals FROM m_fixture_view ORDER BY idx',
                                 bridge_or_session=object())
    try:
        assert q.complete and 'No player knowledge read' in q.message
        assert len(q.connection.execute('SELECT * FROM m_fixture_view').fetchall()) == 12
    finally:
        q.connection.close()
    with pytest.raises(mv.ManagerViewError):     # a statement on the player views still needs the store
        mv.prepare_manager_query((saves[0] / 'snapshot.sqlite', tmp_path / 'missing.sqlite'),
                                 'SELECT name FROM m_player_view')


def _dry_run_keys(folder, sql):
    """The keys a statement-dependent table (histories) computes for a manager statement."""
    from fm_live_mcp.fmdb.sources.histories import statement_keys
    statement = mv.ManagerStatement(sql, None, folder / 'snapshot.sqlite', folder / 'knowledge.sqlite')
    return statement_keys(statement, 'career', 'person_idx', ['entry', 'team_idx'], 'SELECT idx FROM person')


def test_statement_dependent_dry_run_uses_what_the_manager_sees(saves):
    a, b = saves
    sql = ('SELECT * FROM m_career WHERE person_idx IN (SELECT person_idx FROM m_contract_view '
           'WHERE loan_fee > 100 OR person_idx > 38)')
    ka, kb = _dry_run_keys(a, sql), _dry_run_keys(b, sql)
    assert ka == kb == set(leaks.OWN) | {39, 40}       # other clubs' loan fees read NULL in the dry run
    assert _dry_run_keys(a, 'SELECT entry FROM m_career WHERE person_idx = 7') == {7}
    # the dry run runs the statement under the manager authorizer: a bare table is refused, so
    # the source computes nothing (None) instead of rows chosen by a withheld value
    assert _dry_run_keys(a, 'SELECT * FROM m_career WHERE person_idx IN '
                            '(SELECT person_idx FROM contract WHERE loan_fee > 100)') is None
    # only the source's own setup statements run without the authorizer; the statement runs under it
    sql = 'SELECT * FROM m_fixture WHERE idx IN (SELECT idx FROM transfer_offer WHERE amount_raw > 5)'
    conn, close = sources.dry_run_connection(None, mv.ManagerStatement(sql, None, a / 'snapshot.sqlite',
                                                                       a / 'knowledge.sqlite'))
    try:
        conn.execute('CREATE TEMP TABLE _keys(k INTEGER)')
        conn.execute('INSERT INTO _keys SELECT idx FROM transfer_offer')
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(sql).fetchall()
        assert conn.execute('SELECT count(*) FROM m_fixture').fetchone()[0] == 12
    finally:
        close()


def test_manager_query_refreshes_the_collection_tables_it_reads(saves, monkeypatch):
    seen = []

    def refresh(engine, path, reads, *, log=None, statement=None):
        seen.append(({r[0] for r in reads}, statement))
        return {'contract': {'unchanged': True}}
    monkeypatch.setattr(sources, 'refresh_for_query', refresh)
    monkeypatch.setattr(tools, '_knowledge_path', lambda e: saves[0] / 'knowledge.sqlite')
    notes = []
    out = tools._manager_collections(None, saves[0] / 'snapshot.sqlite',
                                     'SELECT person_name FROM m_contract_view JOIN m_fixture ON 1', None, notes)
    assert out == {'contract': {'unchanged': True}} and not notes
    tables, statement = seen[0]
    assert tables == {'contract', 'fixture'} and isinstance(statement, mv.ManagerStatement)
    assert tuple(statement) == ('SELECT person_name FROM m_contract_view JOIN m_fixture ON 1', None,
                                saves[0] / 'snapshot.sqlite')
    assert tools._manager_collections(None, saves[0] / 'snapshot.sqlite', 'SELECT name FROM m_player_view',
                                      None, notes) is None


def test_schema_lists_every_view_with_its_policy_in_one_line(saves, monkeypatch):
    monkeypatch.setattr(tools, '_knowledge_path', lambda e: saves[0] / 'knowledge.sqlite')
    meta = {'save_name': 'Career X', 'game_date': '2030-12-13', 'built_at': 'now'}
    out = tools.manager_schema(None, saves[0] / 'snapshot.sqlite', meta)
    assert out['views']['m_contract_view'].startswith('own_club: every row: idx, person_idx')
    assert out['views']['m_fixture'] == 'public: every row and column'
    assert out['views']['m_club_finance'] == "own_rows: only your club's rows"
    assert 'm_engine_state' in out['withheld'] and 'm_engine_state' not in out['views']
    one = tools.manager_schema(None, saves[0] / 'snapshot.sqlite', meta, table='m_contract_view')
    assert {c['column']: c['policy'] for c in one['columns']}['loan_fee'] == 'own_club'
    with pytest.raises(tools.FmdbError, match='withheld'):
        tools.manager_schema(None, saves[0] / 'snapshot.sqlite', meta, table='m_leaky_view')


def test_denied_read_names_the_masked_view(saves):
    text = tools._manager_denied_hint('access to main.contract.loan_fee is prohibited',
                                      'SELECT * FROM contract_view', saves[0] / 'snapshot.sqlite')
    assert 'contract_view -> m_contract_view' in text


def test_relation_view_policies_name_their_own_rows():
    """Every own-club policy names how a row is the manager's (manager_view._own_condition)."""
    from fm_live_mcp.fmdb.sources import relations
    keys = ('own_club_column', 'own_club_columns', 'own_person_column', 'own_team_column', 'own_club_via',
            'own_club_rule')
    views = relations.views(None)
    assert views['person_favourite'][2]['scope'] == 'public'
    assert views['club_favourite_person'][2]['scope'] == 'public'
    assert views['player_position'][2]['own_person_column'] == 'player_idx'
    assert all(any(k in spec[2] for k in keys) for spec in views.values() if spec[2]['scope'] == 'own_club')
    assert json.dumps(views['player_position'][2])


def test_rename_views_keeps_literals_and_other_tokens():
    sql = "SELECT 'm_fixture' AS m, f.home_goals / 1.5 FROM m_fixture f -- m_fixture\n JOIN \"m_FIXTURE\" g ON 1"
    assert mv.rename_views(sql, {'m_fixture': 'fixture'}) == (
        "SELECT 'm_fixture' AS m, f.home_goals / 1.5 FROM \"fixture\" f -- m_fixture\n JOIN \"fixture\" g ON 1")


def test_public_statement_runs_as_the_full_statement(saves, monkeypatch):
    calls = []
    monkeypatch.setattr(tools, '_knowledge_path', lambda e: saves[0] / 'knowledge.sqlite')
    monkeypatch.setattr(tools, '_full_query', lambda engine, path, meta, refreshed, stale, sql, params, max_rows:
                        calls.append(sql) or {'columns': [], 'rows': []})
    path = saves[0] / 'snapshot.sqlite'
    out = tools.manager_public_query(None, path, {}, None, 'SELECT * FROM m_fixture_view JOIN m_career ON 1', None, 5)
    assert out['view'] == 'manager' and calls == ['SELECT * FROM "fixture_view" JOIN "career" ON 1']
    # a statement that reads an own-club or knowledge view, or nothing masked, takes the masked path
    for sql in ('SELECT * FROM m_contract', 'SELECT * FROM m_fixture JOIN m_player_view ON 1', 'SELECT 1'):
        assert tools.manager_public_query(None, path, {}, None, sql, None, 5) is None
    # a bare table next to a public view is refused before anything runs on the full data
    with pytest.raises(tools.query.QueryError, match='m_<name>'):
        tools.manager_public_query(None, path, {}, None,
                                   'SELECT * FROM m_fixture WHERE idx IN (SELECT idx FROM contract)', None, 5)
    assert len(calls) == 1
