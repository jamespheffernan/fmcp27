"""Offline checks of `fmdb/match_rating.py` (the rating updater 0x4560B60 mirrored).

The equality with the emulated updater on real players is in test_match_rating_live.py; here the
arithmetic helpers and a synthetic player in fake memory, worked by hand from the disassembly."""
import struct

import pytest

from fm_live_mcp.fmdb import match_rating as mr


def test_position_code_and_counted_spells():
    # bits 6..12 are a signed 7-bit code; bit 13 excludes the spell
    assert mr._position_code(0x0000) == 0
    assert mr._position_code(5 << 6) == 5
    assert mr._position_code(0x7F << 6) == -1
    assert mr._position_code(0x41 << 6) == -63
    assert not mr._counted(0x2000)
    # f >= 0 counts when bit f of 0xFEDED is set (f <= 0x13)
    assert mr._counted(0 << 6) and not mr._counted(1 << 6) and mr._counted(2 << 6)
    assert not mr._counted(0x14 << 6)
    # f < 0 counts when bit f + 31 of 0x16B7EFFF is set
    assert mr._counted((-31 & 0x7F) << 6)          # bit 0
    assert not mr._counted((-19 & 0x7F) << 6)      # bit 12 is clear in 0x16B7EFFF


def test_integer_helpers_match_the_instructions():
    assert mr._div21600(43199) == 1 and mr._div21600(-43199) == -1     # truncates toward zero
    assert mr._round_half_away(2.5) == 3 and mr._round_half_away(-2.5) == -3
    assert mr._round_half_away(-0.4) == 0
    assert mr._fcvtzs(-1.9) == -1


@pytest.mark.parametrize('k, gf, ga, expect', [
    (0, 2, 1, (0x40, 0x44)), (0, 1, 1, (0x58, 0x5C)), (0, 0, 1, (0x70, 0x74)),
    (1, 2, 1, (0x58, 0x5C)), (2, 1, 0, (0x80, 0x84)), (1, 3, 0, (0x50, 0x54)),
    (1, 0, 1, (0x70, 0x74)), (2, 0, 1, (0x60, 0x64)), (1, 1, 1, (0x78, 0x7C)), (2, 1, 1, (0x68, 0x6C)),
    (-1, 0, 1, (0x58, 0x5C)), (-2, 0, 1, (0x50, 0x54)), (-1, 0, 2, (0x80, 0x84)),
    (-1, 1, 0, (0x40, 0x44)), (-1, 1, 1, (0x48, 0x4C)), (-2, 1, 1, (0x38, 0x3C)), (-2, 2, 1, (0x30, 0x34)),
])
def test_multiplier_selection(k, gf, ga, expect):
    """0x45612C4..0x4561570: expectation k against the on-pitch goal difference."""
    assert mr._multiplier_offsets(k, gf, ga) == expect


class _Mem:
    def __init__(self):
        self.m = {}

    def put(self, addr, data):
        for i, b in enumerate(data):
            self.m[addr + i] = b

    def q(self, addr, v):
        self.put(addr, struct.pack('<Q', v))

    def read(self, addr, n):
        return bytes(self.m.get(addr + i, 0) for i in range(n))


def test_synthetic_player_full_match():
    """One spell (f = 0, 90 minutes), one weight row: rating = base + round(m x acc)."""
    base = 0x100000000
    mem = _Mem()
    mgr, entry, rows, node = 0x200000, 0x210000, 0x220000, 0x230000
    match, pl, st, spells, side, team = 0x300000, 0x400000, 0x500000, 0x600000, 0x700000, 0x710000
    mem.q(base + mr.RATINGS_MANAGER, mgr)
    mem.q(mgr, base + mr.RATINGS_VT)
    mem.q(mgr + 8, entry)
    mem.q(mgr + 0x10, entry + 0x90)
    mem.put(entry + 0x88, struct.pack('<iI', 6700, 0))
    mem.q(entry, rows)
    for k in range(22):
        mem.put(entry + 0x30 + 4 * k, struct.pack('<f', 1.0))
    mem.put(entry + 0x5C, struct.pack('<f', 1.1))            # k = 0, level, acc < 0: offset 0x5C
    # position masks: f = 0 -> index 31 -> bit 3 in both tables
    mem.q(base + mr.POS_UNION_TABLE + 8 * 31, 1 << 3)
    mem.q(base + mr.POS_TEST_TABLE + 8 * 31, 1 << 3)
    # std::map end node at entry +0x20 whose left child is the root; key 1 << 3 -> row 0
    mem.q(entry + 0x20, node)
    mem.q(node + 0x20, 1 << 3)
    mem.put(node + 0x28, struct.pack('<i', 0))
    row = {0x00: -700, 0x14: 30, 0x1E: 7, 0x32: 70}         # time, shots, passes completed, interceptions
    for off, v in row.items():
        mem.put(rows + off, struct.pack('<h', v))
    mem.q(pl, base + mr.MATCH_PLAYER_VT)
    mem.q(pl + 0x280, match)
    mem.q(pl + 0x288, side)
    mem.q(pl + 0x290, side)
    mem.q(pl + 0x298, team)
    mem.q(pl + 0x1880, st)
    mem.q(pl + 0x1AC0, spells)
    mem.q(pl + 0x1AC8, spells + 40)
    mem.put(spells, struct.pack('<H', 0))
    mem.put(spells + 0x20, struct.pack('<I', 21600))
    mem.put(side + 0x739, b'\xff')
    mem.put(team + 0x34FC, struct.pack('<f', 0.0))
    mem.put(st + 0x90, b'\x02')                               # 2 shots
    mem.put(st + 0xE8, struct.pack('<HH', 30, 0))             # 30 passes completed (+0xE8, +0xEA)
    mem.put(st + 0xE4, struct.pack('<HH', 30, 0))             # 30 attempted
    mem.put(st + 0xCF, b'\x03')                               # 3 interceptions
    mem.put(base + mr.FULL_TIME_F, struct.pack('<f', 21600.0))
    out = mr.compute(mem.read, base, pl, check_class=False)
    acc = 2 * 30 + 30 * 7 + 3 * 70 - 700                     # S then the full-time row +0x00
    assert out['acc'] == acc == -220
    assert out['multiplier'] == pytest.approx(1.1)
    assert out['rating'] == 6700 + round(1.1 * acc) == 6458
    b = mr.breakdown(out)
    total = b['base'] + sum(c['contribution'] for c in b['components']) + b['rounding']
    assert total == pytest.approx(b['recomputed'])
    assert {c['term'] for c in b['components']} == {'shots', 'passes_completed', 'interceptions', 'time_on_pitch'}
    assert next(c for c in b['components'] if c['term'] == 'interceptions')['contribution'] == pytest.approx(0.231)


def test_no_statistics_object_is_not_rated():
    base = 0x100000000
    mem = _Mem()
    mem.q(base + mr.RATINGS_MANAGER, 0x200000)
    mem.q(0x200000, base + mr.RATINGS_VT)
    mem.q(0x400000, base + mr.MATCH_PLAYER_VT)
    mem.q(0x400000 + 0x280, 0x300000)
    with pytest.raises(ValueError, match='not rated'):
        mr.compute(mem.read, base, 0x400000)


def test_every_term_has_a_label_entry():
    keys = {k for _, k, _ in mr.TERMS} | {k for _, k, _ in mr.EXTRA_TERMS}
    keys |= {'assists_beyond_first', 'goals_below_xg', 'yellow_card', 'second_yellow', 'time_on_pitch',
             'no_goal_conceded_flag', 'keeper_shots_faced', 'goal_item', 'goal_item_flagged', 'goal_item_kind_1',
             'goal_item_kind_2', 'goal_item_later', 'goal_item_decisive', 'goal_item_decisive_recent'}
    assert keys <= set(mr.LABELS)
