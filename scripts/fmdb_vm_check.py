"""Differential check: FastVM (C accelerator) against PropertyVM on the running FM27.

For sampled records of every snapshot table and every column code of the table, both VMs run
the record's getter on the same cached live pages. A cell agrees when the canonical value,
the variant kind, the handled flag, the view and (for refusals) the reason text are equal;
the emulated instruction count is compared as well.

PropertyVM stops a call after 5 s of wall-clock time, so on a loaded machine it refuses calls
that the instruction budget allows. A cell that differs is therefore asked again on a
PropertyVM with a 10-minute timeout; `classic_timed_out` counts the ones that only differed
because of the wall clock. The game runs during the check and each VM keeps the pages it read, so
a cell that still differs is asked of both VMs again on new instances, back to back, up to three
times: `moved_between_runs` counts the cells that then agree (the game changed the value between
the first two runs), and `different` the cells that disagree every time.

Usage: PYTHONPATH=. python scripts/fmdb_vm_check.py [--records 12] [--tables player,person]
           [--seed 7] [--timing]
Exit status 1 when any cell disagrees.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter, defaultdict

from fm_live_mcp.fmdb import bulkplans, fastvm, snapshot, tables
from fm_live_mcp.fmdb.engine import Engine, _VMReader
from fm_live_mcp.fmdb.extras import read_derived
from fm_live_mcp.fmdb.vm import PropertyVM, Unavailable


def describe(result):
    value = bulkplans.canonical(result)
    reason = result.value.reason if isinstance(result.value, Unavailable) else None
    return (repr(value), result.kind, result.handled, result.view, reason)


def ask(vm, record, code):
    if code.startswith('x:'):
        return read_derived(vm, record, code[2:])
    return vm.get_property(record, code)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--records', type=int, default=12, help='records per class')
    ap.add_argument('--tables')
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--timing', action='store_true', help='also print per-VM seconds')
    args = ap.parse_args(argv)
    if not fastvm.available():
        print('fm_vm_accel is not built (scripts/build_vm_accel.sh)')
        return 2
    engine = Engine.open()
    rng = random.Random(args.seed)
    wanted = args.tables.split(',') if args.tables else list(snapshot.TABLES)
    try:
        reader = _VMReader(engine.memory)
        resolver = engine.file_resolver()
        classic = PropertyVM(reader, engine.base, engine.image, file_resolver=resolver)
        patient = None                      # PropertyVM with a 10-minute timeout, made on first use
        fast = fastvm.FastVM(reader, engine.base, engine.image, file_resolver=resolver)
        live = {}
        totals = Counter()
        seconds = defaultdict(float)
        differences = []
        instruction_diffs = 0
        for t in wanted:
            kind = tables.RECORD_TYPES[snapshot.TABLES[t]].table
            if kind not in live:
                live[kind] = snapshot.enumerate_table(engine, kind)
            table = live[kind]
            rows = snapshot.table_rows(table, snapshot.TABLES[t])
            by_class = defaultdict(list)
            for i in rows:
                by_class[table.classes[i]].append(i)
            codes = [c.code for c in snapshot.columns_for(engine.catalog, t)]
            codes = list(dict.fromkeys(codes))
            for cls, idxs in sorted(by_class.items()):
                sample = rng.sample(idxs, min(args.records, len(idxs)))
                engine.prefetch([table.pointers[i] for i in sample])
                for i in sample:
                    record = table.pointers[i]
                    for code in codes:
                        t0 = time.perf_counter()
                        a = ask(classic, record, code)
                        t1 = time.perf_counter()
                        b = ask(fast, record, code)
                        t2 = time.perf_counter()
                        seconds['classic'] += t1 - t0
                        seconds['fast'] += t2 - t1
                        totals['cells'] += 1
                        da, db = describe(a), describe(b)
                        if da != db:
                            if patient is None or len(patient.live_pages) > 3000:
                                patient = PropertyVM(reader, engine.base, engine.image, file_resolver=resolver,
                                                     timeout_us=600_000_000)
                            again = ask(patient, record, code)
                            if describe(again) == db:
                                totals['classic_timed_out'] += 1
                                if again.stats.instructions != b.stats.instructions:
                                    instruction_diffs += 1
                                continue
                            # The game runs while this reads, and each VM keeps its own copy of
                            # the pages it touched: a value the game changed between the two
                            # runs differs without either VM being wrong. Ask both again, back
                            # to back, on new VMs with no pages kept; the cell is `different`
                            # only when they still disagree every time.
                            moved = False
                            for _retry in range(3):
                                engine.prefetch([record])
                                one = ask(PropertyVM(reader, engine.base, engine.image, file_resolver=resolver,
                                                     timeout_us=600_000_000), record, code)
                                two = ask(fastvm.FastVM(reader, engine.base, engine.image,
                                                        file_resolver=resolver), record, code)
                                if describe(one) == describe(two):
                                    moved = True
                                    break
                            if moved:
                                totals['moved_between_runs'] += 1
                                continue
                            totals['different'] += 1
                            if len(differences) < 40:
                                differences.append({'table': t, 'class': cls, 'idx': i, 'code': code,
                                                    'classic': da, 'fast': db})
                        elif a.stats.instructions != b.stats.instructions:
                            instruction_diffs += 1
                        if da[4]:
                            totals['refused: ' + da[4]] += 1
            print(f'{t}: {totals["cells"]} cells so far, {totals["different"]} different', flush=True)
            if len(classic.live_pages) > 3000:      # as Engine.get_property does for PropertyVM
                classic = PropertyVM(reader, engine.base, engine.image, file_resolver=resolver)
        print(json.dumps({'cells': totals['cells'], 'different': totals['different'],
                          'classic_timed_out': totals['classic_timed_out'],
                          'moved_between_runs': totals['moved_between_runs'],
                          'instruction_count_differs': instruction_diffs,
                          'refusals': {k[9:]: v for k, v in totals.items() if k.startswith('refused: ')},
                          'seconds': {k: round(v, 2) for k, v in seconds.items()} if args.timing else None,
                          'fast_state': {'live_pages': len(fast.live_pages), 'tlb_fills': fast._st.fills,
                                         'python_faults': fast._st.faults, 'tlb_flushes': fast._st.tlb_flushes}},
                         indent=1))
        for d in differences:
            print(json.dumps(d))
        return 1 if totals['different'] else 0
    finally:
        engine.close()


if __name__ == '__main__':
    sys.exit(main())
