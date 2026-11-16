"""Build fm_live_mcp/fmdb/data/ui_registry.json.gz (UI property keys, handler classes, types).

Inputs:
* the key/label registry recovered from GameAssembly's registration function 0xA296BC
  (`ui-property-registry.json` from the runtime research directory; 8,305 key+label pairs);
* the pinned on-disk ARM64 plugin slice (vtables, slot functions, FourCC immediates);
* optionally a running game (`--live`): every handler type 1..144 is built through the
  game's own GAME_UI_HANDLER_FACTORY inside the VM, which names the client and server
  classes exactly (falls back to "unknown" per type when the factory stops).

Key scan: a FourCC counts for a slot when the slot function materialises it as a 32-bit
immediate (movz/movk, or movz/movk then add/sub imm) and the registry knows it; for
slot 16 (declare inputs) every immediate passed in w1 is kept, registered or not.

Usage: PYTHONPATH=. python scripts/fmdb_ui_registry_build.py [--live] [--research DIR]
"""
from __future__ import annotations

import argparse
import bisect
import gzip
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fm_live_mcp.fmdb.image import PluginImage  # noqa: E402

from fm_live_mcp import build_paths  # noqa: E402

PLUGIN = build_paths.pinned_path(build_paths.PLUGIN_IN_APP)   # the shipped registry is the pinned build's
RESEARCH = Path('/Volumes/4TB Private/Offloaded/Agent Work/fmdb-runtime-research')
OUT = ROOT / 'fm_live_mcp' / 'fmdb' / 'data' / 'ui_registry.json.gz'
SLOTS = 30
DECLARE_SLOT = 16


def function_starts(image):
    """LC_FUNCTION_STARTS of the slice (ULEB deltas)."""
    data = image._map
    off = image.slice_offset
    ncmds = struct.unpack_from('<I', data, off + 16)[0]
    cursor = off + 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from('<II', data, cursor)
        if cmd == 0x26:
            dataoff, datasize = struct.unpack_from('<II', data, cursor + 8)
            blob = data[off + dataoff: off + dataoff + datasize]
            starts, value, i = [], 0, 0
            while i < len(blob):
                delta = shift = 0
                while True:
                    byte = blob[i]
                    i += 1
                    delta |= (byte & 0x7F) << shift
                    shift += 7
                    if not byte & 0x80:
                        break
                if delta == 0:
                    break
                value += delta
                starts.append(value)
            return starts
        cursor += size
    raise SystemExit('no LC_FUNCTION_STARTS')


def immediates(code: bytes):
    """32-bit constants materialised in w registers: [(value, register)]."""
    regs, found = {}, []
    for (w,) in struct.iter_unpack('<I', code):
        rd = w & 31
        if (w & 0xFF800000) == 0x52800000:      # movz w
            regs[rd] = ((w >> 5) & 0xFFFF) << (16 * ((w >> 21) & 3))
            found.append((regs[rd], rd))
        elif (w & 0xFF800000) == 0x72800000:    # movk w
            hw = (w >> 21) & 3
            if rd in regs:
                regs[rd] = (regs[rd] & ~(0xFFFF << (16 * hw))) | (((w >> 5) & 0xFFFF) << (16 * hw))
                found.append((regs[rd], rd))
        elif (w & 0x7F000000) == 0x11000000 and not w >> 31:   # add/sub w, imm
            rn, imm = (w >> 5) & 31, (w >> 10) & 0xFFF
            if (w >> 22) & 1:
                imm <<= 12
            if rn in regs:
                regs[rd] = (regs[rn] - imm if (w >> 30) & 1 else regs[rn] + imm) & 0xFFFFFFFF
                found.append((regs[rd], rd))
    return found


def printable(value):
    return all(0x20 <= b < 0x7F for b in value.to_bytes(4, 'big')) and value != 0x20202020


def fourcc_text(key):
    return key.to_bytes(4, 'big').decode('latin-1')


def build(research: Path, live: bool, plugin: Path):
    from fm_live_mcp import players
    registry = json.loads((research / 'ui-property-registry.json').read_text())
    vtables = json.loads((research / 'plugin-vtables.json').read_text())
    keys = {}
    for row in registry:
        if row.get('fourcc') and row.get('label') is not None:
            keys.setdefault(row['fourcc'], row['label'])
    key_numbers = {int.from_bytes(k.encode('latin-1'), 'big') for k in keys}
    image = PluginImage.load(plugin)
    starts = function_starts(image)

    def function_code(fn):
        i = bisect.bisect_right(starts, fn) - 1
        end = starts[i + 1] if i + 1 < len(starts) else fn + 0x1000
        return image.file_bytes(fn, min(end - fn, 0x40000))

    def slot_fn(vt, slot):
        if vt + 8 * slot in image.binds:
            return None
        raw = struct.unpack('<Q', image.file_bytes(vt + 8 * slot, 8))[0]
        rva = raw & 0xFFFFFFFFF
        return rva if image.is_code(rva) else None

    classes = {}
    for name, vt in vtables.items():
        if 'UI_HANDLER' not in name:
            continue
        vt = int(vt, 16)
        short = name.split('::')[-1]
        slots, row = {}, {'vtable': vt}
        limit = 7 if short.endswith('_SERVER') else SLOTS
        for slot in range(limit):
            fn = slot_fn(vt, slot)
            if fn is None:
                continue
            consts = immediates(function_code(fn))
            hit = sorted({fourcc_text(v) for v, _ in consts if v in key_numbers})
            entry = {'fn': fn}
            if hit:
                entry['keys'] = hit
            if slot == DECLARE_SLOT and not short.endswith('_SERVER'):
                entry['declares'] = sorted({fourcc_text(v) for v, r in consts
                                            if r == 1 and printable(v)})
            if (slot == 2 and short.endswith('_SERVER')) or (slot == 17 and not short.endswith('_SERVER')):
                entry['fourccs'] = sorted({fourcc_text(v) for v, _ in consts if printable(v)})
            slots[str(slot)] = entry
        row['slots'] = slots
        classes[short] = row
    types = {}
    if live:
        types = live_types()
    return {'build': players.SHA256, 'keys': keys, 'classes': classes, 'types': types}


def live_types():
    from fm_live_mcp.fmdb.live import open_live
    from fm_live_mcp.fmdb.memory import LiveMemory
    from fm_live_mcp.fmdb.ui_vm import UiHandlerVM
    from fm_live_mcp.fmdb.vm import _Stop
    session = open_live()
    image = PluginImage.load(session.plugin_path)
    memory = LiveMemory(session.pid)
    vm = UiHandlerVM(memory, session.base, image)
    out = {}
    try:
        for handler_type in range(1, 0x91):
            row = {}
            for side in ('client', 'server'):
                try:
                    handler = vm.build(handler_type, {}, server=(side == 'server'), client=(side == 'client'))
                    obj = handler.client if side == 'client' else handler.server
                    row[side] = vm.class_name(obj) if obj else None
                except _Stop as stop:
                    row[side] = None
                    row[side + '_error'] = f'{stop.reason} {stop.detail or ""}'.strip()
            out[str(handler_type)] = row
    finally:
        memory.close()
        session.close()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--live', action='store_true')
    ap.add_argument('--research', type=Path, default=RESEARCH)
    ap.add_argument('--out', type=Path, default=OUT)
    ap.add_argument('--plugin', type=Path, default=PLUGIN)
    args = ap.parse_args(argv)
    data = build(args.research, args.live, args.plugin)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(data, sort_keys=True, separators=(',', ':')).encode()
    args.out.write_bytes(gzip.compress(blob, 9, mtime=0))
    print(f'{args.out}: {len(data["keys"])} keys, {len(data["classes"])} classes, '
          f'{len(data["types"])} types, {args.out.stat().st_size} bytes')


if __name__ == '__main__':
    main()
