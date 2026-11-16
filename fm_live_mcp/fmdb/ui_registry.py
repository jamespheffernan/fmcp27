"""UI property registry: FourCC key <-> label, handler classes and handler types.

Data file `data/ui_registry.json.gz` (built by scripts/fmdb_ui_registry_build.py):

* `keys`: {fourcc: label} - the front end's property registry, recovered from
  GameAssembly's registration function 0xA296BC (8,305 key+label pairs);
* `classes`: {class: {vtable, slots: {slot: {fn, keys?, declares?}}}} - every plugin
  `*_UI_HANDLER` / `*_UI_HANDLER_SERVER` class, with the registry keys each vtable slot
  function materialises (slot 4 = client get_property, slot 2 = server get) and, for
  slot 16, the input keys the client declares;
* `types`: {type id: {client, server}} - what GAME_UI_HANDLER_FACTORY builds for each
  value of UI_RECORD key '110 ' (filled by emulating the factory on a live game).

Everything is pinned to the plugin build in `build` (players.SHA256).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import gzip
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent / 'data' / 'ui_registry.json.gz'


@dataclass(frozen=True)
class HandlerClass:
    name: str
    vtable: int
    slots: dict

    def keys(self, slot=4):
        return tuple(self.slots.get(str(slot), {}).get('keys', ()))

    def declares(self):
        return tuple(self.slots.get('16', {}).get('declares', ()))

    def fn(self, slot):
        entry = self.slots.get(str(slot))
        return entry['fn'] if entry else None


class Registry:
    def __init__(self, data: dict):
        self.build = data.get('build')
        self.labels = dict(data['keys'])
        self.by_label = {}
        for code, label in self.labels.items():
            self.by_label.setdefault(label, []).append(code)
        self.classes = {name: HandlerClass(name, row['vtable'], row['slots'])
                        for name, row in data['classes'].items()}
        self.types = {int(k): v for k, v in data.get('types', {}).items()}

    def label(self, code: str) -> str | None:
        return self.labels.get(code)

    def codes(self, label: str) -> list:
        return list(self.by_label.get(label, ()))

    def handler_class(self, name: str) -> HandlerClass:
        name = name.split('::')[-1]
        if not name.endswith(('_UI_HANDLER', '_UI_HANDLER_SERVER')):
            name += '_UI_HANDLER'
        return self.classes[name]

    def type_of(self, class_name: str) -> int | None:
        short = class_name.split('::')[-1]
        for number, row in self.types.items():
            if row.get('client') == short:
                return number
        return None

    def server_of(self, class_name: str) -> HandlerClass | None:
        return self.classes.get(class_name.split('::')[-1] + '_SERVER')


def load(path: Path = DATA) -> Registry:
    return Registry(json.loads(gzip.decompress(Path(path).read_bytes())))


@lru_cache(maxsize=1)
def default() -> Registry:
    """The registry of the active build: the shipped file on the pinned build; on a mapped build
    the one the update command built from that plugin (`<sha256>.ui_registry.json.gz` next to the
    address map), when it exists."""
    from .. import address_book
    if address_book.ACTIVE['state'] == 'mapped':
        path = address_book.cache_dir() / f'{address_book.ACTIVE["sha256"]}.ui_registry.json.gz'
        if path.exists():
            return load(path)
    return load()
