"""Name columns: carried into a new build by their declared inputs, and computed cell by cell on
the name VM (ondemand.NAME_VM_CODES), on the synthetic game of `_fmdb_fake.py`. No game needed."""
from __future__ import annotations

import sqlite3

import pytest

from fm_live_mcp.fmdb import ondemand

from _fmdb_fake import CODE, FakeEngine, build, statement, use_cache

ROWS = 600


def raw(path, sql, params=()):
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


@pytest.fixture()
def game(tmp_path, monkeypatch):
    use_cache(monkeypatch, tmp_path)
    # 'computed' (Nemu, serial squared) declared a function of 'code' (Ncod, stored): the
    # mechanism under test, not a claim about the fake getter
    monkeypatch.setattr(ondemand, 'DECLARED_INPUTS', {('nati', 'Nemu'): ('Ncod',)})
    engine = FakeEngine(count=ROWS)
    for i in range(ROWS):
        engine.poke(i, CODE, '<i', 1000 + i)
    path, _ = build(engine, tmp_path)
    vm = engine.tracked_vm or engine.vm
    del vm.calls[:]
    return engine, path, vm, tmp_path


def test_declared_cells_are_carried_into_the_next_build(game):
    engine, path, vm, root = game
    first, _ = statement(engine, path, 'SELECT SUM(computed), COUNT(computed) FROM nation')
    assert first['rows'][0][1] == ROWS and vm.count('Nemu') == ROWS
    engine.poke(5, CODE, '<i', 99_999)                  # one row's declared input changes in the game
    engine.refresh_memory()
    path2, builder = build(engine, root)
    assert path2 == path
    carried = raw(path, "SELECT value FROM _build WHERE key='declared_carried'")
    assert '"nation.computed": %d' % (ROWS - 1) in carried[0][0]
    stored = dict(raw(path, 'SELECT idx, computed FROM nation WHERE computed IS NOT NULL'))
    assert len(stored) == ROWS - 1 and 5 not in stored
    assert all(stored[i] == engine.expected(i, 'Nemu') for i in stored)
    before = vm.count('Nemu')
    again, computed = statement(engine, path, 'SELECT SUM(computed), COUNT(computed) FROM nation')
    assert again['rows'] == first['rows'] and vm.count('Nemu') == before + 1      # only row 5
    assert computed['cells'] == 1


def test_inputs_that_gave_two_values_are_not_carried(game):
    engine, path, vm, root = game
    engine.poke(7, CODE, '<i', 1000 + 8)                # rows 7 and 8 share an input, values differ
    engine.refresh_memory()
    build(engine, root)                                 # the stored inputs now say so
    statement(engine, path, 'SELECT COUNT(computed) FROM nation')
    build(engine, root)
    stored = dict(raw(path, 'SELECT idx, computed FROM nation WHERE computed IS NOT NULL'))
    assert 7 not in stored and 8 not in stored and len(stored) == ROWS - 2


def test_name_vm_column_is_computed_for_the_rows_asked_only(game, monkeypatch):
    engine, path, vm, _ = game
    monkeypatch.setattr(ondemand, 'NAME_VM_CODES', {('nati', 'Nemu')})
    calls = []

    class NameVM:
        live_pages = ()

        def begin_read(self):
            calls.append('begin_read')

        def invalidate(self):
            pass

        def get_property(self, pointer, code):
            calls.append(code)
            return vm.get_property(pointer, code)
    monkeypatch.setattr(ondemand, 'name_vm', lambda engine: NameVM())
    result, computed = statement(engine, path, 'SELECT idx FROM nation WHERE computed % 7 = 0 AND idx < 300',
                                 bulk_after=10)
    assert calls.count('Nemu') == 300 and calls[0] == 'begin_read' and calls.count('begin_read') == 1
    assert [c.get('whole_column') for c in computed['columns']] == [None]          # no whole-column pass
    assert len(result['rows']) == sum(1 for i in range(300) if engine.expected(i, 'Nemu') % 7 == 0)
