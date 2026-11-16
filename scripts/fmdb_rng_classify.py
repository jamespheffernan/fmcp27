"""Classify every UI screen field that draws random numbers (docs/fmdb/REFUSALS.md "RNG").

Each screen of `ui_recipes_more.SCREENS` (and the player status recipe for one squad player) is
read twice on fresh UiHandlerVMs with rng='copy': once with the VM-private copy of the game
thread's pcg32 state as it is (salt 0), once with that copy replaced by a salted state (and the
private std::random_device sequence salted the same way). A field that drew numbers and is equal
in both runs is class (a), independent of the draws; a field that differs is class (b), a
function of the generator state: 'copy' gives what the game would compute from its current
state, not necessarily what a screen already on display drew.

  PYTHONPATH=. python scripts/fmdb_rng_classify.py [--screens medical,transfers] [--salt 4660]
      [--json out.json]

Read-only against the game: shipped code runs in this process on copied bytes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

VOLATILE = {'seconds', 'rng_uses', '_meta', 'timing', 'data_seconds', 'request_params_used', 'build_seconds',
            'input_seconds', 'wall_seconds'}


def run(name, salt):
    from fmdb_ui_read import open_vm
    from fm_live_mcp.fmdb import ui_recipes_more as M
    session, memory, vm = open_vm(rng='copy')
    vm.rng_salt = salt
    try:
        started, cpu = time.perf_counter(), time.process_time()
        out = M.SCREENS[name](vm)
        return (json.loads(json.dumps(out, default=str)), time.perf_counter() - started,
                time.process_time() - cpu)
    finally:
        memory.close()
        session.close()


def classify(name, salt):
    from fm_live_mcp.fmdb.ui_vm import two_seed
    runs = {}

    def read(s):
        runs[s] = run(name, s)
        return runs[s][0]
    answer, changed = two_seed(read, salt, ignore=VOLATILE)
    a, b = runs[0][0], runs[salt][0]
    drew = {}
    for source, info in (a.get('sources') or {}).items():
        for field in info.get('fields_using_random_draws') or ():
            moved = [p for p in changed if repr(field) in p]
            drew[f'{source}.{field}'] = 'generated at read' if moved else 'stable'
    unavailable = {run_: {s: info.get('unavailable') for s, info in (out.get('sources') or {}).items()
                          if info.get('unavailable')} for run_, out in (('plain', a), ('salted', b))}
    return {'screen': name, 'rng_uses': a.get('rng_uses'), 'rng_uses_salted': b.get('rng_uses'),
            'fields_using_random_draws': drew, 'unavailable': unavailable, 'changed_paths': changed[:200],
            'changed_count': len(changed), 'seconds': [round(runs[0][1], 1), round(runs[salt][1], 1)],
            'cpu_seconds': [round(runs[0][2], 1), round(runs[salt][2], 1)]}


def main(argv=None):
    from fm_live_mcp.fmdb import ui_recipes_more as M
    ap = argparse.ArgumentParser()
    ap.add_argument('--screens', help='comma-separated SCREENS names (default: all)')
    ap.add_argument('--salt', type=int, default=0x1234)
    ap.add_argument('--json', help='write the classification here')
    args = ap.parse_args(argv)
    names = args.screens.split(',') if args.screens else list(M.SCREENS)
    results = []
    for name in names:
        try:
            r = classify(name, args.salt)
        except Exception as exc:  # noqa: BLE001 - report and continue
            r = {'screen': name, 'error': f'{type(exc).__name__}: {exc}'}
        results.append(r)
        print(json.dumps({k: v for k, v in r.items() if k != 'changed_paths'}, default=str), flush=True)
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=1, default=str))
    return 0


if __name__ == '__main__':
    sys.exit(main())
