"""Extract the front end's screen specification into fm_live_mcp/fmdb/data/ui_frontend.json.gz.

Read-only, from the installed files (nothing is copied; the game need not run):

* GameAssembly.dylib + global-metadata.dat v39 (`ui_frontend.FrontEnd`):
  - `registry`: every property key the front end registers with its label
    (SI.Bindable PropertyRegistration::Initialise, one per assembly; keys built with
    mov/movk/add/sub/orr/eor are followed, so the 311 keys the older extractor missed, such as
    VisionObjectiveProgress = 'cvop', are included);
  - `records`: every `*Reference` class (the record schemas the views bind to): its record id
    (get_ID), the property keys it accepts (GetPropertiesInternal) and the record ids its
    properties refer to (GetPropertyTypeInternal -> ReferenceID::op_Implicit);
  - `ui_record_ids`: FM.GamePlugin.UiRecordID (the UI_RECORD '110 ' handler types by name).
* game_plugin (`plugin_params`): the screen-parameter globals the plugin looks up through
  0x77E228, each a {hash, const char *name} pair set by a static initialiser.
* The ui-* asset bundles (UnityPy): per view (VisualTreeAsset) the binding paths, the
  BindingVariables it sets ({name}{Type|value|}) and the records it expects
  (BindingExpect var:type); per table factory the columns and bindings; per data collection
  the value keys and translation ids (value -> text on screen, translated at run time by
  `ui_recipes_screens.translate`).

Usage: PYTHONPATH=. uv run --with capstone --with UnityPy python scripts/fmdb_ui_frontend.py [--out FILE]
       [--app FM.APP] [--compare OLD.json.gz]

Without `--app` it reads the pinned build (the shipped table). `--app` names the `fm.app` of
another build: scripts/fm_update_build.py runs this on the installed app after a game update and
writes `<plugin sha256>.ui_frontend.json.gz` next to the address map, which `ui_frontend.table()`
loads for that build. `--compare` prints what differs from another table (`diff_tables`).
"""
from __future__ import annotations

import argparse
import bisect
import gzip
import json
from pathlib import Path
import re
import struct
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fm_live_mcp.fmdb import ui_frontend  # noqa: E402
from fm_live_mcp.fmdb.ui_frontend import FrontEnd, GameAssembly, Metadata, APP  # noqa: E402

PLUGIN = APP / 'PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin'
BUNDLES = APP / 'Resources/Data/StreamingAssets/aa/StandaloneOSX'


def use_app(app: Path) -> None:
    """Read another build: `app` is its `fm.app` (or its `Contents`)."""
    global APP, PLUGIN, BUNDLES
    app = Path(app)
    APP = app if app.name == 'Contents' else app / 'Contents'
    PLUGIN = APP / 'PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin'
    BUNDLES = APP / 'Resources/Data/StreamingAssets/aa/StandaloneOSX'
VIEW_BUNDLES = ('ui-visualtreeassets_assets_gameworldvisualtreeassetpreload.bundle',
                'ui-visualtreeassets_assets_globalvisualtreeassetpreload.bundle')
TABLE_BUNDLES = ('ui-tableviews_assets_all.bundle', 'ui-tablefactories_assets_all.bundle')
COLLECTION_BUNDLE = 'ui-datacollections_assets_all.bundle'

PROPERTY_ID_IMPLICIT = 'SI.Bindable.Reference.Core.PropertyID::op_Implicit'
REFERENCE_ID_IMPLICIT = 'SI.Bindable.Reference.Core.ReferenceID::op_Implicit'


def fourcc_text(value: int) -> str | None:
    raw = struct.pack('>I', value & 0xFFFFFFFF)
    return raw.decode('latin1') if all(32 <= c < 127 for c in raw) else None


# ------------------------------------------------------------------ ARM64 constant tracking
class Tracker:
    """Constants in w/x registers over straight-line code (enough for generated binding code)."""

    def __init__(self, fe: FrontEnd):
        import capstone
        from capstone import arm64_const as A
        self.fe, self.A = fe, A
        self.md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
        self.md.detail = True
        self.addrs = sorted(fe.by_address)
        self.names = {a: fe.meta.method_name(m) for a, m in fe.by_address.items()}

    def end_of(self, address):
        i = bisect.bisect_right(self.addrs, address)
        return self.addrs[i] if i < len(self.addrs) else address + 0x1000

    def run(self, address, on_call, on_insn=None, limit=None):
        A = self.A
        end = self.end_of(address)
        if limit:
            end = min(end, address + 4 * limit)
        code = self.fe.ga.read(address, end - address)
        regs: dict = {}

        def norm(r):
            return 'x' + r[1:] if r and r[0] == 'w' else r

        for ins in self.md.disasm(code, address):
            ops = ins.operands
            m = ins.mnemonic

            def reg(i):
                return norm(ins.reg_name(ops[i].reg)) if i < len(ops) and ops[i].type == A.ARM64_OP_REG else None

            def imm(i):
                return ops[i].imm if i < len(ops) and ops[i].type == A.ARM64_OP_IMM else None

            d = reg(0)
            if on_insn:
                on_insn(ins, regs)
            if m in ('mov', 'movz', 'movn') and imm(1) is not None:
                v = imm(1)
                if m == 'movn':
                    v = ~v
                regs[d] = v & 0xFFFFFFFFFFFFFFFF
            elif m == 'mov' and reg(1):
                regs[d] = regs.get(reg(1))
            elif m == 'movk' and imm(1) is not None:
                sh = ops[1].shift.value if ops[1].shift.type else 0
                cur = regs.get(d)
                regs[d] = None if cur is None else (cur & ~(0xFFFF << sh)) | (imm(1) << sh)
            elif m in ('add', 'sub', 'orr', 'eor') and reg(1) and (imm(2) is not None or reg(2)):
                v = regs.get(reg(1))
                w = imm(2) if imm(2) is not None else regs.get(reg(2))
                if isinstance(w, int) and len(ops) > 2 and ops[2].shift.type:
                    w = w << ops[2].shift.value if ops[2].shift.type == A.ARM64_SFT_LSL else None
                if not isinstance(v, int) or not isinstance(w, int):
                    regs[d] = None
                else:
                    v = {'add': v + w, 'sub': v - w, 'orr': v | w, 'eor': v ^ w}[m]
                    regs[d] = v & 0xFFFFFFFFFFFFFFFF
            elif m == 'adrp':
                regs[d] = imm(1)
            elif m == 'ldr' and len(ops) == 2 and ops[1].type == A.ARM64_OP_MEM:
                base = norm(ins.reg_name(ops[1].mem.base))
                v = regs.get(base)
                regs[d] = ('slot', v + ops[1].mem.disp) if isinstance(v, int) else None
            elif m == 'bl':
                target = imm(0)
                on_call(ins.address, self.names.get(target), target, regs)
                keep = {k: v for k, v in regs.items() if k in
                        ('x19', 'x20', 'x21', 'x22', 'x23', 'x24', 'x25', 'x26', 'x27', 'x28')}
                regs.clear()
                regs.update(keep)
            elif m in ('ret', 'b') and on_insn is None and m == 'ret' and limit is None:
                pass
            elif d and m not in ('str', 'stp', 'strb', 'strh', 'stur', 'cmp', 'cmn', 'tst', 'cbz', 'cbnz',
                                 'tbz', 'tbnz', 'b', 'ret', 'br', 'blr') and not m.startswith('b.'):
                regs[d] = None


def extract_registry(fe: FrontEnd, tracker: Tracker) -> dict:
    """{fourcc or hex: label} from every PropertyRegistration::Initialise."""
    meta = fe.meta
    out = {}
    for t in meta.types:
        if t.name != 'PropertyRegistration':
            continue
        for m in meta.type_methods(t):
            if m.name != 'Initialise' or not m.address:
                continue
            pending = {'key': None}

            def on_call(address, name, target, regs):
                if name == PROPERTY_ID_IMPLICIT:
                    pending['key'] = regs.get('x0')
                    return
                slot = regs.get('x2')
                if pending['key'] is not None and isinstance(slot, tuple):
                    usage = fe.usage(slot[1])
                    if usage and usage[0] == 'string':
                        key = pending['key'] & 0xFFFFFFFF
                        out[fourcc_text(key) or f'{key:#x}'] = meta.literal(usage[1])
                pending['key'] = None

            tracker.run(m.address, on_call)
    return out


def extract_records(fe: FrontEnd, tracker: Tracker) -> dict:
    """{record id: {class, properties: [...], refers: {property: record id}}} per Reference."""
    meta = fe.meta
    out = {}
    for t in meta.types:
        if not t.name.endswith('Reference'):
            continue
        methods = {m.name: m for m in meta.type_methods(t)}
        if 'GetPropertiesInternal' not in methods or 'get_ID' not in methods:
            continue
        ident = {}
        tracker.run(methods['get_ID'].address, lambda *a: None,
                    on_insn=lambda ins, regs: ident.__setitem__('w0', regs.get('x0')) if ins.mnemonic == 'ret' else None,
                    limit=8)
        rid = ident.get('w0')
        props = []

        def on_prop(address, name, target, regs):
            if name == PROPERTY_ID_IMPLICIT and regs.get('x0') is not None:
                key = regs['x0'] & 0xFFFFFFFF
                props.append(fourcc_text(key) or f'{key:#x}')

        tracker.run(methods['GetPropertiesInternal'].address, on_prop)
        refers = {}
        if 'GetPropertyTypeInternal' in methods:
            refers = _property_refs(fe, tracker, methods['GetPropertyTypeInternal'].address, props)
        key = (fourcc_text(rid) or f'{rid:#x}') if isinstance(rid, int) else t.full_name
        out[key] = {'class': t.full_name, 'properties': props, 'refers': refers}
    return out


def _property_refs(fe, tracker, address, props) -> dict:
    """Property -> referenced record id, from the compare tree of GetPropertyTypeInternal:
    a `cmp wN, <key>; b.eq T` or `b.ne` edge leads to a block that calls ReferenceID::op_Implicit."""
    import capstone
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
    end = tracker.end_of(address)
    insns = list(md.disasm(fe.ga.read(address, end - address), address))
    index = {i.address: k for k, i in enumerate(insns)}
    consts, edges = {}, {}
    last_cmp = None
    for k, ins in enumerate(insns):
        m, op = ins.mnemonic, ins.op_str
        parts = [p.strip() for p in op.split(',')]
        if m in ('mov', 'movz') and len(parts) == 2 and parts[1].startswith('#'):
            consts[parts[0]] = int(parts[1][1:], 0) & 0xFFFF
        elif m == 'movk' and parts[0] in consts and 'lsl #16' in op:
            consts[parts[0]] = (consts[parts[0]] & 0xFFFF) | (int(parts[1][1:], 0) << 16)
        elif m == 'cmp' and len(parts) == 2 and parts[1] in consts:
            last_cmp = consts[parts[1]]
        elif m == 'b.eq' and last_cmp is not None:
            edges[last_cmp] = int(op.lstrip('#'), 0)
        elif m == 'b.ne' and last_cmp is not None and k + 1 < len(insns):
            edges[last_cmp] = insns[k + 1].address
    refs = {}
    for key, target in edges.items():
        name = fourcc_text(key)
        if name not in props:
            continue
        k = index.get(target)
        steps = 0
        w0 = None
        while k is not None and k < len(insns) and steps < 40:
            ins = insns[k]
            parts = [p.strip() for p in ins.op_str.split(',')]
            if ins.mnemonic in ('mov', 'movz') and parts[0] == 'w0' and parts[1].startswith('#'):
                w0 = int(parts[1][1:], 0) & 0xFFFF
            elif ins.mnemonic == 'movk' and parts[0] == 'w0' and w0 is not None:
                w0 = (w0 & 0xFFFF) | (int(parts[1][1:], 0) << 16)
            elif ins.mnemonic == 'bl':
                if tracker.names.get(int(ins.op_str.lstrip('#'), 0)) == REFERENCE_ID_IMPLICIT:
                    if w0 is not None:
                        refs[name] = fourcc_text(w0) or f'{w0:#x}'
                    break
            elif ins.mnemonic == 'b':
                k = index.get(int(ins.op_str.lstrip('#'), 0))
                steps += 1
                continue
            elif ins.mnemonic in ('ret', 'br') or ins.mnemonic.startswith('b.'):
                break
            k += 1
            steps += 1
    return refs


def extract_ui_record_ids(fe: FrontEnd) -> dict:
    for t in fe.meta.types:
        if t.full_name == 'FM.GamePlugin.UiRecordID':
            return {name: value for name, value in fe.meta.enum_values(t).items()}
    return {}


# ------------------------------------------------------------------ plugin parameter globals
def extract_plugin_params(path: Path = PLUGIN) -> dict:
    """{parameter name: global RVA} from `stp x0, x19, [x8]` stores of {hash, name} pairs."""
    import mmap
    f = open(path, 'rb')
    mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    base = 0
    if struct.unpack('>I', mm[:4])[0] == 0xCAFEBABE:
        for i in range(struct.unpack('>I', mm[4:8])[0]):
            cpu, _sub, off, _size, _al = struct.unpack('>5I', mm[8 + 20 * i: 28 + 20 * i])
            if cpu == 0x0100000C:
                base = off
    ncmds = struct.unpack_from('<I', mm, base + 16)[0]
    p = base + 32
    segs, text = [], None
    for _ in range(ncmds):
        cmd, size = struct.unpack_from('<II', mm, p)
        if cmd == 0x19:
            vm, _vs, fo, fs = struct.unpack_from('<4Q', mm, p + 24)
            segs.append((vm, fo, fs))
            nsect = struct.unpack_from('<I', mm, p + 64)[0]
            q = p + 72
            for _ in range(nsect):
                if mm[q:q + 16].rstrip(b'\0') == b'__text':
                    addr, sz = struct.unpack_from('<QQ', mm, q + 32)
                    off = struct.unpack_from('<I', mm, q + 48)[0]
                    text = (addr, base + off, sz)
                q += 80
        p += size

    def fileoff(vm):
        for v, fo, fs in segs:
            if v <= vm < v + fs:
                return base + fo + vm - v
        return None

    def cstr(vm):
        o = fileoff(vm)
        if o is None:
            return None
        e = mm.find(b'\0', o, o + 128)
        raw = mm[o:e]
        return raw.decode('latin1') if raw and all(32 <= c < 127 for c in raw) else None

    addr, off, size = text
    words = struct.unpack_from('<%dI' % (size // 4), mm, off)

    def resolve(i, reg, back):
        add = None
        for j in range(i - 1, max(0, i - back), -1):
            w = words[j]
            if (w & 0xFF800000) == 0x91000000 and (w & 31) == reg and ((w >> 5) & 31) == reg and add is None:
                add = (w >> 10) & 0xFFF
                continue
            if (w & 0x9F000000) == 0x90000000 and (w & 31) == reg:
                imm = ((w >> 29) & 3) | (((w >> 5) & 0x7FFFF) << 2)
                if imm & (1 << 20):
                    imm -= 1 << 21
                pc = addr + 4 * j
                return (pc & ~0xFFF) + (imm << 12) + (add or 0)
        return None

    out = {}
    for i, w in enumerate(words):
        if w != 0xA9004D00:      # stp x0, x19, [x8]
            continue
        g, s = resolve(i, 8, 4), resolve(i, 19, 14)
        name = cstr(s) if g and s else None
        if name:
            out[name] = f'{g:#x}'
    return out


# ------------------------------------------------------------------ asset bundles
def _objects(bundle: str):
    import UnityPy
    env = UnityPy.load(str(BUNDLES / bundle))
    for obj in env.objects:
        if obj.type.name != 'MonoBehaviour':
            continue
        raw = bytes(obj.get_raw_data())
        n = int.from_bytes(raw[28:32], 'little')
        name = raw[32:32 + n].decode('utf-8', 'replace') if 0 < n < 300 else ''
        yield name, raw


PATH_RX = re.compile(rb'\[SI\.Bindable\.BindingPath\]\x01(.)', re.S)   # flag byte, length byte
VAR_RX = re.compile(rb'\{([A-Za-z0-9_]+)\}\{([A-Za-z]+)\|([^|{}]*)\|\}')
VAR_JSON_RX = re.compile(rb'\{([A-Za-z0-9_]+)\}\{\{"\$type":"([^"&]+)[^}]*"m_value":\[([0-9,\-]*)\]\}\}')
EXPECT_RX = re.compile(rb'([a-z][A-Za-z0-9_]{1,40}):([a-z][A-Za-z0-9_]{1,60}):(True|False)')
BINDING_RX = re.compile(rb'binding\.([A-Za-z][A-Za-z0-9_]{2,80})')


def _paths(raw: bytes) -> list:
    out = []
    for m in PATH_RX.finditer(raw):
        start = m.end(1)
        n = m.group(1)[0]
        text = raw[start:start + n]
        if 0 < n < 128 and all(32 < c < 127 for c in text):
            out.append(text.decode())
    return out


def extract_views() -> dict:
    views = {}
    for bundle in VIEW_BUNDLES:
        for name, raw in _objects(bundle):
            paths = sorted(set(_paths(raw)))
            variables = {}
            for m in VAR_RX.finditer(raw):
                variables.setdefault(m.group(1).decode(), []).append(
                    f'{m.group(2).decode()}:{m.group(3).decode()}')
            for m in VAR_JSON_RX.finditer(raw):
                variables.setdefault(m.group(1).decode(), []).append(
                    f'{m.group(2).decode().split(".")[-1]}:[{m.group(3).decode()}]')
            expects = sorted({f'{a.decode()}:{b.decode()}' for a, b, _c in EXPECT_RX.findall(raw)})
            if not (paths or variables or expects):
                continue
            row = views.setdefault(name, {})
            if paths:
                row['bindings'] = sorted(set(row.get('bindings', [])) | set(paths))
            if variables:
                merged = row.setdefault('params', {})
                for k, v in variables.items():
                    merged[k] = sorted(set(merged.get(k, [])) | set(v))
            if expects:
                row['expects'] = sorted(set(row.get('expects', [])) | set(expects))
    return views


def extract_tables() -> dict:
    out = {}
    for bundle in TABLE_BUNDLES:
        for name, raw in _objects(bundle):
            cols = sorted(set(m.decode() for m in BINDING_RX.findall(raw)))
            paths = sorted(set(_paths(raw)))
            if cols or paths:
                out[name] = {'bindings': sorted(set(cols) | set(paths))}
    return out


def _ints_after(raw: bytes, marker: bytes, start=0, skip_first=False):
    i = raw.find(marker, start)
    if i < 0:
        return None, -1
    p = (i + len(marker) + 3) & ~3
    # walk forward to a plausible count followed by that many ints
    for q in range(p, min(len(raw) - 4, p + 256), 4):
        n = struct.unpack_from('<i', raw, q)[0]
        if 0 < n <= 4096 and q + 4 + 4 * n <= len(raw):
            vals = struct.unpack_from('<%di' % n, raw, q + 4)
            if all(-1_000_000 < v < 10_000_000 for v in vals):
                return list(vals), q + 4 + 4 * n
    return None, -1


def _int_keys(raw: bytes, want=None):
    """Values of the IntDataSet field named 'Key': ['Key'] [optional description string]
    [count] [ints], 4-byte aligned. The serialised order varies between collections, so
    every 'Key' name is tried; with `want` (the translation count) the count must match."""
    start = 0
    while True:
        k = raw.find(b'\x03\x00\x00\x00Key', start)
        if k < 0:
            return None
        start = k + 1
        p = (k + 7 + 3) & ~3
        if p + 8 > len(raw):
            return None
        n = struct.unpack_from('<i', raw, p)[0]
        text = raw[p + 4:p + 4 + n] if 0 < n < 400 else b''
        if n == 0 or text and all(32 <= c < 127 for c in text):   # (empty) description
            p = (p + 4 + n + 3) & ~3
            n = struct.unpack_from('<i', raw, p)[0]
        if not 0 < n <= 4096 or p + 4 + 4 * n > len(raw) or (want and n != want):
            continue
        vals = list(struct.unpack_from('<%di' % n, raw, p + 4))
        if all(-1_000_000 < v < 1_000_000 for v in vals):
            return vals


def extract_collections() -> dict:
    out = {}
    for name, raw in _objects(COLLECTION_BUNDLE):
        if not name.endswith('DataCollection'):
            continue
        row = {}
        t = raw.rfind(b'TranslationDataSet')
        if t >= 0:
            ids, _ = _ints_after(raw, b'TranslationDataSet', t)
            if ids and ids[0] == 0 and len(ids) > 1:   # a leading 0 (empty field) before the count
                ids = None
            if ids is None:
                p = (t + len(b'TranslationDataSet') + 3) & ~3
                for q in range(p, min(len(raw) - 8, p + 64), 4):
                    n = struct.unpack_from('<i', raw, q + 4)[0]
                    if 0 < n <= 4096 and q + 8 + 4 * n <= len(raw):
                        ids = list(struct.unpack_from('<%di' % n, raw, q + 8))
                        break
            if ids:
                row['translations'] = ids
        keys = _int_keys(raw, len(row['translations']) if row.get('translations') else None) or _int_keys(raw)
        if keys:
            row['keys'] = keys
        styles = re.findall(rb'(?:club|ui|game|scaling)-[a-z0-9\-_]{3,80}', raw)
        if styles:
            row['styles'] = [s.decode() for s in styles][:64]
        if row:
            out[name] = row
    return out


# ------------------------------------------------------------------ re-sweep with the views' parameters
OBJECT_PARAMS = {'human': ('Hhum', 'huma'), 'person': ('Pers', 'dref', 'PbPY'), 'team': ('Ttea', 'Team'),
                 'club': ('club', 'Club'), 'date': ('fdte', 'date'), 'competition': ('comp', 'Comp', 'dref')}
MAX_COMBOS = 8


def view_values(table: dict) -> dict:
    """{parameter name (lower case): sorted legal values} from every view's BindingVariables."""
    out = {}
    for view in table.get('views', {}).values():
        for name, values in view.get('params', {}).items():
            for text in values:
                kind, _, raw = text.partition(':')
                try:
                    value = {'Int': int, 'Bool': lambda v: bool(int(v))}[kind](raw)
                except (KeyError, ValueError):
                    continue
                out.setdefault(name.lower(), set()).add(value)
    return {k: sorted(v, key=lambda x: (isinstance(x, bool), x)) for k, v in out.items()}


def candidates(name: str, record: dict, legal: dict) -> list:
    if name in OBJECT_PARAMS:
        return [record[k] for k in OBJECT_PARAMS[name] if k in record][:2] or [0]
    return legal.get(name.lower()) or [0, 1]


def resweep(sweep_path: Path, out_path: Path, shard=(0, 1), only_types=None):
    """Re-read every key the earlier sweep left unset after it asked for screen parameters,
    supplying those parameters by name with the values the views use (or the career object
    for object-valued ones), through ui_recipes_screens.read_key (slot-2 context + slot-4
    lookups). One fresh emulator per handler type; results to out_path (JSON)."""
    import itertools
    from fm_live_mcp.fmdb import ui_recipes_screens as S, variant
    from fm_live_mcp.fmdb.image import PluginImage
    from fm_live_mcp.fmdb.live import open_live
    from fm_live_mcp.fmdb.memory import LiveMemory
    from fm_live_mcp.fmdb.ui_handlers import plain_text
    from fm_live_mcp.fmdb.ui_recipes_more import install_param_trace
    from fm_live_mcp.fmdb.ui_vm import UiHandlerVM, lsof_resolver
    from fm_live_mcp.fmdb.vm import Unavailable, _Stop
    table = ui_frontend.load_table()
    by_rva = {int(v, 16): k for k, v in table['plugin_params'].items()}
    legal = view_values(table)
    sweep = json.loads(Path(sweep_path).read_text())
    jobs = []
    for job in sweep['types']:
        keys = {k: v for k, v in job['keys'].items() if v.get('status') == 'unset' and v.get('params')}
        if keys and (not only_types or job['type'] in only_types):
            jobs.append((job, keys))
    jobs = [j for i, j in enumerate(jobs) if i % shard[1] == shard[0]]
    results = json.loads(out_path.read_text()) if out_path.exists() else {}
    session = open_live()
    image = PluginImage.load(session.plugin_path)
    for job, keys in jobs:
        tag = f'{job["type"]}:{job["client"]}'
        if tag in results:
            continue
        started = time.time()
        memory = LiveMemory(session.pid)
        rows = {}
        try:
            vm = UiHandlerVM(memory, session.base, image, file_resolver=lsof_resolver(session.pid), rng='copy')
            vm.fast()
            install_param_trace(vm)
            record = {k: v for k, v in job['record'].items()}
            base = None
            for code, before in keys.items():
                names = [by_rva.get(int(p, 16)) for p in before['params']]
                if None in names:
                    rows[code] = {'label': before.get('label'), 'status': 'skipped',
                                  'reason': 'parameter global without a name', 'params': before['params']}
                    continue
                if any(n in OBJECT_PARAMS for n in names):
                    # person/human/team/club/date/competition parameters are typed object
                    # references (RECORD / SI_DATE values), which read_key does not build
                    rows[code] = {'label': before.get('label'), 'param_names': names, 'status': 'skipped',
                                  'reason': 'object-valued parameter (needs a RECORD or SI_DATE typed value)'}
                    continue
                choices = [candidates(n, record, legal) for n in names]
                tried = []
                found = None
                for combo in itertools.islice(itertools.product(*choices), MAX_COMBOS):
                    params = dict(zip(names, combo))
                    try:
                        if base is None:
                            base = S.open_handler(vm, job['type'], record)
                        reading, entries, _ = S.read_key(vm, job['type'], record, code, params, reader=base)
                    except _Stop as stop:
                        tried.append({'params': params, 'status': 'unavailable', 'reason': stop.reason})
                        continue
                    value = reading.value
                    status = reading.status
                    tried.append({'params': {k: v for k, v in params.items()}, 'status': status,
                                  'context': [c for c, _ in entries]})
                    if status == 'value':
                        found = {'params': params, 'context': [c for c, _ in entries], 'kind': reading.kind,
                                 'value': str(plain_text(variant.to_json(value)))[:400]}
                        break
                rows[code] = {'label': before.get('label'), 'param_names': names,
                              'status': 'value' if found else (tried[-1]['status'] if tried else 'unset'),
                              'found': found, 'tried': len(tried)}
        except Exception as exc:  # noqa: BLE001 - keep sweeping other handler types
            rows['_error'] = f'{type(exc).__name__}: {exc}'[:300]
        finally:
            memory.close()
        results[tag] = {'type': job['type'], 'client': job['client'], 'seconds': round(time.time() - started, 1),
                        'keys': rows}
        out_path.write_text(json.dumps(results, indent=1, default=str))
        done = sum(1 for r in rows.values() if isinstance(r, dict) and r.get('status') == 'value')
        print(tag, f'{done}/{len(keys)} now read', round(time.time() - started, 1), 's', flush=True)
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', default=str(ui_frontend.DATA))
    ap.add_argument('--skip-bundles', action='store_true')
    ap.add_argument('--resweep', metavar='SWEEP_JSON', help='re-read unset parameter keys of an earlier sweep')
    ap.add_argument('--resweep-out', default='out/fmdb-ui-frontend/resweep.json')
    ap.add_argument('--shard', default='0/1', help='i/n: this process takes every n-th handler type')
    ap.add_argument('--types', default='', help='comma-separated handler types to limit the re-sweep')
    ap.add_argument('--app', help='fm.app of the build to read (default: the pinned build)')
    ap.add_argument('--compare', help='print what differs from this table (e.g. the shipped one)')
    args = ap.parse_args(argv)
    if args.app:
        use_app(Path(args.app))
    if args.resweep:
        i, n = (int(x) for x in args.shard.split('/'))
        out = Path(args.resweep_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        only = {int(t) for t in args.types.split(',') if t}
        resweep(Path(args.resweep), out, (i, n), only)
        return
    started = time.time()
    ga_path = APP / 'Frameworks/GameAssembly.dylib'
    meta_path = APP / 'Resources/Data/il2cpp_data/Metadata/global-metadata.dat'
    fe = FrontEnd(Metadata(meta_path), GameAssembly(ga_path))
    tracker = Tracker(fe)
    table = {'build': build_identity(ga_path)}
    table['registry'] = extract_registry(fe, tracker)
    print('registry', len(table['registry']), round(time.time() - started, 1))
    table['records'] = extract_records(fe, tracker)
    print('records', len(table['records']), round(time.time() - started, 1))
    table['ui_record_ids'] = extract_ui_record_ids(fe)
    table['plugin_params'] = extract_plugin_params(PLUGIN)
    print('params', len(table['plugin_params']), round(time.time() - started, 1))
    if not args.skip_bundles and not BUNDLES.is_dir():
        print(f'no asset bundles at {BUNDLES}: views, tables and data collections left out')
        table['build']['bundles'] = None
    elif not args.skip_bundles:
        table['views'] = extract_views()
        print('views', len(table['views']), round(time.time() - started, 1))
        table['tables'] = extract_tables()
        table['data_collections'] = extract_collections()
        print('tables', len(table['tables']), 'collections', len(table['data_collections']))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(table, sort_keys=True, separators=(',', ':')).encode()
    out.write_bytes(gzip.compress(blob, 9, mtime=0))
    print('wrote', out, len(blob), 'bytes json,', out.stat().st_size, 'gz', round(time.time() - started, 1), 's')
    if args.compare:
        print(json.dumps(ui_frontend.diff_tables(ui_frontend.load_table(Path(args.compare)), table), indent=1))


def build_identity(ga_path: Path) -> dict:
    """What the table was read from: the app version, the plugin's sha256, the two IL2CPP files'
    sizes (the shipped table of the pinned build has only metadata_version and
    game_assembly_bytes)."""
    import hashlib
    import plistlib
    out = {'metadata_version': 39, 'game_assembly_bytes': ga_path.stat().st_size}
    try:
        out['version'] = plistlib.loads((APP / 'Info.plist').read_bytes()).get('CFBundleShortVersionString')
    except (OSError, ValueError):
        out['version'] = None
    if PLUGIN.is_file():
        with PLUGIN.open('rb') as stream:
            out['plugin_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return out


if __name__ == '__main__':
    main()
