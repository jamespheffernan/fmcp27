"""Offline checks of `fmdb/sources/match_state.py` (no game).

The page-capture tests run the match-screen statistics route over the live-match captures taken
during West Ham v Newcastle (13 Dec 2030); they are skipped where the captures or the pinned
build's plugin binary are absent."""
import json
from pathlib import Path
import struct
import zlib

import pytest

from fm_live_mcp.fmdb.sources import match_state as ms

LIVE = Path('/Volumes/4TB Private/Offloaded/Agent Work/fmdb-20261111/cache-match/live')
import _pinned_build

PLUGIN = _pinned_build.PLUGIN      # the captures were taken on the pinned build
PAGE = 0x4000


class _Engine:
    """Engine stand-in for the table declarations (no reads)."""
    base = 0


def test_tables_declare_policy_and_unique_columns():
    tables = ms.tables(_Engine())
    names = [t.name for t in tables]
    assert names == ['player_registration_marker', 'competition_registration_rule', 'registration_verdict',
                     'squad_manager_entry', 'comp_host_record', 'comp_host_nation',
                     'match_momentum_weight', 'match_rating_weight', 'match_screen_team_stats',
                     'match_momentum', 'match_rating_component', 'native_manager']
    for t in tables:
        cols = [c.name for c in t.columns]
        assert len(cols) == len(set(cols)), t.name
        assert t.manager.get('scope') in ('public', 'own_club', 'never'), t.name
        assert t.build_mode == 'lazy' and t.refresh == 'content' and t.fingerprint, t.name
        assert t.source_note, t.name
    reg = tables[0]
    assert reg.manager == {**reg.manager, 'scope': 'own_club', 'own_club_column': 'club_idx'}


def test_predicate_newest_exact_marker_decides():
    team, other = 0x7A00001000, 0x7A00002000
    m = [(0, team, 4, 25, 8, 0), (1, other, 4, 25, 8, 0), (2, team, 4, 27, 8, 0)]
    assert ms.predicate(m, team, 8) == (False, 27)            # newest is a pending removal
    assert ms.predicate(m[:2], team, 8) == (True, 25)
    assert ms.predicate(m, team, 0) == (False, None)          # no marker for that selector
    assert ms.predicate(m + [(3, team, 4, 56, 0, 0)], team, 8) == (False, 56)   # kind 56 ignores selector
    assert ms.predicate([(0, team, 3, 25, 8, 0)], team, 8) == (False, None)    # not a TEAM transport


def test_manager_roots_are_distinct_and_checked_by_vtable():
    rvas = [(rva, chain) for _, rva, chain, _, _ in ms.MANAGERS]
    assert len(rvas) == len(set(rvas))
    squad = next(m for m in ms.MANAGERS if m[0] == 'GAME_SQUAD_MANAGER')
    assert squad[1:] == (0x56A4B90, (0x158, 0x58), 0x55DE078, 0x567A0E8)


def test_vector_sizes_finds_headers_and_skips_image_pointers():
    base = 0x7000000000
    raw = bytearray(0x100)
    struct.pack_into('<Q', raw, 0, base + 0x55DE078)                       # vtable
    struct.pack_into('<QQQ', raw, 8, 0x7A00000000, 0x7A00000020, 0x7A00000040)
    struct.pack_into('<QQQ', raw, 0x40, base + 0x10, base + 0x20, base + 0x30)   # image range: not a vector
    struct.pack_into('<QQQ', raw, 0x80, 0x7A00001000, 0x7A00001000, 0x7A00001000)
    assert ms._vector_sizes(bytes(raw), base) == {'0x8': 0x20, '0x80': 0}


def test_squad_entry_dates():
    rec = bytearray(0x30)
    struct.pack_into('<IHHI', rec, 0, 345, 0, 5, 1)
    for k, day in enumerate((342, 343, 342, 342, 342)):
        struct.pack_into('<HH', rec, 0x0C + 4 * k, 2030, day)          # <u16 year, u16 day>
    struct.pack_into('<HH', rec, 0x20, 343, 2030)                       # packed <day, year>
    dates = [ms._packed(((v & 0xFFFF) << 16) | (v >> 16)) for v in struct.unpack_from('<5I', rec, 0x0C)]
    dates.append(ms._packed(struct.unpack_from('<I', rec, 0x20)[0]))
    assert dates == ['2030-12-08', '2030-12-09', '2030-12-08', '2030-12-08', '2030-12-08', '2030-12-09']
    empty = struct.pack('<HH', 0, 0xFFFF)
    v = struct.unpack('<I', empty)[0]
    assert ms._packed(((v & 0xFFFF) << 16) | (v >> 16)) is None


class _Capture:
    """`<Q page><I zlib length><zlib 16 KB page>` records; image bytes absent from the capture come
    from the installed plugin file (code and constants are identical in memory)."""

    def __init__(self, tag):
        from fm_live_mcp.fmdb.image import PluginImage
        self.meta = json.loads((LIVE / f'{tag}.meta.json').read_text())
        self.base = self.meta['base']
        self.data = (LIVE / f'{tag}.pages.z').read_bytes()
        self.index, off = {}, 0
        while off + 12 <= len(self.data):
            addr, n = struct.unpack_from('<QI', self.data, off)
            self.index[addr] = (off + 12, n)
            off += 12 + n
        self.pages = {}
        self.image = PluginImage.load(PLUGIN, verify=False)

    def _page(self, a):
        if a not in self.pages:
            loc = self.index.get(a)
            self.pages[a] = zlib.decompress(self.data[loc[0]:loc[0] + loc[1]]) if loc else None
        return self.pages[a]

    def read(self, address, length):
        out, a = bytearray(), address
        while len(out) < length:
            pa = a & ~(PAGE - 1)
            pg = self._page(pa)
            if pg is None:
                if self.base <= address < self.base + 0x5800000:
                    return self.image.file_bytes(address - self.base, length)
                raise ValueError(f'page {pa:#x} not captured')
            take = min(PAGE - (a - pa), length - len(out))
            out += pg[a - pa:a - pa + take]
            a += take
        return bytes(out)


def _capture(tag):
    if not (LIVE / f'{tag}.pages.z').is_file() or not PLUGIN.is_file():
        pytest.skip('live-match captures or the pinned build plugin are not present')
    return _Capture(tag)


def test_half_time_screen_statistics_are_the_simulation_scope():
    cap = _capture('ht1')
    rows = ms.screen_stats_rows(cap.read, cap.base)
    report = json.loads((LIVE / 'ht1.report.json').read_text())
    keyed = {scope: {s['team_index']: s for s in report[scope]['report']['team_statistics']['sides']}
             for scope in ('simulation', 'client_snapshot')}
    assert [(r[1], r[2], r[3], r[4]) for r in rows] == [(0, 591, '2030-12-13', 7), (1, 545, '2030-12-13', 7)]
    for r in rows:
        sim, snap = keyed['simulation'][r[2]], keyed['client_snapshot'][r[2]]
        got = dict(shots=r[5], shots_on_target=r[6], expected_goals=r[7], passes_attempted=r[8],
                   passes_completed=r[9], corners=r[10], possession_time_raw=r[11])
        assert got == {k: (round(sim[k], 4) if k == 'expected_goals' else sim[k]) for k in got}
        assert (r[8], r[9]) != (snap['passes_attempted'], snap['passes_completed'])
    # Newcastle at half time: 4 shots, none on target, xG 0.24 (the client snapshot said 5 and 0.63)
    assert rows[1][5:8] == (4, 0, 0.2383)


def test_full_time_capture_reads_the_same_route():
    cap = _capture('ft1')
    rows = ms.screen_stats_rows(cap.read, cap.base)
    assert [(r[2], r[5], r[6], r[7]) for r in rows] == [(591, 7, 2, 0.9114), (545, 9, 1, 1.2386)]


def test_screen_route_refuses_changed_code():
    cap = _capture('ht1')
    real = cap.read

    def patched(address, length):
        raw = real(address, length)
        if address == cap.base + ms.SCREEN_STATS_CODE[0]:
            return b'\0' + raw[1:]
        return raw
    with pytest.raises(ValueError, match='changed in this build'):
        ms.screen_stats_rows(patched, cap.base)
