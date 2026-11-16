"""Freshness by content: keep the snapshot's direct rows equal to live memory.

A snapshot is not valid "for a game date". It is valid for the bytes it was read from, so each
time the tools are used (at most once every `CHECK_INTERVAL_S`) `refresh` compares those bytes
with the game's and repairs what differs:

* Dependencies. While direct plans are evaluated (`bulkplans.evaluate(touch=...)`) and the
  computed columns are read, a `Recorder` notes the exact windows (address and length) each
  block of rows was read from (`BLOCK_ROWS` consecutive idx values of one SQL table): the
  windows of the rows' own records and everything reached through a pointer (strings, the
  head of a referenced record, fields of a contract object). The snapshot stores them per
  block with one CRC of their bytes and the set of 16 KiB pages they lie on
  (`_direct_blocks`), one hash per page (`_direct_pages`) and the live table vectors (`_live`:
  record pointers, classes, unique and random ids by idx).
* Check. Read every page in `_direct_pages` (about 16,000 pages, one batched read), hash, and
  compare. For a block with a window on a changed page, compute the CRC of its windows again:
  a page changes far more often than the bytes a plan reads on it. Read every table vector
  and compare the record pointers.
* Repair. A block whose CRC differs, or that holds an idx whose record pointer changed, is
  evaluated again (the same plans, a few hundred rows) and compared with the stored rows; rows
  that differ are updated in place, new records are inserted, records that left are deleted,
  in one SQLite transaction. Emulated cells are not touched here: every memoised cell carries
  its own read set (`ondemand.py`) and is checked when a query needs it; an idx whose record
  pointer changed loses its memoised cells.
* Mixed state. After the blocks are evaluated their pages are read once more; a block whose
  window bytes moved in between is not published in that round and is evaluated again (up to
  `MAX_ROUNDS`). What is still moving then keeps its old rows and its old CRC, so the next
  check evaluates it again, and the result says so.

Nothing here writes to the game or runs code in it.
"""
from __future__ import annotations

from array import array
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import sqlite3
import struct
import time
import zlib

from . import bulkplans, tables
from .bulkplans import Missing

BLOCK_SHIFT = 8
BLOCK_ROWS = 1 << BLOCK_SHIFT
PAGE_SHIFT = 14                     # LiveMemory pages: 16 KiB
PAGE_SIZE = 1 << PAGE_SHIFT
CHECK_INTERVAL_S = 3.0              # a check younger than this is reused
MAX_ROUNDS = 3

FRESH_SQL = """
CREATE TABLE IF NOT EXISTS _live(kind TEXT PRIMARY KEY, identity TEXT, pointers BLOB, uids BLOB, rids BLOB,
                                 class_ids BLOB, class_names TEXT);
CREATE TABLE IF NOT EXISTS _direct_blocks(table_name TEXT, block INTEGER, pages BLOB, windows BLOB, crc INTEGER,
                                          PRIMARY KEY(table_name, block)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS _direct_pages(page INTEGER PRIMARY KEY, hash INTEGER);
CREATE TABLE IF NOT EXISTS _memo(table_name TEXT, column_name TEXT, valid BLOB, cells INTEGER, computed_at TEXT,
                                 cpu_seconds REAL, queries INTEGER,
                                 PRIMARY KEY(table_name, column_name)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS _memo_blocks(table_name TEXT, block INTEGER, reads BLOB, hashes BLOB,
                                        PRIMARY KEY(table_name, block)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS _fresh(key TEXT PRIMARY KEY, value);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def page_hash(data) -> int:
    """63-bit content hash of one page (CRC-32 and Adler-32 of the bytes)."""
    return ((zlib.adler32(data) << 32) | zlib.crc32(data)) & 0x7FFF_FFFF_FFFF_FFFF


def _page(memory, base):
    """The cached bytes of the page at `base`, or None when it cannot be read."""
    try:
        return memory.page(base)
    except Exception:  # noqa: BLE001 - MemoryReadError and reader failures: the page has no content
        return None


def reread(memory, bases):
    """Read the pages again from the process and replace them in the page cache; the bases
    whose bytes differ from the cached ones. A memory without `reread` (a fixed image) has none."""
    fn = getattr(memory, 'reread', None)
    return fn(bases) if fn is not None else set()


# --------------------------------------------------------------------------- dependency recording
class Recorder:
    """The windows each block of rows was read from, for one build or one repair round.

    `touch_for(table, idxs)` gives the callback `bulkplans.evaluate` wants. It faults the pages
    into the page cache with one batched read (so the windows that follow are sliced from the
    cache and the bytes that were decoded are the bytes that get hashed) and records the
    addresses per block."""

    def __init__(self, engine):
        self.engine = engine
        self.memory = engine.memory
        self.groups = defaultdict(dict)         # table -> {block: [(length, sorted addresses)]}

    def windows(self, addresses, length):
        return self.engine.windows(addresses, length)

    def read_many(self, requests):
        out = []
        read = self.memory.cached_read
        for address, length in requests:
            try:
                out.append(read(address, length))
            except Exception:  # noqa: BLE001 - an unreadable range is a Missing value, as in read_many
                out.append(None)
        return out

    def forget(self, table):
        self.groups.pop(table, None)

    def touch_for(self, table, idxs):
        blocks = [i >> BLOCK_SHIFT for i in idxs]
        n = len(blocks)
        whole = range(n)
        groups = self.groups[table]
        prefetch = getattr(self.memory, 'prefetch', None)
        # positions [start, end) of every block in `idxs` (idx values are ascending within a class)
        spans, start = [], 0
        for k in range(1, n + 1):
            if k == n or blocks[k] != blocks[start]:
                spans.append((blocks[start], start, k))
                start = k
        ordered = all(blocks[k] <= blocks[k + 1] for k in range(n - 1))

        def add(block, addresses, length):
            group = set(addresses)
            group.discard(0)
            if group:
                groups.setdefault(block, []).append((length, sorted(group)))

        def touch(rows, addresses, length, depth=0):
            end = length - 1
            pages = {a >> PAGE_SHIFT for a in addresses}
            if end:
                pages.update([(a + end) >> PAGE_SHIFT for a in addresses if a])
            pages.discard(0)
            if prefetch is not None and pages:
                try:
                    prefetch([(p << PAGE_SHIFT, 1) for p in pages])
                except Exception:  # noqa: BLE001 - unreadable pages surface as Missing values
                    pass
            if ordered and len(rows) == n and (rows is whole or (rows[0] == 0 and rows[-1] == n - 1)):
                for block, k0, k1 in spans:
                    add(block, addresses[k0:k1], length)
            elif ordered:
                for block, k0, k1 in spans:
                    lo, hi = bisect_left(rows, k0), bisect_left(rows, k1)
                    if lo < hi:
                        add(block, addresses[lo:hi], length)
            else:
                by_block = defaultdict(list)
                for r, a in zip(rows, addresses):
                    by_block[blocks[r]].append(a)
                for block, group in by_block.items():
                    add(block, group, length)
        return touch

    def block_pages(self, table) -> dict:
        """{block: the page numbers its windows lie on} for one table."""
        out = {}
        for block, groups in self.groups.get(table, {}).items():
            pages = set()
            for length, addresses in groups:
                pages.update([a >> PAGE_SHIFT for a in addresses])
                if length > 1:
                    pages.update([(a + length - 1) >> PAGE_SHIFT for a in addresses])
            out[block] = pages
        return out

    def pages(self) -> set:
        pages = set()
        for table in self.groups:
            for group in self.block_pages(table).values():
                pages |= group
        return pages

    def crcs(self, table) -> dict:
        """{block: CRC of its window bytes as cached now}."""
        return {block: windows_crc(self.memory, groups) for block, groups in self.groups.get(table, {}).items()}

    def hashes(self, pages=None) -> dict:
        """{page number: hash of the cached bytes}; 0 for a page that is not readable (it then
        differs from any later reading, so its blocks are checked again)."""
        out = {}
        for page in (self.pages() if pages is None else pages):
            data = _page(self.memory, page << PAGE_SHIFT)
            out[page] = page_hash(data) if data is not None else 0
        return out


def windows_crc(memory, groups) -> int:
    """CRC-32 over the bytes of windows [(length, addresses)], read from the page cache in the
    recorded order. An unreadable window contributes its address instead."""
    crc = 0
    cache = getattr(memory, '_cache', None)
    mask = PAGE_SIZE - 1
    empty = b''
    for length, addresses in groups:
        if cache is not None:
            parts = [cache.get(a & ~mask, empty)[a & mask:(a & mask) + length] for a in addresses]
        else:
            parts = [empty] * len(addresses)
        data = b''.join(parts)
        if len(data) != length * len(addresses):
            # some window crosses a page or lies on a page that is not cached: those one by one
            for k, part in enumerate(parts):
                if len(part) != length:
                    try:
                        parts[k] = memory.cached_read(addresses[k], length)
                    except Exception:  # noqa: BLE001
                        parts[k] = struct.pack('<Q', addresses[k])
            data = b''.join(parts)
        crc = zlib.crc32(data, crc)
    return crc


def pack_weak(groups) -> bytes:
    out = [struct.pack('<I', len(groups))]
    for length, addresses in groups:
        out.append(struct.pack('<II', length, len(addresses)))
        out.append(array('Q', addresses).tobytes())
    return zlib.compress(b''.join(out), 1)


def unpack_weak(blob) -> list:
    data = zlib.decompress(blob)
    (count,), at = struct.unpack_from('<I', data, 0), 4
    groups = []
    for _ in range(count):
        length, n = struct.unpack_from('<II', data, at)
        at += 8
        addresses = array('Q')
        addresses.frombytes(data[at:at + 8 * n])
        at += 8 * n
        groups.append((length, addresses))
    return groups


# --------------------------------------------------------------------------- persisted live tables
def save_live(conn, live: dict, *, only_changed=False):
    """Store the table vectors. `only_changed`: write a vector only when its content digest
    differs from the one stored with it (`_fresh` live_digest:<kind>); a content check where
    no record moved writes nothing here (the vectors are megabytes: rewriting them on every
    check cost 1.5 to 2 s of writes and a 1 to 4 s commit)."""
    rows, digests = [], {}
    for kind, lt in live.items():
        names = sorted(set(lt.classes))
        index = {name: k for k, name in enumerate(names)}
        row = (kind, json.dumps(list(lt.identity)), array('Q', lt.pointers).tobytes(),
               array('q', [-1 if u is None else u for u in lt.uids]).tobytes(),
               array('q', [-1 if r is None else r for r in lt.rids]).tobytes(),
               array('H', [index[c] for c in lt.classes]).tobytes(), json.dumps(names))
        digest = hashlib.blake2b(b'\0'.join(x.encode() if isinstance(x, str) else x for x in row),
                                 digest_size=16).hexdigest()
        if only_changed and get_fresh(conn, f'live_digest:{kind}') == digest:
            continue
        rows.append(row)
        digests[f'live_digest:{kind}'] = digest
    conn.executemany('INSERT OR REPLACE INTO _live VALUES (?, ?, ?, ?, ?, ?, ?)', rows)
    if digests:
        set_fresh(conn, **digests)
    return len(rows)


def load_live(conn) -> dict:
    from .snapshot import LiveTable
    out = {}
    for kind, identity, pointers, uids, rids, class_ids, class_names in conn.execute('SELECT * FROM _live'):
        names = json.loads(class_names)
        p, u, r, c = array('Q'), array('q'), array('q'), array('H')
        p.frombytes(pointers), u.frombytes(uids), r.frombytes(rids), c.frombytes(class_ids)
        out[kind] = LiveTable(kind, p.tolist(), tuple(json.loads(identity)), [names[k] for k in c],
                              [None if v < 0 else v for v in u], [None if v < 0 else v for v in r])
    return out


def write_dependencies(conn, recorder: Recorder, only=None):
    """Store the recorder's windows (with their CRC and page sets) and the page hashes. `only`:
    {table: blocks} to restrict to (a repair round publishes only the blocks that were stable)."""
    used = set()
    for table, by_block in recorder.groups.items():
        pages_of = recorder.block_pages(table)
        rows = []
        for block, groups in by_block.items():
            if only is not None and block not in only.get(table, ()):
                continue
            pages = pages_of[block]
            used.update(pages)
            rows.append((table, block, array('Q', sorted(pages)).tobytes(), pack_weak(groups),
                         windows_crc(recorder.memory, groups)))
        conn.executemany('INSERT OR REPLACE INTO _direct_blocks VALUES (?, ?, ?, ?, ?)', rows)
    hashes = recorder.hashes(used)
    conn.executemany('INSERT OR REPLACE INTO _direct_pages VALUES (?, ?)', list(hashes.items()))
    return len(used)


def get_fresh(conn, key, default=None):
    try:
        row = conn.execute('SELECT value FROM _fresh WHERE key=?', (key,)).fetchone()
    except sqlite3.Error:
        return default
    return row[0] if row else default


def set_fresh(conn, **values):
    conn.executemany('INSERT OR REPLACE INTO _fresh VALUES (?, ?)',
                     [(k, json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in values.items()])


def status(conn) -> dict:
    """What the snapshot was last checked against (for tool results)."""
    checked = get_fresh(conn, 'checked_at_unix')
    out = {'checked_at': get_fresh(conn, 'checked_at'), 'rows_refreshed': get_fresh(conn, 'rows_refreshed', 0),
           'pages_changed': get_fresh(conn, 'pages_changed', 0), 'pages_checked': get_fresh(conn, 'pages_checked', 0)}
    if checked is not None:
        out['checked_ms_ago'] = max(0, int((time.time() - float(checked)) * 1000))
    return out


# --------------------------------------------------------------------------- repair
def _same(a, b):
    return a == b or (a is not None and b is not None and type(a) is not type(b) and str(a) == str(b))


class _Sync:
    """Evaluate blocks of rows again and work out the row operations that make the stored
    rows equal to them (no database write happens here; `apply` does that for stable blocks)."""

    def __init__(self, engine, conn, live, store):
        from . import snapshot
        self.snapshot = snapshot
        self.engine, self.conn, self.live, self.store = engine, conn, live, store
        self.live_by_sql = {t: live[tables.RECORD_TYPES[rt].table] for t, rt in snapshot.TABLES.items()
                            if tables.RECORD_TYPES[rt].table in live}
        self.present = {r[0] for r in conn.execute('SELECT table_name FROM _tables')}
        self._columns, self._direct, self._computed = {}, {}, None

    def columns(self, table):
        if table not in self._columns:
            self._columns[table] = {c.name: c for c in self.snapshot.columns_for(self.engine.catalog, table)}
        return self._columns[table]

    def direct(self, table, cls):
        """{column name: (Column, plan)} read directly for one class of one table, as the build
        decided (`_column_state`), with the plans of the current plan cache."""
        key = (table, cls)
        if key not in self._direct:
            cols = self.columns(table)
            out = {}
            for (name,) in self.conn.execute(
                    "SELECT column_name FROM _column_state WHERE table_name=? AND class=? AND source='direct' "
                    "AND status='ready'", (table, cls)):
                col = cols.get(name)
                plan = self.store.get(cls, col.code) if col is not None else None
                if plan and plan.get('status') == 'direct':
                    out[name] = (col, plan)
            self._direct[key] = out
        return self._direct[key]

    def computed(self):
        if self._computed is None:
            club_rows = set(self.snapshot.table_rows(self.live_by_sql['club'], self.snapshot.TABLES['club'])) \
                if 'club' in self.live_by_sql else set()
            self._computed = self.snapshot.Computed(self.engine, self.live, club_rows)
        return self._computed

    def rows(self, table, blocks):
        live = self.live_by_sql[table]
        wanted = set(tables.RECORD_TYPES[self.snapshot.TABLES[table]].classes)
        n = len(live.pointers)
        out = []
        for b in sorted(blocks):
            for i in range(b << BLOCK_SHIFT, min((b + 1) << BLOCK_SHIFT, n)):
                c = live.classes[i]
                if live.pointers[i] and c != 'unreadable' and (not wanted or c in wanted):
                    out.append(i)
        return out

    def prepare(self, table, blocks, recorder):
        """(inserts, updates, deletes) for the blocks of one table: `inserts` {idx: {column:
        value}}, `updates` {idx: {column: value}} (changed cells only), `deletes` [idx]."""
        snap = self.snapshot
        live = self.live_by_sql[table]
        desired = self.rows(table, blocks)
        by_class = defaultdict(list)
        for i in desired:
            by_class[live.classes[i]].append(i)
        resolver = snap.Resolver(self.live_by_sql)
        new = defaultdict(dict)                 # column -> {idx: sql value}
        for cls, idxs in by_class.items():
            direct = self.direct(table, cls)
            if not direct:
                continue
            got = bulkplans.evaluate(recorder.read_many, [live.pointers[i] for i in idxs],
                                     {n: p for n, (c, p) in direct.items()}, windows=recorder.windows,
                                     touch=recorder.touch_for(table, idxs))
            for name, (col, _) in direct.items():
                new[name].update(zip(idxs, snap.convert_column(col, idxs, got[name], resolver)))
        if desired and table in snap.Computed.TABLES:
            values, _ = self.computed().columns(table, desired, recorder.touch_for(table, desired))
            for name, column in values:
                new[name].update(column)
        names = list(new)
        stored = {}
        if names:
            select = ', '.join(snap._quote(n) for n in ['idx', 'uid', 'class'] + names)
            for b in sorted(blocks):
                for row in self.conn.execute(f'SELECT {select} FROM {snap._quote(table)} WHERE idx >= ? AND idx < ?',
                                             (b << BLOCK_SHIFT, (b + 1) << BLOCK_SHIFT)):
                    stored[row[0]] = row
        else:
            for b in sorted(blocks):
                for row in self.conn.execute(f'SELECT idx, uid, class FROM {snap._quote(table)} WHERE idx >= ? '
                                             'AND idx < ?', (b << BLOCK_SHIFT, (b + 1) << BLOCK_SHIFT)):
                    stored[row[0]] = row
        inserts, updates = {}, {}
        for i in desired:
            values = {'uid': live.uids[i], 'class': live.classes[i]}
            row = stored.get(i)
            if row is None:
                values.update({n: new[n].get(i) for n in names})
                inserts[i] = values
                continue
            diff = {}
            if row[1] != values['uid']:
                diff['uid'] = values['uid']
            if row[2] != values['class']:
                diff['class'] = values['class']
            for k, n in enumerate(names, 3):
                # a column that is direct for another class only is not compared for this row
                if i in new[n] and not _same(row[k], new[n][i]):
                    diff[n] = new[n][i]
            if diff:
                updates[i] = diff
        wanted = set(desired)
        deletes = [i for i in stored if i not in wanted]
        return inserts, updates, deletes, resolver.unresolved

    def apply(self, table, ops, stable_blocks):
        snap = self.snapshot
        inserts, updates, deletes, unresolved = ops
        q = snap._quote
        n = 0
        for i, values in inserts.items():
            if i >> BLOCK_SHIFT in stable_blocks:
                names = ['idx'] + list(values)
                self.conn.execute(f'INSERT OR REPLACE INTO {q(table)} ({", ".join(map(q, names))}) VALUES '
                                  f'({", ".join("?" * len(names))})', [i] + list(values.values()))
                n += 1
        declared = None
        for i, diff in updates.items():
            if i >> BLOCK_SHIFT in stable_blocks:
                self.conn.execute(f'UPDATE {q(table)} SET {", ".join(q(c) + "=?" for c in diff)} WHERE idx=?',
                                  list(diff.values()) + [i])
                n += 1
                # a memoised cell that is valid by declared inputs (ondemand.DECLARED_INPUTS) is
                # dropped when one of its inputs in this row changed
                if declared is None:
                    from . import ondemand
                    declared = ondemand.declared_columns(self.conn, self.engine.catalog, table)
                for column, inputs in declared.items():
                    if not inputs.isdisjoint(diff):
                        clear_memo_rows(self.conn, table, [i], columns=[column])
        gone = [i for i in deletes if i >> BLOCK_SHIFT in stable_blocks]
        self.conn.executemany(f'DELETE FROM {q(table)} WHERE idx=?', [(i,) for i in gone])
        if unresolved:
            self.conn.executemany('INSERT INTO _unresolved VALUES (?, ?, ?, ?)',
                                  [u for u in unresolved if u[2] >> BLOCK_SHIFT in stable_blocks])
        if any(i >> BLOCK_SHIFT in stable_blocks for i in inserts) or gone:
            live = self.live_by_sql[table]
            rows = snap.table_rows(live, snap.TABLES[table])
            classes = defaultdict(int)
            for i in rows:
                classes[live.classes[i]] += 1
            self.conn.execute('UPDATE _tables SET rows=?, classes_json=? WHERE table_name=?',
                              (len(rows), json.dumps(dict(classes)), table))
        return n + len(gone)


def _update_vectors(engine, live):
    """Read every table vector; for an idx whose record pointer changed read the record head
    again. Returns {kind: [changed idx]} and updates `live` in place."""
    changed = {}
    for kind, lt in live.items():
        pointers, identity = engine.table_entries(kind)
        if pointers == lt.pointers:
            lt.identity = identity
            continue
        old = lt.pointers
        n_old, n_new = len(old), len(pointers)
        idxs = [i for i in range(min(n_old, n_new)) if old[i] != pointers[i]] + list(range(min(n_old, n_new),
                                                                                             max(n_old, n_new)))
        if n_new < n_old:
            del lt.classes[n_new:], lt.uids[n_new:], lt.rids[n_new:]
        else:
            pad = n_new - n_old
            lt.classes += [''] * pad
            lt.uids += [None] * pad
            lt.rids += [None] * pad
        lt.pointers = pointers
        lt.identity = identity
        _read_heads(engine, lt, [i for i in idxs if i < n_new])
        lt.__dict__.pop('_uid_index', None)
        changed[kind] = idxs
    return changed


def _read_heads(engine, lt, idxs):
    """Class, unique id and random id of the records at `idxs` (as snapshot.enumerate_table)."""
    present = [i for i in idxs if lt.pointers[i]]
    for i in idxs:
        if not lt.pointers[i]:
            lt.classes[i], lt.uids[i], lt.rids[i] = '', None, None
    if not present:
        return False
    payload, bad = engine.windows([lt.pointers[i] for i in present], 0x14)
    bad = set(bad)
    moved = False
    base = engine.base
    for k, (i, (vtable, uid, rid)) in enumerate(zip(present, struct.iter_unpack('<Q4xII', payload))):
        if k in bad:
            new = ('unreadable', None, None)
        else:
            entry = tables.CLASSES.get(vtable - base)
            new = (entry[0] if entry else f'vtable@{vtable - base:#x}', uid, rid or uid)
        if (lt.classes[i], lt.uids[i], lt.rids[i]) != new:
            lt.classes[i], lt.uids[i], lt.rids[i] = new
            moved = True
    if moved:
        lt.__dict__.pop('_uid_index', None)
    return moved


def clear_memo_rows(conn, table, idxs, columns=None):
    """Drop the memoised cells of some rows of one table (all its on-demand columns, or the
    given ones): the
    validity bits are cleared and the stored cells are set to NULL, so no reader of the table
    meets a cell computed for the record that was at that idx before."""
    if not idxs:
        return
    hit_columns, hit_rows = [], set()
    for column, blob in conn.execute('SELECT column_name, valid FROM _memo WHERE table_name=?', (table,)).fetchall():
        if columns is not None and column not in columns:
            continue
        valid = bytearray(blob or b'')
        hit = False
        for i in idxs:
            if (i >> 3) < len(valid) and valid[i >> 3] >> (i & 7) & 1:
                valid[i >> 3] &= ~(1 << (i & 7)) & 0xFF
                hit = True
                hit_rows.add(i)
        if hit:
            hit_columns.append(column)
            conn.execute('UPDATE _memo SET valid=?, cells=? WHERE table_name=? AND column_name=?',
                         (bytes(valid), sum(bin(b).count('1') for b in valid), table, column))
    q = '"' + table.replace('"', '""') + '"'
    for start in range(0, len(hit_columns), 200):
        sets = ', '.join('"' + c.replace('"', '""') + '"=NULL' for c in hit_columns[start:start + 200])
        conn.executemany(f'UPDATE {q} SET {sets} WHERE idx=?', [(i,) for i in sorted(hit_rows)])


def refresh(engine, path, *, log=None, force=False, min_interval=CHECK_INTERVAL_S) -> dict:
    """Check the snapshot at `path` against live memory and repair it (module docstring).

    Returns what was done: seconds and CPU-seconds, pages checked and changed, rows refreshed
    per table, records that appeared or left, blocks that were still changing, and `reused`
    when the last check is younger than `min_interval`. Raises `Rebuild` when the snapshot
    cannot be repaired in place (another process or save, no dependency tables)."""
    from . import snapshot
    started, cpu = time.time(), time.process_time()
    with engine.lock:
        conn = sqlite3.connect(path, timeout=30)
        try:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='_direct_pages'").fetchone():
                raise Rebuild('the snapshot has no dependency tables (built before content checks)')
            last = get_fresh(conn, 'checked_at_unix')
            if not force and last is not None and time.time() - float(last) < min_interval:
                return {'reused': True, **status(conn)}
            process = conn.execute("SELECT value FROM _build WHERE key='process'").fetchone()
            if process is None or json.loads(process[0]) != list(map(str, engine.process_key)):
                raise Rebuild('the game process is not the one the snapshot was read from')
            engine.refresh_memory()
            save = engine.save_info()
            row = conn.execute('SELECT save_key, game_date FROM _snapshot').fetchone()
            if row is None or row[0] != save.save_key:
                raise Rebuild('another save is loaded')
            # The table vectors as this process stored them at the last check (they are reloaded
            # only when another process checked since): decoding them costs 1 to 3 s.
            cached = getattr(engine, '_fmdb_live', None)
            if cached and last is not None and cached[0] == (str(path), last):
                live = cached[1]
            else:
                live = load_live(conn)
            engine._fmdb_live = None            # updated in place below; published again with the check
            moved = _update_vectors(engine, live)
            # ---- pages
            stored = dict(conn.execute('SELECT page, hash FROM _direct_pages'))
            prefetch = getattr(engine.memory, 'prefetch', None)
            if prefetch is not None and stored:
                try:
                    prefetch([(p << PAGE_SHIFT, 1) for p in stored])
                except Exception:  # noqa: BLE001 - unreadable pages hash as 0 below
                    pass
            changed_pages = set()
            for page, old in stored.items():
                data = _page(engine.memory, page << PAGE_SHIFT)
                if (page_hash(data) if data is not None else 0) != old:
                    changed_pages.add(page)
            t_pages = time.time() - started
            # ---- blocks to evaluate again
            pending = defaultdict(set)
            blocks_checked = 0
            if changed_pages:
                for table, block, blob, windows, crc in conn.execute(
                        'SELECT table_name, block, pages, windows, crc FROM _direct_blocks'):
                    pages = array('Q')
                    pages.frombytes(blob)
                    if not changed_pages.isdisjoint(pages):
                        # a window on a changed page: evaluate again only if the window bytes differ
                        blocks_checked += 1
                        if windows_crc(engine.memory, unpack_weak(windows)) != crc:
                            pending[table].add(block)
            blocks_changed = sum(len(b) for b in pending.values())
            sync = _Sync(engine, conn, live, snapshot.plan_store(engine))
            moved_rows = {}
            for kind, idxs in moved.items():
                for table, rtype in snapshot.TABLES.items():
                    if tables.RECORD_TYPES[rtype].table == kind and table in sync.present:
                        pending[table].update(i >> BLOCK_SHIFT for i in idxs)
                        moved_rows[table] = idxs
            pending = {t: b for t, b in pending.items() if t in sync.present and b}
            # the record heads (class, ids) of rows on changed pages
            for table, blocks in pending.items():
                lt = sync.live_by_sql[table]
                _read_heads(engine, lt, [i for b in blocks for i in range(b << BLOCK_SHIFT,
                                                                           min((b + 1) << BLOCK_SHIFT, len(lt.pointers)))])
            refreshed = defaultdict(int)
            unstable_left = {}
            rounds = 0
            while pending and rounds < MAX_ROUNDS:
                rounds += 1
                recorder = Recorder(engine)
                ops = {t: sync.prepare(t, blocks, recorder) for t, blocks in pending.items()}
                read_crc = {t: recorder.crcs(t) for t in pending}       # of the bytes that were decoded
                moving = reread(engine.memory, [p << PAGE_SHIFT for p in recorder.pages()])
                moving = {base >> PAGE_SHIFT for base in moving}
                stable, again = {}, {}
                for t, blocks in pending.items():
                    bad = set()
                    if moving:
                        pages_of = recorder.block_pages(t)
                        for b in blocks:
                            if b in pages_of and not moving.isdisjoint(pages_of[b]) and \
                                    windows_crc(engine.memory, recorder.groups[t][b]) != read_crc[t].get(b):
                                bad.add(b)          # its bytes moved while it was being read
                    stable[t] = blocks - bad
                    if bad:
                        again[t] = bad
                for t, blocks in stable.items():
                    if blocks:
                        refreshed[t] += sync.apply(t, ops[t], blocks)
                        # a block without windows now (every record left) keeps no dependency row
                        conn.executemany('DELETE FROM _direct_blocks WHERE table_name=? AND block=?',
                                         [(t, b) for b in blocks])
                write_dependencies(conn, recorder, only=stable)
                pending, unstable_left = again, again
            if not pending:
                unstable_left = {}
            for table, idxs in moved_rows.items():
                clear_memo_rows(conn, table, idxs)
            # A changed page that no evaluated block reads any more (its rows now read elsewhere) takes
            # its current hash, so it is not reported again; pages of blocks that are still changing
            # keep the old hash and are seen as changed by the next check.
            held = set()
            for t, blocks in unstable_left.items():
                for b in blocks:
                    row = conn.execute('SELECT pages FROM _direct_blocks WHERE table_name=? AND block=?',
                                       (t, b)).fetchone()
                    if row:
                        pages = array('Q')
                        pages.frombytes(row[0])
                        held.update(pages)
            rehash = []
            for page in changed_pages - held:
                data = _page(engine.memory, page << PAGE_SHIFT)
                rehash.append((page_hash(data) if data is not None else 0, page))
            conn.executemany('UPDATE _direct_pages SET hash=? WHERE page=?', rehash)
            vectors_written = save_live(conn, live, only_changed=True)
            conn.execute('UPDATE _snapshot SET game_date=?', (save.game_date,))
            identity = {k: list(v.identity) for k, v in live.items()}
            conn.execute("INSERT OR REPLACE INTO _build VALUES ('identity', ?)", (json.dumps(identity),))
            total = sum(refreshed.values())
            seq = int(get_fresh(conn, 'change_seq', 0) or 0) + (1 if (total or changed_pages or moved) else 0)
            result = {'seconds': round(time.time() - started, 3), 'cpu_seconds': round(time.process_time() - cpu, 3),
                      'pages_checked': len(stored), 'pages_changed': len(changed_pages),
                      'page_read_seconds': round(t_pages, 3),
                      'rows_refreshed': total, 'by_table': {t: n for t, n in refreshed.items() if n},
                      'rounds': rounds, 'blocks_checked': blocks_checked, 'blocks_changed': blocks_changed,
                      'vectors_written': vectors_written,
                      'records_moved': {k: len(v) for k, v in moved.items()},
                      'game_date': save.game_date}
            if unstable_left:
                result['still_changing'] = {t: len(b) for t, b in unstable_left.items()}
            stamp = time.time()
            engine._fmdb_live = ((str(path), stamp), live)
            set_fresh(conn, checked_at=now_iso(), checked_at_unix=stamp, rows_refreshed=total,
                      pages_changed=len(changed_pages), pages_checked=len(stored), change_seq=seq,
                      last_check=result,
                      changed_tables=sorted(t for t, n in refreshed.items() if n),
                      checks=int(get_fresh(conn, 'checks', 0) or 0) + 1)
            for table, n in refreshed.items():
                if n:
                    set_fresh(conn, **{f'seq:{table}': seq})
            conn.commit()
            if log:
                log(f'freshness: {result}')
            return {**result, **status(conn)}
        finally:
            conn.close()


class Rebuild(RuntimeError):
    """The snapshot cannot be repaired in place; build it again."""


def table_seq(conn, table) -> int:
    """The change sequence number at which rows of `table` last changed (0: not since the build).
    Collection sources use it as a content key for data they derive from snapshot rows."""
    return int(get_fresh(conn, f'seq:{table}', 0) or 0)
