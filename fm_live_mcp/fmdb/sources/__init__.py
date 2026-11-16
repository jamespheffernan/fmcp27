"""Collection tables: save data that is not one of the 24 `DATABASE_TABLE` singletons.

A save holds far more than the enumerated tables: contracts hang off people, fixtures and
league tables off competitions, transfer offers and news off managers. Each module in this
package exposes

    def tables(engine) -> list[SourceTable]            # tables with rows of their own
    def views(engine) -> {name: (description, SELECT template[, manager policy])}   # optional

Cost rule (orchestrator, 11 Nov 2026): no work per game day that a query has not asked for.

* `mode='lazy'` (the default) tables are created empty at snapshot build (status `lazy`) and
  built the first time a query references them (`refresh_for_query`, called from the same
  pre-pass in `tools.db_query` that materialises pending columns). `mode='eager'` tables are
  built during the snapshot build and must cost about 2 s or less on a quiet machine.
* `invalidation` says when stored rows are stale:
    'immutable'  rows never change once created (past results, news by id): only new rows are added
    'append'     the collection only grows: only new rows are added
    'content'    rebuilt when `fingerprint()` (cheap: page or pointer hashes) changes
    'game_date'  rebuilt when the game date changes (only where nothing better exists)
  `immutable`/`append` tables name their row identity (`identity` columns) and may give
  `new_rows(existing identities)` so a refresh reads only what is new. An `append` table may
  name a `replace_key`: an added row deletes the stored rows with the same values there first
  (identity ('idx', 'detail_level') with replace_key ('idx',) lets a row be superseded when its
  detail rises; a content digest in the identity does the same for changed content). `layout`
  is a token stored with the table: rows are carried from the previous snapshot only when it is
  unchanged. `check_interval` overrides CHECK_INTERVAL_S per table (0: every reference), and
  `current_statement()` gives the statement being prepared to tables whose rows depend on it
  (player_season_rates computes only the rows a statement reads). When a snapshot is
  rebuilt (new game date), rows of `immutable`, `append` and `content` tables are carried over
  from the previous snapshot file (`content` ones re-checked by fingerprint on next use);
  `game_date` tables start empty again.
* Checks are rate-limited: a table referenced again within `CHECK_INTERVAL_S` is not re-checked.
* Nothing here starts or depends on a background process.

Build time (wall and CPU seconds), row counts, mode and invalidation are recorded in
`_source_tables` and in `_tables.classes_json`, and `fm_db_schema` shows them.

A module that fails to import, or a table whose rows raise, never stops the build or the
query: the table is marked `unavailable` with the reason (`_source_failures` keeps it) and is
retried on a later reference after `RETRY_UNAVAILABLE_S`.

Backward compatibility with the first contract: a missing `mode` means lazy, a missing
`invalidation` means `game_date`; `slow=True` is accepted and means lazy.

Trust. A source reads values the way the hand-built tools do (proven layouts, checked against
the shipped getter on separate records) or by emulating the record's own property getter. Each
table states its route in `source_note` (`_fields.note`).

Manager view. Each table carries a `manager` policy entry (`MANAGER_SCOPES`), written to
`_source_tables.manager_json`; see docs/fmdb/MANAGER_VIEW.md ("Collection tables").
"""
from __future__ import annotations

import argparse
import contextvars
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import pkgutil
import re
import sqlite3
import sys
import time
import traceback
from typing import Callable, Iterable

# Manager-view scopes for collection tables (policy, not proven game behaviour; MANAGER_VIEW.md).
#   public    every row and column is visible in the game's UI for any club/person
#   own_club  rows are visible only when `own_club_column` names the manager's club (club.idx)
#   never     not shown in the UI as stored here (internal values)
# An `own_club` policy names how a row is the manager's (manager_view._own_condition), one of:
#   own_club_column / own_club_columns  club idx column(s) (any of them)
#   own_person_column                   a person idx column: the person is contracted to a team of the club
#   own_team_column                     a team idx column: a team of the club
#   own_club_via 'table.column'         `<table>_idx` names a row of table whose column is the club
#   own_club_rule                       an SQL condition over the row's own columns
# and optionally `public_columns`: columns shown on every row (the rest only on the club's rows);
# without them a row of another club is withheld entirely.
MANAGER_SCOPES = ('public', 'own_club', 'never')
MODES = ('eager', 'lazy')
INVALIDATIONS = ('immutable', 'append', 'content', 'game_date')
EAGER_BUDGET_S = 2.0            # an eager table should cost about this much on a quiet machine
CHECK_INTERVAL_S = 5.0          # a referenced table is re-checked at most this often
RETRY_UNAVAILABLE_S = 60.0      # an unavailable table is retried on reference after this long


@dataclass
class Column:
    name: str
    sql_type: str                       # INTEGER | TEXT | REAL
    meaning: str
    enum: dict | None = None            # {int value: label}
    references: str | None = None       # snapshot table whose idx this column holds


@dataclass
class SourceTable:
    name: str
    description: str
    columns: list[Column]
    rows: Callable[[], Iterable[tuple]]
    key: str = 'idx'
    cost_note: str = ''
    # additive extensions (defaults keep the first contract working)
    mode: str | None = None             # 'eager' | 'lazy' (None: lazy)
    invalidation: str | None = None     # see INVALIDATIONS (None: 'game_date')
    fingerprint: Callable[[], str] | None = None   # 'content': cheap change detector
    identity: tuple = ()                # 'immutable'/'append': columns that identify a row
    new_rows: Callable[[set], Iterable[tuple]] | None = None   # rows whose identity is not in the set
    # 'append': columns whose stored rows an added row supersedes (deleted before it is inserted),
    # e.g. ('idx',) with identity ('idx', 'detail_level'): a row whose detail rose replaces the old
    replace_key: tuple = ()
    # rows are carried from the previous snapshot only when its stored layout equals this token
    # (change it when the meaning of stored rows changes, e.g. how idx is assigned)
    layout: str = ''
    # seconds within which a referenced table is not checked again (None: CHECK_INTERVAL_S); 0 for
    # a table whose rows depend on the statement (`current_statement`)
    check_interval: float | None = None
    slow: bool = False                 # first contract: True meant "background"; now means lazy
    source_note: str = ''               # trust route: how the values are read
    indexes: tuple = ()                 # columns to index
    manager: dict = field(default_factory=lambda: {'scope': 'never'})
    views: dict = field(default_factory=dict)    # view name -> SELECT (created after every table exists)
    coverage: Callable[[], str] | None = None   # called after rows(): what was not read and why (-> note)
    # called after rows() / new_rows(): one line per thing the statement named whose read failed,
    # with the reason. The lines go into the query answer (`collections[table]['not_read']` and a
    # note), so rows that are absent because a read failed are told apart from rows that do not exist.
    not_read: Callable[[], list] | None = None

    @property
    def build_mode(self) -> str:
        return self.mode if self.mode in MODES else 'lazy'

    @property
    def refresh(self) -> str:
        return self.invalidation if self.invalidation in INVALIDATIONS else 'game_date'


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _q(name):
    return '"' + name.replace('"', '""') + '"'


def reset_cache(engine):
    """Drop the per-build caches the source modules keep on the engine (`_common`)."""
    engine.__dict__.pop('_collection_cache', None)
    engine.__dict__.pop('_collection_live_cache', None)


def digest(*parts) -> str:
    """A short hash of bytes/str/int parts (for fingerprints)."""
    h = hashlib.blake2b(digest_size=16)
    for part in parts:
        if isinstance(part, int):
            part = part.to_bytes(8, 'little', signed=part < 0)
        elif isinstance(part, str):
            part = part.encode()
        h.update(part or b'')
    return h.hexdigest()


# --------------------------------------------------------------------------- discovery
def module_names() -> list[str]:
    """Modules the snapshot discovers: every `sources/<name>.py` not starting with `_`."""
    return sorted(m.name for m in pkgutil.iter_modules(__path__) if not m.name.startswith('_'))


def discover(engine, only=None, log=None):
    """[(module, SourceTable)], [(module, reason)]: every module's tables; failures are recorded.

    `only` names the modules to load (it may name `_`-prefixed modules such as `_example`,
    which are never discovered by default)."""
    log = log or (lambda m: None)
    found, failures = [], []
    for name in (list(only) if only else module_names()):
        try:
            mod = importlib.import_module(f'{__name__}.{name}')
            fn = getattr(mod, 'tables', None)
            if fn is None:
                continue
            for t in fn(engine):
                found.append((name, t))
        except Exception as exc:  # noqa: BLE001 - one module never stops the build
            reason = f'{type(exc).__name__}: {exc}'
            log(f'collection module {name} failed: {reason}')
            failures.append((name, reason[:500]))
    return found, failures


# --------------------------------------------------------------------------- metadata
SOURCE_SQL = """
CREATE TABLE IF NOT EXISTS _source_tables(table_name TEXT PRIMARY KEY, module TEXT, status TEXT, rows INTEGER,
    seconds REAL, built_at TEXT, description TEXT, cost_note TEXT, note TEXT, manager_scope TEXT,
    manager_json TEXT, views_json TEXT, mode TEXT, invalidation TEXT, fingerprint TEXT, built_game_date TEXT,
    cpu_seconds REAL, checked_at REAL, attempted_at REAL, refreshes INTEGER, last_refresh_json TEXT, layout TEXT);
CREATE TABLE IF NOT EXISTS _source_failures(module TEXT, reason TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS _source_views(view TEXT PRIMARY KEY, module TEXT, description TEXT, template TEXT,
    manager_json TEXT);
"""
_STATE_COLUMNS = ('table_name', 'module', 'status', 'rows', 'seconds', 'built_at', 'description', 'cost_note', 'note',
                  'manager_scope', 'manager_json', 'views_json', 'mode', 'invalidation', 'fingerprint',
                  'built_game_date', 'cpu_seconds', 'checked_at', 'attempted_at', 'refreshes', 'last_refresh_json',
                  'layout')


def ensure_state_columns(conn, schema='main'):
    """Add `_source_tables` columns a file written by an older reader lacks (additive)."""
    have = {r[1] for r in conn.execute(f'PRAGMA {schema}.table_info(_source_tables)')}
    if have and 'layout' not in have:
        conn.execute(f'ALTER TABLE {schema}._source_tables ADD COLUMN layout TEXT')


def discover_views(engine, only=None, log=None):
    """[(module, view name, description, SELECT template, manager policy)] from modules that expose
    `views(engine) -> {name: (description, template[, manager])}` (views over the core tables,
    e.g. list columns exploded into rows; no data of their own)."""
    log = log or (lambda m: None)
    out = []
    for name in (list(only) if only else module_names()):
        try:
            mod = importlib.import_module(f'{__name__}.{name}')
            fn = getattr(mod, 'views', None)
            if fn is None:
                continue
            for view, spec in fn(engine).items():
                description, template, *rest = spec
                out.append((name, view, description, template, rest[0] if rest else {'scope': 'never'}))
        except Exception as exc:  # noqa: BLE001
            log(f'collection module {name} views failed: {type(exc).__name__}: {exc}')
    return out


def _columns(t: SourceTable) -> list[Column]:
    cols = list(t.columns)
    if not any(c.name == 'idx' for c in cols):
        cols.insert(0, Column('idx', 'INTEGER', 'row number in this collection table (no game meaning)'))
    return cols


def _cost_json(module, t, status, rows=0, seconds=None, cpu=None, built_at=None):
    return json.dumps({'collection': module, 'mode': t.build_mode, 'invalidation': t.refresh, 'status': status,
                       'rows': rows, 'seconds': seconds, 'cpu_seconds': cpu, 'built_at': built_at})


def create_empty(conn, module: str, t: SourceTable, status: str, note: str = ''):
    """Create the table, its metadata rows and indexes (no data)."""
    cols = _columns(t)
    conn.execute(f'DROP TABLE IF EXISTS main.{_q(t.name)}')          # main.: a previous snapshot may be attached
    body = ', '.join(f'{_q(c.name)} {c.sql_type}' + (' PRIMARY KEY' if c.name == 'idx' else '') for c in cols)
    conn.execute(f'CREATE TABLE main.{_q(t.name)} ({body})')
    names = {c.name for c in cols}
    for col in dict.fromkeys(([t.key] if t.key != 'idx' and t.key in names else []) + list(t.indexes)):
        conn.execute(f'CREATE INDEX main.{_q(f"ix_{t.name}_{col}")} ON {_q(t.name)}({_q(col)})')
    if t.identity and all(c in names for c in t.identity):
        conn.execute(f'CREATE INDEX main.{_q(f"ix_{t.name}__identity")} ON {_q(t.name)}('
                     + ', '.join(_q(c) for c in t.identity) + ')')
    conn.execute('DELETE FROM _fields WHERE table_name=?', (t.name,))
    conn.execute('DELETE FROM _enum_labels WHERE table_name=?', (t.name,))
    route = t.source_note or 'collection source'
    meta, labels = [], []
    for c in cols:
        ftype = 'enum' if c.enum else {'INTEGER': 'integer', 'TEXT': 'string', 'REAL': 'real'}.get(c.sql_type, 'string')
        if c.references:
            ftype = 'database_record_unique_id'
        meta.append((t.name, c.name, None, None, c.meaning.split(';')[0][:80], c.meaning, ftype,
                     json.dumps({str(k): v for k, v in sorted(c.enum.items())}) if c.enum else None,
                     c.references, 'collection', 'ready' if status == 'ready' else status,
                     f'{route}. {note}'.strip().rstrip('.') if note else route))
        if c.enum:
            labels += [(t.name, c.name, int(k), v) for k, v in c.enum.items()]
    conn.executemany('INSERT INTO _fields VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)', meta)
    conn.executemany('INSERT OR REPLACE INTO _enum_labels VALUES (?, ?, ?, ?)', labels)
    conn.execute('DELETE FROM _tables WHERE table_name=?', (t.name,))
    conn.execute('INSERT INTO _tables VALUES (?, ?, ?, ?)', (t.name, f'collection:{module}', 0,
                                                             _cost_json(module, t, status)))
    conn.execute(f'INSERT OR REPLACE INTO _source_tables ({", ".join(_STATE_COLUMNS)}) VALUES '
                 f'({", ".join("?" * len(_STATE_COLUMNS))})', (
                     t.name, module, status, 0, None, None, t.description, t.cost_note, note,
                     t.manager.get('scope', 'never'), json.dumps(t.manager), json.dumps(t.views), t.build_mode,
                     t.refresh, None, None, None, None, None, 0, None, t.layout))


def _insert(conn, t: SourceTable, rows, start_idx=0) -> int:
    cols = _columns(t)
    names = [c.name for c in cols]
    auto_idx = not any(c.name == 'idx' for c in t.columns)
    sql = f'INSERT INTO {_q(t.name)} VALUES ({", ".join("?" * len(names))})'
    data = [(start_idx + i, *r) for i, r in enumerate(rows)] if auto_idx else list(rows)
    for start in range(0, len(data), 5000):
        conn.executemany(sql, data[start:start + 5000])
    return len(data)


def _record(conn, module, t, *, rows_total, seconds, cpu, note, fingerprint, game_date, refresh_info):
    built = _now()
    conn.execute('UPDATE _tables SET rows=?, classes_json=? WHERE table_name=?',
                 (rows_total, _cost_json(module, t, 'ready', rows_total, round(seconds, 2), round(cpu, 2), built),
                  t.name))
    conn.execute("UPDATE _fields SET status='ready' WHERE table_name=?", (t.name,))
    conn.execute("UPDATE _source_tables SET status='ready', rows=?, seconds=?, cpu_seconds=?, built_at=?, note=?, "
                 "fingerprint=?, built_game_date=?, checked_at=?, refreshes=COALESCE(refreshes, 0) + 1, "
                 "last_refresh_json=? WHERE table_name=?",
                 (rows_total, round(seconds, 2), round(cpu, 2), built, note, fingerprint, game_date, time.time(),
                  json.dumps(refresh_info), t.name))


def fill_table(conn, module: str, t: SourceTable, rows: list, seconds: float, note: str = '', *, cpu=0.0,
               fingerprint=None, game_date=None):
    """Replace the rows of an existing collection table and mark it ready."""
    conn.execute(f'DELETE FROM {_q(t.name)}')
    n = _insert(conn, t, rows)
    if note:
        conn.execute("UPDATE _fields SET note = note || '. ' || ? WHERE table_name=?", (note, t.name))
    _record(conn, module, t, rows_total=n, seconds=seconds, cpu=cpu, note=note, fingerprint=fingerprint,
            game_date=game_date, refresh_info={'kind': 'full', 'rows': n})


def mark(conn, name: str, status: str, note: str):
    conn.execute('UPDATE _source_tables SET status=?, note=?, attempted_at=? WHERE table_name=?',
                 (status, note[:1000], time.time(), name))
    conn.execute('UPDATE _fields SET status=?, note=note || ? WHERE table_name=?', (status, f'. {status}: {note[:300]}', name))


def run_rows(t: SourceTable, rows_fn=None) -> tuple[list, float, float]:
    """(rows, wall seconds, CPU seconds of this process)."""
    started, cpu = time.time(), time.process_time()
    rows = [tuple(r) for r in (rows_fn or t.rows)()]
    return rows, time.time() - started, time.process_time() - cpu


def coverage_note(t: SourceTable) -> str:
    if t.coverage is None:
        return ''
    try:
        return t.coverage() or ''
    except Exception as exc:  # noqa: BLE001
        return f'coverage unknown ({type(exc).__name__}: {exc})'


def not_read_lines(t: SourceTable) -> list:
    """What the last rows() / new_rows() call of `t` could not read, one line each with the reason."""
    if t.not_read is None:
        return []
    try:
        return [str(line) for line in t.not_read() or []]
    except Exception as exc:  # noqa: BLE001
        return [f'what was not read is unknown ({type(exc).__name__}: {exc})']


def not_read_note(name: str, lines) -> str:
    """The query note for a table whose read failed for part of what the statement named."""
    return (f'{name}: not read for part of what the statement names, so those rows are missing from the '
            f'answer (the read failed; it did not find them empty): ' + '; '.join(lines))


def _fingerprint(t: SourceTable):
    if t.fingerprint is None:
        return None
    return str(t.fingerprint())


_KEYWORDS = frozenset({'select', 'from', 'where', 'group', 'order', 'limit', 'having', 'union', 'except',
                       'intersect', 'window'})
_TOKEN = re.compile(r"""'(?:[^']|'')*'|"(?:[^"]|"")*"|[A-Za-z_][A-Za-z0-9_]*|\S""")


def _select_items(sql: str) -> list[list[tuple[str, str]]]:
    """For each top-level SELECT of a (compound) statement: [(item text, output name)] of its
    result list, and one ('', '') entry holding the rest of that SELECT (FROM, WHERE, ...).

    A small scanner: quotes and parentheses are respected; the output name is the `AS` alias, or
    the last identifier of a bare column reference."""
    selects, depth, current, item, rest, in_list = [], 0, None, [], [], False
    for m in _TOKEN.finditer(sql):
        tok = m.group(0)
        low = tok.lower()
        if tok == '(':
            depth += 1
        elif tok == ')':
            depth -= 1
        if depth == 0 and low == 'select':
            if current is not None:
                current.append((' '.join(rest), ''))
            current, item, rest, in_list = [], [], [], True
            selects.append(current)
            continue
        if current is None:
            continue
        if depth == 0 and in_list and (tok == ',' or low in _KEYWORDS):
            current.append((' '.join(item), _output_name(item)))
            item = []
            if tok == ',':
                continue
            in_list = False
        (item if in_list else rest).append(tok)
    if current is not None:
        if in_list and item:
            current.append((' '.join(item), _output_name(item)))
        current.append((' '.join(rest), ''))
    return selects


def _output_name(tokens) -> str:
    if len(tokens) >= 2 and tokens[-2].lower() == 'as':
        name = tokens[-1]
    elif tokens and all(t == '.' or re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*|"(?:[^"]|"")*"', t) for t in tokens):
        name = tokens[-1]
    else:
        return ''
    return name[1:-1].replace('""', '"') if name.startswith('"') else name


def view_lineage(select: str, marks: dict) -> list[tuple[str, str, str]]:
    """[(view column, base table, base column)] for the placeholders of a resolved template.

    `marks` maps a marker token left in `select` to the (table, column) it stands for. A marker in
    a result item belongs to that item's output column (by position in every SELECT of a compound
    statement, named after the first); a marker elsewhere (FROM, WHERE, JOIN) belongs to every
    output column, because each row the view yields reads it."""
    selects = _select_items(select)
    if not selects:
        return []
    names = [n for _, n in selects[0][:-1]]
    out = []
    for items in selects:
        result, rest = items[:-1], items[-1][0]
        for pos, (text, _) in enumerate(result):
            name = names[pos] if pos < len(names) else ''
            for marker, (table, column) in marks.items():
                if marker in text and name:
                    out.append((name, table, column))
        for marker, (table, column) in marks.items():
            if marker in rest:
                out += [(name, table, column) for name in names if name]
    return sorted(set(out))


def create_views(conn):
    """Resolved views declared by the collection tables (after every table exists).

    A placeholder `{table.CODE1|CODE2}` takes the first alternative that is stored (read directly
    for at least nine rows in ten), else the first that exists: a name the getter computes on
    demand is NULL until a statement names it. Every placeholder is recorded in `_view_columns`
    under the view column it feeds, so a statement that names the view column has the base column
    computed for the rows it reads (`ondemand.Session.plan`), as for the curated views.

    A view whose SELECT fails (a referenced table or column is missing) is skipped."""
    try:
        rows = conn.execute("SELECT table_name, views_json FROM _source_tables").fetchall()
    except sqlite3.Error:
        return []
    codes = {}
    for t, c, code in conn.execute('SELECT table_name, column_name, code FROM _fields WHERE code IS NOT NULL '
                                   'ORDER BY rowid'):
        codes.setdefault((t, code), c)
    try:
        lazy = {(t, c) for t, c in conn.execute(
            "SELECT table_name, column_name FROM _column_state GROUP BY table_name, column_name "
            "HAVING 10 * SUM(CASE WHEN status = 'on_demand' THEN rows ELSE 0 END) > SUM(rows)")}
    except sqlite3.Error:
        lazy = set()
    conn.execute('CREATE TABLE IF NOT EXISTS _view_columns(view TEXT, column_name TEXT, base_table TEXT, '
                 'base_column TEXT)')
    marks = {}

    def column(match):
        table, alternatives = match.group(1), match.group(2).split('|')
        names = [codes[(table, code)] for code in alternatives if (table, code) in codes]
        if not names:
            raise KeyError(f'no column for {table}.{match.group(2)}')
        stored = [n for n in names if (table, n) not in lazy]
        marker = f'__fmdb_placeholder_{len(marks)}__'
        marks[marker] = (table, (stored or names)[0])
        return marker

    made = []
    try:
        extra = [(None, json.dumps({v: t})) for v, t in conn.execute('SELECT view, template FROM _source_views')]
    except sqlite3.Error:
        extra = []
    for table, views_json in rows + extra:
        for name, template in (json.loads(views_json or '{}')).items():
            marks.clear()
            try:
                marked = re.sub(r'\{(\w+)\.([^}]+)\}', column, template)
            except KeyError as exc:
                conn.execute('INSERT INTO _source_failures VALUES (?, ?, ?)', (f'view:{name}', str(exc), _now()))
                continue
            select = marked
            for marker, (_, col) in marks.items():
                select = select.replace(marker, _q(col))
            try:
                conn.execute(f'DROP VIEW IF EXISTS {_q(name)}')
                conn.execute('DELETE FROM _view_columns WHERE view = ?', (name,))
                conn.execute(f'CREATE VIEW {_q(name)} AS {select}')
                conn.execute(f'SELECT * FROM {_q(name)} LIMIT 0').fetchall()
                conn.execute('INSERT OR REPLACE INTO _build VALUES (?, ?)', (f'view:{name}', select))
                conn.executemany('INSERT INTO _view_columns VALUES (?, ?, ?, ?)',
                                 [(name, alias, t, c) for alias, t, c in view_lineage(marked, marks)])
                made.append(name)
            except sqlite3.Error as exc:
                try:
                    conn.execute(f'DROP VIEW IF EXISTS {_q(name)}')
                except sqlite3.Error:
                    pass
                conn.execute('INSERT INTO _source_failures VALUES (?, ?, ?)', (f'view:{name}', str(exc), _now()))
    return made


def _same_process(conn, process) -> bool:
    """True when the previous snapshot was read from the game process `process` (engine.process_key)."""
    if process is None:
        return False
    try:
        row = conn.execute("SELECT value FROM prev._build WHERE key = 'process'").fetchone()
    except sqlite3.Error:
        return False
    return bool(row) and json.loads(row[0]) == [str(p) for p in process]


def _carry(conn, previous: Path | None, module: str, t: SourceTable, game_date, process=None) -> bool:
    """Copy a table's rows and state from the previous snapshot file when its invalidation key
    allows (immutable, append, content; game_date when the previous file was read from this game
    process on this game date, so a rebuild in the middle of a session keeps them); False when
    nothing was carried."""
    if previous is None:
        return False
    try:
        old = conn.execute("SELECT status, fingerprint, built_game_date, note FROM prev._source_tables "
                           "WHERE table_name=?", (t.name,)).fetchone()
    except sqlite3.Error:
        return False
    if not old or old[0] != 'ready':
        return False
    if t.refresh == 'game_date' and (old[2] != game_date or not _same_process(conn, process)):
        return False
    try:
        layout = conn.execute('SELECT layout FROM prev._source_tables WHERE table_name=?', (t.name,)).fetchone()
    except sqlite3.Error:
        layout = None                         # an older file has no layout column
    if ((layout[0] if layout else None) or '') != (t.layout or ''):
        return False                          # stored rows mean something else now: build afresh
    names = [c.name for c in _columns(t)]
    try:
        have = [r[1] for r in conn.execute(f'PRAGMA prev.table_info({_q(t.name)})')]
        if have != names:
            return False                      # the module's columns changed: build afresh
        started = time.time()
        conn.execute(f'INSERT INTO main.{_q(t.name)} SELECT * FROM prev.{_q(t.name)}')
    except sqlite3.Error:
        return False
    n = conn.execute(f'SELECT COUNT(*) FROM {_q(t.name)}').fetchone()[0]
    _record(conn, module, t, rows_total=n, seconds=time.time() - started, cpu=0.0,
            note=(old[3] or ''), fingerprint=old[1], game_date=old[2],
            refresh_info={'kind': 'carried', 'rows': n, 'from_game_date': old[2]})
    # force a check on next reference (content: fingerprint; append/immutable: new rows)
    conn.execute('UPDATE _source_tables SET checked_at=NULL WHERE table_name=?', (t.name,))
    return True


def build_in_snapshot(engine, conn, *, budget_s=None, log=None, only=None, previous: Path | None = None,
                      game_date=None) -> dict:
    """Called by the snapshot build before views: every collection table is created; eager ones
    are built now, lazy ones carried over from `previous` (by invalidation key) or left `lazy`
    for the first query that references them."""
    log = log or (lambda m: None)
    reset_cache(engine)
    conn.executescript(SOURCE_SQL)
    ensure_state_columns(conn)
    found, failures = discover(engine, only=only, log=log)
    conn.executemany('INSERT INTO _source_failures VALUES (?, ?, ?)', [(m, r, _now()) for m, r in failures])
    conn.execute('DELETE FROM _source_views')
    conn.executemany('INSERT OR REPLACE INTO _source_views VALUES (?, ?, ?, ?, ?)',
                     [(v, m, d, tmpl, json.dumps(pol)) for m, v, d, tmpl, pol in discover_views(engine, only=only,
                                                                                               log=log)])
    summary = {'eager': [], 'carried': [], 'lazy': [], 'unavailable': [], 'failed_modules': [m for m, _ in failures],
               'seconds': {}, 'cpu_seconds': {}}
    attached = False
    if previous is not None and Path(previous).is_file():
        try:
            conn.commit()                          # ATTACH is refused inside a transaction
            conn.execute('ATTACH DATABASE ? AS prev', (f'file:{previous}?mode=ro',))
            attached = True
        except sqlite3.Error:
            previous = None
    else:
        previous = None
    try:
        for module, t in found:
            try:
                create_empty(conn, module, t, 'lazy')
            except sqlite3.Error as exc:
                log(f'collection table {t.name}: cannot create ({exc})')
                summary['unavailable'].append(t.name)
                continue
            if t.build_mode != 'eager' or t.slow:
                if _carry(conn, previous, module, t, game_date, getattr(engine, 'process_key', None)):
                    summary['carried'].append(t.name)
                else:
                    mark(conn, t.name, 'lazy', 'built on the first query that references it')
                    summary['lazy'].append(t.name)
                continue
            try:
                rows, seconds, cpu = run_rows(t)
                fill_table(conn, module, t, rows, seconds, coverage_note(t), cpu=cpu, fingerprint=_fingerprint(t),
                           game_date=game_date)
                summary['eager'].append(t.name)
                summary['seconds'][t.name] = round(seconds, 2)
                summary['cpu_seconds'][t.name] = round(cpu, 2)
                if cpu > EAGER_BUDGET_S * 3:
                    log(f'collection table {t.name} is eager but cost {cpu:.1f} CPU s (budget about '
                        f'{EAGER_BUDGET_S} s)')
                log(f'collection table {t.name}: {len(rows)} rows in {seconds:.1f}s ({cpu:.1f} CPU s)')
            except Exception as exc:  # noqa: BLE001 - a failing source never stops the build
                reason = f'{type(exc).__name__}: {exc}'
                log(f'collection table {t.name} failed: {reason}\n{traceback.format_exc(limit=4)}')
                mark(conn, t.name, 'unavailable', reason)
                summary['unavailable'].append(t.name)
    finally:
        if attached:
            conn.commit()
            conn.execute('DETACH DATABASE prev')
    conn.execute('INSERT OR REPLACE INTO _build VALUES (?, ?)', ('sources', json.dumps(summary)))
    return summary


# --------------------------------------------------------------------------- on reference
def collection_tables(path) -> dict:
    """{table: state row dict} of the collection tables in the snapshot at `path` (read-only)."""
    try:
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=10)
    except sqlite3.Error:
        return {}
    try:
        have = [r[1] for r in conn.execute('PRAGMA table_info(_source_tables)')]
        if not have:
            return {}
        return {r[0]: dict(zip(have, r)) for r in conn.execute('SELECT * FROM _source_tables')}
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def _needs(state: dict, t: SourceTable, game_date, now) -> str | None:
    """Why the table must be (re)built or checked now, or None."""
    status = state.get('status')
    if status == 'unavailable':
        return 'retry' if now - (state.get('attempted_at') or 0) >= RETRY_UNAVAILABLE_S else None
    if status != 'ready':
        return 'first reference'
    if t.refresh == 'game_date':
        return 'game date changed' if state.get('built_game_date') != game_date else None
    interval = CHECK_INTERVAL_S if t.check_interval is None else t.check_interval
    if state.get('checked_at') and now - state['checked_at'] < interval:
        return None
    return 'check'


def refresh_tables(engine, path, names, *, log=None, game_date=None) -> dict:
    """Build or refresh the collection tables `names` in the snapshot at `path` per their mode and
    invalidation key. Returns {table: what was done}."""
    log = log or (lambda m: None)
    states = collection_tables(path)
    wanted = [n for n in names if n in states]
    if not wanted:
        return {}
    now = time.time()
    game_date = game_date or engine.game_date()
    reset_cache(engine)
    modules = sorted({states[n]['module'] for n in wanted})
    found, failures = discover(engine, only=modules, log=log)
    by_name = {t.name: (m, t) for m, t in found}
    done = {}
    conn = sqlite3.connect(path, timeout=120)
    try:
        for name in wanted:
            state = states[name]
            module, t = by_name.get(name, (state['module'], None))
            if t is None:
                reason = '; '.join(r for m, r in failures if m == state['module']) or 'module no longer describes it'
                mark(conn, name, 'unavailable', reason)
                conn.commit()
                done[name] = {'unavailable': reason}
                continue
            why = _needs(state, t, game_date, now)
            if why is None:
                continue
            try:
                done[name] = _refresh_one(conn, module, t, state, why, game_date)
            except StatementTooWide as exc:     # the statement must be narrowed; the table stays as it is
                conn.rollback()
                done[name] = {'error': str(exc)}
            except Exception as exc:  # noqa: BLE001 - a failing source never stops the query
                reason = f'{type(exc).__name__}: {exc}'
                log(f'collection table {name} failed: {reason}\n{traceback.format_exc(limit=4)}')
                conn.rollback()
                mark(conn, name, 'unavailable', reason)
                done[name] = {'unavailable': reason}
            conn.commit()
    finally:
        conn.close()
    return done


def _refresh_one(conn, module, t, state, why, game_date) -> dict:
    full = why in ('first reference', 'retry', 'game date changed')
    fp_started, fp_cpu = time.time(), time.process_time()
    fp = _fingerprint(t) if t.refresh == 'content' else None
    fp_cost = {'seconds': round(time.time() - fp_started, 3), 'cpu_seconds': round(time.process_time() - fp_cpu, 3)}
    if not full and t.refresh == 'content':
        if fp is not None and fp == state.get('fingerprint'):
            conn.execute('UPDATE _source_tables SET checked_at=?, last_refresh_json=? WHERE table_name=?',
                         (time.time(), json.dumps({'kind': 'unchanged', 'fingerprint': fp_cost}), t.name))
            return {'unchanged': True, **fp_cost}
        full = True
        why = 'fingerprint changed' if fp is not None else 'no fingerprint'
    if not full and t.refresh in ('append', 'immutable') and t.identity:
        cols = ', '.join(_q(c) for c in t.identity)
        existing = set(conn.execute(f'SELECT {cols} FROM {_q(t.name)}').fetchall())
        if t.new_rows is not None:
            rows, seconds, cpu = run_rows(t, lambda: t.new_rows(existing))
        else:
            rows, seconds, cpu = run_rows(t)
        positions = [[c.name for c in t.columns].index(c) for c in t.identity]
        rows = [r for r in rows if tuple(r[i] for i in positions) not in existing]
        replaced = supersede(conn, t, rows)
        start = (conn.execute(f'SELECT COALESCE(MAX(idx), -1) + 1 FROM {_q(t.name)}').fetchone()[0])
        added = _insert(conn, t, rows, start)
        total = conn.execute(f'SELECT COUNT(*) FROM {_q(t.name)}').fetchone()[0]
        missing = not_read_lines(t)
        note = coverage_note(t) if added or missing else (state.get('note') or '')
        info = {'kind': 'added', 'rows_added': added, 'seconds': round(seconds, 2), 'cpu_seconds': round(cpu, 2)}
        if replaced:
            info['rows_replaced'] = replaced
        if missing:
            info['not_read'] = missing
        _record(conn, module, t, rows_total=total, seconds=seconds, cpu=cpu, note=note, fingerprint=fp,
                game_date=game_date, refresh_info=info)
        out = {'added': added, 'seconds': round(seconds, 2), 'cpu_seconds': round(cpu, 2)}
        if replaced:
            out['replaced'] = replaced
        if missing:
            out['not_read'] = missing
        return out
    rows, seconds, cpu = run_rows(t)
    missing = not_read_lines(t)
    fill_table(conn, module, t, rows, seconds, coverage_note(t), cpu=cpu, fingerprint=fp, game_date=game_date)
    out = {'built': len(rows), 'why': why, 'seconds': round(seconds, 2), 'cpu_seconds': round(cpu, 2)}
    if missing:
        out['not_read'] = missing
    return out


def supersede(conn, t: SourceTable, rows) -> int:
    """Delete the stored rows that `rows` supersede (same `replace_key` values); the count."""
    if not t.replace_key or not rows:
        return 0
    names = [c.name for c in t.columns]
    positions = [names.index(c) for c in t.replace_key]
    keys = sorted({tuple(r[i] for i in positions) for r in rows}, key=repr)
    where = ' AND '.join(f'{_q(c)} IS ?' for c in t.replace_key)
    before = conn.total_changes
    conn.executemany(f'DELETE FROM {_q(t.name)} WHERE {where}', keys)
    return conn.total_changes - before


def tables_referenced(reads) -> set:
    """Base tables in `query.referenced_columns` output ((table, column, view) triples)."""
    return {r[0] for r in reads}


_STATEMENT = contextvars.ContextVar('fmdb_source_statement', default=None)


class StatementTooWide(Exception):
    """Raised by a table whose rows are computed for what a statement names (histories) when the
    statement would need a whole-save computation; tools.db_query returns the message as the
    error (how to narrow the statement) and the table is left unchanged."""


def current_statement():
    """(sql, params, snapshot path) of the statement whose pre-pass is refreshing tables, or None.

    tools.db_query passes it to `refresh_for_query(statement=...)`. A table whose rows depend on
    the statement (player_season_rates) computes nothing without one."""
    return _STATEMENT.get()


def dry_run_connection(engine, statement):
    """(connection, close) for running `statement` once to learn which rows it reads of a table
    whose rows depend on the statement (histories, player_season_rates).

    The connection is read-only. When `engine` is given, the on-demand session of the real run is
    attached first, so a column the game computes (person.person_type, a name) is computed as the
    dry run filters on it; without that the dry run sees NULL where the real run sees a value and
    selects fewer rows. `close()` closes the connection and stores the computed cells. Call it
    with the engine lock held (refresh_for_query holds it).

    A manager-view statement (`manager_view.ManagerStatement`) brings its own masked connection
    (`open_dry_run`), so the rows it reads are decided by what the manager sees."""
    opener = getattr(statement, 'open_dry_run', None)
    if opener is not None:
        return opener()
    sql, params, path = statement
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=30)
    session = None
    if engine is not None:
        try:
            from .. import ondemand, query
            session = ondemand.Session(engine, path)
            session.plan(query.referenced_columns(path, sql, params), sql)
            session.attach(conn)
        except Exception:  # noqa: BLE001 - a dry run without computed columns is still a dry run
            session = None

    def close():
        try:
            conn.close()
        finally:
            if session is not None:
                try:
                    session.finish()
                except Exception:  # noqa: BLE001
                    pass
    return conn, close


def refresh_for_query(engine, path, reads, *, log=None, statement=None) -> dict:
    """The query pre-pass hook (tools.db_query): build or refresh every collection table the
    statement reads. Holds the engine lock while reading the game. `statement` is
    (sql, params, path) of that statement (`current_statement`)."""
    states = collection_tables(path)
    names = sorted(tables_referenced(reads) & set(states))
    if not names:
        return {}
    token = _STATEMENT.set(statement) if statement is not None else None
    try:
        lock = getattr(engine, 'lock', None)
        if lock is None:
            return refresh_tables(engine, path, names, log=log)
        with lock:
            return refresh_tables(engine, path, names, log=log)
    finally:
        if token is not None:
            _STATEMENT.reset(token)


def schema_summary(conn) -> tuple[dict, dict]:
    """({table: summary}, {view: about}) of the collection tables for fm_db_schema."""
    try:
        cols = [r[1] for r in conn.execute('PRAGMA table_info(_source_tables)')]
        rows = [dict(zip(cols, r)) for r in conn.execute('SELECT * FROM _source_tables ORDER BY table_name')]
        extra = conn.execute('SELECT view, description FROM _source_views ORDER BY view').fetchall()
    except sqlite3.Error:
        return {}, {}
    existing = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view'")}
    tables, views = {}, {}
    for r in rows:
        name, status = r['table_name'], r['status']
        entry = {'rows': r['rows'], 'about': f'collection table: {r["description"]}', 'status': status,
                 'mode': r.get('mode'), 'invalidation': r.get('invalidation'),
                 'build_seconds': r.get('seconds'), 'build_cpu_seconds': r.get('cpu_seconds'),
                 'columns': conn.execute('SELECT COUNT(*) FROM _fields WHERE table_name=?', (name,)).fetchone()[0]}
        if status == 'lazy':
            entry['note'] = 'built when a query first references it' + (f' ({r["cost_note"]})' if r['cost_note']
                                                                          else '')
        elif r.get('note'):
            entry['note'] = r['note'][:400]
        tables[name] = entry
        for view in json.loads(r['views_json'] or '{}'):
            if view in existing:
                views[view] = f'resolved view over {name} (names joined)'
    for view, description in extra:
        if view in existing:
            views[view] = description
    return tables, views


def failures(conn) -> list[dict]:
    """Collection modules and views that failed in this snapshot's build, for fm_db_schema: a module
    that fails removes its tables, and a reader of the schema must be told which and why."""
    try:
        rows = conn.execute('SELECT module, reason, at FROM _source_failures ORDER BY at').fetchall()
    except sqlite3.Error:
        return []
    return [{'module': m, 'reason': (r or '')[:300], 'at': at} for m, r, at in rows]


# --------------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    """`python -m fm_live_mcp.fmdb.sources build [--table T ...]`: build or refresh collection
    tables of the live save's snapshot now (scripts and checks; queries do this on reference)."""
    from .. import snapshot
    from ..engine import Engine
    ap = argparse.ArgumentParser(prog='fmdb sources')
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build', help='build or refresh collection tables of the live snapshot')
    b.add_argument('--table', action='append', help='table name (default: every collection table)')
    sub.add_parser('status', help='collection table states of the live snapshot')
    args = ap.parse_args(argv)
    engine = Engine.open()
    try:
        path = snapshot.snapshot_path(engine)
        states = collection_tables(path)
        if args.cmd == 'status':
            print(json.dumps({n: {k: s.get(k) for k in ('status', 'rows', 'mode', 'invalidation', 'seconds',
                                                        'cpu_seconds', 'built_game_date')}
                              for n, s in states.items()}, indent=1))
            return 0
        names = args.table or sorted(states)
        print(json.dumps(refresh_tables(engine, path, names, log=lambda m: print(m, flush=True)), indent=1))
        return 0
    finally:
        engine.close()
