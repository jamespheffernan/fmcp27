#!/usr/bin/env python3
"""Regenerate tests/suite_profile.json, the measured data tests/conftest.py turns into markers.

    python -m pytest --complete -n0 -m "not live" --durations=0 \
        --suite-probe /tmp/probe.jsonl > durations.log           # sequential: honest per-test seconds
    python -m pytest --complete -n0 --collect-only -q > collected.txt
    python scripts/test_suite_profile.py --durations durations.log --collected collected.txt \
        --probe '/tmp/probe.jsonl.*' [--slow-seconds 1.0] [--keep-live] [--write]

--durations is a sequential `--durations=0` log (pytest hides phases under 5 ms, which cannot
reach the threshold). A test is slow when setup + call + teardown reaches --slow-seconds; the
first test of a module carries its module fixtures. --probe is the per-worker JSON lines of a
`--suite-probe` run: a test that started a reader on the game's pid is live; a test, or a test
module at import, that read a git-ignored file under evidence/ needs evidence. Ids are collapsed
to the test function, or to the file, when every collected id under it qualifies. Files named
*_live.py are live by name and are not listed.

Without --write the script prints a summary and the would-be file size and changes nothing.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / 'tests' / 'suite_profile.json'
DURATION = re.compile(r'^\s*([\d.]+)s (setup|call|teardown)\s+(\S.*?)\s*$')


def base(nodeid: str) -> str:
    return nodeid.split('[', 1)[0]


def per_test_seconds(paths) -> dict[str, float]:
    totals: dict[str, float] = collections.defaultdict(float)
    for path in paths:
        for line in Path(path).read_text(errors='replace').splitlines():
            match = DURATION.match(line)
            if match:
                totals[match.group(3)] += float(match.group(1))
    return dict(totals)


def collected_ids(path) -> list[str]:
    ids = []
    for line in Path(path).read_text(errors='replace').splitlines():
        line = line.strip()
        if '::' in line and not line.startswith(('=', '-')) and ' ' not in line.split('::', 1)[0]:
            ids.append(line)
    return ids


def probe_records(pattern):
    for path in sorted(glob.glob(pattern)):
        with open(path) as stream:
            for line in stream:
                if line.strip():
                    yield json.loads(line)


def collapse(selected: set[str], collected: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Return (files, functions, ids) that together cover exactly `selected`."""
    by_file = collections.defaultdict(list)
    by_function = collections.defaultdict(list)
    for nodeid in collected:
        by_file[nodeid.split('::', 1)[0]].append(nodeid)
        by_function[base(nodeid)].append(nodeid)
    files = sorted(f for f, ids in by_file.items() if all(i in selected for i in ids))
    covered = {i for f in files for i in by_file[f]}
    functions = sorted(fn for fn, ids in by_function.items()
                       if len(ids) > 1 and all(i in selected for i in ids) and ids[0] not in covered)
    covered |= {i for fn in functions for i in by_function[fn]}
    ids = sorted(i for i in selected if i not in covered)
    return files, functions, ids


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--durations', action='append', default=[], help='sequential --durations=0 -vv log')
    parser.add_argument('--collected', required=True, help='--collect-only -q output of a --complete run')
    parser.add_argument('--probe', help='glob of --suite-probe JSON lines files')
    parser.add_argument('--slow-seconds', type=float, default=1.0)
    parser.add_argument('--keep-live', action='store_true', help='keep the live entries already in the profile')
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args(argv)

    collected = collected_ids(args.collected)
    known = set(collected)
    old = json.loads(PROFILE.read_text()) if PROFILE.exists() else {}
    seconds = per_test_seconds(args.durations)
    slow = {i: round(s, 2) for i, s in seconds.items() if s >= args.slow_seconds and i in known}

    live: set[str] = set()
    evidence: set[str] = set()
    evidence_modules: set[str] = set()
    if args.probe:
        for record in probe_records(args.probe):
            if record.get('phase') == 'collect':
                if record['evidence_reads']:
                    evidence_modules.add(record['nodeid'])
                continue
            if record['live']:
                live.add(record['nodeid'])
            if record['evidence_reads']:
                evidence.add(record['nodeid'])
    evidence |= {i for i in collected if i.split('::', 1)[0] in evidence_modules}
    live_files, live_functions, live_ids = collapse(live, collected)
    live_files = [f for f in live_files if not f.endswith('_live.py')]
    if args.keep_live:
        live_files = sorted(set(live_files) | set(old.get('live_files', ())))
        live_ids = sorted(set(live_functions) | set(live_ids) | set(old.get('live_tests', ())))
    else:
        live_ids = sorted(set(live_functions) | set(live_ids))
    ev_files, ev_functions, ev_ids = collapse(evidence, collected)

    commit = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, capture_output=True,
                            text=True, check=False).stdout.strip()
    profile = {
        '_about': ('Measured data for tests/conftest.py markers. Regenerate with scripts/test_suite_profile.py '
                   '(docs/TESTING.md); do not edit by hand except to add a live test the guard reported.'),
        'measured_at_commit': commit,
        'slow_threshold_seconds': args.slow_seconds,
        'live_files': live_files,
        'live_tests': live_ids,
        'slow_tests': dict(sorted(slow.items())),
        'evidence_files': ev_files,
        'evidence_tests': sorted(set(ev_functions) | set(ev_ids)),
    }
    text = json.dumps(profile, indent=1) + '\n'
    slow_total = sum(slow.values())
    print(f'collected {len(collected)}; timed {len(seconds)}; total measured {sum(seconds.values()):.0f}s')
    print(f'slow (>= {args.slow_seconds}s): {len(slow)} ids, {slow_total:.0f}s')
    print(f'live: {len(live)} ids -> {len(live_files)} files, {len(live_ids)} entries')
    print(f'evidence: {len(evidence)} ids -> {len(ev_files)} files, {len(profile["evidence_tests"])} entries')
    print(f'profile size {len(text)} bytes')
    if args.write:
        PROFILE.write_text(text)
        print(f'wrote {PROFILE}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
