"""Collection tables for the transfer, contract, scouting, staff-job and club manager singletons.

Each manager is a plugin global holding a pointer to one object (`mgr_walk.root` checks the object's
vtable). What each object holds was established from its constructor (field initialisation and the size
passed to operator new) and from the game functions that read its containers; the element layouts below
cite those functions. A label is code-evidenced when the column meaning says which function sets or
reads the field; otherwise the meaning gives the record type and says the role is inferred, or gives the
offset and type only.

Tables (all lazy, content invalidation with a fingerprint over the container headers and element bytes):

* `market_manager_container`  every container of the thirteen managers, with its live element count
* `job_advert`                JOB_CENTRE_MANAGER +0x18: staff and manager vacancies (JOB_ADVERT objects)
* `scout_player_assignment`   SCOUT_MANAGER +0x20: players scouted specifically, with the scout
* `scout_manager_entry`       SCOUT_MANAGER +0x80: dated player entries of the human team
* `contract_manager_entry`    CONTRACT_MANAGER +0x18 and +0x78: per-player dated entries
* `feeder_club_group`         FEEDER_CLUB_MANAGER +0x30: groups of affiliated clubs (one row per member)
* `board_takeover_entry`      BOARD_TAKEOVER_MANAGER +0x18: clubs with a takeover state
* `training_camp`             TRAINING_CAMP_MANAGER +0x18: booked training camps
* `backroom_advice_entry`     BACKROOM_ADVICE_MANAGER +0x50: dated advice entries per club
* `finance_manager_entry`     FINANCE_MANAGER +0x18: club / stadium entries
* `human_non_player`          HUMAN_NON_PLAYER_MANAGER +0x18: the human managers' records

Nothing here writes to the game or runs game code: plain reads of the live objects.
"""
from __future__ import annotations

from ... import address_book
from .. import mgr_walk as W
from . import Column, SourceTable
from . import _common as C

# manager: (global root rva, primary vtable rva, object bytes from the constructor, constructor)
MANAGERS = {
    'AGENT_MANAGER': (0x56B6188, 0x55F4360, 0x68, 0x250FE84),
    'CONTRACT_MANAGER': (0x56A64C8, 0x55F5580, 0x118, 0x25F880C),
    'PLAYER_BUYIN_MANAGER': (0x5734818, 0x55F78A8, 0x18, 0x250FE84),
    'SCOUT_MANAGER': (0x56A6AB0, 0x55F7F30, None, 0x2AA27C0),
    'JOB_CENTRE_MANAGER': (0x56A57A0, 0x55F66D0, 0x30, 0x278A5E8),
    'FEEDER_CLUB_MANAGER': (0x56B6190, 0x55F5980, 0x48, 0x266CB74),
    'BOARD_TAKEOVER_MANAGER': (0x56B5430, 0x55F53F0, 0x48, 0x25E6D8C),
    'FINANCE_MANAGER': (0x56B5428, 0x55F5A18, 0x30, 0x268ACAC),
    'FAN_DAY_MANAGER': (0x5732638, 0x55DCA90, None, 0x1AC400C),
    'PITCH_CONDITION_MANAGER': (0x56B6180, 0x55F75C8, 0x8, 0x250FE84),
    'TRAINING_CAMP_MANAGER': (0x56A8700, 0x55F96B0, None, 0x2C89EAC),
    'BACKROOM_ADVICE_MANAGER': (0x56A4F40, 0x55F5328, None, 0x25D6598),
    'HUMAN_NON_PLAYER_MANAGER': (0x56A6890, 0x55F6088, None, 0x26DCB80),
}


def manager(engine, name):
    disabled = address_book.disabled_manager(name)
    if disabled:
        raise address_book.UnresolvedAddress(disabled)
    rva, vt, _, _ = MANAGERS[name]
    return W.root(engine, rva, vt)


# --------------------------------------------------------------------------- inventory
# (manager, offset, container kind, element description, decoding table or '')
#   kinds: 'ptrvec' vector<T*>; 'inline:<stride>' vector<T>; 'ptr->ptrvec' pointer to a vector<T*>;
#   'ptr->inline:<stride>' pointer to a vector<T>; 'none' (the object holds no container)
CONTAINERS = [
    ('AGENT_MANAGER', 0x08, 'inline:8', '8-byte elements (empty on every observed state)', ''),
    ('AGENT_MANAGER', 0x38, 'inline:4', 'u32 values, consecutive (an id range; not person unique ids or table '
                                        'indexes on the observed state)', ''),
    ('AGENT_MANAGER', 0x50, 'inline:8', '8-byte elements', ''),
    ('CONTRACT_MANAGER', 0x18, 'inline:8', '{u32 person index, u32 date}', 'contract_manager_entry'),
    ('CONTRACT_MANAGER', 0x30, 'inline:8', '8-byte elements', ''),
    ('CONTRACT_MANAGER', 0x60, 'ptrvec', 'objects starting with a CLUB pointer and a vector', ''),
    ('CONTRACT_MANAGER', 0x78, 'ptrvec', '16-byte {u32 person index, u32 date, u32 code, u32}',
     'contract_manager_entry'),
    ('CONTRACT_MANAGER', 0x90, 'ptrvec', 'per-person club entries: person +0x10, club +0x18, u32 +0x24 (-1 while '
                                         'open). 0x26063AC answers whether an entry exists for (person, club), '
                                         'comparing clubs through their main team; 0x2605010 removes the open entry '
                                         'of (person, club) and is called from 0x26004AC, the function that sends '
                                         'HUMAN_NON_PLAYER_CONTRACT_OFFER_NEWS: inferred, open contract offers. '
                                         'Empty on every observed state', ''),
    ('CONTRACT_MANAGER', 0xA8, 'inline:8', 'elements (empty on the observed state)', ''),
    ('CONTRACT_MANAGER', 0xC0, 'inline:8', 'elements (empty on the observed state)', ''),
    ('CONTRACT_MANAGER', 0xD8, 'inline:16', '16-byte {key pointer, ..., state byte +0xC} (read by 0x201E510)', ''),
    ('CONTRACT_MANAGER', 0xF8, 'inline:8', 'elements (empty on the observed state)', ''),
    ('PLAYER_BUYIN_MANAGER', None, 'none', 'no container: the 0x18-byte object holds two vtables and a message id; '
                                           'player buy-in state lives on the players (chemistry)', ''),
    ('SCOUT_MANAGER', 0x20, 'ptrvec', 'specifically scouted players: player, scout, team, date',
     'scout_player_assignment'),
    ('SCOUT_MANAGER', 0x80, 'ptrvec', '0x40-byte entries: player, team, two dates', 'scout_manager_entry'),
    ('JOB_CENTRE_MANAGER', 0x18, 'ptrvec', 'JOB_ADVERT (0x40 bytes)', 'job_advert'),
    ('FEEDER_CLUB_MANAGER', 0x18, 'inline:8', 'elements (empty on the observed state)', ''),
    ('FEEDER_CLUB_MANAGER', 0x30, 'ptrvec', 'vector<CLUB*> groups: a parent club and clubs under the same board '
                                            '(see feeder_club_group)', 'feeder_club_group'),
    ('BOARD_TAKEOVER_MANAGER', 0x18, 'ptrvec', '0x60-byte entries: club, CLUB_VISION_OBJECTIVE vector, dates',
     'board_takeover_entry'),
    ('BOARD_TAKEOVER_MANAGER', 0x30, 'inline:8', 'elements', ''),
    ('FINANCE_MANAGER', 0x18, 'ptr->inline:32', '0x20-byte groups, each a vector of 0x40-byte club/stadium entries',
     'finance_stadium_entry'),
    ('FINANCE_MANAGER', 0x20, 'ptr->ptrvec', 'db::FACILITY_UPGRADE', 'facility_upgrade'),
    ('FINANCE_MANAGER', 0x28, 'ptr->inline:144', '0x90-byte elements holding six vectors', ''),
    ('FAN_DAY_MANAGER', 0x60, 'ptrvec', '0x20-byte entries', ''),
    ('FAN_DAY_MANAGER', 0x80, 'ptrvec', 'entries', ''),
    ('FAN_DAY_MANAGER', 0xA0, 'ptrvec', 'entries', ''),
    ('FAN_DAY_MANAGER', 0xC0, 'ptrvec', 'entries', ''),
    ('FAN_DAY_MANAGER', 0xE0, 'ptrvec', 'entries', ''),
    ('FAN_DAY_MANAGER', 0x100, 'ptrvec', 'entries', ''),
    ('PITCH_CONDITION_MANAGER', None, 'none', 'no container: the object is its vtable only (8 bytes, allocated in '
                                              '0x250FE84); pitch condition is held per stadium/club', ''),
    ('TRAINING_CAMP_MANAGER', 0x18, 'ptrvec', '0x50-byte entries: team, city, local region, nation, dates',
     'training_camp'),
    ('BACKROOM_ADVICE_MANAGER', 0x20, 'inline:32', '{FourCC u32, vector<u8>}', ''),
    ('BACKROOM_ADVICE_MANAGER', 0x38, 'ptrvec', '0x50-byte entries with two typed values', ''),
    ('BACKROOM_ADVICE_MANAGER', 0x50, 'ptrvec', '0x30-byte entries: club, date, count, vector',
     'backroom_advice_entry'),
    ('HUMAN_NON_PLAYER_MANAGER', 0x18, 'ptrvec', 'db::HUMAN_NON_PLAYER records', 'human_non_player'),
]


def _container_elements(engine, mgr, off, kind):
    if kind == 'none' or off is None:
        return None, None
    if kind.startswith('ptr->'):
        p = C.u64s(engine, [mgr + off])[0]
        if not p:
            return 0, p
        kind, header = kind[5:], p
    else:
        header = mgr + off
    if kind == 'ptrvec':
        return len(W.pointers(engine, header)), header
    stride = int(kind.split(':')[1])
    return W.vector(engine, header, stride)[1], header


def _inventory(engine):
    rows = []
    for name, off, kind, what, table in CONTAINERS:
        rva, vt, size, ctor = MANAGERS[name]
        note = ''
        try:
            mgr = manager(engine, name)
            count, _ = _container_elements(engine, mgr, off, kind)
        except W.WalkError as exc:
            count, note = None, str(exc)
        rows.append((name, f'{rva:#x}', size, f'{ctor:#x}', None if off is None else off, kind, what, count,
                     table or None, note or None))
    return rows


def _inventory_fp(engine):
    from . import digest
    parts = []
    for name, off, kind, _, _ in CONTAINERS:
        try:
            mgr = manager(engine, name)
            parts.append(_container_elements(engine, mgr, off, kind))
        except W.WalkError as exc:
            parts.append(str(exc))
    return digest(repr(parts))


# --------------------------------------------------------------------------- element layouts
JOB_ADVERT_VT = 0x55F3F90
JOB_ADVERT = [
    ('team_idx', 0x20, 'ref:team', 'advertising team (+0x20, set from the create call\'s team argument by '
                                   '0x2500E50; adverts are looked up by team and job code in 0x278AF00)'),
    ('competition_idx', 0x28, 'ref:competition', 'the team\'s competition when created (+0x28 = team +0x50, '
                                                 '0x2500E50)'),
    ('competition_u16_30', 0x30, 'u16', 'u16 copied from the competition (+0x188) at creation (0x2500E50); '
                                        'meaning not established'),
    ('league_position', 0x32, 'u16', 'team position in the competition at creation: 1 + index returned by '
                                     '0x3AA90B4 (0x2500E50); 0 when not found'),
    ('created', 0x34, 'date', 'current game date when the advert was created (0x278AF00 stores the date global '
                              '0x56B1DB8)'),
    ('closing_date', 0x38, 'date', 'date +0x38: at creation the date 0x278B948 returns for the job and team (the '
                                   'advert\'s closing date; adverts the AI places get 3 more days, 0x278B0AC..0x278B124, '
                                   'adverts the human places keep it); set to the appointment date when 0x332FA78 '
                                   'sets the status to 2. Role from the code; the wording "closing date" is inferred'),
    ('job_code', 0x3C, 'u8', 'native job code of the vacancy (+0x3C, create argument; matched against the staff '
                             'member\'s job byte in 0x332FA78; codes 16/17 take the manager-job path in 0x20625FC). '
                             'Same enum as the contract job code (contract_view.job_code): on 13 Dec 2030 none of the '
                             '50 code-16 adverts had a main-contract holder of job 16 at the advertising team'),
    ('human_placed', 0x3D, 'u8', '1 when the human manager placed the advert: the create call\'s flag (0x278AF00 w3) is '
                                 '1 from PLACE_JOB_ADVERT_ACTION_UI_HANDLER_SERVER slot 7 (0xA1698) and '
                                 'ADD_JOB_ADVERT_TO_REPLACE_NON_PLAYER_RESPONSE slot 11 (0x3841BFC), 0 from the AI '
                                 'callers; with 1 the creator also posts the advert to the human (0x278B2D0..0x278B340)'),
    ('status_code', 0x3E, 'u8', 'advert state: 0 at creation (0x278AF00), set to 2 by 0x332FA78 when the job is '
                                'taken. Observed 13 Dec 2030: 0 on 133 adverts (107 of them with no main-contract '
                                'holder of the job at the team), 1 on 10 (9 with a holder: inferred, an appointment '
                                'is made)'),
    ('list_count', 0x08, 'vcount', 'element count of the vector at +0x08 (empty at creation; role not '
                                   'established)'),
]
SCOUT_20 = [
    ('person_idx', 0x00, 'ref:person', 'player being scouted (+0x00): the list equals, in order, the specifically '
                                       'scouted players of SCOUT_PLAYER_PRIORITIES_UI_HANDLER (key sj22, '
                                       'fm_get_scouting) on 13 Dec 2030, 7 of 7'),
    ('scout_idx', 0x08, 'ref:person', 'staff member (+0x08): a scout of the club on every observed entry (inferred: '
                                      'the scout assigned to the player)'),
    ('team_idx', 0x10, 'ref:team', 'scouting team (+0x10): the human manager\'s team on every observed entry'),
    ('date_a', 0x20, 'date', 'packed date +0x20 (on or before the current date on observed entries: inferred to be '
                             'when scouting was requested)'),
    ('date_b', 0x24, 'date', 'packed date +0x24 (0xFFFFFFFF, no date, on observed entries)'),
    ('u32_2c', 0x2C, 'u32', 'u32 +0x2C (bytes look like small codes; not mapped)'),
]
SCOUT_80 = [
    ('person_idx', 0x00, 'ref:person', 'player (+0x00; role inferred from the record type)'),
    ('person2_idx', 0x08, 'ref:person', 'second person slot (+0x08; empty on observed entries)'),
    ('team_idx', 0x10, 'ref:team', 'team (+0x10): the human manager\'s team on every observed entry'),
    ('date_a', 0x28, 'date', 'packed date +0x28 (meaning not established)'),
    ('date_b', 0x2C, 'date', 'packed date +0x2C (meaning not established)'),
    ('u32_30', 0x30, 'u32', 'u32 +0x30 (1 on observed entries; meaning not established)'),
]
CONTRACT_18 = [
    ('person_idx', 0x00, 'pidx', 'u32 PERSON table index (+0x00; checked: a live record, a player on the observed '
                                 'entries)'),
    ('date', 0x04, 'date', 'packed date +0x04 (the current date on observed entries)'),
]
CONTRACT_78 = [
    ('table_index', 0x00, 'u32', 'u32 table index (+0x00): a PERSON index, or a CLUB index for reason code 7 (the '
                                 'daily pass 0x260AFA4 looks code-7 entries up in the club table 0x56D2D28 and the '
                                 'others in the person table 0x56D2D80, 0x260CC68..0x260CD5C)'),
    ('due_date', 0x04, 'date', 'packed date +0x04: the day the deferred action is due. The daily pass sorts the queue '
                               '(0x264CEA8) and pops every entry whose date has arrived (0x260CC38..0x260CC64)'),
    ('reason_code', 0x08, 'u8', 'byte +0x08 (entries are 12 bytes, allocated by 0x2624C04 and 0x2624D5C): the contract '
                                'termination reason passed to 0x26248BC(manager, contract, person, reason) when the '
                                'entry falls due; 7 = the club\'s retained list (0x2624C04; due entries go to '
                                '0x2623CE8: CLUB_RETAINED_LIST_PUBLICATION_NEWS, PLAYERS_ABOUT_TO_BE_RELEASED_WARNING_NEWS). '
                                'Other values are the reason the original caller passed to 0x26248BC; 0x262AF58 '
                                'defers it through 0x2624D5C when the contract cannot end yet (observed 5, 14, 18, 22)'),
]
TAKEOVER = [
    ('club_idx', 0x00, 'ref:club', 'club (+0x00)'),
    ('objectives', 0x08, 'vcount', 'number of db::CLUB_VISION_OBJECTIVE objects in the vector at +0x08'),
    ('date_a', 0x28, 'date', 'packed date +0x28 (meaning not established)'),
    ('date_b', 0x2C, 'date', 'packed date +0x2C (meaning not established)'),
    ('u32_30', 0x30, 'u32', 'u32 +0x30'),
    ('u32_40', 0x40, 'u32', 'u32 +0x40 (25 to 31 on observed entries)'),
]
CAMP = [
    ('team_idx', 0x00, 'ref:team', 'team going to the camp (+0x00; inferred)'),
    ('city_idx', 0x20, 'ref:city', 'camp city (+0x20; inferred: destination)'),
    ('local_region_idx', 0x28, 'ref:local_region', 'local region of the camp (+0x28)'),
    ('nation_idx', 0x30, 'ref:nation', 'nation of the camp (+0x30)'),
    ('start_date', 0x38, 'date', 'packed date +0x38 (earlier of the pair: inferred start)'),
    ('end_date', 0x3C, 'date', 'packed date +0x3C (later of the pair: inferred end)'),
    ('u32_48', 0x48, 'u32', 'u32 +0x48 (packed small codes; not mapped)'),
    ('u32_4c', 0x4C, 'u32', 'u32 +0x4C'),
]
ADVICE = [
    ('club_idx', 0x00, 'ref:club', 'club (+0x00)'),
    ('date', 0x10, 'date', 'packed date +0x10'),
    ('u16_14', 0x14, 'u16', 'u16 +0x14 (1 to 8 on observed entries)'),
    ('u16_16', 0x16, 'u16', 'u16 +0x16 (0 or 900 on observed entries)'),
    ('list_count', 0x18, 'vcount', 'element count of the vector at +0x18'),
]
FINANCE = [
    ('club_idx', 0x00, 'ref:club', 'club (+0x00)'),
    ('stadium_idx', 0x08, 'ref:stadium', 'stadium (+0x08)'),
    ('date', 0x18, 'date', 'packed date +0x18 (inferred: when the stadium work completes)'),
    ('date_1c', 0x1C, 'date', 'packed date +0x1C (1900-01-01, the no-date value, on observed entries)'),
    ('u32_20', 0x20, 'u32', 'u32 +0x20 (inferred: the stadium capacity before the work)'),
    ('u32_30', 0x30, 'u32', 'u32 +0x30 (inferred: the capacity after the work)'),
    ('u32_34', 0x34, 'u32', 'u32 +0x34 (equal to +0x30 on observed entries)'),
]
FACILITY = [
    ('class', 0x00, 'class', 'record class (db::FACILITY_UPGRADE on observed entries)'),
    ('club_idx', 0x08, 'ref:club', 'club (+0x08)'),
    ('date', 0x10, 'date', 'packed date +0x10 (inferred: when the upgrade completes)'),
    ('u8_14', 0x14, 'u8', 'byte +0x14 (not mapped)'),
    ('u8_15', 0x15, 'u8', 'byte +0x15 (not mapped)'),
]
HUMAN = [
    ('class', 0x00, 'class', 'record class of the element (db::HUMAN_NON_PLAYER)'),
]


def _rows_from(engine, addresses, layout, prefix=(), with_address=False):
    """(*prefix, position, *values) per element; the element address after the position when asked
    (tables do not show native addresses)."""
    out = []
    for i, (a, values) in enumerate(zip(addresses, W.decode(engine, addresses, layout))):
        if values is None:
            continue
        out.append((*prefix, i, a, *values) if with_address else (*prefix, i, *values))
    return out


def _cols(layout, refs=True):
    out = []
    for name, _, kind, meaning in layout:
        ref = kind[4:] if kind.startswith('ref:') else 'person' if kind == 'pidx' else None
        sql = 'TEXT' if kind in ('date', 'class') else 'REAL' if kind == 'f32' else 'INTEGER'
        out.append(Column(name, sql, meaning + ('; -1 when the pointer is not a record of that table'
                                                if kind.startswith('ref:') else ''), references=ref))
    return out


# --------------------------------------------------------------------------- tables
def _job_adverts(engine):
    mgr = manager(engine, 'JOB_CENTRE_MANAGER')
    ads = W.pointers(engine, mgr + 0x18)
    heads = C.u64s(engine, ads)
    bad = [a for a, h in zip(ads, heads) if h != engine.base + JOB_ADVERT_VT]
    if bad:
        raise W.WalkError(f'{len(bad)} job_advert elements are not JOB_ADVERT objects')
    rows = _rows_from(engine, ads, JOB_ADVERT)
    team_club = C.team_clubs(engine)
    teams = C.live(engine, 'teams').pointers
    types = dict(zip([r[1] for r in rows], [b[0] if b else None for b in C.blobs(
        engine, [(teams[r[1]] + 0x28, 1) if r[1] is not None and 0 <= r[1] < len(teams) else (0, 0) for r in rows])]))
    from ... import staff_jobs
    out = []
    for r in rows:
        team, code = r[1], r[7]
        ttype = types.get(team)
        title = None
        if ttype is not None and code is not None and code < 90:
            group = staff_jobs.TEAM_GROUP[ttype] if ttype < len(staff_jobs.TEAM_GROUP) else 2
            title = staff_jobs.JOB_LABELS.get(staff_jobs.JOB_GROUPS[group][code]) or None
        out.append((*r, team_club.get(teams[team]) if team is not None and 0 <= team < len(teams) else None, title))
    return out


def _scout(engine, off, layout):
    mgr = manager(engine, 'SCOUT_MANAGER')
    rows = _rows_from(engine, W.pointers(engine, mgr + off), layout)
    team_club = C.team_clubs(engine)
    teams = C.live(engine, 'teams').pointers
    return [(*r, team_club.get(teams[r[3]]) if r[3] is not None and 0 <= r[3] < len(teams) else None) for r in rows]


def _contract(engine):
    """+0x18 {person, date} and +0x78 {index, due date, reason}: one row each; person_idx / club_idx resolve the
    +0x78 index by its reason (7: club, otherwise person; checked against the live tables)."""
    mgr = manager(engine, 'CONTRACT_MANAGER')
    people = C.live(engine, 'people').pointers
    clubs = C.live(engine, 'clubs').pointers
    rows = [('+0x18', r[0], r[1], r[2], None, None) for r in _rows_from(engine, W.inline(engine, mgr + 0x18, 8),
                                                                         CONTRACT_18)]
    for r in _rows_from(engine, W.pointers(engine, mgr + 0x78), CONTRACT_78):
        index, due, reason = r[1], r[2], r[3]
        if reason == 7:
            person, club = None, index if index < len(clubs) and clubs[index] else None
        else:
            person, club = (index if index < len(people) and people[index] else None), None
        rows.append(('+0x78', r[0], person, due, reason, club))
    return rows


CONTRACT_OFFER = [
    ('person_idx', 0x10, 'ref:person', 'the person the offer is for (+0x10; 0x26063AC compares it with its person '
                                       'argument)'),
    ('club_idx', 0x18, 'ref:club', 'the offering club (+0x18; 0x26063AC compares clubs through their main team)'),
    ('status', 0x24, 'i32', 'state +0x24: -1 while the offer is open (0x2605010 removes the open entry of a person and '
                            'club; it is called from 0x26004AC, which sends HUMAN_NON_PLAYER_CONTRACT_OFFER_NEWS)'),
]
CONTRACT_CLUB_LIST = [
    ('club_idx', 0x00, 'ref:club', 'club (+0x00)'),
    ('list_count', 0x08, 'vcount', 'element count of the vector at +0x08 (elements not decoded)'),
]
CONTRACT_D8 = [
    ('key_class', 0x00, 'class', 'class of the object the 16-byte entry is keyed on (+0x00; 0x201E510 looks entries up '
                                 'by it)'),
    ('state', 0x0C, 'u8', 'state byte +0x0C (read by 0x201E510)'),
]


def _contract_offers(engine):
    mgr = manager(engine, 'CONTRACT_MANAGER')
    return _rows_from(engine, W.pointers(engine, mgr + 0x90), CONTRACT_OFFER)


def _contract_lists(engine):
    mgr = manager(engine, 'CONTRACT_MANAGER')
    rows = [('+0x60', r[0], *r[1:], None, None) for r in
            _rows_from(engine, W.pointers(engine, mgr + 0x60), CONTRACT_CLUB_LIST)]
    rows += [('+0xD8', r[0], None, None, *r[1:]) for r in
             _rows_from(engine, W.inline(engine, mgr + 0xD8, 16), CONTRACT_D8)]
    return rows


def _feeder(engine):
    mgr = manager(engine, 'FEEDER_CLUB_MANAGER')
    clubs = C.index_of(engine, 'clubs')
    rows = []
    for g, header in enumerate(W.pointers(engine, mgr + 0x30)):
        for pos, p in enumerate(W.pointers(engine, header)):
            rows.append((g, pos, clubs.get(p, -1) if p else None))
    return rows


def _takeover(engine):
    mgr = manager(engine, 'BOARD_TAKEOVER_MANAGER')
    return _rows_from(engine, W.pointers(engine, mgr + 0x18), TAKEOVER)


def _camps(engine):
    mgr = manager(engine, 'TRAINING_CAMP_MANAGER')
    rows = _rows_from(engine, W.pointers(engine, mgr + 0x18), CAMP)
    team_club = C.team_clubs(engine)
    teams = C.live(engine, 'teams').pointers
    return [(*r, team_club.get(teams[r[1]]) if r[1] is not None and 0 <= r[1] < len(teams) else None) for r in rows]


def _advice(engine):
    mgr = manager(engine, 'BACKROOM_ADVICE_MANAGER')
    return _rows_from(engine, W.pointers(engine, mgr + 0x50), ADVICE)


def _finance(engine):
    """FINANCE_MANAGER +0x18 points at a vector of 0x20-byte groups; each group starts with a vector of
    0x40-byte club/stadium entries (one row per entry, `group_idx` the group)."""
    mgr = manager(engine, 'FINANCE_MANAGER')
    header = C.u64s(engine, [mgr + 0x18])[0]
    rows = []
    for g, group in enumerate(W.inline(engine, header, 0x20) if header else []):
        rows += _rows_from(engine, W.inline(engine, group, 0x40), FINANCE, prefix=(g,))
    return rows


def _facilities(engine):
    mgr = manager(engine, 'FINANCE_MANAGER')
    header = C.u64s(engine, [mgr + 0x20])[0]
    return _rows_from(engine, W.pointers(engine, header), FACILITY) if header else []


def _human(engine):
    """Each element points inside a PERSON record of class HUMAN_NON_PLAYER (the human manager): the
    record is the live PERSON entry whose pointer lies at most 0x100 bytes below the element."""
    import bisect
    mgr = manager(engine, 'HUMAN_NON_PLAYER_MANAGER')
    elems = W.pointers(engine, mgr + 0x18)
    people = C.live(engine, 'people')
    humans = sorted((p, i) for i, (p, c) in enumerate(zip(people.pointers, people.classes))
                    if p and c == 'HUMAN_NON_PLAYER')
    out = []
    for r in _rows_from(engine, elems, HUMAN, with_address=True):
        a = r[1]
        k = bisect.bisect_right(humans, (a, 1 << 40)) - 1
        hit = humans[k] if k >= 0 and 0 <= a - humans[k][0] < 0x100 else None
        out.append((r[0], *r[2:], hit[1] if hit else None, a - hit[0] if hit else None))
    return out


def _fp(rows_fn):
    def fp():
        from . import digest
        try:
            return digest(repr(rows_fn()))
        except W.WalkError as exc:
            return 'error:' + str(exc)
    return fp


def tables(engine):
    own = lambda col, why: {'scope': 'own_club', 'own_club_column': col, 'reason': why}   # noqa: E731
    never = lambda why: {'scope': 'never', 'reason': why}                                 # noqa: E731
    common = dict(mode='lazy', invalidation='content')
    pos = [Column('entry', 'INTEGER', 'position in the container')]
    return [
        SourceTable('market_manager_container',
                    'every container of the transfer, contract, scouting, staff-job and club manager singletons '
                    '(AGENT, CONTRACT, PLAYER_BUYIN, SCOUT, JOB_CENTRE, FEEDER_CLUB, BOARD_TAKEOVER, FINANCE, FAN_DAY, '
                    'PITCH_CONDITION, TRAINING_CAMP, BACKROOM_ADVICE, HUMAN_NON_PLAYER) with its live element count',
                    [Column('manager', 'TEXT', 'manager class (RTTI)'),
                     Column('root', 'TEXT', 'plugin global holding the manager pointer'),
                     Column('object_bytes', 'INTEGER', 'object size passed to operator new by the constructor '
                                                       '(NULL where not read)'),
                     Column('constructor', 'TEXT', 'constructor or allocating function'),
                     Column('offset', 'INTEGER', 'container offset in the manager object'),
                     Column('container', 'TEXT', "'ptrvec' vector<T*>, 'inline:N' vector<T> of N-byte elements, "
                                                 "'ptr->...' pointer to such a vector, 'none'"),
                     Column('element', 'TEXT', 'what the elements are (record classes by RTTI or by pointer checks)'),
                     Column('elements', 'INTEGER', 'live element count'),
                     Column('decoded_in', 'TEXT', 'table that decodes the elements, if any'),
                     Column('note', 'TEXT', 'walk error, if any')],
                    lambda: _inventory(engine), cost_note='one header read per container',
                    fingerprint=lambda: _inventory_fp(engine),
                    source_note='manager roots checked by vtable; vector headers checked',
                    manager=never('internal container inventory'), **common),
        SourceTable('job_advert', 'every job vacancy the job centre holds (JOB_ADVERT objects of JOB_CENTRE_MANAGER '
                    '+0x18): advertising team and club, job, creation date, state',
                    pos + _cols(JOB_ADVERT) + [
                        Column('club_idx', 'INTEGER', 'club of the advertising team (team +0x30)', references='club'),
                        Column('job_title', 'TEXT', 'English job title by the native contract job conversion '
                                                    '(staff_jobs: team type +0x28 and job code; the advert code is '
                                                    'the contract job enum, see job_code)')],
                    lambda: _job_adverts(engine), cost_note='one read per advert',
                    fingerprint=_fp(lambda: _job_adverts(engine)),
                    source_note='JOB_CENTRE_MANAGER (global 0x56A57A0) +0x18; JOB_ADVERT vtable 0x55F3F90 checked; '
                                'layout from 0x278AF00 / 0x2500E50 / 0x332FA78',
                    indexes=('team_idx', 'club_idx'),
                    manager={'scope': 'public', 'reason': 'vacancies are listed in the job centre for every club'},
                    **common),
        SourceTable('scout_player_assignment', 'players the human club is scouting specifically, with the scout '
                    '(SCOUT_MANAGER +0x20; the Scout Players list of the recruitment screens)',
                    pos + _cols(SCOUT_20) + [Column('club_idx', 'INTEGER', 'club of team_idx', references='club')],
                    lambda: _scout(engine, 0x20, SCOUT_20), cost_note='one read per entry',
                    fingerprint=_fp(lambda: _scout(engine, 0x20, SCOUT_20)),
                    source_note='SCOUT_MANAGER (global 0x56A6AB0) +0x20 pointer vector; vtable checked; checked '
                                'against SCOUT_PLAYER_PRIORITIES_UI_HANDLER',
                    indexes=('person_idx',),
                    manager=own('club_idx', 'the club\'s own scouting list'), **common),
        SourceTable('scout_manager_entry', 'the scouting manager\'s dated player entries for the human team '
                    '(SCOUT_MANAGER +0x80): player, team and two dates; role inferred',
                    pos + _cols(SCOUT_80) + [Column('club_idx', 'INTEGER', 'club of team_idx', references='club')],
                    lambda: _scout(engine, 0x80, SCOUT_80), cost_note='one read per entry',
                    fingerprint=_fp(lambda: _scout(engine, 0x80, SCOUT_80)),
                    source_note='SCOUT_MANAGER (global 0x56A6AB0) +0x80 pointer vector; vtable checked',
                    indexes=('person_idx',),
                    manager=own('club_idx', 'scouting entries belong to the human team'), **common),
        SourceTable('contract_manager_entry', 'the contract manager\'s dated per-player entries (CONTRACT_MANAGER '
                    '+0x18: person and date; +0x78: the queue of deferred contract terminations, each with its due '
                    'date and termination reason code, processed by the daily pass 0x260AFA4)',
                    [Column('container', 'TEXT', "'+0x18' (inline 8-byte {person, date} entries) or '+0x78' "
                                                 "(pointers to 12-byte {index, due date, reason} entries)")] + pos + [
                        Column('person_idx', 'INTEGER', 'the person (+0x18 entries: u32 +0x00; +0x78 entries: the '
                                                        'index when the reason is not 7, checked against the live '
                                                        'person table)', references='person'),
                        Column('due_date', 'TEXT', _cols(CONTRACT_78)[1].meaning + '; +0x18 entries: their date '
                                                                                  '+0x04 (role not established)'),
                        Column('reason_code', 'INTEGER', _cols(CONTRACT_78)[2].meaning),
                        Column('club_idx', 'INTEGER', '+0x78 entries with reason 7: the club whose retained list is '
                                                      'due', references='club')],
                    lambda: _contract(engine), cost_note='one read per entry',
                    fingerprint=_fp(lambda: _contract(engine)),
                    source_note='CONTRACT_MANAGER (global 0x56A64C8); vtable checked; queue layout from 0x2624C04, '
                                '0x2624D5C and the daily pass 0x260AFA4 (0x260CC20..0x260CE48)',
                    indexes=('person_idx',),
                    manager=never('scheduled contract terminations of every club are not shown by the game'),
                    **common),
        SourceTable('contract_offer', 'open contract offers the contract manager holds per person and club '
                    '(CONTRACT_MANAGER +0x90; empty when no offer is open, as on 13 Dec 2030)',
                    pos + _cols(CONTRACT_OFFER), lambda: _contract_offers(engine), cost_note='one read per entry',
                    fingerprint=_fp(lambda: _contract_offers(engine)),
                    source_note='CONTRACT_MANAGER +0x90 pointer vector; layout from 0x26063AC / 0x2605010',
                    indexes=('person_idx',),
                    manager=own('club_idx', 'the manager sees the offers his own club has made'), **common),
        SourceTable('contract_manager_list', 'the contract manager\'s other two containers: +0x60 per-club objects '
                    '(club and a vector, counted) and +0xD8 16-byte keyed entries with a state byte',
                    [Column('container', 'TEXT', "'+0x60' or '+0xD8'")] + pos + _cols(CONTRACT_CLUB_LIST) +
                    _cols(CONTRACT_D8), lambda: _contract_lists(engine), cost_note='one read per entry',
                    fingerprint=_fp(lambda: _contract_lists(engine)),
                    source_note='CONTRACT_MANAGER +0x60 (pointer vector) and +0xD8 (inline, read by 0x201E510)',
                    manager=never('internal contract-manager state; roles not established'), **common),
        SourceTable('feeder_club_group', 'groups of clubs the feeder-club manager links (FEEDER_CLUB_MANAGER +0x30: '
                    'one vector<CLUB*> per group); one row per member. The first club is the parent; the others are '
                    'its affiliates under the Same Board term (club_affiliation): on 12 Nov 2026 all 175 parent-side '
                    'Normal Affiliated Club and Feeder Team links with Same Board lay inside a group, and 20 of the '
                    '196 group links lacked it (selection rule inferred from the data, not traced)',
                    [Column('group_idx', 'INTEGER', 'group position in the manager vector'),
                     Column('position', 'INTEGER', 'position in the group'),
                     Column('club_idx', 'INTEGER', 'member club (-1 when not a CLUB record)', references='club')],
                    lambda: _feeder(engine), cost_note='one read per group',
                    fingerprint=_fp(lambda: _feeder(engine)),
                    source_note='FEEDER_CLUB_MANAGER (global 0x56B6190) +0x30; vtable checked',
                    indexes=('club_idx',),
                    manager={'scope': 'public', 'reason': 'affiliations show on club profiles (role of the groups '
                                                          'inferred)'}, **common),
        SourceTable('board_takeover_entry', 'clubs the board-takeover manager holds (BOARD_TAKEOVER_MANAGER +0x18)',
                    pos + _cols(TAKEOVER), lambda: _takeover(engine), cost_note='one read per entry',
                    fingerprint=_fp(lambda: _takeover(engine)),
                    source_note='BOARD_TAKEOVER_MANAGER (global 0x56B5430) +0x18; vtable checked',
                    manager=never('takeover state of other clubs is not shown as stored'), **common),
        SourceTable('training_camp', 'training camps the training-camp manager holds (TRAINING_CAMP_MANAGER +0x18): '
                    'team, destination city, region, nation and dates',
                    pos + _cols(CAMP) + [Column('club_idx', 'INTEGER', 'club of team_idx', references='club')],
                    lambda: _camps(engine), cost_note='one read per camp', fingerprint=_fp(lambda: _camps(engine)),
                    source_note='TRAINING_CAMP_MANAGER (global 0x56A8700) +0x18; vtable checked',
                    indexes=('team_idx',),
                    manager=own('club_idx', 'the manager sees his own club\'s training camps'), **common),
        SourceTable('backroom_advice_entry', 'dated per-club entries of the backroom advice manager '
                    '(BACKROOM_ADVICE_MANAGER +0x50)', pos + _cols(ADVICE), lambda: _advice(engine),
                    cost_note='one read per entry', fingerprint=_fp(lambda: _advice(engine)),
                    source_note='BACKROOM_ADVICE_MANAGER (global 0x56A4F40) +0x50; vtable checked',
                    manager=own('club_idx', 'backroom advice is given to the manager\'s own club'), **common),
        SourceTable('finance_stadium_entry', 'club and stadium entries of the finance manager (FINANCE_MANAGER +0x18 '
                    'points at a vector of groups, each a vector of 0x40-byte entries): club, stadium, date, two '
                    'capacity-like values; roles inferred',
                    [Column('group_idx', 'INTEGER', 'group position')] + pos + _cols(FINANCE),
                    lambda: _finance(engine), cost_note='one read per group',
                    fingerprint=_fp(lambda: _finance(engine)),
                    source_note='FINANCE_MANAGER (global 0x56B5428) +0x18; vtable checked',
                    manager=own('club_idx', 'club finances show for the manager\'s own club only'), **common),
        SourceTable('facility_upgrade', 'facility upgrades the finance manager holds (FINANCE_MANAGER +0x20 points at '
                    'a vector of db::FACILITY_UPGRADE pointers): club and date',
                    pos + _cols(FACILITY), lambda: _facilities(engine), cost_note='one read',
                    fingerprint=_fp(lambda: _facilities(engine)),
                    source_note='FINANCE_MANAGER (global 0x56B5428) +0x20; vtable checked',
                    manager=own('club_idx', 'facility work shows for the manager\'s own club'), **common),
        SourceTable('human_non_player', 'the human managers\' records (HUMAN_NON_PLAYER_MANAGER +0x18)',
                    pos + _cols(HUMAN) + [
                        Column('person_idx', 'INTEGER', 'the PERSON record (class HUMAN_NON_PLAYER) the element points '
                                                        'into', references='person'),
                        Column('offset_in_person', 'INTEGER', 'element address minus the PERSON record address')],
                    lambda: _human(engine), cost_note='one read',
                    fingerprint=_fp(lambda: _human(engine)),
                    source_note='HUMAN_NON_PLAYER_MANAGER (global 0x56A6890) +0x18; vtable checked',
                    manager=never('internal'), **common),
    ]
