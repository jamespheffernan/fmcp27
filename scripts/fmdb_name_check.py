"""Name columns on the UI accelerator against FastVM, on every record (ondemand.NAME_VM_CODES).

For each (record type, code) of `ondemand.NAME_VM_CODES`, every record of the live table is read
through the engine's FastVM (the path the snapshot used before) and through `ondemand.name_vm`
(FastUiHandlerVM in the database view), and the canonical values are compared. Prints counts,
differences and the time per call of both.

  PYTHONPATH=. python scripts/fmdb_name_check.py [--codes team.Tlna,comp.dbnm] [--limit N] [--out file.json]

Read-only against the game.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--codes')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--out')
    args = ap.parse_args(argv)
    from fm_live_mcp.fmdb import bulkplans, ondemand, tables
    from fm_live_mcp.fmdb.engine import Engine
    engine = Engine.open()
    ref = engine.vm
    fast = ondemand.name_vm(engine)
    if fast is None:
        raise SystemExit('the UI accelerator is not available (scripts/build_ui_accel.sh)')
    codes = sorted(ondemand.NAME_VM_CODES)
    if args.codes:
        codes = [tuple(c.split('.')) for c in args.codes.split(',')]
    report = []
    for record_type, code in codes:
        kind = tables.RECORD_TYPES[record_type].table
        pointers = tables.entries(engine.read, engine.base, kind)
        if args.limit:
            pointers = pointers[:args.limit]
        values, seconds = {}, {}
        for name, vm in (('fastvm', ref), ('name_vm', fast)):
            if name == 'name_vm':
                fast.begin_read()
            started = time.process_time()
            out = []
            for p in pointers:
                if not p:
                    out.append(None)
                    continue
                out.append(repr(bulkplans.canonical(vm.get_property(p, code))))
            seconds[name] = round(time.process_time() - started, 2)
            values[name] = out
        diff = [(i, a, b) for i, (a, b) in enumerate(zip(values['fastvm'], values['name_vm'])) if a != b]
        row = {'column': f'{record_type}.{code}', 'records': len(pointers), 'different': len(diff),
               'examples': diff[:10], 'cpu_s': seconds,
               'ms_per_call': {k: round(1000 * v / max(1, len(pointers)), 3) for k, v in seconds.items()},
               'load': round(os.getloadavg()[0], 1)}
        report.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False))
    return 1 if any(r['different'] for r in report) else 0


if __name__ == '__main__':
    sys.exit(main())
