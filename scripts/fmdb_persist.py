#!/usr/bin/env python3
"""Run the game's own save code for every save route and write the persisted-class schema.

    PYTHONPATH=. python scripts/fmdb_persist.py [--only ROOT ...] [--prov-budget N] [--out PATH]

For each route of `fm_live_mcp/fmdb/data/persist_routes.json`: one fast run (FastVM, no load
tracking) over the whole save function gives the field lists, repetition counts and element
classes; a second run with load provenance, stopped after `--prov-budget` instructions, gives the
object offsets of the fields it reached (the first instances of every container). Offsets are
merged by field key (save function, write site, helpers, width). Writes
`fm_live_mcp/fmdb/data/persist_schema.json.gz` and prints one line per route.

Read-only against the game: the save runs inside the VM (docs/fmdb/PERSIST.md).
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fm_live_mcp.fmdb import persist  # noqa: E402
from fm_live_mcp.fmdb.engine import Engine  # noqa: E402


def build(engine, route, prov_budget):
    t = time.perf_counter()
    fast = persist.record(engine, route, provenance=False, use_cache=False)
    an = persist.Analysis(engine, fast)
    schema = persist._schema_of(an, fast, route)
    fast_s = time.perf_counter() - t
    prov_s, prov_status = None, None
    if prov_budget:
        t = time.perf_counter()
        vm = persist._vm(engine, True)
        saved = vm.budget
        vm.budget = prov_budget
        try:
            prov = persist.record(engine, route, provenance=True, use_cache=False)
        finally:
            vm.budget = saved
        prov_status = prov.refusal or prov.status
        anp = persist.Analysis(engine, prov)
        merged = 0
        for f in schema['functions']:
            fn = int(f['function'], 16)
            if fn not in anp.fields:
                continue
            for field in f['fields']:
                key = persist.key_of(field)
                if key is None or key not in anp.fields[fn]:
                    continue
                where, how = anp.offset(fn, key)
                if where is not None and (field.get('offset') is None or field.get('offset_source') == 'value (one instance)'):
                    field['offset'], field['offset_source'] = persist._fmt_offset(where), how
                    merged += 1
                elif field.get('offset') is None and how and not field.get('offset_source'):
                    field['offset_source'] = how
        prov_s = time.perf_counter() - t
        schema['provenance'] = {'budget': prov_budget, 'status': prov_status, 'seconds': round(prov_s, 2),
                                'writes': len(prov.writes), 'offsets_merged': merged}
    schema['fast_seconds'] = round(fast_s, 2)
    return schema


def markdown(doc) -> str:
    """Per-root census table and per-class field lists for docs/fmdb/PERSIST.md."""
    lines = [f"Census: game date {doc.get('game_date')}, build {doc.get('build')}, {doc.get('built_at')}, "
             f"{doc.get('seconds')} s, load average {', '.join(f'{x:.1f}' for x in doc.get('load', []))}.", '',
             '| Root | Status | Writes | Bytes | Save functions | Objects (classes) | Value fields (with offset) | Fast s | Refusal |',
             '|---|---|---|---|---|---|---|---|---|']
    classes = {}
    for r in doc['roots']:
        fns = r.get('functions', [])
        nval = sum(1 for f in fns for x in f['fields'] if x['kind'] == 'value')
        noff = sum(1 for f in fns for x in f['fields'] if x['kind'] == 'value' and x.get('offset'))
        objs = sum(f['instances'] for f in fns)
        ncls = len({f['class'] for f in fns if f.get('class')})
        lines.append(f"| {r['root']} | {r.get('status')} | {r.get('writes') or 0:,} | {r.get('bytes') or 0:,} | {len(fns)} | "
                     f"{objs:,} ({ncls}) | {nval:,} ({noff:,}) | {r.get('fast_seconds')} | {(r.get('refusal') or '')[:140]} |")
        for f in fns:
            if f.get('class'):
                classes.setdefault(f['class'], []).append((r['root'], f))
    lines += ['', f'{len(classes)} classes have objects written by a save function:', '',
              '| Class | Root | Save function | Objects | Value fields | Offsets proven | Labelled |', '|---|---|---|---|---|---|---|']
    for cls in sorted(classes):
        for root, f in classes[cls]:
            vals = [x for x in f['fields'] if x['kind'] == 'value']
            lines.append(f"| {cls} | {root} | {f['function']} | {f['instances']:,} | {len(vals)} | "
                         f"{sum(1 for x in vals if x.get('offset'))} | {sum(1 for x in vals if x.get('label_source'))} |")
    return '\n'.join(lines) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--markdown', help='write the census tables (from the schema file) to this path and exit')
    ap.add_argument('--relabel', action='store_true',
                    help='apply persist.DECODER_LABELS to the schema file (no game needed) and exit')
    ap.add_argument('--only', nargs='*')
    ap.add_argument('--prov-budget', type=int, default=20_000_000)
    ap.add_argument('--out', default=str(persist.SCHEMA_FILE))
    args = ap.parse_args()
    if args.relabel:
        doc = json.loads(gzip.decompress(Path(args.out).read_bytes()))
        n = 0
        for r in doc['roots']:
            for f in r.get('functions', []):
                short = (f.get('class') or '').split('::')[-1]
                for x in f['fields']:
                    hit = persist.DECODER_LABELS.get((short, x.get('offset')))
                    if hit is None and short.endswith('_NEWS'):
                        hit = persist.NEWS_LABELS.get(x.get('offset'))
                    if x['kind'] == 'value' and hit and not x.get('label_source'):
                        x['name'], x['label_source'] = hit[0], f'decoder:{hit[1]}'
                        n += 1
        Path(args.out).write_bytes(gzip.compress(json.dumps(doc, default=str, separators=(',', ':')).encode(), 9))
        print(f'relabelled {n} fields')
        return
    if args.markdown:
        doc = json.loads(gzip.decompress(Path(args.out).read_bytes()))
        Path(args.markdown).write_text(markdown(doc))
        print(f'wrote {args.markdown}')
        return
    engine = Engine.open()
    roots, started = [], time.perf_counter()
    previous = {}
    if args.only and Path(args.out).is_file():
        previous = {r['root']: r for r in json.loads(gzip.decompress(Path(args.out).read_bytes()))['roots']}
    for route in persist.routes():
        if args.only and route['key'] not in args.only and route['root'] not in args.only:
            if route['key'] in previous:
                roots.append(previous[route['key']])
            continue
        try:
            s = build(engine, route, args.prov_budget)
        except Exception as exc:  # noqa: BLE001 - one root never stops the census
            s = {'root': route['key'], 'status': 'error', 'refusal': f'{type(exc).__name__}: {exc}', 'functions': []}
        roots.append(s)
        nval = sum(1 for f in s['functions'] for x in f['fields'] if x['kind'] == 'value')
        noff = sum(1 for f in s['functions'] for x in f['fields'] if x['kind'] == 'value' and x.get('offset'))
        print(f"{s['root']}: {s['status']} {s.get('refusal') or ''} writes={s.get('writes')} bytes={s.get('bytes')} "
              f"functions={len(s['functions'])} value_fields={nval} with_offset={noff} "
              f"fast={s.get('fast_seconds')}s prov={s.get('provenance', {}).get('seconds')}s", flush=True)
    doc = {'build': engine.build, 'game_date': engine.game_date(), 'built_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
           'seconds': round(time.perf_counter() - started, 1), 'load': os.getloadavg(), 'roots': roots}
    Path(args.out).write_bytes(gzip.compress(json.dumps(doc, default=str, separators=(',', ':')).encode(), 9))
    print(f'wrote {args.out} ({Path(args.out).stat().st_size} bytes) in {doc["seconds"]}s')
    engine.close()


if __name__ == '__main__':
    main()
