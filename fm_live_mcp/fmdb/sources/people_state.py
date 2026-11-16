"""People state the game shows on its screens, read through the screens' own handlers (lane people2,
docs/fmdb/MANAGERS_PEOPLE.md "Promises" and "Attribute history").

* promise                   the Promises screen of each human manager: PERSON_UI_HANDLER bound to the
                            human, keys HumanActivePromisesMadeList (zWLF), HumanCompletedPromisesMadeList
                            (vP71), HumanBoardPromises (tcoS) and HumanOtherManagerPromises (bfN3); each
                            row is matched to its INTERACTION_MANAGER +0xF8 item (kind code +0x4E)
* player_attribute_history  the development screen's attribute history: PERSON_UI_HANDLER data key
                            'PpAH' (AbilityProgressHistory's source), computed for the players a
                            statement names

The person server answers 'PpAH' only when the game's context-variable table (global 0x56D38C0,
vector of (u32 key, typed*) read by 0x11B5510) holds 'Hhum', the human the screen is drawn for. The
live table is empty between UI calls, so the VM copy is given that one entry (a RECORD {'dref': human
UI id}) after each handler is built; nothing is written to the game. The server then checks the
human's club against the player's (0xD3EB4C..0xD43930): other clubs' players come back null, which is
the game's own fog of war.
"""
from __future__ import annotations

import json
import struct
import time

from . import Column, SourceTable, digest
from . import _common as C
from . import managers_people as MP

CONTEXT_VARIABLES = 0x56D38C0       # vector<(u32 key, typed*)> read by 0x11B5510 (key 'Hhum')
RECORD_TRAITS, INT32_TRAITS = 0xB8, 0x28    # offsets in the typed-value registry (variant.py)

PROMISE_LISTS = {'active': 'zWLF', 'completed': 'vP71', 'board': 'tcoS', 'other_manager': 'bfN3'}
PROMISE_FIELDS = {          # row key -> (column, registry label)
    'qEjH': 'title', 'Iv5a': 'description', 'PcSd': 'made_on', 'Pced': 'deadline', 'dxI2': 'ongoing',
    'adP2': 'status_text', 'PpKc': 'status_icon', 'MPtx': 'progress_flag', 'HuBD': 'duration_text',
    'dqiL': 'duration_hint', '5Z j': 'days_total', 'Drd3': 'days_passed', 'HuBF': 'days_left',
    'jXXX': 'time_passed_pct', '17Xg': 'duration_min', 'Om9k': 'has_target', '1pDd': 'target_title'}
PROMISE_KIND_TITLES = 'kind_titles'      # static: 0x24419A4 dispatch (see promise_kind_title)


# --------------------------------------------------------------------------- humans and the VM
def human_people(engine) -> list:
    """People idx of the human managers (PERSON records of class HUMAN_NON_PLAYER)."""
    people = C.live(engine, 'people')
    return [i for i, c in enumerate(people.classes) if c == 'HUMAN_NON_PLAYER' and people.pointers[i]]


class PersonScreens:
    """One UI VM for a batch of PERSON_UI_HANDLER reads drawn for one human (fresh memory, closed after)."""

    def __init__(self, engine, human: int):
        from .. import history_read as H
        self.H, self.engine, self.human = H, engine, human
        self.reader = H.UiReader(engine)
        self.vm = self.reader.vm

    def close(self):
        self.reader.close()

    def _seed_human(self):
        """'Hhum' = RECORD {'dref': int32 human UI id} in the VM's context-variable table."""
        from ..ui_vm import fourcc
        vm, base = self.vm, self.engine.base
        vm._restore()
        reg = vm.registry
        number = vm.heap_bytes(struct.pack('<QQ', reg + INT32_TRAITS, self.H.ui_id(self.H.UI_PERSON, self.human)))
        entry = vm.heap_bytes(struct.pack('<IIQ', fourcc('dref'), 0, number))
        vector = vm.heap_bytes(struct.pack('<QQQ', entry, entry + 16, entry + 16))
        record = vm.heap_bytes(struct.pack('<QQ', reg + RECORD_TRAITS, vector))
        table = vm.heap_bytes(struct.pack('<IIQ', fourcc('Hhum'), 0, record))
        vm.read(base + CONTEXT_VARIABLES, 24)
        vm.uc.mem_write(base + CONTEXT_VARIABLES, struct.pack('<QQQ', table, table + 16, table + 16))
        vm.commit()

    def read(self, person: int, keys: dict, data_keys: dict | None = None) -> dict:
        """{name: value | Unavailable} for one person (as history_read.UiReader.read, Hhum seeded)."""
        from .. import ui_recipes_person as P
        from ..ui_handlers import plain_text
        from .. import variant
        H, vm = self.H, self.vm
        out = {}
        try:
            handler = vm.build(P.DATABASE_RECORD, {'dref': H.ui_id(H.UI_PERSON, person)})
            self._seed_human()
        except Exception as exc:  # noqa: BLE001 - one person never stops the table
            bad = H.Unavailable(f'handler not built: {type(exc).__name__}: {exc}')
            return {n: bad for n in list(keys) + list(data_keys or {})}
        reader = P.DataReader(vm, handler)
        for name, code in keys.items():
            try:
                reading = reader.get(code)
                value = reading.value
                out[name] = value if isinstance(value, H.Unavailable) else P._value(reading)
            except Exception as exc:  # noqa: BLE001
                out[name] = H.Unavailable(f'{type(exc).__name__}: {exc}')
        for name, code in (data_keys or {}).items():
            try:
                _, value = reader.data_value(code)
                out[name] = value if isinstance(value, H.Unavailable) else plain_text(variant.to_json(value))
            except Exception as exc:  # noqa: BLE001
                out[name] = H.Unavailable(f'{type(exc).__name__}: {exc}')
        return out


# --------------------------------------------------------------------------- promise kinds
def promise_kind_titles(engine) -> dict:
    """{kind: (translation id, English title)} from the title dispatch 0x24419A4: kind - 1 indexes the
    u16 table at 0x53B90A6 (248 entries), target = 0x2441A44 + 4 * entry; the target loads the title's
    translation id into w1 for 0x43DB8B8. Kinds whose target is the default branch 0x2443BFC have no
    title of their own (the formatter only fills person / competition placeholders)."""
    c = C.cache(engine)
    if 'people2_kind_titles' in c:
        return c['people2_kind_titles']
    from ..fieldroutes import language_text
    image = engine.image
    table = image.file_bytes(0x53B90A6, 0xF8 * 2)
    out = {}
    for kind in range(1, 0xF9):
        target = 0x2441A44 + 4 * struct.unpack_from('<H', table, (kind - 1) * 2)[0]
        tid = _title_id(image, target)
        out[kind] = (tid, language_text(tid) if tid else None)
    c['people2_kind_titles'] = out
    return out


def _title_id(image, pc, limit=24):
    """Translation id the code at `pc` passes in w1 to 0x43DB8B8 (mov/movk w1 then bl), following b."""
    w1 = None
    for _ in range(limit):
        w = struct.unpack('<I', image.file_bytes(pc, 4))[0]
        if (w & 0x7FE0001F) == 0x52800001:                          # movz w1, #imm
            w1 = (w >> 5) & 0xFFFF
        elif (w & 0x7FE0001F) == 0x72A00001 and w1 is not None:     # movk w1, #imm, lsl 16
            w1 |= ((w >> 5) & 0xFFFF) << 16
        elif (w & 0xFC000000) == 0x94000000:                        # bl
            off = w & 0x3FFFFFF
            target = pc + 4 * (off - (1 << 26) if off >> 25 else off)
            if target == 0x43DB8B8:
                return w1
            w1 = None
        elif (w & 0xFC000000) == 0x14000000:                        # b
            off = w & 0x3FFFFFF
            target = pc + 4 * (off - (1 << 26) if off >> 25 else off)
            if target in (0x2443BF4, 0x2443BFC):
                return None
            pc = target
            continue
        elif (w & 0xFF000010) == 0x54000000 or w == 0xD65F03C0:     # b.cond / ret: not a plain title
            return None
        pc += 4
    return None


# --------------------------------------------------------------------------- promise
def _person_of(value):
    from .. import history_read as H
    return H.ui_index(value, H.UI_PERSON)


def _promise_rows(engine):
    from .. import history_read as H
    humans = human_people(engine)
    if not humans:
        return []
    items = MP._items(engine)
    by_player = {}
    for r in items:
        by_player.setdefault(r[4], []).append(r)        # person_20 is the player on manager-made items
    titles = promise_kind_titles(engine)
    rows = []
    for human in humans:
        screens = PersonScreens(engine, human)
        try:
            got = screens.read(human, PROMISE_LISTS)
        finally:
            screens.close()
        for list_name, value in got.items():
            if isinstance(value, H.Unavailable) or not isinstance(value, list):
                continue
            for n, it in enumerate(value):
                if not isinstance(it, dict):
                    continue
                player = _person_of(it.get('ekSJ'))
                made, deadline = H.iso(it.get('PcSd')), H.iso(it.get('Pced'))
                match = [r for r in by_player.get(player, ()) if r[9] == made and r[10] == deadline]
                item = match[0] if len(match) == 1 else None
                kind = item[11] if item else None
                club = (item[6] or item[8]) if item else None
                f = {col: H.plain(it.get(code)) for code, col in PROMISE_FIELDS.items()}
                rows.append((human, list_name, n, player, club, kind,
                             titles.get(kind, (None, None))[1] if kind else None,
                             item[0] if item else None,
                             f['title'], f['description'], made, deadline,
                             None if f['ongoing'] is None else int(bool(f['ongoing'])), f['status_text'],
                             f['status_icon'], f['progress_flag'], f['duration_text'], f['duration_hint'],
                             f['days_total'], f['days_passed'], f['days_left'],
                             None if f['time_passed_pct'] is None else round(float(f['time_passed_pct']), 2),
                             f['duration_min'], None if f['has_target'] is None else int(bool(f['has_target'])),
                             f['target_title'] or None))
    return rows


def _promise_fingerprint(engine):
    return digest(MP._items_fingerprint(engine), engine.game_date(), *human_people(engine))


# --------------------------------------------------------------------------- attribute history
SNAPSHOT_BYTES = 47


def snapshot_month(game_date, entries, n):
    """'YYYY-MM' of snapshot n (oldest first) of `entries`: one snapshot per month, the newest for the
    game's current month. From the history getter's window (PLAYER_TRAINING_UI_HANDLER 0x41C800..0x41FEE4):
    it counts the whole months from the window start to the game date with 0x42ECC1C (unit 1 = months,
    checked: 2030-04-10 to 2030-12-13 gives 8) and keeps the newest max(months + 1, 6) snapshots."""
    try:
        y, m = int(game_date[:4]), int(game_date[5:7])
    except (TypeError, ValueError):
        return None
    total = y * 12 + (m - 1) - (entries - 1 - n)
    return f'{total // 12:04d}-{total % 12 + 1:02d}'


def _history_rows(person, value, game_date=None):
    """One row per stored snapshot of PpAH ('atrs': [{valu, atrs: 47 bytes, srTT: 3 bytes}])."""
    rows = []
    entries = value.get('atrs') if isinstance(value, dict) else None
    for n, it in enumerate(entries if isinstance(entries, list) else []):
        if not isinstance(it, dict):
            continue
        raw = _bytes(it.get('atrs'))
        tail = _bytes(it.get('srTT'))
        rows.append((person, n, len(entries), snapshot_month(game_date, len(entries), n), it.get('valu'),
                     raw.hex() if raw is not None else None,
                     json.dumps(list(raw)) if raw is not None else None,
                     json.dumps(attribute_values(raw)) if raw is not None else None,
                     tail.hex() if tail is not None else None))
    return rows


def _bytes(value):
    if isinstance(value, dict) and 'data_hex' in value:
        return bytes.fromhex(value['data_hex'])
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    return None


def snapshot_attributes() -> dict:
    """Snapshot byte index -> attribute column: the index is the native attribute field id
    (knowledge_codes.FIELDS order). Checked: the newest snapshot equals the editor getter PDxx (1-100
    code) for all 47 attributes of 5 Newcastle players (235 of 235), and each index matches one PLAYER
    record offset on all 66 players read (MANAGERS_PEOPLE.md)."""
    from ..knowledge_codes import FIELDS
    return {f['field_id']: f['column'] for f in FIELDS}


def attribute_values(raw: bytes) -> dict:
    """{attribute column: stored value on the editor's 1-100 scale (PDxx)} for one snapshot."""
    return {name: raw[i] for i, name in snapshot_attributes().items() if i < len(raw)}


def _attribute_batch(engine):
    from .. import history_read as H

    def read(keys):
        humans = human_people(engine)
        rows, notes = [], []
        if not humans:
            return rows, ['no human manager in the save']
        # a save holds several HUMAN_NON_PLAYER people; the one that answers is the human whose club
        # employs the player (the server's own check), tried in order and remembered
        order = sorted(humans, key=lambda h: h != engine.__dict__.get('_people2_human'))
        screens = PersonScreens(engine, order[0])
        try:
            for k in keys:
                value = None
                for h in order:
                    screens.human = h
                    got = screens.read(k, {}, {'history': 'PpAH'})
                    value = got.get('history')
                    if value is not None and not isinstance(value, H.Unavailable):
                        engine.__dict__['_people2_human'] = h
                        order = sorted(humans, key=lambda x: x != h)
                        break
                if isinstance(value, H.Unavailable):
                    notes.append(f'{k}: {value.reason}')
                    continue
                if value is None:
                    notes.append(f'{k}: the game returns no history (not a player of a human\'s club, '
                                 'or nothing stored)')
                    continue
                rows += _history_rows(k, value, engine.game_date())
        finally:
            screens.close()
        return rows, notes
    return read


# --------------------------------------------------------------------------- squad hierarchy, social groups
# The Squad > Dynamics screen (TEAM_UI_HANDLER on the human's team). The server builds the hierarchy in
# 0x225C4F0. It keeps the list in a cache on the human manager: team +0x80 (the manager's NON_PLAYER
# subobject, person + 0x20) -> +0x388 -> +0xFE8, a vector of 0x20-byte entries indexed by the team's
# position in its club's team list (club +0x18). An entry is vector<item*> plus the packed date it was
# computed (+0x18); the server uses it while that date is later than the game date minus 8 days
# (0x225CBA0..0x225D384) and recomputes it otherwise. An item (0x30 bytes, refcounted) holds 14 signed
# 16-bit influence factors at +0x4..+0x1E, the influence at +0x24 and the person at +0x28. 0x225D89C
# sorts the items into the four tiers by influence: >= 9000 team leader, >= 7500 highly influential,
# >= 6000 influential, else other. Only human managers carry the cache; for other clubs the server
# answers "Failed to get data" (the game shows no dynamics for them). Social groups are computed by the
# server from the players' relationship lists each time the screen is drawn (no stored groups).
HIERARCHY_CACHE, HIERARCHY_ENTRIES, HIERARCHY_ITEM = 0x388, 0xFE8, 0x30
HIERARCHY_STALE_DAYS = 8
TIER_THRESHOLDS = ((9000, 'team_leader'), (7500, 'highly_influential'), (6000, 'influential'))
TIER_LISTS = {'tlea': 'team_leader', 'lepl': 'highly_influential', 'infp': 'influential', 'squp': 'other'}
TIER_ROW = {'THgi': 'th_gi', 'THli': 'th_li', 'THrc': 'th_rc', 'THcc': 'th_cc', 'THnc': 'th_nc'}
# sgEd group 'clin' -> (name, labelled member-list key, reasons key)
SOCIAL_GROUPS = {0: ('core', 'E3iL', 'rZKm'), 1: ('secondary_1', 'E3iM', 'rZKn'),
                 2: ('secondary_2', 'E3iN', 'rZKo'), 3: ('other', 'E3iO', 'rZKp')}
DYNAMICS_KEYS = {'key_personnel': '6F5W', 'atmosphere': 'gTJS', 'groups': 'TQv0',
                 **{f'reasons_{g[0]}': g[2] for g in SOCIAL_GROUPS.values()}}


def tier_of(influence) -> str | None:
    """Tier 0x225D89C gives an influence value."""
    if influence is None:
        return None
    for floor, name in TIER_THRESHOLDS:
        if influence >= floor:
            return name
    return 'other'


def _human_teams(engine):
    """[(team pointer, team idx, club idx, position in club +0x18, human idx)] for the teams managed by a
    human (team +0x80 is the human's NON_PLAYER subobject)."""
    humans = set(human_people(engine))
    if not humans:
        return []
    people = C.live(engine, 'people')
    teams = C.index_of(engine, 'teams')
    clubs = C.index_of(engine, 'clubs')
    out = []
    for club in engine.save_info().managed_clubs:
        if club not in clubs:
            continue
        b, e = C.u64s(engine, [club + 0x18, club + 0x20])
        n = (e - b) // 8 if b and e >= b and (e - b) < 1 << 16 else 0
        members = C.u64s(engine, [b + 8 * k for k in range(n)]) if n else []
        managers = C.u64s(engine, [t + 0x80 for t in members])
        for pos, (team, mgr) in enumerate(zip(members, managers)):
            if team not in teams or not mgr:
                continue
            for h in humans:
                if people.pointers[h] == mgr - 0x20:
                    out.append((team, teams[team], clubs[club], pos, h))
    return out


def _hierarchy_cache(engine, team, pos):
    """(computed date, [(item pointer, influence, person idx, factors)]) or (None, []) when absent."""
    people = C.index_of(engine, 'people')
    mgr = C.u64s(engine, [team + 0x80])[0]
    obj = C.u64s(engine, [mgr + HIERARCHY_CACHE])[0] if mgr else 0
    if not obj:
        return None, []
    b, e = C.u64s(engine, [obj + HIERARCHY_ENTRIES, obj + HIERARCHY_ENTRIES + 8])
    if not b or e < b or pos >= (e - b) // 8 or (e - b) > 1 << 16:
        return None, []
    entry = C.u64s(engine, [b + 8 * pos])[0]
    raw = C.blobs(engine, [(entry, 0x20)])[0] if entry else None
    if not raw:
        return None, []
    vb, ve = struct.unpack_from('<QQ', raw, 0)
    n = (ve - vb) // 8 if vb and ve >= vb and ve - vb < 1 << 12 else 0
    ptrs = C.u64s(engine, [vb + 8 * k for k in range(n)]) if n else []
    items = []
    for p, r in zip(ptrs, C.blobs(engine, [(p, HIERARCHY_ITEM) for p in ptrs])):
        if not r:
            continue
        items.append((p, struct.unpack_from('<i', r, 0x24)[0], people.get(struct.unpack_from('<Q', r, 0x28)[0]),
                      list(struct.unpack_from('<14h', r, 0x4))))
    return C.packed_date(struct.unpack_from('<I', raw, 0x18)[0]), items


def _dynamics_fingerprint(engine):
    parts = [engine.game_date()]
    for team, tidx, club, pos, human in _human_teams(engine):
        date, items = _hierarchy_cache(engine, team, pos)
        sb, se = C.u64s(engine, [team + 0x38, team + 0x40])
        squad = C.blobs(engine, [(sb, se - sb)])[0] if sb and 0 < se - sb < 1 << 14 else b''
        parts += [tidx, pos, human, date, squad or b'', *(x for it in items for x in (it[0], it[1], it[2]))]
    return digest(*parts)


def _dynamics(engine):
    """{team idx: {...}} for the human-managed teams: the stored hierarchy cache and the screen's values
    (one TEAM_UI_HANDLER read per team), memoised per fingerprint."""
    from .. import history_read as H
    c = C.cache(engine)
    fp = _dynamics_fingerprint(engine)
    if c.get('people3_dynamics', (None,))[0] == fp:
        return c['people3_dynamics'][1]
    out = {}
    teams = _human_teams(engine)
    reader = H.UiReader(engine) if teams else None
    try:
        for team, tidx, club, pos, human in teams:
            date, items = _hierarchy_cache(engine, team, pos)
            got = reader.read(H.ui_id(H.UI_TEAM, tidx), DYNAMICS_KEYS,
                              {**{k: k for k in TIER_LISTS}, 'sgEd': 'sgEd'})
            out[tidx] = {'club': club, 'human': human, 'position': pos, 'computed_on': date, 'items': items,
                         'screen': got}
    finally:
        if reader is not None:
            reader.close()
    c['people3_dynamics'] = (fp, out)
    return out


def _stale(engine, date):
    import datetime as dt
    try:
        today = dt.date.fromisoformat(engine.game_date()[:10])
        return int(dt.date.fromisoformat(date) <= today - dt.timedelta(days=HIERARCHY_STALE_DAYS))
    except Exception:  # noqa: BLE001
        return None


def _hierarchy_rows(engine):
    from .. import history_read as H
    rows = []
    for tidx, d in _dynamics(engine).items():
        screen = d['screen']
        stored = {it[2]: it for it in d['items']}
        keyp = screen.get('key_personnel')
        key_people = {H.ui_index(v, H.UI_PERSON) for v in keyp} if isinstance(keyp, list) else set()
        stale = _stale(engine, d['computed_on']) if d['computed_on'] else None
        seen = set()
        for code, tier in TIER_LISTS.items():
            lst = screen.get(code)
            for n, it in enumerate(lst if isinstance(lst, list) else []):
                if not isinstance(it, dict):
                    continue
                person = H.ui_index(it.get('Pers'), H.UI_PERSON)
                seen.add(person)
                s = stored.get(person)
                infl = s[1] if s else None
                rows.append((d['club'], tidx, person, tier, n, infl, tier_of(infl),
                             json.dumps(s[3]) if s else None, sum(s[3]) if s else None,
                             d['computed_on'], stale, int(person in key_people),
                             *(H.plain(it.get(k)) for k in TIER_ROW)))
        for p, s in stored.items():         # stored but not listed on the screen
            if p not in seen:
                rows.append((d['club'], tidx, p, None, None, s[1], tier_of(s[1]), json.dumps(s[3]), sum(s[3]),
                             d['computed_on'], stale, int(p in key_people), None, None, None, None, None))
    return rows


def _social_rows(engine):
    from .. import history_read as H
    rows = []
    for tidx, d in _dynamics(engine).items():
        screen = d['screen']
        groups = screen.get('sgEd')
        for g in groups if isinstance(groups, list) else []:
            if not isinstance(g, dict):
                continue
            index = g.get('clin')
            name, _, reasons_key = SOCIAL_GROUPS.get(index, (None, None, None))
            reasons = H.plain(screen.get(f'reasons_{name}')) if name else None
            members = g.get('clpl') if isinstance(g.get('clpl'), list) else []
            for n, m in enumerate(members):
                rows.append((d['club'], tidx, index, name, n, H.ui_index(m, H.UI_PERSON), H.plain(g.get('clpc')),
                             H.plain(g.get('clml')), H.plain(g.get('cbsg')), reasons,
                             H.plain(screen.get('atmosphere'))))
    return rows


# --------------------------------------------------------------------------- happiness reasons, concerns
# PERSON_UI_HANDLER HappinessPositives (HPPo) / HappinessNegatives (HPNe) are computed when the screen
# is drawn. A read trace of HPPo for Jay Robinson reads his two promise items through 0xCDB374 /
# 0x2476034 and his concern ring through 0x150B3E0..0x150B460, plus injury and transfer state; the listed
# texts ("Ignoring the speculation regarding his future", "Looking forward to recovering from his
# injury") are not stored anywhere as a list. The stored happiness state is the concern ring: player
# primary +0x2F0 (the main contract, whose +0x8 is the person) -> contract +0x30 -> ring (count u8 +0x0,
# ten slot pointers +0x8, head u8 +0x58) of 28-byte records: start +0x0, end +0x4 (1900-01-01 while
# open), u16 reason +0x16 (500..1362), category +0x19; the same layout fm_get_player_concern_history
# decodes (player_concern_history_source.py).
HAPPINESS_KEYS = {'positives': 'HPPo', 'negatives': 'HPNe', 'playing_time': '225*', 'playing_time_level': 'pthn',
                  'happiness_level': 'Pohl', 'morale': 'dafe'}
PRIMARY_FROM_PERSON = 0x388           # people-table pointer = player primary + 0x388
CONTRACT_OFF, RING_OFF, RING_BYTES, CONCERN_BYTES = 0x2F0, 0x30, 0x60, 28
CONCERN_CATEGORIES = 0x539BA90        # u8 per reason code 500..1362 (863 bytes)
FULL_CONTRACT_VTABLE = 0x55ABD68      # db::FULL_CONTRACT (world.TYPES)


def _current_clubs(engine, people_idx):
    """{person idx: current club idx} through primary +0x128 (team) -> team +0x30 (club)."""
    people = C.live(engine, 'people')
    clubs = C.index_of(engine, 'clubs')
    ptrs = [people.pointers[i] for i in people_idx]
    teams = C.u64s(engine, [p - PRIMARY_FROM_PERSON + 0x128 if p else 0 for p in ptrs])
    club_ptrs = C.u64s(engine, [t + 0x30 if t else 0 for t in teams])
    return {i: clubs.get(c) for i, c in zip(people_idx, club_ptrs)}


def _happiness_rows(person, got, club):
    from .. import history_read as H
    rows = []
    entry = 0
    common = (H.plain(got.get('happiness_level')), H.plain(got.get('morale')), club)
    for sign in ('positives', 'negatives'):
        lst = got.get(sign)
        for n, it in enumerate(lst if isinstance(lst, list) else []):
            if not isinstance(it, dict) or it.get('2   ') == -1:      # the screen's "None" placeholder
                continue
            rows.append((person, entry, sign[:-1], n, H.plain(it.get('name')), H.plain(it.get('2   ')), None,
                         *common))
            entry += 1
    text = H.plain(got.get('playing_time'))
    if text:
        rows.append((person, entry, 'playing_time', 0, text, None, H.plain(got.get('playing_time_level')), *common))
    return rows


def _happiness_batch(engine):
    from .. import history_read as H

    def read(keys):
        humans = human_people(engine)
        if not humans:
            return [], ['no human manager in the save']
        clubs = _current_clubs(engine, keys)
        rows, notes = [], []
        screens = PersonScreens(engine, humans[0])
        try:
            for k in keys:
                got = screens.read(k, HAPPINESS_KEYS)
                bad = H.unavailable_reasons({n: got[n] for n in ('positives', 'negatives')})
                if bad:
                    notes.append(f'{k}: {bad[0]}')
                    continue
                rows += _happiness_rows(k, got, clubs.get(k))
        finally:
            screens.close()
        return rows, notes
    return read


def concern_records(engine, person):
    """[(entry, slot, record bytes)] of a player's concern ring, newest first; [] when he has none."""
    people = C.live(engine, 'people')
    ptr = people.pointers[person] if 0 <= person < len(people.pointers) else 0
    if not ptr:
        return []
    contract = C.u64s(engine, [ptr - PRIMARY_FROM_PERSON + CONTRACT_OFF])[0]
    if not contract:
        return []
    vtable, owner = C.u64s(engine, [contract, contract + 0x8])
    if owner != ptr or vtable != engine.base + FULL_CONTRACT_VTABLE:
        return []                       # no FULL_CONTRACT owned by this person (the decoder's supported case)
    ring = C.u64s(engine, [contract + RING_OFF])[0]
    head = C.blobs(engine, [(ring, RING_BYTES)])[0] if ring else None
    if not head or head[0] > 10 or head[0x58] > 9:
        return []
    count, first = head[0], head[0x58]
    slots = [(count + first - 1 - n) % 10 for n in range(count)]
    ptrs = [struct.unpack_from('<Q', head, 8 + 8 * s)[0] for s in slots]
    raws = C.blobs(engine, [(p, CONCERN_BYTES) for p in ptrs])
    return [(n, s, r) for n, (s, r) in enumerate(zip(slots, raws)) if r]


def _concern_rows(engine, person, club, categories):
    rows = []
    for n, slot, raw in concern_records(engine, person):
        start, end = struct.unpack_from('<II', raw, 0)
        reason = struct.unpack_from('<H', raw, 0x16)[0]
        ongoing = int(end & 0xFFFF01FF == (1900 << 16 | 1))
        rows.append((person, n, slot, C.packed_date(start), None if ongoing else C.packed_date(end), ongoing, reason,
                     raw[0x19], categories[reason - 500] if 500 <= reason < 500 + len(categories) else None,
                     *struct.unpack_from('<iiIH', raw, 0x8), struct.unpack_from('<b', raw, 0x18)[0], raw[0x1A],
                     raw[0x1B], club))
    return rows


def _concern_batch(engine):
    def read(keys):
        categories = engine.image.file_bytes(CONCERN_CATEGORIES, 863)
        clubs = _current_clubs(engine, keys)
        rows = []
        for k in keys:
            rows += _concern_rows(engine, k, clubs.get(k), categories)
        return rows, []
    return read


def tables(engine):
    from . import histories as HS
    own = {'scope': 'own_club', 'own_club_column': 'club_idx',
           'reason': 'the Promises screen lists the human manager\'s own promises only'}
    promise = SourceTable(
        'promise', 'Promises each human manager has made, as the Promises screen lists them (active, completed, '
        'board and other-manager lists of PERSON_UI_HANDLER bound to the human), with the INTERACTION_MANAGER '
        'item each one is stored as',
        [Column('human_idx', 'INTEGER', 'the human manager whose screen lists the promise', references='person'),
         Column('list', 'TEXT', "'active' (zWLF HumanActivePromisesMadeList), 'completed' (vP71), 'board' "
                "(tcoS), 'other_manager' (bfN3)"),
         Column('position', 'INTEGER', 'row on the screen list'),
         Column('player_idx', 'INTEGER', 'the person the promise concerns (row key ekSJ InteractionPromisePromiser: '
                'on the human\'s screen it names the player; on the player\'s screen the manager)',
                references='person'),
         Column('club_idx', 'INTEGER', 'club of the matched item\'s team (+0x28, else +0x30)', references='club'),
         Column('kind_code', 'INTEGER', 'u16 +0x4E of the matched INTERACTION_MANAGER item (NULL: no unique '
                'match by player, start and end date)'),
         Column('kind_title', 'TEXT', 'title the dispatch 0x24419A4 gives that kind (game string; NULL for '
                'kinds on its default branch)'),
         Column('item_position', 'INTEGER', 'position of the matched item in interaction_item'),
         Column('title', 'TEXT', 'InteractionPromiseTitle (qEjH)'),
         Column('description', 'TEXT', 'InteractionPromiseDescription (Iv5a)'),
         Column('made_on', 'TEXT', 'StartDate (PcSd); equals the item start_date'),
         Column('deadline', 'TEXT', 'EndDate (Pced); equals the item end_date'),
         Column('ongoing', 'INTEGER', 'InteractionPromiseOngoing (dxI2)'),
         Column('status_text', 'TEXT', 'InteractionPromiseStatusText (adP2): the player\'s view of progress'),
         Column('status_icon', 'INTEGER', 'InteractionPromiseStatusIcon (PpKc)'),
         Column('progress_flag', 'INTEGER', 'InteractionPromiseProgressFlag (MPtx)'),
         Column('duration_text', 'TEXT', 'InteractionPromiseDurationText (HuBD), e.g. "54 days"'),
         Column('duration_hint', 'TEXT', 'InteractionPromiseDurationHint (dqiL), e.g. "Started: ... - Ends: ..."'),
         Column('days_total', 'INTEGER', "row key '5Z j' (no registry label): days from start to end"),
         Column('days_passed', 'INTEGER', 'InteractionPromiseDurationValue (Drd3)'),
         Column('days_left', 'INTEGER', "row key 'HuBF' (no registry label): days to the end date"),
         Column('time_passed_pct', 'REAL', 'InteractionPromiseTimePassedPercentage (jXXX)'),
         Column('duration_min', 'INTEGER', 'InteractionPromiseDurationMin (17Xg)'),
         Column('has_target', 'INTEGER', 'HasTarget (Om9k)'),
         Column('target_title', 'TEXT', 'TargetTitle (1pDd)')],
        lambda: _promise_rows(engine), mode='lazy', invalidation='content',
        fingerprint=lambda: _promise_fingerprint(engine),
        cost_note='one PERSON_UI_HANDLER read per human manager (about 2 s with the VM build)',
        source_note='emulated PERSON_UI_HANDLER get_property on the human (0x3C7CCC formats data keys Hppm / Hmpm '
                    '/ Hbpm through 0x441638); items matched in INTERACTION_MANAGER +0xF8',
        indexes=('player_idx',), manager=own)

    class _History(HS._Table):
        def source_table(self):
            st = super().source_table()
            st.manager = {'scope': 'own_club', 'own_club_column': 'club_idx',
                          'reason': 'the game answers the history only for the human\'s own players'}
            return st

    history = _History(
        engine, 'player_attribute_history',
        'Attribute history the development screen draws (AbilityProgressHistory): the stored snapshots of a '
        'player\'s attributes, oldest first, computed for the players a statement names',
        'person_idx', 'person',
        [Column('person_idx', 'INTEGER', 'the player', references='person'),
         Column('entry', 'INTEGER', 'snapshot position, oldest first'),
         Column('entries', 'INTEGER', 'snapshots stored for the player'),
         Column('month', 'TEXT', "'YYYY-MM' the snapshot stands for: one per month, the newest for the game's "
                'current month (the getter keeps the newest months + 1 snapshots for a window of whole months '
                'ending on the game date: 0x41C800..0x41FEE4 with 0x42ECC1C / 0x42EC72C)'),
         Column('ability_value', 'INTEGER', "'valu' of the snapshot (record +0x3C): the list AbilityProgressHistory "
                'returns. Units not established: the newest value is 207-224 times current ability on 5 players'),
         Column('attributes_hex', 'TEXT', f'the {SNAPSHOT_BYTES} attribute bytes of the snapshot (0-100 scale)'),
         Column('attributes_raw', 'TEXT', 'the same bytes as a JSON list'),
         Column('attributes', 'TEXT', 'JSON {attribute: value on the editor 1-100 scale (PDxx; the screen shows '
                'about value / 5)}; byte i is native attribute field i'),
         Column('extra_hex', 'TEXT', "'srTT' bytes of the snapshot (raw)"),
         Column('club_idx', 'INTEGER', 'NULL here; the manager view joins the player\'s club', references='club')],
        _attribute_batch_with_club(engine), 'emulated PERSON_UI_HANDLER_SERVER data key PpAH with the human set as '
        "the screen's context ('Hhum'); stored records: 0x44 bytes each (47 attribute bytes, valu at +0x3C)",
        HS.PEOPLE_SQL, HS.NARROW_PERSON)

    dyn = dict(mode='lazy', invalidation='content', fingerprint=lambda: _dynamics_fingerprint(engine),
               cost_note='one TEAM_UI_HANDLER read per human-managed team (about 2 s with the VM build), shared '
                         'by squad_hierarchy and social_group',
               manager={'scope': 'own_club', 'own_club_column': 'club_idx',
                        'reason': 'Squad > Dynamics exists for the human\'s own squad only; the game answers '
                                  '"Failed to get data" for other clubs'})
    hierarchy = SourceTable(
        'squad_hierarchy', 'The squad hierarchy Squad > Dynamics shows for each human-managed team: each player\'s '
        'tier (team leader, highly influential, influential, other) as the screen lists it, with the influence and '
        'influence factors the game stores for him',
        [Column('club_idx', 'INTEGER', 'the club', references='club'),
         Column('team_idx', 'INTEGER', 'the team', references='team'),
         Column('person_idx', 'INTEGER', 'the player', references='person'),
         Column('tier', 'TEXT', "screen list the player is on: 'team_leader' (data key tlea, HierarchyTeamLeaders), "
                "'highly_influential' (lepl), 'influential' (infp), 'other' (squp); NULL: stored but not listed"),
         Column('tier_position', 'INTEGER', 'row on that list'),
         Column('influence', 'INTEGER', 'stored influence (item +0x24); 0x225D89C sorts the tiers by it'),
         Column('tier_by_influence', 'TEXT', "tier the stored influence gives (>= 9000, >= 7500, >= 6000, "
                'else other); differs from tier only when the stored list is stale'),
         Column('factors', 'TEXT', 'JSON list of the 14 signed 16-bit influence factors (item +0x4..+0x1E, raw; '
                'which factor is which is not established)'),
         Column('factor_sum', 'INTEGER', 'sum of the factors; equals influence unless the game capped or '
                'adjusted it (8999 on players kept below team leader, inferred)'),
         Column('computed_on', 'TEXT', 'date the game last computed the stored list (entry +0x18)'),
         Column('stale', 'INTEGER', '1 when computed_on is 8 or more days before the game date: the screen then '
                'recomputes the list and these stored values are the previous ones'),
         Column('key_personnel', 'INTEGER', '1 when the player is in SquadDynamicsKeyPersonnel (6F5W)'),
         Column('th_gi', 'INTEGER', "screen row field 'THgi' (unlabelled, raw)"),
         Column('th_li', 'INTEGER', "screen row field 'THli' (unlabelled, raw)"),
         Column('th_rc', 'INTEGER', "screen row field 'THrc' (unlabelled, raw)"),
         Column('th_cc', 'INTEGER', "screen row field 'THcc' (unlabelled, raw)"),
         Column('th_nc', 'INTEGER', "screen row field 'THnc' (unlabelled, raw)")],
        lambda: _hierarchy_rows(engine),
        source_note='stored cache: team +0x80 (human) -> +0x388 -> +0xFE8[team position] -> items (+0x24 influence, '
                    '+0x28 person); tiers from the emulated TEAM_UI_HANDLER_SERVER data keys tlea/lepl/infp/squp',
        indexes=('person_idx',), **dyn)
    social = SourceTable(
        'social_group', 'The social groups Squad > Dynamics shows for each human-managed team: one row per member, '
        'with the group\'s reasons text; computed by the game from the players\' relationships when drawn',
        [Column('club_idx', 'INTEGER', 'the club', references='club'),
         Column('team_idx', 'INTEGER', 'the team', references='team'),
         Column('group_index', 'INTEGER', "group number 'clin' of data key sgEd (0 core, 1 and 2 secondary, 3 "
                'other: matched to the labelled lists E3iL, E3iM, E3iN, E3iO)'),
         Column('group_name', 'TEXT', "'core', 'secondary_1', 'secondary_2', 'other'"),
         Column('position', 'INTEGER', 'member position in the group'),
         Column('person_idx', 'INTEGER', 'the member', references='person'),
         Column('member_count', 'INTEGER', "'clpc': members in the group"),
         Column('value_clml', 'INTEGER', "group field 'clml' (unlabelled, raw)"),
         Column('flag_cbsg', 'INTEGER', "group field 'cbsg' (unlabelled, raw)"),
         Column('reasons', 'TEXT', 'the group\'s reasons text: CoreSocialGroupReasons (rZKm), Secondary1SocialGroupReasons '
                '(rZKn), rZKo (unlabelled key between them in the same compare chain: secondary 2, inferred), '
                'OtherSocialGroupReasons (rZKp)'),
         Column('dressing_room_atmosphere', 'INTEGER', 'CurrentDressingRoomAtmosphereLevel (gTJS) of the team')],
        lambda: _social_rows(engine),
        source_note='emulated TEAM_UI_HANDLER_SERVER data key sgEd (groups built from each player\'s '
                    'relationship list, reached through the pointer at person +0x2E0)', indexes=('person_idx',), **dyn)
    own_player = {'scope': 'own_club', 'own_club_column': 'club_idx',
                  'reason': 'a player\'s happiness and concerns show on his profile for the manager\'s own squad only'}

    class _Own(HS._Table):
        def source_table(self):
            st = super().source_table()
            st.manager = own_player
            return st

    happiness = _Own(
        engine, 'player_happiness_reason',
        'The reasons the player\'s Happiness panel lists, as the game words them: HappinessPositives, '
        'HappinessNegatives and the playing-time line, computed for the players a statement names',
        'person_idx', 'person',
        [Column('person_idx', 'INTEGER', 'the player', references='person'),
         Column('entry', 'INTEGER', 'row number for the player'),
         Column('sign', 'TEXT', "'positive' (HPPo HappinessPositives), 'negative' (HPNe HappinessNegatives) or "
                "'playing_time' (225* PlayingTimeHappinessLongText)"),
         Column('position', 'INTEGER', 'row on its list'),
         Column('reason_text', 'TEXT', 'the text the screen shows (game string)'),
         Column('reason_code', 'INTEGER', "row field '2   ' of the list (unlabelled; 8 on injury texts, 10 on "
                'transfer-speculation texts on the reference save, raw). Rows with -1, the screen\'s "None", are '
                'left out'),
         Column('level', 'INTEGER', 'PlayingTimeHappinessLevel (pthn) on the playing_time row'),
         Column('happiness_level', 'INTEGER', 'HierarchyOverallHappinessLevel (Pohl) of the player'),
         Column('morale', 'TEXT', 'MoraleString (dafe)'),
         Column('club_idx', 'INTEGER', 'the player\'s current club (primary +0x128 team, +0x30 club)',
                references='club')],
        _happiness_batch(engine),
        'emulated PERSON_UI_HANDLER keys HPPo, HPNe, 225*, pthn, Pohl, dafe (computed on draw from promises, '
        'concerns, injury and transfer state; no stored list)', HS.PEOPLE_SQL, HS.NARROW_PERSON)
    concern = _Own(
        engine, 'player_concern',
        'The concerns the game stores for a player (the ten-slot concern ring on his main contract), newest '
        'first: when each started and ended, the reason code and category; computed for the players a '
        'statement names',
        'person_idx', 'person',
        [Column('person_idx', 'INTEGER', 'the player', references='person'),
         Column('entry', 'INTEGER', 'position in the ring, newest first'),
         Column('slot', 'INTEGER', 'physical ring slot (0-9)'),
         Column('started', 'TEXT', 'packed date +0x0'),
         Column('ended', 'TEXT', 'packed date +0x4 (NULL while the concern is open)'),
         Column('ongoing', 'INTEGER', '1 when +0x4 is the unset date 1900-01-01: the open concern the Happiness '
                'getter 0x150B3E0 reads'),
         Column('reason_code', 'INTEGER', 'u16 +0x16 (500..1362; text not decoded)'),
         Column('category', 'INTEGER', 'u8 +0x19 (stored category)'),
         Column('compiled_category', 'INTEGER', 'category the game\'s table 0x539BA90 gives reason_code'),
         Column('value_08', 'INTEGER', 'i32 +0x8 (raw; a PERSON index on some reasons, inferred)'),
         Column('value_0c', 'INTEGER', 'i32 +0xC (raw)'),
         Column('value_10', 'INTEGER', 'u32 +0x10 (raw)'),
         Column('value_14', 'INTEGER', 'u16 +0x14 (raw)'),
         Column('value_18', 'INTEGER', 'i8 +0x18 (raw)'),
         Column('byte_1a', 'INTEGER', 'u8 +0x1A (raw)'),
         Column('flags_1b', 'INTEGER', 'u8 +0x1B (raw)'),
         Column('club_idx', 'INTEGER', 'the player\'s current club', references='club')],
        _concern_batch(engine),
        'direct read: primary +0x2F0 main contract (+0x8 = the person) -> +0x30 ring -> 28-byte records; layout '
        'as fm_get_player_concern_history', HS.PEOPLE_SQL, HS.NARROW_PERSON)
    return [promise, history.source_table(), hierarchy, social, happiness.source_table(), concern.source_table()]


def _attribute_batch_with_club(engine):
    inner = _attribute_batch(engine)

    def read(keys):
        rows, notes = inner(keys)
        club = _human_club(engine)
        return [(*r, club) for r in rows], notes
    return read


def _human_club(engine):
    """The managed club (club idx): the server answers PpAH only for players of the human's club."""
    try:
        clubs = C.index_of(engine, 'clubs')
        managed = [clubs[c] for c in engine.save_info().managed_clubs if c in clubs]
        return managed[0] if len(managed) == 1 else None
    except Exception:  # noqa: BLE001 - only the manager-view join is lost
        return None
