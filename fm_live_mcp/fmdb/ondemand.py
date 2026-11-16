"""On-demand emulated columns: computed when a query names them, for the rows it needs.

A snapshot table holds its direct columns; a column whose value only the game's getter can
give (`_column_state.status = 'on_demand'`) is NULL until asked for. `Session` runs one
statement:

* `plan(reads, sql)`: the base tables the statement reads that have on-demand columns are
  shadowed, for this connection only, by a TEMP view of the same name in which every on-demand
  column `c` is `fm_cell(<id>, idx, c)`; every stored view that reads a shadowed table is
  created again as a TEMP view so it resolves to the shadow. A column is *enabled* when the
  statement names it, or names a view column built from it.
* `fm_cell` (a SQL function bound to the session) returns the stored cell when it is memoised
  and still valid; computes it through the getter when the column is enabled; and returns NULL
  otherwise. SQLite evaluates a result column only for rows that pass the WHERE clause on other
  columns, so a point lookup or a filtered query computes exactly the rows it returns or sorts.
  A statement that filters, sorts, groups or joins on the column makes SQLite ask for every
  row: after `BULK_AFTER` computed cells of one column in one statement the rest of that
  column is computed in one pass (record pages fetched in batches), once.
* `finish()`: the computed cells are written into the table (the snapshot is the memo), with
  the validity bitmap of each column (`_memo`) and the read set of each block of rows
  (`_memo_blocks`).

The `SELECT *` rule. `*` never computes: a column that the statement does not name returns
its memoised cells and NULL elsewhere, and the result lists what was left out. Name a column
(or the view column built from it) to have it computed.

Validity. The tracking VM (`fastvm.TrackingFastVM`) records which 8-byte words of live memory
the getter calls of a block of rows (`freshness.BLOCK_ROWS` consecutive idx values) read, less
the words a call itself stored in full (reference counts, locks, allocator free lists, the
result it built). The block's read set, with a hash of those words, is stored with the cells.
Before a memoised cell of a block is used, and before more cells are added to it, the words
are read again and hashed: any difference drops every memoised cell of the block (all columns
of the table; the stored cells are set to NULL), which are then computed again on demand.
Without the tracking accelerator (`scripts/build_vm_accel.sh`) cells are computed the same way
for the statement and are not written to the table. An idx whose record pointer changed loses its cells (`freshness.clear_memo_rows`).

Declared inputs. The position-text getters (`Ppsr`, `Ppss`, about 1 ms per player) build their
string in a scratch buffer of the game that changes every few seconds, so their read set never
holds. Their value is a function of the player's stored position ratings: on 14,000 players
(7,008 distinct rating tuples) no tuple had two texts. For such a column (`DECLARED_INPUTS`) a
cell stays valid until one of its input cells in the same row changes (`freshness` clears it
when it updates the row); its reads are not added to the block's read set. The audit recomputes
samples of it like any memoised column and marks it `nomemo` on a difference.

Values are those of the released path: `bulkplans.canonical(getter result)`, the plan's
fallback for a `_fseeko` refusal, then `snapshot.to_sql`.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import os
import re
import sqlite3
import struct
import time
import zlib

from . import bulkplans, freshness, tables
from .bulkplans import Missing
from .freshness import BLOCK_SHIFT

BULK_AFTER = 1024               # computed cells of one column in one statement before the whole column is computed
# Storing computed cells waits at most this long for the snapshot's write lock. Lock order: a
# session stores only after the statement's query connection is closed, and every other
# connection to the snapshot that is open meanwhile (the manager view's masked connection) is in
# autocommit, so the wait is for another process, never for this one.
STORE_TIMEOUT_S = 30.0
POSITION_RATINGS = ('Pgoa', 'Pdls', 'Pdce', 'Pdrs', 'Pdmc', 'Pwbl', 'Pwbr', 'Pmls', 'Pmce', 'Pmrs', 'Paml', 'Pamc',
                    'Pamr', 'Pace')
# (record type, code) -> codes of the stored columns of the same row the value is a function of
# Team and competition names: every getter call reads one heap word shared by all calls (a
# pointer that changes every few seconds; 1 of 15,881 words of 40 team-name calls in 8 s, 1 of
# 658 for competitions) while the names stayed equal (40 of 40 each, 12 Nov 2026), so their read
# sets never held and every statement that filtered on a team name computed all 66,021 again
# (about 130 CPU s). A name is constant over the record's life: valid until the row's unique id
# (or, for teams, its type or gender) changes, or the record pointer changes (freshness drops the
# row's cells). A club renamed in the game keeps its teams' old names until the audit samples one.
TEAM_NAME_INPUTS = ('duni', 'Ttyp', 'PLgn')
DECLARED_INPUTS = {('play', 'Ppsr'): POSITION_RATINGS, ('play', 'Ppss'): POSITION_RATINGS,
                   ('team', 'Tlna'): TEAM_NAME_INPUTS, ('team', 'Tsna'): TEAM_NAME_INPUTS,
                   ('team', 'dbnm'): TEAM_NAME_INPUTS, ('comp', 'dbnm'): ('duni',), ('comp', 'Csna'): ('duni',),
                   ('comp', 'Cnam'): ('duni',)}
# Name columns computed on the UI accelerator (ui_fastvm.FastUiHandlerVM in the database view,
# reader thread): the same getter, with memmove/strcmp/strlen and the game's pool allocators
# modelled in C, about 0.25 ms a team name against 0.8 ms on FastVM (whose models of those
# imports are Python). scripts/fmdb_name_check.py compared the two on every record of these
# columns (docs/fmdb/PERFORMANCE.md). Only declared-input columns qualify: they keep no read set,
# which this VM does not record in the memo's format. FMDB_NAME_VM=0 uses the tracking VM.
NAME_VM_CODES = {('team', 'Tlna'), ('team', 'Tsna'), ('team', 'dbnm'), ('comp', 'dbnm'), ('comp', 'Csna'),
                 ('comp', 'Cnam')}
VM_PAGE = 4096
_NO = object()


def name_vm(engine):
    """The engine's VM for NAME_VM_CODES (None without the UI accelerator or with FMDB_NAME_VM=0)."""
    if os.environ.get('FMDB_NAME_VM', '1') == '0':
        return None
    vm = getattr(engine, '_fmdb_name_vm', None)
    if vm is None:
        from . import ui_fastvm, ui_vm
        from .engine import _VMReader
        if not ui_vm.fast_wanted() or not ui_fastvm.available():
            return None
        ref = engine.vm
        vm = ui_vm.UiHandlerVM(_VMReader(engine.memory), engine.base, engine.image, view='database',
                               thread='reader', budget=ref.budget, timeout_us=ref.timeout_us,
                               file_resolver=engine.file_resolver(),
                               rng=ref.rng if ref.rng in ui_vm.RNG_POLICIES else 'refuse')
        if not hasattr(vm, 'begin_read'):
            return None
        try:
            engine._fmdb_name_vm = vm
        except AttributeError:
            pass
    return vm
_IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')


def _q(name):
    return '"' + name.replace('"', '""') + '"'


class _Column:
    __slots__ = ('table', 'name', 'col', 'cid', 'ondemand', 'valid', 'fresh', 'enabled', 'misses', 'computed',
                 'omitted', 'fallback', 'missing', 'bulk', 'cpu', 'hits', 'stored_cells', 'keep', 'declared', 'namevm')

    def __init__(self, table, name, col, cid):
        self.table, self.name, self.col, self.cid = table, name, col, cid
        self.ondemand = set()           # record classes computed on demand
        self.valid = bytearray()
        self.fresh = {}                 # idx -> SQL value computed in this session
        self.enabled = False
        self.misses = self.computed = self.omitted = self.hits = 0
        self.fallback = {}              # class -> plan with a fallback
        self.missing = Counter()
        self.bulk = False
        self.cpu = 0.0
        self.stored_cells = 0
        self.keep = True                # False: the audit found a stale cell; never memoised again
        self.declared = False           # valid until a declared input cell of the row changes (DECLARED_INPUTS)
        self.namevm = False             # computed on name_vm(), cell by cell (NAME_VM_CODES)


class _Block:
    __slots__ = ('reads', 'dirty', 'hashes')

    def __init__(self):
        self.reads = {}                 # 4 KiB page address -> 512-bit mask of 8-byte words read
        self.dirty = False
        self.hashes = None              # packed u64 per page (sorted by page) when computed


class _Table:
    def __init__(self, name, live):
        self.name, self.live = name, live
        self.columns = {}               # name -> _Column (on-demand columns only)
        self.blocks = {}                # block -> _Block
        self.verified = set()           # blocks checked in this memory generation
        self.invalidated = set()        # blocks whose memoised cells were dropped in this session
        self.dropped = defaultdict(set)  # block -> columns that had memoised cells there
        self.loaded = False


def unpack_reads(records: bytes) -> dict:
    out = {}
    for off in range(0, len(records), 72):
        page = struct.unpack_from('<Q', records, off)[0]
        out[page] = int.from_bytes(records[off + 8:off + 72], 'little')
    return out


def pack_reads(reads: dict) -> bytes:
    return b''.join(struct.pack('<Q', page) + reads[page].to_bytes(64, 'little') for page in sorted(reads))


class Session:
    """One statement's on-demand work (module docstring). Hold `engine.lock` from `plan` to
    `finish`; the session is not reusable."""

    def __init__(self, engine, path, *, log=None, bulk_after=BULK_AFTER, bulk_budget_s=None):
        self.engine, self.path, self.log = engine, path, log
        self.bulk_after = bulk_after
        # whole-column passes of this session stop this long after it was created (None: no limit)
        self.bulk_deadline = None if bulk_budget_s is None else time.time() + bulk_budget_s
        self.vm = engine.tracked_vm
        self.tracking = self.vm is not None
        if self.vm is None:
            self.vm = engine.vm
        self.tables = {}
        self.cols = []                  # cid -> _Column
        self.shadowed = []
        self.seconds = 0.0              # time spent computing (the query time limit does not count it)
        self.cpu = 0.0
        self.blocks_dropped = 0
        self.unresolved = []
        self._conn = None
        self._live = None
        self._resolver = None
        self._states = None
        self._nomemo = None
        self._py_reads = None           # Python-side reads of the cell being computed
        self._namevm = _NO
        self.finished = False

    def namevm(self):
        """name_vm(engine), with a new page generation once per session (pages copied by an
        earlier statement are read again before use)."""
        if self._namevm is _NO:
            self._namevm = name_vm(self.engine)
            if self._namevm is not None:
                from .fastvm import LIVE_PAGE_LIMIT
                if len(self._namevm.live_pages) > LIVE_PAGE_LIMIT:
                    self._namevm.invalidate()
                self._namevm.begin_read()
        return self._namevm

    # ------------------------------------------------------------------ set-up
    def _meta(self):
        if self._conn is None:
            self._conn = sqlite3.connect(f'file:{self.path}?mode=ro', uri=True, timeout=30)
        return self._conn

    def live(self):
        if self._live is None:
            cached = getattr(self.engine, '_fmdb_live', None)
            stamp = freshness.get_fresh(self._meta(), 'checked_at_unix')
            if cached and cached[0] == (str(self.path), stamp):
                self._live = cached[1]
            else:
                self._live = freshness.load_live(self._meta())
                self.engine._fmdb_live = ((str(self.path), stamp), self._live)
        return self._live

    def resolver(self):
        if self._resolver is None:
            from . import snapshot
            live = self.live()
            self._resolver = snapshot.Resolver({t: live[tables.RECORD_TYPES[rt].table]
                                                for t, rt in snapshot.TABLES.items()
                                                if tables.RECORD_TYPES[rt].table in live})
        return self._resolver

    def states(self):
        """{table: {column: {classes computed on demand}}} from `_column_state`. The table is
        written only by a build, so it is read once per snapshot build and process (0.2 s a
        statement before)."""
        if self._states is None:
            try:
                # plans_verified changes when a demoted plan's column becomes on-demand in place
                built = self._meta().execute('SELECT built_at, plans_verified FROM _snapshot').fetchone()
            except sqlite3.Error:
                built = None
            try:
                inode = os.stat(self.path).st_ino        # a build replaces the file (a new inode)
            except OSError:
                inode = None
            key = (str(self.path), inode, tuple(built) if built else None)
            cached = getattr(self.engine, '_fmdb_states', None)
            if built and cached and cached[0] == key:
                self._states = cached[1]
                return self._states
            out = defaultdict(lambda: defaultdict(set))
            try:
                for t, c, cls in self._meta().execute(
                        "SELECT table_name, column_name, class FROM _column_state WHERE status='on_demand'"):
                    out[t][c].add(cls)
            except sqlite3.Error:
                pass
            self._states = out
            if built:
                try:
                    self.engine._fmdb_states = (key, out)
                except AttributeError:
                    pass
        return self._states

    def nomemo(self):
        """Columns the audit excluded from the memo (`_fresh` nomemo:<table>.<column>), one query."""
        if self._nomemo is None:
            try:
                self._nomemo = {k for (k,) in self._meta().execute("SELECT key FROM _fresh WHERE key LIKE 'nomemo:%'")}
            except sqlite3.Error:
                self._nomemo = set()
        return self._nomemo

    def table(self, name) -> _Table:
        """The on-demand state of one table: its columns, their validity bitmaps and fallbacks."""
        t = self.tables.get(name)
        if t is not None:
            return t
        from . import snapshot
        live = self.live()[tables.RECORD_TYPES[snapshot.TABLES[name]].table]
        t = self.tables[name] = _Table(name, live)
        columns = {c.name: c for c in snapshot.columns_for(self.engine.catalog, name)}
        store = None
        size = (len(live.pointers) + 7) // 8
        valid = {c: (v, n) for c, v, n in self._meta().execute(
            'SELECT column_name, valid, cells FROM _memo WHERE table_name=?', (name,))}
        counts = Counter(c for c, p in zip(live.classes, live.pointers) if p)
        declared = declared_columns(self._meta(), self.engine.catalog, name)     # once a table, not once a column
        for cname, classes in self.states().get(name, {}).items():
            col = columns.get(cname)
            if col is None:
                continue
            c = _Column(t, cname, col, len(self.cols))
            c.ondemand = set(classes)
            blob, cells = valid.get(cname, (b'', 0))
            c.keep = f'nomemo:{name}.{cname}' not in self.nomemo()
            c.valid = bytearray((blob or b'') if c.keep else b'')
            c.stored_cells = (cells or 0) if c.keep else 0
            if len(c.valid) < size:
                c.valid.extend(bytes(size - len(c.valid)))
            c.declared = cname in declared
            c.namevm = c.declared and (col.record_type, col.code) in NAME_VM_CODES
            if snapshot.traced(col):
                for cls in classes:
                    if counts.get(cls, 0) > snapshot.SMALL_CLASS:
                        if store is None:
                            store = snapshot.plan_store(self.engine)
                        plan = store.get(cls, col.code)
                        if plan and plan.get('fallback'):
                            c.fallback[cls] = plan
            self.cols.append(c)
            t.columns[cname] = c
        t.loaded = True
        return t

    def plan(self, reads, sql):
        """Decide which tables to shadow and which columns the statement enables. `reads` is
        `query.referenced_columns` output; returns the number of enabled columns."""
        states = self.states()
        tokens = {tok.lower() for tok in _IDENT.findall(sql)}
        wanted = sorted({t for t, c, _ in reads if t in states and c in states[t]})
        aliases = defaultdict(set)
        if wanted:
            try:
                for alias, t, c in self._meta().execute('SELECT column_name, base_table, base_column '
                                                        'FROM _view_columns'):
                    aliases[(t, c)].add(alias.lower())
            except sqlite3.Error:
                pass
        enabled = 0
        for name in wanted:
            t = self.table(name)
            self.shadowed.append(name)
            for c in t.columns.values():
                c.enabled = c.name.lower() in tokens or not aliases[(name, c.name)].isdisjoint(tokens)
                enabled += c.enabled
        return enabled

    def enable(self, table, columns):
        t = self.table(table)
        if table not in self.shadowed:
            self.shadowed.append(table)
        for name in columns:
            if name in t.columns:
                t.columns[name].enabled = True

    def attach(self, conn):
        """Create the shadow views and `fm_cell` on a query connection (before its authorizer)."""
        if not self.shadowed:
            return
        conn.create_function('fm_cell', 3, self.cell)
        recreated = set()
        for name in self.shadowed:
            t = self.tables[name]
            parts = []
            for (_, column, *_rest) in conn.execute(f'PRAGMA main.table_info({_q(name)})').fetchall():
                c = t.columns.get(column)
                parts.append(_q(column) if c is None else f'fm_cell({c.cid}, idx, {_q(column)}) AS {_q(column)}')
            conn.execute(f'CREATE TEMP VIEW {_q(name)} AS SELECT {", ".join(parts)} FROM main.{_q(name)}')
            recreated.add(name.lower())
        # stored views that read a shadowed table (or a view created again here) must resolve to the shadow
        views = conn.execute("SELECT name, sql FROM main.sqlite_master WHERE type='view'").fetchall()
        bodies = {}
        for name, sql in views:
            m = re.match(r'\s*CREATE\s+VIEW\s+(?:"(?:[^"]|"")*"|\S+)\s+AS\s+', sql or '', re.I | re.S)
            if m:
                bodies[name] = (sql[m.end():], {tok.lower() for tok in _IDENT.findall(sql[m.end():])})
        changed = True
        while changed:
            changed = False
            for name, (body, toks) in bodies.items():
                if name.lower() not in recreated and not toks.isdisjoint(recreated):
                    conn.execute(f'CREATE TEMP VIEW {_q(name)} AS {body}')
                    recreated.add(name.lower())
                    changed = True

    # ------------------------------------------------------------------ the SQL function
    def cell(self, cid, idx, stored):
        c = self.cols[cid]
        if c.fresh:
            v = c.fresh.get(idx, _NO)
            if v is not _NO:
                return v
        t = c.table
        try:
            cls = t.live.classes[idx]
        except (IndexError, TypeError):
            return stored
        if cls not in c.ondemand:
            return stored                       # a class read directly (stored at build) or unavailable
        block = idx >> BLOCK_SHIFT
        if block not in t.verified:
            self.verify(t, block)
        if c.valid[idx >> 3] >> (idx & 7) & 1:
            c.hits += 1
            return stored
        if not c.enabled:
            c.omitted += 1
            return None
        c.misses += 1
        # a name column on name_vm() is computed for exactly the rows the statement asks for (a
        # join from fixtures needs 7,055 of 66,021 team names): no whole-column pass
        if c.misses > self.bulk_after and not c.bulk and not (c.namevm and self.namevm() is not None):
            self.bulk(c, budget_s=None if self.bulk_deadline is None
                      else max(0.0, self.bulk_deadline - time.time()))
            v = c.fresh.get(idx, _NO)
            if v is not _NO:
                return v
        return self.compute(c, block, (idx,))[0]

    # ------------------------------------------------------------------ validity
    def _page_bytes(self, pages):
        """(buffer, offsets) of the VM's copy of each 4 KiB page (None: unreadable). Reading
        through the VM makes later getter calls in this session see exactly these bytes."""
        prefetch = getattr(self.engine.memory, 'prefetch', None)
        if prefetch is not None:
            try:
                prefetch([(p, VM_PAGE) for p in pages])
            except Exception:  # noqa: BLE001 - unreadable pages are handled one by one below
                pass
        settle = getattr(self.vm, 'settle', None)
        if settle is not None:
            settle()
        parts, offsets, at = [], [], 0
        read = self.vm.read
        for page in pages:
            try:
                data = read(page, VM_PAGE)
            except Exception:  # noqa: BLE001 - a page the VM cannot copy has no content
                offsets.append(None)
                continue
            parts.append(data)
            offsets.append(at)
            at += VM_PAGE
        return b''.join(parts), offsets

    def _hashes(self, reads: dict) -> bytes:
        from . import fastvm
        pages = sorted(reads)
        buffer, offsets = self._page_bytes(pages)
        hashes = fastvm.words_hash(buffer, offsets, pack_reads(reads))
        return struct.pack(f'<{len(hashes)}Q', *hashes)

    def verify(self, t: _Table, block: int):
        """Check the stored read set of one block against memory now; drop its cells if it moved."""
        t.verified.add(block)
        b = t.blocks.get(block)
        if b is None:
            b = t.blocks[block] = _Block()
            row = self._meta().execute('SELECT reads, hashes FROM _memo_blocks WHERE table_name=? AND block=?',
                                       (t.name, block)).fetchone()
            if row is not None:
                b.reads = unpack_reads(zlib.decompress(row[0]))
                b.hashes = row[1]
        elif b.dirty and self.tracking:
            return                              # read set extended in this session, hashed from this generation
        ok = self.tracking and b.hashes is not None and self._hashes(b.reads) == b.hashes
        if ok:
            return
        # no read set, no tracking, or a word changed: nothing memoised in this block is usable
        lo, hi = block << BLOCK_SHIFT, (block + 1) << BLOCK_SHIFT
        dropped = False
        for c in t.columns.values():
            if not c.stored_cells or c.declared:
                continue                        # nothing memoised here, or valid by its declared inputs
            for byte in range(lo >> 3, min(hi >> 3, len(c.valid))):
                if c.valid[byte]:
                    c.valid[byte] = 0
                    dropped = True
                    t.dropped[block].add(c.name)
        if dropped or b.reads:
            t.invalidated.add(block)
            self.blocks_dropped += dropped
        b.reads, b.hashes, b.dirty = {}, None, bool(b.reads)

    def drop_block(self, t: _Table, block: int):
        """Drop every memoised cell of one block (the audit found one of them stale)."""
        b = t.blocks.setdefault(block, _Block())
        b.hashes = None
        b.reads = {0: 1}                # no stored hash can match: verify() drops the block
        b.dirty = False
        t.verified.discard(block)
        self.verify(t, block)

    def check_stored(self, table):
        """Check every block of `table` that has memoised cells, so that a reader of the stored
        table (the manager view's `*`) sees only cells that are valid now: the cells of a block
        that moved are set to NULL by `finish`."""
        if table not in self.states():
            return
        t = self.table(table)
        for (block,) in self._meta().execute('SELECT block FROM _memo_blocks WHERE table_name=?', (table,)).fetchall():
            if block not in t.verified:
                self.verify(t, block)

    # ------------------------------------------------------------------ computing
    def _read_logged(self, address, length):
        """`engine.cached_read` for Python-side reads of a cell (plan fallbacks), recorded."""
        self._py_reads.append((address, length))
        return self.engine.cached_read(address, length)

    def compute(self, c: _Column, block: int, idxs) -> list:
        """Run the getter for rows of one block; values go to `c.fresh`, reads to the block."""
        from . import snapshot
        from .extras import read_derived
        from .fastvm import LIVE_PAGE_LIMIT
        started, cpu = time.time(), time.process_time()
        vm, t = self.vm, c.table
        named = self.namevm() if c.namevm else None
        tracking = self.tracking and named is None
        live = t.live
        if named is not None:
            vm = named
            if len(vm.live_pages) > LIVE_PAGE_LIMIT:
                vm.invalidate()
                vm.begin_read()
        elif len(vm.live_pages) > LIVE_PAGE_LIMIT:
            self._drop_vm_pages()
        if tracking:
            vm.touch_begin()
        code = c.col.code
        derived = code[2:] if code.startswith('x:') else None
        resolver = self.resolver()
        before = len(resolver.unresolved)
        self._py_reads = []
        out = []
        try:
            for i in idxs:
                pointer = live.pointers[i]
                result = read_derived(vm, pointer, derived) if derived else vm.get_property(pointer, code)
                value = bulkplans.canonical(result)
                if isinstance(value, Missing):
                    plan = c.fallback.get(live.classes[i])
                    if plan is not None and value.reason.endswith('_fseeko'):
                        value = bulkplans.try_apply(self._read_logged, pointer, plan)
                    else:
                        c.missing[value.reason] += 1
                value = snapshot.to_sql(c.col, i, value, resolver)
                c.fresh[i] = value
                out.append(value)
        finally:
            records = vm.touch_end() if tracking else b''
        c.computed += len(idxs)
        if len(resolver.unresolved) > before:
            self.unresolved += resolver.unresolved[before:]
            del resolver.unresolved[before:]
        if self.tracking and not c.declared:
            b = t.blocks.get(block)
            if b is None:
                b = t.blocks[block] = _Block()
            reads = b.reads
            for off in range(0, len(records), 72):
                page = struct.unpack_from('<Q', records, off)[0]
                reads[page] = reads.get(page, 0) | int.from_bytes(records[off + 8:off + 72], 'little')
            for address, length in self._py_reads:
                last = address + length - 1
                for page in range(address & ~(VM_PAGE - 1), last + 1, VM_PAGE):
                    lo = max(address, page) - page >> 3
                    hi = min(last, page + VM_PAGE - 1) - page >> 3
                    reads[page] = reads.get(page, 0) | (((1 << (hi - lo + 1)) - 1) << lo)
            b.dirty = True
            b.hashes = None
        spent = time.time() - started
        self.seconds += spent
        used = time.process_time() - cpu
        c.cpu += used
        self.cpu += used
        return out

    def _drop_vm_pages(self):
        """The VM's page pool is full: fix the hashes of the read sets recorded so far (they
        describe the copies about to be dropped), drop, and check every block again before its
        next use, because pages copied from now on may hold newer bytes."""
        if self.tracking:
            for t in self.tables.values():
                for b in t.blocks.values():
                    if b.dirty and b.hashes is None and b.reads:
                        b.hashes = self._hashes(b.reads)
                t.verified.clear()
        drop = getattr(self.vm, 'drop_live_pages', None)
        if drop is not None:
            drop()
        else:                                   # PropertyVM: a new instance is the cheap way
            self.engine._vm = None
            self.vm = self.engine.vm

    def rows(self, c: _Column):
        """idx values of the column's on-demand rows that have no usable cell yet, by block."""
        live = c.table.live
        valid, fresh, classes = c.valid, c.fresh, c.ondemand
        by_block = defaultdict(list)
        for i, (pointer, cls) in enumerate(zip(live.pointers, live.classes)):
            if pointer and cls in classes and i not in fresh:
                by_block[i >> BLOCK_SHIFT].append(i)
        return by_block, valid

    def bulk(self, c: _Column, only=None, budget_s=None):
        """Compute every missing cell of the column (or of the idx values in `only`)."""
        started = time.time()
        t = c.table
        by_block, valid = self.rows(c)
        if only is not None:
            only = set(only)
        done = True
        for block in sorted(by_block):
            idxs = by_block[block] if only is None else [i for i in by_block[block] if i in only]
            if not idxs:
                continue
            if budget_s is not None and time.time() - started > budget_s:
                done = False
                break
            if block not in t.verified:
                self.verify(t, block)
            todo = [i for i in idxs if not valid[i >> 3] >> (i & 7) & 1]
            if not todo:
                continue
            self.engine.prefetch([t.live.pointers[i] for i in todo])
            self.compute(c, block, todo)
        if only is None and done:
            c.bulk = True
        return done

    # ------------------------------------------------------------------ writing back
    def finish(self) -> dict:
        """Store what was computed and return the summary for the tool result."""
        if self.finished:
            return {}
        self.finished = True
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        columns, omitted, cells = [], Counter(), 0
        for t in self.tables.values():
            for c in t.columns.values():
                if c.computed:
                    columns.append({'column': f'{t.name}.{c.name}', 'cells': c.computed, 'cpu_seconds': round(c.cpu, 3),
                                    **({'whole_column': True} if c.bulk else {}),
                                    **({'unavailable': dict(c.missing)} if c.missing else {})})
                    cells += c.computed
                if c.omitted:
                    omitted[t.name] += 1
        summary = {}
        if columns:
            summary.update(columns=columns, cells=cells, seconds=round(self.seconds, 3), cpu_seconds=round(self.cpu, 3))
        if omitted:
            summary['not_computed'] = dict(omitted)
        if self.blocks_dropped:
            summary['memo_blocks_dropped'] = self.blocks_dropped
        dirty = any(c.fresh for t in self.tables.values() for c in t.columns.values()) or \
            any(t.invalidated for t in self.tables.values())
        if not dirty:
            return summary
        started = time.time()
        try:
            self._store()
            summary['stored'] = self.tracking
            if not self.tracking:
                summary['note'] = ('cells were computed for this statement only: the read-tracking accelerator is '
                                   'not built (scripts/build_vm_accel.sh), so they cannot be checked later')
        except (sqlite3.Error, OSError) as exc:
            summary['stored'] = False
            summary['note'] = f'computed cells were returned but not stored: {exc}'
        summary['store_seconds'] = round(time.time() - started, 3)
        return summary

    def _store(self):
        from .engine import MIN_FREE_FILL, require_space
        require_space(self.path.parent, MIN_FREE_FILL, 'Storing computed cells')
        now = freshness.now_iso()
        conn = sqlite3.connect(self.path, timeout=STORE_TIMEOUT_S)
        try:
            for t in self.tables.values():
                # a stored cell of a block that moved is NULL again (a reader of the file never
                # meets a cell that failed its check); cells computed now are written after
                for block, names in t.dropped.items():
                    names = sorted(names)
                    for start in range(0, len(names), UPDATE_COLUMNS):
                        sets = ', '.join(f'{_q(n)}=NULL' for n in names[start:start + UPDATE_COLUMNS])
                        conn.execute(f'UPDATE {_q(t.name)} SET {sets} WHERE idx >= ? AND idx < ?',
                                     (block << BLOCK_SHIFT, (block + 1) << BLOCK_SHIFT))
                pairs = {}
                for c in t.columns.values():
                    if not c.fresh or not ((self.tracking or c.declared) and c.keep):
                        continue                # no read set, or a column the audit excluded: this statement only
                    pairs[c.name] = [(v, i) for i, v in c.fresh.items()]
                    for i in c.fresh:
                        c.valid[i >> 3] |= 1 << (i & 7)
                write_cells(conn, t.name, pairs)
                touched = bool(t.invalidated)
                for c in t.columns.values():
                    if c.fresh or touched:
                        count = sum(bin(b).count('1') for b in c.valid) if (c.fresh or c.stored_cells) else 0
                        if count or c.stored_cells or c.fresh:
                            conn.execute(
                                'INSERT INTO _memo VALUES (?, ?, ?, ?, ?, ?, 1) ON CONFLICT(table_name, column_name) '
                                'DO UPDATE SET valid=excluded.valid, cells=excluded.cells, '
                                'computed_at=CASE WHEN ? THEN excluded.computed_at ELSE computed_at END, '
                                'cpu_seconds=COALESCE(cpu_seconds, 0) + excluded.cpu_seconds, queries=queries + ?',
                                (t.name, c.name, bytes(c.valid), count, now, round(c.cpu, 4), bool(c.fresh),
                                 int(bool(c.fresh))))
                for block, b in t.blocks.items():
                    if not (b.dirty or block in t.invalidated):
                        continue
                    if self.tracking and b.reads:
                        if b.hashes is None:
                            b.hashes = self._hashes(b.reads)
                        conn.execute('INSERT OR REPLACE INTO _memo_blocks VALUES (?, ?, ?, ?)',
                                     (t.name, block, zlib.compress(pack_reads(b.reads), 1), b.hashes))
                    else:
                        conn.execute('DELETE FROM _memo_blocks WHERE table_name=? AND block=?', (t.name, block))
            if self.unresolved:
                conn.executemany('INSERT INTO _unresolved VALUES (?, ?, ?, ?)', self.unresolved)
            conn.commit()
        finally:
            conn.close()


UPDATE_COLUMNS = 200


def write_cells(conn, table, pairs_by_column):
    """Store {column: [(value, idx), ...]}. Columns that cover the same rows in the same order are
    set by one UPDATE per row: SQLite rewrites the whole (wide) row for every UPDATE."""
    groups = defaultdict(list)
    for name, pairs in pairs_by_column.items():
        if pairs:
            groups[tuple(i for _, i in pairs)].append(name)
    for idxs, names in groups.items():
        for start in range(0, len(names), UPDATE_COLUMNS):
            part = names[start:start + UPDATE_COLUMNS]
            columns = [[v for v, _ in pairs_by_column[name]] for name in part]
            sets = ', '.join(f'{_q(name)}=?' for name in part)
            conn.executemany(f'UPDATE {_q(table)} SET {sets} WHERE idx=?', zip(*columns, idxs))


def compute(engine, path, table, columns, where_idx=None, *, budget_s=None) -> dict:
    """Compute and store on-demand columns of one table now, for all rows or for `where_idx`.
    Cells that are memoised and still valid are kept. Returns counts and timing."""
    from . import snapshot
    started = time.time()
    with engine.lock:
        session = Session(engine, path)
        try:
            t = session.table(table)
            unknown = [c for c in columns if c not in {col.name for col in snapshot.columns_for(engine.catalog, table)}]
            if unknown:
                raise snapshot.SnapshotError(f'unknown columns for {table}: {unknown}')
            filled, complete = {}, True
            for name in columns:
                c = t.columns.get(name)
                if c is None:
                    filled[name] = 0            # a direct or unavailable column: nothing to compute
                    continue
                left = None if budget_s is None else max(0.0, budget_s - (time.time() - started))
                complete = session.bulk(c, only=where_idx, budget_s=left) and complete
                filled[name] = c.computed
        finally:
            summary = session.finish()
    return {'table': table, 'filled': filled, 'seconds': round(time.time() - started, 3), 'complete': complete,
            'rows': 'all' if where_idx is None else len(where_idx), 'stored': summary.get('stored', True),
            **({'note': summary['note']} if summary.get('note') else {})}


def declared_columns(conn, catalog, table) -> dict:
    """{column name: input column names} for the columns of `table` that are memoised by declared
    inputs: every input must be stored (read directly) for every class the column is computed
    on demand for, else the column is treated like any other."""
    from . import snapshot
    out = {}
    columns = snapshot.columns_for(catalog, table)
    by_code = {}
    for c in columns:
        by_code.setdefault((c.record_type, c.code), c.name)
    for c in columns:
        codes = DECLARED_INPUTS.get((c.record_type, c.code))
        if not codes or c.name != by_code.get((c.record_type, c.code)):
            continue
        inputs = [by_code.get((c.record_type, code)) for code in codes]
        if None in inputs:
            continue
        try:
            classes = {r[0] for r in conn.execute(
                "SELECT class FROM _column_state WHERE table_name=? AND column_name=? AND status='on_demand'",
                (table, c.name))}
            stored = [{r[0] for r in conn.execute(
                "SELECT class FROM _column_state WHERE table_name=? AND column_name=? AND source='direct' "
                "AND status='ready'", (table, name))} for name in inputs]
        except sqlite3.Error:
            continue
        if classes and all(classes <= s for s in stored):
            out[c.name] = set(inputs)
    return out


def carry_declared(conn, previous, catalog, log=None) -> dict:
    """Copy the memoised cells of declared-input columns from the previous snapshot of this save
    into a new build (`conn`, before its first statement). A cell is a function of its declared
    inputs (DECLARED_INPUTS: team names of the unique id, type and gender; competition names of
    the unique id; position text of the 14 ratings), so it is carried to every row of the new
    build whose input cells are equal, in this game process or another one. Input tuples that
    gave two values in the previous file are not carried. The audit samples carried cells like
    any memoised cell. Returns {table.column: cells carried}."""
    from pathlib import Path
    previous = Path(previous)
    out = {}
    if not previous.exists():
        return out
    try:
        old = sqlite3.connect(f'file:{previous}?mode=ro', uri=True, timeout=5)
    except sqlite3.Error:
        return out
    try:
        tables_old = {r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if '_memo' not in tables_old:
            return out
        memo = {(t, c): (v, n) for t, c, v, n in old.execute('SELECT table_name, column_name, valid, cells FROM _memo')
                if n}
        nomemo = {k for (k,) in old.execute("SELECT key FROM _fresh WHERE key LIKE 'nomemo:%'")} \
            if '_fresh' in tables_old else set()
        by_table = defaultdict(list)
        for (t, c) in memo:
            by_table[t].append(c)
        now = freshness.now_iso()
        for table, cols in by_table.items():
            declared = declared_columns(conn, catalog, table)
            if not declared:
                continue
            new_cols = {r[1] for r in conn.execute(f'PRAGMA main.table_info({_q(table)})')}
            old_cols = {r[1] for r in old.execute(f'PRAGMA table_info({_q(table)})')}
            classes_of = defaultdict(set)
            for c, cls in conn.execute("SELECT column_name, class FROM _column_state WHERE table_name=? "
                                       "AND status='on_demand'", (table,)):
                classes_of[c].add(cls)
            for col in cols:
                inputs = sorted(declared.get(col, ()))
                if (not inputs or f'nomemo:{table}.{col}' in nomemo or col not in new_cols or col not in old_cols
                        or not set(inputs) <= new_cols or not set(inputs) <= old_cols):
                    continue
                valid = memo[(table, col)][0] or b''
                keyed, clash = {}, set()
                select = ', '.join(_q(n) for n in inputs)
                for row in old.execute(f'SELECT idx, {_q(col)}, {select} FROM {_q(table)} '
                                       f'WHERE {_q(col)} IS NOT NULL'):
                    idx = row[0]
                    if not (idx >> 3 < len(valid) and valid[idx >> 3] >> (idx & 7) & 1):
                        continue
                    key = row[2:]
                    if key in keyed and keyed[key] != row[1]:
                        clash.add(key)
                    keyed[key] = row[1]
                for key in clash:
                    keyed.pop(key, None)
                if not keyed:
                    continue
                classes = classes_of.get(col, set())
                pairs = []
                size = 0
                for row in conn.execute(f'SELECT idx, class, {select} FROM {_q(table)}'):
                    size = max(size, row[0] + 1)
                    if row[1] in classes:
                        value = keyed.get(row[2:], _NO)
                        if value is not _NO:
                            pairs.append((value, row[0]))
                if not pairs:
                    continue
                bitmap = bytearray((size + 7) // 8)
                for _, idx in pairs:
                    bitmap[idx >> 3] |= 1 << (idx & 7)
                write_cells(conn, table, {col: pairs})
                conn.execute('INSERT INTO _memo VALUES (?, ?, ?, ?, ?, ?, 0) ON CONFLICT(table_name, column_name) '
                             'DO UPDATE SET valid=excluded.valid, cells=excluded.cells, computed_at=excluded.computed_at',
                             (table, col, bytes(bitmap), len(pairs), now, 0.0))
                out[f'{table}.{col}'] = len(pairs)
    except sqlite3.Error as exc:
        if log:
            log(f'declared cells not carried over: {exc}')
    finally:
        old.close()
    return out


def memo_summary(conn) -> dict:
    """{table: {columns memoised, cells}} for fm_db_schema."""
    out = {}
    try:
        for t, n, cells in conn.execute('SELECT table_name, COUNT(*), SUM(cells) FROM _memo WHERE cells > 0 '
                                        'GROUP BY table_name'):
            out[t] = {'columns': n, 'cells': cells}
    except sqlite3.Error:
        pass
    return out
