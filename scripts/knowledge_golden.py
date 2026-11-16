"""Whole-store golden comparison for the knowledge engine, at one frozen game state.

The game keeps running while a store is built, so two builds never see the same bytes. This
script freezes memory instead: every 16 KiB page is read from the game once, on first touch, and
every later read of it (by the bridge's helper path, by ``LiveMemory``, by the emulators) is
served from that copy. The copy is written to a page file, so a second build, by another code
tree, runs on exactly the same bytes.

    # 1. the reference: any code tree (``--tree`` is a directory holding ``fm_live_mcp``)
    python scripts/knowledge_golden.py build --tree OLD --store old.sqlite --pages pages.bin
    # 2. this tree on the recorded pages (pages it touches beyond them are counted)
    python scripts/knowledge_golden.py build --store new.sqlite --pages pages.bin --replay
    # 3. every row of every knowledge table
    python scripts/knowledge_golden.py diff old.sqlite new.sqlite

Read-only against the game. Process identity checks (pid, kernel incarnation, loaded image)
still go to the live process, which therefore has to stay up.
"""
from __future__ import annotations

import argparse
import json
import os
import resource
import sqlite3
import struct
import sys
import time
import zlib
from pathlib import Path

PAGE = 16384
_HEAD = struct.Struct('<QI')      # page base, compressed length (0xFFFFFFFF: unreadable)


class Frozen:
    """First-touch page copies of the game's memory."""

    def __init__(self, live, *, replay=False):
        self.live = live
        self.pages = {}
        self.bad = set()
        self.replay = replay
        self.late = 0             # pages faulted from the game after a replay file was loaded
        self.frozen = False       # True: a missing page is an error instead of a live read

    def load(self, path):
        with open(path, 'rb') as f:
            while True:
                head = f.read(_HEAD.size)
                if not head:
                    break
                base, size = _HEAD.unpack(head)
                if size == 0xFFFFFFFF:
                    self.bad.add(base)
                else:
                    self.pages[base] = zlib.decompress(f.read(size))

    def dump(self, path):
        tmp = Path(str(path) + '.tmp')
        with open(tmp, 'wb') as f:
            for base in sorted(self.pages):
                blob = zlib.compress(self.pages[base], 1)
                f.write(_HEAD.pack(base, len(blob)))
                f.write(blob)
            for base in sorted(self.bad):
                f.write(_HEAD.pack(base, 0xFFFFFFFF))
        os.replace(tmp, path)

    def fault(self, bases):
        missing = sorted(b for b in set(bases) if b not in self.pages and b not in self.bad)
        if not missing:
            return
        if self.frozen:
            raise RuntimeError(f'page {missing[0]:#x} is not in the frozen page file')
        if self.replay:
            self.late += len(missing)
        for base, raw in zip(missing, self.live.read_many([(b, PAGE) for b in missing])):
            if raw is None or len(raw) != PAGE:
                self.bad.add(base)
            else:
                self.pages[base] = bytes(raw)

    def read(self, address, length):
        """bytes, or None when a page of the range is unreadable."""
        first = address & ~(PAGE - 1)
        last = (address + length - 1) & ~(PAGE - 1)
        if first == last:
            page = self.pages.get(first)
            if page is None:
                self.fault((first,))
                page = self.pages.get(first)
                if page is None:
                    return None
            offset = address - first
            return page[offset:offset + length]
        bases = range(first, last + 1, PAGE)
        self.fault(bases)
        if any(b not in self.pages for b in bases):
            return None
        data = b''.join(self.pages[b] for b in bases)
        return data[address - first:address - first + length]


def install(frozen):
    """Route the tree's two memory transports through ``frozen``."""
    from fm_live_mcp import bridge as bridge_module
    from fm_live_mcp.fmdb import memory

    def bridge_read(self, process, address, length):
        if not 0 < address < 2 ** 64 - length or not 1 <= length <= 16384:
            raise bridge_module.BridgeError('Invalid bounded memory read.')
        raw = frozen.read(address, length)
        if raw is None:
            raise bridge_module.BridgeError('Native read failed or returned a mismatched response.')
        return raw

    bridge_module.Bridge._read_memory = bridge_read

    class FrozenLive(memory.MemoryBase):
        def __init__(self, pid, **_):
            self.pid = pid
            self.stats = memory.Stats()
            self.executable = getattr(frozen.live, 'executable', '')

        def read(self, address, length):
            raw = frozen.read(address, length)
            if raw is None:
                raise memory.MemoryReadError(f'cannot read {length} bytes at {address:#x}: read_failed',
                                             memory.ST_READ_FAILED)
            return raw

        cached_read = read

        def read_many_status(self, requests):
            out = []
            frozen.fault(b for a, n in requests for b in range(a & ~(PAGE - 1), a + n, PAGE))
            for address, length in requests:
                raw = frozen.read(address, length)
                out.append((memory.ST_OK, raw) if raw is not None else (memory.ST_READ_FAILED, None))
            return out

        def read_many(self, requests):
            return [raw for _, raw in self.read_many_status(requests)]

        def page(self, address):
            return self.read(address & ~(PAGE - 1), PAGE)

        def prefetch(self, ranges):
            frozen.fault(b for a, n in ranges for b in range(a & ~(PAGE - 1), a + n, PAGE))
            return 0

        def invalidate(self):
            pass

        def regions(self, **kwargs):
            return frozen.live.regions(**kwargs)

        def ping(self):
            return True

        def close(self):
            pass

    memory.LiveMemory = FrozenLive
    return FrozenLive


def cpu_seconds():
    a, b = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    return a.ru_utime + a.ru_stime + b.ru_utime + b.ru_stime


def build(args):
    tree = Path(args.tree).resolve() if args.tree else Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(tree))
    from fm_live_mcp import bridge as bridge_module
    from fm_live_mcp.fmdb import memory, knowledge_store as ks
    bridge = bridge_module.Bridge()
    sid = bridge.attach()['session_id']
    live = memory.LiveMemory(bridge.process.pid, expected_executable=bridge.process.executable)
    frozen = Frozen(live, replay=args.replay)
    if args.replay:
        frozen.load(args.pages)
        print(json.dumps(dict(loaded_pages=len(frozen.pages), unreadable=len(frozen.bad))), flush=True)
    install(frozen)
    try:
        from fm_live_mcp import knowledge_inputs
        knowledge_inputs.READAHEAD = 0      # a frozen build reads exactly the pages it consumes
    except ImportError:
        pass
    started, cpu0 = time.monotonic(), cpu_seconds()
    store_path = Path(args.store)
    if store_path.exists() and not args.resume:
        raise SystemExit(f'{store_path} exists; pass --resume or remove it')
    try:
        store = ks.KnowledgeStore(store_path)
        progress = lambda p: print(json.dumps(p), flush=True)
        if hasattr(ks, 'ensure_knowledge'):
            # this tree: everything through the on-demand entry point
            result = ks.golden_build((bridge, sid), store, limit=args.limit, on_progress=progress)
        else:
            builder = ks.KnowledgeBuilder((bridge, sid), store, chunk_size=args.chunk, on_progress=progress)
            if args.limit:
                builder.tier1()
                result = builder.tier3(max_players=args.limit)
            else:
                result = builder.fill(tiers=(1, 3))
        summary = dict(tree=str(tree), seconds=round(time.monotonic() - started, 1),
                       cpu_seconds=round(cpu_seconds() - cpu0, 1), pages=len(frozen.pages),
                       unreadable_pages=len(frozen.bad), late_pages=frozen.late,
                       load=[round(x, 1) for x in os.getloadavg()], coverage=result)
        print(json.dumps(summary, default=str), flush=True)
        Path(str(store_path) + '.summary.json').write_text(json.dumps(summary, default=str, indent=1))
    finally:
        try:
            bridge.detach()
        finally:
            if not args.replay or frozen.late:
                frozen.dump(args.pages)
            live.close()
    return 0


# Columns that are bookkeeping, not knowledge (wall-clock stamps and how the row was scheduled).
IGNORED = {'knowledge_player': ('computed_at', 'tier')}
TABLES = ('knowledge_player', 'knowledge_attribute', 'knowledge_wide', 'knowledge_universe', 'knowledge_seed',
          'knowledge_fields')


def diff(args):
    a = sqlite3.connect(f'file:{args.a}?mode=ro', uri=True)
    b = sqlite3.connect(f'file:{args.b}?mode=ro', uri=True)
    report, different = {}, 0
    for table in TABLES:
        cols_a = [r[1] for r in a.execute(f'PRAGMA table_info({table})')]
        cols_b = [r[1] for r in b.execute(f'PRAGMA table_info({table})')]
        shared = [c for c in cols_a if c in cols_b and c not in IGNORED.get(table, ())]
        key = [r[1] for r in sorted((r for r in a.execute(f'PRAGMA table_info({table})') if r[5]),
                                    key=lambda r: r[5])] or shared[:1]
        select = f'SELECT {", ".join(chr(34) + c + chr(34) for c in shared)} FROM {table} ' \
                 f'ORDER BY {", ".join(key)}'
        rows_a, rows_b = a.execute(select), b.execute(select)
        n = equal = 0
        examples = []
        index = [shared.index(k) for k in key]
        row_a, row_b = rows_a.fetchone(), rows_b.fetchone()
        only_a = only_b = 0
        while row_a is not None or row_b is not None:
            ka = tuple(row_a[i] for i in index) if row_a is not None else None
            kb = tuple(row_b[i] for i in index) if row_b is not None else None
            if kb is None or (ka is not None and ka < kb):
                only_a += 1
                if len(examples) < 5:
                    examples.append(dict(only_in_a=ka))
                row_a = rows_a.fetchone()
            elif ka is None or kb < ka:
                only_b += 1
                if len(examples) < 5:
                    examples.append(dict(only_in_b=kb))
                row_b = rows_b.fetchone()
            else:
                n += 1
                if row_a == row_b:
                    equal += 1
                elif len(examples) < 5:
                    examples.append(dict(key=ka, differ={c: (x, y) for c, x, y in zip(shared, row_a, row_b)
                                                         if x != y}))
                row_a, row_b = rows_a.fetchone(), rows_b.fetchone()
        report[table] = dict(rows_compared=n, equal=equal, different=n - equal, only_in_a=only_a,
                             only_in_b=only_b, columns=len(shared),
                             columns_only_in_a=[c for c in cols_a if c not in cols_b],
                             columns_only_in_b=[c for c in cols_b if c not in cols_a],
                             ignored=list(IGNORED.get(table, ())), examples=examples)
        different += (n - equal) + only_a + only_b
    print(json.dumps(report, indent=1, default=str))
    return 1 if different else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build')
    b.add_argument('--tree', help='directory holding the fm_live_mcp package to run (default: this checkout)')
    b.add_argument('--store', required=True)
    b.add_argument('--pages', required=True, help='page file to write (or to replay with --replay)')
    b.add_argument('--replay', action='store_true')
    b.add_argument('--resume', action='store_true')
    b.add_argument('--chunk', type=int, default=1000)
    b.add_argument('--limit', type=int, help='stop after this many players beyond the named population')
    d = sub.add_parser('diff')
    d.add_argument('a')
    d.add_argument('b')
    args = ap.parse_args(argv)
    return build(args) if args.cmd == 'build' else diff(args)


if __name__ == '__main__':
    sys.exit(main())
