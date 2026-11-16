"""Hold-out check of direct plans: plain reads (plans.apply) vs the PropertyVM on fresh records.

Usage: PYTHONPATH=. python scripts/fmdb_plan_check.py out/fmdb-coverage/plans.json [--per-class 10]

Records are taken from the middle of each class's population with a different stride
from the coverage sample. A plan agrees when apply() returns the VM's value (floats
bit-exact; record_ptr by unique/random id; a null pointer counts as agreeing with an
unset VM value only when the plan says null_pointer_is_unset).
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import struct
import sys

from fm_live_mcp.fmdb import plans, tables, variant
from fm_live_mcp.fmdb.image import PluginImage
from fm_live_mcp.fmdb.live import open_live
from fm_live_mcp.fmdb.vm import PropertyVM, Unavailable


def agrees(plan, direct, result):
    value = result.value
    if isinstance(value, Unavailable):
        return None
    if result.kind == 'null' or value is None:
        return plan.get('null_pointer_is_unset') and direct in (None, '')
    if plan['type'] == 'record_ptr':
        return (isinstance(value, variant.RecordRef) and direct is not None
                and (direct['unique_id'], direct['random_id']) == (value.unique_id, value.random_id))
    if plan['type'] == 'float' and isinstance(value, float) and isinstance(direct, float):
        return struct.pack('<f', value) == struct.pack('<f', direct)
    return direct == value


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('plans')
    ap.add_argument('--per-class', type=int, default=10)
    ap.add_argument('--json')
    args = ap.parse_args(argv)
    data = json.loads(Path(args.plans).read_text())['plans']
    session = open_live()
    try:
        read, base = session.reader.read, session.base
        vm = PropertyVM(session.reader, base, PluginImage.load(session.plugin_path))
        by_class = defaultdict(list)
        for kind in sorted({spec.table for spec in tables.RECORD_TYPES.values()}):
            pointers = tables.entries(read, base, kind)
            for p in pointers:
                if p:
                    by_class[tables.class_of(read, base, p)[0]].append(p)
        totals, report = Counter(), {}
        for cls, fields in data.items():
            population = by_class.get(cls, [])
            if not population:
                continue
            step = max(1, len(population) // (args.per_class * 3))
            records = population[step // 2::step][:args.per_class]
            for code, plan in fields.items():
                if plan['status'] != 'direct':
                    continue
                counts = Counter()
                for record in records:
                    try:
                        direct = plans.apply(read, record, plan)
                    except Exception:  # noqa: BLE001 - an unreadable chain is a disagreement
                        direct = 'unreadable'
                    verdict = agrees(plan, direct, vm.get_property(record, code))
                    counts['vm_unavailable' if verdict is None else 'agree' if verdict else 'disagree'] += 1
                report.setdefault(cls, {})[code] = dict(counts)
                totals.update(counts)
                totals['plans'] += 1
                if counts['disagree']:
                    totals['plans_with_disagreement'] += 1
        print(json.dumps(dict(totals)))
        if args.json:
            Path(args.json).write_text(json.dumps({'totals': totals, 'per_class': report}, indent=1))
        return 0
    finally:
        session.close()


if __name__ == '__main__':
    sys.exit(main())
