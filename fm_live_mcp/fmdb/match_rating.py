"""Match player rating: the engine's formula, mirrored from the updater 0x4560B60, with a per-term breakdown.

docs/fmdb/MATCH_STATE.md ("Match ratings") has the derivation. Summary of what 0x4560B60 does for one
simatch::MATCH_PLAYER `pl` (all integer arithmetic 32-bit, all float arithmetic float32, as the code):

* Model entry E: the first 0x90-byte entry of MATCH_PLAYER_RATINGS_MANAGER (global 0x56C35A0) +0x08 whose
  +0x8C (packed build) does not exceed GAME_MATCH +0xA2C. Base rating = E +0x88 (6700), else
  GAME_MATCH +0xA74 x 10.
* Position spells: MATCH_PLAYER +0x1AC0 vector of 40-byte entries <u16 code, ..., u32 time +0x20>.
  Code bit 13 excludes a spell; bits 6..12 are a signed position code f. Total time T is the time of the
  spells whose f passes the masks 0x16B7EFFF (f < 0, bit f + 31) or 0xFEDED (f >= 0, bit f).
  Time is in engine ticks (240 a minute; 21,600 = 90 minutes).
* For each position bit p (0..58) in the union of table 0x53FCBA8[f + 31] over the spells: t_p = time of
  spells with bit p in table 0x53FCD40[f + 31]; the weight row = E +0x00 rows (0x68 bytes, 52 i16) at the
  index E +0x18 std::map holds for key 1 << p. S_p = sum of weight x input over the player's
  GAME_MATCH_PLAYER_STATS (MATCH_PLAYER +0x1880) counters (TERMS). acc += round(t_p / T x S_p); plus
  the time-weighted terms (row +0x00, +0x42, +0x50: x min(t_p, 21600) / 21600) and the goal items
  (MATCH_PLAYER +0x1AA8 16-byte items whose +0x00 is 1 << p).
* Multiplier m: one of E's 22 floats (+0x30..+0x84) chosen by the team's expectation (team +0x34FC,
  truncated) against the player's on-pitch goal difference (stats +0xD1 - +0xD2) and by the sign of acc;
  scaled toward 1 when T < 21,600 by T / f32[0x53FCA6C].
* Rating = clamp(base + round(m x acc), 0, 10000) at MATCH_PLAYER +0x1D58 (x1000). +0x1D64 = rating less
  a losing-side term; stats +0x82 = (rating + 5) / 10 (the hundredths the statistics keep), +0xB3 =
  (rating + 500) / 1000.

`compute(read, base, player)` returns the rating and its breakdown; `players(read, base, engine)` lists the
MATCH_PLAYER objects of a GAME_MATCH. Both take any reader (live memory or a page capture).
"""
from __future__ import annotations

import hashlib
import struct

UPDATER = (0x4560B60, 0x45616AC)
UPDATER_SHA1 = '5e9b164d6d7bdd58e7208f8ce6734d85680da194'   # 0x4560B60..0x45616AC in build 27.0.0.2493426
# sha1 of the updater's bytes on every build whose updater this mirror was proven equal to, by
# emulating that build's code over the same synthetic players (tests/test_match_rating_builds.py).
# The bytes include the ADRP page offsets of the globals, so each hash matches only its own build.
# 27.0.1.2503222 (0x4589918..0x458A478): the same instructions as 27.0.0 apart from block layout
# (the spell test and keeper block moved, the multiplier selection re-laid out with the same
# outcomes) and the global page offsets; no structure offset, constant or call changed.
VERIFIED_UPDATERS = frozenset({
    UPDATER_SHA1,                                   # 27.0.0.2493426
    'c35d3ddceb6fcf51fbd95d77985d279cf8046935',     # 27.0.1.2503222
})
RATINGS_MANAGER = 0x56C35A0
RATINGS_VT = 0x56A01C8
POS_UNION_TABLE = 0x53FCBA8    # u64[51] position masks, by f + 31 (loop 2)
POS_TEST_TABLE = 0x53FCD40     # u64[51] position masks, by f + 31 (loop 3)
FULL_TIME_F = 0x53FCA6C        # float divisor of the short-time multiplier scaling
MATCH_PLAYER_VT = 0x569EE68
PLAYER_STATS_VT = 0x55FA800
GAME_MATCH_VT = 0x55FA258
FULL = 21600                   # ticks in 90 minutes
KEEPER_MASK = 0x20000000001001
TIME = 0x154DC                 # GAME_MATCH + 0x15000 + 0x4DC: match time in ticks
FLAGS = 0x154F0
MODE = 0x1555A
ELAPSED = 0x15454

# (weight offset in the row, term key, how the input is read). Inputs: ('u8', off) stats byte,
# ('sub', a, b) u8 a - u8 b, ('sum', offs...) u8 sum, ('pl32', off) MATCH_PLAYER i32, ...
TERMS = (
    (0x10, 'assists', ('u8', 0x9F)),
    (0x14, 'shots', ('u8', 0x90)),
    (0x16, 'shots_on_target', ('u8', 0x91)),
    (0x1A, 'stat_8d_less_8e', ('sub', 0x8D, 0x8E)),
    (0x1C, 'open_play_key_passes', ('u8', 0xBD)),
    (0x1E, 'passes_completed', ('sum16', 0xE8, 0xEA)),
    (0x20, 'passes_not_completed', ('diff16', 0xE4, 0xE6, 0xE8, 0xEA)),
    (0x22, 'dribbles_made', ('u8', 0xA1)),
    (0x24, 'fouls_against', ('u8', 0xA4)),
    (0x26, 'open_play_crosses_completed', ('sum', 0xE1, 0xE2)),
    (0x28, 'open_play_crosses_not_completed', ('cross_fail',)),
    (0x2A, 'chances_created', ('u8', 0xA0)),
    (0x2C, 'stat_28_float_x100', ('f100', 0x28)),
    (0x2E, 'tackles_completed', ('u8', 0xC7)),
    (0x30, 'tackles_not_completed', ('sub', 0xC6, 0xC7)),
    (0x32, 'interceptions', ('u8', 0xCF)),
    (0x34, 'fouls_made', ('u8', 0xA3)),
    (0x36, 'shots_blocked_defending', ('u8', 0x9C)),
    (0x38, 'clearances', ('u8', 0xD9)),
    (0x3A, 'goal_mistakes', ('u8', 0xD0)),
    (0x3C, 'possession_won', ('u8', 0xD7)),
    (0x3E, 'headers_won', ('u8', 0xCB)),
    (0x40, 'headers_lost', ('sub', 0xCA, 0xCB)),
    (0x44, 'stat_8f', ('u8', 0x8F)),
    (0x46, 'total_saves', ('sum8', 0x99, 0x9A, 0x9B)),
    (0x48, 'player_1c48', ('pl32', 0x1C48)),
    (0x4A, 'player_1bbc', ('pl32', 0x1BBC)),
    (0x4C, 'stat_9e', ('u8', 0x9E)),
    (0x4E, 'stat_9d_less_9e', ('sub', 0x9D, 0x9E)),
    (0x56, 'red_card', ('u8', 0xA7)),
    (0x64, 'team_goals_on_pitch', ('u8', 0xD1)),
    (0x66, 'team_conceded_on_pitch', ('u8', 0xD2)),
)
EXTRA_TERMS = (   # added only when GAME_MATCH +0x1555A == 4 or a side +0x739 is positive (0x4560FCC)
    (0x58, 'player_1aed', ('pli8', 0x1AED)), (0x5A, 'player_1aef', ('pli8', 0x1AEF)),
    (0x5C, 'player_1aee', ('pli8', 0x1AEE)), (0x5E, 'player_1e4a', ('plu8', 0x1E4A)),
    (0x60, 'player_1e4b', ('plu8', 0x1E4B)), (0x62, 'player_1e4c', ('plu8', 0x1E4C)),
)
# term key -> (label, where the name comes from). 'game:' names are the game's own: the FourCC property
# key MATCH player statistics get_property 0x20493C sets right after loading that offset (labels from the
# UI registry), or the analytics string 0x2F0F828 writes next to it. 'inferred:' names are ours, with the
# evidence; 'unlabelled' terms carry their offset only.
LABELS = {
    'assists': ('Assists', 'game: key 0x4F614173 after +0x9F (0x204E28); analytics "assists" (0x2F10E34)'),
    'assists_beyond_first': ('Assists (each after the first)', 'game: +0x9F; row +0x12 applies when two or more'),
    'goals_below_xg': ('Goals below expected goals (x100, only when negative)',
                       'game: Goals +0x8B (key 0x6F76476F, analytics "goals_scored") less expected goals +0x1C'),
    'shots': ('Shot attempts', 'game: key ShotAttempts / TotalShots after +0x90'),
    'shots_on_target': ('Shots on target', 'game: analytics "shots_on_target" after +0x91'),
    'stat_8d_less_8e': (None, 'unlabelled: stats +0x8D less +0x8E (zero in both captures)'),
    'open_play_key_passes': ('Open play key passes', 'game: key 0x47767A57 after +0xBD'),
    'passes_completed': ('Passes completed', 'inferred: u16 +0xE8 + +0xEA equals PassCompleted (+0xBB) for every '
                                             'outfield player in both captures'),
    'passes_not_completed': ('Passes not completed', 'inferred: (+0xE4 + +0xE6) equals PassAttempts (+0xBA); '
                                                     'less the completed'),
    'dribbles_made': ('Dribbles made', 'game: key 0x4D417476 after +0xA1'),
    'fouls_against': ('Fouls against', 'game: key 0x2C716872 after +0xA4'),
    'open_play_crosses_completed': ('Open play crosses completed', 'game: key 0x58465367 after +0xE1/+0xE2'),
    'open_play_crosses_not_completed': ('Open play crosses not completed',
                                        'game: OpenPlayCrossesAttempted (+0xDF + +0xE0) less completed'),
    'chances_created': ('Chances created', 'game: key 0x30485A6F after +0xA0'),
    'stat_28_float_x100': (None, 'unlabelled: stats float +0x28 x 100'),
    'tackles_completed': ('Tackles completed', 'game: key 0x41796E32 after +0xC7'),
    'tackles_not_completed': ('Tackles not completed', 'game: TackleAttempts (+0xC6) less TackleCompleted'),
    'interceptions': ('Interceptions', 'game: key 0x65627130 after +0xCF'),
    'fouls_made': ('Fouls made', 'game: key 0x3747760C after +0xA3'),
    'shots_blocked_defending': ('Shots blocked (defending)', 'game: key 0x20565375 after +0x9C'),
    'clearances': ('Clearances', 'game: key 0x7A434632 after +0xD9'),
    'goal_mistakes': ('Mistakes leading to goals', 'game: key GoalMistakes 0x51666261 after +0xD0'),
    'possession_won': ('Possession won', 'game: key 0x42744244 after +0xD7'),
    'headers_won': ('Headers won', 'game: HeaderCompleted / AerialDuelsCompleted after +0xCB'),
    'headers_lost': ('Headers lost', 'game: HeaderAttempts (+0xCA) less HeaderCompleted'),
    'stat_8f': (None, 'unlabelled: stats +0x8F (zero in both captures)'),
    'total_saves': ('Total saves', 'game: key TotalSaves 0x45553965 over +0x99..+0x9B'),
    'player_1c48': (None, 'unlabelled: MATCH_PLAYER i32 +0x1C48 (zero in both captures)'),
    'player_1bbc': (None, 'unlabelled: MATCH_PLAYER i32 +0x1BBC (zero in both captures)'),
    'stat_9e': (None, 'unlabelled: stats +0x9E (zero in both captures)'),
    'stat_9d_less_9e': (None, 'unlabelled: stats +0x9D less +0x9E (zero in both captures)'),
    'yellow_card': ('Yellow card (one)', 'game: YellowCardedInMatch +0xA6 = 1'),
    'second_yellow': ('Yellow cards (two)', 'game: YellowCardedInMatch +0xA6 = 2'),
    'red_card': ('Red card', 'game: analytics "red_cards_recieved" after +0xA7'),
    'team_goals_on_pitch': ('Team goals while on the pitch', 'inferred: stats +0xD1 equals the goals the side '
                                                            'scored while the player was on (52 of 52 in the captures)'),
    'team_conceded_on_pitch': ('Goals conceded while on the pitch', 'inferred: stats +0xD2, as +0xD1 for the opponents'),
    'time_on_pitch': ('Time in position', 'formula: weight row +0x00 x minutes in the position / 90'),
    'no_goal_conceded_flag': ('No goal conceded (match flag set)',
                              'formula: row +0x42 x minutes / 90 when GAME_MATCH +0x154F0 bit 2 and +0xD2 is 0'),
    'keeper_shots_faced': ('Goalkeeper: fewer than 5 shots faced on target',
                           'formula: row +0x50 x (5 - saves - conceded) x minutes / 90, keeper positions'),
    'goal_item': ('Goal', 'formula: MATCH_PLAYER +0x1AA8 item in this position, row +0x02 (inferred: the goals)'),
    'goal_item_flagged': ('Goal (item flag +0x0E set)', 'formula: row +0x18 instead of +0x02 (meaning inferred)'),
    'goal_item_kind_1': ('Goal kind 1', 'formula: item +0x0C = 1, row +0x04 (kind not labelled)'),
    'goal_item_kind_2': ('Goal kind 2', 'formula: item +0x0C = 2, row +0x06 (kind not labelled)'),
    'goal_item_later': ('Goal after the first', 'formula: items after the first, row +0x0C'),
    'goal_item_decisive': ('Latest goal levels or leads by one',
                           'formula: item +0x0D equals the total goals and the margin is 0 or 1, row +0x08'),
    'goal_item_decisive_recent': ('Latest goal levels or leads by one, scored in the last 10 minutes',
                                  'formula: as above within 2,400 ticks, row +0x0A'),
}
for _off, _key, _how in EXTRA_TERMS:
    LABELS[_key] = (None, f'unlabelled: MATCH_PLAYER +{_how[1]:#x}, only in mode 4 or with a side +0x739 set')


def _f32(x):
    return struct.unpack('<f', struct.pack('<f', x))[0]


def _i32(x):
    x &= 0xFFFFFFFF
    return x - (1 << 32) if x & 0x80000000 else x


def _fcvtzs(x):
    if x != x:
        return 0
    v = int(x)          # truncation toward zero
    return max(-(1 << 31), min((1 << 31) - 1, v))


def _round_half_away(x):
    """fcmp x, 0; fcsel +-0.5; fadd; fcvtzs (float32)."""
    return _fcvtzs(_f32(x + (0.5 if x >= 0 else -0.5)))


def _div21600(x):
    """smull by 0xC22E4507, add, asr 14, add sign bit: signed division by 21600, truncating."""
    x = _i32(x)
    q = abs(x) // FULL
    return -q if x < 0 else q


class _R:
    def __init__(self, read):
        self.read = read

    def u64(self, a):
        return struct.unpack('<Q', self.read(a, 8))[0]

    def u32(self, a):
        return struct.unpack('<I', self.read(a, 4))[0]

    def i32(self, a):
        return struct.unpack('<i', self.read(a, 4))[0]

    def u16(self, a):
        return struct.unpack('<H', self.read(a, 2))[0]

    def i16(self, a):
        return struct.unpack('<h', self.read(a, 2))[0]

    def u8(self, a):
        return self.read(a, 1)[0]

    def i8(self, a):
        return struct.unpack('<b', self.read(a, 1))[0]

    def f32(self, a):
        return struct.unpack('<f', self.read(a, 4))[0]


def pin(read, base):
    """sha1 of the updater's bytes in the running image (compared against UPDATER_SHA1 when set)."""
    return hashlib.sha1(read(base + UPDATER[0], UPDATER[1] - UPDATER[0])).hexdigest()


def model_entry(r, base, match):
    """(entry address or 0, base rating) as 0x4560B7C..0x4560BB4 and 0x45615E0 choose them."""
    mgr = r.u64(base + RATINGS_MANAGER)
    if not mgr or r.u64(mgr) != base + RATINGS_VT:
        raise ValueError('MATCH_PLAYER_RATINGS_MANAGER not resident or not the expected class')
    build = r.u32(match + 0xA2C)
    start, end = r.u64(mgr + 8), r.u64(mgr + 0x10)
    entry = 0
    for e in range(start, end, 0x90):
        if r.u32(e + 0x8C) <= build:
            entry = e
            break
    if entry and r.i32(entry + 0x88) != -1:
        return entry, r.i32(entry + 0x88)
    return entry, _i32(r.i32(match + 0xA74) * 10)


def _row_index(r, entry, key):
    """std::map<u64, i32> lookup at entry +0x18 (end node +0x20): lower bound, then key equality."""
    end = entry + 0x20
    node, best = r.u64(end), end
    while node:
        if r.u64(node + 0x20) < key:
            node = r.u64(node + 8)
        else:
            best, node = node, r.u64(node)
    if best == end or r.u64(best + 0x20) > key:
        return None
    return r.i32(best + 0x28)


def _position_code(code):
    v = (code << 3) & 0xFFFF
    v = v - 0x10000 if v & 0x8000 else v
    return v >> 9          # signed 7-bit field of code bits 6..12


def _counted(code):
    """Loop 1 (0x4560BEC..0x45610A4): does this spell count toward the total time T?"""
    if code & 0x2000:
        return False
    f = _position_code(code)
    if f < 0:
        k = f + 31
        return 0 <= k <= 0x1C and bool((1 << k) & 0x16B7EFFF)
    return f <= 0x13 and bool((1 << f) & 0xFEDED)


def _mask(r, base, table, code):
    k = _position_code(code) + 31
    return r.u64(base + table + 8 * k) if 0 <= k <= 0x32 else 0


def _input(r, st, pl, how):
    kind = how[0]
    if kind == 'u8':
        return r.u8(st + how[1])
    if kind == 'sub':
        return r.u8(st + how[1]) - r.u8(st + how[2])
    if kind == 'sum':
        return sum(r.u8(st + o) for o in how[1:])
    if kind == 'sum8':
        return sum(r.u8(st + o) for o in how[1:]) & 0xFF
    if kind == 'sum16':
        return (r.u16(st + how[1]) + r.u16(st + how[2])) & 0xFFFF
    if kind == 'diff16':
        return ((r.u16(st + how[1]) + r.u16(st + how[2])) & 0xFFFF) - ((r.u16(st + how[3]) + r.u16(st + how[4])) & 0xFFFF)
    if kind == 'cross_fail':
        return r.u8(st + 0xE0) - (r.u8(st + 0xE1) + r.u8(st + 0xE2)) + r.u8(st + 0xDF)
    if kind == 'f100':
        return _fcvtzs(_f32(r.f32(st + how[1]) * 100.0))
    if kind == 'pl32':
        return r.i32(pl + how[1])
    if kind == 'pli8':
        return r.i8(pl + how[1])
    if kind == 'plu8':
        return r.u8(pl + how[1])
    raise ValueError(kind)


def _multiplier_offsets(k, gf, ga):
    """(offset used when acc >= 0, offset used when acc < 0) into the entry (0x45612C4..0x4561570)."""
    diff = gf - ga
    if k == 0:
        if diff > 0:
            return 0x40, 0x44
        return (0x58, 0x5C) if gf == ga else (0x70, 0x74)
    if k > 0:
        if diff >= 1:
            if diff == k:
                return 0x58, 0x5C
            return (0x80, 0x84) if (diff & 0xFFFFFFFF) < (k & 0xFFFFFFFF) else (0x50, 0x54)
        if gf != ga:
            return (0x70, 0x74) if k == 1 else (0x60, 0x64)
        return (0x78, 0x7C) if k == 1 else (0x68, 0x6C)
    if diff < 0:
        if diff == k:
            return 0x58, 0x5C
        return (0x50, 0x54) if (diff & 0xFFFFFFFF) > (k & 0xFFFFFFFF) else (0x80, 0x84)
    if k == -1:
        if gf != ga:
            return 0x40, 0x44
        return 0x48, 0x4C
    if gf == ga:
        return 0x38, 0x3C
    return 0x30, 0x34


def compute(read, base, pl, *, check_class=True):
    """Rating of one MATCH_PLAYER by the updater's formula, with the breakdown.

    Returns dict: rating (x1000), stored (MATCH_PLAYER +0x1D58), rating_2 / stored_2 (+0x1D64), base,
    multiplier, acc (the integer sum before the multiplier), total_time (ticks), positions
    [{bit, time, row}], terms {key: {'input', 'raw', 'contribution'}} (raw: before the multiplier;
    contribution: after it, float), rounding (rating - base - sum of contributions), clamped."""
    r = _R(read)
    if check_class and r.u64(pl) != base + MATCH_PLAYER_VT:
        raise ValueError(f'{pl:#x} is not a simatch::MATCH_PLAYER')
    match = r.u64(pl + 0x280)
    entry, base_rating = model_entry(r, base, match)
    spells = []
    s, e = r.u64(pl + 0x1AC0), r.u64(pl + 0x1AC8)
    if s and e > s and (e - s) % 40 == 0 and e - s <= 40 * 512:
        for a in range(s, e, 40):
            spells.append((r.u16(a), r.u32(a + 0x20)))
    total = 0
    for code, t in spells:
        if _counted(code):
            total = _i32(total + t)
    st = r.u64(pl + 0x1880)
    if not st:
        # the updater dereferences +0x1880 unconditionally (0x456129C..0x45612B4): it is not run for
        # a player without a statistics object, whose rating word stays at its initial value
        raise ValueError('MATCH_PLAYER has no GAME_MATCH_PLAYER_STATS (+0x1880 is null): not rated')
    if check_class and r.u64(st) != base + PLAYER_STATS_VT:
        raise ValueError('MATCH_PLAYER +0x1880 is not a GAME_MATCH_PLAYER_STATS')
    terms, positions = {}, []
    acc = 0

    def add(key, inp, raw):
        t = terms.setdefault(key, {'input': 0, 'raw': 0.0})
        t['input'] = inp
        t['raw'] += raw

    if total:
        union = 0
        for code, _ in spells:
            if not code & 0x2000:
                union |= _mask(r, base, POS_UNION_TABLE, code)
        flags = r.u32(match + FLAGS)
        mode = r.u8(match + MODE)
        sides = (r.u64(pl + 0x288), r.u64(pl + 0x290))
        extra_on = mode == 4 or r.i8(sides[0] + 0x739) > 0 or r.i8(sides[1] + 0x739) >= 1
        items = []
        a, b = r.u64(pl + 0x1AA8), r.u64(pl + 0x1AB0)
        if a and b > a and (b - a) % 16 == 0 and b - a <= 16 * 256:
            items = [(r.u64(x), r.u32(x + 8), r.u8(x + 0xC), r.u8(x + 0xD), r.u8(x + 0xE)) for x in range(a, b, 16)]
        fT = _f32(float(total))
        for p in range(59):
            bit = 1 << p
            if not bit & union:
                continue
            tp = 0
            for code, t in spells:
                if not code & 0x2000 and _mask(r, base, POS_TEST_TABLE, code) & bit:
                    tp = _i32(tp + t)
            if not tp or not entry:
                continue
            idx = _row_index(r, entry, bit)
            rows = r.u64(entry)
            if idx is None or not rows:
                continue
            row_addr = rows + 0x68 * idx
            w = lambda off: r.i16(row_addr + off)
            share = _f32(_f32(float(tp)) / fT)
            parts = []                     # (key, input, weight)
            n9f = r.u8(st + 0x9F)
            parts.append(('assists', n9f, w(0x10)))
            if n9f >= 2:
                parts.append(('assists_beyond_first', n9f - 1, w(0x12)))
            for off, key, how in TERMS[1:]:
                parts.append((key, _input(r, st, pl, how), w(off)))
            g = _fcvtzs(_f32(_f32(float(r.u8(st + 0x8B)) - r.f32(st + 0x1C)) * 100.0))
            if g < 0:
                parts.append(('goals_below_xg', g, w(0x0E)))
            y = r.u8(st + 0xA6)
            if y == 1:
                parts.append(('yellow_card', 1, w(0x52)))
            if y == 2:
                parts.append(('second_yellow', 1, w(0x54)))
            if extra_on:
                for off, key, how in EXTRA_TERMS:
                    parts.append((key, _input(r, st, pl, how), w(off)))
            S = 0
            for _, inp, wt in parts:
                S = _i32(S + inp * wt)
            if S:
                acc = _i32(acc + _round_half_away(_f32(share * _f32(float(S)))))
                for key, inp, wt in parts:
                    add(key, inp, float(share) * inp * wt)
            d2 = r.u8(st + 0xD2)
            no_conceded = bool(flags & 4) and d2 == 0
            faced = (r.u8(st + 0x99) + r.u8(st + 0x9A) + r.u8(st + 0x9B)) & 0xFF
            faced += d2
            keeper = bool(bit & KEEPER_MASK) and faced < 5
            timed = [('time_on_pitch', 1, w(0x00))]
            if no_conceded:
                timed.append(('no_goal_conceded_flag', 1, w(0x42)))
            if keeper:
                timed.append(('keeper_shots_faced', 5 - faced, w(0x50)))
            for key, inp, wt in timed:
                if tp >= FULL:
                    v = inp * wt
                else:
                    v = _div21600(inp * tp * wt) if key == 'keeper_shots_faced' else _div21600(tp * wt)
                acc = _i32(acc + v)
                add(key, inp, float(v))
            for n, (ikey, itime, ikind, iscore, iflag) in enumerate(items):
                if ikey != bit:
                    continue
                if n:
                    acc = _i32(acc + w(0x0C))
                    add('goal_item_later', 1, float(w(0x0C)))
                if iflag & 1:
                    acc = _i32(acc + w(0x18))
                    add('goal_item_flagged', 1, float(w(0x18)))
                    continue
                acc = _i32(acc + w(0x02))
                add('goal_item', 1, float(w(0x02)))
                if ikind in (1, 2):
                    v = w(0x04) if ikind == 1 else w(0x06)
                    acc = _i32(acc + v)
                    add(f'goal_item_kind_{ikind}', 1, float(v))
                if flags & 4:
                    own, opp = sides[0], r.u64(sides[0] + 0x698)
                    ga_, gb_ = r.u8(own + 0x73A), r.u8(opp + 0x73A)
                    if iscore == (ga_ + gb_) & 0xFF:
                        d = ga_ - gb_
                        if r.u8(match + 0xAC2) == 2:
                            d = d + r.u8(own + 0x12A) - r.u8(opp + 0x12A)
                        if (d & 0xFF) <= 1:
                            recent = _i32(r.u32(match + TIME) - itime) < 0x961
                            v = w(0x0A) if recent else w(0x08)
                            acc = _i32(acc + v)
                            add('goal_item_decisive_recent' if recent else 'goal_item_decisive', 1, float(v))
            positions.append({'bit': p, 'time': tp, 'row': idx, 'S': S})
    # final multiplier (0x4561298..0x4561360)
    mult = 1.0
    if entry:
        team = r.u64(pl + 0x298)
        k = _fcvtzs(r.f32(team + 0x34FC))
        gf, ga = r.i8(st + 0xD1), r.i8(st + 0xD2)
        pos_off, neg_off = _multiplier_offsets(k, gf, ga)
        mult = r.f32(entry + (neg_off if acc < 0 else pos_off))
    if total <= 0x545F:
        c = r.f32(base + FULL_TIME_F)
        mult = _f32(_f32(_f32(_f32(float(total)) / c) * _f32(mult - 1.0)) + 1.0)
    delta = _round_half_away(_f32(mult * _f32(float(acc))))
    raw_rating = _i32(base_rating + delta)
    rating = min(max(raw_rating, 0), 10000)
    for t in terms.values():
        t['contribution'] = t['raw'] * mult
    rounding = (rating - base_rating) - sum(t['contribution'] for t in terms.values())
    # second word (0x456137C..0x45613F4)
    minutes = _i32(r.i32(match + ELAPSED) // 240 if r.i32(match + ELAPSED) >= 0 else -(-r.i32(match + ELAPSED) // 240))
    played = ((minutes - r.u8(st + 0xAF) + 1) & 0xFF) if st else 0
    played = played - 256 if played & 0x80 else played
    rating2 = rating
    if played >= 21:
        team = r.u64(pl + 0x298)
        d = _i32(r.i32(team + 0x34A8) - r.i32(team + 0x34AC))
        if d < 0:
            m = played if (played & 0xFFFFFFFF) < 90 else 90
            rating2 = rating - (((d * m * d) & 0xFFFFFFFF) // 60)
    rating2 = max(rating2, 0)
    return {'rating': rating, 'stored': r.i32(pl + 0x1D58), 'rating_2': rating2, 'stored_2': r.i32(pl + 0x1D64),
            'stats_hundredths': r.u16(st + 0x82) if st else None, 'base': base_rating, 'multiplier': mult,
            'acc': acc, 'total_time': total, 'positions': positions, 'terms': terms, 'rounding': rounding,
            'clamped': raw_rating != rating, 'entry': entry, 'computed_at_time': r.u32(pl + 0x1DE0),
            'match_time': r.u32(match + TIME)}


def players(read, base, engine):
    """[(side, slot, MATCH_PLAYER)] of a GAME_MATCH: engine +0x15370/+0x15378 sides, side +0x140 26 slots."""
    r = _R(read)
    if r.u64(engine) != base + GAME_MATCH_VT:
        raise ValueError('not a GAME_MATCH')
    out = []
    for side, off in enumerate((0x15370, 0x15378)):
        sp = r.u64(engine + off)
        if not sp:
            continue
        for slot, p in enumerate(struct.unpack('<26Q', read(sp + 0x140, 208))):
            if p and r.u64(p) == base + MATCH_PLAYER_VT:
                out.append((side, slot, p))
    return out


# --------------------------------------------------------------------------- loaded match
def check_pinned(read, base):
    """Raise ValueError when the updater's bytes are not those of a build this mirror was proven on."""
    if pin(read, base) not in VERIFIED_UPDATERS:
        raise ValueError(f'rating updater {UPDATER[0]:#x} changed in this build: the mirrored formula is not verified')


def breakdown(result):
    """The per-player `rating_breakdown` shape from a compute() result: ratings in match-rating units
    (x1000 / 1000), contributions sorted by size, summing with `rounding` to recomputed - base."""
    comps = []
    for key, t in result['terms'].items():
        if not t['contribution'] and not t['input']:
            continue
        label, source = LABELS.get(key, (None, 'unlabelled'))
        comps.append({'term': key, 'label': label, 'count': t['input'],
                      'contribution': round(t['contribution'] / 1000, 4), 'name_source': source})
    comps.sort(key=lambda c: -abs(c['contribution']))
    recomputed = result['rating'] / 1000
    rounding = round(recomputed - result['base'] / 1000 - sum(c['contribution'] for c in comps), 4)
    return {
        'state': 'computed',
        'rating': result['stored'] / 1000,
        'rating_hundredths': result['stats_hundredths'],
        'recomputed': recomputed,
        'stored_minus_recomputed': (result['stored'] - result['rating']) / 1000,
        'base': result['base'] / 1000,
        'multiplier': round(result['multiplier'], 6),
        'minutes_in_positions': round(result['total_time'] / 240, 2),
        'positions': [{'position_bit': p['bit'], 'minutes': round(p['time'] / 240, 2), 'weight_row': p['row']}
                      for p in result['positions']],
        'components': comps,
        'rounding': rounding,
        'clamped': result['clamped'],
        'note': ('recomputed = base + sum of contributions + rounding, by the updater 0x4560B60 mirrored '
                 '(equal to emulating it on every rated player of both captures). rating is the stored value the '
                 'match screen shows; it differs from recomputed when an input changed after the player\'s last '
                 'update (stored at MATCH_PLAYER +0x1DE0).'),
    }


def loaded_matches(read, base):
    """Every resident match the match screen can show, with its players' rating breakdowns.

    [{'client', 'engine', 'date', 'competition_index', 'sides': [{'team', 'goals'}], 'match_minutes',
      'players': [{'side', 'slot', 'person', 'team', 'breakdown' or 'unavailable'}]}]. person and team are
    native pointers (PERSON subobject = MATCH_PLAYER +0x20, team = side +0xB8). Raises ValueError with the
    reason when no match is loaded or the updater changed."""
    from .sources.match_state import screen_stats_source, _packed
    check_pinned(read, base)
    r = _R(read)
    out = []
    for index, client, engine, stats in screen_stats_source(read, base):
        fixture = r.u64(stats + 0x18)
        day_year = r.u32(fixture + 0x4C) if fixture else 0
        name = r.u64(fixture + 0x20) if fixture else 0
        comp = r.u64(name + 0x18) if name else 0
        sides = []
        for off in (0x15370, 0x15378):
            sp = r.u64(engine + off)
            sides.append({'side_object': sp, 'team': r.u64(sp + 0xB8) if sp else 0,
                          'goals': r.u8(sp + 0x73A) if sp else None})
        rows = []
        for side, slot, pl in players(read, base, engine):
            row = {'side': side, 'slot': slot, 'person': r.u64(pl + 0x20), 'team': sides[side]['team']}
            try:
                row['breakdown'] = breakdown(compute(read, base, pl))
            except ValueError as exc:
                row['unavailable'] = str(exc)
            rows.append(row)
        out.append({'client': index, 'engine': engine, 'date': _packed(day_year),
                    'competition_index': r.u32(comp + 8) if comp else None, 'sides': sides,
                    'match_minutes': round(r.i32(engine + ELAPSED) / 240, 2), 'players': rows})
    return out
