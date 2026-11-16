"""Read a game UI handler through UiHandlerVM on the running game and print/save the values.

Examples:
  PYTHONPATH=. python scripts/fmdb_ui_read.py team-confidence --json out.json
  PYTHONPATH=. python scripts/fmdb_ui_read.py team-confidence --club-index 1   # another club
  PYTHONPATH=. python scripts/fmdb_ui_read.py raw --type 114 --record Ttea=0x18000221

Read-only against the game: code runs in this process on copied bytes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fm_live_mcp.fmdb import ui_handlers, ui_registry, variant  # noqa: E402
from fm_live_mcp.fmdb.image import PluginImage  # noqa: E402
from fm_live_mcp.fmdb.live import open_live  # noqa: E402
from fm_live_mcp.fmdb.memory import LiveMemory  # noqa: E402
from fm_live_mcp.fmdb.ui_vm import UiHandlerVM, lsof_resolver  # noqa: E402


def open_vm(rng='copy'):
    session = open_live()
    image = PluginImage.load(session.plugin_path)
    memory = LiveMemory(session.pid)
    vm = UiHandlerVM(memory, session.base, image, file_resolver=lsof_resolver(session.pid), rng=rng)
    vm.fast()
    return session, memory, vm


def managed_team(session):
    from fm_live_mcp import world
    record, _ = world.loaded(world.ReadSet(session.reader.read), session.base)
    return record['coaches'][0]['team_address']


def other_team(session, vm, index):
    """First team of another club in the managed team's league table order (by club list)."""
    from fm_live_mcp.fmdb import tables
    read = session.reader.read
    clubs = [p for p in tables.entries(read, session.base, 'clubs') if p]
    seen = 0
    for club in clubs:
        if vm.class_name(club) != 'CLUB':
            continue
        begin, end = struct.unpack('<QQ', read(club + 0x18, 16))
        if begin == end:
            continue
        team = struct.unpack('<Q', read(begin, 8))[0]
        if team == managed_team(session):
            continue
        seen += 1
        if seen == index:
            return team
    raise SystemExit('no such club')


def report(reading, plain=True):
    rows = []
    for r in reading.readings:
        value = variant.to_json(r.value)
        if plain:
            value = ui_handlers.plain_text(value)
        rows.append({'key': r.code, 'label': r.label, 'kind': r.kind, 'value': value,
                     'ms': round(r.seconds * 1000, 1)})
    return {'handler_type': reading.handler_type, 'client': reading.client_class,
            'server': reading.server_class, 'record': reading.record, 'inputs': reading.inputs,
            'build_seconds': round(reading.build_seconds, 3),
            'input_seconds': round(reading.input_seconds, 2), 'files_read': list(reading.files_read),
            'summary': reading.summary(), 'readings': rows}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('what', choices=('team-confidence', 'raw'))
    ap.add_argument('--club-index', type=int, default=0, help='0 = managed club, n = nth other club')
    ap.add_argument('--type', type=int)
    ap.add_argument('--record', action='append', default=[], help='KEY=u32 (repeatable)')
    ap.add_argument('--keys', help='comma-separated FourCCs (default: all slot-4 keys)')
    ap.add_argument('--inputs', help='comma-separated input keys (default: declared/consumed)')
    ap.add_argument('--rng', choices=('copy', 'refuse'), default='copy')
    ap.add_argument('--json')
    ap.add_argument('--raw-text', action='store_true', help='keep link markup in strings')
    args = ap.parse_args(argv)
    session, memory, vm = open_vm(args.rng)
    try:
        keys = args.keys.split(',') if args.keys else None
        started = time.perf_counter()
        if args.what == 'team-confidence':
            team = managed_team(session) if not args.club_index else other_team(session, vm, args.club_index)
            reading = ui_handlers.team_confidence(vm, team, keys=keys)
        else:
            record = {}
            for item in args.record:
                k, v = item.split('=', 1)
                record[k] = int(v, 0)
            inputs = args.inputs.split(',') if args.inputs is not None else None
            reading = ui_handlers.read_handler(vm, args.type, record, keys=keys,
                                               inputs=[i for i in (inputs or []) if i] if inputs is not None else None)
        out = report(reading, plain=not args.raw_text)
        out['seconds'] = round(time.perf_counter() - started, 1)
        out['rng_uses'] = vm.rng_uses
        reg = ui_registry.default()
        out['registry_build'] = reg.build
        text = json.dumps(out, indent=1, ensure_ascii=False, default=str)
        if args.json:
            Path(args.json).write_text(text)
        print(json.dumps({k: out[k] for k in ('client', 'record', 'inputs', 'summary', 'seconds', 'rng_uses')},
                         default=str))
        if not args.json:
            print(text)
    finally:
        memory.close()
        session.close()


if __name__ == '__main__':
    main()
