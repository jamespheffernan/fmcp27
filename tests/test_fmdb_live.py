"""Live-gated PropertyVM checks against the repo's hand-proven decoders.

Skipped unless a supported FM27 process and the native helper are available.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _live_available():
    if sys.platform != 'darwin':
        return False
    try:
        from fm_live_mcp.bridge import Bridge, discover_processes
        return Bridge().helper.is_file() and len(discover_processes()) == 1
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _live_available(), reason='FM27 not running or helper missing')


@pytest.fixture(scope='module')
def report(tmp_path_factory):
    sys.path.insert(0, str(ROOT / 'scripts'))
    import fmdb_validate
    import json
    out = tmp_path_factory.mktemp('fmdb') / 'validate.json'
    fmdb_validate.main(['--per-type', '20', '--json', str(out)])
    return json.loads(out.read_text())


# Known, explained difference: the CURRENCY getter overrides the stored name with a
# translated name when the translation table has one (e.g. 'U.S. Dollar').
EXPLAINED = {('currencies', 'Cnam')}


@pytest.mark.parametrize('kind,fields', [
    ('cities', ('Cnam', 'Clat', 'Clon')), ('currencies', ('Cexr',)), ('competitions', ('crep',)),
    ('players', ('PCAB', 'PPAB', 'Pfit', 'Pjad', 'Pcon')),
])
def test_ground_truth(report, kind, fields):
    assert report[kind]['records'] >= 20
    for field in fields:
        counts = report[kind]['fields'][field]
        assert counts.get('mismatch', 0) == 0, (kind, field, counts)
        assert counts.get('match', 0) >= 20, (kind, field, counts)
