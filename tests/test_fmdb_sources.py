"""Collection tables (fmdb/sources): the loader contract, offline (no game)."""
from __future__ import annotations

import json
import sqlite3
import sys
import types

from fm_live_mcp.fmdb import snapshot, sources
from fm_live_mcp.fmdb.sources import Column, SourceTable


class FakeEngine:
    def game_date(self):
        return '2030-12-10'


def _conn():
    conn = sqlite3.connect(':memory:')
    snapshot.create_metadata(conn)
    return conn


def _install(name, fn):
    mod = types.ModuleType(f'fm_live_mcp.fmdb.sources.{name}')
    mod.tables = fn
    sys.modules[mod.__name__] = mod
    return mod


def test_dataclass_contract_and_backward_compatible_defaults():
    c = Column('x', 'INTEGER', 'meaning')
    assert (c.enum, c.references) == (None, None)
    t = SourceTable('t', 'd', [c], rows=lambda: [])
    assert (t.key, t.cost_note, t.slow) == ('idx', '', False)
    # first-contract sources: no mode means lazy, no invalidation means game_date
    assert (t.build_mode, t.refresh) == ('lazy', 'game_date')
    assert SourceTable('t', 'd', [c], rows=lambda: [], mode='eager', invalidation='append').refresh == 'append'


def test_eager_example_builds_with_metadata_cost_and_view():
    conn = _conn()
    summary = sources.build_in_snapshot(FakeEngine(), conn, only=['_example'])
    assert summary['eager'] == ['example_collection']
    assert conn.execute('SELECT idx, code, label, person_idx FROM example_collection ORDER BY idx').fetchall() == [
        (0, 0, 'none', None), (1, 1, 'some', 3)]
    rt, rows, cost = conn.execute("SELECT record_type, rows, classes_json FROM _tables "
                                  "WHERE table_name='example_collection'").fetchone()
    cost = json.loads(cost)
    assert (rt, rows, cost['mode'], cost['invalidation'], cost['rows']) == ('collection:_example', 2, 'eager',
                                                                          'immutable', 2)
    assert cost['seconds'] is not None and cost['cpu_seconds'] is not None
    fields = dict(conn.execute("SELECT column_name, source FROM _fields WHERE table_name='example_collection'"))
    assert set(fields) == {'idx', 'code', 'label', 'person_idx'} and set(fields.values()) == {'collection'}
    assert conn.execute("SELECT references_table FROM _fields WHERE table_name='example_collection' "
                        "AND column_name='person_idx'").fetchone() == ('person',)
    assert conn.execute("SELECT label FROM _enum_labels WHERE table_name='example_collection' AND value=1"
                        ).fetchone() == ('some',)
    st = conn.execute("SELECT status, rows, manager_scope FROM _source_tables").fetchone()
    assert st == ('ready', 2, 'public')
    assert sources.create_views(conn) == ['example_collection_view']
    assert conn.execute('SELECT COUNT(*) FROM example_collection_view').fetchone() == (2,)


def test_failing_module_and_failing_rows_do_not_stop_the_build():
    def boom_rows():
        raise RuntimeError('reader broke')
        yield ()

    _install('_boom', lambda engine: [SourceTable('boom_table', 'd', [Column('a', 'INTEGER', 'a')], rows=boom_rows,
                                                  mode='eager')])
    _install('_bad', lambda engine: 1 / 0)
    conn = _conn()
    summary = sources.build_in_snapshot(FakeEngine(), conn, only=['_bad', '_boom', '_example', '_missing'])
    assert summary['eager'] == ['example_collection']
    assert summary['unavailable'] == ['boom_table']
    assert set(summary['failed_modules']) == {'_bad', '_missing'}
    status, note = conn.execute("SELECT status, note FROM _source_tables WHERE table_name='boom_table'").fetchone()
    assert status == 'unavailable' and 'reader broke' in note
    assert conn.execute('SELECT COUNT(*) FROM boom_table').fetchone() == (0,)
    assert {r[0] for r in conn.execute('SELECT module FROM _source_failures')} >= {'_bad', '_missing'}


def _snapshot_file(path, modules, previous=None):
    conn = sqlite3.connect(path)
    snapshot.create_metadata(conn)
    conn.execute("INSERT INTO _snapshot VALUES ('s', 'k', '2030-12-10', 'now', 'b', 0, '[]')")
    summary = sources.build_in_snapshot(FakeEngine(), conn, only=modules, previous=previous,
                                        game_date=FakeEngine().game_date())
    conn.commit()
    conn.close()
    return summary


def _rows(path, sql):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_lazy_table_is_built_on_first_reference_only(tmp_path):
    calls = []

    def rows():
        calls.append(1)
        return [(5,), (6,)]
    _install('_lazy', lambda engine: [SourceTable('lazy_table', 'd', [Column('a', 'INTEGER', 'a')], rows=rows,
                                                  cost_note='per-record')])
    path = tmp_path / 'snapshot.sqlite'
    summary = _snapshot_file(path, ['_lazy'])
    assert summary['lazy'] == ['lazy_table'] and calls == []
    assert _rows(path, "SELECT status FROM _source_tables") == [('lazy',)]
    reads = {('lazy_table', 'a', None)}
    done = sources.refresh_for_query(FakeEngine(), path, reads)
    assert done['lazy_table']['built'] == 2 and calls == [1]
    assert _rows(path, 'SELECT a FROM lazy_table ORDER BY idx') == [(5,), (6,)]
    # referenced again at once: no work (rate limit); unrelated reads: nothing
    assert sources.refresh_for_query(FakeEngine(), path, reads) == {}
    assert sources.refresh_for_query(FakeEngine(), path, {('person', 'x', None)}) == {}
    assert calls == [1]


def test_content_table_rebuilds_only_when_its_fingerprint_changes(tmp_path, monkeypatch):
    state = {'fp': 'a', 'rows': [(1,)], 'built': 0}

    def rows():
        state['built'] += 1
        return state['rows']
    _install('_content', lambda engine: [SourceTable('content_table', 'd', [Column('a', 'INTEGER', 'a')], rows=rows,
                                                     invalidation='content', fingerprint=lambda: state['fp'])])
    path = tmp_path / 'snapshot.sqlite'
    _snapshot_file(path, ['_content'])
    reads = {('content_table', 'a', None)}
    sources.refresh_for_query(FakeEngine(), path, reads)
    monkeypatch.setattr(sources, 'CHECK_INTERVAL_S', 0.0)
    assert sources.refresh_for_query(FakeEngine(), path, reads)['content_table']['unchanged']
    state.update(fp='b', rows=[(1,), (2,)])
    assert sources.refresh_for_query(FakeEngine(), path, reads)['content_table']['built'] == 2
    assert state['built'] == 2
    # a new snapshot (next game day) carries the rows; the next reference only checks the fingerprint
    nxt = tmp_path / 'next.sqlite'
    assert _snapshot_file(nxt, ['_content'], previous=path)['carried'] == ['content_table']
    assert _rows(nxt, 'SELECT a FROM content_table ORDER BY idx') == [(1,), (2,)]
    assert sources.refresh_for_query(FakeEngine(), nxt, reads)['content_table']['unchanged']
    assert state['built'] == 2


def test_append_table_adds_only_new_rows_and_survives_rebuilds(tmp_path, monkeypatch):
    store = {'groups': {(2025, 0): [(2025, 0, 'x')], (2025, 1): [(2025, 1, 'y')]}, 'asked': []}

    def new_rows(existing):
        store['asked'].append(set(existing))
        return [r for k, rs in sorted(store['groups'].items()) if k not in existing for r in rs]
    cols = [Column('year', 'INTEGER', 'y'), Column('grp', 'INTEGER', 'g'), Column('v', 'TEXT', 'v')]
    _install('_append', lambda engine: [SourceTable('append_table', 'd', cols, rows=lambda: new_rows(set()),
                                                    invalidation='append', identity=('year', 'grp'),
                                                    new_rows=new_rows)])
    path = tmp_path / 'snapshot.sqlite'
    _snapshot_file(path, ['_append'])
    reads = {('append_table', 'v', None)}
    assert sources.refresh_for_query(FakeEngine(), path, reads)['append_table']['built'] == 2
    monkeypatch.setattr(sources, 'CHECK_INTERVAL_S', 0.0)
    store['groups'][(2026, 0)] = [(2026, 0, 'z'), (2026, 0, 'w')]
    done = sources.refresh_for_query(FakeEngine(), path, reads)['append_table']
    assert done['added'] == 2 and store['asked'][-1] == {(2025, 0), (2025, 1)}
    assert _rows(path, 'SELECT idx, year, grp, v FROM append_table ORDER BY idx') == [
        (0, 2025, 0, 'x'), (1, 2025, 1, 'y'), (2, 2026, 0, 'z'), (3, 2026, 0, 'w')]
    nxt = tmp_path / 'next.sqlite'
    assert _snapshot_file(nxt, ['_append'], previous=path)['carried'] == ['append_table']
    assert sources.refresh_for_query(FakeEngine(), nxt, reads)['append_table']['added'] == 0
    assert _rows(nxt, 'SELECT COUNT(*) FROM append_table') == [(4,)]


def test_a_read_that_failed_for_part_of_a_statement_is_reported(tmp_path, monkeypatch):
    """`not_read` lines of a table go into the refresh result (first build and later additions) and
    into the stored note, so an answer can tell a failed read from rows that do not exist."""
    state = {'failed': ['club 414: PTin 2025: the game did not answer'], 'rows': []}

    def new_rows(existing):
        return [r for r in state['rows'] if (r[0],) not in existing]
    _install('_partial', lambda engine: [SourceTable(
        'partial_table', 'd', [Column('club_idx', 'INTEGER', 'club')], rows=lambda: new_rows(set()),
        invalidation='append', identity=('club_idx',), new_rows=new_rows, check_interval=0.0,
        coverage=lambda: 'read 1 club(s)', not_read=lambda: list(state['failed']))])
    path = tmp_path / 'snapshot.sqlite'
    _snapshot_file(path, ['_partial'])
    reads = {('partial_table', 'club_idx', None)}
    first = sources.refresh_for_query(FakeEngine(), path, reads)['partial_table']
    assert first['built'] == 0 and first['not_read'] == state['failed']
    again = sources.refresh_for_query(FakeEngine(), path, reads)['partial_table']
    assert again['added'] == 0 and again['not_read'] == state['failed']
    assert _rows(path, "SELECT note FROM _source_tables WHERE table_name='partial_table'") == [('read 1 club(s)',)]
    note = sources.not_read_note('partial_table', again['not_read'])
    assert note.startswith('partial_table: not read for part of what the statement names')
    assert 'it did not find them empty' in note and note.endswith('club 414: PTin 2025: the game did not answer')
    state.update(failed=[], rows=[(414,)])                      # the read answers: no report any more
    done = sources.refresh_for_query(FakeEngine(), path, reads)['partial_table']
    assert done['added'] == 1 and 'not_read' not in done


def test_game_date_tables_are_not_carried(tmp_path):
    _install('_daily', lambda engine: [SourceTable('daily_table', 'd', [Column('a', 'INTEGER', 'a')],
                                                   rows=lambda: [(1,)])])
    path = tmp_path / 'snapshot.sqlite'
    _snapshot_file(path, ['_daily'])
    sources.refresh_for_query(FakeEngine(), path, {('daily_table', 'a', None)})
    nxt = tmp_path / 'next.sqlite'
    assert _snapshot_file(nxt, ['_daily'], previous=path)['lazy'] == ['daily_table']


def test_game_date_tables_are_carried_within_one_game_process_and_date(tmp_path):
    """A rebuild in the middle of a session (same game process, same game date) keeps the stored
    rows of game-date tables; another process or another date builds them afresh."""
    built = []
    _install('_daily', lambda engine: [SourceTable('daily_table', 'd', [Column('a', 'INTEGER', 'a')],
                                                   rows=lambda: built.append(1) or [(1,)],
                                                   invalidation='game_date')])

    class Engine(FakeEngine):
        process_key = ('13991', 'fm', 'start')
    path = tmp_path / 'snapshot.sqlite'
    _snapshot_file(path, ['_daily'])
    sources.refresh_for_query(Engine(), path, {('daily_table', 'a', None)})
    conn = sqlite3.connect(path)
    conn.execute("INSERT OR REPLACE INTO _build VALUES ('process', ?)", (json.dumps(list(Engine.process_key)),))
    conn.commit()
    conn.close()
    nxt = tmp_path / 'next.sqlite'
    conn = sqlite3.connect(nxt)
    snapshot.create_metadata(conn)
    summary = sources.build_in_snapshot(Engine(), conn, only=['_daily'], previous=path, game_date='2030-12-10')
    conn.commit()
    conn.close()
    assert summary['carried'] == ['daily_table'] and built == [1]
    assert sources.refresh_for_query(Engine(), nxt, {('daily_table', 'a', None)}) == {} and built == [1]
    other = tmp_path / 'other.sqlite'
    conn = sqlite3.connect(other)
    snapshot.create_metadata(conn)
    assert sources.build_in_snapshot(Engine(), conn, only=['_daily'], previous=path,
                                     game_date='2030-12-11')['lazy'] == ['daily_table']
    conn.close()


def test_key_column_is_indexed():
    _install('_keyed', lambda engine: [SourceTable('keyed', 'd', [Column('uid', 'INTEGER', 'u')],
                                                   rows=lambda: [(9,)], key='uid', mode='eager')])
    conn = _conn()
    sources.build_in_snapshot(FakeEngine(), conn, only=['_keyed'])
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND tbl_name='keyed'").fetchone() == (1,)


def _core(conn):
    """Minimal core tables with the codes the relation views use."""
    conn.execute('CREATE TABLE club(idx INTEGER PRIMARY KEY, uid INTEGER, rival_clubs TEXT, current_affiliations TEXT, '
                 'favourite_people TEXT, disliked_people TEXT)')
    conn.execute('CREATE TABLE person(idx INTEGER PRIMARY KEY, uid INTEGER, nationality_idx INTEGER, '
                 'second_nations_PNRs TEXT, favourite_people TEXT, disliked_people TEXT, favourite_clubs TEXT, '
                 'disliked_clubs TEXT)')
    conn.execute('CREATE TABLE player(idx INTEGER PRIMARY KEY, position_ratings_PPra TEXT)')
    conn.execute('CREATE TABLE nation(idx INTEGER PRIMARY KEY, uid INTEGER)')
    fields = [('club', 'rival_clubs', 'Crvc'), ('club', 'current_affiliations', 'Cafl'),
              ('club', 'favourite_people', 'Cfvp'), ('club', 'disliked_people', 'Cdsp'),
              ('person', 'nationality_idx', 'Pnat'), ('person', 'second_nations_PNRs', 'PNRs'),
              ('person', 'favourite_people', 'Pfvp'), ('person', 'disliked_people', 'Pdsp'),
              ('person', 'favourite_clubs', 'Pfvc'), ('person', 'disliked_clubs', 'Pdsc'),
              ('player', 'position_ratings_PPra', 'PPra')]
    conn.executemany('INSERT INTO _fields(table_name, column_name, code) VALUES (?, ?, ?)', fields)
    ref = lambda t, u: {'table': t, 'unique_id': u, 'random_id': u}  # noqa: E731
    import json
    conn.executemany('INSERT INTO club VALUES (?, ?, ?, ?, ?, ?)', [
        (0, 61, json.dumps([{'club': ref('Cclu', 64), 'leve': 90, 'rcdt': False, 'rrea': 2}]), '[]', None, None),
        (1, 64, None, None, json.dumps([{'pers': ref('Pers', 7), 'leve': 50, 'perm': True, 'rrea': 1}]), '[]')])
    conn.executemany('INSERT INTO person VALUES (?, ?, ?, ?, ?, ?, ?, ?)', [
        (0, 7, 3, json.dumps([{'nati': ref('Nnat', 387), 'ntin': 80}]), None, None,
         json.dumps([{'club': ref('Cclu', 61), 'leve': 75, 'rrea': 2}]), '[]')])
    conn.execute("INSERT INTO player VALUES (0, '[20, 1, 5]')")
    conn.executemany('INSERT INTO nation VALUES (?, ?)', [(3, 1), (9, 387)])


def test_relation_views_explode_core_lists():
    conn = _conn()
    _core(conn)
    sources.build_in_snapshot(FakeEngine(), conn, only=['relations'])
    made = sources.create_views(conn)
    assert set(made) == {'club_rival', 'club_affiliate', 'person_favourite', 'club_favourite_person',
                         'player_position', 'person_nationality'}
    assert conn.execute('SELECT club_idx, kind, target_idx, target_uid, level, reason_code FROM club_rival'
                        ).fetchall() == [(0, 'rival', 1, 64, 90, 2)]
    assert conn.execute('SELECT person_idx, kind, target_table, target_idx, level FROM person_favourite'
                        ).fetchall() == [(0, 'favourite', 'club', 0, 75)]
    assert conn.execute('SELECT club_idx, kind, target_idx, permanent FROM club_favourite_person').fetchall() == [
        (1, 'favourite', 0, 1)]
    assert conn.execute('SELECT * FROM player_position ORDER BY position_index').fetchall() == [
        (0, 0, 20), (0, 1, 1), (0, 2, 5)]
    assert conn.execute('SELECT kind, nation_idx, info FROM person_nationality ORDER BY kind').fetchall() == [
        ('main', 3, None), ('second', 9, 80)]
    tables, views = sources.schema_summary(conn)
    assert 'club_rival' in views and tables == {}


def test_contract_clause_expiry_rule():
    from fm_live_mcp.fmdb.sources import contracts
    signed = 2030 << 16 | 182                    # 2030-07-01
    assert contracts._expiry(signed, 365, 0) == '2031-07-01'
    assert contracts._expiry(signed, -1, 0) is None
    assert contracts._expiry(signed, 30, 2) is None


def test_archive_vm_allows_only_data_and_temporary_archives():
    from fm_live_mcp.fmdb.sources import _archive_vm as av
    assert av.allowed(av.TEMPORARY / 'fixture_group_archive.obs')
    assert av.allowed(av.TEMPORARY / 'pl_hist_dt.cmt')
    assert av.allowed('/x/Resources/data/game_simulation/languages.fmf')
    assert not av.allowed(av.TEMPORARY / 'other.txt')
    assert not av.allowed('/Users/x/Documents/fixture_group_archive.obs')
    assert not av.allowed(None)


def test_every_source_module_imports_and_declares_tables():
    """discover() records a failing module and carries on, so a module that does not import
    removes its tables without failing a build. The match module shipped that way once (a missing
    comma in a column list); this test fails instead."""
    import importlib

    names = sources.module_names()
    assert {'club_finance', 'contracts', 'fixture_tables', 'matches', 'virtual_players'} <= set(names)
    for name in names:
        mod = importlib.import_module(f'fm_live_mcp.fmdb.sources.{name}')
        assert callable(getattr(mod, 'tables', None)) or callable(getattr(mod, 'views', None)), name


def test_whole_package_compiles():
    """Every module of the reader parses: lazily imported modules are otherwise checked by nothing."""
    import ast
    from pathlib import Path

    root = Path(sources.__file__).resolve().parents[2]
    bad = []
    for path in root.rglob('*.py'):
        try:
            ast.parse(path.read_text())
        except SyntaxError as exc:
            bad.append(f'{path.relative_to(root)}:{exc.lineno}: {exc.msg}')
    assert not bad, bad


def test_failures_lists_recorded_module_failures():
    conn = _conn()
    conn.executescript(sources.SOURCE_SQL)
    assert sources.failures(conn) == []
    conn.execute("INSERT INTO _source_failures VALUES ('matches', 'SyntaxError: invalid syntax', '2026-11-12T01:00:00')")
    assert sources.failures(conn) == [{'module': 'matches', 'reason': 'SyntaxError: invalid syntax',
                                       'at': '2026-11-12T01:00:00'}]
    assert sources.failures(sqlite3.connect(':memory:')) == []
