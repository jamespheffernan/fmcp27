"""Decode the 16-byte `sicore` typed value a property getter writes to `out`.

ABI (established from the shipped code; summary in docs/fmdb/COVERAGE.md):

* A typed value is `{traits*, payload:u64}`. `traits` points at `{vtable, kind:u8}`;
  `traits->vtable[3](traits, value*)` destroys a value. The getter destroys the
  caller's old value through it before storing the new one, so `out` must start
  as a valid NULL value.
* One traits instance per primitive lives in the registry built by 0x4403cd4
  (pointer at global RVA 0x573BBA0). Kinds are told apart by RTTI class name:
  NULL (+0x08), bool `b` (+0x18), int32 `i` (+0x28), uint32 `j` (+0x38),
  int64 `x` (+0x48), uint64 `y` (+0x58), float `f` (+0x68), double `d` (+0x78),
  STRING (+0x88), SYMBOL (+0x98), TYPED_LIST (+0xA8), RECORD (+0xB8), DATE_TIME (+0xC8).
* Raw kinds keep the value in the payload (bool in the low byte, float in the low 32 bits).
* STRING payload: pointer to `{u32 length, utf-8 bytes}`, refcount (u32) at pointer-4; 0 = "".
* RECORD payload: pointer to a vector `{begin, end, cap}` of 16-byte entries
  `{u32 key, pad, typed*}` (keyed insertion 0x43F72E4, boxing 0x4404654).
  A database record reference is a RECORD with one entry
  `{table FourCC: int64 (unique id | random id << 32)}` (builder 0x11B404C);
  the random id half is the record's +0x10 when non-zero, else its unique id.
* fmdate SI_DATE (traits outside the registry): inline `year << 17 | day_of_year << 8 | low8`
  (checked against stored birth dates: 2001-02-24 = 0x0FA23700). 1900-01-01 appears as a
  "no date" value in some fields and is returned as is.
* RGBA: inline u32 read as 0xAARRGGBB (channel order inferred from hair/skin colour samples).
* DATA payload: pointer to `{u8* bytes, u32 size}` (traits 0x5697D58 methods 0x437DE70
  destroy / 0x437DFA8 copy); decoded as the byte string.
* TYPED_LIST payload: pointer to a vector `{begin, end, cap}` of `typed*` (8-byte
  pointers to pool-allocated typed values), decoded element by element.

Unknown kinds come back as `Unavailable('variant kind N (...)')` with the raw bytes.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

from .vm import Unavailable

RAW = {
    'b': ('bool', lambda p: bool(p & 0xFF)),
    'i': ('int', lambda p: struct.unpack('<i', struct.pack('<I', p & 0xFFFFFFFF))[0]),
    'j': ('uint', lambda p: p & 0xFFFFFFFF),
    'x': ('int64', lambda p: struct.unpack('<q', struct.pack('<Q', p))[0]),
    'y': ('uint64', lambda p: p),
    'f': ('float', lambda p: struct.unpack('<f', struct.pack('<I', p & 0xFFFFFFFF))[0]),
    'd': ('double', lambda p: struct.unpack('<d', struct.pack('<Q', p))[0]),
}
RAW_PREFIX = 'N6sicore16RAW_TYPED_TRAITSI'
NULL = 'N6sicore17NULL_TYPED_TRAITSE'
STRING = 'N6sicore19STRING_TYPED_TRAITSE'
SYMBOL = 'N6sicore19SYMBOL_TYPED_TRAITSE'
RECORD = 'N6sicore28INTERNAL_OBJECT_TYPED_TRAITSINS_6RECORDELh10EEE'
LIST = 'N6sicore28INTERNAL_OBJECT_TYPED_TRAITSINS_10TYPED_LISTELh11EEE'
DATE_TIME = 'N6sicore22DATE_TIME_TYPED_TRAITSE'
DATA = 'N6sicore17DATA_TYPED_TRAITSE'
SI_DATE = 'N6fmdate20SI_DATE_TYPED_TRAITSE'
RGBA = 'N6sicore17RGBA_TYPED_TRAITSE'
MAX_DATA = 1 << 20
MAX_ITEMS = 100_000
MAX_DEPTH = 8


@dataclass(frozen=True)
class RecordRef:
    """A database record reference as the getter encodes it (table FourCC + identity)."""
    table: str
    unique_id: int
    random_id: int

    def to_json(self):
        return {'table': self.table, 'unique_id': self.unique_id, 'random_id': self.random_id}


def fourcc_text(key):
    return (key & 0xFFFFFFFF).to_bytes(4, 'big').decode('latin-1')


def decode(vm, out):
    """Decode the typed value at `out` (VM address); returns (kind, value)."""
    return decode_typed(vm, out, 0)


def decode_typed(vm, address, depth):
    raw = vm.read(address, 16)
    traits, payload = struct.unpack('<QQ', raw)
    if traits < 0x1_0000_0000:
        return None, Unavailable('variant has no traits', raw=raw)
    vtable = vm.read_u64(traits)
    name = vm.rtti_name(vtable) or f'vtable@{vtable - vm.base:#x}'
    kind_byte = vm.read(traits + 8, 1)[0]
    return _decode(vm, name, kind_byte, payload, raw, depth)


def _decode(vm, name, kind_byte, payload, raw, depth):
    if name == NULL:
        return 'null', None
    if name.startswith(RAW_PREFIX) and len(name) == len(RAW_PREFIX) + 3:
        code = name[len(RAW_PREFIX)]
        if code in RAW:
            kind, fn = RAW[code]
            return kind, fn(payload)
    if name == STRING:
        return 'string', read_string(vm, payload)
    if depth >= MAX_DEPTH:
        return name, Unavailable('variant nesting too deep', raw=raw)
    if name == RECORD:
        return _record(vm, payload, raw, depth)
    if name == LIST:
        return _list(vm, payload, raw, depth)
    if name == DATA:
        return _data(vm, payload, raw)
    if name == SI_DATE:
        return 'date', si_date(payload)
    if name == RGBA:
        value = payload & 0xFFFFFFFF
        return 'colour', {'a': value >> 24, 'r': (value >> 16) & 0xFF, 'g': (value >> 8) & 0xFF,
                          'b': value & 0xFF}
    extra = b''
    if payload >= 0x1_0000_0000:
        try:
            extra = vm.read(payload, 64)
        except Exception:  # noqa: BLE001 - raw preservation is best effort
            extra = b''
    return _short(name), Unavailable(f'variant kind {kind_byte} ({_short(name)})', raw=raw + extra)


def _short(name):
    for prefix, label in ((RAW_PREFIX, 'raw:'),):
        if name.startswith(prefix):
            return label + name[len(prefix):]
    return {SYMBOL: 'symbol', DATE_TIME: 'date_time', RECORD: 'record', LIST: 'list',
            DATA: 'data', SI_DATE: 'date', RGBA: 'colour'}.get(name, name)


def read_string(vm, pointer):
    if pointer == 0:
        return ''
    length = struct.unpack('<I', vm.read(pointer, 4))[0]
    if length > 1 << 20:
        return Unavailable('implausible string length', raw=vm.read(pointer, 16))
    return vm.read(pointer + 4, length).decode('utf-8', 'replace')


def _vector(vm, pointer, stride, raw):
    if pointer < 0x1_0000_0000:
        return None, Unavailable('internal object without storage', raw=raw)
    begin, end, cap = struct.unpack('<QQQ', vm.read(pointer, 24))
    if begin == end:
        return [], None
    if begin < 0x1_0000_0000 or end < begin or cap < end or (end - begin) % stride \
            or (end - begin) // stride > MAX_ITEMS:
        return None, Unavailable('implausible internal vector', raw=raw + vm.read(pointer, 24))
    return [begin + i * stride for i in range((end - begin) // stride)], None


def si_date(payload):
    """fmdate SI_DATE: year << 17 | day-of-year (1-based, 9 bits) << 8 | low byte."""
    from datetime import date, timedelta
    value = payload & 0xFFFFFFFF
    year, day, low = value >> 17, (value >> 8) & 0x1FF, value & 0xFF
    try:
        result = date(year, 1, 1) + timedelta(days=day - 1)
    except (ValueError, OverflowError):
        return Unavailable('invalid SI_DATE', raw=struct.pack('<Q', payload))
    if result.year != year or day == 0:
        return Unavailable('invalid SI_DATE', raw=struct.pack('<Q', payload))
    return SiDate(result.isoformat(), low)


@dataclass(frozen=True)
class SiDate:
    iso: str
    low: int = 0     # low byte of the packed value (0 in every sample seen)

    def to_json(self):
        return self.iso if not self.low else {'date': self.iso, 'low': self.low}


def _data(vm, payload, raw):
    if payload == 0:
        return 'data', b''
    pointer, size = struct.unpack('<QI', vm.read(payload, 12))
    if size > MAX_DATA or (size and pointer < 0x1_0000_0000):
        return 'data', Unavailable('implausible data blob', raw=raw + vm.read(payload, 16))
    return 'data', vm.read(pointer, size) if size else b''


def _record(vm, payload, raw, depth):
    slots, problem = _vector(vm, payload, 16, raw)
    if problem is not None:
        return 'record', problem
    entries = {}
    for slot in slots:
        key, value = struct.unpack('<IxxxxQ', vm.read(slot, 16))
        entries[fourcc_text(key)] = decode_typed(vm, value, depth + 1)
    if len(entries) == 1:
        (table, (kind, value)), = entries.items()
        if kind == 'int64':
            return 'record_ref', RecordRef(table, value & 0xFFFFFFFF,
                                           (value >> 32) & 0xFFFFFFFF)
    return 'record', {key: value for key, (kind, value) in entries.items()}


def _list(vm, payload, raw, depth):
    slots, problem = _vector(vm, payload, 8, raw)
    if problem is not None:
        return 'list', problem
    items = []
    for slot in slots:
        pointer = struct.unpack('<Q', vm.read(slot, 8))[0]
        if pointer < 0x1_0000_0000:
            items.append(Unavailable('null list element', raw=vm.read(slot, 8)))
            continue
        kind, value = decode_typed(vm, pointer, depth + 1)
        items.append(value)
    return 'list', items


def to_json(value):
    """JSON-friendly form of a decoded value."""
    if isinstance(value, (RecordRef, Unavailable, SiDate)):
        return value.to_json()
    if isinstance(value, (bytes, bytearray)):
        return {'data_hex': bytes(value).hex()}
    if isinstance(value, dict):
        return {k: to_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_json(v) for v in value]
    if isinstance(value, float) and value != value:
        return 'NaN'
    return value
