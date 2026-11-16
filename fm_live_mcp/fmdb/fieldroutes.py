"""Where each editor field lives in a running career: a per-field route table.

The editor schema (`editor.fmf`) does not map one-to-one onto the live record getters. For every
(record type, FourCC) pair the getters left without a value (coverage run: 505 not claimed, 477
unset on every sampled record; plus every `unavailable` snapshot column) this module says which of
these is true, with the static and live evidence:

``live_route``      the field has a live counterpart under another key of the same record; the
                    snapshot asks that key (`alias`). Proven per route in `ROUTES`.
``sampling``        the getter answers it for some records: the coverage sample (25 records) or the
                    plan sample (12 records) had none. A census of 300 to 430 records per type found
                    values. The snapshot emulates it.
``starting_table``  only the getter of an editor ``db::STARTING_*`` table answers it (starting club
                    finances, loans, future transfers, past transfers, injuries ...). The game
                    consumes these tables when a career starts; every one has 0 records in a running
                    career (`starting_table_counts`). Where the live data exists elsewhere, `ROUTES`
                    names it.
``setter_only``     the key appears only in a record class's ``set_property`` (vtable slot 2), its
                    property list (slot 5) or the database-file loader, never in a getter.
``editor_only``     the key appears only in the in-game editor's own code (class ``EDITOR``) or in
                    database-change bookkeeping that no getter reaches.
``constructed_key`` the FourCC is not an immediate anywhere in the plugin: the editor builds it from
                    a row index (staff responsibilities ``RPnn``/``RJnn``) or never asks it live.
``claimed_unset``   a getter claims the key but every census record was unset or not claimed (the
                    save has no such data, e.g. tournaments not in this database).
``emulator``        the getter needs something the emulator refuses (random-number state, clock,
                    instruction budget); the "virtual" lane's work turns these into values.

Static evidence: `fourcc_sites` finds every FourCC built with ``movz/movk`` (and constants derived
with ``add/sub #imm``) in the pinned ARM64 ``__text``; `function_starts` maps sites to functions;
`function_roles` names each function by the vtable slots that point at it; `getter_closure` follows
``bl``/``b`` from every property getter (slot 3) and game-layer interceptor slot.

The data file `data/fieldroutes.json.gz` is written by `scripts/fmdb_field_routes.py`.

Language text: `language_text(translation_id)` is the one lookup of the shipped English language
table (``example.ltf``, the template of ``languages.fmf``) for other modules (the label ledger).
"""
from __future__ import annotations

import array
import bisect
from dataclasses import dataclass
from functools import lru_cache
import gzip
import json
from pathlib import Path
import re
import struct

FORMAT = 'fmdb-field-routes/1'
DATA = Path(__file__).with_name('data') / 'fieldroutes.json.gz'

CATEGORIES = ('live_route', 'sampling', 'starting_table', 'other_record', 'setter_only', 'editor_only',
              'constructed_key', 'claimed_unset', 'emulator', 'superseded')


# --------------------------------------------------------------------------- curated live routes
@dataclass(frozen=True)
class Route:
    kind: str            # alias: ask `key` of the same record | via_club: the team's club column | emulate
    key: str | None
    note: str
    unit: str = ''


ROUTES = {
    ('club', 'CcfE'): Route('alias', 'Ccfa', (
        'CLUB getter 0xE476C4 rewrites CcfE to Ccfa (0xE53D00) before asking the STARTING_CLUB_DEBT record; the '
        'CLUB getter answers Ccfa itself (catalog "Corporate Facilities")')),
    ('club', 'Ctbu'): Route('alias', 'Ctfc', (
        'Ctbu is answered only from STARTING_CLUB_DEBT (0x16E9CC8; 0 records in a career); the live transfer '
        'budget is the game-layer key Ctfc (catalog "Transfer Budget"), equal to the hand-built '
        'current_transfer_budget (club_finance.py) on every compared club'), 'GBP'),
    ('club', 'Crmb'): Route('alias', 'Cwrb', (
        'Crmb is answered only from STARTING_CLUB_DEBT; the live remaining wage budget is the game-layer key Cwrb '
        '(wage_budget.py: weekly budget less stored weekly spending), weekly like wage_budget (Cwwb)'), 'GBP/week'),
    ('club', 'CSbR'): Route('emulate', 'CSbR', (
        'the game layer (GAME_CLUB) answers CSbR for clubs with a full CLUB_FINANCE object; the 12-record plan '
        'sample had none, so the snapshot had marked it unavailable'), 'GBP'),
    ('team', 'Ctbu'): Route('via_club', 'Ctfc', 'TEAM getter does not claim it; read club.transfer_budget via '
                                                'team.club_idx (team record +0x30)'),
    ('team', 'Crmb'): Route('via_club', 'Cwrb', 'TEAM getter does not claim it; read '
                                                'club.remaining_player_wage_budget via team.club_idx'),
    # round 2 (editor2): nation transfer windows, answered only by the in-game editor's getter
    **{('nati', k): Route('alias', f'x:transfer_window_{k}', (
        f'no record getter claims {k}; the EDITOR getter 0x6710F0 answers it for a NATIONAL_TEAM_CONTAINER '
        f'(slot 8 type 9) from the game date and the nation\'s competitions: emulated on the nation\'s men\'s '
        f'container (natc NTCn = nation, PLgn 0); extras.DERIVED nati.transfer_window_{k}'), 'date')
       for k in ('cwsd', 'cwed', 'nwsd', 'nwed')},
}

# Keys whose live counterpart is not a getter key (or not found), with the next route to try.
NEXT_ROUTE = {
    ('club', 'CMWE'): 'only STARTING_CLUB_DEBT answers it; the finances UI handler reads a maximum wage '
                      '(UI keys FinanceDebugMaximumWage jWYJ, AdvisedMaxBasicWage gBHm): build that handler',
    ('club', 'Csry'): 'only STARTING_CLUB_DEBT answers it; hand-built club_stadium_rent.py reads the live rent',
    ('club', 'CssT'): 'database-file loader 0xDEAEC8 only; live special season tickets: club extension '
                      '(club+0x100) as financial_details.club_details reads season-ticket holders',
}


# Editor keys whose data the game keeps under a different editor field that reads (round 2, editor2 lane).
SUPERSEDED_NOTE = {
    'responsibility': (
        'legacy flat responsibility row (RPnn person / RJnn expected job): no view of editor.fmf lists it '
        '(club ui.xml and national team container ui.xml show only TCrs), the FourCC is never an immediate in the '
        'plugin __text and no lone "RP"/"RJ" high half is built either (movz/movk scan: only complete constants '
        'such as other RPxx keys). The live responsibilities are the TCrs list (items PUnI responsibility, PUnT '
        'team type, PUnP person, PUnJ expected job), which reads: snapshot club.responsibilities / '
        'national_team.responsibilities; hand-built club_staff_responsibilities.py reads the same club +0xB0 -> '
        '+0x48 vector'),
}


def superseded(record_type: str, code: str) -> str | None:
    """The note for an editor key superseded by another editor field that reads, or None."""
    if record_type in ('club', 'natc') and re.fullmatch(r'R[PJ]\d\d', code):
        return SUPERSEDED_NOTE['responsibility']
    return None


def route(record_type: str, code: str) -> Route | None:
    return ROUTES.get((record_type, code))


def alias(record_type: str, code: str) -> str | None:
    """The live key the snapshot asks instead of `code` (same record), or None."""
    r = ROUTES.get((record_type, code))
    return r.key if r is not None and r.kind == 'alias' else None


def emulate_anyway(record_type: str, code: str) -> bool:
    """True when a plan sample said 'getter does not handle' but the getter answers other records."""
    if (record_type, code) in ROUTES:
        return ROUTES[(record_type, code)].kind in ('alias', 'emulate')
    row = pairs().get(f'{record_type}.{code}')
    return bool(row and row.get('category') == 'sampling')


def reason(record_type: str, code: str) -> str | None:
    """One-line reason for a field with no live value, from the route table (None if not classified)."""
    r = ROUTES.get((record_type, code))
    if r is not None:
        return f'route {r.kind} {r.key}: {r.note}'
    sup = superseded(record_type, code)
    if sup:
        return f'superseded: {sup}'
    row = pairs().get(f'{record_type}.{code}')
    if not row:
        return None
    text = f"{row['category']}: {row['reason']}"
    nxt = NEXT_ROUTE.get((record_type, code))
    return f'{text}; next route: {nxt}' if nxt else text


@lru_cache(maxsize=1)
def _document() -> dict:
    try:
        with gzip.open(DATA, 'rt') as fh:
            return json.load(fh)
    except OSError:
        return {'pairs': {}, 'starting_tables': {}}


def pairs() -> dict:
    """{'<record type>.<code>': row} from the data file (category, reason, evidence, census counts)."""
    return _document().get('pairs', {})


def summary() -> dict:
    """Counts by (coverage outcome, category)."""
    out = {}
    for row in pairs().values():
        key = f"{row.get('coverage', 'value')}/{row['category']}"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


# --------------------------------------------------------------------------- static evidence
def _slice_words(image):
    lo, hi = image.text_range
    return lo, array.array('I', image.file_bytes(lo, hi - lo))


def function_starts(image) -> list[int]:
    """Function start RVAs from LC_FUNCTION_STARTS (ULEB128 deltas)."""
    m, off = image._map, image.slice_offset
    ncmds = struct.unpack_from('<I', m, off + 16)[0]
    cur = off + 32
    dataoff = datasize = None
    for _ in range(ncmds):
        cmd, size = struct.unpack_from('<II', m, cur)
        if cmd == 0x26:        # LC_FUNCTION_STARTS
            dataoff, datasize = struct.unpack_from('<II', m, cur + 8)
        cur += size
    if dataoff is None:
        raise ValueError('no LC_FUNCTION_STARTS')
    data = m[off + dataoff:off + dataoff + datasize]
    starts, addr, i = [], 0, 0
    while i < len(data):
        v = s = 0
        while True:
            b = data[i]
            i += 1
            v |= (b & 0x7F) << s
            s += 7
            if not b & 0x80:
                break
        if v == 0:
            break
        addr += v
        starts.append(addr)
    return starts


def _printable(v: int) -> bool:
    return all(0x20 <= c < 0x7F for c in v.to_bytes(4, 'big'))


def fourcc_sites(image, starts=None) -> dict[str, list[int]]:
    """{FourCC: [instruction RVAs]} for every printable 32-bit constant built in __text with
    movz/movk, a lone `movz #imm, lsl #16`, or add/sub #imm from such a constant (the compiler
    derives neighbouring keys this way: 'Cnag' + 6 = 'Cnam'). Register values reset at function starts."""
    lo, words = _slice_words(image)
    start_set = set(starts or function_starts(image))
    sites: dict[int, list[int]] = {}
    val, age = [None] * 32, [0] * 32

    def put(v, i):
        if _printable(v):
            sites.setdefault(v, []).append(lo + 4 * i)
    for i, w in enumerate(words):
        if (lo + 4 * i) in start_set:
            val = [None] * 32
        top = w & 0xFF800000
        if top == 0x52800000:                                   # movz w
            rd, hw, imm = w & 31, (w >> 21) & 3, (w >> 5) & 0xFFFF
            if hw == 0:
                val[rd], age[rd] = imm, i
            elif hw == 1:
                val[rd], age[rd] = imm << 16, i
                put(imm << 16, i)
            else:
                val[rd] = None
        elif top == 0x72800000:                                 # movk w
            rd, hw = w & 31, (w >> 21) & 3
            if hw == 1 and val[rd] is not None and val[rd] < 0x10000 and i - age[rd] <= 16:
                v = (((w >> 5) & 0xFFFF) << 16) | val[rd]
                val[rd], age[rd] = v, i
                put(v, i)
            else:
                val[rd] = None
        elif (w & 0xFF000000) in (0x11000000, 0x51000000):      # add/sub w, w, #imm
            rd, rn = w & 31, (w >> 5) & 31
            imm = ((w >> 10) & 0xFFF) << (12 * ((w >> 22) & 1))
            if rn != 31 and val[rn] is not None and val[rn] >= 0x10000 and i - age[rn] <= 400:
                v = (val[rn] + imm if (w & 0xFF000000) == 0x11000000 else val[rn] - imm) & 0xFFFFFFFF
                if rd != 31:
                    val[rd], age[rd] = v, i
                put(v, i)
            elif rd != 31:
                val[rd] = None
    return {v.to_bytes(4, 'big').decode('latin-1'): a for v, a in sites.items()}


def call_targets(words, lo: int, start: int, end: int) -> set[int]:
    """Direct bl/b targets of the function [start, end)."""
    out = set()
    for i in range((start - lo) // 4, (end - lo) // 4):
        w = words[i]
        if w & 0x7C000000 == 0x14000000:                        # b / bl imm26
            off = w & 0x3FFFFFF
            if off & 0x2000000:
                off -= 0x4000000
            out.add(lo + 4 * i + 4 * off)
    return out


INTERCEPTOR_CLASSES = ('GAME_PLAYER', 'GAME_PERSON', 'GAME_ACTUAL_NON_PLAYER', 'GAME_ACTUAL_PLAYER',
                       'GAME_HUMAN_NON_PLAYER', 'GAME_RETIRED_PERSON', 'GAME_CLUB', 'GAME_NATIONAL_TEAM_CONTAINER',
                       'GAME_TEAM_CONTAINER', 'GAME_COMP', 'GAME_STADIUM', 'GAME_AWARD', 'GAME_MEDIA_SOURCE',
                       'GAME_DB_RECORD', 'GAME_CONTINENT')


def function_roles(slots: dict) -> dict[int, list[str]]:
    """{function: roles} from {function: [(class, slot)]}: getter (slot 3 of a db:: class),
    starting_getter (slot 3 of db::STARTING_*), setter (slot 2), property_list (slot 5),
    game (slots 8+ of the 15 interceptor classes), editor (class EDITOR)."""
    roles = {}
    for fn, entries in slots.items():
        out = set()
        for name, slot in entries:
            if name == 'EDITOR':
                out.add('editor')
            elif name in INTERCEPTOR_CLASSES and slot >= 8:
                out.add('game')
            elif name.startswith('db::STARTING_') and slot == 3:
                out.add('starting_getter')
            elif name.startswith('db::') and not name.startswith('db::DATABASE_TABLE') and '::' not in name[4:]:
                out.add({3: 'getter', 2: 'setter', 5: 'property_list'}.get(slot, 'other'))
        if out:
            roles[fn] = sorted(out)
    return roles


def getter_closure(image, starts, roles, depth=3, roots=None) -> dict[int, str]:
    """{function: root role} reachable by bl/b from getters, starting getters and game slots (or from
    the given {function: role} roots)."""
    lo, words = _slice_words(image)
    ends = {s: e for s, e in zip(starts, starts[1:] + [image.text_range[1]])}
    seen = {}
    frontier = (list(roots.items()) if roots is not None else
                [(fn, r) for fn, rs in roles.items() for r in rs if r in ('getter', 'game', 'starting_getter')])
    for fn, r in frontier:
        seen.setdefault(fn, r)
    for _ in range(depth):
        nxt = []
        for fn, r in frontier:
            if fn not in ends:
                continue
            for t in call_targets(words, lo, fn, ends[fn]):
                if t in ends and t not in seen and not set(roles.get(t, ())) & {'setter', 'property_list', 'editor'}:
                    role = 'starting_getter' if 'starting_getter' in roles.get(t, ()) else r
                    seen[t] = role
                    nxt.append((t, role))
        frontier = nxt
    return seen


def static_evidence(code: str, sites: dict, starts: list, roles: dict, closure: dict, own: dict | None = None) -> dict:
    """Functions that build the FourCC and what they are. `own` is the closure of the record type's
    own class getters (plus the game layer): 'in_own' marks a key that getter chain compares."""
    fns = sorted({starts[bisect.bisect_right(starts, a) - 1] for a in sites.get(code, ())})
    kinds = set()
    for fn in fns:
        if own is not None and fn in own and own[fn] != 'starting_getter':
            kinds.add('in_own')
        if fn in closure:
            kinds.add('in_' + closure[fn])
        for r in roles.get(fn, ()):
            kinds.add(r)
        if fn not in closure and not roles.get(fn):
            kinds.add('other')
    return {'functions': [hex(f) for f in fns[:12]], 'function_count': len(fns), 'kinds': sorted(kinds)}


def starting_table_counts(engine, vtables: dict) -> dict[str, int]:
    """{STARTING_* class: live record count} for every db::DATABASE_TABLE<db::STARTING_*> singleton in
    the plugin's globals (0x56A0000..0x5740000), read uncached."""
    names = {v: n for n, v in vtables.items()}
    lo, hi = 0x56A0000, 0x5740000
    data = engine.read(engine.base + lo, hi - lo)
    out = {}
    for off in range(0, len(data), 8):
        p = struct.unpack_from('<Q', data, off)[0]
        if p < 1 << 32 or p % 8:
            continue
        try:
            vt = struct.unpack('<Q', engine.read(p, 8))[0] - engine.base
        except Exception:  # noqa: BLE001 - not a readable pointer
            continue
        name = names.get(vt, '')
        m = re.match(r'db::DATABASE_TABLE<db::(STARTING_\w+)>', name)
        if not m:
            continue
        header = struct.unpack('<Q', engine.read(p + 0x88, 8))[0]
        start, end, _ = struct.unpack('<QQQ', engine.read(header, 24))
        out[m.group(1)] = (end - start) // 8
    return out


def categorise(record_type: str, code: str, row: dict, starting: dict) -> tuple[str, str]:
    """(category, reason) for one pair from its evidence (see the module docstring)."""
    kinds = set(row.get('kinds', ()))
    census = row.get('census') or {}
    r = ROUTES.get((record_type, code))
    if r is not None and r.kind in ('alias', 'via_club'):
        return 'live_route', f'{r.kind} {r.key}: {r.note}'
    if r is not None and r.kind == 'emulate':
        return 'sampling', r.note
    if census.get('value'):
        n = sum(census.values())
        return 'sampling', (f"census: {census['value']} of {n} records give a value"
                            + (f' ({r.note})' if r is not None else ''))
    note = (row.get('snapshot') or {}).get('note', '')
    if not census and 'getter gave' in note:
        return 'emulator', f'snapshot plan sample: {note[:120]}'
    emu = {k: v for k, v in census.items() if k.startswith('unavailable:')}
    if emu and sum(emu.values()) >= sum(census.values()) * 0.5:
        top = max(emu, key=emu.get)[len('unavailable:'):]
        return 'emulator', f'getter needs {top} on {sum(emu.values())} of {sum(census.values())} census records'
    empty = ', '.join(f'{k} {v}' for k, v in sorted(starting.items()) if v == 0)
    if 'in_starting_getter' in kinds or 'starting_getter' in kinds:
        if not kinds & {'in_getter', 'in_game', 'getter', 'game'} or 'in_starting_getter' in kinds:
            return 'starting_table', (f"answered only through an editor STARTING_* table getter "
                                      f"({', '.join(row.get('functions', [])[:4])}); every STARTING_* table "
                                      f"has 0 records in this career")
    seen = ', '.join(f'{k} {v}' for k, v in sorted(census.items())) or 'no census'
    if 'in_own' in kinds:
        if census.get('unset') or not census:
            return 'claimed_unset', (f"the record's getter chain claims the key "
                                     f"({', '.join(row.get('functions', [])[:3])}) and returned no value; census: {seen}")
        return 'claimed_unset', (f"the record's getter chain compares the key ({', '.join(row.get('functions', [])[:3])}) "
                                 f"but did not claim it for any census record (guarded branch); census: {seen}")
    if kinds & {'in_getter', 'in_game'}:
        return 'other_record', (f"only getters of other record classes compare the key "
                                f"({', '.join(row.get('functions', [])[:4])}); this record's getter chain never does; "
                                f"census: {seen}")
    if kinds & {'setter', 'property_list'}:
        return 'setter_only', (f"only in set_property / property-list functions "
                               f"({', '.join(row.get('functions', [])[:4])}), no getter compares it")
    if 'editor' in kinds:
        return 'editor_only', f"only in the in-game editor (class EDITOR: {', '.join(row.get('functions', [])[:3])})"
    if superseded(record_type, code):
        return 'superseded', superseded(record_type, code)
    if not row.get('function_count'):
        if re.fullmatch(r'R[PJ]\d\d', code):
            return 'constructed_key', ('responsibility row key RPnn/RJnn is built from the row index by the editor; '
                                       'no getter forms it. Live rows: hand-built club_staff_responsibilities.py '
                                       '(club +0xB0 -> +0x48 vector)')
        return 'constructed_key', 'the FourCC is not an immediate anywhere in the plugin __text; no getter can claim it'
    return 'editor_only', (f"only in functions no property getter reaches "
                           f"({', '.join(row.get('functions', [])[:4])}): database-file loader or change log")


# --------------------------------------------------------------------------- language table
LTF_RELATIVE = Path('Contents/PlugIns/game_plugin.bundle/Contents/Resources/data/game_simulation/'
                    'templates/user_folder/languages/example.ltf')
from .. import build_paths  # noqa: E402

DEFAULT_APP = build_paths.installed_app()   # run time: the installed build (FMCP_PLUGIN_PATH)
_KEY = re.compile(r'^KEY-(\d+): ?(.*?)(?:\[COMMENT[^\]]*\])?\s*$')


@lru_cache(maxsize=2)
def _language(path: str) -> dict[int, str]:
    out = {}
    with open(path, encoding='utf-8-sig', errors='replace') as fh:
        for line in fh:
            if line.startswith('KEY-'):
                m = _KEY.match(line)
                if m:
                    out[int(m.group(1))] = m.group(2)
    return out


def language_text(translation_id: int, app: Path | None = None) -> str | None:
    """English text of a translation id from the shipped language template (`example.ltf`, the
    English source of `languages.fmf`); None when the id is not in the table. The first call parses
    the 155 MB file (a few seconds); later calls are dictionary lookups."""
    path = Path(app or DEFAULT_APP) / LTF_RELATIVE
    return _language(str(path)).get(int(translation_id))
