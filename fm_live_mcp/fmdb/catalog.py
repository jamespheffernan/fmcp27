"""Typed schema catalog parsed offline from Football Manager's ``editor.fmf``.

``editor.fmf`` is an archive of XML definition files (the editor's field
definitions, filter and column layouts, named enums). This module decodes the
container and turns the definitions into a catalog of record types and fields
without needing the running game.

Container format (decoded from the shipped file, see ``parse_container``)::

    offset 0   02 01 'fmf.' 08 00 00      9-byte preamble
    offset 9   u64 dir_rel                directory chunk starts at 9 + dir_rel
    offset 17  u64 data_rel               data (first frame) starts at 9 + data_rel (= 26)
    offset 25  u8  3                      not interpreted
    26...      concatenated Zstandard frames, one per archived file, back to back
    dir chunk  the same 9-byte preamble followed by one more Zstandard frame

The directory frame decompresses to a little-endian tree::

    dir   := str(name) u32(nfiles) file* u32(ndirs) dir*
    file  := str(stem) str(ext) u64(offset) u64(compressed) u64(size) u64(t1) u64(t2)
    str   := u32(length) utf-8 bytes

``offset`` is relative to the data start. Paths are ``dir/dir/stem+ext``.

If the directory cannot be decoded the parser falls back to scanning for the
Zstandard magic number; ``Catalog.container["mode"]`` says which was used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
import threading
import xml.etree.ElementTree as ET
from collections import Counter
from compression.zstd import ZstdDecompressor
from dataclasses import dataclass, field as _dc_field, replace
from pathlib import Path
from typing import Any, Iterable, Iterator

from fm_live_mcp import build_paths  # noqa: E402

# The installed build's editor.fmf (run time; FMCP_PLUGIN_PATH names the installed plugin).
DEFAULT_EDITOR_FMF = build_paths.installed_app() / (
    "Contents/PlugIns/game_plugin.bundle/Contents/Resources/shared/data/editor.fmf"
)
EDITOR_FMF_RELATIVE = Path("Contents/Resources/shared/data/editor.fmf")

_PREAMBLE = b"\x02\x01fmf.\x08\x00\x00"
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
_MAX_FRAME_OUTPUT = 20_000_000
DIRECTORY_FRAME_NAME = "<directory>"

REFERENCE_TYPES = frozenset({"database_record_unique_id", "database_record_list", "database_table"})
ENUM_TYPES = frozenset({"enum", "multiple_enum"})
DEPENDENCY_LIST_IDS = frozenset(
    {"dependencies", "or_dependencies", "read_only_dependencies", "visible_or_dependencies"}
)


class CatalogError(ValueError):
    """The archive could not be decoded."""


class _ContainerError(CatalogError):
    pass


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FrameInfo:
    index: int
    name: str
    offset: int
    compressed_size: int
    size: int
    mtime: int | None
    mtime2: int | None
    record_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Field:
    code: str
    name: str | None
    comment: str | None
    type: str | None
    min_value: int | float | str | None
    max_value: int | float | str | None
    enum: dict[int, str] | None
    references: str | None
    item_fields: dict[str, "Field"] | None
    category: str | None
    dependencies: tuple[dict[str, Any], ...]
    flags: dict[str, Any]
    extra: dict[str, Any]
    translation_id: int | None = None
    hint: str | None = None
    enum_ref: str | None = None
    item_view: str | None = None
    item_field_list: tuple["Field", ...] | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"code": self.code}
        for key in ("name", "comment", "type", "min_value", "max_value", "references",
                    "category", "hint", "enum_ref", "item_view", "translation_id"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        if self.enum is not None and self.enum_ref is None:  # registry labels live in Catalog.enums
            out["enum"] = {str(k): self.enum[k] for k in sorted(self.enum)}
        if self.item_fields is not None:
            out["item_fields"] = {c: self.item_fields[c].to_json() for c in sorted(self.item_fields)}
            out["item_order"] = [f.code for f in (self.item_field_list or ())]
        if self.dependencies:
            out["dependencies"] = [_sorted_json(d) for d in self.dependencies]
        if self.flags:
            out["flags"] = {k: self.flags[k] for k in sorted(self.flags)}
        if self.extra:
            out["extra"] = _sorted_json(self.extra)
        return out


@dataclass(frozen=True, slots=True)
class RecordType:
    code: str
    comment: str | None
    fields: dict[str, Field]
    frame_index: int
    field_list: tuple[Field, ...] = ()
    extra: dict[str, Any] = _dc_field(default_factory=dict)

    @property
    def duplicates(self) -> dict[str, tuple[Field, ...]]:
        """Codes defined more than once in this record type (all definitions)."""
        grouped: dict[str, list[Field]] = {}
        for f in self.field_list:
            grouped.setdefault(f.code, []).append(f)
        return {c: tuple(v) for c, v in grouped.items() if len(v) > 1}


@dataclass(frozen=True, slots=True)
class ViewEntry:
    """One ``db_field="table,CODE"`` row of a filter, column or layout list.

    ``section`` is the chain of layout section titles enclosing the row (empty for
    flat filter/column lists); ``attrs`` keeps every other attribute and child.
    """

    record_type: str
    code: str
    attrs: dict[str, Any]
    section: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FieldScope:
    """One definition of a code. ``path`` is the chain of enclosing list-field codes."""

    record_type: str
    path: tuple[str, ...]
    field: Field

    @property
    def scope(self) -> str:
        return "/".join((self.record_type, *self.path, self.field.code))


@dataclass(frozen=True, slots=True)
class Catalog:
    sha256: str
    frames: tuple[FrameInfo, ...]
    record_types: dict[str, RecordType]
    views: dict[str, list[tuple[str, str]]]
    view_entries: dict[str, tuple[ViewEntry, ...]]
    view_comments: dict[str, str]
    view_includes: dict[str, tuple[str, ...]]
    sections: dict[str, tuple[dict[str, Any], ...]]
    enums: dict[str, dict[int, str]]
    enum_comments: dict[str, dict[int, str]]
    stub_enums: tuple[str, ...]
    table_types: dict[str, tuple[str, ...]]
    table_type_ids: dict[str, int]
    table_layouts: dict[str, str]
    config: dict[str, dict[str, Any]]
    container: dict[str, Any]
    report: dict[str, Any]
    source_path: str | None = None

    # -- navigation -----------------------------------------------------
    def iter_fields(self) -> Iterator[FieldScope]:
        """Every field definition, including nested list items, in definition order."""
        for rt in self.record_types.values():
            yield from _walk(rt.code, (), rt.field_list)

    def find(self, code: str) -> list[FieldScope]:
        """Every scope that defines ``code`` (case-sensitive: codes like ``Pcst`` vs ``PCST`` differ)."""
        return [s for s in self.iter_fields() if s.field.code == code]

    def search(self, text: str) -> list[FieldScope]:
        """Case-insensitive substring search over code, name, comment, hint and category."""
        needle = text.casefold()
        hits = []
        for scope in self.iter_fields():
            f = scope.field
            haystack = (f.code, f.name, f.comment, f.hint, f.category)
            if any(h and needle in h.casefold() for h in haystack):
                hits.append(scope)
        return hits

    def field(self, record_type: str, code: str) -> Field | None:
        rt = self.record_types.get(record_type)
        return rt.fields.get(code) if rt else None

    def resolve_table(self, table_type: str) -> tuple[str, ...]:
        """Record types describing a ``database_table_type`` name such as ``club``."""
        return self.table_types.get(table_type, ())

    def codes(self) -> set[str]:
        return {s.field.code for s in self.iter_fields()}

    # -- export ---------------------------------------------------------
    def to_json(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "container": _sorted_json(self.container),
            "frames": [
                {
                    "index": fr.index, "name": fr.name, "offset": fr.offset,
                    "compressed_size": fr.compressed_size, "size": fr.size,
                    "mtime": fr.mtime, "mtime2": fr.mtime2, "record_ids": list(fr.record_ids),
                }
                for fr in self.frames
            ],
            "record_types": {
                code: {
                    "code": rt.code,
                    "comment": rt.comment,
                    "frame_index": rt.frame_index,
                    "fields": {c: rt.fields[c].to_json() for c in sorted(rt.fields)},
                    "order": [f.code for f in rt.field_list],
                    "duplicates": {c: [f.to_json() for f in v] for c, v in sorted(rt.duplicates.items())},
                    "extra": _sorted_json(rt.extra),
                }
                for code, rt in sorted(self.record_types.items())
            },
            "views": {k: [list(p) for p in v] for k, v in sorted(self.views.items())},
            "view_entries": {
                k: [
                    {"record_type": e.record_type, "code": e.code, "attrs": _sorted_json(e.attrs),
                     **({"section": list(e.section)} if e.section else {})}
                    for e in v
                ]
                for k, v in sorted(self.view_entries.items())
            },
            "view_comments": dict(sorted(self.view_comments.items())),
            "view_includes": {k: list(v) for k, v in sorted(self.view_includes.items())},
            "sections": {k: _sorted_json(v) for k, v in sorted(self.sections.items())},
            "stub_enums": sorted(self.stub_enums),
            "enums": {k: {str(n): v[n] for n in sorted(v)} for k, v in sorted(self.enums.items())},
            "enum_comments": {
                k: {str(n): v[n] for n in sorted(v)} for k, v in sorted(self.enum_comments.items())
            },
            "table_types": {k: list(v) for k, v in sorted(self.table_types.items())},
            "table_type_ids": dict(sorted(self.table_type_ids.items())),
            "table_layouts": dict(sorted(self.table_layouts.items())),
            "config": _sorted_json(self.config),
            "report": _sorted_json(self.report),
        }

    def summary(self) -> dict[str, Any]:
        scopes = list(self.iter_fields())
        hist = Counter(s.field.type for s in scopes)
        per_total = Counter(s.record_type for s in scopes)
        return {
            "frames": len(self.frames),
            "record_types": len(self.record_types),
            "fields_per_record_type": {c: len(rt.field_list) for c, rt in self.record_types.items()},
            "definitions_per_record_type_incl_nested": {c: per_total.get(c, 0) for c in self.record_types},
            "unique_codes": len(self.codes()),
            "type_histogram": dict(hist.most_common()),
            "views": {k: len(v) for k, v in self.views.items()},
            "enums": len(self.enums),
            "container": self.container,
            "report": self.report,
        }


def _walk(record_type: str, path: tuple[str, ...], fields: Iterable[Field]) -> Iterator[FieldScope]:
    for f in fields:
        yield FieldScope(record_type, path, f)
        if f.item_field_list:
            yield from _walk(record_type, (*path, f.code), f.item_field_list)


def _sorted_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _sorted_json(value[k]) for k in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_sorted_json(v) for v in value]
    return value


# --------------------------------------------------------------------------
# Container
# --------------------------------------------------------------------------


def _decompress_exact(data: bytes | memoryview, start: int, end: int | None = None) -> tuple[bytes, int]:
    """Decompress one frame starting at ``start``; returns (output, bytes consumed)."""
    view = memoryview(data)[start:end]
    dec = ZstdDecompressor()
    try:
        out = dec.decompress(view, max_length=_MAX_FRAME_OUTPUT)
    except Exception as exc:  # compression.zstd.ZstdError
        raise _ContainerError(f"zstd frame at {start} did not decompress: {exc}") from exc
    if not dec.eof:
        raise _ContainerError(f"zstd frame at {start} is truncated or exceeds the size limit")
    return out, len(view) - len(dec.unused_data)


class _Reader:
    def __init__(self, buf: bytes) -> None:
        self.buf, self.pos = buf, 0

    def u32(self) -> int:
        (v,) = struct.unpack_from("<I", self.buf, self.pos)
        self.pos += 4
        return v

    def u64(self) -> int:
        (v,) = struct.unpack_from("<Q", self.buf, self.pos)
        self.pos += 8
        return v

    def string(self) -> str:
        n = self.u32()
        if self.pos + n > len(self.buf):
            raise _ContainerError("directory string overruns the buffer")
        v = self.buf[self.pos:self.pos + n].decode("utf-8")
        self.pos += n
        return v


def _parse_directory(buf: bytes) -> list[dict[str, Any]]:
    rd = _Reader(buf)
    entries: list[dict[str, Any]] = []

    def directory(prefix: str, depth: int) -> None:
        if depth > 32:
            raise _ContainerError("directory tree too deep")
        name = rd.string()
        path = f"{prefix}{name}/"
        for _ in range(rd.u32()):
            stem, ext = rd.string(), rd.string()
            entries.append({
                "name": f"{path}{stem}{ext}", "offset": rd.u64(), "compressed": rd.u64(),
                "size": rd.u64(), "t1": rd.u64(), "t2": rd.u64(),
            })
        for _ in range(rd.u32()):
            directory(path, depth + 1)

    try:
        directory("", 0)
    except (struct.error, UnicodeDecodeError) as exc:
        raise _ContainerError(f"directory frame is malformed: {exc}") from exc
    if rd.pos != len(buf):
        raise _ContainerError(f"directory frame has {len(buf) - rd.pos} unparsed trailing bytes")
    return entries


def _container_from_directory(data: bytes) -> tuple[list[tuple[FrameInfo, bytes]], dict[str, Any]]:
    if data[:9] != _PREAMBLE:
        raise _ContainerError("missing fmf preamble")
    dir_rel, data_rel = struct.unpack_from("<QQ", data, 9)
    flag = data[25]
    data_start, dir_chunk = 9 + data_rel, 9 + dir_rel
    if not (26 <= data_start < dir_chunk < len(data)) or data[dir_chunk:dir_chunk + 9] != _PREAMBLE:
        raise _ContainerError("directory chunk not where the header says")
    dir_start = dir_chunk + 9
    dir_xml, used = _decompress_exact(data, dir_start)
    if dir_start + used != len(data):
        raise _ContainerError("directory frame does not end at end of file")
    entries = sorted(_parse_directory(dir_xml), key=lambda e: e["offset"])
    frames: list[tuple[FrameInfo, bytes]] = []
    cursor = data_start
    for i, e in enumerate(entries):
        start = data_start + e["offset"]
        if start != cursor or data[start:start + 4] != _ZSTD_MAGIC:
            raise _ContainerError(f"frame {e['name']!r} is not contiguous with its predecessor")
        out, used = _decompress_exact(data, start, start + e["compressed"])
        if used != e["compressed"] or len(out) != e["size"]:
            raise _ContainerError(f"frame {e['name']!r} size mismatch with the directory")
        cursor = start + e["compressed"]
        frames.append((FrameInfo(i, e["name"], start, e["compressed"], len(out), e["t1"], e["t2"], ()), out))
    if cursor != dir_chunk:
        raise _ContainerError("frames do not tile the data region")
    i = len(frames)
    frames.append((FrameInfo(i, DIRECTORY_FRAME_NAME, dir_start, used, len(dir_xml), None, None, ()), dir_xml))
    meta = {
        "mode": "directory", "header_flag": flag, "data_start": data_start,
        "directory_chunk": dir_chunk, "files": len(entries),
    }
    return frames, meta


def _container_from_magic_scan(data: bytes) -> tuple[list[tuple[FrameInfo, bytes]], dict[str, Any]]:
    frames: list[tuple[FrameInfo, bytes]] = []
    pos = 0
    while (start := data.find(_ZSTD_MAGIC, pos)) >= 0:
        try:
            out, used = _decompress_exact(data, start)
        except _ContainerError:
            pos = start + 1
            continue
        frames.append((FrameInfo(len(frames), f"frame-{len(frames)}", start, used, len(out), None, None, ()), out))
        pos = start + used
    if not frames:
        raise CatalogError("no Zstandard frames found")
    return frames, {"mode": "magic-scan", "files": len(frames)}


def parse_container(data: bytes) -> tuple[list[tuple[FrameInfo, bytes]], dict[str, Any]]:
    """Split an ``.fmf`` archive into (frame info, decompressed XML bytes) pairs.

    Uses the directory when it is consistent with the data, otherwise falls back
    to scanning for the Zstandard magic number.
    """
    try:
        return _container_from_directory(data)
    except _ContainerError as exc:
        frames, meta = _container_from_magic_scan(data)
        meta["directory_error"] = str(exc)
        return frames, meta


# --------------------------------------------------------------------------
# XML helpers
# --------------------------------------------------------------------------

_COMMENT_MARK = "[COMMENT"


def split_comment(text: str | None) -> tuple[str | None, str | None]:
    """Split ``"Name[COMMENT: note]"`` into ``("Name", "note")``.

    The shipped data uses ``[COMMENT: ...]``, ``[COMMENT; ...]`` and ``[COMMENT - ...]``.
    """
    if text is None:
        return None, None
    i = text.find(_COMMENT_MARK)
    if i < 0:
        return text.strip(), None
    clean = text[:i].strip()
    rest = text[i + len(_COMMENT_MARK):].rstrip()
    if rest.endswith("]"):
        rest = rest[:-1]
    rest = rest.lstrip(" \t:;-").strip()
    return clean, rest or None


def _parse_xml(raw: bytes) -> ET.Element:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    parser.feed(raw.decode("utf-8-sig"))
    return parser.close()


def _kids(e: ET.Element) -> list[ET.Element]:
    return [c for c in e if isinstance(c.tag, str)]


def _num(text: str | None) -> int | float | str | None:
    if text is None:
        return None
    t = text.strip()
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        return text


def _int(text: str | None) -> int | None:
    try:
        return int(text.strip(), 0) if text is not None else None
    except ValueError:
        return None


def _bool(text: str | None) -> bool | str | None:
    if text is None:
        return None
    low = text.strip().lower()
    if low == "true":
        return True
    if low == "false":
        return False
    return text


_CODE_IDS = ("field", "field_id")


def _has_code(rec: ET.Element) -> bool:
    """A record defines a field if it names a code (several spellings) or carries an ``id``."""
    if rec.get("field_id") or rec.get("id"):
        return True
    return any(_spells_code(k) for k in _kids(rec))


def _spells_code(k: ET.Element) -> bool:
    """``<flags id="field">``, ``<integer id="field">`` and ``<integer id="id">`` all name the code."""
    cid = k.get("id")
    if k.tag == "flags":
        return cid in _CODE_IDS
    return k.tag in ("integer", "string") and cid in (*_CODE_IDS, "id")


def _plain(e: ET.Element) -> dict[str, Any]:
    """Lossless JSON-able rendering of an element we do not interpret."""
    out: dict[str, Any] = {"tag": e.tag}
    out.update(e.attrib)
    kids = _kids(e)
    if kids:
        out["children"] = [_plain(c) for c in kids]
    return out


class _Parser:
    """One-shot builder; collects the catalog pieces and a parse report."""

    def __init__(self) -> None:
        self.record_types: dict[str, RecordType] = {}
        self.view_entries: dict[str, list[ViewEntry]] = {}
        self.view_comments: dict[str, str] = {}
        self.view_includes: dict[str, list[str]] = {}
        self.sections: dict[str, list[dict[str, Any]]] = {}
        self.stubs: list[str] = []
        self.enums: dict[str, dict[int, str]] = {}
        self.enum_comments: dict[str, dict[int, str]] = {}
        self.config: dict[str, dict[str, Any]] = {}
        self.trees: dict[int, ET.Element] = {}
        self.seen: set[int] = set()
        self.frame_index = 0
        self.r: Counter[str] = Counter()
        self.unparsed: Counter[str] = Counter()
        self.kept_raw: Counter[str] = Counter()
        self.notes: list[str] = []

    # -- bookkeeping ----------------------------------------------------
    def mark(self, e: ET.Element, deep: bool = False) -> None:
        if deep:
            for x in e.iter():
                if isinstance(x.tag, str):
                    self.seen.add(id(x))
        else:
            self.seen.add(id(e))

    def raw(self, e: ET.Element, owner: str) -> dict[str, Any]:
        self.mark(e, deep=True)
        self.kept_raw[f"{e.tag}:{e.get('id') or ''}"] += 1
        return _plain(e)

    # -- frames ---------------------------------------------------------
    def load(self, index: int, xml: bytes) -> None:
        """Pass 1: parse the XML and register named enums, so later field definitions can resolve them."""
        self.frame_index = index
        root = _parse_xml(xml)
        self.trees[index] = root
        for rec in root:
            if not (isinstance(rec.tag, str) and rec.tag == "record" and rec.get("id")):
                continue
            kids = _kids(rec)
            has_fields = any(k.tag == "list" and k.get("id") == "fields" for k in kids)
            enum_list = next((k for k in kids if k.tag == "list" and k.get("id") == "enum_values"), None)
            if enum_list is not None and not has_fields:
                self.mark(enum_list)
                labels, comments, _ = self.enum_labels(enum_list)
                code = rec.get("id")
                if code in self.enums:
                    self.notes.append(f"enum {code!r} defined more than once; first kept")
                else:
                    self.enums[code] = labels
                    if comments:
                        self.enum_comments[code] = comments

    def frame(self, index: int) -> list[str]:
        """Pass 2: definitions, views and layouts."""
        self.frame_index = index
        root = self.trees.pop(index)
        self.mark(root)
        ids: list[str] = []
        last_comment: str | None = None
        for child in root:
            if not isinstance(child.tag, str):
                last_comment = (child.text or "").strip() or None
                continue
            if child.tag == "record" and child.get("id"):
                self.root_record(child, last_comment)
                ids.append(child.get("id"))
                last_comment = None
            elif child.tag in ("boolean", "integer", "string", "flags", "real") and child.get("id"):
                self.mark(child)
                cfg = self.config.setdefault(str(index), {})
                cfg[child.get("id")] = _bool(child.get("value")) if child.tag == "boolean" else child.get("value")
            else:
                self.raw(child, "frame")
        for x in root.iter():
            if isinstance(x.tag, str) and id(x) not in self.seen:
                self.unparsed[x.tag] += 1
                if len(self.notes) < 10:
                    self.notes.append(f"frame {index}: unparsed <{x.tag}> {dict(x.attrib)}")
        return ids

    def root_record(self, rec: ET.Element, comment: str | None) -> None:
        code = rec.get("id")
        self.mark(rec)
        kids = _kids(rec)
        fields_list = next((k for k in kids if k.tag == "list" and k.get("id") == "fields"), None)
        enum_list = next((k for k in kids if k.tag == "list" and k.get("id") == "enum_values"), None)
        meta: dict[str, Any] = {}
        for k in kids:
            if k is fields_list or k is enum_list:
                continue
            self.record_meta(k, meta)
        attrs = {a: v for a, v in rec.attrib.items() if a != "id"}
        if attrs:
            meta["attrs"] = attrs
        if enum_list is not None and fields_list is None:
            # labels were registered in pass 1
            if meta:
                self.record_types.setdefault(code, RecordType(code, comment, {}, self.frame_index, (), meta))
            return
        if fields_list is None:
            if not meta and not _kids(rec):
                self.stubs.append(code)  # declared by name only; labels live in the game database
                return
            self.record_types[code] = RecordType(code, comment, {}, self.frame_index, (), meta)
            self.r["root_records_without_fields_list"] += 1
            return
        self.mark(fields_list)
        view: list[ViewEntry] = []
        defs: list[Field] = []
        includes: list[str] = []
        self.fields_list(fields_list, code, (code,), (), view, defs, includes, meta)
        if view:
            self.view_entries[code] = view
            if comment:
                self.view_comments[code] = comment
        if includes:
            self.view_includes[code] = includes
        if defs or not (view or includes):
            first: dict[str, Field] = {}
            for f in defs:
                first.setdefault(f.code, f)
            self.record_types[code] = RecordType(code, comment, first, self.frame_index, tuple(defs), meta)
        if (view or includes) and defs:
            self.r["records_mixing_views_and_definitions"] += 1

    def fields_list(self, lst: ET.Element, scope: str, path: tuple[str, ...], section: tuple[str, ...],
                    view: list[ViewEntry], defs: list[Field], includes: list[str], meta: dict[str, Any]) -> None:
        """Walk a ``fields`` list: field definitions, ``db_field`` rows, nested layout sections.

        ``scope`` keys section metadata (a record id, or ``record/field`` for list items);
        ``path`` is the chain of enclosing codes used for field scoping.
        """
        for item in lst:
            if not isinstance(item.tag, str):
                continue
            if item.tag != "record":
                meta.setdefault("unparsed", []).append(self.raw(item, scope))
                continue
            nested = next((k for k in _kids(item) if k.tag == "list" and k.get("id") == "fields"), None)
            if "db_field" in item.attrib:
                entry = self.view_entry(item, section)
                if entry:
                    view.append(entry)
            elif _has_code(item):
                f = self.field(item, path, section)
                if f:
                    defs.append(f)
            elif "insert_fields" in item.attrib:
                self.mark(item)
                includes.append(item.get("insert_fields"))
                rest = {a: v for a, v in item.attrib.items() if a != "insert_fields"}
                if rest or _kids(item):
                    meta.setdefault("insert_fields_attrs", {})[item.get("insert_fields")] = {
                        **rest, **({"children": [self.raw(k, scope) for k in _kids(item)]} if _kids(item) else {})}
            elif nested is not None:
                # a layout section: no code of its own; carries a title, flags and dependencies
                self.mark(item)
                self.mark(nested)
                props: dict[str, Any] = {}
                for k in _kids(item):
                    if k is not nested:
                        self.record_meta(k, props)
                attrs = {a: v for a, v in item.attrib.items()}
                if attrs:
                    props["attrs"] = attrs
                title = props.get("name") if isinstance(props.get("name"), str) else None
                title = title or "?"
                self.sections.setdefault(scope, []).append({"path": [*section, title], "props": props})
                self.r["layout_sections"] += 1
                self.fields_list(nested, scope, path, (*section, title), view, defs, includes, meta)
            else:
                self.r["field_records_without_code"] += 1
                self.notes.append(f"frame {self.frame_index}: record without code or fields under {scope}: "
                                  f"{json.dumps(_plain(item))[:200]}")
                meta.setdefault("unparsed", []).append(self.raw(item, scope))

    def record_meta(self, k: ET.Element, meta: dict[str, Any]) -> None:
        """Record-level (non-field) children, e.g. the file section header in ``fmat``."""
        key = k.get("id") or k.tag
        self.mark(k)
        if k.tag == "translation":
            clean, comment = split_comment(k.get("value"))
            meta[key] = clean
            if comment:
                meta[f"{key}_comment"] = comment
        elif k.tag == "boolean":
            meta[key] = _bool(k.get("value"))
        elif k.tag in ("flags", "string", "integer", "real"):
            meta[key] = k.get("value") if k.tag != "integer" else _num(k.get("value"))
        elif k.tag == "list" and k.get("id") in DEPENDENCY_LIST_IDS:
            meta.setdefault(key, []).extend(self.dependency_list(k))
        else:
            self.mark(k, deep=True)
            self.kept_raw[f"{k.tag}:{k.get('id') or ''}"] += 1
            meta[key] = _plain(k)

    # -- views ----------------------------------------------------------
    def view_entry(self, rec: ET.Element, section: tuple[str, ...] = ()) -> ViewEntry | None:
        self.mark(rec)
        ref = rec.get("db_field", "")
        table, _, code = ref.partition(",")
        table, code = table.strip(), code.strip()
        if not table or not code:
            self.r["view_entries_malformed"] += 1
            self.mark(rec, deep=True)
            return None
        attrs: dict[str, Any] = {a: v for a, v in rec.attrib.items() if a != "db_field"}
        if f"{table},{code}" != ref:
            attrs["db_field_raw"] = ref
        for k in _kids(rec):
            self.mark(k)
            if k.tag == "translation":
                clean, comment = split_comment(k.get("value"))
                attrs[k.get("id") or "name"] = clean
                if comment:
                    attrs[f"{k.get('id') or 'name'}_comment"] = comment
            else:
                attrs[k.get("id") or k.tag] = self.raw(k, "view")
        self.r["view_entries"] += 1
        return ViewEntry(table, code, attrs, section)

    # -- enums ----------------------------------------------------------
    def enum_labels(self, lst: ET.Element) -> tuple[dict[int, str], dict[int, str], dict[int, Any]]:
        labels: dict[int, str] = {}
        comments: dict[int, str] = {}
        extras: dict[int, Any] = {}
        for rec in _kids(lst):
            self.mark(rec)
            n = _int(rec.get("enum")) if rec.tag == "record" else None
            symbol = None
            if n is None and rec.tag == "record" and rec.get("enum") is not None:
                n = _int(rec.get("enum_id"))  # symbolic key such as enum="male" enum_id="0"
                symbol = rec.get("enum")
            if n is None:
                self.r["enum_entries_unparsed"] += 1
                extras.setdefault("unparsed", []).append(self.raw(rec, "enum"))
                continue
            if symbol is not None:
                extras.setdefault(n, {})["key"] = symbol
                self.r["enum_entries_with_symbolic_key"] += 1
            label = None
            for k in _kids(rec):
                self.mark(k)
                if k.get("id") == "name" and k.tag in ("translation", "string", "flags"):
                    label, comment = split_comment(k.get("value"))
                    if comment:
                        comments[n] = comment
                    if k.tag == "translation" and k.get("translation_id"):
                        extras.setdefault(n, {})["translation_id"] = _int(k.get("translation_id"))
                else:
                    extras.setdefault(n, {})[k.get("id") or k.tag] = self.raw(k, "enum")
            attrs = {a: v for a, v in rec.attrib.items() if a != "enum"}
            if symbol is not None or attrs.get("enum_id") == rec.get("enum"):
                attrs.pop("enum_id", None)
            elif "enum_id" in attrs:
                self.r["enum_id_differs_from_enum"] += 1
            if attrs:
                extras.setdefault(n, {})["attrs"] = attrs
            if n in labels:
                self.r["enum_duplicate_values"] += 1
                continue
            if label is None:
                self.r["enum_entries_without_label"] += 1
                label = ""
            labels[n] = label
        return labels, comments, extras

    # -- fields ---------------------------------------------------------
    def field(self, rec: ET.Element, path: tuple[str, ...], section: tuple[str, ...] = ()) -> Field | None:
        self.mark(rec)
        code: str | None = None
        name = comment = category = hint = None
        translation_id: int | None = None
        ftype: str | None = None
        min_v: Any = None
        max_v: Any = None
        enum: dict[int, str] | None = None
        enum_ref: str | None = None
        table_type: str | None = None
        fields_ref: str | None = None
        item_fields: dict[str, Field] | None = None
        item_list: list[Field] | None = None
        item_view: str | None = None
        deps: list[dict[str, Any]] = []
        flags: dict[str, Any] = {}
        extra: dict[str, Any] = {}

        for c in _kids(rec):
            tag, cid, val = c.tag, c.get("id"), c.get("value")
            if tag == "flags":
                self.mark(c)
                if cid in _CODE_IDS:
                    code = val
                elif cid == "type":
                    ftype = val
                elif cid == "name":
                    name, comment = split_comment(val)
                elif cid == "enum_values":
                    enum_ref = val
                elif cid == "database_table_type":
                    table_type = val
                elif cid == "fields":
                    fields_ref = val
                elif cid == "min_value":
                    min_v = _num(val)
                elif cid == "max_value":
                    max_v = _num(val)
                elif _bool(val) in (True, False) and cid:
                    flags[cid] = _bool(val)
                elif cid:
                    extra[cid] = val
                else:
                    extra.setdefault("unnamed", []).append(_plain(c))
            elif tag == "translation":
                self.mark(c)
                clean, cm = split_comment(val)
                if cid == "name":
                    name, comment = clean, cm
                    translation_id = _int(c.get("translation_id"))
                elif cid == "category":
                    category = clean
                    if cm:
                        extra["category_comment"] = cm
                elif cid == "hint":
                    hint = clean
                    if cm:
                        extra["hint_comment"] = cm
                else:
                    extra[f"{cid}"] = {"value": clean, **({"comment": cm} if cm else {}),
                                       **({"translation_id": _int(c.get("translation_id"))} if c.get("translation_id") else {})}
                odd = {a: v for a, v in c.attrib.items() if a not in ("id", "value", "translation_id", "type")}
                if c.get("type") not in (None, "use"):
                    odd["type"] = c.get("type")
                if odd:
                    extra.setdefault("translation_attrs", {})[cid or "?"] = odd
            elif tag == "translation_list":
                self.mark(c, deep=True)
                items = []
                for t in _kids(c):
                    clean, cm = split_comment(t.get("value"))
                    items.append({"value": clean, **({"comment": cm} if cm else {}),
                                  **({"translation_id": _int(t.get("translation_id"))} if t.get("translation_id") else {})})
                extra[cid or "translation_list"] = items
            elif tag == "boolean":
                self.mark(c)
                flags[cid or "?"] = _bool(val) if val is not None else True
                if val is None:
                    self.r["boolean_without_value_taken_as_true"] += 1
            elif tag in ("integer", "real", "float", "string"):
                self.mark(c)
                if cid in ("min_value", "max_value") and val is not None:
                    v = _num(val)
                    if cid == "min_value":
                        min_v = v
                    else:
                        max_v = v
                elif _spells_code(c):
                    code = val  # a few definitions spell the code as <integer id="field" value="Natt"/>
                elif tag == "string" and cid == "name":
                    name, comment = split_comment(val)
                elif tag == "string" and cid == "hint":
                    hint, cm = split_comment(val)
                    if cm:
                        extra["hint_comment"] = cm
                elif tag == "string" and cid == "enum_values":
                    enum_ref = val
                elif tag == "string" and cid == "database_table_type":
                    table_type = val
                elif tag == "string" and cid == "fields":
                    fields_ref = val
                elif cid is None:
                    extra.setdefault("unnamed", []).append(_plain(c))
                else:
                    extra[cid] = _num(val) if tag != "string" else val
                    if tag == "string" and "[COMMENT" in (val or ""):
                        extra[cid], cm = split_comment(val)
                        if cm:
                            extra[f"{cid}_comment"] = cm
            elif tag == "list":
                self.mark(c)
                if cid == "enum_values":
                    labels, cmts, ex = self.enum_labels(c)
                    enum = labels
                    if cmts:
                        extra["enum_comments"] = {str(k): v for k, v in sorted(cmts.items())}
                    if ex:
                        extra["enum_extra"] = {str(k): v for k, v in ex.items()}
                elif cid == "dependencies":
                    deps.extend(self.dependency_list(c))
                elif cid in DEPENDENCY_LIST_IDS:
                    extra[cid] = self.dependency_list(c)
                elif cid == "fields":
                    item_fields, item_list, left = self.item_fields(c, path, rec)
                    if left:
                        extra["item_extra"] = left
                else:
                    extra[cid or "list"] = [self.raw(x, "list") for x in _kids(c)]
                    self.kept_raw[f"list:{cid or ''}"] += 1
            elif tag == "record":
                if cid == "list_item":
                    self.mark(c)
                    for g in _kids(c):
                        if g.tag == "list" and g.get("id") == "fields":
                            self.mark(g)
                            item_fields, item_list, left = self.item_fields(g, path, rec)
                            if left:
                                extra["item_extra"] = left
                        elif g.tag in ("flags", "string") and g.get("id") == "fields":
                            self.mark(g)
                            item_view = g.get("value")
                        else:
                            extra.setdefault("list_item", {})[g.get("id") or g.tag] = self.raw(g, "list_item")
                    extra_attrs = {a: v for a, v in c.attrib.items() if a != "id"}
                    if extra_attrs:
                        extra.setdefault("list_item", {})["attrs"] = extra_attrs
                else:
                    extra[cid or "record"] = self.raw(c, "record")
            else:
                extra.setdefault("unhandled", []).append(self.raw(c, "field"))

        attrs = {a: v for a, v in rec.attrib.items() if a not in ("id", "field_id")}
        if attrs:
            extra["attrs"] = attrs
        if section:
            extra["section"] = list(section)
        if code is None:
            code = rec.get("field_id") or rec.get("id")
            if code is None:
                self.r["field_records_without_code"] += 1
                self.notes.append(f"frame {self.frame_index}: field record without a code under {'/'.join(path)}: "
                                  f"{json.dumps(_plain(rec))[:200]}")
                self.mark(rec, deep=True)
                return None
        elif rec.get("id") and rec.get("id") != code:
            extra["record_id"] = rec.get("id")
        if rec.get("field_id") and rec.get("field_id") != code:
            extra["record_field_id"] = rec.get("field_id")

        # What a field points at. Reference types name their target table; plain
        # ``record`` fields point at a layout record via ``fields``.
        references: str | None = None
        if ftype in REFERENCE_TYPES:
            references = table_type
            if table_type is None:
                self.r["reference_fields_without_target"] += 1
        elif ftype == "record" and table_type is not None:
            references = table_type
        elif table_type is not None:
            extra["database_table_type"] = table_type
        if fields_ref is not None:
            item_view = fields_ref if item_view is None else item_view

        if enum is None and enum_ref is not None and enum_ref in self.enums:
            enum = self.enums[enum_ref]  # shared with Catalog.enums
        self.r["field_definitions"] += 1
        if path[1:]:
            self.r["nested_field_definitions"] += 1
        if ftype is None:
            self.r["fields_without_type"] += 1
        if min_v is not None and not isinstance(min_v, (int, float)):
            self.r["non_numeric_min_value"] += 1
        if max_v is not None and not isinstance(max_v, (int, float)):
            self.r["non_numeric_max_value"] += 1
        return Field(
            code=code, name=name, comment=comment, type=ftype, min_value=min_v, max_value=max_v,
            enum=enum, references=references, item_fields=item_fields, category=category,
            dependencies=tuple(deps), flags=flags, extra=extra, translation_id=translation_id,
            hint=hint, enum_ref=enum_ref, item_view=item_view,
            item_field_list=tuple(item_list) if item_list is not None else None,
        )

    def item_fields(self, lst: ET.Element, path: tuple[str, ...], owner: ET.Element
                    ) -> tuple[dict[str, Field], list[Field], dict[str, Any]]:
        """Definitions of a list field's items. Returns (by code, in order, leftovers for ``extra``)."""
        code = next((k.get("value") for k in _kids(owner) if _spells_code(k)), None) or owner.get("id") or "?"
        inner = (*path, code)
        view: list[ViewEntry] = []
        ordered: list[Field] = []
        includes: list[str] = []
        left: dict[str, Any] = {}
        self.fields_list(lst, "/".join(inner), inner, (), view, ordered, includes, left)
        fields: dict[str, Field] = {}
        for f in ordered:
            if f.code in fields:
                self.r["duplicate_item_field_codes"] += 1
            else:
                fields[f.code] = f
        if view:
            self.r["item_entries_not_field_definitions"] += len(view)
            left["view_entries"] = [{"record_type": e.record_type, "code": e.code, "attrs": e.attrs,
                                     "section": list(e.section)} for e in view]
        if includes:
            left["includes"] = includes
        return fields, ordered, left

    def dependency_list(self, lst: ET.Element) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for rec in _kids(lst):
            self.mark(rec)
            d: dict[str, Any] = dict(rec.attrib)
            for g in _kids(rec):
                self.mark(g)
                if g.tag == "list":
                    values = []
                    for x in _kids(g):
                        self.mark(x, deep=True)
                        values.append(_num(x.get("value")) if x.get("value") is not None else _plain(x))
                    d[g.get("id") or "list"] = values
                else:
                    d[g.get("id") or g.tag] = self.raw(g, "dependency")
            out.append(d)
        return out


# --------------------------------------------------------------------------
# Catalog construction
# --------------------------------------------------------------------------


def build_catalog(data: bytes, source_path: str | None = None) -> Catalog:
    """Build a catalog from the raw bytes of an ``editor.fmf`` archive."""
    sha = hashlib.sha256(data).hexdigest()
    frames, container = parse_container(data)
    p = _Parser()
    infos: list[FrameInfo] = []
    for info, xml in frames:
        if info.name != DIRECTORY_FRAME_NAME:
            p.load(info.index, xml)
    for info, _xml in frames:
        if info.name == DIRECTORY_FRAME_NAME:
            infos.append(info)
            continue
        ids = p.frame(info.index)
        infos.append(FrameInfo(info.index, info.name, info.offset, info.compressed_size, info.size,
                               info.mtime, info.mtime2, tuple(ids)))
    views = {k: [(e.record_type, e.code) for e in v] for k, v in p.view_entries.items()}

    # table type name -> record types (the record type whose `dbnm` field carries it)
    tt: dict[str, list[str]] = {}
    for rt in p.record_types.values():
        dbnm = rt.fields.get("dbnm")
        name = dbnm.extra.get("database_table_type") if dbnm else None
        if name:
            tt.setdefault(name, []).append(rt.code)
    # numeric ids come from the `recs` table: dependency `database_table_type equals N`
    ids: dict[str, int] = {}
    layouts: dict[str, str] = {}
    recs = p.record_types.get("recs")
    for f in (recs.field_list if recs else ()):
        if f.references and f.item_view:
            layouts.setdefault(f.references, f.item_view)
        for dep in f.dependencies:
            if dep.get("field") == "database_table_type" and f.references:
                n = _int(dep.get("equals"))
                if n is not None:
                    ids.setdefault(f.references, n)
    defined = set(p.record_types) | set(views) | set(p.view_includes)

    catalog = Catalog(
        sha256=sha, frames=tuple(infos), record_types=p.record_types, views=views,
        view_entries={k: tuple(v) for k, v in p.view_entries.items()}, view_comments=p.view_comments,
        view_includes={k: tuple(v) for k, v in p.view_includes.items()},
        sections={k: tuple(v) for k, v in p.sections.items()},
        enums=p.enums, enum_comments=p.enum_comments, stub_enums=tuple(p.stubs),
        table_types={k: tuple(v) for k, v in tt.items()}, table_type_ids=ids,
        table_layouts=layouts, config=p.config, container=container, report={}, source_path=source_path,
    )
    report = _build_report(catalog, p, defined)
    return replace(catalog, report=report)


def _build_report(cat: Catalog, p: _Parser, defined: set[str]) -> dict[str, Any]:
    all_fields = list(cat.iter_fields())
    enum_fields = [s.field for s in all_fields if s.field.type in ENUM_TYPES]
    inline = [f for f in enum_fields if f.enum and not f.enum_ref]
    via_registry, unresolved_ref, no_labels = [], [], []
    for f in enum_fields:
        if f.enum and not f.enum_ref:
            continue
        if f.enum_ref and f.enum_ref in cat.enums:
            via_registry.append(f)
        elif f.enum_ref:
            unresolved_ref.append(f)
        else:
            no_labels.append(f)
    # an enum referencing a registry carries no inline labels; expose them on demand
    ref_fields = [s.field for s in all_fields if s.field.type in REFERENCE_TYPES]
    no_target = [f for f in ref_fields if not f.references]
    unknown_target = [f for f in ref_fields if f.references and f.references not in cat.table_types]
    record_fields = [s.field for s in all_fields if s.field.type == "record"]
    list_fields = [s.field for s in all_fields if s.field.item_view or s.field.item_fields is not None]
    view_refs = [f for f in list_fields if f.item_view]
    unresolved_views = [f for f in view_refs if f.item_view not in defined]
    list_like = [s.field for s in all_fields if s.field.type in ("list", "database_table")]
    list_without_items = [f for f in list_like if f.item_fields is None and not f.item_view]
    dup_scopes = {c: len(rt.duplicates) for c, rt in cat.record_types.items() if rt.duplicates}
    return {
        "field_definitions": len(all_fields),
        "top_level_field_definitions": sum(len(rt.field_list) for rt in cat.record_types.values()),
        "nested_field_definitions": p.r["nested_field_definitions"],
        "unique_codes": len({s.field.code for s in all_fields}),
        "fields_without_type": sum(1 for s in all_fields if s.field.type is None),
        "field_records_without_code": p.r["field_records_without_code"],
        "enum_fields": len(enum_fields),
        "enum_fields_with_inline_labels": len(inline),
        "enum_fields_resolved_via_named_enum": len(via_registry),
        "enum_fields_referencing_enum_not_in_archive": len(unresolved_ref),
        "enum_fields_referencing_enum_declared_without_labels": sum(
            1 for f in unresolved_ref if f.enum_ref in cat.stub_enums),
        "enum_fields_referencing_undeclared_enum": sum(
            1 for f in unresolved_ref if f.enum_ref not in cat.stub_enums),
        "enum_fields_without_labels_or_reference": len(no_labels),
        "enum_names_not_in_archive": sorted({f.enum_ref for f in unresolved_ref} - set(cat.stub_enums)),
        "enum_names_declared_without_labels": sorted({f.enum_ref for f in unresolved_ref} & set(cat.stub_enums)),
        "named_enums": len(cat.enums),
        "reference_fields": len(ref_fields),
        "reference_fields_without_target": len(no_target),
        "reference_fields_with_unresolvable_target": len(unknown_target),
        "unresolvable_targets": sorted({f.references for f in unknown_target}),
        "record_fields": len(record_fields),
        "list_fields_without_item_definition": len(list_without_items),
        "item_view_references": len(view_refs),
        "item_view_references_not_defined_in_archive": len(unresolved_views),
        "item_views_not_in_archive": sorted({f.item_view for f in unresolved_views}),
        "duplicate_definitions_in_scope": dup_scopes,
        "duplicate_item_field_codes": p.r["duplicate_item_field_codes"],
        "view_entries": p.r["view_entries"],
        "view_entries_malformed": p.r["view_entries_malformed"],
        "enum_entries_unparsed": p.r["enum_entries_unparsed"],
        "enum_entries_with_symbolic_key": p.r["enum_entries_with_symbolic_key"],
        "enum_id_differs_from_enum": p.r["enum_id_differs_from_enum"],
        "layout_sections": p.r["layout_sections"],
        "item_entries_not_field_definitions": p.r["item_entries_not_field_definitions"],
        "enum_entries_without_label": p.r["enum_entries_without_label"],
        "enum_duplicate_values": p.r["enum_duplicate_values"],
        "booleans_without_value_taken_as_true": p.r["boolean_without_value_taken_as_true"],
        "non_numeric_min_or_max_values": p.r["non_numeric_min_value"] + p.r["non_numeric_max_value"],
        "unparsed_elements_by_tag": dict(sorted(p.unparsed.items())),
        "elements_kept_raw_in_extra_by_tag_id": dict(sorted(p.kept_raw.items())),
        "notes": p.notes,
    }


# --------------------------------------------------------------------------
# Loading and caching
# --------------------------------------------------------------------------

_CACHE: dict[tuple[str, int, int, str], Catalog] = {}
_CACHE_LOCK = threading.Lock()


def load_catalog(editor_fmf_path: str | Path | None = None) -> Catalog:
    """Load (and cache by path, size, mtime and sha256) the catalog for ``editor.fmf``."""
    path = Path(editor_fmf_path) if editor_fmf_path is not None else DEFAULT_EDITOR_FMF
    path = path.expanduser()
    data = path.read_bytes()
    st = path.stat()
    key = (str(path.resolve()), len(data), st.st_mtime_ns, hashlib.sha256(data).hexdigest())
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
    if hit is not None:
        return hit
    catalog = build_catalog(data, source_path=str(path))
    with _CACHE_LOCK:
        # drop stale entries for the same path
        for old in [k for k in _CACHE if k[0] == key[0]]:
            del _CACHE[old]
        _CACHE[key] = catalog
    return catalog


def editor_fmf_for_plugin(plugin_binary_path: str | Path) -> Path:
    """``<bundle>/Contents/Resources/shared/data/editor.fmf`` for a plugin binary or bundle path."""
    p = Path(plugin_binary_path).expanduser()
    for candidate in (p, *p.parents):
        if candidate.name == "Contents":
            return candidate / EDITOR_FMF_RELATIVE.relative_to("Contents")
        if candidate.suffix == ".bundle":
            return candidate / EDITOR_FMF_RELATIVE
    raise CatalogError(f"cannot locate the plugin bundle from {plugin_binary_path}")


def load_catalog_for_plugin(plugin_binary_path: str | Path) -> Catalog:
    return load_catalog(editor_fmf_for_plugin(plugin_binary_path))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _describe(scope: FieldScope) -> str:
    f = scope.field
    bits = [scope.scope, f"type={f.type}", f"name={f.name!r}"]
    if f.min_value is not None or f.max_value is not None:
        bits.append(f"range={f.min_value}..{f.max_value}")
    if f.references:
        bits.append(f"-> {f.references}")
    if f.enum:
        bits.append(f"enum[{len(f.enum)}]")
    elif f.enum_ref:
        bits.append(f"enum_ref={f.enum_ref}")
    if f.comment:
        bits.append(f"comment={f.comment!r}")
    return "  ".join(bits)


def _print_summary(cat: Catalog, out) -> None:
    s = cat.summary()
    print(f"sha256 {cat.sha256}", file=out)
    print(f"container {json.dumps(cat.container, sort_keys=True)}", file=out)
    print(f"frames {s['frames']}  record types {s['record_types']}  unique codes {s['unique_codes']}  "
          f"field definitions {cat.report['field_definitions']}  named enums {s['enums']}", file=out)
    print("fields per record type (top-level / including nested list items):", file=out)
    total = s["definitions_per_record_type_incl_nested"]
    for code, n in sorted(s["fields_per_record_type"].items(), key=lambda kv: (-total[kv[0]], kv[0])):
        print(f"  {code:6} {n:5} / {total[code]}", file=out)
    print("type histogram:", file=out)
    for t, n in s["type_histogram"].items():
        print(f"  {str(t):28} {n}", file=out)
    print("views (entries):", file=out)
    for k, n in sorted(s["views"].items()):
        print(f"  {k:6} {n}", file=out)
    print("report:", file=out)
    for k, v in cat.report.items():
        print(f"  {k}: {json.dumps(v, sort_keys=True)}", file=out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m fm_live_mcp.fmdb.catalog", description=__doc__.splitlines()[0])
    ap.add_argument("--path", help="editor.fmf path (default: installed Football Manager 27)")
    ap.add_argument("--summary", action="store_true", help="counts per record type, type histogram, parse report")
    ap.add_argument("--dump", metavar="OUT.json", help="write the full catalog as JSON")
    ap.add_argument("--find", metavar="CODE", help="every scope defining a field code")
    ap.add_argument("--search", metavar="TEXT", help="search names, comments, hints and categories")
    args = ap.parse_args(argv)
    if not (args.summary or args.dump or args.find or args.search):
        ap.print_help()
        return 2
    cat = load_catalog(args.path)
    if args.summary:
        _print_summary(cat, sys.stdout)
    if args.dump:
        Path(args.dump).write_text(json.dumps(cat.to_json(), indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                                   encoding="utf-8")
        print(f"wrote {args.dump}")
    if args.find:
        hits = cat.find(args.find)
        for h in hits:
            print(_describe(h))
        if not hits:
            print(f"no field {args.find!r}")
            return 1
    if args.search:
        hits = cat.search(args.search)
        for h in hits:
            print(_describe(h))
        print(f"{len(hits)} match(es)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
