"""Classify every editor field the getters left without a value and write the route table data.

Usage (FM27 attached, read-only):
    PYTHONPATH=. python scripts/fmdb_field_routes.py --coverage <coverage.json> \
        --census <census.json> [--census ...] [--snapshot <snapshot.sqlite>] [--out fm_live_mcp/fmdb/data/fieldroutes.json.gz]

Inputs: the coverage run (`scripts/fmdb_coverage.py`, 25 records per type), one or more census files
(`--census`: the same pairs asked of 300 to 430 records per type, written by `census()` below with
`--write-census`), and optionally a snapshot whose `unavailable` columns are added to the set.

Static evidence comes from the shipped ARM64 plugin (`fieldroutes.fourcc_sites`,
`fieldroutes.function_starts`, `fieldroutes.call_targets`) and the live vtables (slot pointers read
from the game, never written). See `fm_live_mcp/fmdb/fieldroutes.py` for the categories.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import struct
import sys
import time

from fm_live_mcp.fmdb import fieldroutes, tables, variant

RESEARCH = Path('/Volumes/4TB Private/Offloaded/Agent Work/fmdb-runtime-research')
# game-layer interceptors that sit in front of each live table's getters (vm.INTERCEPTORS)
GAME_LAYER = {'people': ('GAME_PLAYER', 'GAME_PERSON', 'GAME_ACTUAL_NON_PLAYER', 'GAME_ACTUAL_PLAYER',
                         'GAME_HUMAN_NON_PLAYER', 'GAME_RETIRED_PERSON', 'GAME_DB_RECORD'),
              'clubs': ('GAME_CLUB', 'GAME_TEAM_CONTAINER', 'GAME_DB_RECORD'),
              'national_team_containers': ('GAME_NATIONAL_TEAM_CONTAINER', 'GAME_TEAM_CONTAINER', 'GAME_DB_RECORD'),
              'competitions': ('GAME_COMP', 'GAME_DB_RECORD'), 'stadiums': ('GAME_STADIUM', 'GAME_DB_RECORD'),
              'awards': ('GAME_AWARD', 'GAME_DB_RECORD'), 'media_sources': ('GAME_MEDIA_SOURCE', 'GAME_DB_RECORD'),
              'continents': ('GAME_CONTINENT', 'GAME_DB_RECORD')}
# live table of each record class (tables.CLASSES census of 2026-11-11)
TABLE_OF = {**{n: 'people' for n in ('ACTUAL_PLAYER', 'ACTUAL_NON_PLAYER', 'RETIRED_PERSON_NAME_STRINGS',
                                      'RETIRED_PERSON_NAME_POINTERS', 'VIRTUAL_PLAYER', 'SUPPORT_STAFF',
                                      'ACTUAL_PLAYER_AND_NON_PLAYER', 'OFFICIAL', 'JOURNALIST', 'AGENT',
                                      'HUMAN_NON_PLAYER')},
            'CLUB': 'clubs', 'LEAGUE_BODY_CLUB': 'clubs', 'NATIONAL_TEAM_CONTAINER': 'national_team_containers',
            'TEAM': 'teams', 'NATIONAL_TEAM': 'teams', 'COMP': 'competitions', 'CONTINENT': 'continents',
            'PLAYER_TYPE': 'player_types', 'NATION': 'nations', 'STADIUM': 'stadiums', 'STADIUM_CHANGE': 'stadiums',
            'CURRENCY_RECORD': 'currencies', 'INJURY': 'injuries', 'LANGUAGE': 'languages',
            'LOCAL_REGION': 'local_regions', 'WEATHER': 'weather', 'FIXTURE_NAME': 'fixture_names',
            'STAGE_NAME': 'stage_names', 'MEDIA_SOURCE': 'media_sources', 'REGION': 'regions', 'AWARD': 'awards',
            'REMOVED_RECORD': 'removed_records', 'DERBY': 'derbies', 'AGREEMENT': 'agreements', 'CITY': 'cities'}


def vtable_slots(engine, vtables: dict, slots=48) -> dict:
    """{function rva: [(class, slot)]} for every vtable slot that points into the plugin."""
    out = {}
    items = list(vtables.items())
    datas = engine.read_many([(engine.base + v, 8 * slots) for _, v in items])
    for (name, v), data in zip(items, datas):
        if data is None:
            continue
        for s in range(slots):
            p = struct.unpack_from('<Q', data, 8 * s)[0] - engine.base
            if 0 < p < 0x5000000:
                out.setdefault(p, []).append((name, s))
    return out


def census(engine, coverage: dict, types: list, per: int) -> dict:
    """Ask every pair the coverage run left without a value of `per` records per type (plus the
    managed club and squad), with the game-layer fallback."""
    read, base = engine.cached_read, engine.base
    clubs, people = tables.managed(read, base)
    result = {}
    for rtype in types:
        info = coverage['record_types'][rtype]
        keys = [c for c, f in info['per_field'].items() if not f['counts'].get('value')]
        spec = tables.RECORD_TYPES[rtype]
        pointers = tables.entries(read, base, spec.table)
        classes = tables.classify(read, base, pointers) if spec.classes else None
        records = tables.sample(read, base, rtype, per, pointers=pointers, classes=classes)
        if rtype in ('club', 'c2tm', 'c3tm', 'c4tm'):
            records = list(dict.fromkeys(clubs + records))
        if rtype in ('pers', 'play', 'CntF', 'nnpl'):
            records = list(dict.fromkeys(people[:30] + records))
        stats = {}
        for key in keys:
            counts, views, example = Counter(), Counter(), None
            for record in records:
                res = engine.get_property(record, key)
                value = res.value
                if type(value).__name__ == 'Unavailable':
                    counts['unavailable:' + value.reason[:40]] += 1
                elif res.kind == 'null' and res.handled is False:
                    counts['nh'] += 1
                elif res.kind == 'null' or value in (None, '', [], {}):
                    counts['unset'] += 1
                else:
                    counts['value'] += 1
                    views[res.view] += 1
                    if example is None:
                        example = str(variant.to_json(value))[:120]
            stats[key] = {'counts': dict(counts), 'views': dict(views), 'example': example}
        result[rtype] = {'records': len(records), 'keys': stats}
    return result


def outcome(counts: dict) -> str:
    if counts.get('value'):
        return 'value'
    if counts.get('unset'):
        return 'unset'
    if counts.get('not_handled') or counts.get('nh'):
        return 'not_handled'
    return 'unavailable'


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--coverage', required=True)
    ap.add_argument('--census', action='append', default=[])
    ap.add_argument('--write-census', help='run the census and write it here (needs --types)')
    ap.add_argument('--types')
    ap.add_argument('--per-type', type=int, default=300)
    ap.add_argument('--snapshot')
    ap.add_argument('--out', default=str(fieldroutes.DATA))
    args = ap.parse_args(argv)
    from fm_live_mcp.fmdb.engine import Engine
    coverage = json.loads(Path(args.coverage).read_text())
    engine = Engine.open()
    started = time.time()
    try:
        if args.write_census:
            types = args.types.split(',') if args.types else list(coverage['record_types'])
            Path(args.write_census).write_text(json.dumps(census(engine, coverage, types, args.per_type)))
            print(f'census written in {time.time() - started:.0f}s')
            return 0
        image = engine.image
        starts = fieldroutes.function_starts(image)
        sites = fieldroutes.fourcc_sites(image, starts)
        vtables = {n: int(v, 16) for n, v in json.loads((RESEARCH / 'plugin-vtables.json').read_text()).items()}
        slots = vtable_slots(engine, vtables)
        roles = fieldroutes.function_roles(slots)
        closure = fieldroutes.getter_closure(image, starts, roles)
        starting = fieldroutes.starting_table_counts(engine, vtables)
        census_data = {}
        for path in args.census:
            for rtype, info in json.loads(Path(path).read_text()).items():
                census_data.setdefault(rtype, {}).update(info['keys'])
        pairs = {}
        for rtype, info in coverage['record_types'].items():
            for code, f in info['per_field'].items():
                status = outcome(f['counts'])
                if status != 'value':
                    pairs[(rtype, code)] = {'coverage': status, 'name': f['name'], 'type': f['editor_type']}
        if args.snapshot:
            import sqlite3
            conn = sqlite3.connect(f'file:{args.snapshot}?mode=ro', uri=True)
            for table, column, code, rtype, note in conn.execute(
                    "SELECT table_name, column_name, code, record_type, note FROM _fields WHERE status='unavailable'"):
                entry = pairs.setdefault((rtype, code), {'coverage': 'value'})
                entry['snapshot'] = {'table': table, 'column': column, 'note': (note or '')[:160]}
        # the record type's own getter chain: its classes' slot-3 getters plus the game layer
        getters = {}
        for _, (name, getter, _) in tables.CLASSES.items():
            getters.setdefault(name, getter)
        table_classes = {}
        for name in getters:
            table_classes.setdefault(TABLE_OF.get(name, name), set()).add(name)
        own_closures = {}
        for rtype in {rt for rt, _ in pairs}:
            spec = tables.RECORD_TYPES.get(rtype)
            if spec is None:
                continue
            names = spec.classes or tuple(table_classes.get(spec.table, ()))
            roots = {getters[n]: 'getter' for n in names if n in getters}
            layer = GAME_LAYER.get(spec.table, ('GAME_DB_RECORD',))
            game = {fn: 'game' for fn, entries in slots.items()
                    if any(c in layer and s >= 8 for c, s in entries)}
            own_closures[rtype] = fieldroutes.getter_closure(image, starts, roles, depth=2, roots={**game, **roots})
        rows = {}
        for (rtype, code), entry in sorted(pairs.items()):
            evidence = fieldroutes.static_evidence(code, sites, starts, roles, closure, own_closures.get(rtype))
            cen = census_data.get(rtype, {}).get(code)
            row = {**entry, **evidence}
            if cen:
                row['census'] = cen['counts']
                if cen.get('example'):
                    row['census_example'] = cen['example'][:80]
            row['category'], row['reason'] = fieldroutes.categorise(rtype, code, row, starting)
            rows[f'{rtype}.{code}'] = row
        doc = {'format': fieldroutes.FORMAT, 'build': engine.build, 'plugin_sha256': engine.plugin_sha256,
               'starting_tables': starting, 'coverage_records_per_type': 25,
               'census_records': {rt: len(v) for rt, v in census_data.items()}, 'pairs': rows}
        with gzip.open(args.out, 'wt') as fh:
            json.dump(doc, fh, sort_keys=True, separators=(',', ':'))
        counts = Counter((r.get('coverage'), r['category']) for r in rows.values())
        for (cov, cat), n in sorted(counts.items(), key=lambda kv: (str(kv[0][0]), -kv[1])):
            print(f'{cov or "-":12} {cat:24} {n}')
        print(f'{len(rows)} pairs written to {args.out} in {time.time() - started:.0f}s')
        return 0
    finally:
        engine.close()


if __name__ == '__main__':
    sys.exit(main())
