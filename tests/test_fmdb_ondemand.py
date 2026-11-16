"""Offline tests for on-demand emulated columns (ondemand.py), freshness by content
(freshness.py) and the plan audit (audit.py), on the synthetic game of `_fmdb_fake.py`.

The table has 600 rows: three blocks of `freshness.BLOCK_ROWS` (256, 256, 88). The getter
that on-demand cells are computed with is the fake tracking VM, which records the words it
reads; the read-set hashes come from the real accelerator library, so the tests that need
memoised cells are skipped when it is not built."""
from __future__ import annotations

import ast
from collections import Counter
import itertools
import json
import multiprocessing
import os
from pathlib import Path
import random
import sqlite3
import struct
import subprocess
from types import SimpleNamespace

import pytest

from fm_live_mcp.fmdb import audit, bulkplans, fastvm, freshness, ondemand, snapshot, tools

from _fmdb_fake import BONUS, CODE, POINTS, SPARE, STRINGS, FakeEngine, build, statement, use_cache

ROWS = 600
BLOCK = freshness.BLOCK_ROWS
needs_tracking = pytest.mark.skipif(not fastvm.tracks_reads(),
                                    reason='needs the read-tracking accelerator (scripts/build_vm_accel.sh)')


def scrambled_engine(**kwargs):
    """600 nations whose on-demand inputs are not in idx order: score has 50 distinct values
    (12 rows each), far is distinct for every row."""
    engine = FakeEngine(count=ROWS, **kwargs)
    for i in range(ROWS):
        engine.poke(i, POINTS, '<i', (i * 7919) % 50)
        engine.poke_side(i, (i * 7919) % 10007)
    return engine


@pytest.fixture()
def game(tmp_path, monkeypatch):
    use_cache(monkeypatch, tmp_path)
    engine = scrambled_engine()
    path, builder = build(engine, tmp_path)
    vm = engine.tracked_vm or engine.vm         # the VM on-demand cells are computed with
    del vm.calls[:]                             # the derivation's calls are not the statements'
    return SimpleNamespace(engine=engine, path=path, builder=builder, vm=vm, root=tmp_path)


def raw(path, sql, params=()):
    """Rows of the snapshot file as stored (no on-demand session)."""
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def memo(path, column):
    """(validity bitmap, cells) of one memoised nation column."""
    rows = raw(path, "SELECT valid, cells FROM _memo WHERE table_name='nation' AND column_name=?", (column,))
    return (bytes(rows[0][0] or b''), rows[0][1]) if rows else (b'', 0)


def is_valid(bitmap, idx):
    return bool((idx >> 3) < len(bitmap) and bitmap[idx >> 3] >> (idx & 7) & 1)


def scores(engine):
    return [engine.expected(i, 'Nscr') for i in range(len(engine.pointers))]


# --------------------------------------------------------------------------- query shapes
def test_point_lookup_computes_one_cell(game):
    e = game.engine
    result, computed = statement(e, game.path, 'SELECT score FROM nation WHERE idx = ?', [7])
    assert result['rows'] == [[e.expected(7, 'Nscr')]] == [[((7 * 7919) % 50) * 2 + 1]]
    assert game.vm.calls == [(e.pointers[7], 'Nscr')]
    assert [(c['column'], c['cells']) for c in computed['columns']] == [('nation.score', 1)]
    assert computed['cells'] == 1 and computed['stored'] is (e.tracked_vm is not None)
    assert 'not_computed' not in computed


def test_direct_predicate_computes_only_the_rows_that_pass(game):
    e = game.engine
    result, computed = statement(e, game.path, 'SELECT idx, score, far FROM nation WHERE code BETWEEN 30 AND 59 '
                                               'ORDER BY idx')
    passed = list(range(10, 20))                        # code = idx * 3, a direct column
    assert result['rows'] == [[i, e.expected(i, 'Nscr'), e.expected(i, 'Nfar')] for i in passed]
    assert game.vm.count('Nscr') == game.vm.count('Nfar') == len(passed) and game.vm.count() == 2 * len(passed)
    assert {record for record, _ in game.vm.calls} == {e.pointers[i] for i in passed}
    assert computed['cells'] == 2 * len(passed)


def _filter(e):
    return [[i] for i, s in enumerate(scores(e)) if s >= 91]


def _order(e):
    values = scores(e)
    return [[i, values[i]] for i in sorted(range(ROWS), key=lambda i: (-values[i], i))[:7]]


def _group(e):
    return [[s, n] for s, n in sorted(Counter(scores(e)).items())]


def _join(e):
    return [[sum(n * n for n in Counter(scores(e)).values()), ROWS]]


SHAPES = {
    'filter': ('SELECT idx FROM nation WHERE score >= 91 ORDER BY idx', _filter),
    'order_by': ('SELECT idx, score FROM nation ORDER BY score DESC, idx LIMIT 7', _order),
    'group_by': ('SELECT score, COUNT(*) FROM nation GROUP BY score ORDER BY score', _group),
    'join': ('SELECT COUNT(*), SUM(a.idx = b.idx) FROM nation a JOIN nation b ON a.score = b.score', _join),
}


@needs_tracking
@pytest.mark.parametrize('bulk_after', [ondemand.BULK_AFTER, 64], ids=['cell_by_cell', 'bulk'])
@pytest.mark.parametrize('shape', sorted(SHAPES))
def test_statement_on_the_column_computes_the_whole_column_once(game, shape, bulk_after):
    e = game.engine
    sql, expected = SHAPES[shape]
    result, computed = statement(e, game.path, sql, bulk_after=bulk_after)
    assert result['rows'] == expected(e)
    assert game.vm.count('Nscr') == ROWS == game.vm.count()         # every row once, no other column
    assert sorted(record for record, _ in game.vm.calls) == sorted(e.pointers)
    (column,) = computed['columns']
    assert (column['column'], column['cells']) == ('nation.score', ROWS) and computed['stored'] is True
    assert column.get('whole_column', False) is (bulk_after < ROWS)
    # the snapshot is the memo: the cells, their validity and the read set of each block of rows
    assert raw(game.path, 'SELECT COUNT(score), COUNT(far) FROM nation') == [(ROWS, 0)]
    assert memo(game.path, 'score')[1] == ROWS
    assert raw(game.path, "SELECT COUNT(*) FROM _memo_blocks WHERE table_name='nation'") == [((ROWS + BLOCK - 1) // BLOCK,)]
    again, computed = statement(e, game.path, sql, bulk_after=bulk_after)
    assert again['rows'] == result['rows'] and game.vm.count() == ROWS      # zero getter calls
    assert 'columns' not in computed


def test_view_column_enables_the_base_column_it_is_built_from(game):
    e = game.engine
    conn = sqlite3.connect(game.path)
    conn.execute('CREATE VIEW nation_rating_view AS SELECT n.idx AS idx, n.name AS name, n.score AS rating, '
                 'n.far AS distance FROM nation n')
    conn.executemany('INSERT INTO _view_columns VALUES (?, ?, ?, ?)',           # as views.create_views records them
                     [('nation_rating_view', alias, 'nation', column) for alias, column in (
                         ('idx', 'idx'), ('name', 'name'), ('rating', 'score'), ('distance', 'far'))])
    conn.commit()
    conn.close()
    result, computed = statement(e, game.path, 'SELECT name, rating FROM nation_rating_view WHERE idx IN (3, 4) '
                                               'ORDER BY idx')
    assert result['rows'] == [['Nation 3', e.expected(3, 'Nscr')], ['Nation 4', e.expected(4, 'Nscr')]]
    assert game.vm.calls == [(e.pointers[3], 'Nscr'), (e.pointers[4], 'Nscr')]        # `distance` was not named
    assert [(c['column'], c['cells']) for c in computed['columns']] == [('nation.score', 2)]
    # the labelled view the build creates is a view over the table as well
    result, _ = statement(e, game.path, 'SELECT state_label, far FROM nation_labelled WHERE idx = 5')
    assert result['rows'] == [['rich', e.expected(5, 'Nfar')]] and game.vm.calls[2:] == [(e.pointers[5], 'Nfar')]
    if e.tracked_vm is None:
        return
    # `*` through the view: the cells computed above, NULL elsewhere, nothing computed
    result, computed = statement(e, game.path, 'SELECT * FROM nation_rating_view WHERE idx IN (3, 4, 5) ORDER BY idx')
    assert result['columns'] == ['idx', 'name', 'rating', 'distance']
    assert result['rows'] == [[3, 'Nation 3', e.expected(3, 'Nscr'), None], [4, 'Nation 4', e.expected(4, 'Nscr'), None],
                              [5, 'Nation 5', None, e.expected(5, 'Nfar')]]
    assert len(game.vm.calls) == 3 and computed['not_computed'] == {'nation': 2} and 'columns' not in computed


def test_collection_view_column_enables_the_on_demand_name_it_resolves_to(game):
    """A resolved collection view (sources.create_views) takes a name placeholder's stored
    alternative when there is one, and records every placeholder under the view column it feeds,
    so naming that view column has the on-demand base column computed for the rows it reads
    (before: the planner did not see through the view, and the name read NULL)."""
    from fm_live_mcp.fmdb import sources
    e = game.engine
    conn = sqlite3.connect(game.path)
    conn.executescript(sources.SOURCE_SQL)
    conn.execute('DELETE FROM _source_views')
    template = ('SELECT a.idx AS pair_idx, a.{nation.Nscr|Nfar} AS home_score, b.{nation.Nfar} AS away_far, '
                "COALESCE(NULLIF(b.{nation.Nscr|Nnam}, ''), 'none') AS away_name "
                'FROM nation a JOIN nation b ON b.idx = a.idx + 1 WHERE a.{nation.Ncod} >= 0')
    conn.execute("INSERT INTO _source_views VALUES ('nation_pair_view', 'test', 'pairs', ?, '{}')", (template,))
    assert 'nation_pair_view' in sources.create_views(conn)
    conn.commit()
    lineage = sorted(conn.execute("SELECT column_name, base_table, base_column FROM _view_columns "
                                  "WHERE view='nation_pair_view'").fetchall())
    conn.close()
    # Nscr and Nfar are both on demand: the first alternative; for away_name the stored name wins
    assert ('home_score', 'nation', 'score') in lineage and ('home_score', 'nation', 'far') not in lineage
    assert ('away_far', 'nation', 'far') in lineage
    assert ('away_name', 'nation', 'name') in lineage and ('away_name', 'nation', 'score') not in lineage
    # the WHERE placeholder feeds every row the view yields: every column depends on it
    assert {c for c, _, b in lineage if b == 'code'} == {'pair_idx', 'home_score', 'away_far', 'away_name'}
    result, computed = statement(e, game.path, 'SELECT pair_idx, home_score FROM nation_pair_view '
                                               'WHERE pair_idx IN (3, 4) ORDER BY pair_idx')
    assert result['rows'] == [[3, e.expected(3, 'Nscr')], [4, e.expected(4, 'Nscr')]]
    assert game.vm.calls == [(e.pointers[3], 'Nscr'), (e.pointers[4], 'Nscr')]      # away_far was not named
    assert [(c['column'], c['cells']) for c in computed['columns']] == [('nation.score', 2)]
    result, computed = statement(e, game.path, 'SELECT away_far FROM nation_pair_view WHERE pair_idx = 7')
    assert result['rows'] == [[e.expected(8, 'Nfar')]] and game.vm.calls[2:] == [(e.pointers[8], 'Nfar')]


# --------------------------------------------------------------------------- the SELECT * rule
@needs_tracking
def test_select_star_never_computes(game):
    e = game.engine
    statement(e, game.path, 'SELECT score FROM nation WHERE idx = 3')       # an earlier statement named the column
    assert len(game.vm.calls) == 1
    on_demand = {r[0] for r in raw(game.path, "SELECT DISTINCT column_name FROM _column_state WHERE "
                                              "table_name='nation' AND status='on_demand'")}
    assert {'score', 'far', 'computed', 'slow', 'badly_planned'} <= on_demand
    result, computed = statement(e, game.path, 'SELECT * FROM nation')
    assert len(game.vm.calls) == 1                                          # zero getter calls
    assert result['row_count'] == ROWS and not result['truncated']
    at = {name: k for k, name in enumerate(result['columns'])}
    for row in result['rows']:
        idx = row[at['idx']]
        assert row[at['code']] == idx * 3 and row[at['name']] == f'Nation {idx}'        # direct columns: stored
        assert row[at['score']] == (e.expected(3, 'Nscr') if idx == 3 else None)
        assert all(row[at[name]] is None for name in on_demand - {'score'})
    assert computed['not_computed'] == {'nation': len(on_demand)}
    assert 'columns' not in computed and 'cells' not in computed
    # an alias star is the same rule; a column named next to `*` is computed
    result, computed = statement(e, game.path, 'SELECT n.* FROM nation n WHERE n.idx = 8')
    assert len(game.vm.calls) == 1 and result['rows'][0][at['score']] is None and 'not_computed' in computed
    result, computed = statement(e, game.path, 'SELECT *, score AS named FROM nation WHERE idx = 9')
    assert game.vm.calls[1:] == [(e.pointers[9], 'Nscr')]
    assert result['rows'][0][at['score']] == result['rows'][0][-1] == e.expected(9, 'Nscr')
    assert result['rows'][0][at['far']] is None
    assert computed['cells'] == 1 and computed['not_computed'] == {'nation': len(on_demand) - 1}


# --------------------------------------------------------------------------- validity of memoised cells
@needs_tracking
def test_changed_word_drops_the_cells_of_its_block_only(game):
    e, vm = game.engine, game.vm
    total = 'SELECT SUM(score), COUNT(score) FROM nation'
    first, _ = statement(e, game.path, total)
    assert first['rows'] == [[sum(scores(e)), ROWS]] and vm.count('Nscr') == ROWS
    # a word the getter read for record 300 changes in the game (block 1: rows 256..511)
    old = e.expected(300, 'Nscr')
    e.poke(300, POINTS, '<i', 4000)
    e.refresh_memory()                          # a new memory generation, as every content check starts one
    before = len(vm.calls)
    second, computed = statement(e, game.path, total)
    assert second['rows'] == [[first['rows'][0][0] - old + 8001, ROWS]]
    assert sorted(vm.calls[before:]) == sorted((p, 'Nscr') for p in e.pointers[BLOCK:2 * BLOCK])
    assert computed['memo_blocks_dropped'] == 1 and computed['cells'] == BLOCK
    # a word on the same page that no getter call read: nothing is computed
    e.poke(300, SPARE, '<Q', 0xDEADBEEF)
    e.refresh_memory()
    third, computed = statement(e, game.path, total)
    assert third['rows'] == second['rows'] and len(vm.calls) == before + BLOCK
    assert 'memo_blocks_dropped' not in computed and 'columns' not in computed
    # a point lookup after a change computes its row; the other cells of the block are NULL in the file
    e.poke(590, POINTS, '<i', 7)
    e.refresh_memory()
    fourth, computed = statement(e, game.path, 'SELECT score FROM nation WHERE idx = 590')
    assert fourth['rows'] == [[15]] and vm.calls[before + BLOCK:] == [(e.pointers[590], 'Nscr')]
    assert computed['memo_blocks_dropped'] == 1
    assert raw(game.path, 'SELECT COUNT(score) FROM nation') == [(2 * BLOCK + 1,)]
    bitmap, cells = memo(game.path, 'score')
    assert cells == 2 * BLOCK + 1 and is_valid(bitmap, 590) and not is_valid(bitmap, 589) and is_valid(bitmap, 511)
    fifth, _ = statement(e, game.path, total)
    assert fifth['rows'] == [[sum(scores(e)), ROWS]] and len(vm.calls) == before + BLOCK + 1 + (ROWS - 2 * BLOCK - 1)


@needs_tracking
def test_value_reached_through_a_pointer_is_part_of_the_read_set(game):
    e, vm = game.engine, game.vm
    statement(e, game.path, 'SELECT SUM(score), SUM(far) FROM nation')
    assert vm.count('Nscr') == vm.count('Nfar') == ROWS
    e.poke_side(10, 123456)                     # the side object of record 10 lies on another page than the record
    e.refresh_memory()
    before = len(vm.calls)
    result, computed = statement(e, game.path, 'SELECT far FROM nation WHERE idx IN (10, 11, 400) ORDER BY idx')
    assert result['rows'] == [[123463], [e.expected(11, 'Nfar')], [e.expected(400, 'Nfar')]]
    # block 0 was dropped (rows 10 and 11 are computed again); row 400 of block 1 is still memoised
    assert sorted(vm.calls[before:]) == sorted([(e.pointers[10], 'Nfar'), (e.pointers[11], 'Nfar')])
    assert computed['memo_blocks_dropped'] == 1
    # a block has one read set for all columns of the table: score lost its cells of block 0 as well
    assert raw(game.path, 'SELECT COUNT(score), COUNT(far) FROM nation') == [(ROWS - BLOCK, ROWS - BLOCK + 2)]
    before = len(vm.calls)
    result, _ = statement(e, game.path, 'SELECT COUNT(score) FROM nation')
    assert result['rows'] == [[ROWS]] and sorted(vm.calls[before:]) == sorted((p, 'Nscr') for p in e.pointers[:BLOCK])


def test_without_read_tracking_cells_are_computed_for_every_statement(tmp_path, monkeypatch):
    use_cache(monkeypatch, tmp_path)
    e = scrambled_engine(tracking=False)
    path, _ = build(e, tmp_path)
    sql = 'SELECT score FROM nation WHERE idx IN (1, 2, 3) ORDER BY idx'
    for repeat in (1, 2):
        before = e.vm.count('Nscr')
        result, computed = statement(e, path, sql)
        assert result['rows'] == [[e.expected(i, 'Nscr')] for i in (1, 2, 3)]
        assert e.vm.count('Nscr') == before + 3, repeat
        assert computed['stored'] is False and 'read-tracking accelerator' in computed['note']
    # a cell that cannot be checked later is never shown as memoised
    before = e.vm.count()
    result, computed = statement(e, path, 'SELECT * FROM nation WHERE idx = 2')
    assert result['rows'][0][result['columns'].index('score')] is None and e.vm.count() == before
    assert memo(path, 'score')[1] == 0 and raw(path, 'SELECT COUNT(*) FROM _memo_blocks') == [(0,)]


# --------------------------------------------------------------------------- direct rows by content
DIRECT = 'SELECT idx, uid, class, code, name, "name_Ndup", neighbour_idx, state FROM nation ORDER BY idx'


def test_refresh_updates_exactly_the_row_whose_bytes_changed(game):
    e = game.engine
    before = raw(game.path, DIRECT)
    e.poke(300, CODE, '<i', 987654)
    result = freshness.refresh(e, game.path, force=True)
    assert result['rows_refreshed'] == 1 and result['by_table'] == {'nation': 1}
    assert (result['pages_changed'], result['blocks_checked'], result['blocks_changed'], result['rounds']) == (1, 1, 1, 1)
    assert 'still_changing' not in result and result['checked_ms_ago'] >= 0
    after = raw(game.path, DIRECT)
    assert after[300] == (300, 1300, 'NATION', 987654, 'Nation 300', 'Nation 300', 301, 0)
    assert after[:300] == before[:300] and after[301:] == before[301:]
    # a value reached through a pointer: the name string of record 5
    e.memory.load(STRINGS + 5 * 0x40, struct.pack('<I', 6) + b'Utopia')
    result = freshness.refresh(e, game.path, force=True)
    assert result['rows_refreshed'] == 1 and result['pages_changed'] == 1
    assert raw(game.path, 'SELECT name, "name_Ndup", code FROM nation WHERE idx = 5') == [('Utopia', 'Utopia', 15)]
    # nothing changed: no block is evaluated
    result = freshness.refresh(e, game.path, force=True)
    assert (result['pages_changed'], result['rows_refreshed'], result['rounds']) == (0, 0, 0)
    assert result['pages_checked'] > 0
    conn = sqlite3.connect(game.path)
    assert freshness.table_seq(conn, 'nation') == 2 == freshness.get_fresh(conn, 'change_seq')
    conn.close()
    fresh = tools.snapshot_meta(game.path)['fresh']
    assert fresh['rows_refreshed'] == 0 and fresh['checked_ms_ago'] >= 0 and fresh['checked_at']


def test_refresh_does_not_evaluate_a_block_whose_windows_did_not_change(game, monkeypatch):
    e = game.engine
    evaluated = []
    real = bulkplans.evaluate
    monkeypatch.setattr(bulkplans, 'evaluate', lambda *args, **kwargs: evaluated.append(1) or real(*args, **kwargs))
    before = raw(game.path, DIRECT)
    # bytes on a page the direct rows were read from, outside every window a plan read
    e.poke(300, SPARE, '<Q', 0xFEEDFACE)
    e.poke(301, POINTS, '<i', 77)
    result = freshness.refresh(e, game.path, force=True)
    assert result['pages_changed'] == 1 and result['blocks_checked'] == 1
    assert (result['blocks_changed'], result['rows_refreshed'], result['rounds']) == (0, 0, 0)
    assert not evaluated and raw(game.path, DIRECT) == before
    # the page has its new hash: the next check does not see it as changed
    assert freshness.refresh(e, game.path, force=True)['pages_changed'] == 0


def test_refresh_follows_reallocation_growth_and_removal(game):
    e, vm = game.engine, game.vm
    tracking = e.tracked_vm is not None
    statement(e, game.path, 'SELECT COUNT(score) FROM nation')              # memoise the column
    calls = len(vm.calls)
    grown, replaced = e.new_record(700, neighbour=3), e.new_record(800, neighbour=4)
    pointers = list(e.pointers)
    pointers[10] = replaced
    e.set_pointers(pointers + [grown])          # a new vector: new list, new identity
    result = freshness.refresh(e, game.path, force=True)
    assert result['records_moved'] == {'nations': 2}
    assert result['rows_refreshed'] == 2 and result['by_table'] == {'nation': 2}       # one insert, one update
    assert raw(game.path, 'SELECT idx, uid, class, code, name, neighbour_idx FROM nation WHERE idx IN (9, 10, 600) '
                          'ORDER BY idx') == [(9, 1009, 'NATION', 27, 'Nation 9', 10),
                                              (10, 1800, 'NATION', 2400, 'Nation 800', 4),
                                              (600, 1700, 'NATION', 2100, 'Nation 700', 3)]
    assert raw(game.path, "SELECT rows, classes_json FROM _tables WHERE table_name='nation'") == \
        [(ROWS + 1, json.dumps({'NATION': ROWS + 1}))]
    conn = sqlite3.connect(game.path)
    live = freshness.load_live(conn)['nations']
    conn.close()
    assert live.pointers == e.pointers and live.uids[10] == 1800 and live.uids[600] == 1700
    assert len(vm.calls) == calls                                           # a content check runs no getter
    if tracking:
        # the memoised cell of the idx whose record was replaced is dropped; its neighbours keep theirs
        bitmap, cells = memo(game.path, 'score')
        assert not is_valid(bitmap, 10) and is_valid(bitmap, 9) and is_valid(bitmap, 11) and cells == ROWS - 1
    result, _ = statement(e, game.path, 'SELECT idx, score FROM nation WHERE idx IN (9, 10, 600) ORDER BY idx')
    assert result['rows'] == [[9, e.expected(9, 'Nscr')], [10, 1801], [600, 1601]]
    if tracking:
        assert sorted(vm.calls[calls:]) == sorted([(replaced, 'Nscr'), (grown, 'Nscr')])
    # the last record leaves the table
    e.set_pointers(e.pointers[:-1])
    result = freshness.refresh(e, game.path, force=True)
    assert result['records_moved'] == {'nations': 1} and result['rows_refreshed'] == 1
    assert raw(game.path, 'SELECT COUNT(*), MAX(idx) FROM nation') == [(ROWS, ROWS - 1)]
    assert raw(game.path, "SELECT rows FROM _tables WHERE table_name='nation'") == [(ROWS,)]
    if tracking:
        bitmap, cells = memo(game.path, 'score')
        assert not is_valid(bitmap, 600) and is_valid(bitmap, 10) and cells == ROWS


@needs_tracking
def test_replaced_record_keeps_no_stored_cell_of_the_previous_record(game):
    e = game.engine
    statement(e, game.path, 'SELECT COUNT(score) FROM nation')
    pointers = list(e.pointers)
    pointers[10] = e.new_record(800)
    e.set_pointers(pointers)
    assert freshness.refresh(e, game.path, force=True)['records_moved'] == {'nations': 1}
    with e.lock:                                # what tools.manager_prewarm does before a masked `*`
        session = ondemand.Session(e, game.path)
        session.check_stored('nation')
        session.finish()
    assert raw(game.path, 'SELECT uid, score FROM nation WHERE idx = 10') == [(1800, None)]


def test_block_that_keeps_changing_is_not_published(game):
    e = game.engine
    step = itertools.count(1)
    e.poke(300, CODE, '<i', 5000)
    # the game writes the field again every time the pages are read again after an evaluation
    e.memory.before_reread = lambda bases: e.poke(300, CODE, '<i', 5000 + next(step))
    result = freshness.refresh(e, game.path, force=True)
    assert result['still_changing'] == {'nation': 1} and result['rounds'] == freshness.MAX_ROUNDS
    assert result['rows_refreshed'] == 0 and result['blocks_changed'] == 1
    assert raw(game.path, 'SELECT code FROM nation WHERE idx = 300') == [(900,)]       # the row keeps its old value
    # the block keeps its old CRC, so the next check evaluates it again; the bytes are at rest now
    e.memory.before_reread = None
    result = freshness.refresh(e, game.path, force=True)
    assert 'still_changing' not in result and result['rows_refreshed'] == 1 and result['rounds'] == 1
    assert raw(game.path, 'SELECT code FROM nation WHERE idx = 300') == [(5000 + freshness.MAX_ROUNDS,)]
    assert freshness.refresh(e, game.path, force=True)['pages_changed'] == 0


def test_refresh_is_reused_within_the_interval_and_refuses_another_process(game):
    e = game.engine
    first = freshness.refresh(e, game.path, force=True)
    assert 'reused' not in first
    again = freshness.refresh(e, game.path, min_interval=3600.0)        # a check younger than the interval is reused
    assert again['reused'] is True and again['checked_at'] == first['checked_at']
    assert freshness.CHECK_INTERVAL_S > 0
    assert 'reused' not in freshness.refresh(e, game.path, min_interval=0.0)
    e.date = '2030-12-11'                                   # the date is the date of the check
    assert freshness.refresh(e, game.path, force=True)['game_date'] == '2030-12-11'
    assert raw(game.path, 'SELECT game_date FROM _snapshot') == [('2030-12-11',)]
    built_at = tools.snapshot_meta(game.path)['built_at']
    path, meta, refreshed, _, stale = tools.current_snapshot(e, force_check=True)
    assert path == game.path and set(refreshed) == {'checked'} and not stale and meta['built_at'] == built_at
    e.process_key = (2, 'fake', 'later')
    with pytest.raises(freshness.Rebuild, match='process'):
        freshness.refresh(e, game.path, force=True)
    path, meta, refreshed, _, stale = tools.current_snapshot(e)
    assert refreshed['rebuilt'] is True and 'another game process' in refreshed['reason'] and not stale
    assert meta['process'] == ['2', 'fake', 'later'] and meta['fresh']['checked_ms_ago'] >= 0


def test_a_collection_read_that_failed_for_part_of_a_statement_is_noted(tmp_path, monkeypatch):
    """What a collection table could not read for a statement is in the answer's notes: rows that
    are missing because a read failed never look like rows that do not exist."""
    from fm_live_mcp.fmdb import sources
    use_cache(monkeypatch, tmp_path)
    e = scrambled_engine()
    build(e, tmp_path)
    monkeypatch.setattr(tools, 'engine_for', lambda bridge, session: e)
    monkeypatch.setitem(tools._STATE, 'audited_at', -1e9)
    failed = ['club 414: PTin 2025: data key Cpts: external call _pthread_condattr_init']
    monkeypatch.setattr(sources, 'refresh_for_query',
                        lambda *args, **kwargs: {'club_transfer_history': {'added': 0, 'not_read': failed}})
    out = tools.db_query(None, 's', 'SELECT idx FROM nation WHERE idx < 2 ORDER BY idx')
    assert out['rows'] == [[0], [1]] and out['collections']['club_transfer_history']['not_read'] == failed
    assert [n for n in out['notes'] if n.startswith('club_transfer_history: not read')] == [
        sources.not_read_note('club_transfer_history', failed)]


# --------------------------------------------------------------------------- no detached processes
def test_tools_start_no_process(tmp_path, monkeypatch):
    use_cache(monkeypatch, tmp_path)
    e = scrambled_engine()
    path, _ = build(e, tmp_path)                # the plans exist (scripts/fmdb_snapshot.py derives them)
    path.unlink()                               # the tool call builds the snapshot itself
    started = []

    def refuse(*args, **kwargs):
        started.append(args)
        raise AssertionError(f'a process was started: {args!r}')

    monkeypatch.setattr(subprocess, 'Popen', refuse)
    for name in ('fork', 'forkpty', 'posix_spawn', 'posix_spawnp', 'system', 'popen', 'execv', 'execve'):
        if hasattr(os, name):
            monkeypatch.setattr(os, name, refuse)
    monkeypatch.setattr(multiprocessing.Process, 'start', refuse)
    monkeypatch.setattr(tools, 'engine_for', lambda bridge, session: e)
    monkeypatch.setitem(tools._STATE, 'audited_at', -1e9)      # not the process's first statement
    vm = e.tracked_vm or e.vm
    del vm.calls[:]

    def asked(code):
        return {record for record, c in vm.calls if c == code}

    assert tools.db_schema(None, 's')['snapshot'] is None                   # no snapshot: the schema says so
    first = tools.db_query(None, 's', 'SELECT idx, score FROM nation WHERE code < 30 ORDER BY idx')
    assert first['rows'] == [[i, e.expected(i, 'Nscr')] for i in range(10)]
    assert first['refreshed']['rebuilt'] is True and first['refreshed']['reason'] == 'no snapshot yet'
    # the statement computed the ten rows that passed; the audit that follows may compute memoised cells
    # again (audit.py), which are cells of the same ten records
    assert first['computed']['cells'] == 10 and vm.count('Nscr') >= 10
    assert asked('Nscr') == set(e.pointers[:10]) and not asked('Nfar')
    assert first['snapshot']['stale'] is False and first['snapshot']['checked_ms_ago'] >= 0
    assert first['snapshot']['rows_refreshed'] == 0
    assert 'error' not in first['audit'] and first['audit']['disagreed'] == 0 and first['audit']['cells'] > 0
    assert [(c['column'], c['cells']) for c in first['computed']['columns']] == [('nation.score', 10)]
    # notes only when they change what to do: no constant lines (consistency, check time, audit summary)
    assert first['notes'] == []

    star = tools.db_query(None, 's', 'SELECT * FROM nation WHERE idx < 3 ORDER BY idx', max_rows=10)
    assert asked('Nscr') == set(e.pointers[:10]) and not asked('Nfar')
    assert 'columns' not in star['computed'] and star['computed']['not_computed']['nation'] >= 5
    assert any('Name a column to have it computed' in note for note in star['notes'])

    schema = tools.db_schema(None, 's')
    assert schema['tables']['nation']['rows'] == ROWS and schema['tables']['nation']['on_demand'] >= 5
    described = tools.db_schema(None, 's', table='nation')
    assert described['table'] == 'nation'

    e.poke(6, CODE, '<i', 4243)                 # the game moves: the next statement's check reads the row again
    import time as _time
    _time.sleep(freshness.CHECK_INTERVAL_S + 0.1)
    moved = tools.db_query(None, 's', 'SELECT code FROM nation WHERE idx = 6')
    assert moved['rows'] == [[4243]] and moved['snapshot']['rows_refreshed'] == 1
    assert moved['notes'] == ['1 rows had changed in the game since the last check and were read again before '
                              'this answer.']

    e.poke(5, CODE, '<i', 4242)                 # the game moves; an explicit refresh checks at once
    out = tools.db_refresh(None, 's', columns=['nation.far'])
    assert out['checked']['checked']['rows_refreshed'] == 1
    assert out['computed'][0]['filled'] == {'far': ROWS} and out['computed'][0]['complete'] is True
    assert vm.count('Nfar') == ROWS and asked('Nfar') == set(e.pointers) and asked('Nscr') == set(e.pointers[:10])
    assert out['counts']['nation']['rows'] == ROWS and any('no background process' in note for note in out['notes'])
    second = tools.db_query(None, 's', 'SELECT code, far FROM nation WHERE idx = 5')
    assert second['rows'] == [[4242, e.expected(5, 'Nfar')]]
    if e.tracked_vm is not None:
        assert 'columns' not in second.get('computed', {})                  # memoised: nothing to compute

    rebuilt = tools.db_refresh(None, 's')       # an explicit rebuild runs in this process as well
    assert rebuilt['rebuilt']['timing']['total'] >= 0 and rebuilt['counts']['nation']['rows'] == ROWS
    assert audit.run(e, path, budget_cpu=0.05, rng=random.Random(3)) is not None
    assert started == []
    assert not [p for p in tmp_path.rglob('*') if p.name.endswith(('.pid', '.lock')) or 'fill' in p.name]


def test_database_modules_have_no_process_code():
    root = Path(snapshot.__file__).parent
    assert not (root / 'fill.py').exists() and not (root / 'consistency.py').exists()
    for name in ('tools.py', 'snapshot.py', 'ondemand.py', 'freshness.py', 'audit.py', 'query.py', 'views.py',
                 'sources/__init__.py'):
        tree = ast.parse((root / name).read_text())
        top_level = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_level |= {alias.name.split('.')[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                top_level.add((node.module or '').split('.')[0])
                top_level |= {alias.name for alias in node.names}
        assert not top_level & {'subprocess', 'multiprocessing', 'fill'}, name
        for node in ast.walk(tree):
            named = node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else None
            assert named != 'Popen', f'{name}:{node.lineno} uses Popen'
    for name in ('needed_columns', 'coverage_note', 'fill_progress', '_building'):
        assert not hasattr(tools, name), name
    assert callable(tools.manager_prewarm)


# --------------------------------------------------------------------------- plan audit
def test_audit_demotes_a_plan_that_disagrees_with_the_getter(game):
    e = game.engine
    first = audit.run(e, game.path, budget_cpu=0.2, rng=random.Random(1))
    assert first['cells'] > 0 and first['disagreed'] == 0 and 'demoted_now' not in first
    conn = sqlite3.connect(game.path)
    state = json.loads(freshness.get_fresh(conn, 'audit'))
    conn.close()
    assert state['cells'] == first['cells'] and state['runs'] == 1 and state['demoted'] == []
    assert state['direct_cells'] == 5 * ROWS                # code, name, name_Ndup, neighbour_idx, state
    assert state['coverage'] == round(state['cells'] / state['direct_cells'], 6)
    # the getter takes a path the plan does not follow for every fourth record: Ncod = code + bonus
    for i in range(0, ROWS, 4):
        e.poke(i, BONUS, '<i', 5)
    assert freshness.refresh(e, game.path, force=True)['rows_refreshed'] == 0      # the plan reads the same bytes
    second = audit.run(e, game.path, budget_cpu=0.2, rng=random.Random(2))
    assert [(d['class'], d['code'], d['column']) for d in second['demoted_now']] == [('NATION', 'Ncod', 'nation.code')]
    assert second['disagreed'] >= 1 and second['cells'] > first['cells']
    store = snapshot.plan_store(e)
    plan = store.get('NATION', 'Ncod')
    assert plan['status'] == 'emulate-only' and plan['reason'].startswith('audit:') and plan['origin'] == 'audit'
    for code in ('Nnam', 'Ndup', 'Nref', 'Nsta'):           # the plans that agree stay
        assert store.get('NATION', code)['status'] == 'direct', code
    conn = sqlite3.connect(game.path)
    grown = json.loads(freshness.get_fresh(conn, 'audit'))
    notes = json.loads(conn.execute('SELECT notes FROM _snapshot').fetchone()[0])
    conn.close()
    assert grown['cells'] == second['cells'] > state['cells'] and grown['runs'] == 2
    assert grown['disagreed'] == second['disagreed'] and [d['code'] for d in grown['demoted']] == ['Ncod']
    assert grown['coverage'] > state['coverage']
    assert sum(note.startswith(audit.AUDIT_NOTE) for note in notes) == 1 and '1 plans demoted' in notes[-1]
    # the next tool call turns the demoted plan's column into an on-demand column in place (no rebuild)
    built = raw(game.path, 'SELECT built_at FROM _snapshot')
    path, meta, refreshed, _, stale = tools.current_snapshot(e)
    assert 'rebuilt' not in refreshed and not stale and raw(path, 'SELECT built_at FROM _snapshot') == built
    assert raw(path, "SELECT source, status FROM _column_state WHERE table_name='nation' AND column_name='code'") == \
        [('emulated', 'on_demand')]
    result, _ = statement(e, path, 'SELECT code FROM nation WHERE idx IN (4, 5) ORDER BY idx')
    assert result['rows'] == [[4 * 3 + 5], [5 * 3]]


@needs_tracking
def test_audit_recomputes_memoised_cells(game):
    e = game.engine
    statement(e, game.path, 'SELECT COUNT(score) FROM nation')
    clean = audit.run(e, game.path, budget_cpu=0.2, rng=random.Random(4))
    assert clean['checked_now'] > 0 and 'memo_disagreed' not in clean
    conn = sqlite3.connect(game.path)
    assert json.loads(freshness.get_fresh(conn, 'audit'))['memo_cells'] > 0
    assert freshness.get_fresh(conn, 'nomemo:nation.score') is None
    # stored cells that no longer equal the getter although their read set did not move
    conn.execute('UPDATE nation SET score = -1')
    conn.commit()
    conn.close()
    found = audit.run(e, game.path, budget_cpu=0.2, rng=random.Random(5))
    assert found['memo_disagreed'] and found['memo_disagreed'][0]['column'] == 'nation.score'
    conn = sqlite3.connect(game.path)
    assert freshness.get_fresh(conn, 'nomemo:nation.score') == 1
    conn.close()
    # the column is computed for every statement from now on and never kept
    calls = game.vm.count('Nscr')
    for repeat in (1, 2):
        result, _ = statement(e, game.path, 'SELECT score FROM nation WHERE idx = 20')
        assert result['rows'] == [[e.expected(20, 'Nscr')]] and game.vm.count('Nscr') == calls + repeat


def test_content_check_writes_only_the_table_vectors_that_changed(game):
    """save_live(only_changed=True) skips a vector whose digest equals the stored one: a check
    where no record moved rewrote megabytes of vectors and paid a 1 to 4 s commit before."""
    conn = sqlite3.connect(game.path)
    try:
        live = freshness.load_live(conn)
        kind = next(k for k, lt in live.items() if len(lt.pointers) > 1)
        assert freshness.save_live(conn, live) == len(live)                  # unconditional: every vector
        assert freshness.save_live(conn, live, only_changed=True) == 0       # digests stored with them
        live[kind].pointers[1] += 8
        assert freshness.save_live(conn, live, only_changed=True) == 1
        conn.commit()
        assert freshness.load_live(conn)[kind].pointers[1] == live[kind].pointers[1]
    finally:
        conn.close()
    # a check reuses this process's vectors when nobody else checked since, and stays correct
    e = game.engine
    e.poke(9, CODE, '<i', 777)
    first = freshness.refresh(e, game.path, force=True)
    assert first['rows_refreshed'] == 1 and e._fmdb_live is not None
    e.poke(9, CODE, '<i', 778)
    second = freshness.refresh(e, game.path, force=True)
    assert second['rows_refreshed'] == 1
    assert raw(game.path, 'SELECT code FROM nation WHERE idx = 9') == [(778,)]
