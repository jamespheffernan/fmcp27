"""MCP tools over the fmdb snapshot: fm_db_schema, fm_db_query, fm_db_read, fm_db_refresh.

All four are read-only against the game. The snapshot (`snapshot.py`) holds the direct columns
of the whole save; every `fm_db_query` first checks it against live memory and repairs the rows
that changed (`freshness.py`), then computes the emulated columns the statement names for the
rows it needs (`ondemand.py`). `fm_db_read` is the exact per-record path through the game's own
property getter. No tool starts another process.
"""
from __future__ import annotations

from collections import Counter
import json
import re
import sqlite3
import threading
import time
from typing import Annotated, Any, Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from . import bulkplans, freshness, ondemand, query, snapshot, tables, variant
from .engine import Engine, EngineError, cache_root
from .vm import Unavailable

REFRESH_MATERIALISE_BUDGET_S = 600.0    # fm_db_refresh(columns=[...]): compute named columns now, at most this long
AUDIT_CPU_S = 0.5                       # plan audit after an fm_db_query, in this process (audit.py)
AUDIT_MIN_INTERVAL_S = 15.0             # at most one audit slice in this long: a burst of statements pays once
MANAGER_PREWARM_S = 20.0                # manager view: at most this long computing on-demand cells per query
_STATE = {'engine': None}
_LOCK = threading.Lock()


class FmdbError(RuntimeError):
    pass


# --------------------------------------------------------------------------- plumbing
def engine_for(bridge, session_id) -> Engine:
    with _LOCK:
        try:
            _STATE['engine'] = Engine.from_bridge(bridge, session_id, _STATE['engine'])
        except EngineError as exc:
            raise FmdbError(f'{exc} (call fm_attach first if the session is unknown)') from exc
        return _STATE['engine']


def snapshot_meta(path):
    if not path.is_file():
        return None
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        row = conn.execute('SELECT save_name, save_key, game_date, built_at, build, plans_verified, notes '
                           'FROM _snapshot').fetchone()
        process = conn.execute("SELECT value FROM _build WHERE key='process'").fetchone()
        layout = conn.execute("SELECT value FROM _build WHERE key='layout'").fetchone()
        current = conn.execute("SELECT 1 FROM sqlite_master WHERE name='_direct_pages'").fetchone() is not None
        fresh = freshness.status(conn) if current else {}
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    if not row:
        return None
    keys = ('save_name', 'save_key', 'game_date', 'built_at', 'build', 'plans_verified', 'notes')
    meta = dict(zip(keys, row))
    meta['notes'] = json.loads(meta['notes'] or '[]')
    meta['process'] = json.loads(process[0]) if process else None
    meta['layout'] = layout[0] if layout else None
    meta['current_format'] = current       # snapshots without dependency tables are rebuilt
    meta['fresh'] = fresh
    return meta


_PLAN_COUNTS = {}       # plan cache path -> ((mtime_ns, size), direct plans)


def direct_plan_count(engine) -> int | None:
    """Direct plans in the plan cache of this game build (None without a cache file). A snapshot
    records the count it was built with (`_snapshot.plans_verified`); when a plan is demoted
    afterwards (the differential check, or a shipped plan that fails its check) the counts
    differ and the snapshot, whose column still holds the demoted plan's values, is rebuilt."""
    path = cache_root() / 'plans' / f'{engine.plugin_sha256}.{snapshot.PLAN_FILE_TAG}.json'
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (stat.st_mtime_ns, stat.st_size)
    hit = _PLAN_COUNTS.get(path)
    if hit is None or hit[0] != key:
        store = snapshot.plan_store(engine)
        hit = _PLAN_COUNTS[path] = (key, sum(1 for fields in store.plans.values() for plan in fields.values()
                                              if plan.get('status') == 'direct'))
    return hit[1]


DEMOTED_NOTE = 'direct read plan demoted after the build (audit): computed on demand through the getter'


def repair_demoted(engine, path, plans_now) -> int | None:
    """Turn every stored column whose direct plan is no longer direct in the plan cache into an
    on-demand column, in place: `_column_state` says on_demand for that class, so the stored
    (wrong) cells are never served (`ondemand.Session.cell` serves a class computed on demand only
    from a valid memo cell) and the getter computes them when a statement names the column.
    `_snapshot.plans_verified` becomes `plans_now`. Returns the (table, column, class) entries
    converted, or None when the snapshot could not be written (the caller rebuilds)."""
    store = snapshot.plan_store(engine)
    try:
        conn = sqlite3.connect(path, timeout=30)
    except sqlite3.Error:
        return None
    try:
        rows = conn.execute("SELECT table_name, column_name, class FROM _column_state "
                            "WHERE source='direct' AND status='ready'").fetchall()
        codes = {}
        demoted = []
        for table, name, cls in rows:
            if table not in codes:
                codes[table] = {c.name: c.code for c in snapshot.columns_for(engine.catalog, table)}
            code = codes[table].get(name)
            plan = store.get(cls, code) if code else None
            if code and not (plan and plan.get('status') == 'direct'):
                demoted.append((table, name, cls))
        conn.executemany("UPDATE _column_state SET source='emulated', status='on_demand', note=? "
                         "WHERE table_name=? AND column_name=? AND class=?",
                         [(DEMOTED_NOTE, t, c, cls) for t, c, cls in demoted])
        conn.execute('UPDATE _snapshot SET plans_verified=?', (plans_now,))
        conn.commit()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    engine.__dict__.pop('_fmdb_states', None)       # ondemand.Session.states() reads _column_state again
    return len(demoted)


def current_snapshot(engine, *, build_if_needed=True, log=None, force_check=False):
    """(path, meta, refreshed, live save, stale): the snapshot of the loaded save, made current.

    A snapshot that was read from this game process and save is checked against live memory and
    repaired in place (`freshness.refresh`: rows on changed pages are read again; at most once
    every `freshness.CHECK_INTERVAL_S`). It is built again only when there is none, when the
    process or the save differs, when its format is older, or when a direct plan was demoted
    after it was built. The build runs here, in the calling process; plans that are missing
    for this game build are not derived by a tool call (their columns are computed on demand
    until `scripts/fmdb_snapshot.py` has derived them). `refreshed` says what was done;
    `stale` is True only when `build_if_needed` is False and a rebuild is due, or a rebuild
    failed and the previous snapshot is used."""
    save = engine.save_info()
    path = cache_root() / save.save_key / 'snapshot.sqlite'
    meta = snapshot_meta(path)
    reason = None
    if meta is None:
        reason = 'no snapshot yet'
    elif meta['save_key'] != save.save_key or meta.get('process') != list(map(str, engine.process_key)):
        reason = 'the snapshot was read from another game process or save'
    elif not meta.get('current_format', True):
        reason = 'the snapshot was written by an older reader (no content-check tables)'
    elif snapshot.layout_signature(engine) and meta.get('layout') != snapshot.layout_signature(engine):
        reason = ('the snapshot was written by a reader with other tables or columns; rebuilt so every table '
                  'and column of this reader exists')
    elif meta.get('plans_verified') is not None:
        plans_now = direct_plan_count(engine)
        if plans_now is not None and plans_now != meta['plans_verified']:
            # fewer direct plans: the demoted ones become on-demand columns in place; more: a
            # rebuild reads the new plans' columns directly
            repaired = repair_demoted(engine, path, plans_now) if plans_now < meta['plans_verified'] else None
            if repaired is None:
                reason = ('a direct read plan was added after the snapshot was built (or a demotion could not be '
                          'written in place); rebuilt so every column follows the current plans')
            else:
                meta = snapshot_meta(path)
    refreshed = None
    if not build_if_needed:
        return path, meta, None, save, reason is not None
    if reason is None:
        try:
            refreshed = {'checked': freshness.refresh(engine, path, log=log, force=force_check)}
            meta = snapshot_meta(path)
            return path, meta, refreshed, save, False
        except freshness.Rebuild as exc:
            reason = str(exc)
        except (sqlite3.Error, OSError) as exc:
            # e.g. the cache volume is full: answer from the stored rows and say so
            return path, meta, {'error': str(exc), 'reason': 'the content check could not write; answering from '
                                                             'the rows as last checked'}, save, True
    started = time.time()
    builder = snapshot.Build(engine, log=log, derive_plans=False)
    try:
        builder.run()
    except (snapshot.SnapshotError, EngineError) as exc:
        if meta is None:
            raise FmdbError(str(exc)) from exc
        return path, meta, {'error': str(exc), 'reason': 'rebuild failed; answering from the previous snapshot'}, \
            save, True
    refreshed = {'rebuilt': True, 'reason': reason, 'seconds': round(time.time() - started, 1),
                 'timing': builder.timing}
    missing = builder.plans_missing()
    if missing:
        refreshed['plans_missing'] = missing
        refreshed['next'] = (f'{missing} (class, field) pairs have no direct plan for this game build: their columns '
                             'are computed on demand. Run scripts/fmdb_snapshot.py once (about 40 minutes) to derive '
                             'the plans; the snapshot is then rebuilt with them.')
    return path, snapshot_meta(path), refreshed, save, False


def _public_snapshot(meta, stale=False):
    """What a result says about the data it was answered from."""
    if meta is None:
        return None
    fresh = meta.get('fresh') or {}
    out = {'save_name': meta['save_name'], 'game_date': meta['game_date'], 'built_at': meta['built_at'],
           'stale': bool(stale)}
    for key in ('checked_at', 'checked_ms_ago', 'rows_refreshed', 'pages_changed'):
        if fresh.get(key) is not None:
            out[key] = fresh[key]
    return out


def _notes(meta):
    return (meta or {}).get('notes') or [snapshot.CONSISTENCY_NOTE]


def _refreshed_note(meta):
    """fm_db_query: a note only when the check found rows that moved (they were read again) or
    blocks still moving; the constant 'checked N ms ago' line is in `snapshot` and the tool
    description."""
    fresh = (meta or {}).get('fresh') or {}
    if fresh.get('rows_refreshed'):
        return (f'{fresh["rows_refreshed"]} rows had changed in the game since the last check and were read '
                'again before this answer.')
    return None


def _audit_note(audit):
    """A note when this call's plan audit disagreed with the game's getter (the next call rebuilds)."""
    if not audit or not (audit.get('demoted_now') or audit.get('memo_disagreed')):
        return None
    parts = []
    if audit.get('demoted_now'):
        parts.append(f'{len(audit["demoted_now"])} direct read plans disagreed with the getter and were demoted; '
                     'the next call rebuilds the snapshot without them, so repeat a statement that read those '
                     'columns: ' + ', '.join(d['column'] for d in audit['demoted_now'][:5]))
    if audit.get('memo_disagreed'):
        parts.append('memoised cells disagreed with the getter and were dropped (they are computed again): '
                     + ', '.join(sorted({d['column'] for d in audit['memo_disagreed']})))
    return 'Plan audit: ' + '; '.join(parts) + '.'


# --------------------------------------------------------------------------- schema
def db_schema(bridge, session_id, table=None, search=None, include_pending=False, view='full'):
    if view not in ('full', 'manager'):
        raise FmdbError('view must be "full" or "manager".')
    engine = engine_for(bridge, session_id)
    path, meta, _, save, stale = current_snapshot(engine, build_if_needed=False)
    if stale and meta is not None:
        # A snapshot of another process, plan set or reader layout does not hold the tables this
        # reader describes: after an upgrade a schema call answered "Unknown table 'promise'" from
        # the old file and the client gave up. Build it now (about 20 s, once), as fm_db_query does.
        path, meta, _, save, stale = current_snapshot(engine)
    if view == 'manager' and meta is not None:
        return manager_schema(engine, path, meta, table)
    if meta is None:
        return {'snapshot': None, 'game_date': save.game_date,
                'next': 'No snapshot for this save yet: fm_db_query builds it (10 to 30 seconds).',
                'tables': {t: snapshot.DESCRIPTIONS[t] for t in snapshot.TABLES}}
    conn = query.connect_ro(path)
    try:
        out = {'snapshot': _public_snapshot(meta, stale)}
        if stale:
            out['next'] = 'The snapshot is for another process, save or plan set; fm_db_query rebuilds it.'
        if table:
            return {**out, **_table_schema(conn, table, include_pending)}
        if search:
            return {**out, **_search(conn, search, include_pending)}
        rows = {}
        on_demand = dict(conn.execute("SELECT table_name, COUNT(DISTINCT column_name) FROM _column_state "
                                      "WHERE status='on_demand' GROUP BY table_name"))
        memo = ondemand.memo_summary(conn)
        for name, n in conn.execute('SELECT table_name, rows FROM _tables ORDER BY table_name'):
            counts = dict(conn.execute("SELECT status, COUNT(*) FROM _fields WHERE table_name=? AND code IS NOT NULL "
                                       "GROUP BY status", (name,)).fetchall())
            rows[name] = {'rows': n, 'about': snapshot.DESCRIPTIONS.get(name, ''),
                          'columns_ready': counts.get('ready', 0), 'on_demand': on_demand.get(name, 0),
                          'unavailable': counts.get('unavailable', 0)}
            if name in memo:
                rows[name]['memoised'] = memo[name]
        views = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")]
        from . import sources                                     # collection tables (fmdb/sources)
        collection_tables, collection_views = sources.schema_summary(conn)
        rows.update(collection_tables)
        failed = sources.failures(conn)
        if failed:                                               # a failing module removes its tables
            out['collection_failures'] = failed
        out.update({
            'tables': rows,
            'views': {'player_view': 'one row per real player (virtual youth placeholders excluded): name, age, '
                                     'nationalities, club / contracted club / loan club, position, CA/PA, 1-20 '
                                     'attributes, hidden, personality, condition, injuries, morale, form, season '
                                     'statistics, wage, contract, transfer value',
                      'club_view': 'clubs with nation, city, division, stadium, reputation, finances, facilities, '
                                   'colours',
                      'staff_view': 'non-players with job, club, ratings, personality, tendencies, contract',
                      'competition_view': 'competitions with nation/continent names, type, reputation, level, last '
                                          'winner',
                      '<table>_labelled': f'every table plus <column>_label for enum columns ({len(views) - 4} views)',
                      **collection_views},
            'joins': 'x_idx columns hold the referenced table row idx (e.g. person.nationality_idx -> nation.idx); '
                     'player/non_player/official/journalist/agent.idx = person.idx; team.club_idx -> club.idx.',
            'on_demand': 'columns_ready counts every column a query can read. Of those, on_demand columns are '
                         'computed by the game\'s getter when a statement names them (or the view column built '
                         'from them), for the rows the statement needs; SELECT * does not compute them (it shows '
                         'the cells already computed and NULL elsewhere). Every result says when the data was '
                         'last checked against live memory.',
            'notes': _notes(meta)})
        return out
    finally:
        conn.close()


def _compact_labels(enum_json):
    if not enum_json:
        return None
    labels = json.loads(enum_json)
    if len(labels) > 25:
        return f'{len(labels)} labels; SELECT value, label FROM _enum_labels WHERE table_name=... AND column_name=...'
    return labels


def _table_schema(conn, table, include_pending):
    tables_known = {r[0] for r in conn.execute('SELECT table_name FROM _tables')}
    views = {r[0]: r[1] for r in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='view'")}
    if table in views and table not in tables_known:
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
        return {'view': table, 'columns': cols,
                'about': 'curated view; source columns and statuses: fm_db_schema(table=<base table>)'}
    if table not in tables_known:
        raise FmdbError(f'Unknown table {table!r}. Tables: {", ".join(sorted(tables_known))}; '
                        f'views: {", ".join(sorted(v for v in views if not v.endswith("_labelled")))}.')
    columns, hidden = [], Counter()
    lazy = {r[0] for r in conn.execute("SELECT DISTINCT column_name FROM _column_state WHERE table_name=? "
                                       "AND status='on_demand'", (table,))}
    for name, code, fname, comment, ftype, enum_json, ref, source, status, note in conn.execute(
            'SELECT column_name, code, name, comment, type, enum_json, references_table, source, status, note '
            'FROM _fields WHERE table_name=? ORDER BY rowid', (table,)):
        if status != 'ready' and not include_pending:
            hidden[status] += 1
            continue
        row = {'column': name, 'type': ftype}
        if name in lazy:
            row['on_demand'] = True
        if code:
            row['code'] = code
        meaning = fname or ''
        if comment and comment != fname:
            meaning = f'{meaning} - {comment}' if meaning else comment
        if meaning:
            row['meaning'] = meaning[:160]
        if ref:
            row['references'] = ref
        labels = _compact_labels(enum_json)
        if labels:
            row['labels'] = labels
        if status != 'ready':
            row['status'] = status
        if note and (status != 'ready' or include_pending):
            row['note'] = note[:240]
        columns.append(row)
    rows, classes = conn.execute('SELECT rows, classes_json FROM _tables WHERE table_name=?', (table,)).fetchone()
    out = {'table': table, 'rows': rows, 'classes': json.loads(classes), 'columns': columns}
    if hidden:
        out['hidden_columns'] = dict(hidden)
        out['next'] = 'Pass include_pending=true to list unavailable columns with reasons.'
    if table + '_labelled' in views:
        out['labelled_view'] = table + '_labelled'
    return out


def _search(conn, text, include_pending):
    like = f'%{text}%'
    hits = []
    for t, name, code, fname, status in conn.execute(
            'SELECT table_name, column_name, code, name, status FROM _fields WHERE column_name LIKE ? OR name LIKE ? '
            'OR code = ? OR comment LIKE ? ORDER BY table_name', (like, like, text, like)):
        if status != 'ready' and not include_pending:
            continue
        row = {'table': t, 'column': name, 'meaning': fname}
        if code:
            row['code'] = code
        if status != 'ready':
            row['status'] = status
        hits.append(row)
    return {'search': text, 'matches': hits[:150], 'truncated': len(hits) > 150}


# --------------------------------------------------------------------------- query
def db_query(bridge, session_id, sql, params=None, max_rows=200, view='full'):
    if view not in ('full', 'manager'):
        raise FmdbError('view must be "full" (stored data) or "manager" (what the manager knows).')
    query.check_sql(sql)
    engine = engine_for(bridge, session_id)
    path, meta, refreshed, save, stale = current_snapshot(engine)
    if view == 'manager':
        return manager_query(engine, bridge, session_id, sql, params, max_rows, path, meta, refreshed)
    return _full_query(engine, path, meta, refreshed, stale, sql, params, max_rows)


def _full_query(engine, path, meta, refreshed, stale, sql, params, max_rows):
    """The full view's statement after `current_snapshot` (also the manager view's statements that
    read only public tables, `manager_public_query`)."""
    # Notes only when they change what the caller should do; the constant statements (reads are
    # not atomic, checked against live memory before answering) are in the tool description.
    notes = []
    moved = _refreshed_note(meta)
    if moved:
        notes.append(moved)
    if stale:
        notes.append(f'{refreshed["reason"]}: {refreshed["error"]}' if refreshed and refreshed.get('error')
                     else 'the snapshot could not be made current')
    reads = query.referenced_columns(path, sql, params)
    collections = None
    if not stale:                         # collection tables (fmdb/sources): built or refreshed on reference
        from . import sources
        try:
            collections = sources.refresh_for_query(engine, path, reads, statement=(sql, params, path))
        except (sqlite3.Error, OSError) as exc:
            notes.append(f'collection tables not refreshed: {exc}')
        for name, what in (collections or {}).items():
            if 'unavailable' in what:
                notes.append(f'{name}: unavailable ({what["unavailable"]})')
            if what.get('not_read'):           # part of what the statement names could not be read
                notes.append(sources.not_read_note(name, what['not_read']))
            if 'error' in what:                # sources.StatementTooWide: the statement must be narrowed
                raise FmdbError(f'{name}: {what["error"]}')
    with engine.lock:
        session = ondemand.Session(engine, path)
        try:
            session.plan(reads, sql)
            result = query.run_session(path, sql, params, session=session, max_rows=max_rows)
        finally:
            computed = session.finish()
    result['snapshot'] = _public_snapshot(meta, stale)
    if refreshed and (refreshed.get('rebuilt') or refreshed.get('error')):
        result['refreshed'] = refreshed
    if computed:
        result['computed'] = computed           # what was computed on demand (columns, cells, seconds)
        if computed.get('not_computed'):
            notes.append('on-demand columns that the statement did not name were not computed (their cells are NULL '
                         'unless computed earlier): ' + ', '.join(f'{n} columns of {t}'
                                                                  for t, n in computed['not_computed'].items())
                         + '. Name a column to have it computed.')
        if computed.get('note'):
            notes.append(computed['note'])
    if collections:
        result['collections'] = collections
    audit = plan_audit(engine, path)
    if audit:
        result['audit'] = audit
        line = _audit_note(audit)
        if line:
            notes.append(line)
    result['notes'] = notes
    return result


def plan_audit(engine, path):
    """The budgeted plan audit that follows a query (`audit.run`); never fails the query."""
    now = time.monotonic()
    if _STATE.get('audited_at') is None:
        # not on the first statement of a server process, which already pays for opening the
        # engine and loading the table vectors (the audit cost it 1 to 2 s wall)
        _STATE['audited_at'] = now
        return None
    if now - _STATE['audited_at'] < AUDIT_MIN_INTERVAL_S:
        return None
    _STATE['audited_at'] = now
    try:
        from . import audit
        return audit.run(engine, path, budget_cpu=AUDIT_CPU_S)
    except Exception as exc:  # noqa: BLE001 - an audit problem is reported, not raised
        return {'error': f'{type(exc).__name__}: {exc}'}


# --------------------------------------------------------------------------- manager view
MANAGER_WAIT_S = 40.0
_MANAGER = {'thread': None, 'result': None, 'error': None, 'started': None}
RANGE_LINES = ['<attr>_min >= x: the manager knows it is at least x (sure).',
               '<attr>_max >= x: at least x is consistent with what the manager knows (could be).']


def _knowledge_path(engine):
    from . import knowledge_store as ks
    return ks.cache_root() / engine.save_info().save_key / ks.FILE_NAME


def knowledge_progress(path) -> dict:
    """Read-only coverage of a knowledge store (players covered / universe), or zeros."""
    from . import knowledge_store as ks
    out = {'covered': 0, 'universe': None, 'tier1_complete': False, 'tier3_complete': False}
    if not path.is_file():
        return out
    try:
        store = ks.KnowledgeStore.__new__(ks.KnowledgeStore)
        store.path, store.con = path, ks.connect(path, readonly=True)
        try:
            cov = store.coverage()
        finally:
            store.con.close()
    except Exception:  # noqa: BLE001 - schema not created yet
        return out
    out.update(covered=cov.get('universe_players_covered') or cov.get('knowledge_rows') or 0,
               universe=cov.get('universe_players'), tier1_complete=cov.get('tier1_complete'),
               tier3_complete=cov.get('tier3_complete'), game_date=cov.get('game_date'))
    return out


def _prepare_manager(engine, bridge, session_id, sql, wait_s, params=None, max_rows=None):
    """prepare_manager_query on a worker thread so a statement that needs knowledge for much of
    the save (minutes the first time) returns a 'building' status instead of outliving the
    client's timeout."""
    from . import manager_view as mv
    state = _MANAGER
    thread = state['thread']
    if thread is not None and thread.is_alive():
        thread.join(wait_s)
        if thread.is_alive():
            return None
    if state['result'] is not None:          # a finished build from an earlier call: discard its connection
        try:
            state['result'].connection.close()
        except Exception:  # noqa: BLE001
            pass
        state['result'] = None
    state['error'] = None

    def work():
        try:
            state['result'] = mv.prepare_manager_query(engine, sql, bridge_or_session=(bridge, session_id),
                                                       params=params, max_rows=max_rows)
        except Exception as exc:  # noqa: BLE001 - reported to the caller
            state['error'] = exc

    state['thread'] = threading.Thread(target=work, name='fmdb-manager-prepare', daemon=True)
    state['started'] = time.time()
    state['thread'].start()
    state['thread'].join(wait_s)
    if state['thread'].is_alive():
        return None
    if state['error'] is not None:
        exc, state['error'] = state['error'], None
        if isinstance(exc, mv.ManagerViewError):
            raise FmdbError(f'Manager view: {exc}') from exc
        raise exc
    result, state['result'] = state['result'], None
    return result


def manager_query(engine, bridge, session_id, sql, params, max_rows, path, meta, refreshed,
                  wait_s=None):
    from . import manager_view as mv
    try:
        mv.check_sql(sql)
    except mv.ManagerViewError as exc:
        raise FmdbError(f'Manager view: {exc}') from exc
    public = manager_public_query(engine, path, meta, refreshed, sql, params, max_rows)
    if public is not None:
        return public
    pre_notes = []
    collections = _manager_collections(engine, path, sql, params, pre_notes)
    q = _prepare_manager(engine, bridge, session_id, sql, MANAGER_WAIT_S if wait_s is None else wait_s,
                         params, max_rows)
    if q is not None and collections is not None and (q.coverage.get('on_demand') or {}).get('evaluated'):
        # knowledge computed for this statement can widen what a statement-dependent table
        # (histories, season rates) must compute: check those tables again with it
        again = _manager_collections(engine, path, sql, params, pre_notes)
        if any('added' in w and w.get('added') for w in (again or {}).values()):
            q.connection.close()
            q = _prepare_manager(engine, bridge, session_id, sql, MANAGER_WAIT_S if wait_s is None else wait_s,
                                 params, max_rows)
        for name, what in (again or {}).items():
            collections.setdefault(name, what)
    if q is None:
        progress = knowledge_progress(_knowledge_path(engine))
        total = progress['universe'] or 'all'
        elapsed = time.time() - (_MANAGER['started'] or time.time())
        return {'status': 'building', 'columns': [], 'rows': [], 'row_count': 0, 'truncated': False,
                'view': 'manager', 'coverage': progress,
                'notes': [f'Building manager knowledge for {meta["game_date"]}: {progress["covered"]} of {total} '
                          f'players covered so far ({elapsed:.0f}s elapsed). Only the rows the statement reads '
                          'are computed; a statement that reads knowledge columns of every player takes a few '
                          'minutes the first time and much less afterwards. Call fm_db_query again with the '
                          'same SQL in about 30 s; no rows were returned yet.' + subquery_hint(sql)]}
    try:
        computed = manager_prewarm(engine, path, sql, q, params, max_rows)
        computed_refs = manager_prewarm_refs(engine, path, sql, q, params, max_rows)
        if computed_refs:
            computed = dict(computed or {}, cells=(computed or {}).get('cells', 0) + computed_refs['cells'],
                            **({'not_stored': computed_refs['not_stored']} if computed_refs.get('not_stored') else {}))
        try:
            result = query.fetch(q.connection, sql, params, max_rows=max_rows)
        except query.QueryError as exc:
            raise query.QueryError(_manager_denied_hint(str(exc), sql, path)) from exc
    finally:
        q.connection.close()
    # Notes only when they change what the caller should do (partial knowledge, cells not computed);
    # the knowledge summary is in `message`, the masking rules in the tool description.
    notes = pre_notes + ([q.message] if not q.complete else []) + list(q.notes)
    if collections:
        result['collections'] = collections
    if computed and computed.get('not_stored'):
        notes.append('On-demand columns are incomplete in this result: ' + computed['not_stored'] + '. Narrow the '
                     'statement to m_scouted_player_view or to idx values, or repeat it: cells computed so far are kept '
                     'while the bytes they read stay the same.')
    if not q.complete:
        notes.append('Partial population: the knowledge this statement reads could not be completed '
                     f'({q.coverage.get("universe_players_covered")} of {q.coverage.get("universe_players")} '
                     'players current). Repeat the query, or read m_scouted_player_view for the scouted population.')
    result.update(view='manager', coverage={k: q.coverage.get(k) for k in (
        'universe_players', 'universe_players_covered', 'scouted_rows', 'tier1_complete', 'tier3_complete',
        'fill_running', 'game_date')}, complete=q.complete, message=q.message,
        snapshot=_public_snapshot(meta, False), notes=notes)
    if refreshed and (refreshed.get('rebuilt') or refreshed.get('error')):
        result['refreshed'] = refreshed
    return result


def manager_public_query(engine, path, meta, refreshed, sql, params, max_rows):
    """A manager statement whose every masked view has policy `public` (every row and column as
    stored) and that reads no player knowledge is the full statement over the same rows: it is
    checked on a masked connection first (so a bare table or a withheld view is refused exactly
    as there), then answered by the full path on the statement with each m_<name> written as
    <name>. It costs what the full statement costs, builds and refreshes collection tables and
    computes on-demand cells the same way. None when the statement does not qualify."""
    from . import manager_view as mv
    names = mv.referenced_names(sql)
    masked = {n for n in names if n.startswith('m_')}
    if not masked or names & mv.KNOWLEDGE_VIEWS or 'kn' in names:
        return None
    try:
        con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        try:
            cat = mv.catalog(con)
        finally:
            con.close()
    except sqlite3.Error:
        return None
    if not all(n in cat and cat[n].scope == 'public' for n in masked):
        return None
    try:
        check = mv.open_manager_connection(path, _knowledge_path(engine), only=masked)
    except mv.ManagerViewError:
        return None
    try:
        if not masked <= set(check.manager_info['public_views']):
            return None                         # a declared-public view the manager view refused
        try:
            check.execute(f'EXPLAIN {sql}', params or ()).fetchall()
        except sqlite3.Error as exc:
            raise query.QueryError(_manager_denied_hint(f'SQL error: {exc}.', sql, path)) from exc
    finally:
        check.close()
    full_sql = mv.rename_views(sql, {n: cat[n].base for n in masked})
    result = _full_query(engine, path, meta, refreshed, False, full_sql, params, max_rows)
    result.update(view='manager', complete=True,
                  message='Public tables only: every row and column the statement reads is shown to any manager.')
    return result


def _manager_collections(engine, path, sql, params, notes):
    """Build or refresh the collection tables a manager statement reads (through its m_* names),
    as the full path does; a statement-dependent table (histories, season rates) runs its dry
    run on a masked connection (`manager_view.ManagerStatement`). None when it reads none."""
    from . import manager_view as mv
    from . import sources
    try:
        tables = mv.collection_reads(path, sql)
    except sqlite3.Error:
        return None
    if not tables:
        return None
    statement = mv.ManagerStatement(sql, params, path, _knowledge_path(engine))
    try:
        done = sources.refresh_for_query(engine, path, {(t, None, None) for t in tables}, statement=statement)
    except (sqlite3.Error, OSError) as exc:
        notes.append(f'collection tables not refreshed: {exc}')
        return {}
    for name, what in (done or {}).items():
        if 'unavailable' in what:
            notes.append(f'{name}: unavailable ({what["unavailable"]})')
        if what.get('not_read'):               # part of what the statement names could not be read
            notes.append(sources.not_read_note(name, what['not_read']))
        if 'error' in what:                    # sources.StatementTooWide: the statement must be narrowed
            raise FmdbError(f'{name}: {what["error"]}')
    return dict(done or {})


def _manager_denied_hint(message, sql, path=None):
    """A denied read on a manager connection: name the masked view to use instead."""
    if 'not authorized' not in message and 'prohibited' not in message:
        return message
    from . import manager_view as mv
    try:
        con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        try:
            known = {e.base: n for n, e in mv.catalog(con).items()}
        finally:
            con.close()
    except (sqlite3.Error, TypeError):
        known = {}
    known.update({'player_view': 'm_player_view', 'player': 'm_player', 'person': 'm_person'})
    use = sorted(f'{n} -> {known[n]}' for n in mv.referenced_names(sql) if n in known)
    return (f'{message} In the manager view every table and view is read as m_<name>'
            + (f' ({"; ".join(use[:6])})' if use else '') + '; the bare names are the stored data. '
            'fm_db_schema(view="manager") lists the m_* views with their policy.')


def subquery_hint(sql) -> str:
    """For a statement that reaches every player through a subquery: the usual cause (a column the
    subquery's own table lacks is the outer row's, so the subquery is correlated and keeps every row)."""
    if not re.search(r'\(\s*select\b', sql or '', re.I):
        return ''
    return (' If a subquery picks the players, check that every column in it belongs to its own table: a '
            'column that table lacks is read from the outer row (club_idx in a subquery over m_club_view, '
            'whose key is idx), so the subquery keeps every player. Write e.g. WHERE club_idx IN '
            "(SELECT idx FROM m_club WHERE name = 'Newcastle United'), or join m__managed for your own club.")


def manager_prewarm_refs(engine, path, sql, q, params=None, max_rows=None):
    """Compute the on-demand cells of core tables (team, competition, stadium, injury names ...)
    that the generic masked views showed, for exactly the rows the masked statement read
    (`ManagerQuery.refs`), and only for columns the statement names (as the full path, which
    does not compute columns that `SELECT *` leaves unnamed). Repeats the probe up to twice when
    the statement filters, joins or sorts on such a column."""
    from . import manager_view as mv
    refs = getattr(q, 'refs', None)
    need = getattr(q.connection, 'manager_need', None)
    if not refs:
        return None
    tokens = {t.lower() for t in re.findall(r'[A-Za-z_][A-Za-z0-9_]*', sql)}
    after_from = {t.lower() for t in re.findall(r'[A-Za-z_][A-Za-z0-9_]*',
                                                  re.split(r'\bfrom\b', sql, maxsplit=1, flags=re.I)[-1])}
    deadline = time.time() + MANAGER_PREWARM_S
    done, cells, problem = {}, 0, None
    with engine.lock:
        for _round in range(3):
            todo = {}
            for (view, column, table, base_column), idxs in refs.items():
                if column.lower() not in tokens:
                    continue
                left = idxs - done.get((table, base_column), set())
                if left:
                    todo.setdefault((table, base_column), set()).update(left)
            if not todo:
                break
            before = cells
            for (table, base_column), idxs in sorted(todo.items()):
                done.setdefault((table, base_column), set()).update(idxs)
                left = deadline - time.time()
                if left <= 0:
                    problem = problem or f'the {MANAGER_PREWARM_S:g} s budget was used before {table}.{base_column}'
                    continue
                probe = (f'SELECT count("{base_column}") FROM "{table}" '
                         'WHERE idx IN (SELECT value FROM json_each(?))')
                args = [json.dumps(sorted(idxs))]
                session = ondemand.Session(engine, path, bulk_budget_s=left)
                try:
                    if session.plan(query.referenced_columns(path, probe, args), probe):
                        query.run_session(path, probe, args, session=session, time_limit_s=left, count_compute=True)
                except query.QueryError:
                    problem = (f'{table}.{base_column} could not be computed for all {len(idxs)} rows within '
                               f'{MANAGER_PREWARM_S:g} s; the rows not reached read NULL')
                finally:
                    summary = session.finish()
                    cells += summary.get('cells', 0)
                    if summary.get('cells') and not summary.get('stored'):
                        problem = summary.get('note') or 'the computed cells could not be stored'
            names = {c.lower() for (_, c, _, _) in refs}
            if need is None or problem or time.time() >= deadline or cells == before or not names & after_from:
                break
            need.clear()
            mv._probe(q.connection, sql, params, max_rows)
            refs = mv.refs_read(need)
    if not cells and not problem:
        return None
    return {'cells': cells, **({'not_stored': problem} if problem else {})}


_STAR = re.compile(r'(?:select|,)\s*(?:distinct\s+)?(?:"?\w+"?\.)?\*', re.I)
_MANAGER_BASE = {'m_player_view': 'player_view', 'm_scouted_player_view': 'player_view', 'm_player': 'player',
                 'm_person': 'person'}


def manager_prewarm(engine, path, sql, q, params=None, max_rows=None):
    """Compute the on-demand cells a manager-view statement can show, and no others.

    The masked views read the stored tables, so the cells must be stored before the statement
    runs. For every masked view the statement reads, the columns it names are taken with their
    policy from `m_columns`: a `public` column is computed for the players the view can show
    (the scouted ones when the statement is limited to them), an `own_club` column only for the
    manager's own players, and `never`, attribute and knowledge columns not at all. With a live
    game (`q.cells`), the rows are narrower: per column, exactly the rows whose cell the
    statement read through the masked view when prepare_manager_query probed it; the statement
    is probed again after the cells are stored, up to three rounds, for rows a filter on a
    column that read NULL kept out. The work is
    done by a probe through the full view (`count(<column>)` over those rows), so cells of
    joined tables (club and nation names) are computed for exactly the rows that are shown.
    What is computed depends on the statement's text and on who the manager knows, never on a
    withheld value. `SELECT *` computes nothing; the stored cells it shows are checked first.
    The work stops after `MANAGER_PREWARM_S`: the cells not reached read NULL in this result
    and the result says so (a dear column over the whole population, such as position text at
    about 1 ms per player, does not fit; `m_scouted_player_view` or a filter by idx does)."""
    from . import manager_view as mv
    tokens = {t.lower() for t in re.findall(r'[A-Za-z_][A-Za-z0-9_]*', sql)}
    used = [v for v in _MANAGER_BASE if v in tokens]
    if not used:
        return None
    policies = {}
    for view, column, policy in q.connection.execute('SELECT view, column_name, policy FROM m_columns'):
        policies.setdefault(view, {})[column] = policy
    try:
        kn = sqlite3.connect(f'file:{_knowledge_path(engine)}?mode=ro', uri=True)
        try:
            people = kn.execute('SELECT idx, own_club, scouted FROM knowledge_player').fetchall()
        finally:
            kn.close()
    except sqlite3.Error:
        return None
    scouted_only = mv.limited_to_scouted(sql)
    own = {i for i, o, _ in people if o}
    reached = getattr(q, 'cells', None)        # rows whose on-demand cells the masked statement read
    need = getattr(q.connection, 'manager_need', None)
    cells, problem = 0, None
    deadline = time.time() + MANAGER_PREWARM_S
    done = {}
    with engine.lock:
        if _STAR.search(sql):
            session = ondemand.Session(engine, path)
            try:
                for view in used:
                    for table in sorted({t for t, _, _ in query.referenced_columns(
                            path, f'SELECT * FROM {_MANAGER_BASE[view]} LIMIT 0')}):
                        session.check_stored(table)
            finally:
                session.finish()
        for _round in range(3):
            before = cells
            if reached is not None:
                todo = {c: idxs - done.get(c, set()) for c, idxs in reached.items()}
                todo = {c: idxs for c, idxs in todo.items() if idxs}
                if not todo:
                    break
                for c, idxs in todo.items():
                    done.setdefault(c, set()).update(idxs)
            for view in used:
                base = _MANAGER_BASE[view]
                columns = policies.get('m_player_view' if view == 'm_scouted_player_view' else view, {})
                work = []                       # (policy, idx list, column names)
                for policy in (mv.PUBLIC, mv.OWN_CLUB):
                    named = sorted(c for c, p in columns.items() if p == policy and c.lower() in tokens)
                    if reached is not None:
                        # exactly the cells the statement read through the masked view, per column
                        groups = {}
                        for c in named:
                            idxs = todo.get(c, set()) & (own if policy == mv.OWN_CLUB else todo.get(c, set()))
                            if idxs:
                                groups.setdefault(tuple(sorted(idxs)), []).append(c)
                        work += [(policy, list(idxs), names) for idxs, names in groups.items()]
                    else:
                        narrow = scouted_only or view == 'm_scouted_player_view'
                        idxs = [i for i, o, scouted in people if scouted or not narrow] if policy == mv.PUBLIC \
                            else sorted(own)
                        work.append((policy, idxs, named))
                for policy, idxs, names in work:
                    if not names or not idxs:
                        continue
                    select = ', '.join('count("' + c.replace('"', '""') + '")' for c in names)
                    probe = f'SELECT {select} FROM {base} WHERE idx IN (SELECT value FROM json_each(?))'
                    args = [json.dumps(idxs)]
                    left = deadline - time.time()
                    if left <= 0:
                        problem = problem or f'the {MANAGER_PREWARM_S:g} s budget was used before {", ".join(names)}'
                        continue
                    session = ondemand.Session(engine, path, bulk_budget_s=left)
                    try:
                        if session.plan(query.referenced_columns(path, probe, args), probe):
                            query.run_session(path, probe, args, session=session, time_limit_s=left,
                                              count_compute=True)
                    except query.QueryError:
                        problem = (f'{", ".join(names)} could not be computed for all {len(idxs)} players within '
                                   f'{MANAGER_PREWARM_S:g} s; the players not reached read NULL'
                                   + (subquery_hint(sql) if len(idxs) > 5000 else ''))
                    finally:
                        summary = session.finish()
                        cells += summary.get('cells', 0)
                        if summary.get('cells') and not summary.get('stored'):
                            problem = summary.get('note') or 'the computed cells could not be stored'
            if reached is None or need is None or problem or time.time() >= deadline:
                break
            # Only a statement that filters, joins, groups or sorts on a computed column can read
            # further rows now; one that only shows it read exactly these (a probe costs about as
            # much as the statement: 0.7 s for a filter over the player universe).
            after_from = {t.lower() for t in re.findall(r'[A-Za-z_][A-Za-z0-9_]*',
                                                          re.split(r'\bfrom\b', sql, maxsplit=1, flags=re.I)[-1])}
            if cells == before or not {c.lower() for c in done} & after_from:
                break                           # nothing new was stored, or no filter reads it
            # With the cells stored the statement may read further rows (a filter on a column that
            # was NULL before): run it again through the masked connection and compute what it adds.
            need.clear()
            mv._probe(q.connection, sql, params, max_rows)
            reached = mv.cells_read(need)
    if not cells and not problem:
        return None
    return {'cells': cells, **({'not_stored': problem} if problem else {})}


# views listed by fm_db_schema(view="manager") that are not rows of m_columns
MANAGER_ALIASES = {'m_scouted_player_view': 'm_player_view'}
MANAGER_METADATA_VIEWS = {'m_columns': 'every masked column with its policy',
                          'm_attribute_columns': 'the 47 attributes and their column names',
                          'm_coverage': 'how much of the save the knowledge covers (key, value)'}


def manager_schema(engine, path, meta, table=None):
    from . import manager_view as mv
    knowledge = _knowledge_path(engine)
    progress = knowledge_progress(knowledge)
    base = {'view': 'manager', 'snapshot': _public_snapshot(meta, False), 'knowledge': progress,
            'range_filters': RANGE_LINES}
    static = {'m_player_view': 'player_view masked to what the manager knows',
              'm_scouted_player_view': 'm_player_view limited to scouted players (complete population)',
              'm_player': 'player table masked', 'm_person': 'person table masked',
              'm_columns': 'every masked column with its policy',
              'm_attribute_columns': 'the 47 attributes and their column names',
              'm_coverage': 'how much of the save the knowledge covers',
              'm_tables': 'every manager view and withheld object: scope, rule, reason'}
    no_knowledge = not progress['tier1_complete'] and not knowledge.is_file()
    try:
        if no_knowledge:
            names = _generic_manager_names(path)
            con = mv.open_manager_connection(path, knowledge, only=names)
        else:
            con = mv.open_manager_connection(path, knowledge)
    except mv.ManagerViewError as exc:
        raise FmdbError(f'Manager view: {exc}') from exc
    try:
        rows = con.execute('SELECT view, column_name, code, policy, field FROM m_columns').fetchall()
        views = {}
        for v, name, code, policy, fld in rows:
            views.setdefault(v, []).append((name, code, policy, fld))
        try:
            listed = {r[0]: r[1:] for r in con.execute('SELECT view, scope, rule, reason FROM m_tables')}
        except sqlite3.Error:
            listed = {}
        if table and table in listed and table not in views:
            scope, rule, reason = listed[table]
            raise FmdbError(f'{table} is withheld in the manager view: {reason}')
        if table and table in listed:
            scope, rule, reason = listed[table]
            cols = [{'column': name, 'policy': policy, **({'code': code} if code else {})}
                    for name, code, policy, _ in views[table] if policy != mv.NEVER]
            base.update(table=table, scope=scope, about=f'{rule}' + (f' ({reason})' if reason else ''),
                        columns=cols, withheld=sorted(n for n, _, p, _ in views[table] if p == mv.NEVER),
                        policies={'public': 'shown on every row', 'own_club': "shown only on your club's rows",
                                  'identity': 'row identity'})
            return base
        if no_knowledge and not table:
            base['next'] = ('No manager knowledge stored yet: fm_db_query(view="manager") computes what each '
                            'statement reads (seconds for the scouted population, minutes the first time for '
                            'knowledge columns of the whole save).')
            base['views'] = dict(static)
            base['views'].update({v: f'{s}: {r}' for v, (s, r, _) in sorted(listed.items()) if s != 'never'})
            base['withheld'] = {v: reason for v, (s, _, reason) in sorted(listed.items()) if s == 'never'}
            return base
        if table:
            if table in MANAGER_METADATA_VIEWS:
                cur = con.execute(f'SELECT * FROM {table} LIMIT 0')
                base.update(table=table, columns=[{'column': d[0]} for d in cur.description],
                            about=MANAGER_METADATA_VIEWS[table])
                return base
            source = MANAGER_ALIASES.get(table, table)
            if source not in views:
                raise FmdbError(f'Unknown manager view {table!r}; manager views: '
                                f'{", ".join(sorted(set(views) | set(MANAGER_ALIASES) | set(MANAGER_METADATA_VIEWS)))}.')
            if source != table:
                base['about'] = f'{table} has the columns of {source}, limited to scouted players'
            attrs = sorted({fld for _, _, policy, fld in views[source] if policy == mv.ATTRIBUTE and fld})
            cols = []
            for name, code, policy, fld in views[source]:
                if policy == mv.ATTRIBUTE or policy == mv.NEVER:
                    continue
                cols.append({'column': name, 'policy': policy, **({'code': code} if code else {})})
            attr_cols = sorted({name for name, _, policy, _ in views[source] if policy == mv.ATTRIBUTE
                                and not name.endswith(('_min', '_max', '_state'))})
            base.update(table=table, columns=cols, attributes=attr_cols,
                        attribute_columns='each attribute appears as <attr>, <attr>_min, <attr>_max, <attr>_state',
                        withheld=sorted(name for name, _, policy, _ in views[source] if policy == mv.NEVER),
                        policies={'public': 'shown for every player', 'own_club': 'shown only for your own players',
                                  'identity': 'row identity'}, attribute_fields=len(attrs))
            return base
        base['views'] = {v: {'columns': len(c), 'attributes': len({f for _, _, p, f in c if p == mv.ATTRIBUTE and f})}
                         for v, c in sorted(views.items()) if v not in listed}
        base['views'].update({'m_scouted_player_view': 'm_player_view WHERE scouted = 1',
                              'm_columns': 'column policies', 'm_attribute_columns': '47 attribute columns',
                              'm_coverage': 'coverage key/value'})
        if listed:
            base['views']['m_tables'] = 'every manager view and withheld object: scope, rule, reason'
            # one line each: scope and what the manager sees
            base['views'].update({v: f'{s}: {r}' for v, (s, r, _) in sorted(listed.items()) if s != 'never'})
            base['withheld'] = {v: reason for v, (s, _, reason) in sorted(listed.items()) if s == 'never'}
        base['next'] = ('fm_db_schema(view="manager", table="m_player_view") lists its columns; every table and '
                        'view of the full schema is m_<name> here.')
        return base
    finally:
        con.close()


def _generic_manager_names(path):
    """Public names of the generic masked views (every object but the knowledge views)."""
    from . import manager_view as mv
    con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        return set(mv.catalog(con))
    finally:
        con.close()


def _manager_read_guard(path, table, idx):
    """Manager view: person-family records only for the manager's own club."""
    if snapshot.TABLES[table] not in ('pers', 'play', 'nnpl', 'offc', 'jour', 'agen'):
        return
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        club_col = conn.execute("SELECT column_name FROM _fields WHERE table_name='person' AND code='Pcti'").fetchone()
        own = {r[0] for r in conn.execute('SELECT team_idx FROM _managed')}
        outside = []
        for i in idx:
            row = conn.execute(f'SELECT "{club_col[0]}" FROM person WHERE idx=?', (i,)).fetchone() if club_col else None
            if not row or row[0] not in own:
                outside.append(i)
    finally:
        conn.close()
    if outside:
        raise FmdbError(f'Manager view: idx {outside} are not at your club, and a live exact read would bypass '
                        'the manager\'s knowledge. Use fm_db_query(view="manager") on m_player_view or '
                        'fm_get_manager_visible_attributes for what the manager sees.')


# --------------------------------------------------------------------------- read
def _json_value(column, result, resolver):
    value = result.value
    if isinstance(value, Unavailable):
        return None, value.reason
    if result.kind == 'null' or value is None:
        return None, None
    if isinstance(value, (bytes, bytearray)):
        rating = bulkplans.blob_rating(value)
        out = {'data_hex': bytes(value).hex()}
        if rating is not None:
            out['rating'] = rating
        return out, None
    if column is not None and column.kind == 'ref' and isinstance(value, (variant.RecordRef, int)) \
            and not isinstance(value, bool):
        ref = bulkplans.canonical_value(value)
        idx = resolver.ref(column, -1, ref)
        raw = value.to_json() if isinstance(value, variant.RecordRef) else {'unique_id': value}
        return {'idx': idx, 'table': column.references, **raw}, None
    return variant.to_json(value), None


def db_read(bridge, session_id, table, idx, fields=None, view='full'):
    if table not in snapshot.TABLES:
        raise FmdbError(f'Unknown table {table!r}. Tables: {", ".join(snapshot.TABLES)}.')
    if isinstance(idx, int) and not isinstance(idx, bool):
        idx = [idx]
    if not isinstance(idx, list) or not 1 <= len(idx) <= 50 or any(
            not isinstance(i, int) or isinstance(i, bool) or i < 0 for i in idx):
        raise FmdbError('idx must be 1-50 non-negative integers (row idx values from fm_db_query).')
    if view not in ('full', 'manager'):
        raise FmdbError('view must be "full" or "manager".')
    engine = engine_for(bridge, session_id)
    if view == 'manager':
        path, _, _, _, _ = current_snapshot(engine)
        _manager_read_guard(path, table, idx)
    started = time.time()
    with engine.lock:
        engine.fresh()
        rtype = snapshot.TABLES[table]
        kind = tables.RECORD_TYPES[rtype].table
        live = snapshot.enumerate_table(engine, kind)
        columns = snapshot.columns_for(engine.catalog, table)
        # is_injured of a player, as player_view has it: his injuries leave days still out. The
        # catalog key of that name (Phij) reads a table that is empty in a running career.
        injured_alias = table == 'player' and (not fields or 'is_injured' in fields)
        if fields:
            wanted = {f for f in fields}
            if injured_alias:
                wanted = (wanted - {'is_injured'}) | {'injury_days_remaining'}
            chosen = [c for c in columns if c.name in wanted or c.code in wanted]
            unknown = wanted - {c.name for c in chosen} - {c.code for c in chosen}
            if unknown:
                raise FmdbError(f'Unknown fields for {table}: {sorted(unknown)}. See fm_db_schema(table={table!r}).')
        else:
            chosen = columns
        live_by_sql = {}
        for t in {c.references for c in chosen if c.kind == 'ref' and c.references} | \
                {t for c in chosen if c.kind == 'ref' for v in snapshot.REF_FOURCC.values() for t in v}:
            k = tables.RECORD_TYPES[snapshot.TABLES[t]].table
            live_by_sql[t] = live if k == kind else snapshot.enumerate_table(engine, k)
        resolver = snapshot.Resolver(live_by_sql)
        wanted_classes = set(tables.RECORD_TYPES[rtype].classes)
        records = []
        for i in idx:
            if i >= len(live.pointers) or not live.pointers[i]:
                records.append({'idx': i, 'error': 'no record at this idx in the live table'})
                continue
            cls = live.classes[i]
            if wanted_classes and cls not in wanted_classes:
                records.append({'idx': i, 'class': cls, 'error': f'idx {i} is a {cls}, not a {table} record'})
                continue
            values, unavailable, not_handled = {}, {}, []
            for col in chosen:
                result = engine.get_property(live.pointers[i], col.code)
                if result.kind == 'null' and result.handled is False:
                    if fields:
                        not_handled.append(col.name)
                    continue
                value, reason = _json_value(col, result, resolver)
                if reason:
                    unavailable[col.name] = reason
                else:
                    values[col.name] = value
            if injured_alias:
                days = values.get('injury_days_remaining')
                if isinstance(days, int) and not isinstance(days, bool):
                    values['is_injured'] = days > 0
                elif 'injury_days_remaining' in unavailable:
                    unavailable['is_injured'] = unavailable['injury_days_remaining']
                if fields and 'injury_days_remaining' not in fields and 'x:injury_days_remaining' not in fields:
                    values.pop('injury_days_remaining', None)
                    unavailable.pop('injury_days_remaining', None)
            if view == 'manager' and snapshot.TABLES[table] in ('pers', 'play', 'nnpl', 'offc', 'jour', 'agen'):
                from . import manager_view as mv
                codes = {c.name: c.code for c in chosen}
                hidden = sorted(n for n in list(values) + list(unavailable)
                                if mv._policy_for_code(codes.get(n)) == mv.NEVER)
                for n in hidden:
                    values.pop(n, None)
                    unavailable.pop(n, None)
            row = {'idx': i, 'uid': live.uids[i], 'class': cls, 'values': values}
            if unavailable:
                row['unavailable'] = unavailable
            if not_handled:
                row['not_handled'] = not_handled
            records.append(row)
    return {'table': table, 'records': records, 'read_at_game_date': engine.game_date(),
            'seconds': round(time.time() - started, 2),
            'notes': ['Fresh read through the game\'s own property getter (emulated, read-only). '
                      'Null values are omitted; attribute blobs show data_hex and the 1-20 rating.',
                      snapshot.CONSISTENCY_NOTE]}


# --------------------------------------------------------------------------- refresh
def db_refresh(bridge, session_id, tables_=None, columns=None):
    """No arguments: build the snapshot again now (an explicit rebuild; queries keep a snapshot
    current by themselves). columns: compute those on-demand columns for every row now, at most
    REFRESH_MATERIALISE_BUDGET_S. tables: kept for older callers; nothing is queued, because a
    column is computed when a query names it. Everything runs in this process."""
    engine = engine_for(bridge, session_id)
    started = time.time()
    out = {}
    if columns or tables_:
        path, meta, refreshed, _, _ = current_snapshot(engine, force_check=True)
        if refreshed:
            out['rebuilt' if refreshed.get('rebuilt') else 'checked'] = refreshed
    else:
        builder = snapshot.Build(engine, derive_plans=False)
        path = builder.run()
        out['rebuilt'] = {'seconds': builder.timing.get('total'), 'timing': builder.timing, 'notes': builder.notes}
        missing = builder.plans_missing()
        if missing:
            out['rebuilt']['plans_missing'] = missing
    targets = {}
    for item in columns or ():
        if not isinstance(item, str) or '.' not in item:
            raise FmdbError('columns must be "table.column" strings, e.g. "player.best_roles".')
        t, c = item.split('.', 1)
        if t not in snapshot.TABLES:
            raise FmdbError(f'Unknown table {t!r}.')
        targets.setdefault(t, []).append(c)
    for t in tables_ or ():
        if t not in snapshot.TABLES:
            raise FmdbError(f'Unknown table {t!r}.')
    if tables_:
        out['tables'] = {'tables': list(tables_),
                         'note': 'nothing is queued: an on-demand column is computed when a query names it, or now '
                                 'with columns=["table.column", ...]'}
    computed = []
    budget_left = REFRESH_MATERIALISE_BUDGET_S
    for t, cols in targets.items():
        if budget_left <= 0:
            break
        t0 = time.time()
        computed.append(snapshot.materialise(engine, path, t, cols, budget_s=budget_left))
        budget_left -= time.time() - t0
    if computed:
        out['computed'] = computed
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        on_demand = dict(conn.execute("SELECT table_name, COUNT(DISTINCT column_name) FROM _column_state "
                                      "WHERE status='on_demand' GROUP BY table_name"))
        out['counts'] = {t: {'rows': n, 'on_demand': on_demand.get(t, 0), **dict(conn.execute(
            'SELECT status, COUNT(*) FROM _fields WHERE table_name=? AND code IS NOT NULL GROUP BY status',
            (t,)).fetchall())} for t, n in conn.execute('SELECT table_name, rows FROM _tables')}
        memo = ondemand.memo_summary(conn)
    finally:
        conn.close()
    meta = snapshot_meta(path)
    out.update({'snapshot': _public_snapshot(meta, False), 'memoised': memo,
                'seconds': round(time.time() - started, 1),
                'notes': _notes(meta) + ['On-demand columns are computed by fm_db_query for the rows a statement '
                                         'needs; no background process runs.']})
    return out


# --------------------------------------------------------------------------- registration
def _wrap(fn):
    try:
        return fn()
    except (FmdbError, query.QueryError, snapshot.SnapshotError, EngineError) as exc:
        raise ValueError(str(exc)) from exc


def register_fmdb_tools(mcp, bridge):
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    @mcp.tool(annotations=read_only)
    def fm_db_schema(
        session_id: str,
        table: Annotated[str | None, Field(min_length=1, max_length=64)] = None,
        search: Annotated[str | None, Field(min_length=2, max_length=64)] = None,
        include_pending: bool = False,
        view: Literal['full', 'manager'] = 'full',
    ) -> dict[str, Any]:
        """Describe the SQLite snapshot of the whole loaded save (every person, player, club, nation, competition...). No arguments: tables and views with row counts, snapshot game date. table: its columns (type, meaning, enum labels; on_demand marks a column the game's getter computes when a query names it; unavailable columns only with include_pending=true). search: columns across tables whose name or meaning matches. Default view="full" is the stored data; view="manager" lists the masked m_* views (what the manager knows; attributes as <attr>, <attr>_min, <attr>_max). Then answer questions with fm_db_query."""
        return _wrap(lambda: db_schema(bridge, session_id, table, search, include_pending, view))

    @mcp.tool(annotations=read_only)
    def fm_db_query(
        session_id: str,
        sql: Annotated[str, Field(min_length=1, max_length=20000)],
        params: list[Any] | dict[str, Any] | None = None,
        max_rows: Annotated[int, Field(ge=1, le=5000)] = 200,
        view: Literal['full', 'manager'] = 'full',
    ) -> dict[str, Any]:
        """Run one read-only SQLite SELECT (or WITH ... SELECT) against the save snapshot. Prefer the views: player_view (name, age, nationality, club / contracted_club / loan_club, on_loan, position, current_ability, potential_ability, 1-20 attributes, personality, condition, injuries, morale, form, appearances, goals, assists, average_rating, wage, contract_expires, transfer_value...), club_view, staff_view, competition_view. *_idx columns join to <table>.idx; team.club_idx joins teams to clubs. Default view="full" is the stored data (full information). view="manager" answers only from what the manager knows: query m_player_view / m_scouted_player_view, where each attribute is <attr> (exact), <attr>_min/<attr>_max (range); <attr>_min >= x means surely at least x, <attr>_max >= x means could be. Before answering, the stored rows are checked against live memory and the rows that changed are read again (snapshot.checked_ms_ago, rows_refreshed), so a result reflects the game as it is now, also within a game date. Columns the game's getter computes (on_demand in fm_db_schema) are computed when the statement names them, for the rows it needs, and kept until a byte they read changes; SELECT * does not compute them. In the manager view every other table and view is m_<name> (m_fixture_view, m_standing_view, m_contract_view, m_club_view ...), masked by its policy (fm_db_schema(view="manager")); it withholds CA/PA, hidden attributes, other clubs' finances, clauses and transfer activity. Returns columns, rows, truncated, snapshot (game date, checked_ms_ago, rows_refreshed), computed (what was computed on demand) and notes. Values are a best-effort non-atomic read of live memory (the game is not paused). notes is empty unless something changes what to do: rows the check read again, a stale snapshot, on-demand columns left out by SELECT *, a plan the audit demoted, partial manager knowledge."""
        return _wrap(lambda: db_query(bridge, session_id, sql, params, max_rows, view))

    @mcp.tool(annotations=read_only)
    def fm_db_read(
        session_id: str,
        table: Annotated[str, Field(min_length=1, max_length=64)],
        idx: Annotated[list[Annotated[int, Field(ge=0)]], Field(min_length=1, max_length=50)],
        fields: Annotated[list[Annotated[str, Field(min_length=1, max_length=96)]] | None,
                          Field(min_length=1, max_length=400)] = None,
        view: Literal['full', 'manager'] = 'full',
    ) -> dict[str, Any]:
        """Fresh exact read of 1-50 records (row idx from fm_db_query) through the game's own property getter: every handled field (or the named columns/codes), lists and records as JSON, references with their idx, and a reason for each unavailable field. Default view="full" reads stored data; view="manager" allows people only at your own club (hidden values withheld) and any non-person table. Slower than fm_db_query; use it to confirm current values."""
        return _wrap(lambda: db_read(bridge, session_id, table, idx, fields, view))

    @mcp.tool(annotations=read_only)
    def fm_db_refresh(
        session_id: str,
        tables: Annotated[list[Annotated[str, Field(min_length=1, max_length=64)]] | None,
                          Field(min_length=1, max_length=30)] = None,
        columns: Annotated[list[Annotated[str, Field(min_length=3, max_length=128)]] | None,
                           Field(min_length=1, max_length=200)] = None,
    ) -> dict[str, Any]:
        """Rebuild the save snapshot from live memory now (no arguments: every direct column is read again, 10 to 30 seconds). Not needed in normal use: fm_db_query checks the snapshot against live memory and repairs it before every answer. columns: compute the named on-demand columns for every row now ("table.column", up to 10 minutes) instead of when a query needs them. tables: accepted, nothing is queued. Returns timing, per-table column counts and what is memoised. Nothing runs in the background."""
        return _wrap(lambda: db_refresh(bridge, session_id, tables, columns))
