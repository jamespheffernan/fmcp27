"""Compile direct plans from the getters' code for the fields emulated today (plancompile.py).

    PYTHONPATH=. python scripts/fmdb_plancompile.py [--classes CLUB,COMP] [--write] [--json FILE]

For every record class: the fields whose plan is emulate-only (for a reason a direct plan can
address) are compiled on a synthetic record, then each compiled plan is compared with the
getter on 50 separate real records. Prints per class and per snapshot table: fields emulated
today, compiled, verified, demoted. `--write` stores the verified plans in the plan cache
($FMCP_CACHE_DIR/fmdb/plans/<sha>.v2.json, origin 'compiled'); without it nothing is written.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import random
import sys
import time

from fm_live_mcp.fmdb import plancompile, platform_model, snapshot, tables
from fm_live_mcp.fmdb.engine import Engine


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--classes')
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--json')
    args = ap.parse_args(argv)
    engine = Engine.open()
    started = time.time()
    try:
        store = snapshot.plan_store(engine)
        binary = platform_model.load_binary(engine.plugin_path)
        live = {kind: snapshot.enumerate_table(engine, kind)
                for kind in sorted({spec.table for spec in tables.RECORD_TYPES.values()})}
        members = defaultdict(list)
        for kind, table in live.items():
            for p, cls in zip(table.pointers, table.classes):
                if p:
                    members[cls].append(p)
        todo = plancompile.emulated_codes(store.plans)
        if args.classes:
            todo = {c: v for c, v in todo.items() if c in args.classes.split(',')}
        report = {}
        for cls, codes in sorted(todo.items()):
            pool = members.get(cls, [])
            if len(pool) < 10:
                report[cls] = {'emulated': len(codes), 'skipped': f'only {len(pool)} live records'}
                continue
            t = time.time()
            compiled = plancompile.compile_class(engine, cls, codes, binary=binary)
            rng = random.Random(f'{store.sha256}:{cls}:compiled')
            check = rng.sample(pool, min(plancompile.VERIFY_RECORDS, len(pool)))
            compiler = plancompile.Compiler(engine, cls, binary=binary)
            verdicts = plancompile.verify(engine, check, {c: r.plan for c, r in compiled.items() if r.plan},
                                          compiler=compiler)
            reasons = Counter(r.reason.split(' (')[0][:70] for r in compiled.values() if not r.plan)
            v = Counter(x[0] for x in verdicts.values())
            row = {'emulated': len(codes), 'compiled': sum(1 for r in compiled.values() if r.plan),
                   'verified': v.get('verified', 0), 'demoted': v.get('demoted', 0),
                   'too_few': v.get('too few records', 0), 'uncovered': v.get('uncovered path', 0),
                   'paths_per_plan': sorted(len(r.paths) for r in compiled.values() if r.plan),
                   'uncovered_examples': [f'{c}: {x[3]}' for c, x in verdicts.items() if x[0] == 'uncovered path'][:5],
                   'verified_constant': sum(1 for x in verdicts.values() if x[0] == 'verified' and x[2] < 2),
                   'seconds': round(time.time() - t, 1), 'runs': sum(r.runs for r in compiled.values()),
                   'not_compiled': dict(reasons.most_common()),
                   'demoted_examples': [f'{c}: {x[3]}' for c, x in verdicts.items() if x[0] == 'demoted'][:5],
                   'verified_codes': sorted(c for c, x in verdicts.items() if x[0] == 'verified'),
                   'compiled_codes': sorted(c for c, r in compiled.items() if r.plan)}
            report[cls] = row
            print(f'{cls}: {row["emulated"]} emulated, {row["compiled"]} compiled, {row["verified"]} verified '
                  f'({row["verified_constant"]} on constant values), {row["demoted"]} demoted, '
                  f'{row["uncovered"]} on an uncovered path, '
                  f'{row["seconds"]}s, {row["runs"]} getter runs', flush=True)
            if args.write:
                n = plancompile.store_compiled(store, cls, compiled, verdicts)
                store.save()
                print(f'  stored {n} verified compiled plans', flush=True)
        by_table = defaultdict(Counter)
        for t, rtype in snapshot.TABLES.items():
            spec = tables.RECORD_TYPES[rtype]
            codes = {c.code for c in snapshot.columns_for(engine.catalog, t) if snapshot.traced(c)}
            classes = spec.classes or sorted({c for c in live[spec.table].classes if c in report})
            for cls in classes:
                row = report.get(cls)
                if not row or 'skipped' in row:
                    continue
                emulated = codes & set(todo.get(cls, ()))
                by_table[t]['emulated'] += len(emulated)
                by_table[t]['verified'] += len(emulated & set(row['verified_codes']))
                by_table[t]['compiled'] += len(emulated & set(row.get('compiled_codes', ())))
        print('\nper snapshot table (sum over its record classes):')
        for t, c in sorted(by_table.items()):
            share = 100 * c['verified'] / max(c['emulated'], 1)
            print(f'  {t:16} emulated {c["emulated"]:4}  compiled {c["compiled"]:4}  verified {c["verified"]:4} '
                  f'({share:.0f}%)')
        total = Counter()
        for row in report.values():
            if 'skipped' not in row:
                total.update({k: row[k] for k in ('emulated', 'compiled', 'verified', 'demoted', 'uncovered', 'runs')})
        import resource
        cpu = resource.getrusage(resource.RUSAGE_SELF)
        print(f'\nall classes: {dict(total)}; {time.time() - started:.0f}s wall, '
              f'{cpu.ru_utime + cpu.ru_stime:.0f} CPU s (this process)')
        if args.json:
            with open(args.json, 'w') as fh:
                json.dump({'classes': report, 'tables': {t: dict(c) for t, c in by_table.items()},
                           'total': dict(total)}, fh, indent=1)
    finally:
        engine.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
