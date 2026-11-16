"""Screens read the way the front end asks for them (docs/fmdb/UI_FRONTEND.md).

The front end (GameAssembly + the UXML views in the ui-* asset bundles) binds named
parameters to every view (`{visionisusingperformancedata}{Bool|1|}` on the Club Vision
blocks, for example). The plugin turns them into data-key arguments in two steps, both
shipped code:

1. the client handler's slot 2 `(this, request, out bag)` looks each parameter up through
   0x77E228 and writes it into a bag under a data key (CLUB_UI_HANDLER 0xCA708:
   `visionisusingperformancedata` -> 'CVpe');
2. the database getters read those arguments from the plugin-wide UI context record at
   0x56D38C0 (a vector of {u32 key, typed*}; e.g. the CLUB getter 0x1FAF4D8 looks up 'CVpe'
   at 0x1FB9A88 and 'ytpe' / 'CVls' at 0x1FB3878). In live memory the record already holds a
   'CVpe' entry (null once the screen is closed), which is where the game keeps it.

`ContextReader` runs step 1 with the view's parameters and puts the resulting entries into
the context record (in the VM's copy only) for the duration of each server computation,
then restores the record. With 'CVpe' = true the CLUB getter builds the evaluated objective
list (0x1A27C8C / 0x1A27E20, judgement 0x1F03728 / 0x1CAB9E8) instead of the raw database
list (0x1A27AF8, judgement fixed at 6).

Text for enum values comes from the front end's data collections (value -> translation id,
`ui_frontend` table) and the game's own translator (`translate`, plugin export
i_translator_get_translation_from_id -> translator vtable slot 4).
"""
from __future__ import annotations

import re
import struct
import time

from . import ui_frontend, variant
from .ui_handlers import plain_text
from .ui_recipes_person import (DATABASE_RECORD, DataReader, _install_param_hook,
                                _session_vm, read_record)
from .ui_recipes_more import KeyReader, STALE_MEMORY_SIGNS, open_handler, refresh_live_memory
from .ui_vm import UiHandlerVM, fourcc, fourcc_text, REQUEST_SIZE, REQUEST_KEY_OFFSET
from .vm import Unavailable, _Stop

GLOBAL_CONTEXT_RVA = 0x56D38C0     # plugin UI context record: vector<{u32 key, pad, typed*}>
CLIENT_PARAMS_SLOT = 2             # client (this, request, out bag): parameters -> data-key args
TRANSLATOR_GLOBAL_RVA = 0x5721E70  # i_translator_get_instance() returns this global
TRANSLATE_SLOT = 4                 # translator->vtable[4](this, id, vars, x8 -> result)
TYPED_OFFSET = {'bool': 0x18, 'int': 0x28, 'uint': 0x38}   # traits in the registry (variant.py)

# Parameter globals the plugin looks up through 0x77E228 ({hash, const char *name} pairs set
# by static initialisers, e.g. 0x65247C). The full table (232 names) is in the front-end
# data file; these are the ones the recipes below need even without it.
PARAMS = {
    'visionobjectivesetter': 0x56D1A08, 'visionobjectivetype': 0x56D1A18,
    'visionobjectiveyear': 0x56D1A28, 'clubvisionnegotiationtype': 0x56D1A38,
    'visionisusingperformancedata': 0x56D19F8,
}

# ClubVisionProgressDataCollection (ui-datacollections bundle): VisionObjectiveProgress value
# (cvop, 0..16) -> translation id. Kept here as the fallback for a missing data file.
PROGRESS_TRANSLATIONS = (1743, 1744, 1745, 1746, 1747, 1748, 1749, 1750, 1751, 1752, 1753,
                         1754, 1755, 1756, 1757, 1758, 4583)
SETTERS = {'board': 1, 'supporters': 2}


# ---------------------------------------------------------------------- helpers
def param_rva(name: str) -> int:
    name = name.lower()
    if name in PARAMS:
        return PARAMS[name]
    table = _table()
    rva = (table.get('plugin_params') or {}).get(name)
    if rva is None:
        if name in (table.get('_plugin_params_dropped') or ()):
            raise KeyError(f'screen parameter {name!r} has no known global on the running build. '
                           f'{front_end_note()}')
        raise KeyError(f'unknown screen parameter {name!r}')
    return int(rva, 16) if isinstance(rva, str) else rva


_TABLE = None


def _table() -> dict:
    """The running build's front-end table (ui_frontend.active_source)."""
    global _TABLE
    if _TABLE is None:
        try:
            _TABLE = ui_frontend.table()
        except (OSError, ValueError):
            _TABLE = {}
    return _TABLE


def front_end_note() -> str | None:
    """Set when the running build has no front-end table of its own (ui_frontend.note)."""
    return (_table().get('_source') or {}).get('note')


def typed_value(vm: UiHandlerVM, kind: str, value: int) -> int:
    """A VM-heap typed value of a raw kind ('bool', 'int', 'uint')."""
    address = vm.alloc(16)
    payload = int(bool(value)) if kind == 'bool' else value & 0xFFFFFFFF
    vm.uc.mem_write(address, struct.pack('<QQ', vm.registry + TYPED_OFFSET[kind], payload))
    return address


def _typed_params(vm, params: dict) -> dict:
    """{name: value} -> {parameter global RVA: typed*}; bools stay bools, other non-integer
    values are not supplied (the getter then runs its own fallback)."""
    out = {}
    for name, value in (params or {}).items():
        if not isinstance(value, int):
            continue
        kind = 'bool' if isinstance(value, bool) else 'int'
        out[param_rva(name)] = typed_value(vm, kind, value)
    return out


_VARIABLE_TOKEN = re.compile(r'(?:person|club|team|nation|competition|staff|player|manager)#\d+')


def clean_text(text: str) -> str:
    """Drop the translator's unresolved variable tokens ('Pleasedperson#1': the gender
    variable a view would substitute; the word itself has none)."""
    return _VARIABLE_TOKEN.sub('', text).strip()


def translate(vm: UiHandlerVM, translation_id: int) -> str | None:
    """Text of a front-end translation id through the game's translator (None if empty)."""
    cache = vm.__dict__.setdefault('_translations', {})
    if translation_id in cache:
        return cache[translation_id]
    pinned = vm._baseline
    text = None
    try:
        vm._restore()
        translator = struct.unpack('<Q', vm.read(vm.base + TRANSLATOR_GLOBAL_RVA, 8))[0]
        if not translator:
            raise _Stop('translator not created')
        out = vm.alloc(32)
        args = vm.alloc(32)
        vm.uc.mem_write(out, b'\0' * 32)
        vm.uc.mem_write(args, b'\0' * 32)
        vm.commit()
        vm.vcall(translator, TRANSLATE_SLOT, (translation_id, args), x8=out)
        pointer = struct.unpack('<Q', vm.read(out, 8))[0]
        if pointer:
            length = struct.unpack('<I', vm.read(pointer - 4, 4))[0]
            if 0 < length < 4096:
                text = clean_text(vm.read(pointer, length).decode('utf-8', 'replace'))
    finally:
        vm._baseline = pinned
        vm._restore()
    cache[translation_id] = text
    return text


def collection_text(vm: UiHandlerVM, collection: str, value) -> str | None:
    """The word a view shows for `value` through one of the front end's data collections:
    the first row whose IntDataSet key (an inclusive maximum) is >= value, translated by the
    game. Collections without keys are indexed by value. None when the collection, the row
    or the translation is missing."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    row = (_table().get('data_collections') or {}).get(collection)
    if not row or not row.get('translations'):
        return None
    ids = row['translations']
    keys = row.get('keys') or list(range(len(ids)))
    for key, tid in zip(keys, ids):
        if value <= key:
            return translate(vm, tid)
    return None


def collection_words(vm: UiHandlerVM, collection: str) -> list:
    """[(inclusive maximum, word)] of a data collection (the full value -> word table)."""
    row = (_table().get('data_collections') or {}).get(collection) or {}
    ids = row.get('translations') or []
    keys = row.get('keys') or list(range(len(ids)))
    return [(key, translate(vm, tid)) for key, tid in zip(keys, ids)]


IMPORTANCE_COLLECTION = 'ClubVisionImportanceDataCollection'   # keys 0, 3, 6, 8, 10; strings 1738-1742


def importance_text(vm: UiHandlerVM, value) -> str | None:
    """Club vision importance (coip, 0..10) -> the word the Club Vision screen shows, from the
    front end's ClubVisionImportanceDataCollection (IntDataSet: inclusive maximum per row),
    translated by the game."""
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    return collection_text(vm, IMPORTANCE_COLLECTION, value)


def progress_text(vm: UiHandlerVM, value) -> str | None:
    """VisionObjectiveProgress (cvop) -> the judgement word the Club Vision screen shows."""
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    collection = (_table().get('data_collections') or {}).get('ClubVisionProgressDataCollection')
    keys, ids = (collection['keys'], collection['translations']) if collection else \
        (list(range(len(PROGRESS_TRANSLATIONS))), list(PROGRESS_TRANSLATIONS))
    for key, tid in zip(keys, ids):      # IntDataSet: inclusive maximum per row
        if value <= key:
            return translate(vm, tid)
    return None


# ---------------------------------------------------------------------- context protocol
def client_params(vm: UiHandlerVM, handler, key: str, params: dict) -> list:
    """Client slot 2 for one property with the view's parameters answered: the data-key
    arguments [(fourcc, 16 raw bytes of the typed value)] the plugin derives from them."""
    pinned = vm._baseline
    request = None
    try:
        vm._restore()
        request = vm.alloc(REQUEST_SIZE)
        vm.uc.mem_write(request, b'\0' * REQUEST_SIZE)
        vm.uc.mem_write(request + REQUEST_KEY_OFFSET, struct.pack('<I', fourcc(key)))
        bag = vm.alloc(64)
        vm.uc.mem_write(bag, b'\0' * 64)
        values = _typed_params(vm, params)
        vm.commit()
        _install_param_hook(vm)
        vm._request_params[request] = values
        vm.vcall(handler.client, CLIENT_PARAMS_SLOT, (request, bag))
        begin, end = struct.unpack('<QQ', vm.read(bag, 16))
        entries = []
        if 0 <= end - begin <= 16 * 256:
            for p in range(begin, end, 16):
                code = struct.unpack('<I', vm.read(p, 4))[0]
                typed = struct.unpack('<Q', vm.read(p + 8, 8))[0]
                # The getters null a context value once they have read it (observed: 'CVpe'
                # read back null after the first server get), so keep the 16 raw bytes and
                # give every computation a fresh copy (raw kinds hold the value inline).
                entries.append((fourcc_text(code), bytes(vm.read(typed, 16))))
        return entries
    finally:
        if request is not None and getattr(vm, '_request_params', None):
            vm._request_params.pop(request, None)
        vm._baseline = pinned
        vm._restore()


def install_context(vm: UiHandlerVM, entries) -> bytes:
    """Point the plugin's UI context record at a VM-heap entry array: the entries already
    there plus `entries` [(fourcc, raw typed bytes)], replacing equal keys, sorted by key.
    Returns the record's original 24-byte header for `remove_context`."""
    record = vm.base + GLOBAL_CONTEXT_RVA
    header = bytes(vm.read(record, 24))
    begin, end = struct.unpack('<QQ', header[:16])
    table = {}
    if 0 < end - begin <= 16 * 4096:
        for p in range(begin, end, 16):
            key, typed = struct.unpack('<I4xQ', vm.read(p, 16))
            table[key] = typed
    for code, raw in entries:
        typed = vm.alloc(16)
        vm.uc.mem_write(typed, raw)
        table[fourcc(code)] = typed
    array = vm.alloc(16 * max(len(table), 1))
    blob = b''.join(struct.pack('<I4xQ', key, table[key]) for key in sorted(table))
    vm.uc.mem_write(array, blob)
    vm.uc.mem_write(record, struct.pack('<QQQ', array, array + len(blob), array + len(blob)))
    return header


def remove_context(vm: UiHandlerVM, header: bytes):
    vm.uc.mem_write(vm.base + GLOBAL_CONTEXT_RVA, header)


def server_value_in_context(vm: UiHandlerVM, handler, key, entries, context=0):
    """Server slot 2 with `entries` in the UI context record; the record is restored and the
    result committed (as DataReader.fetch / KeyReader.fetch do)."""
    vm._restore()
    header = install_context(vm, entries)
    vm.commit()
    _, address, _ = vm.server_value(handler, key, context=context)
    remove_context(vm, header)
    vm.commit()
    return address


class ContextReader(DataReader):
    """DataReader (data-key protocol) whose server computations see `context` entries in the
    plugin's UI context record (see module docstring)."""

    def __init__(self, vm, handler, context=()):
        super().__init__(vm, handler)
        self.context = list(context)

    def fetch(self, data_key):
        if not self.context:
            return super().fetch(data_key)
        if data_key in self.data:
            return self.data[data_key]
        vm = self.vm
        started, rng = time.perf_counter(), vm.rng_uses
        pinned = vm._baseline
        try:
            self.data[data_key] = server_value_in_context(vm, self.handler, data_key, self.context)
        except _Stop as stop:
            trace = vm.backtrace()
            vm._baseline = pinned
            vm._restore()
            self.data[data_key] = Unavailable(f'data key {data_key}: {stop.reason}',
                                              detail=f'{stop.detail} [{" < ".join(trace)}]')
        self.data_seconds[data_key] = time.perf_counter() - started
        self.rng_by_data[data_key] = vm.rng_uses - rng
        return self.data[data_key]


class ContextKeyReader(KeyReader):
    """ui_recipes_more.KeyReader (every client protocol) with the same context handling."""

    def __init__(self, vm, handler, registry=None, context=()):
        super().__init__(vm, handler, registry)
        self.context = list(context)

    def fetch(self, key, context=0):
        if not self.context:
            return super().fetch(key, context)
        if context == 0 and key in self.data:
            return self.data[key]
        vm = self.vm
        started, rng = time.perf_counter(), vm.rng_uses
        pinned = vm._baseline
        try:
            result = server_value_in_context(vm, self.handler, key, self.context, context)
        except _Stop as stop:
            trace = vm.backtrace()
            vm._baseline = pinned
            vm._restore()
            result = Unavailable(f'server key {key}: {stop.reason}',
                                 detail=f'{stop.detail or ""} [{" < ".join(trace)}]')
        if context == 0:
            self.data[key] = result
            self.data_seconds[key] = time.perf_counter() - started
            self.rng_by_data[key] = vm.rng_uses - rng
        return result


def context_reader(vm: UiHandlerVM, handler_type: int, record: dict, key: str, view_params: dict,
                   inputs=()) -> ContextReader:
    """Build a handler and a data-key reader whose context is what client slot 2 derives
    from the view's parameters for `key`."""
    _, plain = read_record(vm, handler_type, record, keys=[], inputs=inputs)
    entries = client_params(vm, plain.handler, key, view_params) if view_params else []
    return ContextReader(vm, plain.handler, entries)


def read_key(vm: UiHandlerVM, handler_type: int, record: dict, key: str, view_params: dict | None = None,
             *, inputs=True, registry=None, reader=None):
    """One client key the way a view asks for it: `view_params` {parameter name: value}
    (names as in the views and the plugin, e.g. {'visionobjectivetype': 4}) answer both the
    slot-2 context and the slot-4 parameter lookups. Returns (KeyReading, context, reader)."""
    base = reader or open_handler(vm, handler_type, record, inputs=inputs, registry=registry)
    entries = client_params(vm, base.handler, key, view_params) if view_params else []
    ctx = ContextKeyReader(vm, base.handler, base.registry, entries)
    ctx.inputs = base.inputs
    ints = {param_rva(n): int(v) for n, v in (view_params or {}).items() if isinstance(v, int)}
    return ctx.get(key, params=ints or None), entries, ctx


def _value(reading):
    value = reading.value
    if isinstance(value, Unavailable):
        return {'unavailable': value.reason}
    return plain_text(variant.to_json(value))


# ---------------------------------------------------------------------- club vision
# The Club Vision views bind (UXML BindingVariables, ui-visualtreeassets bundles):
#   ClubBoardBlock / ClubVisionBlock_8x6: visionobjectivesetter 1, visionisusingperformancedata
#   true, visionobjectivetype 4 (culture) or the tab's type, visionobjectiveyear 0;
#   the five-year plan iterates yearsinplan [1..5] through visionobjectiveyear.
# The judgement column ('judgement' in ClubVisionObjectiveTableFactory) is
# VisionObjectiveProgress = 'cvop' of each objective record ('cvor').
OBJECTIVE_FIELDS = {'cvon': 'objective', 'coip': 'importance_value', 'cvoc': 'category',
                    'cvoi': 'id', 'Viys': 'season', 'VOse': 'setter', 'cvos': 'status',
                    'VOdt': 'type', 'cvop': 'progress_value', 'aZDo': 'performance', 'hint': 'hint',
                    'comp': 'competition'}
VISION_LISTS = {'all': 0, 'contract_rules': 1, 'culture': 4, 'actionable': 6,
                'competitions_this_season': 5}


def club_vision_progress(vm_or_session, club=None, *, read=None, years=(0,), lists=('all',)) -> dict:
    """See _club_vision_progress. A read that hits pages copied at different moments of the
    running game ('write to shipped code', as KeyReader retries) is redone once on a fresh
    copy of live memory."""
    out = _club_vision_progress(vm_or_session, club, read=read, years=years, lists=lists)
    text = repr(out.get('objectives'))
    if any(sign in text for sign in STALE_MEMORY_SIGNS) and isinstance(vm_or_session, UiHandlerVM):
        refresh_live_memory(vm_or_session)
        out = _club_vision_progress(vm_or_session, club, read=read, years=years, lists=lists)
        out['stale_memory_retry'] = True
    return out


def _club_vision_progress(vm_or_session, club=None, *, read=None, years=(0,), lists=('all',)) -> dict:
    """Club Vision objectives with the judgement each one shows on the Club Vision, Board and
    Supporters screens (VisionObjectiveProgress, evaluated with the views' own parameter
    visionisusingperformancedata = true)."""
    if isinstance(vm_or_session, UiHandlerVM) or not hasattr(vm_or_session, 'plugin_path'):
        vm, memory = vm_or_session, None
    else:
        vm, memory = _session_vm(vm_or_session)
        read = read or vm_or_session.reader.read
    try:
        started, rng0 = time.perf_counter(), vm.rng_uses
        if club is None:
            from .. import world
            team = world.loaded(world.ReadSet(read), vm.base)[0]['coaches'][0]['team_address']
            club = world.pointer(read, team + 0x30)
        cid = club if club >> 24 == 3 and club < 1 << 26 else vm.object_ref(club)
        reader = context_reader(vm, DATABASE_RECORD, {'dref': cid}, 'ViOl',
                                {'visionisusingperformancedata': True}, inputs=())
        out = {'club_id': cid, 'handler': reader.handler.client_class,
               'context': [(code, _decoded(vm, raw)) for code, raw in reader.context],
               'recipe': {'type': DATABASE_RECORD, 'record': {'dref': cid}, 'property': 'ViOl',
                          'view_params': {'visionisusingperformancedata': True}},
               'objectives': {}}
        for owner, setter in SETTERS.items():
            for list_name in lists:
                for year in years:
                    x = reader.get('ViOl', params={
                        PARAMS['visionobjectivesetter']: setter,
                        PARAMS['visionobjectivetype']: VISION_LISTS[list_name],
                        PARAMS['visionobjectiveyear']: year})
                    value = x.value
                    if isinstance(value, Unavailable):
                        rows = {'unavailable': value.reason}
                    elif isinstance(value, list):
                        rows = []
                        for entry in value:
                            row = {name: plain_text(variant.to_json(entry.get(code)))
                                   for code, name in OBJECTIVE_FIELDS.items()}
                            row['progress'] = progress_text(vm, row['progress_value'])
                            row['importance'] = importance_text(vm, row['importance_value'])
                            rows.append(row)
                    else:
                        rows = plain_text(variant.to_json(value))
                    label = list_name if len(years) == 1 else f'{list_name}@year{year}'
                    out['objectives'].setdefault(owner, {})[label] = rows
        out['rng_uses'] = vm.rng_uses - rng0
        out['seconds'] = round(time.perf_counter() - started, 3)
        if front_end_note():
            out['front_end_note'] = front_end_note()
        return out
    finally:
        if memory is not None:
            memory.close()


def _plain(value):
    if isinstance(value, Unavailable):
        return {'unavailable': value.reason}
    return plain_text(variant.to_json(value))


# ---------------------------------------------------------------------- transfer offer rows
# Transfer Activity rows bind the record 'Q2DC' (FM.UI.TransferActivityTransferOfferReference,
# 37 properties); the row record is what TRANSFER_ACTIVITY lists hand out, read through the
# TRANSFER_ACTIVITY_TRANSFER_OFFER handler (type 134). UNTESTED: no offer existed on the
# reference save; the shape comes from the front end's record schema.
TRANSFER_ACTIVITY_TRANSFER_OFFER = 134
OFFER_ROW_RECORD = 'Q2DC'


def transfer_offer_row(vm: UiHandlerVM, row_record: dict) -> dict:
    """One Transfer Activity offer row, every property of the front end's row schema.
    `row_record`: the UiRecord a TRANSFER_ACTIVITY list returns for the row."""
    data = _table()
    schema = (data.get('records') or {}).get(OFFER_ROW_RECORD) or {}
    keys = list(schema.get('properties') or ())
    record = {k: v for k, v in row_record.items() if k != '110 '}
    handler_type = row_record.get('110 ', TRANSFER_ACTIVITY_TRANSFER_OFFER)
    reader = open_handler(vm, handler_type, record)
    labels = data.get('registry') or {}
    out = {'handler_type': handler_type, 'record': record, 'tested': False, 'fields': {}}
    for code in keys:
        reading = reader.get(code)
        out['fields'][labels.get(code, code)] = _plain(reading.value)
    return out


# ---------------------------------------------------------------------- happiness words
def happiness_word(vm: UiHandlerVM, level) -> str | None:
    """The Squad/Player screens' word for HierarchyOverallHappinessLevel ('Pohl')."""
    return collection_text(vm, 'OverallHappinessDataCollection', level)


def playing_time_word(vm: UiHandlerVM, level) -> str | None:
    """The word for PlayingTimeHappinessLevel ('pthn', -100..100): '-', Alienated, Unhappy,
    Concerned, Satisfied, Happy, Very Happy, Delighted."""
    return collection_text(vm, 'PlayingTimeHappinessDataCollection', level)


# ---------------------------------------------------------------------- squad happiness
# List/narrative split: the list (every player of every team of the club, three integer
# levels each) costs one PERSON handler build and three slot-13 passthrough keys per player
# on one warm VM, with no input transfer; the narrative (the screen's reasons, the
# HappinessNegatives list with 8 data keys) is read only for players whose overall level is
# below Content (<= 19, OverallHappinessDataCollection) or whose playing-time level is
# Concerned or worse (<= -20), or for every player with reasons='all'.
SQUAD_LIST_KEYS = {'name': 'iSnm', 'overall_level': 'Pohl', 'playing_time_level': 'pthn', 'morale_value': 'Mora'}
SQUAD_REASON_KEYS = {'happiness_negatives': 'HPNe', 'morale': 'dafe'}
UNHAPPY_OVERALL_MAX = 19          # 'Content' is the band up to 19; below is Slightly Unhappy..
UNHAPPY_PLAYING_TIME_MAX = -20    # 'Concerned' and worse


def club_players(read, club: int) -> list:
    """(team address, player primary) for every team of the club (club +0x18 team vector,
    team +0x38 roster), each player once."""
    from .. import world
    begin, end = struct.unpack('<QQ', read(club + 0x18, 16))
    out, seen = [], set()
    for p in range(begin, min(end, begin + 8 * 64), 8):
        team = struct.unpack('<Q', read(p, 8))[0]
        for primary in world.vector(read, team + 0x38, 512):
            if primary not in seen:
                seen.add(primary)
                out.append((team, primary))
    return out


def squad_happiness(vm_or_session, club=None, *, read=None, reasons='unhappy') -> dict:
    """Who is unhappy at the club and why, in one call: every player's overall happiness
    and playing-time happiness with the words the Squad > Happiness screen uses, and the
    screen's reasons (HappinessNegatives) for the unhappy ones. reasons: 'unhappy', 'all'
    or 'none'."""
    from .ui_recipes_person import person_id
    if isinstance(vm_or_session, UiHandlerVM) or not hasattr(vm_or_session, 'plugin_path'):
        vm, memory = vm_or_session, None
    else:
        vm, memory = _session_vm(vm_or_session)
        read = read or vm_or_session.reader.read
    try:
        started, cpu0, rng0 = time.perf_counter(), time.process_time(), vm.rng_uses
        from .. import world
        if club is None:
            team = world.loaded(world.ReadSet(read), vm.base)[0]['coaches'][0]['team_address']
            club = world.pointer(read, team + 0x30)
        elif club >> 24 == 3 and club < 1 << 26:          # CLUB UI id -> object
            from .ui_recipes_news import resolve
            club = resolve(vm, club)
            if not club:
                raise _Stop('club id did not resolve')
        rows, failed, virtual = [], [], []
        list_cpu = 0.0
        virtual_vt = vm.base + world.TYPES['virtual_player'][0]
        for team, primary in club_players(read, club):
            c0 = time.process_time()
            if struct.unpack('<Q', read(primary, 8))[0] == virtual_vt:
                # a youth-intake placeholder on the roster (VIRTUAL_PLAYER): no PERSON_UI record and
                # not a player the Happiness screen lists
                virtual.append(hex(primary))
                continue
            try:
                pid = person_id(vm, read, primary)
                reading, reader = read_record(vm, DATABASE_RECORD, {'dref': pid},
                                              keys=list(SQUAD_LIST_KEYS.values()), inputs=())
            except (_Stop, ValueError) as exc:
                failed.append({'player': hex(primary), 'reason': getattr(exc, 'reason', str(exc))})
                continue
            by = {r.code: _plain(r.value) for r in reading.readings}
            row = {name: by.get(code) for name, code in SQUAD_LIST_KEYS.items()}
            row.update(person_id=pid, team=vm.object_ref(team) if team else None,
                       overall=happiness_word(vm, row['overall_level']),
                       playing_time=playing_time_word(vm, row['playing_time_level']))
            list_cpu += time.process_time() - c0
            low = ((isinstance(row['overall_level'], int) and row['overall_level'] <= UNHAPPY_OVERALL_MAX)
                   or (isinstance(row['playing_time_level'], int)
                       and row['playing_time_level'] <= UNHAPPY_PLAYING_TIME_MAX))
            row['unhappy'] = bool(low)
            if reasons == 'all' or reasons == 'unhappy' and low:
                # the reason lists consult the client's transferred inputs (as player_status)
                try:
                    detail, _ = read_record(vm, DATABASE_RECORD, {'dref': pid},
                                            keys=list(SQUAD_REASON_KEYS.values()))
                    got = {r.code: _plain(r.value) for r in detail.readings}
                except _Stop as stop:
                    got = {code: {'unavailable': stop.reason} for code in SQUAD_REASON_KEYS.values()}
                for name, code in SQUAD_REASON_KEYS.items():
                    row[name] = got.get(code)
            rows.append(row)
        counts = {}
        for row in rows:
            counts[row['overall']] = counts.get(row['overall'], 0) + 1
        extra = {'front_end_note': front_end_note()} if front_end_note() else {}
        return {**extra, 'club_id': vm.object_ref(club), 'players': rows, 'failed': failed,
                'virtual_players_skipped': virtual,
                'unhappy': [r['name'] for r in rows if r['unhappy']], 'overall_counts': counts,
                'words': {'overall': collection_words(vm, 'OverallHappinessDataCollection'),
                          'playing_time': collection_words(vm, 'PlayingTimeHappinessDataCollection')},
                'rng_uses': vm.rng_uses - rng0,
                'seconds': round(time.perf_counter() - started, 2),
                'cpu_seconds': round(time.process_time() - cpu0, 2),
                'list_cpu_seconds': round(list_cpu, 2)}
    finally:
        if memory is not None:
            memory.close()


def _decoded(vm, raw: bytes):
    """Decode a context value kept as its 16 raw bytes (diagnostics only)."""
    pinned = vm._baseline
    try:
        vm._restore()
        typed = vm.alloc(16)
        vm.uc.mem_write(typed, raw)
        kind, value = vm.decode(typed)
        return variant.to_json(value)
    except Exception:  # noqa: BLE001 - diagnostics only
        return None
    finally:
        vm._baseline = pinned
        vm._restore()


__all__ = ['squad_happiness', 'happiness_word', 'playing_time_word', 'clean_text', 'transfer_offer_row',
           'collection_text', 'collection_words', 'ContextReader', 'ContextKeyReader', 'client_params', 'context_reader', 'read_key',
           'install_context', 'remove_context', 'translate', 'progress_text', 'importance_text', 'club_vision_progress',
           'typed_value', 'param_rva', 'GLOBAL_CONTEXT_RVA']
