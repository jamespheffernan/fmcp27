#!/usr/bin/env python3
"""Compare the test ids and outcomes of two pytest JUnit XML reports.

    python scripts/test_suite_compare.py BEFORE.xml AFTER.xml [--live-file NAME ...] [--json OUT]

A test id is the JUnit classname plus name (pytest writes `tests.test_x` or `tests.test_x.Class`
and the test name with its parameters). The outcome is passed, skipped, failed or error; a test
reported twice (for example a call failure and a teardown error) keeps the worst outcome.

Prints the ids only in one report, the ids whose outcome changed, and a count per outcome. Ids in
files named `*_live.py` or passed with --live-file are listed separately as game-dependent: their
outcome follows the running game and the cache, not the code; so are the ids tests/suite_profile.json
lists as live (--profile). Exit status 1 when any non-live id
is missing from one side or changed outcome, else 0.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

RANK = {'passed': 0, 'skipped': 1, 'failed': 2, 'error': 3}


def outcomes(path: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for case in ET.parse(path).getroot().iter('testcase'):
        if not case.get('classname') and not case.get('name'):
            continue  # the placeholder an interrupted run writes
        # xdist's loadgroup suffix (`@group`) is not part of the id
        name = re.sub(r'@[\w.-]+$', '', case.get('name', ''))
        key = f"{case.get('classname', '')}::{name}"
        tags = {child.tag for child in case}
        outcome = ('error' if 'error' in tags else 'failed' if 'failure' in tags
                   else 'skipped' if 'skipped' in tags else 'passed')
        if key not in result or RANK[outcome] > RANK[result[key]]:
            result[key] = outcome
    return result


def junit_key(nodeid: str) -> str:
    """tests/test_x.py::Class::test_y[p] -> tests.test_x.Class::test_y[p] (the JUnit spelling)."""
    parts = nodeid.split('::')
    classname = '.'.join([parts[0][:-3].replace('/', '.'), *parts[1:-1]])
    return f'{classname}::{parts[-1]}'


def profile_live(path: Path) -> tuple[set[str], set[str]]:
    """Live modules and live test keys (with and without parameters) from tests/suite_profile.json."""
    if not path.is_file():
        return set(), set()
    data = json.loads(path.read_text())
    modules = {Path(f).stem for f in data.get('live_files', ())}
    return modules, {junit_key(n) for n in data.get('live_tests', ())}


def is_live(key: str, live_files: set[str], live_keys: set[str] = frozenset()) -> bool:
    if key in live_keys or key.split('[', 1)[0] in live_keys:
        return True
    module = key.split('::', 1)[0]
    parts = module.split('.')
    return any(p.endswith('_live') or p in live_files for p in parts)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('before')
    parser.add_argument('after')
    parser.add_argument('--live-file', action='append', default=[],
                        help='module name (for example test_knowledge_stars) whose tests read the game')
    parser.add_argument('--profile', default=str(Path(__file__).resolve().parents[1] / 'tests/suite_profile.json'),
                        help='suite profile whose live_files and live_tests also count as live')
    parser.add_argument('--json', help='write the full comparison here')
    parser.add_argument('--limit', type=int, default=50, help='ids to print per section')
    args = parser.parse_args(argv)
    before, after = outcomes(args.before), outcomes(args.after)
    profile_modules, live_keys = profile_live(Path(args.profile))
    live_files = set(args.live_file) | profile_modules

    only_before = sorted(set(before) - set(after))
    only_after = sorted(set(after) - set(before))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    sections = {
        'only_in_before': [k for k in only_before if not is_live(k, live_files, live_keys)],
        'only_in_after': [k for k in only_after if not is_live(k, live_files, live_keys)],
        'outcome_changed': [f'{k}: {before[k]} -> {after[k]}' for k in changed if not is_live(k, live_files, live_keys)],
        'live_only_in_before': [k for k in only_before if is_live(k, live_files, live_keys)],
        'live_only_in_after': [k for k in only_after if is_live(k, live_files, live_keys)],
        'live_outcome_changed': [f'{k}: {before[k]} -> {after[k]}' for k in changed if is_live(k, live_files, live_keys)],
    }
    counts = {name: dict(sorted(collections.Counter(data.values()).items()))
              for name, data in (('before', before), ('after', after))}
    print(f'before: {len(before)} ids {counts["before"]}')
    print(f'after:  {len(after)} ids {counts["after"]}')
    print(f'identical ids and outcomes: {sum(1 for k in before if after.get(k) == before[k])}')
    for name, rows in sections.items():
        print(f'{name}: {len(rows)}')
        for row in rows[:args.limit]:
            print(f'  {row}')
        if len(rows) > args.limit:
            print(f'  ... {len(rows) - args.limit} more')
    if args.json:
        with open(args.json, 'w') as stream:
            json.dump({'counts': counts, **sections}, stream, indent=1)
    differs = sections['only_in_before'] or sections['only_in_after'] or sections['outcome_changed']
    print('RESULT:', 'DIFFERENT' if differs else 'SAME (outside live files)')
    return 1 if differs else 0


if __name__ == '__main__':
    sys.exit(main())
