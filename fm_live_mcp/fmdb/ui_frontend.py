"""Static reader for the game's IL2CPP front end (GameAssembly.dylib + global-metadata.dat v39).

The C# front end decides what every screen asks the plugin for: it builds the UI_RECORD
(sorted (u32 key, u32 value) pairs, key '110 ' = handler type), the screen parameters and the
list of property keys each view requests, then calls the plugin through the channel functions.
This module reads that code as shipped, read-only, from the installed files:

* `Metadata` parses global-metadata.dat v39 (the v38+ header of (offset, size, count) triples,
  compressed 2-byte type/container indices): identifier strings, string literals, images,
  type definitions, methods, fields and properties.
* `GameAssembly` reads the ARM64 slice of GameAssembly.dylib, decodes chained-fixup pointers
  and finds each image's Il2CppCodeGenModule, which gives every method's code address.
* `usage(slot)` decodes an IL2CPP metadata-usage slot (the pre-initialisation value
  (kind << 29) | (index << 1) | 1 stored in __DATA), so an ADRP/LDR of a slot names the string
  literal, type, method or field the code uses.

The heavy analysis (disassembly) lives in `scripts/fmdb_ui_frontend.py`, which needs capstone
(`uv run --with capstone`); its output is the data file `data/ui_frontend.json.gz`, which the
runtime reads with `load_table()` and no capstone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
import gzip
import json
import mmap
from pathlib import Path
import struct

from .. import build_paths

# The shipped table (DATA) was built from the pinned build's GameAssembly and metadata
# (scripts/fmdb_ui_frontend.py); the readers below default to those files, not the installed ones.
# Another build has its own table, extracted by the update command into the cache next to its
# address map (`build_path`); `table()` loads the running build's (`active_source`).
APP = build_paths.pinned_path("Contents")
GA_PATH = APP / "Frameworks/GameAssembly.dylib"
META_PATH = APP / "Resources/Data/il2cpp_data/Metadata/global-metadata.dat"
DATA = Path(__file__).with_name("data") / "ui_frontend.json.gz"

# Header section order of metadata v38/v39 (each entry is (offset, size, count)).
SECTIONS = (
    "stringLiteral", "stringLiteralData", "string", "events", "properties", "methods",
    "parameterDefaultValues", "fieldDefaultValues", "fieldAndParameterDefaultValueData",
    "fieldMarshaledSizes", "parameters", "fields", "genericParameters",
    "genericParameterConstraints", "genericContainers", "nestedTypes", "interfaces",
    "vtableMethods", "interfaceOffsets", "typeDefinitions", "images", "assemblies",
    "fieldRefs", "referencedAssemblies", "attributeData", "attributeDataRange",
    "unresolvedIndirectCallParameterTypes", "unresolvedIndirectCallParameterRanges",
    "windowsRuntimeTypeNames", "windowsRuntimeStrings", "exportedTypeDefinitions",
)

USAGE_KINDS = {1: "type_info", 2: "type", 3: "method_def", 4: "field", 5: "string", 6: "method_ref", 7: "field_rva"}

U16_NONE = 0xFFFF
U32_NONE = 0xFFFFFFFF


class FrontEndError(RuntimeError):
    pass


@dataclass
class TypeDef:
    index: int
    name: str
    namespace: str
    declaring: int  # type index or -1
    parent: int  # Il2CppType index (binary), -1 when none
    flags: int
    field_start: int
    method_start: int
    property_start: int
    nested_start: int
    method_count: int
    property_count: int
    field_count: int
    nested_count: int
    token: int
    image: str = ""
    full_name: str = ""


@dataclass
class MethodDef:
    index: int
    name: str
    declaring: int
    return_type: int
    param_start: int
    token: int
    flags: int
    param_count: int
    address: int = 0


@dataclass
class FieldDef:
    index: int
    name: str
    type_index: int
    token: int


class Metadata:
    """global-metadata.dat v39, read in place."""

    def __init__(self, path: Path = META_PATH):
        f = open(path, "rb")
        self.mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        magic, version = struct.unpack_from("<II", self.mm, 0)
        if magic != 0xFAB11BAF or version != 39:
            raise FrontEndError(f"unexpected metadata header {magic:#x} v{version}")
        hdr = struct.unpack_from("<%dI" % (3 * len(SECTIONS)), self.mm, 8)
        self.sec = {n: hdr[3 * i:3 * i + 3] for i, n in enumerate(SECTIONS)}
        self._str_cache: dict[int, str] = {}

    def string(self, index: int) -> str:
        s = self._str_cache.get(index)
        if s is None:
            base = self.sec["string"][0] + index
            end = self.mm.find(b"\0", base)
            s = self.mm[base:end].decode("utf-8", "replace")
            self._str_cache[index] = s
        return s

    @cached_property
    def _literal_offsets(self):
        off, _size, n = self.sec["stringLiteral"]
        return struct.unpack_from("<%dI" % n, self.mm, off)

    @property
    def literal_count(self) -> int:
        return len(self._literal_offsets) - 1

    def literal(self, index: int) -> str:
        offs = self._literal_offsets
        data = self.sec["stringLiteralData"][0]
        return self.mm[data + offs[index]: data + offs[index + 1]].decode("utf-8", "replace")

    @cached_property
    def images(self) -> list[tuple[str, int, int]]:
        """(name, first type index, type count). The v39 image record's type range fields do
        not index typeDefinitions; each image's types are the run that starts where the type
        token restarts at 0x02000001, in image order (checked: the highest method token of
        each run equals that image's CodeGenModule method count)."""
        off, _size, n = self.sec["images"]
        names = [self.string(struct.unpack_from("<I", self.mm, off + 36 * k)[0]) for k in range(n)]
        toff, _tsize, tn = self.sec["typeDefinitions"]
        starts = [k for k in range(tn)
                  if struct.unpack_from("<I", self.mm, toff + 76 * k + 72)[0] & 0xFFFFFF == 1]
        starts.append(tn)
        return [(names[k], starts[k], starts[k + 1] - starts[k]) for k in range(min(n, len(starts) - 1))]

    @cached_property
    def types(self) -> list[TypeDef]:
        off, _size, n = self.sec["typeDefinitions"]
        out = []
        for k in range(n):
            b = off + 76 * k
            name, ns = struct.unpack_from("<II", self.mm, b)
            _byval, decl, parent, _gc = struct.unpack_from("<4H", self.mm, b + 8)
            flags, fs, ms, _es, ps, ns_, _is, _vs, _ios = struct.unpack_from("<9I", self.mm, b + 16)
            mc, pc, fc, _ec, nc, _vc, _ic, _ioc = struct.unpack_from("<8H", self.mm, b + 52)
            token = struct.unpack_from("<I", self.mm, b + 72)[0]
            out.append(TypeDef(
                k, self.string(name), self.string(ns),
                -1 if decl == U16_NONE else decl, -1 if parent == U16_NONE else parent,
                flags, fs, ms, ps, ns_, mc, pc, fc, nc, token,
            ))
        for img, start, count in self.images:
            for t in out[start:start + count]:
                t.image = img
        nested_off = self.sec["nestedTypes"][0]
        for t in out:  # declaring index for nested types comes from the nested table too
            for j in range(t.nested_count):
                child = struct.unpack_from("<I", self.mm, nested_off + 4 * (t.nested_start + j))[0]
                if child < len(out) and out[child].declaring < 0:
                    out[child].declaring = t.index
        for t in out:
            parts, cur, guard = [], t, 0
            while cur is not None and guard < 16:
                parts.append(cur.name)
                ns = cur.namespace
                cur = out[cur.declaring] if 0 <= cur.declaring < len(out) and cur.declaring != cur.index else None
                guard += 1
            t.full_name = (ns + "." if ns else "") + "/".join(reversed(parts))
        return out

    @cached_property
    def methods(self) -> list[MethodDef]:
        off, _size, n = self.sec["methods"]
        out = []
        for k in range(n):
            b = off + 30 * k
            name, decl, ret, _rpt, ps, _gc, tok, flags, _if, _slot, pc = struct.unpack_from(
                "<IHHIIHIHHHH", self.mm, b)
            out.append(MethodDef(k, self.string(name), decl, ret, ps, tok, flags, pc))
        return out

    @cached_property
    def fields(self) -> list[FieldDef]:
        off, _size, n = self.sec["fields"]
        out = []
        for k in range(n):
            name, ti, tok = struct.unpack_from("<IHI", self.mm, off + 10 * k)
            out.append(FieldDef(k, self.string(name), ti, tok))
        return out

    @cached_property
    def field_defaults(self) -> dict[int, int]:
        """{field index: offset into fieldAndParameterDefaultValueData}."""
        off, _size, n = self.sec["fieldDefaultValues"]
        out = {}
        for k in range(n):
            fi, _ti, di = struct.unpack_from("<IHI", self.mm, off + 10 * k)
            out[fi] = di
        return out

    def enum_values(self, t: TypeDef, width: int = 4) -> dict[str, int]:
        """Constant fields of an enum type (`value__` skipped), read as little-endian ints.
        IL2CPP stores enum constants compressed (ECMA compressed int) in v29+; both are tried."""
        base = self.sec["fieldAndParameterDefaultValueData"][0]
        rows = [(f.name, self.field_defaults.get(f.index)) for f in self.type_fields(t) if f.name != "value__"]
        rows = [(n, d) for n, d in rows if d is not None]
        # A byte-backed enum stores one raw byte per constant (consecutive offsets 1 apart).
        offs = [d for _n, d in rows]
        one_byte = len(offs) > 1 and all(b - a == 1 for a, b in zip(offs, offs[1:]))
        out = {}
        for n, d in rows:
            out[n] = self.mm[base + d] if one_byte else self._compressed_int(base + d)
        return out

    def _compressed_int(self, p: int) -> int:
        """IL2CPP's uleb-like 'compressed' encoding used for default values since v29."""
        b0 = self.mm[p]
        if b0 & 0x80 == 0:
            v = b0
        elif b0 & 0xC0 == 0x80:
            v = ((b0 & 0x3F) << 8) | self.mm[p + 1]
        elif b0 & 0xE0 == 0xC0:
            v = ((b0 & 0x1F) << 24) | (self.mm[p + 1] << 16) | (self.mm[p + 2] << 8) | self.mm[p + 3]
        elif b0 == 0xF0:
            v = struct.unpack_from(">I", self.mm, p + 1)[0]
        elif b0 == 0xFE:
            v = 0xFFFFFFFE
        elif b0 == 0xFF:
            v = 0xFFFFFFFF
        else:
            v = -1
        return v

    def type_methods(self, t: TypeDef) -> list[MethodDef]:
        if t.method_start == U32_NONE:
            return []
        return self.methods[t.method_start:t.method_start + t.method_count]

    def type_fields(self, t: TypeDef) -> list[FieldDef]:
        if t.field_start == U32_NONE:
            return []
        return self.fields[t.field_start:t.field_start + t.field_count]

    def method_name(self, m: MethodDef) -> str:
        return f"{self.types[m.declaring].full_name}::{m.name}"


class GameAssembly:
    """ARM64 slice of GameAssembly.dylib, read in place."""

    def __init__(self, path: Path = GA_PATH):
        f = open(path, "rb")
        self.mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        mm = self.mm
        self.base = 0
        if struct.unpack(">I", mm[:4])[0] == 0xCAFEBABE:
            n = struct.unpack(">I", mm[4:8])[0]
            for i in range(n):
                cpu, _sub, off, _size, _al = struct.unpack(">5I", mm[8 + 20 * i: 28 + 20 * i])
                if cpu == 0x0100000C:
                    self.base = off
        b = self.base
        ncmds = struct.unpack_from("<I", mm, b + 16)[0]
        p = b + 32
        self.segs, self.sects = [], []
        for _ in range(ncmds):
            cmd, csz = struct.unpack_from("<II", mm, p)
            if cmd == 0x19:
                name = mm[p + 8:p + 24].rstrip(b"\0").decode()
                vm, vms, fo, fs = struct.unpack_from("<4Q", mm, p + 24)
                ns = struct.unpack_from("<I", mm, p + 64)[0]
                self.segs.append((name, vm, vms, fo, fs))
                q = p + 72
                for _ in range(ns):
                    sn = mm[q:q + 16].rstrip(b"\0").decode()
                    sg = mm[q + 16:q + 32].rstrip(b"\0").decode()
                    a, s = struct.unpack_from("<QQ", mm, q + 32)
                    o = struct.unpack_from("<I", mm, q + 48)[0]
                    self.sects.append((sg, sn, a, s, o))
                    q += 80
            p += csz

    def off(self, vm: int):
        for _name, v, _vs, fo, fs in self.segs:
            if v <= vm < v + fs:
                return self.base + fo + (vm - v)
        return None

    def read(self, vm: int, n: int) -> bytes:
        o = self.off(vm)
        if o is None:
            raise FrontEndError(f"address {vm:#x} not in file")
        return self.mm[o:o + n]

    def u64(self, vm: int) -> int:
        return struct.unpack("<Q", self.read(vm, 8))[0]

    def u32(self, vm: int) -> int:
        return struct.unpack("<I", self.read(vm, 4))[0]

    @staticmethod
    def ptr(raw: int) -> int:
        """Chained-fixup rebase target (DYLD_CHAINED_PTR_64: low 36 bits)."""
        if raw >> 63:
            return 0  # bind to an imported symbol
        return raw & 0xFFFFFFFFF

    def sect(self, seg: str, name: str):
        for s in self.sects:
            if s[0] == seg and s[1] == name:
                return s
        return None

    def sect_bytes(self, seg: str, name: str):
        s = self.sect(seg, name)
        return s[2], self.mm[self.base + s[4]: self.base + s[4] + s[3]]

    def cstr(self, vm: int, maxn: int = 256) -> str:
        return self.read(vm, maxn).split(b"\0", 1)[0].decode("latin1")

    def codegen_modules(self, names: list[str]) -> dict[str, tuple[int, int]]:
        """{image name: (methodPointers address, count)} found by the module-name pointer."""
        a, b = self.sect_bytes("__TEXT", "__cstring")
        b = bytes(b)
        want = {}
        for n in names:
            i = b.find(b"\0" + n.encode() + b"\0")
            if i >= 0:
                want[a + i + 1] = n
        out = {}
        for name, vm, _vs, fo, fs in self.segs:
            if not name.startswith("__DATA"):
                continue
            data = self.mm[self.base + fo:self.base + fo + fs]
            for j in range(0, len(data) - 24, 8):
                raw = struct.unpack_from("<Q", data, j)[0]
                if not raw or raw >> 63:
                    continue
                t = raw & 0xFFFFFFFFF
                if t in want and want[t] not in out:
                    count = struct.unpack_from("<Q", data, j + 8)[0] & 0xFFFFFFFF
                    mp = self.ptr(struct.unpack_from("<Q", data, j + 16)[0])
                    if 0 < count < 200000 and mp and self.off(mp) is not None \
                            and self.off(mp + 8 * count - 8) is not None:
                        out[want[t]] = (mp, count)
        return out


class FrontEnd:
    """Metadata + code addresses."""

    def __init__(self, meta: Metadata | None = None, ga: GameAssembly | None = None):
        self.meta = meta or Metadata()
        self.ga = ga or GameAssembly()
        self.by_address: dict[int, MethodDef] = {}
        mods = self.ga.codegen_modules([img for img, _s, _c in self.meta.images])
        self.modules = mods
        for img, start, count in self.meta.images:
            if img not in mods:
                continue
            mp, n = mods[img]
            ptrs = struct.unpack("<%dQ" % n, self.ga.read(mp, 8 * n))
            for t in self.meta.types[start:start + count]:
                for m in self.meta.type_methods(t):
                    rid = m.token & 0xFFFFFF
                    if 1 <= rid <= n:
                        addr = self.ga.ptr(ptrs[rid - 1])
                        if addr:
                            m.address = addr
                            self.by_address.setdefault(addr, m)

    def usage(self, slot: int):
        """Decode a metadata-usage slot: (kind, index) or None."""
        try:
            v = self.ga.u64(slot)
        except Exception:
            return None
        if not (v & 1) or v >> 32:
            return None
        kind = (v >> 29) & 7
        if kind not in USAGE_KINDS:
            return None
        return USAGE_KINDS[kind], (v & ((1 << 29) - 1)) >> 1

    def describe_usage(self, slot: int) -> str | None:
        u = self.usage(slot)
        if u is None:
            return None
        kind, idx = u
        try:
            if kind == "string" and idx < self.meta.literal_count:
                return "str:" + self.meta.literal(idx)
            if kind == "method_def" and idx < len(self.meta.methods):
                return "method:" + self.meta.method_name(self.meta.methods[idx])
            if kind == "field" :
                return f"field#{idx}"
            return f"{kind}#{idx}"
        except Exception:
            return None

    def find_types(self, pattern: str) -> list[TypeDef]:
        import re
        rx = re.compile(pattern)
        return [t for t in self.meta.types if rx.search(t.full_name)]


def build_path(sha256: str) -> Path:
    """Where the update command writes the front-end table of one build (next to its address map)."""
    from .. import address_book
    return address_book.cache_dir() / f"{sha256}.ui_frontend.json.gz"


def active_source() -> dict:
    """Which front-end table belongs to the running build.

    {'path', 'build', 'per_build': bool, 'note'}: the shipped table on the pinned build; on a
    mapped build the table the update command extracted from that build's GameAssembly.dylib,
    global-metadata.dat, plugin and asset bundles (`<sha256>.ui_frontend.json.gz`); on a mapped
    build without one, the shipped table with a note (its translation ids, collections, labels
    and parameter names are the pinned build's, and its parameter globals are pinned plugin
    addresses, translated through the address map where the map has them)."""
    from .. import address_book
    state = address_book.ACTIVE.get("state")
    if state != "mapped":
        return {"path": str(DATA), "build": address_book.PINNED_VERSION, "per_build": False, "note": None}
    sha = address_book.ACTIVE["sha256"]
    version = address_book.ACTIVE.get("version") or sha[:12]
    path = build_path(sha)
    if path.exists():
        return {"path": str(path), "build": version, "per_build": True, "note": None}
    return {"path": str(DATA), "build": address_book.PINNED_VERSION, "per_build": False,
            "note": (f"No front-end data for the running build {version}: the words, labels and screen-parameter "
                     f"names come from build {address_book.PINNED_VERSION}'s front end and may be wrong or missing. "
                     f"Run `PYTHONPATH=. python {address_book.UPDATE_COMMAND} --installed` and restart the server.")}


def load_table(path: Path | None = None) -> dict:
    """The extracted front-end table (written by scripts/fmdb_ui_frontend.py); without a path,
    the running build's (`active_source`)."""
    if path is None:
        return table()
    with gzip.open(path, "rt") as f:
        return json.load(f)


_CACHED: dict | None = None


def table() -> dict:
    """The running build's front-end table (`active_source`), loaded once."""
    global _CACHED
    if _CACHED is None:
        source = active_source()
        data = load_table(Path(source["path"]))
        if not source["per_build"] and source["note"]:
            data = _pinned_on_mapped_build(data)
        data["_source"] = source
        _CACHED = data
    return _CACHED


def _pinned_on_mapped_build(data: dict) -> dict:
    """The shipped table on a mapped build without its own: parameter globals are plugin
    addresses of the pinned build; keep those the address map translates, drop the others."""
    from .. import address_book
    params, dropped = {}, []
    for name, rva in (data.get("plugin_params") or {}).items():
        pinned = int(rva, 16) if isinstance(rva, str) else int(rva)
        new = address_book._VALUES.get(pinned)
        if isinstance(new, int):
            params[name] = f"{new:#x}"
        else:
            dropped.append(name)
    data = dict(data, plugin_params=params)
    data["_plugin_params_dropped"] = sorted(dropped)
    return data


def note() -> str | None:
    """The fallback note of `active_source`, or None when the running build has its own table."""
    return table()["_source"]["note"]


def reset() -> None:
    """Forget the loaded table (tests)."""
    global _CACHED
    _CACHED = None


def diff_tables(old: dict, new: dict, limit: int = 60) -> dict:
    """What differs between two front-end tables (two builds): registry keys added, removed and
    relabelled; data collections whose translation ids or keys changed (with both); record
    schemas, views and table factories added or removed; screen-parameter names added or removed
    (their globals always move with the plugin); UI record ids renumbered."""
    def keyed(name):
        return old.get(name) or {}, new.get(name) or {}

    out = {"build": {"old": old.get("build"), "new": new.get("build")}}
    a, b = keyed("registry")
    out["registry"] = {"old": len(a), "new": len(b),
                       "added": dict(sorted((k, b[k]) for k in set(b) - set(a))[:limit]),
                       "added_count": len(set(b) - set(a)),
                       "removed": dict(sorted((k, a[k]) for k in set(a) - set(b))[:limit]),
                       "removed_count": len(set(a) - set(b)),
                       "relabelled": {k: [a[k], b[k]] for k in sorted(set(a) & set(b)) if a[k] != b[k]}}
    a, b = keyed("data_collections")
    changed = {}
    for name in sorted(set(a) & set(b)):
        x, y = a[name], b[name]
        if x.get("translations") != y.get("translations") or x.get("keys") != y.get("keys"):
            changed[name] = {"old": {k: x.get(k) for k in ("keys", "translations")},
                             "new": {k: y.get(k) for k in ("keys", "translations")}}
    ids_old = {i for c in a.values() for i in c.get("translations") or ()}
    ids_new = {i for c in b.values() for i in c.get("translations") or ()}
    out["data_collections"] = {"old": len(a), "new": len(b), "added": sorted(set(b) - set(a))[:limit],
                               "removed": sorted(set(a) - set(b))[:limit], "changed": changed,
                               "translation_ids_added": sorted(ids_new - ids_old)[:limit],
                               "translation_ids_removed": sorted(ids_old - ids_new)[:limit],
                               "translation_ids": {"old": len(ids_old), "new": len(ids_new),
                                                   "added": len(ids_new - ids_old),
                                                   "removed": len(ids_old - ids_new)}}
    for name in ("records", "views", "tables"):
        a, b = keyed(name)
        changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])
        out[name] = {"old": len(a), "new": len(b), "added": sorted(set(b) - set(a))[:limit],
                     "removed": sorted(set(a) - set(b))[:limit], "changed_count": len(changed),
                     "changed": changed[:limit]}
    a, b = keyed("plugin_params")
    out["plugin_params"] = {"old": len(a), "new": len(b), "added": sorted(set(b) - set(a)),
                            "removed": sorted(set(a) - set(b))}
    a, b = keyed("ui_record_ids")
    out["ui_record_ids"] = {"added": sorted(set(b) - set(a)), "removed": sorted(set(a) - set(b)),
                            "renumbered": {k: [a[k], b[k]] for k in sorted(set(a) & set(b)) if a[k] != b[k]}}
    return out


def property_label(key: str, data: dict | None = None) -> str | None:
    return (data or table())["registry"].get(key)


def property_key(label: str, data: dict | None = None) -> list[str]:
    return [k for k, v in (data or table())["registry"].items() if v == label]


def views_binding(label: str, data: dict | None = None) -> list[str]:
    """Views whose bindings end in `.label` (or are `label`)."""
    data = data or table()
    out = []
    for name, view in data.get("views", {}).items():
        if any(b == label or b.endswith("." + label) for b in view.get("bindings", ())):
            out.append(name)
    return sorted(out)


def describe(*, search=None, view=None, record=None, parameter=None, limit=40) -> dict:
    """Offline lookup over the front-end table (the fm_ui_frontend tool)."""
    data = table()
    out: dict = {"counts": {k: len(data.get(k, {})) for k in
                            ("registry", "records", "views", "tables", "data_collections", "plugin_params")},
                 "source": data.get("_source")}
    if view:
        hits = {n: v for n, v in data.get("views", {}).items() if view.lower() in n.lower()}
        out["views"] = dict(list(sorted(hits.items()))[:limit])
    if record:
        rec = data.get("records", {}).get(record)
        if rec is None:
            rec = next(({"id": k, **v} for k, v in data.get("records", {}).items()
                        if record.lower() in v["class"].lower()), None)
        if rec is not None:
            rec = dict(rec)
            rec["labels"] = {k: data["registry"].get(k) for k in rec.get("properties", ())}
        out["record"] = rec
    if parameter:
        p = parameter.lower()
        views = {n: v["params"][k] for n, v in data.get("views", {}).items()
                 for k in v.get("params", {}) if k.lower() == p}
        params = data.get("plugin_params", {})
        out["parameter"] = {"plugin_global": params.get(p) or params.get(parameter),
                            "views": dict(sorted(views.items())[:limit])}
    if search:
        s = search.lower()
        keys = [{"key": k, "label": v} for k, v in data["registry"].items() if s in v.lower() or s == k.lower()]
        out["properties"] = keys[:limit]
        labels = {row["label"] for row in keys[:limit]}
        out["bound_by_views"] = {lab: views_binding(lab, data)[:limit] for lab in sorted(labels)}
        out["records_with_property"] = sorted(
            rid for rid, r in data.get("records", {}).items()
            if any(row["key"] in r.get("properties", ()) for row in keys[:limit]))[:limit]
        out["data_collections"] = {n: c for n, c in data.get("data_collections", {}).items()
                                   if s in n.lower()}
    return out
