"""Build the completeness ledger (`fm_live_mcp/fmdb/ledger.py`) and compare it with the recorded "before".

Usage (from the repo root, game running):

    PYTHONPATH=. python scripts/fmdb_ledger.py --refresh          # census + snapshot + UI sweep + ledger + compare
    PYTHONPATH=. python scripts/fmdb_ledger.py                    # ledger from existing inputs + compare
    PYTHONPATH=. python scripts/fmdb_ledger.py --record-before    # store the result as the "before" baseline
    PYTHONPATH=. python scripts/fmdb_ledger.py --markdown docs/fmdb/LEDGER.md

`--refresh` re-runs, in order, one process at a time and under `nice -n 10`: the getter census (`scripts/fmdb_coverage.py` into
$FMCP_CACHE_DIR/coverage), the snapshot build (`scripts/fmdb_snapshot.py`, into $FMCP_CACHE_DIR), and the UI
sweep (`scripts/fmdb_ui_sweep.py --redo --budget 420`: the default 120 s per handler runs out on
TEAM, PERSON and COMPETITION when the machine is loaded); then builds the ledger from those outputs. Set FMCP_CACHE_DIR to a
private cache: the default cache belongs to the installed product. Writes
`fm_live_mcp/fmdb/data/ledger.json.gz` and prints the headline and the comparison with
`ledger-before.json.gz`.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fm_live_mcp.fmdb import ledger  # noqa: E402


def run(step, args):
    print(f'{time.strftime("%H:%M:%S")} {step}: {" ".join(args)}', flush=True)
    started = time.time()
    proc = subprocess.run(['nice', '-n', '10', sys.executable, *args], cwd=ROOT, env={**os.environ, 'PYTHONPATH': str(ROOT)},
                          capture_output=True, text=True)
    tail = (proc.stdout + proc.stderr).strip().splitlines()[-3:]
    print(f'   {step} exit {proc.returncode} in {time.time() - started:.0f}s; ' + ' | '.join(tail)[:600], flush=True)
    return proc.returncode


def cache_dir() -> Path:
    env = os.environ.get('FMCP_CACHE_DIR')
    if not env:
        raise SystemExit('Set FMCP_CACHE_DIR to a private cache before --refresh (the default cache is in use).')
    return Path(env)


def latest_snapshot(cache: Path) -> Path | None:
    found = sorted((cache / 'fmdb').glob('*/snapshot.sqlite'), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--refresh', action='store_true', help='re-run census, snapshot and UI sweep first')
    ap.add_argument('--skip', default='', help='with --refresh: comma list of census,snapshot,sweep to skip')
    ap.add_argument('--coverage', help='coverage.json (default: $FMCP_CACHE_DIR/coverage, else the real seed)')
    ap.add_argument('--snapshot', help='snapshot.sqlite opened read-only (default: newest in $FMCP_CACHE_DIR)')
    ap.add_argument('--offline', action='store_true', help='skip the live root scan')
    ap.add_argument('--record-before', action='store_true', help='store this build as ledger-before.json.gz')
    ap.add_argument('--out', default=str(ledger.CURRENT))
    ap.add_argument('--markdown', help='render docs/fmdb/LEDGER.md from the saved ledger(s)')
    ap.add_argument('--apply-screen-reads', action='store_true',
                    help='mark ledger.SCREEN_READS in the saved ledger without rebuilding it (no sweep, no game)')
    args = ap.parse_args(argv)

    if args.apply_screen_reads:
        current = ledger.load(args.out)
        if current is None:
            raise SystemExit(f'no ledger at {args.out}')
        changed = ledger.apply_screen_reads(current['rows'])
        current['meta']['screen_reads'] = {'rows_changed': changed, 'applied_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')}
        current['headline'] = ledger.headline(current)
        current['gaps'] = ledger.gaps(current)
        ledger.save(current, args.out)
        ui = current['headline']['ui']
        print(f"screen reads: {changed} rows changed; ui {ui['reads']} / {ui['total']} {ui['by_status']}")
        if not args.markdown:
            return

    if args.markdown and not (args.refresh or args.record_before):
        current = ledger.load(args.out) or ledger.load(ledger.BEFORE)
        Path(args.markdown).write_text(ledger.render_markdown(current, ledger.load(ledger.BEFORE)))
        print('wrote', args.markdown)
        return

    env_cache = Path(os.environ['FMCP_CACHE_DIR']) if os.environ.get('FMCP_CACHE_DIR') else None
    if args.refresh:
        cache = cache_dir()
        skip = set(filter(None, args.skip.split(',')))
        if 'census' not in skip:
            run('census', ['scripts/fmdb_coverage.py', '--out', str(cache / 'coverage')])
        if 'snapshot' not in skip:
            run('snapshot', ['scripts/fmdb_snapshot.py'])
        if 'sweep' not in skip:
            run('sweep', ['scripts/fmdb_ui_sweep.py', '--redo', '--budget', '420'])
            run('sweep merge', ['scripts/fmdb_ui_sweep.py', '--merge-only'])
    coverage = Path(args.coverage) if args.coverage else None
    if coverage is None and env_cache and (env_cache / 'coverage' / 'coverage.json').exists():
        coverage = env_cache / 'coverage' / 'coverage.json'
    snap = Path(args.snapshot) if args.snapshot else (latest_snapshot(env_cache) if env_cache else None)
    inputs = ledger.Inputs(coverage=coverage, snapshot=snap, live=not args.offline)
    built = ledger.build(inputs)
    path = ledger.save(built, ledger.BEFORE if args.record_before else args.out)
    if args.record_before:
        ledger.save(built, args.out)
    size = path.stat().st_size
    print(f'wrote {path} ({size / 1e6:.2f} MB); inputs {json.dumps(built["meta"]["inputs"])}')
    print('timings', built['meta']['timings_s'], 'load', [round(x, 1) for x in built['meta']['load']])
    for denom, h in built['headline'].items():
        print(f"  {denom:16s} {h['reads']:6d} / {h['total']:6d}  ({h['percent']}%)  {h['by_status']}")
    before = ledger.load(ledger.BEFORE)
    if before and not args.record_before:
        cmp = ledger.compare(before, built)
        print('compare with before:')
        for k, v in cmp.items():
            if isinstance(v, dict):
                print(f"  {k:16s} {v['before']:>14s} -> {v['after']:>14s}  ({v['gained']:+d})")
        print('  newly read', cmp['newly_read'], 'no longer read', len(cmp['no_longer_read']))
    if args.markdown:
        Path(args.markdown).write_text(ledger.render_markdown(built, before if not args.record_before else None))
        print('wrote', args.markdown)


if __name__ == '__main__':
    main()
