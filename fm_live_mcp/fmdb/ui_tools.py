"""MCP tools over the game's own UI handlers: fm_ui_schema, fm_ui_read,
fm_get_board_confidence, and thin wrappers over the recipe modules when present
(fm_get_inbox, fm_get_calendar from ui_recipes_news; fm_get_player_status,
fm_get_club_vision from ui_recipes_person).

Values are what the game's UI layer would display: `UiHandlerVM` builds the plugin's
handler pair from a UI_RECORD and runs the unmodified shipped code (factory, server
computation, input transfer, client getter) on copied live memory. Nothing is written
to the game. Random draws come from a VM-private copy of the game thread's generator
(`rng='copy'`): they are what the game would draw next, not necessarily what an
already-drawn screen showed. Only the factory (slots 3/5), server get (slot 2), client
set_input (slot 17, the game's own server-to-client transfer) and client get_property
(slot 4) are ever called; no set-property slot.

Results are cached on disk per (save, game date, handler, inputs) by `ui_cache`; the
emulator keeps one copy of live memory per game day (at most VM_MAX_AGE_S old).
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import re
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .. import players, world
from . import ui_cache, ui_registry, variant
from .ui_handlers import input_keys, plain_text
from .vm import Unavailable, _Stop

log = logging.getLogger(__name__)

TEAM_CONFIDENCE = 114
DATABASE_RECORD_TYPE = 28          # factory case that dispatches on the dref's table type (ui_recipes_more)
TEAM_TABLE_TYPE = 0x18             # UI object id table type of TEAM (Newcastle = 0x18000221)
PERSON_TABLE_TYPE = 0x01           # people-table index
CLUB_TABLE_TYPE = 0x03             # club-table index (ui_recipes_person.club_vision)
COMPETITION_TABLE_TYPE = 0x19      # competition-table index (Premier League = 0x19000007)
DEFAULT_TIME_BUDGET_S = 120
MAX_TIME_BUDGET_S = 600
BOARD_TIME_BUDGET_S = 300
DEFAULT_MAX_INSTRUCTIONS = 500_000_000
MAX_INSTRUCTIONS = 4_000_000_000
VM_MAX_AGE_S = 900
POOL_PAGES_SOFT_LIMIT = 100_000    # copied live pages (400 MiB) before the emulator drops them
VOLATILE_LIMIT = 8192
READ_BURST_S = 2.0
TWO_SEED_REUSE = 20                # recomputations that reuse a clean two-seed result
# Leaves that differ between two runs of the same computation without meaning anything.
TIMING_LEAVES = frozenset({'seconds', 'ms', 'timing', 'rng_uses', 'cpu_seconds', 'list_cpu_seconds',
                           'build_seconds', 'input_seconds', 'data_seconds', 'total_s',
                           'build_and_inputs_s', 'request_params_used', '_meta'})
RNG_MODE = 'copy'

UI_NOTE = (
    "This is what the game's own UI layer would show, computed by emulating shipped game code "
    "on a copy of game memory (nothing is written to the game). Values can depend on random "
    "draws taken from a private copy of the game's generator: they are what the game would draw "
    "next, not necessarily what a screen already showed (rng_uses counts them). The computation "
    "can take tens of seconds the first time each game day; later calls that day come from an "
    "on-disk cache whose answer says when it was computed (fresh=true recomputes from current "
    "memory).")

# Board grades are integers; these were matched against the Board screen (UI_HANDLERS.md and
# the owner's screenshots of 10 Dec 2030). 0 = no grade yet.
BOARD_GRADES = {5: 'C', 6: 'C+', 7: 'B-', 8: 'B', 9: 'B+', 11: 'A'}
BOARD_GRADES_INFERRED = {4: 'C-', 10: 'A-'}    # by the scale's order; not yet seen on a screen
# Supporter grades: a separate scale, lower is better (matched wording on the same screens).
SUPPORTER_GRADES = {1: 'very pleased', 3: 'pleased', 4: 'satisfied', 6: 'disappointed'}

# Six runs with the VM copy of the generator state (thread-local 0x56C44F8, 16 bytes)
# perturbed changed none of the 71 TEAM_CONFIDENCE keys (Newcastle, 10 Dec 2030), although
# the state advanced by the 8 draws each time. Keys that changed would be listed here.
BOARD_RNG_DEPENDENT_KEYS: frozenset = frozenset()
BOARD_RNG_EVIDENCE = (
    'Empirical: the computation draws 8 numbers; with the private generator state perturbed in '
    'six runs no TEAM_CONFIDENCE key changed (Newcastle, 10 Dec 2030), so no field below is known '
    'to depend on the draws. Fields listed in fields_depending_on_draws would.')
FEE_NOTE = ('Raw TEAM_CONFIDENCE "Fee" (K0qE): the TRANSFER record\'s cash field, which the '
            'person-handlers lane (UI_PERSON.md) reads as GBP fixed at signing (game money is stored '
            'in GBP). It does not equal the Board screen (Huber 5,340,963 here, £5.25M shown); the '
            'screen probably converts the fee agreed in the seller\'s currency at today\'s rate. '
            'Not verified.')

# UI_RECORD fields known per handler type (from the live recipes in UI_HANDLERS.md).
RECORD_DOCS = {
    114: {'Ttea': 'team object id (0x18 << 24 | team-table index); token "managed_team"'},
    75: {'Pers': 'person object id (1 << 24 | people-table index); token "person:<index>"',
         'PbPY': 'the human manager\'s person object id; token "managed_manager"'},
    128: {'Ttea': 'team object id; token "managed_team"',
          'PbPY': 'the human manager\'s person object id; token "managed_manager" (without it input '
                  'TiSc dereferences null at 0x43FEB48 and every unit reads "Goalkeeping Unit")'},
    50: {'fhmT': 'home team object id', 'fawT': 'away team object id', 'fdte': 'SI_DATE payload',
         'ctxt': 'viewing team object id (server key FxRl reads it; without it, it dereferences HUMAN+0x438)',
         'VMty': '0xFFFFFFFF', 'frhi': '0xFFFFFFFF', 'frht': '0xFFFFFFFF'},
    97: {'iyrZ': 'team object id (SCOUTING_INFO: recruitment focuses, scouting budget and range)',
         'PbPY': 'manager person object id'},
    70: {'huma': 'manager person index', 'unid': 'news item unique id (item+0x90); no item found yet'},
    9: {'Ttea': 'team object id', 'Hhum': 'human object; every CALENDAR input currently stops'},
}

_LOCK = threading.Lock()
_STATE: dict = {'session': None}


class UiToolError(RuntimeError):
    """The request cannot be served; the message says why and what to do."""


# --------------------------------------------------------------------------- registry helpers
def registry():
    reg = ui_registry.default()
    if reg.build != players.SHA256:
        raise UiToolError('UI registry data is for another plugin build; rebuild it with '
                          'scripts/fmdb_ui_registry_build.py --live')
    return reg


def buildable_types(reg) -> dict:
    return {t: row for t, row in sorted(reg.types.items()) if row.get('client')}


def resolve_handler(reg, handler) -> tuple[int, dict]:
    """Handler type number (or class name, with or without _UI_HANDLER) -> (type, row)."""
    if isinstance(handler, bool):
        raise UiToolError('handler must be a type number or a class name')
    if isinstance(handler, int) or (isinstance(handler, str) and handler.strip().isdigit()):
        number = int(handler)
    elif isinstance(handler, str) and handler.strip():
        name = handler.strip().split('::')[-1].upper()
        if not name.endswith('_UI_HANDLER'):
            name += '_UI_HANDLER'
        number = reg.type_of(name)
        if number is None and name in reg.classes:
            # A database record's handler (TEAM, PERSON, CLUB, COMPETITION ...): factory type 28 builds
            # the class of the object its 'dref' names, so the class has no type number of its own.
            return DATABASE_RECORD_TYPE, {'client': name, 'server': None, 'record_class': True}
        if number is None:
            close = [r['client'] for r in reg.types.values()
                     if r.get('client') and name.replace('_UI_HANDLER', '') in r['client']][:8]
            raise UiToolError(f'no buildable handler type has client class {name}'
                              + (f'; similar: {", ".join(close)}' if close else ''))
    else:
        raise UiToolError('handler must be a type number or a class name')
    row = reg.types.get(number)
    if row is None:
        raise UiToolError(f'unknown handler type {number} (types are 1..144; see fm_ui_schema)')
    if not row.get('client'):
        raise UiToolError(f'handler type {number} is not buildable: {row.get("client_error") or "no client handler"}')
    return number, row


def handler_info(reg, number: int, row: dict, *, keys: bool) -> dict:
    client = reg.classes.get(row['client'])
    server = reg.classes.get(row['server']) if row.get('server') else None
    inputs = list(input_keys(reg, row['client']))
    out = {'type': number, 'client': row['client'], 'server': row.get('server'),
           'input_keys': [{'key': k, 'label': reg.label(k)} for k in inputs],
           'key_count': len(client.keys(4)) if client else 0}
    docs = RECORD_DOCS.get(number)
    if docs:
        out['record_fields'] = docs
    if server is not None:
        fourccs = [c for c in server.slots.get('2', {}).get('fourccs', ()) if c not in inputs]
        if fourccs:
            out['server_fourccs'] = fourccs
    if keys and client:
        out['keys'] = [{'key': k, 'label': reg.label(k)} for k in client.keys(4)]
    return out


def ui_schema(handler=None, search=None, *, limit=200) -> dict:
    """Offline description of the UI handler registry (pinned to the plugin build)."""
    reg = registry()
    note = ('Inputs for fm_ui_read are UI_RECORD fields {fourcc: u32}. input_keys are what the '
            'client consumes from its server (slot-16 declarations and slot-17 immediates); '
            'record_fields are documented where a live recipe established them; server_fourccs '
            'are other FourCCs the server compares or reads (candidate record fields).')
    if handler is not None:
        number, row = resolve_handler(reg, handler)
        out = handler_info(reg, number, row, keys=True)
        out['note'] = note
        return out
    if search is not None:
        text = search.strip().lower()
        if len(text) < 2:
            raise UiToolError('search needs at least 2 characters')
        owners = {}
        for number, row in buildable_types(reg).items():
            client = reg.classes.get(row['client'])
            for code in client.keys(4) if client else ():
                owners.setdefault(code, []).append(number)
        hits = []
        for code, label in reg.labels.items():
            if text in label.lower() or text == code.lower():
                hits.append({'key': code, 'label': label, 'handler_types': owners.get(code, [])})
        hits.sort(key=lambda h: (not h['handler_types'], h['label']))
        return {'search': search, 'matches': hits[:limit], 'truncated': len(hits) > limit,
                'note': 'handler_types lists the buildable handlers whose get_property materialises the key.'}
    types = [handler_info(reg, n, r, keys=False) for n, r in buildable_types(reg).items()]
    not_built = {n: r.get('client_error') for n, r in sorted(reg.types.items()) if not r.get('client')}
    return {'build': reg.build, 'handler_types': types, 'not_buildable': not_built, 'note': note}


# --------------------------------------------------------------------------- live session
class UiSession:
    """One attached FM27 process: fast memory reader, plugin image, UI emulators."""

    def __init__(self, *, pid, executable, base, plugin_path, process_key, layout):
        from .image import PluginImage
        from .memory import LiveMemory
        self.pid, self.base, self.plugin_path = pid, base, Path(plugin_path)
        self.process_key, self.layout = process_key, layout
        self.memory = LiveMemory(pid, expected_executable=executable)
        self.image = PluginImage.load(self.plugin_path)
        self.lock = threading.RLock()
        self._vms = {}
        self.process = [pid, str(process_key[2])]   # the address space read sets belong to
        self.volatile = set()                       # live pages seen to change between checks
        self._volatile_loaded = None
        self._resolver = None

    @classmethod
    def from_bridge(cls, bridge, session_id, existing=None):
        """Run the Bridge's pinned-build check; reuse `existing` for the same process (the
        check ran when it was made: build, plugin and load address cannot change in a process)."""
        try:
            with bridge.lock:
                process = bridge._current(session_id)
                key = (process.pid, process.executable, process.started)
                if existing is not None and existing.process_key == key:
                    return existing
                with bridge._read_scope(session_id):
                    layout = bridge._player_layout(process)
                plugin_path = Path(bridge.plugin_identity[0][0])
        except Exception as exc:  # noqa: BLE001 - BridgeError and verification failures
            raise UiToolError(f'{exc} (call fm_attach first if the session is unknown)') from exc
        base = layout[0] - players.RVA[0]
        if existing is not None and existing.process_key == key and existing.base == base \
                and existing.plugin_path == plugin_path:
            existing.layout = layout
            return existing
        if existing is not None:
            existing.close()
        return cls(pid=process.pid, executable=process.executable, base=base,
                   plugin_path=plugin_path, process_key=key, layout=layout)

    def close(self):
        self._vms.clear()
        try:
            self.memory.close()
        except Exception:  # noqa: BLE001
            pass

    def read(self, address, length):
        return self.memory.read(address, length)

    def save_state(self) -> dict:
        """Save identity, save count and game date, read uncached and re-verified."""
        reader = world.ReadSet(self.read)
        try:
            record, _ = world.loaded(reader, self.base)
            reader.verify()
        except ValueError as exc:
            raise UiToolError(f'Loaded career not readable: {exc}. Load a career in FM27 and retry.') from exc
        return {'record': record, 'game_date': record['current_date'], 'save_count': record['save_count'],
                'save_name': record['name'],
                'save_key': ui_cache.save_key(record['name'], record['created_date'], record['created_version'])}

    def cache(self, state) -> ui_cache.UiCache:
        return ui_cache.UiCache(state['save_key'], state['game_date'], save_count=state['save_count'],
                                build=players.SHA256)

    def screen_cache(self, state) -> ui_cache.ScreenCache:
        """Answers keyed by object identity and validated by read set (ui_cache version 2)."""
        store = ui_cache.ScreenCache(state['save_key'], build=players.SHA256)
        if self._volatile_loaded != state['save_key']:
            self._volatile_loaded = state['save_key']
            try:
                saved = json.loads(self._volatile_path(store).read_text())
                if saved.get('process') == self.process:
                    self.volatile.update(saved['pages'])
                else:
                    store.prune_process(self.process)
            except (OSError, ValueError, KeyError):
                pass
        return store

    def _volatile_path(self, store):
        return store.dir / 'volatile-pages.json'

    def note_volatile(self, store, pages):
        """Remember live pages that changed between a computation and its check: the next
        traced computation records its reads of them per word (FastUiHandlerVM.watch)."""
        new = set(pages) - self.volatile
        if not new or len(self.volatile) >= VOLATILE_LIMIT:
            return
        self.volatile.update(new)
        try:
            store.dir.mkdir(parents=True, exist_ok=True)
            self._volatile_path(store).write_text(json.dumps({'process': self.process,
                                                              'pages': sorted(self.volatile)}))
        except OSError:
            pass

    def vm(self, mode, state, *, fresh=False, max_instructions=None):
        """The emulator for `mode` ('fast': no instruction limit; 'guarded': an instruction
        limit per call). The accelerated emulator lives as long as the save is loaded: it
        re-reads each copied page from the game before use in a new read (generations), so
        fresh=True and a new game date need no new emulator. The reference emulator copies
        live memory once per (save, game date, save count), at most VM_MAX_AGE_S old."""
        from .ui_vm import UiHandlerVM, lsof_resolver
        key = (state['save_key'], state['game_date'], state['save_count'])
        entry = self._vms.get(mode)
        if entry is not None and entry['generations']:
            if entry['key'][0] != key[0] or entry['limit'] != max_instructions:
                entry = None
            elif entry['vm'].live_pages.__len__() > POOL_PAGES_SOFT_LIMIT:
                entry['vm'].invalidate()               # keeps the instance and its translated code
        elif entry is not None and (fresh or entry['key'] != key or time.time() - entry['created'] > VM_MAX_AGE_S
                                    or entry['limit'] != max_instructions):
            entry = None
        if entry is None:
            self._vms.pop(mode, None)
            if self._resolver is None:
                self._resolver = lsof_resolver(self.pid)
            vm = UiHandlerVM(self.memory, self.base, self.image, file_resolver=self._resolver, rng=RNG_MODE)
            vm.fast()
            if max_instructions:
                vm.limit_instructions(max_instructions)
            entry = self._vms[mode] = {'vm': vm, 'key': key, 'created': time.time(), 'limit': max_instructions,
                                       'generations': hasattr(vm, 'trace_begin')}
        return entry['vm']

    # -- references ---------------------------------------------------------------
    def table_index(self, kind, address) -> int | None:
        from . import tables
        try:
            return tables.entries(self.read, self.base, kind).index(address)
        except ValueError:
            return None

    def team_object_id(self, team) -> int:
        index = self.table_index('teams', team)
        if index is None:
            raise UiToolError('team record is not in the live team table')
        return (TEAM_TABLE_TYPE << 24) | index

    def club_first_team(self, bridge, club_ref) -> int:
        with bridge.lock:
            try:
                _, address, _, _ = bridge._referenced_club(self.read, self.base, club_ref, self.layout)
            except Exception as exc:  # noqa: BLE001 - BridgeError
                raise UiToolError(str(exc)) from exc
        begin, end = struct.unpack('<QQ', self.read(address + 0x18, 16))
        if begin == end:
            raise UiToolError('club has no teams')
        return struct.unpack('<Q', self.read(begin, 8))[0]


def session_for(bridge, session_id) -> UiSession:
    with _LOCK:
        _STATE['session'] = UiSession.from_bridge(bridge, session_id, _STATE['session'])
        return _STATE['session']


# --------------------------------------------------------------------------- computation
BUDGET_TEXT = 'emulation stopped early (timeout)'


def _budget_reason(text):
    return text.replace(BUDGET_TEXT, 'stopped by the instruction or time budget') if isinstance(text, str) else text


def row_json(code, label, kind, value, seconds) -> dict:
    row = {'key': code, 'label': label, 'kind': kind}
    if isinstance(value, Unavailable):
        row.update(status='unavailable', reason=_budget_reason(value.reason))
        if value.detail:
            row['detail'] = value.detail
    else:
        row['value'] = plain_text(variant.to_json(value))
        row['status'] = 'unset' if value in (None, '', [], {}) or kind == 'null' else 'value'
    row['ms'] = round(seconds * 1000, 1)
    return row


def normalize_params(params) -> dict:
    """{screen parameter name: int | bool} -> {name (lower case): int} (names: ui_params.table())."""
    if not params:
        return {}
    from . import ui_params
    if not isinstance(params, dict) or len(params) > 16:
        raise UiToolError('params must be an object {parameter name: integer}, at most 16 entries')
    out = {}
    for name, value in params.items():
        key = str(name).lower()
        if key not in ui_params.table():
            raise UiToolError(f'unknown screen parameter {name!r} (see docs/fmdb/UI_ROUND2.md)')
        if isinstance(value, bool):
            value = int(value)
        if not isinstance(value, int) or not -0x80000000 <= value <= 0xFFFFFFFF:
            raise UiToolError(f'{name}: parameter values are 32-bit integers')
        out[key] = value
    return out


def compute_handler_params(vm, number, record, keys, params, *, deadline, reg, context=None,
                           record_class=None) -> dict:
    """compute_handler with screen parameters: every key is read by ui_recipes_more.KeyReader
    (all client protocols) with the parameter lookups 0x77E228 answered from `params`. `context`
    ({data key: UI object id}) is handed to every server computation as object arguments
    (ui_recipes_analytics.ObjectContextKeyReader). `record_class`: the client class a database
    record's dref must build (type 28)."""
    from . import ui_params
    from .ui_recipes_more import KeyReader, TEAM_INPUTS
    started = time.perf_counter()
    rng0 = vm.rng_uses
    vm.timeout_us = max(1000, int((deadline - time.time()) * 1e6))
    try:
        handler = vm.build(number, record)
    except _Stop as stop:
        raise UiToolError(f'handler type {number} did not build: {_budget_reason(stop.reason)} '
                          f'{stop.detail or ""}'.strip()) from None
    if record_class and handler.client_class != record_class:
        raise UiToolError(f"dref {record.get('dref')!r} builds {handler.client_class}, not {record_class}")
    inputs = {}
    # TEAM_UI_HANDLER's slot-17 inputs take ~20 s and most of the VM heap, and its keys read the same
    # without them (ui_recipes_more.TEAM_INPUTS).
    if handler.server and (TEAM_INPUTS or handler.client_class != 'TEAM_UI_HANDLER'):
        for key in input_keys(reg, handler.client_class):
            if time.time() >= deadline:
                inputs[key] = 'unavailable: time budget exhausted before this input'
                continue
            inputs[key] = _budget_reason(vm.transfer(handler, key))
    if context:
        from .ui_recipes_analytics import ObjectContextKeyReader
        reader = ObjectContextKeyReader(vm, handler, reg, context)
    else:
        reader = KeyReader(vm, handler, reg)
    by_rva = {ui_params.rva_of(name): value for name, value in (params or {}).items()}
    rows = []
    for code in keys:
        if time.time() >= deadline:
            rows.append(row_json(code, reg.label(code), None, Unavailable('time budget exhausted before this key'), 0))
            continue
        vm.timeout_us = max(1000, int((deadline - time.time()) * 1e6))
        r = reader.get(code, params=by_rva)
        row = row_json(code, reg.label(code), r.kind, r.value, r.seconds)
        if r.params_read:
            row['params_read'] = [d['name'] or d['rva'] for d in ui_params.describe(r.params_read)]
        rows.append(row)
    return {'handler_type': number, 'client': handler.client_class, 'server': handler.server_class,
            'record': dict(record), 'params': dict(params or {}), **({'context': dict(context)} if context else {}),
            'input_status': inputs, 'rows': rows,
            'rng_uses': vm.rng_uses - rng0, 'files_read': sorted(Path(p).name for p in vm.files_read),
            'timing': {'total_s': round(time.perf_counter() - started, 2)}}


def compute_handler(vm, number, record, keys, *, deadline, reg, params=None, context=None,
                    record_class=None) -> dict:
    """Build, transfer every declared input, read `keys`; all inside the time budget."""
    if params or context or record_class:
        return compute_handler_params(vm, number, record, keys, params or {}, deadline=deadline, reg=reg,
                                      context=context, record_class=record_class)
    started = time.perf_counter()
    rng0 = vm.rng_uses

    def remaining_us():
        return max(1000, int((deadline - time.time()) * 1e6))
    vm.timeout_us = remaining_us()
    try:
        handler = vm.build(number, record)
    except _Stop as stop:
        raise UiToolError(f'handler type {number} did not build: {_budget_reason(stop.reason)} '
                          f'{stop.detail or ""}'.strip()) from None
    inputs = {}
    if handler.server:
        for key in input_keys(reg, handler.client_class):
            if time.time() >= deadline:
                inputs[key] = 'unavailable: time budget exhausted before this input'
                continue
            vm.timeout_us = remaining_us()
            inputs[key] = _budget_reason(vm.transfer(handler, key))
    input_seconds = time.perf_counter() - started
    rows = []
    for code in keys:
        t0 = time.perf_counter()
        if time.time() >= deadline:
            value, kind = Unavailable('time budget exhausted before this key'), None
        else:
            vm.timeout_us = remaining_us()
            result = vm.get(handler, code)
            value, kind = result.value, result.kind
        rows.append(row_json(code, reg.label(code), kind, value, time.perf_counter() - t0))
    return {'handler_type': number, 'client': handler.client_class, 'server': handler.server_class,
            'record': dict(record), 'input_status': inputs, 'rows': rows, 'rng_uses': vm.rng_uses - rng0,
            'files_read': sorted(Path(p).name for p in vm.files_read),
            'timing': {'build_and_inputs_s': round(input_seconds, 2),
                       'total_s': round(time.perf_counter() - started, 2)}}


def summary(rows) -> dict:
    out = {'value': 0, 'unset': 0, 'unavailable': 0}
    for row in rows:
        out[row['status']] += 1
    return out


# --------------------------------------------------------------------------- fm_ui_read
_FOURCC = re.compile(r'^[\x20-\x7e]{1,4}$')


def _fourcc(text) -> str:
    if not isinstance(text, str) or not _FOURCC.match(text):
        raise UiToolError(f'invalid FourCC {text!r}: 1-4 printable characters')
    return text.ljust(4)


def normalize_record(inputs) -> dict:
    """{fourcc: u32 | "0x..." | "managed_team" | "managed_manager" | "team:N" | "person:N"}."""
    if inputs is None:
        return {}
    if not isinstance(inputs, dict):
        raise UiToolError('inputs must be an object {FourCC: value}')
    out = {}
    for key, value in inputs.items():
        code = _fourcc(key)
        if code == '110 ':
            raise UiToolError("'110 ' is the handler type; pass handler instead")
        if isinstance(value, bool):
            raise UiToolError(f'{code}: booleans are not UI_RECORD values')
        if isinstance(value, int):
            if not 0 <= value <= 0xFFFFFFFF:
                raise UiToolError(f'{code}: value must be a u32')
        elif isinstance(value, str):
            text = value.strip()
            if text in ('managed_team', 'managed_manager') or re.fullmatch(r'(team|person):\d+', text):
                value = text
            else:
                try:
                    value = int(text, 0)
                except ValueError:
                    raise UiToolError(f'{code}: {value!r} is not a u32, hex string or token') from None
                if not 0 <= value <= 0xFFFFFFFF:
                    raise UiToolError(f'{code}: value must be a u32')
        else:
            raise UiToolError(f'{code}: value must be an integer or string')
        out[code] = value
    if len(out) > 32:
        raise UiToolError('at most 32 UI_RECORD fields')
    return out


def resolve_tokens(session, state, record) -> dict:
    out = {}
    coach = state['record']['coaches'][0] if state['record']['coaches'] else None
    for code, value in record.items():
        if isinstance(value, int):
            out[code] = value
            continue
        if value in ('managed_team', 'managed_manager') and coach is None:
            raise UiToolError('no human manager in the loaded career')
        if value == 'managed_team':
            out[code] = session.team_object_id(coach['team_address'])
        elif value == 'managed_manager':
            # the people table holds the PERSON part of the HUMAN_NON_PLAYER record, at +0x548
            # (ui_recipes_news.PERSON_HUMAN_OFFSET; the 'huma' index at +0x550 names the same entry)
            from .ui_recipes_news import PERSON_HUMAN_OFFSET
            index = session.table_index('people', coach['manager_address'] + PERSON_HUMAN_OFFSET)
            if index is None:
                raise UiToolError('manager record is not in the live people table')
            out[code] = (PERSON_TABLE_TYPE << 24) | index
        else:
            kind, index = value.split(':')
            out[code] = ((TEAM_TABLE_TYPE if kind == 'team' else PERSON_TABLE_TYPE) << 24) | (int(index) & 0x7FFFFF)
    return out


def resolve_keys(reg, client_class, keys) -> list:
    client = reg.classes.get(client_class)
    available = list(client.keys(4)) if client else []
    if keys is None:
        return available
    out = []
    for item in keys:
        if isinstance(item, str) and len(item) <= 4 and _FOURCC.match(item) and (item.ljust(4) in reg.labels or item.ljust(4) in available):
            code = item.ljust(4)
        else:
            codes = [c for c in reg.codes(str(item)) if c in available] or reg.codes(str(item))
            if not codes:
                raise UiToolError(f'unknown key or label {item!r} (see fm_ui_schema handler=...)')
            code = codes[0]
        if code not in out:
            out.append(code)
    return out


def ui_read(bridge, session_id, handler, inputs=None, keys=None, fresh=False, *,
            time_budget_s=DEFAULT_TIME_BUDGET_S, max_instructions=DEFAULT_MAX_INSTRUCTIONS, params=None,
            context=None) -> dict:
    reg = registry()
    number, row = resolve_handler(reg, handler)
    record = normalize_record(inputs)
    params = normalize_params(params)
    context = normalize_record(context)
    if len(context) > 8:
        raise UiToolError('at most 8 context objects')
    if row.get('record_class') and 'dref' not in record:
        raise UiToolError(f"{row['client']} is a database record's handler: pass the object as "
                          'inputs={"dref": <UI id, "managed_team", "team:<index>" or "person:<index>">}')
    wanted = resolve_keys(reg, row['client'], keys)
    if not wanted:
        raise UiToolError(f'handler type {number} has no known keys; pass keys explicitly')
    time_budget_s = min(max(1, int(time_budget_s)), MAX_TIME_BUDGET_S)
    max_instructions = min(max(1_000_000, int(max_instructions)), MAX_INSTRUCTIONS)
    session = session_for(bridge, session_id)
    with session.lock:
        state = session.save_state()
        record = resolve_tokens(session, state, record)
        context = resolve_tokens(session, state, context)
        kind, key = f'handler:{number}', {'record': record, 'rng': RNG_MODE}
        if params:
            key['params'] = params
        if context:
            key['context'] = context
        extra = {**({'params': params} if params else {}), **({'context': context} if context else {}),
                 **({'record_class': row['client']} if row.get('record_class') else {})}
        if row.get('record_class'):
            key['class'] = row['client']
        if fingerprinting(session):
            previous = session.screen_cache(state).get(kind, key) if not fresh else None
            codes = list(dict.fromkeys(wanted + (list(previous['rows']) if previous else [])))

            def compute(vm):
                result = compute_handler(vm, number, record, codes, deadline=time.time() + time_budget_s, reg=reg,
                                         **extra)
                payload = {k: v for k, v in result.items() if k != 'rows'}
                payload['rows'] = {r['key']: r for r in result['rows']}
                payload['budgets'] = {'time_s': time_budget_s, 'max_instructions_per_call': max_instructions}
                payload['game_date'] = state['game_date']
                payload['stopped_on_budget'] = stopped_on_budget(result)
                return payload
            entry, block = tracked(session, state, kind, key, compute, fresh=fresh, mode='guarded',
                                   max_instructions=max_instructions,
                                   complete=lambda payload: not payload['stopped_on_budget'],
                                   usable=lambda e: all(code in e['rows'] for code in wanted))
            rows = dict(entry['rows'])
            for code, value in rows.items():       # a row the two-seed rule withheld as a whole
                if 'status' not in value:
                    rows[code] = {'key': code, 'label': reg.label(code), 'kind': None, 'status': 'unavailable',
                                  'reason': value.get('unavailable', 'withheld')}
            out = _read_answer(dict(entry, rows=rows, game_date=state['game_date']), wanted, number, row,
                               hit=block['hit'])
            out['cache'] = block
            return out
        cache = session.cache(state)
        entry = cache.get(kind, key)
        if entry and not fresh and all(code in entry['rows'] for code in wanted):
            return _read_answer(entry, wanted, number, row, hit=True)
        deadline = time.time() + time_budget_s
        vm = session.vm('guarded', state, fresh=fresh, max_instructions=max_instructions)
        codes = list(dict.fromkeys(wanted + (list(entry['rows']) if entry and not fresh else [])))
        result = compute_handler(vm, number, record, codes, deadline=deadline, reg=reg, **extra)
        payload = {k: v for k, v in result.items() if k != 'rows'}
        payload['rows'] = {r['key']: r for r in result['rows']}
        payload['budgets'] = {'time_s': time_budget_s, 'max_instructions_per_segment': max_instructions}
        payload['game_date'] = state['game_date']
        if stopped_on_budget(result):
            entry = cache.entry(kind, key, dict(payload, stored=False))
        else:
            entry = cache.put(kind, key, payload)
        return _read_answer(entry, wanted, number, row, hit=False)


def stopped_on_budget(result) -> bool:
    texts = [str(s) for s in result['input_status'].values()]
    texts += [r.get('reason', '') for r in result['rows']]
    return any('budget' in t for t in texts)


def _read_answer(entry, wanted, number, row, *, hit) -> dict:
    rows = [entry['rows'][code] for code in wanted]
    out = {'handler_type': number, 'client': row['client'], 'server': row.get('server'),
           'record': entry['record'], 'input_status': entry['input_status'], 'rows': rows, 'summary': summary(rows),
           'rng_uses': entry['rng_uses'], 'timing': entry['timing'], 'budgets': entry.get('budgets'),
           'game_date': entry['game_date'], 'cache': ui_cache.describe(entry, hit=hit)}
    failed = {k: v for k, v in entry['input_status'].items() if not str(v).startswith('ok')}
    if failed:
        out['warning'] = ('Some inputs did not transfer; keys fed by them read as unset: '
                          + '; '.join(f'{k}: {v}' for k, v in failed.items()))
    return out


# --------------------------------------------------------------------------- board confidence
def board_grade(value):
    if not isinstance(value, int) or isinstance(value, bool):
        return {'value': value, 'letter': None}
    if value == 0:
        return {'value': 0, 'letter': None, 'note': 'no grade yet'}
    if value in BOARD_GRADES:
        return {'value': value, 'letter': BOARD_GRADES[value]}
    if value in BOARD_GRADES_INFERRED:
        return {'value': value, 'letter': BOARD_GRADES_INFERRED[value], 'letter_verified': False}
    return {'value': value, 'letter': None, 'note': 'grade value not yet matched to a screen'}


def supporter_grade(value):
    if not isinstance(value, int) or isinstance(value, bool):
        return {'value': value, 'wording': None}
    out = {'value': value, 'wording': SUPPORTER_GRADES.get(value), 'scale': 'lower is better'}
    if value not in SUPPORTER_GRADES:
        out['note'] = 'value not yet matched to a screen'
    return out


def _date(value):
    if isinstance(value, int):
        decoded = variant.si_date(value)
        return decoded.iso if hasattr(decoded, 'iso') else None
    if isinstance(value, dict):
        return value.get('date')
    return value


class _Names:
    """Display names of UI object ids (people via the game's own 'Pnam' getter; teams via
    their club record), resolved on the emulator that produced the answer."""

    def __init__(self, session, vm):
        from . import tables
        self.session, self.vm = session, vm
        self._tables = {}
        self._entries = tables.entries
        self.cache = {}

    def _record(self, kind, index):
        if kind not in self._tables:
            self._tables[kind] = self._entries(self.session.read, self.session.base, kind)
        rows = self._tables[kind]
        return rows[index] if 0 <= index < len(rows) else 0

    def name(self, ref):
        oid = ref.get('dref') if isinstance(ref, dict) else ref
        if not isinstance(oid, int):
            return None
        if oid in self.cache:
            return self.cache[oid]
        kind, index = oid >> 24, oid & 0x7FFFFF
        name = None
        try:
            if kind == PERSON_TABLE_TYPE:
                record = self._record('people', index)
                if record:
                    value = self.vm.get_property(record, 'Pnam').value
                    if isinstance(value, dict):
                        name = value.get('Pcna') or ' '.join(p for p in (value.get('Pfna'), value.get('Psna')) if p)
            elif kind == TEAM_TABLE_TYPE:
                team = self._record('teams', index)
                if team:
                    club = struct.unpack('<Q', self.session.read(team + 0x30, 8))[0]
                    name = world.club(self.session.read, self.session.base, club)[0]['name']
        except Exception:  # noqa: BLE001 - a name is a convenience; the id stays in the answer
            name = None
        self.cache[oid] = name or None
        return self.cache[oid]


def shape_board_confidence(values: dict, names, game_date) -> dict:
    """Structured Board/Supporter confidence from TEAM_CONFIDENCE key values (by FourCC)."""
    v = values.get

    def strn(items):
        return [{'text': i.get('Strn'), 'positive': i.get('haz1')} if isinstance(i, dict) else i
                for i in (items or [])]

    signings = []
    for t in v('TjWO') or []:
        board, fans = t.get('pbk5') or {}, t.get('0Uxv') or {}
        signings.append({
            'name': names.name(t.get('plyr')), 'player_object_id': (t.get('plyr') or {}).get('dref'),
            'from_club': names.name(t.get('TOst')), 'wage': t.get('Pcww'), 'on_loan': t.get('twlj'),
            'fee_raw': t.get('K0qE'), 'fee_note': FEE_NOTE, 'guaranteed_fee_raw': t.get('QhuE'),
            'potential_fee_raw': t.get('lsUe'), 'profit_raw': t.get('LDNp'), 'date': _date(t.get('CqMA')),
            'board': {'grade': board_grade(board.get('r5Fk')), 'feedback': board.get('desc')},
            'supporters': {'grade': supporter_grade(fans.get('r5Fk')), 'reaction': fans.get('desc')},
        })
    players_ = [{'name': names.name(p.get('plyr')), 'player_object_id': (p.get('plyr') or {}).get('dref'),
                 'grade': supporter_grade(p.get('r5Fk')), 'reaction': p.get('y789'), 'position_raw': p.get('Posi')}
                for p in v('71fR') or []]
    recent = [{'date': _date(m.get('fdte')), 'result': m.get('fxrs'), 'result_type_raw': m.get('y4WE'),
               'board': {'grade': board_grade(m.get('YCq7')), 'sentence': m.get('vxPz'),
                         'highlights': m.get('iajq'), 'criticisms': m.get('SZtr')},
               'supporters': {'grade': supporter_grade(m.get('GuH4')), 'sentence': m.get('PUk1'),
                              'highlights': m.get('GUph'), 'criticisms': m.get('3hBS')}}
              for m in v('FAtR') or []]
    fixtures = []
    for f in v('8l7J') or []:
        when = _date(f.get('fdte'))
        fixtures.append({'date': when, 'home': names.name(f.get('fhmT')), 'away': names.name(f.get('fawT')),
                         'home_object_id': f.get('fhmT'), 'away_object_id': f.get('fawT'),
                         'upcoming': bool(when and game_date and when > game_date)})
    upcoming = [f for f in fixtures if f['upcoming']]
    return {
        'overall': {'grade': board_grade(v('4zmg')), 'sentence': v('tRDU')},
        'areas': {
            'club_vision': {'grade': board_grade(v('4ssg')), 'sentence': v('WQXS'), 'culture': v('dyRm')},
            'match': {'grade': board_grade(v('YCq7')), 'sentence': v('vxPz')},
            'recruitment': {'grade': board_grade(v('mA5F')), 'sentence': v('jU9W')},
            'tactics': {'grade': board_grade(v('0otV')), 'sentence': v('oayd'), 'feedback': strn(v('4CUZ'))},
            'squad': {'grade': board_grade(v('niy[')), 'sentence': v('CZQm'), 'short': v('9rBC')},
        },
        'competitions': {'grade': board_grade(v('6ujb')), 'short': v('3oPe'), 'sentence': v('Cfeq'),
                         'list': v('fs7L')},
        'highlights': v('iajq') or [], 'criticisms': v('SZtr') or [],
        'signings': signings,
        'transfers': {'in_count': v('bi6D'), 'out_count': v('asbd'), 'out': v('oFBd') or [],
                      'completed': v('kYct') or []},
        'supporters': {
            'overall': {'grade': supporter_grade(v('nnrF')), 'sentence': v('ScoS')},
            'club_vision': {'grade': supporter_grade(v('A9tQ')), 'sentence': v('HZHh')},
            'match': {'grade': supporter_grade(v('GuH4')), 'sentence': v('PUk1')},
            'recruitment': {'grade': supporter_grade(v('5lFe')), 'sentence': v('kPbO'), 'short': v('YN8Y')},
            'tactics': {'grade': supporter_grade(v('9sIS')), 'sentence': v('H1fn'), 'feedback': strn(v('zcwx'))},
            'squad': {'sentence': v('y2R7')},
            'highlights': v('GUph') or [], 'criticisms': v('3hBS') or [],
            'players': players_,
        },
        'job_security': {'value': v('Gc5S'), 'label': 'JobSecurityFromContract',
                         'note': 'raw TEAM_CONFIDENCE value; its scale is not established'},
        'recent_matches': recent,
        'match_fixtures': fixtures,
        'next_match_expectation': {
            'available': False,
            'fixture': upcoming[0] if upcoming else None,
            'reason': ('TEAM_CONFIDENCE (type 114) has no next-match expectation key; the fixture is '
                       'the first upcoming entry of MatchConfidenceFixtureList when there is one.')},
    }


def board_confidence(bridge, session_id, club_ref=None, fresh=False) -> dict:
    reg = registry()
    session = session_for(bridge, session_id)
    with session.lock:
        state = session.save_state()
        coaches = state['record']['coaches']
        if club_ref is None:
            if not coaches:
                raise UiToolError('no human manager in the loaded career; pass club_ref')
            team = coaches[0]['team_address']
        else:
            team = session.club_first_team(bridge, club_ref)
        team_id = session.team_object_id(team)
        key = {'team': team_id, 'rng': RNG_MODE}
        client = reg.classes.get(reg.types[TEAM_CONFIDENCE]['client'])
        raw_result = {}

        def compute(vm):
            deadline = time.time() + BOARD_TIME_BUDGET_S
            result = compute_handler(vm, TEAM_CONFIDENCE, {'Ttea': team_id}, list(client.keys(4)),
                                     deadline=deadline, reg=reg)
            values = {r['key']: r.get('value') for r in result['rows'] if r['status'] != 'unavailable'}
            names = _Names(session, vm)
            shaped = shape_board_confidence(values, names, state['game_date'])
            shaped['team'] = {'name': names.name(team_id), 'object_id': team_id,
                              'managed': club_ref is None}
            unavailable = [r for r in result['rows'] if r['status'] == 'unavailable']
            raw_result.update(result)
            return {'answer': shaped, 'game_date': state['game_date'], 'input_status': result['input_status'],
                    'rng_uses': result['rng_uses'], 'timing': result['timing'],
                    'summary': summary(result['rows']),
                    'unavailable_keys': [{k: r[k] for k in ('key', 'label', 'reason')} for r in unavailable],
                    'complete': all(str(s).startswith('ok') for s in result['input_status'].values())
                    and not stopped_on_budget(result)}
        if fingerprinting(session):
            entry, block = tracked(session, state, 'board_confidence', key, compute, fresh=fresh,
                                   complete=lambda payload: payload['complete'])
            out = _board_answer(dict(entry, game_date=state['game_date']), hit=block['hit'])
            out['cache'] = block
            return out
        cache = session.cache(state)
        entry = None if fresh else cache.get('board_confidence', key)
        if entry is not None:
            return _board_answer(entry, hit=True)
        payload = compute(session.vm('fast', state, fresh=fresh))
        result = raw_result
        raw = dict(result, rows={r['key']: r for r in result['rows']}, game_date=state['game_date'],
                   budgets={'time_s': BOARD_TIME_BUDGET_S, 'max_instructions_per_segment': None})
        complete = payload.pop('complete')
        if not complete:            # never keep a failed computation for the rest of the day
            return _board_answer(cache.entry('board_confidence', key, dict(payload, stored=False)), hit=False)
        cache.put(f'handler:{TEAM_CONFIDENCE}', {'record': {'Ttea': team_id}, 'rng': RNG_MODE}, raw)
        entry = cache.put('board_confidence', key, payload)
        return _board_answer(entry, hit=False)


def _board_answer(entry, *, hit) -> dict:
    out = dict(entry['answer'])
    out['game_date'] = entry['game_date']
    out['rng'] = {'draws': entry['rng_uses'], 'fields_depending_on_draws': sorted(BOARD_RNG_DEPENDENT_KEYS),
                  'evidence': BOARD_RNG_EVIDENCE}
    if entry.get('rng_rule'):
        out['rng']['two_seed'] = entry['rng_rule']
    out['source'] = {'handler': 'TEAM_CONFIDENCE_UI_HANDLER (type 114)', 'input_status': entry['input_status'],
                     'summary': entry['summary'], 'unavailable_keys': entry['unavailable_keys'],
                     'timing': entry['timing']}
    failed = {k: v for k, v in entry['input_status'].items() if not str(v).startswith('ok')}
    if failed:
        out['warning'] = ('The board computation did not complete, so grades and sentences are unset: '
                          + '; '.join(f'{k}: {v}' for k, v in failed.items()))
    out['cache'] = ui_cache.describe(entry, hit=hit)
    return out


# --------------------------------------------------------------------------- tracked computations
def fingerprinting(session) -> bool:
    """True when answers are cached by read set: the session keeps a ScreenCache and the
    accelerated emulator (which records read sets) is in use."""
    from .ui_vm import fast_wanted
    return hasattr(session, 'screen_cache') and fast_wanted()


IGNORED_WORDS_LIMIT = 32
_ENTRY_KEYS = frozenset({'version', 'save_key', 'build', 'kind', 'inputs', 'validity', 'computed_at',
                         'computed_at_unix', 'age_seconds', 'read_set', 'rng_rule', 'stored', 'game_date'})


def same_answer(a, b) -> bool:
    """Two answers to one question are equal, timings and cache bookkeeping apart."""
    from .ui_vm import leaves
    skip = TIMING_LEAVES | _ENTRY_KEYS

    def kept(value):
        return {p: v for p, v in leaves(json.loads(json.dumps(value, default=str))).items()
                if not any(k in skip for k in p)}
    return kept(a) == kept(b)


def ignored_words(previous, check, payload) -> set:
    """The volatile-word rule (docs/fmdb/UI_FAST.md). A stored answer failed its check because
    words the computation read changed, and every changed page is read by word, so the words are
    known exactly; the answer computed again from the new bytes is equal to the stored one: those
    words are shown not to decide this answer and are left out of its fingerprint from now on
    (like the random-generator state under the two-seed rule). Words shown so before stay out
    while answers stay equal; a different answer clears them all. At most IGNORED_WORDS_LIMIT.
    FMDB_UI_IGNORED_WORDS=0 turns the rule off."""
    import os
    if os.environ.get('FMDB_UI_IGNORED_WORDS', '1') == '0':
        return set()
    if not previous or previous.get('stored') is False or not same_answer(previous, payload):
        return set()
    known = set((previous.get('validity') or {}).get('ignored_words') or ())
    if check is not None and check.get('changed_words'):
        known |= set(check['changed_words'])
    return known if len(known) <= IGNORED_WORDS_LIMIT else set()


def tracked(session, state, kind, identity, compute, *, fresh=False, forever=False, mode='fast',
            max_instructions=None, complete=None, usable=None, new_read=True):
    """Answer `kind`/`identity` from the ScreenCache when its validity check passes, else run
    `compute(vm) -> dict` and store the result. Returns (entry, cache block).

    * forever=True: the object does not change (news item narrative); no read set is kept.
    * otherwise the computation is traced: the live pages (words, for pages the game keeps
      changing) and game files it read are stored with their fingerprints, and a later call
      re-reads exactly those and recomputes only if one differs.
    * A computation that drew random numbers runs a second time with a reseeded copy of the
      generator (the two-seed rule, ui_vm.two_seed): leaves that differ are withheld as
      'generated at read'; the generator state is then not part of the fingerprint.
    * complete(payload) False: the answer is returned but not stored (budget stops).
    * usable(entry) False: the stored entry does not cover the request (treated as a miss)."""
    from . import ui_fastvm, ui_vm
    store = session.screen_cache(state)
    check = None
    previous = store.get(kind, identity)
    entry = None if fresh else previous
    if entry is not None and usable is not None and not usable(entry):
        entry = None
    if entry is not None:
        if entry['validity']['mode'] == 'forever':
            return entry, ui_cache.describe_checked(entry, hit=True)
        stored = store.read_set(kind, identity)
        if stored is not None:
            check = ui_cache.check_read_set(stored, session.memory.read_many_status, ui_fastvm.hash_masked,
                                            session.process)
            if check['ok']:
                return entry, ui_cache.describe_checked(entry, hit=True, check=check)
            session.note_volatile(store, check['changed'])
    vm = session.vm(mode, state, max_instructions=max_instructions)
    if new_read:
        # a page copy at most READ_BURST_S old serves a burst of first-time questions; a failed
        # check or fresh=True always reads again
        vm.begin_read(max_age=None if (fresh or check is not None) else READ_BURST_S)
    else:
        vm.reset()
    if check is not None and check['data']:
        vm.prefetch(list(check['data']), list(check['data'].values()))
    if not forever:
        vm.watch(session.volatile)
        vm.trace_begin()
    rng0 = vm.rng_uses
    try:
        payload = compute(vm)
        if not forever:
            pages, masks = vm.read_set()
            files = sorted(vm.files_touched or ())
    finally:
        if not forever:
            vm.trace_end()
    drew = vm.rng_uses - rng0
    if drew:
        known = (previous or {}).get('rng_rule') or {}
        if known.get('draws') == drew and not known.get('leaves_withheld') \
                and known.get('served_without_second_read', 0) < TWO_SEED_REUSE:
            # the same question drew the same number of times before and no leaf depended on
            # the draws: the second read is repeated only every TWO_SEED_REUSE recomputations
            payload = dict(payload, rng_rule=dict(
                known, served_without_second_read=known.get('served_without_second_read', 0) + 1))
        else:
            vm.rng_salt = ui_vm.TWO_SEED_SALT
            try:
                other = compute(vm)
            finally:
                vm.rng_salt = 0
            payload, withheld = ui_vm.two_seed(lambda salt: other if salt else payload, ui_vm.TWO_SEED_SALT,
                                               ignore=TIMING_LEAVES)
            payload = dict(payload, rng_rule={
                'draws': drew, 'rule': 'two-seed: read again with the copied random state reseeded',
                'leaves_withheld': withheld, 'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
        state_range = vm.rng_state_range()
        if state_range and not forever:
            address, length = state_range
            for word in range(address & ~7, address + length, 8):
                page, index = word & ~0xFFF, (word & 0xFFF) >> 3
                if page in masks:
                    groups = list(masks[page])
                    groups[index >> 6] &= ~(1 << (index & 63))
                    masks[page] = tuple(groups)
                else:
                    session.note_volatile(store, [page])
    validity = {'mode': 'forever' if forever else 'read_set'}
    if not forever:
        ignored = ignored_words(previous, check, payload)
        if ignored:
            ui_cache.clear_words(masks, ignored)
            validity['ignored_words'] = sorted(ignored)
    if complete is not None and not complete(payload):
        entry = store.entry(kind, identity, dict(payload, stored=False), validity)
    elif forever:
        entry = store.put(kind, identity, payload, validity)
    else:
        words = {p: ui_cache.masked_words(vm.live_read(p, ui_cache.PAGE), m) for p, m in masks.items()}
        read_set = ui_cache.ReadSet(session.process, pages, vm.fingerprint(pages, masks), masks,
                                    [ui_cache.file_stamp(f) for f in files], words)
        entry = store.put(kind, identity, dict(payload, read_set={
            'pages': len(pages), 'pages_by_word': len(masks), 'files': [Path(f).name for f in files]}),
            validity, read_set)
    return entry, ui_cache.describe_checked(entry, hit=False, check=check)


# --------------------------------------------------------------------------- recipe wrappers
def _jsonable(value):
    if hasattr(value, 'to_json') and not isinstance(value, dict):
        return plain_text(_jsonable(value.to_json()))
    if isinstance(value, Unavailable):
        return value.to_json()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, '__dataclass_fields__'):
        from dataclasses import asdict
        return _jsonable(asdict(value))
    if isinstance(value, (bytes, bytearray)):
        return {'data_hex': bytes(value).hex()}
    return plain_text(variant.to_json(value))


def object_ref(value, table_type, prefix):
    """None, a UI object id (int, digits or "0x..."), or "<prefix>:<table index>"."""
    if value is None or isinstance(value, int) and not isinstance(value, bool):
        return value
    text = str(value).strip()
    match = re.fullmatch(rf'{prefix}:(\d+)', text)
    if match:
        return (table_type << 24) | (int(match.group(1)) & 0x7FFFFF)
    try:
        return int(text, 0)
    except ValueError:
        raise UiToolError(f'{value!r} is not a UI object id or "{prefix}:<index>"') from None


def _happiness_reasons(bridge, session_id, result, *, everyone=False):
    """Attach `reasons` (the Happiness panel's positives, negatives and playing-time line, drawn
    for the human manager: player_happiness_reason) to the unhappy players (or every player)."""
    from .tools import db_query
    players = [p for p in result.get('players') or () if isinstance(p.get('person_id'), int)
               and (everyone or p.get('unhappy'))]
    if not players:
        return
    by_idx = {p['person_id'] & 0xFFFFFF: p for p in players}
    try:
        got = db_query(bridge, session_id, 'SELECT person_idx, sign, position, reason_text, level FROM '
                       f'player_happiness_reason WHERE person_idx IN ({", ".join(map(str, sorted(by_idx)))}) '
                       'ORDER BY person_idx, entry', None, 5000)
    except Exception as exc:  # noqa: BLE001 - the list stands without its reasons
        result['reasons_unavailable'] = str(exc)[:300]
        return
    for p in players:
        p['reasons'] = []
    for idx, sign, position, text, level in got.get('rows') or ():
        p = by_idx.get(idx)
        if p is not None:
            p['reasons'].append({'sign': sign, 'text': text, **({'level': level} if level is not None else {})})


def recipe_read(bridge, session_id, kind, fn, kwargs, fresh=False, *, pass_read=False) -> dict:
    session = session_for(bridge, session_id)
    with session.lock:
        state = session.save_state()
        if fingerprinting(session):
            def compute(vm):
                rng0, started = vm.rng_uses, time.perf_counter()
                extra = {'read': vm.reader.read} if pass_read else {}
                try:
                    result = fn(vm, **kwargs, **extra)
                except _Stop as stop:
                    raise UiToolError(f'{kind}: {stop.reason} {stop.detail or ""}'.strip()) from None
                return {'result': _jsonable(result), 'rng_uses': vm.rng_uses - rng0,
                        'game_date': state['game_date'],
                        'timing': {'total_s': round(time.perf_counter() - started, 2)}}
            entry, cache = tracked(session, state, f'recipe:{kind}', {'args': kwargs, 'rng': RNG_MODE}, compute,
                                   fresh=fresh)
            out = {'result': entry['result'], 'game_date': state['game_date'], 'rng_uses': entry['rng_uses'],
                   'timing': entry['timing'], 'cache': cache}
            if entry.get('rng_rule'):
                out['rng_rule'] = entry['rng_rule']
            return out
        cache = session.cache(state)
        key = {'args': kwargs, 'rng': RNG_MODE}
        entry = None if fresh else cache.get(f'recipe:{kind}', key)
        if entry is None:
            vm = session.vm('fast', state, fresh=fresh)
            rng0, started = vm.rng_uses, time.perf_counter()
            extra = {'read': session.read} if pass_read else {}
            try:
                result = fn(vm, **kwargs, **extra)
            except _Stop as stop:
                raise UiToolError(f'{kind}: {stop.reason} {stop.detail or ""}'.strip()) from None
            entry = cache.put(f'recipe:{kind}', key, {
                'result': _jsonable(result), 'rng_uses': vm.rng_uses - rng0, 'game_date': state['game_date'],
                'timing': {'total_s': round(time.perf_counter() - started, 2)}})
            hit = False
        else:
            hit = True
        return {'result': entry['result'], 'game_date': entry['game_date'], 'rng_uses': entry['rng_uses'],
                'timing': entry['timing'], 'cache': ui_cache.describe(entry, hit=hit)}


# --------------------------------------------------------------------------- inbox: list and bodies
# Volatile per-item values are read from the stored object on every call (read flag); the
# narrative is rendered once per item and kept for the life of the save ('forever').
NEWS_HEAD_FIELDS = ('subject', 'headline_subtitle', 'time_sent')
NEWS_BODY_FIELDS = ('body', 'body_links', 'important', 'priority', 'sender', 'sender_team', 'media_source',
                    'media_category', 'tags', 'induction', 'references')
NEWS_AS_RENDERED_FIELDS = ('action', 'can_respond', 'has_responded', 'deadline', 'age')
INBOX_TIME_BUDGET_S = 60


def inbox(bridge, session_id, limit=50, unread_only=False, items=None, fresh=False,
          time_budget_s=INBOX_TIME_BUDGET_S) -> dict:
    """The inbox list from the stored news objects (id, class, date, read flag) with each item's
    subject, and the full narrative of the items named in `items`. Subjects and bodies are
    rendered once per item (the game's NEWS_ITEM handler) and then served from the cache."""
    news = recipe_module('ui_recipes_news')
    session = session_for(bridge, session_id)
    with session.lock:
        state = session.save_state()
        if not fingerprinting(session):
            return recipe_read(bridge, session_id, 'inbox', news.inbox,
                               {'limit': limit, 'unread_only': unread_only}, fresh)
        started, cpu = time.perf_counter(), time.process_time()
        vm = session.vm('fast', state)
        vm.begin_read()
        view = news.viewer(vm)
        entries = news.inbox_entries(vm, view.human)
        total, unread = len(entries), sum(1 for e in entries if not e.read)
        wanted = set(int(u) for u in (items or ()))
        listed = [e for e in entries if not unread_only or not e.read][:limit]
        listed += [e for e in entries if e.unid in wanted and e not in listed]
        missing = sorted(wanted - {e.unid for e in entries})
        store = session.screen_cache(state)
        names = news.Names(vm)
        deadline = time.time() + time_budget_s
        rows, rendered, pending = [], 0, 0
        for entry in listed:
            full = entry.unid in wanted
            row = {'unid': entry.unid, 'news_class': entry.news_class, 'date': entry.date, 'read': entry.read}
            identity = {'unid': entry.unid, 'human': view.person_index, 'rng': RNG_MODE}
            cached = None
            if not (fresh and full):
                cached = store.get('news_body', identity) or (None if full else store.get('news_head', identity))
            if cached is None and time.time() > deadline:
                row.update(subject=None, pending='not rendered within the time budget; ask again')
                pending += 1
                rows.append(row)
                continue
            if cached is None:
                def compute(vm, entry=entry, full=full):
                    t0 = time.perf_counter()
                    reading = news.news_item(vm, view.person_index, entry.unid,
                                             news.NEWS_KEYS if full else news.NEWS_HEAD_KEYS)
                    shaped = _jsonable(news.shape_news(entry, reading, names))
                    return {'row': shaped, 'rendered_on_game_date': state['game_date'],
                            'seconds': round(time.perf_counter() - t0, 3)}
                cached, _ = tracked(session, state, 'news_body' if full else 'news_head', identity, compute,
                                    fresh=True, forever=True, new_read=False,
                                    complete=lambda payload: not any('budget' in str(v) for v in (
                                        payload['row'].get('input_failures') or {}).values()))
                rendered += 1
            shaped = cached['row']
            row.update({name: shaped.get(name) for name in NEWS_HEAD_FIELDS})
            if shaped.get('input_failures'):
                row['input_failures'] = shaped['input_failures']
            if full:
                row.update({name: shaped.get(name) for name in NEWS_BODY_FIELDS})
                row['as_rendered'] = dict({name: shaped.get(name) for name in NEWS_AS_RENDERED_FIELDS},
                                          game_date=cached.get('rendered_on_game_date'))
                row['unavailable'] = shaped.get('unavailable')
                if cached.get('rng_rule'):
                    row['rng_rule'] = cached['rng_rule']
            rows.append(row)
        note = ('List from the stored news objects (read flags are current); subject and body are rendered '
                'once per item and kept. Pass items=[unid, ...] for bodies; fields under as_rendered '
                '(response state, deadline, age) are as of the first rendering, fresh=true with items '
                'renders those items again.')
        return {'result': rows, 'inbox_size': total, 'unread': unread, 'items_not_in_inbox': missing,
                'game_date': state['game_date'],
                'timing': {'total_s': round(time.perf_counter() - started, 3),
                           'cpu_s': round(time.process_time() - cpu, 3)},
                'cache': {'hit': rendered == 0, 'rendered_now': rendered, 'pending': pending, 'note': note}}


def recipe_module(name):
    """The sibling recipe module if it exists, else None (registration then adds nothing)."""
    full = f'{__package__}.{name}'
    if full in sys.modules:
        return sys.modules[full]
    try:
        if importlib.util.find_spec(full) is None:
            return None
    except (ImportError, ValueError):
        return None
    try:
        return importlib.import_module(full)
    except Exception as exc:  # noqa: BLE001 - a broken optional module must not stop the server
        log.warning('UI recipe module %s failed to import: %s', full, exc)
        return None


# --------------------------------------------------------------------------- registration
def _wrap(fn):
    try:
        return fn()
    except UiToolError as exc:
        raise ValueError(str(exc)) from exc


def register_fmdb_ui_tools(mcp, bridge):
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
    registered = []

    @mcp.tool(annotations=read_only, description=(
        "Describe the game's UI handlers (offline; nothing is read from the game). No arguments: every "
        "handler type that builds, with client/server classes, the input keys the client consumes, "
        "documented UI_RECORD fields and its key count. handler (type number or class name such as "
        "TEAM_CONFIDENCE): its keys with labels. search: keys whose label contains the text, with the "
        "handler types that produce them. Use the result to call fm_ui_read."))
    def fm_ui_schema(
        session_id: str,
        handler: Annotated[int | str | None, Field(description='type number (1-144) or class name')] = None,
        search: Annotated[str | None, Field(min_length=2, max_length=64)] = None,
    ) -> dict[str, Any]:
        return _wrap(lambda: ui_schema(handler, search))
    registered.append('fm_ui_schema')

    @mcp.tool(annotations=read_only, description=(
        "Read any buildable UI handler type with explicit UI_RECORD inputs, e.g. handler=114, "
        "inputs={\"Ttea\": \"managed_team\"} (values: u32, \"0x...\", \"managed_team\", \"managed_manager\", "
        "\"team:<index>\", \"person:<index>\"). A database record's handler is named by its class with the "
        "object in dref: handler=\"TEAM_UI_HANDLER\", inputs={\"dref\": \"managed_team\"} (also PERSON, CLUB, "
        "COMPETITION). Returns {key, label, value} rows (status value/unset/"
        "unavailable with a reason), input transfer statuses, timing, rng_uses and cache state. Guard "
        "rails: an instruction budget per emulated segment (max_instructions, default 500 M; Unicorn's "
        "counter, which makes emulation ~2x slower than fm_get_board_confidence) and a wall-clock "
        "budget (time_budget_s); only factory, server get, input transfer and client get slots run, "
        "never a set-property slot. params: screen parameters a view would set, {name: integer} with "
        "the game's parameter names (number, person, team, club, competition, date, ishometeam, "
        "monthindex, viewid ...; object parameters take UI ids); with params every key is read through "
        "all client protocols and each row lists the parameters its getter asked for (params_read). "
        "context: object arguments a view passes to the server getter by data key, {FourCC: UI id or "
        "token}; the Data Hub's TeamAnalytics and PlayerAnalytics need {\"Hhum\": \"managed_manager\", "
        "\"mCLv\": \"managed_team\"} (fm_get_ui_screen screen=team_analytics does this and names the charts). "
        + UI_NOTE))
    def fm_ui_read(
        session_id: str,
        handler: Annotated[int | str, Field(description='type number (1-144) or class name')],
        inputs: Annotated[dict[str, int | str] | None, Field(description='UI_RECORD fields {FourCC: value}')] = None,
        keys: Annotated[list[Annotated[str, Field(min_length=1, max_length=96)]] | None,
                        Field(min_length=1, max_length=400)] = None,
        fresh: bool = False,
        time_budget_s: Annotated[int, Field(ge=1, le=MAX_TIME_BUDGET_S)] = DEFAULT_TIME_BUDGET_S,
        max_instructions: Annotated[int, Field(ge=1_000_000, le=MAX_INSTRUCTIONS)] = DEFAULT_MAX_INSTRUCTIONS,
        params: Annotated[dict[str, int] | None, Field(description='screen parameters {name: integer}')] = None,
        context: Annotated[dict[str, int | str] | None,
                           Field(description='object arguments {data key FourCC: UI id or token}')] = None,
    ) -> dict[str, Any]:
        return _wrap(lambda: ui_read(bridge, session_id, handler, inputs, keys, fresh,
                                     time_budget_s=time_budget_s, max_instructions=max_instructions,
                                     params=params, context=context))
    registered.append('fm_ui_read')

    @mcp.tool(annotations=read_only, description=(
        "Board and supporter confidence for the managed club (or another club by club_ref from "
        "fm_find_clubs), as on the Board > Confidence screens: overall grade and sentence; club vision, "
        "match, recruitment, tactics and squad grades (letters decoded) with sentences; board highlights "
        "and criticisms; each signing with name, wage, raw fee (unit unresolved), board grade and "
        "supporter reaction; supporter grades, sentences and per-player reactions; job-security figure; "
        "recent match grades and the match fixture list. The game has no next-match expectation key in "
        "this handler; the answer says so. The rng block names any field known to depend on the random "
        "draws. " + UI_NOTE))
    def fm_get_board_confidence(
        session_id: str,
        club_ref: Annotated[str | None, Field(min_length=1, max_length=256)] = None,
        fresh: bool = False,
    ) -> dict[str, Any]:
        return _wrap(lambda: board_confidence(bridge, session_id, club_ref, fresh))
    registered.append('fm_get_board_confidence')

    news = recipe_module('ui_recipes_news')
    if news is not None and callable(getattr(news, 'inbox', None)):
        @mcp.tool(annotations=read_only, description=(
            "The manager's inbox, newest first: up to limit items (unread_only to skip read ones) with "
            "unid, date, read flag, news class and subject, from the stored news objects (well under a "
            "second once subjects are rendered; a first listing renders them, ~10-100 ms per item). "
            "items=[unid, ...] adds the full narrative of those items (body, links, sender, references, "
            "response state): a few hundred ms each the first time, then kept for the save. " + UI_NOTE))
        def fm_get_inbox(
            session_id: str,
            limit: Annotated[int, Field(ge=1, le=500)] = 50,
            unread_only: bool = False,
            items: Annotated[list[int] | None, Field(max_length=100, description='unids whose bodies to include')] = None,
            fresh: bool = False,
        ) -> dict[str, Any]:
            return _wrap(lambda: inbox(bridge, session_id, limit, unread_only, items, fresh))
        registered.append('fm_get_inbox')
    if news is not None and callable(getattr(news, 'calendar', None)):
        @mcp.tool(annotations=read_only, description=(
            "Calendar of fixtures, training days and competition dates for the managed team (or team: "
            "a UI team id or \"team:<team-table index>\") over the next days, as the game's UI layer "
            "shows it. " + UI_NOTE))
        def fm_get_calendar(
            session_id: str,
            team: Annotated[int | str | None, Field(description='UI team id or "team:<index>"')] = None,
            days: Annotated[int, Field(ge=1, le=400)] = 60,
            fresh: bool = False,
        ) -> dict[str, Any]:
            return _wrap(lambda: recipe_read(bridge, session_id, 'calendar', news.calendar,
                                             {'team': object_ref(team, TEAM_TABLE_TYPE, 'team'), 'days': days},
                                             fresh))
        registered.append('fm_get_calendar')

    person = recipe_module('ui_recipes_person')
    if person is not None and callable(getattr(person, 'player_status', None)):
        @mcp.tool(annotations=read_only, description=(
            "A player's runtime status as the game's Player screens show it (happiness, promises, "
            "interest, contract and squad status). player: person UI id (1 << 24 | people-table "
            "index) or \"person:<people-table index>\". " + UI_NOTE))
        def fm_get_player_status(
            session_id: str,
            player: Annotated[int | str, Field(description='person UI id or "person:<index>"')],
            fresh: bool = False,
        ) -> dict[str, Any]:
            return _wrap(lambda: recipe_read(bridge, session_id, 'player_status', person.player_status,
                                             {'player': object_ref(player, PERSON_TABLE_TYPE, 'person')},
                                             fresh, pass_read=True))
        registered.append('fm_get_player_status')
    if person is not None and callable(getattr(person, 'club_vision', None)):
        @mcp.tool(annotations=read_only, description=(
            "The club vision (the board's long-term and seasonal objectives) for the managed club, or "
            "another club by CLUB UI id or \"club:<club-table index>\", as the game's UI layer shows "
            "it. " + UI_NOTE))
        def fm_get_club_vision(
            session_id: str,
            club: Annotated[int | str | None, Field(description='CLUB UI id or "club:<index>"')] = None,
            fresh: bool = False,
        ) -> dict[str, Any]:
            return _wrap(lambda: recipe_read(bridge, session_id, 'club_vision', person.club_vision,
                                             {'club': object_ref(club, CLUB_TABLE_TYPE, 'club')},
                                             fresh, pass_read=True))
        registered.append('fm_get_club_vision')
    registered += register_more_ui_tools(mcp, bridge, read_only)
    registered += register_screen_tools(mcp, bridge, read_only)
    registered += register_match_tools(mcp, bridge, read_only)
    registered += register_round2_tools(mcp, bridge, read_only)
    return registered


def _role_line(position, role) -> str:
    return f"{position or '?'} {role or 'role not named'}"


def manager_tactics(bridge, session_id) -> dict:
    """The `tactic` part of fm_get_ui_screen(screen='tactics'): the manager's prepared tactics and,
    while a match is loaded, the tactic in use there.

    The UI layer's COMPETITION_TACTIC handler, built from the team record, describes a default
    tactic, not the manager's (ui_recipes_round2.SCREENS). These come from the hand-built readers:
    fm_get_managed_tactics for the stored slots, fm_get_current_match for the match engine's
    resident settings of the managed side."""
    out = {'source': 'fm_get_managed_tactics; in_match from fm_get_current_match'}
    team_id = None
    try:
        doc = bridge.get_managed_tactics(session_id, None, True, True, True)
    except (RuntimeError, ValueError) as exc:
        out['prepared'] = {'unavailable': str(exc)[:200]}
    else:
        team_id = (doc.get('team') or {}).get('native_id')
        if doc.get('source_state') != 'available':
            out['prepared'] = {'unavailable': doc.get('unavailable_reason') or doc.get('source_state')}
        else:
            slots = []
            for slot in doc.get('slots') or []:
                row = {'slot': slot.get('slot_index'), 'state': slot.get('state'), 'name': slot.get('name')}
                if slot.get('state') == 'stored':
                    row['mentality'] = (slot.get('mentality') or {}).get('name')
                    row['team_instructions'] = [o.get('name') or f"option {o.get('native_option_id')}" for o in
                                                (slot.get('team_instructions') or {}).get('selected_options') or []]
                    for phase, body in (slot.get('phases') or {}).items():
                        row[phase] = [_role_line(p.get('name'), (p.get('base_role') or {}).get('compiled_english_name'))
                                      for p in body.get('positions') or []]
                slots.append(row)
            out['prepared'] = {'primary_trained_slot': (doc.get('primary_trained_tactic') or {}).get('slot_index'),
                               'slots': slots,
                               'note': 'stored slots; which one a match uses is in in_match while a match is loaded'}
    try:
        from ..current_match_report import current_match_report
        match = current_match_report(bridge, session_id, 'simulation', True, persist_host_observations=False)
    except (RuntimeError, ValueError) as exc:
        out['in_match'] = {'unavailable': str(exc)[:200]}
        return out
    tactics = match.get('tactics') or {}
    if match.get('state') != 'available_fixture_bound' or tactics.get('state') != 'available':
        out['in_match'] = None
        return out
    sides = [s for s in tactics.get('sides') or [] if (s.get('team') or {}).get('native_id') == team_id]
    if len(sides) != 1:
        out['in_match'] = {'unavailable': 'the managed team is not one of the two sides of the loaded match'}
        return out
    side = sides[0]
    row = {'name': side.get('name'), 'mentality': (side.get('mentality') or {}).get('name'),
           'team_instructions': [o.get('name') or f"option {o.get('native_option_id')}" for o in
                                 (side.get('instructions') or {}).get('selected_options') or []],
           'period': match.get('displayed_period'), 'score': match.get('displayed_score'),
           'note': "the match engine's current settings for your side; per-player overrides are not included. "
                   'In-match condition: fm_get_current_match_player_physical. Substitutions made: '
                   'fm_get_current_match(include_player_changes=true).'}
    for phase, positions in (side.get('phases') or {}).items():
        row[phase] = [_role_line(p.get('position'), p.get('base_role')) for p in positions or []]
    out['in_match'] = row
    return out


def register_round2_tools(mcp, bridge, read_only) -> list:
    """fm_get_ui_screen: the round-2 screens of ui_recipes_round2 (docs/fmdb/UI_ROUND2.md)."""
    more = recipe_module('ui_recipes_more')            # the round-2 screens read through its KeyReader
    round2 = recipe_module('ui_recipes_round2') if callable(getattr(more, 'read_screen', None)) else None
    if round2 is None or not callable(getattr(round2, 'screen', None)):
        return []
    analytics = recipe_module('ui_recipes_analytics')
    analytics_screens = dict(getattr(analytics, 'SCREENS', None) or {})
    names = tuple(round2.SCREENS) + tuple(analytics_screens)

    @mcp.tool(annotations=read_only, description=(
        "Screens the game's UI layer builds, read as the front end asks for them: player_comparison "
        "(two people side by side: attribute averages, positional stats and abilities, career and "
        "per-90 stats), staff_comparison (the team's coaching, recruitment and medical staff against "
        "the league), tactics (your prepared tactics by slot with name, mentality, named team instructions "
        "and both phases' positions and roles; in_match: the tactic the loaded match is using for your side; "
        "formation chances and style), squad_registration (registered and unregistered players, rules, "
        "deadline), training (units, ratings, best and worst trainers, mentoring, coach assignments; "
        "one player's workload, position and progress), contract_negotiation, transfer_negotiation "
        "(the offer screens for a player), competition_rules (stages, shared rules, squad rewards), "
        "team_analytics (the Data Hub's own team charts for this season: the Possession Gained, Possession "
        "Lost, Passes attempted and Defensive Actions zone maps with the percentage in each of six columns "
        "from the defended end to the opposition's, the set-piece first-contact maps, and the game's summary "
        "sentences; chart=\"all\" or words of a chart name such as \"possession scatter\" for the scatter "
        "graphs against the division and the polygons), player_analytics (every player scatter graph the Data "
        "Hub offers for the squad, by the game's groups; names only until chart is given), person_analytics "
        "(one player's own polygons and scatter graphs; person), opposition_analytics (the charts of a team's "
        "report; team) and match_analytics (one of the Data Hub's recent matches, match 1 = the latest: action "
        "zones and both shot maps by location with expected goals; chart=\"pass map\", \"average positions\" or "
        "\"all\" for the rest). "
        "person / other: PERSON UI id or \"person:<index>\" (default: the first two squad players); "
        "competition: COMPETITION UI id or \"comp:<index>\" (default: the managed league); team: TEAM UI id "
        "or \"team:<index>\" for the analytics screens (default: the managed team; another team answers with "
        "its opposition report's shorter set). Fields are keyed by the game's property labels. " + UI_NOTE))
    def fm_get_ui_screen(
        session_id: str,
        screen: Annotated[str, Field(description='player_comparison, staff_comparison, tactics, squad_registration, '
                                                 'training, contract_negotiation, transfer_negotiation, '
                                                 'competition_rules, team_analytics, player_analytics, '
                                                 'person_analytics, opposition_analytics or match_analytics',
                                     min_length=3, max_length=40)],
        person: Annotated[int | str | None, Field(description='PERSON UI id or "person:<index>"')] = None,
        other: Annotated[int | str | None, Field(description='second person for player_comparison')] = None,
        competition: Annotated[int | str | None, Field(description='COMPETITION UI id or "comp:<index>"')] = None,
        fresh: bool = False,
        team: Annotated[int | str | None, Field(description='TEAM UI id or "team:<index>" (analytics screens)')] = None,
        chart: Annotated[str | None, Field(description='analytics screens: "all" or words of a chart name',
                                           min_length=2, max_length=80)] = None,
        match: Annotated[int | None, Field(description='match_analytics: 1 = the latest recent match', ge=1, le=20)] = None,
    ) -> dict[str, Any]:
        def run():
            if screen not in names:
                raise UiToolError(f'unknown screen {screen!r}; one of {", ".join(names)}')
            if screen in analytics_screens:
                kwargs = {'chart': chart}
                if screen == 'match_analytics':
                    kwargs['match'] = match or 1
                elif screen == 'person_analytics':
                    kwargs['person'] = object_ref(person, PERSON_TABLE_TYPE, 'person')
                else:
                    kwargs['team'] = object_ref(team, TEAM_TABLE_TYPE, 'team')
                return recipe_read(bridge, session_id, f'analytics:{screen}', analytics_screens[screen], kwargs, fresh)
            kwargs = {'name': screen, 'person': object_ref(person, PERSON_TABLE_TYPE, 'person'),
                      'other': object_ref(other, PERSON_TABLE_TYPE, 'person'),
                      'competition': object_ref(competition, COMPETITION_TABLE_TYPE, 'comp')}
            out = recipe_read(bridge, session_id, f'round2:{screen}', round2.screen, kwargs, fresh)
            if screen == 'tactics':
                # never cached with the screen: the match's tactic changes while the save state does not
                out = {**out, 'result': {**out['result'], 'fields': {'tactic': manager_tactics(bridge, session_id),
                                                                       **out['result'].get('fields', {})}}}
            return out
        return _wrap(run)
    return ['fm_get_ui_screen']


# Tools over ui_recipes_screens / ui_frontend (docs/fmdb/UI_FRONTEND.md).
def register_screen_tools(mcp, bridge, read_only) -> list:
    screens = recipe_module('ui_recipes_screens')
    frontend = recipe_module('ui_frontend')
    out = []
    if screens is not None and callable(getattr(screens, 'club_vision_progress', None)):
        @mcp.tool(annotations=read_only, description=(
            "Club Vision objectives with the judgement the Club Vision, Board and Supporters screens "
            "show for each one (On Course, Pleased, Delighted, Not Judging, Reserving Judgement, Passed, "
            "...), its importance as the screen words it (importance: N/A, Favoured, Preferred, Desired, "
            "Required; importance_value is the raw 0-10) and the board's or fans' sentence behind it (the "
            "screen's info tooltip), for the "
            "managed club or club (CLUB UI id or \"club:<club-table index>\"). Board and supporter "
            "lists; includes competition objectives such as the FA Cup. Read with the views' own "
            "parameter visionisusingperformancedata = true. First call ~5 s. " + UI_NOTE))
        def fm_get_club_vision_progress(
            session_id: str,
            club: Annotated[int | str | None, Field(description='CLUB UI id or "club:<index>"')] = None,
            fresh: bool = False,
        ) -> dict[str, Any]:
            return _wrap(lambda: recipe_read(bridge, session_id, 'club_vision_progress',
                                             screens.club_vision_progress,
                                             {'club': object_ref(club, CLUB_TABLE_TYPE, 'club')},
                                             fresh, pass_read=True))
        out.append('fm_get_club_vision_progress')
    if screens is not None and callable(getattr(screens, 'squad_happiness', None)):
        @mcp.tool(annotations=read_only, description=(
            "Who is unhappy at the managed club (or club) and why, in one call: every player of "
            "every team with overall happiness and playing-time happiness as numbers and as the "
            "words the Squad > Happiness screen uses (Delighted .. Devastated; Alienated, "
            "Concerned, ...), and for the unhappy ones (overall below Content or playing time "
            "Concerned or worse) the screen's happiness negatives and morale, and `reasons`: every "
            "line of the player's Happiness panel (positives, negatives and the playing-time "
            "sentence, from the player_happiness_reason table). reasons: 'unhappy' (default), 'all' "
            "or 'none'. Youth-intake placeholders (VIRTUAL_PLAYER) on the roster are listed in "
            "virtual_players_skipped. ~1.5 CPU-s for the list of 66 players, ~0.4 s per player with "
            "reasons. " + UI_NOTE))
        def fm_get_squad_happiness(
            session_id: str,
            club: Annotated[int | str | None, Field(description='CLUB UI id or "club:<index>"')] = None,
            reasons: Annotated[str, Field(pattern='^(unhappy|all|none)$')] = 'unhappy',
            fresh: bool = False,
        ) -> dict[str, Any]:
            def run():
                out = recipe_read(bridge, session_id, 'squad_happiness', screens.squad_happiness,
                                  {'club': object_ref(club, CLUB_TABLE_TYPE, 'club'), 'reasons': reasons},
                                  fresh, pass_read=True)
                if reasons != 'none':
                    _happiness_reasons(bridge, session_id, out.get('result') or {}, everyone=reasons == 'all')
                return out
            return _wrap(run)
        out.append('fm_get_squad_happiness')
    if frontend is not None and callable(getattr(frontend, 'describe', None)):
        @mcp.tool(annotations=read_only, description=(
            "The front end's screen specification (offline; nothing is read from the game): which "
            "views bind a property (search by label, FourCC key or view name), the screen parameters "
            "each view sets with their legal values, the records a view expects, the record schemas "
            "(record id -> property keys), the value -> on-screen word tables (data collections, "
            "translation ids) and the plugin's screen-parameter names. Use it to choose UI_RECORD "
            "inputs and parameters for fm_ui_read."))
        def fm_ui_frontend(
            session_id: str,
            search: Annotated[str | None, Field(min_length=2, max_length=96)] = None,
            view: Annotated[str | None, Field(min_length=2, max_length=128)] = None,
            record: Annotated[str | None, Field(min_length=4, max_length=128)] = None,
            parameter: Annotated[str | None, Field(min_length=2, max_length=96)] = None,
            limit: Annotated[int, Field(ge=1, le=200)] = 40,
        ) -> dict[str, Any]:
            return _wrap(lambda: frontend.describe(search=search, view=view, record=record,
                                                   parameter=parameter, limit=limit))
        out.append('fm_ui_frontend')
    return out


def register_match_tools(mcp, bridge, read_only) -> list:
    """fm_get_match (match lane; docs/fmdb/MATCH.md)."""
    from .match_tool import get_match_live
    from .tools import current_snapshot, db_query, engine_for

    @mcp.tool(annotations=read_only, description=(
        "One played match as the match screens show it, from the snapshot match tables: result "
        "(extra time, penalties, aggregate), half-time score, attendance, stadium, referee, goals "
        "with scorer and minute, substitutions and dismissals, team statistics (shots, xG, "
        "possession, passes, corners), every player's line (minutes, rating, goals, assists and "
        "the stored per-match counters) and, for retained full-detail matches, the shot map. "
        "Select by match_idx (match.idx from fm_db_query) or by team with optional date "
        "(YYYY-MM-DD) and opponent; team and opponent take a name or a team idx (team.idx). A name "
        "matches exactly first, then as a substring, and of several substring matches your own team "
        "(then your club's teams) is preferred; a team alone gives its latest match. For lists and "
        "aggregates query the match tables with fm_db_query."))
    def fm_get_match(
        session_id: str,
        match_idx: Annotated[int | None, Field(ge=0)] = None,
        team: Annotated[str, Field(min_length=1, max_length=80)] | Annotated[int, Field(ge=0)] | None = None,
        date: Annotated[str | None, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')] = None,
        opponent: Annotated[str, Field(min_length=1, max_length=80)] | Annotated[int, Field(ge=0)] | None = None,
    ) -> dict[str, Any]:
        def query(sql, params, max_rows):
            return db_query(bridge, session_id, sql, params, max_rows, 'full')

        def run():
            # one match decoded from the live game; names from the snapshot (match_tool docstring)
            engine = engine_for(bridge, session_id)
            path = current_snapshot(engine)[0]
            return get_match_live(engine, path, match_idx, team, date, opponent, fallback=query)
        return _wrap(run)
    return ['fm_get_match']


# Shaped screens from ui_recipes_more (docs/fmdb/UI_SWEEP.md): tool name -> (recipe function,
# description). First-call costs were measured on the reference save (11 Nov 2026).
MORE_SCREENS = (
    ('fm_get_scouting', 'scouting',
     "Scouting for the managed club as the Recruitment screens show it: the club's scouts, players "
     "and teams scouted specifically, every recruitment focus (status, positions, role, age and "
     "ability filters, assigned scouts, recommended and near-miss player counts, priority, dates), "
     "scouting budget and range, and the club's scouting knowledge per nation and region with the "
     "scout who holds it. First call ~10 s."),
    ('fm_get_transfer_activity', 'transfers',
     "The managed club's transfer activity (player, staff and trade offers in and out, offers "
     "awaiting a response, budget impact), transfer and wage budgets with the transfer-budget "
     "history and projection, and the transfer window (dates, days remaining, window totals). "
     "First call ~2 s."),
    ('fm_get_squad_dynamics', 'squad_dynamics',
     "Squad dynamics of the managed team as Squad > Dynamics shows them: team leaders, highly "
     "influential, influential and other players, the staff's hierarchy feedback, social groups "
     "(core, secondary, other) and dressing-room atmosphere level. First call ~25 s (the team "
     "handler's inputs)."),
    ('fm_get_training_schedule', 'training',
     "Team training as Training > Overview/Schedule show it: this week's schedule (day by day, "
     "three sessions each), next week's days, last week's template and focus, training "
     "performance and average rating, the four units, the training squad and intensity options. "
     "First call ~2 s."),
    ('fm_get_medical_centre', 'medical',
     "Medical Centre overview for the managed team: injury-risk groups (low to very high), players "
     "at risk, exhausted and recurring injuries, injuries this and last season with a monthly "
     "summary, players expected back for the next match, medical staff count. The risk assessment "
     "draws random numbers (see sources.*.fields_using_random_draws). First call ~25 s."),
    ('fm_get_finance_projections', 'finances',
     "Finances summary and projections for the managed club as Finances > Summary/Projections show "
     "them: balance, income and expenditure (this and last season, last month), sponsorship, debt "
     "and loans, balance history, end-of-season projections (balance, turnover, expenditure, "
     "profit/loss, wage costs, transfer budget) for three seasons, budgets and facility ratings. "
     "Money is GBP. First call ~2 s."),
    ('fm_get_youth_intake', 'youth_intake',
     "Youth intake preview for the managed club: days until the intake, intake rating and youth "
     "facilities. Level, grade and feedback text need std::random_device in the game and come "
     "back unavailable with that reason. First call ~2 s."),
    ('fm_get_season_expectations', 'season_expectations',
     "The board's competition expectations for this season (Club Vision > season expectations): per "
     "competition the expected stage, importance (value and word), the stage options with the "
     "selected minimum and whether it can be or was set to not judged; plus the new transfer and "
     "wage budgets the meeting would set. Covers competitions such as the FA Cup that the club-vision "
     "objective list leaves out. First call ~2 s."),
    ('fm_get_manager_profile', 'manager_profile',
     "The human manager's profile: job and team, wage, preferred mentality and pressing, contract "
     "renewal advice, clubs interested, plus the board's job-security figure and overall verdict "
     "(TEAM_CONFIDENCE). First call ~10-40 s."),
)


def register_more_ui_tools(mcp, bridge, read_only) -> list:
    more = recipe_module('ui_recipes_more')
    if more is None:
        return []
    out = []

    def screen_tool(tool_name, kind, fn, description):
        def tool(session_id: str, fresh: bool = False) -> dict[str, Any]:
            return _wrap(lambda: recipe_read(bridge, session_id, kind, fn, {}, fresh))
        tool.__name__ = tool_name
        mcp.tool(name=tool_name, annotations=read_only, description=description + ' ' + UI_NOTE)(tool)

    for tool_name, kind, description in MORE_SCREENS:
        fn = getattr(more, kind, None)
        if callable(fn):
            screen_tool(tool_name, kind, fn, description)
            out.append(tool_name)
    if callable(getattr(more, 'league_table', None)):
        @mcp.tool(annotations=read_only, description=(
            "League table of a competition's current stage as the game's UI layer shows it (default: "
            "the managed team's league; competition: COMPETITION UI id or \"comp:<competition-table "
            "index>\"): position, played, won, drawn, lost, goals, goal difference, points and colour "
            "group per team, the table over the last games, top scorers and the xG table. First call "
            "~3 s. " + UI_NOTE))
        def fm_get_league_table(
            session_id: str,
            competition: Annotated[int | str | None, Field(description='COMPETITION UI id or "comp:<index>"')] = None,
            fresh: bool = False,
        ) -> dict[str, Any]:
            return _wrap(lambda: recipe_read(bridge, session_id, 'league_table', more.league_table,
                                             {'competition': object_ref(competition, COMPETITION_TABLE_TYPE, 'comp')},
                                             fresh))
        out.append('fm_get_league_table')
    return out


__all__ = ['register_fmdb_ui_tools', 'ui_schema', 'ui_read', 'board_confidence', 'shape_board_confidence',
           'board_grade', 'supporter_grade', 'resolve_handler', 'normalize_record', 'recipe_module']
