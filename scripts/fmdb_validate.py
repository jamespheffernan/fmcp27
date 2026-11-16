"""Compare PropertyVM values with the repo's hand-proven decoders on live records.

Usage: PYTHONPATH=. python scripts/fmdb_validate.py [--per-type 25] [--json out/fmdb-coverage/validate.json]

Ground truth (direct reads, offsets proven elsewhere in this repo):
  CITY      Cnam = string at +0x18, Clat = float32 +0x48, Clon = float32 +0x4C
  CURRENCY  Cnam = string at +0x18, Cexr = float32 +0x38
  COMP      crep = int16 +0x188
  PLAYER    PCAB/PPAB = int16 primary+0x25C/+0x25E, Pfit/Pjad/Pcon = int16 primary+0x250/+0x252/+0x254
            (primary = PERSON entry - 0x388 for ACTUAL_PLAYER)
A VM result is a match only when it equals the direct value exactly (floats bit-exact).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct
import sys

from fm_live_mcp import database, players
from fm_live_mcp.fmdb.live import open_live
from fm_live_mcp.fmdb.image import PluginImage
from fm_live_mcp.fmdb.vm import PropertyVM, Unavailable


def u64(read, a):
    return struct.unpack('<Q', read(a, 8))[0]


def string_at(read, holder):
    pointer = u64(read, holder)
    if not pointer:
        return ''
    length = struct.unpack('<I', read(pointer, 4))[0]
    return read(pointer + 4, length).decode('utf-8', 'replace')


def f32(read, a):
    return struct.unpack('<f', read(a, 4))[0]


def i16(read, a):
    return struct.unpack('<h', read(a, 2))[0]


CHECKS = {
    'cities': {'Cnam': lambda r, x: string_at(r, x + 0x18), 'Clat': lambda r, x: f32(r, x + 0x48),
               'Clon': lambda r, x: f32(r, x + 0x4C)},
    'currencies': {'Cnam': lambda r, x: string_at(r, x + 0x18), 'Cexr': lambda r, x: f32(r, x + 0x38)},
    'competitions': {'crep': lambda r, x: i16(r, x + 0x188)},
    'players': {'PCAB': lambda r, p: i16(r, p - 0x388 + 0x25C), 'PPAB': lambda r, p: i16(r, p - 0x388 + 0x25E),
                'Pfit': lambda r, p: i16(r, p - 0x388 + 0x250), 'Pjad': lambda r, p: i16(r, p - 0x388 + 0x252),
                'Pcon': lambda r, p: i16(r, p - 0x388 + 0x254)},
}


def sample(read, base, kind, count):
    table = database.table(read, base, 'people' if kind == 'players' else kind)
    n = table['count']
    if kind != 'players':
        step = max(1, n // count)
        return [u64(read, table['start'] + i * 8) for i in range(0, n, step)][:count]
    out, want = [], base + players.RVA[2]
    step = max(1, n // (count * 4))
    for i in range(0, n, step):
        person = u64(read, table['start'] + i * 8)
        if person and u64(read, person) == want:
            out.append(person)
            if len(out) == count:
                break
    return out


def same(a, b):
    if isinstance(a, float) and isinstance(b, float):
        return struct.pack('<f', a) == struct.pack('<f', b)
    return a == b


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--per-type', type=int, default=25)
    ap.add_argument('--json')
    args = ap.parse_args(argv)
    session = open_live()
    try:
        image = PluginImage.load(session.plugin_path)
        vm = PropertyVM(session.reader, session.base, image)
        read = session.reader.read
        report = {}
        for kind, checks in CHECKS.items():
            rows = []
            for record in sample(read, session.base, kind, args.per_type):
                for code, truth in checks.items():
                    # The game runs while this reads: a stored value can change between the
                    # direct read and the getter's run (a player's condition during a match).
                    # Compare only when the direct read is the same before and after the getter.
                    for _attempt in range(4):
                        expected = truth(read, record)
                        result = vm.get_property(record, code)
                        stable = same(truth(read, record), expected)
                        if stable:
                            break
                    if isinstance(result.value, Unavailable):
                        status = 'unavailable'
                    elif not stable:
                        status = 'moved'
                    else:
                        status = 'match' if same(result.value, expected) else 'mismatch'
                    if status == 'mismatch' and code == 'Pcon' and result.value == -1:
                        # The game's own rule (docs/fmdb/ORACLE.md, M1): Pcon returns -1 while
                        # the player's injuries leave days still out, and the stored value otherwise.
                        from fm_live_mcp.fmdb import extras
                        days = extras.read_derived(vm, record, 'injury_days_remaining').value
                        if isinstance(days, int) and days > 0:
                            status = 'match'
                    rows.append({'record': hex(record), 'field': code, 'status': status,
                                 'expected': expected, 'vm': repr(result.value), 'kind': result.kind,
                                 'instructions': result.stats.instructions})
            summary = {}
            for row in rows:
                summary.setdefault(row['field'], {}).setdefault(row['status'], 0)
                summary[row['field']][row['status']] += 1
            report[kind] = {'records': len({r['record'] for r in rows}), 'fields': summary,
                            'problems': [r for r in rows if r['status'] != 'match']}
            print(kind, report[kind]['records'], 'records', json.dumps(summary))
            for row in report[kind]['problems'][:10]:
                print('   ', row)
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(json.dumps(report, indent=1, default=str))
        bad = sum(v.get('mismatch', 0) for k in report.values() for v in k['fields'].values())
        return 1 if bad else 0
    finally:
        session.close()


if __name__ == '__main__':
    sys.exit(main())
