"""Match-day, match-engine and competition-service managers (docs/fmdb/MATCH_STATE.md).

Roots (plugin RVAs; each object's class is checked by its vtable before a read):

* globals holding the manager pointer: MATCHDAY_MANAGER 0x56A49F0, PLAY_FIXTURE_MANAGER 0x56A4A00,
  simatch::MATCH_MOMENTUM_MANAGER 0x56A66E0, simatch::MATCH_PLAYER_RATINGS_MANAGER 0x56C35A0,
  simatch::MATCH_SYSTEM 0x573C8B0, simatch::TRANSLATABLE_MANAGER 0x56A4BF0,
  simatchshared::MATCH_APPEARANCE_SYSTEM 0x56A9690, simatchshared::MATCH_TEAM_KIT_SYSTEM 0x56A7F90,
  simatchshared::PLAYER_INSTRUCTIONS_MANAGER 0x5734828, simatchshared::STAT_DISTRIBUTION_MANAGER 0x573C8A8,
  sicomps::COMP_HOSTS_MANAGER 0x56BF8D0, sicomps::TV_MANAGER 0x56BF8E8, NETWORK_COMPETITION_MANAGER 0x56A6888.
* members of the competition manager: GAME_RULE_GROUP_MANAGER (global 0x56A4B90) +0x158 is
  GAME_COMP_MANAGER (vtable 0x55DC600). sicomps::COMP_MANAGER's constructor 0x3BAC420 stores the
  results of its own virtual factories there: +0x50 slot 5 (0x1AC51E0, GAME_STADIUM_MANAGER, vtable
  0x55DE108, base sicomps::STADIUM_MANAGER 0x567A1B0), +0x58 slot 6 (0x1AC5218, GAME_SQUAD_MANAGER,
  vtable 0x55DE078, base sicomps::SQUAD_MANAGER 0x567A0E8), +0x60 GAME_NATIONAL_TEAMS, +0x68
  GAME_FRIENDLY_MANAGER, +0x70 GAME_DISCIPLINE.

Tables (all lazy):

* `player_registration_marker`  every competition-registration marker of every ordinary
  ACTUAL_PLAYER: the PERSON+0x48 holder's 16-byte relation vector (common subobject primary+0x278),
  kinds 25..29 and 56, the entries D32054 (PLAYER virtual +240, the RegisteredPlayers predicate)
  admits. Layout and kind meanings from the hand-built `player_registration_source`.
* `squad_manager_entry`  the 1,002 records of GAME_SQUAD_MANAGER +0x08 (0x30 bytes each): key,
  competition where the key is one, codes and six dates. Field meanings are not decoded.
* `comp_host_record`, `comp_host_nation`  COMP_HOSTS_MANAGER +0x08 records (competition, year and
  code bytes) and the NATION lists of the +0x20 and +0x38 records. Field meanings are not decoded.
* `match_momentum_weight`  the 48 (code, code, code, value) entries of MATCH_MOMENTUM_MANAGER +0x08.
* `match_rating_weight`  the three 0x90-byte entries of MATCH_PLAYER_RATINGS_MANAGER +0x08: their
  22 float multipliers by position, with the entry's counters.
* `match_screen_team_stats`  while a match is loaded: the team statistics the match screen shows.
  MATCH_UI_HANDLER (a MATCH_STATS_UI_HANDLER) reads every team statistic from the object its
  virtual +0x108 returns; MATCH_UI_HANDLER's +0x108 (0x2A0D04) locks its client (+0xC8/+0xD0) and
  calls 0x48E6DF8, which returns client +0xF8 -> +0x18 (the GAME_MATCH) -> +0x14E90: the engine's
  GAME_MATCH_STATS, the "simulation" scope of current_match_report, not the client snapshot at
  client +0x08. Side records +0x68/+0x70 are decoded by the hand-built live_match_performance.
  Unavailable, with the reason, when no viewable match client is resident.
* `native_manager`  one row per manager above: whether the root resolves, its class, and the byte
  size of every vector header in its first 0x100 bytes (what the reader reaches, not a decode).
"""
from __future__ import annotations

import hashlib
import json
import struct

from . import Column, SourceTable
from . import _common as C

RULE_GROUP_MANAGER = 0x56A4B90
COMP_MANAGER_AT = 0x158
COMP_MANAGER_VT = 0x55DC600
SQUAD_MANAGER_AT, SQUAD_MANAGER_VT, SQUAD_BASE_VT = 0x58, 0x55DE078, 0x567A0E8
STADIUM_MANAGER_AT, STADIUM_MANAGER_VT, STADIUM_BASE_VT = 0x50, 0x55DE108, 0x567A1B0
COMP_HOSTS, COMP_HOSTS_VT = 0x56BF8D0, 0x566CFB0
MOMENTUM, MOMENTUM_VT = 0x56A66E0, 0x56A06E8
RATINGS, RATINGS_VT = 0x56C35A0, 0x56A01C8
CLIENT_MANAGER = 0x56A6AD8                     # GAME_VIEWABLE_MATCH_CLIENT_MANAGER (active_match_source)
GAME_MATCH_VT, GAME_MATCH_STATS_VT = 0x55FA258, 0x55FA850
ENGINE_STATS_AT = 0x14E90
# MATCH_UI_HANDLER +0x108 -> 0x48E6DF8: client +0xF8 -> +0x18 -> +0x14E90 (pinned bytes)
SCREEN_STATS_CODE = (0x48E6DF8, bytes.fromhex('087c40f9e80000b4080d40f9a80000b409d289522900a072'
                                              '006969f8c0035fd6000080d2c0035fd6'))
# people pointer -> primary (tables.CLASSES); D32054 is each class's virtual +0x240
PLAYER_CLASSES = {'ACTUAL_PLAYER': 0x388, 'ACTUAL_PLAYER_AND_NON_PLAYER': 0x480}
PREDICATE_SLOT, PREDICATE_FN = 0x240, 0xD32054
REGISTRATION_KINDS = (25, 26, 27, 28, 29, 56)
MAX_RELATIONS = 125                            # player_registration_source.MAX_RECORDS

# (name, global RVA, member chain, vtable of the object, base-class vtable when derived)
MANAGERS = (
    ('MATCHDAY_MANAGER', 0x56A49F0, (), 0x55F6980, None),
    ('PLAY_FIXTURE_MANAGER', 0x56A4A00, (), 0x55F7630, None),
    ('simatch::MATCH_MOMENTUM_MANAGER', MOMENTUM, (), MOMENTUM_VT, None),
    ('simatch::MATCH_PLAYER_RATINGS_MANAGER', RATINGS, (), RATINGS_VT, None),
    ('simatch::MATCH_SYSTEM', 0x573C8B0, (), 0x569F240, None),
    ('simatch::TRANSLATABLE_MANAGER', 0x56A4BF0, (), 0x55A3828, None),
    ('simatchshared::MATCH_APPEARANCE_SYSTEM', 0x56A9690, (), 0x56A1E00, None),
    ('simatchshared::MATCH_TEAM_KIT_SYSTEM', 0x56A7F90, (), 0x56A1D98, None),
    ('simatchshared::PLAYER_INSTRUCTIONS_MANAGER', 0x5734828, (), 0x5669110, None),
    ('simatchshared::STAT_DISTRIBUTION_MANAGER', 0x573C8A8, (), 0x56A08C0, None),
    ('sicomps::COMP_HOSTS_MANAGER', COMP_HOSTS, (), COMP_HOSTS_VT, None),
    ('sicomps::TV_MANAGER', 0x56BF8E8, (), 0x566D6C8, None),
    ('NETWORK_COMPETITION_MANAGER', 0x56A6888, (), 0x55F7050, None),
    ('GAME_COMP_MANAGER', RULE_GROUP_MANAGER, (COMP_MANAGER_AT,), COMP_MANAGER_VT, None),
    ('GAME_SQUAD_MANAGER', RULE_GROUP_MANAGER, (COMP_MANAGER_AT, SQUAD_MANAGER_AT), SQUAD_MANAGER_VT,
     SQUAD_BASE_VT),
    ('GAME_STADIUM_MANAGER', RULE_GROUP_MANAGER, (COMP_MANAGER_AT, STADIUM_MANAGER_AT), STADIUM_MANAGER_VT,
     STADIUM_BASE_VT),
)
# The match commentary and emotion systems are not read here: they exist only during a match and no
# reader decodes them (docs/fmdb/MATCH_STATE.md, "Not read"). They are deliberately not named in this
# source so the ledger's name evidence does not count them as reached.


def _u64(raw, off=0):
    return struct.unpack_from('<Q', raw, off)[0]


def _resolve(engine, rva, chain, vtable):
    """Object address by global + member chain, checked by vtable; 0 when the root is empty."""
    obj = C.u64s(engine, [engine.base + rva])[0]
    for off in chain:
        if not obj:
            return 0
        obj = C.u64s(engine, [obj + off])[0]
    if obj and C.u64s(engine, [obj])[0] != engine.base + vtable:
        raise ValueError(f'object at {rva:#x}{"".join(f"+{o:#x}" for o in chain)} is not the expected class '
                         f'(vtable {vtable:#x})')
    return obj


def _vector(engine, header, stride, limit):
    """(start, count) of a std::vector header; raises on an inconsistent header."""
    raw = C.blobs(engine, [(header, 24)])[0]
    if raw is None:
        raise ValueError(f'unreadable vector header {header:#x}')
    start, end, cap = struct.unpack('<QQQ', raw)
    if start == end:
        return start, 0
    if not start or start % 8 or not start <= end <= cap or (end - start) % stride or (end - start) // stride > limit:
        raise ValueError(f'invalid vector header at {header:#x}')
    return start, (end - start) // stride


def _pointers(engine, header, limit):
    start, n = _vector(engine, header, 8, limit)
    if not n:
        return []
    return list(struct.unpack(f'<{n}Q', C.blobs(engine, [(start, 8 * n)])[0]))


def _packed(value):
    return C.packed_date(value) if value not in (0, 0xFFFF, 0xFFFF0000, 0xFFFFFFFF) else None


def _comp_ids(engine) -> dict:
    """{competition database index (record +8): competition idx}."""
    c = C.cache(engine)
    if 'ms_comp_ids' not in c:
        pts = [p for p in C.live(engine, 'competitions').pointers]
        heads = C.blobs(engine, [(p, 12) if p else (0, 0) for p in pts])
        c['ms_comp_ids'] = {struct.unpack_from('<I', h, 8)[0]: i for i, h in enumerate(heads) if h}
    return c['ms_comp_ids']


# --------------------------------------------------------------------------- registration markers
def _registration_raw(engine):
    """Relation vectors of every player record, by D32054's own route: the class vtable's +0x240 is
    D32054, which takes the common subobject at this + *(vtable - 0x20) (0x278 for ACTUAL_PLAYER,
    0x370 for ACTUAL_PLAYER_AND_NON_PLAYER) and reads its +0x48 holder."""
    people = C.live(engine, 'people')
    idx, primaries, unsupported = [], [], 0
    by_class = {}
    for i, (p, cls) in enumerate(zip(people.pointers, people.classes)):
        if p and cls in PLAYER_CLASSES:
            by_class.setdefault(cls, []).append(i)
    for cls, members in by_class.items():
        prim = [people.pointers[i] - PLAYER_CLASSES[cls] for i in members]
        vt = C.u64s(engine, [prim[0]])[0]
        slot, vbase = C.u64s(engine, [vt + PREDICATE_SLOT, vt - 0x20])
        if slot != engine.base + PREDICATE_FN or not 0 < vbase < 0x2000:
            unsupported += len(members)
            continue
        idx += members
        primaries += [q + vbase for q in prim]
    holders = C.u64s(engine, [p + 0x48 for p in primaries])
    heads = C.blobs(engine, [(h, 24) if h else (0, 0) for h in holders])
    reqs, bad = [], 0
    for h, raw in zip(holders, heads):
        if not raw:
            reqs.append((0, 0))
            continue
        s, e, cap = struct.unpack('<QQQ', raw)
        if s == e:
            reqs.append((0, 0))
        elif s % 8 or not s <= e <= cap or (e - s) % 16 or (e - s) > MAX_RELATIONS * 16:
            bad += 1
            reqs.append((0, 0))
        else:
            reqs.append((s, e - s))
    vecs = C.blobs(engine, reqs)
    C.cache(engine)['ms_registration_cov'] = (len(idx), sum(1 for h in holders if h), bad, unsupported,
                                              {c: len(m) for c, m in by_class.items()})
    return idx, vecs


def _markers(engine):
    """[(person idx, [(slot, entity, transport, kind, selector, metadata), ...])] (admitted kinds)."""
    idx, vecs = _registration_raw(engine)
    out = []
    for person, raw in zip(idx, vecs):
        if not raw:
            continue
        ms_ = []
        for slot in range(len(raw) // 16):
            ptr, _, transport, kind, selector, meta, _ = struct.unpack_from('<QHBBBBH', raw, slot * 16)
            if kind in REGISTRATION_KINDS:
                ms_.append((slot, ptr, transport, kind, selector, meta))
        if ms_:
            out.append((person, ms_))
    return out


def _registration_rows(engine):
    teams = C.index_of(engine, 'teams')
    clubs = C.team_clubs(engine)
    rows = []
    for person, ms_ in _markers(engine):
        for slot, ptr, transport, kind, selector, meta in ms_:
            team = teams.get(ptr) if transport == 4 else None
            rows.append((person, slot, team, clubs.get(ptr) if team is not None else None, kind, selector,
                         meta, transport))
    return rows


def predicate(markers, team, selector):
    """D32054 mode 1 over one player's admitted markers: the newest marker (highest slot) with
    transport 4, exactly this team, and this selector (kind 56 matches any selector) decides;
    kinds 25 and 26 are true. Returns (verdict, deciding kind or None)."""
    for slot, ptr, transport, kind, sel, meta in sorted(markers, reverse=True):
        if transport != 4 or ptr != team or (kind != 56 and sel != selector):
            continue
        return kind in (25, 26), kind
    return False, None


def _verdict_rows(engine):
    teams = C.index_of(engine, 'teams')
    clubs = C.team_clubs(engine)
    selectors = {r[4] for r in _rule_rows(engine) if r[4] is not None and r[4] >= 0}
    rows = []
    for person, ms_ in _markers(engine):
        pairs = {(ptr, sel) for _, ptr, transport, kind, sel, _ in ms_ if transport == 4 and kind != 56}
        pairs |= {(ptr, s) for _, ptr, transport, kind, _, _ in ms_ if transport == 4 and kind == 56 for s in selectors}
        for ptr, sel in sorted(pairs):
            if ptr not in teams or sel not in selectors:
                continue
            ok, kind = predicate(ms_, ptr, sel)
            rows.append((person, teams[ptr], clubs.get(ptr), sel, int(ok), kind))
    return rows


def _registration_fingerprint(engine):
    _, vecs = _registration_raw(engine)
    h = hashlib.sha1()
    for raw in vecs:
        h.update(raw or b'-')
    return h.hexdigest()


def _registration_cov(engine):
    n, holders, bad, unsupported, classes = C.cache(engine).get('ms_registration_cov', (0, 0, 0, 0, {}))
    return (f'{n} player records read ({", ".join(f"{k} {v}" for k, v in classes.items())}), {holders} with a '
            f'relation holder, {bad} invalid vectors skipped, {unsupported} in a class whose +0x240 is not '
            f'D32054; the selector is the registration rule\'s selector (competition_registration_rule)')


# --------------------------------------------------------------------------- registration rules
def _rule_rows(engine):
    """Every competition's registration rule: COMP +0xB0 runtime, its current rule index (+0x49) into
    the rule bank (runtime +0x388 -> +0x1F0 -> +0x60 vector), the rule's selector (+0x125, signed) and
    competition id (+0x108), as ucl_registration_source.rule_context reads them."""
    key = 'ms_rules'
    c = C.cache(engine)
    if key in c:
        return c[key]
    comps = C.live(engine, 'competitions')
    pts = list(comps.pointers)
    runtimes = C.u64s(engine, [p + 0xB0 if p else 0 for p in pts])
    banks, rows = {}, []
    for ci, (cp, rt) in enumerate(zip(pts, runtimes)):
        if not cp or not rt:
            continue
        head = C.blobs(engine, [(rt + 0x40, 0x10), (rt + 0x388, 8), (rt + 0x3BE, 1)])
        if not all(head):
            continue
        current, owner, kind = head[0][9], _u64(head[1]), head[2][0]
        bank = C.u64s(engine, [owner + 0x1F0])[0] if owner else 0
        if not bank:
            rows.append((ci, kind, current, 0, None, None, None, None))
            continue
        token = banks.setdefault(bank, len(banks))
        rules = _pointers(engine, bank + 0x60, 256)
        sel = cid = None
        if current < len(rules) and rules[current]:
            raw = C.blobs(engine, [(rules[current] + 0x108, 4), (rules[current] + 0x125, 1)])
            cid = struct.unpack('<i', raw[0])[0]
            sel = struct.unpack('<b', raw[1])[0]
        all_sel = [struct.unpack('<b', r)[0] if r else None
                   for r in C.blobs(engine, [(r + 0x125, 1) if r else (0, 0) for r in rules])]
        rows.append((ci, kind, current, len(rules), sel, cid, token, json.dumps(all_sel)))
    c[key] = rows
    return rows


# --------------------------------------------------------------------------- squad manager
def _squad_rows(engine):
    sm = _resolve(engine, RULE_GROUP_MANAGER, (COMP_MANAGER_AT, SQUAD_MANAGER_AT), SQUAD_MANAGER_VT)
    if not sm:
        raise ValueError('GAME_SQUAD_MANAGER not resident (rule group or competition manager absent)')
    ptrs = _pointers(engine, sm + 8, 100_000)
    comps = _comp_ids(engine)
    rows = []
    for slot, (p, raw) in enumerate(zip(ptrs, C.blobs(engine, [(p, 0x30) for p in ptrs]))):
        if not raw:
            continue
        key, key_kind, code, count = struct.unpack_from('<IHHI', raw, 0)
        dates = [_packed(((v & 0xFFFF) << 16) | (v >> 16)) for v in struct.unpack_from('<5I', raw, 0x0C)]
        dates.append(_packed(struct.unpack_from('<I', raw, 0x20)[0]))
        rows.append((slot, key, key_kind, code, count, comps.get(key) if key_kind == 0 else None, *dates))
    return rows


def _squad_fingerprint(engine):
    sm = _resolve(engine, RULE_GROUP_MANAGER, (COMP_MANAGER_AT, SQUAD_MANAGER_AT), SQUAD_MANAGER_VT)
    ptrs = _pointers(engine, sm + 8, 100_000) if sm else []
    h = hashlib.sha1(struct.pack(f'<{len(ptrs)}Q', *ptrs))
    for raw in C.blobs(engine, [(p, 0x30) for p in ptrs]):
        h.update(raw or b'-')
    return h.hexdigest()


# --------------------------------------------------------------------------- competition hosts
def _host_rows(engine):
    hm = _resolve(engine, COMP_HOSTS, (), COMP_HOSTS_VT)
    if not hm:
        raise ValueError('COMP_HOSTS_MANAGER not resident')
    comps = C.index_of(engine, 'competitions')
    rows = []
    ptrs = _pointers(engine, hm + 0x08, 100_000)
    for slot, (p, raw) in enumerate(zip(ptrs, C.blobs(engine, [(p, 0x68) for p in ptrs]))):
        if not raw:
            continue
        a_s, a_e = struct.unpack_from('<QQ', raw, 0)
        b_s, b_e = struct.unpack_from('<QQ', raw, 0x30)
        y1, y2, y3 = struct.unpack_from('<HHH', raw, 0x58)
        codes = raw[0x5E:0x63]
        rows.append((slot, comps.get(_u64(raw, 0x48)), y1, y2, y3, *codes, (a_e - a_s) // 8, (b_e - b_s) // 8))
    return rows


def _host_nation_rows(engine):
    hm = _resolve(engine, COMP_HOSTS, (), COMP_HOSTS_VT)
    if not hm:
        raise ValueError('COMP_HOSTS_MANAGER not resident')
    nations = C.index_of(engine, 'nations')
    rows = []
    for which in (0x20, 0x38):
        recs = _pointers(engine, hm + which, 100_000)
        for slot, (r, raw) in enumerate(zip(recs, C.blobs(engine, [(r, 0x50) for r in recs]))):
            if not raw:
                continue
            s, e = struct.unpack_from('<QQ', raw, 0x18)
            n = (e - s) // 8 if s and e >= s and (e - s) % 8 == 0 and e - s <= 8 * 1000 else 0
            items = struct.unpack(f'<{n}Q', C.blobs(engine, [(s, 8 * n)])[0]) if n else ()
            for pos, nat in enumerate(items):
                rows.append((which, slot, pos, nations.get(nat), struct.unpack_from('<H', raw, 0x30)[0]))
    return rows


# --------------------------------------------------------------------------- match engine config
def _momentum_rows(engine):
    m = _resolve(engine, MOMENTUM, (), MOMENTUM_VT)
    if not m:
        raise ValueError('MATCH_MOMENTUM_MANAGER not resident')
    start, n = _vector(engine, m + 8, 8, 4096)
    raw = C.blobs(engine, [(start, 8 * n)])[0] if n else b''
    # byte +3 is padding: the builder reads +0, +1 and +2 with ldrb (0x48991D0..0x489923C; 27.0.1
    # 0x4953908..0x4953974) and never +3, which is 0 on 27.0.0 and 0x71 on 27.0.1
    return [(k, *struct.unpack_from('<BBBxi', raw, 8 * k)) for k in range(n)]


def _rating_rows(engine):
    r = _resolve(engine, RATINGS, (), RATINGS_VT)
    if not r:
        raise ValueError('MATCH_PLAYER_RATINGS_MANAGER not resident')
    start, n = _vector(engine, r + 8, 0x90, 64)
    raw = C.blobs(engine, [(start, 0x90 * n)])[0] if n else b''
    rows = []
    for k in range(n):
        e = raw[0x90 * k:0x90 * (k + 1)]
        a = (_u64(e, 8) - _u64(e, 0)) if _u64(e, 0) else 0
        b = (_u64(e, 0x20) - _u64(e, 0x18)) if _u64(e, 0x18) else 0
        count = _u64(e, 0x28)
        code, = struct.unpack_from('<I', e, 0x88)
        tail = e[0x8C:0x90].hex()
        for pos, v in enumerate(struct.unpack_from('<22f', e, 0x30)):
            rows.append((k, pos, round(v, 6), count, a, b, code, tail))
    return rows


# --------------------------------------------------------------------------- match screen statistics
def screen_stats_source(read, base):
    """(client, engine, GAME_MATCH_STATS address) of every resident viewable client with an engine,
    following the match screen's own route (0x48E6DF8). Raises ValueError with the reason when no
    match is loaded. `read(address, length)` may be live memory or a page capture."""
    from ... import active_match_source as ams
    code = read(base + SCREEN_STATS_CODE[0], len(SCREEN_STATS_CODE[1]))
    if code != SCREEN_STATS_CODE[1]:
        raise ValueError('match screen statistics route 0x48E6DF8 changed in this build')
    try:
        state = ams.inspect(read, base)
    except ValueError as exc:
        raise ValueError(f'no match loaded: viewable client manager not readable ({exc})') from exc
    if state['source_state'] == 'inactive' or not state['clients']:
        raise ValueError(f'no match loaded: {state["reason"]}')
    root = _u64(read(base + CLIENT_MANAGER, 8))
    start = _u64(read(root + 8, 8))
    out = []
    for c in state['clients']:
        client = _u64(read(start + 16 * c['source_index'], 8))
        owner = _u64(read(client + 0xF8, 8))
        engine = _u64(read(owner + 0x18, 8)) if owner else 0
        if not engine:
            continue
        if _u64(read(engine, 8)) != base + GAME_MATCH_VT:
            raise ValueError('viewable client engine is not a GAME_MATCH')
        stats = _u64(read(engine + ENGINE_STATS_AT, 8))
        if not stats:
            continue
        out.append((c['source_index'], client, engine, stats))
    if not out:
        raise ValueError('no match loaded: resident viewable clients have no engine statistics')
    return out


def screen_stats_rows(read, base):
    """Rows of `match_screen_team_stats` from any reader (live memory or a page capture). Sides are
    decoded by the hand-built live_match_performance.decode_side; the fixture only by its packed date
    (+0x4C) and competition (name record +0x20 -> +0x18 -> database index +8), as fixtures.record
    reads them, so a capture needs no string pages."""
    from ... import live_match_performance as lmp
    rows = []
    for index, client, engine, stats in screen_stats_source(read, base):
        head = read(stats, 0x78)
        if _u64(head) != base + GAME_MATCH_STATS_VT:
            raise ValueError('engine statistics object is not a GAME_MATCH_STATS')
        fixture = _u64(head, 0x18)
        day_year = struct.unpack('<I', read(fixture + 0x4C, 4))[0] if fixture else 0
        name = _u64(read(fixture + 0x20, 8)) if fixture else 0      # fixture name record (fixtures.record)
        comp = _u64(read(name + 0x18, 8)) if name else 0
        comp_index = struct.unpack('<I', read(comp + 8, 4))[0] if comp else None
        for side, off in enumerate((0x68, 0x70)):
            ptr = _u64(head, off)
            if not ptr or ptr % 8:
                raise ValueError('absent or unaligned statistics side')
            raw = read(ptr, 0x1A0)
            s = lmp.decode_side(raw, struct.unpack_from('<I', raw, 0x5C)[0])
            rows.append((index, side, s['team_index'], _packed(day_year), comp_index, s['shots'],
                         s['shots_on_target'], round(s['expected_goals'], 4), s['passes_attempted'],
                         s['passes_completed'], s['corners'], s['possession_time_raw']))
    return rows


def _screen_fingerprint(engine):
    try:
        src = screen_stats_source(engine.read, engine.base)
    except ValueError as exc:
        return 'none:' + str(exc)[:80]
    h = hashlib.sha1()
    for _, _, _, stats in src:
        head = engine.read(stats, 0x78)
        h.update(head)
        for k in (0x68, 0x70):
            p = _u64(head, k)
            h.update(engine.read(p, 0x1A0) if p else b'-')
    return h.hexdigest()


# --------------------------------------------------------------------------- momentum
# MatchMomentum (key 0x39533448) in MATCH_UI_HANDLER get_property 0x29A3AC -> 0x299B5C(side): the client's
# engine +0x14A58 (0x48E6E20) +0x440 (0x48DA88C) is the match's event store; 0x4898A94(momentum manager,
# store) returns a vector of 8-byte segments <f32 value, u32 end tick> (5-minute segments, 1,200 ticks);
# 0x4899854 shows a segment's value for side 0 and its negation for side 1 (0x4899980..0x489998C).
MOMENTUM_FN = 0x4898A94
MOMENTUM_SHA1 = 'fcb28cf69af14f0ba9bd1bfa476b33f7eaa3914f'     # 0x4898A94..0x4899854, build 27.0.0.2493426
# sha1 of the builder's bytes on every build whose builder was proven to keep the interface this reader
# assumes (manager in x0, event store in x1, the vector returned through x8, 8-byte <f32, u32 tick>
# segments), by running each build's unmodified code over the same synthetic managers and event stores
# and comparing the returned vectors (tests/test_match_momentum_builds.py). The bytes include the ADRP
# page offsets of the globals, so each hash matches only its own build.
# 27.0.1.2503222 (0x4953288..0x4953ED8): re-compiled (helpers inlined, stack slots reassigned); the same
# segments for 600 synthetic matches, and the UI function after it still shows side 1 as the negation.
VERIFIED_MOMENTUM = frozenset({
    MOMENTUM_SHA1,                                  # 27.0.0.2493426
    '324ccea30365d1414d585fe2dc5b82e74afc8c4d',     # 27.0.1.2503222
})
EVENT_STORE_AT = 0x14A58 + 0x440


def momentum_series(vm, read, base, engine_ptr):
    """[(end tick, value for side 0)] as the game computes it now, by emulating 0x4898A94 in `vm`."""
    import hashlib
    import unicorn
    from unicorn import arm64_const as A
    if hashlib.sha1(read(base + MOMENTUM_FN, 0x4899854 - MOMENTUM_FN)).hexdigest() not in VERIFIED_MOMENTUM:
        raise ValueError(f'momentum builder {MOMENTUM_FN:#x} changed in this build')
    mgr = _u64(read(base + MOMENTUM, 8))
    if not mgr or _u64(read(mgr, 8)) != base + MOMENTUM_VT:
        raise ValueError('MATCH_MOMENTUM_MANAGER not resident')
    store = _u64(read(engine_ptr + EVENT_STORE_AT, 8))
    if not store:
        raise ValueError('match event store (engine +0x14E98) is empty')
    out = vm.alloc(0x18)          # 0x4898A94 zeroes the vector header it returns (0x4898ACC)
    entry = base + MOMENTUM_FN

    def sret(uc, addr, size, _):
        if addr == entry:
            uc.reg_write(A.UC_ARM64_REG_X8, out)
    hook = vm.uc.hook_add(unicorn.UC_HOOK_CODE, sret, begin=entry, end=entry + 4)
    try:
        vm.call(entry, (mgr, store))
    except Exception as exc:  # noqa: BLE001  the emulator's stop reasons are not ValueErrors
        raise ValueError(f'momentum builder emulation stopped: {exc}') from exc
    finally:
        vm.uc.hook_del(hook)
    start, end, _ = struct.unpack('<QQQ', vm.read(out, 24))
    if end < start or (end - start) % 8 or end - start > 8 * 64:
        raise ValueError('momentum builder returned an invalid vector')
    raw = vm.read(start, end - start) if end > start else b''
    return [(t, v) for v, t in struct.iter_unpack('<fI', raw)]


def match_identity(date, home_team_idx):
    """`match.idx` of the match played on `date` (YYYY-MM-DD) with that home team: YYYYMMDD * 100000 +
    home team idx (sources/matches.py), or None."""
    if not date or home_team_idx is None:
        return None
    return int(date.replace('-', '')) * 100000 + int(home_team_idx)


def _client_matches(engine):
    """{client: (match idx, date)} of the loaded matches, from the screen statistics' fixture date and
    home team."""
    out = {}
    for row in screen_stats_rows(engine.read, engine.base):
        if row[1] == 0:
            out[row[0]] = (match_identity(row[3], row[2]), row[3])
    return out


def _momentum_series_rows(engine):
    rows = []
    vm = engine.new_vm()
    ids = _client_matches(engine)
    for index, _client, eng, _stats in screen_stats_source(engine.read, engine.base):
        match_idx, date = ids.get(index, (None, None))
        for seg, (tick, value) in enumerate(momentum_series(vm, engine.read, engine.base, eng)):
            rows.append((index, seg, tick, round(tick / 240, 1), round(value, 6), round(-value, 6), match_idx, date))
    return rows


# --------------------------------------------------------------------------- rating components
def _rating_component_rows(engine):
    """Rows of `match_rating_component` for every loaded match (fmdb/match_rating.py). Per player: one row
    per contributing term, plus 'base' and 'rounding', so SUM(contribution) per player is the rating the
    updater computes now; stored_rating is the value the match screen shows."""
    from .. import match_rating as mr
    people = C.index_of(engine, 'people')
    teams = C.index_of(engine, 'teams')
    rows = []
    for m in mr.loaded_matches(engine.read, engine.base):
        ident = (match_identity(m['date'], teams.get(m['sides'][0]['team'])), m['date'])
        for p in m['players']:
            key = (m['client'], p['side'], p['slot'], people.get(p['person']), teams.get(p['team']))
            b = p.get('breakdown')
            if b is None:
                continue
            head = (b['rating'], b['recomputed'], b['multiplier'], b['minutes_in_positions'])
            rows.append((*key, 'base', 'model base rating', None, b['base'], *head,
                         'MATCH_PLAYER_RATINGS_MANAGER entry +0x88', *ident))
            for c in b['components']:
                rows.append((*key, c['term'], c['label'], c['count'], c['contribution'], *head, c['name_source'],
                             *ident))
            rows.append((*key, 'rounding', 'per-position and final rounding', None, b['rounding'], *head,
                         'formula: round-half-away per position and after the multiplier', *ident))
    return rows


def _rating_fingerprint(engine):
    try:
        src = screen_stats_source(engine.read, engine.base)
    except ValueError as exc:
        return 'none:' + str(exc)[:80]
    from .. import match_rating as mr
    h = hashlib.sha1()
    for _, _, eng, _ in src:
        h.update(engine.read(eng + mr.ELAPSED, 4))
        for _, _, pl in mr.players(engine.read, engine.base, eng):
            h.update(engine.read(pl + 0x1D58, 0x10))
            st = _u64(engine.read(pl + 0x1880, 8))
            h.update(engine.read(st + 0x80, 0x90) if st else b'-')
    return h.hexdigest()


# --------------------------------------------------------------------------- manager census
def _vector_sizes(raw, base):
    out = {}
    k = 8
    while k + 24 <= len(raw):
        s, e, cap = struct.unpack_from('<QQQ', raw, k)
        if (s and 4096 <= s < 1 << 48 and not s % 4 and s <= e <= cap and cap - s < 1 << 28
                and not base <= s < base + 0x7000000):
            out[f'{k:#x}'] = e - s
            k += 24
        else:
            k += 8
    return out


def _manager_rows(engine):
    rows = []
    for name, rva, chain, vt, base_vt in MANAGERS:
        try:
            obj = _resolve(engine, rva, chain, vt)
            state = 'resident' if obj else 'root empty'
        except ValueError as exc:
            obj, state = 0, str(exc)
        raw = C.blobs(engine, [(obj, 0x100)])[0] if obj else None
        sizes = _vector_sizes(raw, engine.base) if raw else {}
        route = f'global {rva:#x}' + ''.join(f' +{o:#x}' for o in chain)
        rows.append((name, route, f'{vt:#x}', f'{base_vt:#x}' if base_vt else None, state,
                     json.dumps(sizes) if raw else None))
    return rows


def _const_fingerprint(engine, fn):
    return hashlib.sha1(repr(fn(engine)).encode()).hexdigest()


def tables(engine) -> list[SourceTable]:
    own_reg = {'scope': 'own_club', 'own_club_column': 'club_idx',
               'reason': 'registration lists are edited and shown for the manager\'s own club; other clubs\' '
                         'registrations are not listed in the game'}
    never = {'scope': 'never', 'reason': 'internal engine or service state; not shown in the game as stored'}
    public = {'scope': 'public', 'reason': 'shown on the match screen of the match being played'}
    date_cols = [Column(f'date_{i}', 'TEXT', f'date field {i} (ISO; meaning not decoded)') for i in range(1, 7)]
    return [
        SourceTable(
            name='player_registration_marker',
            description='Competition registration markers of every player (who is registered for which team '
                        'and rule selector), as the RegisteredPlayers predicate D32054 reads them.',
            columns=[Column('person_idx', 'INTEGER', 'player', references='person'),
                     Column('slot', 'INTEGER', 'position in the relation vector (newest last)'),
                     Column('team_idx', 'INTEGER', 'team the registration is for', references='team'),
                     Column('club_idx', 'INTEGER', 'club of that team', references='club'),
                     Column('kind', 'INTEGER', 'marker kind', enum={25: 'registered (committed)',
                            26: 'pending addition', 27: 'pending removal', 28: 'kind 28 (unmapped)',
                            29: 'kind 29 (unmapped)', 56: 'kind 56 (selector not compared)'}),
                     Column('selector', 'INTEGER', 'registration rule selector the predicate compares '
                            '(competition_registration_rule.selector names the competitions)'),
                     Column('metadata', 'INTEGER', 'unmapped metadata byte'),
                     Column('transport', 'INTEGER', 'entity transport code (4 = TEAM pointer)')],
            rows=lambda: _registration_rows(engine), mode='lazy', invalidation='content',
            fingerprint=lambda: _registration_fingerprint(engine), indexes=('person_idx', 'team_idx', 'club_idx'),
            source_note='player primary + *(vtable - 0x20) + 0x48 holder (D32054), 16-byte relations <Q entity, H, B transport, B kind, '
                        'B selector, B metadata, H> (hand-built player_registration_source.project, same layout); '
                        'kinds 25..29/56 admitted by D32054',
            coverage=lambda: _registration_cov(engine), manager=own_reg,
            cost_note='about 1 s: two batched reads per player'),
        SourceTable(
            name='competition_registration_rule',
            description='Each competition\'s current registration rule: its selector (the value registration '
                        'markers carry) and the rule\'s competition id.',
            columns=[Column('competition_idx', 'INTEGER', 'competition', references='competition'),
                     Column('runtime_kind', 'INTEGER', 'runtime +0x3BE kind byte'),
                     Column('current_rule', 'INTEGER', 'runtime +0x49 index into the rule bank (255: not set)'),
                     Column('rules', 'INTEGER', 'rules in the bank'),
                     Column('selector', 'INTEGER', 'current rule +0x125 (signed; -1: no registration selector)'),
                     Column('rule_competition_id', 'INTEGER', 'current rule +0x108 (-1 when unset)'),
                     Column('bank', 'INTEGER', 'rule bank (competitions with the same value share it)'),
                     Column('selectors_json', 'TEXT', 'selector of every rule in the bank, by index')],
            rows=lambda: _rule_rows(engine), mode='lazy', invalidation='content',
            fingerprint=lambda: _const_fingerprint(engine, lambda e: (C.cache(e).pop('ms_rules', None),
                                                                      _rule_rows(e))[1]),
            indexes=('competition_idx', 'selector'),
            source_note='COMP +0xB0 runtime; +0x49 rule index; +0x388 -> +0x1F0 rule bank -> +0x60 rules; rule '
                        '+0x125 selector, +0x108 competition id (ucl_registration_source.rule_context reads)',
            manager={'scope': 'public', 'reason': 'registration rules of a competition are shown in its rules'},
            cost_note='under 0.5 s'),
        SourceTable(
            name='registration_verdict',
            description='The game\'s registration predicate (D32054, mode 1) for every player, team and rule '
                        'selector the player has a marker for.',
            columns=[Column('person_idx', 'INTEGER', 'player', references='person'),
                     Column('team_idx', 'INTEGER', 'team', references='team'),
                     Column('club_idx', 'INTEGER', 'club of the team', references='club'),
                     Column('selector', 'INTEGER', 'rule selector (competition_registration_rule.selector)'),
                     Column('registered', 'INTEGER', '1 when the newest matching marker is kind 25 or 26'),
                     Column('deciding_kind', 'INTEGER', 'kind of that marker (27: pending removal, 56: the '
                            'selector-free kind, which is false)')],
            rows=lambda: _verdict_rows(engine), mode='lazy', invalidation='content',
            fingerprint=lambda: _registration_fingerprint(engine), indexes=('person_idx', 'team_idx', 'selector'),
            source_note='player_registration_marker rows evaluated newest first as D32054 does (team, transport 4, '
                        'selector or kind 56; true for 25/26); selectors are those of competition rules',
            manager=own_reg, cost_note='about 1.5 s',
            views={'competition_registration': (
                'SELECT v.person_idx, v.team_idx, v.club_idx, r.competition_idx, v.selector, v.registered, '
                'v.deciding_kind FROM registration_verdict v JOIN competition_registration_rule r '
                'ON r.selector = v.selector WHERE EXISTS (SELECT 1 FROM fixture f WHERE f.competition_idx = '
                'r.competition_idx AND (f.home_team_idx = v.team_idx OR f.away_team_idx = v.team_idx) '
                'AND f.season_code = (SELECT max(g.season_code) FROM fixture g WHERE g.competition_idx = '
                'r.competition_idx))')}),
        SourceTable(
            name='squad_manager_entry',
            description='GAME_SQUAD_MANAGER records (0x30 bytes each): key, competition where the key is one, '
                        'codes and dates; meanings not decoded.',
            columns=[Column('slot', 'INTEGER', 'position in GAME_SQUAD_MANAGER +0x08'),
                     Column('key', 'INTEGER', 'record +0x00 u32 (a competition index when key_kind is 0)'),
                     Column('key_kind', 'INTEGER', 'record +0x04 u16'),
                     Column('code', 'INTEGER', 'record +0x06 u16 (meaning not decoded)'),
                     Column('count', 'INTEGER', 'record +0x08 u32 (meaning not decoded)'),
                     Column('competition_idx', 'INTEGER', 'competition named by the key', references='competition'),
                     *date_cols],
            rows=lambda: _squad_rows(engine), mode='lazy', invalidation='content',
            fingerprint=lambda: _squad_fingerprint(engine), indexes=('competition_idx',),
            source_note='global 0x56A4B90 +0x158 (GAME_COMP_MANAGER) +0x58 (GAME_SQUAD_MANAGER, vtable 0x55DE078, '
                        'base sicomps::SQUAD_MANAGER 0x567A0E8) +0x08 pointer vector; direct reads; dates 1-5 '
                        '<u16 year, u16 day> at +0x0C..+0x1C, date 6 packed <day, year> at +0x20 (inferred)',
            manager=never, cost_note='under 0.1 s'),
        SourceTable(
            name='comp_host_record',
            description='COMP_HOSTS_MANAGER host-selection records: competition, three year fields, code '
                        'bytes and list sizes; meanings not decoded.',
            columns=[Column('slot', 'INTEGER', 'position in COMP_HOSTS_MANAGER +0x08'),
                     Column('competition_idx', 'INTEGER', 'competition (record +0x48)', references='competition'),
                     Column('year_1', 'INTEGER', 'record +0x58 u16'), Column('year_2', 'INTEGER', 'record +0x5A u16'),
                     Column('year_3', 'INTEGER', 'record +0x5C u16'),
                     *[Column(f'code_{i}', 'INTEGER', f'record +{0x5E + i - 1:#x} byte') for i in range(1, 6)],
                     Column('entries', 'INTEGER', 'size of the record +0x00 pointer vector'),
                     Column('ranks', 'INTEGER', 'size of the record +0x30 vector (8-byte entries)')],
            rows=lambda: _host_rows(engine), mode='lazy', invalidation='content',
            fingerprint=lambda: _const_fingerprint(engine, _host_rows), indexes=('competition_idx',),
            source_note='global 0x56BF8D0 (sicomps::COMP_HOSTS_MANAGER, vtable 0x566CFB0) +0x08; direct reads',
            manager=never, cost_note='under 0.1 s'),
        SourceTable(
            name='comp_host_nation',
            description='NATION lists of the COMP_HOSTS_MANAGER +0x20 and +0x38 records; meanings not decoded.',
            columns=[Column('list_offset', 'INTEGER', 'manager vector the record is in (32 = +0x20, 56 = +0x38)'),
                     Column('record', 'INTEGER', 'record position in that vector'),
                     Column('position', 'INTEGER', 'position in the record +0x18 NATION vector'),
                     Column('nation_idx', 'INTEGER', 'nation', references='nation'),
                     Column('flags', 'INTEGER', 'record +0x30 u16')],
            rows=lambda: _host_nation_rows(engine), mode='lazy', invalidation='content',
            fingerprint=lambda: _const_fingerprint(engine, _host_nation_rows), indexes=('nation_idx',),
            source_note='global 0x56BF8D0 +0x20 / +0x38 records (0x50 bytes), +0x18 vector of NATION pointers',
            manager=never, cost_note='under 0.1 s'),
        SourceTable(
            name='match_momentum_weight',
            description='MATCH_MOMENTUM_MANAGER table: 48 (code a, code b, code c, value) entries.',
            columns=[Column('slot', 'INTEGER', 'position'), Column('code_a', 'INTEGER', 'byte 0 (not decoded)'),
                     Column('code_b', 'INTEGER', 'byte 1 (not decoded)'),
                     Column('code_c', 'INTEGER', 'byte 2 (0, 1, 2 in every triple; byte 3 is padding)'),
                     Column('value', 'INTEGER', 'i32 at +4')],
            rows=lambda: _momentum_rows(engine), mode='lazy', invalidation='content',
            fingerprint=lambda: _const_fingerprint(engine, _momentum_rows),
            source_note='global 0x56A66E0 (vtable 0x56A06E8) +0x08 vector of 8-byte entries; identical at half '
                        'time of a match (ht1 capture) and between matches',
            manager=never, cost_note='one read'),
        SourceTable(
            name='match_rating_weight',
            description='MATCH_PLAYER_RATINGS_MANAGER entries: 22 float multipliers each, with counters.',
            columns=[Column('entry', 'INTEGER', 'entry (0..2)'), Column('position', 'INTEGER', 'float position'),
                     Column('value', 'REAL', 'float at +0x30 + 4 * position'),
                     Column('count', 'INTEGER', 'entry +0x28 u64 (40 in each)'),
                     Column('vector_a_bytes', 'INTEGER', 'entry +0x00 vector size in bytes'),
                     Column('vector_b_bytes', 'INTEGER', 'entry +0x18 vector size in bytes'),
                     Column('code', 'INTEGER', 'entry +0x88 u32'),
                     Column('tail_hex', 'TEXT', 'entry +0x8C bytes')],
            rows=lambda: _rating_rows(engine), mode='lazy', invalidation='content',
            fingerprint=lambda: _const_fingerprint(engine, _rating_rows),
            source_note='global 0x56C35A0 (vtable 0x56A01C8) +0x08 vector of 0x90-byte entries; identical at half '
                        'time (ht1 capture) and between matches: model parameters, not per-match ratings',
            manager=never, cost_note='one read'),
        SourceTable(
            name='match_screen_team_stats',
            description='While a match is loaded: the team statistics the match screen shows (the engine\'s '
                        'GAME_MATCH_STATS, which MATCH_UI_HANDLER reads). Unavailable when no match is loaded.',
            columns=[Column('client', 'INTEGER', 'viewable client position'),
                     Column('side', 'INTEGER', 'side', enum={0: 'home', 1: 'away'}),
                     Column('team_idx', 'INTEGER', 'team', references='team'),
                     Column('date', 'TEXT', 'fixture date'),
                     Column('competition_idx', 'INTEGER', 'competition', references='competition'),
                     Column('shots', 'INTEGER', 'TotalShots (side +0x16F)'),
                     Column('shots_on_target', 'INTEGER', 'side +0x170'),
                     Column('expected_goals', 'REAL', 'ExpectedGoals (side +0x60)'),
                     Column('passes_attempted', 'INTEGER', 'side +0xD8'),
                     Column('passes_completed', 'INTEGER', 'side +0xDA'),
                     Column('corners', 'INTEGER', 'side +0x19D'),
                     Column('possession_time_raw', 'INTEGER', 'side +0x7C (units not decoded)')],
            rows=lambda: screen_stats_rows(engine.read, engine.base), mode='lazy', invalidation='content',
            fingerprint=lambda: _screen_fingerprint(engine), check_interval=0,
            source_note='client manager 0x56A6AD8 -> client +0xF8 -> +0x18 GAME_MATCH -> +0x14E90 GAME_MATCH_STATS '
                        '(MATCH_UI_HANDLER +0x108 = 0x2A0D04 -> 0x48E6DF8), sides +0x68/+0x70 decoded by the '
                        'hand-built live_match_performance',
            manager=public, cost_note='a few reads; only while a match is loaded'),
        SourceTable(
            name='match_momentum',
            description='While a match is loaded: the momentum series the match screen draws (MatchMomentum), '
                        'one row per 5-minute segment, with the value each side is shown.',
            columns=[Column('client', 'INTEGER', 'viewable client position'),
                     Column('segment', 'INTEGER', 'segment (0 = first 5 minutes)'),
                     Column('end_tick', 'INTEGER', 'segment end in engine ticks (240 a minute; the second half '
                            'starts at 10,800)'),
                     Column('end_minute', 'REAL', 'segment end in minutes'),
                     Column('home_value', 'REAL', 'momentum shown for side 0 (the series value)'),
                     Column('away_value', 'REAL', 'momentum shown for side 1 (the negation, 0x4899980)'),
                     Column('match_idx', 'INTEGER', 'the match (match.idx: YYYYMMDD * 100000 + home team idx); '
                            'match has the row once the game archives the result', references='match'),
                     Column('date', 'TEXT', 'fixture date')],
            rows=lambda: _momentum_series_rows(engine), mode='lazy', invalidation='content',
            fingerprint=lambda: _rating_fingerprint(engine), check_interval=0,
            source_note='MATCH_UI_HANDLER MatchMomentum (0x29B034) -> 0x299B5C: 0x4898A94(momentum manager '
                        '0x56A66E0, engine +0x14A58 +0x440 event store) emulated (bytes pinned); 8-byte segments '
                        '<f32 value, u32 end tick>; side 1 sees -value (0x4899854)',
            manager={'scope': 'public', 'reason': 'shown on the match screen of the match being played'},
            cost_note='one emulated call (about 0.1 s); only while a match is loaded'),
        SourceTable(
            name='match_rating_component',
            description='While a match is loaded: each player\'s match rating split into the terms the game\'s '
                        'rating updater (0x4560B60) adds, with the count of each. SUM(contribution) per player is the '
                        'recomputed rating. Archived matches keep only the final rating.',
            columns=[Column('client', 'INTEGER', 'viewable client position'),
                     Column('side', 'INTEGER', 'side', enum={0: 'home', 1: 'away'}),
                     Column('slot', 'INTEGER', 'player slot in the side (0..25)'),
                     Column('person_idx', 'INTEGER', 'player', references='person'),
                     Column('team_idx', 'INTEGER', 'team', references='team'),
                     Column('term', 'TEXT', 'term key (base, rounding, or a weight-row term)'),
                     Column('label', 'TEXT', 'name of the term (name_source says where it comes from)'),
                     Column('count', 'INTEGER', 'the input the weight multiplies (a count, or the formula input)'),
                     Column('contribution', 'REAL', 'rating points this term adds (after the result multiplier)'),
                     Column('stored_rating', 'REAL', 'rating the match screen shows (MATCH_PLAYER +0x1D58 / 1000)'),
                     Column('recomputed_rating', 'REAL', 'rating the updater gives now (sum of contribution)'),
                     Column('multiplier', 'REAL', 'result-expectation multiplier applied to the summed terms'),
                     Column('minutes', 'REAL', 'minutes counted in positions'),
                     Column('name_source', 'TEXT', 'game key or string the label comes from, or inferred'),
                     Column('match_idx', 'INTEGER', 'the match (match.idx: YYYYMMDD * 100000 + home team idx); '
                            'match has the row once the game archives the result', references='match'),
                     Column('date', 'TEXT', 'fixture date')],
            rows=lambda: _rating_component_rows(engine), mode='lazy', invalidation='content',
            fingerprint=lambda: _rating_fingerprint(engine), check_interval=0, indexes=('person_idx', 'match_idx'),
            source_note='MATCH_PLAYER objects of the loaded GAME_MATCH (engine +0x15370/+0x15378, side +0x140); the '
                        'updater 0x4560B60 mirrored in fmdb/match_rating.py (bytes pinned), equal to emulating it',
            manager={'scope': 'public', 'reason': 'ratings and the statistics they are made from are shown on the '
                                                  'match screen of the match being played'},
            cost_note='about 0.2 s; only while a match is loaded'),
        SourceTable(
            name='native_manager',
            description='Match-day, match-engine and competition-service managers: root route, class check and '
                        'the byte size of each vector they hold.',
            columns=[Column('name', 'TEXT', 'class'), Column('route', 'TEXT', 'global RVA and member offsets'),
                     Column('vtable', 'TEXT', 'vtable RVA checked'), Column('base_vtable', 'TEXT', 'base-class vtable'),
                     Column('state', 'TEXT', 'resident, root empty, or why not'),
                     Column('vectors_json', 'TEXT', '{header offset: bytes} for vector headers in the first 0x100 bytes')],
            rows=lambda: _manager_rows(engine), mode='lazy', invalidation='content',
            fingerprint=lambda: _const_fingerprint(engine, _manager_rows),
            source_note='direct reads of each root; vtable compared before any read', manager=never,
            cost_note='under 0.1 s'),
    ]
