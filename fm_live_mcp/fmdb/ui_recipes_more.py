"""More UI handler recipes: one reader for every client protocol, plus shaped screens.

`KeyReader` reads one client key of a built handler with every protocol the plugin's
clients use (verified on build 27.0.0.2493426, see docs/fmdb/UI_SWEEP.md):

1. cached inputs: the server -> client transfer through client slot 17 (TEAM_CONFIDENCE
   style; `transfer_inputs`), after which slot 4 answers from the client's own cache;
2. declared server keys: client slot 16 `(this, request, declarations)` lists groups
   {params bag, client params bag, sorted u32 keys} and slot 14 `(this, request, out u32
   vector)` lists plain server keys; each is computed by server slot 2 (with the group's
   params bag as context) and passed to slot 4 in a property bag (FIXTURE, CALENDAR,
   PERSON/CLUB style);
3. direct keys: client slot 13 `(this, key) -> u32` names a server key whose value *is*
   the property (slot 4 returns null for those);
4. screen parameters: getters that read `0x77E228(request, path, out, inherit)` get the
   int32 values passed in `params` ({path RVA: value}, the hook in ui_recipes_person).

Server values are computed once per (handler, key) when they take no parameters and stay
in the committed baseline; the bag, request and every store of slot 4 are discarded (the
baseline is pinned before and restored after), so the order of reads does not matter.

Everything is read-only: shipped code runs on copied live memory inside UiHandlerVM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
import struct
import time

from . import ui_registry, variant
from .ui_handlers import HandlerReading, Reading, plain_text, input_keys
from .ui_vm import (UiHandlerVM, Handler, fourcc, fourcc_text, object_id, REQUEST_SIZE,
                    REQUEST_KEY_OFFSET, CLIENT_GET_SLOT)
from .vm import Unavailable, _Stop

CLIENT_DIRECT_KEY_SLOT = 13
CLIENT_SERVER_KEYS_SLOT = 14
CLIENT_DECLARE_SLOT = 16
NULL_KEY = 0x4E554C4C                 # 'NULL'
PARAM_LOOKUP_RVA = 0x77E228           # (request, parameter path global, out typed*, inherit)
INT32_VARIANT_RVA = 0x4403EC0         # (typed* out, int32 value)
DATABASE_RECORD = 28                  # factory case that dispatches on the dref's table type
HEAP_REFRESH_BYTES = 16 << 20         # rebuild a handler once cached values add this much VM heap
HEAP_CEILING_BYTES = 48 << 20         # ... or once the VM heap (64 MiB) is this full
# Failures that mean the copied pages disagree with each other (copied at different moments).
STALE_MEMORY_SIGNS = ('write to shipped code', 'call into non-plugin code')
MAX_STALE_RETRIES = 3                 # per handler reader


def is_empty(value, kind=None) -> bool:
    return value in (None, '', [], {}) or kind == 'null'


def status_of(value, kind=None) -> str:
    if isinstance(value, Unavailable):
        return 'unavailable'
    return 'unset' if is_empty(value, kind) else 'value'


# ---------------------------------------------------------------------- parameter trace
def install_param_trace(vm: UiHandlerVM):
    """Record the screen parameters (path RVAs) getters ask for through 0x77E228 into
    `vm.param_trace` (a set, or None to switch tracing off)."""
    if getattr(vm, '_param_trace_installed', False):
        return
    import unicorn.arm64_const as A
    from unicorn import UC_HOOK_CODE
    vm.param_trace = None

    def hook(uc, address, size, user):
        if vm.param_trace is not None:
            vm.param_trace.add(uc.reg_read(A.UC_ARM64_REG_X1) - vm.base)
    vm.uc.hook_add(UC_HOOK_CODE, hook, None, begin=vm.base + PARAM_LOOKUP_RVA,
                   end=vm.base + PARAM_LOOKUP_RVA)
    vm.uc.ctl_remove_cache(vm.base + PARAM_LOOKUP_RVA, vm.base + PARAM_LOOKUP_RVA + 0x100)
    vm._param_trace_installed = True


# ---------------------------------------------------------------------- unified reader
@dataclass
class KeyReading:
    code: str
    label: str | None
    kind: str | None
    value: object
    seconds: float
    protocol: str = 'none'            # cache | declared | direct | none
    server_keys: tuple = ()
    failed: dict = field(default_factory=dict)
    params_read: tuple = ()
    rng_uses: int = 0

    @property
    def status(self):
        return status_of(self.value, self.kind)

    def json_value(self):
        if isinstance(self.value, Unavailable):
            return {'unavailable': self.value.reason}
        return plain_text(variant.to_json(self.value))


class KeyReader:
    """Reads client keys of one built handler through every protocol (module docstring)."""

    def __init__(self, vm: UiHandlerVM, handler: Handler, registry=None):
        self.vm, self.handler = vm, handler
        self.registry = registry or ui_registry.default()
        self.data = {}               # server key (no params) -> typed* or Unavailable
        self.inputs = True           # what open_handler transferred (refresh repeats it)
        self.refreshes = 0
        self.inputs_dropped = False
        self.stale_retries = 0
        self.base_heap = self.heap_used()
        self.data_seconds = {}
        self.rng_by_data = {}
        self.direct = {}

    # -- server values ----------------------------------------------------------------
    def fetch(self, key, context=0):
        """Server slot 2 value of `key` (cached when context is 0); committed into the
        baseline so later reads see it."""
        if context == 0 and key in self.data:
            return self.data[key]
        vm = self.vm
        started, rng = time.perf_counter(), vm.rng_uses
        pinned = vm._baseline
        try:
            vm._restore()
            _, address, _ = vm.server_value(self.handler, key, context=context)
            vm.commit()
            result = address
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

    def value(self, key, context=0):
        """Decoded server value of one key (diagnostics, shaped recipes)."""
        address = self.fetch(key, context)
        if isinstance(address, Unavailable):
            return None, address
        self.vm._restore()
        return self.vm.decode(address)

    def direct_key(self, code):
        if code not in self.direct:
            vm = self.vm
            pinned = vm._baseline
            try:
                vm._restore()
                vm.commit()
                number, _ = vm.vcall(self.handler.client, CLIENT_DIRECT_KEY_SLOT, (fourcc(code),))
                number &= 0xFFFFFFFF
                self.direct[code] = None if number in (NULL_KEY, 0) else fourcc_text(number)
            except _Stop:
                self.direct[code] = None
            finally:
                vm._baseline = pinned
                vm._restore()
        return self.direct[code]

    def _request(self, number):
        vm = self.vm
        request = vm.alloc(REQUEST_SIZE)
        vm.uc.mem_write(request, b'\0' * REQUEST_SIZE)
        vm.uc.mem_write(request + REQUEST_KEY_OFFSET, struct.pack('<I', number))
        return request

    def _declare(self, code):
        """Run client slots 16 and 14 in the current (uncommitted) state:
        [(params bag address or 0, [server keys])]. Empty params bags count as 0."""
        from .ui_recipes_news import parse_declarations
        vm = self.vm
        request = self._request(fourcc(code))
        decl = vm.alloc(24)
        vm.uc.mem_write(decl, b'\0' * 24)
        needed = vm.alloc(24)
        vm.uc.mem_write(needed, b'\0' * 24)
        vm.commit()
        vm.vcall(self.handler.client, CLIENT_DECLARE_SLOT, (request, decl))
        vm.commit()
        vm.vcall(self.handler.client, CLIENT_SERVER_KEYS_SLOT, (request, needed))
        vm.commit()
        groups = []
        for params, _client, keys in parse_declarations(vm.read, decl):
            begin, end = struct.unpack('<QQ', vm.read(params, 16))
            groups.append((params if end > begin else 0, keys))
        begin, end = struct.unpack('<QQ', vm.read(needed, 16))
        if end < begin or (end - begin) % 4 or end - begin > 4 * 1024:
            raise _Stop('implausible server key vector', hex(end - begin))
        plain = [fourcc_text(k) for k in struct.unpack(f'<{(end - begin) // 4}I', vm.read(begin, end - begin))] \
            if end > begin else []
        if plain:
            groups.append((0, plain))
        return groups

    def declarations(self, code):
        """[(has params, [server keys])] the client asks for to answer `code` (no state kept)."""
        if not self.handler.server:
            return []
        vm = self.vm
        pinned = vm._baseline
        try:
            vm._restore()
            return [(bool(params), keys) for params, keys in self._declare(code)]
        finally:
            vm._baseline = pinned
            vm._restore()

    def heap_used(self) -> int:
        from .vm import HEAP
        return self.vm.heap_top - HEAP

    def refresh(self):
        """Rebuild the handler pair (fresh inputs, empty value cache) to free the VM heap."""
        record = {k: v for k, v in self.handler.record.items() if k != '110 '}
        self.handler = self.vm.build(self.handler.handler_type, record)
        if self.inputs:
            transfer_inputs(self.vm, self.handler, self.registry, None if self.inputs is True else self.inputs)
        self.data.clear()
        self.direct.clear()
        self.refreshes += 1
        self.base_heap = self.heap_used()

    # -- one key ----------------------------------------------------------------------
    def get(self, code, *, params=None) -> KeyReading:
        """One client key (see _get); a read that ran out of VM heap is retried once on a
        rebuilt handler, without its slot-17 inputs when those alone fill most of the heap
        (TEAM_UI_HANDLER: ~20 s and most of the 64 MiB)."""
        reading = self._get(code, params=params)
        reason = reading.value.reason or '' if isinstance(reading.value, Unavailable) else ''
        if any(sign in reason for sign in STALE_MEMORY_SIGNS) and self.stale_retries < MAX_STALE_RETRIES:
            # Pages copied at different moments of the running game disagree (a pointer leads
            # into shipped code): copy live memory afresh, rebuild, read again.
            self.stale_retries += 1
            refresh_live_memory(self.vm)
            self.refresh()
            reading = self._get(code, params=params)
            reason = reading.value.reason or '' if isinstance(reading.value, Unavailable) else ''
        if 'heap exhausted' in reason:
            self.refresh()
            if self.inputs and self.base_heap > HEAP_CEILING_BYTES // 2:
                self.inputs = False
                self.inputs_dropped = True
                self.refresh()
            reading = self._get(code, params=params)
        return reading

    def _get(self, code, *, params=None) -> KeyReading:
        """One client key. Server keys without parameters are computed once and kept in
        the baseline; declarations, keys computed with a params bag, the property bag,
        the request and every store of slot 4 are discarded afterwards."""
        vm = self.vm
        code = code if isinstance(code, str) else fourcc_text(code)
        label = self.registry.label(code)
        started, rng0 = time.perf_counter(), vm.rng_uses
        used = self.heap_used()
        if self.data and (used - self.base_heap > HEAP_REFRESH_BYTES
                          or used > HEAP_CEILING_BYTES and self.base_heap < HEAP_CEILING_BYTES // 2):
            self.refresh()
        trace = set() if getattr(vm, '_param_trace_installed', False) else None
        try:
            groups = self.declarations(code)
        except (_Stop, ValueError) as exc:
            reason = exc.reason if isinstance(exc, _Stop) else str(exc)
            return KeyReading(code, label, None, Unavailable('input declaration failed: ' + reason),
                              time.perf_counter() - started)
        failed, keys = {}, []
        for has_params, server_keys in groups:
            keys.extend(server_keys)
            if not has_params:
                for key in server_keys:
                    address = self.fetch(key)
                    if isinstance(address, Unavailable):
                        failed[key] = address
        pinned = vm._baseline
        request = None
        kind, value = None, None
        try:
            from .ui_recipes_news import place_bag
            from .ui_recipes_person import _install_param_hook
            vm._restore()
            values = []
            live = self._declare(code) if any(p for p, _ in groups) else [(0, k) for _, k in groups]
            for params_bag, server_keys in live:
                for key in server_keys:
                    if not params_bag:
                        if not isinstance(self.data.get(key), Unavailable):
                            values.append((key, self.data[key]))
                        continue
                    try:
                        _, address, _ = vm.server_value(self.handler, key, context=params_bag)
                        vm.commit()
                        values.append((key, address))
                    except _Stop as stop:
                        vm.reset_to_last()
                        failed[key] = Unavailable(f'server key {key}: {stop.reason}', detail=stop.detail)
            bag = place_bag(vm, values)
            request = self._request(fourcc(code))
            out = vm.alloc(16)
            vm.uc.mem_write(out, struct.pack('<QQ', vm.registry + 8, 0))
            typed = {}
            for rva in (params or {}):
                typed[rva] = vm.alloc(16)
                vm.uc.mem_write(typed[rva], b'\0' * 16)
            vm.commit()
            for rva, number in (params or {}).items():
                vm.call(vm.base + INT32_VARIANT_RVA, [typed[rva], number & 0xFFFFFFFF])
                vm.commit()
            if typed:
                _install_param_hook(vm)
                vm._request_params[request] = typed
            vm.param_trace = trace if trace is not None else getattr(vm, 'param_trace', None)
            vm.vcall(self.handler.client, CLIENT_GET_SLOT, (request, out, bag))
            kind, value = vm.decode(out)
        except _Stop as stop:
            stack = vm.backtrace()
            value = Unavailable(stop.reason, detail=f'{stop.detail or ""} [{" < ".join(stack)}]')
        finally:
            if getattr(vm, '_request_params', None):
                vm._request_params.pop(request, None)
            if trace is not None:
                vm.param_trace = None
            vm._baseline = pinned
            vm._restore()
        protocol = 'declared' if keys else 'cache'
        if not isinstance(value, Unavailable) and is_empty(value, kind) and not keys:
            direct = self.direct_key(code)
            if direct:
                address = self.fetch(direct)
                keys.append(direct)
                protocol = 'direct'
                if isinstance(address, Unavailable):
                    failed[direct] = address
                else:
                    vm._restore()
                    kind, value = vm.decode(address)
        if failed:
            # A getter given an incomplete bag answers with defaults; never report those.
            first = next(iter(failed.values()))
            value = Unavailable(first.reason, detail=f'{len(failed)} of {len(keys)} server keys failed; '
                                f'{first.detail}')
            kind = None
        return KeyReading(code, label, kind, value, time.perf_counter() - started, protocol,
                          tuple(dict.fromkeys(keys)), {k: v.reason for k, v in failed.items()},
                          tuple(sorted(trace or ())), vm.rng_uses - rng0)


def transfer_inputs(vm: UiHandlerVM, handler: Handler, registry=None, keys=None) -> dict:
    """Server -> client transfer (slot 17) of every input the client consumes."""
    registry = registry or ui_registry.default()
    if not handler.server:
        return {}
    for key in (keys if keys is not None else input_keys(registry, handler.client_class)):
        vm.transfer(handler, key)
    return dict(handler.inputs)


def refresh_live_memory(vm: UiHandlerVM):
    """Read from current game memory again. The accelerated emulator starts a new page
    generation (every copied page is read again before its next use; translated code and page
    tables stay, so this costs one warm computation). The reference emulator drops every
    copied page and its factory object."""
    vm.begin_read()
    vm.live_refreshes = getattr(vm, 'live_refreshes', 0) + 1


def open_handler(vm: UiHandlerVM, handler_type: int, record: dict, *, inputs=True, registry=None):
    """Build a handler pair, transfer its inputs and return a KeyReader for it."""
    registry = registry or ui_registry.default()
    try:
        handler = vm.build(handler_type, record)
    except _Stop:
        # Live pages are copied lazily, so a long-lived VM can hold pages copied at different
        # moments of a running game; a build that faults on that mix succeeds after a fresh
        # copy (observed once: a RECRUITMENT_FOCUS build after many reads). Retry once.
        refresh_live_memory(vm)
        handler = vm.build(handler_type, record)
    if inputs:
        transfer_inputs(vm, handler, registry, None if inputs is True else inputs)
    reader = KeyReader(vm, handler, registry)
    reader.inputs = inputs
    return reader


def read_keys(vm: UiHandlerVM, handler_type: int, record: dict, keys, *, inputs=True, params=None,
              registry=None) -> tuple[dict, KeyReader]:
    """{code: KeyReading} for `keys` of one handler (built once)."""
    reader = open_handler(vm, handler_type, record, inputs=inputs, registry=registry)
    return {code: reader.get(code, params=params) for code in keys}, reader


def counts(readings) -> dict:
    out = {'value': 0, 'unset': 0, 'unavailable': 0}
    for r in readings:
        out[r.status] += 1
    return out


# ====================================================================== shaped screens
# Handler types and record fields (verified live on 11 Nov 2026, Newcastle, 10 Dec 2030;
# docs/fmdb/UI_SWEEP.md). Every screen below uses the generic KeyReader.
SCOUT_ASSIGNMENTS, SCOUT_PLAYER_PRIORITIES, SCOUT_TEAM_PRIORITIES = 90, 91, 92
SCOUTING_INFO, RECRUITMENT_FOCUS = 97, 85
TRANSFER_ACTIVITY, TRANSFER_WINDOW = 131, 142
TEAM_TRAINING = 128
COMPETITION_STAGE = 17
FIXTURE = 50
NULL_ID = 0xFF7FFFFF            # the "no object" UI id (table 0xFF, index 0x7FFFFF)
# TEAM_UI_HANDLER's slot-17 inputs take ~20 s; the dynamics and medical keys read declared
# server keys only, and gave identical values without them (checked on the reference save).
TEAM_INPUTS = False


@dataclass(frozen=True)
class Viewer:
    """The human manager's context, as the record fields the screens read."""
    human: int              # HUMAN_NON_PLAYER address
    person_index: int
    person_id: int          # 1 << 24 | people index ('Hhum', 'PbPY')
    team: int               # managed TEAM address
    team_id: int            # 0x18 << 24 | team index ('Ttea', 'Team', 'iyrZ')
    club_id: int            # 3 << 24 | club index ('club')
    game_date: str

    def record(self, **extra) -> dict:
        out = {'Hhum': self.person_id, 'huma': self.person_index, 'PbPY': self.person_id,
               'Ttea': self.team_id, 'Team': self.team_id, 'team': self.team_id, 'iyrZ': self.team_id,
               'club': self.club_id}
        out.update(extra)
        return out


def viewer(vm: UiHandlerVM, coach=0) -> Viewer:
    from .. import world
    from .ui_recipes_news import viewer as news_viewer
    view = news_viewer(vm, coach)
    team_id = vm.object_ref(view.team)
    club = world.pointer(vm.reader.read, view.team + 0x30)
    return Viewer(view.human, view.person_index, object_id(1, view.person_index), view.team, team_id,
                  vm.object_ref(club), view.current_date)


class Refs:
    """Turns nested UI references ({'110 ': 28, 'dref': id}) into {'id', 'type', 'name'}.

    Names come from the game's resolver 0x111344C and the record's 'dbnm' property. The
    resolver resets the VM baseline, so call this only after a handler's reads are done."""

    def __init__(self, vm):
        from .ui_recipes_news import Names
        self.names = Names(vm)

    def ref(self, value):
        target = value.get('dref') if isinstance(value, dict) else value
        if isinstance(target, dict):
            target = target.get('dref')
        if not isinstance(target, int) or isinstance(target, bool):
            return value
        target &= 0xFFFFFFFF
        if target == NULL_ID or target >> 24 == 0xFF:
            return None
        found = self.names(target) or {}
        return {'id': target, 'type': found.get('type'), 'name': found.get('name')}

    def __call__(self, value, depth=0):
        if depth > 6:
            return value
        if isinstance(value, dict):
            if set(value) <= {'110 ', 'dref'} and 'dref' in value and value.get('110 ') in (28, None):
                return self.ref(value)
            return {k: self(v, depth + 1) for k, v in value.items()}
        if isinstance(value, list):
            return [self(v, depth + 1) for v in value]
        return value


@dataclass
class ScreenRead:
    """Values of named keys of one handler, with coverage and cost."""
    handler: str | None
    recipe: dict
    fields: dict
    readings: dict
    seconds: float
    rng_uses: int
    inputs: dict

    def coverage(self):
        return counts(self.readings.values())

    def failures(self):
        return {name: r.value.reason for name, r in self.readings.items() if isinstance(r.value, Unavailable)}

    def rng_fields(self):
        return sorted(name for name, r in self.readings.items() if r.rng_uses)


def read_screen(vm: UiHandlerVM, handler_type: int, record: dict, keys: dict, *, params=None,
                refs=None, inputs=True) -> ScreenRead:
    """Build one handler and read `keys` ({field name: FourCC}); `params` = {field name:
    {parameter RVA: int}} for getters that read screen parameters."""
    started, rng0 = time.perf_counter(), vm.rng_uses
    reader = open_handler(vm, handler_type, record, inputs=inputs)
    readings = {}
    for name, code in keys.items():
        readings[name] = reader.get(code, params=(params or {}).get(name))
    fields = {name: r.json_value() for name, r in readings.items()}
    if refs is not None:
        fields = refs(fields)
    return ScreenRead(reader.handler.client_class, {'type': handler_type, 'record': dict(record)}, fields,
                      readings, round(time.perf_counter() - started, 3), vm.rng_uses - rng0,
                      dict(reader.handler.inputs))


def _answer(parts: dict, started, rng0, vm, **extra) -> dict:
    """Common envelope: fields per part, recipe, coverage, unavailable reasons, cost."""
    out = dict(extra)
    coverage = {'value': 0, 'unset': 0, 'unavailable': 0}
    for name, part in parts.items():
        if not isinstance(part, ScreenRead):
            continue
        c = part.coverage()
        for k in coverage:
            coverage[k] += c[k]
        out.setdefault('sources', {})[name] = {
            'handler': part.handler, 'recipe': part.recipe, 'coverage': c, 'seconds': part.seconds,
            'rng_uses': part.rng_uses, 'unavailable': part.failures(),
            'fields_using_random_draws': part.rng_fields()}
    out['coverage'] = coverage
    out['seconds'] = round(time.perf_counter() - started, 3)
    out['rng_uses'] = vm.rng_uses - rng0
    return out


def _vm_and_view(vm_or_session, coach=0):
    from .ui_recipes_news import as_vm
    vm = as_vm(vm_or_session)
    return vm, viewer(vm, coach)


# ---------------------------------------------------------------------- scouting
RECRUITMENT_FOCUS_KEYS = {
    'status': 'z529', 'positions': 'jg4i', 'role': 'qbjW', 'filters': '79Uq', 'min_age': 'qDgc',
    'max_age': '7mLp', 'current_ability_stars': 'PCAB', 'potential_ability_stars': 'PPAB',
    'scouts': '9CEM', 'scout_count': 'P3ZV', 'analyst_count': 'MeJa', 'priority': 'dMxa',
    'transfer_deal_type': 'Y945', 'created': 'geoV', 'completion': '8BkQ', 'created_by': 'MfvO',
    'recommended_count': 'Gj62', 'near_miss_count': 'f9hW', 'is_complete': 'jJFu',
    'is_struggling': 'Rtwu', 'recommended_players': 'aYyP',
}


def scouting(vm_or_session, *, focuses=True, coach=0) -> dict:
    """Scouting as the Recruitment screens show it: the club's scouts and which one is
    selected (SCOUT_ASSIGNMENTS, type 90), players and teams scouted specifically (types 91,
    92), recruitment focuses (SCOUTING_INFO type 97 with record 'iyrZ' = team, then each
    focus through RECRUITMENT_FOCUS type 85), scouting budget and range, and the club's
    scouting knowledge by nation and region (CLUB_UI_HANDLER)."""
    vm, view = _vm_and_view(vm_or_session, coach)
    started, rng0 = time.perf_counter(), vm.rng_uses
    refs = Refs(vm)
    parts = {}
    parts['assignments'] = read_screen(vm, SCOUT_ASSIGNMENTS, view.record(),
                                       {'scouts': 'JUAj', 'selected_scout': 'oXWO'}, refs=refs)
    parts['players'] = read_screen(vm, SCOUT_PLAYER_PRIORITIES, view.record(),
                                   {'specifically_scouted_players': 'sj22', 'count': 'ssPC'}, refs=refs)
    parts['teams'] = read_screen(vm, SCOUT_TEAM_PRIORITIES, view.record(), {'count': 'h9ac'}, refs=refs)
    parts['info'] = read_screen(vm, SCOUTING_INFO, view.record(), {
        'recruitment_focuses': 'twli', 'recruitment_focus_count': '9jwF', 'scouting_budget': 'scbg',
        'scouting_range': 'scrg', 'scouting_cost_monthly': 'sccs'})
    parts['knowledge'] = read_screen(vm, DATABASE_RECORD, {'dref': view.club_id}, {
        'nations': '4Ynn', 'regions': 'wZfj', 'scouting_costs_this_season': '9vyf',
        'scouting_vacancies': 'ayxV'}, refs=refs)
    rows = []
    focus_records = parts['info'].fields.get('recruitment_focuses')
    if focuses and isinstance(focus_records, list):
        for rec in focus_records:
            if not isinstance(rec, dict) or rec.get('110 ') != RECRUITMENT_FOCUS:
                continue
            record = {k: v for k, v in rec.items() if k != '110 '}
            part = read_screen(vm, RECRUITMENT_FOCUS, record, RECRUITMENT_FOCUS_KEYS, refs=refs)
            parts[f'focus_{record.get("rfid")}'] = part
            rows.append(dict(part.fields, id=record.get('rfid')))
    info = refs(dict(parts['info'].fields))
    info['recruitment_focuses'] = rows
    return _answer(parts, started, rng0, vm, game_date=view.game_date,
                   scouts=parts['assignments'].fields, scouted=parts['players'].fields,
                   scouted_teams_count=parts['teams'].fields['count'], recruitment=info,
                   knowledge=parts['knowledge'].fields)


# ---------------------------------------------------------------------- transfers
TRANSFER_ACTIVITY_KEYS = {
    'players_in': 'taIT', 'players_out': 'taOT', 'players_all': 'Jy7b', 'staff_in': '0lgL',
    'staff_out': 'OpOX', 'trade_offers': 'QUw5', 'player_offers_count': 'toac',
    'offers_needing_response_in': '5fxp', 'offers_needing_response_out': 'iJhj',
    'staff_offers_count': 'FDjl', 'in_potential_value': 'O4Il', 'all_potential_value': 'yP3p',
    'in_budget_impact': 'nUpV', 'out_budget_impact': 'obcC', 'all_budget_impact': '2mq3',
    'all_wages': '1hUM',
}
CLUB_BUDGET_KEYS = {
    'transfer_budget_at_start': 'Alvg', 'transfer_budget_next_season': '7JWg', 'wage_budget': '17CQ',
    'remaining_wage_budget': 'i9nk', 'wage_budget_next_season': 'IbyI', 'transfer_debt': 'coCj',
    'transfer_budget_history': 'qAlY', 'projected_transfer_budget': 'LQPH',
}
TRANSFER_WINDOW_KEYS = {
    'status': 'irtw', 'start': 'PcSd', 'end': 'Pced', 'days_remaining': 'twds', 'days_since_start': '0CyS',
    'in_count': 'Qq69', 'out_count': 'eosW', 'in_value': 'hZLR', 'out_value': 'KOO6',
    'competitions': 'R0C6', 'open_competitions': 'fjHt',
}


def transfers(vm_or_session, *, coach=0) -> dict:
    """The club's transfer activity (offers in and out for players, staff and trades:
    TRANSFER_ACTIVITY, type 131), the transfer and wage budgets (CLUB_UI_HANDLER) and the
    transfer window (TRANSFER_WINDOW, type 142)."""
    vm, view = _vm_and_view(vm_or_session, coach)
    started, rng0 = time.perf_counter(), vm.rng_uses
    refs = Refs(vm)
    parts = {
        'activity': read_screen(vm, TRANSFER_ACTIVITY, view.record(), TRANSFER_ACTIVITY_KEYS, refs=refs),
        'budgets': read_screen(vm, DATABASE_RECORD, {'dref': view.club_id}, CLUB_BUDGET_KEYS, refs=refs),
        'window': read_screen(vm, TRANSFER_WINDOW, view.record(comp=managed_league(vm, view)),
                              TRANSFER_WINDOW_KEYS, refs=refs),
    }
    return _answer(parts, started, rng0, vm, game_date=view.game_date, activity=parts['activity'].fields,
                   budgets=parts['budgets'].fields, window=parts['window'].fields)


# ---------------------------------------------------------------------- squad dynamics
DYNAMICS_KEYS = {
    'team_leaders': 'TeBK', 'highly_influential': 'FLaw', 'other': '9oKX', 'players_in_hierarchy': 'Odm5',
    'team_leaders_count': '8bsn', 'highly_influential_count': 'kNjS', 'influential_count': 'mhZb',
    'other_count': 'PNvL', 'highest_hierarchy_type': 'ONUa', 'positive_feedback': '1rJX',
    'social_groups': 'TQv0', 'key_personnel': '6F5W', 'dressing_room_atmosphere_level': 'gTJS',
}
SOCIAL_GROUPS = {'E3iL': 'core', 'E3iM': 'secondary_1', 'E3iN': 'secondary_2', 'E3iO': 'other',
                 'rLNK': 'core_count', 'rLNL': 'secondary_1_count', 'rLNM': 'secondary_2_count',
                 'rLNN': 'other_count'}


def squad_dynamics(vm_or_session, *, coach=0) -> dict:
    """Squad hierarchy and social groups as Squad > Dynamics shows them (TEAM_UI_HANDLER)."""
    vm, view = _vm_and_view(vm_or_session, coach)
    started, rng0 = time.perf_counter(), vm.rng_uses
    refs = Refs(vm)
    part = read_screen(vm, DATABASE_RECORD, {'dref': view.team_id}, DYNAMICS_KEYS, refs=refs,
                       inputs=TEAM_INPUTS)
    fields = dict(part.fields)
    groups = fields.pop('social_groups', None)
    if isinstance(groups, dict):
        fields['social_groups'] = {SOCIAL_GROUPS.get(k, k): v for k, v in groups.items()}
    return _answer({'team': part}, started, rng0, vm, game_date=view.game_date, **fields)


# ---------------------------------------------------------------------- training
TRAINING_KEYS = {
    'current_week': 'fFKF', 'current_week_days': 'eCOI', 'next_week_days': 'KTwK',
    'last_week_template': 'Qiuu', 'last_week_category': '6O0G', 'current_focus': 'WRyv',
    'next_week_focus': 'BZen', 'performance_status': 'A1kM', 'performance_month': '3llI',
    'average_rating': '3tgG', 'goalkeeping_unit': 'rRmW', 'defensive_unit': 'rPLf',
    'midfield_unit': 'VQFc', 'attacking_unit': 'GQbx', 'training_squad': 'UcjD',
    'best_ratings': 'eXrB', 'worst_ratings': 'CnwZ', 'intensities': 'qO8v',
}


def training(vm_or_session, *, coach=0) -> dict:
    """Team training as Training > Overview / Schedule show it (TEAM_TRAINING, type 128,
    record with 'Ttea', 'Team' and 'Hhum'; input 'TiSc' transfers)."""
    vm, view = _vm_and_view(vm_or_session, coach)
    started, rng0 = time.perf_counter(), vm.rng_uses
    refs = Refs(vm)
    part = read_screen(vm, TEAM_TRAINING, view.record(), TRAINING_KEYS, refs=refs)
    f = dict(part.fields)
    units = {name: f.pop(name) for name in ('goalkeeping_unit', 'defensive_unit', 'midfield_unit', 'attacking_unit')}
    schedule = f.pop('current_week')
    days = []
    if isinstance(schedule, list):
        # A flat list: day name followed by its three sessions (morning, afternoon, extra).
        names = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
        current = None
        for item in schedule:
            if item in names:
                current = {'day': item, 'sessions': []}
                days.append(current)
            elif current is not None:
                current['sessions'].append(item)
    return _answer({'training': part}, started, rng0, vm, game_date=view.game_date, schedule=days,
                   units=units, input_status=part.inputs, **f)


# ---------------------------------------------------------------------- medical
MEDICAL_KEYS = {
    'injury_summary_players': 'y2Ux', 'season_injury_summary': 'qJS2', 'returns_next_fixture': 'QF3x',
    'players_at_risk': 'pRmJ', 'exhausted_and_recurring': 'pRmL', 'risk_assessment': 'jz9N',
    'medical_staff_count': 'VbcC', 'injuries_header': 'g7AR',
}
RISK_GROUPS = {'iX5m': 'low', '8tNb': 'normal', 'HXII': 'increased', 'Up2H': 'high', 'WnMY': 'very_high'}


def medical(vm_or_session, *, coach=0) -> dict:
    """Medical Centre overview for the managed team (TEAM_UI_HANDLER): injury risk groups,
    injury summary, returns before the next match. The risk assessment draws random numbers
    (68 draws on the reference save): see fields_using_random_draws."""
    vm, view = _vm_and_view(vm_or_session, coach)
    started, rng0 = time.perf_counter(), vm.rng_uses
    refs = Refs(vm)
    part = read_screen(vm, DATABASE_RECORD, {'dref': view.team_id}, MEDICAL_KEYS, refs=refs,
                       inputs=TEAM_INPUTS)
    f = dict(part.fields)
    risk = f.pop('risk_assessment')
    if isinstance(risk, dict):
        f['risk_assessment'] = {RISK_GROUPS.get(k, k): v for k, v in risk.items()}
    return _answer({'team': part}, started, rng0, vm, game_date=view.game_date, **f)


# ---------------------------------------------------------------------- finances
FINANCE_KEYS = {
    'balance': 'bala', 'income_this_season': 'DX6O', 'expenditure_this_season': 'qGOh',
    'income_last_season': 'qVYZ', 'expenditure_last_season': 'PVPo', 'turnover_this_season': 'xl6M',
    'income_last_month': 'SJNN', 'expenditure_last_month': 'iLwz', 'expenditure_this_month': '9Vmx',
    'sponsorship_this_season': 'LoTZ', 'net_debt': 'nW00', 'transfer_debt': 'coCj',
    'loans': 'GG32', 'sponsorships': 'tP1R', 'balance_history': 'ev1w',
    'projection_balance': 'TLMW', 'projection_turnover': 'LRWa', 'projection_expenditure': 'jUZD',
    'projection_profit_loss': '6l1I', 'projection_wage_costs': 'Ux3G', 'projection_transfer_budget': 'LQPH',
    'wage_budget': '17CQ', 'remaining_wage_budget': 'i9nk', 'transfer_budget_at_start': 'Alvg',
    'transfer_budget_next_season': '7JWg', 'training_facilities': 'ux2P', 'youth_facilities': 'JJ7f',
    'corporate_facilities': 'gtkk', 'reputation_scope': 'wQp8',
}
PROJECTION_COLUMNS = {'AM m': 'this_season_end', 'YJRd': 'next_season_end', '7VhS': 'season_after_end'}


def finances(vm_or_session, *, coach=0) -> dict:
    """Finances summary and projections for the managed club (CLUB_UI_HANDLER). Money is GBP
    (integers) unless the game formatted it as text."""
    vm, view = _vm_and_view(vm_or_session, coach)
    started, rng0 = time.perf_counter(), vm.rng_uses
    part = read_screen(vm, DATABASE_RECORD, {'dref': view.club_id}, FINANCE_KEYS)
    f = dict(part.fields)
    for name in [n for n in f if n.startswith('projection_')]:
        value = f[name]
        if isinstance(value, dict):
            f[name] = {PROJECTION_COLUMNS.get(k, k): {'season': v.get('vw s'), 'label': v.get('namf'),
                                                      'value': v.get('ptvl'), 'trend': v.get('6epL')}
                       if isinstance(v, dict) else v for k, v in value.items()}
    return _answer({'club': part}, started, rng0, vm, game_date=view.game_date, **f)


# ---------------------------------------------------------------------- youth intake
YOUTH_KEYS = {
    'days_until_youth_intake': '91Jj', 'youth_intake_rating': 'g2Mv', 'youth_intake_level': 'aO95',
    'youth_intake_feedback': 'tzyJ', 'youth_intake_grade': 'ecbF', 'youth_intake_status': 'e5Rk',
    'youth_intake_description': 'JHbU', 'youth_intake_position_previews': 'JiyO',
    'youth_facilities': 'JJ7f',
}


def youth_intake(vm_or_session, *, coach=0) -> dict:
    """Youth intake preview for the managed club (CLUB_UI_HANDLER)."""
    vm, view = _vm_and_view(vm_or_session, coach)
    started, rng0 = time.perf_counter(), vm.rng_uses
    part = read_screen(vm, DATABASE_RECORD, {'dref': view.club_id}, YOUTH_KEYS)
    return _answer({'club': part}, started, rng0, vm, game_date=view.game_date, **part.fields)


# ---------------------------------------------------------------------- league table
TABLE_ROW = {'ztvp': 'position', 'gpld': 'played', 'gwon': 'won', 'gdrw': 'drawn', 'glos': 'lost',
             'glfr': 'goals_for', 'GAgn': 'goals_against', 'lgdf': 'goal_difference', 'glor': 'points',
             'Pqxg': 'colour_group'}
COMPETITION_KEYS = {'current_stage': 'stgr', 'colour_groups': 'r6m0', 'top_scorers': 'plst',
                    'xg_table': 'XGst', 'suspensions': 'PcJL'}
STAGE_KEYS = {'table': 'lgtb', 'last_games_table': 'lxgt', 'team_count': 'nmtm', 'colour_groups': 'uA0c'}


def _table(rows, refs):
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        item = {name: row.get(code) for code, name in TABLE_ROW.items()}
        item['team'] = refs(row.get('Team'))
        out.append(item)
    return out


def league_table(vm_or_session, competition=None, *, coach=0) -> dict:
    """League table of a competition's current stage (default: the managed team's league):
    COMPETITION_UI_HANDLER ('stgr' CurrentStage gives the stage record) then
    COMPETITION_STAGE (type 17) 'lgtb' LeagueTable; plus top scorers and xG table."""
    vm, view = _vm_and_view(vm_or_session, coach)
    started, rng0 = time.perf_counter(), vm.rng_uses
    refs = Refs(vm)
    if competition is None:
        competition = managed_league(vm, view)
    comp = read_screen(vm, DATABASE_RECORD, {'dref': competition}, COMPETITION_KEYS)
    stage_value = comp.fields.get('current_stage')
    stage = stage_value.get('uirp') if isinstance(stage_value, dict) else None
    parts = {'competition': comp}
    table = last = None
    if isinstance(stage, dict):
        ref = stage.get('dref')
        record = {'dref': (ref.get('dref') if isinstance(ref, dict) else ref) or competition,
                  'year': stage.get('year') or 0, 'mnst': (stage.get('mnst') or 0) & 0xFFFFFFFF,
                  'sbst': (stage.get('sbst') if stage.get('sbst') is not None else -1) & 0xFFFFFFFF,
                  'ssst': (stage.get('ssst') if stage.get('ssst') is not None else -1) & 0xFFFFFFFF}
        parts['stage'] = read_screen(vm, COMPETITION_STAGE, record, STAGE_KEYS)
        table = _table(parts['stage'].fields.get('table'), refs)
        last = _table(parts['stage'].fields.get('last_games_table'), refs)
    scorers = comp.fields.get('top_scorers')
    top = []
    if isinstance(scorers, dict):
        for row in scorers.get('77  ') or []:
            if isinstance(row, dict):
                top.append({'player': refs(row.get('plyr')), 'position': row.get('Posi'),
                            'goals': row.get('stvl'), 'apps': row.get('CSV1')})
    return _answer(parts, started, rng0, vm, game_date=view.game_date,
                   competition=refs.ref(competition), table=table, last_games_table=last,
                   colour_groups=comp.fields.get('colour_groups'), top_scorers=top,
                   xg_table=refs(comp.fields.get('xg_table')))


def managed_league(vm, view) -> int:
    """UI id of the managed team's main league (TEAM 'obpZ' MainDivision)."""
    # The TEAM handler's slot-17 inputs cost ~20 s and 'obpZ' does not need them.
    value = open_handler(vm, DATABASE_RECORD, {'dref': view.team_id}, inputs=False).get('obpZ').json_value()
    target = value.get('dref') if isinstance(value, dict) else None
    if not isinstance(target, int):
        raise _Stop('managed league not found', str(value)[:200])
    return target & 0xFFFFFFFF


# ---------------------------------------------------------------------- manager profile
MANAGER_KEYS = {
    'name': 'iSnm', 'job': 'b9r7', 'job_team_type': '8XCi', 'preferred_job': 'UqAJ',
    'weekly_wage': 'QNVC', 'preferred_mentality': 'R0St', 'preferred_pressing': 'gpHg',
    'contract_renewal_advice': 'W7Yc', 'contract_renewal_advice_reason': 'PaTB',
    'interested_clubs_count': 'sYaw', 'active_interested_clubs_count': '5LJ3',
    'offer_agreements': 'iI0d', 'nationality': 'natY',
}


def manager_profile(vm_or_session, *, coach=0, job_security=True) -> dict:
    """The human manager's profile (PERSON_UI_HANDLER on the manager) and, with
    job_security, the board's job-security figure and overall verdict (TEAM_CONFIDENCE,
    ~5-40 s more)."""
    vm, view = _vm_and_view(vm_or_session, coach)
    started, rng0 = time.perf_counter(), vm.rng_uses
    refs = Refs(vm)
    parts = {'manager': read_screen(vm, DATABASE_RECORD, {'dref': view.person_id}, MANAGER_KEYS, refs=refs)}
    extra = {}
    if job_security:
        parts['board'] = read_screen(vm, 114, {'Ttea': view.team_id}, {
            'job_security_from_contract': 'Gc5S', 'board_overall_grade': '4zmg', 'board_overall': 'tRDU',
            'supporters_overall': 'ScoS'})
        extra = {'job_security': parts['board'].fields}
    return _answer(parts, started, rng0, vm, game_date=view.game_date, **parts['manager'].fields, **extra)


# ---------------------------------------------------------------------- fixture result
FIXTURE_RESULT_KEYS = {
    'home_score': 'fxhs', 'away_score': 'fxas', 'result': 'fxrs', 'result_type': 'y4WE',
    'has_result': 'G62Z', 'has_final_result': 'WLvD', 'home_xg': 'JsGu', 'venue': 'KmOX',
    'kickoff': 'fxko', 'fixture_name': 'hQi0', 'goalscorers': '2fli', 'home_team_won': 'htWN',
    'away_team_won': 'atWN', 'home_possession': '7Qyd', 'away_possession': 'KOuC',
    'home_shots_on_target': '1NpQ', 'away_shots_on_target': 'TV7r', 'stage': 'stgn',
    'home_league_position': 'hlps', 'away_league_position': 'alps', 'weather': 'Zu6x',
    'home_events': 'lrdR', 'away_events': 'nOZa',
}


def fixture_record(home_id: int, away_id: int, si_date: int, context_team: int) -> dict:
    """The FIXTURE UI_RECORD the game itself builds (TEAM_CONFIDENCE 'MatchConfidenceFixtureList'
    entries): home/away team ids, SI_DATE 'fdte', 'ctxt' = the viewing team (the server's
    'FxRl' reads it from the record before falling back to HUMAN+0x438) and three -1 fields."""
    return {'fhmT': home_id, 'fawT': away_id, 'fdte': si_date, 'ctxt': context_team,
            'VMty': 0xFFFFFFFF, 'frhi': 0xFFFFFFFF, 'frht': 0xFFFFFFFF}


def fixture_result(vm_or_session, home_id: int, away_id: int, si_date: int, *, keys=None, coach=0) -> dict:
    """Score, result and match facts of one fixture (FIXTURE, type 50) with the game's own
    record form; the client inputs (isVM, lasc, slLL, tims) are transferred first."""
    vm, view = _vm_and_view(vm_or_session, coach)
    started, rng0 = time.perf_counter(), vm.rng_uses
    part = read_screen(vm, FIXTURE, fixture_record(home_id, away_id, si_date, view.team_id),
                       keys or FIXTURE_RESULT_KEYS)
    return _answer({'fixture': part}, started, rng0, vm, game_date=view.game_date,
                   input_status=part.inputs, **_fixture_shape(part.fields))


def _fixture_shape(fields: dict) -> dict:
    """Blank the score fields of a fixture without a result (the handler reads -1 there)."""
    out = dict(fields)
    if out.get('has_result') is False:
        for name in ('home_score', 'away_score', 'result'):
            out[name] = None
    return out


# ---------------------------------------------------------------------- season expectations
CLUB_VISION_SEASON_EXPECTATIONS = 15
SEASON_EXPECTATION_KEYS = {
    'competitions': 'Rp8X', 'competition_count': 'HdZq', 'new_transfer_budget': 'L427',
    'new_wage_budget': 'w9OD', 'new_remaining_wage_budget': 'nyfr',
}


def season_expectations(vm_or_session, *, coach=0) -> dict:
    """The board's competition expectations for this season (CLUB_VISION_MEETING_SEASON_
    EXPECTATIONS, type 15, record 'club' + 'PbPY'): per competition the expected stage, the
    importance (0..10, same bands as the club vision), the stage options with the selected
    minimum, and whether it can be or was set to 'not judged'. This is where the FA Cup
    expectation lives on the reference save; the club-vision objective list (CvBo) has no
    FA Cup row (docs/fmdb/UI_SWEEP.md)."""
    from .ui_recipes_person import importance_text
    vm, view = _vm_and_view(vm_or_session, coach)
    started, rng0 = time.perf_counter(), vm.rng_uses
    refs = Refs(vm)
    part = read_screen(vm, CLUB_VISION_SEASON_EXPECTATIONS, view.record(), SEASON_EXPECTATION_KEYS)
    rows = []
    for entry in part.fields.get('competitions') or []:
        if not isinstance(entry, dict):
            continue
        options = []
        for option in entry.get('IlIs') or []:
            text = (option.get('7CkW') or {}).get('qvJ6') if isinstance(option, dict) else None
            options.append({'option': text, 'selected': option.get('6dFg') if isinstance(option, dict) else None})
        importance = entry.get('t0IC')
        rows.append({'competition': refs(entry.get('VhSp')), 'expected_stage': entry.get('ko7Q'),
                     'importance_value': importance, 'importance': importance_text(importance),
                     'can_be_set_to_not_judged': entry.get('2M4t'), 'set_to_not_judged': entry.get('dM9T'),
                     'options': options, 'raw_flags': {'QQ8q': entry.get('QQ8q'), 'v7CP': entry.get('v7CP')}})
    fields = {k: v for k, v in part.fields.items() if k != 'competitions'}
    return _answer({'expectations': part}, started, rng0, vm, game_date=view.game_date, competitions=rows,
                   **fields)


SCREENS = {
    'scouting': scouting, 'transfers': transfers, 'squad_dynamics': squad_dynamics, 'training': training,
    'medical': medical, 'finances': finances, 'youth_intake': youth_intake, 'league_table': league_table,
    'manager_profile': manager_profile, 'season_expectations': season_expectations,
}


__all__ = ['KeyReader', 'KeyReading', 'transfer_inputs', 'open_handler', 'read_keys', 'counts',
           'install_param_trace', 'is_empty', 'status_of', 'read_screen', 'ScreenRead', 'Refs', 'viewer',
           'Viewer', 'SCREENS', 'fixture_record', 'fixture_result', *SCREENS]
