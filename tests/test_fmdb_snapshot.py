"""Offline tests for the fmdb snapshot, plans, SQL guardrails and on-demand columns.

The fake engine (`_fmdb_fake.py`) serves a small NATION table from a memory the tests can
change and answers properties from the same bytes (the 'getter'), so direct plans can be
verified against it."""
from __future__ import annotations

import json
import sqlite3
import struct
from types import SimpleNamespace

import pytest

from fm_live_mcp.fmdb import bulkplans, query, snapshot, views
from fm_live_mcp.fmdb.bulkplans import Observation
from fm_live_mcp.fmdb.memory import SnapshotMemory

from _fmdb_fake import COUNT, FIELDS, FakeEngine, FakeTracer, field, statement, use_cache  # noqa: F401 - shared with test_fmdb_perf


@pytest.fixture()
def built(tmp_path, monkeypatch):
    use_cache(monkeypatch, tmp_path)
    engine = FakeEngine(tmp_path)
    builder = snapshot.Build(engine, root=tmp_path, tables_wanted=['nation'], column_budget=20, build_budget=90)
    path = builder.run()
    return engine, path, builder


def test_build_contract_and_values(built):
    engine, path, builder = built
    conn = sqlite3.connect(path)
    # metadata contract
    cols = [r[1] for r in conn.execute('PRAGMA table_info(_fields)')]
    assert cols == ['table_name', 'column_name', 'code', 'record_type', 'name', 'comment', 'type', 'enum_json',
                    'references_table', 'source', 'status', 'note']
    assert [r[1] for r in conn.execute('PRAGMA table_info(_tables)')] == ['table_name', 'record_type', 'rows',
                                                                         'classes_json']
    assert [r[1] for r in conn.execute('PRAGMA table_info(_snapshot)')] == [
        'save_name', 'save_key', 'game_date', 'built_at', 'build', 'plans_verified', 'notes']
    save_name, save_key, game_date, _, build, verified, notes = conn.execute('SELECT * FROM _snapshot').fetchone()
    assert (save_name, save_key, game_date, build) == ('Test Career', 'test-career', '2030-12-10', 'test')
    assert snapshot.CONSISTENCY_NOTE in json.loads(notes)
    assert conn.execute("SELECT rows, classes_json FROM _tables WHERE table_name='nation'").fetchone() == \
        (COUNT, json.dumps({'NATION': COUNT}))
    nation_cols = [r[1] for r in conn.execute('PRAGMA table_info(nation)')]
    assert nation_cols[:3] == ['idx', 'uid', 'class']
    assert 'press' not in nation_cols and 'name_Ndup' in nation_cols and 'neighbour_idx' in nation_cols
    # a column is `ready` in _fields whether it is stored (direct) or computed on demand (emulated)
    status = {r[0]: r[1:] for r in conn.execute(
        "SELECT column_name, source, status, note FROM _fields WHERE table_name='nation'")}
    assert status['code'][:2] == ('direct', 'ready')
    assert status['name'][:2] == ('direct', 'ready')
    assert status['computed'][:2] == ('emulated', 'ready') and 'computed on demand' in status['computed'][2]
    assert status['slow'][:2] == ('emulated', 'ready')
    assert status['not_handled'][:2] == ('emulated', 'unavailable')
    # the wrong plan was caught by verification and demoted to emulation
    assert status['badly_planned'][:2] == ('emulated', 'ready')
    plan = builder.store.get('NATION', 'Nbad')
    assert plan['status'] == 'emulate-only' and plan['reason'].startswith('verification:')
    # per class: stored at build, computed on demand, or unavailable; nothing is pending or partial
    state = {r[0]: r[1:] for r in conn.execute(
        "SELECT column_name, source, status FROM _column_state WHERE table_name='nation' AND class='NATION'")}
    assert state['code'] == ('direct', 'ready') and state['name'] == ('direct', 'ready')
    assert state['computed'] == state['slow'] == state['badly_planned'] == state['score'] == ('emulated', 'on_demand')
    assert state['not_handled'] == ('emulated', 'unavailable')
    assert {r[0] for r in conn.execute('SELECT status FROM _column_state')} <= {'ready', 'on_demand', 'unavailable'}
    assert {r[0] for r in conn.execute("SELECT status FROM _fields WHERE table_name='nation'")} == \
        {'ready', 'unavailable'}
    # a build reads direct columns only: every emulated cell is NULL until a query names its column
    rows = conn.execute('SELECT idx, uid, code, name, badly_planned, computed, slow, neighbour_idx, state '
                        'FROM nation ORDER BY idx').fetchall()
    assert len(rows) == COUNT
    for idx, uid, code, name, bad, computed, slow, neighbour, state_ in rows:
        assert uid == 1000 + idx and code == idx * 3 and name == f'Nation {idx}'
        assert bad is None and computed is None and slow is None
        assert neighbour == (idx + 1) % COUNT and state_ == idx % 2
    assert engine.tracked_vm is None or not engine.tracked_vm.calls
    labelled = conn.execute("SELECT state, state_label FROM nation_labelled WHERE idx IN (0, 1) ORDER BY idx").fetchall()
    assert labelled == [(0, 'poor'), (1, 'rich')]
    assert 'enumerate' in builder.timing and 'direct' in builder.timing and 'write' in builder.timing
    # the build ends with the content check that later keeps the snapshot current (freshness.refresh)
    assert 'settle' in builder.timing and builder.settled['rows_refreshed'] == 0 and not builder.notes
    assert conn.execute('SELECT COUNT(*) FROM _direct_blocks').fetchone()[0] == (COUNT + 255) // 256
    assert conn.execute("SELECT value FROM _fresh WHERE key='checks'").fetchone()[0] == 1
    conn.close()
    # the getter's value, not the wrong plan's, when a statement names the column
    result, computed = statement(engine, path, 'SELECT idx, badly_planned, computed, slow FROM nation ORDER BY idx')
    for idx, bad, emulated, slow in result['rows']:
        assert bad == idx + (1 if idx % 3 == 0 else 0) and emulated == idx * idx and slow == -idx
    assert computed['cells'] == 3 * COUNT


def test_removed_eager_emulation_api():
    for name in ('estimate', 'pending_columns', 'REFRESH_BUILD_BUDGET_S', 'BUILD_BUDGET_S', 'PRIORITY_CODES'):
        assert not hasattr(snapshot, name), name
    assert not hasattr(snapshot.Build, '_fill') and not hasattr(snapshot.Build, '_fill_rank')


def test_materialise_bookkeeping(built):
    """`snapshot.materialise` is the explicit form of what a query does (`ondemand.compute`)."""
    engine, path, _ = built
    tracking = engine.tracked_vm is not None
    result = snapshot.materialise(engine, path, 'nation', ['slow'], where_idx=[2, 5])
    assert result['filled'] == {'slow': 2} and result['rows'] == 2 and result['complete'] is True
    assert result['stored'] is tracking
    conn = sqlite3.connect(path)
    assert conn.execute('SELECT idx, slow FROM nation WHERE slow IS NOT NULL ORDER BY idx').fetchall() == [(2, -2), (5, -5)]
    assert conn.execute("SELECT status FROM _fields WHERE table_name='nation' AND column_name='slow'").fetchone()[0] == 'ready'
    assert conn.execute("SELECT status FROM _column_state WHERE table_name='nation' AND column_name='slow'"
                        ).fetchone()[0] == 'on_demand'
    assert conn.execute("SELECT cells FROM _memo WHERE table_name='nation' AND column_name='slow'").fetchone()[0] == \
        (2 if tracking else 0)
    conn.close()
    result = snapshot.materialise(engine, path, 'nation', ['slow', 'code'])
    # cells that are memoised and still valid are kept; a direct column has nothing to compute
    assert result['filled'] == {'slow': COUNT - 2 if tracking else COUNT, 'code': 0} and result['rows'] == 'all'
    conn = sqlite3.connect(path)
    assert conn.execute('SELECT COUNT(*) FROM nation WHERE slow = -idx').fetchone()[0] == COUNT
    conn.close()
    with pytest.raises(snapshot.SnapshotError, match='unknown columns'):
        snapshot.materialise(engine, path, 'nation', ['no_such_column'])


def test_naming_and_deduplication():
    catalog = SimpleNamespace(record_types={'nati': SimpleNamespace(field_list=FIELDS + [
        field('Ncod', 'Code', 'integer'), field('N2nd', '2nd Name', 'string'), field('Nidx', 'Idx', 'integer')])},
        enums={})
    cols = snapshot.columns_for(catalog, 'nation')
    names = [c.name for c in cols]
    assert len(names) == len(set(names))
    assert names.count('code') == 1                      # repeated code skipped
    assert 'name' in names and 'name_Ndup' in names      # collision gets _<code>
    assert 'neighbour_idx' in names                      # references end in _idx
    assert 'f_2nd_name' in names and 'idx_Nidx' in names  # leading digit, reserved name
    assert snapshot.snake('CA/RCA % Difference') == 'ca_rca_difference'


def test_bulk_evaluate_chains_and_strings():
    memory = SnapshotMemory()
    record, child, text = 0x3_0000_0000, 0x3_0001_0000, 0x3_0002_0000
    long_text = 'x' * 200
    memory.load(text, struct.pack('<I', len(long_text)) + long_text.encode())
    memory.load(child, struct.pack('<Hh', 2030 * 0 + 41, 2030) + b'\0' * 12 + struct.pack('<I', 7))
    memory.load(record, struct.pack('<QQQ', child, text, 0) + bytes(16))
    empty = 0x3_0003_0000
    memory.load(empty, bytes(32))
    plans = {'date': {'chain': [0, 0], 'width': 4, 'signed': False, 'type': 'date_yd', 'transform': 'identity'},
             'deep': {'chain': [0, 0x10], 'width': 4, 'signed': False, 'type': 'int', 'transform': 'identity'},
             'text': {'chain': [8], 'width': 8, 'signed': False, 'type': 'string', 'transform': 'identity'},
             'nul': {'chain': [16, 0], 'width': 4, 'signed': False, 'type': 'int', 'transform': 'identity'}}
    out = bulkplans.evaluate(memory.read_many, [record, empty], plans)
    assert out['date'] == ['2030-02-10', None] and out['deep'] == [7, None]
    assert out['text'] == [long_text, ''] and out['nul'] == [None, None]
    for code, plan in plans.items():
        assert bulkplans.apply(memory.read, record, plan) == out[code][0]


def test_rating_blob_plan():
    memory = SnapshotMemory()
    primary = 0x4_0000_0000
    person = primary + 0x388
    memory.load(primary, bytes(0x400))
    memory.load(primary + 0x270, bytes([0x80]))
    memory.load(primary + 0x148, bytes([66]))
    raw = {'chain': [-0x388 + 0x148], 'width': 1, 'signed': False, 'type': 'int', 'transform': 'identity'}
    flag = {'chain': [-0x388 + 0x270], 'width': 1, 'signed': False, 'type': 'int', 'transform': 'identity'}
    plan = {'type': 'rating_blob', 'source_plan': raw, 'flag_plan': flag}
    assert bulkplans.evaluate(memory.read_many, [person], {'a': plan})['a'] == [13]
    assert bulkplans.blob_rating(bytes([1, 13, 13, 13])) == 13 and bulkplans.blob_rating(b'\x01\x02\x03\x04') is None
    memory.load(primary + 0x270, bytes([0]))
    memory.load(primary + 0x148, bytes([66]))
    assert isinstance(bulkplans.apply(memory.read, person, plan), bulkplans.Missing)  # raw > 20 without fifths


def test_derive_handles_unset_by_null_pointer():
    memory = SnapshotMemory()
    a, b, child = 0x5_0000_0000, 0x5_0001_0000, 0x5_0002_0000
    memory.load(child, struct.pack('<I', 9))
    memory.load(a, struct.pack('<Q', child))
    memory.load(b, struct.pack('<Q', 0))
    c2 = 0x5_0003_0000
    memory.load(c2, struct.pack('<I', 4))
    a2 = 0x5_0004_0000
    memory.load(a2, struct.pack('<Q', c2))
    cand = frozenset({((0, 0), 4, False, 'int', 'identity')})
    obs = [Observation(a, 'int', 9, cand, None, True, 0.1), Observation(a2, 'int', 4, cand, None, True, 0.1),
           Observation(b, 'null', None, None, 'unset', True, 0.1)]
    plan = bulkplans.derive(obs, memory.read)
    assert plan['status'] == 'direct' and plan['chain'] == [0, 0]


# --------------------------------------------------------------------------- SQL guardrails
@pytest.fixture()
def db(tmp_path):
    path = tmp_path / 'g.sqlite'
    conn = sqlite3.connect(path)
    conn.executescript('CREATE TABLE t(idx INTEGER PRIMARY KEY, a INTEGER, b TEXT);'
                       'INSERT INTO t VALUES (1, 10, "x"), (2, 20, "y"), (3, 30, "z");'
                       'CREATE VIEW v AS SELECT idx, a * 2 AS a2 FROM t;')
    conn.close()
    return path


@pytest.mark.parametrize('sql', [
    'INSERT INTO t VALUES (9, 9, "w")', 'DELETE FROM t', 'UPDATE t SET a = 0', 'DROP TABLE t',
    "ATTACH DATABASE ':memory:' AS x", 'PRAGMA table_info(t)', 'SELECT 1; DELETE FROM t',
    'SELECT 1; SELECT 2', "SELECT load_extension('x')", 'CREATE TABLE z(a)', 'BEGIN', 'VACUUM',
    'WITH x AS (SELECT 1) DELETE FROM t', '', '   ', 'REPLACE INTO t VALUES (1, 1, "a")'])
def test_sql_guardrails_reject(db, sql):
    with pytest.raises(query.QueryError):
        query.run(db, sql)
    conn = sqlite3.connect(db)
    assert conn.execute('SELECT COUNT(*) FROM t').fetchone()[0] == 3


def test_sql_runaway_query_stopped(db):
    sql = 'WITH RECURSIVE c(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM c) SELECT MAX(n) FROM c'
    with pytest.raises(query.QueryError, match='stopped'):
        query.run(db, sql, time_limit_s=0.3)


def test_sql_select_caps_and_columns(db):
    result = query.run(db, '-- comment\nSELECT idx, a FROM t ORDER BY idx', max_rows=2)
    assert result['columns'] == ['idx', 'a'] and result['rows'] == [[1, 10], [2, 20]]
    assert result['truncated'] is True and result['row_count'] == 2
    assert query.run(db, 'WITH x AS (SELECT a FROM t WHERE a > ?) SELECT COUNT(*) FROM x', [15])['rows'] == [[2]]
    reads = query.referenced_columns(db, 'SELECT a2 FROM v WHERE idx = 1')
    assert ('t', 'a', 'v') in reads
    with pytest.raises(query.QueryError):
        query.run(db, 'SELECT 1', max_rows=0)


def test_views_skip_missing_sources(tmp_path):
    conn = sqlite3.connect(tmp_path / 'v.sqlite')
    snapshot.create_metadata(conn)
    conn.execute('CREATE TABLE club(idx INTEGER PRIMARY KEY, uid INTEGER, class TEXT, name TEXT)')
    conn.execute("INSERT INTO club VALUES (0, 5, 'CLUB', 'Newcastle United')")
    conn.execute("INSERT INTO _tables VALUES ('club', 'club', 1, '{}')")
    conn.execute("INSERT INTO _fields VALUES ('club', 'name', 'dbnm', 'club', 'Name', NULL, 'string', NULL, NULL, "
                 "'direct', 'ready', '')")
    conn.execute("INSERT INTO _snapshot VALUES ('s', 'k', '2030-12-10', 'now', 'b', 0, '[]')")
    views.create_views(conn)
    assert conn.execute('SELECT idx, name FROM club_view').fetchall() == [(0, 'Newcastle United')]
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='player_view'").fetchone() is None


def test_derive_dates_from_half_words_and_empty_strings():
    from fm_live_mcp.fmdb import variant
    memory = SnapshotMemory()
    rec = [0x6_0000_0000 + i * 0x1000 for i in range(3)]
    names = [0x6_1000_0000, 0x6_1000_1000]
    memory.load(names[0], struct.pack('<I', 3) + b'Ann')
    memory.load(names[1], struct.pack('<I', 3) + b'Bob')
    holder = [0x6_2000_0000, 0x6_2000_1000]
    memory.load(holder[0], struct.pack('<Q', names[0]))
    memory.load(holder[1], struct.pack('<Q', names[1]))
    memory.load(rec[0], struct.pack('<Q', holder[0]))
    memory.load(rec[1], struct.pack('<Q', holder[1]))
    memory.load(rec[2], struct.pack('<Q', 0))
    cand = ((0, 0), 8, False, 'string', 'identity')
    obs = [Observation(rec[0], 'string', 'Ann', frozenset({cand}), None, True, 0.1),
           Observation(rec[1], 'string', 'Bob', frozenset({cand}), None, True, 0.1),
           Observation(rec[2], 'string', '', frozenset({((0,), 8, False, 'string', 'identity')}), None, True, 0.1)]
    plan = bulkplans.derive(obs, memory.read)
    assert plan['status'] == 'direct' and plan['null_is_empty'] is True
    assert bulkplans.evaluate(memory.read_many, rec, {'n': plan})['n'] == ['Ann', 'Bob', '']
    # date stored as u16 day-of-year then u16 year
    memory.load(0x6_3000_0000, struct.pack('<HH', 41, 2030))
    date_plan = {'chain': [0], 'width': 4, 'signed': False, 'type': 'date_yd', 'transform': 'identity'}
    assert bulkplans.apply(memory.read, 0x6_3000_0000, date_plan) == '2030-02-10'
    assert variant.si_date(2030 << 17 | 41 << 8).iso == '2030-02-10'
