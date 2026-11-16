"""Player- and club-centred UI handlers: PERSON, CLUB (club vision), PLAYER_REPORT scouting.

Database-record handlers (PERSON_UI_HANDLER, CLUB_UI_HANDLER, TEAM_UI_HANDLER, ...) do not
read their values from a cache filled by input transfers (TEAM_CONFIDENCE style). They use
the *data-key* protocol, verified on build 27.0.0.2493426:

1. client slot 14 `(this, request{key @+0x44}, out vector<u32>)` lists the data keys the
   property needs (e.g. MoraleString 'dafe' -> ['Pmor']; HappinessPositives 'HPPo' ->
   ['PHsg', 'PRHP', 'Pclb', 'Pipl', 'PmOD', 'Pnfo', 'Pspa', 'gDhI']);
2. the server partner's slot 2 `(this, key, out typed*, context)` computes each data key;
3. the values go into a property bag (insert 0x43F72E4 `(bag, u32 key, typed*)`);
4. client slot 4 `get_property(this, request, out, bag)` formats the property from the bag
   (e.g. 'dafe' looks up 'Pmor' with 0x43F899C and maps it through 0x154AB00).

With an empty bag slot 4 still answers, with defaults ("Abysmal" morale, empty lists): that
is why a reading whose data keys could not all be computed is returned as `Unavailable`.

Handler selection: UI_RECORD `{'110 ': 28, 'dref': object id}` makes the factory switch on
the dref's table type (0x218688, jump table 0x52E1D80): table 1 (person) -> PERSON family,
3 (club) -> CLUB_UI_HANDLER (ctor at 0x219A00), 0x18 (team) -> TEAM_UI_HANDLER. The
selected object is read back by 0x1B24A0 from record key 'dref' (0x64726566). Type 106
(SQUAD_SELECTION_PLAYER) is PERSON with one override and the same record.

Everything is read-only: shipped code runs on copied live memory inside UiHandlerVM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import struct
import time

from . import ui_registry, variant
from .ui_handlers import HandlerReading, Reading, plain_text, input_keys
from .ui_vm import (UiHandlerVM, Handler, fourcc, fourcc_text, REQUEST_SIZE, REQUEST_KEY_OFFSET,
                    CLIENT_GET_SLOT)
from .vm import Unavailable, _Stop

DATABASE_RECORD = 28            # factory case dispatching on the dref's table type
SQUAD_SELECTION_PLAYER = 106    # PERSON_UI_HANDLER subclass (same record)
PLAYER_REPORT = 75
CLIENT_DATA_KEYS_SLOT = 14      # (this, request, out vector<u32>)
CLIENT_DIRECT_KEY_SLOT = 13     # (this, u32 key) -> u32 data key or 'NULL'
NULL_KEY = 0x4E554C4C           # 'NULL'
BAG_INSERT_RVA = 0x43F72E4      # property bag insert (bag, u32 key, typed* value)
PERSON_IN_PLAYER = 0x388        # ACTUAL_PLAYER -> PERSON sub-object (players.person_offset)
PERSON_IN_STAFF = 0x480

# Squad screen happiness bands ('Pohl' HierarchyOverallHappinessLevel), see UI_PERSON.md.


# ---------------------------------------------------------------------- request parameters
# Some getters read screen parameters from the request's UI context: 0x77E228(request, path,
# out typed*, inherit) looks the parameter `path` (a global, e.g. 0x56D1A08) up in the
# context node request+0x38 (hash map 0x56A4A98, walking parent nodes at node+0x38). Our
# requests carry no context node (+0x38 = 0), so a parameter the front end would set is
# answered here: a code hook after the prologue (0x77E240) sees (x0 request, x1 path,
# x2 out); for a parameter we supply it continues at the shipped success tail 0x77E2CC
# (x20 = out, x0 = value: `copy(out, value); return 1`). Values are int32 typed values built
# with the shipped constructor 0x4403EC0. Unsupplied parameters run the original code.
PARAM_LOOKUP_RVA = 0x77E228
PARAM_HOOK_RVA = 0x77E240       # after the prologue: cbz x22 (context node), x0..x2 intact
PARAM_FOUND_RVA = 0x77E2CC      # mov x1, x0; mov x0, x20; bl copy; mov w0, #1; epilogue
INT32_VARIANT_RVA = 0x4403EC0   # (typed* out, int32 value)


def _install_param_hook(vm):
    if getattr(vm, '_request_params', None) is not None:
        return
    import unicorn.arm64_const as A
    from unicorn import UC_HOOK_CODE
    vm._request_params = {}       # request address -> {path rva: typed* value}

    def hook(uc, address, size, user):
        params = vm._request_params.get(uc.reg_read(A.UC_ARM64_REG_X0))
        if not params:
            return
        value = params.get(uc.reg_read(A.UC_ARM64_REG_X1) - vm.base)
        if value is None:
            return
        vm.request_params_used = getattr(vm, 'request_params_used', 0) + 1
        uc.reg_write(A.UC_ARM64_REG_X20, uc.reg_read(A.UC_ARM64_REG_X2))
        uc.reg_write(A.UC_ARM64_REG_X0, value)
        uc.reg_write(A.UC_ARM64_REG_PC, vm.base + PARAM_FOUND_RVA)

    vm.uc.hook_add(UC_HOOK_CODE, hook, None, begin=vm.base + PARAM_HOOK_RVA,
                   end=vm.base + PARAM_HOOK_RVA)
    # A range hook only applies to blocks translated after it is added: drop any cached
    # translation of the lookup (observed: no parameter answered once 0x77E228 had run).
    vm.uc.ctl_remove_cache(vm.base + PARAM_LOOKUP_RVA, vm.base + PARAM_FOUND_RVA + 0x24)


# ---------------------------------------------------------------------- data-key protocol
@dataclass
class DataReader:
    """Reads properties of one built handler through the data-key protocol.

    Data values are computed once per handler (server slot 2) and shared by every property
    read afterwards; each value stays on the VM heap (part of the committed baseline)."""
    vm: UiHandlerVM
    handler: Handler
    data: dict = field(default_factory=dict)      # data key -> typed* or Unavailable
    deps: dict = field(default_factory=dict)      # property key -> tuple of data keys
    direct: dict = field(default_factory=dict)    # property key -> direct data key or None
    data_seconds: dict = field(default_factory=dict)
    rng_by_data: dict = field(default_factory=dict)

    def _request(self, key):
        request = self.vm.alloc(REQUEST_SIZE)
        self.vm.uc.mem_write(request, b'\0' * REQUEST_SIZE)
        self.vm.uc.mem_write(request + REQUEST_KEY_OFFSET, struct.pack('<I', fourcc(key)))
        return request

    def direct_key(self, key):
        """Client slot 13 `(this, key) -> u32`: the server data key whose value *is* the
        property ('NULL' when the property is computed by slot 4; e.g. Morale 'Mora' ->
        'Pmor'). The client's slot 4 returns null for such properties."""
        if key not in self.direct:
            vm = self.vm
            pinned = vm._baseline
            try:
                vm._restore()
                vm.commit()
                code, _ = vm.vcall(self.handler.client, CLIENT_DIRECT_KEY_SLOT, (fourcc(key),))
                code &= 0xFFFFFFFF
                self.direct[key] = None if code in (NULL_KEY, 0) else fourcc_text(code)
            except _Stop:
                self.direct[key] = None
            finally:
                vm._baseline = pinned
                vm._restore()
        return self.direct[key]

    def data_keys(self, key):
        if key not in self.deps:
            vm = self.vm
            pinned = vm._baseline
            try:
                vm._restore()
                request = self._request(key)
                vector = vm.alloc(64)
                vm.uc.mem_write(vector, b'\0' * 64)
                vm.commit()
                vm.vcall(self.handler.client, CLIENT_DATA_KEYS_SLOT, (request, vector))
                begin, end = struct.unpack('<QQ', vm.read(vector, 16))
                count = (end - begin) // 4
                if end < begin or count > 4096:
                    raise _Stop('implausible data-key vector', f'{begin:#x}..{end:#x}')
                codes = struct.unpack(f'<{count}I', vm.read(begin, 4 * count)) if count else ()
                self.deps[key] = tuple(dict.fromkeys(fourcc_text(c) for c in codes))
            except _Stop as stop:
                self.deps[key] = Unavailable('data-key declaration failed: ' + stop.reason,
                                             detail=stop.detail)
            finally:
                vm._baseline = pinned
                vm._restore()
        return self.deps[key]

    def fetch(self, data_key):
        if data_key not in self.data:
            vm = self.vm
            started, rng = time.perf_counter(), vm.rng_uses
            pinned = vm._baseline
            try:
                # Start from the committed state: a preceding get leaves its stores in the
                # VM, and server_value commits before it runs (observed: reading
                # HappinessTraining first emptied HappinessPositives).
                vm._restore()
                _, address, _ = vm.server_value(self.handler, data_key)
                vm.commit()
                self.data[data_key] = address
            except _Stop as stop:
                trace = vm.backtrace()
                vm._baseline = pinned
                vm._restore()
                self.data[data_key] = Unavailable(f'data key {data_key}: {stop.reason}',
                                                  detail=f'{stop.detail} [{" < ".join(trace)}]')
            self.data_seconds[data_key] = time.perf_counter() - started
            self.rng_by_data[data_key] = vm.rng_uses - rng
        return self.data[data_key]

    def data_value(self, data_key):
        """Decoded server value of one data key (for diagnostics and tests)."""
        address = self.fetch(data_key)
        if isinstance(address, Unavailable):
            return None, address
        self.vm._restore()
        return self.vm.decode(address)

    def get(self, key, params=None) -> Reading:
        """One property. `params` = {parameter path RVA: int} answers request parameters the
        getter reads through 0x77E228 (see PARAM_* above).

        The bag, request and every store of the getter are dropped afterwards: the
        baseline is pinned before and put back after (bag inserts copy typed values and
        touch the shared variant pool; letting them into the baseline changed later reads,
        observed: HappinessTraining before HappinessPositives emptied the latter)."""
        vm = self.vm
        started = time.perf_counter()
        code = key if isinstance(key, str) else fourcc_text(key)
        deps = self.data_keys(code)
        if isinstance(deps, Unavailable):
            return Reading(code, None, None, deps, time.perf_counter() - started)
        direct = self.direct_key(code) if not deps else None
        if direct:
            address = self.fetch(direct)
            if isinstance(address, Unavailable):
                return Reading(code, None, None, address, time.perf_counter() - started)
            vm._restore()
            kind, value = vm.decode(address)
            return Reading(code, None, kind, value, time.perf_counter() - started)
        addresses = {d: self.fetch(d) for d in deps}
        missing = {d: a for d, a in addresses.items() if isinstance(a, Unavailable)}
        if missing:
            first = next(iter(missing.values()))
            return Reading(code, None, None,
                           Unavailable(first.reason, detail=f'{len(missing)} of {len(deps)} data keys failed; '
                                       f'{first.detail}'), time.perf_counter() - started)
        pinned = vm._baseline
        request = None
        try:
            vm._restore()
            bag = vm.alloc(64)
            vm.uc.mem_write(bag, b'\0' * 64)
            vm.commit()
            for data_key, address in addresses.items():
                vm.call(vm.base + BAG_INSERT_RVA, [bag, fourcc(data_key), address])
                vm.commit()
            request = self._request(code)
            out = vm.alloc(16)
            vm.uc.mem_write(out, struct.pack('<QQ', vm.registry + 8, 0))
            values = {}
            for rva, number in (params or {}).items():
                values[rva] = vm.alloc(16)
                vm.uc.mem_write(values[rva], b'\0' * 16)
            vm.commit()
            for rva, number in (params or {}).items():
                vm.call(vm.base + INT32_VARIANT_RVA, [values[rva], number & 0xFFFFFFFF])
                vm.commit()
            if values:
                _install_param_hook(vm)
                vm._request_params[request] = values
            vm.vcall(self.handler.client, CLIENT_GET_SLOT, (request, out, bag))
            kind, value = vm.decode(out)
        except _Stop as stop:
            trace = vm.backtrace()
            kind, value = None, Unavailable(stop.reason, detail=f'{stop.detail} [{" < ".join(trace)}]')
        finally:
            if getattr(vm, '_request_params', None):
                vm._request_params.pop(request, None)
            vm._baseline = pinned
            vm._restore()
        return Reading(code, None, kind, value, time.perf_counter() - started)

    def rng_keys(self, key):
        deps = self.deps.get(key)
        if not isinstance(deps, tuple):
            return ()
        return tuple(d for d in deps if self.rng_by_data.get(d))


def read_record(vm: UiHandlerVM, handler_type: int, record: dict, keys=None, *, inputs=None,
                registry=None) -> tuple[HandlerReading, DataReader]:
    """Build a database-record handler and read `keys` (default: every slot-4 key of the
    client class) through the data-key protocol. Declared inputs are transferred first
    (as `read_handler` does) because some getters also consult the client cache."""
    registry = registry or ui_registry.default()
    handler = vm.build(handler_type, record)
    out = HandlerReading(handler_type, handler.client_class, handler.server_class,
                         dict(handler.record), {}, build_seconds=handler.build_seconds)
    started = time.perf_counter()
    if handler.server:
        for key in (inputs if inputs is not None else input_keys(registry, handler.client_class)):
            vm.transfer(handler, key)
    out.inputs = dict(handler.inputs)
    out.input_seconds = time.perf_counter() - started
    reader = DataReader(vm, handler)
    if keys is None:
        row = registry.classes.get(handler.client_class) or registry.classes.get('PERSON_UI_HANDLER')
        keys = row.keys(4) if row else ()
    for code in keys:
        reading = reader.get(code)
        reading.label = registry.label(code)
        out.readings.append(reading)
    out.files_read = tuple(sorted(vm.files_read))
    return out, reader


# ---------------------------------------------------------------------- object ids
def person_object(read, primary: int, base: int) -> int:
    """PERSON sub-object of an ACTUAL_PLAYER / player-staff primary (the object whose virtual
    +0x88 returns the person's UI id; the primary itself returns 0)."""
    from .. import players
    table = struct.unpack('<Q', read(primary, 8))[0]
    if table == base + players.STAFF_RVA[0]:
        return primary + PERSON_IN_STAFF
    if table == base + players.RVA[0]:
        return primary + PERSON_IN_PLAYER
    raise ValueError('not a player or player-staff primary object')


def person_id(vm: UiHandlerVM, read, primary: int) -> int:
    pid = vm.object_ref(person_object(read, primary, vm.base))
    if pid >> 24 != 1:
        raise ValueError(f'unexpected person UI id {pid:#x}')
    return pid


# ---------------------------------------------------------------------- player status
PLAYER_KEYS = {
    # identity
    'name': '2K31', 'unique_id': 'unid',
    # happiness and morale
    'morale': 'dafe', 'morale_value': 'Mora',
    'happiness_level': 'Pohl', 'happiness_recent_change': 'd1g9', 'happiness_training': 'd1g4',
    'happiness_positives': 'HPPo', 'happiness_negatives': 'HPNe',
    'happiness_positives_count': 'Oden', 'happiness_negatives_count': 'iP61',
    'playing_time_happiness': '225*', 'playing_time_happiness_level': 'pthn',
    'international_happiness': 'V2SL',
    'international_positives': 'IHPo', 'international_negatives': 'IHNe',
    'positive_reaction': 'sE6l', 'negative_reaction': 'a7z1',
    'positive_players': '0DRm', 'negative_players': 'iYLB',
    'hierarchy_influence': 'THic', 'hierarchy_influence_short': 'K9UT',
    # promises
    'promises': 'Pmbm', 'promises_count': 'd1g:', 'active_promises_count': 'FkLZ',
    'completed_promises': 'W2VE', 'completed_promises_count': 'TvIj',
    'job_interview_promises': 'T2Jj', 'board_requests': 'Rs4n',
    # squad status and playing time
    'expected_playing_time': '224*', 'expected_vs_promised_playing_time': '224+',
    # transfer status and interest
    'transfer_status': 'glsW', 'transfer_value': '4OUZ',
    'transfer_offer_status': 'douK',
    'active_interested_clubs': 'OMVS', 'active_interested_clubs_count': '5LJ3',
    'all_interested_clubs': 'I1cd', 'all_interested_clubs_count': 'sYaw',
    'rumoured_interested_clubs': 'eYwU', 'rumoured_interested_clubs_count': 'Twmb',
    'transfer_offers_and_interest': 'aLhi',
    'first_populated_interest_list': 'cub6', 'not_interested_count': 'i7xA',
    'transfer_confidence': 'Vvsx',
    # contract
    'contract_weekly_wage': 'QNVC', 'new_contract': 'T1Db', 'contract': 'ctrc',
}

# Opt-in (pass the name or code in `keys`): HumanTransferRumours draws the game's RNG
# (126 draws for one player) and took ~100 s, against ~1 s for the default set.
OPTIONAL_PLAYER_KEYS = {'transfer_rumours': 'U4XF'}

# CONTRACT_UI_HANDLER (type 19) keys read through the record PERSON returns for 'ctrc'.
CONTRACT = 19
CONTRACT_KEYS = {
    'squad_status_actual': 'QJql', 'squad_status_agreed': 'iag9', 'contract_status': 'Pcif',
    'contract_type': 'Q2Of', 'set_for_release': 'PsfR', 'wage': 'Pcww',
    'agreed_playing_time_future': 'zm17',
}

# Squad-screen happiness bands. The CLUB/TEAM 'nohp' data key (HappyPlayersCount, 47 / 23
# on the reference save) counts a player when the signed byte at +0x5A of the object his
# virtual +0x3C0 returns is > 59 (0x1FB1974: ldrsb; cmp #0x3B), skipping objects whose
# virtual +0x90 returns 5 and players whose virtual +0x4E8 is true. 'Pohl' reproduces the
# first-team count exactly (23); see UI_PERSON.md for the club-wide comparison.
VERY_HAPPY_ABOVE = 59


def squad_screen_band(fields: dict) -> str | None:
    level = fields.get('happiness_level')
    if not isinstance(level, int) or isinstance(level, bool):
        return None
    if level > VERY_HAPPY_ABOVE:
        return 'very happy'
    if isinstance(fields.get('playing_time_happiness_level'), int) and fields['playing_time_happiness_level'] < 0 \
            and str(fields.get('playing_time_happiness', '')).startswith('Is concerned'):
        return 'concerned about playing time'
    return 'other'


def _session_vm(vm_or_session, rng='copy'):
    if isinstance(vm_or_session, UiHandlerVM):
        return vm_or_session, None
    from .image import PluginImage
    from .memory import LiveMemory
    from .ui_vm import lsof_resolver
    session = vm_or_session
    image = PluginImage.load(session.plugin_path)
    memory = LiveMemory(session.pid)
    vm = UiHandlerVM(memory, session.base, image, file_resolver=lsof_resolver(session.pid), rng=rng)
    vm.fast()
    return vm, memory


def _value(reading):
    value = reading.value
    if isinstance(value, Unavailable):
        return {'unavailable': value.reason}
    return plain_text(variant.to_json(value))


def player_status(vm_or_session, player, *, keys=None, all_keys=False, record_type=DATABASE_RECORD,
                  read=None, contract=True) -> dict:
    """Runtime status of one player as the game's Player screens show it.

    `player`: a person UI id (`1 << 24 | people index`), or the address of an ACTUAL_PLAYER /
    player-staff primary object (then `read` or a live session is needed to locate the PERSON
    sub-object). Returns {'fields': {name: value}, 'contract': {...}, 'squad_screen_band',
    'keys' (with all_keys: every PERSON slot-4 key, about 660), 'summary', timings, rng}.
    Recipe: UI_RECORD {'110 ': 28, 'dref': person id} -> PERSON_UI_HANDLER; values through
    the data-key protocol. With `contract`, the record PERSON returns for 'ctrc' is opened as
    CONTRACT_UI_HANDLER (type 19) for squad status and contract status."""
    if isinstance(vm_or_session, UiHandlerVM) or not hasattr(vm_or_session, 'plugin_path'):
        vm, memory = vm_or_session, None
    else:
        vm, memory = _session_vm(vm_or_session)
        read = read or vm_or_session.reader.read
    try:
        if player >> 24 == 1 and player < 1 << 25:
            pid = player
        else:
            pid = person_id(vm, read or vm.reader.read, player)
        names = dict(PLAYER_KEYS)
        if keys is not None:
            names = {k: v for k, v in {**PLAYER_KEYS, **OPTIONAL_PLAYER_KEYS}.items()
                     if k in keys or v in keys}
        if contract:
            names.setdefault('contract', 'ctrc')
        codes = list(dict.fromkeys(names.values()))
        if all_keys:
            codes = list(dict.fromkeys(codes + list(ui_registry.default().classes['PERSON_UI_HANDLER'].keys(4))))
        rng0, started = vm.rng_uses, time.perf_counter()
        reading, reader = read_record(vm, record_type, {'dref': pid}, keys=codes)
        by_code = {r.code: r for r in reading.readings}
        fields = {name: _value(by_code[code]) for name, code in names.items() if code in by_code}
        out = {
            'person_id': pid, 'handler': reading.client_class, 'server': reading.server_class,
            'recipe': {'type': record_type, 'record': {'dref': pid}},
            'fields': fields,
            'summary': reading.summary(),
            'seconds': round(time.perf_counter() - started, 3),
            'rng_uses': vm.rng_uses - rng0,
            'rng_data_keys': sorted(k for k, n in reader.rng_by_data.items() if n),
            'failed_data_keys': {k: v.reason for k, v in reader.data.items() if isinstance(v, Unavailable)},
        }
        out['squad_screen_band'] = squad_screen_band(fields)
        record = by_code.get('ctrc')
        if contract and record is not None and isinstance(record.value, dict) \
                and record.value.get('110 ') == CONTRACT:
            rec = {k: v for k, v in record.value.items() if k != '110 '}
            c_reading, c_reader = read_record(vm, CONTRACT, rec, keys=list(CONTRACT_KEYS.values()))
            c_by = {r.code: r for r in c_reading.readings}
            out['contract'] = {name: _value(c_by[code]) for name, code in CONTRACT_KEYS.items()}
            out['contract_recipe'] = {'type': CONTRACT, 'record': rec}
            out['rng_uses'] = vm.rng_uses - rng0
        out['seconds'] = round(time.perf_counter() - started, 3)
        if all_keys:
            out['keys'] = {r.code: {'label': r.label, 'kind': r.kind, 'value': _value(r)}
                           for r in reading.readings}
        return out
    finally:
        if memory is not None:
            memory.close()


# ---------------------------------------------------------------------- club vision
# CLUB_UI_HANDLER 'ViOl' (VisionObjectiveList, getter at 0xB9FAC) reads three request
# parameters through 0x77E228: owner (0x56D1A08: 1 board -> data 'CvBo', 2 supporters ->
# 'Cvso'), filter (0x56D1A18) and a flag (0x56D1A28). Filter values were mapped on the
# reference save against the Club Vision screen (UI_PERSON.md): 0 all, 1 contract rules,
# 2 actionable non-contract, 3 actionable + culture, 4 culture, 5 competitions (current
# season, needs flag 1), 6 actionable (as the screen's "Actionable" list), 7 like 5.
VISION_OWNER, VISION_FILTER, VISION_FLAG = 0x56D1A08, 0x56D1A18, 0x56D1A28
VISION_FILTERS = {'all': 0, 'actionable': 6, 'culture': 4, 'competitions_this_season': 5}
OWNERS = {'board': 1, 'supporters': 2}
# Importance text: the screen's words for the raw 'coip' (0..10) value. Bands inferred from
# the 17 objectives on the reference save (1/3 Favoured, 4/5/6 Preferred, 7 Desired,
# 10 Required); values 2, 8 and 9 were not observed. Fallback only: the screen's words come
# from the front end's ClubVisionImportanceDataCollection (keys 0, 3, 6, 8, 10; game strings
# 1738-1742), `ui_recipes_screens.importance_text`.
IMPORTANCE_BANDS = ((10, 'Required'), (7, 'Desired'), (4, 'Preferred'), (1, 'Favoured'))
OBJECTIVE_FIELDS = {'cvon': 'objective', 'coip': 'importance_value', 'cvoc': 'category',
                    'cvoi': 'id', 'Viys': 'season', 'hint': 'hint', 'VOse': 'setter',
                    'cvos': 'state', 'VOdt': 'type', 'cvop': 'judgement_value', 'aZDo': 'linked_name',
                    'comp': 'competition'}
CLUB_KEYS = {
    'board_culture': 'G4M5', 'supporter_culture': 'aEhV', 'board_members_count': 'O8ap',
    'supporter_board_influence': 'CsbR', 'chairman_status': 'VIKf', 'wages': '6MU6',
    'happy_players': 'zCj2', 'vision_objective_count': 'ViOc', 'vision_year': 'Viys',
}
BOARD_MEMBER_KEYS = {'surname': '2K31', 'name': 'iSnm', 'job': 'b9r7', 'nationality': 'natY'}


def importance_text(value):
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return None
    for floor, text in IMPORTANCE_BANDS:
        if value >= floor:
            return text
    return None


def _objective(entry, vm=None):
    row = {name: entry.get(code) for code, name in OBJECTIVE_FIELDS.items()}
    word = None
    if vm is not None:      # the screen's own word (ClubVisionImportanceDataCollection, translated)
        from .ui_recipes_screens import importance_text as game_importance
        try:
            word = game_importance(vm, row['importance_value'])
        except Exception:  # noqa: BLE001 - fall back to the inferred bands
            word = None
    row['importance'] = word or importance_text(row['importance_value'])
    return row


def club_vision(vm_or_session, club=None, *, read=None, members=True) -> dict:
    """Club Vision as the Club Vision / Board / Supporters / Finances screens show it.

    `club`: CLUB UI id (table 3) or the CLUB object's address; default the managed club.
    Recipe: {'110 ': 28, 'dref': club id} -> CLUB_UI_HANDLER, data-key protocol; objective
    lists with request parameters (VISION_*). Judgements are not available (see docs)."""
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
        reading, reader = read_record(vm, DATABASE_RECORD, {'dref': cid}, keys=list(CLUB_KEYS.values()))
        by = {r.code: r for r in reading.readings}
        out = {'club_id': cid, 'handler': reading.client_class,
               'recipe': {'type': DATABASE_RECORD, 'record': {'dref': cid}},
               'fields': {name: _value(by[code]) for name, code in CLUB_KEYS.items()},
               'objectives': {}}
        for owner, number in OWNERS.items():
            lists = {}
            for name, mode in VISION_FILTERS.items():
                x = reader.get('ViOl', params={VISION_OWNER: number, VISION_FILTER: mode,
                                               VISION_FLAG: 1})
                value = _value(x)
                lists[name] = [_objective(e, vm) for e in value] if isinstance(value, list) else value
            out['objectives'][owner] = lists
        if members:
            kind, refs = reader.data_value('TCsO')
            rows = []
            for ref in (refs if isinstance(refs, list) else []):
                person = ref.get('dref') if isinstance(ref, dict) else None
                if person is None:
                    continue
                m_reading, _ = read_record(vm, DATABASE_RECORD, {'dref': person},
                                           keys=list(BOARD_MEMBER_KEYS.values()), inputs=())
                m_by = {r.code: _value(r) for r in m_reading.readings}
                row = {name: m_by.get(code) for name, code in BOARD_MEMBER_KEYS.items()}
                job = row.get('job')
                row['role'] = job.get('17 !') if isinstance(job, dict) else None
                row['person_id'] = person
                rows.append(row)
            out['board_members'] = rows
        out['rng_uses'] = vm.rng_uses - rng0
        out['rng_data_keys'] = sorted(k for k, n in reader.rng_by_data.items() if n)
        out['request_params_used'] = getattr(vm, 'request_params_used', 0)
        out['seconds'] = round(time.perf_counter() - started, 3)
        return out
    finally:
        if memory is not None:
            memory.close()


# ---------------------------------------------------------------------- scout report
# PLAYER_REPORT (type 75) is a cache-style handler: record {'Pers': person id, 'PbPY':
# manager person id}; inputs 'anli', 'scri', 'scrp' are transferred server -> client and
# slot 4 reads from the client cache (ui_handlers.read_handler). Knowledge is applied by
# the handler: ability is a star range (MinV/MaxV), unknown values read "Unknown" or
# "Scouting Required", own players are exact (MinV == MaxV).
SCOUT_KEYS = {
    'title': 'nLPp', 'overall': 'oeo9', 'scout_grade': 'gzwO', 'analyst_grade': 'NrKz',
    'pros_cons': 'F1Ip', 'analyst_pros_cons': 'tozv', 'report': 'XwEJ', 'analyst_report': '9MnI',
    'current_ability': 'ybPw', 'potential_ability': 'Smxq', 'transfer': 'AxDD',
    'positions': 'My2T', 'best_role': 'P5lg', 'best_oop_role': 'Jngq',
    'training_feedback': 'uNhy', 'watched_matches': 'F3aR', 'has_scouted_info': 's9wb',
    'squad_comparison': 'j5L3',
}


def scout_report(vm, person: int, manager: int) -> dict:
    """Scouting report on one player as the Player > Reports screen shows it to `manager`.

    `person`, `manager`: person UI ids (1 << 24 | people index)."""
    from .ui_handlers import read_handler
    started, rng0 = time.perf_counter(), vm.rng_uses
    reading = read_handler(vm, PLAYER_REPORT, {'Pers': person, 'PbPY': manager},
                           keys=list(SCOUT_KEYS.values()))
    by = {r.code: r for r in reading.readings}
    fields = {name: _value(by[code]) for name, code in SCOUT_KEYS.items()}
    overall, pc = fields.get('overall'), fields.get('pros_cons')
    report = fields.get('report')
    summary = {
        'recommendation': overall.get('pzbQ') if isinstance(overall, dict) else None,
        'recommendation_text': overall.get('a2Lc') if isinstance(overall, dict) else None,
        'grade_value': overall.get('r5Fk') if isinstance(overall, dict) else None,
        'pros': [p.get('QSGC') for p in pc.get('6NmT', [])] if isinstance(pc, dict) else None,
        'cons': [p.get('QSGC') for p in pc.get('6NmU', [])] if isinstance(pc, dict) else None,
        'report_date': report.get('119 ') if isinstance(report, dict) else None,
        'scout_id': (report.get('g iS') or {}).get('dref') if isinstance(report, dict) else None,
    }
    if summary['scout_id']:
        s_reading, _ = read_record(vm, DATABASE_RECORD, {'dref': summary['scout_id']}, keys=['iSnm'],
                                   inputs=())
        summary['scout'] = _value(s_reading.readings[0])
    return {'person_id': person, 'manager_id': manager, 'handler': reading.client_class,
            'recipe': {'type': PLAYER_REPORT, 'record': {'Pers': person, 'PbPY': manager}},
            'inputs': reading.inputs, 'summary': summary, 'fields': fields,
            'counts': reading.summary(), 'rng_uses': vm.rng_uses - rng0,
            'seconds': round(time.perf_counter() - started, 3)}


__all__ = ['scout_report', 'DataReader', 'read_record', 'player_status', 'club_vision', 'person_id', 'person_object',
           'PLAYER_KEYS', 'CONTRACT_KEYS', 'CLUB_KEYS', 'DATABASE_RECORD', 'SQUAD_SELECTION_PLAYER',
           'squad_screen_band', 'importance_text']
