"""Live-gated ledger checks: the live root scan finds the singletons the hand-built readers pin.

Reads the plugin's data segment and one word per candidate pointer; nothing is written to the game.
"""
import sys

import pytest


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
def scan():
    from fm_live_mcp.fmdb import ledger
    from fm_live_mcp.fmdb.engine import Engine
    engine = Engine.open()
    try:
        rtti = ledger.rtti_inventory(engine.image)
        yield rtti, ledger.live_roots(engine, engine.image, rtti)
    finally:
        engine.close()


def test_roots_match_pinned_globals(scan):
    from fm_live_mcp import database
    from fm_live_mcp.fmdb import ledger
    rtti, roots = scan
    # NEWS_MANAGER global documented in UI_NEWS.md (all news, +0xB8).
    assert (0x56A5908, 'pointer') in roots['NEWS_MANAGER']
    # Every enumerated DATABASE_TABLE singleton is found at the global database.py pins.
    for kind, (root, _, mangled) in database.TABLES.items():
        name = ledger._demangle([mangled.decode()])[0]
        assert (root, 'pointer') in roots.get(name, []), kind


def test_most_managers_have_roots(scan):
    from fm_live_mcp.fmdb import ledger
    rtti, roots = scan
    managers = [n for n in rtti if ledger.class_kind(n, ledger.ancestors(rtti, n)) == 'manager']
    assert sum(1 for n in managers if n in roots) >= 0.75 * len(managers)
