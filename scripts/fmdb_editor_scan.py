"""Targeted full scan of the editor fields the 25-record census left without a value.

For every editor (record type, field) pair the ledger does not count as `reads` (and every list-item field
whose parent list did not read), ask the record getter (with the game-layer fallback, as
`Engine.get_property` does) of EVERY record of the type, the managed club and squad first, until the
field has given `--stop` values. A field set on some record becomes readable with an example record; a
field unset on every record of the save is "empty in this save" (ledger status `empty_in_save`), which is a different
statement from "not reached". A scan cut short by `--budget` says how many records it asked.

Usage (game running, read-only):

    PYTHONPATH=. FMCP_NO_BACKGROUND_FILL=1 FMCP_CACHE_DIR=... python scripts/fmdb_editor_scan.py \
        --types natc,comp --out out/editor-scan            # one JSON per type in <out>/
    PYTHONPATH=. python scripts/fmdb_editor_scan.py --merge out/editor-scan   # -> fm_live_mcp/fmdb/data/editor_live.json.gz

Targets come from the ledger (`fm_live_mcp/fmdb/data/ledger.json.gz`) unless `--codes` names them
(`club.CBWo,club.Cstc.Styp`). Nothing is written to the game; every getter call runs in the emulator.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import json
import os
from pathlib import Path
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fm_live_mcp.fmdb import editor_live, fieldroutes, tables, variant  # noqa: E402

EMPTY_VALUES = (None, '', [], {})


def targets_from_ledger(path=None) -> dict:
    """{record type: {'top': {code}, 'items': {parent: {code}}}} for every editor row that does not read."""
    from fm_live_mcp.fmdb import ledger
    led = ledger.load(Path(path) if path else ledger.CURRENT)
    cols = led['columns']
    ki, si = cols.index('key'), cols.index('status')
    out = defaultdict(lambda: {'top': set(), 'items': defaultdict(set)})
    for row in led['rows']:
        if row[0] != 'editor' or row[si] == 'reads':
            continue
        parts = row[ki].split('.')
        rtype = parts[0]
        if rtype not in tables.RECORD_TYPES:
            continue
        if len(parts) == 2:
            out[rtype]['top'].add(parts[1])
        elif len(parts) == 3:
            out[rtype]['items'][parts[1]].add(parts[2])
    return out


def targets_from_codes(text: str) -> dict:
    out = defaultdict(lambda: {'top': set(), 'items': defaultdict(set)})
    for item in filter(None, text.split(',')):
        parts = item.split('.')
        if len(parts) == 2:
            out[parts[0]]['top'].add(parts[1])
        else:
            out[parts[0]]['items'][parts[1]].add(parts[2])
    return out


def records_of(engine, rtype, managed):
    read, base = engine.cached_read, engine.base
    spec = tables.RECORD_TYPES[rtype]
    pointers = [p for p in tables.entries(read, base, spec.table) if p]
    index = {p: i for i, p in enumerate(tables.entries(read, base, spec.table)) if p}
    if spec.classes:
        classes = tables.classify(read, base, pointers)
        pointers = [p for p in pointers if classes.get(p) in spec.classes]
    clubs, people = managed
    first = clubs if spec.table == 'clubs' else people if spec.table == 'people' else []
    wanted = set(pointers)
    ordered = list(dict.fromkeys([p for p in first if p in wanted] + pointers))
    return ordered, index


def _outcome(res):
    value = res.value
    if type(value).__name__ == 'Unavailable':
        return 'unavailable', value.reason[:60], None
    if res.kind == 'null' and res.handled is False:
        return 'nh', None, None
    if res.kind == 'null' or value in EMPTY_VALUES:
        return 'unset', None, None
    return 'value', None, value


def _ident(engine, record, index):
    try:
        uid = struct.unpack('<I', engine.cached_read(record + 0xC, 4))[0]
    except Exception:  # noqa: BLE001
        uid = None
    return {'index': index.get(record), 'unique_id': uid}


def scan_type(engine, rtype, top, items, *, stop=3, budget=600.0, log=print):
    """Scan one record type; returns the per-pair result dict (see editor_scan.load)."""
    managed = tables.managed(engine.cached_read, engine.base)
    records, index = records_of(engine, rtype, managed)
    total = len(records)
    top = set(top) | set(items)            # a list parent is asked as a field too
    stats = {c: {'counts': Counter(), 'examples': [], 'asked': 0} for c in top}
    istats = {(p, c): {'counts': Counter(), 'examples': [], 'lists': 0}
              for p, codes in items.items() for c in codes}
    active = set(top)
    iactive = set(istats)
    started = time.process_time()
    wall = time.time()
    n = 0
    for n, record in enumerate(records, 1):
        if not active:
            break
        for code in list(active):
            st = stats[code]
            st['asked'] += 1
            try:
                # a field routed to another key (fieldroutes.ROUTES alias) is asked through its route
                res = engine.get_property(record, fieldroutes.alias(rtype, code) or code)
                kind, why, value = _outcome(res)
            except Exception as exc:  # noqa: BLE001 - an emulator failure is a result, not a stop
                kind, why, value = 'unavailable', f'{type(exc).__name__}: {exc}'[:60], None
            st['counts'][kind if kind != 'unavailable' else f'unavailable:{why}'] += 1
            if kind == 'value':
                js = variant.to_json(value)
                if len(st['examples']) < stop:
                    st['examples'].append({**_ident(engine, record, index), 'value': str(js)[:160]})
                if code in items and isinstance(js, list):
                    for (p, c) in list(iactive):
                        if p != code:
                            continue
                        ist = istats[(p, c)]
                        ist['lists'] += 1
                        hit = None
                        for item in js:
                            if isinstance(item, dict):
                                v = item.get(c)
                                ist['counts']['value' if v not in EMPTY_VALUES else 'unset'] += 1
                                if v not in EMPTY_VALUES and hit is None:
                                    hit = v
                        if hit is not None and len(ist['examples']) < stop:
                            ist['examples'].append({**_ident(engine, record, index), 'value': str(hit)[:160]})
                        if len(ist['examples']) >= stop:
                            iactive.discard((p, c))
                if len(st['examples']) >= stop and not any(p == code for p, _ in iactive):
                    active.discard(code)
        if time.process_time() - started > budget:
            break
        if n % 5000 == 0:
            log(f'  {rtype} {n}/{total} active {len(active)} items {len(iactive)} '
                f'cpu {time.process_time() - started:.0f}s load {os.getloadavg()[0]:.1f}', flush=True)
    cpu = time.process_time() - started
    complete = n >= total
    out = {'records': total, 'scanned': n, 'complete': complete, 'cpu_s': round(cpu, 1),
           'wall_s': round(time.time() - wall, 1), 'load': [round(x, 1) for x in os.getloadavg()], 'pairs': {}}
    for code, st in stats.items():
        out['pairs'][f'{rtype}.{code}'] = {'asked': st['asked'], 'of': total, 'counts': dict(st['counts']),
                                          'examples': st['examples'], 'complete': st['asked'] >= total}
    for (p, c), ist in istats.items():
        parent = stats[p]
        out['pairs'][f'{rtype}.{p}.{c}'] = {'asked': parent['asked'], 'of': total, 'lists': ist['lists'],
                                           'counts': dict(ist['counts']), 'examples': ist['examples'],
                                           'complete': parent['asked'] >= total,
                                           'parent_counts': dict(parent['counts'])}
    return out


def embedded(engine, *, stop=3, clubs_limit=3000, stadiums_limit=26000):
    """Editor types that are not table records, checked against the live data that holds them
    (`editor_live.EMBEDDED`): recs/lsts (the live tables), ktfl (kit items of the colours lists),
    stadium stand flags (stadium sides Ssds)."""
    read, base = engine.cached_read, engine.base
    started = time.process_time()
    out = {'pairs': {}}
    for name, table in editor_live.RECS_TABLES.items():
        ptrs = [p for p in tables.entries(read, base, table) if p]
        ex = [_ident(engine, p, {p: i for i, p in enumerate(ptrs[:1])}) for p in ptrs[:1]]
        out['pairs'][f'recs.database_record#{name}'] = {'asked': len(ptrs), 'of': len(ptrs), 'complete': True,
                                                         'counts': {'value': len(ptrs)}, 'examples': ex,
                                                         'table': table}
    for code, table in editor_live.LSTS_TABLES.items():
        n = sum(1 for p in tables.entries(read, base, table) if p)
        out['pairs'][f'lsts.{code}'] = {'asked': 1, 'of': 1, 'complete': True, 'counts': {'value': 1},
                                        'examples': [{'index': None, 'unique_id': None, 'value': f'{n} records'}],
                                        'table': table}
    # kit records: items of the colours/kits lists of clubs and national teams
    codes = editor_live.KIT_CODES
    stats = {c: {'value': 0, 'unset': 0} for c in codes}
    examples = {c: [] for c in codes}
    asked = 0
    for rtype, parents in editor_live.KIT_LISTS.items():
        records, index = records_of(engine, rtype, tables.managed(read, base))
        for record in records[:clubs_limit]:
            asked += 1
            for parent in parents:
                res = engine.get_property(record, parent)
                kind, _, value = _outcome(res)
                if kind != 'value':
                    continue
                for item in variant.to_json(value):
                    if not isinstance(item, dict):
                        continue
                    for c in codes:
                        v = item.get(c)
                        stats[c]['value' if v not in EMPTY_VALUES else 'unset'] += 1
                        if v not in EMPTY_VALUES and len(examples[c]) < stop:
                            examples[c].append({**_ident(engine, record, index), 'value': f'{rtype}.{parent}: {v}'[:160]})
            if all(len(v) >= stop for v in examples.values()):
                break
    for c in codes:
        out['pairs'][f'ktfl.{c}'] = {'asked': asked, 'of': None, 'complete': False, 'counts': stats[c],
                                     'examples': examples[c], 'via': 'club/natc colours lists'}
    # stadium stand flags: the side item of Ssds with indx == side
    sides = {v: k for k, v in editor_live.STAND_KEYS.items()}
    sstats = {k: Counter() for k in editor_live.STAND_KEYS}
    sexamples = {k: [] for k in editor_live.STAND_KEYS}
    records, index = records_of(engine, 'stad', ([], []))
    n = 0
    for n, record in enumerate(records[:stadiums_limit], 1):
        kind, _, value = _outcome(engine.get_property(record, 'Ssds'))
        if kind != 'value':
            continue
        for item in variant.to_json(value):
            if isinstance(item, dict) and item.get('indx') in sides:
                key = sides[item['indx']]
                exis = item.get('exis')
                sstats[key]['value'] += 1
                sstats[key]['true' if exis else 'false'] += 1
                if len(sexamples[key]) < stop and exis:
                    sexamples[key].append({**_ident(engine, record, index), 'value': f'Ssds side {item["indx"]} exis {exis}'})
    for key in editor_live.STAND_KEYS:
        out['pairs'][f'stad.{key}'] = {'asked': n, 'of': len(records), 'complete': n >= len(records),
                                       'counts': dict(sstats[key]), 'examples': sexamples[key], 'via': 'stad.Ssds'}
    out.update(records=None, scanned=None, complete=True, cpu_s=round(time.process_time() - started, 1),
               wall_s=None, load=[round(x, 1) for x in os.getloadavg()])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--embedded', action='store_true', help='check recs/lsts/ktfl/stand flags (embedded.json)')
    ap.add_argument('--types', default='')
    ap.add_argument('--codes', default='')
    ap.add_argument('--ledger')
    ap.add_argument('--out', default=str(ROOT / 'out' / 'editor-scan'))
    ap.add_argument('--stop', type=int, default=3)
    ap.add_argument('--budget', type=float, default=900.0, help='CPU seconds per record type')
    ap.add_argument('--merge', help='merge <dir>/*.json into the shipped data file and exit')
    args = ap.parse_args(argv)
    if args.merge:
        path = editor_live.merge(Path(args.merge))
        print('wrote', path, editor_live.summary(editor_live.load(path)))
        return
    targets = targets_from_codes(args.codes) if args.codes else targets_from_ledger(args.ledger)
    types = [t for t in (args.types.split(',') if args.types else targets) if t in targets]
    from fm_live_mcp.fmdb.engine import Engine
    engine = Engine.open()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        meta = {'build': engine.build, 'game_date': engine.game_date()}
        if args.embedded:
            res = embedded(engine, stop=args.stop)
            res.update(meta)
            res['scanned_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
            (out / 'embedded.json').write_text(json.dumps(res))
            print('embedded', json.dumps({k: v['counts'] for k, v in res['pairs'].items()})[:3000])
            return
        for rtype in types:
            t = targets[rtype]
            print(f'{time.strftime("%H:%M:%S")} {rtype}: {len(t["top"])} fields, '
                  f'{sum(len(v) for v in t["items"].values())} items of {len(t["items"])} lists', flush=True)
            res = scan_type(engine, rtype, t['top'], t['items'], stop=args.stop, budget=args.budget)
            res.update(meta)
            res['scanned_at'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
            (out / f'{rtype}.json').write_text(json.dumps(res))
            vals = sum(1 for v in res['pairs'].values() if v['counts'].get('value'))
            print(f'  {rtype}: {res["scanned"]}/{res["records"]} records, {res["cpu_s"]} CPU-s, '
                  f'{vals}/{len(res["pairs"])} pairs with a value, load {res["load"]}', flush=True)
    finally:
        engine.close()


if __name__ == '__main__':
    main()
