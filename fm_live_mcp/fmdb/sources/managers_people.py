"""People-side native managers: interaction, morale, dispute, dynamics, team talk, team blend, AWOL,
progression, injury, regeneration, retirement, award, hall of fame, achievements and stats managers.

Layout and evidence: `fmdb/mgr_walk_people.py` and docs/fmdb/MANAGERS_PEOPLE.md. Every manager
object is read at its data-segment global, its vtable checked against the class's RTTI vtable and
its size taken from the allocation in the world constructor; containers are declared offsets that
are checked live (vector or map header invariants) before their elements are read.

Tables (all lazy, content-invalidated by a fingerprint of the manager objects and, for the decoded
tables, of the element bytes they read):

* people_manager            one row per manager: object, size, id, containers, element totals
* people_manager_container  one row per declared container: kind, status, count, element classes
* people_manager_element    one row per element of every pointer vector: class or database record
* interaction_item          INTERACTION_MANAGER +0xF8 items (refcounted; the person-screen promise
                            and happiness getters read them through 0xCDB374 / 0x2476034)
* award_schedule            AWARD_MANAGER +0x18 award-period objects (YEAR/MONTH/TEAM/GOAL/CLUB_AWARD_DATA)
* hall_of_fame_entry        HALL_OF_FAME_MANAGER +0x18 entries and the human managers' entries (+0x30)
* injury_case               INJURY_MANAGER +0x70 records: one per person with an injury in progress
* retirement_entry          RETIREMENT_MANAGER +0x18 / +0x30 per-person, per-season entries
"""
from __future__ import annotations

import json
import struct

from .. import mgr_walk_people as MW
from . import Column, SourceTable, digest
from . import _common as C

INTERNAL = {'scope': 'never', 'reason': 'native manager structure (addresses, container sizes); not a game screen'}

# INTERACTION_MANAGER +0xF8 item layout (bytes). Roles established from code (0xCDB374 filters the
# items of a person's list: status byte +0x56 == 6 is skipped, +0x10 tested for null, the packed date
# at +0x38 compared with a date argument; 0x2476034 dispatches on the u16 type at +0x4E, tests flag
# +0x53 bit 0, resolves +0x20 as the item's person and reads +0x18, +0x28, +0x30) and from the live
# rows (+0x18/+0x20 people, +0x28/+0x30 teams, +0x0 a reference count of 2 or 3).
ITEM = {'refcount': (0x00, '<I'), 'linked': (0x10, '<Q'), 'person_18': (0x18, '<Q'), 'person_20': (0x20, '<Q'),
        'team_28': (0x28, '<Q'), 'team_30': (0x30, '<Q'), 'date_38': (0x38, '<I'), 'date_3c': (0x3C, '<I'),
        'value_40': (0x40, '<i'), 'value_44': (0x44, '<i'), 'value_4c': (0x4C, '<H'), 'type_code': (0x4E, '<H'),
        'flags_53': (0x53, '<B'), 'value_54': (0x54, '<B'), 'status_code': (0x56, '<B'), 'value_57': (0x57, '<B')}
ITEM_SIZE = 0x60
AWARD_DATA_SIZE = 0x30
HOF_SIZE = 0x60


def _walk(engine):
    return MW.walk(engine)


def _container(engine, name, offset):
    for c in _walk(engine).containers:
        if c.manager == name and c.offset == offset:
            return c
    return None


# --------------------------------------------------------------------------- census
def _managers(engine):
    w = _walk(engine)
    by = {}
    for c in w.containers:
        by.setdefault(c.manager, []).append(c)
    rows = []
    for m in MW.MANAGERS:
        obj = w.objects.get(m.name, 0)
        head = w.heads.get(m.name)
        cs = by.get(m.name, [])
        manager_id = struct.unpack_from('<I', head, 0x10)[0] if head and m.size >= 0x18 else None
        state = 'no instance state' if m.size <= 0x18 else \
            'containers' if (m.vectors or m.maps or m.pointers) else 'scalars only'
        rows.append((m.name, f'{m.root:#x}', f'{obj:#x}' if obj else None, m.size, f'{m.alloc_site:#x}',
                     f'{m.vtable:#x}', w.problems.get(m.name) or 'ok', manager_id, state, len(cs),
                     sum(1 for c in cs if c.status == 'ok' and c.count), sum(c.count or 0 for c in cs),
                     head.hex() if head and m.size <= 0x30 else None, m.holds))
    return rows


def _containers(engine):
    rows = []
    for c in _walk(engine).containers:
        classes = {k or 'unclassified': v for k, v in c.classes.most_common()} if c.classes else None
        tables = sorted({k.split(':', 1)[1] for k in c.classes if k and k.startswith('table:')})
        rows.append((c.manager, c.offset, f'+{c.offset:#x}', c.kind, c.status, c.count, c.byte_size,
                     c.element_kind, json.dumps(classes) if classes else None, ','.join(tables) or None))
    return rows


def _elements(engine):
    recs = MW.record_index(engine)
    rows = []
    for c in _walk(engine).containers:
        if c.element_kind != 'pointer':
            continue
        for pos, (p, cls) in enumerate(zip(c.pointers, c.element_class)):
            rec = recs.get(p)
            rows.append((c.manager, c.offset, pos, f'{p:#x}' if p else None,
                         cls if cls and not cls.startswith('table:') else None,
                         rec[0] if rec else None, rec[1] if rec else None))
    return rows


# --------------------------------------------------------------------------- interaction items
def _item_raws(engine):
    c = _container(engine, 'INTERACTION_MANAGER', 0xF8)
    if c is None or c.status != 'ok' or c.element_kind != 'pointer':
        return [], []
    return c.pointers, C.blobs(engine, [(p, ITEM_SIZE) for p in c.pointers])


def _items(engine):
    people = C.index_of(engine, 'people')
    teams = C.index_of(engine, 'teams')
    team_club = C.team_clubs(engine)
    rows = []
    pointers, raws = _item_raws(engine)
    titles = _kind_titles(engine)
    for pos, (p, raw) in enumerate(zip(pointers, raws)):
        if not raw:
            continue
        v = {k: struct.unpack_from(fmt, raw, off)[0] for k, (off, fmt) in ITEM.items()}
        t28, t30 = teams.get(v['team_28']), teams.get(v['team_30'])
        rows.append((pos, v['refcount'], int(bool(v['linked'])),
                     people.get(v['person_18']), people.get(v['person_20']), t28, team_club.get(v['team_28']),
                     t30, team_club.get(v['team_30']), C.packed_date(v['date_38']), C.packed_date(v['date_3c']),
                     v['type_code'], v['status_code'], v['flags_53'], v['value_40'], v['value_44'], v['value_4c'],
                     v['value_54'], v['value_57'], raw[0x40:0x58].hex(), titles.get(v['type_code'], (None, None))[1]))
    return rows


def _kind_titles(engine):
    try:
        from .people_state import promise_kind_titles
        return promise_kind_titles(engine)
    except Exception:  # noqa: BLE001 - only the title column is lost
        return {}


def _items_fingerprint(engine):
    pointers, raws = _item_raws(engine)
    return digest(*MW.fingerprint_parts(engine, ['INTERACTION_MANAGER']), *pointers, *(r or b'' for r in raws))


# --------------------------------------------------------------------------- award schedule
def _award_raws(engine):
    c = _container(engine, 'AWARD_MANAGER', 0x18)
    if c is None or c.status != 'ok' or c.element_kind != 'pointer':
        return None, [], []
    return c, c.pointers, C.blobs(engine, [(p, AWARD_DATA_SIZE) for p in c.pointers])


def _awards(engine):
    awards = C.index_of(engine, 'awards')
    c, pointers, raws = _award_raws(engine)
    rows = []
    for pos, (p, cls, raw) in enumerate(zip(pointers, c.element_class if c else [], raws)):
        if not raw:
            continue
        award, ident, minus = struct.unpack_from('<QIi', raw, 0x8)
        dates = struct.unpack_from('<4I', raw, 0x18)
        rows.append((pos, cls, awards.get(award), ident, *(C.packed_date(d) for d in dates),
                     *struct.unpack_from('<HH', raw, 0x28)))
    return rows


def _awards_fingerprint(engine):
    _, pointers, raws = _award_raws(engine)
    return digest(*MW.fingerprint_parts(engine, ['AWARD_MANAGER']), *pointers, *(r or b'' for r in raws))


# --------------------------------------------------------------------------- hall of fame
def _hof_raws(engine):
    out = []
    for off, list_name in ((0x18, 'hall_of_fame'), (0x30, 'human_managers')):
        c = _container(engine, 'HALL_OF_FAME_MANAGER', off)
        if c is None or c.status != 'ok' or c.element_kind != 'pointer':
            continue
        out += [(list_name, pos, p) for pos, p in enumerate(c.pointers)]
    return out, C.blobs(engine, [(p, HOF_SIZE) for _, _, p in out])


def _hof(engine):
    people = C.index_of(engine, 'people')
    nations = C.index_of(engine, 'nations')
    entries, raws = _hof_raws(engine)
    rows = []
    for (list_name, pos, p), raw in zip(entries, raws):
        if not raw:
            continue
        b, e, cap = struct.unpack_from('<3Q', raw, 0)
        sub = (e - b) // 8 if b and b <= e <= cap and not (e - b) % 8 and e - b < 1 << 20 else None
        person, nation = struct.unpack_from('<QQ', raw, 0x18)
        rows.append((list_name, pos, people.get(person), int(bool(person)), nations.get(nation),
                     C.packed_date(struct.unpack_from('<I', raw, 0x48)[0]), sub,
                     *struct.unpack_from('<iii', raw, 0x4C), struct.unpack_from('<I', raw, 0x58)[0]))
    return rows


def _hof_fingerprint(engine):
    entries, raws = _hof_raws(engine)
    return digest(*MW.fingerprint_parts(engine, ['HALL_OF_FAME_MANAGER']), *(p for *_, p in entries),
                  *(r or b'' for r in raws))


# --------------------------------------------------------------------------- injury cases, retirement lists
def _small_records(engine, manager, offsets, size):
    """[(offset, position, pointer, raw)] for pointer vectors whose elements are `size`-byte records."""
    out = []
    for off in offsets:
        c = _container(engine, manager, off)
        if c is None or c.status != 'ok' or c.element_kind != 'pointer':
            continue
        out += [(off, pos, p) for pos, p in enumerate(c.pointers)]
    return [(off, pos, p, raw) for (off, pos, p), raw in zip(out, C.blobs(engine, [(p, size) for *_, p in out]))]


def _person_by_index(engine):
    """Validated people index -> idx (identity), None when out of range: these records store the live
    PERSON table index itself (checked: INJURY +0x70 indexes are 1,817 of 1,825 currently injured players)."""
    n = len(C.live(engine, 'people').pointers)
    return lambda i: i if 0 <= i < n else None


def _injury_cases(engine):
    person = _person_by_index(engine)
    rows = []
    for _, pos, p, raw in _small_records(engine, 'INJURY_MANAGER', (0x70,), 0x10):
        if not raw:
            continue
        a, b, idx = struct.unpack_from('<III', raw, 0)
        rows.append((pos, person(idx), C.packed_date(a), a >> 9 & 0x7F, C.packed_date(b), b >> 9 & 0x7F))
    return rows


def _injury_fingerprint(engine):
    recs = _small_records(engine, 'INJURY_MANAGER', (0x70,), 0x10)
    return digest(*MW.fingerprint_parts(engine, ['INJURY_MANAGER']), *(r[2] for r in recs), *(r[3] or b'' for r in recs))


def _retirement(engine):
    person = _person_by_index(engine)
    rows = []
    for off, pos, p, raw in _small_records(engine, 'RETIREMENT_MANAGER', (0x18, 0x30), 0x18):
        if not raw:
            continue
        idx, other, d1, d2, d3, flags = struct.unpack_from('<IIIIII', raw, 0)
        rows.append(('list_18' if off == 0x18 else 'list_30', pos, person(idx), other,
                     C.packed_date(d1), C.packed_date(d2), C.packed_date(d3), flags))
    return rows


def _retirement_fingerprint(engine):
    recs = _small_records(engine, 'RETIREMENT_MANAGER', (0x18, 0x30), 0x18)
    return digest(*MW.fingerprint_parts(engine, ['RETIREMENT_MANAGER']), *(r[2] for r in recs),
                  *(r[3] or b'' for r in recs))


def _census_fingerprint(engine):
    return digest(*MW.fingerprint_parts(engine))


def _element_fingerprint(engine):
    """Manager objects plus every pointer-vector buffer (an element added, removed or moved)."""
    parts = MW.fingerprint_parts(engine)
    reqs = []
    objs = C.u64s(engine, [engine.base + m.root for m in MW.MANAGERS])
    heads = C.blobs(engine, [(o, m.size) for o, m in zip(objs, MW.MANAGERS)])
    for m, head in zip(MW.MANAGERS, heads):
        if not head:
            continue
        for off in m.vectors:
            b, e, cap = struct.unpack_from('<3Q', head, off)
            if b and b <= e <= cap and e - b <= MW.MAX_VECTOR_BYTES:
                reqs.append((b, e - b))
    return digest(*parts, *(r or b'' for r in C.blobs(engine, reqs)))


def tables(engine):
    def people_view(alias, col):
        return (f"COALESCE(NULLIF({alias}.{{person.Pcna}}, ''), TRIM(COALESCE({alias}.{{person.Pfna}}, '') || ' ' || "
                f"COALESCE({alias}.{{person.Psna}}, ''))) AS {col}")

    item_view = (
        f"SELECT i.position, i.kind_code, i.status_code, i.person_20_idx, {people_view('p2', 'person_20_name')}, "
        f"i.person_18_idx, {people_view('p1', 'person_18_name')}, i.team_28_idx, t.{{team.Tlna|Tsna|dbnm}} AS team_28, "
        "i.start_date, i.end_date, i.kind_title FROM interaction_item i LEFT JOIN person p1 ON p1.idx = i.person_18_idx "
        "LEFT JOIN person p2 ON p2.idx = i.person_20_idx LEFT JOIN team t ON t.idx = i.team_28_idx")
    hof_view = (
        f"SELECT h.list, h.position, h.person_idx, {people_view('p', 'person_name')}, h.nation_idx, "
        "n.{nation.Nnam|dbnm|Nsnm} AS nation, h.date_48, h.value_54, h.sub_records FROM hall_of_fame_entry h "
        "LEFT JOIN person p ON p.idx = h.person_idx LEFT JOIN nation n ON n.idx = h.nation_idx")
    census = dict(mode='lazy', invalidation='content', fingerprint=lambda: _census_fingerprint(engine))
    return [
        SourceTable('people_manager', 'the people-side native managers (interaction, morale, dispute, dynamics, '
                    'team talk, team blend, AWOL, progression, injury, regeneration, retirement, award, hall of '
                    'fame, achievements, official/simulated/output stats): object, size, id, containers',
                    [Column('manager', 'TEXT', 'native class name (RTTI)'),
                     Column('root_rva', 'TEXT', 'data-segment global holding the object pointer'),
                     Column('object', 'TEXT', 'live object address'),
                     Column('object_bytes', 'INTEGER', 'allocation size at alloc_site (operator new argument)'),
                     Column('alloc_site', 'TEXT', 'the `mov w0, #size` before operator new in the creating code'),
                     Column('vtable_rva', 'TEXT', 'primary vtable the live object must carry'),
                     Column('check', 'TEXT', "'ok' or why the object was not read"),
                     Column('manager_id', 'INTEGER', 'u32 at +0x10 (every manager stores one; meaning: the '
                            'manager registry id, inferred)'),
                     Column('state', 'TEXT', "'containers', 'scalars only' (words after the id, no containers) or "
                            "'no instance state' (vtables and id only)"),
                     Column('containers', 'INTEGER', 'declared containers checked'),
                     Column('non_empty', 'INTEGER', 'containers with elements'),
                     Column('elements', 'INTEGER', 'elements over pointer vectors and maps'),
                     Column('object_hex', 'TEXT', 'raw object bytes for objects of 0x30 bytes or less'),
                     Column('holds', 'TEXT', 'what the manager holds (docs/fmdb/MANAGERS_PEOPLE.md: established '
                            'from code and screens, else marked inferred)')],
                    lambda: _managers(engine), cost_note='17 object reads plus container headers',
                    source_note='mgr_walk_people: globals, vtables, allocation sizes, live header checks',
                    manager=INTERNAL, **census),
        SourceTable('people_manager_container', 'every declared container of the people-side managers: vector or '
                    'map, live check, element count and element classes (RTTI or database table)',
                    [Column('manager', 'TEXT', 'owning manager'),
                     Column('offset', 'INTEGER', 'byte offset in the manager object'),
                     Column('offset_hex', 'TEXT', 'offset as +0x..'),
                     Column('kind', 'TEXT', "'vector' (libc++ begin/end/capacity), 'map' (begin node/root/size) "
                            "or 'pointer' (one object pointer)"),
                     Column('status', 'TEXT', "'ok', 'empty' or 'invalid: <why>'"),
                     Column('count', 'INTEGER', 'elements: pointers in a pointer vector, map size; NULL for vectors '
                            'of inline records (record size not established)'),
                     Column('bytes', 'INTEGER', 'vector payload bytes (end - begin)'),
                     Column('element_kind', 'TEXT', "'pointer' (heap pointers) or 'inline' (records stored in the "
                            'buffer)'),
                     Column('element_classes', 'TEXT', "JSON {class: count}; 'table:<kind>' for database records, "
                            "'unclassified' for objects without a vtable"),
                     Column('record_tables', 'TEXT', 'database tables the elements belong to')],
                    lambda: _containers(engine), cost_note='container headers plus one read per element',
                    source_note='mgr_walk_people.walk', manager=INTERNAL, **census),
        SourceTable('people_manager_element', 'one row per element of every pointer vector of the people-side '
                    'managers: element class (RTTI) or the database record it is',
                    [Column('manager', 'TEXT', 'owning manager'),
                     Column('offset', 'INTEGER', 'container offset in the manager object'),
                     Column('position', 'INTEGER', 'position in the vector'),
                     Column('object', 'TEXT', 'element address'),
                     Column('class', 'TEXT', 'RTTI class of the element object (NULL: no vtable or a record)'),
                     Column('record_table', 'TEXT', 'database table when the element is a record (people, teams, '
                            'awards, ...)'),
                     Column('record_idx', 'INTEGER', 'idx in that table')],
                    lambda: _elements(engine), cost_note='one read per element (about 130,000)',
                    mode='lazy', invalidation='content', fingerprint=lambda: _element_fingerprint(engine),
                    source_note='mgr_walk_people.walk / classify', indexes=('manager', 'record_idx'),
                    manager=INTERNAL),
        SourceTable('interaction_item', 'INTERACTION_MANAGER interaction items (+0xF8): two people, two teams, two '
                    'packed dates, the type and status codes the game dispatches and filters on, raw values',
                    [Column('position', 'INTEGER', 'position in the +0xF8 vector'),
                     Column('refcount', 'INTEGER', 'u32 +0x0 reference count (the per-person list code adds to it '
                            'with ldadd when it copies an item pointer)'),
                     Column('has_link', 'INTEGER', '+0x10 non-null (the filter 0xCDB374 treats a null link with '
                            'status 0 differently; target not established)'),
                     Column('person_18_idx', 'INTEGER', 'person +0x18 (on the managed club: the human manager on '
                            'items about a player, the player on items about the manager)', references='person'),
                     Column('person_20_idx', 'INTEGER', 'person +0x20 (0x2476034 resolves it as the item\'s person)',
                            references='person'),
                     Column('team_28_idx', 'INTEGER', 'team +0x28', references='team'),
                     Column('team_28_club_idx', 'INTEGER', 'club of team_28', references='club'),
                     Column('team_30_idx', 'INTEGER', 'team +0x30 (NULL on group items)', references='team'),
                     Column('team_30_club_idx', 'INTEGER', 'club of team_30', references='club'),
                     Column('start_date', 'TEXT', 'packed date +0x38: the start (the Promises screen\'s StartDate PcSd '
                            'equals it on every listed promise; 0xCDB374 compares it with its date argument)'),
                     Column('end_date', 'TEXT', 'packed date +0x3C: the end (the Promises screen\'s EndDate Pced '
                            'equals it on every listed promise)'),
                     Column('kind_code', 'INTEGER', 'u16 +0x4E promise kind: the index of the title dispatch '
                            '0x24419A4 (see kind_title); 0x2476034 branches on 8, 17, 243; 0x24890EC looks for 7, '
                            '0x1F5CCC0 for 16'),
                     Column('status_code', 'INTEGER', 'u8 +0x56 (6: skipped by the person-list filter 0xCDB374)'),
                     Column('flags_53', 'INTEGER', 'u8 +0x53 (bit 0 set: 0x2476034 returns early)'),
                     Column('value_40', 'INTEGER', 'i32 +0x40 (raw)'),
                     Column('kind_value', 'INTEGER', 'i32 +0x44, read per kind: on kind 7 0x24890EC returns it to the '
                            'happiness computation 0x20ABDB4 (> 0 sets factor bit 35, < 0 bit 36) and the person '
                            "server 0x234C0A8 publishes it as data key 'sqbs'; on kind 16 0x1F5CCC0 reads it (7 on "
                            'every kind-16 item here); on kind 9 it is 0..57 and pairs with value_4c (6000..6005)'),
                     Column('value_4c', 'INTEGER', 'u16 +0x4C (raw)'),
                     Column('value_54', 'INTEGER', 'u8 +0x54 (raw)'),
                     Column('value_57', 'INTEGER', 'u8 +0x57 (raw)'),
                     Column('raw_40_58', 'TEXT', 'bytes +0x40..+0x58 as hex'),
                     Column('kind_title', 'TEXT', 'title the promise-title dispatch 0x24419A4 gives kind_code (game '
                            'string, e.g. 1 Fair increase in playing time, 25 Find loan move for player); NULL for '
                            'codes on its default branch (7, 9, 10, ...), which have no title of their own')],
                    lambda: _items(engine), cost_note='one read per item (about 1,800)',
                    mode='lazy', invalidation='content', fingerprint=lambda: _items_fingerprint(engine),
                    source_note='INTERACTION_MANAGER +0xF8 (vector checked live); roles from 0xCDB374 and 0x2476034',
                    indexes=('person_18_idx', 'person_20_idx', 'team_28_club_idx'),
                    manager={'scope': 'own_club', 'own_club_columns': ['team_28_club_idx', 'team_30_club_idx'],
                             'reason': 'promises, conversations and happiness items show for the manager\'s own '
                                       'squad only'},
                    views={'interaction_item_view': item_view}),
        SourceTable('award_schedule', 'AWARD_MANAGER award periods (+0x18): one AWARD_DATA object per award and '
                    'period with the award, its class (year, month, team, goal, club award) and four packed dates',
                    [Column('position', 'INTEGER', 'position in the +0x18 vector'),
                     Column('data_class', 'TEXT', 'RTTI class: YEAR_AWARD_DATA, MONTH_AWARD_DATA, TEAM_AWARD_DATA, '
                            'GOAL_AWARD_DATA, CLUB_AWARD_DATA'),
                     Column('award_idx', 'INTEGER', 'the db::AWARD record (+0x8)', references='award'),
                     Column('value_10', 'INTEGER', 'u32 +0x10 (raw; meaning not established)'),
                     Column('date_18', 'TEXT', 'packed date +0x18 (start of the period on observed rows, inferred)'),
                     Column('date_1c', 'TEXT', 'packed date +0x1C (end of the period on observed rows, inferred)'),
                     Column('date_20', 'TEXT', 'packed date +0x20'),
                     Column('date_24', 'TEXT', 'packed date +0x24 (1900-01-01 means unset)'),
                     Column('value_28', 'INTEGER', 'u16 +0x28 (raw)'),
                     Column('value_2a', 'INTEGER', 'u16 +0x2A (raw)')],
                    lambda: _awards(engine), cost_note='one read per award period (about 400)',
                    mode='lazy', invalidation='content', fingerprint=lambda: _awards_fingerprint(engine),
                    source_note='AWARD_MANAGER +0x18 (vector checked live; element class by RTTI)',
                    indexes=('award_idx',),
                    manager={'scope': 'public', 'reason': 'award calendars and winners are public competition screens'}),
        SourceTable('hall_of_fame_entry', 'the managers\' Hall of Fame (HALL_OF_FAME_MANAGER +0x18; seeded from the '
                    'database starting hall-of-fame records) and the human managers\' own entries (+0x30): person (when still in '
                    'the database), nation, birth date, points',
                    [Column('list', 'TEXT', "'hall_of_fame' (+0x18) or 'human_managers' (+0x30)"),
                     Column('position', 'INTEGER', 'position in the list'),
                     Column('person_idx', 'INTEGER', 'person +0x18 (NULL: the person is no longer in the database)',
                            references='person'),
                     Column('has_person', 'INTEGER', '+0x18 non-null'),
                     Column('nation_idx', 'INTEGER', 'nation +0x20', references='nation'),
                     Column('date_48', 'TEXT', 'packed date +0x48: birth date (equals person.date_of_birth on 1,162 '
                            'of the 1,168 entries where both are set; set here on 852 whose person record has none)'),
                     Column('sub_records', 'INTEGER', 'pointers in the entry\'s own vector +0x0 (0x48-byte records; '
                            'per-job or per-honour records, inferred)'),
                     Column('value_4c', 'INTEGER', 'i32 +0x4C (raw)'),
                     Column('value_50', 'INTEGER', 'i32 +0x50 (raw)'),
                     Column('value_54', 'INTEGER', 'i32 +0x54: hall-of-fame points (inferred: ordering puts Guardiola, '
                            'Ferguson, Ancelotti, Mourinho first; not yet checked against the screen)'),
                     Column('value_58', 'INTEGER', 'u32 +0x58 (raw)')],
                    lambda: _hof(engine), cost_note='one read per entry (about 6,400)',
                    mode='lazy', invalidation='content', fingerprint=lambda: _hof_fingerprint(engine),
                    source_note='HALL_OF_FAME_MANAGER +0x18 / +0x30 (vectors checked live)',
                    indexes=('person_idx',),
                    manager={'scope': 'public', 'reason': 'the Hall of Fame screen lists every entry'},
                    views={'hall_of_fame_view': hof_view}),
        SourceTable('injury_case', 'INJURY_MANAGER +0x70: one 16-byte record per person with an injury in '
                    'progress (person index and two packed dates)',
                    [Column('position', 'INTEGER', 'position in the +0x70 vector'),
                     Column('person_idx', 'INTEGER', 'u32 +0x8: the PERSON table index (1,817 of the 1,825 on the '
                            'reference save have a current injury in player_injury)', references='person'),
                     Column('date_0', 'TEXT', 'packed date +0x0 (on or after the injury start on 1,816 of 1,817; '
                            'role not established)'),
                     Column('date_0_bits', 'INTEGER', 'bits 9-15 of the +0x0 word (above the day of year; raw)'),
                     Column('date_4', 'TEXT', 'packed date +0x4 (from the next game day onwards on observed rows; '
                            'role not established)'),
                     Column('date_4_bits', 'INTEGER', 'bits 9-15 of the +0x4 word (raw)')],
                    lambda: _injury_cases(engine), cost_note='one read per record (about 1,800)',
                    mode='lazy', invalidation='content', fingerprint=lambda: _injury_fingerprint(engine),
                    source_note='INJURY_MANAGER +0x70 (vector checked live)', indexes=('person_idx',),
                    manager={'scope': 'public', 'reason': 'injuries in progress show on every profile'}),
        SourceTable('retirement_entry', 'RETIREMENT_MANAGER +0x18 and +0x30: 24-byte entries (person index, a '
                    'second u32, three packed dates, flags); +0x78 / +0x90 are their sorted indexes',
                    [Column('list', 'TEXT', "'list_18' (+0x18, indexed by +0x78) or 'list_30' (+0x30, indexed by "
                            '+0x90)'),
                     Column('position', 'INTEGER', 'position in the list'),
                     Column('person_idx', 'INTEGER', 'u32 +0x0: the PERSON table index (inferred: the person screen '
                            'binary-searches the sorted +0x78 / +0x90 indexes by it)', references='person'),
                     Column('value_4', 'INTEGER', 'u32 +0x4 (raw; not a person, club or team unique id)'),
                     Column('date_8', 'TEXT', 'packed date +0x8 (2030-05-28 or 2030-01-01 on the reference save: '
                            'the start of the person\'s season, inferred)'),
                     Column('date_c', 'TEXT', 'packed date +0xC (about a year after date_8: the end of that season, '
                            'inferred)'),
                     Column('date_10', 'TEXT', 'packed date +0x10 (inside that season; role not established)'),
                     Column('flags_14', 'INTEGER', 'u32 +0x14 (raw flag word)')],
                    lambda: _retirement(engine), cost_note='one read per entry (about 1,100)',
                    mode='lazy', invalidation='content', fingerprint=lambda: _retirement_fingerprint(engine),
                    source_note='RETIREMENT_MANAGER +0x18 / +0x30 (vectors checked live)', indexes=('person_idx',),
                    manager={'scope': 'never', 'reason': 'retirement plans are announced in the game only when '
                             'decided; the stored lists are internal'}),
    ]
