"""Live-gated checks of `fmdb/match_rating.py`: the mirrored formula equals the emulated updater 0x4560B60.

Runs on the loaded match when one is resident, and on the half-time / full-time page captures when they
are present (their pages lack the ratings manager, which is read from the live game: the model
parameters are identical between matches). Skipped unless FM27 and the native helper are available."""
import json
import os
import struct
import sys
import zlib
from pathlib import Path

import pytest

LIVE_DIR = Path(os.environ.get('FMCP_MATCH_CAPTURES',
                               '/Volumes/4TB Private/Offloaded/Agent Work/fmdb-20261111/cache-match/live'))
# The running game's code: the installed build's plugin (the address book maps match_rating's addresses).
from fm_live_mcp import build_paths
PLUGIN = build_paths.installed_plugin()


def _live_available():
    if sys.platform != 'darwin':
        return False
    try:
        from fm_live_mcp.bridge import Bridge, discover_processes
        return Bridge().helper.is_file() and len(discover_processes()) == 1
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _live_available() or not PLUGIN.is_file(),
                                reason='FM27 not running, helper or plugin missing')


@pytest.fixture(scope='module')
def engine():
    from fm_live_mcp.fmdb.engine import Engine
    e = Engine.open()
    yield e
    e.close()


class _Capture:
    """`<Q page><I zlib length><zlib 16 KB page>` records; pages it lacks come from `fallback`."""

    def __init__(self, path, fallback):
        data = path.read_bytes()
        self.index, off = {}, 0
        while off + 12 <= len(data):
            a, n = struct.unpack_from('<QI', data, off)
            self.index[a] = (off + 12, n)
            off += 12 + n
        self.data, self.fallback, self.pages = data, fallback, {}

    def read(self, address, length):
        out, a = bytearray(), address
        while len(out) < length:
            pa = a & ~0x3FFF
            take = min(0x4000 - (a - pa), length - len(out))
            if pa in self.index:
                if pa not in self.pages:
                    o, n = self.index[pa]
                    self.pages[pa] = zlib.decompress(self.data[o:o + n])
                out += self.pages[pa][a - pa:a - pa + take]
            else:
                out += self.fallback(a, take)
            a += take
        return bytes(out)


def _compare(read, base, engine_ptr, vm):
    from fm_live_mcp.fmdb import match_rating as mr
    checked = 0
    for _, _, pl in mr.players(read, base, engine_ptr):
        try:
            out = mr.compute(read, base, pl)
        except ValueError as exc:
            assert 'not rated' in str(exc)
            continue
        vm.call(base + mr.UPDATER[0], (pl,))
        assert struct.unpack('<i', vm.read(pl + 0x1D58, 4))[0] == out['rating']
        assert struct.unpack('<i', vm.read(pl + 0x1D64, 4))[0] == out['rating_2']
        b = mr.breakdown(out)
        assert b['base'] + sum(c['contribution'] for c in b['components']) + b['rounding'] == pytest.approx(b['recomputed'])
        assert abs(b['rounding']) < 0.002
        checked += 1
    return checked


def _vm(reader, base):
    from fm_live_mcp.fmdb.image import PluginImage
    from fm_live_mcp.fmdb.vm import PropertyVM
    return PropertyVM(reader, base, PluginImage.load(PLUGIN, verify=False), view='game', rng='refuse')


def test_updater_bytes_are_pinned(engine):
    from fm_live_mcp.fmdb import match_rating as mr
    assert mr.pin(engine.read, engine.base) in mr.VERIFIED_UPDATERS


@pytest.mark.parametrize('tag', ['ht1', 'ft1'])
def test_mirror_equals_emulated_updater_on_captures(engine, tag):
    path = LIVE_DIR / f'{tag}.pages.z'
    if not path.is_file():
        pytest.skip('live-match capture not present')
    meta = json.loads((LIVE_DIR / f'{tag}.meta.json').read_text())
    if meta['base'] != engine.base:
        pytest.skip('capture taken from another game process')
    cap = _Capture(path, engine.read)
    assert _compare(cap.read, meta['base'], meta['engine'], _vm(cap, meta['base'])) >= 30


def test_mirror_equals_emulated_updater_on_loaded_match(engine):
    from fm_live_mcp.fmdb.sources.match_state import screen_stats_source
    try:
        src = screen_stats_source(engine.read, engine.base)
    except ValueError as exc:
        pytest.skip(str(exc))
    vm = _vm(engine, engine.base)
    assert sum(_compare(engine.read, engine.base, eng, vm) for _, _, eng, _ in src) > 0


def test_component_table_sums_to_recomputed_rating(engine):
    from fm_live_mcp.fmdb.sources import match_state as ms
    table = next(t for t in ms.tables(engine) if t.name == 'match_rating_component')
    try:
        rows = list(table.rows())
    except ValueError as exc:
        pytest.skip(str(exc))
    totals = {}
    for r in rows:
        key = r[:3]
        totals.setdefault(key, [0.0, r[10]])[0] += r[8]
    assert totals
    for total, recomputed in totals.values():
        assert total == pytest.approx(recomputed, abs=1e-6)
    # match identity: the same as match.idx (YYYYMMDD * 100000 + home team idx) and the fixture date
    stats = {(r[0], r[1]): r for r in ms.screen_stats_rows(engine.read, engine.base)}
    for r in rows:
        home = stats[(r[0], 0)]
        assert r[15] == home[3] and r[14] == int(home[3].replace('-', '')) * 100000 + home[2]


def test_momentum_series_is_the_match_screen_series(engine):
    """MatchMomentum: 0x4898A94 emulated on the loaded match; 5-minute segments, side 1 the negation."""
    from fm_live_mcp.fmdb.sources import match_state as ms
    table = next(t for t in ms.tables(engine) if t.name == 'match_momentum')
    try:
        rows = list(table.rows())
    except ValueError as exc:
        pytest.skip(str(exc))
    assert rows
    stats = {(r[0], r[1]): r for r in ms.screen_stats_rows(engine.read, engine.base)}
    for client, seg, tick, minute, home, away, match_idx, date in rows:
        assert away == -home and -1.0 <= home <= 1.0
        assert date == stats[(client, 0)][3] and match_idx == int(date.replace('-', '')) * 100000 + stats[(client, 0)][2]
    ticks = [r[2] for r in rows]
    assert ticks == sorted(ticks) and ticks[0] == 1199
