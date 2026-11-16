"""Season statistics of a player for every season of his career, per competition scope, through
the game's own code (build 27.0.0.2493426; findings in docs/fmdb/HISTORIES.md).

Route, all emulated in the UI VM (owner thread, read-only file model):

1. `0xF1FB44(PLAYER_STATS_MANAGER [0x56A83C8], people-table entry, out vector<ROW*>, 1, &u16, 1)`
   builds the career statistics rows the PERSON server reads at 0x1F6930C (it pages
   `Temporary/pl_hist_dt.cmt` and `player_stats_hist_dt.cmt`). One row per season and club:
   +0x00 team record, +0x10 competition record, +0x18 team unique id (0xFFFFFFFF on the
   current season's row), +0x1C fee (-1 none), +0x20 i16 season year, +0x24 byte 1 = loan, then
   six statistics blocks of 0x20 bytes at +0x28 + 0x20 * scope.
2. `0xF74E50(block, out vector<variant*>)` turns one block into the 83-entry list the PERSON server
   sends as data keys `Psfr` (scope 0) and `Psle` (scope 1) for the current season (0xD5866C:
   block = [0x56D2D08]->vfunc 0x200(person, scope), then 0xF74E50). Entries 0..12 are the block's
   bytes +0xC..+0x18, 13 and 14 its i16 at +8 and +0xA, 15..82 the stored i16 list (0xF75588).
3. `0x39AF34(out variant, &list, competition)` is the client code that turns such a list into a
   SeasonStats row (the PERSON client calls it for `Psle` and `Psfr`): the keys it emits carry
   the UI registry's labels (Appearances `ovAp`, Goals `ovGo`, AverageRating `ovAR` ...).

So every value here is computed by shipped code from the stored history; nothing is decoded by
hand. Two rules come from that code, not from guesses:

* A byte entry (0..12) equal to 0xFF is unset: 0xF75588 reads such a byte as -1. A column whose
  value reads an unset entry (`ENTRY_DEPS`, found by changing one list entry at a time and
  re-running 0x39AF34) is NULL. Seasons before this save keep only appearances and goals.
* Several keys read the same stored entry (`ENTRY_DEPS`): the goalkeeping keys share entries
  with outfield ones (PenaltiesFaced and TackleAttempts both read entry 21 ...). The game emits
  both; which one a profile shows depends on the player.
"""
from __future__ import annotations

import struct
import time

from .vm import Unavailable

STATS_MANAGER = 0x56A83C8
CAREER_ROWS = 0xF1FB44
BLOCK_LIST = 0xF74E50
VARIANT_INIT = 0x4403B80
CLIENT_ROW = 0x39AF34
ROW_BYTES = 0xE8
BLOCK0, BLOCK_SIZE, SCOPES = 0x28, 0x20, 6
BYTE_ENTRIES = 13
UNSET_BYTE = 0xFF

# Scope = block index (the PERSON server passes it to 0xD5866C; screen parameter PlayerStatsScope).
# Names are the hand-built decoder's category labels (current_player_statistics.CATEGORY_LABELS,
# same blocks under 0x56D2D08); they are not read from the game. Consistent with the data of
# 13 Dec 2030: the current season's per-competition rows (WSiZ SeasonStatsList) sum to these blocks
# exactly (1 = Premier League, 2 = FA Community Shield, 3 = UEFA Champions League + UEFA Super Cup),
# and 5 = 1 + 2 + 3 on every season checked.
SCOPE_NAMES = {0: 'Non Competitive', 1: 'League', 2: 'Cup', 3: 'Continental', 4: 'International',
               5: 'Overall (Club)'}

# (client key, column, UI registry label or None, list entries the value reads)
KEYS = [
    ('RPSj', 'starts', 'StartingAppearances', (0,)),
    ('WSx1', 'sub_appearances', 'SubAppearances', (1,)),
    ('ovAp', 'appearances', 'Appearances', (0, 1)),
    ('apfr', 'appearances_for_rating', 'AppearancesForRating', (2,)),
    ('ovGo', 'goals', 'Goals', (3,)),
    ('OaAs', 'assists', 'Assists', (4,)),
    ('x57l', 'conceded', 'Conceded', (5,)),
    ('te81', 'penalties', 'Penalties', (6,)),
    ('jLjO', 'penalties_scored', 'PenaltiesScored', (7,)),
    ('ZM4w', 'player_of_the_match', 'PlayerOfTheMatchAwards', (8,)),
    ('k2rI', 'red_cards', 'RedCards', (9,)),
    ('z5N4', 'yellow_cards', 'YellowCards', (10,)),
    ('Wzbz', 'clean_sheets', 'CleanSheets', (11,)),
    ('Fifu', 'total_rating', 'TotalRating', (13,)),
    ('ovAR', 'average_rating', 'AverageRating', (2, 13)),
    ('MzTC', 'pass_completion_percentage', 'PassCompletionPercentage', (19, 20)),
    ('fpbr', 'tackle_completion_percentage', 'TackleCompletionPercentage', (21, 22)),
    ('fQrg', 'penalties_faced', 'PenaltiesFaced', (21,)),
    ('Ayn2', 'tackles_completed', 'TackleCompleted', (22,)),
    ('dx7k', 'penalties_saved', 'PenaltiesSaved', (22,)),
    ('8Suo', 'header_completion_percentage', 'HeaderCompletionPercentage', (23, 24)),
    ('ecc3', 'saves_held', 'SavesHeld', (23,)),
    ('0jOC', 'headers_completed', 'HeaderCompleted', (24,)),
    ('Wz1X', 'saves_parried', 'SavesParried', (24,)),
    ('MAtv', 'dribbles_made', 'DribblesMade', (25,)),
    ('Ke8V', 'fouls_per_90', 'FoulsPer90', (0, 1, 26)),
    (',qhr', 'fouls_against', 'FoulsAgainst', (27,)),
    ('w2EQ', 'shots_on_target_percentage', 'ShotsOnTargetPercentage', (28, 29)),
    ('MoHh', 'saves_tipped', 'SavesTipped', (40,)),
    ('MVOW', 'expected_goals', 'ExpectedGoals', (51,)),
    ('IgSg', 'expected_assists', 'ExpectedAssists', (52,)),
    ('zCF2', 'clearances', 'Clearances', (53,)),
    ('Cqja', 'full_stats_available', 'FullStatsAvailable', ()),
    # emitted by 0x39AF34 with no label in the UI registry
    ('7Gv\x0c', 'key_3747760c', None, (26,)),
    ('-\x9ee\xb1', 'key_2d9e65b1', None, (0, 1, 27)),
    (' rgc', 'key_20726763', None, (72,)),
]
ENTRY_DEPS = {k: deps for k, _, _, deps in KEYS}


def column_specs():
    """[(column, sql type, meaning)] of the statistics columns, in KEYS order."""
    out = []
    for key, col, label, deps in KEYS:
        sql = 'REAL' if col in ('average_rating', 'fouls_per_90', 'expected_goals', 'expected_assists',
                               'key_2d9e65b1') else 'INTEGER'
        shared = [k2 for k2, c2, _, d2 in KEYS if c2 != col and set(d2) & set(deps) and len(d2) == 1 == len(deps)]
        what = label if label else f'client key {key!r} (no label in the UI registry)'
        note = f'{what}; reads stored list entries {list(deps)}'
        if shared:
            note += f' (the same stored entry as {", ".join(c for k2, c, _, d2 in KEYS if k2 in shared)})'
        out.append((col, sql, note))
    return out


def _value(key, row, entries):
    v = row.get(key)
    if any(i < BYTE_ENTRIES and entries[i] == UNSET_BYTE for i in ENTRY_DEPS[key]):
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, float) and v != v:            # NaN: no games to divide by
        return None
    return v if isinstance(v, (int, float)) else None


class SeasonReader:
    """Career statistics rows of players, read in one UI VM (history_read.UiReader.vm)."""

    def __init__(self, engine, vm):
        self.engine, self.vm = engine, vm
        from .sources import _common as C
        self.teams = C.index_of(engine, 'teams')
        self.team_uids = C.live(engine, 'teams').uid_index()
        self.comps = C.index_of(engine, 'competitions')
        self.seconds = 0.0

    def _zeroed(self, size):
        vm = self.vm
        address = vm.alloc(size)
        vm.uc.mem_write(address, b'\0' * size)
        return address

    def read(self, person_pointer):
        """[{year, team_idx, competition_idx, fee, on_loan, career_row, scope, entries, values}] or
        Unavailable. Every stop is reported, never a partial list."""
        from . import variant
        from .ui_vm import _Stop
        vm, base = self.vm, self.engine.base
        started = time.perf_counter()
        pinned = vm._baseline
        try:
            vm._restore()
            vec, flag = self._zeroed(64), self._zeroed(16)
            vm.commit()
            vm.call(base + CAREER_ROWS, [vm.read_u64(base + STATS_MANAGER), person_pointer, vec, 1, flag, 1])
            vm.commit()
            after_rows = vm._baseline
            begin, end = struct.unpack('<QQ', vm.read(vec, 16))
            if end < begin or end - begin > 8 * 4096:
                return Unavailable(f'implausible career row vector {begin:#x}..{end:#x}')
            out = []
            for n in range((end - begin) // 8):
                row = vm.read_u64(begin + 8 * n)
                raw = vm.read(row, ROW_BYTES)
                team_ptr, comp_ptr = struct.unpack_from('<Q', raw, 0)[0], struct.unpack_from('<Q', raw, 0x10)[0]
                uid, fee, year = struct.unpack_from('<Iih', raw, 0x18)
                team = self.teams.get(team_ptr)
                if team is None and uid != 0xFFFFFFFF:
                    team = self.team_uids.get(uid)
                head = {'career_row': n, 'year': year, 'team_idx': team, 'competition_idx': self.comps.get(comp_ptr),
                        'fee': None if fee < 0 else fee, 'on_loan': int(raw[0x24] == 1)}
                for scope in range(SCOPES):
                    vm._baseline = after_rows
                    vm._restore()
                    lst, value = self._zeroed(32), self._zeroed(32)
                    vm.commit()
                    vm.call(base + BLOCK_LIST, [row + BLOCK0 + BLOCK_SIZE * scope, lst])
                    vm.commit()
                    lb, le = struct.unpack('<QQ', vm.read(lst, 16))
                    entries = [struct.unpack('<i', vm.read(vm.read_u64(lb + 8 * j) + 8, 4))[0]
                               for j in range((le - lb) // 8)]
                    vm.call(base + VARIANT_INIT, [value])
                    vm.commit()
                    vm.call(base + CLIENT_ROW, [value, lst, 0])
                    decoded = variant.to_json(vm.decode(value)[1])
                    if not isinstance(decoded, dict) or len(entries) < 83:
                        return Unavailable(f'season row {n} scope {scope}: unexpected client row')
                    out.append({**head, 'scope': scope, 'entries': entries,
                                'values': {key: _value(key, decoded, entries) for key, *_ in KEYS}})
            return out
        except _Stop as stop:
            return Unavailable(f'career statistics: {stop.reason}', detail=stop.detail)
        finally:
            vm._baseline = pinned
            vm._restore()
            self.seconds += time.perf_counter() - started


def keep(row) -> bool:
    """The club-competitions total (scope 5) of every season row; other scopes when they hold games."""
    if row['scope'] == 5:
        return True
    apps = row['values'].get('ovAp')
    return isinstance(apps, int) and apps > 0


__all__ = ['KEYS', 'ENTRY_DEPS', 'SCOPE_NAMES', 'SeasonReader', 'column_specs', 'keep']
