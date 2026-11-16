"""Live-gated snapshot checks: build/refresh, differential vs the getter, cross-check vs the
hand-built tools, and the three example queries (scripts/fmdb_snapshot_check.py).

Skipped unless one supported FM27 process and the native helpers are available."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _live_available():
    if sys.platform != 'darwin':
        return False
    try:
        from fm_live_mcp.bridge import Bridge, discover_processes
        return Bridge().helper.is_file() and len(discover_processes()) == 1 \
            and (ROOT / 'build' / 'fm_fast_reader').is_file()
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _live_available(), reason='FM27 not running or helpers missing')


@pytest.fixture(scope='module')
def report(tmp_path_factory):
    sys.path.insert(0, str(ROOT / 'scripts'))
    import fmdb_snapshot_check
    out = tmp_path_factory.mktemp('fmdb') / 'check.json'
    try:
        fmdb_snapshot_check.main(['--rows', '200', '--json', str(out)])
    except fmdb_snapshot_check.SnapshotNotReady as exc:
        # An empty cache derives its read plans in the background first; nothing to check yet.
        pytest.skip(f'snapshot not built in this cache yet: {exc}')
    return json.loads(out.read_text())


def test_differential_mismatches_demote_plans(report):
    diff = report['differential']
    assert diff['cells_compared'] > 10_000
    mismatched = {f'{t}.{key.split("/", 1)[1]} ({key.split("/", 1)[0]})'
                  for t, row in diff['tables'].items() for key in row['mismatched_columns']}
    # every disagreeing (table, column, class) was demoted in the plan cache, never ignored
    assert mismatched <= set(diff['demoted_plans'])


def test_crosscheck_against_existing_tools(report):
    totals = report['crosscheck']['totals']
    assert totals.get('unmatched_players', 0) == 0
    assert len(report['crosscheck']['players']) >= 10
    assert totals['fields_matched'] >= 10 * 60
    assert totals.get('fields_mismatched', 0) == 0      # NULL (pending / not given by the getter) is counted apart


def test_example_queries(report):
    for name, result in report['queries'].items():
        assert 'error' not in result, (name, result)
        if name != 'managed_contracts_expiring_12_months':   # can legitimately be empty
            assert result['row_count'] > 0, name
        assert result['seconds'] < 60, name


def test_manager_view_query(report):
    runs = report['manager_query']['runs']
    done = [r for r in runs if r.get('status') == 'done']
    assert done, runs
    assert all('error' not in r for r in runs)
    assert done[-1]['seconds'] < 30                       # warm query
    if done[-1]['complete'] is False:
        assert done[-1]['notes'][0].startswith('PARTIAL:')
    for r in runs:
        if r.get('status') == 'building':
            assert 'players covered so far' in r['notes'][0]
