"""Candidate direct-access plans derived from traced PropertyVM runs.

While the VM emulates a getter, `Tracer` records every load from live memory
(address, width, bytes). Loads are linked into offset chains rooted at the
record pointer as it appears in its table (for PERSON tables that is the PERSON
subobject, so offsets into the primary come out negative, e.g. -0x388 + 0x25C).
After the call, the decoded value is matched against the traced loads under a
few simple transforms. A plan is kept for a (record class, field) only when one
candidate explains the value for every sampled record of that class.

Plan file format (`plans.json`), version 1:

    {
      "format": "fmdb-direct-plans/1",
      "build": "<plugin path>",
      "plans": {
        "<RTTI class, e.g. ACTUAL_PLAYER>": {
          "<FourCC>": {
            "status": "direct",
            "chain": [-300],          # see below
            "width": 2,               # bytes read at the final address (1, 2, 4 or 8)
            "signed": true,           # integer signedness (ignored for float/string/record_ptr)
            "type": "int",            # int | float | double | bool | string | record_ptr
            "transform": "identity",  # identity | nonzero | bit:<k> | div10
            "records": 25,            # sampled records the plan explained
            "distinct_values": 19,    # distinct values seen (a plan needs at least 2)
            "alternatives": 0,        # other chains that also explained every sample
            "null_pointer_is_unset": false  # string/record_ptr: samples with a null pointer
                                            # at the chain were unset (apply() returns None/"")
          },
          "<FourCC>": {"status": "emulate-only", "reason": "...", "records": 25}
        }
      }
    }

Chain semantics: start with `a = record` (the table entry pointer). For every
offset except the last, `a = u64(a + offset)` (a pointer dereference; a null
pointer means the field is unset). The field lives at `a + chain[-1]`.
Types: `int`/`bool` read `width` bytes as a (signed) integer, then apply the
transform (`nonzero`: value != 0; `bit:k`: bit k of the integer); `float`
(width 4) / `double` (width 8) read IEEE values (`div10`: integer / 10 as a
float); `string` reads the u64 at the final address as a pointer P to
`{u32 length, utf-8 bytes}` (P == 0 means ""); `record_ptr` reads a u64 record
pointer whose +0xC/+0x10 are the unique / random ids of the referenced record.

Caveat: a plan is an observation over the sampled records, not a proof. Getters
with branches (sentinels, fallbacks, translated names, lazily updated caches)
are labelled emulate-only whenever the samples disagree or include unset values.
"""
from __future__ import annotations

from collections import defaultdict
import json
import math
from pathlib import Path
import struct

from unicorn import UC_HOOK_MEM_READ

from . import tables, variant
from .vm import NULL_LIMIT, PRIVATE, Unavailable

FORMAT = 'fmdb-direct-plans/1'
MAX_LOADS = 20_000
MAX_DEPTH = 4
WINDOW = (-0x2000, 0x20000)


class Tracer:
    def __init__(self, vm):
        self.vm = vm
        self.active = False
        self.loads = []
        self.observations = defaultdict(list)   # (class, code) -> [candidate set | ('unset',) | (reason,)]
        vm.uc.hook_add(UC_HOOK_MEM_READ, self._on_read, begin=NULL_LIMIT, end=PRIVATE - 1)

    def _on_read(self, uc, access, address, size, value, user):
        if self.active and len(self.loads) <= MAX_LOADS:
            self.loads.append((address, size))

    def get_property(self, record, code):
        self.loads = []
        self.active = True
        try:
            result = self.vm.get_property(record, code)
        finally:
            self.active = False
        try:
            cls = tables.class_of(self.vm.read, self.vm.base, record)[0]
        except Exception:  # noqa: BLE001
            cls = 'unknown'
        self.observations[(cls, code)].append((self._candidates(record, result), repr(result.value)))
        return result

    # --------------------------------------------------------------- analysis
    def _chains(self, record):
        """[(chain, width, bytes)] for traced loads linked to the record."""
        import bisect
        tracked = {record: ()}
        keys = [record]
        out = []
        if len(self.loads) > MAX_LOADS:
            return None
        for address, size in self.loads:
            lo = bisect.bisect_left(keys, address - WINDOW[1] + 1)
            hi = bisect.bisect_right(keys, address - WINDOW[0])
            best = None
            for base in keys[lo:hi]:
                chain, off = tracked[base], address - base
                if best is None or (len(chain), abs(off)) < (len(best[1]), abs(best[0])):
                    best = (off, chain)
            if best is None:
                continue
            chain = best[1] + (best[0],)
            try:
                data = self.vm.read(address, size)
            except Exception:  # noqa: BLE001
                continue
            out.append((chain, size, data))
            if size == 8 and len(chain) < MAX_DEPTH:
                pointer = struct.unpack('<Q', data)[0]
                if NULL_LIMIT <= pointer < PRIVATE and pointer not in tracked:
                    tracked[pointer] = chain
                    bisect.insort(keys, pointer)
        return out

    def _candidates(self, record, result):
        value = result.value
        if isinstance(value, Unavailable):
            return ('unavailable: ' + value.reason,)
        if result.kind == 'null' or value is None:
            # Record which traced 8-byte loads read a null pointer: a pointer plan whose
            # chain is among them explains the unset result (null pointer -> unset).
            loads = self._chains(record) or []
            return ('unset', frozenset(chain for chain, width, data in loads
                                       if width == 8 and data == bytes(8)))
        if result.kind not in ('int', 'uint', 'int64', 'uint64', 'bool', 'float', 'double', 'string',
                               'record_ref'):
            return (f'non-scalar kind {result.kind}',)
        loads = self._chains(record)
        if loads is None:
            return ('too many loads to trace',)
        found = set()
        for chain, width, data in loads:
            if result.kind == 'string' and width == 8:
                pointer = struct.unpack('<Q', data)[0]
                try:
                    text = variant.read_string(self.vm, pointer) if pointer else ''
                except Exception:  # noqa: BLE001
                    continue
                if text == value:
                    found.add((chain, 8, False, 'string', 'identity'))
            elif result.kind == 'record_ref' and width == 8:
                pointer = struct.unpack('<Q', data)[0]
                if NULL_LIMIT <= pointer < PRIVATE:
                    try:
                        uid, rid = struct.unpack('<II', self.vm.read(pointer + 0xC, 8))
                    except Exception:  # noqa: BLE001
                        continue
                    if uid == value.unique_id and (rid or uid) == value.random_id:
                        found.add((chain, 8, False, 'record_ptr', 'identity'))
            elif result.kind in ('float', 'double'):
                if width == 4 and result.kind == 'float' and data == struct.pack('<f', value):
                    found.add((chain, 4, False, 'float', 'identity'))
                if width == 8 and result.kind == 'double' and data == struct.pack('<d', value):
                    found.add((chain, 8, False, 'double', 'identity'))
                if width in (1, 2, 4):
                    for signed in (True, False):
                        n = int.from_bytes(data, 'little', signed=signed)
                        if math.isclose(n / 10, value, rel_tol=1e-6, abs_tol=1e-6):
                            found.add((chain, width, signed, result.kind, 'div10'))
            elif result.kind == 'bool':
                n = int.from_bytes(data, 'little')
                if width <= 4:
                    if bool(n) == value:
                        found.add((chain, width, False, 'bool', 'nonzero'))
                    for bit in range(width * 8):
                        if bool(n >> bit & 1) == value:
                            found.add((chain, width, False, 'bool', f'bit:{bit}'))
            else:
                for signed in (True, False):
                    if int.from_bytes(data, 'little', signed=signed) == value and width in (1, 2, 4, 8):
                        found.add((chain, width, signed, 'int', 'identity'))
        return frozenset(found) if found else ('value not explained by a traced load',)

    # --------------------------------------------------------------- output
    def plans(self):
        out = defaultdict(dict)
        for (cls, code), pairs in self.observations.items():
            observations = [o for o, _ in pairs]
            values = {v for o, v in pairs if isinstance(o, frozenset)}
            sets = [o for o in observations if isinstance(o, frozenset)]
            nulls = [o[1] for o in observations if not isinstance(o, frozenset) and o[0] == 'unset'
                     and len(o) > 1]
            others = [o[0] for o in observations if not isinstance(o, frozenset)]
            if not sets:
                reason = max(set(others), key=others.count) if others else 'no observations'
                out[cls][code] = {'status': 'emulate-only', 'reason': reason, 'records': len(observations)}
                continue
            common = frozenset.intersection(*sets)
            null_unset = False
            if others and len(nulls) == len(others) and common:
                pointer_plans = frozenset(c for c in common if c[3] in ('record_ptr', 'string')
                                          and all(c[0] in n for n in nulls))
                if pointer_plans:
                    common, others, null_unset = pointer_plans, [], True
            if others:
                out[cls][code] = {'status': 'emulate-only',
                                  'reason': f'{len(others)} of {len(observations)} sampled records gave '
                                            f'{max(set(others), key=others.count)!r}',
                                  'records': len(observations)}
                continue
            if not common:
                out[cls][code] = {'status': 'emulate-only',
                                  'reason': 'no single load explains every sampled record',
                                  'records': len(observations)}
                continue
            if len(values) < 2:
                out[cls][code] = {'status': 'emulate-only',
                                  'reason': f'constant in the sample ({next(iter(values))}); load is ambiguous',
                                  'records': len(observations)}
                continue
            chain, width, signed, kind, transform = min(
                common, key=lambda c: (len(c[0]), c[4] not in ('identity', 'nonzero'), c[1], not c[2]))
            out[cls][code] = {'status': 'direct', 'chain': list(chain), 'width': width, 'signed': signed,
                              'type': kind, 'transform': transform, 'records': len(observations),
                              'distinct_values': len(values),
                              'alternatives': len({c[0] for c in common}) - 1,
                              'null_pointer_is_unset': null_unset}
        return out

    def write(self, path):
        plans = self.plans()
        counts = defaultdict(lambda: defaultdict(int))
        for cls, fields in plans.items():
            for row in fields.values():
                counts[cls][row['status']] += 1
        Path(path).write_text(json.dumps({'format': FORMAT, 'build': str(self.vm.image.path),
                                          'summary': counts, 'plans': plans}, indent=1))
        return plans


def apply(read, record, plan):
    """Evaluate one direct plan with plain reads (reference implementation for the bulk lane)."""
    address = record
    for offset in plan['chain'][:-1]:
        address = struct.unpack('<Q', read(address + offset, 8))[0]
        if address == 0:
            return None
    address += plan['chain'][-1]
    kind, width, transform = plan['type'], plan['width'], plan['transform']
    data = read(address, width)
    if kind == 'string':
        pointer = struct.unpack('<Q', data)[0]
        if not pointer:
            return ''
        length = struct.unpack('<I', read(pointer, 4))[0]
        return read(pointer + 4, length).decode('utf-8', 'replace')
    if kind == 'record_ptr':
        pointer = struct.unpack('<Q', data)[0]
        if not pointer:
            return None
        uid, rid = struct.unpack('<II', read(pointer + 0xC, 8))
        return {'unique_id': uid, 'random_id': rid or uid, 'address': pointer}
    if kind in ('float', 'double') and transform == 'identity':
        return struct.unpack('<f' if width == 4 else '<d', data)[0]
    n = int.from_bytes(data, 'little', signed=plan['signed'])
    if transform == 'div10':
        return n / 10
    if transform == 'nonzero':
        return n != 0
    if transform.startswith('bit:'):
        return bool(n >> int(transform[4:]) & 1)
    return n
