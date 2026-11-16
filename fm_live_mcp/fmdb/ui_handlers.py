"""Generic UI handler reads and per-screen recipes on top of UiHandlerVM.

`read_handler(vm, handler_type, record, keys=None, inputs=None)` builds the client and
server handlers for a UI_RECORD, transfers every input the client consumes from the
server (the game's own exchange), then reads the requested keys (default: every
registry key the client's get_property materialises) and labels them.

Values are what the game's UI layer would display, produced by the unmodified shipped
handler code on copied live memory; anything the emulation cannot produce is
`Unavailable(reason)`. Handler output can include values derived at call time and, in a
manager career, already reflects what the human manager is allowed to know.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import time

from . import ui_registry, variant
from .ui_vm import UiHandlerVM, Handler
from .vm import Unavailable, _Stop

TEAM_CONFIDENCE = 114


@dataclass
class Reading:
    code: str
    label: str | None
    kind: str | None
    value: object
    seconds: float

    @property
    def ok(self):
        return not isinstance(self.value, Unavailable)

    def to_json(self):
        return {'key': self.code, 'label': self.label, 'kind': self.kind,
                'value': variant.to_json(self.value)}


@dataclass
class HandlerReading:
    handler_type: int
    client_class: str | None
    server_class: str | None
    record: dict
    inputs: dict
    readings: list = field(default_factory=list)
    build_seconds: float = 0.0
    input_seconds: float = 0.0
    files_read: tuple = ()

    def by_label(self):
        return {r.label or r.code: r.value for r in self.readings}

    def summary(self):
        counts = {'value': 0, 'unset': 0}
        reasons = {}
        for r in self.readings:
            if isinstance(r.value, Unavailable):
                reasons[r.value.reason] = reasons.get(r.value.reason, 0) + 1
            elif r.value in (None, '', [], {}) or r.kind == 'null':
                counts['unset'] += 1
            else:
                counts['value'] += 1
        counts['unavailable'] = reasons
        return counts


def input_keys(registry, client_class):
    """Inputs the client consumes: slot 16 declarations plus slot 17 immediates."""
    row = registry.classes.get(client_class)
    if row is None:
        return ()
    keys = list(row.declares())
    for code in row.slots.get('17', {}).get('fourccs', ()):
        if code not in keys:
            keys.append(code)
    return tuple(keys)


def read_handler(vm: UiHandlerVM, handler_type: int, record: dict | None = None, keys=None,
                 inputs=None, registry=None) -> HandlerReading:
    registry = registry or ui_registry.default()
    handler = vm.build(handler_type, record or {})
    out = HandlerReading(handler_type, handler.client_class, handler.server_class,
                         dict(handler.record), {}, build_seconds=handler.build_seconds)
    started = time.perf_counter()
    if handler.server:
        for key in (inputs if inputs is not None else input_keys(registry, handler.client_class)):
            vm.transfer(handler, key)
    out.inputs = dict(handler.inputs)
    out.input_seconds = time.perf_counter() - started
    if keys is None:
        row = registry.classes.get(handler.client_class)
        keys = row.keys(4) if row else ()
    for code in keys:
        t0 = time.perf_counter()
        result = vm.get(handler, code)
        out.readings.append(Reading(code, registry.label(code), result.kind, result.value,
                                    time.perf_counter() - t0))
    out.files_read = tuple(sorted(vm.files_read))
    return out


# ---------------------------------------------------------------------- recipes
def team_confidence(vm: UiHandlerVM, team: int, keys=None) -> HandlerReading:
    """Board/supporter confidence for a team (db::TEAM pointer): type 114, record
    {'Ttea': team object id}; the server computes TEAM_CONFIDENCE data (0x1DC62F4) and
    serialises it as input 'Tcnf' (DATA value); the client deserialises it (0x1DB1ABC)."""
    return read_handler(vm, TEAM_CONFIDENCE, {'Ttea': vm.object_ref(team)}, keys=keys)


def plain_text(value):
    """Display text of a UI string: links are '\\x01<base64 link record>\\x02<text>\\x01'."""
    import re
    if isinstance(value, str):
        return re.sub(r'\x01[A-Za-z0-9+/=]*\x02([^\x01]*)\x01', r'\1', value)
    if isinstance(value, list):
        return [plain_text(v) for v in value]
    if isinstance(value, dict):
        return type(value)({k: plain_text(v) for k, v in value.items()}) if type(value) is dict \
            else value
    return value


GRADES = {5: 'C', 6: 'C+', 8: 'B', 9: 'B+'}   # observed against the Board screen (see docs)


def safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except _Stop as stop:
        return Unavailable(stop.reason, detail=stop.detail)


__all__ = ['read_handler', 'team_confidence', 'HandlerReading', 'Reading', 'Handler', 'input_keys']
