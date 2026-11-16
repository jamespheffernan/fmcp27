"""Direct read plans compiled from the plugin file alone (no game), and their diff between builds.

    PYTHONPATH=. python scripts/fmdb_static_plans.py --plugin <game_plugin> [--map <addresses.json>] --out A.json
    PYTHONPATH=. python scripts/fmdb_static_plans.py --compare OLD.json NEW.json

plancompile.py runs each record class's getter on a synthetic record. Live, every other read
comes from the game; here it comes from the plugin file: rebased pointers point into the image
(loaded at a fixed base), every import has its own address so the VM models it by name, every
game-layer interceptor object (vm.INTERCEPTORS) is a stand-in whose vtable is its class's shipped
vtable (so the database view bypasses each), and the sicore typed-traits registry is built by
running the registry's own lazy constructor in the VM first. Anything else outside the image is
unreadable, so a getter that needs game state (a loaded database, a language table) does not
compile here and is reported with its reason.

The fields compiled are those with a direct plan in the shipped plan file of the pinned build.
A build other than the pinned one needs its address map (`--map`, from fm_update_build.py) so
that the fmdb constants (tables.CLASSES, vm.INTERCEPTORS, VARIANT_REGISTRY_RVA) are the new
build's. `--compare` diffs two outputs per class and field: a field whose chain, width, sign,
type or transform differs is a moved or retyped field.

27.0.0 -> 27.0.1 (12 November 2026): 613 of the 1,224 direct-plan fields compile statically on
both builds, all 613 identical; 611 compile on neither (they need game state). On the pinned
build, 544 of the 613 equal the shipped live-derived plan exactly and the other 69 differ only
in the record pointer's subobject offset or the sign convention.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
import os
from pathlib import Path
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BASE = 0x1_2000_0000
FAKE = 0x5F00_0000_0000          # stand-in objects (registry, interceptors) and import addresses


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--plugin')
    ap.add_argument('--map', help='address map of a build other than the pinned one')
    ap.add_argument('--out')
    ap.add_argument('--classes')
    ap.add_argument('--compare', nargs=2, metavar=('OLD', 'NEW'))
    args = ap.parse_args(argv)
    if args.compare:
        return compare(*args.compare)
    if not args.plugin or not args.out:
        ap.error('--plugin and --out, or --compare')
    if args.map:
        os.environ['FMCP_ADDRESS_MAP'] = args.map
        os.environ.pop('FMCP_ADDRESS_BOOK', None)
    else:
        os.environ['FMCP_ADDRESS_BOOK'] = 'off'
    sys.path.insert(0, str(ROOT))
    import fm_live_mcp  # noqa: F401  (installs the address book before the fmdb modules load)
    from fm_live_mcp import address_book
    from fm_live_mcp.fmdb import plancompile
    print(f'address book {address_book.ACTIVE["state"]} {address_book.ACTIVE["version"]}', flush=True)
    engine = StaticEngine(args.plugin)
    shipped_path = ROOT / 'fm_live_mcp/fmdb/data' / f'plans-{address_book.PINNED_SHA256}.v2.json.gz'
    shipped = json.loads(gzip.decompress(shipped_path.read_bytes()))['plans']
    only = set(args.classes.split(',')) if args.classes else None
    out, started = {}, time.time()
    for cls in sorted(shipped):
        if only and cls not in only:
            continue
        codes = sorted(c for c, p in shipped[cls].items() if p.get('status') == 'direct')
        if not codes:
            continue
        t = time.time()
        try:
            compiled = plancompile.compile_class(engine, cls, codes, binary=engine.binary)
        except Exception as exc:  # noqa: BLE001 - a class that cannot run statically is reported
            out[cls] = {'error': f'{type(exc).__name__}: {exc}'[:300]}
            print(f'{cls}: error {out[cls]["error"]}', flush=True)
            continue
        out[cls] = {code: ({k: v for k, v in c.plan.items() if k != 'paths'} if c.plan else {'reason': c.reason[:200]})
                    for code, c in compiled.items()}
        n = sum(1 for v in out[cls].values() if 'reason' not in v)
        print(f'{cls}: {n} of {len(codes)} compiled ({time.time() - t:.0f}s)', flush=True)
    Path(args.out).write_text(json.dumps(out, indent=0, default=str))
    print(f'total {time.time() - started:.0f}s; wrote {args.out}')
    return 0


class StaticMemory:
    """`cached_read` of the plugin file at BASE, with the stand-ins described above."""

    def __init__(self, binary):
        from fm_live_mcp.fmdb import vm
        self.b = binary
        self.end = binary.image_end()
        self.binds = binary.image.binds
        names = sorted(set(self.binds.values()))
        self.import_address = {n: FAKE + 0x80_0000 + 0x10 * k for k, n in enumerate(names)}
        self.registry = vm.VARIANT_REGISTRY_RVA
        self.registry_object = FAKE
        self.fake, self.objects = {}, {}
        for k, (glob, rtti, _slot, _original) in enumerate(vm.INTERCEPTORS):
            obj = FAKE + 0x10000 + 0x100 * k
            self.fake[obj] = struct.pack('<Q', BASE + binary.vtable(rtti, 0))
            self.objects[glob] = obj

    def cached_read(self, address, length):
        from fm_live_mcp.fmdb.memory import MemoryReadError
        if FAKE <= address < FAKE + 0x100_0000:
            data = bytearray(length)
            for at, word in self.fake.items():
                for k in range(8):
                    if address <= at + k < address + length:
                        data[at + k - address] = word[k]
            return bytes(data)
        rva = address - BASE
        if not (0 <= rva and rva + length <= self.end):
            raise MemoryReadError(f'static image: {address:#x} is outside the plugin')
        try:
            data = bytearray(self.b.image.file_bytes(rva, length))
        except Exception as exc:  # noqa: BLE001
            raise MemoryReadError(str(exc)) from exc
        for slot in range((rva - 8) & ~7, rva + length, 8):
            if slot == self.registry:
                word = struct.pack('<Q', self.registry_object)
            elif slot in self.objects:
                word = struct.pack('<Q', self.objects[slot])
            elif slot in self.b.rebases:
                word = struct.pack('<Q', BASE + self.b.rebases[slot])
            elif slot in self.binds:
                word = struct.pack('<Q', self.import_address[self.binds[slot]])
            else:
                continue
            for k in range(8):
                if rva <= slot + k < rva + length:
                    data[slot + k - rva] = word[k]
        return bytes(data)

    read = cached_read


class StaticEngine:
    """The parts of fmdb.engine.Engine that plancompile.Compiler uses."""

    def __init__(self, path):
        from fm_live_mcp.fmdb import platform_model
        from fm_live_mcp.fmdb.image import PluginImage
        self.plugin_path = Path(path)
        self.binary = platform_model.load_binary(path)
        self.image = PluginImage.load(path, verify=False)
        self.memory = StaticMemory(self.binary)
        self.base = BASE
        self._bootstrap_registry()

    def file_resolver(self):
        return False

    def _bootstrap_registry(self):
        """Run the typed-traits registry's lazy constructor-getter (the function that loads the
        registry global and allocates 0xd8 bytes when it is null) and keep the object it builds."""
        from fm_live_mcp.fmdb import vm as vmmod
        mem, b = self.memory, self.binary
        getter = None
        for _adrp, use, _kind in b.refs.get(mem.registry, ()):
            start, end = b.function_of(use)
            if (end - start) // 4 < 200 and any(b.word(pc) == 0x52801B00 for pc in range(start, end, 4)):
                getter = start
                break
        if getter is None:
            raise SystemExit('the typed-traits registry constructor was not found')
        v = vmmod.PropertyVM(mem, BASE, self.image, file_resolver=False)
        v.set_overlay(BASE + mem.registry, bytes(8))
        obj, _stats = v.call(BASE + getter)
        words = struct.unpack('<32Q', v.read(obj, 0x100))
        for k, w in enumerate(words):
            mem.fake[FAKE + 0x2000 + 8 * k] = struct.pack('<Q', w)
        mem.registry_object = FAKE + 0x2000


def compare(old_path, new_path):
    old, new = json.loads(Path(old_path).read_text()), json.loads(Path(new_path).read_text())
    totals, rows = Counter(), []
    for cls in sorted(set(old) | set(new)):
        a, b = old.get(cls, {}), new.get(cls, {})
        if 'error' in a or 'error' in b:
            totals['class errors'] += 1
            continue
        for code in sorted(set(a) | set(b)):
            x, y = a.get(code, {}), b.get(code, {})
            if 'reason' not in x and 'reason' not in y and x and y:
                if x == y:
                    totals['same'] += 1
                else:
                    totals['different'] += 1
                    rows.append((cls, code, x, y))
            elif ('reason' not in x and x) or ('reason' not in y and y):
                totals['compiled on one build only'] += 1
                rows.append((cls, code, x, y))
            else:
                totals['compiled on neither'] += 1
    print(dict(totals))
    for cls, code, x, y in rows:
        print(f'  {cls} {code}: {x.get("chain", x.get("reason"))} -> {y.get("chain", y.get("reason"))}')
    return 0 if not rows else 1


if __name__ == '__main__':
    sys.exit(main())
