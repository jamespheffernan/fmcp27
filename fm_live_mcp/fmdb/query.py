"""Read-only SQL over a snapshot file: guardrails, column discovery, bounded execution.

Guardrails (all enforced, independently):
* the text must be one SELECT or WITH ... SELECT statement (sqlite3 refuses a second
  statement; a leading keyword check rejects everything else);
* the connection is opened read-only (`mode=ro`) and a SQLite authorizer allows only
  SELECT, READ, FUNCTION and RECURSIVE actions (no PRAGMA, ATTACH, writes, DDL or
  transactions) and denies extension-loading/file functions;
* a progress handler stops a query after `time_limit_s`;
* at most `max_rows` rows and about `max_bytes` of cell data are returned.
"""
from __future__ import annotations

import re
import sqlite3
import time

MAX_SQL = 20_000
MAX_BYTES = 1_000_000
DENIED_FUNCTIONS = {'load_extension', 'readfile', 'writefile', 'edit', 'fts3_tokenizer', 'zipfile', 'sqlar_compress'}
ALLOWED = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
_LEAD = re.compile(r'^\s*(?:(?:--[^\n]*\n)|(?:/\*.*?\*/)|\s)*(\w+)', re.S)


class QueryError(ValueError):
    """The query was rejected or failed; the message says what to change."""


def check_sql(sql: str) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise QueryError('Supply one SELECT statement.')
    if len(sql) > MAX_SQL:
        raise QueryError(f'SQL is longer than {MAX_SQL} characters; simplify it.')
    match = _LEAD.match(sql)
    keyword = match.group(1).upper() if match else ''
    if keyword not in ('SELECT', 'WITH', 'VALUES'):
        raise QueryError(f'Only one read-only SELECT (or WITH ... SELECT) is allowed; got {keyword or "nothing"}. '
                         'Use fm_db_refresh to rebuild data.')
    return sql


def _authorizer(reads=None, denied=None):
    def authorize(action, arg1, arg2, db_name, trigger):
        if action == sqlite3.SQLITE_READ:
            if reads is not None and arg1:
                reads.add((arg1, arg2, trigger))
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION:
            if (arg2 or '').lower() in DENIED_FUNCTIONS:
                if denied is not None:
                    denied.append(f'function {arg2}')
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        if action in ALLOWED:
            return sqlite3.SQLITE_OK
        if denied is not None:
            denied.append(_ACTION_NAMES.get(action, str(action)))
        return sqlite3.SQLITE_DENY
    return authorize


_ACTION_NAMES = {getattr(sqlite3, n): n.replace('SQLITE_', '') for n in dir(sqlite3)
                 if n.startswith('SQLITE_') and isinstance(getattr(sqlite3, n), int)
                 and n not in ('SQLITE_OK', 'SQLITE_DENY', 'SQLITE_IGNORE')}


def connect_ro(path) -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=10, check_same_thread=False)
    except sqlite3.Error as exc:
        raise QueryError(f'cannot open the snapshot: {exc}. Call fm_db_refresh.') from exc
    return conn


def referenced_columns(path, sql: str, params=None) -> set[tuple[str, str, str | None]]:
    """(table, column, view-or-CTE) reads the statement performs, collected by the authorizer
    while compiling `EXPLAIN <sql>`. Views expand to every underlying column they define,
    tagged with the view name (the third item; None for a direct read)."""
    check_sql(sql)
    reads, denied = set(), []
    conn = connect_ro(path)
    try:
        conn.set_authorizer(_authorizer(reads, denied))
        try:
            conn.execute('EXPLAIN ' + sql, params or ()).fetchall()
        except sqlite3.Error as exc:
            raise QueryError(_explain_error(exc, denied)) from exc
    finally:
        conn.close()
    return reads


def _explain_error(exc, denied):
    text = str(exc)
    if denied or 'not authorized' in text:
        return (f'Rejected: the query needs a non-read action ({", ".join(dict.fromkeys(denied)) or text}). '
                'Only one read-only SELECT is allowed.')
    if 'one statement at a time' in text:
        return 'Rejected: send exactly one statement (no semicolon-separated statements).'
    return f'SQL error: {text}. Check table/column names with fm_db_schema.'


def run(path, sql: str, params=None, *, max_rows: int = 200, time_limit_s: float = 15.0,
        max_bytes: int = MAX_BYTES) -> dict:
    check_sql(sql)
    denied = []
    conn = connect_ro(path)
    try:
        conn.set_authorizer(_authorizer(None, denied))
        return fetch(conn, sql, params, max_rows=max_rows, time_limit_s=time_limit_s, max_bytes=max_bytes,
                     denied=denied)
    finally:
        conn.close()


def fetch(conn, sql: str, params=None, *, max_rows: int = 200, time_limit_s: float = 15.0,
          max_bytes: int = MAX_BYTES, denied=None, uncounted=None) -> dict:
    """Execute on an already-guarded connection (its authorizer is left in place) with a time
    limit and row/size caps. `uncounted()` returns seconds that do not count against the time
    limit (the getter time of on-demand cells, which is reported separately)."""
    if not isinstance(max_rows, int) or isinstance(max_rows, bool) or not 1 <= max_rows <= 5000:
        raise QueryError('max_rows must be an integer from 1 to 5000.')
    if params is not None and not isinstance(params, (list, dict)):
        raise QueryError('params must be a list (for ?) or an object (for :name).')
    denied = denied if denied is not None else []
    deadline = time.monotonic() + time_limit_s
    timed_out = []

    def progress():
        if time.monotonic() > deadline + (uncounted() if uncounted is not None else 0.0):
            timed_out.append(True)
            return 1
        return 0

    conn.set_progress_handler(progress, 20_000)
    started = time.monotonic()
    try:
        cursor = conn.execute(sql, params or ())
        rows, size, truncated = [], 0, False
        while True:
            batch = cursor.fetchmany(256)
            if not batch:
                break
            for row in batch:
                if len(rows) >= max_rows:
                    truncated = True
                    break
                row = [r.hex() if isinstance(r, (bytes, bytearray)) else r for r in row]
                size += sum(len(str(v)) for v in row)
                if size > max_bytes:
                    truncated = True
                    break
                rows.append(row)
            if truncated:
                break
        columns = [d[0] for d in cursor.description or ()]
    except sqlite3.OperationalError as exc:
        if timed_out:
            raise QueryError(f'Query stopped after {time_limit_s:g}s. Add filters or LIMIT, '
                             'or avoid scanning large views with correlated subqueries.') from exc
        raise QueryError(_explain_error(exc, denied)) from exc
    except (sqlite3.Error, ValueError) as exc:
        raise QueryError(_explain_error(exc, denied)) from exc
    finally:
        conn.set_progress_handler(None, 0)
    return {'columns': columns, 'rows': rows, 'row_count': len(rows), 'truncated': truncated,
            'seconds': round(time.monotonic() - started, 3)}


def run_session(path, sql: str, params=None, *, session=None, max_rows: int = 200, time_limit_s: float = 15.0,
                max_bytes: int = MAX_BYTES, count_compute: bool = False) -> dict:
    """`run` with an on-demand session (`ondemand.Session`, already planned): its shadow views
    and `fm_cell` are created on the connection before the authorizer is installed. The getter
    time of on-demand cells does not count against the time limit unless `count_compute`."""
    check_sql(sql)
    denied = []
    conn = connect_ro(path)
    try:
        if session is not None:
            session.attach(conn)
        conn.set_authorizer(_authorizer(None, denied))
        return fetch(conn, sql, params, max_rows=max_rows, time_limit_s=time_limit_s, max_bytes=max_bytes,
                     denied=denied,
                     uncounted=(lambda: session.seconds) if session is not None and not count_compute else None)
    finally:
        conn.close()
