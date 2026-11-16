"""Find every pinned plugin address on a build of the game plugin and write an anchor file.

    PYTHONPATH=. python scripts/fmdb_rebase.py <plugin path> [--live] [--out FILE]
    PYTHONPATH=. python scripts/fmdb_rebase.py <plugin path> --census       # repo-wide pinned-RVA census
    PYTHONPATH=. python scripts/fmdb_rebase.py <pinned plugin> --census --write   # rebuild the address census
    PYTHONPATH=. python scripts/fmdb_rebase.py <plugin path> --all          # = scripts/fm_update_build.py
    PYTHONPATH=. python scripts/fmdb_rebase.py <pinned plugin> --write-reference

The anchors come from RTTI, code shape, an optional live type scan (`--live`: the running game
must have this exact plugin loaded; read-only) and the shipped fingerprint index of the pinned
build (`fm_live_mcp/fmdb/data/anchors-reference-<sha>.json.gz`). The anchor file goes to
`$FMCP_CACHE_DIR/fmdb/anchors/<plugin sha256>.json`, where `fmdb.build` picks it up.
Compared with the pinned values (when the build is the pinned one, every row should match).
"""
from __future__ import annotations

import os
os.environ['FMCP_ADDRESS_BOOK'] = 'off'      # the pinned numbers, never a loaded address map

import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import sys
import time

from fm_live_mcp.fmdb import anchors, platform_model

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('plugin')
    ap.add_argument('--live', action='store_true', help='type-scan the running game (same build only)')
    ap.add_argument('--pid', type=int)
    ap.add_argument('--reference', help='pinned plugin binary (instead of the shipped fingerprint index)')
    ap.add_argument('--out', help='anchor file path (default: the cache anchor directory)')
    ap.add_argument('--census', action='store_true', help='classify every RVA literal in fm_live_mcp/')
    ap.add_argument('--write-reference', action='store_true',
                    help='write the shipped fingerprint index from this (pinned) plugin')
    ap.add_argument('--no-index', action='store_true', help='semantic methods only (no fingerprints)')
    ap.add_argument('--write', action='store_true', help='with --census: rebuild data/address_census.json.gz')
    ap.add_argument('--all', action='store_true', help='the whole update: scripts/fm_update_build.py')
    ap.add_argument('--verbose', '-v', action='store_true')
    args, rest = ap.parse_known_args(argv)
    if args.all:
        import runpy
        passed = [*rest] + (['--live'] if args.live else [])
        for flag, value in (('--out', args.out), ('--reference', args.reference), ('--pid', args.pid)):
            if value is not None:
                passed += [flag, str(value)]
        sys.argv = ['fm_update_build.py', args.plugin, *passed]
        runpy.run_path(str(ROOT / 'scripts/fm_update_build.py'), run_name='__main__')
        return 0
    started = time.time()
    binary = platform_model.load_binary(args.plugin)
    print(f'plugin {binary.path}\n  version {binary.version()} sha256 {binary.sha256}')
    print(f'  {len(binary.rtti)} type_info, {len(binary.vtables)} classes with vtables, '
          f'{len(binary.starts)} functions ({time.time() - started:.1f}s)')
    if args.write_reference:
        return write_reference(binary)
    if args.census:
        return census(binary, args)
    reference = platform_model.load_binary(args.reference) if args.reference else None
    index = None if reference or args.no_index else anchors.load_reference()
    typed = None
    if args.live:
        memory, base = platform_model.open_process(binary, args.pid)
        if memory is None:
            print(f'  live scan skipped: {base}')
        else:
            t = time.time()
            typed = anchors.scan_live_globals(binary, memory.read, base, memory.read_many)
            memory.close()
            print(f'  live scan: {len(typed)} typed globals ({time.time() - t:.1f}s)')
    found = anchors.resolve(binary, reference=reference, index=index, typed=typed)
    from fm_live_mcp import players
    rows = anchors.compare(found, same_build=binary.sha256 == players.SHA256)
    verdicts = Counter(v for v, _a, _p in rows.values())
    by_method = Counter(a.method for v, a, _p in rows.values() if a is not None)
    print(f'  anchors: {len(rows)} pinned; ' + ', '.join(f'{k} {n}' for k, n in sorted(verdicts.items())))
    print('  by method: ' + ', '.join(f'{k} {n}' for k, n in sorted(by_method.items())))
    for name, (verdict, anchor, value) in sorted(rows.items()):
        if verdict not in ('match', 'found') or args.verbose:
            got = anchor.public() if anchor else None
            print(f'    {verdict:10} {name}: pinned {_fmt(value)} found {got}')
    for name, (a, b) in getattr(anchors.resolve, 'conflicts', {}).items():
        print(f'    conflict   {name}: {a.method} {_fmt(a.value)} vs {b.method} {_fmt(b.value)}')
    ui_layer(binary)
    doc = anchors.anchor_document(binary, found, live=typed is not None, rows=rows)
    out = Path(args.out) if args.out else anchors.anchor_dir() / f'{binary.sha256}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1))
    print(f'  wrote {out} ({time.time() - started:.1f}s)')
    return 0


def ui_layer(binary):
    """UI handler layer: handler classes and slots by RTTI, registry function in GameAssembly."""
    registry = json.loads(gzip.decompress((ROOT / 'fm_live_mcp/fmdb/data/ui_registry.json.gz').read_bytes()))
    found, classes, equal, slots = anchors.handler_classes(binary, registry)
    print(f'  UI handler classes by RTTI: {found} of {classes}; slot functions equal to the shipped '
          f'registry: {equal} of {slots}')
    ga = binary.path.parents[4] / 'Frameworks' / 'GameAssembly.dylib'
    if ga.is_file():
        anchor = anchors.registry_function(platform_model.load_binary(ga))
        print(f'  UI key/label registration function: {anchor.public() if anchor else "not found"}')


def _fmt(value):
    if isinstance(value, int):
        return hex(value)
    if isinstance(value, (tuple, list)):
        return '(' + ', '.join(_fmt(v) for v in value) + ')'
    return repr(value)


def write_reference(binary):
    from fm_live_mcp import players
    if binary.sha256 != players.SHA256:
        print('  refusing: the fingerprint index is written from the pinned build only')
        return 2
    want = anchors.pinned()
    literals = anchors.census_literals(ROOT / 'fm_live_mcp', max(s.vmaddr + s.vmsize for s in binary.image.segments))
    extra = {f'literal.{v:#x}': v for v in literals if anchors.classify(binary, v) != 'not-an-address'}
    index = anchors.reference_index(binary, {**want, **extra})
    path = anchors.reference_path(binary.sha256)
    path.write_bytes(gzip.compress(json.dumps(index, separators=(',', ':')).encode(), 9))
    print(f'  wrote {path}: {len(index)} entries, {path.stat().st_size} bytes')
    return 0


def census(binary, args):
    """The address census (fmdb/address_census.py): every in-range integer literal under
    fm_live_mcp/ decided address or coincidence on the pinned build, and how many of the
    addresses resolve on `binary` from the preserved pinned plugin (`--reference`, default the
    builds directory). `--write` rebuilds the shipped census (pinned plugin only)."""
    from fm_live_mcp import players
    from fm_live_mcp.fmdb import address_census, address_map
    pinned_build = binary.sha256 == players.SHA256
    if args.write:
        if not pinned_build:
            print('  refusing: the census is classified on the pinned build only')
            return 2
        doc = address_census.build(binary)
        path = address_census.save(doc)
        address_census._CACHE.clear()
        print(f'  wrote {path} ({path.stat().st_size} bytes); values decided both ways in one file: {doc["mixed"]}')
    doc = address_census.load()
    for g, s in address_census.summary(doc).items():
        print(f'    {g:10} values: {dict(s["values"])}; sites: {dict(s["sites"])}')
        for (d, rule), n in sorted(s['rules'].items()):
            print(f'      {d} {rule:18} {n} sites')
    ref_path = args.reference or ROOT.parent.parent / 'fmdb-runtime-research' / 'builds' / players.VERSION / 'game_plugin'
    ref_path = Path(ref_path)
    if not ref_path.exists():
        ref_path = Path('/Volumes/4TB Private/Offloaded/Agent Work/fmdb-runtime-research/builds') / players.VERSION / 'game_plugin'
    reference = binary if pinned_build else platform_model.load_binary(ref_path)
    res = address_map.derive(binary, reference, doc, strict=pinned_build)
    addr = address_census.addresses(doc)
    table = defaultdict(Counter)
    for v, sites in addr.items():
        for g in {address_census.group_of(rel) for rel, _ in sites}:
            table[g]['total'] += 1
            table[g]['resolved' if res[v].value is not None else 'unresolved'] += 1
    print('  address values resolved on this build' + (' (from scratch: strict)' if pinned_build else ''))
    for g, c in sorted(table.items()):
        print(f'    {g:10} {c["resolved"]} of {c["total"]}')
    return 0


def index_kind(index, value):
    entry = index.get(f'literal.{value:#x}')
    if entry is None:
        return 'not-an-address'
    return 'function' if entry['kind'] == 'code' else 'data-referenced'


if __name__ == '__main__':
    sys.exit(main())
