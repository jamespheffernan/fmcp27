"""Direct-access plans for bulk snapshot reads, derived from traced getters and checked
against them.

Builds on `plans.Tracer` (load tracing inside the PropertyVM) with what the snapshot
needs on top of `plans.py`:

* more value kinds: SI_DATE (`sidate`: the stored u32 equals the getter's packed value;
  `date_yd`: stored `u16 day-of-year, u16 year`), RGBA colours, and the 4-byte DATA
  blobs the player getter returns for 1-20 attributes (`rating_blob`, see below);
* unset values: a candidate may explain a null result when its pointer chain meets a
  null pointer, or (`zero_null`) when the stored integer is 0 and no sampled value was 0;
* translated names: a string plan that explains every record whose getter succeeded,
  while others needed a language file (`_fseeko`), is kept with `fallback: true`;
* bulk evaluation of many plans over many records with batched scatter reads
  (`evaluate`), and `canonical()`, the one value form used to compare a plan with the
  getter and to store values.

`rating_blob`: for ACTUAL_PLAYER-family records the getter answers the 1-20 attribute
codes (`Pacc`, `Pcro`, ...) with DATA `[1, r, r, r]` where `r` is the 1-20 rating of a
stored 0-100 attribute byte (`player_profile.rating(raw, fifths)`, fifths flag bit 7 of
primary+0x270). The plan names the raw field's own direct plan (`source`) and the flag
chain; it is kept only if it reproduces every sampled blob and then must pass the same
verification as any other plan. The column value is `r`.

A plan is an optimisation, never a source of truth: the snapshot verifies every plan
against the getter on separate records and demotes it on any disagreement.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import json
import math
import struct

from . import plans as base_plans
from . import variant
from .vm import Unavailable

# Version 2 (2026-11-11): plans, `unavailable` marks and timings re-derived under the VM defaults
# of the gap-fix lane (the database view bypasses all 15 game-layer interceptors; unclaimed keys
# retry through the game layer; translated names read languages.fmf). Version-1 files are read
# only as candidates: their direct plans are re-verified, everything else is traced again.
FORMAT = 'fmdb-bulk-plans/2'
OLD_FORMATS = ('fmdb-bulk-plans/1',)
VM_DEFAULTS = 'database view bypasses all interceptors; game fallback; file resolver'
DERIVE_VERSION = 4
CLUSTER_GAP = 256
FLAG_OFFSET = 0x270          # players.py: fifths flag byte at primary + 0x270, bit 7
NULL_LIMIT = 0x1_0000_0000


# --------------------------------------------------------------------------- values
@dataclass(frozen=True)
class Ref:
    """A record reference by identity (table FourCC may be unknown for direct reads)."""
    unique_id: int
    random_id: int
    table: str | None = None


class Missing:
    """Getter result that is not a value (Unavailable), kept for comparisons."""
    __slots__ = ('reason',)

    def __init__(self, reason):
        self.reason = reason

    def __repr__(self):
        return f'Missing({self.reason!r})'


def blob_rating(data):
    """`r` of a `[1, r, r, r]` attribute blob, else None."""
    if isinstance(data, (bytes, bytearray)) and len(data) == 4 and data[0] == 1 and data[1] == data[2] == data[3]:
        return data[1]
    return None


def colour_text(value: int) -> str:
    return '#%08X' % (value & 0xFFFFFFFF)


def canonical(result):
    """One comparable / storable form of a getter result.

    None (null), bool, int, float, str (dates ISO, colours '#AARRGGBB', lists/records as
    JSON text), Ref, or Missing(reason)."""
    value, kind = result.value, result.kind
    if isinstance(value, Unavailable):
        return Missing(value.reason)
    return canonical_value(value, kind)


def canonical_value(value, kind=None):
    if kind == 'null' or value is None:
        return None
    if isinstance(value, Unavailable):
        return Missing(value.reason)
    if isinstance(value, variant.SiDate):
        return value.iso          # the low byte is not part of the date (see snapshot _fields notes)
    if isinstance(value, variant.RecordRef):
        return Ref(value.unique_id, value.random_id, value.table)
    if kind == 'colour' and isinstance(value, dict):
        return colour_text(value['a'] << 24 | value['r'] << 16 | value['g'] << 8 | value['b'])
    if isinstance(value, (bytes, bytearray)):
        rating = blob_rating(value)
        return rating if rating is not None else json.dumps({'data_hex': bytes(value).hex()})
    if isinstance(value, (list, dict)):
        return json.dumps(variant.to_json(value), sort_keys=True, default=str)
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def same(a, b) -> bool:
    if isinstance(a, Missing) or isinstance(b, Missing):
        return False
    if isinstance(a, Ref) and isinstance(b, Ref):
        return a.unique_id == b.unique_id and a.random_id == b.random_id
    if isinstance(a, bool) or isinstance(b, bool):
        return a is not None and b is not None and bool(a) == bool(b) and type(a) in (bool, int) \
            and type(b) in (bool, int)
    if isinstance(a, float) or isinstance(b, float):
        try:
            return a is not None and b is not None and (a == b or math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6))
        except TypeError:
            return False
    return a == b and type(a) is type(b)


# --------------------------------------------------------------------------- tracing
@dataclass
class Observation:
    record: int
    kind: str | None
    value: object                  # canonical value (or Missing)
    candidates: frozenset | None   # explaining (chain, width, signed, type, transform) tuples
    reason: str | None             # why there are no candidates
    handled: bool | None
    ms: float
    blob: int | None = None        # rating of a [1, r, r, r] blob
    view: str | None = None        # 'database', or 'game' when only the game layer answered
    path: str | None = None        # branch path hash (plancompile.path_hash of the executed blocks)


class PlanTracer(base_plans.Tracer):
    """`plans.Tracer` that returns Observations and knows dates, colours and blobs. Every
    observation carries the branch path the getter took (plancompile.PathTracer)."""

    def __init__(self, vm):
        super().__init__(vm)
        from .plancompile import PathTracer
        self.path_tracer = PathTracer(vm)

    def observe(self, record, code) -> tuple[object, Observation]:
        self.loads = []
        self.active = True
        self.path_tracer.start()
        try:
            result = self.vm.get_property(record, code)
        finally:
            self.active = False
            path = self.path_tracer.stop()
        value = canonical(result)
        ms = result.stats.seconds * 1000
        obs = Observation(record, result.kind, value, None, None, result.handled, ms,
                          view=getattr(result, 'view', None), path=path)
        raw = result.value
        if isinstance(raw, Unavailable):
            obs.reason = 'unavailable: ' + raw.reason
        elif result.kind == 'null' or raw is None:
            obs.reason = 'unset' if result.handled else 'not handled'
        elif result.kind == 'date' and isinstance(raw, variant.SiDate):
            obs.candidates, obs.reason = self._date_candidates(record, raw)
        elif result.kind == 'colour':
            packed = raw['a'] << 24 | raw['r'] << 16 | raw['g'] << 8 | raw['b']
            obs.candidates, obs.reason = self._u32_candidates(record, {packed: 'colour'})
        elif result.kind == 'data':
            obs.blob = blob_rating(raw)
            obs.reason = 'attribute blob' if obs.blob is not None else 'non-scalar kind data'
        elif result.kind == 'bool':
            obs.candidates, obs.reason = self._bool_candidates(record, bool(raw))
        else:
            found = self._candidates(record, result)
            if isinstance(found, frozenset):
                obs.candidates = found
            else:
                obs.reason = found[0]
                if result.kind in ('int', 'uint') and 0 <= raw <= 20:
                    obs.blob = raw            # maybe a 1-20 rating of a stored 0-100 byte
                    obs.reason = 'rating candidate'
        return result, obs

    def close(self):
        self.vm = None

    def _bool_candidates(self, record, value):
        """nonzero / bit:k over loads of every width (flag words are often u64)."""
        loads = self._chains(record)
        if loads is None:
            return None, 'too many loads to trace'
        found = set()
        for chain, width, data in loads:
            n = int.from_bytes(data, 'little')
            if width <= 8:
                if bool(n) == value:
                    found.add((chain, width, False, 'bool', 'nonzero'))
                for bit in range(width * 8):
                    if bool(n >> bit & 1) == value:
                        found.add((chain, width, False, 'bool', f'bit:{bit}'))
        return (frozenset(found), None) if found else (None, 'value not explained by a traced load')

    def _u32_candidates(self, record, wanted):
        loads = self._chains(record)
        if loads is None:
            return None, 'too many loads to trace'
        found = set()
        for chain, width, data in loads:
            if width == 4:
                kind = wanted.get(struct.unpack('<I', data)[0])
                if kind:
                    found.add((chain, 4, False, kind, 'identity'))
        return (frozenset(found), None) if found else (None, 'value not explained by a traced load')

    def _date_candidates(self, record, value):
        """u32 loads equal to the packed SI_DATE or to `year << 16 | day`, plus u16 day-of-year
        loads followed in memory by the u16 year (getters often load the halves separately)."""
        from datetime import date
        d = date.fromisoformat(value.iso)
        doy = d.timetuple().tm_yday
        found, reason = self._u32_candidates(record, {d.year << 17 | doy << 8 | value.low: 'sidate',
                                                      d.year << 16 | doy: 'date_yd'})
        found = set(found or ())
        for chain, width, data in self._chains(record) or ():
            if width == 2 and int.from_bytes(data, 'little') == doy:
                address = self._address(record, chain)
                try:
                    year = int.from_bytes(self.vm.read(address + 2, 2), 'little')
                except Exception:  # noqa: BLE001
                    continue
                if year == d.year:
                    found.add((chain, 4, False, 'date_yd', 'identity'))
        return (frozenset(found), None) if found else (None, reason or 'value not explained by a traced load')

    def _address(self, record, chain):
        address = record
        for offset in chain[:-1]:
            address = struct.unpack('<Q', self.vm.read(address + offset, 8))[0]
        return address + chain[-1]


# --------------------------------------------------------------------------- single-record evaluation
def _read_int(data, width, signed):
    return int.from_bytes(data[:width], 'little', signed=signed)


def decode_terminal(plan, data):
    """Decode the bytes at a plan's final address (strings/records need follow-up reads)."""
    kind, width, transform = plan['type'], plan['width'], plan.get('transform', 'identity')
    if kind in ('float', 'double') and transform == 'identity':
        return struct.unpack('<f' if width == 4 else '<d', data[:width])[0]
    n = _read_int(data, width, plan.get('signed', False))
    if plan.get('zero_null') and n == 0:
        return None
    if kind == 'sidate':
        return variant.si_date(n)
    if kind == 'date_yd':
        from datetime import date, timedelta
        year, day = n >> 16, n & 0xFFFF
        try:
            result = date(year, 1, 1) + timedelta(days=day - 1)
        except (ValueError, OverflowError):
            return Missing('invalid stored date')
        return result.isoformat() if result.year == year and day else Missing('invalid stored date')
    if kind == 'colour':
        return colour_text(n)
    if transform == 'div10':
        return n / 10
    if transform == 'nonzero':
        return n != 0
    if transform.startswith('bit:'):
        return bool(n >> int(transform[4:]) & 1)
    if kind == 'bool':
        return n != 0
    return n


def _finish(value):
    if isinstance(value, variant.SiDate):
        return value.iso
    if isinstance(value, Unavailable):
        return Missing(value.reason)
    return value


def apply(read, record, plan):
    """Evaluate one plan for one record with plain reads (reference implementation)."""
    if plan['type'] == 'rating_blob':
        raw = apply(read, record, plan['source_plan'])
        flag = apply(read, record, plan['flag_plan'])
        if raw is None or flag is None or isinstance(raw, Missing) or isinstance(flag, Missing):
            return None
        return rating(raw, flag)
    address = record
    for offset in plan['chain'][:-1]:
        address = struct.unpack('<Q', read(address + offset, 8))[0]
        if address == 0:
            return '' if plan.get('null_is_empty') else None
    address += plan['chain'][-1]
    kind = plan['type']
    if kind == 'string':
        pointer = struct.unpack('<Q', read(address, 8))[0]
        if not pointer:
            return None if plan.get('zero_null') else ''
        length = struct.unpack('<I', read(pointer, 4))[0]
        if length > 1 << 20:
            return Missing('implausible string length')
        return read(pointer + 4, length).decode('utf-8', 'replace')
    if kind == 'record_ptr':
        pointer = struct.unpack('<Q', read(address, 8))[0]
        if not pointer:
            return None
        uid, rid = struct.unpack('<II', read(pointer + 0xC, 8))
        return Ref(uid, rid or uid)
    return _finish(decode_terminal(plan, read(address, plan['width'])))


def try_apply(read, record, plan):
    """`apply` that turns an unreadable address into Missing (used while judging candidates)."""
    try:
        return apply(read, record, plan)
    except Exception as exc:  # noqa: BLE001 - any read failure rejects the candidate
        return Missing(f'unreadable: {exc}')


def rating(raw, flag):
    fifths = bool(flag & 0x80)
    if not 0 <= raw <= (100 if fifths else 20):
        return Missing('attribute outside the verified range')
    return max(1, (raw + 2) // 5) if fifths else raw


# --------------------------------------------------------------------------- derivation
CHOICE = lambda c: (len(c[0]), c[4] not in ('identity', 'nonzero'), c[1], not c[2])  # noqa: E731


def _distinct(values):
    out = set()
    for v in values:
        out.add(repr(v))
    return out


def derive(observations: list[Observation], read) -> dict:
    """One plan entry for a (class, code) from its traced observations."""
    n = len(observations)
    ok = [o for o in observations if o.candidates]
    blobs = [o for o in observations if o.blob is not None]
    unset = [o for o in observations if o.reason == 'unset']
    not_handled = [o for o in observations if o.reason == 'not handled']
    fseeko = [o for o in observations if o.reason and o.reason.endswith('_fseeko')]
    ms = sorted(o.ms for o in observations)
    unavailable = [o for o in observations if o.reason and o.reason.startswith('unavailable')]
    timing = {'v': DERIVE_VERSION, 'records': n, 'ms': round(ms[len(ms) // 2], 4) if ms else None,
              'not_handled': len(not_handled), 'unset': len(unset),
              'unavailable_share': round(len(unavailable) / n, 3) if n else 0.0}
    game = sum(1 for o in observations if o.view == 'game')
    if game:
        timing['game_view'] = game      # records answered only by the game layer
    if unavailable:
        reasons = [o.reason for o in unavailable]
        timing['unavailable_reason'] = max(set(reasons), key=reasons.count)
    if blobs:
        rating_like = [o for o in observations if o.candidates and isinstance(o.value, int)
                       and not isinstance(o.value, bool) and 0 <= o.value <= 20]
        if len(blobs) + len(unset) + len(rating_like) == n:
            for o in rating_like:
                o.blob = o.value
            return {'status': 'blob-pending', **timing}
    if not ok:
        if not_handled and len(not_handled) == n:
            reason = 'getter does not handle this code'
        elif unset and len(unset) + len(not_handled) == n:
            reason = 'null in every sampled record'
        else:
            reasons = [o.reason for o in observations if o.reason]
            reason = max(set(reasons), key=reasons.count) if reasons else 'no observations'
        return {'status': 'emulate-only', 'reason': reason, **timing}
    if ok and not_handled:
        # an unclaimed code also reads as null: a plan must explain it like an unset value
        unset = unset + not_handled
    others = [o for o in observations if not o.candidates and o not in unset and o not in fseeko]
    if others:
        reasons = [o.reason for o in others]
        return {'status': 'emulate-only', 'reason': f'{len(others)} of {n} sampled records gave '
                f'{max(set(reasons), key=reasons.count)!r}', **timing}
    empty = []
    if any(o.kind == 'string' for o in ok):
        empty = [o for o in ok if o.value == '']
        nonempty = [o for o in ok if o.value != '']
        if empty and nonempty:
            ok = nonempty
    common = frozenset.intersection(*[o.candidates for o in ok])
    null_is_empty = False
    if empty and common:
        common = frozenset(c for c in common if c[3] == 'string'
                           and all(try_apply(read, o.record, _plan_from(c)) in (None, '') for o in empty))
    zero_null = False
    if unset and common:
        nonzero_values = all(o.value not in (0, '', False) for o in ok)
        kept = set()
        zero_kept = set()
        for cand in common:
            plan = _plan_from(cand)
            results = [try_apply(read, o.record, plan) for o in unset]
            if all(r is None for r in results):
                kept.add(cand)
            elif nonzero_values and cand[3] in ('int', 'sidate', 'date_yd', 'record_ptr', 'string'):
                zplan = dict(plan, zero_null=True)
                if all(try_apply(read, o.record, zplan) is None for o in unset):
                    zero_kept.add(cand)
        common = frozenset(kept or zero_kept)
        zero_null = not kept and bool(zero_kept)
    if not common:
        return {'status': 'emulate-only', 'reason': 'no single load explains every sampled record'
                + (' (including unset ones)' if unset else ''), **timing}
    values = _distinct(o.value for o in ok)
    if len(values) < 2:
        return {'status': 'emulate-only',
                'reason': f'constant in the sample ({next(iter(values))}); load is ambiguous', **timing}
    best = min(common, key=CHOICE)
    plan = _plan_from(best)
    plan.update(status='direct', distinct_values=len(values),
                alternatives=len({c[0] for c in common}) - 1, **timing)
    paths = defaultdict(int)
    for o in observations:
        if o.path:
            paths[o.path] += 1
    if paths:
        # the branch paths the plan was derived on, with the number of sampled records on each;
        # a record on another path is not covered by the derivation (see plancompile.audit_paths)
        plan['paths'] = dict(paths)
    if zero_null:
        plan['zero_null'] = True
    if empty and any(try_apply(read, o.record, plan) is None for o in empty):
        plan['null_is_empty'] = True
    if fseeko:
        plan['fallback'] = True
        plan['fallback_note'] = (f'{len(fseeko)} of {n} sampled records needed a language file (_fseeko); '
                                 'for those the column holds the stored string')
    return plan


def _plan_from(cand):
    chain, width, signed, kind, transform = cand
    return {'chain': list(chain), 'width': width, 'signed': signed, 'type': kind, 'transform': transform}


def derive_blobs(class_plans: dict, observations: dict, read, names: dict, primary: int | None,
                 known: dict | None = None):
    """Turn 'blob-pending' entries into rating_blob plans when one direct raw field explains them.

    `known` adds already-verified plans of the class as raw sources."""
    if primary is None:
        for code, plan in class_plans.items():
            if plan.get('status') == 'blob-pending':
                class_plans[code] = {**plan, 'status': 'emulate-only',
                                     'reason': 'attribute blob; class has no known primary offset'}
        return
    flag_plan = {'chain': [-primary + FLAG_OFFSET], 'width': 1, 'signed': False, 'type': 'int',
                 'transform': 'identity'}
    sources = {c: p for c, p in {**(known or {}), **class_plans}.items()
               if p.get('status') == 'direct' and p['type'] == 'int' and p['width'] == 1
               and len(p['chain']) == 1}
    for code, plan in list(class_plans.items()):
        if plan.get('status') != 'blob-pending':
            continue
        obs = observations[code]
        hits = []
        for src, sp in sources.items():
            good = True
            for o in obs:
                expected = None if o.blob is None else o.blob
                got = try_apply(read, o.record, {'type': 'rating_blob', 'source_plan': sp, 'flag_plan': flag_plan})
                if o.reason == 'unset':
                    good = got is None
                elif got != expected:
                    good = False
                if not good:
                    break
            if good:
                hits.append(src)
        if len(hits) > 1:
            named = [h for h in hits if names.get(h) and names.get(h) == names.get(code)]
            hits = named if len(named) == 1 else hits
        if len(hits) == 1:
            class_plans[code] = {'status': 'direct', 'type': 'rating_blob', 'source': hits[0],
                                 'source_plan': sources[hits[0]], 'flag_plan': flag_plan,
                                 'records': plan['records'], 'ms': plan['ms'],
                                 'not_handled': plan['not_handled'], 'unset': plan['unset'],
                                 'distinct_values': len({o.blob for o in obs})}
        else:
            class_plans[code] = {**plan, 'status': 'emulate-only',
                                 'reason': f'attribute blob; {len(hits)} raw fields explain it'}


# --------------------------------------------------------------------------- bulk evaluation
def _clusters(ranges):
    """Merge (lo, hi) byte ranges that are within CLUSTER_GAP of each other."""
    out = []
    for lo, hi in sorted(ranges):
        if out and lo <= out[-1][1] + CLUSTER_GAP:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return out


def evaluate(read_many, records: list, plans: dict, *, stats=None, windows=None, touch=None) -> dict:
    """{code: [value per record]} for many direct plans over many records.

    Pointer chains are followed in stages; each stage reads one window per record and
    byte cluster with one batched scatter read. Strings read the pointer, then a 64-byte
    prefix, then any longer remainder. Missing reads give Missing('unreadable').

    With `windows` (MemoryBase.windows) every stage is one fixed-stride buffer that is decoded
    column by column with `struct.iter_unpack`; the values are the same (tests compare the two
    routes), without one `bytes` object and one Python decode call per cell.

    `touch(rows, addresses, length, depth)` (window route only) is called before every read with
    the row positions and the addresses about to be read (an address of 0 is not read); depth 0
    is a window of the record itself, 1 anything reached through a pointer. The snapshot
    records from it what each row's direct cells were read from (freshness.py)."""
    n = len(records)
    out = {code: [None] * n for code in plans}
    simple = {c: p for c, p in plans.items() if p['type'] != 'rating_blob'}
    derived = {c: p for c, p in plans.items() if p['type'] == 'rating_blob'}
    entries = [(code, tuple(p['chain']), p) for code, p in simple.items()]
    for code, p in derived.items():
        entries.append((code + '\0raw', tuple(p['source_plan']['chain']), p['source_plan']))
        entries.append((code + '\0flag', tuple(p['flag_plan']['chain']), p['flag_plan']))
    tmp = {}
    if windows is not None:
        _walk_windows(windows, read_many, list(records), list(range(n)), entries, tmp, stats, touch=touch)
    else:
        _walk(read_many, list(records), list(range(n)), entries, tmp, stats)
    for code, p in simple.items():
        out[code] = tmp[code]
        if p.get('null_is_empty'):
            out[code] = ['' if v is None else v for v in out[code]]
    for code in derived:
        raws, flags = tmp[code + '\0raw'], tmp[code + '\0flag']
        values = []
        seen = {}                       # (raw, flag) -> value: integers repeat, Missing objects do not
        for pair in zip(raws, flags):
            try:
                values.append(seen[pair])
                continue
            except KeyError:
                pass
            raw, flag = pair
            if raw is None or flag is None:
                value = None
            elif isinstance(raw, Missing) or isinstance(flag, Missing):
                value = raw if isinstance(raw, Missing) else flag
            else:
                value = rating(raw, flag)
            seen[pair] = value
            values.append(value)
        out[code] = values
    return out


def _walk(read_many, bases, rows, entries, out, stats, total=None):
    """Evaluate entries (code, remaining chain, plan) at `bases` (record or pointer per row)."""
    if total is None:
        total = len(bases)
        for code, _, _ in entries:
            out[code] = [None] * total
    terminals = [(c, ch[0], p) for c, ch, p in entries if len(ch) == 1]
    deeper = defaultdict(list)
    for c, ch, p in entries:
        if len(ch) > 1:
            deeper[ch[0]].append((c, ch[1:], p))
    ranges = [(off, off + (8 if p['type'] in ('string', 'record_ptr') else p['width'])) for _, off, p in terminals]
    ranges += [(off, off + 8) for off in deeper]
    clusters = _clusters(ranges)
    live = [i for i, b in enumerate(bases) if b]
    requests = [(bases[i] + lo, hi - lo) for i in live for lo, hi in clusters]
    blobs = read_many(requests) if requests else []
    if stats is not None:
        stats['items'] = stats.get('items', 0) + len(requests)
        stats['bytes'] = stats.get('bytes', 0) + sum(n for _, n in requests)
    k = len(clusters)
    located = {}
    for ci, (lo, hi) in enumerate(clusters):
        for off, end in ranges:
            if lo <= off and end <= hi and off not in located:
                located[off] = (ci, off - lo)
    per_cluster = [blobs[ci::k] for ci in range(k)]
    unreadable = Missing('unreadable live memory')
    live_rows = [rows[i] for i in live]
    followups = []          # (code, row, pointer, plan)
    for code, off, p in terminals:
        target = out[code]
        kind = p['type']
        ci, rel = located[off]
        column = per_cluster[ci]
        if kind in ('string', 'record_ptr'):
            empty = None if (kind == 'record_ptr' or p.get('zero_null')) else ''
            for row, data in zip(live_rows, column):
                if data is None:
                    target[row] = unreadable
                    continue
                pointer = _U64.unpack_from(data, rel)[0]
                if not pointer:
                    target[row] = empty
                else:
                    followups.append((code, row, pointer, p))
            continue
        decode = _decoder(p)
        for row, data in zip(live_rows, column):
            target[row] = unreadable if data is None else decode(data, rel)
    if followups:
        _follow(read_many, followups, out, stats)
    for off, sub in deeper.items():
        ci, rel = located[off]
        nxt = []
        for data in per_cluster[ci]:
            pointer = _U64.unpack_from(data, rel)[0] if data is not None else 0
            nxt.append(pointer if pointer >= NULL_LIMIT else 0)
        _walk(read_many, nxt, live_rows, sub, out, stats, total)


def _field(plan):
    """(struct code, post) for a terminal read with iter_unpack: the integer and float decoders
    of `_decoder` map to a struct code; every other terminal is read as raw bytes and decoded by
    `decode_terminal` once per distinct byte string."""
    kind, width, transform = plan['type'], plan['width'], plan.get('transform', 'identity')
    if kind in ('int', 'bool') and transform in ('identity', 'nonzero') and not plan.get('zero_null'):
        code = _INT[(width, bool(plan.get('signed')))].format[-1]
        return code, ('value' if kind == 'int' and transform == 'identity' else 'nonzero')
    if kind in ('float', 'double') and transform == 'identity':
        return ('f' if width == 4 else 'd'), 'value'
    return f'{width}s', 'bytes'


def _columns(payload, stride, fields):
    """Unpack `fields` [(offset, width, struct code)] from a fixed-stride buffer: one list per
    field. Fields that overlap are unpacked in separate passes."""
    out = [None] * len(fields)
    pending = sorted(range(len(fields)), key=lambda k: fields[k][0])
    while pending:
        group, rest, end = [], [], 0
        for k in pending:
            if fields[k][0] >= end:
                group.append(k)
                end = fields[k][0] + fields[k][1]
            else:
                rest.append(k)
        fmt, at = ['<'], 0
        for k in group:
            off, width, code = fields[k]
            if off > at:
                fmt.append(f'{off - at}x')
            fmt.append(code)
            at = off + width
        if stride > at:
            fmt.append(f'{stride - at}x')
        columns = list(zip(*struct.Struct(''.join(fmt)).iter_unpack(payload)))
        for k, column in zip(group, columns):
            out[k] = column
        pending = rest
    return out


def _walk_windows(windows, read_many, bases, rows, entries, out, stats, total=None, touch=None, depth=0):
    """`_walk` over fixed-stride buffers (same results)."""
    if total is None:
        total = len(bases)
        for code, _, _ in entries:
            out[code] = [None] * total
    terminals = [(c, ch[0], p) for c, ch, p in entries if len(ch) == 1]
    deeper = defaultdict(list)
    for c, ch, p in entries:
        if len(ch) > 1:
            deeper[ch[0]].append((c, ch[1:], p))
    ranges = [(off, off + (8 if p['type'] in ('string', 'record_ptr') else p['width'])) for _, off, p in terminals]
    ranges += [(off, off + 8) for off in deeper]
    clusters = _clusters(ranges)
    live = [i for i, b in enumerate(bases) if b]
    if not live:
        return
    whole = len(live) == len(bases)
    live_bases = bases if whole else [bases[i] for i in live]
    live_rows = rows if whole else [rows[i] for i in live]
    direct = whole and live_rows == list(range(total))     # column k is row k: assign whole lists
    located = {}
    for ci, (lo, hi) in enumerate(clusters):
        for off, end in ranges:
            if lo <= off and end <= hi and off not in located:
                located[off] = (ci, off - lo)
    unreadable = Missing('unreadable live memory')
    next_bases = {}
    for ci, (lo, hi) in enumerate(clusters):
        stride = hi - lo
        addresses = [b + lo for b in live_bases] if lo else live_bases
        if touch is not None:
            touch(live_rows, addresses, stride, depth)
        payload, bad = windows(addresses, stride)
        if stats is not None:
            stats['items'] = stats.get('items', 0) + len(live_bases)
            stats['bytes'] = stats.get('bytes', 0) + len(live_bases) * stride
        jobs, fields = [], []           # (what, code/off, plan, post)
        for code, off, p in terminals:
            if located[off][0] != ci:
                continue
            rel = located[off][1]
            if p['type'] in ('string', 'record_ptr'):
                jobs.append(('pointer', code, p, None))
                fields.append((rel, 8, 'Q'))
            else:
                fmt, post = _field(p)
                jobs.append(('value', code, p, post))
                fields.append((rel, p['width'], fmt))
        for off in deeper:
            if located[off][0] == ci:
                jobs.append(('chain', off, None, None))
                fields.append((located[off][1], 8, 'Q'))
        if not jobs:
            continue
        columns = _columns(payload, stride, fields)
        for (what, key, p, post), column in zip(jobs, columns):
            if what == 'chain':
                pointers = [v if v >= NULL_LIMIT else 0 for v in column]
                for k in bad:
                    pointers[k] = 0
                next_bases[key] = pointers
                continue
            target = out[key]
            if what == 'pointer':
                # every distinct pointer is followed once (names and references repeat across rows)
                kind = p['type']
                table = _follow_windows(windows, read_many, column, kind, stats, live_rows, touch)
                table[0] = None if (kind == 'record_ptr' or p.get('zero_null')) else ''
                values = [table[pointer] for pointer in column]
                for k in bad:
                    values[k] = unreadable
                if direct:
                    out[key] = values
                else:
                    for row, value in zip(live_rows, values):
                        target[row] = value
                continue
            if post == 'value':
                values = list(column)
            elif post == 'nonzero':
                values = [v != 0 for v in column]
            else:
                cache = {}
                values = []
                for raw in column:
                    try:
                        values.append(cache[raw])
                    except KeyError:
                        value = cache[raw] = _finish(decode_terminal(p, raw))
                        values.append(value)
            for k in bad:
                values[k] = unreadable
            if direct:
                out[key] = values
            else:
                for row, value in zip(live_rows, values):
                    target[row] = value
    for off, sub in deeper.items():
        _walk_windows(windows, read_many, next_bases[off], live_rows, sub, out, stats, total, touch, 1)


def _follow_windows(windows, read_many, column, kind, stats, rows=None, touch=None):
    """{pointer: value} for the distinct non-null pointers of one string or record-reference
    column (the values `_follow` gives each row)."""
    pointers = set(column)
    pointers.discard(0)
    pointers = list(pointers)
    table = {}
    if not pointers:
        return table
    if touch is not None:           # per row: the 8 bytes of a record head, or a string's first 68
        if kind == 'record_ptr':
            touch(rows, [ptr + 0xC if ptr else 0 for ptr in column], 8, 1)
        else:
            touch(rows, column, 68, 1)
    if kind == 'record_ptr':
        payload, bad = windows([ptr + 0xC for ptr in pointers], 8)
        for ptr, (uid, rid) in zip(pointers, struct.iter_unpack('<II', payload)):
            table[ptr] = Ref(uid, rid or uid)
        for k in bad:
            table[pointers[k]] = Missing('unreadable live memory')
        return table
    payload, bad = windows(pointers, 68)
    longer = []
    for ptr, (length, data) in zip(pointers, struct.iter_unpack('<I64s', payload)):
        if length <= 64:
            table[ptr] = data[:length].decode('utf-8', 'replace')
        elif length > 1 << 20:
            table[ptr] = Missing('implausible string length')
        else:
            longer.append((ptr, length))
    for k in bad:                       # as _follow: the length alone may still be readable
        ptr = pointers[k]
        got_one = read_many([(ptr, 4)])[0]
        if got_one is None:
            table[ptr] = Missing('unreadable live memory')
            continue
        length = struct.unpack('<I', got_one)[0]
        if length > 1 << 20:
            table[ptr] = Missing('implausible string length')
        elif length == 0:
            table[ptr] = ''
        else:
            longer.append((ptr, length))
    if longer:
        if touch is not None:
            lengths = dict(longer)
            for row, ptr in zip(rows, column):
                if ptr in lengths:
                    touch([row], [ptr + 4], lengths[ptr], 1)
        got = read_many([(ptr + 4, length) for ptr, length in longer])
        for (ptr, _), data in zip(longer, got):
            table[ptr] = Missing('unreadable live memory') if data is None else data.decode('utf-8', 'replace')
    if stats is not None:               # counted per row, as _follow does
        rows = len(column) - column.count(0)
        long_rows = sum(column.count(ptr) for ptr, _ in longer) if longer else 0
        stats['items'] = stats.get('items', 0) + rows + long_rows
    return table


_U64 = struct.Struct('<Q')
_INT = {(1, False): struct.Struct('<B'), (1, True): struct.Struct('<b'), (2, False): struct.Struct('<H'),
        (2, True): struct.Struct('<h'), (4, False): struct.Struct('<I'), (4, True): struct.Struct('<i'),
        (8, False): struct.Struct('<Q'), (8, True): struct.Struct('<q')}


def _decoder(plan):
    """Fast `decode(data, offset)` for a terminal plan (same results as decode_terminal)."""
    kind, width, transform = plan['type'], plan['width'], plan.get('transform', 'identity')
    if kind in ('int', 'bool') and transform in ('identity', 'nonzero') and not plan.get('zero_null'):
        st = _INT[(width, bool(plan.get('signed')))]
        if kind == 'int' and transform == 'identity':
            return lambda data, off: st.unpack_from(data, off)[0]
        return lambda data, off: st.unpack_from(data, off)[0] != 0
    if kind in ('float', 'double') and transform == 'identity':
        st = struct.Struct('<f' if width == 4 else '<d')
        return lambda data, off: st.unpack_from(data, off)[0]
    return lambda data, off: _finish(decode_terminal(plan, data[off:off + width]))


def _follow(read_many, followups, out, stats):
    strings = [f for f in followups if f[3]['type'] == 'string']
    refs = [f for f in followups if f[3]['type'] == 'record_ptr']
    if refs:
        got = read_many([(ptr + 0xC, 8) for _, _, ptr, _ in refs])
        for (code, row, _, _), data in zip(refs, got):
            if data is None:
                out[code][row] = Missing('unreadable live memory')
            else:
                uid, rid = struct.unpack('<II', data)
                out[code][row] = Ref(uid, rid or uid)
    if strings:
        got = read_many([(ptr, 68) for _, _, ptr, _ in strings])
        longer = []
        for (code, row, ptr, _), data in zip(strings, got):
            if data is None:
                got_one = read_many([(ptr, 4)])[0]
                if got_one is None:
                    out[code][row] = Missing('unreadable live memory')
                    continue
                data = got_one
            length = struct.unpack('<I', data[:4])[0]
            if length > 1 << 20:
                out[code][row] = Missing('implausible string length')
            elif length <= len(data) - 4:
                out[code][row] = data[4:4 + length].decode('utf-8', 'replace')
            else:
                longer.append((code, row, ptr, length))
        if longer:
            got = read_many([(ptr + 4, length) for _, _, ptr, length in longer])
            for (code, row, _, _), data in zip(longer, got):
                out[code][row] = Missing('unreadable live memory') if data is None else data.decode('utf-8', 'replace')
        if stats is not None:
            stats['items'] = stats.get('items', 0) + len(strings) + len(longer)


# --------------------------------------------------------------------------- cache file
def cache_document(build, sha256, plans_by_class):
    counts = defaultdict(lambda: defaultdict(int))
    for cls, fields in plans_by_class.items():
        for row in fields.values():
            counts[cls][row['status']] += 1
    return {'format': FORMAT, 'vm_defaults': VM_DEFAULTS, 'build': build, 'sha256': sha256, 'summary': counts,
            'plans': plans_by_class}
