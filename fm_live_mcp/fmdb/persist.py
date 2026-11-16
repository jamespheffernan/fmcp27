"""Read persisted native objects by running the game's own save code (docs/fmdb/PERSIST.md).

`dump(engine, root)` runs the save function of one manager root (from `data/persist_routes.json`,
the calls the save walker 0x256D728 makes) in `persist_stream.SaveRecorderVM` against the live
objects and returns the ordered typed field list it wrote, nested by the save functions that
wrote each part (`Call`s), with:

* `offset`: the object offset a value came from. `buffer` when save code handed write() a pointer
  into the object itself; `value` when the bytes equal the bytes at one offset of the object on
  every instance written by the same code (all instances with a nonzero value agree, and the
  offset is unique); otherwise None.
* `class`: RTTI class of the object a save function was given (x0), `ref`: table and idx when
  that object is a database record of a live table.
* `label`: only from evidence (`label_source`): a hand-built decoder that reads the same class and
  offset (`decoder`), the element class (`rtti`); otherwise `field_<n>` with type and offset.

`schema(engine, root)` aggregates the same run per save function: the fields in write order with
widths, how often each repeats per instance (containers), offsets and element classes.

`dump(engine, class_name, instance_address)` runs the save function that the root runs for that
class (learnt from the root's run) on one instance.

Nothing is written to the game: the save runs in the VM on copied pages, and the recorder refuses
file-system calls (persist_stream.SAVE_REFUSED).
"""
from __future__ import annotations

from collections import Counter, defaultdict
import bisect
import gzip
import json
from pathlib import Path
import re
import struct
import time

from .vm import _Stop, PRIVATE, NULL_LIMIT

DATA = Path(__file__).resolve().parent / 'data'
ROUTES_FILE = DATA / 'persist_routes.json'
SCHEMA_FILE = DATA / 'persist_schema.json.gz'
WALKER_RVA = 0x256D728
WINDOW = 0x800                  # bytes of an object searched for a written value
VERIFY_SAMPLES = 400             # objects per field whose bytes are compared at the winning offset
PLAIN_SPAN = 0x2000             # an address this far past an object start counts as inside it
DEFAULT_BUDGET = 400_000_000
DEFAULT_TIMEOUT_US = 300_000_000
CACHE_SECONDS = 120.0
CACHE_ENTRIES = 2               # recordings kept per engine (each up to MAX_WRITES writes)
MAX_WRITES = 4_000_000          # GAME_RULE_GROUP_MANAGER writes the whole database: 15 M writes, 5 min

# Database record classes (RTTI short name) -> live table (sources/_common.live kinds).
TABLE_OF_CLASS = {
    **{c: 'people' for c in ('ACTUAL_PLAYER', 'ACTUAL_NON_PLAYER', 'ACTUAL_PLAYER_AND_NON_PLAYER', 'VIRTUAL_PLAYER',
                              'HUMAN_NON_PLAYER', 'SUPPORT_STAFF', 'OFFICIAL', 'JOURNALIST', 'AGENT', 'PERSON',
                              'PLAYER', 'NON_PLAYER', 'RETIRED_PERSON')},
    'CLUB': 'clubs', 'LEAGUE_BODY_CLUB': 'clubs', 'TEAM': 'teams', 'NATIONAL_TEAM': 'teams',
    'COMP': 'competitions', 'NATION': 'nations', 'NATIONAL_TEAM_CONTAINER': 'national_team_containers',
    'CONTINENT': 'continents', 'CITY': 'cities', 'CURRENCY_RECORD': 'currencies', 'STADIUM': 'stadiums',
    'LANGUAGE': 'languages', 'LOCAL_REGION': 'local_regions', 'WEATHER': 'weather', 'INJURY': 'injuries',
    'AWARD': 'awards', 'MEDIA_SOURCE': 'media_sources', 'REGION': 'regions', 'DERBY': 'derbies',
    'AGREEMENT': 'agreements', 'STAGE_NAME': 'stage_names', 'PLAYER_TYPE': 'player_types',
}

# Offsets that hand-built decoders read, by class: (class, offset text as _fmt_offset prints it) ->
# (label, decoder module). Each entry names the module whose code reads it and was checked by
# scripts/fmdb_persist_check.py (PERSIST.md "Checks"): the save writes the same bytes from there.
_OFFER_LABELS = {'0x58': 'amount', '0x8d': 'state', '[+0x38]+0x8': 'person (unique id)',
                 '[+0x40]+0x8': 'team 1 (unique id)', '[+0x48]+0x8': 'team 2 (unique id)',
                 '0x70': 'date 1 (low half)', '0x72': 'date 1 (high half)', '0x74': 'date 2 (low half)',
                 '0x76': 'date 2 (high half)', '0x78': 'date 3 (low half)', '0x7a': 'date 3 (high half)',
                 '0x7c': 'date 4 (low half)', '0x7e': 'date 4 (high half)'}
# news items (every *_NEWS class NEWS_MANAGER +0xB8 holds; live_state.news_item reads these): checked on
# 90 items of 37 classes, the date as two u16 writes
NEWS_LABELS = {'0x90': ('unique id', 'live_state.news_item'), '0x98': ('flags', 'live_state.news_item'),
               '0x88': ('packed date (low half)', 'live_state.news_item'),
               '0x8a': ('packed date (high half)', 'live_state.news_item')}
DECODER_LABELS = {(cls, off): (label, 'live_transfer_offers')
                  for cls in ('DRAFT_OFFER', 'ENQUIRY_OFFER', 'TRANSFER_OFFER', 'FULL_TRANSFER_OFFER', 'LOAN_OFFER',
                              'TRIAL_OFFER', 'TRADE_OFFER', 'B_CLUB_MOVE_OFFER')
                  for off, label in _OFFER_LABELS.items()}


class PersistError(RuntimeError):
    pass


# ------------------------------------------------------------------------------------------- routes
# Every address of data/persist_routes.json in the order `_route_addresses` lists them, written as
# literals so the address book translates them on another game build (the JSON is data and is never
# rewritten: on 27.0.1 every route refused "save walker call site ... is not a direct call").
_ROUTE_ADDRESSES = (
    0x256d728, 0x2583dcc, 0x55f4ac8, 0x56a4b90, 0x4215d94, 0x2571a4c,
    0x56a6890, 0x26e346c, 0x2571e18, 0x56a5908, 0x28f274c, 0x25721e4,
    0x56a49f8, 0x1828858, 0x25725b0, 0x56a49f8, 0x2c734fc, 0x25725c0,
    0x56a4be0, 0x2b1bb14, 0x257298c, 0x56a5e50, 0x2b66f84, 0x2573120,
    0x56a8310, 0x2b511a0, 0x25734ec, 0x56a8428, 0x1596634, 0x25738b8,
    0x56a82a8, 0x2a8d2b0, 0x2573c84, 0x56b76a0, 0x265bab0, 0x2574050,
    0x56a5190, 0x266c388, 0x257441c, 0x56a8430, 0x26c2c48, 0x2574bb4,
    0x56a82a0, 0x26fe31c, 0x2574f80, 0x56a5740, 0x2cb9224, 0x257534c,
    0x56a8700, 0x2c8a83c, 0x2575718, 0x56a6ab0, 0x2aa8aa8, 0x2575d58,
    0x56a82b0, 0x25d0364, 0x2576124, 0x56a6218, 0x25b8bbc, 0x25764f0,
    0x56b5030, 0x26bbba4, 0x25768bc, 0x56a64c8, 0x26047d0, 0x2576c88,
    0x56b50a8, 0x291f604, 0x2577054, 0x56b5568, 0x2905b24, 0x2577420,
    0x56b6188, 0x259e31c, 0x25777ec, 0x56b7680, 0x2666838, 0x2577bb8,
    0x56b5428, 0x268ba48, 0x2577f84, 0x56a6888, 0x28cf5b4, 0x2578350,
    0x56b54e0, 0x2b3f7e0, 0x257871c, 0x56a7f10, 0x26c90b4, 0x2578ae8,
    0x56a4f40, 0x25d95e0, 0x2578eb4, 0x56a5688, 0x273ee94, 0x2579280,
    0x56a8690, 0x295290c, 0x257964c, 0x56a57a0, 0x278abfc, 0x2579a18,
    0x56b6770, 0x2bdb0dc, 0x2579de4, 0x56b5430, 0x25e836c, 0x257a1b0,
    0x56b5438, 0x26b9d84, 0x257a57c, 0x56b6190, 0x2675f58, 0x257a948,
    0x56a86f0, 0x25f6b60, 0x257ad14, 0x56a80e0, 0x1390904, 0x257b0e0,
    0x56b5038, 0x2878750, 0x257b4ac, 0x56a49f0, 0x27cd9c4, 0x257b878,
    0x56a4a00, 0x293c320, 0x257bc44, 0x56a8438, 0x2668da8, 0x257c010,
    0x56b5570, 0x1c41fdc, 0x257c7a8, 0x56b51d8, 0x27964b8, 0x2572d54,
)


def _route_addresses(doc) -> list[int]:
    """The pinned addresses of the route file: walker, slot function, save system vtable, then
    each route's root_rva, function and site."""
    keys = ('root_rva', 'function', 'site')
    return [int(doc[k], 16) for k in ('walker', 'slot_function', 'save_system_vtable')] + \
        [int(r[k], 16) for r in doc['routes'] for k in keys]


def routes() -> list[dict]:
    """The save walker's calls: [{root, root_rva, path, function, site}] (data/persist_routes.json),
    with the addresses of the running build."""
    doc = json.loads(ROUTES_FILE.read_text())
    pinned = _route_addresses(doc)
    if len(pinned) != len(_ROUTE_ADDRESSES):
        raise PersistError('persist_routes.json and its address literals differ; regenerate _ROUTE_ADDRESSES')
    here = {}
    for old, new in zip(pinned, _ROUTE_ADDRESSES):
        if here.setdefault(old, new) != new:
            raise PersistError(f'save route address {old:#x} translates two ways')
    return [dict(r, **{k: f'{here[int(r[k], 16)]:#x}' for k in ('root_rva', 'function', 'site')})
            for r in doc['routes']]


def _verify_route(engine, route):
    """The call site in the walker must still be `bl function` in the loaded plugin image."""
    site = int(route['site'], 16)
    word = struct.unpack('<I', engine.image.file_bytes(site, 4))[0]
    if word >> 26 != 0b100101:
        raise PersistError(f"save walker call site {route['site']} is not a direct call in this build")
    imm = word & 0x3FFFFFF
    if imm & (1 << 25):
        imm -= 1 << 26
    if site + 4 * imm != int(route['function'], 16):
        raise PersistError(f"save walker call site {route['site']} calls another function in this build")


def _resolve_object(engine, vm, route) -> int:
    obj = vm.read_u64(engine.base + int(route['root_rva'], 16))
    for op, v in re.findall(r'([+*])(0x[0-9a-f]+)', route.get('path') or ''):
        obj = obj + int(v, 16) if op == '+' else vm.read_u64(obj + int(v, 16))
    return obj


def find_route(name: str) -> dict:
    want = name.strip()
    for r in routes():
        if r['key'] == want or r['root'] == want:
            return r
    raise PersistError(f'no save route for {name!r}: one of ' + ', '.join(r['key'] for r in routes()))


# ------------------------------------------------------------------------------------------- running
class Recording:
    """One emulated save of one object: the recorder's writes and calls plus derived facts."""

    def __init__(self, key, function, obj, status, refusal, vm, seconds, instructions):
        self.key, self.function, self.obj = key, function, obj
        self.status, self.refusal = status, refusal
        self.writes, self.calls = vm.writes, vm.calls
        self.streams, self.items = vm.streams, vm.items
        self.seconds, self.instructions = seconds, instructions
        self.files_read = sorted(vm.files_read)
        self.marked = dict(vm.marked)
        self.taken = time.time()
        self.classes = {}           # call id -> RTTI class short name or None
        self.windows = {}           # call id -> bytes of the object window (live objects only)


def _vm(engine, provenance=True):
    attr = '_persist_vm_p' if provenance else '_persist_vm'
    vm = getattr(engine, attr, None)
    if vm is None:
        from . import persist_stream
        from .engine import _VMReader
        from .ledger import function_starts
        cls = persist_stream.recorder_class()
        vm = cls(_VMReader(engine.memory), engine.base, engine.image, budget=DEFAULT_BUDGET,
                 timeout_us=DEFAULT_TIMEOUT_US, file_resolver=engine.file_resolver(),
                 function_starts=function_starts(engine.image), provenance=provenance)
        vm.max_writes = MAX_WRITES
        setattr(engine, attr, vm)
        engine._persist_starts = sorted(vm.function_starts)
    return vm


def demangle(name: str | None) -> str | None:
    """Itanium type name -> C++ name for plain and nested names (N...E); templates kept raw."""
    if not name:
        return None
    s = name

    def parse_source(i):
        m = re.match(r'(\d+)', s[i:])
        if not m:
            return None, i
        n = int(m.group(1))
        j = i + len(m.group(1))
        return s[j:j + n], j + n

    if s.startswith('N'):
        parts, i = [], 1
        while i < len(s) and s[i] != 'E':
            part, i2 = parse_source(i)
            if part is None:
                return name
            parts.append(part)
            i = i2
        return '::'.join(parts) if i < len(s) else name
    part, i = parse_source(0)
    return part if part is not None and i == len(s) else name


def class_at(vm, address) -> str | None:
    """RTTI class of an object (None when the first word is not a vtable with typeinfo)."""
    if not NULL_LIMIT <= address < PRIVATE:
        return None
    try:
        vt = vm.read_u64(address)
        if not (vm.base <= vt < vm.base + 0x6000000):
            return None
        return demangle(vm.rtti_name(vt))
    except (_Stop, Exception):  # noqa: BLE001 - unreadable or not an object
        return None


def record(engine, route: dict, *, obj: int | None = None, function: int | None = None,
           use_cache=True, provenance=True) -> Recording:
    """Run one save function (the route's, or `function` on `obj`) and keep the recording.
    provenance=True tracks the load each written value came from (slower; see persist_stream)."""
    vm = _vm(engine, provenance)
    key = (route['key'] if route else f'{function:#x}@{obj:#x}') + ('' if provenance else '#fast')
    cache = engine.__dict__.setdefault('_persist_cache', {})
    now = time.time()
    for k in [k for k, v in cache.items() if now - v.taken >= CACHE_SECONDS]:
        del cache[k]                    # recordings hold up to MAX_WRITES writes: keep few, briefly
    hit = cache.get(key)
    if use_cache and hit is not None:
        return hit
    while len(cache) >= CACHE_ENTRIES:
        del cache[min(cache, key=lambda k: cache[k].taken)]
    if route is not None:
        _verify_route(engine, route)
        function = int(route['function'], 16)
        if getattr(vm, '_persist_used', False):
            vm.refresh_pages()          # current game memory (drops the copied pages)
        obj = _resolve_object(engine, vm, route)
    vm._persist_used = True
    if not NULL_LIMIT <= obj < PRIVATE:
        raise PersistError(f'{key}: object pointer {obj:#x} is not a live address (manager not created)')
    started = time.perf_counter()
    status, refusal = 'ok', None
    try:
        vm.run(function, obj, holder_only=bool(route and route.get('holder_only')))
    except _Stop as stop:
        status, refusal = 'refused', f'{stop.reason}' + (f' ({stop.detail})' if stop.detail else '')
    rec = Recording(key, function, obj, status, refusal, vm, time.perf_counter() - started, vm._instructions())
    rec.provenance = vm.provenance
    for c in rec.calls:
        rec.classes[c.id] = class_at(vm, c.obj)
    rec.root_class = class_at(vm, obj)
    _object_windows(vm, rec)
    cache[key] = rec
    return rec


def _object_windows(vm, rec):
    """Copy the first WINDOW bytes of every live object a save function was given (value-offset
    search). Objects closer than WINDOW to the end of their mapping are cut at the page end."""
    for c in rec.calls:
        if NULL_LIMIT <= c.obj < PRIVATE and c.obj not in rec.windows:
            try:
                rec.windows[c.obj] = vm.read(c.obj, WINDOW)
            except Exception:  # noqa: BLE001 - next page unmapped
                try:
                    rec.windows[c.obj] = vm.read(c.obj, 0x1000 - (c.obj & 0xFFF))
                except Exception:  # noqa: BLE001
                    rec.windows[c.obj] = b''


# ------------------------------------------------------------------------------------------- analysis
def _fn(starts, rva):
    k = bisect.bisect_right(starts, rva) - 1
    return starts[k] if k >= 0 else rva


def _write_key(starts, call_fn, w):
    """(site in the calling save function, helper functions between it and write())."""
    helpers = []
    for f in w.frames:
        fn = _fn(starts, f)
        if fn == call_fn:
            return f, tuple(helpers)
        helpers.append(fn)
    return (w.frames[0] if w.frames else 0), tuple(helpers[:1])


def _int(data):
    return int.from_bytes(data, 'little') if len(data) in (1, 2, 4, 8) else None


TYPE_OF_WIDTH = {1: 'u8', 2: 'u16', 4: 'u32', 8: 'u64'}


class Analysis:
    """Per save function: field keys in first-seen order with aggregated facts."""

    def __init__(self, engine, rec: Recording):
        self.rec = rec
        self.engine = engine
        starts = engine._persist_starts
        self.starts = starts
        calls = rec.calls
        self.children = defaultdict(list)       # call id (or None: root writes) -> [(seq, kind, obj)]
        for w in rec.writes:
            self.children[w.call].append((w.seq, 'w', w))
        for c in calls:
            if c.parent is not None or c.id != 0:
                self.children[c.parent].append((c.seq, 'c', c))
        for v in self.children.values():
            v.sort(key=lambda t: t[0])
        self.by_fn = defaultdict(list)           # function -> [call]
        for c in calls:
            self.by_fn[c.function].append(c)
        self.fields = {}                         # function -> {key: facts}
        self.order = defaultdict(list)           # function -> [key]
        self._aggregate()

    def keys_of(self, call):
        """[(key, entry)] of one call in write order."""
        out = []
        for _, kind, obj in self.children.get(call.id, ()):
            if kind == 'w':
                site, helpers = _write_key(self.starts, call.function, obj)
                out.append((('w', site, helpers, len(obj.data)), obj))
            else:
                out.append((('c', obj.function, obj.site), obj))
        return out

    def _aggregate(self):
        rec = self.rec
        for fn, calls in self.by_fn.items():
            fields, order = {}, self.order[fn]
            for c in calls:
                per = Counter()
                window = rec.windows.get(c.obj, b'')
                for key, entry in self.keys_of(c):
                    f = fields.get(key)
                    if f is None:
                        f = fields[key] = {'count': Counter(), 'values': Counter(), 'cands': None, 'buffer': Counter(),
                                           'classes': Counter(), 'instances': 0, 'nonzero': 0,
                                           'load': Counter(), 'other': Counter()}
                        order.append(key)
                    per[key] += 1
                    if key[0] == 'w':
                        data = entry.data
                        if len(f['values']) < 6:
                            f['values'][data.hex()] += 1
                        if per[key] == 1:
                            self._offset_vote(f, c, entry, window)
                            if len(f.setdefault('samples', [])) < VERIFY_SAMPLES:
                                f['samples'].append((c, data))
                    else:
                        f['classes'][rec.classes.get(entry.id)] += 1
                for key in per:
                    fields[key]['count'][per[key]] += 1
                    fields[key]['instances'] += 1
            self.fields[fn] = fields
            for key, f in fields.items():
                self._verify(f)

    def _verify(self, f):
        """Check the winning plain offset on every sampled object: the written bytes must be the
        bytes at that offset (a load inside a callee can prove an offset for one object while the
        callee computes the value for another). f['verified'] = (agree, differ)."""
        where, _ = self._winner(f)
        if where is None or len(where) != 2:
            return
        ok = bad = 0
        for call, data in f.get('samples', ()):
            owner = dict(self.owners(call)).get(where[0])
            window = self.rec.windows.get(owner, b'') if owner is not None else b''
            if not window or where[1] + len(data) > len(window):
                continue
            if window[where[1]:where[1] + len(data)] == data:
                ok += 1
            else:
                bad += 1
        f['verified'] = (ok, bad)

    def owners(self, call, levels=3):
        """[(depth, object)]: the call's own object, then its callers' objects (live ones only)."""
        out, c, depth = [], call, 0
        while c is not None and depth <= levels:
            if NULL_LIMIT <= c.obj < PRIVATE:
                out.append((depth, c.obj))
            c = self.rec.calls[c.parent] if c.parent is not None else None
            depth += 1
        return out

    def locate(self, owners, address):
        """An address relative to the save functions' objects: (depth, offset) inside an object;
        (depth, 'vec', V) inside the element array of a vector whose begin/end pointers sit at object +V;
        (depth, 'ptr', P, r) inside the 0x400 bytes after a pointer at object +P."""
        for depth, obj in owners:
            if 0 <= address - obj < PLAIN_SPAN:
                return (depth, address - obj)
        for depth, obj in owners:
            window = self.rec.windows.get(obj, b'')
            n = len(window) // 8
            if not n:
                continue
            words = struct.unpack_from(f'<{n}Q', window)
            for k in range(n - 1):
                b, e = words[k], words[k + 1]
                if b <= address < e and e - b < (1 << 26) and NULL_LIMIT <= b:
                    return (depth, 'vec', 8 * k)
            for k in range(n):
                q = words[k]
                if NULL_LIMIT <= q <= address < q + 0x400:
                    return (depth, 'ptr', 8 * k, address - q)
        return None

    def _offset_vote(self, f, call, w, window):
        """Where the written bytes came from, relative to the object of this call or of a caller:
        the buffer itself (`buffer`), the load that produced the stored value (`load`), else the
        unique offset of the same bytes in the object (`value`, intersected over instances)."""
        data = w.data
        owners = self.owners(call)
        source, address = None, None
        if NULL_LIMIT <= w.buffer < PRIVATE:
            source, address = 'buffer', w.buffer
        else:
            loads = [p for p in w.parts if p[2] == 'load' and p[0] == 0]
            if loads and NULL_LIMIT <= loads[0][3] < PRIVATE:
                source, address = 'load', loads[0][3]
        if source:
            where = self.locate(owners, address)
            if where is not None:
                f[source][where] += 1
            else:
                f['other'][source + ' (outside the objects)'] += 1
            return
        if w.parts and w.parts[0][2] in ('computed', 'unknown'):
            f['other'][w.parts[0][2]] += 1
        if not data or len(data) > 8 or not any(data) or not window:
            return
        step = len(data) if len(data) in (2, 4, 8) else 1
        cands, i = set(), window.find(data)
        while i >= 0:
            if i % step == 0:
                cands.add(i)
            i = window.find(data, i + 1)
        f['nonzero'] += 1
        f['cands'] = cands if f['cands'] is None else (f['cands'] & cands)

    def offset(self, fn, key):
        """((depth, offset) | None, source); an offset whose bytes differ on some sampled object is
        not proven (None, with the counts)."""
        f = self.fields[fn][key]
        where, how = self._winner(f)
        ok, bad = f.get('verified', (0, 0))
        if where is not None and bad:
            return None, f'{how} at {_fmt_offset(where)} differs on {bad} of {ok + bad} objects (computed by a callee)'
        return where, how

    def _winner(self, f):
        for source in ('buffer', 'load'):
            votes = f[source]
            if votes:
                (where, n), = votes.most_common(1)
                agree = n / sum(votes.values())
                return where, source if agree == 1 else f'{source} ({agree:.0%} of instances)'
        c = f['cands']
        if c is not None and len(c) == 1 and f['nonzero'] >= 1:
            return (0, next(iter(c))), 'value' if f['nonzero'] >= 2 else 'value (one instance)'
        if f['other']:
            return None, f['other'].most_common(1)[0][0]
        return None, None


def key_text(key) -> str:
    """Stable text of a field key: w:<site>:<helper|...>:<width> or c:<function>:<site>."""
    if key[0] == 'w':
        return f"w:{key[1]:#x}:{'|'.join(f'{h:#x}' for h in key[2])}:{key[3]}"
    return f'c:{key[1]:#x}:{key[2]:#x}'


def key_of(field) -> tuple | None:
    text = field.get('key') if isinstance(field, dict) else field
    if not text:
        return None
    parts = text.split(':')
    if parts[0] == 'w':
        helpers = tuple(int(h, 16) for h in parts[2].split('|') if h)
        return ('w', int(parts[1], 16), helpers, int(parts[3]))
    return ('c', int(parts[1], 16), int(parts[2], 16))


def _fmt_offset(where):
    if where is None:
        return None
    depth = where[0]
    owner = '' if depth == 0 else f'caller{depth}'
    if len(where) == 2:
        return f'{where[1]:#x}' if depth == 0 else f'{owner}+{where[1]:#x}'
    if where[1] == 'vec':
        return f'{owner}+{where[2]:#x}[]'
    return f'{owner}[+{where[2]:#x}]+{where[3]:#x}'


def _type_of(key, data=None):
    if key[0] != 'w':
        return 'object'
    helpers, width = key[2], key[3]
    t = TYPE_OF_WIDTH.get(width, f'bytes[{width}]')
    return t


def _label(cls, offset, width=None, delta=None):
    """(label, source) from evidence: a hand-built decoder's (class, offset), else the database getter's
    verified direct plan for that class whose single load is this offset of the record (`getter:<KEY>`)."""
    if offset is None or offset[0] != 0:
        return None
    short = (cls or '').split('::')[-1]
    hit = DECODER_LABELS.get((short, _fmt_offset(offset)))
    if hit is None and short.endswith('_NEWS'):
        hit = NEWS_LABELS.get(_fmt_offset(offset))
    if hit:
        return hit[0], f'decoder:{hit[1]}'
    if len(offset) != 2:
        return None
    if cls and delta is not None and width:
        code = plan_labels().get((cls.split('::')[-1], offset[1] - delta, width))
        if code:
            return code, f'getter:{cls.split("::")[-1]}.{code}'
    return None


_PLAN_LABELS = None


def plan_labels() -> dict:
    """{(record class, offset from the table pointer, width): editor key} for every verified direct plan
    with a single load (data/plans-<sha>.json.gz): the record getter reads that offset for that key."""
    global _PLAN_LABELS
    if _PLAN_LABELS is None:
        idx = {}
        for path in sorted(DATA.glob('plans-*.json.gz')):
            try:
                plans = json.loads(gzip.decompress(path.read_bytes())).get('plans', {})
            except Exception:  # noqa: BLE001 - unreadable plan file
                continue
            for cls, keys in plans.items():
                for code, plan in keys.items():
                    chain = plan.get('chain')
                    if plan.get('status') == 'direct' and isinstance(chain, list) and len(chain) == 1 \
                            and plan.get('transform') in ('identity', None) and plan.get('width'):
                        idx.setdefault((cls, chain[0], plan['width']), code)
        _PLAN_LABELS = idx
    return _PLAN_LABELS


def record_delta(engine, cls, obj):
    """Offset from the object a save function got to its table pointer (the getter's `this`), when the
    object is a record of a live table; None otherwise."""
    if not cls:
        return None
    table = TABLE_OF_CLASS.get(cls.split('::')[-1])
    if table is None:
        return None
    try:
        from .sources import _common as C
        from . import tables as T
        index = C.index_of(engine, table)
    except Exception:  # noqa: BLE001
        return None
    if obj in index:
        return 0
    for _, (name, _, off) in T.CLASSES.items():
        if off and name == cls.split('::')[-1] and obj + off in index:
            return off
    return None


def _ref(engine, vm, cls, obj):
    """(table, idx) when obj is a record of a live database table."""
    if not cls:
        return None
    short = cls.split('::')[-1]
    table = TABLE_OF_CLASS.get(short)
    if table is None:
        return None
    try:
        from .sources import _common as C
        idx = C.index_of(engine, table).get(obj)
    except Exception:  # noqa: BLE001 - table not readable in this state
        idx = None
    return {'table': table, 'idx': idx} if idx is not None else {'table': table, 'idx': None}


def _node(engine, an, call, depth, budget, counter, *, with_values=True):
    rec = an.rec
    fn = call.function
    cls = rec.classes.get(call.id)
    out = {'function': f'{fn:#x}', 'class': cls, 'object': f'{call.obj:#x}', 'fields': []}
    delta = record_delta(engine, cls, call.obj)
    ref = _ref(engine, None, cls, call.obj) if cls else None
    if ref:
        out['ref'] = ref
    index = {k: i for i, k in enumerate(an.order[fn])}
    for key, entry in an.keys_of(call):
        if key[0] == 'c' and not an.children.get(entry.id):
            continue        # entered with the recorder in x1/x2 but wrote nothing: not a save function
        if counter[0] >= budget:
            out['truncated'] = True
            break
        counter[0] += 1
        n = index[key]
        if key[0] == 'w':
            off, how = an.offset(fn, key)
            shipped_off = None
            if off is None or how == 'value (one instance)':
                shipped_off = shipped_offset(fn, key)
            lab = _label(cls, off, key[3], delta)
            field = {'n': n, 'name': lab[0] if lab else f'field_{n}', 'type': _type_of(key),
                     'offset': _fmt_offset(off), 'offset_source': how,
                     'site': f'{key[1]:#x}'}
            if lab:
                field['label_source'] = lab[1]
            if shipped_off:
                field['offset'], field['offset_source'] = shipped_off[0], f'{shipped_off[1]} (schema run)'
            if with_values:
                field['value'] = _int(entry.data) if len(entry.data) in (1, 2, 4, 8) else entry.data[:64].hex()
            out['fields'].append(field)
        else:
            child_cls = rec.classes.get(entry.id)
            field = {'n': n, 'name': f'field_{n}', 'type': 'object', 'site': f'{key[2]:#x}',
                     'label_source': 'rtti' if child_cls else None}
            if child_cls:
                field['name'] = child_cls.split('::')[-1].lower()
            if depth > 0:
                field['object'] = _node(engine, an, entry, depth - 1, budget, counter, with_values=with_values)
            else:
                field['object'] = {'function': f'{entry.function:#x}', 'class': child_cls,
                                   'object': f'{entry.obj:#x}', 'fields': '…'}
            out['fields'].append(field)
    return out


def dump(engine, class_or_root: str, instance_address: int | None = None, *, depth: int = 6,
         limit: int = 5000, use_cache=True, provenance=False) -> dict:
    """Ordered typed field list of one persisted object (see module docstring)."""
    target = None
    if instance_address is None:
        route = find_route(class_or_root)
        rec = record(engine, route, use_cache=use_cache, provenance=provenance)
    else:
        # the object's own save function runs inside its root's save, with the arguments the game
        # gives it there: run the root (cached) and return that object's part of the recording
        function = function_for_class(engine, class_or_root)
        route = find_route(root_for_function(function))
        rec = record(engine, route, use_cache=use_cache, provenance=provenance)
        target = next((c for c in rec.calls if c.function == function and c.obj == instance_address), None)
        if target is None:
            raise PersistError(f'{class_or_root} at {instance_address:#x}: the save of {route["key"]} did not write '
                               f'that object with function {function:#x}')
    an = Analysis(engine, rec)
    head = {
        'object': class_or_root, 'address': f'{rec.obj:#x}', 'class': rec.root_class,
        'save_function': f'{rec.function:#x}', 'status': rec.status, 'refusal': rec.refusal,
        'writes': len(rec.writes), 'bytes': sum(len(w.data) for w in rec.writes),
        'save_functions': len(an.by_fn), 'objects': len(rec.calls), 'instructions': rec.instructions,
        'seconds': round(rec.seconds, 3), 'files_read': rec.files_read,
        'streams': [{'item': _item_path(rec, s.item), 'tag': s.tag.hex(), 'version': s.version, 'bytes': s.size}
                    for s in rec.streams],
    }
    root = target or (rec.calls[0] if rec.calls else None)
    if target is not None:
        head.update({'address': f'{target.obj:#x}', 'class': rec.classes.get(target.id),
                     'save_function': f'{target.function:#x}', 'root': route['key']})
    if root is None:
        head['fields'] = []
        return head
    counter = [0]
    body = _node(engine, an, root, depth, limit, counter)
    head['fields'] = body['fields']
    head['fields_returned'] = counter[0]
    head['truncated'] = counter[0] >= limit
    return head


def _item_path(rec, item_id):
    parts = []
    while item_id is not None:
        it = rec.items[item_id]
        if it.name:
            parts.append(it.name)
        item_id = it.parent
    return '/'.join(reversed(parts))


def schema(engine, root: str, *, use_cache=True) -> dict:
    """Per save function of one root's run: fields in write order (see module docstring)."""
    route = find_route(root)
    rec = record(engine, route, use_cache=use_cache)
    an = Analysis(engine, rec)
    return _schema_of(an, rec, route)


def _schema_of(an, rec, route):
    fns = []
    for fn, calls in an.by_fn.items():
        classes = Counter(rec.classes.get(c.id) for c in calls)
        cls = classes.most_common(1)[0][0] if classes else None
        delta = None
        if an.engine is not None and cls and cls.split('::')[-1] in TABLE_OF_CLASS:
            for c in calls[:5]:
                if rec.classes.get(c.id) == cls:
                    delta = record_delta(an.engine, cls, c.obj)
                    if delta is not None:
                        break
        fields = []
        for n, key in enumerate(an.order[fn]):
            f = an.fields[fn][key]
            reps = f['count']
            entry = {'n': n, 'key': key_text(key), 'kind': 'value' if key[0] == 'w' else 'object',
                     'per_instance': [min(reps), max(reps)], 'instances': f['instances']}
            if key[0] == 'w':
                off, how = an.offset(fn, key)
                lab = _label(cls, off, key[3], delta)
                entry.update({'type': _type_of(key), 'site': f'{key[1]:#x}',
                              'helpers': [f'{h:#x}' for h in key[2]],
                              'offset': _fmt_offset(off), 'offset_source': how,
                              'name': lab[0] if lab else f'field_{n}',
                              'label_source': lab[1] if lab else None})
            else:
                child = Counter({k: v for k, v in f['classes'].items()})
                ccls = child.most_common(1)[0][0] if child else None
                entry.update({'function': f'{key[1]:#x}', 'site': f'{key[2]:#x}', 'element_class': ccls,
                              'name': ccls.split('::')[-1].lower() if ccls else f'field_{n}',
                              'label_source': 'rtti' if ccls else None,
                              'container': max(reps) > 1})
            fields.append(entry)
        if not fields:
            continue        # entered with the recorder in x1/x2 but wrote nothing (not a save function)
        fns.append({'function': f'{fn:#x}', 'class': cls, 'instances': len(calls), 'record_delta': delta,
                    'classes': {str(k): v for k, v in classes.items()}, 'fields': fields})
    fns.sort(key=lambda d: -d['instances'])
    return {'root': route['key'] if route else rec.key, 'root_class': rec.root_class, 'status': rec.status,
            'refusal': rec.refusal, 'writes': len(rec.writes), 'bytes': sum(len(w.data) for w in rec.writes),
            'seconds': round(rec.seconds, 3), 'instructions': rec.instructions, 'files_read': rec.files_read,
            'functions': fns}


_SHIPPED_OFFSETS = None


def shipped_offset(fn: int, key) -> tuple | None:
    """(offset text, source) the schema build proved for this field (provenance run), if any."""
    global _SHIPPED_OFFSETS
    if _SHIPPED_OFFSETS is None:
        idx = {}
        for root in load_schema().get('roots', []):
            for f in root.get('functions', []):
                for x in f.get('fields', []):
                    if x.get('offset') and x.get('key'):
                        idx.setdefault((f['function'], x['key']), (x['offset'], x.get('offset_source')))
        _SHIPPED_OFFSETS = idx
    return _SHIPPED_OFFSETS.get((f'{fn:#x}', key_text(key)))


def root_for_function(function: int) -> str:
    """The save root whose run (shipped schema) called `function` most often."""
    best, n = None, 0
    for root in load_schema().get('roots', []):
        for f in root.get('functions', []):
            if f['function'] == f'{function:#x}' and f.get('instances', 0) > n:
                best, n = root['root'], f['instances']
    if best is None:
        raise PersistError(f'no save root calls {function:#x}')
    return best


def function_for_class(engine, class_name: str) -> int:
    """The save function the shipped schema (data/persist_schema.json.gz) names for a class."""
    data = load_schema()
    want = class_name.strip()
    hits = Counter()
    for root in data.get('roots', []):
        for f in root.get('functions', []):
            if f.get('class') and (f['class'] == want or f['class'].split('::')[-1] == want):
                hits[f['function']] += f.get('instances', 1)
    if not hits:
        raise PersistError(f'no save function known for class {class_name!r} (fm_native_schema lists classes)')
    return int(hits.most_common(1)[0][0], 16)


_SCHEMA = None


def load_schema() -> dict:
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = json.loads(gzip.decompress(SCHEMA_FILE.read_bytes())) if SCHEMA_FILE.is_file() else {'roots': []}
    return _SCHEMA
