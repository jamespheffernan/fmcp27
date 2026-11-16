"""Per-competition player season statistics read through the game's own getter.

Every runtime competition (COMP record +0xB0) owns a GAME_COMP_STATS object (+0x390). Its
vector at +0x1278 lists the PERSON_COMP_STATS rows (stride 0xAC: u32 person index, u32 last
team index, counters). The game answers each statistic with

    float 0xF314B4(GAME_COMP_STATS *stats, PERSON_COMP_STATS *row, int stat, 0)

(a switch over stat codes 1..157) and names each code with 0xF47A8C(stat, &string, 0), the
function the competition statistics screens use (via 0x39DAED4). Both are emulated here in
the PropertyVM against live memory; the labels come from the game's language data.

Two kinds of column:
* counters: the getter returns one stored field unchanged. Each has a direct read plan
  (type, offset) that is checked against the emulated getter on sample rows every build
  (`verify_plans`); a disagreement drops the plan and the column is emulated instead.
* derived values (rates, percentages, average rating, starting appearances): always emulated.
"""
from __future__ import annotations

import hashlib
import random
import struct
import time

from .. import database, players, world

GETTER = 0xF314B4
LABEL = 0xF47A8C
COMP_RUNTIME = 0xB0
RUNTIME_STATS = 0x390
RUNTIME_SEASON = 0x3B0
ROWS_VECTOR = 0x1278
ROW_BYTES = 0xAC
STATS_CLASS = 'GAME_COMP_STATS'

# Direct plans found by matching the emulated getter on 500 random rows of 54,312 (2026-11-11);
# the counters at even offsets 60..134 are 16-bit (code 127 reads 312 on one row).
# code: (struct format, offset)
DIRECT = {
    1: ('B', 10), 2: ('B', 12), 3: ('B', 13), 4: ('B', 151), 5: ('B', 154), 6: ('b', 155),
    7: ('B', 156), 8: ('B', 157), 9: ('B', 158), 10: ('B', 159), 11: ('B', 160), 12: ('B', 161),
    20: ('B', 163), 21: ('h', 76), 23: ('h', 88), 24: ('h', 90), 25: ('h', 92), 26: ('h', 94),
    29: ('h', 96), 46: ('h', 66), 47: ('h', 68), 48: ('h', 98), 49: ('h', 100), 50: ('h', 102),
    51: ('h', 104), 52: ('h', 106), 53: ('h', 110), 54: ('h', 112), 56: ('h', 52), 57: ('B', 153),
    59: ('B', 152), 62: ('h', 64), 63: ('h', 62), 64: ('h', 114), 65: ('h', 116), 66: ('h', 120),
    67: ('h', 118), 68: ('f', 24), 69: ('f', 28), 70: ('h', 122), 79: ('h', 56), 82: ('h', 78),
    84: ('h', 70), 85: ('h', 72), 89: ('h', 60), 101: ('h', 58), 102: ('h', 80), 109: ('f', 36),
    111: ('f', 32), 126: ('h', 126), 127: ('h', 128), 128: ('h', 130), 129: ('h', 132),
    131: ('h', 134), 138: ('h', 108),
}
# Codes the getter answers that are computed from the counters (always emulated).
DERIVED = (13, 14, 15, 16, 17, 18, 19, 22, 27, 30, 35, 45, 55, 71, 72, 73, 74, 75, 76, 77, 78,
           80, 81, 83, 86, 87, 88, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 103, 104, 105,
           106, 107, 108, 110, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124,
           125, 130, 132, 133, 134, 135, 136, 137, 139, 140, 141)
# Derived codes kept in the main table because they are what the screens lead with.
CORE_DERIVED = (27, 45)
# Codes the getter labels but that read zero on every sampled row (career totals, mistakes).
ZERO = (28, 60, 61)
# Codes whose 0 means "no value": average rating (27). The getter returns 0 for 24,015 of
# 54,515 rows (every one with appearances, in all 127 competitions; 12 Dec 2030), through the
# same path as a rated row (it reads the row's team and minutes and the competition's rating
# data, the same number of words either way), so 0 is the game's own answer, not a failed
# read; a match rating is never 0. Rated and unrated rows overlap in minutes (Premier League:
# rated from 252 minutes, unrated up to 370), so the rule is the game's, not a minutes threshold.
NO_VALUE_ZERO = frozenset({27})
# Duplicate-label codes the getter answers identically to a counter: 40 ('Goals') = 2,
# 58 ('Penalties saved') = 57. Kept out of the column list.
ALIASES = {40: 2, 58: 57}


def labels(engine):
    """{code: label} from the game's stat-name function (None when the game has no name)."""
    from .variant import read_string
    vm = engine.vm
    out = {}
    for code in range(1, 158):
        slot = vm.alloc(16)
        vm.call(engine.base + LABEL, [code, slot, 0])
        pointer = struct.unpack('<Q', vm.read(slot, 8))[0]
        out[code] = read_string(vm, pointer) if pointer else None
    return out


def snake(label):
    text = ''.join(ch.lower() if ch.isalnum() else '_' for ch in label.replace('%', 'pct').replace('/', ' per '))
    while '__' in text:
        text = text.replace('__', '_')
    return text.strip('_')


def column_names(label_map):
    """[(code, column name, label)] in code order for every labelled code we expose."""
    seen, out = set(), []
    for code in sorted(set(DIRECT) | set(DERIVED) | set(ZERO)):
        label = label_map.get(code)
        if not label:
            continue
        name = snake(label)
        if name in seen:
            name = f'{name}_{code}'
        seen.add(name)
        out.append((code, name, label))
    return out


def stats_objects(engine):
    """[(competition index, stats address, season code)] for every distinct GAME_COMP_STATS."""
    read, base = engine.read, engine.base
    info = database.table(world.ReadSet(read), base, 'competitions')
    count = info['count']
    pointers = struct.unpack(f'<{count}Q', read(info['start'], count * 8))
    out, seen = [], set()
    for index, address in enumerate(pointers):
        if not address:
            continue
        runtime = players.u64(read(address + COMP_RUNTIME, 8))
        if not runtime:
            continue
        stats = players.u64(read(runtime + RUNTIME_STATS, 8))
        if not stats or stats in seen:
            continue
        # A runtime shared by several COMP records belongs to its owner (runtime +0x138).
        owner = players.u64(read(runtime + 0x138, 8))
        if owner and owner != address:
            index = int.from_bytes(read(owner + 8, 4), 'little')
            if index >= count or pointers[index] != owner:
                raise ValueError('Runtime competition owner membership changed')
        if engine.class_name(world.pointer(read, stats) - base) != STATS_CLASS:
            raise ValueError('Competition statistics class changed')
        seen.add(stats)
        season = int.from_bytes(read(runtime + RUNTIME_SEASON, 2), 'little')
        out.append((index, stats, season))
    return out


def rows(engine, objects):
    """[(competition index, season, stats, row address, raw 172 bytes)]."""
    read = engine.read
    out = []
    for comp, stats, season in objects:
        start, end, _cap = struct.unpack('<QQQ', read(stats + ROWS_VECTOR, 24))
        n = (end - start) // 8
        if n <= 0:
            continue
        addresses = struct.unpack(f'<{n}Q', read(start, n * 8))
        for address, raw in zip(addresses, engine.read_many([(a, ROW_BYTES) for a in addresses])):
            out.append((comp, season, stats, address, raw))
    return out


def emulate(engine, stats, row, code):
    from .vm import _bits_s
    engine.vm.call(engine.base + GETTER, [stats, row, code, 0])
    return _bits_s(engine.vm, 0)


def _f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def direct_value(raw, code):
    fmt, offset = DIRECT[code]
    return struct.unpack_from('<' + fmt, raw, offset)[0]


def verify_plans(engine, all_rows, sample=96, seed=11):
    """Codes whose direct plan agrees with the emulated getter on every sampled row.

    The sample mixes random rows with, per planned field, the rows holding the largest and the
    smallest planned value and the largest next byte (so a narrow or wide read of a field shows)."""
    rng = random.Random(seed)
    picks = rng.sample(all_rows, min(sample, len(all_rows)))
    for code, (fmt, offset) in DIRECT.items():
        if fmt == 'f':
            continue
        picks.append(max(all_rows, key=lambda r: direct_value(r[4], code)))
        picks.append(min(all_rows, key=lambda r: direct_value(r[4], code)))
        width = struct.calcsize(fmt)
        if offset + width < ROW_BYTES:
            picks.append(max(all_rows, key=lambda r: r[4][offset + width]))
    good, bad = set(DIRECT), {}
    for comp, season, stats, address, raw in picks:
        for code in list(good):
            got = emulate(engine, stats, address, code)
            if _f32(float(direct_value(raw, code))) != got:
                good.discard(code)
                bad[code] = (address, direct_value(raw, code), got)
    return good, bad


def row_digest(raw) -> str:
    """Content check of one PERSON_COMP_STATS row (its 172 stored bytes)."""
    return hashlib.blake2b(raw, digest_size=8).hexdigest()


def row_key(comp, season, raw):
    person, team = struct.unpack_from('<II', raw)
    return comp, season, person, None if team == 0xFFFFFFFF else team


def split_columns(columns):
    core = [c for c in columns if c[0] in DIRECT or c[0] in CORE_DERIVED or c[0] in ZERO]
    rates = [c for c in columns if c[0] not in DIRECT and c[0] not in CORE_DERIVED and c[0] not in ZERO]
    return core, rates


def collect(engine, *, include_rates=False, include_core=True, log=None, want=None, all_rows=None,
            label_map=None):
    """{'columns': [(code, name, label)], 'rate_columns': [...], 'rows': [dict], 'stats': {...}}.

    `want(competition_idx, season, person_idx, row_digest)` selects the rows to compute (None:
    every row); `all_rows` reuses a `rows()` read. Direct plans are checked against the emulated
    getter on a sample of the rows computed (`verify_plans`)."""
    log = log or (lambda m: None)
    started = time.time()
    label_map = label_map or labels(engine)
    columns = column_names(label_map)
    objects = None
    if all_rows is None:
        objects = stats_objects(engine)
        all_rows = rows(engine, objects)
    picked = []
    for item in all_rows:
        comp, season, _, _, raw = item
        digest = row_digest(raw)
        if want is None or want(comp, season, struct.unpack_from('<I', raw)[0], digest):
            picked.append((item, digest))
    core, rates = split_columns(columns)
    good, bad = (verify_plans(engine, [p for p, _ in picked]) if include_core and picked else (set(DIRECT), {}))
    out = []
    emulated = 0
    for (comp, season, stats, address, raw), digest in picked:
        _, _, person, team = row_key(comp, season, raw)
        row = {'competition_idx': comp, 'season': season, 'person_idx': person, 'team_idx': team,
               'row_digest': digest}
        if include_core:
            for code, name, _ in core:
                if code in good:
                    row[name] = direct_value(raw, code)
                else:
                    row[name] = emulate(engine, stats, address, code)
                    emulated += 1
                if code in NO_VALUE_ZERO and row[name] == 0:
                    row[name] = None
        if include_rates:
            for code, name, _ in rates:
                row[name] = emulate(engine, stats, address, code)
                emulated += 1
        out.append(row)
    log(f'competition player stats: {len(out)} of {len(all_rows)} rows, '
        f'{emulated} emulated getter calls, {time.time() - started:.1f}s')
    return {'columns': core, 'rate_columns': rates, 'rows': out,
            'stats': {'competitions': len(objects) if objects is not None else None, 'rows': len(out),
                      'rows_read': len(all_rows), 'plans_verified': len(good),
                      'plans_dropped': {c: list(map(str, v)) for c, v in bad.items()},
                      'emulated_calls': emulated, 'seconds': round(time.time() - started, 1)}}
