"""Build or refresh the fmdb SQLite snapshot of the running FM27 save.

Usage: PYTHONPATH=. python scripts/fmdb_snapshot.py [--tables player,person] [--column-budget 20]
           [--no-derive]

Writes $FMCP_CACHE_DIR/fmdb/<save key>/snapshot.sqlite (default cache on the external disk)
and prints per-phase timings and per-table column states. Unlike a build started by a tool
call, this one derives the direct plans that are missing for the game build (tens of minutes
on a new build) and runs the static plan compilation; the tools then rebuild with them.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time

from fm_live_mcp.fmdb import snapshot
from fm_live_mcp.fmdb.engine import Engine


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--tables')
    ap.add_argument('--no-derive', action='store_true', help='build with the plans there are')
    ap.add_argument('--column-budget', type=float, default=snapshot.COLUMN_BUDGET_S)
    args = ap.parse_args(argv)
    engine = Engine.open()
    try:
        started = time.time()
        path = snapshot.build(engine, tables_wanted=args.tables.split(',') if args.tables else None,
                              log=lambda m: print(m, flush=True), column_budget=args.column_budget,
                              derive_plans=not args.no_derive)
        print(f'built {path} in {time.time() - started:.1f}s')
        with sqlite3.connect(path) as conn:
            print(json.dumps(json.loads(conn.execute("SELECT value FROM _build WHERE key='timing'").fetchone()[0])))
            for table, rows in conn.execute('SELECT table_name, rows FROM _tables ORDER BY table_name'):
                counts = dict(conn.execute(
                    "SELECT source || '/' || status, COUNT(*) FROM _fields WHERE table_name=? AND code IS NOT NULL "
                    "GROUP BY 1", (table,)).fetchall())
                print(f'{table}: {rows} rows {counts}')
    finally:
        engine.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
