"""Editor record types -> live tables, record classes and property getters (FM27 2493426).

Built on `database.TABLES` (the 24 `db::DATABASE_TABLE<T>` singletons; each entry
is a record pointer and record+8 == index). Every record class is identified by
its vtable RTTI and answers properties through vtable slot 3; `survey()` checks the
live classes and getters against `CLASSES` below (a census of every table taken on
2026-11-11; PERSON fully, other tables up to ~3,000 spread entries).

PERSON family. The `people` table holds pointers to the embedded PERSON subobject,
not to the most-derived object. The subobject's vtable is a secondary vtable of the
derived class, so its RTTI names the derived class, and its slot 3 is a thunk that
adjusts `this` to the primary before running the class getter (e.g. 0xD47498 for
ACTUAL_PLAYER moves to person-0x388 and calls 0xD3E6F0; player properties it does
not handle fall to the base PLAYER getter 0x1503624). The VM therefore always calls
the getter through the table pointer and never adjusts `this` itself. Primary
offsets, where the repo has proven them: ACTUAL_PLAYER 0x388, ACTUAL_PLAYER_AND_NON_PLAYER
0x480, ACTUAL_NON_PLAYER 0x208, HUMAN_NON_PLAYER 0x548, VIRTUAL_PLAYER 0x20.

Editor record types without a live table are listed in `NO_TABLE` with the reason.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

from .. import database, players

# vtable RVA of the record (or PERSON subobject) -> (RTTI class, getter RVA, primary offset)
CLASSES = {
    0x55B5B30: ('MEDIA_SOURCE', 0x1394488, 0), 0x55BA7B8: ('REGION', 0x15AE49C, 0),
    0x559B4A0: ('AWARD', 0xD82D7C, 0), 0x55BABD0: ('REMOVED_RECORD', 0x11B23E8, 0),
    0x55A40E0: ('DERBY', 0x11DB38C, 0), 0x559AF90: ('AGREEMENT', 0xD7398C, 0),
    0x559C558: ('CITY', 0xDD548C, 0),
    0x558A780: ('ACTUAL_PLAYER', 0xD47498, 0x388),
    0x55849D8: ('ACTUAL_NON_PLAYER', 0xC9EC0C, 0x208),
    0x55BAD40: ('RETIRED_PERSON_NAME_STRINGS', 0x15C43A8, None),
    0x55BB4A0: ('RETIRED_PERSON_NAME_POINTERS', 0x15C4EE4, None),
    0x55CB9F8: ('VIRTUAL_PLAYER', 0x18A83C8, 0x20),
    0x55C1558: ('SUPPORT_STAFF', 0xCEE9A8, None),
    0x55908E0: ('ACTUAL_PLAYER_AND_NON_PLAYER', 0xD65230, 0x480),
    0x55B7248: ('OFFICIAL', 0x146F8D4, None), 0x55B3798: ('JOURNALIST', 0x136321C, None),
    0x5599538: ('AGENT', 0xD69BC0, None), 0x55AD820: ('HUMAN_NON_PLAYER', 0x12E6554, 0x548),
    0x559CF48: ('CLUB', 0xE476C4, 0), 0x55B5288: ('LEAGUE_BODY_CLUB', 0xE476C4, 0),
    0x55B5E98: ('NATIONAL_TEAM_CONTAINER', 0x13EC530, 0),
    0x55C2E40: ('TEAM', 0x177580C, 0), 0x55B5D50: ('NATIONAL_TEAM', 0x13D746C, 0),
    0x559ED88: ('COMP', 0xEFD3B8, 0), 0x55A06B0: ('CONTINENT', 0xFE05C0, 0),
    0x55BA468: ('PLAYER_TYPE', 0x15590E8, 0), 0x55B5C40: ('NATION', 0x13B1D14, 0),
    0x55BD7B0: ('STADIUM', 0x16C8BC8, 0), 0x55BD8C0: ('STADIUM_CHANGE', 0x16D5C84, 0),
    0x55A1188: ('CURRENCY_RECORD', 0x1010480, 0), 0x55B2820: ('INJURY', 0x1329D64, 0),
    0x55B5080: ('LANGUAGE', 0x1369C14, 0), 0x55B5718: ('LOCAL_REGION', 0x137A600, 0),
    0x55CC3A0: ('WEATHER', 0x18B2768, 0), 0x55AB970: ('FIXTURE_NAME', 0x11B23E8, 0),
    0x55BD9E8: ('STAGE_NAME', 0x16E2D4C, 0),
}

PLAYERS = ('ACTUAL_PLAYER', 'ACTUAL_PLAYER_AND_NON_PLAYER', 'VIRTUAL_PLAYER')
NON_PLAYERS = ('ACTUAL_NON_PLAYER', 'ACTUAL_PLAYER_AND_NON_PLAYER', 'HUMAN_NON_PLAYER', 'SUPPORT_STAFF')


@dataclass(frozen=True)
class Spec:
    table: str
    classes: tuple = ()        # restrict to these RTTI classes (empty = every class in the table)
    note: str = ''


RECORD_TYPES = {
    'pers': Spec('people', note='every PERSON class'),
    'play': Spec('people', PLAYERS),
    'nnpl': Spec('people', NON_PLAYERS),
    'offc': Spec('people', ('OFFICIAL',)),
    'jour': Spec('people', ('JOURNALIST',)),
    'agen': Spec('people', ('AGENT',)),
    'CntF': Spec('people', ('ACTUAL_PLAYER', 'ACTUAL_NON_PLAYER'),
                 note='contract fields asked of the PERSON getter (contracts have no table)'),
    'club': Spec('clubs'),
    'c2tm': Spec('clubs', ('CLUB',), note="club's 2nd team fields, asked of the CLUB getter"),
    'c3tm': Spec('clubs', ('CLUB',), note="club's 3rd team fields, asked of the CLUB getter"),
    'c4tm': Spec('clubs', ('CLUB',), note="club's 4th team fields, asked of the CLUB getter"),
    'natc': Spec('national_team_containers'),
    'nati': Spec('nations'),
    'team': Spec('teams'),
    'comp': Spec('competitions'),
    'cont': Spec('continents'),
    'city': Spec('cities'),
    'curr': Spec('currencies'),
    'stad': Spec('stadiums'),
    'lang': Spec('languages'),
    'lcrg': Spec('local_regions'),
    'weat': Spec('weather'),
    'inju': Spec('injuries'),
    'awar': Spec('awards'),
    'mdso': Spec('media_sources'),
    'regi': Spec('regions'),
    'drbr': Spec('derbies'),
    'agrm': Spec('agreements'),
    'stgn': Spec('stage_names'),
    'dscr': Spec('player_types', note="'Descriptions' (PTna) are PLAYER_TYPE records"),
}

NO_TABLE = {
    'prnm': 'person-name records (first/common/second names) live in name tables that are not '
            'among the 24 DATABASE_TABLE singletons',
    'ktfl': 'kits are embedded lists of club/team records, not table records',
    'alnm': 'alternative names are embedded lists, not table records',
    'dbch': 'editor database-change log; no live table',
    'lsts': 'editor list-of-tables view; no live table',
    'fmat': 'editor file format metadata; no live table',
}

# Table FourCCs seen in record references (variant.RecordRef.table) -> live table.
REF_TABLES = {
    'Nnat': 'nations', 'lang': 'languages', 'lcrg': 'local_regions', 'wthr': 'weather',
}


def u64(read, address):
    return struct.unpack('<Q', read(address, 8))[0]


def entries(read, base, kind):
    """All record pointers of a table (bulk 16 KiB reads of the pointer vector)."""
    info = database.table(read, base, kind)
    n, out = info['count'], []
    for off in range(0, n * 8, 16384):
        chunk = read(info['start'] + off, min(16384, n * 8 - off))
        out += struct.unpack(f'<{len(chunk) // 8}Q', chunk)
    return out


def class_of(read, base, record):
    vtable = u64(read, record) - base
    entry = CLASSES.get(vtable)
    return (entry[0] if entry else f'vtable@{vtable:#x}'), vtable


def classify(read, base, pointers):
    """{pointer: class name} for every non-null table entry (one 8-byte read each)."""
    return {p: class_of(read, base, p)[0] for p in pointers if p}


def sample(read, base, rtype, count, *, pointers=None, classes=None):
    """Up to `count` records of an editor record type, spread evenly across the table.

    With class restrictions, records are spread across the table per class and taken
    round-robin across the wanted classes (`classes` may supply a `classify` result)."""
    spec = RECORD_TYPES[rtype]
    pointers = pointers if pointers is not None else entries(read, base, spec.table)
    if not spec.classes:
        step = max(1, len(pointers) // count)
        return [p for p in pointers[::step] if p][:count]
    classes = classes if classes is not None else classify(read, base, pointers)
    per_class, out = {}, []
    for name in spec.classes:
        members = [p for p in pointers if p and classes.get(p) == name]
        step = max(1, len(members) // count)
        per_class[name] = members[::step][:count]
    while len(out) < count and any(per_class.values()):
        for name in spec.classes:
            if per_class.get(name):
                out.append(per_class[name].pop(0))
                if len(out) == count:
                    break
    return out


def survey(read, base, kind, limit=3000):
    """Live classes of a table: {RTTI: {'vtable', 'getter', 'count', 'known'}} (getter checked)."""
    pointers = entries(read, base, kind)
    step = max(1, len(pointers) // limit)
    out = {}
    for p in pointers[::step]:
        if not p:
            continue
        name, vtable = class_of(read, base, p)
        row = out.setdefault(name, {'vtable': vtable, 'count': 0})
        row['count'] += 1
    for name, row in out.items():
        getter = u64(read, base + row['vtable'] + 0x18) - base
        known = CLASSES.get(row['vtable'])
        row['getter'] = getter
        row['known'] = bool(known and known[1] == getter)
    return out


_UID_INDEX = {}


def unique_id_index(read, base, kind):
    """{unique id: (index, address)} for one table; cached per (base, kind, table identity)."""
    info = database.table(read, base, kind)
    key = (base, kind, info['identity'])
    if key not in _UID_INDEX:
        index = {}
        for i, p in enumerate(entries(read, base, kind)):
            if p:
                uid = struct.unpack('<I', read(p + 0xC, 4))[0]
                index.setdefault(uid, (i, p))
        _UID_INDEX[key] = index
    return _UID_INDEX[key]


def resolve(read, base, ref):
    """Table kind, index and address for a RecordRef whose table FourCC is mapped."""
    kind = REF_TABLES.get(ref.table)
    if kind is None:
        return None
    hit = unique_id_index(read, base, kind).get(ref.unique_id)
    if hit is None:
        return {'table': kind, 'index': None, 'address': None}
    return {'table': kind, 'index': hit[0], 'address': hit[1]}


def managed(read, base):
    """Managed clubs and their first-team players (PERSON pointers) from the loaded career."""
    from .. import world
    record, _ = world.loaded(world.ReadSet(read), base)
    clubs, people = [], []
    for coach in record['coaches']:
        team = coach['team_address']
        clubs.append(u64(read, team + 0x30))
        begin, end = struct.unpack('<QQ', read(team + 0x38, 16))
        for slot in range(begin, min(end, begin + 8 * 200), 8):
            primary = u64(read, slot)
            if not primary:
                continue
            vtable = u64(read, primary) - base
            if vtable == players.RVA[0]:
                people.append(primary + 0x388)
            elif vtable == players.STAFF_RVA[0]:
                people.append(primary + 0x480)
    return clubs, people
