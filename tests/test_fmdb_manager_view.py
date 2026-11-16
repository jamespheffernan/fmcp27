"""Offline tests for the manager view: synthetic snapshot (snapshot-lane contract) + synthetic knowledge.

Covers view construction, the masking policy, authorizer enforcement against bypass attempts,
epochs and fingerprint-driven confirmation, and on-demand computation of the rows a statement
reads. No game is needed.
"""
import sqlite3

import pytest

from fm_live_mcp import knowledge_bulk as kb
from fm_live_mcp.bridge import BridgeError
from fm_live_mcp.fmdb import knowledge_codes as codes
from fm_live_mcp.fmdb import knowledge_store as ks
from fm_live_mcp.fmdb import manager_view as mv

DATE = '2030-12-10'
IDENT = dict(save_key='career-x', save_name='Career X', game_date=DATE, coach='Cesar Jules', club='Newcastle')

# (table, column, code, record_type). 'wage' and 'contract_expires' carry stand-in codes (Pcbx, Pcxx) for
# person fields the policy keeps to the own club; the real wage and expiry codes (Pcwg, Pcex) are
# public since the round-3 audit (test_fmdb_manager_view_tables.py checks them).
FIELDS = [
    ('person', 'first_name', 'Pfna', 'pers'), ('person', 'date_of_birth', 'Pdob', 'pers'),
    ('person', 'wage', 'Pcbx', 'pers'), ('person', 'contract_expires', 'Pcxx', 'pers'),
    ('person', 'nationality', 'Pnat', 'pers'), ('person', 'club', 'Pcti', 'pers'),
    ('person', 'adaptability', 'Pada', 'pers'), ('person', 'squad_status', 'PMsq', 'pers'),
    ('team', 'long_name', 'Tlna', 'team'), ('team', 'reputation', 'Trep', 'team'),
    ('player', 'current_ability', 'PCAB', 'play'), ('player', 'potential_ability', 'PPAB', 'play'),
    ('player', 'passing', 'Ppas', 'play'), ('player', 'acceleration_pacc', 'Pacc', 'play'),
    ('player', 'acceleration_pdac', 'PDac', 'play'), ('player', 'consistency', 'PCON', 'play'),
    ('player', 'current_reputation', 'PCRP', 'play'), ('player', 'transfer_value', 'PbvE', 'play'),
    ('player', 'overall_physical_condition', 'Pcon', 'play'), ('player', 'goalkeeper', 'Pgoa', 'play'),
    ('player', 'position', 'Ppsr', 'play'),
]
PEOPLE = {  # idx: (first_name, ca, passing raw, acceleration raw)
    1: ('Own', 150, 16, 14), 2: ('Scouted', 140, 12, 11), 3: ('Stranger', 90, 9, 8),
    4: ('Broken', 100, 10, 10), 5: ('Unseen', 160, 18, 17),
}


# The snapshot lane's curated style (views.py): every item `alias."column" AS "name"`, renamed
# columns, derived expressions, enum-label subqueries and LEFT JOINs to referenced tables.
CURATED_VIEW = """CREATE VIEW player_view AS SELECT
  p.idx AS "idx",
  p.uid AS "uid",
  p.class AS "class",
  COALESCE(NULLIF(pe."first_name", ''), 'nobody') AS "name",
  pe."first_name" AS "first_name",
  pe."date_of_birth" AS "date_of_birth",
  CASE WHEN pe."date_of_birth" IS NULL THEN NULL ELSE CAST(strftime('%Y', (SELECT game_date FROM _snapshot LIMIT 1))
    AS INTEGER) - CAST(strftime('%Y', pe."date_of_birth") AS INTEGER) END AS "age",
  pe."nationality" AS "nationality_idx",
  pe."club" AS "club_idx",
  COALESCE(NULLIF(cl."long_name", ''), NULL) AS "club",
  cl."reputation" AS "club_reputation",
  json_extract(p."position", '$.text') AS "position",
  p."current_ability" AS "current_ability",
  p."potential_ability" AS "potential_ability",
  p."passing" AS "passing",
  p."acceleration_pacc" AS "acceleration",
  p."acceleration_pdac" AS "acceleration_pdac",
  p."consistency" AS "consistency",
  p."current_reputation" AS "current_reputation",
  p."goalkeeper" AS "pos_goalkeeper",
  p."overall_physical_condition" AS "condition",
  p."transfer_value" AS "transfer_value",
  pe."wage" AS "wage",
  pe."contract_expires" AS "contract_expires",
  pe."adaptability" AS "adaptability",
  (SELECT label FROM _enum_labels WHERE table_name='person' AND column_name='squad_status'
    AND value=pe."squad_status") AS "squad_status",
  pe."first_name" || '!' AS "shout",
  pe."wage" * 2 AS "double_wage",
  p."current_ability" / 20 AS "ca_stars",
  (p."passing" + p."acceleration_pacc") / 2 AS "pas_acc_avg",
  'const' AS "const"
FROM player p JOIN person pe ON pe.idx = p.idx
LEFT JOIN team cl ON cl.idx = pe."club\""""
PLAIN_VIEW = """CREATE VIEW player_view AS
    SELECT p.idx, p.uid, s.first_name, s.wage, p.current_ability, p.passing, p.acceleration_pacc,
           p.acceleration_pdac, s.adaptability
    FROM player p JOIN person s ON s.idx = p.idx"""


def make_snapshot(path, view=CURATED_VIEW, people=None):
    """`people`: PERSON indices for a generated population (default: the five named PEOPLE)."""
    con = sqlite3.connect(path)
    population = PEOPLE if people is None else {
        i: (f'P{i}', 100 + i % 50, 5 + i % 15, 5 + i % 14) for i in people}
    cols = {t: [c for tt, c, _, _ in FIELDS if tt == t] for t in ('person', 'player', 'team')}
    for t in cols:
        con.execute(f'CREATE TABLE {t}(idx INTEGER PRIMARY KEY, uid INTEGER, class TEXT, {", ".join(cols[t])})')
    con.execute("INSERT INTO team VALUES (10, 10, 'TEAM', 'Club A', 9000), (11, 11, 'TEAM', 'Club B', 5000)")
    for idx, (name, ca, pas, acc) in population.items():
        con.execute('INSERT INTO person VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    (idx, 1000 + idx, 'ACTUAL_PLAYER', name, '2000-01-01', 50000 + idx, '2033-06-30', 7,
                     10 if idx == 1 else 11, 15, 2))
        con.execute('INSERT INTO player VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (idx, 1000 + idx, 'ACTUAL_PLAYER', ca, ca + 10, pas, acc, acc * 5, 13, 5000, 1_000_000, 95,
                     1, '{"text": "M (C)"}'))
    con.execute('CREATE TABLE _fields(table_name, column_name, code, record_type, name, comment, type, enum_json, '
                'references_table, source, status, note)')
    con.executemany('INSERT INTO _fields(table_name, column_name, code, record_type) VALUES (?,?,?,?)', FIELDS)
    con.execute('CREATE TABLE _tables(table_name, record_type, rows, classes_json)')
    con.execute('CREATE TABLE _enum_labels(table_name, column_name, value, label)')
    con.execute("INSERT INTO _enum_labels VALUES ('person', 'squad_status', 2, 'Key Player')")
    con.execute('CREATE TABLE _snapshot(save_name, save_key, game_date, built_at, build, plans_verified, notes)')
    con.execute("INSERT INTO _snapshot VALUES ('Career X', 'career-x', ?, 'now', 'test', 1, '')", (DATE,))
    con.execute(view)
    con.commit()
    con.close()


def cells(kind, value=None):
    if kind == 'exact':
        return dict(state='exact', value=value, min=value, max=value, reason=None)
    if kind == 'range':
        return dict(state='range', value=None, min=value - 2, max=value + 2, reason=None)
    if kind == 'unknown':
        return dict(state='unknown', value=None, min=None, max=None, reason=None)
    return dict(state='unavailable', value=None, min=None, max=None, reason='unavailable_source: test')


def row(idx, kind, *, own=False, value=10, k=5, node=None, report=None, stars=None, search=None):
    cs = [cells(kind, value) for _ in codes.FIELDS]
    counts = {s: sum(c['state'] == s for c in cs) for s in ks.STATES}
    return dict(idx=idx, cells=cs, exact_n=counts['exact'], range_n=counts['range'], unknown_n=counts['unknown'],
                unavailable_n=counts['unavailable'],
                unavailable_reason='unavailable_source: test' if kind == 'unavailable' else None,
                k=None if own else k, node_score=node, report_score=report, own_club=int(own),
                sources='own_club' if own else 'context', h_score=None if own else k, ca_gate=2 if own else 0,
                pa_gate=2 if own else 0, category=None if own else 1, node_present=int(node is not None),
                report_present=int(report is not None), **star_fields(stars), in_player_search=search)


def star_fields(stars):
    """stars: None (not computed), 'unknown', or (ca_min, ca_max, pa_min, pa_max)."""
    if stars is None:
        return {k: v for k, v in ks.NOT_COMPUTED.items() if k != 'in_player_search'}
    if stars == 'unknown':
        return dict(ca_stars_min=None, ca_stars_max=None, ca_stars_state='unknown', pa_stars_min=None,
                    pa_stars_max=None, pa_stars_state='unknown')
    a, b, c, d = stars
    return dict(ca_stars_min=a, ca_stars_max=b, ca_stars_state='exact' if a == b else 'range',
                pa_stars_min=c, pa_stars_max=d, pa_stars_state='exact' if c == d else 'range')


@pytest.fixture
def env(tmp_path):
    snap = tmp_path / 'snapshot.sqlite'
    make_snapshot(snap)
    store = ks.KnowledgeStore(tmp_path / 'knowledge.sqlite')
    store.ensure_identity(IDENT)
    store.set_seeds(dict(fow_nodes=[2], report_primary=[], own_club_rosters=[1]))
    store.set_universe([1, 2, 3, 4, 5], source='test')
    store.write_rows([row(1, 'exact', own=True, value=16, stars=(3.5, 3.5, 4.0, 4.5), search=1),
                      row(2, 'range', value=12, node=40, stars=(2.0, 3.0, 2.5, 4.0), search=1),
                      row(3, 'unknown', stars='unknown', search=0), row(4, 'unavailable')], tier=1, ident=IDENT)
    store.set_meta({'tier1_complete': True})
    yield snap, store
    store.close()


@pytest.fixture
def con(env):
    snap, store = env
    c = mv.open_manager_connection(snap, store.path, coverage=store.coverage())
    yield c
    c.close()


def fetch(con, sql):
    cur = con.execute(sql)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


# ----------------------------------------------------------------------------- view construction

def test_rows_are_players_with_knowledge(con):
    rows = fetch(con, 'SELECT idx FROM m_player_view ORDER BY idx')
    assert [r['idx'] for r in rows] == [1, 2, 3, 4]          # 5 has no knowledge row
    assert [r['idx'] for r in fetch(con, 'SELECT idx FROM m_scouted_player_view ORDER BY idx')] == [1, 2]
    assert [r['idx'] for r in fetch(con, 'SELECT idx FROM m_player ORDER BY idx')] == [1, 2, 3, 4]
    assert [r['idx'] for r in fetch(con, 'SELECT idx FROM m_person ORDER BY idx')] == [1, 2, 3, 4]


def test_attribute_columns_follow_cells(con):
    r = {x['idx']: x for x in fetch(con, 'SELECT * FROM m_player_view')}
    assert (r[1]['passing'], r[1]['passing_min'], r[1]['passing_max'], r[1]['passing_state']) == (16, 16, 16, 'exact')
    assert (r[2]['passing'], r[2]['passing_min'], r[2]['passing_max'], r[2]['passing_state']) == (None, 10, 14, 'range')
    assert (r[3]['passing'], r[3]['passing_min'], r[3]['passing_max'], r[3]['passing_state']) == (None, None, None, 'unknown')
    assert (r[4]['passing'], r[4]['passing_min'], r[4]['passing_state']) == (None, None, 'unavailable')
    assert r[4]['unavailable_reason'] == 'unavailable_source: test'
    # a renamed base attribute column (acceleration_pacc AS acceleration) keeps the view's name
    assert (r[1]['acceleration'], r[2]['acceleration_min'], r[2]['acceleration_state']) == (16, 10, 'range')
    # attributes absent from player_view are added under their canonical names
    for f in codes.FIELDS:
        if f['code'] not in ('Ppas', 'Pacc'):
            assert f['column'] in r[1] and f['column'] + '_max' in r[1]
    assert 'knowledge_acceleration' not in r[1]
    # base attribute values never leak: own-club exact value is the knowledge value (16), base is 16 by
    # construction, but the stranger's base passing (9) must not appear anywhere
    assert 9 not in (r[3]['passing'], r[3]['passing_min'], r[3]['passing_max'])
    assert (r[1]['scouted'], r[2]['scouted'], r[3]['scouted']) == (1, 1, 0)
    assert r[2]['knowledge_date'] == DATE and r[2]['k'] == 5 and r[1]['own_club'] == 1


def test_attribute_column_map(con):
    m = dict(con.execute('SELECT field, column_name FROM m_attribute_columns').fetchall())
    assert len(m) == 47 and m['Passing'] == 'passing' and m['Acceleration'] == 'acceleration'
    assert m['Free Kick Taking'] == 'free_kick_taking'


# ----------------------------------------------------------------------------- masking policy

def test_masking_policy(con):
    r = {x['idx']: x for x in fetch(con, 'SELECT * FROM m_player_view')}
    for idx in (1, 2, 3, 4):
        # never: CA/PA (and anything derived from them), hidden attribute, 1..100 attribute, personality,
        # raw reputation, expressions over raw attributes, constants without a base column,
        # non-name columns of referenced tables
        for col in ('current_ability', 'potential_ability', 'consistency', 'acceleration_pdac', 'adaptability',
                    'current_reputation', 'ca_stars', 'pas_acc_avg', 'const', 'club_reputation'):
            assert r[idx][col] is None, (idx, col)
        # public for every known player, including derived columns over public base columns
        name = PEOPLE[idx][0]
        assert (r[idx]['first_name'], r[idx]['name'], r[idx]['shout']) == (name, name, name + '!')
        assert r[idx]['date_of_birth'] == '2000-01-01' and r[idx]['age'] == 30
        assert r[idx]['nationality_idx'] == 7 and r[idx]['position'] == 'M (C)'
        assert r[idx]['club'] == ('Club A' if idx == 1 else 'Club B') and r[idx]['club_idx'] in (10, 11)
    # own club only (including derived columns and enum labels over own-club-only columns)
    own = ('wage', 'contract_expires', 'transfer_value', 'condition', 'pos_goalkeeper', 'squad_status',
           'double_wage')
    assert tuple(r[1][c] for c in own) == (50001, '2033-06-30', 1_000_000, 95, 1, 'Key Player', 100002)
    for idx in (2, 3, 4):
        assert all(r[idx][c] is None for c in own), idx
    policies = dict(con.execute("SELECT column_name, policy FROM m_columns WHERE view='m_player_view'").fetchall())
    assert policies['current_ability'] == 'never' and policies['wage'] == 'own_club'
    assert policies['first_name'] == 'public' and policies['passing'] == 'attribute'
    assert policies['acceleration'] == 'attribute' and policies['pas_acc_avg'] == 'never'
    assert policies['squad_status'] == 'own_club' and policies['age'] == 'public' and policies['club'] == 'public'
    assert policies['idx'] == 'identity' and policies['nationality_idx'] == 'public'


BARE_VIEW = """CREATE VIEW player_view AS SELECT idx, uid, current_ability, passing, acceleration_pacc AS pace_like,
    (SELECT wage FROM person WHERE person.idx = player.idx) AS sub_wage,
    (SELECT first_name FROM person x WHERE x.idx = player.idx) AS name,
    (SELECT max(current_ability) FROM player) AS name_too,
    hex(passing) AS digest
    FROM player"""


def test_bare_column_view_style(tmp_path, env):
    _, store = env
    snap = tmp_path / 'bare.sqlite'
    make_snapshot(snap, 'SELECT 1')   # no view yet
    c = sqlite3.connect(snap)
    c.execute(BARE_VIEW)
    c.commit()
    c.close()
    con = sqlite3.connect(snap)
    columns = {c.name: c for c in mv.column_policy(con, 'player_view',
                                                   [r[1] for r in con.execute('PRAGMA table_info(player_view)')],
                                                   mv._CREATE_VIEW.match(con.execute(
                                                       "SELECT sql FROM sqlite_master WHERE name='player_view'"
                                                   ).fetchone()[0]).group('body'))}
    con.close()
    assert columns['idx'].policy == 'identity' and columns['uid'].policy == 'identity'
    assert columns['current_ability'].policy == 'never'
    assert columns['passing'].policy == 'attribute' and columns['pace_like'].policy == 'attribute'
    assert columns['sub_wage'].policy == 'own_club'      # subquery over person.wage
    assert columns['name'].policy == 'public'            # subquery over person.first_name via alias x
    assert columns['name_too'].policy == 'never'         # a public-looking name over current_ability
    assert columns['digest'].policy == 'never'           # function of a raw attribute


def test_plain_view_style(tmp_path, env):
    _, store = env
    snap = tmp_path / 'plain.sqlite'
    make_snapshot(snap, PLAIN_VIEW)
    c = mv.open_manager_connection(snap, store.path)
    try:
        r = {x['idx']: x for x in fetch(c, 'SELECT * FROM m_player_view')}
        assert r[1]['wage'] == 50001 and r[2]['wage'] is None and r[2]['first_name'] == 'Scouted'
        assert r[1]['current_ability'] is None and r[1]['acceleration_pdac'] is None
        assert (r[1]['acceleration_pacc'], r[2]['passing_max']) == (16, 14)
    finally:
        c.close()


def test_base_player_table_masked(con):
    r = {x['idx']: x for x in fetch(con, 'SELECT * FROM m_player')}
    assert r[1]['current_ability'] is None and r[1]['overall_physical_condition'] == 95
    assert r[2]['overall_physical_condition'] is None and r[2]['goalkeeper'] is None
    assert r[1]['current_reputation'] is None


def test_range_filters(con):
    sure = mv.range_filter('sure_at_least', 'passing', 11)
    could = mv.range_filter('could_be_at_least', 'passing', 13)
    assert [x for x, in con.execute(f'SELECT idx FROM m_player_view WHERE {sure} ORDER BY idx')] == [1]
    assert [x for x, in con.execute(f'SELECT idx FROM m_player_view WHERE {could} ORDER BY idx')] == [1, 2]
    with pytest.raises(ValueError):
        mv.range_filter('sure_at_least', 'passing; drop', 3)


# ----------------------------------------------------------------------------- authorizer

DENIED = [
    'SELECT current_ability FROM player',
    'SELECT * FROM player',
    'SELECT * FROM person',
    'SELECT * FROM player_view',
    'SELECT idx, (SELECT current_ability FROM player p WHERE p.idx = m.idx) FROM m_player_view m',
    'SELECT * FROM (SELECT current_ability FROM player)',
    'WITH x AS (SELECT current_ability FROM player) SELECT * FROM x',
    'WITH m_player_view AS (SELECT current_ability FROM player) SELECT * FROM m_player_view',
    'WITH player_view AS (SELECT current_ability FROM player) SELECT * FROM player_view',
    'WITH m_scouted_player_view AS (SELECT * FROM main.player) SELECT * FROM m_scouted_player_view',
    'SELECT m.idx, p.current_ability FROM m_player_view m JOIN player p USING (idx)',
    'SELECT idx FROM m_player_view WHERE idx IN (SELECT idx FROM player WHERE current_ability > 120)',
    'SELECT idx FROM m_player_view m WHERE EXISTS (SELECT 1 FROM player p WHERE p.idx = m.idx AND p.passing > 10)',
    'SELECT idx FROM m_player_view UNION SELECT current_ability FROM player',
    'SELECT * FROM main.player',
    'SELECT count(*) FROM player WHERE current_ability > 100',
    'SELECT 1 FROM player ORDER BY current_ability',
    'SELECT rowid FROM player',
    'SELECT max(potential_ability) FROM player',
    'SELECT * FROM sqlite_master',
    'SELECT * FROM sqlite_temp_master',
    'SELECT * FROM temp.sqlite_master',
    'SELECT * FROM sqlite_schema',
    'SELECT * FROM kn.sqlite_master',
    'SELECT * FROM pragma_table_list',
    "SELECT * FROM pragma_table_info('m_player_view')",
    'PRAGMA table_list',
    "ATTACH DATABASE ':memory:' AS z",
    'DETACH DATABASE kn',
    'CREATE TEMP TABLE t AS SELECT * FROM m_player_view',
    'CREATE TEMP VIEW v AS SELECT * FROM player',
    'INSERT INTO m_columns VALUES (1,2,3,4,5,6)',
    'DELETE FROM m_coverage',
]


@pytest.mark.parametrize('sql', DENIED)
def test_bypass_attempts_are_denied(con, sql):
    with pytest.raises(sqlite3.DatabaseError):
        con.execute(sql).fetchall()


def test_private_view_needs_public_context(con):
    assert all(not n.startswith(mv.PRIVATE_PREFIX) for n in con.manager_info['public_views'])
    # Even knowing the private name, a top-level read of it is denied (needs a public view as context)
    con.set_authorizer(None)
    name = con.execute("SELECT name FROM temp.sqlite_master WHERE name LIKE '\\_mv\\_%' ESCAPE '\\' "
                       "AND name LIKE '%m_player_view'").fetchone()[0]
    public = set(con.manager_info['public_views'])
    private = {r[0] for r in con.execute("SELECT name FROM temp.sqlite_master WHERE name LIKE '\\_mv\\_%' ESCAPE '\\'")}
    con.set_authorizer(mv._authorizer(public, private))
    with pytest.raises(sqlite3.DatabaseError):
        con.execute(f'SELECT current_ability FROM "{name}"').fetchall()
    # ... and naming a CTE after it is rejected before execution
    with pytest.raises(mv.ManagerViewError):
        mv.check_sql(f'WITH "{name}" AS (SELECT current_ability FROM player) SELECT * FROM "{name}"')


ALLOWED = [
    'SELECT * FROM m_player_view',
    'SELECT current_ability, potential_ability FROM m_player_view',
    'SELECT idx FROM m_player_view WHERE idx IN (SELECT idx FROM m_scouted_player_view)',
    'WITH x AS (SELECT idx, passing_min FROM m_player_view) SELECT * FROM x WHERE passing_min > 5',
    'WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 3) SELECT * FROM n',
    'SELECT idx, rank() OVER (ORDER BY passing_max DESC) FROM m_player_view',
    'SELECT * FROM kn.knowledge_player',
    'SELECT * FROM knowledge_attribute LIMIT 3',
    'SELECT * FROM m_columns',
    'SELECT * FROM m_coverage',
    'SELECT * FROM _fields',
    "SELECT value FROM json_each('[1,2]')",
    'SELECT m.idx, p.wage FROM m_player_view m JOIN m_person p USING (idx)',
]


@pytest.mark.parametrize('sql', ALLOWED)
def test_allowed_queries(con, sql):
    con.execute(sql).fetchall()


def test_table_level_access_exposes_row_count_only(con):
    # SQLite reports a table read with no column (e.g. count(*)) without view context; it is
    # allowed because it carries no column value.
    assert con.execute('SELECT count(*) FROM player').fetchone()[0] == 5


def test_masked_values_through_every_shape(con):
    shapes = [
        'SELECT current_ability FROM m_player_view',
        'WITH c AS (SELECT * FROM m_player_view) SELECT current_ability FROM c',
        'SELECT current_ability FROM (SELECT * FROM m_player_view)',
        'SELECT (SELECT max(current_ability) FROM m_player_view)',
    ]
    for sql in shapes:
        assert all(v is None for v, in con.execute(sql).fetchall()), sql


def test_explain_does_not_reveal_private_names(con):
    for sql in ('SELECT * FROM m_player_view', 'SELECT count(*) FROM m_player_view GROUP BY club',
                'SELECT * FROM m_scouted_player_view ORDER BY passing_max'):
        for prefix in ('EXPLAIN QUERY PLAN ', 'EXPLAIN '):
            text = ' '.join(str(c) for r in con.execute(prefix + sql).fetchall() for c in r)
            assert mv.PRIVATE_PREFIX not in text
        with pytest.raises(mv.ManagerViewError):
            mv.check_sql('EXPLAIN ' + sql)


# ----------------------------------------------------------------------------- SQL checks

@pytest.mark.parametrize('sql', [
    '', '   ', 'PRAGMA table_list', 'EXPLAIN SELECT 1', "ATTACH 'x' AS y", 'SELECT 1; SELECT 2',
    'SELECT 1; DROP TABLE x', 'DELETE FROM m_columns', 'SELECT * FROM _mv_abc', 'SELECT * FROM "_MV_abc"',
    'SELECT * FROM [_mv_x]',
])
def test_check_sql_rejects(sql):
    with pytest.raises(mv.ManagerViewError):
        mv.check_sql(sql)


@pytest.mark.parametrize('sql', [
    'SELECT 1', 'select 1;', "SELECT ';' AS x", '-- c\nSELECT 1 /* ; */', "SELECT '_mv_' AS s",
    'WITH a AS (SELECT 1) SELECT * FROM a', 'VALUES (1)',
])
def test_check_sql_accepts(sql):
    mv.check_sql(sql)


def test_limited_to_scouted():
    assert mv.limited_to_scouted('SELECT * FROM m_scouted_player_view')
    assert mv.limited_to_scouted('SELECT * FROM m_player_view WHERE scouted = 1 AND passing_min > 3')
    assert not mv.limited_to_scouted('SELECT * FROM m_player_view WHERE scouted = 1 OR club = 1')
    assert not mv.limited_to_scouted('SELECT * FROM m_player_view')
    assert not mv.limited_to_scouted('SELECT * FROM m_scouted_player_view UNION SELECT * FROM m_player_view')


# ----------------------------------------------------------------------------- prepare (offline)

def test_prepare_offline_reports_partial_then_complete(env):
    snap, store = env
    q = mv.prepare_manager_query({'snapshot': snap, 'knowledge': store.path}, 'SELECT * FROM m_player_view')
    try:
        assert not q.complete and q.message.startswith('PARTIAL')
        assert q.coverage['universe_players'] == 5 and q.coverage['universe_players_covered'] == 4
        assert '4 of 5 players' in q.message
        assert q.coverage['snapshot_rows'] == 5 and q.coverage['snapshot_rows_covered'] == 4
        assert dict(q.connection.execute('SELECT key, value FROM m_coverage').fetchall())['complete'] == 0
    finally:
        q.connection.close()
    q = mv.prepare_manager_query((snap, store.path), 'SELECT * FROM m_scouted_player_view')
    try:
        assert q.complete and q.limited_to_scouted and q.coverage['scouted_rows'] == 2
    finally:
        q.connection.close()
    store.write_rows([row(5, 'range', value=15)], tier=3, ident=IDENT)
    q = mv.prepare_manager_query((snap, store.path), 'SELECT * FROM m_player_view')
    try:
        assert q.complete and q.message.startswith('Complete') and '5 players' in q.message
        assert 'outside' not in q.message
        assert q.connection.execute('SELECT count(*) FROM m_player_view').fetchone()[0] == 5
    finally:
        q.connection.close()
    # a snapshot player outside the native player list is named in the message and never shown
    c = sqlite3.connect(snap)
    c.execute("INSERT INTO person(idx, first_name) VALUES (6, 'Virtual')")
    c.execute('INSERT INTO player(idx) VALUES (6)')
    c.commit()
    c.close()
    q = mv.prepare_manager_query((snap, store.path), 'SELECT * FROM m_player_view')
    try:
        assert q.complete and '1 of 6 snapshot player_view rows are outside' in q.message
    finally:
        q.connection.close()


def test_prepare_rejects_bad_sql_and_empty_store(env, tmp_path):
    snap, store = env
    with pytest.raises(mv.ManagerViewError):
        mv.prepare_manager_query((snap, store.path), 'SELECT 1; SELECT 2')
    store.begin_epoch(DATE)                       # nothing confirmed in the new epoch
    with pytest.raises(mv.ManagerViewError, match='no current rows'):
        mv.prepare_manager_query((snap, store.path), 'SELECT * FROM m_player_view')


def test_nested_view_dependency_refused(tmp_path):
    snap = tmp_path / 'snapshot.sqlite'
    make_snapshot(snap)
    c = sqlite3.connect(snap)
    c.execute('DROP VIEW player_view')
    c.execute('CREATE VIEW inner_v AS SELECT * FROM player')
    c.execute('CREATE VIEW player_view AS SELECT * FROM inner_v')
    c.commit()
    c.close()
    store = ks.KnowledgeStore(tmp_path / 'knowledge.sqlite')
    store.ensure_identity(IDENT)
    with pytest.raises(mv.ManagerViewError, match='depends on other views'):
        mv.open_manager_connection(snap, store.path)
    store.close()


# ----------------------------------------------------------------------------- epochs

def test_new_game_date_starts_an_epoch_and_keeps_the_rows(env):
    snap, store = env
    before = store.epoch()['id']
    result = store.ensure_identity(dict(IDENT, game_date='2030-12-11'))
    assert not result['invalidated'] and result['new_epoch'] and store.epoch()['id'] == before + 1
    assert store.game_date() == '2030-12-11'
    # the rows and their cells are still stored, none is current, and the view shows none
    assert store.con.execute('SELECT count(*) FROM knowledge_player').fetchone()[0] == 4
    assert store.con.execute('SELECT count(*) FROM knowledge_attribute').fetchone()[0] == 4 * 47
    assert store.coverage()['knowledge_rows'] == 0 and store.lacking([1, 2, 3, 4, 5]) == [1, 2, 3, 4, 5]
    c = mv.open_manager_connection(snap, store.path)
    try:
        assert c.execute('SELECT count(*) FROM m_player_view').fetchone()[0] == 0
    finally:
        c.close()
    assert not {n for n, in store.con.execute("SELECT name FROM sqlite_master WHERE name LIKE 'stale_%'")}


def test_save_or_coach_change_drops_everything(env):
    _, store = env
    result = store.ensure_identity(dict(IDENT, coach='Someone Else'))
    assert result['invalidated'] and result['reason'] == 'save or coach changed'
    for table in ('knowledge_player', 'knowledge_attribute', 'knowledge_wide', 'knowledge_input',
                  'knowledge_group', 'knowledge_seed', 'knowledge_universe'):
        assert store.con.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0


def test_manager_view_refuses_mismatched_live_date(env, monkeypatch):
    snap, store = env
    monkeypatch.setattr(ks, 'cache_root', lambda: snap.parent.parent)

    class FakeEngine:
        def save_info(self):
            class I:
                save_key, game_date = snap.parent.name, '2030-12-11'
            return I()
    with pytest.raises(mv.ManagerViewError, match='game is on 2030-12-11'):
        mv.prepare_manager_query(FakeEngine(), 'SELECT * FROM m_player_view')


def test_no_background_fill():
    for name in ('start_background_fill', 'stop_background_fill', 'fill_status'):
        assert not hasattr(ks, name)


# ----------------------------------------------------------------------------- on-demand builder

class FakeGame:
    """Stands in for the live engine: dates, captures with fingerprints, rejections.

    A fingerprint here is the player's `version`; `changed` bumps it, which is what a changed
    consumed byte does to a real fingerprint."""

    def __init__(self, universe, date=DATE):
        self.universe, self.date = universe, date
        self.calls, self.fail_changed, self.poison = [], 0, set()
        self.roll_after = None
        self.noded, self.star_calls, self.search_calls, self.natives = {150}, [], [], []
        self.star_date, self.pipe_once = None, False
        self.version = {}
        self.context = 'process-1'

    def changed(self, *idxs):
        for i in idxs:
            self.version[i] = self.version.get(i, 0) + 1

    def stars(self, target, keys, coach_name=None):
        self.star_calls.append(list(keys))
        return dict(current_date=self.star_date or self.date,
                    players={k: (2.5, 3.5, 'range', 3.0, 4.0, 'range') for k in keys})

    def search(self, target, keys, coach_name=None):
        self.search_calls.append(list(keys))
        return dict(current_date=self.date, players={k: int(k % 7 != 0) for k in keys})

    def identity(self, target, coach_name=None):
        return dict(IDENT, game_date=self.date)

    def capture(self, target, keys, coach_name=None, native=True, plan=None):
        self.natives.append(native)
        if self.pipe_once:
            self.pipe_once = False
            raise BridgeError('Bulk knowledge query rejected; no partial result returned: Native read stream '
                              'rejected: [Errno 32] Broken pipe')
        if self.roll_after is not None and len(self.calls) >= self.roll_after:
            self.date, self.roll_after = '2030-12-11', None
            raise BridgeError('Bulk knowledge query rejected; no partial result returned: Selected context changed')
        if self.fail_changed:
            self.fail_changed -= 1
            raise BridgeError('Bulk knowledge query rejected; no partial result returned: Final world differs; changed')
        if self.poison & set(keys):
            raise BridgeError('Bulk knowledge query rejected; no partial result returned: journal budget')
        context, stored, _ = plan if plan is not None else (None, {}, {})
        digest = lambda k: bytes([self.version.get(k, 0)])
        kept = [k for k in keys if context == self.context and k in stored and stored[k]['digest'] == digest(k)]
        todo = [k for k in keys if k not in kept]
        self.calls.append(list(todo))
        return dict(save=dict(current_date=self.date),
                    rows=[row(k, 'range', value=11 + self.version.get(k, 0), node=30 if k in self.noded else None)
                          for k in todo],
                    inputs=dict(context=self.context, kept=kept, groups={},
                                players={k: dict(spans=b'', digest=digest(k), groups=[], facts=[]) for k in todo}))

    def population(self, target, coach_name=None, evaluate=False):
        return dict(save=dict(current_date=self.date),
                    seeds=dict(fow_nodes=self.universe[:3], report_primary=self.universe[2:5], report_alternate=[],
                               own_club_rosters=[self.universe[0]]))


@pytest.fixture
def game(monkeypatch, tmp_path):
    g = FakeGame(list(range(100, 160)))
    monkeypatch.setattr(ks, 'live_identity', g.identity)
    monkeypatch.setattr(ks, 'capture', g.capture)
    monkeypatch.setattr(ks, 'player_universe', lambda target: dict(indices=g.universe, players=len(g.universe),
                                                                    vector_slots=len(g.universe), seconds=0.0))
    monkeypatch.setattr(kb, 'known_population', g.population)
    monkeypatch.setattr(ks, 'star_capture', g.stars)
    monkeypatch.setattr(ks, 'search_capture', g.search)
    monkeypatch.setattr(ks.KnowledgeBuilder, '_require_space', lambda self, what: None)
    store = ks.KnowledgeStore(tmp_path / 'knowledge.sqlite')
    yield g, store
    store.close()


def evaluated(g):
    return sorted(k for call in g.calls for k in call)


def test_only_what_is_asked_is_computed(game):
    g, store = game
    b = ks.KnowledgeBuilder(object(), store, chunk_size=7)
    assert b.scouted()['computed'] == 5
    assert evaluated(g) == g.universe[:5] and store.coverage()['knowledge_rows'] == 5
    assert store.coverage()['tier1_complete'] and not store.coverage()['tier3_complete']
    assert ks.ensure_knowledge(object(), store, [150, 151, 100]) == dict(
        requested=3, computed=2, confirmed=0, seconds=pytest.approx(0, abs=5))
    assert evaluated(g) == g.universe[:5] + [150, 151]
    assert ks.lacking_knowledge(store, [100, 150, 152]) == [152]
    assert len(ks.lacking_knowledge(store)) == 0            # no universe was asked for yet
    cov = b.everything()
    assert cov['universe_players'] == 60 and cov['universe_players_covered'] == 60 and cov['tier3_complete']
    assert evaluated(g) == g.universe                      # each player exactly once
    assert store.con.execute('SELECT count(*) FROM knowledge_attribute').fetchone()[0] == 60 * 47
    assert store.con.execute('SELECT count(*) FROM knowledge_player WHERE scouted = 1').fetchone()[0] == 5


def test_new_epoch_confirms_unchanged_rows_and_recomputes_changed(game):
    g, store = game
    b = ks.KnowledgeBuilder(object(), store)
    b.ensure(range(100, 120))
    g.calls.clear()
    assert b.ensure(range(100, 120))['computed'] == 0 and g.calls == []        # same epoch: not looked at
    g.changed(105, 111)
    g.date = '2030-12-11'                                                       # a new game day
    b.refresh_identity()
    assert store.lacking(range(100, 120)) == list(range(100, 120))
    result = b.ensure(range(100, 120))
    assert (result['computed'], result['confirmed']) == (2, 18) and g.calls == [[105, 111]]
    rows = dict(store.con.execute('SELECT idx, game_date FROM knowledge_player'))
    assert set(rows.values()) == {'2030-12-11'}
    values = dict(store.con.execute("SELECT idx, min FROM knowledge_attribute WHERE field = 'Passing'"))
    assert values[105] == 10 and values[100] == 9          # 105 re-evaluated (value 12), 100 kept (value 11)
    # another process (new context): every fingerprint is void
    g.context = 'process-2'
    g.calls.clear()
    b.refresh_identity(new_epoch=True)
    assert b.ensure(range(100, 104))['computed'] == 4 and g.calls == [[100, 101, 102, 103]]


def test_epoch_ages_out(game, monkeypatch):
    g, store = game
    b = ks.KnowledgeBuilder(object(), store, epoch_seconds=10)
    b.ensure([100])
    assert not b.refresh_identity().get('new_epoch')
    clock = ks.time.time()
    monkeypatch.setattr(ks.time, 'time', lambda: clock + 11)
    assert b.refresh_identity()['new_epoch'] and store.lacking([100]) == [100]


def test_rejected_capture_is_retried(game):
    g, store = game
    g.fail_changed = 2
    b = ks.KnowledgeBuilder(object(), store, chunk_size=100)
    b.scouted()
    assert store.coverage()['knowledge_rows'] == 5 and len(g.calls) == 1


def test_day_change_mid_ensure_starts_a_new_epoch_and_finishes(game):
    g, store = game
    b = ks.KnowledgeBuilder(object(), store, chunk_size=10)
    g.roll_after = 2                         # the third chunk sees the day roll over
    b.ensure(g.universe)
    assert store.game_date() == '2030-12-11' and store.meta('last_day_change')
    assert store.lacking(g.universe) == []
    assert {d for d, in store.con.execute('SELECT DISTINCT game_date FROM knowledge_player')} == {'2030-12-11'}
    # the chunks written before the roll were confirmed from their fingerprints, not recomputed
    assert evaluated(g) == g.universe


def test_persistently_failing_player_is_isolated(game):
    g, store = game
    g.poison = {130}
    b = ks.KnowledgeBuilder(object(), store, chunk_size=16)
    b.ensure(g.universe)
    assert store.lacking(g.universe) == []
    bad = store.con.execute('SELECT unavailable_n, unavailable_reason FROM knowledge_player WHERE idx=130').fetchone()
    assert bad[0] == 47 and bad[1].startswith('capture_rejected')
    assert store.con.execute('SELECT count(*) FROM knowledge_player WHERE unavailable_n = 47').fetchone()[0] == 1


def test_systematic_failure_stops_instead_of_bisecting_forever(game, monkeypatch):
    g, store = game
    g.poison = set(g.universe)
    monkeypatch.setattr(ks, 'MAX_ISOLATED_FAILURES', 3)
    b = ks.KnowledgeBuilder(object(), store, chunk_size=16)
    with pytest.raises(ks.KnowledgeError, match='keep failing'):
        b.ensure(g.universe)


def test_stars_and_search_rules(game):
    g, store = game
    b = ks.KnowledgeBuilder(object(), store)
    b.ensure([100, 101, 150, 151])                              # 100, 101 named population; 150 has a node
    b.seeds()
    assert store.lacking([100, 101, 150, 151], stars=True) == [100, 101, 150, 151]
    assert b.ensure_stars([100, 101, 150, 151]) == dict(stars=3, search=2)
    assert g.star_calls == [[100, 101, 150]] and g.search_calls == [[100, 101]]
    r = {i: (s, p) for i, s, p in store.con.execute('SELECT idx, ca_stars_state, in_player_search FROM knowledge_player')}
    assert r[100] == ('range', 1) and r[150] == ('range', None) and r[151] == ('not_computed', None)
    assert store.lacking([100, 101, 150, 151], stars=True) == []
    assert b.ensure_stars([100, 150, 151]) == dict(stars=0, search=0)       # current: nothing to do
    assert b.ensure_stars([100], search=[100]) == dict(stars=0, search=0)
    b.refresh_identity(new_epoch=True)
    b.ensure([151])
    assert b.ensure_stars([151], search=[151]) == dict(stars=0, search=1)   # asked for by index


def test_native_switch_drops_the_rows(game):
    g, store = game
    ks.KnowledgeBuilder(object(), store).ensure([100, 101])
    b = ks.KnowledgeBuilder(object(), store, native=False)
    assert b.refresh_identity()['reason'] == 'capture options changed'
    assert store.con.execute('SELECT count(*) FROM knowledge_player').fetchone()[0] == 0
    b.ensure([100])
    assert g.natives[-1] is False


def test_star_date_mismatch_and_broken_pipe_are_retried(game):
    g, store = game
    b = ks.KnowledgeBuilder(object(), store)
    g.pipe_once = True
    b.ensure([100, 101])
    assert store.lacking([100, 101]) == []
    b.seeds()
    g.star_date = '2030-12-11'
    with pytest.raises(ks.DayChanged):
        b.ensure_stars([100, 101])


# ----------------------------------------------------------------------------- on-demand statements

def _on_demand(game, tmp_path, sql, **kwargs):
    g, store = game
    snap = tmp_path / 'snapshot.sqlite'
    if not snap.exists():
        make_snapshot(snap, people=range(100, 160))
    g.calls.clear()
    g.star_calls.clear()
    q = mv.prepare_manager_query((snap, store.path), sql, bridge_or_session=object(), **kwargs)
    try:
        cur = q.connection.execute(sql)
        names = [d[0] for d in cur.description]
        return q, [dict(zip(names, r)) for r in cur.fetchall()]
    finally:
        q.connection.close()


def test_statement_on_public_columns_computes_nothing(game, tmp_path):
    g, _ = game
    q, rows = _on_demand(game, tmp_path, 'SELECT idx, first_name FROM m_player_view WHERE idx < 110 ORDER BY idx')
    assert [r['idx'] for r in rows] == list(range(100, 110)) and g.calls == [] and q.complete
    assert q.coverage['on_demand']['evaluated'] == 0


def test_statement_computes_only_the_rows_it_reads(game, tmp_path):
    g, _ = game
    q, rows = _on_demand(game, tmp_path,
                         'SELECT idx, passing_min FROM m_player_view WHERE idx BETWEEN 120 AND 124 ORDER BY idx')
    assert [r['passing_min'] for r in rows] == [9] * 5 and evaluated(g) == [120, 121, 122, 123, 124]
    assert q.complete and q.coverage['on_demand']['passes'] == 2
    # the same statement again in the same epoch: nothing to do, one pass
    q, rows = _on_demand(game, tmp_path,
                         'SELECT idx, passing_min FROM m_player_view WHERE idx BETWEEN 120 AND 124 ORDER BY idx')
    assert g.calls == [] and q.coverage['on_demand']['passes'] == 1 and len(rows) == 5


def test_scouted_view_reaches_only_the_named_population(game, tmp_path):
    g, _ = game
    q, rows = _on_demand(game, tmp_path, 'SELECT idx, passing_max, scouted FROM m_scouted_player_view ORDER BY idx')
    assert [r['idx'] for r in rows] == [100, 101, 102, 103, 104] and evaluated(g) == [100, 101, 102, 103, 104]
    assert {r['scouted'] for r in rows} == {1} and q.limited_to_scouted and q.complete


def test_star_columns_are_computed_for_the_rows_that_read_them(game, tmp_path):
    g, _ = game
    q, rows = _on_demand(game, tmp_path, 'SELECT idx, current_ability_stars_max FROM m_player_view '
                                         'WHERE idx IN (100, 150, 151) ORDER BY idx')
    assert [r['current_ability_stars_max'] for r in rows] == [3.5, 3.5, None]
    assert g.star_calls == [[100, 150]] and evaluated(g) == [100, 150, 151] and q.complete


def test_statement_over_every_row_computes_the_universe_once(game, tmp_path):
    g, store = game
    q, rows = _on_demand(game, tmp_path, 'SELECT count(*) AS n FROM m_player_view WHERE passing_min >= 9')
    assert rows == [dict(n=60)] and evaluated(g) == g.universe and q.complete
    assert store.coverage()['tier3_complete']


def test_limit_reads_no_further_than_the_fetch(game, tmp_path, monkeypatch):
    g, _ = game
    monkeypatch.setattr(mv, 'PROBE_BATCH', 2)        # query.fetch reads batches until past max_rows
    q, rows = _on_demand(game, tmp_path, 'SELECT idx, passing_min FROM m_player_view', max_rows=3)
    assert evaluated(g)[:4] == [100, 101, 102, 103] and len(evaluated(g)) <= 6 and q.complete
    assert [r['passing_min'] for r in rows[:4]] == [9, 9, 9, 9]


def test_old_schema_store_is_rebuilt(tmp_path):
    path = tmp_path / 'knowledge.sqlite'
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE _knowledge_meta(key TEXT PRIMARY KEY, value TEXT)')
    con.execute("INSERT INTO _knowledge_meta VALUES ('schema_version', '1'), ('identity', ?)",
                ('{"save_key": "career-x", "game_date": "2030-12-10"}',))
    con.execute('CREATE TABLE knowledge_player(idx INTEGER PRIMARY KEY, k INTEGER, game_date TEXT)')
    con.execute("INSERT INTO knowledge_player VALUES (1, 5, '2030-12-10')")
    con.execute('CREATE TABLE stale_knowledge_player(idx INTEGER)')
    con.commit()
    con.close()
    store = ks.KnowledgeStore(path)
    try:
        assert store.rebuilt_from == 1 and store.meta('schema_version') == ks.SCHEMA_VERSION
        assert store.meta('rebuilt_from_schema') == 1 and store.identity() is None
        assert store.con.execute('SELECT count(*) FROM knowledge_player').fetchone()[0] == 0
        cols = {r[1] for r in store.con.execute('PRAGMA table_info(knowledge_player)')}
        assert {'ca_stars_min', 'pa_stars_state', 'in_player_search'} <= cols
        assert not store.con.execute("SELECT name FROM sqlite_master WHERE name LIKE 'stale_%'").fetchall()
    finally:
        store.close()
    again = ks.KnowledgeStore(path)          # a current store is left alone
    assert again.rebuilt_from is None
    again.close()


def test_stars_in_manager_view(con):
    r = {x['idx']: x for x in fetch(con, 'SELECT * FROM m_player_view')}
    assert (r[1]['current_ability_stars_min'], r[1]['current_ability_stars_max']) == (3.5, 3.5)
    assert (r[1]['potential_ability_stars_min'], r[1]['potential_ability_stars_max']) == (4.0, 4.5)
    assert (r[2]['current_ability_stars_min'], r[2]['current_ability_stars_max'],
            r[2]['current_ability_stars_state']) == (2.0, 3.0, 'range')
    assert (r[3]['current_ability_stars_min'], r[3]['current_ability_stars_state']) == (None, 'unknown')
    assert r[4]['potential_ability_stars_state'] == 'not_computed'
    assert (r[1]['in_player_search'], r[3]['in_player_search'], r[4]['in_player_search']) == (1, 0, None)
    assert r[2]['current_ability'] is None                         # the number itself stays hidden
    scouted = {x['idx']: x for x in fetch(con, 'SELECT * FROM m_scouted_player_view')}
    assert scouted[2]['potential_ability_stars_max'] == 4.0
    policies = dict(con.execute("SELECT column_name, policy FROM m_columns WHERE view='m_player_view'").fetchall())
    assert policies['current_ability_stars_min'] == 'knowledge'


# ----------------------------------------------------------------------------- capture flattening

def test_player_row_from_engine_subject():
    k = dict(failure=None, own_context=False, category=3, score=30, score_failure=None, reciprocal=30,
             node_present=True, context_k=12, context_k_failure=None, report_present=False, report=None,
             person_index=77, age=None, assessor_bytes=None, range_failure=None, range_inputs=True)
    fields = [dict(native_field_id=i, name=f['name'], state='range', minimum=8, maximum=12)
              for i, f in enumerate(codes.FIELDS)]
    fields[0] = dict(native_field_id=0, name='Aerial Reach', state='exact', value=14)
    fields[1] = dict(native_field_id=1, name='Command Of Area', state='unknown')
    fields[2] = dict(native_field_id=2, name='Communication', state='unavailable', reason='unavailable_source',
                     detail='x')
    subject = dict(key=77, native_identity=dict(database_index=77), knowledge=k, fields=fields)
    r, needs = ks.player_row(subject)
    assert not needs and r['idx'] == 77 and r['node_score'] == 30 and r['sources'] == 'node'
    assert (r['exact_n'], r['range_n'], r['unknown_n'], r['unavailable_n']) == (1, 44, 1, 1)
    assert r['cells'][0] == dict(state='exact', value=14, min=14, max=14, reason=None)
    assert r['cells'][3] == dict(state='range', value=None, min=8, max=12, reason=None)
    assert r['unavailable_reason'] == 'unavailable_source: x'
    assert (r['ca_gate'], r['pa_gate']) == (kb.ability_state(k, 0x62)[0], kb.ability_state(k, 0x63)[0])
    # zero thresholds everywhere: the cells capture has no H score, the gates need a summary capture
    r, needs = ks.player_row(dict(subject, knowledge=dict(k, score=None)))
    assert needs and r['ca_gate'] is None


def test_field_codes_table():
    assert len(codes.FIELDS) == 47 and len(codes.VISIBLE_CODES) == 47 and len(codes.SCALED_CODES) == 47
    assert not (codes.VISIBLE_CODES & codes.HIDDEN_ATTRIBUTE_CODES)
    assert codes.BY_NAME['Off The Ball']['code'] == 'Potb' and codes.BY_NAME['Vision']['code_100'] == 'PDvs'


def test_other_schema_writer_is_refused_and_reset_recovers(env):
    _, store = env
    store.set_meta({'schema_version': 2})          # an older knowledge_store wrote here meanwhile
    with pytest.raises(ks.KnowledgeError, match='another knowledge_store'):
        store.ensure_identity(IDENT)
    with pytest.raises(ks.KnowledgeError, match='another knowledge_store'):
        store.write_rows([row(9, 'unknown')], tier=2, ident=IDENT)
    store.reset()
    assert store.identity() is None and store.meta('schema_version') == ks.SCHEMA_VERSION
    assert store.ensure_identity(IDENT)['invalidated'] and store.coverage()['knowledge_rows'] == 0


# ----------------------------------------------------------------------------- on-demand cells (tools.manager_prewarm)

class PeopleEngine:
    """What `ondemand.Session` uses of an engine, over the five people of the synthetic snapshot.
    First name (public), wage (own club) and current ability (never shown) are on-demand columns;
    the getter reads them from each person's record and the VM records every call."""
    RECORDS = 0x2_0000_0000
    OFFSETS = {'Pfna': 0, 'Pcbx': 4, 'PCAB': 8}

    def __init__(self):
        import struct
        import threading
        from types import SimpleNamespace
        from fm_live_mcp.fmdb import fastvm
        from _fmdb_fake import FakeMemory, FakeTrackedVM, FakeVM, field
        self.lock = threading.RLock()
        self.memory = FakeMemory()
        self.catalog = SimpleNamespace(enums={}, record_types={
            'pers': SimpleNamespace(field_list=[field('Pfna', 'First Name', 'string'),
                                                field('Pcbx', 'Wage', 'integer')]),
            'play': SimpleNamespace(field_list=[field('PCAB', 'Current Ability', 'integer')])})
        self.pointers = [0] + [self.RECORDS + idx * 0x100 for idx in sorted(PEOPLE)]
        for idx, (_, ca, _, _) in PEOPLE.items():
            self.memory.load(self.pointers[idx], struct.pack('<iii', idx, 50000 + idx, ca))
        self.vm = FakeVM(self)
        self.tracked_vm = FakeTrackedVM(self) if fastvm.tracks_reads() else None
        self.getter_vm = self.tracked_vm or self.vm

    @classmethod
    def getter(cls, load, record, code):
        import struct
        from fm_live_mcp.fmdb.vm import CallStats, PropertyResult
        stats = CallStats(seconds=0.00001)
        if code not in cls.OFFSETS:
            return PropertyResult(code, None, 'null', False, stats)
        value = struct.unpack('<i', load(record + cls.OFFSETS[code], 4))[0]
        if code == 'Pfna':
            return PropertyResult(code, f'P{value}', 'string', True, stats)
        return PropertyResult(code, value, 'int', True, stats)

    def cached_read(self, address, length):
        return self.memory.cached_read(address, length)

    def prefetch(self, records, before=0x400, after=0x800):
        self.memory.prefetch([(r - before, before + after) for r in records if r])

    def refresh_memory(self):
        self.memory.invalidate()
        self.getter_vm.invalidate()

    def calls(self, code):
        """idx values the getter was called for with `code`, in call order."""
        return [self.pointers.index(record) for record, c in self.getter_vm.calls if c == code]


def make_on_demand(snap, engine):
    """Turn person.first_name, person.wage and player.current_ability of the synthetic snapshot
    into on-demand columns (NULL until computed), with the tables `ondemand.Session` reads."""
    from fm_live_mcp.fmdb import freshness, snapshot
    con = sqlite3.connect(snap)
    con.executescript(freshness.FRESH_SQL)
    con.execute('CREATE TABLE _column_state(table_name TEXT, column_name TEXT, class TEXT, rows INTEGER, source TEXT, '
                'status TEXT, ms_per_row REAL, note TEXT, missing_json TEXT, '
                'PRIMARY KEY(table_name, column_name, class))')
    con.executemany("INSERT INTO _column_state VALUES (?, ?, 'ACTUAL_PLAYER', 5, 'emulated', 'on_demand', 1.0, '', '{}')",
                    [('person', 'first_name'), ('person', 'wage'), ('player', 'current_ability')])
    con.execute('UPDATE person SET first_name = NULL, wage = NULL')
    con.execute('UPDATE player SET current_ability = NULL')
    n = len(engine.pointers)
    uids = [None] + [1000 + idx for idx in range(1, n)]
    freshness.save_live(con, {'people': snapshot.LiveTable('people', list(engine.pointers), ('people', n),
                                                           [''] + ['ACTUAL_PLAYER'] * (n - 1), uids, list(uids))})
    con.commit()
    con.close()


def test_prewarm_computes_only_the_cells_the_manager_view_can_show(env, monkeypatch):
    from types import SimpleNamespace
    from fm_live_mcp.fmdb import tools
    snap, store = env
    engine = PeopleEngine()
    make_on_demand(snap, engine)
    monkeypatch.setattr(tools, '_knowledge_path', lambda e: store.path)
    tracking = engine.tracked_vm is not None

    def manager(sql):
        """One manager-view statement as tools.manager_query runs it: a masked connection, the
        prewarm, then the statement on that connection. Returns (prewarm result, rows)."""
        con = mv.open_manager_connection(snap, store.path, coverage=store.coverage())
        try:
            if sql.startswith('SELECT *'):
                policy = dict(con.execute("SELECT column_name, policy FROM m_columns WHERE view='m_player_view'"))
                assert (policy['first_name'], policy['wage'], policy['current_ability']) == \
                    (mv.PUBLIC, mv.OWN_CLUB, mv.NEVER)
            computed = tools.manager_prewarm(engine, snap, sql, SimpleNamespace(connection=con))
            return computed, [(r['idx'], r.get('first_name'), r.get('wage'), r.get('current_ability'))
                              for r in fetch(con, sql)]
        finally:
            con.close()

    def stored():
        """(idx with a first name, idx with a wage, current-ability cells) in the snapshot file."""
        raw = sqlite3.connect(f'file:{snap}?mode=ro', uri=True)
        try:
            return ([r[0] for r in raw.execute('SELECT idx FROM person WHERE first_name IS NOT NULL ORDER BY idx')],
                    [r[0] for r in raw.execute('SELECT idx FROM person WHERE wage IS NOT NULL ORDER BY idx')],
                    raw.execute('SELECT COUNT(current_ability) FROM player').fetchone()[0])
        finally:
            raw.close()

    # `*` on a masked view computes nothing
    computed, rows = manager('SELECT * FROM m_player_view ORDER BY idx')
    assert computed is None and engine.getter_vm.calls == [] and stored() == ([], [], 0)
    assert rows == [(i, None, None, None) for i in (1, 2, 3, 4)]

    # limited to the scouted players: a public column for those, an own-club column for the own player
    computed, rows = manager('SELECT idx, first_name, wage, current_ability FROM m_scouted_player_view ORDER BY idx')
    assert computed == {'cells': 3}
    assert sorted(engine.calls('Pfna')) == [1, 2] and engine.calls('Pcbx') == [1] and engine.calls('PCAB') == []
    assert stored() == ([1, 2], [1], 0)
    assert rows == [(1, 'P1', 50001, None), (2, 'P2', None, None)]

    # every player the view can show (those with a knowledge row: 1..4; player 5 has none)
    computed, rows = manager('SELECT idx, first_name, wage, current_ability FROM m_player_view ORDER BY idx')
    assert set(engine.calls('Pfna')) == {1, 2, 3, 4} and set(engine.calls('Pcbx')) == {1}
    assert engine.calls('PCAB') == [] and stored() == ([1, 2, 3, 4], [1], 0)
    if tracking:                                        # the cells of the first statement were kept
        assert computed == {'cells': 2} and sorted(engine.calls('Pfna')) == [1, 2, 3, 4]
        assert engine.calls('Pcbx') == [1]
    assert rows == [(1, 'P1', 50001, None), (2, 'P2', None, None), (3, 'P3', None, None), (4, 'P4', None, None)]

    # a never column named alone, and `*` again: no getter call; `*` shows the cells already stored
    calls = len(engine.getter_vm.calls)
    computed, withheld = manager('SELECT idx, current_ability FROM m_player_view ORDER BY idx')
    assert computed is None and withheld == [(i, None, None, None) for i in (1, 2, 3, 4)]
    computed, shown = manager('SELECT * FROM m_player_view ORDER BY idx')
    assert computed is None and shown == rows
    assert len(engine.getter_vm.calls) == calls and stored() == ([1, 2, 3, 4], [1], 0)

    if tracking:
        # a byte the cells were read from changes: `*` computes nothing, and the stored cells of the
        # block, which fail their check, are NULL before the statement reads them
        engine.memory.load(engine.pointers[2], b'\x09')
        engine.refresh_memory()
        computed, shown = manager('SELECT * FROM m_player_view ORDER BY idx')
        assert computed is None and shown == [(i, None, None, None) for i in (1, 2, 3, 4)]
        assert len(engine.getter_vm.calls) == calls and stored() == ([], [], 0)
        # naming the column computes it again from the bytes as they are now
        computed, rows = manager('SELECT idx, first_name, wage, current_ability FROM m_player_view ORDER BY idx')
        assert computed == {'cells': 5} and rows[1] == (2, 'P9', None, None) and rows[0] == (1, 'P1', 50001, None)


# ----------------------------------------------------------------------------- lock order
def test_masked_connection_releases_the_snapshot_after_each_statement(env):
    """A writer of the snapshot in the same process (on-demand cells, the content check) never
    waits for the masked connection: it is in autocommit, so a read holds the snapshot's lock only
    while its statement runs. With the sqlite3 default the INSERTs into its temp tables opened a
    transaction that was never committed, and the writer timed out on 'database is locked'."""
    snap, store = env
    c = mv.open_manager_connection(snap, store.path, coverage=store.coverage(), need=set())
    try:
        assert fetch(c, 'SELECT idx, first_name FROM m_player_view ORDER BY idx')
        c.set_authorizer(None)                       # as prepare_manager_query updates m_coverage
        c.executemany('INSERT OR REPLACE INTO temp.m_coverage VALUES (?,?)', [('complete', 1)])
        c.set_authorizer(c.manager_authorizer)
        assert fetch(c, 'SELECT count(*) AS n FROM m_player_view')
        writer = sqlite3.connect(snap, timeout=0.5)
        try:
            writer.execute("UPDATE person SET first_name = first_name || '' WHERE idx = 1")
            writer.commit()
        finally:
            writer.close()
    finally:
        c.close()


def test_prewarm_after_the_statement_stores_without_waiting_and_only_the_rows_read(env, monkeypatch):
    """tools.manager_query runs the prewarm while the masked connection prepare_manager_query
    probed the statement on is open. The on-demand cells are stored at once (old code: the store
    waited for that connection's lock until its timeout, and the cells read NULL), and only for the
    rows whose cells the statement read through the masked view (need(idx, CELL))."""
    from fm_live_mcp.fmdb import ondemand, tools
    snap, store = env
    engine = PeopleEngine()
    make_on_demand(snap, engine)
    raw = sqlite3.connect(snap)
    raw.execute('CREATE TABLE _view_columns(view TEXT, column_name TEXT, base_table TEXT, base_column TEXT)')
    raw.executemany('INSERT INTO _view_columns VALUES (?, ?, ?, ?)',
                    [('player_view', 'first_name', 'person', 'first_name'), ('player_view', 'name', 'person',
                                                                              'first_name'),
                     ('player_view', 'wage', 'person', 'wage')])
    raw.commit()
    raw.close()
    monkeypatch.setattr(tools, '_knowledge_path', lambda e: store.path)
    monkeypatch.setattr(ondemand, 'STORE_TIMEOUT_S', 1.0, raising=False)
    sql = 'SELECT idx, first_name FROM m_player_view WHERE idx IN (2, 3) ORDER BY idx'
    need = set()
    con = mv.open_manager_connection(snap, store.path, coverage=store.coverage(), need=need)
    try:
        assert mv._probe(con, sql, None, 10)
        cells = mv.cells_read(need)
        assert cells == {'first_name': {2, 3}}          # wage (own club) was not read: not recorded
        q = mv.ManagerQuery(con, {}, False, True, '', [], cells=cells)
        started = __import__('time').monotonic()
        computed = tools.manager_prewarm(engine, snap, sql, q)
        assert __import__('time').monotonic() - started < 5
        assert computed == {'cells': 2}, computed
        assert sorted(engine.calls('Pfna')) == [2, 3]
        assert [(r['idx'], r['first_name']) for r in fetch(con, sql)] == [(2, 'P2'), (3, 'P3')]
        # a filter on the on-demand column: the probe saw NULL everywhere, the prewarm computes
        # every row the filter read, and the statement then finds its row
        need.clear()
        sql = "SELECT idx FROM m_player_view WHERE first_name = 'P4'"
        assert mv._probe(con, sql, None, 10) and mv.cells_read(need) == {'first_name': {1, 2, 3, 4, 5}}
        q = mv.ManagerQuery(con, {}, False, True, '', [], cells=mv.cells_read(need))
        assert tools.manager_prewarm(engine, snap, sql, q) == {'cells': 3}        # 2 and 3 were stored
        assert [r['idx'] for r in fetch(con, sql)] == [4]
    finally:
        con.close()


def test_subquery_hint_names_the_correlated_subquery_cause():
    """A statement whose subquery names a column its own view lacks (club_idx over m_club_view) is
    correlated and keeps every player; the building and prewarm notes say how to write it."""
    from fm_live_mcp.fmdb.tools import subquery_hint
    hint = subquery_hint("SELECT name, position FROM m_player_view WHERE club_idx IN "
                         "(SELECT club_idx FROM m_club_view WHERE name = 'Newcastle United')")
    assert 'm_club_view' in hint and 'SELECT idx FROM m_club' in hint
    assert subquery_hint('SELECT name FROM m_player_view WHERE club_idx = 414') == ''
