"""Live checks of the editor2 lane: the full-scan machinery, the role tables that the 25-record census called
unavailable, the stadium sides behind the stand flags, and the nation transfer windows (EDITOR getter)."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


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
def engine():
    from fm_live_mcp.fmdb.engine import Engine
    eng = Engine.open()
    try:
        yield eng
    finally:
        eng.close()


def test_scan_type_decides_small_type(engine):
    sys.path.insert(0, str(ROOT / 'scripts'))
    import fmdb_editor_scan as scan
    res = scan.scan_type(engine, 'regi', {'rdui', 'dbnm'}, {}, stop=2, budget=60)
    assert res['complete'] and res['records'] == res['scanned'] > 0
    assert res['pairs']['regi.dbnm']['counts'].get('value') == 2          # stops after `stop` values
    assert res['pairs']['regi.rdui']['asked'] == res['records']


def test_role_tables_read_on_the_managed_squad(engine):
    from fm_live_mcp.fmdb import tables
    _, people = tables.managed(engine.cached_read, engine.base)
    res = engine.get_property(people[0], 'PATL')
    assert isinstance(res.value, list) and res.value and 'valu' in res.value[0]
    res = engine.get_property(people[0], 'PWEI')
    assert isinstance(res.value, list) and res.value and 'WeGK' in res.value[0]


def test_stadium_sides_carry_the_stand_flags(engine):
    from fm_live_mcp.fmdb import editor_live, tables, variant
    stadiums = [p for p in tables.entries(engine.cached_read, engine.base, 'stadiums') if p][:40]
    seen = set()
    for p in stadiums:
        sides = variant.to_json(engine.get_property(p, 'Ssds').value) or []
        seen |= {s.get('indx') for s in sides if isinstance(s, dict)}
    assert set(editor_live.STAND_KEYS.values()) <= seen


def test_nation_transfer_window(engine):
    from fm_live_mcp.fmdb import tables, variant
    nations = [p for p in tables.entries(engine.cached_read, engine.base, 'nations') if p]
    england = next(p for p in nations if engine.get_property(p, 'dbnm').value == 'England')
    start = engine.get_property(england, 'x:transfer_window_nwsd')
    end = engine.get_property(england, 'x:transfer_window_nwed')
    assert start.ok and end.ok
    s, e = str(variant.to_json(start.value)), str(variant.to_json(end.value))
    assert s[:4].isdigit() and e[:4].isdigit() and s < e and s > engine.game_date()
