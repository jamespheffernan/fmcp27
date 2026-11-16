"""Cell-by-cell comparison of two fmdb snapshots (golden check for reader changes).

Usage: python scripts/fmdb_golden_diff.py OLD/snapshot.sqlite NEW/snapshot.sqlite [--samples 5]

Build OLD with the released reader and NEW with the changed reader at the same game state,
then run this. For every data table and every column, rows are joined on `idx` and counted as

* equal (`IS`, so NULL equals NULL),
* filled: OLD is NULL and NEW has a value. Allowed only where OLD's column was not ready
  (`_column_state.status` pending for some class, or `_fill` owned it); elsewhere it is reported,
* lost: OLD has a value and NEW is NULL (always reported),
* changed: both have a value and they differ (always reported).

NEW may be a snapshot with on-demand columns (`_column_state.status = 'on_demand'`): such a
column holds a value only where a query (or `ondemand.compute`) computed it. Its cells are
compared for the rows NEW has memoised (`_memo.valid`) and counted as `on_demand_not_computed`
elsewhere, so the check covers exactly the cells that were computed.

Rows present in only one snapshot and columns present in only one are reported. The game is
not paused between two builds, so a small number of changed cells in live fields (condition,
morale, ...) is expected; the report lists the columns and sample rows so they can be judged.
Exit status 1 when anything is reported.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys

BATCH = 60


def q(name):
    return '"' + name.replace('"', '""') + '"'


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('old')
    ap.add_argument('new')
    ap.add_argument('--samples', type=int, default=5)
    args = ap.parse_args(argv)
    conn = sqlite3.connect(f'file:{args.old}?mode=ro', uri=True)
    conn.execute('ATTACH DATABASE ? AS new', (f'file:{args.new}?mode=ro',))
    tables_old = [r[0] for r in conn.execute('SELECT table_name FROM main._tables ORDER BY 1')]
    tables_new = [r[0] for r in conn.execute('SELECT table_name FROM new._tables ORDER BY 1')]
    not_ready = {(t, c) for t, c in conn.execute(
        "SELECT DISTINCT table_name, column_name FROM main._column_state WHERE status != 'ready'")}
    try:
        not_ready |= {(t, c) for t, c in conn.execute('SELECT table_name, column_name FROM main._fill')}
    except sqlite3.Error:
        pass                                    # OLD has no background fill either
    on_demand, memo = set(), {}
    try:
        on_demand = {(t, c) for t, c in conn.execute(
            "SELECT DISTINCT table_name, column_name FROM new._column_state WHERE status = 'on_demand'")}
        memo = {(t, c): v for t, c, v in conn.execute('SELECT table_name, column_name, valid FROM new._memo '
                                                      'WHERE cells > 0')}
    except sqlite3.Error:
        pass
    conn.execute('CREATE TEMP TABLE _valid(idx INTEGER PRIMARY KEY)')
    totals = {'tables': 0, 'columns': 0, 'cells': 0, 'equal': 0, 'filled_allowed': 0, 'filled_unexpected': 0,
              'lost': 0, 'changed': 0, 'on_demand_columns_compared': 0, 'on_demand_cells_compared': 0,
              'on_demand_not_computed': 0}
    problems = []
    for t in sorted(set(tables_old) | set(tables_new)):
        if t not in tables_old or t not in tables_new:
            problems.append({'table': t, 'problem': 'table in one snapshot only'})
            continue
        totals['tables'] += 1
        cols_old = [r[1] for r in conn.execute(f'PRAGMA main.table_info({q(t)})')]
        cols_new = [r[1] for r in conn.execute(f'PRAGMA new.table_info({q(t)})')]
        for c in sorted(set(cols_old) ^ set(cols_new)):
            problems.append({'table': t, 'column': c, 'problem': 'column in one snapshot only'})
        only_old = conn.execute(f'SELECT COUNT(*) FROM main.{q(t)} WHERE idx NOT IN (SELECT idx FROM new.{q(t)})').fetchone()[0]
        only_new = conn.execute(f'SELECT COUNT(*) FROM new.{q(t)} WHERE idx NOT IN (SELECT idx FROM main.{q(t)})').fetchone()[0]
        if only_old or only_new:
            problems.append({'table': t, 'problem': 'row sets differ', 'only_old': only_old, 'only_new': only_new})
        rows = conn.execute(f'SELECT COUNT(*) FROM main.{q(t)} x JOIN new.{q(t)} y ON y.idx = x.idx').fetchone()[0]
        common = [c for c in cols_old if c in set(cols_new) and c != 'idx']
        totals['columns'] += len(common)
        totals['cells'] += rows * len(common)
        # on-demand columns of NEW: the memoised rows only, one column at a time
        lazy = [c for c in common if (t, c) in on_demand]
        common = [c for c in common if (t, c) not in on_demand]
        for c in lazy:
            valid = memo.get((t, c))
            if not valid:
                totals['on_demand_not_computed'] += rows
                continue
            conn.execute('DELETE FROM _valid')
            conn.executemany('INSERT INTO _valid VALUES (?)',
                             [(i,) for i in range(len(valid) * 8) if valid[i >> 3] >> (i & 7) & 1])
            n, filled, lost, changed = conn.execute(
                f'SELECT COUNT(*), SUM(x.{q(c)} IS NULL AND y.{q(c)} IS NOT NULL), '
                f'SUM(x.{q(c)} IS NOT NULL AND y.{q(c)} IS NULL), '
                f'SUM(x.{q(c)} IS NOT NULL AND y.{q(c)} IS NOT NULL AND x.{q(c)} IS NOT y.{q(c)}) '
                f'FROM main.{q(t)} x JOIN new.{q(t)} y ON y.idx = x.idx JOIN _valid v ON v.idx = x.idx').fetchone()
            filled, lost, changed = filled or 0, lost or 0, changed or 0
            # rows where the direct classes of a mixed column are stored are compared as well
            totals['on_demand_columns_compared'] += 1
            totals['on_demand_cells_compared'] += n
            totals['on_demand_not_computed'] += rows - n
            totals['equal'] += n - filled - lost - changed
            allowed = (t, c) in not_ready
            totals['filled_allowed' if allowed else 'filled_unexpected'] += filled
            totals['lost'] += lost
            totals['changed'] += changed
            if lost or changed or (filled and not allowed):
                sample = conn.execute(
                    f'SELECT x.idx, x.{q(c)}, y.{q(c)} FROM main.{q(t)} x JOIN new.{q(t)} y ON y.idx = x.idx '
                    f'JOIN _valid v ON v.idx = x.idx WHERE x.{q(c)} IS NOT NULL AND x.{q(c)} IS NOT y.{q(c)} LIMIT ?',
                    (args.samples,)).fetchall()
                problems.append({'table': t, 'column': c, 'on_demand': True, 'filled_unexpected': 0 if allowed else filled,
                                 'lost': lost, 'changed': changed,
                                 'samples': [[i, repr(a)[:60], repr(b)[:60]] for i, a, b in sample]})
        for start in range(0, len(common), BATCH):
            part = common[start:start + BATCH]
            sums = ', '.join(
                f'SUM(x.{q(c)} IS NULL AND y.{q(c)} IS NOT NULL), SUM(x.{q(c)} IS NOT NULL AND y.{q(c)} IS NULL), '
                f'SUM(x.{q(c)} IS NOT NULL AND y.{q(c)} IS NOT NULL AND x.{q(c)} IS NOT y.{q(c)})' for c in part)
            got = conn.execute(f'SELECT {sums} FROM main.{q(t)} x JOIN new.{q(t)} y ON y.idx = x.idx').fetchone()
            for k, c in enumerate(part):
                filled, lost, changed = (got[3 * k] or 0), (got[3 * k + 1] or 0), (got[3 * k + 2] or 0)
                totals['equal'] += rows - filled - lost - changed
                allowed = (t, c) in not_ready
                totals['filled_allowed' if allowed else 'filled_unexpected'] += filled
                totals['lost'] += lost
                totals['changed'] += changed
                if lost or changed or (filled and not allowed):
                    where = (f'(x.{q(c)} IS NOT y.{q(c)})' if not allowed else
                             f'(x.{q(c)} IS NOT NULL AND x.{q(c)} IS NOT y.{q(c)})')
                    sample = conn.execute(
                        f'SELECT x.idx, x.{q(c)}, y.{q(c)} FROM main.{q(t)} x JOIN new.{q(t)} y ON y.idx = x.idx '
                        f'WHERE {where} LIMIT ?', (args.samples,)).fetchall()
                    problems.append({'table': t, 'column': c, 'filled_unexpected': 0 if allowed else filled,
                                     'lost': lost, 'changed': changed,
                                     'samples': [[i, repr(a)[:60], repr(b)[:60]] for i, a, b in sample]})
    states = {}
    for name in ('main', 'new'):
        states[name] = dict(conn.execute(f"SELECT status, COUNT(*) FROM {name}._fields GROUP BY 1").fetchall())
    regress = conn.execute(
        "SELECT COUNT(*) FROM main._fields o JOIN new._fields n ON n.table_name = o.table_name AND "
        "n.column_name = o.column_name WHERE o.status = 'ready' AND n.status != 'ready'").fetchone()[0]
    print(json.dumps({'totals': totals, 'field_status_old': states['main'], 'field_status_new': states['new'],
                      'columns_ready_in_old_not_ready_in_new': regress, 'reported': len(problems)}, indent=1))
    for p in problems[:80]:
        print(json.dumps(p))
    return 1 if problems or regress else 0


if __name__ == '__main__':
    sys.exit(main())
