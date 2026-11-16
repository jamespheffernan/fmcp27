"""Plan audit: a budgeted, random re-check of stored values against the game's getter.

A direct plan was traced on a few records and verified on about fifty; a rare path can still
be wrong (a 200-row check once found 8 wrong cells in 5 plans). `run` spends at most
`budget_cpu` CPU-seconds, in the calling process, after a tool call:

* Direct cells. A random table and record class (weighted by their direct cells), a few random
  rows, every direct plan of the class: the plan is evaluated and the getter is run on the
  same cached bytes, so a difference is a wrong plan and not the game moving. A plan that
  disagrees is demoted in the plan cache (`status: emulate-only`, reason `audit: ...`); the
  next tool call then rebuilds the snapshot without it (`tools.current_snapshot`).
* Memoised cells. A few stored on-demand cells whose block passes its read-set check are
  computed again. A difference means the recorded read set missed something the value depends
  on: the block is dropped and the column is marked `nomemo` (computed for every statement,
  never kept).

Coverage accumulates in `_fresh['audit']` (cells checked, share of the snapshot's direct
cells, disagreements, demoted plans) and one line of `_snapshot.notes`.

The robust lane records, per plan, the branch paths the getter took on the records the plan was
derived on (`plan['paths']`: {path hash: records}, `plancompile.path_hash`). A plan whose
getter showed one path is sampled at a tenth of the rate; a plan with several paths, or with
no path record (plans derived before the hash existed), is sampled every time, because a
record on a path the derivation did not see is where a plan goes wrong.
"""
from __future__ import annotations

import json
import random
import sqlite3
import time

from . import bulkplans, freshness, tables
from .bulkplans import Missing

ROWS_PER_SAMPLE = 6
MEMO_SHARE = 0.2            # of the budget, when anything is memoised
MEMO_CELLS = 12
AUDIT_NOTE = 'Plan audit: '


def _store(engine):
    """The plan store of this game build, re-read when the cache file changes."""
    from . import snapshot
    from .engine import cache_root
    path = cache_root() / 'plans' / f'{engine.plugin_sha256}.{snapshot.PLAN_FILE_TAG}.json'
    try:
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        key = (str(path), None, None)
    cached = getattr(engine, '_audit_store', None)
    if cached is None or cached[0] != key:
        cached = engine._audit_store = (key, snapshot.plan_store(engine))
    return cached[1]


def _single_path(plan) -> bool:
    paths = plan.get('paths')
    return isinstance(paths, dict) and len(paths) == 1


def run(engine, path, *, budget_cpu=0.5, rng=None) -> dict | None:
    """Audit within `budget_cpu` CPU-seconds; returns the cumulative coverage (None when the
    snapshot has nothing to audit)."""
    from . import ondemand, snapshot
    started = time.process_time()
    rng = rng or random.Random()
    with engine.lock:
        conn = sqlite3.connect(path, timeout=30)
        try:
            groups = conn.execute(
                "SELECT table_name, class, COUNT(*), MAX(rows) FROM _column_state WHERE source='direct' "
                "AND status='ready' GROUP BY table_name, class").fetchall()
            if not groups:
                return None
            state = json.loads(freshness.get_fresh(conn, 'audit') or '{}')
            state.setdefault('cells', 0)
            state.setdefault('disagreed', 0)
            state.setdefault('demoted', [])
            state.setdefault('memo_cells', 0)
            state.setdefault('memo_disagreed', [])
            state['direct_cells'] = sum(n * rows for _, _, n, rows in groups)
            live_all = freshness.load_live(conn) if getattr(engine, '_fmdb_live', None) is None \
                else engine._fmdb_live[1]
            store = _store(engine)
            recorder = freshness.Recorder(engine)
            weights = [n * rows for _, _, n, rows in groups]
            columns_cache, rows_cache = {}, {}
            checked = disagreed = 0
            demoted = []
            memo_budget = budget_cpu * MEMO_SHARE
            while time.process_time() - started < budget_cpu - memo_budget:
                table, cls, _, _ = rng.choices(groups, weights)[0]
                live = live_all[tables.RECORD_TYPES[snapshot.TABLES[table]].table]
                if (table, cls) not in rows_cache:
                    rows_cache[(table, cls)] = [i for i, (p, c) in enumerate(zip(live.pointers, live.classes))
                                                if p and c == cls]
                    cols = columns_cache.setdefault(table, {c.name: c for c in snapshot.columns_for(engine.catalog,
                                                                                                    table)})
                    plans = {}
                    for (name,) in conn.execute(
                            "SELECT column_name FROM _column_state WHERE table_name=? AND class=? AND "
                            "source='direct' AND status='ready'", (table, cls)):
                        col = cols.get(name)
                        plan = store.get(cls, col.code) if col is not None else None
                        if plan and plan.get('status') == 'direct':
                            plans[name] = (col, plan)
                    rows_cache[(table, cls, 'plans')] = plans
                idxs, plans = rows_cache[(table, cls)], rows_cache[(table, cls, 'plans')]
                if not idxs or not plans:
                    continue
                sample = rng.sample(idxs, min(ROWS_PER_SAMPLE, len(idxs)))
                chosen = {n: cp for n, cp in plans.items() if not _single_path(cp[1]) or rng.random() < 0.1}
                if not chosen:
                    continue
                pointers = [live.pointers[i] for i in sample]
                got = bulkplans.evaluate(recorder.read_many, pointers, {n: p for n, (c, p) in chosen.items()},
                                         windows=recorder.windows, touch=recorder.touch_for(table, sample))
                for name, (col, plan) in chosen.items():
                    if plan.get('status') != 'direct':
                        continue                    # demoted earlier in this run (a code shared by columns)
                    for pointer, value in zip(pointers, got[name]):
                        expected = bulkplans.canonical(engine.get_property(pointer, col.code))
                        if isinstance(expected, Missing) and plan.get('fallback') and expected.reason.endswith('_fseeko'):
                            continue
                        checked += 1
                        if not bulkplans.same(value, expected):
                            disagreed += 1
                            reason = (f'audit: plan {value!r} vs getter {expected!r} on record {pointer:#x} '
                                      f'({table}.{name})')
                            store.plans[cls][col.code] = {'status': 'emulate-only', 'records': plan.get('records'),
                                                          'ms': plan.get('ms'), 'origin': 'audit', 'reason': reason}
                            plan['status'] = 'demoted'
                            demoted.append({'class': cls, 'code': col.code, 'column': f'{table}.{name}',
                                            'reason': reason[:200]})
                            break
            if demoted:
                store.save()
            state['cells'] += checked
            state['disagreed'] += disagreed
            state['demoted'] += demoted
        finally:
            conn.close()
        # the memo share is kept even when the last direct sample overran its part of the budget
        memo = _memo(engine, path, rng, max(memo_budget, budget_cpu - (time.process_time() - started)))
        state['memo_cells'] += memo['cells']
        state['memo_disagreed'] += memo['disagreed']
        state['coverage'] = round(state['cells'] / state['direct_cells'], 6) if state['direct_cells'] else 0.0
        state['runs'] = state.get('runs', 0) + 1
        state['last_at'] = freshness.now_iso()
        state['cpu_seconds'] = round(state.get('cpu_seconds', 0.0) + time.process_time() - started, 3)
        line = (f'{AUDIT_NOTE}{state["cells"]} direct cells ({state["coverage"]:.2%} of {state["direct_cells"]}) '
                f'compared with the getter, {state["disagreed"]} disagreed, {len(state["demoted"])} plans demoted; '
                f'{state["memo_cells"]} memoised cells recomputed, {len(state["memo_disagreed"])} disagreed.')
        conn = sqlite3.connect(path, timeout=30)
        try:
            freshness.set_fresh(conn, audit=json.dumps(state))
            row = conn.execute('SELECT notes FROM _snapshot').fetchone()
            notes = [n for n in json.loads((row[0] if row else None) or '[]') if not n.startswith(AUDIT_NOTE)]
            conn.execute('UPDATE _snapshot SET notes=?', (json.dumps(notes + [line]),))
            conn.commit()
        finally:
            conn.close()
    out = {'cells': state['cells'], 'coverage': state['coverage'], 'disagreed': state['disagreed'],
           'checked_now': checked + memo['cells']}
    if demoted:
        out['demoted_now'] = demoted
    if state['memo_disagreed']:
        out['memo_disagreed'] = state['memo_disagreed'][-5:]
    return out


def _memo(engine, path, rng, budget_cpu) -> dict:
    """Recompute a few memoised cells whose block passes its read-set check."""
    from . import ondemand
    out = {'cells': 0, 'disagreed': []}
    if budget_cpu <= 0:
        return out
    started = time.process_time()
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=30)
    try:
        try:
            columns = conn.execute('SELECT table_name, column_name FROM _memo WHERE cells > 0').fetchall()
        except sqlite3.Error:
            return out
        if not columns:
            return out
        table, column = rng.choice(columns)
        session = ondemand.Session(engine, path)
        bad_blocks = set()
        try:
            t = session.table(table)
            c = t.columns.get(column)
            if c is None or not session.tracking:
                return out
            valid = [i for i in range(len(c.valid) * 8) if c.valid[i >> 3] >> (i & 7) & 1]
            for i in rng.sample(valid, min(MEMO_CELLS, len(valid))):
                if time.process_time() - started > budget_cpu:
                    break
                block = i >> freshness.BLOCK_SHIFT
                if block not in t.verified:
                    session.verify(t, block)
                if not c.valid[i >> 3] >> (i & 7) & 1 or block in bad_blocks:
                    continue                    # the block moved: dropped by the check, as a query would
                stored = conn.execute(f'SELECT {ondemand._q(column)} FROM {ondemand._q(table)} WHERE idx=?',
                                      (i,)).fetchone()
                value = session.compute(c, block, (i,))[0]
                out['cells'] += 1
                if stored is None or not freshness._same(stored[0], value):
                    out['disagreed'].append({'column': f'{table}.{column}', 'idx': i,
                                             'stored': repr(stored[0] if stored else None)[:60],
                                             'getter': repr(value)[:60]})
                    bad_blocks.add(block)
                    session.drop_block(t, block)
                else:
                    del c.fresh[i]              # equal: nothing to write for this cell
            c.computed = 0
        finally:
            session.finish()
    finally:
        conn.close()
    if out['disagreed']:
        conn = sqlite3.connect(path, timeout=30)
        try:
            freshness.set_fresh(conn, **{f'nomemo:{table}.{column}': 1})
            conn.commit()
        finally:
            conn.close()
    return out


def main(argv=None):
    """`python -m fm_live_mcp.fmdb.audit [--cpu SECONDS]`: audit the live save's snapshot now, in
    this process, for the given CPU budget (the tools spend 0.5 CPU-seconds per query)."""
    import argparse
    from . import snapshot
    from .engine import Engine
    ap = argparse.ArgumentParser(description=main.__doc__)
    ap.add_argument('--cpu', type=float, default=10.0)
    args = ap.parse_args(argv)
    engine = Engine.open()
    try:
        path = snapshot.snapshot_path(engine)
        freshness.refresh(engine, path, force=True)       # one memory generation for plans and getter
        print(json.dumps(run(engine, path, budget_cpu=args.cpu), indent=1))
    finally:
        engine.close()
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
