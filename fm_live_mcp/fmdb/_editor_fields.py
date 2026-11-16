"""Private, minimal extraction of (record type, field code, name, type) from editor.fmf.

This only drives the VM coverage runs. The full schema parser lives in another lane
(`fmdb/catalog.py`); nothing here is a public schema API.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re
import xml.etree.ElementTree as ET

MAGIC = b'\x28\xb5\x2f\xfd'


@dataclass(frozen=True)
class Field:
    record: str
    code: str
    name: str
    type: str

    @property
    def fourcc(self) -> int:
        return fourcc(self.code)


def fourcc(code: str) -> int:
    raw = code.encode('latin-1')
    if len(raw) != 4:
        raise ValueError(f'FourCC must be four bytes: {code!r}')
    return int.from_bytes(raw, 'big')


def fourcc_text(key: int) -> str:
    return key.to_bytes(4, 'big').decode('latin-1')


def editor_path(plugin_binary: Path) -> Path:
    # .../game_plugin.bundle/Contents/MacOS/game_plugin -> .../Contents/Resources/shared/data/editor.fmf
    return Path(plugin_binary).parent.parent / 'Resources/shared/data/editor.fmf'


def _frames(data: bytes):
    from compression import zstd
    for match in re.finditer(re.escape(MAGIC), data):
        try:
            yield zstd.ZstdDecompressor().decompress(data[match.start():], max_length=20_000_000)
        except Exception:  # noqa: BLE001 - a false magic hit inside a frame
            continue


def _clean_name(value: str) -> str:
    return re.sub(r'\[COMMENT[^\]]*\]', '', value).strip()


@lru_cache(maxsize=4)
def load_fields(path: str) -> dict[str, list[Field]]:
    """Return {record type: [Field, ...]} for every editor record with a direct field list."""
    out: dict[str, list[Field]] = {}
    for frame in _frames(Path(path).read_bytes()):
        text = frame.decode('utf-8', 'replace').lstrip('﻿')
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            continue
        for record in root.findall('record'):
            rtype = record.get('id')
            fields = record.find("list[@id='fields']")
            if not rtype or fields is None:
                continue
            seen = {f.code for f in out.get(rtype, [])}
            for item in fields.findall('record'):
                code = item.find("flags[@id='field']")
                if code is None or len(code.get('value', '')) != 4:
                    continue
                kind = item.find("flags[@id='type']")
                name = item.find("translation[@id='name']")
                value = code.get('value')
                if value in seen:
                    continue
                seen.add(value)
                out.setdefault(rtype, []).append(Field(
                    rtype, value, _clean_name(name.get('value', '')) if name is not None else '',
                    kind.get('value', '') if kind is not None else ''))
    return out
