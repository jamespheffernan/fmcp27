"""Differential check of the bulk direct reader on the running FM27.

For every snapshot table and record class, the direct plans are evaluated twice over every
row: with the fixed-stride window route (`bulkplans.evaluate(..., windows=...)`) and with the
per-item route the released reader used. The per-item route is served from the same cached
pages, so a difference is a decoding difference; a cell that differs is read again on both
routes before it is reported (the game is not paused).

Usage: PYTHONPATH=. python scripts/fmdb_direct_check.py [--tables player,person] [--rows 0]
Exit status 1 when any cell differs after the re-read.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict

from fm_live_mcp.fmdb import bulkplans, snapshot
from fm_live_mcp.fmdb.bulkplans import Missing
from fm_live_mcp.fmdb.engine import Engine
from fm_live_mcp.fmdb.memory import MemoryReadError


def norm(value):
    if isinstance(value, Missing):
        return ('missing', value.reason)
    if isinstance(value, float) and value != value:
        return ('nan',)
    return value


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--tables')
    ap.add_argument('--rows', type=int, default=0, help='rows per class (0: all)')
    args = ap.parse_args(argv)
    engine = Engine.open()
    try:
        build = snapshot.Build(engine, tables_wanted=args.tables.split(',') if args.tables else None)
        build.prepare()

        def cached_many(requests):
            out = []
            for address, length in requests:
                try:
                    out.append(engine.cached_read(address, length))
                except MemoryReadError:
                    out.append(None)
            return out

        totals = defaultdict(int)
        seconds = defaultdict(float)
        report = []
        for t in build.wanted:
            live = build.live_by_sql[t]
            by_class = defaultdict(list)
            for i in build.rows[t]:
                by_class[live.classes[i]].append(i)
            for cls, idxs in sorted(by_class.items()):
                if len(idxs) <= snapshot.SMALL_CLASS:
                    continue
                plans = {}
                for col in build.columns[t]:
                    plan = build.store.get(cls, col.code) if snapshot.traced(col) else None
                    if plan and plan.get('status') == 'direct':
                        plans[col.name] = plan
                if not plans:
                    continue
                if args.rows:
                    idxs = idxs[:args.rows]
                pointers = [live.pointers[i] for i in idxs]
                t0 = time.perf_counter()
                new = bulkplans.evaluate(engine.read_many, pointers, plans, windows=engine.windows)
                t1 = time.perf_counter()
                old = bulkplans.evaluate(cached_many, pointers, plans)
                t2 = time.perf_counter()
                seconds['windows'] += t1 - t0
                seconds['per_item_cached'] += t2 - t1
                for name in plans:
                    a, b = new[name], old[name]
                    totals['cells'] += len(a)
                    if a == b:
                        continue
                    for k, (x, y) in enumerate(zip(a, b)):
                        if x is y or norm(x) == norm(y):
                            continue
                        one = {name: plans[name]}
                        again_new = bulkplans.evaluate(engine.read_many, [pointers[k]], one, windows=engine.windows)
                        again_old = bulkplans.evaluate(engine.read_many, [pointers[k]], one)
                        if norm(again_new[name][0]) == norm(again_old[name][0]):
                            totals['changed_during_check'] += 1
                            continue
                        totals['different'] += 1
                        if len(report) < 30:
                            report.append({'table': t, 'class': cls, 'idx': idxs[k], 'column': name,
                                           'windows': repr(x), 'per_item': repr(y)})
            print(f'{t}: {totals["cells"]} cells so far, {totals["different"]} different', flush=True)
        print(json.dumps({'cells': totals['cells'], 'different': totals['different'],
                          'changed_during_check': totals['changed_during_check'],
                          'seconds': {k: round(v, 2) for k, v in seconds.items()}}, indent=1))
        for row in report:
            print(json.dumps(row))
        return 1 if totals['different'] else 0
    finally:
        engine.close()


if __name__ == '__main__':
    sys.exit(main())
