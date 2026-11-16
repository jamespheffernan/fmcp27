"""Extras census: FourCC keys the record getters claim that are not editor catalog fields.

Usage:
  PYTHONPATH=. python scripts/fmdb_extras.py [--per-type 4] [--types play,nnpl,...]
      [--out fm_live_mcp/fmdb/data/extras.json.gz]

Static step (no game access needed beyond the plugin binary): for every record class
getter in `tables.CLASSES` (and the game-layer interceptor handlers listed in
`vm.INTERCEPTORS`, whose vtables are read live), walk the shipped ARM64 code by
recursive descent and collect every 32-bit constant built with `movz wN,#lo` /
`movk wN,#hi,lsl #16` and then compared with `cmp wA, wN`, where the constant is four
printable ASCII bytes. Direct branches are followed; `bl` calls are followed up to
CALL_DEPTH levels (class getters delegate to their base getters through `bl`/`b`).

Dynamic step (live, read-only): candidates minus every editor catalog code are asked of
`--per-type` sampled records of each editor record type through `PropertyVM`
(database view, which falls back to the game layer for keys the record does not claim).
A key is kept when at least one sampled record returned a decoded non-empty value.
The output feeds `fm_live_mcp/fmdb/extras.py`.
"""
from __future__ import annotations

import argparse
import gzip
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fm_live_mcp.fmdb import tables, vm as vmmod  # noqa: E402

CALL_DEPTH = 3
MAX_INSNS = 2_000_000
# Keys whose sampled value is personal data of the human player (account name): never stored.
REDACT = {'naml'}
SKIP_TYPES = {'pers', 'CntF', 'c2tm', 'c3tm', 'c4tm'}   # views on records another type already covers


def _signed(value, bits):
    return value - (1 << bits) if value >> (bits - 1) else value


def _printable(value):
    raw = value.to_bytes(4, 'big')
    return raw.decode('latin-1') if all(0x20 < c < 0x7F for c in raw) else None


def scan(image, roots, call_depth=CALL_DEPTH, max_insns=MAX_INSNS):
    """{root rva: set(FourCC text)} of keys compared in code reachable from each root."""
    lo, hi = image.text_range
    text = image.file_bytes(lo, hi - lo)
    out = {}
    for root in roots:
        # Breadth by call depth: a getter's own comparison tree is walked completely before
        # any callee, so deep helper calls cannot use up the instruction budget first.
        keys, seen, count = set(), set(), 0
        queues = [[root]] + [[] for _ in range(call_depth)]
        while count < max_insns:
            depth = next((d for d, q in enumerate(queues) if q), None)
            if depth is None:
                break
            pc = queues[depth].pop()
            regs = {}
            while lo <= pc < hi and pc not in seen and count < max_insns:
                seen.add(pc)
                count += 1
                insn, = struct.unpack_from('<I', text, pc - lo)
                nxt = pc + 4
                if insn & 0xFF800000 == 0x52800000:            # movz wd, #imm, lsl #hw*16
                    hw = (insn >> 21) & 3
                    regs[insn & 31] = ((insn >> 5) & 0xFFFF) << (16 * hw)
                elif insn & 0xFF800000 == 0x72800000:          # movk wd, #imm, lsl #hw*16
                    hw, rd = (insn >> 21) & 3, insn & 31
                    if rd in regs:
                        shift = 16 * hw
                        regs[rd] = (regs[rd] & ~(0xFFFF << shift)) | (((insn >> 5) & 0xFFFF) << shift)
                elif insn & 0xFF20001F == 0x6B00001F:          # cmp wn, wm (subs wzr, wn, wm)
                    for reg in ((insn >> 16) & 31, (insn >> 5) & 31):
                        text_key = _printable(regs.get(reg, 0) & 0xFFFFFFFF) if reg in regs else None
                        if text_key:
                            keys.add(text_key)
                elif insn & 0xFC000000 == 0x14000000:          # b
                    pc = pc + 4 * _signed(insn & 0x3FFFFFF, 26)
                    regs = {}
                    continue
                elif insn & 0xFC000000 == 0x94000000:          # bl
                    if depth < call_depth:
                        queues[depth + 1].append(pc + 4 * _signed(insn & 0x3FFFFFF, 26))
                elif insn & 0xFF000010 == 0x54000000 or insn & 0x7E000000 == 0x34000000:  # b.cond / cbz / cbnz
                    queues[depth].append(pc + 4 * _signed((insn >> 5) & 0x7FFFF, 19))
                elif insn & 0x7E000000 == 0x36000000:          # tbz / tbnz
                    queues[depth].append(pc + 4 * _signed((insn >> 5) & 0x3FFF, 14))
                elif insn & 0xFFFFFC1F in (0xD65F0000, 0xD61F0000):   # ret / br
                    break
                pc = nxt
        out[root] = keys
    return out


def interceptor_handlers(vm):
    """Handler RVAs of each game-layer interceptor: every non-trivial slot after the bypass slot."""
    handlers = {}
    for global_rva, rtti, slot, _ in vmmod.INTERCEPTORS:
        app = vm.read_u64(vm.base + global_rva)
        vtable = vm.read_u64(app)
        found = []
        for i in range(slot + 1, slot + 12):
            target = vm.read_u64(vtable + i * 8) - vm.base
            if vm.image.text_range[0] <= target < vm.image.text_range[1]:
                found.append(target)
        handlers[rtti] = found
    return handlers


def describe(value, kind):
    if isinstance(value, (bytes, bytearray)):
        return value[:16].hex()
    text = repr(value)
    return text if len(text) <= 120 else text[:117] + '...'


def empty(value):
    return value is None or value == [] or value == '' or value == {} or value == b''


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--per-type', type=int, default=4)
    ap.add_argument('--types', default='')
    ap.add_argument('--budget', type=int, default=500_000)
    ap.add_argument('--out', default=str(ROOT / 'fm_live_mcp/fmdb/data/extras.json.gz'))
    args = ap.parse_args(argv)
    from fm_live_mcp.fmdb import catalog as catalog_module
    from fm_live_mcp.fmdb.image import PluginImage
    from fm_live_mcp.fmdb.live import open_live
    session = open_live()
    started = time.time()
    try:
        read, base = session.reader.read, session.base
        image = PluginImage.load(session.plugin_path)
        vm = vmmod.PropertyVM(session.reader, base, image, budget=args.budget,
                              file_resolver=session.file_resolver())
        catalog = catalog_module.load_catalog_for_plugin(session.plugin_path)
        catalog_codes = catalog.codes()
        handlers = interceptor_handlers(vm)
        handler_rvas = sorted({h for hs in handlers.values() for h in hs})
        class_getters = {name: getter for _, (name, getter, _) in tables.CLASSES.items()}
        reach = scan(image, sorted(set(class_getters.values()) | set(handler_rvas)))
        game_keys = set().union(*(reach[h] for h in handler_rvas)) if handler_rvas else set()
        wanted = [t for t in (args.types.split(',') if args.types else tables.RECORD_TYPES) if t not in SKIP_TYPES]
        pointer_cache, class_cache = {}, {}
        result = {}
        for rtype in wanted:
            spec = tables.RECORD_TYPES[rtype]
            if spec.table not in pointer_cache:
                pointer_cache[spec.table] = tables.entries(read, base, spec.table)
            if spec.classes and spec.table not in class_cache:
                class_cache[spec.table] = tables.classify(read, base, pointer_cache[spec.table])
            records = tables.sample(read, base, rtype, args.per_type, pointers=pointer_cache[spec.table],
                                    classes=class_cache.get(spec.table))
            classes = sorted({tables.class_of(read, base, r)[0] for r in records})
            candidates = set()
            for name in classes:
                if name in class_getters:
                    candidates |= reach[class_getters[name]]
            candidates |= game_keys if rtype in ('play', 'nnpl', 'offc', 'jour', 'agen') else set()
            candidates -= catalog_codes
            fields, claimed = {}, Counter()
            t0 = time.time()
            for key in sorted(candidates):
                values, kinds, views, reasons = [], Counter(), Counter(), Counter()
                for record in records:
                    res = vm.get_property(record, key)
                    if not res.ok:
                        reasons[res.value.reason] += 1
                        continue
                    if res.handled:
                        claimed[key] += 1
                    if res.handled and not empty(res.value):
                        values.append(res.value)
                        kinds[res.kind] += 1
                        views[getattr(res, 'view', vm.view)] += 1
                if values:
                    fields[key] = {'kind': kinds.most_common(1)[0][0], 'records_with_value': len(values),
                                   'records_sampled': len(records), 'view': views.most_common(1)[0][0],
                                   'sample': ('<redacted: human manager account name>' if key in REDACT
                                              else describe(values[0], kinds.most_common(1)[0][0]))}
                    if reasons:
                        fields[key]['unavailable'] = dict(reasons)
            result[rtype] = {'classes': classes, 'records': len(records), 'candidates': len(candidates),
                             'claimed': len(claimed), 'with_value': len(fields), 'fields': fields,
                             'seconds': round(time.time() - t0, 1)}
            print(f'{rtype:5} classes={classes} candidates={len(candidates)} claimed={len(claimed)} '
                  f'with_value={len(fields)} {time.time() - t0:.0f}s', flush=True)
        meta = {'generated': datetime.now(timezone.utc).isoformat(), 'plugin': session.plugin_path.name,
                'per_type': args.per_type, 'budget': args.budget, 'call_depth': CALL_DEPTH,
                'elapsed_seconds': round(time.time() - started, 1),
                'interceptor_handlers': {k: [hex(h) for h in v] for k, v in handlers.items()},
                'vm_files_read': sorted(Path(f).name for f in vm.files_read)}
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps({'meta': meta, 'types': result}, indent=1, sort_keys=True)
        if args.out.endswith('.gz'):
            with gzip.open(args.out, 'wt') as handle:
                handle.write(text)
        else:
            Path(args.out).write_text(text)
    finally:
        session.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
