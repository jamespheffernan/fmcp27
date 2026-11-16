"""Inbox (NEWS_ITEM, type 70), calendar (CALENDAR, type 9) and fixture (FIXTURE, type 50) recipes.

All three run the shipped UI handler code in `UiHandlerVM` on copied live memory (nothing is
written to the game). Addresses are RVAs in the arm64 game_plugin of build 27.0.0.2493426;
docs/fmdb/UI_NEWS.md records how each was established.

Inbox. The human manager's inbox is HUMAN+0x350 -> {begin, end, cap} of NEWS_ITEM pointers,
sorted by the item's unique id (u32 at +0x90); the server's own lookup is 0x142273C(unid,
inbox) from NEWS_ITEM_UI_HANDLER_SERVER slot 2 (0x2D0618), which reaches the HUMAN through
'huma' (people-table index) -> 0x106696C -> PERSON vtable+0x6F0. Every news item in the game
(5k+) is in NEWS_MANAGER (global 0x56A5908) +0xB8, also sorted by unid (0x28FF324). An item's
u16 flags are at +0x98 (server key 'Nfla'); bit 0 is the read flag shown as
NewsItemHasBeenRead ('G0xt'). Each item is read through handler type 70 with the UI_RECORD
{'huma': person index, 'unid': unique id}.

Calendar. CALENDAR_UI_HANDLER_SERVER slot 2 (0x97ADC) reads the record keys 'Hhum' (0x71248,
people-table UI id) and 'Team' (0x71254, team UI id; not 'Ttea'), plus per-request parameters
from its context bag (x3). Key 'UIww' with context {'nMzT': SI_DATE} returns the two calendar
weeks starting at the Monday of that date: {'GenE': [events], 'stDT', 'enDT'}; the events come
from 0x12ED77C -> current GAME_HUMAN vtable+0xF8 (0x203D3B8) with flags 0x1FF7FFE.

Fixtures. A calendar fixture event carries 'FRfr' = {'dref': 0x35 << 24 | team index,
'dcnt': SI_DATE}; the UI object resolver 0x111344C turns that pair into a FIXTURE_RECORD
whose +0x18 is the db FIXTURE (home +0x08, away +0x10, fixture name +0x20, stadium +0x28,
packed date +0x4C, as fm_live_mcp.fixtures reads it).

Generic client read with inputs (`declared_get`): the client's get_property (slot 4) reads
server values from its fourth argument, a property bag. The client says which inputs a key
needs through slot 16 (request, declarations): groups of 0x48 bytes {params bag, client
params bag, sorted u32 keys}. The server computes each key with that params bag as context
(slot 2 x3); the values go into one bag passed to slot 4. FIXTURE needs this.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, timedelta
import re
import struct
import time

from . import ui_registry, variant
from .ui_handlers import HandlerReading, Reading, plain_text, read_handler
from .ui_vm import (CLIENT_GET_SLOT, REQUEST_KEY_OFFSET, REQUEST_SIZE, UiHandlerVM, UiRecord,
                    fourcc, fourcc_text, object_id)
from .vm import Unavailable, _Stop

NEWS_ITEM, CALENDAR, FIXTURE = 70, 9, 50

HUMAN_INBOX_OFFSET = 0x350          # HUMAN -> inbox {begin, end, cap} of NEWS_ITEM*
NEWS_MANAGER_RVA = 0x56A5908        # NEWS_MANAGER*; +0xB8 every news item, sorted by unid
NEWS_MANAGER_ITEMS = 0xB8
NEWS_DATE_OFFSET = 0x88             # packed date (sources.live_state reads the same field)
NEWS_UNID_OFFSET = 0x90
NEWS_FLAGS_OFFSET = 0x98
NEWS_READ_FLAG = 0x0001
PERSON_HUMAN_OFFSET = 0x548         # HUMAN_NON_PLAYER: embedded PERSON; its index at +8
PEOPLE_TABLE = 1

RESOLVE_RVA = 0x111344C             # UI object id {u32 id, pad, typed extra} -> object
SI_DATE_TRAITS_RVA = 0x56D5878      # fmdate::SI_DATE_TYPED_TRAITS singleton (0x42F038C)
CLIENT_DECLARE_SLOT = 16
CLIENT_SERVER_KEYS_SLOT = 14        # (this, request, out sorted u32 vector of server keys)
DECLARATION_SIZE = 0x48             # {params bag 0x18, client params bag 0x18, u32 key vector}
BAG_ENTRY = 16                      # property bag entry {u32 key, pad, typed*}

FIXTURE_RECORD_FIXTURE = 0x18       # FIXTURE_RECORD -> db FIXTURE
FIXTURE_HOME, FIXTURE_AWAY, FIXTURE_NAME, FIXTURE_STADIUM, FIXTURE_DATE = 0x08, 0x10, 0x20, 0x28, 0x4C
FIXTURE_REF_TABLE = 0x35

CALENDAR_WINDOW_KEY = 'UIww'        # two weeks from the Monday of context 'nMzT'
CALENDAR_DATE_PARAM = 'nMzT'
CALENDAR_WINDOW_DAYS = 14
NAME_KEY = 'dbnm'                   # database record name (TEAM, COMP, CLUB, STADIUM, PERSON...)

# Event class 'clEv' as observed: 0 fixture, 1 competition calendar date, 17 training day,
# 5 = league transfer-window dates (inferred: Premier League, 1 Jan and 3 Feb with kickoff
# code 69 = 23:00). Competition 'type' codes are not labelled by the server; the inferences in
# COMPETITION_TYPES come from the stage and date of each observed event (see UI_NEWS.md).
EVENT_CLASSES = {0: 'fixture', 1: 'competition', 5: 'transfer_window', 17: 'training'}
COMPETITION_TYPES = {0: 'stage_match_date', 3: 'draw', 4: 'registration_deadline',
                     23: 'round_scheduled_date'}
VENUES = {1: 'home', 2: 'away'}      # 'FxVn' (agrees with 'iSHo'); other codes reported raw

# NEWS_ITEM_UI_HANDLER keys read by default (47 exist; keys='all' reads every one).
NEWS_KEYS = ('titl', 'AJ15', 'OcAz', 'body', 'CqMA', '77MG', 'G0xt', 'WPMe', '4BcE', 'nips',
             '5kio', 'MedS', 'vWWt', '9gog', 'gdp5', 'JKwa', 'lR0V', 'twYr', '8C2l', 'apN1',
             'unid', 'HvMt', 'yXAm', 'Bub]')
# what a list row shows: subject (title or headline), subtitle, date and time sent
NEWS_HEAD_KEYS = ('titl', 'AJ15', 'OcAz', 'CqMA', '77MG')


# ---------------------------------------------------------------------- pure helpers
def si_date(day: date, low: int = 0) -> int:
    """fmdate SI_DATE payload: year << 17 | day of year << 8 | low 7 bits (kickoff code)."""
    if not 0 <= low < 128:
        raise ValueError('SI_DATE low bits out of range')
    return day.year << 17 | day.timetuple().tm_yday << 8 | low


def si_date_parts(payload: int):
    """(date, low) from an SI_DATE payload; None for the 1900-01-01 'no date' value."""
    year, doy, low = payload >> 17, (payload >> 8) & 0x1FF, payload & 0xFF
    if year == 1900 and doy == 1 or not doy:
        return None
    return date(year, 1, 1) + timedelta(days=doy - 1), low


def packed_from_si(payload: int) -> int:
    """SI_DATE payload -> the in-memory date struct as u32 (year << 16 | low << 9 | doy)."""
    return (payload >> 17) << 16 | (payload & 0x7F) << 9 | (payload >> 8) & 0x1FF


def kickoff(payload: int):
    """Kickoff time of a fixture date, decoded as fm_live_mcp.fixtures does."""
    from ..fixtures import kickoff_time
    return kickoff_time(packed_from_si(payload))


def typed_bytes(traits: int, payload: int) -> bytes:
    return struct.pack('<QQ', traits, payload & 0xFFFFFFFFFFFFFFFF)


def bag_bytes(at: int, entries) -> bytes:
    """A property bag placed at `at`: {begin, end, cap} then 16-byte {u32 key, pad, typed*}."""
    body = b''.join(struct.pack('<IIQ', fourcc(k) if isinstance(k, str) else k, 0, typed)
                    for k, typed in entries)
    begin = at + 24
    return struct.pack('<QQQ', begin, begin + len(body), begin + len(body)) + body


def parse_declarations(read, list_address):
    """Client slot 16 output: [(params bag address, client params bag address, [keys])]."""
    begin, end = struct.unpack('<QQ', read(list_address, 16))
    if end < begin or (end - begin) % DECLARATION_SIZE or end - begin > 64 * DECLARATION_SIZE:
        raise ValueError('implausible input declaration list')
    out = []
    for group in range(begin, end, DECLARATION_SIZE):
        kb, ke = struct.unpack('<QQ', read(group + 0x30, 16))
        if ke < kb or (ke - kb) % 4 or ke - kb > 4 * 256:
            raise ValueError('implausible declared key vector')
        keys = struct.unpack(f'<{(ke - kb) // 4}I', read(kb, ke - kb)) if ke > kb else ()
        out.append((group, group + 0x18, [fourcc_text(k) for k in keys]))
    return out


LINK = re.compile(r'\x01([A-Za-z0-9+/=]*)\x02([^\x01]*)\x01')


def links(text):
    """Link markup in a UI string -> [{'text', 'record'}]; record is {fourcc: u32} when the
    base64 payload is a run of (u32 printable FourCC, u32 value) pairs, else the raw base64
    (the game's own link payloads are a serialised record format that is not decoded here)."""
    if not isinstance(text, str):
        return []
    out = []
    for payload, shown in LINK.findall(text):
        record = payload
        try:
            raw = base64.b64decode(payload)
            if raw and len(raw) % 8 == 0:
                pairs = struct.unpack(f'<{len(raw) // 4}I', raw)
                keys = [fourcc_text(pairs[i]) for i in range(0, len(pairs), 2)]
                if all(k.isprintable() for k in keys):
                    record = dict(zip(keys, pairs[1::2]))
        except (ValueError, struct.error):
            pass
        out.append({'text': shown, 'record': record})
    return out


def ui_id_parts(value):
    """(table type, index) of a UI object id; None for the 'no object' id."""
    if value is None:
        return None
    value &= 0xFFFFFFFF
    table, index = value >> 24, value & 0x7FFFFF
    if table == 0xFF or index == 0x7FFFFF:
        return None
    return table, index


def dref(value):
    """The u32 UI object id inside a decoded reference ({'dref': id} or UiRecord)."""
    if isinstance(value, dict) and 'dref' in value and isinstance(value['dref'], int):
        return value['dref'] & 0xFFFFFFFF
    return None


def _event_date(value):
    """(ISO date, low bits) of a decoded SI_DATE value."""
    out = variant.to_json(value)
    if isinstance(out, dict):
        return out.get('date'), out.get('low', 0)
    return out, 0


# ---------------------------------------------------------------------- VM plumbing
def open_vm(session, rng='copy') -> UiHandlerVM:
    """A UiHandlerVM over a fmdb.live.LiveSession (cached on the session)."""
    vm = getattr(session, '_ui_news_vm', None)
    if vm is None:
        from .image import PluginImage
        from .memory import LiveMemory
        from .ui_vm import lsof_resolver
        image = PluginImage.load(session.plugin_path)
        vm = UiHandlerVM(LiveMemory(session.pid), session.base, image,
                         file_resolver=lsof_resolver(session.pid), rng=rng)
        vm.fast()
        session._ui_news_vm = vm
    return vm


def as_vm(vm_or_session) -> UiHandlerVM:
    return vm_or_session if isinstance(vm_or_session, UiHandlerVM) else open_vm(vm_or_session)


@dataclass(frozen=True)
class Viewer:
    human: int            # HUMAN_NON_PLAYER (manager) address
    person_index: int     # people-table index ('huma'; 'Hhum' = object_id(1, index))
    team: int             # managed TEAM address
    current_date: str


def viewer(vm: UiHandlerVM, coach=0) -> Viewer:
    from .. import world
    record, _ = world.loaded(world.ReadSet(vm.reader.read), vm.base)
    row = record['coaches'][coach]
    human = row['manager_address']
    index = struct.unpack('<I', vm.reader.read(human + PERSON_HUMAN_OFFSET + 8, 4))[0]
    return Viewer(human, index, row['team_address'], record['current_date'])


def place(vm: UiHandlerVM, data: bytes) -> int:
    return vm.heap_bytes(data)


def si_value(vm: UiHandlerVM, payload: int) -> int:
    """A SI_DATE typed value on the VM heap."""
    return vm.heap_bytes(typed_bytes(vm.base + SI_DATE_TRAITS_RVA, payload))


def place_bag(vm: UiHandlerVM, entries) -> int:
    """A property bag on the VM heap from [(key, typed address)]."""
    at = vm.alloc(24 + BAG_ENTRY * max(1, len(entries)))
    vm.uc.mem_write(at, bag_bytes(at, entries))
    return at


def resolve(vm: UiHandlerVM, ui_id: int, extra_date: int | None = None) -> int:
    """UI object id -> object address through the game's resolver (0 when unresolved).
    Fixture references (table 0x35) need their date as the typed extra ('dcnt')."""
    vm.reset()
    extra = (typed_bytes(vm.base + SI_DATE_TRAITS_RVA, extra_date) if extra_date is not None
             else typed_bytes(vm.registry + 8, 0))
    buf = vm.heap_bytes(struct.pack('<II', ui_id & 0xFFFFFFFF, 0) + extra)
    vm.commit()
    try:
        address, _ = vm.call(vm.base + RESOLVE_RVA, [buf])
    except _Stop:
        address = 0
    vm.reset()
    return address


def record_name(vm: UiHandlerVM, address: int):
    if not address:
        return None
    value = vm.get_property(address, NAME_KEY).value
    return value if isinstance(value, str) else None


class Names:
    """UI object id -> {'id', 'type', 'name'} with a per-call cache."""

    def __init__(self, vm):
        self.vm, self.cache = vm, {}

    def __call__(self, ui_id):
        if ui_id is None or ui_id_parts(ui_id) is None:
            return None
        if ui_id not in self.cache:
            address = resolve(self.vm, ui_id)
            self.cache[ui_id] = {'id': ui_id, 'type': self.vm.class_name(address) if address else None,
                                 'name': record_name(self.vm, address)}
        return self.cache[ui_id]


def declared_get(vm: UiHandlerVM, handler, code, *, context_values=None):
    """Client slot 4 for one key with the server inputs the client declares for it (slot 16).
    Returns (kind, value, {input key: status})."""
    number = fourcc(code)
    statuses = {}
    vm._restore()
    request = vm.alloc(REQUEST_SIZE)
    vm.uc.mem_write(request, b'\0' * REQUEST_SIZE)
    vm.uc.mem_write(request + REQUEST_KEY_OFFSET, struct.pack('<I', number))
    decl = vm.alloc(24)
    vm.uc.mem_write(decl, b'\0' * 24)
    needed = vm.alloc(24)
    vm.uc.mem_write(needed, b'\0' * 24)
    vm.commit()
    vm.vcall(handler.client, CLIENT_DECLARE_SLOT, (request, decl))
    vm.commit()
    vm.vcall(handler.client, CLIENT_SERVER_KEYS_SLOT, (request, needed))
    vm.commit()
    values = []
    groups = parse_declarations(vm.read, decl)
    begin, end = struct.unpack('<QQ', vm.read(needed, 16))
    if end < begin or (end - begin) % 4 or end - begin > 4 * 1024:
        raise _Stop('implausible server key vector', hex(end - begin))
    plain = [fourcc_text(k) for k in struct.unpack(f'<{(end - begin) // 4}I', vm.read(begin, end - begin))] \
        if end > begin else []
    if plain:
        groups.append((0, 0, plain))
    for params, _client_params, keys in groups:
        for key in keys:
            try:
                _, out, _ = vm.server_value(handler, key, context=params)
                vm.commit()
                values.append((key, out))
                statuses[key] = 'ok'
            except _Stop as stop:
                vm.reset_to_last()
                statuses[key] = f'unavailable: {stop.reason} {stop.detail or ""}'.strip()
    bag = place_bag(vm, values)
    out = vm.alloc(16)
    vm.uc.mem_write(out, struct.pack('<QQ', vm.registry + 8, 0))
    vm.commit()
    try:
        returned, _ = vm.vcall(handler.client, CLIENT_GET_SLOT, (request, out, bag))
    except _Stop as stop:
        vm.reset_to_last()
        return None, Unavailable(stop.reason, detail=stop.detail), statuses
    kind, value = vm.decode(out)
    vm.reset_to_last()
    return kind, value, statuses


# ---------------------------------------------------------------------- inbox
@dataclass(frozen=True)
class InboxEntry:
    address: int
    unid: int
    news_class: str | None
    flags: int
    date: str | None = None      # stored date of the item (+0x88)

    @property
    def read(self):
        return bool(self.flags & NEWS_READ_FLAG)


def inbox_entries(vm: UiHandlerVM, human: int):
    """The human's inbox, newest (highest unique id) first."""
    read = vm.reader.read
    inbox = struct.unpack('<Q', read(human + HUMAN_INBOX_OFFSET, 8))[0]
    if not inbox:
        return []
    begin, end = struct.unpack('<QQ', read(inbox, 16))
    if end < begin or (end - begin) % 8 or end - begin > 8 * 100_000:
        raise ValueError('implausible inbox vector')
    pointers = struct.unpack(f'<{(end - begin) // 8}Q', read(begin, end - begin)) if end > begin else ()
    from .sources._common import packed_date
    out = []
    for item in pointers:
        raw = read(item + NEWS_DATE_OFFSET, NEWS_FLAGS_OFFSET + 2 - NEWS_DATE_OFFSET)
        day, unid, flags = struct.unpack_from('<I', raw, 0)[0], struct.unpack_from('<I', raw, 8)[0], \
            struct.unpack_from('<H', raw, 16)[0]
        out.append(InboxEntry(item, unid, vm.class_name(item), flags, packed_date(day)))
    unids = [e.unid for e in out]
    if unids != sorted(unids):
        raise ValueError('inbox is not sorted by unique id (layout changed)')
    return out[::-1]


def news_item(vm: UiHandlerVM, person_index: int, unid: int, keys=NEWS_KEYS) -> HandlerReading:
    """NEWS_ITEM handler (type 70) for one item: record {'huma', 'unid'}."""
    return read_handler(vm, NEWS_ITEM, {'huma': person_index, 'unid': unid},
                        keys=None if keys == 'all' else keys)


def shape_news(entry: InboxEntry, reading: HandlerReading, names=None, registry=None):
    """One inbox row from an entry and its NEWS_ITEM reading (pure apart from `names`)."""
    registry = registry or ui_registry.default()
    raw = {r.code: r.value for r in reading.readings}

    def text(code):
        value = raw.get(code)
        return plain_text(value) if isinstance(value, str) else None

    def ok(code):
        value = raw.get(code)
        return None if isinstance(value, Unavailable) else value

    day, _ = _event_date(ok('CqMA'))
    refs = []
    action = ok('8C2l')
    if isinstance(action, dict):
        for item in action.get('3Sd ') or ():
            target = dref(item.get('0JJ4')) if isinstance(item, dict) else None
            if target is not None:
                refs.append(names(target) if names else {'id': target})
    sender = dref(ok('nips'))
    media = dref(ok('MedS'))
    sender_team = dref(ok('5kio'))
    body_raw = raw.get('body') if isinstance(raw.get('body'), str) else None
    row = {
        'unid': entry.unid,
        'news_class': entry.news_class,
        'date': day,
        'time_sent': ok('77MG'),
        'subject': text('titl') or text('AJ15'),
        'headline_subtitle': text('OcAz'),
        'body': text('body'),
        'body_links': links(body_raw),
        'read': ok('G0xt') if isinstance(ok('G0xt'), bool) else entry.read,
        'read_flag': entry.read,
        'important': ok('WPMe'),
        'priority': ok('4BcE'),
        'action': ok('gdp5'),
        'can_respond': ok('JKwa'),
        'has_responded': ok('lR0V'),
        'deadline': text('twYr'),
        'sender': names(sender) if names and sender is not None else sender,
        'sender_team': names(sender_team) if names and sender_team is not None else sender_team,
        'media_source': names(media) if names and media is not None else media,
        'media_category': ok('vWWt'),
        'tags': ok('9gog'),
        'induction': ok('apN1'),
        'references': refs,
        'age': ok('Bub]'),
    }
    row['labels'] = {registry.label(r.code) or r.code: variant.to_json(plain_text(r.value))
                     for r in reading.readings}
    row['unavailable'] = {r.code: r.value.reason for r in reading.readings
                          if isinstance(r.value, Unavailable)}
    # A failed 'NewI' input (the item's serialised snapshot) leaves every display key unset.
    row['input_failures'] = {k: v for k, v in (reading.inputs or {}).items() if not v.startswith('ok')}
    return row


def inbox(vm_or_session, limit=50, unread_only=False, *, keys=NEWS_KEYS, resolve_names=True,
          coach=0):
    """The human manager's inbox, newest first, read through NEWS_ITEM_UI_HANDLER.

    Each row: unid, news_class, date, time_sent, subject, headline_subtitle, body (display text),
    body_links, read, important, priority, action, can_respond, has_responded, deadline, sender,
    sender_team, media_source, media_category, tags, references, age, labels (every key read,
    by registry label), unavailable, seconds, rng_uses."""
    vm = as_vm(vm_or_session)
    view = viewer(vm, coach)
    entries = inbox_entries(vm, view.human)
    if unread_only:
        entries = [e for e in entries if not e.read]
    names = Names(vm) if resolve_names else None
    rows = []
    for entry in entries[:limit]:
        started, rng = time.perf_counter(), vm.rng_uses
        reading = news_item(vm, view.person_index, entry.unid, keys)
        row = shape_news(entry, reading, names)
        row['inputs'] = reading.inputs
        row['seconds'] = round(time.perf_counter() - started, 3)
        row['rng_uses'] = vm.rng_uses - rng
        rows.append(row)
    return rows


# ---------------------------------------------------------------------- calendar
def calendar_handler(vm: UiHandlerVM, view: Viewer, team_id: int):
    return vm.build(CALENDAR, {'Hhum': object_id(PEOPLE_TABLE, view.person_index), 'Team': team_id})


def calendar_window(vm: UiHandlerVM, handler, start: date):
    """Server 'UIww' for the two weeks from the Monday of `start` -> decoded record."""
    vm._restore()
    value = si_value(vm, si_date(start))
    bag = place_bag(vm, [(CALENDAR_DATE_PARAM, value)])
    vm.commit()
    _, out, _ = vm.server_value(handler, CALENDAR_WINDOW_KEY, context=bag)
    kind, decoded = vm.decode(out)
    vm.reset_to_last()
    if kind != 'record' or not isinstance(decoded, dict):
        raise _Stop('calendar window did not decode as a record', str(kind))
    return decoded


def event_key(event):
    """Identity of a calendar event across overlapping windows."""
    day, low = _event_date(event.get('date'))
    return (event.get('clEv'), day, low, event.get('type'), dref(event.get('Ttea')),
            dref(event.get('Topp')), dref(event.get('comp')), dref(event.get('sbsn')),
            dref(event.get('mnsn')), tuple(event.get('Szio') or ()))


def shape_event(event, names=None, fixture_detail=None):
    """One calendar row from a decoded 'GenE' event record (pure apart from the callbacks)."""
    day, low = _event_date(event.get('date'))
    cls = event.get('clEv')
    row = {'kind': EVENT_CLASSES.get(cls, f'class_{cls}'), 'date': day, 'event_class': cls}
    name = (lambda v: names(v) if names and v is not None else v)
    if cls == 0:
        payload = si_date(date.fromisoformat(day), low) if day else None
        venue = event.get('FxVn')
        row.update({
            'kickoff': kickoff(payload) if payload is not None else None,
            'competition': name(dref(event.get('comp'))),
            'fixture_name': name(dref(event.get('FxNm'))),
            'team': name(dref(event.get('Ttea'))),
            'opponent': name(dref(event.get('Topp'))),
            'venue': VENUES.get(venue, venue),
            'is_home': event.get('iSHo'),
            'human_controlled': event.get('HUCD'),
            'opponent_position': event.get('TpoN'),
            'fixture_ref': event.get('FRfr'),
        })
        if fixture_detail is not None:
            row.update(fixture_detail(event.get('FRfr')) or {})
    elif cls == 17:
        row['sessions'] = list(event.get('Szio') or ())
    else:
        row.update({
            'type': event.get('type'),
            'type_inferred': COMPETITION_TYPES.get(event.get('type')) if cls == 1 else None,
            'competition': name(dref(event.get('comp'))),
            'team': name(dref(event.get('Ttea'))),
            'stage': name(dref(event.get('sbsn'))),
            'main_stage': name(dref(event.get('mnsn'))),
            'Fmtd': event.get('Fmtd'),
            'crep': event.get('crep'),
            'CoII': event.get('CoII'),
            'date_low': low,
        })
    row['raw'] = variant.to_json(event)
    return row


def fixture_detail(vm: UiHandlerVM, reference):
    """Home, away and stadium of a calendar fixture ('FRfr') through the game's resolver."""
    target = dref(reference)
    day, low = _event_date((reference or {}).get('dcnt'))
    if target is None or day is None:
        return None
    record = resolve(vm, target, si_date(date.fromisoformat(day), low))
    if not record or vm.class_name(record) != 'FIXTURE_RECORD':
        return {'fixture': None}
    fixture = vm.read_u64(record + FIXTURE_RECORD_FIXTURE)
    if not fixture or vm.class_name(fixture) != 'FIXTURE':
        return {'fixture': None}
    home, away, stadium = (vm.read_u64(fixture + o) for o in (FIXTURE_HOME, FIXTURE_AWAY, FIXTURE_STADIUM))
    packed, = struct.unpack('<I', vm.read(fixture + FIXTURE_DATE, 4))
    return {'home_team': record_name(vm, home), 'away_team': record_name(vm, away),
            'stadium': record_name(vm, stadium), 'fixture_packed_date': packed}


def calendar(vm_or_session, team=None, days=60, *, start=None, resolve_names=True,
             fixture_details=True, coach=0):
    """Dated calendar events from `start` (default: the game date) for `days` days.

    `team`: TEAM address or UI team id (default: the managed team). Rows are sorted by date:
    fixtures (competition, team, opponent, venue home/away, kickoff, stadium, home/away team
    names), training days (session codes) and competition calendar dates (type code, stage)."""
    vm = as_vm(vm_or_session)
    view = viewer(vm, coach)
    if team is None:
        team = view.team
    team_id = team if team >> 32 == 0 else vm.object_ref(team)
    first = start or date.fromisoformat(view.current_date)
    last = first + timedelta(days=days)
    started, rng = time.perf_counter(), vm.rng_uses
    handler = calendar_handler(vm, view, team_id)
    seen, events, windows = set(), [], 0
    cursor = first
    while cursor < last:
        window = calendar_window(vm, handler, cursor)
        windows += 1
        for event in window.get('GenE') or ():
            key = event_key(event)
            day = key[1]
            if key in seen or not day or not first.isoformat() <= day < last.isoformat():
                continue
            seen.add(key)
            events.append(event)
        cursor += timedelta(days=CALENDAR_WINDOW_DAYS)
    names = Names(vm) if resolve_names else None
    detail = (lambda ref: fixture_detail(vm, ref)) if fixture_details else None
    rows = [shape_event(e, names, detail) for e in events]
    rows.sort(key=lambda r: (r['date'], r['event_class'] != 0, r['kind']))
    meta = {'seconds': round(time.perf_counter() - started, 3), 'rng_uses': vm.rng_uses - rng,
            'windows': windows, 'team_id': team_id}
    for row in rows:
        row['_meta'] = meta
    return rows


def bridge_fixture_key(row):
    """(date, home team index, away team index) of a Bridge.find_fixtures row."""
    home, away = row.get('home_team') or {}, row.get('away_team') or {}
    return row['date'], home.get('database_index'), away.get('database_index')


def calendar_fixture_key(row):
    """(date, home team index, away team index) of a calendar fixture row."""
    team, opponent = row.get('team') or {}, row.get('opponent') or {}
    mine = ui_id_parts(team.get('id') if isinstance(team, dict) else team)
    theirs = ui_id_parts(opponent.get('id') if isinstance(opponent, dict) else opponent)
    mine, theirs = mine and mine[1], theirs and theirs[1]
    home, away = (mine, theirs) if row.get('is_home') else (theirs, mine)
    return row['date'], home, away


def cross_check_fixtures(calendar_rows, bridge_rows):
    """Compare calendar fixture rows with Bridge.find_fixtures rows field by field.

    Returns {'matched': [...], 'mismatched': [...], 'calendar_only': [...], 'bridge_only': [...]}
    where each matched/mismatched entry lists the compared fields and the differing ones."""
    bridge = {bridge_fixture_key(r): r for r in bridge_rows}
    out = {'matched': [], 'mismatched': [], 'calendar_only': [], 'bridge_only': []}
    used = set()
    for row in calendar_rows:
        if row.get('kind') != 'fixture':
            continue
        key = calendar_fixture_key(row)
        other = bridge.get(key)
        if other is None:
            out['calendar_only'].append(key)
            continue
        used.add(key)
        # The key already pins date and home/away orientation (team indexes on both sides).
        mine = {'kickoff': (row.get('kickoff') or {}).get('time'),
                'competition': (row.get('competition') or {}).get('name'),
                'stadium': row.get('stadium')}
        theirs = {'kickoff': (other.get('kickoff_time') or {}).get('time'),
                  'competition': (other.get('competition') or {}).get('name'),
                  'stadium': (other.get('stadium') or {}).get('name')}
        differs = {k: (mine[k], theirs[k]) for k in mine if mine[k] != theirs[k]}
        entry = {'key': key, 'calendar': mine, 'bridge': theirs, 'differs': differs}
        (out['mismatched'] if differs else out['matched']).append(entry)
    out['bridge_only'] = [k for k in bridge if k not in used]
    return out


# ---------------------------------------------------------------------- fixture handler
def fixture_record(home_id: int, away_id: int, payload: int) -> dict:
    """FIXTURE_UI_HANDLER(_SERVER) UI_RECORD: home/away team UI ids and SI_DATE 'fdte'
    (server lookup 0x207820 -> 0x3D1CFD0)."""
    return {'fhmT': home_id, 'fawT': away_id, 'fdte': payload}


def fixture(vm_or_session, home_id: int, away_id: int, payload: int, keys=None, registry=None):
    """FIXTURE handler (type 50) keys, each read with its declared server inputs."""
    vm = as_vm(vm_or_session)
    registry = registry or ui_registry.default()
    handler = vm.build(FIXTURE, fixture_record(home_id, away_id, payload))
    reading = HandlerReading(FIXTURE, handler.client_class, handler.server_class,
                             dict(handler.record), {}, build_seconds=handler.build_seconds)
    if keys is None:
        row = registry.classes.get(handler.client_class)
        keys = row.keys(4) if row else ()
    for code in keys:
        started = time.perf_counter()
        try:
            kind, value, statuses = declared_get(vm, handler, code)
        except _Stop as stop:
            kind, value, statuses = None, Unavailable(stop.reason, detail=stop.detail), {}
        reading.readings.append(Reading(code, registry.label(code), kind, value,
                                        time.perf_counter() - started))
        for key, status in statuses.items():
            reading.inputs.setdefault(key, status)
    return reading


__all__ = ['inbox', 'calendar', 'fixture', 'inbox_entries', 'news_item', 'shape_news', 'NEWS_HEAD_KEYS',
           'shape_event', 'declared_get', 'resolve', 'Names', 'viewer', 'si_date',
           'si_date_parts', 'kickoff', 'bag_bytes', 'parse_declarations', 'links', 'UiRecord']
