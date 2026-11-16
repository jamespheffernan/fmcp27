"""SQLite snapshot of the live FM27 database for one loaded save.

`build(engine)` writes `<cache>/fmdb/<save key>/snapshot.sqlite` with one SQL table per
editor record type that has a live table (`TABLES`), metadata tables and views:

* every table: `idx INTEGER PRIMARY KEY` (live table index; PERSON-family tables use the
  PERSON index, so `player.idx = person.idx`), `uid` (unique id), `class` (RTTI class),
  then one column per catalog field (snake_case of the field name, `_<code>` appended on
  collision; record references end in `_idx` and hold the referenced row's idx);
* `_fields`, `_tables`, `_snapshot` (the contract other lanes read; names are fixed),
  plus `_column_state` (per table, column and record class: rows, source, status, cost),
  `_enum_labels`, `_unresolved` (references whose target row was not found) and `_build`;
* `_live`, `_direct_blocks`, `_direct_pages` (what the direct rows were read from, for the
  content check in `freshness.py`) and `_memo`, `_memo_blocks` (which emulated cells are
  stored and what each block of them read, `ondemand.py`);
* `<table>_labelled` views adding `<column>_label` for enum columns, and the curated
  `player_view`, `club_view`, `staff_view`, `competition_view` (see `views.py`).

Build phases (timed in `_build`): enumerate every live table in bulk; load or derive
direct plans (trace 12 records per class, verify on 50 others; disagreement demotes);
read every direct column with batched page reads, recording the pages each block of rows
depends on; resolve references; write; re-check table headers and the game date (a moved
table is rebuilt once). A build runs no getter for a column: an emulated column
(`_column_state.status = 'on_demand'`) is a column of NULLs until a query names it, and is
then computed and stored for the rows the query needs (`ondemand.py`).

Reads are not atomic and the game is not paused: a snapshot is a best-effort picture of
memory over the build's duration.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import re
import sqlite3
import struct
import time

from .. import database
from . import bulkplans, tables
from .bulkplans import Missing, Ref

CONSISTENCY_NOTE = ('Reads are not atomic and the game is not paused: values were read from live memory '
                    'over the build duration, not from one frozen instant.')

# SQL table -> editor record type (live table and class filter come from tables.RECORD_TYPES)
TABLES = {
    'person': 'pers', 'player': 'play', 'non_player': 'nnpl', 'official': 'offc', 'journalist': 'jour',
    'agent': 'agen', 'club': 'club', 'nation': 'nati', 'national_team': 'natc', 'team': 'team',
    'competition': 'comp', 'continent': 'cont', 'city': 'city', 'currency': 'curr', 'stadium': 'stad',
    'language': 'lang', 'local_region': 'lcrg', 'weather': 'weat', 'injury': 'inju', 'award': 'awar',
    'media_source': 'mdso', 'region': 'regi', 'derby': 'drbr', 'agreement': 'agrm',
    'stage_name': 'stgn', 'player_type': 'dscr',
}
# extra record types whose fields become prefixed columns of another table
PREFIXED = {'club': (('c2tm', 'second_team_'), ('c3tm', 'third_team_'), ('c4tm', 'fourth_team_')),
            'person': (('CntF', 'contract_'),)}
DESCRIPTIONS = {
    'person': 'every person record (players, staff, officials, journalists, agents, retired names)',
    'player': 'players (actual, player-staff and virtual); join person on idx for names/contracts',
    'non_player': 'staff records (non-players and player-staff); join person on idx',
    'official': 'match officials; join person on idx', 'journalist': 'journalists; join person on idx',
    'agent': 'player agents; join person on idx', 'club': 'clubs (and league bodies)',
    'nation': 'nations', 'national_team': 'national team containers', 'team': 'teams (club and national sides)',
    'competition': 'competitions', 'continent': 'continents', 'city': 'cities', 'currency': 'currencies',
    'stadium': 'stadiums', 'language': 'languages', 'local_region': 'local regions', 'weather': 'weather profiles',
    'injury': 'injury types', 'award': 'awards', 'media_source': 'media sources', 'region': 'regions',
    'derby': 'derbies', 'agreement': 'agreements', 'stage_name': 'stage names', 'player_type': 'player types',
}
# catalog `references` / table type -> SQL table
REF_TABLES = {
    'person': 'person', 'team': 'team', 'club': 'club', 'nation': 'nation', 'national_team_container': 'national_team',
    'competition': 'competition', 'stadium': 'stadium', 'city': 'city', 'local_region': 'local_region',
    'continent': 'continent', 'stage_name': 'stage_name', 'weather': 'weather', 'language': 'language',
    'media_source': 'media_source', 'region': 'region', 'currency': 'currency', 'agreement': 'agreement',
    'award': 'award', 'derby': 'derby', 'injury': 'injury', 'description': 'player_type',
}
# record-reference FourCC -> SQL tables to try (after the catalog's own target)
REF_FOURCC = {'Pers': ('person',), 'Cclu': ('club', 'team'), 'Ttea': ('team', 'club'), 'Nnat': ('nation',),
              'comp': ('competition',), 'city': ('city',), 'curr': ('currency',), 'stad': ('stadium',),
              'lang': ('language',), 'lcrg': ('local_region',), 'wthr': ('weather',), 'MedS': ('media_source',),
              'cont': ('continent',), 'regi': ('region',), 'stgn': ('stage_name',)}
SKIP_TYPES = {'button', 'label'}
RESERVED = {'idx', 'uid', 'class'}
INTEGER_TYPES = {'integer', 'unique_id', 'large', 'short_distance', 'attribute', 'month', 'day_of_week',
                 'boolean', 'enum', 'multiple_enum', 'cash'}
REF_TYPES = {'database_record_unique_id'}

UNAVAILABLE_SHARE = 0.25    # class-level unavailable when the getter fails this often and bulk emulation is costly
SMALL_CLASS = 120          # classes with at most this many rows are emulated in full (no plans)
TRACE_RECORDS = 12
VERIFY_RECORDS = 50
COMPILE_BUDGET_S = 15.0  # per build, for compiling fields that are emulated today (plancompile.py)
TRACE_FIELD_SECONDS = 3.0  # stop tracing a field that is this slow
COLUMN_BUDGET_S = 20.0     # a class whose getter fails often is 'unavailable' when the whole column would cost more
DEFAULT_MS = 1.0


class SnapshotError(RuntimeError):
    pass


def snake(text: str) -> str:
    text = re.sub(r'[^0-9A-Za-z]+', '_', text or '').strip('_').lower()
    text = re.sub(r'_+', '_', text)
    if not text:
        return ''
    return ('f_' + text) if text[0].isdigit() else text


# --------------------------------------------------------------------------- columns
@dataclass
class Column:
    table: str
    name: str
    code: str
    record_type: str
    field: object                 # catalog Field (or ExtraField)
    sql_type: str
    kind: str                     # int | real | text | bool | date | enum | ref | json | cash | colour | attribute | stat
    references: str | None = None  # SQL table for references
    labels: dict | None = None
    prefix: str = ''
    origin: str = 'catalog'       # catalog | extra (getter key outside the catalog) | derived (native slot)
    part: str | None = None       # member of a composite getter value stored in this column

    @property
    def key(self):
        return (self.record_type, self.code)


@dataclass
class ExtraField:
    """Catalog-like description of an `extras` key or derived field."""
    name: str
    comment: str
    type: str
    references: str | None = None
    enum: dict | None = None
    enum_ref: str | None = None
    label_inferred: bool = True


# extras (getter keys outside the editor catalog) become columns of these SQL tables when they
# return a value for at least EXTRA_MIN_SHARE of the census records of the type
EXTRA_TABLES = {'player': 'play', 'non_player': 'nnpl', 'club': 'club', 'team': 'team', 'competition': 'comp',
                'nation': 'nati'}
EXTRA_MIN_SHARE = 0.5
# extras the plan derivation traces (manager-critical); every other extra is emulated
TRACED_EXTRAS = frozenset({'Pmor', 'Pfrm', 'Prat', 'POgl', 'Poas', 'POmi', 'PoxG', 'PoxA', 'Poyc', 'Porc',
                           'Pcww', 'Pced', 'PcSd', 'PPra', 'Pcjo', 'POpa', 'POpC', 'POkp', 'POta', 'POtc'})
# derived fields (extras.DERIVED, code 'x:<name>') stored as columns
DERIVED_COLUMNS = {'player': ('condition_stored', 'injury_days_remaining', 'injuries')}
# composite getter values: (code) -> member stored in the column
COMPOSITE = {'Ptaj': 'Ttea'}
# a second column from the same statistic record: (code) -> (column name, member)
STAT_SECOND = {'Prat': ('season_appearances_Prat', 'numb')}
_EXTRA_KINDS = {'int': ('int', 'INTEGER'), 'uint': ('int', 'INTEGER'), 'int64': ('int', 'INTEGER'),
                'uint64': ('int', 'INTEGER'), 'bool': ('bool', 'INTEGER'), 'float': ('real', 'REAL'),
                'double': ('real', 'REAL'), 'string': ('text', 'TEXT'), 'date': ('date', 'TEXT'),
                'colour': ('colour', 'TEXT'), 'color': ('colour', 'TEXT')}
_GENERIC_LABELS = ('Unlabelled', 'Statistic', 'Record reference', 'Colour', 'Range')


def _code_suffix(code):
    return re.sub(r'[^0-9A-Za-z]+', '_', code).strip('_') or 'x'


def extra_columns(table, used):
    """Columns for the extras of `table`'s record type and its derived fields."""
    out = []
    rtype = EXTRA_TABLES.get(table)
    if rtype:
        from . import extras
        for code, info in sorted(extras.EXTRA_FIELDS.get(rtype, {}).items()):
            if not info['records_sampled'] or info['records_with_value'] < EXTRA_MIN_SHARE * info['records_sampled']:
                continue
            label = info['name']
            stat = label.startswith('Statistic') or ("'valu'" in info['sample'] and "'numb'" in info['sample'])
            if stat:
                kind, sql_type, part = 'stat', '', 'valu'
            else:
                kind, sql_type = _EXTRA_KINDS.get(info['kind'], ('json', ''))
                part = None
            base = 'extra' if label.startswith(_GENERIC_LABELS) else snake(label.split('(')[0])
            how = 'only the game layer answers it' if info['view'] == 'game' else "the record's own getter answers it"
            comment = (f"getter key {code!r} outside the editor catalog ({how}); label "
                       + ('inferred from the FourCC spelling and sampled values, not proven'
                          if info['name_inferred'] else 'established from the getter code')
                       + (f'; statistic record {{valu, numb}}: the column holds valu' if stat else ''))
            fld = ExtraField(label, comment, f'extra:{info["kind"]}', label_inferred=info['name_inferred'])
            name = _unique(f'{base}_{_code_suffix(code)}', used)
            out.append(Column(table, name, code, rtype, fld, sql_type, kind, origin='extra', part=part))
            if code in STAT_SECOND:
                second, member = STAT_SECOND[code]
                fld2 = ExtraField(f'{label}: matches (numb)', comment.replace('holds valu', f'holds {member}'),
                                  f'extra:{info["kind"]}', label_inferred=True)
                out.append(Column(table, _unique(second, used), code, rtype, fld2, 'INTEGER', 'stat',
                                  origin='extra', part=member))
    for name in DERIVED_COLUMNS.get(table, ()):
        from . import extras
        rt, d = next((rt, fields[name]) for rt, fields in extras.DERIVED.items() if name in fields)
        kind, sql_type = _EXTRA_KINDS.get(d.kind, ('json', ''))
        fld = ExtraField(d.label, f'derived field: {d.source}', f'derived:{d.kind}', label_inferred=False)
        out.append(Column(table, _unique(name, used), f'x:{name}', rt, fld, sql_type, kind, origin='derived'))
    return out


def _unique(name, used):
    """`name`, or `name_<n>`, not yet in `used` (lower-case: SQLite column names ignore case)."""
    if name.lower() in used:
        n = 2
        while f'{name}_{n}'.lower() in used:
            n += 1
        name = f'{name}_{n}'
    used.add(name.lower())
    return name


def field_kind(f) -> tuple[str, str]:
    t = f.type or ''
    if t in REF_TYPES:
        return 'ref', 'INTEGER'
    if t == 'boolean':
        return 'bool', 'INTEGER'
    if t in ('enum', 'multiple_enum'):
        return 'enum', 'INTEGER'
    if t == 'cash':
        return 'cash', 'INTEGER'
    if t == 'attribute':
        return 'attribute', 'INTEGER'
    if t in INTEGER_TYPES:
        return 'int', 'INTEGER'
    if t == 'real':
        return 'real', 'REAL'
    if t == 'date':
        return 'date', 'TEXT'
    if t == 'string':
        return 'text', 'TEXT'
    if t == 'colour':
        return 'colour', 'TEXT'
    return 'json', ''      # no affinity: JSON text and the occasional scalar are stored as given


def columns_for(catalog, table: str) -> list[Column]:
    """Catalog fields of a SQL table as columns (names unique within the table).

    The list is a function of the catalog, the extras and the field routes, and costs about 4 ms
    a table (name normalisation); a query asks for it per table and once asked for it per column
    (6.7 s of a 10 s profiled statement). It is kept on the catalog object; the Column objects are
    shared and are not modified after this function returns."""
    from . import extras, fieldroutes
    cache = catalog.__dict__.setdefault('_columns_for', {}) if hasattr(catalog, '__dict__') else {}
    key = (table, id(extras.EXTRA_FIELDS), id(fieldroutes.ROUTES), len(fieldroutes.ROUTES))
    hit = cache.get(key)
    if hit is None:
        hit = cache[key] = tuple(_columns_for(catalog, table))
    return list(hit)


# Catalog names that say something else than the key returns in a running career. Phij ("Is
# Injured") reads the editor's STARTING_INJURY table, which is empty once a career runs, so it is
# false for every player; whether a player is out is injury_days_remaining > 0 (player_view's
# is_injured, and fm_db_read's).
NAME_OVERRIDES = {'Phij': 'starting_injury_listed'}


def _columns_for(catalog, table: str) -> list[Column]:
    rtype = TABLES[table]
    parts = [(rtype, '')] + list(PREFIXED.get(table, ()))
    used = set(RESERVED)
    out = []
    for record_type, prefix in parts:
        rt = catalog.record_types.get(record_type)
        if rt is None:
            continue
        seen = set()
        for f in rt.field_list:
            if f.code in seen or (f.type or '') in SKIP_TYPES:
                continue
            seen.add(f.code)
            kind, sql_type = field_kind(f)
            base = NAME_OVERRIDES.get(f.code) or snake(f.name) or snake(f.code) or 'field'
            ref_table = None
            if kind == 'ref':
                ref_table = REF_TABLES.get(f.references or '')
                base += '_idx'
            name = prefix + base
            if name.lower() in used:            # SQLite column names are case-insensitive
                name = f'{name}_{f.code}'
            n = 2
            while name.lower() in used:
                name = f'{prefix}{base}_{f.code}_{n}'
                n += 1
            used.add(name.lower())
            labels = f.enum or (catalog.enums.get(f.enum_ref) if f.enum_ref else None)
            out.append(Column(table, name, f.code, record_type, f, sql_type, kind, ref_table,
                              dict(labels) if labels else None, prefix,
                              part=COMPOSITE.get(f.code) if not prefix and kind == 'ref' else None))
    return _routed(out) + extra_columns(table, used)


# --- fields lane: per-field routes (fieldroutes.py) -------------------------------------------
def _routed(columns):
    """Editor fields whose live value sits under another key of the same record ask that key
    (`fieldroutes.ROUTES`, kind 'alias'): e.g. club Ctbu (answered only from the empty
    STARTING_CLUB_DEBT table) reads the live transfer budget Ctfc. `routed_from` keeps the editor code."""
    from . import fieldroutes
    for col in columns:
        live = fieldroutes.alias(col.record_type, col.code)
        if live:
            col.routed_from = col.code
            col.code = live
    return columns


def _route_note(col):
    from . import fieldroutes
    code = getattr(col, 'routed_from', None)
    if code:
        return f'editor code {code} answered through {col.code}: {fieldroutes.route(col.record_type, code).note}'
    return None


def _route_emulates(col):
    from . import fieldroutes
    return bool(getattr(col, 'routed_from', None)) or fieldroutes.emulate_anyway(col.record_type, col.code)


def _route_reason(col):
    from . import fieldroutes
    return fieldroutes.reason(col.record_type, col.code)
# --- end fields lane ----------------------------------------------------------------------------


# --------------------------------------------------------------------------- live enumeration
@dataclass
class LiveTable:
    kind: str
    pointers: list
    identity: tuple
    classes: list                 # class name per idx ('' for null entries)
    uids: list
    rids: list

    def uid_index(self):
        if not hasattr(self, '_uid_index'):
            index = {}
            for i, (p, u) in enumerate(zip(self.pointers, self.uids)):
                if p:
                    index.setdefault(u, i)
            self._uid_index = index
        return self._uid_index


def enumerate_table(engine, kind: str) -> LiveTable:
    pointers, identity = engine.table_entries(kind)
    windows = getattr(engine, 'windows', None)
    if windows is not None:
        present = [p for p in pointers if p]
        payload, bad = windows(present, 0x14)
        heads = list(struct.iter_unpack('<Q4xII', payload))
        for k in bad:
            heads[k] = None
    else:
        heads = [None if head is None else struct.unpack('<Q4xII', head)
                 for head in engine.read_many([(p, 0x14) for p in pointers if p])]
    classes, uids, rids = [], [], []
    names = {}                      # vtable -> class name
    base = engine.base
    it = iter(heads)
    for p in pointers:
        if not p:
            classes.append('')
            uids.append(None)
            rids.append(None)
            continue
        head = next(it)
        if head is None:
            classes.append('unreadable')
            uids.append(None)
            rids.append(None)
            continue
        vtable, uid, rid = head
        name = names.get(vtable)
        if name is None:
            entry = tables.CLASSES.get(vtable - base)
            name = names[vtable] = entry[0] if entry else f'vtable@{vtable - base:#x}'
        classes.append(name)
        uids.append(uid)
        rids.append(rid or uid)
    return LiveTable(kind, pointers, identity, classes, uids, rids)


def table_rows(live: LiveTable, record_type: str) -> list[int]:
    wanted = set(tables.RECORD_TYPES[record_type].classes)
    return [i for i, (p, c) in enumerate(zip(live.pointers, live.classes))
            if p and c != 'unreadable' and (not wanted or c in wanted)]


# --------------------------------------------------------------------------- plans
def plan_store(engine, root: Path | None = None) -> 'PlanStore':
    """The plan cache of this game build: `<root>/plans/<plugin sha256>.v2.json`."""
    from .engine import cache_root
    root = Path(root) if root else cache_root()
    return PlanStore(root / 'plans' / f'{engine.plugin_sha256}.{PLAN_FILE_TAG}.json', engine.build,
                     engine.plugin_sha256)


PLAN_FILE_TAG = 'v2'     # the file name carries the format, so checkouts on format 1 never overwrite it
SHIPPED_PLANS = Path(__file__).with_name('data')    # plans-<plugin sha256>.v2.json.gz per pinned game build
SHIPPED_VERIFY_RECORDS = 6                          # records per class a shipped direct plan must agree on


def shipped_plans(sha256: str, directory: Path | None = None) -> dict | None:
    """The plan document shipped with the package for this plugin build, or None.

    The file is the plan cache of a completed derivation (`bulkplans.cache_document`), gzipped.
    It is keyed by the plugin SHA256 like the cache, so it only ever applies to the exact game
    build it was derived on; its direct plans are still checked against the getter before
    their first use (`verify_shipped`)."""
    import gzip
    path = (directory or SHIPPED_PLANS) / f'plans-{sha256}.{PLAN_FILE_TAG}.json.gz'
    try:
        doc = json.loads(gzip.decompress(path.read_bytes()))
    except (OSError, ValueError, EOFError):
        return None
    if doc.get('sha256') != sha256 or doc.get('format') != bulkplans.FORMAT or not isinstance(doc.get('plans'), dict):
        return None
    return doc['plans']


def carried_plans(sha256: str, directory: Path | None = None) -> tuple[str, dict] | None:
    """(source build sha256, plans) to start a build that has no plans of its own from.

    A plan is a chain of offsets inside a record, with no plugin address in it, and a game patch
    seldom moves a database field: on 27.0.1 every one of the 389 plans derived afresh before this
    existed equalled the 27.0.0 plan of the same class and field. So a new build starts from the
    plans shipped for another build instead of deriving them again (about 40 minutes with the game
    running). They are candidates only: each direct plan is compared with this build's getter on
    SHIPPED_VERIFY_RECORDS records before its first use (`verify_shipped`), and one that disagrees
    is demoted to emulation, as a moved field would make it."""
    import gzip
    for path in sorted((directory or SHIPPED_PLANS).glob(f'plans-*.{PLAN_FILE_TAG}.json.gz')):
        try:
            doc = json.loads(gzip.decompress(path.read_bytes()))
        except (OSError, ValueError, EOFError):
            continue
        if doc.get('sha256') and doc['sha256'] != sha256 and doc.get('format') == bulkplans.FORMAT \
                and isinstance(doc.get('plans'), dict):
            return doc['sha256'], doc['plans']
    return None


def _mapped_build(sha256: str) -> bool:
    """Whether `sha256` is the game build this process addresses through an address map (a real
    build after a game update; never a test double or the pinned build)."""
    try:
        from .. import address_book
        return address_book.ACTIVE.get('state') == 'mapped' and address_book.ACTIVE.get('sha256') == sha256
    except Exception:  # noqa: BLE001
        return False


class PlanStore:
    """Verified direct plans per (record class, code), cached on disk by plugin SHA256.

    Format-1 plans (`<sha>.json` or `<sha>.v1.json`, written by older checkouts) are read as
    `prior`: their direct plans are re-verified, never trusted."""

    def __init__(self, path: Path, build: str, sha256: str):
        self.path, self.build, self.sha256 = Path(path), build, sha256
        self.plans = defaultdict(dict)
        self.prior = defaultdict(dict)       # direct plans of an older cache format: re-verified, not trusted
        self.shipped = 0                     # (class, code) plans taken from the package data
        if self.path.is_file():
            try:
                doc = json.loads(self.path.read_text())
                if doc.get('sha256') == sha256 and doc.get('format') == bulkplans.FORMAT:
                    for cls, fields in doc['plans'].items():
                        self.plans[cls].update(fields)
            except (OSError, ValueError):
                pass
        # Plans shipped for this exact plugin build fill what the cache does not have, so a new
        # user does not wait for the derivation. Direct ones carry origin 'shipped' and no
        # 'load_verified' until verify_shipped has compared them with the getter.
        for cls, fields in (shipped_plans(sha256) or {}).items():
            have = self.plans[cls] if cls in self.plans else {}
            for code, plan in fields.items():
                if code not in have:
                    plan = dict(plan)
                    if plan.get('status') == 'direct':
                        plan['origin'] = 'shipped'
                        plan.pop('load_verified', None)
                    self.plans[cls][code] = plan
                    self.shipped += 1
        # A build with no plans at all (a game update): candidates carried from another build.
        self.carried_from = None
        if not self.plans and _mapped_build(sha256):
            carried = carried_plans(sha256)
            if carried:
                self.carried_from, source = carried
                for cls, fields in source.items():
                    for code, plan in fields.items():
                        plan = dict(plan)
                        plan['origin'] = 'carried'
                        plan['carried_from'] = self.carried_from[:12]
                        plan.pop('load_verified', None)
                        self.plans[cls][code] = plan
                        self.shipped += 1
        for old in (self.path.with_name(f'{sha256}.v1.json'), self.path.with_name(f'{sha256}.json')):
            if old == self.path or not old.is_file():
                continue
            try:
                doc = json.loads(old.read_text())
            except (OSError, ValueError):
                continue
            if doc.get('sha256') != sha256 or doc.get('format') not in bulkplans.OLD_FORMATS:
                continue
            for cls, fields in doc['plans'].items():
                for c, p in fields.items():
                    if p.get('status') == 'direct':
                        self.prior[cls].setdefault(c, p)

    def complete(self, by_class) -> bool:
        return not any(self.missing(cls, codes) for cls, codes in by_class.items())

    def unverified_shipped(self, cls) -> dict:
        """Shipped direct plans of a class that have not been compared with the getter yet."""
        return {c: p for c, p in self.plans.get(cls, {}).items()
                if p.get('status') == 'direct' and p.get('origin') in ('shipped', 'carried')
                and 'load_verified' not in p}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + '.tmp')
        text = json.dumps(bulkplans.cache_document(self.build, self.sha256, self.plans), indent=0)
        try:
            # newline='\n': Windows text mode would write CRLF and fail the size check below.
            with open(tmp, 'w', encoding='utf-8', newline='\n') as handle:   # a full disk raises here, before the rename
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            if tmp.stat().st_size != len(text.encode()):
                raise OSError(f'short write of {tmp}')
        except OSError:
            tmp.unlink(missing_ok=True)
            raise
        os.replace(tmp, self.path)

    def get(self, cls, code):
        return self.plans.get(cls, {}).get(code)

    def missing(self, cls, codes):
        """Codes without a plan, plus version-1 plans that the current derivation can improve."""
        have = self.plans.get(cls, {})
        improvable = ("'not handled'", 'value not explained', 'no single load explains')
        return [c for c in codes if c not in have
                or (have[c].get('status') != 'direct' and have[c].get('v', 1) < bulkplans.DERIVE_VERSION
                    and any(r in have[c].get('reason', '') for r in improvable))
                # a plan carried from another build that this build's getter contradicted: the
                # field moved or changed, so it is derived again for this build
                or (have[c].get('status') != 'direct' and have[c].get('origin') == 'carried'
                    and 'disagreed on load' in have[c].get('reason', ''))]


def _extra_view(col: Column):
    from . import extras
    return extras.EXTRA_FIELDS.get(col.record_type, {}).get(col.code, {}).get('view')


def traced(col: Column) -> bool:
    """Whether the plan derivation traces this column's code (derived fields never; extras only
    the manager-critical ones in TRACED_EXTRAS)."""
    if col.origin == 'derived' or str(col.code).startswith('x:'):
        return False            # 'x:' codes are derived fields; an editor field routed to one (fieldroutes
                                # alias, e.g. nati cwsd -> x:transfer_window_cwsd) is no getter key either
    if col.origin == 'extra':
        return col.code in TRACED_EXTRAS and col.part != 'numb'
    return True


def _spread(items, count, rng):
    if len(items) <= count:
        return list(items)
    step = len(items) / count
    picked = [items[int(i * step)] for i in range(count)]
    return picked


RETRY_REASONS = ('null in every sampled record', 'constant in the sample', 'sampled records gave',
                 'no single load explains')


def _retry(plan) -> bool:
    return plan.get('status') == 'emulate-only' and any(r in plan.get('reason', '') for r in RETRY_REASONS)


def measure_ms(engine, records, code) -> float:
    """Median ms of a warm getter call on the main VM (each record is called once to warm it)."""
    times = []
    for record in records:
        engine.get_property(record, code)
        result = engine.get_property(record, code)
        times.append(result.stats.seconds * 1000)   # the VM's own timing of the call
    times.sort()
    return round(times[len(times) // 2], 4) if times else DEFAULT_MS


def derive_class_plans(engine, store: PlanStore, cls: str, records: list[int], codes: list[str],
                       names: dict, log=None, extra=None, seed=None) -> dict:
    """Trace, derive and verify plans for one class (only codes missing from the store).

    `extra` are preferred records for the second sampling stage (e.g. the managed squad);
    `seed` is another lane's plans.json `plans` mapping, used as unverified candidates."""
    todo = store.missing(cls, codes)
    if not todo:
        return {'traced': 0, 'verified': 0, 'demoted': 0, 'seconds': 0.0}
    started = time.time()
    rng = random.Random(f'{store.sha256}:{cls}')
    reverified = 0
    prior = {c: store.prior[cls][c] for c in todo if c in store.prior.get(cls, {})}
    if prior:
        # older-format direct plans: verify against the current getter on spread + random records
        # instead of tracing again; any disagreement sends the code through the full derivation
        pool0 = list(dict.fromkeys(records))
        check = list(dict.fromkeys(_spread(pool0, TRACE_RECORDS, rng) + rng.sample(pool0, min(VERIFY_RECORDS,
                                                                                               len(pool0)))))
        values = bulkplans.evaluate(engine.read_many, check, prior)
        kept = {}
        for code, plan in prior.items():
            compared, ok, distinct = 0, True, set()
            for record, got in zip(check, values[code]):
                expected = bulkplans.canonical(engine.get_property(record, code))
                if isinstance(expected, Missing) and plan.get('fallback') and expected.reason.endswith('_fseeko'):
                    continue
                compared += 1
                distinct.add(repr(expected))
                if not bulkplans.same(got, expected):
                    ok = False
                    break
            if ok and compared >= 10 and len(distinct) >= 2:
                kept[code] = {**plan, 'v': bulkplans.DERIVE_VERSION, 'reverified': compared, 'mismatches': 0,
                              'origin': 'reverified-v1'}
        store.plans[cls].update(kept)
        reverified = len(kept)
        todo = [c for c in todo if c not in kept]
        if not todo:
            store.save()
            if log:
                log(f'plans {cls}: {reverified} older direct plans re-verified, {time.time() - started:.1f}s')
            return {'traced': 0, 'verified': reverified, 'demoted': 0, 'seconds': time.time() - started}
    # adaptive sampling: spread records first, then managed-club and random records for fields
    # that came out unset / constant / mixed (sampling artefacts), up to ~200 records.
    pool = list(dict.fromkeys(records))
    preferred = [r for r in (extra or []) if r in set(pool)]
    stages = [_spread(pool, TRACE_RECORDS, rng)]
    rest = [r for r in pool if r not in set(stages[0])]
    stage2 = list(dict.fromkeys(preferred + rng.sample(rest, min(36, len(rest)))))[:48]
    rest = [r for r in rest if r not in set(stage2)]
    stage3 = rng.sample(rest, min(150, len(rest)))
    stages += [stage2, stage3]
    tracer = engine.plan_tracer()
    observations = {code: [] for code in todo}
    spent = {code: 0.0 for code in todo}
    slow = set()
    read = engine.cached_read
    derived = {}
    traced = set()
    for stage_no, stage in enumerate(stages):
        if stage_no == 0:
            codes_now = list(todo)
        else:
            codes_now = [c for c, p in derived.items() if c not in slow and _retry(p)]
        if not codes_now or not stage:
            continue
        traced.update(stage)
        for code in codes_now:
            for record in stage:
                _, o = tracer.observe(record, code)
                observations[code].append(o)
                spent[code] += o.ms / 1000
                if spent[code] > TRACE_FIELD_SECONDS * (1 + stage_no):
                    slow.add(code)
                    break
            plan = bulkplans.derive(observations[code], read)
            if code in slow and plan.get('status') == 'direct':
                plan = {'status': 'emulate-only', 'reason': 'too slow to trace every sample record',
                        'records': len(observations[code]), 'ms': plan.get('ms')}
            derived[code] = plan
    tracer.close()
    for code, plan in derived.items():
        if plan.get('status') == 'emulate-only' and _retry(plan) and plan.get('records', 0) >= 150:
            plan['note'] = f'stayed {plan["reason"]} across {plan["records"]} sampled records'
    primary = next((entry[2] for entry in tables.CLASSES.values() if entry[0] == cls), None)
    known = {c: p for c, p in store.plans.get(cls, {}).items() if p.get('status') == 'direct'}
    bulkplans.derive_blobs(derived, observations, read, names, primary, known)
    # seed plans (another lane's tracer): candidates only, verified like ours
    for code, plan in derived.items():
        candidate = (seed or {}).get(cls, {}).get(code)
        if plan.get('status') != 'direct' and candidate and candidate.get('status') == 'direct':
            derived[code] = {**{k: candidate[k] for k in ('chain', 'width', 'signed', 'type', 'transform')},
                             'zero_null': bool(candidate.get('null_pointer_is_unset')), 'status': 'direct',
                             'records': plan.get('records'), 'ms': plan.get('ms'), 'origin': 'seed',
                             'replaced_reason': plan.get('reason')}
    # realistic cost of emulation: warm calls on the main VM (tracing hooks inflate timings)
    for code, plan in derived.items():
        if plan.get('status') != 'direct' and plan.get('reason') != 'getter does not handle this code':
            plan['vm_ms'] = measure_ms(engine, stages[0][:3], code)
    # verification on separate records
    others = [r for r in pool if r not in traced]
    check = rng.sample(others, min(VERIFY_RECORDS, len(others)))
    direct = {c: p for c, p in derived.items() if p.get('status') == 'direct'}
    verified = demoted = 0
    if direct and len(check) < 10:
        for code in direct:
            derived[code] = {**derived[code], 'status': 'emulate-only',
                             'reason': f'only {len(check)} records left to verify the plan'}
            demoted += 1
    elif direct:
        values = bulkplans.evaluate(engine.read_many, check, direct)
        for code, plan in direct.items():
            mismatches, compared, skipped, example = 0, 0, 0, None
            for record, got in zip(check, values[code]):
                result = engine.get_property(record, code)
                expected = bulkplans.canonical(result)
                if isinstance(expected, Missing) and plan.get('fallback') and expected.reason.endswith('_fseeko'):
                    skipped += 1
                    continue
                compared += 1
                if not bulkplans.same(got, expected):
                    mismatches += 1
                    if example is None:
                        example = f'record {record:#x}: plan {got!r} vs getter {expected!r}'
            if mismatches:
                derived[code] = {'status': 'emulate-only', 'records': plan.get('records'), 'ms': plan.get('ms'),
                                 'vm_ms': measure_ms(engine, check[:3], code),
                                 'reason': f'verification: {mismatches} of {compared} records disagreed ({example})'}
                demoted += 1
            else:
                derived[code] = {**plan, 'verified': compared, 'mismatches': 0, 'verify_skipped': skipped}
                verified += 1
    store.plans[cls].update(derived)
    store.save()
    seconds = time.time() - started
    if log:
        log(f'plans {cls}: {len(todo)} codes traced, {verified} direct verified, {demoted} demoted, '
            f'{reverified} older plans re-verified, {seconds:.1f}s')
    return {'traced': len(todo), 'verified': verified + reverified, 'demoted': demoted, 'seconds': seconds}


def verify_shipped(engine, store: PlanStore, cls: str, records: list[int], log=None) -> dict:
    """Spot-check the shipped direct plans of one class before their first use: on
    SHIPPED_VERIFY_RECORDS records (spread over the table plus random ones) every plan must
    give the getter's value, with the comparison the derivation uses. A plan that disagrees is
    demoted to emulation, exactly as a derived plan that fails its verification; the others are
    marked `load_verified` and the cache file is written, so the check runs once per cache."""
    todo = store.unverified_shipped(cls)
    pool = list(dict.fromkeys(r for r in records if r))
    if not todo or not pool:
        return {'checked': 0, 'demoted': 0}
    rng = random.Random(f'{store.sha256}:{cls}:shipped')
    half = SHIPPED_VERIFY_RECORDS // 2
    check = list(dict.fromkeys(_spread(pool, half, rng) + rng.sample(pool, min(SHIPPED_VERIFY_RECORDS, len(pool)))))
    check = check[:SHIPPED_VERIFY_RECORDS]
    values = bulkplans.evaluate(engine.read_many, check, todo)
    demoted = 0
    for code, plan in todo.items():
        mismatches, compared, example = 0, 0, None
        for record, got in zip(check, values[code]):
            expected = bulkplans.canonical(engine.get_property(record, code))
            if isinstance(expected, Missing) and plan.get('fallback') and expected.reason.endswith('_fseeko'):
                continue
            compared += 1
            if not bulkplans.same(got, expected):
                mismatches += 1
                if example is None:
                    example = f'record {record:#x}: plan {got!r} vs getter {expected!r}'
        if mismatches:
            store.plans[cls][code] = {
                'status': 'emulate-only', 'records': plan.get('records'), 'ms': plan.get('ms'),
                'vm_ms': measure_ms(engine, check[:3], code), 'origin': plan.get('origin', 'shipped'),
                'reason': f'{plan.get("origin", "shipped")} plan: {mismatches} of {compared} records disagreed on load ({example})'}
            demoted += 1
        else:
            store.plans[cls][code] = {**plan, 'load_verified': compared}
    store.save()
    if log:
        log(f'plans {cls}: {len(todo)} shipped direct plans checked on {len(check)} records, {demoted} demoted')
    return {'checked': len(todo), 'demoted': demoted}


# --------------------------------------------------------------------------- value conversion
class Resolver:
    def __init__(self, live_by_sql: dict):
        self.live = live_by_sql          # SQL table -> LiveTable
        self.unresolved = []             # (table, column, idx, raw json)

    def _lookup(self, sql_table, uid, rid):
        live = self.live.get(sql_table)
        if live is None or uid is None:
            return None
        i = live.uid_index().get(uid)
        if i is None:
            return None
        if rid is not None and live.rids[i] != rid:
            return None
        return i

    def ref(self, column: Column, idx: int, value):
        if isinstance(value, Ref):
            targets = [column.references] if column.references else []
            targets += [t for t in REF_FOURCC.get(value.table or '', ()) if t not in targets]
            for target in targets:
                hit = self._lookup(target, value.unique_id, value.random_id)
                if hit is not None:
                    return hit
            self.unresolved.append((column.table, column.name, idx, json.dumps(
                {'table': value.table, 'unique_id': value.unique_id, 'random_id': value.random_id})))
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            self.unresolved.append((column.table, column.name, idx, json.dumps(value, default=str)))
            return None
        # An integer from the getter is the referenced row's table index, not its unique id:
        # for nationality (Pnat) the index reading agrees with the Nation record reference (Pnti)
        # on 32,157 of 32,157 players, the unique-id reading on 0 of 30,294.
        live = self.live.get(column.references) if column.references else None
        if live is not None and 0 <= value < len(live.pointers) and live.pointers[value]:
            return value
        if value != -1:
            self.unresolved.append((column.table, column.name, idx, json.dumps({'index': value})))
        return None


def member(column: Column, value):
    """The `column.part` member of a composite getter value (canonical JSON text or a dict):
    `{valu, numb}` statistic records, and the `Ttea` team reference inside Ptaj's
    `{Pjle, Psjo, Ttea}` contract record."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if not isinstance(value, dict):
        return value if column.kind != 'ref' else None
    got = value.get(column.part)
    if isinstance(got, dict) and 'unique_id' in got:
        return Ref(got.get('unique_id'), got.get('random_id'), got.get('table'))
    if isinstance(got, (dict, list)):
        return json.dumps(got, sort_keys=True)
    return got


def to_sql(column: Column, idx: int, value, resolver: Resolver):
    if value is None or isinstance(value, Missing):
        return None
    if column.part:
        value = member(column, value)
        if value is None:
            return None
    if column.kind == 'ref':
        return resolver.ref(column, idx, value)
    if isinstance(value, Ref):
        return json.dumps({'table': value.table, 'unique_id': value.unique_id, 'random_id': value.random_id})
    if isinstance(value, bool):
        return int(value)
    return value


# --------------------------------------------------------------------------- computed columns
class Computed:
    """Columns that are not getter values, for all rows of a table or for some of them:

    * `player.is_virtual`: the record class is VIRTUAL_PLAYER;
    * `team.parent_club_idx`: the club pointer at team record +0x30 (the pointer `tables.managed`
      reads), kept when it is a live CLUB table entry (national sides point elsewhere);
      `team.club_idx`: the CLUB record that is this team (same unique id: first teams, and B/U21
      sides that are clubs of their own), else the owning club (reserve and youth teams);
    * `person.contract_team_idx` / `contract_club_idx`: the first team of the person's main
      contract and that team's club (the parent club of a player out on loan, where Pcti and
      Ptaj both name the loan club). Layout as world.player_clubs / loan_contracts: main
      contract pointer at PERSON - 0x98, a FULL or BASIC contract whose +8 is the person, first
      team at +0x10, the team's club at +0x30;
    * `person.contract_squad_status_code`: the agreed playing time (squad status) of a FULL main
      contract, the byte at +0x54 its slot 32 accessor returns (hand-built playing_time.decode).

    `columns(table, idxs, touch)` returns ([(name, {idx: value})], statistics); `touch` is the
    dependency callback of `freshness.Recorder` (positions in `idxs`, addresses, length)."""
    TABLES = ('player', 'team', 'person')

    def __init__(self, engine, live, club_rows):
        self.engine, self.live, self.club_rows = engine, live, club_rows
        self._club_index = self._by_uid = self._team_index = None

    def available(self, table, wanted) -> bool:
        if table == 'player':
            return True
        if table == 'team':
            return 'club' in wanted and 'clubs' in self.live and 'teams' in self.live
        return {'team', 'club'} <= set(wanted) and {'clubs', 'teams', 'people'} <= set(self.live)

    def _windows(self, addresses, length):
        windows = getattr(self.engine, 'windows', None)
        if windows is not None:
            return windows(addresses, length)
        from .memory import _join_windows
        return _join_windows(self.engine.read_many([(a, length) for a in addresses]), length)

    def _u64s(self, addresses, positions, touch, depth=0):
        """One u64 per address (0 where unreadable), read as one fixed-stride buffer."""
        if not addresses:
            return []
        if touch is not None:
            touch(positions, addresses, 8, depth)
        payload, bad = self._windows(addresses, 8)
        values = [v for (v,) in struct.iter_unpack('<Q', payload)]
        for k in bad:
            values[k] = 0
        return values

    def club_index(self):
        if self._club_index is None:
            self._club_index = {p: i for i, p in enumerate(self.live['clubs'].pointers) if p}
        return self._club_index

    def columns(self, table, idxs, touch=None):
        return getattr(self, '_' + table)(list(idxs), touch)

    def _player(self, idxs, touch):
        classes = self.live['people'].classes
        return [('is_virtual', {i: int(classes[i] == 'VIRTUAL_PLAYER') for i in idxs})], True

    def _team(self, idxs, touch):
        teams, clubs = self.live['teams'], self.live['clubs']
        club_index = self.club_index()
        pointers = self._u64s([teams.pointers[i] + 0x30 for i in idxs], list(range(len(idxs))), touch)
        parent = {i: club_index.get(ptr) for i, ptr in zip(idxs, pointers)}
        if self._by_uid is None:
            rows = self.club_rows
            self._by_uid = {u: i for i, u in enumerate(clubs.uids) if i in rows and u is not None}
        by_uid = self._by_uid
        return ([('parent_club_idx', parent), ('club_idx', {i: by_uid.get(teams.uids[i], parent[i]) for i in idxs})],
                (sum(1 for v in parent.values() if v is not None), len(idxs)))

    def _person(self, idxs, touch):
        from .. import world
        people, teams = self.live['people'], self.live['teams']
        club_index = self.club_index()
        if self._team_index is None:
            self._team_index = {p: i for i, p in enumerate(teams.pointers) if p}
        team_index = self._team_index
        from .sources import contracts as K
        kinds = {self.engine.base + world.TYPES[k][0] for k in ('full_contract', 'basic_contract')}
        full = self.engine.base + world.TYPES['full_contract'][0]
        mains = self._u64s([people.pointers[i] - 0x98 for i in idxs], list(range(len(idxs))), touch)
        with_main = [(k, i, ptr) for k, (i, ptr) in enumerate(zip(idxs, mains)) if ptr]
        size = K.SQUAD_STATUS_AT + 8 if self._squad_status_ok() else 0x18
        payload, bad = b'', []
        if with_main:
            addresses = [ptr for _, _, ptr in with_main]
            if touch is not None:
                touch([k for k, _, _ in with_main], addresses, size, 1)
            payload, bad = self._windows(addresses, size)
        skip = set(bad)
        team_of, position, checked, squad = {}, {}, 0, {}
        for n, (k, i, _) in enumerate(with_main):
            if n in skip:
                continue
            vtable, owner, first = struct.unpack_from('<QQQ', payload, n * size)
            if vtable not in kinds or owner != people.pointers[i]:
                continue
            checked += 1
            if vtable == full and size > 0x18:
                squad[i] = payload[n * size + K.SQUAD_STATUS_AT]
            if first in team_index:
                team_of[i] = team_index[first]
                position[i] = k
        club_ptrs = self._u64s([teams.pointers[t] + 0x30 for t in team_of.values()],
                               [position[i] for i in team_of], touch, 1)
        contract_team, contract_club = {}, {}
        for (i, t), ptr in zip(team_of.items(), club_ptrs):
            contract_team[i] = t
            contract_club[i] = club_index.get(ptr) if ptr else None
        return ([('contract_team_idx', contract_team), ('contract_club_idx', contract_club),
                 ('contract_squad_status_code', squad)],
                (checked, len(team_of), len(idxs)))

    def _squad_status_ok(self) -> bool:
        """The FULL_CONTRACT slot 32 accessor still returns the byte at +0x54 (checked once)."""
        if getattr(self, '_squad_ok', None) is None:
            from .. import world
            from .sources import contracts as K
            base = self.engine.base
            try:
                vt = base + world.TYPES['full_contract'][0]
                slot = struct.unpack('<Q', self.engine.read(vt + K.SQUAD_STATUS_SLOT * 8, 8))[0]
                code = self.engine.read(base + K.SQUAD_STATUS_GETTER, 8)
                self._squad_ok = slot == base + K.SQUAD_STATUS_GETTER and code == K.SQUAD_STATUS_GETTER_BYTES
            except Exception:  # noqa: BLE001 - unreadable: the column stays empty
                self._squad_ok = False
        return self._squad_ok


def layout_signature(engine) -> str:
    """Digest of what a snapshot written by this reader holds: every core table's columns, every
    declared collection table with its columns and layout token, the collection views and the view
    builder's source. A snapshot written with another signature lacks tables or columns that this
    reader's schema and guides name (a reader upgrade adds source modules and columns), so
    `tools.current_snapshot` builds it again instead of answering "no such table". Kept on the
    engine: the collection modules are asked once a process (about 0.3 s). '' when a collection
    module failed to describe its tables just now (no verdict; the snapshot is not rebuilt for it)."""
    cached = getattr(engine, '_layout_signature', None)
    if cached:
        return cached
    import hashlib
    from . import sources, views
    h = hashlib.sha256()
    for table in sorted(TABLES):
        h.update(repr((table, [(c.name, c.code, c.sql_type, c.kind) for c in columns_for(engine.catalog, table)])).encode())
    found, failures = sources.discover(engine)
    for module, t in sorted(found, key=lambda mt: mt[1].name):
        # the views with their SQL: a changed view template must reach existing snapshots
        h.update(repr((module, t.name, [(c.name, c.sql_type) for c in t.columns], getattr(t, 'layout', None),
                       sorted((getattr(t, 'views', None) or {}).items(), key=lambda kv: kv[0]))).encode())
    try:
        for module, view, _description, template, _policy in sorted(sources.discover_views(engine)):
            h.update(repr((module, view, template)).encode())
        h.update(Path(views.__file__).read_bytes())
    except Exception:  # noqa: BLE001 - the tables above already identify the layout
        pass
    if failures:            # a module that fails now would change the digest again when it works: no verdict,
        return ''           # and nothing is kept, so the next call asks the modules again
    signature = h.hexdigest()[:24]
    try:
        engine._layout_signature = signature
    except AttributeError:
        pass
    return signature


# --------------------------------------------------------------------------- build
@dataclass
class ColumnState:
    table: str
    column: str
    cls: str
    rows: int
    source: str          # direct | emulated
    status: str          # ready (stored at build) | on_demand (computed when a query names it) | unavailable
    ms: float
    note: str = ''
    missing: Counter = field(default_factory=Counter)


class Build:
    """One snapshot build (or refresh) for an Engine; see module docstring."""

    def __init__(self, engine, *, root: Path | None = None, tables_wanted=None, log=None,
                 column_budget=COLUMN_BUDGET_S, build_budget=None, progress=None, derive_plans=True):
        # `build_budget` was the eager-emulation budget; a build emulates nothing now and the
        # argument is accepted and ignored so existing callers keep working.
        from .engine import cache_root
        self.engine = engine
        self.root = Path(root) if root else cache_root()
        self.log = log or (lambda msg: None)
        self._progress = progress
        self.wanted = list(tables_wanted or TABLES)
        self.column_budget, self.build_budget = column_budget, build_budget
        self.timing = {}
        self.notes = []
        self.store = plan_store(engine, self.root)
        # False (tool calls): shipped plans are checked, missing ones are not derived (tens of
        # minutes); a class without a plan has its columns computed on demand
        self.derive_plans = derive_plans
        self.prepared = False

    def _phase(self, name, started):
        self.timing[name] = round(self.timing.get(name, 0) + time.time() - started, 3)

    def progress(self, phase, done, total, message):
        if self._progress:
            try:
                self._progress(phase, done, total, message)
            except Exception:  # noqa: BLE001 - progress reporting never stops a build
                pass

    def prepare(self):
        """Save identity, live table enumeration, columns and rows (no getter calls)."""
        engine = self.engine
        engine.fresh()
        save = engine.save_info()
        self.save = save
        out_dir = self.root / save.save_key
        self.path = out_dir / 'snapshot.sqlite'
        started = time.time()
        needed_kinds = {tables.RECORD_TYPES[TABLES[t]].table for t in TABLES}
        self.live = {kind: enumerate_table(engine, kind) for kind in sorted(needed_kinds)}
        self.live_by_sql = {t: self.live[tables.RECORD_TYPES[TABLES[t]].table] for t in TABLES}
        self._phase('enumerate', started)
        self.columns = {t: columns_for(engine.catalog, t) for t in self.wanted}
        self.rows = {t: table_rows(self.live_by_sql[t], TABLES[t]) for t in self.wanted}
        self.prepared = True
        return self

    def run(self) -> Path:
        engine = self.engine
        with engine.lock:
            t0 = time.time()
            if not self.prepared:
                self.prepare()
            from .engine import MIN_FREE_BUILD, require_space
            require_space(self.root, MIN_FREE_BUILD, 'Snapshot build')     # before any write
            self.path.parent.mkdir(parents=True, exist_ok=True)
            started = time.time()
            self._plans()
            self._phase('plans', started)
            self.progress('direct', 0, len(self.wanted), 'reading direct columns')
            from . import freshness
            self.recorder = freshness.Recorder(engine)
            data = {t: self._read_table(t) for t in self.wanted}
            # re-check headers and date; rebuild moved tables once
            started = time.time()
            save = self.save
            moved = []
            for kind, live in self.live.items():
                if engine.table_info(kind)['identity'] != live.identity:
                    moved.append(kind)
            date_now = engine.game_date()
            if date_now != save.game_date:
                self.notes.append(f'game date moved during the build ({save.game_date} -> {date_now}); '
                                  'the snapshot mixes both days')
            if moved:
                self.notes.append(f'tables changed during the build and were re-read once: {", ".join(moved)}')
                for kind in moved:
                    self.live[kind] = enumerate_table(engine, kind)
                self.live_by_sql = {t: self.live[tables.RECORD_TYPES[TABLES[t]].table] for t in TABLES}
                for t in self.wanted:
                    if tables.RECORD_TYPES[TABLES[t]].table in moved:
                        self.rows[t] = table_rows(self.live_by_sql[t], TABLES[t])
                        self.recorder.forget(t)
                        data[t] = self._read_table(t)
                still = [k for k in moved if engine.table_info(k)['identity'] != self.live[k].identity]
                if still:
                    self.notes.append(f'tables still changing after the re-read: {", ".join(still)}')
            self._phase('recheck', started)
            started = time.time()
            self.progress('write', 0, 1, 'writing the snapshot')
            self._write(data)
            self._phase('write', started)
            self.timing['total'] = round(time.time() - t0, 3)
            with sqlite3.connect(self.path) as conn:
                conn.execute('INSERT OR REPLACE INTO _build VALUES (?, ?)', ('timing', json.dumps(self.timing)))
            self._settle()
            self.log(f'snapshot {self.path} built in {self.timing["total"]}s: {self.timing}')
            return self.path

    def _settle(self):
        """The game is not paused during a build: a day can pass or a page can change after it was
        read. The content check that every query runs (`freshness.refresh`) is run once here, on
        the finished file: every page a direct row was read from is read again, rows on pages
        that moved are evaluated again, table vectors are compared and the game date is set to
        the date of the check. (This replaces the per-table date stamps and whole-table re-reads
        of the robust lane's consistency.py: the check is per page, and it is the same one that
        keeps the snapshot current afterwards.)"""
        if not hasattr(self.engine, 'refresh_memory'):
            return
        from . import freshness
        started = time.time()
        try:
            result = freshness.refresh(self.engine, self.path, force=True)
        except Exception as exc:  # noqa: BLE001 - the build stands; the next query checks again
            self.notes.append(f'content check after the build did not run: {type(exc).__name__}: {exc}')
            return
        self.settled = result
        self.timing['settle'] = round(time.time() - started, 3)
        self.timing['total'] = round(self.timing['total'] + self.timing['settle'], 3)
        if result.get('rows_refreshed') or result.get('records_moved'):
            self.log(f'the game moved during the build: {result.get("rows_refreshed")} rows read again, '
                     f'records moved {result.get("records_moved")}')

    # ------------------------------------------------------------------ plans
    def plan_codes(self):
        """(kind, class) -> codes the plan derivation traces, and their names."""
        by_class = defaultdict(set)     # (kind, class) -> codes
        names = defaultdict(dict)
        for t in self.wanted:
            live = self.live_by_sql[t]
            classes = Counter(live.classes[i] for i in self.rows[t])
            for cls, count in classes.items():
                if count <= SMALL_CLASS:
                    continue
                for col in self.columns[t]:
                    if not traced(col):
                        continue
                    by_class[(live.kind, cls)].add(col.code)
                    names[(live.kind, cls)][col.code] = col.field.name
        return by_class, names

    def plans_missing(self):
        """Number of (class, code) pairs still to derive (0: a build needs no plan derivation)."""
        by_class, _ = self.plan_codes()
        return sum(len(self.store.missing(cls, codes)) for (_, cls), codes in by_class.items())

    def _plans(self):
        engine = self.engine
        stats = Counter()
        by_class, names = self.plan_codes()
        total = sum(len(self.store.missing(cls, codes)) for (_, cls), codes in by_class.items())
        done = 0
        self.progress('plans', 0, total, f'deriving direct plans for {total} (class, field) pairs')
        seed = None
        seed_path = self.root / 'seed' / 'plans.json'
        if seed_path.is_file() and any(self.store.missing(cls, codes) for (_, cls), codes in by_class.items()):
            try:
                seed = json.loads(seed_path.read_text()).get('plans')
            except (OSError, ValueError):
                seed = None
        try:
            managed_clubs, managed_people = tables.managed(engine.cached_read, engine.base)
        except Exception:  # noqa: BLE001 - no managed squad: random records only
            managed_clubs, managed_people = [], []
        for (kind, cls), codes in sorted(by_class.items()):
            live = self.live[kind]
            records = [p for p, c in zip(live.pointers, live.classes) if c == cls and p]
            if self.store.shipped:
                shipped = verify_shipped(engine, self.store, cls, records, self.log)
                stats.update({'shipped_checked': shipped['checked'], 'shipped_demoted': shipped['demoted']})
            # --- static plan compilation (robust lane, plancompile.py): compile from the getter's code
            # and verify on separate records before tracing; unbudgeted where plans are missing (a new
            # build), else at most COMPILE_BUDGET_S per build for fields emulated today
            from . import plancompile
            missing_now = bool(self.store.missing(cls, sorted(codes)))
            spent = stats.get('compile_seconds', 0.0)
            # (on-demand lane) a build started by a tool call does not compile: measured 69 s for 0
            # verified plans in one such build at load 65, where the budget is 15 s
            if self.derive_plans and (missing_now or spent < COMPILE_BUDGET_S):
                done_c = plancompile.upgrade(engine, self.store, cls, records, sorted(codes), log=self.log,
                                             budget_s=None if missing_now else COMPILE_BUDGET_S - spent)
                stats.update({'compile_verified': done_c['verified'], 'compile_demoted': done_c['demoted']})
                stats['compile_seconds'] = spent + done_c['seconds']
            # --- end static plan compilation
            if not self.derive_plans:
                continue
            extra = managed_people if kind == 'people' else managed_clubs if kind == 'clubs' else []
            todo = len(self.store.missing(cls, sorted(codes)))
            result = derive_class_plans(engine, self.store, cls, records, sorted(codes), names[(kind, cls)],
                                        self.log, extra=extra, seed=seed)
            stats.update({k: v for k, v in result.items() if k != 'seconds'})
            done += todo
            if todo:
                self.progress('plans', done, total, f'plans for {cls} done ({done} of {total} pairs)')
        self.plan_stats = dict(stats)

    # ------------------------------------------------------------------ reading
    def _read_table(self, t):
        """Direct values for one table: {column: {idx: value}} and the per-class column states.
        A column without a direct plan for a class is `on_demand` (or `unavailable`) there."""
        engine = self.engine
        live = self.live_by_sql[t]
        rows = self.rows[t]
        by_class = defaultdict(list)
        for i in rows:
            by_class[live.classes[i]].append(i)
        values = {c.name: {} for c in self.columns[t]}
        states = []
        started = time.time()
        stats = self.__dict__.setdefault('direct_stats', {})
        notes = self.__dict__.setdefault('source_notes', defaultdict(dict))
        recorder = self.recorder
        for cls, idxs in by_class.items():
            direct = {}
            for col in self.columns[t]:
                plan = self.store.get(cls, col.code) if len(idxs) > SMALL_CLASS and traced(col) else None
                game = (plan or {}).get('game_view')
                if game:
                    notes[(t, col.name)][cls] = (f'{cls}: game layer (the record getter does not claim the key; '
                                                 f'{game} of {plan.get("records")} sampled records)')
                elif col.origin == 'extra' and _extra_view(col) == 'game':
                    notes[(t, col.name)][cls] = f'{cls}: game layer (census: only the game layer answers the key)'
                routed = _route_note(col)       # fields lane
                if routed:
                    notes[(t, col.name)][cls] = f'{cls}: {routed}'
                if plan and plan.get('status') == 'direct':
                    direct[col.name] = (col, plan)
                    continue
                ms = (plan or {}).get('vm_ms') or (plan or {}).get('ms') or DEFAULT_MS
                if routed or (plan and plan.get('reason') == 'getter does not handle this code'
                              and _route_emulates(col)):
                    states.append(ColumnState(t, col.name, cls, len(idxs), 'emulated', 'on_demand', ms,
                                              'computed on demand (fieldroutes)'))
                    continue
                if plan and plan.get('reason') == 'getter does not handle this code' and \
                        not _route_emulates(col):        # fields lane: sampled plan, getter answers other rows
                    why = _route_reason(col)
                    states.append(ColumnState(t, col.name, cls, len(idxs), 'emulated', 'unavailable', ms,
                                              f'getter does not handle {col.code} for {cls} '
                                              f'({plan.get("records")} sampled records)' + (f'; {why}' if why else '')))
                    continue
                share = (plan or {}).get('unavailable_share') or 0.0
                if share >= UNAVAILABLE_SHARE and len(idxs) * ms / 1000 > self.column_budget:
                    states.append(ColumnState(t, col.name, cls, len(idxs), 'emulated', 'unavailable', ms,
                                              f'getter gave {plan.get("unavailable_reason")} for {share:.0%} of '
                                              f'{plan.get("records")} sampled {cls} records; not emulated in bulk '
                                              f'(about {len(idxs) * ms / 1000:.0f}s); fm_db_read reads single records'))
                    continue
                reason = (plan or {}).get('reason', 'small class: no plan is derived' if len(idxs) <= SMALL_CLASS else '')
                states.append(ColumnState(t, col.name, cls, len(idxs), 'emulated', 'on_demand', ms, reason))
            if direct:
                pointers = [live.pointers[i] for i in idxs]
                got = bulkplans.evaluate(recorder.read_many, pointers, {n: p for n, (c, p) in direct.items()},
                                         stats=stats, windows=recorder.windows, touch=recorder.touch_for(t, idxs))
                for name, (col, plan) in direct.items():
                    column = got[name]
                    values[name].update(zip(idxs, column))
                    missing = Counter()
                    if Missing in set(map(type, column)):
                        missing.update(v.reason for v in column if isinstance(v, Missing))
                    note = plan.get('fallback_note', '')
                    states.append(ColumnState(t, name, cls, len(idxs), 'direct', 'ready', 0.0, note, missing))
        self._phase('direct', started)
        return values, states

    # ------------------------------------------------------------------ computed columns
    def _computed_data(self):
        """Columns that are not getter values (`Computed`), read before the tables are written so
        they are part of the row INSERT. {table: [(name, {idx: value})]}; the `_fields` rows are
        added by `_computed_metadata` once the tables exist."""
        extra = defaultdict(list)
        self._computed = {}
        computed = Computed(self.engine, self.live, set(self.rows.get('club', ())))
        for t in Computed.TABLES:
            if t not in self.wanted or not computed.available(t, self.wanted):
                continue
            columns, stats = computed.columns(t, self.rows[t], self.recorder.touch_for(t, self.rows[t]))
            extra[t] += columns
            self._computed[t] = stats
        return extra

    def _computed_metadata(self, conn):
        if 'player' in self._computed:
            conn.execute('INSERT INTO _fields VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', (
                'player', 'is_virtual', 'c:is_virtual', None, 'Is virtual (youth placeholder)',
                '1 for VIRTUAL_PLAYER records: youth-intake placeholders whose getter values need the game\'s '
                'random-number state (every getter column is NULL for them); player_view leaves them out',
                'boolean', None, None, 'computed', 'ready', 'class = VIRTUAL_PLAYER'))
        if 'team' in self._computed:
            linked, total = self._computed['team']
            same_uid = conn.execute('SELECT COUNT(*) FROM team t JOIN club c ON c.idx = t.parent_club_idx '
                                    'WHERE c.uid = t.uid').fetchone()[0]
            first = conn.execute('SELECT COUNT(*) FROM team t JOIN club c ON c.uid = t.uid').fetchone()[0]
            conn.executemany('INSERT INTO _fields VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', [
                ('team', 'parent_club_idx', 'c:parent_club_idx', None, 'Parent club',
                 'club.idx of the club that owns this team (team record +0x30); for a B or U21 side that is a club '
                 'of its own this is the parent club; NULL for national sides', 'database_record_unique_id', None,
                 'club', 'direct', 'ready',
                 f'team record +0x30 (the club pointer tables.managed reads), kept when it is a live CLUB entry: '
                 f'{linked} of {total} teams; {same_uid} of {first} teams whose unique id is a club\'s point at '
                 f'that club; the other {first - same_uid} are B/U21 clubs pointing at their parent'),
                ('team', 'club_idx', 'c:club_idx', None, 'Club',
                 'club.idx for this team: the club with the same unique id (first teams; B/U21 sides that are clubs '
                 'of their own), else the parent club (reserve and youth teams); NULL for national sides; join '
                 'squads with person.club_idx -> team.idx -> team.club_idx', 'database_record_unique_id', None,
                 'club', 'direct', 'ready', 'club.uid = team.uid, else parent_club_idx')])
            self.timing['team_club_check'] = [same_uid, first]
        if 'person' in self._computed:
            checked, with_team, total = self._computed['person']
            note = (f'main contract at PERSON - 0x98 (FULL or BASIC contract, owner checked): {checked} of {total} '
                    f'people have one, {with_team} with a team; hand-proven layout (world.player_clubs, '
                    'loan_contracts)')
            conn.executemany('INSERT INTO _fields VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', [
                ('person', 'contract_team_idx', 'c:contract_team_idx', None, 'Contract team',
                 'team.idx of the first team on the person\'s main contract', 'database_record_unique_id', None, 'team',
                 'direct', 'ready', note),
                ('person', 'contract_club_idx', 'c:contract_club_idx', None, 'Contract club',
                 'club.idx of the club holding the main contract: the parent club of a player out on loan (Pcti and '
                 'Ptaj name the loan club); the owning club of a B or reserve team', 'database_record_unique_id', None,
                 'club', 'direct', 'ready', note),
                ('person', 'contract_squad_status_code', 'c:contract_squad_status_code', None, 'Squad status',
                 'agreed playing time (squad status) on the main FULL contract, as the squad and contract screens '
                 'show it: FULL_CONTRACT +0x54, the byte its slot 32 accessor 0x1005C78 returns (hand-built '
                 'playing_time.decode); labels are the compiled English fallback names; NULL without a FULL '
                 'main contract', 'enum', json.dumps({str(k): v for k, v in SQUAD_STATUS_LABELS.items()}), None,
                 'direct', 'ready', note)])
            conn.executemany('INSERT OR REPLACE INTO _enum_labels VALUES (?, ?, ?, ?)',
                             [('person', 'contract_squad_status_code', k, v) for k, v in SQUAD_STATUS_LABELS.items()])
            from . import views
            conn.executemany('INSERT OR REPLACE INTO _enum_labels VALUES (?, ?, ?, ?)', views.staff_job_labels())
            self.timing['contract_club_rows'] = [checked, with_team]

    # ------------------------------------------------------------------ writing
    def _write(self, data):
        tmp = self.path.with_name('snapshot.sqlite.tmp')
        for suffix in ('', '-wal', '-shm', '-journal'):
            Path(str(tmp) + suffix).unlink(missing_ok=True)
        resolver = Resolver(self.live_by_sql)
        conn = sqlite3.connect(tmp)
        try:
            conn.execute('PRAGMA journal_mode=OFF')
            conn.execute('PRAGMA synchronous=OFF')
            create_metadata(conn)
            notes = getattr(self, 'source_notes', {})
            extra = self._computed_data()
            for t in self.wanted:
                values, states = data[t]
                write_table(conn, t, self.columns[t], self.rows[t], self.live_by_sql[t], values, states, resolver,
                            {name: n for (tt, name), n in notes.items() if tt == t}, extra=extra.get(t))
            conn.executemany('INSERT INTO _unresolved VALUES (?, ?, ?, ?)', resolver.unresolved)
            self._computed_metadata(conn)
            save = self.save
            teams, clubs = self.live.get('teams'), self.live.get('clubs')
            team_index = {p: i for i, p in enumerate(teams.pointers)} if teams else {}
            club_index = {p: i for i, p in enumerate(clubs.pointers)} if clubs else {}
            conn.executemany('INSERT INTO _managed VALUES (?, ?, ?)', [
                (team_index.get(team), club_index.get(club), coach['name'])
                for team, club, coach in zip(save.managed_teams, save.managed_clubs, save.coaches)])
            plans_verified = sum(1 for fields in self.store.plans.values() for p in fields.values()
                                 if p.get('status') == 'direct')
            conn.execute('INSERT INTO _snapshot VALUES (?, ?, ?, ?, ?, ?, ?)', (
                save.save_name, save.save_key, save.game_date, datetime.now(timezone.utc).isoformat(timespec='seconds'),
                self.engine.build, plans_verified, json.dumps([CONSISTENCY_NOTE] + self.notes)))
            identity = {k: list(v.identity) for k, v in self.live.items()}
            conn.executemany('INSERT OR REPLACE INTO _build VALUES (?, ?)', [
                ('save', json.dumps(save.public())), ('identity', json.dumps(identity)),
                ('process', json.dumps(list(map(str, self.engine.process_key)))),
                ('layout', layout_signature(self.engine)),
                ('plan_stats', json.dumps(getattr(self, 'plan_stats', {}))),
                ('direct_reads', json.dumps(getattr(self, 'direct_stats', {})))])
            # ---- collection tables (fmdb/sources, collections lane): objects outside the 24
            # DATABASE_TABLE singletons; eager ones now, lazy ones carried over from the previous
            # snapshot by invalidation key or built on first reference; never fails the snapshot
            from . import sources
            started_sources = time.time()
            self.engine._collection_live = self.live
            try:
                self.source_summary = sources.build_in_snapshot(self.engine, conn, log=self.log, previous=self.path,
                                                                game_date=self.save.game_date)
            except Exception as exc:  # noqa: BLE001
                self.log(f'collection tables skipped: {type(exc).__name__}: {exc}')
                self.source_summary = {'error': f'{type(exc).__name__}: {exc}'}
            finally:
                self.engine.__dict__.pop('_collection_live', None)
            self._phase('collections', started_sources)
            # ---- end collection tables
            from . import views
            views.create_views(conn)
            conn.commit()
            from . import freshness
            started = time.time()
            conn.executescript(freshness.FRESH_SQL)
            freshness.save_live(conn, self.live)
            pages = freshness.write_dependencies(conn, self.recorder)
            freshness.set_fresh(conn, checked_at=freshness.now_iso(), checked_at_unix=time.time(), rows_refreshed=0,
                                pages_changed=0, pages_checked=pages, change_seq=0, checks=0)
            conn.execute('INSERT OR REPLACE INTO _build VALUES (?, ?)', ('dependencies', json.dumps(
                {'pages': pages, 'seconds': round(time.time() - started, 2)})))
            # names and position text of the previous snapshot of this save, by their declared inputs
            from . import ondemand
            started = time.time()
            carried = ondemand.carry_declared(conn, self.path, self.engine.catalog, log=self.log)
            conn.execute('INSERT OR REPLACE INTO _build VALUES (?, ?)', ('declared_carried', json.dumps(
                {'cells': carried, 'seconds': round(time.time() - started, 2)})))
            conn.commit()
        except (sqlite3.OperationalError, OSError) as exc:
            conn.close()
            for suffix in ('', '-wal', '-shm', '-journal'):       # no partial file is left behind
                Path(str(tmp) + suffix).unlink(missing_ok=True)
            from .engine import free_bytes, is_disk_full
            if is_disk_full(exc):
                raise SnapshotError(f'snapshot write failed, disk full: {free_bytes(tmp) / 1024 ** 2:.0f} MiB free at '
                                    f'{self.path.parent}; the previous snapshot is unchanged') from exc
            raise
        finally:
            conn.close()
        for suffix in ('-wal', '-shm', '-journal'):
            Path(str(self.path) + suffix).unlink(missing_ok=True)
        # rollback journal (not WAL): read-only connections cannot open a WAL file whose -shm is
        # gone; materialise commits per class, so readers wait at most one short write
        os.replace(tmp, self.path)


METADATA_SQL = """
CREATE TABLE _fields(table_name TEXT, column_name TEXT, code TEXT, record_type TEXT, name TEXT, comment TEXT,
                     type TEXT, enum_json TEXT, references_table TEXT, source TEXT, status TEXT, note TEXT,
                     PRIMARY KEY(table_name, column_name));
CREATE TABLE _tables(table_name TEXT PRIMARY KEY, record_type TEXT, rows INTEGER, classes_json TEXT);
CREATE TABLE _snapshot(save_name TEXT, save_key TEXT, game_date TEXT, built_at TEXT, build TEXT,
                       plans_verified INTEGER, notes TEXT);
CREATE TABLE _column_state(table_name TEXT, column_name TEXT, class TEXT, rows INTEGER, source TEXT,
                           status TEXT, ms_per_row REAL, note TEXT, missing_json TEXT,
                           PRIMARY KEY(table_name, column_name, class));
CREATE TABLE _enum_labels(table_name TEXT, column_name TEXT, value INTEGER, label TEXT,
                          PRIMARY KEY(table_name, column_name, value));
CREATE TABLE _unresolved(table_name TEXT, column_name TEXT, idx INTEGER, raw_json TEXT);
CREATE TABLE _build(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE _managed(team_idx INTEGER, club_idx INTEGER, coach TEXT);
CREATE TABLE _view_columns(view TEXT, column_name TEXT, base_table TEXT, base_column TEXT);
"""


def create_metadata(conn):
    conn.executescript(METADATA_SQL)


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def summarise_states(states):
    """Column-level (source, status, note) from per-class states. A column is `ready` when some
    class can give a value: stored at build (direct) or computed on demand (emulated)."""
    if not states:
        return 'emulated', 'unavailable', 'no rows'
    sources = {s.source for s in states if s.status != 'unavailable'} or {s.source for s in states}
    statuses = {s.status for s in states}
    source = 'direct' if sources == {'direct'} else 'emulated'
    status = 'unavailable' if statuses == {'unavailable'} else 'ready'
    parts = []
    if 'on_demand' in statuses:
        parts.append('computed on demand: the getter runs for the rows a query needs when the query names the '
                     'column, and the cells are kept until a byte they read changes')
    if len(sources) > 1:
        parts.append('direct for ' + ', '.join(s.cls for s in states if s.source == 'direct')
                     + '; emulated for ' + ', '.join(f'{s.cls} ({s.rows} rows)' for s in states
                                                     if s.source != 'direct' and s.status != 'unavailable'))
    for s in states:
        if s.status == 'unavailable':
            parts.append(s.note)
        elif s.note and s.source == 'direct':
            parts.append(s.note)
    missing = Counter()
    for s in states:
        missing.update(s.missing)
    if missing:
        parts.append('unavailable values: ' + ', '.join(f'{r} ({n})' for r, n in missing.most_common(4)))
    return source, status, '; '.join(dict.fromkeys(p for p in parts if p))


_PLAIN = {int, str, float, type(None)}

def _squad_status_labels():
    from .. import playing_time
    return {code: label[2] for code, label in playing_time.LABELS.items()}


SQUAD_STATUS_LABELS = _squad_status_labels()

# Meanings for catalog columns whose editor field has no comment and whose name misleads.
COLUMN_MEANINGS = {
    ('person', 'Pcti'): ('team.idx (not club.idx) of the team the person plays or works for now, the loan '
                         'team while on loan: the editor field "Club" refers to a TEAM record. The club is '
                         'team.club_idx (player_view.club_idx); the club holding the main contract is '
                         'person.contract_club_idx'),
}


def convert_column(c, rows, column, resolver):
    """SQL values of one column: `to_sql` for every cell, done per column (one Python call per
    cell only where a value needs it; a reference that resolves is resolved once per value)."""
    if c.kind == 'ref' and not c.part:
        return _ref_column(c, rows, column, resolver)
    if c.part:
        return [to_sql(c, i, v, resolver) for i, v in zip(rows, column)]
    if not set(map(type, column)) <= _PLAIN:
        return [v if type(v) in _PLAIN else to_sql(c, i, v, resolver) for i, v in zip(rows, column)]
    return column


def _ref_column(column, rows, values, resolver):
    """`to_sql` for a reference column. A value that resolves is resolved once (record
    references and table indexes repeat); one that does not goes through `to_sql` for every
    row, because the resolver records each unresolved cell."""
    done = {}
    out = []
    for i, value in zip(rows, values):
        if value is None:
            out.append(None)
            continue
        kind = type(value)
        if kind is not int and kind is not Ref:      # bool, text, Missing: the general path
            out.append(to_sql(column, i, value, resolver))
            continue
        hit = done.get(value)
        if hit is None:
            hit = to_sql(column, i, value, resolver)
            if hit is not None:
                done[value] = hit
        out.append(hit)
    return out


def write_table(conn, t, columns, rows, live, values, states, resolver, source_notes=None, extra=None):
    """`extra`: computed INTEGER columns [(name, {idx: value})] placed after the catalog columns."""
    cols_sql = ', '.join([f'{_quote(c.name)} {c.sql_type}'.rstrip() for c in columns]
                         + [f'{name} INTEGER' for name, _ in extra or ()])
    conn.execute(f'CREATE TABLE {_quote(t)} (idx INTEGER PRIMARY KEY, uid INTEGER, class TEXT'
                 + (', ' + cols_sql if cols_sql else '') + ')')
    # Only columns that hold a value are named in the INSERT (the rest are NULL by default), and
    # each column is converted as a whole: one Python call per cell only where a value needs it.
    names = ['idx', 'uid', 'class']
    data = [rows, [live.uids[i] for i in rows], [live.classes[i] for i in rows]]
    for c in columns:
        vals = values[c.name]
        if not vals:
            continue
        column = convert_column(c, rows, list(map(vals.get, rows)), resolver)
        names.append(c.name)
        data.append(column)
    for name, vals in extra or ():
        names.append(name)
        data.append(list(map(vals.get, rows)))
    placeholders = ', '.join(['?'] * len(names))
    sql = f'INSERT INTO {_quote(t)} ({", ".join(map(_quote, names))}) VALUES ({placeholders})'
    table_rows = list(zip(*data))
    for start in range(0, len(table_rows), 5000):
        conn.executemany(sql, table_rows[start:start + 5000])
    by_column = defaultdict(list)
    for s in states:
        by_column[s.column].append(s)
    conn.executemany('INSERT INTO _column_state VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', [
        (t, s.column, s.cls, s.rows, s.source, s.status, s.ms, s.note, json.dumps(dict(s.missing)))
        for s in states])
    meta = [(t, 'idx', None, None, 'Index', 'live table index (PERSON index for person-family tables)',
             'integer', None, None, 'direct', 'ready', ''),
            (t, 'uid', None, None, 'Unique ID', 'record unique id', 'integer', None, None, 'direct', 'ready', ''),
            (t, 'class', None, None, 'Class', 'RTTI record class', 'string', None, None, 'direct', 'ready', '')]
    labels = []
    for c in columns:
        source, status, note = summarise_states(by_column.get(c.name, []))
        f = c.field
        if c.kind == 'attribute' and source == 'direct':
            note = ('getter returns DATA [1, r, r, r]; column stores r (1-20). ' + note).strip()
        if c.kind == 'ref' and c.references:
            note = ('idx of the referenced row: a record reference is matched by unique and random id; an '
                    'integer from the getter is that row\'s table index (checked for nationality against the '
                    'Nation reference: 32,157 of 32,157). ' + note).strip()
        if c.kind == 'ref' and not c.references:
            note = (f'reference target {f.references!r} has no SQL table; idx resolved by record FourCC only. '
                    + note).strip()
        if c.kind == 'date':
            note = ('ISO date of the getter\'s SI_DATE; its low byte (not part of the date) is not stored; '
                    'fm_db_read shows it. ' + note).strip()
        if c.kind == 'cash':
            note = ('cash amount as stored by the getter (no currency conversion; see the club/nation currency). '
                    + note).strip()
        if c.part and c.kind == 'ref':
            note = (f'the getter returns a composite record; the column resolves its {c.part!r} member. '
                    + note).strip()
        game = (source_notes or {}).get(c.name)
        if game:
            note = ('source: ' + '; '.join(game[k] for k in sorted(game)) + '. ' + note).strip()
        elif c.origin == 'extra':
            note = ("source: the record's own getter. " + note).strip()
        if c.origin != 'catalog':
            note = (f'read: {source}. ' + note).strip()
            source = c.origin
            if c.origin == 'extra':
                note = ('label ' + ('inferred (not proven). ' if getattr(f, 'label_inferred', True)
                                    else 'proven from the getter code. ') + note)
        meta.append((t, c.name, getattr(c, 'routed_from', None) or c.code,      # fields lane: editor code
                     c.record_type, f.name, f.comment or COLUMN_MEANINGS.get((t, c.code)), f.type,
                     json.dumps({str(k): v for k, v in sorted(c.labels.items())}) if c.labels else None,
                     c.references, source, status, note))
        if c.labels and (f.type or '') == 'enum':
            labels += [(t, c.name, int(k), v) for k, v in c.labels.items()]
    conn.executemany('INSERT INTO _fields VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', meta)
    conn.executemany('INSERT OR REPLACE INTO _enum_labels VALUES (?, ?, ?, ?)', labels)
    classes = Counter(live.classes[i] for i in rows)
    conn.execute('INSERT INTO _tables VALUES (?, ?, ?, ?)', (t, TABLES[t], len(rows), json.dumps(dict(classes))))


# --------------------------------------------------------------------------- on-demand columns
def materialise(engine, path: Path, table: str, columns, where_idx=None, *, budget_s=None) -> dict:
    """Compute on-demand columns of `table` now, for all rows or the given idx values, and store
    them (`ondemand.compute`). Queries do this themselves for the rows they need; this is the
    explicit form (`fm_db_refresh(columns=[...])`, scripts)."""
    from . import ondemand
    return ondemand.compute(engine, path, table, list(columns), where_idx, budget_s=budget_s)


def _live_tables_for_refs(engine, col, cache):
    if col.kind != 'ref':
        return {}
    targets = [col.references] if col.references else []
    for extra in REF_FOURCC.values():
        targets += [t for t in extra if t not in targets]
    out = {}
    for t in targets:
        kind = tables.RECORD_TYPES[TABLES[t]].table
        if kind not in cache:
            cache[kind] = enumerate_table(engine, kind)
        out[t] = cache[kind]
    return out


def snapshot_path(engine, save_key=None) -> Path:
    from .engine import cache_root
    key = save_key or engine.save_info().save_key
    return cache_root() / key / 'snapshot.sqlite'


def build(engine, **kwargs) -> Path:
    return Build(engine, **kwargs).run()
