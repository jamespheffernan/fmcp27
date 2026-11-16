"""Editor fields decided by a targeted full scan instead of a 25-record sample.

`scripts/fmdb_editor_scan.py` asks every record of a type (managed club and squad first) for each
editor field the ledger did not count as read, through the real getter path (`Engine.get_property`:
record getter, then the game layer), and stops a field once it has given a few values. The merged
result is `data/editor_live.json.gz`; `decide(key)` turns one row of it into a ledger status:

``reads``          some record of this save gives a value (examples name the record index and unique id)
``empty_in_save``  every record of the type was asked and none gives a value: the field is reachable and
                   this save holds no data for it, which is a different statement from "not reached"
``unavailable``    the getter fails on most records asked (the reason is kept)
``unreached``      every record was asked and none claims the key (unhandled null from getter and game layer)
None               the scan did not ask every record (budget) and found nothing: the sample status stands

A list-item field (``club.Cstc.Styp``) reads when an item of the parent list carries it on some record,
and is empty in this save when the parent list was asked of every record and no item carries it.
"""
from __future__ import annotations

from functools import lru_cache
import gzip
import json
from pathlib import Path
import time

FORMAT = 'fmdb-editor-live/1'
DATA = Path(__file__).with_name('data') / 'editor_live.json.gz'

# --------------------------------------------------------------------------- editor types that are not records
# `recs`: one row per database table type ("a record of table X"; the ledger key is the same for all 21, the
# row name tells them apart). `lsts`: the editor's list of each table. Both are the live DATABASE_TABLE
# singletons (`database.TABLES`, `tables.entries`).
RECS_TABLES = {
    'Agreement': 'agreements', 'City': 'cities', 'Club': 'clubs', 'Competition': 'competitions',
    'Continent': 'continents', 'Currency': 'currencies', 'Derby Name': 'derbies', 'Description': 'player_types',
    'Injury': 'injuries', 'Language': 'languages', 'Media Source': 'media_sources', 'Nation': 'nations',
    'National Team': 'national_team_containers', 'Person': 'people', 'Stadium': 'stadiums',
    'Local Region': 'local_regions', 'Region': 'regions', 'Stage Name': 'stage_names', 'Weather': 'weather',
    'Award': 'awards', 'Team': 'teams',
}
LSTS_TABLES = {
    'agls': 'agreements', 'awls': 'awards', 'clls': 'clubs', 'cyls': 'cities', 'cmls': 'competitions',
    'cnls': 'continents', 'crls': 'currencies', 'drls': 'derbies', 'dsls': 'player_types', 'inls': 'injuries',
    'lnls': 'languages', 'lrls': 'local_regions', 'msls': 'media_sources', 'ntls': 'nations',
    'tcls': 'national_team_containers', 'prls': 'people', 'stls': 'stadiums', 'snls': 'stage_names',
    'wels': 'weather',
}
# `ktfl` (kit) records are the items of the colours/kits lists Tko1..Tkg3 of clubs and national teams (the
# CLUB getter returns them as records keyed by the ktfl field codes; c2tm/c3tm/c4tm have their own lists).
KIT_LISTS = {'club': ('Tko1', 'Tkg1', 'Tko2', 'Tkg2', 'Tko3', 'Tkg3'),
             'natc': ('Tko1', 'Tkg1', 'Tko2', 'Tkg2', 'Tko3', 'Tkg3')}
KIT_CODES = ('ktpr', 'kite', 'kits', 'bost', 'ksfg', 'ksbg', 'ksou', 'nmcl', 'nmoc', 'comp', 'year', 'ktal')
# Stadium stand flags Sh**: no getter or setter handles them (the only site of each FourCC is the STADIUM
# property-name list, vtable slot 5 0x16C7B4C). The stadium's sides are the Ssds list, whose item `indx` enum is
# Top, Top Right, Right, Bottom Right, Bottom, Bottom Left, Left, Top Left: the same order and names as the
# eight flags. Has <side> Stand = Ssds item with that indx, field `exis`. The mapping is inferred from the
# names and the order (the code that would connect them is not in the plugin).
STAND_KEYS = {'Shts': 0, 'Shtr': 1, 'Shrs': 2, 'Shbr': 3, 'Shbs': 4, 'Shbl': 5, 'Shls': 6, 'Shtl': 7}
EMBEDDED_NOTE = {
    'recs': 'record of the live DATABASE_TABLE {table} (tables.entries; every fmdb table row is one)',
    'lsts': 'the live DATABASE_TABLE {table}, enumerated by tables.entries',
    'ktfl': 'kit records are the items of the colours/kits lists (club.Tko1..Tkg3, natc.Tko1..Tkg3; snapshot '
            'club.colours_kits)',
    'stad': 'derived (inferred mapping): Ssds item with indx {side} (side enum order equals the flag order), '
            'field exis; snapshot stadium.stadium_sides',
}


# --------------------------------------------------------------------------- nation transfer windows
# nati.cwsd/cwed/nwsd/nwed (current/next transfer window start/end) are answered by no record getter. The
# in-game editor's getter 0x6710F0 (class EDITOR) answers them: arguments (x0, x1 unused on this path,
# x2 record, w3 key, x4 out value, stack flag = 1); the record must report type 9 (NATIONAL_TEAM_CONTAINER,
# vtable slot 8) or 3, so the editor asks them of the nation's national team container (natc NTCn == the
# nation), and computes the windows from the game date and the nation's competitions (0x429B288). A nation
# has a men's and a women's container (natc PLgn 0 / 1); the nation's fields are taken from the men's one.
EDITOR_GETTER = 0x6710F0
WINDOW_KEYS = ('cwsd', 'cwed', 'nwsd', 'nwed')
WINDOW_BUDGET = 80_000_000          # the men's containers of big nations run 5 to 25 M instructions
_NATC_OF_NATION: dict = {}


def _natc_of_nation(vm, nation: int) -> int | None:
    import struct
    from . import tables
    key = vm.base
    index = _NATC_OF_NATION.get(key)
    if index is None:
        index = {}
        for p in tables.entries(vm.read, vm.base, 'national_team_containers'):
            if not p:
                continue
            ref = vm.get_property(p, 'NTCn').value
            gender = vm.get_property(p, 'PLgn').value
            uid = getattr(ref, 'unique_id', None) if not isinstance(ref, dict) else ref.get('unique_id')
            if uid is not None:
                index.setdefault(uid, []).append((0 if gender in (0, None) else 1, p))
        _NATC_OF_NATION.clear()
        _NATC_OF_NATION[key] = index
    uid = struct.unpack('<I', vm.read(nation + 0xC, 4))[0]
    found = sorted(index.get(uid, ()))
    return found[0][1] if found else None


def nation_transfer_window(vm, nation: int, key: str):
    """(kind, value) of one nation transfer-window key, by emulating the EDITOR getter on the nation's men's
    national team container. Raises extras._Stop through vm.call on emulator refusals."""
    import struct
    from . import tables, variant
    from ._editor_fields import fourcc
    if tables.class_of(vm.read, vm.base, nation)[0] != 'NATION':
        from .extras import _Stop
        raise _Stop('not a nation record')
    natc = _natc_of_nation(vm, nation)
    if natc is None:
        return 'null', None
    from .vm import STACK, STACK_SIZE
    if type(vm).__name__ == 'FastVM':
        from .fastvm import SP_START as sp
    else:
        sp = STACK + STACK_SIZE - 0x1000       # PropertyVM.call's stack pointer
    out = STACK + 0x100
    budget, timeout = vm.budget, vm.timeout_us
    scale = max(1, WINDOW_BUDGET // max(1, budget))
    st = getattr(vm, '_st', None)                   # FastVM keeps its timeout in C state ticks
    ticks = st.timeout_ticks if st is not None else None
    vm.budget, vm.timeout_us = budget * scale, timeout * scale
    if st is not None:
        st.timeout_ticks = ticks * scale
    try:
        vm._restore()
        vm._poke(out, struct.pack('<QQ', vm.registry + 8, 0) + b'\0' * 16)
        vm._poke(sp, struct.pack('<Q', 1))          # the getter's stack flag: answer, do not only test
        vm.call(vm.base + EDITOR_GETTER, (0, 0, natc, fourcc(key), out))
        return variant.decode(vm, out)
    finally:
        vm.budget, vm.timeout_us = budget, timeout
        if st is not None:
            st.timeout_ticks = ticks


def surfaces_for(rtype: str, code: str) -> list[str]:
    """Where a reader asks for the value of a field this module decided as readable."""
    if rtype in ('recs', 'lsts'):
        return ['fm_db_query', 'fm_db_schema']
    if rtype == 'ktfl':
        return ['snapshot:club.colours_kits', 'fm_db_read']
    if rtype == 'stad' and code in STAND_KEYS:
        return ['snapshot:stadium.stadium_sides', 'fm_db_read']
    return ['fm_db_read']


# Editor schema types that are controls of the editor UI, not stored values.
CONTROL_TYPES = ('button', 'widget', 'colours_example')
# Club columns that answer a team field routed `via_club` (fieldroutes.ROUTES), by the club's live key.
VIA_CLUB_COLUMNS = {'Ctfc': 'snapshot:club.transfer_budget', 'Cwrb': 'snapshot:club.remaining_player_wage_budget'}


def embedded_key(key: str, name: str | None) -> str:
    return f'{key}#{name}' if key == 'recs.database_record' and name else key


def merge(directory: Path, out: Path = DATA) -> Path:
    """Merge the per-type scan files of `directory` into the shipped data file (newer files win)."""
    doc = {'format': FORMAT, 'merged_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'types': {}, 'pairs': {}}
    if out.exists():
        with gzip.open(out, 'rt') as fh:
            old = json.load(fh)
        doc['types'].update(old.get('types', {}))
        doc['pairs'].update(old.get('pairs', {}))
    # embedded.json last: its derived stand-flag rows replace the plain getter rows of the same keys
    for path in sorted(Path(directory).glob('*.json'), key=lambda p: (p.stem == 'embedded', p.name)):
        res = json.loads(path.read_text())
        rtype = path.stem
        doc['types'][rtype] = {k: res.get(k) for k in ('records', 'scanned', 'complete', 'cpu_s', 'wall_s', 'load',
                                                       'build', 'game_date', 'scanned_at')}
        doc['pairs'].update(res['pairs'])
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, 'wt') as fh:
        json.dump(doc, fh, sort_keys=True, separators=(',', ':'))
    load.cache_clear()
    return out


@lru_cache(maxsize=2)
def load(path: Path = DATA) -> dict:
    try:
        with gzip.open(path, 'rt') as fh:
            return json.load(fh)
    except OSError:
        return {'types': {}, 'pairs': {}}


def pairs() -> dict:
    return load().get('pairs', {})


def _unavailable(counts: dict) -> dict:
    return {k[len('unavailable:'):]: v for k, v in counts.items() if k.startswith('unavailable:')}


def decide(key: str, doc: dict | None = None) -> tuple[str, str] | None:
    """(status, reason) for one ledger key ('club.CBWo' or 'club.Cstc.Styp'), or None when the scan
    has nothing to add."""
    row = (doc or load()).get('pairs', {}).get(key)
    if not row and key.count('.') >= 3:
        # a field of an item of a list item: empty when the enclosing item field is empty in this save
        parent = '.'.join(key.split('.')[:3])
        up = decide(parent, doc)
        if up and up[0] == 'empty_in_save':
            return 'empty_in_save', f'enclosing list field {parent} is empty in this save ({up[1][:120]})'
        return None
    if not row:
        return None
    counts = row.get('counts') or {}
    asked, total = row.get('asked', 0), row.get('of', 0)
    rtype, code = key.split('.')[0], key.split('.')[-1].split('#')[0]
    if rtype in ('recs', 'lsts', 'ktfl') or (rtype == 'stad' and code in STAND_KEYS):
        note = EMBEDDED_NOTE[rtype].format(table=row.get('table'), side=STAND_KEYS.get(code))
        if not counts.get('value'):
            if rtype == 'ktfl' and counts.get('unset'):
                return 'unreached', (f"{note}: none of {counts['unset']:,} kit items carries it; the field is the "
                                     f"editor's kit preview widget (type colours_example), not stored data")
            return None
        ex = (row.get('examples') or [{}])[0]
        extra = f"; e.g. record index {ex.get('index')} (unique id {ex.get('unique_id')}) {ex.get('value', '')}"[:120] \
            if ex else ''
        return 'reads', f"{note}: {counts['value']:,} {'records' if rtype == 'recs' else 'values'}{extra}"
    is_item = key.count('.') == 2
    if counts.get('value'):
        ex = (row.get('examples') or [{}])[0]
        where = f"record index {ex.get('index')} (unique id {ex.get('unique_id')})"
        val = str(ex.get('value', ''))[:60]
        n = f"{counts['value']}+" if not row.get('complete') else str(counts['value'])
        what = 'list items' if is_item else 'records'
        return 'reads', (f'full scan: value on {n} {what} after asking {asked:,} of {total:,} records; '
                         f'e.g. {where} = {val}')
    if is_item:
        parent = row.get('parent_counts') or {}
        lists = row.get('lists', 0)
        bad = _unavailable(parent)
        if bad and sum(bad.values()) >= asked * 0.5:
            top = max(bad, key=bad.get)
            return 'unavailable', f'parent list getter fails on {sum(bad.values())} of {asked} records ({top})'
        if row.get('complete'):
            return 'empty_in_save', (f'full scan: parent list asked of all {total:,} records, {lists:,} non-empty, '
                                     f'no item carries the field')
        return None
    bad = _unavailable(counts)
    if bad and sum(bad.values()) >= asked * 0.5:
        top = max(bad, key=bad.get)
        return 'unavailable', f'full scan: getter fails on {sum(bad.values())} of {asked} records ({top})'
    if row.get('complete'):
        nh = counts.get('nh', 0)
        if nh == asked:
            return 'unreached', (f'full scan: no record of {total:,} claims the key (getter and game layer '
                                 f'return an unhandled null on every one)')
        return 'empty_in_save', (f'full scan: asked of all {total:,} records, unset on '
                                 f'{counts.get("unset", 0):,}, not claimed on {nh:,}, no value')
    return None


def summary(doc: dict | None = None) -> dict:
    doc = doc or load()
    out = {}
    for key in doc.get('pairs', {}):
        d = decide(key, doc)
        s = d[0] if d else 'undecided'
        out[s] = out.get(s, 0) + 1
    return out
