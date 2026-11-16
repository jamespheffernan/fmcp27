"""Per-person and per-club histories, read on demand through the game's own code.

Routes (build 27.0.0.2493426; see docs/fmdb/HISTORIES.md):

* Starting playing history `Plhs` and non-playing history `Pnph`: the person record's property
  getter (vtable slot 3), emulated in the reader's FastVM. The getter pages the list in from
  `Temporary/pl_hist_dt.cmt` / `non_pl_hist_dt.cmt` through `FILE_LLIST::get_list` (0x14A0FB0)
  on the owner thread (vm.py OWNER_THREAD retry).
* Career spells (every club and job, including the seasons played in this career), career
  totals, milestone counts and injury history: PERSON_UI_HANDLER (factory type 28, record
  `{'dref': 1 << 24 | person idx}`) in the UI VM, through the data-key protocol
  (ui_recipes_person.DataReader). The server pages `person_record_history_dt.cmt`,
  `injury_histories_dt.cmt`, `pl_hist_dt.cmt` and `player_stats_hist_dt.cmt` read-only.
* Club league history: CLUB_UI_HANDLER `LgHs` (record `{'dref': 3 << 24 | club idx}`), which
  reads `Temporary/tc_league_history_dt.cmt`.

Nothing is read save-wide: every function takes the people or clubs to read.
"""
from __future__ import annotations

import time

from .vm import Unavailable

# UI object ids: table type << 24 | table index (packer 0x11B8B0C)
UI_PERSON, UI_CLUB, UI_TEAM, UI_COMPETITION, UI_INJURY = 1, 3, 0x18, 0x19, 6
NO_DATE = '1900-01-01'

PERSON_KEYS = {
    # career spells (StaffHistory: player and staff jobs, start and end dates)
    'spells': 'erHw',
    # injury history: server list (structured) and the client's formatted rows (labelled)
    'injuries': 'b1SW', 'injury_count': 'G3nh',
    # career totals
    'total_apps': 'GNGR', 'total_goals': 'Ny6I', 'league_apps': 'h4UR', 'league_goals': 'DGAq',
    'club_apps': '0F6G', 'club_goals': 'y1oK', 'club_league_apps': 'XA61', 'club_league_goals': 'Dmwv',
    'league_apps_in_nation': 'ZpBW', 'milestones': 'lcn9',
    # HonoursCount 'uu70' is not read: its getter draws 10 random numbers (11 Nov 2026 save)
    # the game's own visibility flags for the history panels
    'can_view_career_stats': '2KD9', 'can_view_season_stats': 'Ogrh', 'can_view_staff_history': 'Cq7d',
}
PERSON_DATA_KEYS = {'injuries_raw': 'Phis'}
CLUB_KEYS = {'league_history': 'LgHs'}


def ui_id(table_type: int, index: int) -> int:
    return table_type << 24 | index


def ui_index(value, table_type):
    """Table index of a UI object reference ({'dref': id} / int), or None."""
    if isinstance(value, dict):
        value = value.get('dref')
    if not isinstance(value, int) or value >> 24 != table_type:
        return None
    return value & 0xFFFFFF


def iso(value):
    """ISO date of a getter or UI date, None for the game's 'no date' (1900-01-01) and unset."""
    if isinstance(value, dict):
        value = value.get('date')
    iso_text = getattr(value, 'iso', value)
    if not isinstance(iso_text, str) or not iso_text[:4].isdigit() or iso_text.startswith(NO_DATE):
        return None
    return iso_text[:10]


def plain(value):
    """SQL scalar: Unavailable/None -> None, bool -> int, str/int/float as is."""
    if isinstance(value, Unavailable) or value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        return value
    return None


# --------------------------------------------------------------------------- record getters
def getter_lists(engine, records, codes):
    """{record: {code: list or Unavailable}} through the record getter (engine.get_property)."""
    out = {}
    for record in records:
        row = {}
        for code in codes:
            try:
                result = engine.get_property(record, code)
                value = result.value
            except Exception as exc:  # noqa: BLE001 - one record never stops the table
                value = Unavailable(f'{type(exc).__name__}: {exc}')
            if value is None:
                value = []                      # the getter answers no list for this record type
            row[code] = value
        out[record] = row
    return out


# --------------------------------------------------------------------------- UI handlers
class UiReader:
    """One UI VM for a batch of reads (fresh memory: built per refresh, closed after)."""

    def __init__(self, engine):
        from .memory import LiveMemory
        from .ui_vm import UiHandlerVM, lsof_resolver
        self.memory = LiveMemory(engine.pid)
        self.vm = UiHandlerVM(self.memory, engine.base, engine.image,
                              file_resolver=lsof_resolver(engine.pid), rng='copy')
        self.vm.fast()
        self.base = engine.base
        self.seconds = 0.0
        self.handlers = 0

    def close(self):
        try:
            self.memory.close()
        except Exception:  # noqa: BLE001
            pass

    def read(self, ui_object: int, keys: dict, data_keys: dict | None = None) -> dict:
        """{name: value} of a DATABASE_RECORD handler (type 28) for one object; Unavailable on
        failure. '_rng' {name: random draws} for the values whose read drew (data values are computed
        once per handler, so a draw is charged to the first value that needed it)."""
        from . import ui_recipes_person as P
        started, rng = time.perf_counter(), self.vm.rng_uses
        out = {}
        try:
            handler = self.vm.build(P.DATABASE_RECORD, {'dref': ui_object})
        except Exception as exc:  # noqa: BLE001
            reason = Unavailable(f'handler not built: {type(exc).__name__}: {exc}')
            return {name: reason for name in list(keys) + list(data_keys or {})} | {'_rng': {}}
        reader = P.DataReader(self.vm, handler)
        draws = {}
        for name, code in keys.items():
            before = self.vm.rng_uses
            try:
                reading = reader.get(code)
                value = reading.value
                out[name] = value if isinstance(value, Unavailable) else P._value(reading)
            except Exception as exc:  # noqa: BLE001
                out[name] = Unavailable(f'{type(exc).__name__}: {exc}')
            draws[name] = self.vm.rng_uses - before
        for name, code in (data_keys or {}).items():
            before = self.vm.rng_uses
            try:
                kind, value = reader.data_value(code)
                if not isinstance(value, Unavailable):
                    from . import variant
                    from .ui_handlers import plain_text
                    value = plain_text(variant.to_json(value))
                out[name] = value
            except Exception as exc:  # noqa: BLE001
                out[name] = Unavailable(f'{type(exc).__name__}: {exc}')
            draws[name] = self.vm.rng_uses - before
        out['_rng'] = {n: d for n, d in draws.items() if d}
        out['_client'] = handler.client_class
        self.seconds += time.perf_counter() - started
        self.handlers += 1
        return out


# --------------------------------------------------------------------------- row shaping
def playing_history_rows(person, items, team_of, comp_of):
    rows = []
    for n, it in enumerate(items if isinstance(items, list) else []):
        if not isinstance(it, dict):
            continue
        rows.append((person, n, plain(it.get('year')), plain(it.get('yror')), team_of(it.get('clid')),
                     comp_of(it.get('divi')), iso(it.get('join')), iso(it.get('leav')), plain(it.get('onln')),
                     plain(it.get('ytht')), plain(it.get('apps')), plain(it.get('gols')), plain(it.get('cash')),
                     plain(it.get('trib')), plain(it.get('hsfl'))))
    return rows


def non_playing_history_rows(person, items, team_of):
    rows = []
    for n, it in enumerate(items if isinstance(items, list) else []):
        if not isinstance(it, dict):
            continue
        rows.append((person, n, team_of(it.get('team')), iso(it.get('join')), iso(it.get('left')),
                     plain(it.get('tjob'))))
    return rows


def spell_rows(person, items):
    rows = []
    for n, it in enumerate(items if isinstance(items, list) else []):
        if not isinstance(it, dict):
            continue
        job = it.get('b9r7') if isinstance(it.get('b9r7'), dict) else {}
        rows.append((person, n, ui_index(it.get('Team'), UI_TEAM), iso(it.get('PcSd')), iso(it.get('Pced')),
                     plain(job.get('QKws')), plain(job.get('17 !')), plain(it.get('Yfxf'))))
    return rows


def injury_rows(person, shown, raw):
    """Client rows (labelled) paired with the server's list by position; the date must agree."""
    rows = []
    shown = shown if isinstance(shown, list) else []
    raw = raw if isinstance(raw, list) else []
    for n, it in enumerate(shown):
        if not isinstance(it, dict):
            continue
        r = raw[n] if n < len(raw) and isinstance(raw[n], dict) else {}
        date = iso(it.get('inDa'))
        injury = ui_index(r.get('injr'), UI_INJURY) if iso(r.get('iida')) == date else None
        rows.append((person, n, date, injury, plain(it.get('inDe')), plain(it.get('inDu')), plain(it.get('zslN')),
                     plain(it.get('inrh')), plain(it.get('inCa')), plain(it.get('inTr')),
                     plain(r.get('iRec')) if injury is not None else None,
                     plain(r.get('iCur')) if injury is not None else None))
    return rows


def totals_row(person, got):
    ms = got.get('milestones') if isinstance(got.get('milestones'), dict) else {}
    return (person, 0, plain(got.get('total_apps')), plain(got.get('total_goals')), plain(got.get('league_apps')),
            plain(got.get('league_goals')), plain(got.get('club_apps')), plain(got.get('club_goals')),
            plain(got.get('club_league_apps')), plain(got.get('club_league_goals')),
            plain(got.get('league_apps_in_nation')), plain(got.get('injury_count')),
            plain(ms.get('nopw')), plain(ms.get('nopx')), plain(ms.get('nopy')), plain(ms.get('nopz')),
            plain(ms.get('nop{')), plain(ms.get('WnbG')), plain(ms.get('nop|')),
            plain(got.get('can_view_career_stats')), plain(got.get('can_view_season_stats')),
            plain(got.get('can_view_staff_history')))


def league_history_rows(club, value):
    rows = []
    groups = value if isinstance(value, list) else []
    n = 0
    for g, group in enumerate(groups):
        for it in (group if isinstance(group, list) else [group]):
            if not isinstance(it, dict):
                continue
            rows.append((club, n, g, plain(it.get('year')), plain(it.get('wtom')),
                         ui_index(it.get('comp'), UI_COMPETITION), plain(it.get('5ot ')), plain(it.get('lYlr')),
                         plain(it.get('ODJi')), plain(it.get('ntms')), plain(it.get('Q0uf')), plain(it.get('fate')),
                         plain(it.get('dEkT'))))
            n += 1
    return rows


COMPETITION_KEYS = {'history': 'hist'}       # COMPETITION_UI_HANDLER History (server data chst)
AWARD_KEYS = {'past_winners': 'I20k'}         # AWARD_UI_HANDLER PastWinners (server data AwHi, AwSd)
UI_AWARD = 0                                  # award records: UI object table type 0 (factory -> AWARD_UI_HANDLER)


def competition_history_rows(comp, value):
    """History rows (Year, MissingHistoryString, FirstPlaced ...) of one competition, newest first as the game
    lists them. StageName (`stgn`) is empty on every row of the 13 league and cup competitions checked
    (13 Dec 2030), so it is not kept."""
    rows = []
    for n, it in enumerate(value if isinstance(value, list) else []):
        if not isinstance(it, dict):
            continue
        rows.append((comp, n, plain(it.get('year')), plain(it.get('mshs')) or None,
                     ui_index(it.get('1pla'), UI_TEAM), ui_index(it.get('2pla'), UI_TEAM), ui_index(it.get('3pla'), UI_TEAM),
                     ui_index(it.get('9H95'), UI_TEAM), ui_index(it.get('pown'), UI_TEAM),
                     plain(it.get('HstN')) or None, plain(it.get('HstS')) or None))
    return rows


def award_history_rows(award, value):
    """One row per season and placed winner (Winners list; WinnerDefault when the list is empty)."""
    rows = []
    n = 0
    for s, season in enumerate(value if isinstance(value, list) else []):
        if not isinstance(season, dict):
            continue
        placed = season.get('qRMU') if isinstance(season.get('qRMU'), list) else []
        if not placed and isinstance(season.get('fIoV'), dict):
            placed = [season['fIoV']]
        for place, it in enumerate(placed):
            if not isinstance(it, dict):
                continue
            stat = it.get('stvl') if isinstance(it.get('stvl'), dict) else {}
            rows.append((award, n, s, plain(season.get('Strn')), plain(season.get('5nfy')), place,
                         ui_index(it.get('pers'), UI_PERSON), ui_index(it.get('Team'), UI_TEAM),
                         plain(stat.get('ptvl')), plain(stat.get('qvJ6')), plain(it.get('15  ')),
                         plain(it.get('ovAp')), plain(it.get('ovGo')), plain(it.get('OaAs')), plain(it.get('ovAR')),
                         plain(it.get('Wzbz')), plain(it.get('k2rI')), plain(it.get('ToaF')), plain(it.get('zuSC')),
                         plain(it.get('5Niy')), plain(it.get('3lvn'))))
            n += 1
    return rows


# Club transfer history. CLUB data key `Cpts` (server 0x1FAF8A8 > 0x2E22F78) builds its parameter
# bag from a copy of the global bag at 0x56D38C0 (the front end's selection on the club's transfer
# history screen) plus dref/type/Ttea; 0x2E22F78 reads 'year' (default 1900: nothing selected, every
# list empty) and 'mont'. The global holds no selection in the live game, so the VM's private copy of
# that global gets {'year': y} for each season the server reports (styr..edyr).
TRANSFER_SELECTION = 0x56D38C0
BAG_INSERT = 0x43F72E4
CLUB_TRANSFER_KEYS = {'in': 'PTin', 'out': 'PTou'}
CLUB_TRANSFER_AMOUNTS = {'in': 'ptia', 'out': 'ptoa'}


def _selection_bag(vm, base, values: dict):
    """A property bag of int32 typed values on the VM heap, made by the game's own constructors."""
    from . import ui_recipes_person as P
    from .ui_vm import fourcc
    bag = vm.heap_bytes(b'\0' * 64)
    vm.commit()
    for key, number in values.items():
        typed = vm.heap_bytes(b'\0' * 16)
        vm.commit()
        vm.call(base + P.INT32_VARIANT_RVA, [typed, number & 0xFFFFFFFF])
        vm.commit()
        vm.call(base + BAG_INSERT, [bag, fourcc(key), typed])
        vm.commit()
    return bag


def club_transfers(reader: 'UiReader', club: int):
    """[(year, direction, [row dicts], amount)] for every season of one club's transfer history,
    or Unavailable. Reads CLUB_UI_HANDLER PTin/PTou/ptia/ptoa once per season. A club is answered
    whole or not at all: one season the game does not answer makes the club Unavailable with that
    season's reason (a history with a season missing would read as complete)."""
    from . import ui_recipes_person as P
    from .vm import _Stop
    vm = reader.vm
    started = time.perf_counter()
    try:
        handler = vm.build(P.DATABASE_RECORD, {'dref': ui_id(UI_CLUB, club)})
        built = vm._baseline
        kind, summary = P.DataReader(vm, handler).data_value('Cpts')
        if isinstance(summary, Unavailable):
            return summary
        from . import variant
        summary = variant.to_json(summary)
        first, last = summary.get('styr'), summary.get('edyr')
        if not (isinstance(first, int) and isinstance(last, int) and 1900 < first <= last < first + 200):
            return Unavailable(f'the game reports no transfer history seasons for this club ({first!r}..{last!r})')
        out = []
        for year in range(last, first - 1, -1):
            vm._baseline = built
            vm._restore()
            bag = _selection_bag(vm, reader.base, {'year': year})
            vm.uc.mem_write(reader.base + TRANSFER_SELECTION, vm.read(bag, 24))
            vm.commit()
            data = P.DataReader(vm, handler)
            for direction, key in CLUB_TRANSFER_KEYS.items():
                rows = data.get(key)
                amount = data.get(CLUB_TRANSFER_AMOUNTS[direction])
                if isinstance(rows.value, Unavailable):
                    return Unavailable(f'{key} {year}: {rows.value.reason}')
                value = P._value(rows)
                out.append((year, direction, value if isinstance(value, list) else [],
                            None if isinstance(amount.value, Unavailable) else P._value(amount)))
        return out
    except _Stop as stop:
        return Unavailable(f'club transfer history: {stop.reason}', detail=stop.detail)
    finally:
        reader.seconds += time.perf_counter() - started
        reader.handlers += 1


def moved_under_the_read(unavailable) -> bool:
    """A stop that the game changing under the read produces: a pointer from a page copied earlier
    than its neighbours (vm.STALE_SYMPTOMS) or a game file whose stream moved during the read."""
    from .ui_vm import FILE_MOVED
    from .vm import STALE_SYMPTOMS
    return any(symptom in unavailable.reason for symptom in (*STALE_SYMPTOMS, FILE_MOVED))


def club_transfer_rows(club, seasons):
    rows = []
    n = 0
    for year, direction, items, amount in seasons:
        for it in items:
            if not isinstance(it, dict):
                continue
            rows.append((club, n, year, direction, ui_index(it.get('pers'), UI_PERSON), plain(it.get('220 ')) or None,
                         ui_index(it.get('TObt'), UI_TEAM), ui_index(it.get('TOst'), UI_TEAM),
                         plain(it.get('slts')) or None, plain(amount)))
            n += 1
    return rows


def unavailable_reasons(values: dict) -> list[str]:
    return sorted({v.reason for v in values.values() if isinstance(v, Unavailable)})

