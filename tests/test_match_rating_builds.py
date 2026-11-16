"""`fmdb/match_rating.py` on both builds: the mirror equals each build's own updater, emulated.

27.0.1 moved the updater (0x4560B60 -> 0x4589918) and changed its bytes. The masked instruction
diff: the loop-1 spell test and the keeper-time block were moved to other places in the function,
the multiplier selection (0x4561460..0x4561570 -> 0x458A21C..0x458A3CC) was re-laid out with the
same 22 (k, goal difference, sign) outcomes, and the three ADRP page offsets of the position tables
and the short-time divisor follow the data shift. No offset, constant or call changed (the updater
calls nothing). This test runs each build's unmodified code from the preserved plugin files in the
reader's VM over the same synthetic MATCH_PLAYER objects and compares the stored words with the
mirror, its globals set to that build's addresses (what the address book rewrites them to)."""
from __future__ import annotations

import random
import struct
from pathlib import Path

import pytest

from fm_live_mcp.fmdb import match_rating as mr

BUILDS = Path('/Volumes/4TB Private/Offloaded/Agent Work/fmdb-runtime-research/builds')
OLD, NEW = BUILDS / '27.0.0.2493426/game_plugin', BUILDS / '27.0.1.2503222/game_plugin'

# the mirror's globals on each build: 27.0.0 = the source; 27.0.1 read from the updater's own ADRP
# pairs (0x4589934 manager, 0x4589A10 / 0x4589AC0 tables, 0x458A0E0 divisor) and the vtables by RTTI
ADDRESSES = {
    'old': dict(UPDATER=(0x4560B60, 0x45616AC), RATINGS_MANAGER=0x56C35A0, RATINGS_VT=0x56A01C8,
                POS_UNION_TABLE=0x53FCBA8, POS_TEST_TABLE=0x53FCD40, FULL_TIME_F=0x53FCA6C,
                MATCH_PLAYER_VT=0x569EE68, PLAYER_STATS_VT=0x55FA800, GAME_MATCH_VT=0x55FA258),
    'new': dict(UPDATER=(0x4589918, 0x458A478), RATINGS_MANAGER=0x575F5A0, RATINGS_VT=0x573C1C8,
                POS_UNION_TABLE=0x5497DE0, POS_TEST_TABLE=0x5497F78, FULL_TIME_F=0x5497D0C,
                MATCH_PLAYER_VT=0x573AE68, PLAYER_STATS_VT=0x5696800, GAME_MATCH_VT=0x5696258),
}
SHA1 = {'old': '5e9b164d6d7bdd58e7208f8ce6734d85680da194', 'new': 'c35d3ddceb6fcf51fbd95d77985d279cf8046935'}

# position codes whose spells count toward the total time (the masks of loop 1)
COUNTED = [f for f in range(-31, 20) if mr._counted((f & 0x7F) << 6)]
needs_builds = pytest.mark.skipif(not (OLD.is_file() and NEW.is_file()),
                                  reason='preserved 27.0.0 and 27.0.1 plugins not present')


def test_both_updaters_are_accepted_and_nothing_else():
    assert set(mr.VERIFIED_UPDATERS) == set(SHA1.values())


def _static_vm(path):
    """A VM over the plugin file alone (as tests/test_function_match.py): rebased pointers, imports by name."""
    from fm_live_mcp.fmdb import platform_model, vm as vmmod
    from fm_live_mcp.fmdb.image import PluginImage
    from fm_live_mcp.fmdb.memory import MemoryReadError
    base, fake = 0x1_2000_0000, 0x5F00_0000_0000
    b = platform_model.load_binary(path)
    binds = b.image.binds
    imports = {n: fake + 0x80_0000 + 0x10 * k for k, n in enumerate(sorted(set(binds.values())))}

    class Memory:
        def cached_read(self, address, length):
            if fake <= address < fake + 0x100_0000:
                return bytes(length)
            rva = address - base
            if not (0 <= rva and rva + length <= b.image_end()):
                raise MemoryReadError(f'{address:#x} is outside the plugin')
            data = bytearray(b.image.file_bytes(rva, length))
            for slot in range((rva - 8) & ~7, rva + length, 8):
                word = (struct.pack('<Q', base + b.rebases[slot]) if slot in b.rebases else
                        struct.pack('<Q', imports[binds[slot]]) if slot in binds else None)
                for k in range(8 if word else 0):
                    if rva <= slot + k < rva + length:
                        data[slot + k - rva] = word[k]
            return bytes(data)
        read = cached_read

    class Bare(vmmod.PropertyVM):
        def _session_setup(self):
            self._long_results, self.registry, self._interceptors = {}, 0, []
    return Bare(Memory(), base, PluginImage.load(path, verify=False), file_resolver=False, view='game'), base, b


class _World:
    """Synthetic manager, match, sides, team, statistics and MATCH_PLAYER in the VM's static area."""
    SIZES = dict(mgr=0x20, entries=0x90 * 3, rows=0x68 * 64, nodes=0x30 * 64, match=0x15600, pl=0x1E80,
                 st=0x200, side0=0x800, side1=0x800, team=0x3600, spells=40 * 8, items=16 * 8)

    def __init__(self, v, base, a):
        self.v, self.base, self.a = v, base, a
        self.at = {k: v._static(bytes(n)) for k, n in self.SIZES.items()}
        v.set_overlay(base + a['RATINGS_MANAGER'], struct.pack('<Q', self.at['mgr']))

    def put(self, addr, data):
        self.v.uc.mem_write(addr, bytes(data))

    def fill(self, rng):
        at, put = self.at, self.put
        for k, n in self.SIZES.items():
            put(at[k], bytes(n))
        # manager: 1..3 entries; the first whose +0x8C <= match +0xA2C is used
        n_entries = rng.randint(1, 3)
        put(at['mgr'], struct.pack('<QQQ', self.base + self.a['RATINGS_VT'], at['entries'],
                                   at['entries'] + 0x90 * n_entries))
        build = rng.randint(0, 100)
        keys = sorted(rng.sample(range(59), rng.choice([59, 59, rng.randint(1, 58)])))
        for e in range(n_entries):
            ent = at['entries'] + 0x90 * e
            put(ent, struct.pack('<Q', at['rows']))
            for j in range(22):
                put(ent + 0x30 + 4 * j, struct.pack('<f', rng.choice([1.0, rng.uniform(0.6, 1.4)])))
            put(ent + 0x88, struct.pack('<iI', rng.choice([6700, 6500, -1]), rng.choice([0, 0, rng.randint(0, 120)])))
            self._map(ent, keys)
        for k in range(len(keys)):
            put(at['rows'] + 0x68 * k, struct.pack('<52h', *[rng.randint(-900, 900) for _ in range(52)]))
        m = at['match']
        put(m + 0xA2C, struct.pack('<I', build))
        put(m + 0xA74, struct.pack('<i', rng.randint(50, 80)))
        put(m + 0xAC2, bytes([rng.choice([0, 2])]))
        put(m + mr.FLAGS, struct.pack('<I', rng.choice([0, 4, 6])))
        put(m + mr.MODE, bytes([rng.choice([0, 4])]))
        put(m + mr.TIME, struct.pack('<I', rng.randint(0, 30000)))
        put(m + mr.ELAPSED, struct.pack('<i', rng.randint(0, 30000)))
        s0, s1 = at['side0'], at['side1']
        put(s0 + 0x698, struct.pack('<Q', s1))
        put(s1 + 0x698, struct.pack('<Q', s0))
        for s in (s0, s1):
            put(s + 0x739, struct.pack('<b', rng.choice([-1, 0, 0, 1])))
            put(s + 0x73A, bytes([rng.randint(0, 4)]))
            put(s + 0x12A, bytes([rng.randint(0, 3)]))
        t = at['team']
        put(t + 0x34FC, struct.pack('<f', rng.uniform(-3.9, 3.9)))
        put(t + 0x34A8, struct.pack('<ii', rng.randint(0, 4), rng.randint(0, 4)))
        st = at['st']
        put(st, struct.pack('<Q', self.base + self.a['PLAYER_STATS_VT']))
        put(st + 0x10, bytes(rng.choice([0, 0, rng.randint(0, 12)]) for _ in range(0x1E0)))
        put(st + 0x1C, struct.pack('<f', rng.uniform(0, 2.5)))
        put(st + 0x28, struct.pack('<f', rng.uniform(-1, 1)))
        put(st + 0xA6, bytes([rng.randint(0, 2)]))
        put(st + 0xD1, bytes([rng.randint(0, 5), rng.randint(0, 5)]))
        pl = at['pl']
        put(pl, struct.pack('<Q', self.base + self.a['MATCH_PLAYER_VT']))
        put(pl + 0x280, struct.pack('<QQQQ', m, s0, rng.choice([s0, s1]), t))
        put(pl + 0x1880, struct.pack('<Q', st))
        spells = []
        for _ in range(rng.randint(1, 5)):
            f = rng.choice(COUNTED) if rng.random() < 0.85 else rng.randint(-31, 19)
            code = ((f & 0x7F) << 6) | rng.randint(0, 63) | (0x2000 if rng.random() < 0.15 else 0)
            spells.append((code, rng.choice([21600, 30000, rng.randint(0, 21600)])))
        for k, (code, ticks) in enumerate(spells):
            put(at['spells'] + 40 * k, struct.pack('<H', code))
            put(at['spells'] + 40 * k + 0x20, struct.pack('<I', ticks))
        put(pl + 0x1AC0, struct.pack('<QQ', at['spells'], at['spells'] + 40 * len(spells)))
        items = []
        for _ in range(rng.choice([0, 0, 1, 2, 3])):
            items.append(struct.pack('<QIBBBx', 1 << rng.choice(keys + [rng.randint(0, 58)]),
                                     rng.randint(0, 30000), rng.randint(0, 3), rng.randint(0, 6), rng.randint(0, 1)))
        put(at['items'], b''.join(items))
        put(pl + 0x1AA8, struct.pack('<QQ', at['items'], at['items'] + 16 * len(items)))
        for off in (0x1C48, 0x1BBC):
            put(pl + off, struct.pack('<i', rng.randint(-3, 5)))
        put(pl + 0x1AED, bytes(rng.randint(0, 255) for _ in range(3)))
        put(pl + 0x1E4A, bytes(rng.randint(0, 9) for _ in range(3)))
        put(pl + 0x1D58, struct.pack('<i', -12345))
        put(pl + 0x1D64, struct.pack('<i', -12345))
        return pl

    def _map(self, ent, keys):
        """std::map<u64, i32>: a balanced tree of `keys` (key 1 << p, value = row index)."""
        nodes = self.at['nodes']

        def build(lo, hi):
            if lo >= hi:
                return 0
            mid = (lo + hi) // 2
            node = nodes + 0x30 * mid
            left, right = build(lo, mid), build(mid + 1, hi)
            self.put(node, struct.pack('<QQ', left, right))
            self.put(node + 0x20, struct.pack('<Qi', 1 << keys[mid], mid))
            return node
        self.put(ent + 0x18, struct.pack('<QQQ', 0, build(0, len(keys)), len(keys)))


def _run(build, players, seed):
    path = OLD if build == 'old' else NEW
    v, base, b = _static_vm(path)
    a = ADDRESSES[build]
    import hashlib
    assert hashlib.sha1(b.image.file_bytes(a['UPDATER'][0], a['UPDATER'][1] - a['UPDATER'][0])).hexdigest() == SHA1[build]
    w = _World(v, base, a)
    rng = random.Random(seed)
    out = []
    saved = {k: getattr(mr, k) for k in a}
    try:
        for k, val in a.items():
            setattr(mr, k, val)
        for _ in range(players):
            pl = w.fill(rng)
            try:
                mirror = mr.compute(v.read, base, pl)
            except ValueError as exc:
                raise AssertionError(f'mirror refused a synthetic player: {exc}')
            v.call(base + a['UPDATER'][0], (pl,))
            st = w.at['st']
            native = (struct.unpack('<i', v.read(pl + 0x1D58, 4))[0], struct.unpack('<i', v.read(pl + 0x1D64, 4))[0],
                      struct.unpack('<H', v.read(st + 0x82, 2))[0], v.read(st + 0xB3, 1)[0],
                      struct.unpack('<I', v.read(pl + 0x1DE0, 4))[0])
            out.append((native, mirror))
    finally:
        for k, val in saved.items():
            setattr(mr, k, val)
    return out


@pytest.mark.slow
@needs_builds
@pytest.mark.parametrize('seed', [1, 2, 3])
def test_mirror_equals_each_builds_updater(seed):
    """400 random players per seed: the stored rating and second word equal the mirror's on each
    build, and both builds store the same words for the same player."""
    old, new = _run('old', 400, seed), _run('new', 400, seed)
    rated = clamped = 0
    for (no, mo), (nn, mn) in zip(old, new):
        assert no == nn                                     # the two builds' code agree
        assert no[0] == mo['rating'] and no[1] == mo['rating_2']
        assert nn[0] == mn['rating'] and nn[1] == mn['rating_2']
        assert mo['rating'] == mn['rating'] and mo['terms'].keys() == mn['terms'].keys()
        b = mr.breakdown(mn)
        assert b['base'] + sum(c['contribution'] for c in b['components']) + b['rounding'] == pytest.approx(b['recomputed'])
        rated += mo['acc'] != 0 and mo['entry'] != 0
        clamped += mo['clamped']
    assert rated > 250 and clamped


@pytest.mark.slow
@needs_builds
def test_multiplier_selection_on_both_builds():
    """Every expectation k in -4..4 against goals for and against 0..6 and both signs of the sum:
    the multiplier slot each build reads equals `_multiplier_offsets` (one distinct float per slot)."""
    for build in ('old', 'new'):
        path = OLD if build == 'old' else NEW
        v, base, _ = _static_vm(path)
        a = ADDRESSES[build]
        w = _World(v, base, a)
        rng = random.Random(7)
        for k in range(-4, 5):
            for gf in range(7):
                for ga in range(7):
                    for sign in (1, -1):
                        pl = w.fill(rng)
                        ent = w.at['entries']
                        # one entry, model always chosen; distinct floats 1 + slot / 1000
                        w.put(w.at['mgr'] + 0x10, struct.pack('<Q', ent + 0x90))
                        w.put(ent + 0x8C, struct.pack('<I', 0))
                        w.put(ent + 0x88, struct.pack('<i', 6700))
                        for j in range(22):
                            w.put(ent + 0x30 + 4 * j, struct.pack('<f', 1 + (0x30 + 4 * j) / 1000))
                        w.put(w.at['st'] + 0x10, bytes(0x1E0))
                        w.put(w.at['team'] + 0x34FC, struct.pack('<f', k + 0.25 * (1 if k >= 0 else -1)))
                        w.put(w.at['st'] + 0xD1, bytes([gf, ga]))
                        # one full-time spell at f = 0 and a time row of +-2000 fixes the sign of acc
                        w.put(w.at['spells'], struct.pack('<H', 0))
                        w.put(w.at['spells'] + 0x20, struct.pack('<I', 21600))
                        w.put(w.at['pl'] + 0x1AC8, struct.pack('<Q', w.at['spells'] + 40))
                        w.put(w.at['pl'] + 0x1AB0, struct.pack('<Q', w.at['items']))
                        w.put(w.at['match'] + mr.FLAGS, struct.pack('<I', 0))
                        w._map(ent, list(range(59)))
                        for r in range(59):
                            w.put(w.at['rows'] + 0x68 * r, struct.pack('<h', 2000 * sign) + bytes(0x66))
                        v.call(base + a['UPDATER'][0], (pl,))
                        rating = struct.unpack('<i', v.read(pl + 0x1D58, 4))[0]
                        pos, neg = mr._multiplier_offsets(k, gf, ga)
                        saved = {n: getattr(mr, n) for n in a}
                        try:
                            for n, val in a.items():
                                setattr(mr, n, val)
                            out = mr.compute(v.read, base, pl)
                        finally:
                            for n, val in saved.items():
                                setattr(mr, n, val)
                        want = 1 + (pos if sign > 0 else neg) / 1000
                        assert out['multiplier'] == pytest.approx(want, abs=1e-6), (build, k, gf, ga, sign)
                        assert out['rating'] == rating, (build, k, gf, ga, sign)
