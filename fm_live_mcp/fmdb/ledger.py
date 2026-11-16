"""Completeness ledger: what fraction of the game's data the reader can read, against the game's own inventories.

Six denominators, each derived mechanically from shipped files or the live process:

* ``editor``     every (record type, field code) of the shipped editor schema (`catalog.py`, list-item
                 fields included); status from the getter census (`seed/coverage.json`) and the snapshot
                 contract table ``_fields`` (opened read-only);
* ``getter_extra`` every getter key outside the schema (`extras.py`, 1,896 (type, key) pairs); status
                 from the extras census and ``_fields``;
* ``ui``         every FourCC the front end's property registry labels (`ui_registry`, 7,720 keys), with
                 the handler classes whose get_property materialises it; status from the UI sweep
                 (`scripts/fmdb_ui_sweep.py`, `out/fmdb-ui-sweep/types/*.json`);
* ``native``     every class typeinfo in the plugin (RTTI scanned here from the on-disk slice), with its
                 parents, kind (manager/system, database table, record, news item, UI handler, behaviour,
                 other) and the live roots that hold instances (plugin __DATA words pointing at, or holding,
                 an object whose vptr is the class's primary vtable);
* ``persisted``  every class the persistence layer can create by name (`sicore::CLASS_INFO_TEMPLATE<T>`)
                 or that derives from `sicore::PERSISTENT`: what the game writes to a save beyond the
                 database tables and managers;
* ``tools``      the hand-built tools: every oracle-mapped output field (`oracle_map.ENTRIES`), the
                 tool-only fields (`UNMAPPED`) and every registered tool.

Statuses: ``reads`` (a route returns values), ``unset_on_samples`` (the route runs and every sampled
record or binding is unset), ``needs_parameter`` (the route asks for a screen parameter or binding the
sweep did not supply), ``unavailable`` (the route fails; ``reason`` says why), ``unreached`` (no reader
reaches it). Routes: ``direct`` (verified read plan), ``emulated`` (record getter), ``extra`` (getter key
outside the schema), ``ui`` (UI handler key; ``surfaces`` names recipes), ``hand_built`` (an existing
tool's decoder), ``none``.

Reach of a native class by a hand-built tool is established by name or address: the class name, its
vtable or typeinfo RVA, or the RVA of the global that holds it appears in reader source. That is evidence
of reach, not proof of decoding; the entry's ``reason`` says which.

Nothing here writes to the game. The live part reads plugin data segments and one word per candidate
pointer.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import gzip
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time

DATA_DIR = Path(__file__).with_name('data')
CURRENT = DATA_DIR / 'ledger.json.gz'
BEFORE = DATA_DIR / 'ledger-before.json.gz'
PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parent
SWEEP_DIR = REPO / 'out' / 'fmdb-ui-sweep'

# ``empty_in_save`` (editor rows): a full scan asked every record of the type through the getter and none holds
# a value (`editor_live.py`): reachable, and this save has no data for it; distinct from ``unset_on_samples``.
STATUSES = ('reads', 'unset_on_samples', 'empty_in_save', 'needs_parameter', 'unavailable', 'unreached')
DENOMINATORS = {
    'editor': 'editor schema (record type, field), list items included',
    'getter_extra': 'record-getter keys outside the editor schema',
    'ui': 'front-end property registry keys (what the game can show a manager)',
    'native': 'plugin classes by RTTI (state classes: managers, tables, records, news items, persisted)',
    'persisted': 'classes the save layer creates by name or that derive from sicore::PERSISTENT',
    'tools': 'hand-built tools: oracle-mapped fields, tool-only fields and registered tools',
}
COLUMNS = ('denom', 'key', 'domain', 'name', 'label', 'label_source', 'route', 'status', 'reason', 'surfaces',
           'weight', 'extra', 'availability', 'cost_class', 'cost')
# Where a readable value lives and what keeping it readable costs.
#   snapshot_direct    in the snapshot, written at build by a verified direct plan (eager, microseconds a cell)
#   snapshot_emulated  in the snapshot, written by emulating the getter at build or by the background fill
#   on_demand          computed when asked: fm_db_read on one record, a UI handler, a recipe or a hand-built tool
#   none               does not read
AVAILABILITY = ('snapshot_direct', 'snapshot_emulated', 'on_demand', 'none')
COST_CLASSES = ('direct_plan', 'emulated_getter', 'ui_handler', 'hand_built_tool', 'static')

# ---------------------------------------------------------------------------------------------- domains
DOMAINS = (
    ('transfers and contracts', r'TRANSFER|\bBID|OFFER|NEGOTIA|ASKING|LOAN|CONTRACT|AGENT|INTERMEDIAR|CLAUSE|WAGE|'
                                r'SALARY|RELEASE_FEE|BUY_?IN|SELL_ON|SIGN'),
    ('scouting and knowledge', r'SCOUT|RECRUIT|SHORTLIST|ASSESS|KNOWLEDGE|FOG_OF_WAR|RECOMMEND|DATA_HUB|ANALYS|'
                               r'SEARCH|REPORT'),
    ('squad, morale and dynamics', r'HAPPINESS|MORALE|CONCERN|PROMISE|DYNAMIC|SOCIAL|HIERARCHY|RELATIONSHIP|'
                                   r'INFLUENCE|FAVOURED|PERSONALITY|MOOD|INTERACTION|TEAM_TALK|CHEMISTRY|SQUAD|'
                                   r'MENTOR|BLEND|PIVOTAL|AWOL|DISPUTE|FINE\b|CODE_OF_CONDUCT'),
    ('training and medical', r'TRAINING|WORKLOAD|DEVELOPMENT|INDIVIDUAL_FOCUS|PROGRESSION|INJUR|MEDICAL|FITNESS|'
                             r'CONDITION|SHARPNESS|FATIGUE|CAMP'),
    ('tactics and matches', r'TACTIC|FORMATION|FAMILIAR|INSTRUCTION|\bROLE|SET_PIECE|OPPOSITION|MATCH|FIXTURE|'
                            r'LINEUP|SELECTION|PENALTY|CAPTAIN|SUBSTITUT|SIMATCH|PITCH'),
    ('board, club and finance', r'BOARD|CONFIDENCE|VISION|JOB_SECURITY|OBJECTIVE|EXPECTATION|FINANC|BUDGET|INCOME|'
                                r'EXPENDITURE|SPONSOR|REVENUE|DEBT|FFP|FAIR_PLAY|TAKEOVER|STADIUM|FACILIT|FEEDER|'
                                r'AFFILIAT|ATTENDANCE|TICKET|MERCHANDIS|FAN_|SUPPORTER'),
    ('youth, staff and career', r'YOUTH|INTAKE|NEWGEN|REGEN|ACADEMY|STAFF|JOB_CENTRE|BACKROOM|HUMAN|MANAGER_PROFILE|'
                                r'CAREER|REPUTATION|RETIRE|COACH|JOB\b|INTERVIEW_FOR'),
    ('news, press and media', r'NEWS|INBOX|MESSAGE|PRESS|MEDIA|JOURNALIST|INTERVIEW|CONFERENCE|RUMOUR|NARRATIVE|'
                              r'SPEAK|SOCIAL_FEED'),
    ('competitions and calendar', r'COMP|STAGE|CALENDAR|DIARY|LEAGUE|\bCUP|STANDING|RULE_GROUP|FRIENDLY|SCHEDULE|'
                                  r'SEASON|TV_|DRAW|SEEDING|FIFA_RANKING|CONTINENTAL'),
    ('history, stats and awards', r'HISTORY|AWARD|ACHIEVEMENT|HALL_OF_FAME|TROPHY|MEDAL|STAT|RATING|PERFORMANCE|'
                                  r'GOALS|APPEARANCE|CAPS\b|RECORDS?\b'),
    ('people and world database', r'PERSON|PLAYER|NATION|CITY|CONTINENT|REGION|LANGUAGE|CURRENCY|WEATHER|CLUB|TEAM|'
                                  r'DATABASE|OFFICIAL|NAME|BIRTH|ATTRIBUTE|ABILITY|POSITION|HEIGHT|WEIGHT|FOOT'),
)
_DOMAIN_RX = [(name, re.compile(rx)) for name, rx in DOMAINS]
ENGINE = 'engine and front end'
DOMAIN_NAMES = tuple(n for n, _ in DOMAINS) + (ENGINE,)
# Value to a manager, for ranking gaps (engine plumbing ranks nothing).
DOMAIN_VALUE = {
    'transfers and contracts': 10, 'scouting and knowledge': 10, 'squad, morale and dynamics': 9,
    'training and medical': 8, 'tactics and matches': 8, 'board, club and finance': 8,
    'youth, staff and career': 7, 'competitions and calendar': 6, 'history, stats and awards': 6,
    'news, press and media': 5, 'people and world database': 5, ENGINE: 0,
}
RECORD_DOMAIN = {
    'CntF': 'transfers and contracts', 'agen': 'transfers and contracts', 'agrm': 'transfers and contracts',
    'club': 'board, club and finance', 'c2tm': 'board, club and finance', 'c3tm': 'board, club and finance',
    'c4tm': 'board, club and finance', 'stad': 'board, club and finance', 'team': 'tactics and matches',
    'comp': 'competitions and calendar', 'stgn': 'competitions and calendar', 'drbr': 'competitions and calendar',
    'awar': 'history, stats and awards', 'inju': 'training and medical', 'mdso': 'news, press and media',
    'jour': 'news, press and media', 'nnpl': 'youth, staff and career',
}
ENGINE_NAMESPACES = ('icu_', 'CryptoPP', 'std::', 'sianim', 'sicrypt', 'sinetwork', 'simultiplayer', 'sidistribution',
                     'siapplication', 'sixml', 'sicore', 'boost', 'google', 'sitranslation', 'fmdate', 'siuihandler',
                     'sigfx', 'siaudio', 'sirender', 'siinput', 'simigration', 'game_simulation_audit', 'zstd',
                     'game_plugin__', 'sicore__', '(anonymous', 'lua', 'Json', 'nlohmann', 'sqlite', 'ssl', 'crypto')


def domain_of(*texts, record_type=None) -> str:
    for text in texts:
        if not text:
            continue
        up = re.sub(r'[^A-Z0-9:]+', '_', str(text).upper())
        for name, rx in _DOMAIN_RX:
            if rx.search(up):
                return name
    if record_type in RECORD_DOMAIN:
        return RECORD_DOMAIN[record_type]
    if record_type:
        return 'people and world database'
    return ENGINE


def class_domain(name: str) -> str:
    if name.startswith(ENGINE_NAMESPACES) or re.match(r'^[a-z]', name) and '::' not in name:
        return ENGINE
    short = name.split('::')[-1] if not name.startswith(('db::', 'sicomps::', 'simatch')) else name
    return domain_of(short, name)


# ---------------------------------------------------------------------------------------------- RTTI
TYPEINFO_KINDS = {
    '__ZTVN10__cxxabiv117__class_type_infoE': 'class',
    '__ZTVN10__cxxabiv120__si_class_type_infoE': 'si',
    '__ZTVN10__cxxabiv121__vmi_class_type_infoE': 'vmi',
}
_MANGLED = re.compile(r'^(?:N(?:K)?)?(?:St)?(?:\d+[A-Za-z_][A-Za-z0-9_]*)+(?:I.*E)?E?$')


def _demangle(names: list[str]) -> list[str]:
    tool = shutil.which('c++filt')
    if tool and names:
        out = subprocess.run([tool, '-t'], input='\n'.join(names), capture_output=True, text=True).stdout.splitlines()
        if len(out) == len(names):
            return out
    return [_mini_demangle(n) for n in names]


def _mini_demangle(m: str) -> str:
    """Nested names without templates ('N2db9NEWS_ITEME' -> 'db::NEWS_ITEM'); anything else stays mangled."""
    s = m[1:-1] if m.startswith('N') and m.endswith('E') else m
    parts, i = [], 0
    while i < len(s):
        j = i
        while j < len(s) and s[j].isdigit():
            j += 1
        if j == i:
            return m
        n = int(s[i:j])
        parts.append(s[j:j + n])
        i = j + n
    return '::'.join(parts) if parts else m


def rtti_inventory(image) -> dict:
    """{type name: {ti, vt, kind, parents, mangled}} for every class typeinfo in the on-disk plugin slice."""
    words = {}
    for segname in ('__DATA_CONST', '__DATA'):
        try:
            seg = image.segment(segname)
        except Exception:  # noqa: BLE001
            continue
        raw = image.file_bytes(seg.vmaddr, seg.filesize)
        for i, (v,) in enumerate(struct.iter_unpack('<Q', raw[:len(raw) // 8 * 8])):
            if v:
                words[seg.vmaddr + 8 * i] = v

    def target(addr):
        if addr in image.binds:
            return None
        v = words.get(addr)
        if v is None or v >> 63:
            return None
        return (v & 0xFFFFFFFFF) | (((v >> 36) & 0xFF) << 56)

    tis = {}
    for rva, sym in image.binds.items():
        kind = TYPEINFO_KINDS.get(sym)
        if kind:
            name_rva = target(rva + 8)
            if name_rva is None:
                continue
            try:
                raw = image.file_bytes(name_rva, 512).split(b'\0', 1)[0].decode('latin-1')
            except Exception:  # noqa: BLE001
                continue
            if raw and _MANGLED.match(raw):
                tis[rva] = (kind, raw)
    rvas = sorted(tis)
    demangled = _demangle([tis[r][1] for r in rvas])
    by_ti = {r: d for r, d in zip(rvas, demangled)}
    refs = defaultdict(list)
    for addr, v in words.items():
        if not v >> 63:
            t = v & 0xFFFFFFFFF
            if t in by_ti:
                refs[t].append(addr)
    out = {}
    for r in rvas:
        kind, mangled = tis[r]
        name = by_ti[r]
        vt = None
        for ref in refs.get(r, ()):
            if ref - 8 in words or (ref - 8) in image.binds:
                continue          # offset-to-top must be 0 for the primary vtable
            if ref - 8 >= 0:
                vt = ref + 8
                break
        parents = []
        if kind == 'si':
            p = target(r + 16)
            if p in by_ti:
                parents = [by_ti[p]]
        elif kind == 'vmi':
            flags, count = struct.unpack('<II', image.file_bytes(r + 16, 8))
            if 0 < count < 64:
                for i in range(count):
                    p = target(r + 24 + 16 * i)
                    if p in by_ti:
                        parents.append(by_ti[p])
        if name in out:          # duplicate typeinfo (weak copies): keep the one with a vtable
            if out[name]['vt'] or not vt:
                continue
        out[name] = {'ti': r, 'vt': vt, 'kind': kind, 'parents': parents, 'mangled': mangled}
    return out


def ancestors(rtti: dict, name: str, _depth=0) -> list:
    out = []
    for p in rtti.get(name, {}).get('parents', ()):
        out.append(p)
        if _depth < 24:
            out += ancestors(rtti, p, _depth + 1)
    return out


BEHAVIOUR = re.compile(r'(_RULE|_FORMATTER|_ACTION|_SUGGESTION|FILTER\w*|_HELPER|_TRIGGER|RESPONSE\w*|_LISTENER|'
                       r'_BUILDER|_EVENT_HANDLER|_PROVIDER|_COMPARATOR|_SORTER|_VALIDATOR|_FACTORY|_VISITOR|'
                       r'_CALLBACK|_PREDICATE|_TASK|_JOB|_EXPORTER|_GENERATOR|_DELEGATE|_FUNCTOR|_WRAPPER|_POLICY|'
                       r'_COMMENT\w*|_DESCRIPTION|_TRANSLATABLE|_RESOLVER|_CALCULATOR|_CHECKER|_PROCESSOR)(<.*>)?$')


def class_kind(name: str, anc: list) -> str:
    base = set(anc)
    short = re.sub(r'<.*>$', '', name)
    if re.search(r'_MANAGER$|_SYSTEM$', short) and not base & {'INTERACTION_COMMENT_RULE'}:
        return 'manager'
    if 'db::DATABASE_TABLE_BASE' in base or short.startswith('db::DATABASE_TABLE'):
        return 'table'
    if 'siuihandler::UI_HANDLER' in base or 'siuihandler::UI_HANDLER_SERVER' in base:
        return 'ui_handler'
    if any(a.startswith('db::EXTERN_') for a in anc[:1]):
        return 'extern_service'     # the game layer's implementation of a db::EXTERN_* interface (one object)
    if 'db::NEWS_ITEM' in base or short == 'db::NEWS_ITEM':
        return 'news_item'
    if 'db::DATABASE_RECORD' in base or 'sicore::RECORD' in base:
        return 'record'
    if 'sicore::PERSISTENT' in base and not BEHAVIOUR.search(short):
        return 'persisted'
    if BEHAVIOUR.search(short) or 'sitranslation::FORMATTER' in base or 'ACTION_BASE' in base or \
            'INTERACTION_COMMENT_RULE' in base:
        return 'behaviour'
    return 'other'


STATE_KINDS = ('manager', 'table', 'record', 'news_item', 'persisted')


# ---------------------------------------------------------------------------------------------- live roots
def live_roots(engine, image, rtti: dict, *, max_pointers=2_000_000) -> dict:
    """{class: [(data rva, 'static'|'pointer'), ...]} from the plugin's mutable data in the live process.

    A word in __DATA (__data/__bss/__common) that equals base + a primary vtable address point is a static
    instance; a word that points outside the image at an object whose first word is such a vtable is a
    pointer root. One read of the data segment, then one 8-byte read per distinct candidate pointer."""
    base = engine.base
    image_end = max(s.vmaddr + s.vmsize for s in image.segments)
    vt_to_class = {base + info['vt']: name for name, info in rtti.items() if info.get('vt')}
    seg = image.segment('__DATA')
    ranges = [(addr, size) for sect, (addr, size, _) in seg.sections.items()
              if sect in ('__data', '__bss', '__common')]
    roots = defaultdict(list)
    candidates = {}
    for addr, size in ranges:
        for off in range(0, size, 8 << 20):
            n = min(8 << 20, size - off)
            raw = engine.memory.read_many([(base + addr + off, n)])[0]
            if raw is None:
                continue
            for i, (v,) in enumerate(struct.iter_unpack('<Q', raw[:len(raw) // 8 * 8])):
                rva = addr + off + 8 * i
                if v in vt_to_class:
                    roots[vt_to_class[v]].append((rva, 'static'))
                elif 0x100000000 <= v < 0x800000000000 and not (base <= v < base + image_end) and not v & 7:
                    if len(candidates) < max_pointers:
                        candidates.setdefault(v, []).append(rva)
    targets = sorted(candidates)
    for i in range(0, len(targets), 200_000):
        chunk = targets[i:i + 200_000]
        for t, raw in zip(chunk, engine.memory.read_many([(t, 8) for t in chunk])):
            if raw and len(raw) == 8:
                cls = vt_to_class.get(struct.unpack('<Q', raw)[0])
                if cls:
                    for rva in candidates[t]:
                        roots[cls].append((rva, 'pointer'))
    return {k: sorted(set(v))[:8] for k, v in roots.items()}


# ---------------------------------------------------------------------------------------------- save walk
def function_starts(image) -> list:
    """Function start RVAs from LC_FUNCTION_STARTS of the on-disk slice."""
    d, off = image._map, image.slice_offset
    ncmds = struct.unpack_from('<I', d, off + 16)[0]
    cur, found = off + 32, None
    for _ in range(ncmds):
        cmd, size = struct.unpack_from('<II', d, cur)
        if cmd == 0x26:
            found = struct.unpack_from('<II', d, cur + 8)
        cur += size
    if not found:
        return []
    data = d[off + found[0]: off + found[0] + found[1]]
    starts, addr, i = [], 0, 0
    while i < len(data):
        value = shift = 0
        while True:
            c = data[i]
            i += 1
            value |= (c & 0x7F) << shift
            shift += 7
            if c < 0x80:
                break
        if value == 0:
            break
        addr += value
        starts.append(addr)
    return starts


def scan_function(image, start: int, end: int) -> tuple[set, set]:
    """(BL targets, ADRP+LDR/ADD global addresses) of one function's code."""
    raw = image.file_bytes(start, end - start)
    words = struct.unpack(f'<{len(raw) // 4}I', raw[:len(raw) // 4 * 4])
    calls, loads = set(), set()
    for i, w in enumerate(words):
        pc = start + 4 * i
        if w & 0xFC000000 == 0x94000000:
            imm = w & 0x3FFFFFF
            calls.add(pc + ((imm - 0x4000000) if imm & 0x2000000 else imm) * 4)
        elif w & 0x9F000000 == 0x90000000:
            rd = w & 31
            imm = (((w >> 5) & 0x7FFFF) << 2) | ((w >> 29) & 3)
            if imm & (1 << 20):
                imm -= 1 << 21
            page = (pc & ~0xFFF) + (imm << 12)
            for v in words[i + 1:i + 4]:
                if (v >> 5) & 31 != rd:
                    continue
                if v & 0xFFC00000 == 0xF9400000:
                    loads.add(page + ((v >> 10) & 0xFFF) * 8)
                    break
                if v & 0xFF800000 == 0x91000000:
                    loads.add(page + ((v >> 10) & 0xFFF))
                    break
    return calls, loads


def save_walk(image, rtti, roots, *, min_managers=10) -> dict:
    """Managers walked by SAVE_SYSTEM's virtual functions: each slot function's direct callees that load the
    global roots of at least `min_managers` manager singletons are the walkers; their union is the list."""
    info = rtti.get('SAVE_SYSTEM') or {}
    if not info.get('vt') or not roots:
        return {}
    starts = function_starts(image)
    import bisect

    def bounds(fn):
        k = bisect.bisect_right(starts, fn) - 1
        return (starts[k], starts[k + 1]) if 0 <= k < len(starts) - 1 else (fn, fn + 0x4000)

    by_root = {}
    for cls, rs in roots.items():
        if class_kind(cls, ancestors(rtti, cls)) in ('manager', 'table'):
            for rva, _ in rs:
                by_root[rva] = cls
    slots = []
    for k in range(64):
        raw = struct.unpack('<Q', image.file_bytes(info['vt'] + 8 * k, 8))[0]
        target = raw & 0xFFFFFFFFF
        if raw >> 63 or not image.is_code(target):
            break
        slots.append(target)
    walkers, managers = {}, set()
    for slot in slots:
        calls, _ = scan_function(image, *bounds(slot))
        for fn in sorted(calls):
            if not image.is_code(fn):
                continue
            _, loads = scan_function(image, *bounds(fn))
            hit = {by_root[a] for a in loads if a in by_root}
            if len(hit) >= min_managers:
                walkers[hex(fn)] = {'from_slot_function': hex(slot), 'managers': len(hit)}
                managers |= hit
    return {'vtable': hex(info['vt']), 'slots': [hex(x) for x in slots], 'walkers': walkers,
            'managers': sorted(managers)}


# ---------------------------------------------------------------------------------------------- source scan
def source_tokens(paths=None) -> tuple[dict, dict]:
    """Class-like identifiers and integer constants in the reader sources' code -> modules that use them.

    Parsed with `ast`: names, attributes, string constants and integers count; comments and docstrings do not,
    so a class mentioned only in prose is not counted as reached."""
    import ast
    names, ints = defaultdict(set), defaultdict(set)
    skip = {'ledger.py', 'ledger_tools.py', 'labels.py'}
    word = re.compile(r'\b[A-Z][A-Z0-9_]{3,}\b')
    for p in paths or sorted(PACKAGE.rglob('*.py')):
        if p.name in skip:
            continue
        try:
            tree = ast.parse(p.read_text(errors='replace'))
        except (OSError, SyntaxError, ValueError):
            continue
        mod = str(p.relative_to(PACKAGE)).removesuffix('.py').replace('/', '.')
        docs = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    docs.add(id(first.value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant):
                if id(node) in docs:
                    continue
                v = node.value
                if isinstance(v, int) and not isinstance(v, bool) and 0x10000 <= v < 0x8000000:
                    ints[v].add(mod)
                elif isinstance(v, (str, bytes)):
                    text = v.decode('latin-1') if isinstance(v, bytes) else v
                    for tok in set(word.findall(text)):
                        names[tok].add(mod)
            elif isinstance(node, ast.Name) and word.fullmatch(node.id):
                names[node.id].add(mod)
            elif isinstance(node, ast.Attribute) and word.fullmatch(node.attr):
                names[node.attr].add(mod)
    return names, ints


# ---------------------------------------------------------------------------------------------- inputs
def _load_json(path):
    path = Path(path)
    if not path.exists():
        return None
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt') as handle:
        return json.load(handle)


def snapshot_fields(path) -> dict:
    """{(record_type, code): (table, column, source, status, note)} from a snapshot's `_fields` (read-only)."""
    import sqlite3
    out = {}
    if not path or not Path(path).exists():
        return out
    con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        for row in con.execute('select table_name, column_name, code, record_type, source, status, note '
                               'from _fields where code is not null'):
            table, column, code, rtype, source, status, note = row
            out.setdefault((rtype, code), (table, column, source, status, note or ''))
    finally:
        con.close()
    return out


def sweep_results(path=SWEEP_DIR) -> list:
    path = Path(path)
    merged = _load_json(path / 'sweep.json')
    if merged and merged.get('types'):
        return merged['types']
    return [json.loads(f.read_text()) for f in sorted((path / 'types').glob('*.json'))]


def default_snapshot() -> Path | None:
    from .engine import DEFAULT_CACHE
    root = DEFAULT_CACHE / 'fmdb'
    best = None
    for p in root.glob('*/snapshot.sqlite'):
        if best is None or p.stat().st_mtime > best.stat().st_mtime:
            best = p
    return best


# ---------------------------------------------------------------------------------------------- builders
def _row(denom, key, domain, name, label=None, label_source=None, route='none', status='unreached', reason='',
         surfaces=(), weight=1.0, extra=None):
    return [denom, key, domain, name, label, label_source, route, status, reason,
            ', '.join(sorted(set(surfaces))) if surfaces else '', round(weight, 2), extra or {}, 'none', None, None]


def _coverage_status(counts: dict) -> tuple[str, str]:
    """Census counts -> status: any value reads; otherwise the most common outcome of the sampled records."""
    if counts.get('value'):
        return 'reads', ''
    outcomes = {'unset': counts.get('unset', 0), 'unavailable': counts.get('unavailable', 0),
                'not_handled': counts.get('not_handled', 0)}
    top = max(outcomes, key=lambda k: (outcomes[k], k == 'unset'))
    if not outcomes[top]:
        return 'unreached', 'not in the getter census'
    if top == 'unset':
        return 'unset_on_samples', f"unset on every sampled record ({outcomes['unset']})"
    if top == 'unavailable':
        return 'unavailable', 'the getter failed on the sampled records'
    return 'unreached', 'the record getter does not claim the key'


def oracle_codes(oracle_map) -> dict:
    """{(record type, code): {tool call, ...}} for the hand-built tool fields the oracle maps to editor codes."""
    out = defaultdict(set)
    for e in oracle_map.ENTRIES:
        for code in e.codes:
            out[(e.rtype, code)].add(tool_of(oracle_map, e.call))
    return out


def tool_of(oracle_map, call_key: str) -> str:
    call = oracle_map.CALLS.get(call_key)
    method = (call.method if call else call_key).split(':')[-1]
    return method if method.startswith('fm_') else f'fm_{method}'


def _editor_live(key, rtype, code, path, status, route, reason, surfaces, name=None, ftype=None):
    """Overlay the targeted full scan (`editor_live.py`) and the field-route evidence (`fieldroutes.py`) on a
    row the 25-record census left without a value."""
    from . import editor_live, fieldroutes
    r = fieldroutes.route(rtype, code) if not path else None
    if r is not None and r.kind == 'via_club':
        col = editor_live.VIA_CLUB_COLUMNS.get(r.key)
        return 'reads', 'emulated', f'through the club: {r.note}', list(surfaces) + ([col] if col else [])
    if ftype in editor_live.CONTROL_TYPES:
        reason = (f'editor control (type {ftype}): an action button or display widget of the in-game editor, '
                  f'not a stored value; ' + reason)
    decided = editor_live.decide(editor_live.embedded_key(key, name))
    if decided is not None:
        new, why = decided
        if new == 'reads':
            via = editor_live.surfaces_for(rtype, code)
            return 'reads', ('direct' if rtype in ('recs', 'lsts') else 'emulated'), why, \
                list(surfaces) + via

        if new in ('empty_in_save', 'unavailable') or status == 'unreached':
            status, reason = new, why
    if status in ('unreached', 'unavailable') and not path:
        proof = fieldroutes.reason(rtype, code)
        if proof and proof not in reason:
            reason = f'{reason}; {proof}' if reason else proof
    return status, route, reason[:400], surfaces


def build_editor(cat, coverage, fields, label_for, oracle=None) -> list:
    rows = []
    per_type = (coverage or {}).get('record_types', {})
    for scope in cat.iter_fields():
        rtype, f = scope.record_type, scope.field
        path = '.'.join(scope.path)
        key = f'{rtype}.{path + "." if path else ""}{f.code}'
        label, src = (f.name, 'editor') if f.name else label_for(rtype, f.code)
        domain = domain_of(label, f.category, record_type=rtype)
        extra = {'type': f.type}
        if f.type in ('enum', 'multiple_enum'):
            labels = f.enum or (cat.enums.get(f.enum_ref) if f.enum_ref else None)
            extra['enum_labels'] = bool(labels)
            if not labels:
                extra['enum_ref'] = f.enum_ref
        snap = fields.get((rtype, f.code)) if not scope.path else None
        pf = per_type.get(rtype, {}).get('per_field', {}).get(f.code) if not scope.path else None
        surfaces, route, status, reason = [], 'none', 'unreached', ''
        if scope.path:
            parent = fields.get((rtype, scope.path[0]))
            ppf = per_type.get(rtype, {}).get('per_field', {}).get(scope.path[0])
            route = 'emulated'
            if ppf:
                status, reason = _coverage_status(ppf.get('counts') or {})
                if ppf.get('unavailable_reasons') and status == 'unavailable':
                    reason = '; '.join(f'{k} ({v})' for k, v in ppf['unavailable_reasons'].items())
                reason = f'item of list {scope.path[0]}: ' + (reason or 'the getter returns the list')
                surfaces = ['fm_db_read']
            elif parent and parent[3] in ('ready', 'partial'):
                route, status = parent[2], 'reads'
                reason = f'item of list {scope.path[0]} (snapshot column {parent[0]}.{parent[1]})'
                surfaces = [f'snapshot:{parent[0]}.{parent[1]}', 'fm_db_read']
            else:
                status = 'unreached'
                reason = f'item of list {scope.path[0]}, which no census or snapshot column reads'
        elif rtype not in per_type and snap is None:
            reason = 'record type has no live table' if rtype in ('prnm', 'ktfl', 'alnm', 'dbch', 'lsts', 'fmat') \
                else 'record type not enumerated'
        else:
            if pf:
                status, reason = _coverage_status(pf.get('counts') or {})
                route = 'emulated'
                if pf.get('unavailable_reasons') and status == 'unavailable':
                    reason = '; '.join(f'{k} ({v})' for k, v in pf['unavailable_reasons'].items())
            if snap:
                table, column, source, sstatus, note = snap
                route = 'direct' if source == 'direct' else ('extra' if source == 'extra' else
                                                             'emulated' if source == 'emulated' else source)
                surfaces = [f'snapshot:{table}.{column}', 'fm_db_query', 'fm_db_read']
                if sstatus in ('ready', 'partial') and status in ('unreached', 'unset_on_samples', 'reads'):
                    if status == 'unreached':
                        status, reason = 'reads', f'snapshot {sstatus}'
                elif sstatus == 'unavailable' and not pf:
                    status, reason = 'unavailable', (note or reason)[:240]
                extra['snapshot'] = sstatus
            elif status == 'reads':
                surfaces = ['fm_db_read']
        if status != 'reads':
            status, route, reason, surfaces = _editor_live(key, rtype, f.code, scope.path, status, route, reason,
                                                           surfaces, f.name, f.type)
        tools_for = (oracle or {}).get((rtype, f.code)) if not scope.path else None
        if tools_for:
            surfaces = list(surfaces) + sorted(tools_for)
            if status != 'reads':
                route, status = 'hand_built', 'reads'
                reason = f'read by a hand-built tool (oracle-mapped); generic route: {reason or status}'
        if f.type in ('enum', 'multiple_enum') and status == 'reads' and not extra.get('enum_labels'):
            reason = (reason + '; ' if reason else '') + 'enum label set missing (raw codes only)'
        rows.append(_row('editor', key, domain, f.name or f.code, label, src, route, status, reason, surfaces,
                         extra=extra))
    return rows


def build_extras(extras_mod, fields, label_for) -> list:
    rows = []
    for rtype, codes in extras_mod.EXTRA_FIELDS.items():
        for code, info in codes.items():
            label, src = label_for(rtype, code)
            if info.get('records_with_value'):
                status, reason = 'reads', ''
            else:
                status, reason = 'unset_on_samples', f"unset on {info.get('records_sampled', 0)} sampled records"
            snap = fields.get((rtype, code))
            surfaces = ['fm_db_read']
            if snap:
                surfaces.append(f'snapshot:{snap[0]}.{snap[1]}')
                if snap[3] == 'unavailable':
                    status, reason = 'unavailable', snap[4][:240]
            rows.append(_row('getter_extra', f'{rtype}.{code}', domain_of(label, record_type=rtype), code, label, src,
                             'extra', status, reason, surfaces, weight=0.5))
    return rows


def _recipe_literals() -> dict:
    out = defaultdict(set)
    for p in sorted(PACKAGE.glob('fmdb/ui_recipes*.py')) + [PACKAGE / 'fmdb' / 'ui_handlers.py']:
        if not p.exists():
            continue
        text = p.read_text(errors='replace')
        for tok in set(re.findall(r"'([^'\\]{4})'", text)):
            out[tok].add(p.stem)
    return out


def _ui_round2_data() -> dict:
    """Static facts of the UI round 2 (docs/fmdb/UI_ROUND2.md): `compiled_out` {code: [case address]}."""
    path = PACKAGE / 'fmdb' / 'data' / 'ui_round2.json.gz'
    try:
        with gzip.open(path, 'rt') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def build_ui(reg, sweep) -> tuple[list, dict]:
    """One row per registry key; plus per-class results for the native denominator."""
    owners = defaultdict(set)
    for cname, hc in reg.classes.items():
        try:
            for code in hc.keys(4):
                owners[code].add(cname)
        except Exception:  # noqa: BLE001
            continue
    best = {}
    nested = {}
    by_class = {}
    job_wall = {j.get('job'): j.get('wall_seconds') for j in sweep}
    rank = {'value': 0, 'unset': 1, 'unavailable': 2, 'skipped': 3}
    for job in sweep:
        cls = job.get('class')
        counts = job.get('counts') or {}
        info = {'job': job.get('job'), 'counts': counts, 'blocker': job.get('first_blocker'),
                'server': job.get('server'), 'built': not job.get('build_error') and not job.get('crashed')}
        for name in (cls, job.get('server')):
            if name and (name not in by_class or (counts.get('value', 0) > (by_class[name]['counts'] or {}).get('value', 0))):
                by_class[name] = info
        for code, row in (job.get('keys') or {}).items():
            st = row.get('status')
            cur = best.get(code)
            if cur is None or rank.get(st, 9) < rank.get(cur[0], 9):
                best[code] = (st, row, job.get('job'), cls)
        # Round 2 (UI_ROUND2.md): FourCCs found as fields of records inside returned values.
        for code, entry in (job.get('nested') or {}).items():
            if entry[1] == 'value' and code not in nested:
                nested[code] = (job.get('job'), entry[0], cls)
    recipes = _recipe_literals()
    compiled_out = _ui_round2_data().get('compiled_out') or {}
    rows = []
    for code, label in reg.labels.items():
        cls_set = sorted(owners.get(code, ()))
        hit = best.get(code)
        surfaces = []
        if hit:
            st, row, job, cls = hit
            surfaces.append(f'fm_ui_read({job})')
            ui_cost = {'ms': row.get('ms'), 'job_s': job_wall.get(job)}
            if st == 'value':
                status, reason = 'reads', ''
            elif st == 'unset':
                if row.get('params'):
                    status = 'needs_parameter'
                    reason = 'reads screen parameter ' + ','.join(row['params'])
                else:
                    status, reason = 'unset_on_samples', 'unset under every sweep binding'
            elif st == 'unavailable':
                status, reason = 'unavailable', (row.get('reason') or '')[:240]
            else:
                status, reason = 'unavailable', 'not read: the sweep time budget for the handler ran out'
            name = cls
        elif cls_set:
            status, reason, name = 'unreached', 'handler class not built by the sweep', cls_set[0]
        else:
            status, reason, name = 'unreached', 'no plugin handler class materialises the key (front-end only or ' \
                                                'read through another protocol)', ''
        if status != 'reads' and code in nested:
            njob, parent, ncls = nested[code]
            status = 'reads'
            reason = f'field of the records the handler returns for key {parent} ({njob})'
            surfaces.append(f'fm_ui_read({njob.split("@")[0]})')
            name = name or ncls
        elif status == 'unset_on_samples' and code in compiled_out:
            status = 'unavailable'
            reason = ('compiled out of the release build: the get_property case at '
                      f'{", ".join(compiled_out[code][:3])} returns true without a value (shared stub 0x8665c)')
        if code in recipes:
            surfaces += [f'recipe:{m}' for m in sorted(recipes[code])]
        extra_ui = {'classes': cls_set[:6]} if cls_set else {}
        if hit:
            extra_ui['cost'] = ui_cost
        rows.append(_row('ui', code, domain_of(name, label) if name else domain_of(label), name or '', label, 'ui_registry', 'ui', status, reason,
                         surfaces, weight=0.5 if (hit or cls_set) else 0.15,
                         extra=extra_ui or None))
    return rows, by_class


# Keys a shaped screen reads with arguments no sweep binding supplies: (surface, handler class, parent
# key, why the sweep left it empty, keys the parent's records carry that no other read reaches).
# The Data Hub analytics (docs/fmdb/UI_FRONTEND.md, "Data Hub analytics"; ui_recipes_analytics.py),
# read on the Newcastle career on 13 November 2026 (game build 27.0.1, game date 5 January 2031): the team
# charts, the player catalogue, one player's charts, a team's report charts and the match charts.
_ANALYTICS_CONTEXT = ('the server getter takes the manager (Hhum) and the team asking for the report (mCLv) as object '
                      'arguments in its context')
_MATCH_CONTEXT = (_ANALYTICS_CONTEXT + '; the fixture record comes from a row of the Data Hub\'s last-match list '
                  '(TEAM DataHubLastMatchFixtureDropdown)')
SCREEN_READS = (
    ('fm_get_ui_screen(team_analytics)', 'TEAM_UI_HANDLER', 'uvRT',
     'the server getter takes the manager (Hhum) and the team asking for the report (mCLv) as object arguments '
     'in its context; screen parameter boolean only chooses the voice of the sentences',
     ('0Zoa', 'vj3R', 'L9Nj', 'UO5Q', 'wjEU', 'UZlS', 'pyZE', 'tzwN', 'Ywr3', 'YYiF', 'mEuQ', '8DzB', 'bMU2', 'uQqV',
      'Ng8F', '0yQ1', 'lhOD', '9r2h')),
    ('fm_get_ui_screen(player_analytics)', 'TEAM_UI_HANDLER', 'fGjn',
     'the server getter takes the manager (Hhum) and the team asking for the report (mCLv) as object arguments '
     'in its context; screen parameters boolean (voice) and selectedtabindex (0 all, 1 goalkeepers, 2 defenders, '
     '3 midfielders, 4 attackers)', ()),
    ('fm_get_ui_screen(player_analytics)', 'TEAM_UI_HANDLER', 'FyDK',
     'the server getter takes the manager (Hhum), the team asking for the report (mCLv) and the flag isteamvisuals '
     "(1H7p) in its context; built on a person's record it lists that player's charts "
     '(fm_get_ui_screen(person_analytics))', ('0Hsw', 'V7CW')),
    ('fm_get_ui_screen(opposition_analytics)', 'TEAM_UI_HANDLER', 'rijN', _ANALYTICS_CONTEXT, ()),
    ('fm_get_ui_screen(match_analytics)', 'FIXTURE_UI_HANDLER', 'LtKt', _MATCH_CONTEXT,
     ('8Z0D', 'sGQr', 'ptF7', 'OOAY', 'QYJi', 'G0fw', 'cUjX', 'p2AO', 'fdnx', 't6GY', 'vj7G')),
    ('fm_get_ui_screen(match_analytics)', 'FIXTURE_UI_HANDLER', 'UIwU', _MATCH_CONTEXT, ()),
    ('fm_get_ui_screen(match_analytics)', 'FIXTURE_UI_HANDLER', 'EHW7', _MATCH_CONTEXT,
     ('CNml', 'CUMW', 'p1Jl', 'rGxm', 'ZlHu', 'rVJa', '0hle', 'opk6', 'Z7bb', 'opz8', 'SaFD', 'DByv', 'nzFE', '5hlo',
      '73kD', '5Ccq', 'uPa7', 'OhsO', 'lmAw', 'PVPp', 'YgFo', 'D0kb')),
    ('fm_get_ui_screen(match_analytics)', 'FIXTURE_UI_HANDLER', 'k3hM', _MATCH_CONTEXT, ()),
    ('fm_get_ui_screen(match_analytics)', 'FIXTURE_UI_HANDLER', 'MU5d', _MATCH_CONTEXT, ('dNtn', 'A3ba', 'RfAa')),
    ('fm_get_ui_screen(match_analytics)', 'FIXTURE_UI_HANDLER', 'FOjz', _MATCH_CONTEXT, ()),
    ('fm_get_ui_screen(match_analytics)', 'TEAM_UI_HANDLER', 'xlO9', _ANALYTICS_CONTEXT + '; screen parameter id',
     ('3yuv', 'IyAO', 'LYhR', 'P8zC', 'QDfL', 'XHsY', 'Xrh4', 'dNuQ', 'fCVY', 'mcut', 'mmti', 'oge8', 'scor', 'scos', 'scot', 'time', 'uc7K')),
)
SCREEN_READ_SECONDS = 0.6           # first call of either analytics screen through the MCP path


def apply_screen_reads(rows) -> int:
    """Mark the SCREEN_READS keys as read through their screen (in place); returns the rows changed."""
    by_key = {r[1]: r for r in rows if r[0] == 'ui'}
    changed = 0

    def mark(code, surface, cls, reason):
        r = by_key.get(code)
        if r is None:
            return 0
        surfaces = [s for s in r[9].split(', ') if s] + [surface, f'fm_ui_read({cls} with context)',
                                                         'recipe:ui_recipes_analytics']
        before = (r[7], r[9])
        r[3] = r[3] or cls
        r[6], r[7], r[8], r[9] = 'ui', 'reads', reason, ', '.join(sorted(set(surfaces)))
        r[12], r[13], r[14] = 'on_demand', 'ui_handler', {'handler_s': SCREEN_READ_SECONDS}
        return int(before != (r[7], r[9]))

    for surface, cls, parent, why, fields in SCREEN_READS:
        changed += mark(parent, surface, cls, f'read with context objects: {why}')
        for code in fields:
            if by_key.get(code, [None] * 8)[7] != 'reads':
                changed += mark(code, surface, cls, f'field of the records the handler returns for key {parent} '
                                                    f'({surface})')
    return changed


def build_native(rtti, roots, ui_classes, snap_classes, enumerated_tables, names, hexes) -> list:
    rows = []
    rooted_descendants = defaultdict(list)
    for name in roots:
        for a in ancestors(rtti, name):
            rooted_descendants[a].append(name)
    for name, info in sorted(rtti.items()):
        anc = ancestors(rtti, name)
        kind = class_kind(name, anc)
        domain = class_domain(name)
        short = re.sub(r'<.*', '', name).split('::')[-1]
        route, status, reason, surfaces = 'none', 'unreached', '', []
        root = roots.get(name) or []
        extra = {'kind': kind}
        if info.get('vt'):
            extra['vtable'] = hex(info['vt'])
        if root:
            extra['roots'] = [f'{hex(r)}:{how}' for r, how in root[:3]]
        if name in snap_classes or short in snap_classes:
            route, status, reason, surfaces = 'direct', 'reads', 'database record class in the snapshot', \
                ['fm_db_query', 'fm_db_read']
        elif name in enumerated_tables:
            route, status, reason, surfaces = 'direct', 'reads', f'enumerated table {enumerated_tables[name]}', \
                ['fm_db_query']
        elif kind == 'ui_handler':
            res = ui_classes.get(name) or ui_classes.get(short)
            if res and (res['counts'] or {}).get('value'):
                route, status, surfaces = 'ui', 'reads', [f"fm_ui_read({res['job']})"]
                reason = f"{res['counts'].get('value')} keys with values"
            elif res:
                route, status = 'ui', 'unset_on_samples'
                reason = res.get('blocker') or 'every key unset'
                if 'parameter' in reason:
                    status = 'needs_parameter'
                elif 'external' in reason or 'dereference' in reason or 'timeout' in reason:
                    status = 'unavailable'
                surfaces = [f"fm_ui_read({res['job']})"]
            else:
                reason = 'no factory type builds this handler'
        elif kind == 'news_item' and 'db::NEWS_ITEM' in anc:
            route, status, surfaces = 'ui', 'reads', ['fm_get_inbox', 'fm_ui_read(70)']
            reason = 'subject, body, type and dates through NEWS_ITEM_UI_HANDLER; class-specific payload not decoded'
        if status != 'reads':
            # Names count only for plain classes: a template's outer name (DATABASE_TABLE<...>) says nothing
            # about which instantiation a reader reaches.
            mods = set(names.get(short, ())) if '<' not in name and len(short) > 4 and \
                short not in ('NAME', 'DATE', 'TYPE') else set()
            hits = set()
            for a in (info.get('vt'), info.get('ti')):
                if a:
                    hits |= hexes.get(a, set()) | hexes.get(a - 0x10, set())
            for r, _ in root:
                hits |= hexes.get(r, set())
            if hits or mods:
                route, status = 'hand_built', 'reads'
                why = []
                if hits:
                    why.append('vtable, typeinfo or root RVA in reader source')
                if mods:
                    why.append('class named in reader source')
                reason = ' and '.join(why) + ' (evidence of reach, not proof of decoding)'
                surfaces = sorted(hits | mods)[:4]
            elif root and status == 'unreached':
                reason = f'live root at data {hex(root[0][0])} ({root[0][1]}); no reader'
            elif status == 'unreached' and rooted_descendants.get(name):
                derived = sorted(rooted_descendants[name])
                extra['base_of'] = derived[:4]
                reason = f'base class: live instances carry a derived vtable ({", ".join(derived[:3])})'
            elif status == 'unreached':
                reason = 'no live root in plugin data and no reader' if kind in ('manager', 'table') else 'no reader'
        weight = {'manager': 3.0, 'table': 3.0, 'record': 1.5, 'persisted': 1.2, 'news_item': 0.6, 'other': 0.4,
                  'extern_service': 0.3,
                  'ui_handler': 0.3, 'behaviour': 0.05}.get(kind, 0.4)
        rows.append(_row('native', name, domain, short, None, None, route, status, reason, surfaces, weight, extra))
    return rows


def build_persisted(rtti, native_rows, walked=()) -> list:
    status_of = {r[1]: r for r in native_rows}
    persisted = {name: {'SAVE_SYSTEM walker'} for name in walked}
    for name in rtti:
        m = re.match(r'^sicore::CLASS_INFO_TEMPLATE<(.+)>$', name)
        if m:
            persisted.setdefault(m.group(1), set()).add('class info')
    for name in rtti:
        if 'sicore::PERSISTENT' in ancestors(rtti, name):
            persisted.setdefault(name, set()).add('PERSISTENT')
    rows = []
    for name, how in sorted(persisted.items()):
        nat = status_of.get(name)
        if nat:
            route, status, reason, surfaces, kind = nat[6], nat[7], nat[8], nat[9].split(', ') if nat[9] else [], \
                nat[11].get('kind')
        else:
            route, status, reason, surfaces, kind = 'none', 'unreached', 'no typeinfo of its own in the plugin', [], None
        weight = nat[10] if nat else 1.0
        rows.append(_row('persisted', name, class_domain(name), name.split('::')[-1], None, None, route, status,
                         reason, surfaces, weight, {'how': sorted(how), 'kind': kind}))
    return rows


def apply_persist(rows, schema=None) -> int:
    """Native and persisted rows read by emulating the game's save code (persist.py, PERSIST.md): a class
    whose objects a save function wrote, or a save root whose save ran, `reads` (route `persist`, on
    demand, cost = seconds of that root's emulated save); a root whose save stopped is `unavailable` with
    the refusal. Only rows that do not read already change. Returns the number of rows changed."""
    if schema is None:
        try:
            from . import persist
            schema = persist.load_schema()
        except Exception:  # noqa: BLE001 - no packaged schema
            return 0
    seen = {}
    for root in schema.get('roots', []):
        name = root['root'].split('+')[0].split('*')[0]
        secs = root.get('fast_seconds')
        if root.get('status') == 'ok':
            seen.setdefault(name, ('reads', f"save function {root['functions'][0]['function'] if root.get('functions') else '?'} "
                                   f"of {root['root']} ran: {root.get('writes')} writes, {root.get('bytes')} bytes",
                                   secs, root['root']))
        elif name not in seen:
            seen[name] = ('unavailable', f"emulated save of {root['root']} stopped: {root.get('refusal')}", secs,
                          root['root'])
        for f in root.get('functions', []):
            cls = f.get('class')
            if not cls:
                continue
            fields = sum(1 for x in f.get('fields', []) if x.get('kind') == 'value')
            hit = ('reads', f"written by save function {f['function']} of {root['root']} "
                   f"({f['instances']} objects, {fields} value fields)", secs, root['root'])
            for key in {cls, cls.split('::')[-1]}:
                if seen.get(key, ('',))[0] != 'reads':
                    seen[key] = hit
    changed = 0
    for r in rows:
        if r[0] not in ('native', 'persisted') or r[7] == 'reads':
            continue
        hit = seen.get(r[1])
        if hit is None:
            continue
        status, reason, secs, root = hit
        if status == 'unavailable' and r[7] == 'unavailable':
            continue
        r[6], r[7], r[8] = 'persist', status, reason
        surfaces = set(filter(None, r[9].split(', '))) | {f'fm_native_read({root})'}
        r[9] = ', '.join(sorted(surfaces))
        r[11] = dict(r[11] or {}, persist_root=root, persist_seconds=secs)
        if status == 'reads':
            r[12], r[13], r[14] = 'on_demand', 'emulated_save', {'root_save_s': secs}
        changed += 1
    return changed


def build_tools(oracle_map, tool_list) -> list:
    rows = []
    for e in oracle_map.ENTRIES:
        rows.append(_row('tools', f'{e.family}.{e.field}', domain_of(e.field, e.family, record_type=e.rtype),
                         e.field, None, None, 'hand_built', 'reads', f'oracle-mapped to {",".join(e.codes)}',
                         [tool_of(oracle_map, e.call)], 0.3, {'codes': list(e.codes)}))
    for u in oracle_map.UNMAPPED:
        rows.append(_row('tools', f'{u.family}.{u.field}', domain_of(u.field, u.family), u.field, None, None,
                         'hand_built', 'reads', 'tool only: ' + u.reason[:200], [u.tool], 0.3))
    for name, desc in tool_list:
        if name == 'fm_coverage':
            continue
        route = 'direct' if name.startswith('fm_db_') else 'ui' if name in UI_TOOLS else 'hand_built'
        rows.append(_row('tools', f'tool:{name}', domain_of(name.replace('fm_', ''), desc[:120]), name,
                         desc.split('. ')[0][:160] if desc else None, 'tool description', route, 'reads', '', [name],
                         0.3))
    return rows


UI_TOOLS = {'fm_ui_schema', 'fm_ui_read', 'fm_get_board_confidence', 'fm_get_inbox', 'fm_get_calendar',
            'fm_get_player_status', 'fm_get_club_vision', 'fm_get_scouting', 'fm_get_transfer_activity',
            'fm_get_squad_dynamics', 'fm_get_training_schedule', 'fm_get_medical_centre',
            'fm_get_finance_projections', 'fm_get_youth_intake', 'fm_get_season_expectations',
            'fm_get_league_table', 'fm_get_manager_profile'}


def registered_tools() -> list:
    """[(name, description)] from the MCP server's registry (imports the server; no game access)."""
    import asyncio
    from .. import server
    tools = asyncio.run(server.mcp.list_tools())
    return sorted((t.name, t.description or '') for t in tools)


# ---------------------------------------------------------------------------------------------- cost
def snapshot_costs(path) -> dict:
    """Measured costs from a snapshot (read-only): per emulated column the getter's ms per row and the
    rows it covers (`_column_state`), and the build's direct-plan phase as microseconds per cell (`_build`)."""
    import sqlite3
    out = {'columns': {}, 'direct_us_per_cell': None, 'emulated_build_s': None}
    if not path or not Path(path).exists():
        return out
    con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        acc = defaultdict(lambda: [0, 0.0])
        for table, column, rows, source, ms in con.execute(
                'select table_name, column_name, rows, source, ms_per_row from _column_state '
                "where source in ('emulated', 'extra') and ms_per_row is not null"):
            a = acc[(table, column)]
            a[0] += rows or 0
            a[1] += (rows or 0) * ms
        out['columns'] = {f'{t}.{c}': {'ms_per_row': round(v[1] / v[0], 4) if v[0] else None, 'rows': v[0],
                                       'whole_column_s': round(v[1] / 1000, 1)} for (t, c), v in acc.items()}
        timing = con.execute("select value from _build where key='timing'").fetchone()
        cells = con.execute("select sum(t.rows) from _fields f join _tables t using(table_name) "
                            "where f.source='direct' and f.status='ready'").fetchone()[0]
        if timing:
            t = json.loads(timing[0])
            if cells:
                out['direct_us_per_cell'] = round(t.get('direct', 0) * 1e6 / cells, 3)
            out['emulated_build_s'] = t.get('emulated')
            out['build_s'] = t.get('total')
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return out


def annotate_costs(rows, costs, coverage) -> None:
    """Fill availability, cost class and cost of every row (in place)."""
    per_type_ms = {rt: v.get('mean_ms') for rt, v in ((coverage or {}).get('record_types') or {}).items()}
    for r in rows:
        denom, key, route, status, surfaces, extra = r[0], r[1], r[6], r[7], r[9], r[11]
        if status != 'reads':
            r[12], r[13], r[14] = 'none', None, None
            continue
        snap_col = next((x[len('snapshot:'):] for x in surfaces.split(', ') if x.startswith('snapshot:')), None)
        sstatus = extra.get('snapshot')
        if route == 'direct' and denom in ('editor', 'getter_extra'):
            r[12], r[13] = 'snapshot_direct', 'direct_plan'
            r[14] = {'us_per_cell': costs.get('direct_us_per_cell')}
        elif route in ('emulated', 'extra') and denom in ('editor', 'getter_extra'):
            col = costs['columns'].get(snap_col) if snap_col else None
            # a build stores no emulated column any more: the getter runs when a query names the column
            # (ondemand.py); 'snapshot_emulated' remains for snapshots written by older readers
            r[12] = 'snapshot_emulated' if sstatus == 'partial' else 'on_demand'
            r[13] = 'emulated_getter'
            rtype = key.split('.')[0]
            r[14] = ({'ms_per_row': col['ms_per_row'], 'rows': col['rows'], 'whole_column_s': col['whole_column_s']}
                     if col else {'ms_per_call': per_type_ms.get(rtype), 'basis': 'census mean for the record type'})
        elif route == 'direct':
            r[12], r[13], r[14] = 'snapshot_direct', 'direct_plan', {'us_per_cell': costs.get('direct_us_per_cell')}
        elif route == 'ui':
            r[12], r[13] = 'on_demand', 'ui_handler'
            c = extra.get('cost') or {}
            r[14] = {k: v for k, v in (('ms_per_key', c.get('ms')), ('handler_s', c.get('job_s'))) if v is not None} \
                or None
        elif route == 'hand_built':
            r[12], r[13], r[14] = 'on_demand', 'hand_built_tool', None
        elif route == 'persist':
            r[12], r[13], r[14] = 'on_demand', 'emulated_save', {'root_save_s': extra.get('persist_seconds')}
        else:
            r[12], r[13], r[14] = 'on_demand', 'static', None


# ---------------------------------------------------------------------------------------------- summary
def headline(ledger) -> dict:
    out = {}
    rows = ledger['rows']
    for denom in DENOMINATORS:
        sub = [r for r in rows if r[0] == denom]
        if denom == 'native':
            state = [r for r in sub if r[11].get('kind') in STATE_KINDS]
            out['native_state'] = _counts(state)
        if denom == 'persisted':
            out['persisted_state'] = _counts([r for r in sub if r[11].get('kind') != 'behaviour'])
        out[denom] = _counts(sub)
    return out


def _counts(sub) -> dict:
    c = Counter(r[7] for r in sub)
    by_domain = defaultdict(Counter)
    for r in sub:
        by_domain[r[2]][r[7]] += 1
    total = len(sub)
    av = Counter(r[12] if len(r) > 12 else ('on_demand' if r[7] == 'reads' else 'none') for r in sub)
    return {'total': total, 'reads': c.get('reads', 0),
            'by_availability': {a: av.get(a, 0) for a in AVAILABILITY},
            'percent': round(100 * c.get('reads', 0) / total, 1) if total else 0.0,
            'by_status': {s: c.get(s, 0) for s in STATUSES},
            'by_domain': {d: {'total': sum(v.values()), 'reads': v.get('reads', 0)}
                          for d, v in sorted(by_domain.items(), key=lambda kv: -sum(kv[1].values()))}}


STATUS_GAP = {'unreached': 1.0, 'unavailable': 0.9, 'needs_parameter': 0.6, 'unset_on_samples': 0.35,
              'empty_in_save': 0.05}


def gaps(ledger, limit=60) -> list:
    """Ranked gaps: native/persisted classes one by one; UI keys grouped by handler class; schema and getter
    keys grouped by (record type, status). Score = domain value x kind weight x status weight x log size."""
    groups = {}
    for r in ledger['rows']:
        denom, key, domain, name, label, _, route, status, reason, surfaces, weight, extra = r[:12]
        if status == 'reads' or DOMAIN_VALUE.get(domain, 0) == 0 or denom == 'tools':
            continue
        if denom in ('native', 'persisted'):
            if extra.get('kind') in ('behaviour', 'ui_handler') or extra.get('base_of'):
                continue
            gid = ('native', key)
            title = key
        elif denom == 'ui':
            gid = ('ui', name or '(no handler class)', status)
            title = name or 'front-end keys with no plugin handler'
        else:
            rtype = key.split('.')[0]
            gid = (denom, rtype, status)
            title = f'{rtype} {"schema fields" if denom == "editor" else "getter keys"}'
        g = groups.setdefault(gid, {'title': title, 'denom': denom if denom != 'persisted' else 'native',
                                    'status': status, 'domain': Counter(), 'members': [], 'reasons': Counter(),
                                    'weight': 0.0, 'extra': {}, 'surfaces': surfaces})
        g['domain'][domain] += 1
        member = key if denom in ('native', 'persisted') else (label or name or key)
        if member not in g['members']:
            g['members'].append(member)
        g['reasons'][reason[:160]] += 1
        g['weight'] = max(g['weight'], weight)
        if denom in ('native', 'persisted'):
            g['extra'].update(extra)
            g['persisted'] = g.get('persisted') or denom == 'persisted' or 'PERSISTENT' in str(extra.get('how'))
    ranked = []
    for gid, g in groups.items():
        domain = g['domain'].most_common(1)[0][0]
        n = len(g['members'])
        score = DOMAIN_VALUE[domain] * g['weight'] * STATUS_GAP.get(g['status'], 0.3) * (1 + math.log2(n))
        if g['extra'].get('roots'):
            score *= 1.5
        ranked.append({'score': round(score, 2), 'title': g['title'], 'denominator': g['denom'], 'domain': domain,
                       'status': g['status'], 'size': n, 'examples': sorted(set(g['members']))[:6],
                       'reason': g['reasons'].most_common(1)[0][0], 'kind': g['extra'].get('kind'),
                       'roots': g['extra'].get('roots'), 'route': next_route(g),
                       'persisted': bool(g.get('persisted'))})
    ranked.sort(key=lambda x: (-x['score'], x['title']))
    for item in ranked[:limit]:
        note = GAP_NOTES.get(item['title'])
        if note:
            item['holds'], item['route'] = note
    return ranked[:limit]


def next_route(g) -> str:
    st, denom, kind = g['status'], g['denom'], g['extra'].get('kind')
    if denom == 'ui':
        if st == 'needs_parameter':
            return 'supply the screen parameter the getter reads (fmdb_ui_sweep params trace) and re-read'
        if st == 'unavailable':
            return 'model or bypass the refused external named in the reason, then re-sweep'
        if st == 'unset_on_samples':
            return 'bind the handler to a record that has data (parent screen row, another profile)'
        return 'build the handler through its factory type or its parent screen'
    if denom == 'native':
        if g['extra'].get('roots'):
            return 'walk the live root: read the object at the root, map its fields by the vtable getters ' \
                   '(emulate slot functions in PropertyVM)'
        if kind in ('manager', 'table'):
            return 'find the singleton accessor (MANUAL_SINGLETON instance global or getter BL target) and walk it'
        return 'find the owning manager or record field that holds instances (xref the vtable in constructors)'
    if st == 'unreached':
        return 'getter does not claim the key: read the stored field by a direct plan or the owning sub-record'
    if st == 'unavailable':
        return 'model the refused external or read the stored field directly'
    return 'sample records that carry the value (other classes, managed club) to confirm'


# Hand-written notes for gaps whose holding and route were checked in this lane; keyed by gap title.
_WALK = ('walk the live root: trace which fields of the manager object its UI handlers read inside emulation '
         '(PropertyVM page/read trace on the object range) and lift those offsets into direct plans checked against '
         'the handler values')
GAP_NOTES: dict = {
    # Holdings are inferred from the class name unless a related surface is named; related surfaces read today.
    'AGENT_MANAGER': ('agents\' activity on players (inferred); agent records themselves are in the snapshot '
                      '(agen)', _WALK),
    'CONTRACT_MANAGER': ('contract negotiations and contract events (inferred); signed contracts are read from '
                         'person records (fm_get_contract_terms), offers by fm_query_transfer_offers', _WALK),
    'SCOUT_MANAGER': ('scouting assignments and reports (inferred); fm_get_scouting reads the scouting screens '
                      'and the knowledge store holds what is known', _WALK),
    'AWOL_MANAGER': ('players absent without leave (inferred)', _WALK),
    'DISPUTE_MANAGER': ('player and staff disputes (inferred); fm_get_squad_dynamics shows some outcomes', _WALK),
    'DYNAMICS_PIVOTAL_MOMENTS_MANAGER': ('squad-dynamics pivotal moments (inferred); fm_get_squad_dynamics reads '
                                         'the dynamics screen', _WALK),
    'INTERACTION_MANAGER': ('conversations, promises and their deadlines (inferred); fm_get_player_status reads '
                            'per-player happiness through the person screen', _WALK),
    'MORALE_MANAGER': ('morale events and modifiers (inferred); per-person morale is read by fm_get_player_morale',
                       _WALK),
    'TEAM_TALK_MANAGER': ('team-talk state and reactions (inferred)', _WALK),
    'BOARD_TAKEOVER_MANAGER': ('club takeovers (inferred)', _WALK),
    'FEEDER_CLUB_MANAGER': ('feeder and parent club links (inferred)', _WALK),
    'FINANCE_MANAGER': ('club finance processing (inferred); club balances and budgets are read from club records '
                        '(fm_get_club_finances) and the finance screen (fm_get_finance_projections)', _WALK),
    'INJURY_MANAGER': ('injury processing (inferred); current injuries are read from person records '
                       '(fm_get_player_injury_status) and the medical screen (fm_get_medical_centre)', _WALK),
    'MATCHDAY_MANAGER': ('matchday state (inferred); fixtures are read by fm_find_fixtures and fm_get_calendar',
                         _WALK),
    'PERSON_PROGRESSION_MANAGER': ('attribute progression of people (inferred)', _WALK),
    'PLAY_FIXTURE_MANAGER': ('fixtures being played (inferred)', _WALK),
    'TRAINING_CAMP_MANAGER': ('training camps (inferred); the training screen is read by fm_get_training_schedule',
                              _WALK),
    'BACKROOM_ADVICE_MANAGER': ('backroom advice items (inferred); the BACKROOM_ADVICE_* suggestion classes '
                                'are its content types', _WALK),
    'HUMAN_NON_PLAYER_MANAGER': ('the human managers\' state (inferred); fm_get_manager_profile reads the profile '
                                 'screen', _WALK),
    'JOB_CENTRE_MANAGER': ('job vacancies and applications (inferred)', _WALK),
    'db::DATABASE_TABLE<db::GAME_DATABASE_RECORD>': (
        'the table of game-created records (a DATABASE_TABLE singleton with a live root that the reader does not '
        'enumerate)',
        'enumerate it like the 24 tables (database.table with this root) and classify its records by vtable'),
}


# ---------------------------------------------------------------------------------------------- build / io
@dataclass
class Inputs:
    coverage: Path | None = None
    snapshot: Path | None = None
    sweep: Path = SWEEP_DIR
    live: bool = True


def build(inputs: Inputs | None = None, *, engine=None, image=None, log=print) -> dict:
    from . import catalog, extras, oracle_map, ui_registry
    from . import labels
    from .image import PluginImage
    inputs = inputs or Inputs()
    t0 = time.time()
    timings = {}
    from .engine import DEFAULT_CACHE
    cov_path = inputs.coverage or (DEFAULT_CACHE / 'fmdb' / 'seed' / 'coverage.json')
    coverage = _load_json(cov_path)
    snap_path = inputs.snapshot or default_snapshot()
    fields = snapshot_fields(snap_path)
    costs = snapshot_costs(snap_path)
    cat = catalog.load_catalog()
    reg = ui_registry.default()
    rows = build_editor(cat, coverage, fields, labels.label_for, oracle_codes(oracle_map))
    timings['editor'] = round(time.time() - t0, 1)
    rows += build_extras(extras, fields, labels.label_for)
    sweep = sweep_results(inputs.sweep)
    ui_rows, ui_classes = build_ui(reg, sweep)
    rows += ui_rows
    timings['ui'] = round(time.time() - t0, 1)
    if image is None:
        image = engine.image if engine is not None else PluginImage.load(labels.DEFAULT_APP / 'Contents/PlugIns/'
                                                                         'game_plugin.bundle/Contents/MacOS/game_plugin')
    rtti = rtti_inventory(image)
    timings['rtti'] = round(time.time() - t0, 1)
    roots = {}
    if inputs.live:
        if engine is None:
            from .engine import Engine
            engine = Engine.open()
        roots = live_roots(engine, image, rtti)
        timings['live_roots'] = round(time.time() - t0, 1)
    snap_classes = set()
    from . import tables as tables_mod
    snap_classes |= {v[0] for v in tables_mod.CLASSES.values()}
    snap_classes |= {f'db::{v[0]}' for v in tables_mod.CLASSES.values()}
    from .. import database
    enumerated = {}
    demangled = _demangle([raw.decode() for _, _, raw in database.TABLES.values()])
    for (kind, _), dm in zip(database.TABLES.items(), demangled):
        enumerated[dm] = kind
    names, hexes = source_tokens()
    native_rows = build_native(rtti, roots, ui_classes, snap_classes, enumerated, names, hexes)
    rows += native_rows
    walk = save_walk(image, rtti, roots) if roots else {}
    rows += build_persisted(rtti, native_rows, walk.get('managers', ()))
    apply_persist(rows)
    try:
        tool_list = registered_tools()
    except Exception as exc:  # noqa: BLE001
        log(f'tool registry unavailable: {exc}')
        tool_list = []
    rows += build_tools(oracle_map, tool_list)
    timings['total'] = round(time.time() - t0, 1)
    meta = {'built_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'timings_s': timings,
            'inputs': {'coverage': str(cov_path) if coverage else None, 'snapshot': str(snap_path) if fields else None,
                       'sweep_jobs': len(sweep), 'live_roots': bool(roots)},
            'counts': {'rtti_classes': len(rtti), 'with_vtable': sum(1 for v in rtti.values() if v.get('vt')),
                       'classes_with_live_roots': len(roots), 'tools_registered': len(tool_list)},
            'labels': labels.census(), 'load': os.getloadavg(), 'save_walk': walk}
    if engine is not None:
        try:
            meta['game_date'] = engine.game_date()
        except Exception:  # noqa: BLE001
            pass
    annotate_costs(rows, costs, coverage)
    meta['screen_reads'] = apply_screen_reads(rows)
    meta['costs'] = {'direct_us_per_cell': costs.get('direct_us_per_cell'),
                     'emulated_build_s': costs.get('emulated_build_s'), 'snapshot_build_s': costs.get('build_s'),
                     'census_mean_ms': ((coverage or {}).get('timing') or {}).get('mean_ms'),
                     'vm': 'fastvm' if _fastvm_active() else 'python',
                     'basis': 'wall-clock on this machine under the load average in meta.load; snapshot build and '
                              'census were run single-process'}
    ledger = {'meta': meta, 'columns': list(COLUMNS), 'rows': rows}
    ledger['headline'] = headline(ledger)
    ledger['gaps'] = gaps(ledger)
    return ledger


def _fastvm_active() -> bool:
    try:
        from . import fastvm  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return (REPO / 'build' / 'libfm_vm_accel.dylib').exists()


def save(ledger, path=CURRENT):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, 'wt', compresslevel=9) as handle:
        json.dump(ledger, handle, separators=(',', ':'), ensure_ascii=False, default=str)
    return path


def load(path=CURRENT) -> dict | None:
    return _load_json(path)


def compare(before: dict, after: dict) -> dict:
    """Per-denominator readable counts before and after, and the keys that changed status."""
    out = {}
    for denom in list(DENOMINATORS) + ['native_state', 'persisted_state']:
        b, a = before['headline'].get(denom, {}), after['headline'].get(denom, {})
        out[denom] = {'before': f"{b.get('reads', 0)}/{b.get('total', 0)}",
                      'after': f"{a.get('reads', 0)}/{a.get('total', 0)}",
                      'gained': a.get('reads', 0) - b.get('reads', 0),
                      'availability_before': b.get('by_availability', {}),
                      'availability_after': a.get('by_availability', {})}
    bmap = {(r[0], r[1]): r[7] for r in before['rows']}
    newly = [(r[0], r[1]) for r in after['rows'] if r[7] == 'reads' and bmap.get((r[0], r[1])) not in (None, 'reads')]
    lost = [(r[0], r[1]) for r in after['rows'] if r[7] != 'reads' and bmap.get((r[0], r[1])) == 'reads']
    out['newly_read'] = len(newly)
    out['newly_read_examples'] = newly[:40]
    out['no_longer_read'] = lost[:40]
    return out


# A search word matches a row through any of these spellings too: the game's screens say "possession
# gained", the match records and the tools say "possession won".
SEARCH_SYNONYMS = {
    'gained': ('won', 'regain'), 'gains': ('won', 'regain', 'gained'), 'gain': ('won', 'regain'),
    'regained': ('won', 'gained'), 'regains': ('won', 'gained'), 'won': ('gained',),
    'losses': ('lost',), 'turnover': ('possession',), 'turnovers': ('possession',),
    'charts': ('chart',), 'graphs': ('graph',), 'datahub': ('data hub',),
}
# Screens and charts by the name a manager knows -> the rows that answer them. The text is added to
# those rows' search text, and a row whose topic text holds every search word is listed first.
SEARCH_TOPICS = (
    ('data hub analytics team player chart visualisation zone map possession gained lost passes attempted '
     'defensive actions scatter graph polygon set piece first contact',
     (('ui', 'uvRT'), ('ui', 'fGjn'), ('ui', 'UZlS'), ('ui', 'pyZE'), ('ui', 'tzwN'), ('ui', 'vj3R'), ('ui', 'L9Nj'),
      ('ui', 'YYiF'), ('ui', 'bMU2'), ('ui', 'Ywr3'), ('ui', '0Zoa'), ('tools', 'tool:fm_get_ui_screen'))),
    ('data hub chart rebuilt from match events possession gained lost by player and place and half',
     (('tools', 'tool:fm_get_retained_possession_events'), ('tools', 'tool:fm_report_retained_possession_by_period'),
      ('tools', 'tool:fm_list_retained_match_data'))),
    ('data hub analytics player person chart catalogue ask for scatter graph polygon', (('ui', 'FyDK'), ('tools', 'tool:fm_get_ui_screen'))),
    ('data hub opposition report analytics chart polygon key findings', (('ui', 'rijN'), ('tools', 'tool:fm_get_ui_screen'))),
    ('data hub match analytics chart last match pass map shot map average positions action zones expected goals xg story momentum',
     (('ui', 'LtKt'), ('ui', 'UIwU'), ('ui', 'EHW7'), ('ui', 'k3hM'), ('ui', 'MU5d'), ('ui', 'FOjz'), ('ui', 'TqMq'), ('ui', 'xlO9'),
      ('tools', 'tool:fm_get_ui_screen'))),
)


def _search_topics() -> dict:
    out = defaultdict(str)
    for text, keys in SEARCH_TOPICS:
        for key in keys:
            out[key] = (out[key] + ' ' + text).strip()
    return out


def _has_word(word: str, text: str) -> bool:
    return word in text or any(other in text for other in SEARCH_SYNONYMS.get(word, ()))


def query(ledger, domain=None, search=None, denominator=None, status=None, limit=50) -> dict:
    """Rows filtered by domain / free text / denominator / status, for `fm_coverage`. A row matches a
    search when its key, domain, name, label, surfaces or topic text holds every word (SEARCH_SYNONYMS
    widens a word; SEARCH_TOPICS names screens and charts)."""
    rows = ledger['rows']
    if denominator:
        rows = [r for r in rows if r[0] == denominator]
    if domain:
        d = domain.lower()
        rows = [r for r in rows if d in r[2].lower()]
    if status:
        rows = [r for r in rows if r[7] == status]
    led = set()
    if search:
        words = [w.lower() for w in search.split() if w]
        topics = _search_topics()
        kept = []
        for r in rows:
            topic = topics.get((r[0], r[1]), '')
            text = ' '.join(str(x) for x in r[1:6] + [r[9]]).lower() + ' ' + topic
            if all(_has_word(w, text) for w in words):
                kept.append(r)
                if topic and all(_has_word(w, topic) for w in words):
                    led.add((r[0], r[1]))
        rows = kept
    sub = {'total': len(rows), 'by_status': dict(Counter(r[7] for r in rows)),
           'by_denominator': dict(Counter(r[0] for r in rows))}
    items = []
    rank = {s: i for i, s in enumerate(STATUSES)}
    for r in sorted(rows, key=lambda r: ((r[0], r[1]) not in led, rank.get(r[7], 9), -r[10], r[1]))[:limit]:
        item = dict(zip(COLUMNS, r))
        if not item['extra']:
            item.pop('extra')
        items.append({k: v for k, v in item.items() if v not in (None, '', [], {})})
    return {'matches': sub, 'items': items}


# ---------------------------------------------------------------------------------------------- markdown
DOC_INTRO = """# Completeness ledger

What fraction of the game's data the reader can read, measured against the game's own inventories.
Generated by `scripts/fmdb_ledger.py` (`fm_live_mcp/fmdb/ledger.py`); the machine-readable ledger is
`fm_live_mcp/fmdb/data/ledger.json.gz` (and `ledger-before.json.gz`, the baseline), and `fm_coverage`
returns the same rows to a model.

## Statuses and routes

`reads`: a route returned values on this career. `unset_on_samples`: the route runs, every sampled record
or binding was empty. `empty_in_save` (editor rows): a full scan asked every record of the type and none
holds a value, so the field is reachable and this save has no data for it (`editor_live.py`).
`needs_parameter`: the getter read a screen parameter the sweep did not supply.
`unavailable`: the route fails; the row carries the reason. `unreached`: no reader reaches it.
Routes: `direct` (verified read plan), `emulated` (record getter in the VM), `extra` (getter key outside the
schema), `ui` (UI handler key through `fm_ui_read` or a recipe), `hand_built` (an existing tool), `none`.

## Denominators

| Denominator | What one row is | Derived from |
|---|---|---|
| editor | one (record type, field) of the shipped editor schema, list-item fields included | `editor.fmf` via `catalog.py`; status from the getter census and the snapshot `_fields` table |
| getter_extra | one getter key outside the schema that returned a value on some sampled record | `extras.json.gz` (the census keeps only keys with a value, so this denominator is 100% by construction) |
| ui | one FourCC the front end's property registry labels | `ui_registry.json.gz`; status from the UI sweep of every buildable handler |
| native | one class typeinfo in the plugin | RTTI scanned from the on-disk plugin slice (typeinfo objects bound to the three `__cxxabiv1` vtables, primary vtables, parents); live roots from the plugin's `__DATA` in the running game |
| native_state | the native rows of kind manager/system, database table, record, news item or persisted | as above |
| persisted | one class the save layer creates by name (`sicore::CLASS_INFO_TEMPLATE<T>`) or that derives from `sicore::PERSISTENT` | RTTI |
| tools | one oracle-mapped tool field, tool-only field, or registered tool | `oracle_map.py`, the MCP registry |

Reach of a native class by a hand-built tool is evidence of reach (the class name, its vtable or typeinfo
RVA, or its root global appears in reader source), not proof that its fields are decoded.
"""


def _pct(h):
    return f"{h['reads']:,} / {h['total']:,} ({h['percent']}%)"


def render_markdown(current, before=None) -> str:
    out = [DOC_INTRO]
    meta = {'inputs': {}, 'counts': {'rtti_classes': 0, 'with_vtable': 0, 'classes_with_live_roots': 0},
            **current['meta']}
    out.append('## Headline\n')
    out.append(f"Built {meta.get('built_at')} on game date {meta.get('game_date', '?')}; sweep jobs "
               f"{meta['inputs'].get('sweep_jobs')}; live roots {'scanned' if meta['inputs'].get('live_roots') else 'not scanned'}; "
               f"RTTI classes {meta['counts']['rtti_classes']:,} ({meta['counts']['with_vtable']:,} with a primary vtable, "
               f"{meta['counts']['classes_with_live_roots']:,} with a live root). Timings (s, cumulative): "
               f"{meta.get('timings_s')}; load average {tuple(round(x, 1) for x in meta.get('load', ()))}.\n")
    out.append('Readable rows split by where the value lives: in the snapshot by a direct plan, in the snapshot by '
               'emulation (build or background fill), or computed on demand (`fm_db_read`, a UI handler, a recipe, '
               'a hand-built tool). Costs are in the rows (`cost_class`, `cost`); measured costs: '
               + json.dumps(meta.get('costs', {})) + '.\n')
    cols = ('| Denominator | Readable | in snapshot (direct) | in snapshot (emulated) | on demand | unset on samples '
            '| empty in save | needs parameter | unavailable | unreached |')
    if before:
        cols = cols[:-1] + '| before |'
    out += [cols, '|' + '---|' * (cols.count('|') - 1)]
    for denom, h in current['headline'].items():
        s = h['by_status']
        av = h.get('by_availability') or {}
        line = (f"| {denom} | {_pct(h)} | {av.get('snapshot_direct', 0):,} | {av.get('snapshot_emulated', 0):,} | "
                f"{av.get('on_demand', 0):,} | {s['unset_on_samples']:,} | {s.get('empty_in_save', 0):,} | "
                f"{s['needs_parameter']:,} | "
                f"{s['unavailable']:,} | {s['unreached']:,} |")
        if before:
            b = before['headline'].get(denom)
            line += f" {_pct(b) if b else '-'} |"
        out.append(line)
    out.append('')
    out.append('### By domain (readable / total)\n')
    denoms = ['editor', 'ui', 'native_state', 'persisted_state']
    domains = DOMAIN_NAMES
    out.append('| Domain | ' + ' | '.join(denoms) + ' |')
    out.append('|---|' + '---|' * len(denoms))
    for d in domains:
        cells = []
        for denom in denoms:
            v = current['headline'].get(denom, {}).get('by_domain', {}).get(d)
            cells.append(f"{v['reads']:,} / {v['total']:,}" if v else '-')
        out.append(f'| {d} | ' + ' | '.join(cells) + ' |')
    out.append('')
    lab = meta.get('labels') or {}
    out.append('## Labels of the getter keys outside the schema\n')
    out.append(f"{lab.get('from_game_source', 0):,} of {lab.get('extra_keys', 0):,} (type, key) pairs take their label "
               f"from a game source; {lab.get('inferred', 0):,} keep the inferred census label. By source: "
               + ', '.join(f'{k} {v:,}' for k, v in sorted((lab.get('by_source') or {}).items(), key=lambda kv: -kv[1]))
               + '. See `labels.py` for the order of sources.\n')
    out.append(_native_section(current))
    if before:
        cmp = compare(before, current)
        out.append('## Before and after\n')
        out.append('| Denominator | Before | After | Gained |\n|---|---|---|---|')
        for k, v in cmp.items():
            if isinstance(v, dict):
                out.append(f"| {k} | {v['before']} | {v['after']} | {v['gained']:+d} |")
        out.append(f"\n{cmp['newly_read']:,} rows newly read; {len(cmp['no_longer_read'])} rows no longer read.\n")
    out.append(f"## Top {len(current.get('gaps', []))} gaps, ranked by value to a manager\n")
    out.append('Score = domain value x kind weight x status weight x (1 + log2 size), x1.5 when a live root is '
               'known. UI keys are grouped by handler class, schema fields and getter keys by (record type, status); '
               'native classes stand alone. Behaviour classes (rules, formatters, actions), UI handler classes and '
               'base classes whose instances carry a derived vtable are not ranked.\n')
    out.append('| # | Gap | Inventory | Domain | Status | Size | What it holds / examples | Why not read | Next route |')
    out.append('|---|---|---|---|---|---|---|---|---|')
    for i, g in enumerate(current.get('gaps', []), 1):
        holds = g.get('holds') or ', '.join(g['examples'])
        roots = '; persisted (SAVE_SYSTEM walks it or it derives from PERSISTENT)' if g.get('persisted') else ''
        out.append(f"| {i} | `{g['title']}` | {g['denominator']} | {g['domain']} | {g['status']} | {g['size']} | "
                   f"{holds.replace('|', '/')} | {(g['reason'] + roots).replace('|', '/')} | "
                   f"{g['route'].replace('|', '/')} |")
    out.append('')
    out.append(DOC_NOTES)
    return '\n'.join(out) + '\n'


DOC_NOTES = """## Limits of this measurement

* UI sweep results depend on machine load. Handlers that run out of time (`TEAM`, `PERSON`, `COMPETITION`, the
  national squad selection session) lose keys to `unavailable` (timeout or unreadable live memory). The refresh
  uses a 420 s budget per handler; compare before and after on the same procedure and read `newly_read` /
  `no_longer_read` per key, not only the totals.
* `getter_extra` is 100% by construction: the census keeps only getter keys that returned a value on some sampled
  record. Its denominator measures labels, not reach.
* Editor list-item fields take the status of their parent list (`fm_db_read` returns the list); the items' own
  fields are not decoded separately.
* Emulated costs were measured on the Python VM (`meta.costs.vm`); the C-accelerated FastVM lowers them.
* 136 editor enum fields have no label set in `editor.fmf` (99 of them staff jobs, `mdjc`). The language table holds
  the words (for example 59 formation names at translation ids 636403-636461) but the value-to-translation mapping is
  built in native code; `labels.ENUM_SETS_UNRESOLVED` lists each set and its source.
* Gap ranking uses hand-set domain weights. Weighting by what the adviser actually asks is the next refinement.
"""


def _native_section(current) -> str:
    meta = current['meta']
    rows = [r for r in current['rows'] if r[0] == 'native']
    kinds = Counter(r[11].get('kind') for r in rows)
    rooted = Counter(r[11].get('kind') for r in rows if r[11].get('roots'))
    walk = meta.get('save_walk') or {}
    lines = ['## Native classes, live roots and the save walk\n',
             'Kinds (all / with a live root): ' + ', '.join(f'{k} {kinds[k]:,} / {rooted.get(k, 0):,}'
                                                            for k in sorted(kinds, key=lambda k: -kinds[k])) + '.',
             'A live root is a word in the plugin\'s `__data`/`__bss`/`__common` that holds an instance (static) or '
             'points at one whose first word is the class\'s primary vtable. Managers without a root are base '
             'classes whose instances carry a derived vtable, or match-time systems that exist only while a match '
             'is simulated.\n']
    if walk.get('walkers'):
        lines.append(f"SAVE_SYSTEM (vtable {walk['vtable']}, slot functions {', '.join(walk['slots'])}) calls "
                     + '; '.join(f"{fn} from {w['from_slot_function']} ({w['managers']} manager roots)"
                                 for fn, w in walk['walkers'].items())
                     + f". Those walkers load the global roots of {len(walk['managers'])} managers; the ledger "
                     'counts them as persisted (static cross-reference: the walker loads the root; which virtual it '
                     'calls on each manager is not decoded).\n')
    else:
        lines.append('The save walk was not computed (no live roots in this build).\n')
    return '\n'.join(lines) + '\n'
