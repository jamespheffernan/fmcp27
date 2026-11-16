"""Offline tests for the manager-view switch in the fmdb tools (no game, no knowledge build)."""
from __future__ import annotations

import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from fm_live_mcp.fmdb import manager_view as mv
from fm_live_mcp.fmdb import tools


META = {'game_date': '2030-12-10', 'built_at': 'now', 'save_name': 's', 'save_key': 'k', 'notes': [],
        'process': None}


def _manager_connection():
    con = sqlite3.connect(':memory:', check_same_thread=False)
    con.execute('CREATE TABLE m_player_view(idx INTEGER, name TEXT, crossing INTEGER, crossing_min INTEGER, '
                'crossing_max INTEGER)')
    con.executemany('INSERT INTO m_player_view VALUES (?, ?, ?, ?, ?)',
                    [(1, 'A', None, 12, 16), (2, 'B', 15, 15, 15), (3, 'C', None, None, None)])
    # every manager connection describes its columns (open_manager_connection); the tools read the
    # policies from it to decide which on-demand cells a statement may have computed (manager_prewarm)
    con.execute('CREATE TABLE m_columns(view TEXT, column_name TEXT, code TEXT, policy TEXT, field TEXT, note TEXT)')
    con.executemany('INSERT INTO m_columns VALUES (?, ?, ?, ?, ?, ?)',
                    [('m_player_view', 'idx', None, mv.IDENTITY, None, None),
                     ('m_player_view', 'name', None, mv.PUBLIC, None, None),
                     ('m_player_view', 'crossing', 'Pcro', mv.ATTRIBUTE, 'crossing', None),
                     ('m_player_view', 'crossing_min', 'Pcro', mv.ATTRIBUTE, 'crossing', None),
                     ('m_player_view', 'crossing_max', 'Pcro', mv.ATTRIBUTE, 'crossing', None)])
    return con


@pytest.fixture()
def wired(monkeypatch, tmp_path):
    engine = SimpleNamespace(save_info=lambda: SimpleNamespace(save_key='k', game_date='2030-12-10'))
    monkeypatch.setattr(tools, 'engine_for', lambda bridge, session: engine)
    monkeypatch.setattr(tools, 'current_snapshot',
                        lambda e, **kw: (tmp_path / 'snapshot.sqlite', META, None, e.save_info(), False))
    monkeypatch.setattr(tools, '_knowledge_path', lambda e: tmp_path / 'knowledge.sqlite')
    tools._MANAGER.update(thread=None, result=None, error=None, started=None)
    calls = []

    def prepare(engine_, sql, *, bridge_or_session=None, **kw):
        calls.append(sql)
        coverage = {'universe_players': 66043, 'universe_players_covered': 3555, 'scouted_rows': 3555,
                    'tier1_complete': True, 'tier3_complete': False, 'fill_running': True, 'game_date': '2030-12-10'}
        return mv.ManagerQuery(_manager_connection(), coverage, False, False,
                               'PARTIAL: manager knowledge covers 3555 of 66043 players of this save (5.4%); '
                               'results include only those players. Background fill running.', [])

    monkeypatch.setattr(mv, 'prepare_manager_query', prepare)
    return calls


def test_view_switch_runs_on_the_manager_connection(wired):
    result = tools.db_query(None, 's', 'SELECT name, crossing_min FROM m_player_view WHERE crossing_min >= 12 '
                                       'ORDER BY idx', view='manager')
    assert result['view'] == 'manager' and result['rows'] == [['A', 12], ['B', 15]]
    assert result['complete'] is False and result['message'].startswith('PARTIAL:')
    assert result['notes'][0].startswith('PARTIAL:')
    assert any(n.startswith('Partial population') for n in result['notes'])
    assert wired == ['SELECT name, crossing_min FROM m_player_view WHERE crossing_min >= 12 ORDER BY idx']


def test_invalid_view_and_non_select_rejected(wired):
    with pytest.raises(tools.FmdbError):
        tools.db_query(None, 's', 'SELECT 1', view='scout')
    with pytest.raises(Exception):
        tools.db_query(None, 's', 'DELETE FROM m_player_view', view='manager')


def test_building_status_instead_of_timeout(wired, monkeypatch):
    release = threading.Event()
    original = mv.prepare_manager_query

    def slow(*args, **kwargs):
        release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(mv, 'prepare_manager_query', slow)
    engine = tools.engine_for(None, 's')
    first = tools.manager_query(engine, None, 's', 'SELECT name FROM m_player_view', None, 10,
                                None, META, None, wait_s=0.05)
    assert first['status'] == 'building' and first['rows'] == []
    assert 'Building manager knowledge' in first['notes'][0] and 'players covered so far' in first['notes'][0]
    release.set()
    tools._MANAGER['thread'].join(5)
    second = tools.manager_query(engine, None, 's', 'SELECT name FROM m_player_view ORDER BY idx', None, 10,
                                 None, META, None, wait_s=5)
    assert second['rows'] == [['A'], ['B'], ['C']] and 'status' not in second


def _snapshot_with_people(path):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE _fields(table_name TEXT, column_name TEXT, code TEXT, record_type TEXT, name TEXT, comment TEXT,
                             type TEXT, enum_json TEXT, references_table TEXT, source TEXT, status TEXT, note TEXT);
        CREATE TABLE _managed(team_idx INTEGER, club_idx INTEGER, coach TEXT);
        CREATE TABLE person(idx INTEGER PRIMARY KEY, uid INTEGER, class TEXT, club_idx INTEGER);
        INSERT INTO _fields VALUES ('person', 'club_idx', 'Pcti', 'pers', 'Club', NULL, 'database_record_unique_id',
                                    NULL, 'team', 'direct', 'ready', '');
        INSERT INTO _managed VALUES (7, 3, 'Coach');
        INSERT INTO person VALUES (10, 1, 'ACTUAL_PLAYER', 7), (11, 2, 'ACTUAL_PLAYER', 8);
    """)
    con.commit()
    con.close()


def test_manager_read_refuses_players_outside_own_club(tmp_path, monkeypatch):
    path = tmp_path / 'snapshot.sqlite'
    _snapshot_with_people(path)
    tools._manager_read_guard(path, 'player', [10])             # own club: allowed
    tools._manager_read_guard(path, 'club', [0, 1])              # non-person table: allowed
    with pytest.raises(tools.FmdbError, match='fm_get_manager_visible_attributes') as info:
        tools._manager_read_guard(path, 'player', [10, 11])
    assert 'fm_db_query(view="manager")' in str(info.value) and '[11]' in str(info.value)
    engine = SimpleNamespace(save_info=lambda: None)
    monkeypatch.setattr(tools, 'engine_for', lambda bridge, session: engine)
    monkeypatch.setattr(tools, 'current_snapshot', lambda e, **kw: (path, META, None, None, False))
    with pytest.raises(tools.FmdbError, match='not at your club'):
        tools.db_read(None, 's', 'person', [11], view='manager')


def _schema_connection():
    con = sqlite3.connect(':memory:', check_same_thread=False)
    con.execute('CREATE TABLE cols(view TEXT, column_name TEXT, code TEXT, policy TEXT, field TEXT)')
    rows = []
    for view in ('m_player_view', 'm_player', 'm_person'):
        rows += [(view, 'idx', None, mv.IDENTITY, None), (view, 'name', None, mv.PUBLIC, None),
                 (view, 'crossing', 'Pcro', mv.ATTRIBUTE, 'crossing'), (view, 'crossing_min', 'Pcro', mv.ATTRIBUTE,
                                                                        'crossing'),
                 (view, 'current_ability', 'PCAB', mv.NEVER, None)]
    con.executemany('INSERT INTO cols VALUES (?, ?, ?, ?, ?)', rows)
    con.execute('CREATE VIEW m_columns AS SELECT * FROM cols')
    con.execute("CREATE VIEW m_attribute_columns AS SELECT 'crossing' AS field, 'crossing' AS column_name")
    con.execute("CREATE VIEW m_coverage AS SELECT 'universe_players' AS key, 66043 AS value")
    return con


def test_schema_answers_every_listed_manager_view(wired, monkeypatch):
    monkeypatch.setattr(tools, 'knowledge_progress', lambda path: {'covered': 1, 'universe': 1,
                                                                   'tier1_complete': True, 'tier3_complete': True})
    monkeypatch.setattr(mv, 'open_manager_connection', lambda snapshot, knowledge: _schema_connection())
    listed = tools.db_schema(None, 's', view='manager')['views']
    assert {'m_player_view', 'm_scouted_player_view', 'm_player', 'm_person', 'm_columns',
            'm_attribute_columns', 'm_coverage'} <= set(listed)
    for name in listed:
        out = tools.db_schema(None, 's', table=name, view='manager')
        assert out['table'] == name and out['columns'], name
    scouted = tools.db_schema(None, 's', table='m_scouted_player_view', view='manager')
    assert scouted['attributes'] == ['crossing'] and scouted['withheld'] == ['current_ability']
    with pytest.raises(tools.FmdbError, match='m_scouted_player_view'):
        tools.db_schema(None, 's', table='m_nothing', view='manager')


def test_schema_builds_a_stale_snapshot_before_describing_it(tmp_path, monkeypatch):
    """After a reader upgrade the first call of a session was fm_db_schema(table='promise'), which
    answered "Unknown table" from the snapshot of the older layout: only fm_db_query rebuilt it."""
    path = tmp_path / 'snapshot.sqlite'
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE _fields(table_name TEXT, column_name TEXT, code TEXT, label TEXT, kind TEXT,"
                       " sql_type TEXT, enum_json TEXT, references_table TEXT);"
                       "CREATE TABLE _column_state(table_name TEXT, column_name TEXT, class TEXT, rows INTEGER,"
                       " source TEXT, status TEXT, ms REAL);")
    conn.commit()
    conn.close()
    calls = []
    meta = {'save_name': 's', 'game_date': '2030-12-13', 'built_at': 'now', 'fresh': {}, 'notes': []}
    save = SimpleNamespace(game_date='2030-12-13')

    def current_snapshot(engine, *, build_if_needed=True, log=None, force_check=False):
        calls.append(build_if_needed)
        return path, meta, None, save, not build_if_needed          # stale until it is built

    monkeypatch.setattr(tools, 'engine_for', lambda bridge, session: object())
    monkeypatch.setattr(tools, 'current_snapshot', current_snapshot)
    monkeypatch.setattr(tools, '_table_schema', lambda conn, table, include_pending: {'table': table, 'columns': []})
    out = tools.db_schema(None, 's', table='promise')
    assert calls == [False, True]
    assert out['table'] == 'promise' and 'next' not in out
