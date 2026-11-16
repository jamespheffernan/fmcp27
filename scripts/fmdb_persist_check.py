#!/usr/bin/env python3
"""Check the emulated save against the hand-built decoders: the same stored value at the same offset.

    PYTHONPATH=. python scripts/fmdb_persist_check.py [--budget N] [--roots ROOT ...]

For every object the save wrote whose class a hand-built decoder reads (DECODERS below, each entry
naming the module whose code reads it), and for each decoder offset:

* scalar: agree when a write of that object's save function came from exactly that address
  (`buffer` or `load` provenance) and the written bytes equal the live bytes there; `value-only` when
  the written bytes equal the live bytes but the provenance names another address or none; `not
  written` when no write of the object has those bytes at all;
* pointer: agree when a write of the object (or of a save function it called) came from inside the
  pointed-to object (the save stores a reference, e.g. the record's unique id at +8);
  `not written` otherwise.

Prints one line per (class, offset) with counts, and the disagreements. Read-only (docs/fmdb/PERSIST.md).
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fm_live_mcp.fmdb import persist  # noqa: E402
from fm_live_mcp.fmdb.engine import Engine  # noqa: E402

OFFERS = ('DRAFT_OFFER', 'ENQUIRY_OFFER', 'TRANSFER_OFFER', 'FULL_TRANSFER_OFFER', 'LOAN_OFFER', 'TRIAL_OFFER',
          'TRADE_OFFER', 'B_CLUB_MOVE_OFFER')
# class -> [(offset, width or 'ptr', label, decoder module)]
DECODERS = {
    **{c: [(0x38, 'ptr', 'person', 'live_transfer_offers'), (0x40, 'ptr', 'team 1', 'live_transfer_offers'),
           (0x48, 'ptr', 'team 2', 'live_transfer_offers'), (0x50, 'ptr', 'team 3', 'live_transfer_offers'),
           (0x58, 4, 'amount', 'live_transfer_offers'), (0x8D, 1, 'state', 'live_transfer_offers'),
           (0x70, 4, 'date 1', 'live_transfer_offers'), (0x74, 4, 'date 2', 'live_transfer_offers'),
           (0x78, 4, 'date 3', 'live_transfer_offers'), (0x7C, 4, 'date 4', 'live_transfer_offers')]
       for c in OFFERS},
    **{c: [(0x8, 'ptr', 'person (owner)', 'contracts'), (0x10, 'ptr', 'team', 'contracts'),
           (0x18, 'ptr', 'team 2', 'contracts')]
       for c in ('FULL_CONTRACT', 'BASIC_CONTRACT', 'LOAN_CONTRACT', 'TRIAL_CONTRACT')},
    'CLUB_FINANCE': [(0x814, 4, 'spending (wage) store', 'club_finance')],
}
NEWS = [(0x90, 4, 'unique id', 'live_state.news_item'), (0x98, 1, 'flags (bit 0)', 'live_state.news_item'),
        (0x88, 4, 'packed date', 'live_state.news_item')]
INJURY_ENTRY = [(0x8, 'ptr', 'INJURY definition', 'player_health'), (0x20, 4, 'start date', 'player_health')]
DEFAULT_ROOTS = ('TRANSFER_MANAGER+0x18', 'NEWS_MANAGER', 'INJURY_MANAGER', 'CONTRACT_MANAGER', 'FINANCE_MANAGER',
                 'GAME_RULE_GROUP_MANAGER')


def short(cls):
    return (cls or '').split('::')[-1]


def check(engine, rec, vm, results, examples):
    an = persist.Analysis(engine, rec)
    # every write's source address, per call and per call subtree
    by_call = defaultdict(list)
    for w in rec.writes:
        if w.call is None:
            continue
        src = None
        if persist.NULL_LIMIT <= w.buffer < persist.PRIVATE:
            src = w.buffer
        else:
            loads = [p for p in w.parts if p[2] == 'load' and p[0] == 0]
            if loads:
                src = loads[0][3]
        by_call[w.call].append((src, w.data))
    children = defaultdict(list)
    for c in rec.calls:
        if c.parent is not None:
            children[c.parent].append(c.id)

    def subtree(cid, depth=3):
        out = list(by_call.get(cid, ()))
        if depth:
            for k in children.get(cid, ()):
                out += subtree(k, depth - 1)
        return out

    news_items = set()
    if rec.key.startswith('NEWS_MANAGER'):
        news_items = {c.id for c in rec.calls if c.parent == 0 or (c.parent is not None and rec.calls[c.parent].parent == 0)}
    # one object can be written by several save functions (base class, then derived): judge per object
    objects = defaultdict(list)
    for c in rec.calls:
        objects[c.obj].append(c)
    done = set()
    for c in rec.calls:
        if c.obj in done:
            continue
        cls = short(rec.classes.get(c.id))
        specs = DECODERS.get(cls)
        if specs is None and c.id in news_items and cls.endswith('NEWS'):
            specs, cls = NEWS, cls + ' (news item)'
        if specs is None:
            continue
        done.add(c.obj)
        own, tree = [], []
        for k in objects[c.obj]:
            own += by_call.get(k.id, [])
            tree += subtree(k.id)
        for off, width, label, module in specs:
            key = (cls, off, label, module)
            addr = c.obj + off
            if width == 'ptr':
                p = vm.read_u64(addr)
                if not p:
                    results[key]['null pointer'] += 1
                    continue
                hit = [s for s, _ in tree if s is not None and 0 <= s - p < 0x400]
                if hit:
                    results[key]['agree'] += 1
                    examples[key].add(f'pointee+{hit[0] - p:#x}')
                else:
                    direct = [s for s, _ in own if s == addr]
                    results[key]['pointer itself written' if direct else 'not written'] += 1
                continue
            live = vm.read(addr, width)
            parts = [(s, d) for s, d in own if s is not None and addr <= s < addr + width]
            covered = set()
            bad = False
            for s, d in parts:
                piece = vm.read(s, len(d))
                if piece != d:
                    bad = True
                    examples[key].add(f'{d.hex()} != {piece.hex()} at {s:#x}')
                covered |= set(range(s - addr, min(s - addr + len(d), width)))
            if parts and not bad and covered >= set(range(width)):
                results[key]['agree' if len(parts) == 1 else f'agree in {len(parts)} writes'] += 1
                if len(parts) > 1:
                    examples[key].add('split: ' + '+'.join(f'{len(d)}B@{s - addr:#x}' for s, d in sorted(parts)))
            elif parts and not bad:
                results[key]['partly written'] += 1
            elif bad:
                results[key]['DISAGREE'] += 1
            elif any(d == live for _, d in own) and any(live):
                results[key]['value-only'] += 1
            else:
                results[key]['not written'] += 1
    return an


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--roots', nargs='*', default=list(DEFAULT_ROOTS))
    ap.add_argument('--budget', type=int, default=60_000_000)
    args = ap.parse_args()
    engine = Engine.open()
    vm = persist._vm(engine, True)
    vm.budget = args.budget
    results, examples = defaultdict(Counter), defaultdict(set)
    for root in args.roots:
        t = time.perf_counter()
        rec = persist.record(engine, persist.find_route(root), provenance=True, use_cache=False)
        check(engine, rec, vm, results, examples)
        print(f'{root}: {rec.status} {rec.refusal or ""} writes={len(rec.writes)} objects={len(rec.calls)} '
              f'{time.perf_counter() - t:.1f}s', flush=True)
    for key in sorted(results, key=lambda k: (k[0], k[1])):
        cls, off, label, module = key
        counts = {k: v for k, v in results[key].items() if v}
        print(f'{cls} +{off:#x} {label} [{module}]: {counts} {sorted(examples[key])[:3]}')
    engine.close()


if __name__ == '__main__':
    main()
