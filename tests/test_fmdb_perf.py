"""Offline tests for the mechanisms added for speed (docs/fmdb/PERFORMANCE.md): fixed-stride
window reads, window evaluation of direct plans, shipped plans verified on load, one UPDATE
per row when computed cells are stored, and the column-wise conversions of the snapshot writer."""
from __future__ import annotations

import gzip
import json
import random
import sqlite3
import struct
from types import SimpleNamespace

import pytest

from fm_live_mcp.fmdb import bulkplans, ondemand, snapshot
from fm_live_mcp.fmdb.bulkplans import Missing, Ref
from fm_live_mcp.fmdb.memory import LiveMemory, MemoryReadError, SnapshotMemory, _join_windows

from test_fmdb_memory import BASE, make_helper, page_bytes, pages_cfg
from _fmdb_fake import FakeEngine, statement, use_cache

PAGE = 16384


# --------------------------------------------------------------------------- windows
def reference(memory, addresses, length):
    return _join_windows(memory.read_many([(a, length) for a in addresses]), length)


@pytest.mark.parametrize('max_cache_pages', [64, None], ids=['pages', 'scatter'])
def test_windows_equal_item_reads_on_both_routes(tmp_path, max_cache_pages):
    helper = make_helper(tmp_path, pages=pages_cfg(BASE, BASE + PAGE, BASE + 3 * PAGE))
    with LiveMemory(42, helper=helper, max_cache_pages=max_cache_pages) as m:
        addresses = [BASE + 8, BASE + 200, BASE + PAGE - 4,      # the third crosses into the next page
                     BASE + PAGE + 16, BASE + 2 * PAGE + 8,      # unreadable page
                     BASE + 3 * PAGE + 100, BASE + 3 * PAGE - 4]  # starts in the unreadable page
        payload, bad = m.windows(addresses, 16)
        assert len(payload) == len(addresses) * 16
        assert bad == [4, 6]
        assert payload[64:80] == bytes(16) and payload[96:112] == bytes(16)
        with LiveMemory(42, helper=helper) as plain:
            assert (payload, bad) == reference(plain, addresses, 16)
        assert payload[32:48] == page_bytes(BASE)[-4:] + page_bytes(BASE + PAGE)[:12]
        assert m.windows([], 8) == (b'', [])
        with pytest.raises(MemoryReadError):
            m.windows([BASE, 2 ** 64 - 4], 16)                   # as read_many: an invalid address is an error


def test_windows_page_route_reads_each_page_once(tmp_path):
    helper = make_helper(tmp_path, pages=pages_cfg(BASE, BASE + PAGE))
    with LiveMemory(42, helper=helper, max_cache_pages=64) as m:
        addresses = [BASE + 64 * i for i in range(400)]
        payload, bad = m.windows(addresses, 32)
        assert not bad and m.stats.round_trips == 1 and m.stats.items == 2      # two pages, one batch
        assert payload == b''.join(page_bytes(BASE)[64 * i:64 * i + 32] if 64 * i + 32 <= PAGE else
                                   (page_bytes(BASE) + page_bytes(BASE + PAGE))[64 * i:64 * i + 32]
                                   for i in range(400))
        m.windows(addresses, 8)
        assert m.stats.round_trips == 1                                           # served from the page cache


def test_default_windows_on_snapshot_memory():
    memory = SnapshotMemory()
    memory.load(0x3_0000_0000, bytes(range(64)))
    payload, bad = memory.windows([0x3_0000_0000, 0x9_0000_0000, 0x3_0000_0020], 8)
    assert bad == [1] and payload == bytes(range(8)) + bytes(8) + bytes(range(32, 40))


# --------------------------------------------------------------------------- window evaluation
def random_world(seed):
    """Records with scalars, child pointers (some null), strings (shared, long, empty, missing) and
    record references; a few records sit on unreadable memory."""
    rng = random.Random(seed)
    memory = SnapshotMemory()
    strings = []
    for k in range(40):
        text = ('näme %d ' % k) * rng.choice((1, 1, 2, 12))
        at = 0x6_0000_0000 + k * 0x400
        memory.load(at, struct.pack('<I', len(text.encode())) + text.encode())
        strings.append(at)
    huge = 0x6_0010_0000
    memory.load(huge, struct.pack('<I', 5_000_000))               # implausible length
    targets = []
    for k in range(30):
        at = 0x7_0000_0000 + k * 0x40
        memory.load(at, bytes(12) + struct.pack('<II', 5000 + k, rng.choice((0, 77 + k))) + bytes(44))
        targets.append(at)
    records = []
    for i in range(600):
        record = 0x5_0000_0000 + i * 0x180
        child = 0x5_1000_0000 + i * 0x40
        has_child = rng.random() < 0.8
        if has_child:
            memory.load(child, struct.pack('<HhIf', rng.randrange(366), rng.choice((0, 1999, 2030)),
                                           rng.randrange(1 << 20), rng.random()) + bytes(52))
        data = bytearray(0x180)
        struct.pack_into('<Q', data, 0x00, child if has_child else 0)
        struct.pack_into('<Q', data, 0x08, rng.choice(strings + [0, 0, huge, 0x9_0000_0000]))
        struct.pack_into('<Q', data, 0x10, rng.choice(targets + [0, 0x9_0000_1000]))
        struct.pack_into('<i', data, 0x20, rng.randrange(-50, 50))
        data[0x24] = rng.randrange(256)
        data[0x25] = rng.choice((0, 0, 0x40, 0xFF))
        struct.pack_into('<d', data, 0x28, rng.random() * 100)
        data[0x148] = rng.randrange(0, 110)
        data[0x170] = rng.choice((0, 0x80))
        memory.load(record, bytes(data))
        records.append(record)
    records[17] = 0x9_0000_2000                                  # unreadable record
    records[300] = 0                                             # null table entry
    plans = {
        'int': {'chain': [0x20], 'width': 4, 'signed': True, 'type': 'int', 'transform': 'identity'},
        'byte': {'chain': [0x24], 'width': 1, 'signed': False, 'type': 'int', 'transform': 'identity'},
        'flag': {'chain': [0x25], 'width': 1, 'signed': False, 'type': 'bool', 'transform': 'nonzero'},
        'overlap': {'chain': [0x24], 'width': 2, 'signed': False, 'type': 'int', 'transform': 'identity'},
        'real': {'chain': [0x28], 'width': 8, 'signed': False, 'type': 'double', 'transform': 'identity'},
        'date': {'chain': [0, 0], 'width': 4, 'signed': False, 'type': 'date_yd', 'transform': 'identity'},
        'deep': {'chain': [0, 4], 'width': 4, 'signed': False, 'type': 'int', 'transform': 'identity'},
        'deep_real': {'chain': [0, 8], 'width': 4, 'signed': False, 'type': 'float', 'transform': 'identity'},
        'text': {'chain': [8], 'width': 8, 'signed': False, 'type': 'string', 'transform': 'identity'},
        'text_null': {'chain': [8], 'width': 8, 'signed': False, 'type': 'string', 'transform': 'identity',
                      'zero_null': True},
        'ref': {'chain': [0x10], 'width': 8, 'signed': False, 'type': 'record_ptr', 'transform': 'identity'},
        'rating': {'type': 'rating_blob',
                   'source_plan': {'chain': [0x148], 'width': 1, 'signed': False, 'type': 'int', 'transform': 'identity'},
                   'flag_plan': {'chain': [0x170], 'width': 1, 'signed': False, 'type': 'int', 'transform': 'identity'}},
    }
    return memory, records, plans


def normal(value):
    if isinstance(value, Missing):
        return ('missing', value.reason)
    return value


@pytest.mark.parametrize('seed', [1, 2, 3])
def test_window_evaluation_equals_item_evaluation(seed):
    memory, records, plans = random_world(seed)
    stats_old, stats_new = {}, {}
    old = bulkplans.evaluate(memory.read_many, records, plans, stats=stats_old)
    new = bulkplans.evaluate(memory.read_many, records, plans, stats=stats_new, windows=memory.windows)
    for code in plans:
        assert [normal(v) for v in new[code]] == [normal(v) for v in old[code]], code
    assert stats_new == stats_old
    kinds = {code: {type(normal(v)) for v in old[code]} for code in plans}
    assert tuple in kinds['text'] and str in kinds['text'] and Ref in kinds['ref'] and type(None) in kinds['deep']
    assert ('missing', 'implausible string length') in map(normal, old['text'])
    assert ('missing', 'unreadable live memory') in map(normal, old['ref'])
    # a subset (a repair round and the audit evaluate a few records) gives the same cells
    subset = records[10:20]
    part = bulkplans.evaluate(memory.read_many, subset, plans, windows=memory.windows)
    for code in plans:
        assert [normal(v) for v in part[code]] == [normal(v) for v in old[code][10:20]]


# --------------------------------------------------------------------------- shipped plans
def ship(tmp_path, monkeypatch, engine, mutate=None):
    """Derive the plans with the fake engine, write them as package data, empty the cache."""
    snapshot.Build(engine, root=tmp_path, tables_wanted=['nation'], column_budget=20, build_budget=90).run()
    cache = tmp_path / 'plans' / f'{engine.plugin_sha256}.v2.json'
    doc = json.loads(cache.read_text())
    if mutate:
        mutate(doc)
    data = tmp_path / 'data'
    data.mkdir()
    (data / f'plans-{engine.plugin_sha256}.v2.json.gz').write_bytes(gzip.compress(json.dumps(doc).encode()))
    monkeypatch.setattr(snapshot, 'SHIPPED_PLANS', data)
    cache.unlink()
    return cache, doc


def test_shipped_plans_replace_the_derivation_and_are_checked_on_load(tmp_path, monkeypatch):
    use_cache(monkeypatch, tmp_path)
    engine = FakeEngine(tmp_path)
    cache, doc = ship(tmp_path, monkeypatch, engine)
    direct = {c for c, p in doc['plans']['NATION'].items() if p['status'] == 'direct'}
    assert 'Ncod' in direct and 'Nbad' not in direct             # Nbad failed its verification when derived
    traced = []
    monkeypatch.setattr(engine, 'plan_tracer', lambda: traced.append(1) or pytest.fail('derivation ran'))
    builder = snapshot.Build(engine, root=tmp_path, tables_wanted=['nation'], column_budget=20, build_budget=90)
    assert builder.store.shipped == len(doc['plans']['NATION']) and builder.prepare().plans_missing() == 0
    path = builder.run()
    assert builder.plan_stats['shipped_checked'] == len(direct) and builder.plan_stats['shipped_demoted'] == 0
    saved = json.loads(cache.read_text())['plans']['NATION']
    assert all(saved[c]['origin'] == 'shipped' and saved[c]['load_verified'] == snapshot.SHIPPED_VERIFY_RECORDS
               for c in direct)
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT code, name FROM nation WHERE idx = 7').fetchone() == (21, 'Nation 7')
    # the cache now holds the checked plans: a second store takes nothing from the package
    again = snapshot.plan_store(engine, tmp_path)
    assert again.shipped == 0 and not again.unverified_shipped('NATION')


def test_shipped_plan_that_disagrees_with_the_getter_is_demoted_on_load(tmp_path, monkeypatch):
    use_cache(monkeypatch, tmp_path)
    engine = FakeEngine(tmp_path)

    def wrong(doc):                                               # Nsta read from the neighbour's byte
        doc['plans']['NATION']['Nsta'] = {**doc['plans']['NATION']['Nsta'], 'chain': [0x58]}
    cache, doc = ship(tmp_path, monkeypatch, engine, wrong)
    builder = snapshot.Build(engine, root=tmp_path, tables_wanted=['nation'], column_budget=20, build_budget=90)
    path = builder.run()
    assert builder.plan_stats['shipped_demoted'] == 1
    saved = json.loads(cache.read_text())['plans']['NATION']
    assert saved['Nsta']['status'] == 'emulate-only' and 'shipped plan' in saved['Nsta']['reason']
    with sqlite3.connect(path) as conn:                           # the bad plan's values are not stored
        assert [r[0] for r in conn.execute('SELECT state FROM nation WHERE idx IN (4, 5) ORDER BY idx')] == [None, None]
        assert conn.execute("SELECT source, status FROM _column_state WHERE table_name='nation' AND "
                            "column_name='state'").fetchone() == ('emulated', 'on_demand')
    # a statement that names the column gets the getter's values
    result, _ = statement(engine, path, 'SELECT state FROM nation WHERE idx IN (4, 5) ORDER BY idx')
    assert result['rows'] == [[0], [1]]


def test_shipped_plans_of_another_build_or_format_are_ignored(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    sha = 'a' * 64
    plans = {'X': {'Xabc': {'status': 'direct', 'chain': [0], 'width': 4, 'type': 'int'}}}
    for name, doc in (('other', {'format': bulkplans.FORMAT, 'sha256': 'b' * 64, 'plans': plans}),
                      ('old', {'format': 'fmdb-bulk-plans/1', 'sha256': sha, 'plans': plans})):
        (data / f'plans-{sha}.v2.json.gz').write_bytes(gzip.compress(json.dumps(doc).encode()))
        assert snapshot.shipped_plans(sha, data) is None, name
    (data / f'plans-{sha}.v2.json.gz').write_bytes(b'not gzip')
    assert snapshot.shipped_plans(sha, data) is None
    assert snapshot.shipped_plans('c' * 64, data) is None        # no file


def test_package_ships_verified_plans_for_the_pinned_build():
    from fm_live_mcp import players
    plans = snapshot.shipped_plans(players.SHA256)
    assert plans, 'no shipped plans for the pinned plugin build'
    direct = [p for fields in plans.values() for p in fields.values() if p.get('status') == 'direct']
    assert len(direct) >= 1000 and all(p.get('mismatches', 0) == 0 for p in direct)
    assert {'ACTUAL_PLAYER', 'CLUB', 'COMP', 'TEAM'} <= set(plans)


# --------------------------------------------------------------------------- cell and table writers
def test_write_cells_sets_a_chunk_with_one_update_per_row():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE t (idx INTEGER PRIMARY KEY, a, b, c, d)')
    conn.executemany('INSERT INTO t (idx) VALUES (?)', [(i,) for i in range(6)])
    statements = []
    conn.set_trace_callback(statements.append)
    ondemand.write_cells(conn, 't', {'a': [(10, 1), (11, 2), (12, 3)], 'b': [('x', 1), (None, 2), ('z', 3)],
                                     'c': [(5.5, 2), (6.5, 4)], 'd': []})
    conn.set_trace_callback(None)
    assert conn.execute('SELECT idx, a, b, c, d FROM t ORDER BY idx').fetchall() == [
        (0, None, None, None, None), (1, 10, 'x', None, None), (2, 11, None, 5.5, None), (3, 12, 'z', None, None),
        (4, None, None, 6.5, None), (5, None, None, None, None)]
    updates = [s for s in statements if s.startswith('UPDATE')]
    assert len(updates) == 5 and sum('"a"=' in s and '"b"=' in s for s in updates) == 3


def test_reference_column_conversion_equals_cell_by_cell():
    live = SimpleNamespace(pointers=[1] * 50, uids=list(range(1000, 1050)), rids=list(range(1000, 1050)),
                           uid_index=lambda: {1000 + i: i for i in range(50)})
    column = snapshot.Column.__new__(snapshot.Column)
    column.table, column.name, column.kind, column.part, column.references = 't', 'ref', 'ref', None, 'nation'
    rows = list(range(12))
    values = [Ref(1003, 1003), Ref(1003, 1003), 7, 7, True, 1, 1.0, None, Ref(9999, 1), Ref(9999, 1),
              Missing('unreadable live memory'), -1]
    one, two = snapshot.Resolver({'nation': live}), snapshot.Resolver({'nation': live})
    expected = [snapshot.to_sql(column, i, v, one) for i, v in zip(rows, values)]
    assert snapshot._ref_column(column, rows, values, two) == expected
    assert expected[:4] == [3, 3, 7, 7] and expected[4] is None and expected[5] == 1 and expected[6] is None
    assert two.unresolved == one.unresolved and len(one.unresolved) == 4      # bool, float, two unknown references


# --------------------------------------------------------------------------- demotion and staleness
def test_a_demoted_plan_becomes_an_on_demand_column_in_place(tmp_path, monkeypatch):
    """The open differential item: a plan demoted after a build used to leave the snapshot
    serving that plan's values until the game date moved. A demotion then rebuilt the whole
    snapshot (14.9 s in the middle of a session); now the demoted column becomes on demand in
    place: same file, same build time, the stored cells of that class are no longer served."""
    from fm_live_mcp.fmdb import tools
    engine = FakeEngine(tmp_path)
    use_cache(monkeypatch, tmp_path)
    snapshot.Build(engine, root=tmp_path, tables_wanted=['nation'], column_budget=20, build_budget=90).run()
    (tmp_path / 'test-career' / 'snapshot.sqlite').unlink()      # plans derived; the tool path builds from them
    path, meta, refreshed, _, stale = tools.current_snapshot(engine)
    assert refreshed['reason'] == 'no snapshot yet' and not stale
    direct_before = tools.direct_plan_count(engine)
    assert direct_before == meta['plans_verified'] and direct_before >= 3
    # same plans: the snapshot is checked against memory (at most every CHECK_INTERVAL_S), not rebuilt
    again = tools.current_snapshot(engine)
    assert not again[4] and set(again[2]) == {'checked'} and again[1]['built_at'] == meta['built_at']
    assert again[1]['fresh']['checked_ms_ago'] >= 0 and again[1]['fresh']['rows_refreshed'] == 0

    store = snapshot.plan_store(engine, tmp_path)
    assert store.get('NATION', 'Nsta')['status'] == 'direct'
    store.plans['NATION']['Nsta'] = {'status': 'emulate-only', 'reason': 'differential check: 1 of 200 rows disagreed'}
    store.save()
    path, meta, refreshed, _, stale = tools.current_snapshot(engine)
    assert set(refreshed) == {'checked'} and not stale and meta['built_at'] == again[1]['built_at']
    assert meta['plans_verified'] == direct_before - 1 == tools.direct_plan_count(engine)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT source, status FROM _column_state WHERE table_name='nation' AND "
                            "column_name='state'").fetchone() == ('emulated', 'on_demand')
    from fm_live_mcp.fmdb import ondemand
    assert 'NATION' in ondemand.Session(engine, path).states()['nation']['state']    # not the cached states
    assert set(tools.current_snapshot(engine, force_check=True)[2]) == {'checked'}


# --- per-statement overheads found by profiling the merged reader (stored-column statement 4-5 s) ---
def test_columns_for_is_computed_once_per_catalog_and_table(monkeypatch):
    from fm_live_mcp.fmdb import snapshot

    class Catalog:
        record_types = {}
        enums = {}

    calls = []
    real = snapshot._columns_for
    monkeypatch.setattr(snapshot, '_columns_for', lambda catalog, table: calls.append(table) or real(catalog, table))
    catalog = Catalog()
    first = snapshot.columns_for(catalog, 'player')
    second = snapshot.columns_for(catalog, 'player')
    assert calls == ['player']
    assert first == second and first is not second          # callers get their own list
    snapshot.columns_for(Catalog(), 'player')
    assert calls == ['player', 'player']                    # another catalog: computed again


def test_plan_audit_runs_at_most_once_per_interval(monkeypatch):
    from fm_live_mcp.fmdb import audit, tools

    runs = []
    monkeypatch.setattr(audit, 'run', lambda engine, path, budget_cpu: runs.append(budget_cpu) or {'cells': 1})
    monkeypatch.setitem(tools._STATE, 'audited_at', -1e9)
    assert tools.plan_audit(None, None) == {'cells': 1}
    assert tools.plan_audit(None, None) is None             # a burst of statements pays once
    monkeypatch.setitem(tools._STATE, 'audited_at', tools._STATE['audited_at'] - tools.AUDIT_MIN_INTERVAL_S - 1)
    assert tools.plan_audit(None, None) == {'cells': 1}
    assert runs == [tools.AUDIT_CPU_S, tools.AUDIT_CPU_S]


def test_from_bridge_reuses_the_engine_of_an_unchanged_process_without_the_layout_check():
    import threading
    from types import SimpleNamespace
    from fm_live_mcp.fmdb.engine import Engine

    process = SimpleNamespace(pid=7, executable='/x/fm', started='t0')

    class Bridge:
        lock = threading.RLock()

        def _current(self, session_id):
            assert session_id == 's'
            return process

        def _player_layout(self, process):
            raise AssertionError('the layout check must not run again for the same process')

    existing = SimpleNamespace(process_key=(7, '/x/fm', 't0'))
    assert Engine.from_bridge(Bridge(), 's', existing) is existing


def test_plan_audit_skips_the_first_statement_of_a_process(monkeypatch):
    from fm_live_mcp.fmdb import audit, tools

    runs = []
    monkeypatch.setattr(audit, 'run', lambda engine, path, budget_cpu: runs.append(budget_cpu) or {'cells': 1})
    monkeypatch.delitem(tools._STATE, 'audited_at', raising=False)
    assert tools.plan_audit(None, None) is None and runs == []           # the first statement pays nothing
    monkeypatch.setitem(tools._STATE, 'audited_at', tools._STATE['audited_at'] - tools.AUDIT_MIN_INTERVAL_S - 1)
    assert tools.plan_audit(None, None) == {'cells': 1}


def test_layout_signature_changes_with_declared_tables_and_gives_no_verdict_on_a_failing_module(monkeypatch):
    from fm_live_mcp.fmdb import snapshot, sources
    from fm_live_mcp.fmdb.sources import Column, SourceTable

    class Catalog:
        record_types = {}
        enums = {}

    def engine():
        return SimpleNamespace(catalog=Catalog())

    def table(name, columns):
        return SourceTable(name, 'about', [Column(c, 'INTEGER', c) for c in columns], lambda: [])

    monkeypatch.setattr(sources, 'discover_views', lambda engine, only=None, log=None: [])
    monkeypatch.setattr(sources, 'discover', lambda engine, only=None, log=None: ([('m', table('a', ['x']))], []))
    one = snapshot.layout_signature(engine())
    assert one and one == snapshot.layout_signature(engine())
    monkeypatch.setattr(sources, 'discover', lambda engine, only=None, log=None: (
        [('m', table('a', ['x'])), ('n', table('b', ['y']))], []))
    assert snapshot.layout_signature(engine()) not in ('', one)          # a new table: another signature
    monkeypatch.setattr(sources, 'discover', lambda engine, only=None, log=None: (
        [('m', table('a', ['x']))], [('n', 'ImportError: boom')]))
    assert snapshot.layout_signature(engine()) == ''                     # a failing module: no verdict


def test_an_editor_field_routed_to_a_derived_code_is_not_traced_for_plans():
    """scripts/fmdb_snapshot.py failed with 'FourCC must be four bytes' when the plan deriver was
    handed nati cwsd, which fieldroutes aliases to the derived code x:transfer_window_cwsd."""
    from fm_live_mcp.fmdb import snapshot

    def column(code, origin):
        return snapshot.Column('nation', 'c', code, 'nati', None, 'TEXT', 'date', origin=origin)

    assert snapshot.traced(column('Nnam', 'catalog'))
    assert not snapshot.traced(column('x:transfer_window_cwsd', 'catalog'))
    assert not snapshot.traced(column('x:anything', 'derived'))


def test_a_mapped_build_without_plans_starts_from_another_builds_plans_and_checks_them(tmp_path, monkeypatch):
    """After a game update the plans of the previous build are candidates: verified against the new
    build's getter on load, and derived again only where the getter contradicts them."""
    from fm_live_mcp import address_book

    use_cache(monkeypatch, tmp_path)
    old = FakeEngine(tmp_path)
    cache, doc = ship(tmp_path, monkeypatch, old)               # package data now holds the old build's plans
    direct = {c for c, p in doc['plans']['NATION'].items() if p['status'] == 'direct'}
    new = FakeEngine(tmp_path)
    new.plugin_sha256 = 'e' * 64                                 # another build of the game
    assert snapshot.plan_store(new, tmp_path).shipped == 0       # not a mapped build: nothing is carried
    monkeypatch.setitem(address_book.ACTIVE, 'state', 'mapped')
    monkeypatch.setitem(address_book.ACTIVE, 'sha256', new.plugin_sha256)
    store = snapshot.plan_store(new, tmp_path)
    assert store.carried_from == old.plugin_sha256 and store.shipped == len(doc['plans']['NATION'])
    assert set(store.unverified_shipped('NATION')) == direct
    assert all(store.plans['NATION'][c]['origin'] == 'carried' for c in direct)
    assert store.missing('NATION', sorted(doc['plans']['NATION'])) == []
    # a carried plan the getter contradicted is derived again for this build
    code = sorted(direct)[0]
    store.plans['NATION'][code] = {'status': 'emulate-only', 'origin': 'carried',
                                   'reason': 'carried plan: 6 of 6 records disagreed on load (example)'}
    assert store.missing('NATION', sorted(doc['plans']['NATION'])) == [code]
