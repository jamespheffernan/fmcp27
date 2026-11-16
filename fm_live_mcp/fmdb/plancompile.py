"""Direct plans compiled from the getter's own code, without sampling records.

`bulkplans` derives a plan by tracing the getter on real records and matching the value to a
traced load; that needs records whose values differ (a column that is constant, unset or
mixed in the sample stays emulated), and on a new build it costs a trace of every field.
This module runs the same shipped getter on a SYNTHETIC record instead and reads the plan
off the code's behaviour:

1. A synthetic object space (`SYN`, outside every address the game uses) holds the record:
   the class's vtable group (primary and secondary vtables, from RTTI) at their offsets and
   zero everywhere else. Everything else the getter touches (globals, interceptor objects,
   language tables, the typed-traits registry) is the live game memory, as in every VM call.
2. Pointer skeleton: an 8-byte load from synthetic memory that reads 0 is tried as a pointer
   (a fresh zeroed synthetic object is linked in); it is kept when the getter then loads from
   that object. This follows the arm of the comparison tree for the key through thunks,
   helper calls and virtual calls on the record (their targets are fixed by the vtables), and
   builds exactly the offset chains the arm dereferences.
3. Data probes: every other synthetic load is set to chosen test values (0, 1, sign
   boundaries, all-ones, a float 1.0, an SI_DATE, a year/day date, single bits) and the getter
   re-run. A load whose values change the result is an input. With exactly one input, the
   plan is the first plan form of `bulkplans` (int signed/unsigned, bool nonzero/bit k, float,
   double, div10, SI_DATE, year/day, colour, with or without zero-is-null) that reproduces
   every probe; a pointer slot whose object answers `{u32 length, bytes}` is a string plan and
   one whose object's +0xC/+0x10 become the result is a record reference.

Anything else (several inputs, arithmetic over fields, calls through pointers held in the
record, results that do not depend on the record) stays emulated with the reason. A compiled
plan is a candidate only: `verify` compares it with the getter on separate real records,
exactly like a traced plan, and a disagreement demotes it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
import struct
import time

from unicorn import UC_HOOK_BLOCK, UC_HOOK_MEM_READ

from . import bulkplans, variant
from .bulkplans import Missing, Ref

SYN = 0x6F00_0000_0000                # synthetic objects (user range; VM PRIVATE is 0x7E00...)
REGION = 0x10_0000                    # one synthetic object per MiB
RECORD_OFFSET = 0x8_0000              # the record sits mid-region (PERSON primaries are below it)
MAX_REGIONS = 64
MAX_RUNS = 400
SKELETON_RUNS = 60                    # pointer-skeleton attempts per field
PAGE = 4096

TESTS = {
    1: (1, 2, 7, 0x41, 0x7F, 0x80, 0xFF),
    2: (1, 2, 100, 0x1234, 0x7FFF, 0x8000, 0xFFFF),
    4: (1, 2, 100, 0x12345678, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 0x3F800000, 0x0FD06400, 0x07E80064),
    8: (1, 2, 1 << 40, 0x3FF0000000000000, 0x8000000000000000, 0xFFFFFFFFFFFFFFFF),
}


class PathTracer:
    """Branch path of each getter call: the set of executed basic blocks of shipped code (RVAs).

    A path hash is blake2b-8 over the sorted block RVAs, so it does not depend on loop counts
    (a 3-character and a 30-character string take the same path) but changes with every
    branch that runs different code. The same definition can be computed in a C block hook."""

    def __init__(self, vm):
        self.vm, self.active, self.blocks = vm, False, set()
        text = vm.image.segment('__TEXT')
        vm.uc.hook_add(UC_HOOK_BLOCK, self._on_block, begin=vm.base, end=vm.base + text.vmsize - 1)

    def _on_block(self, uc, address, size, user):
        if self.active:
            self.blocks.add(address - self.vm.base)

    def start(self):
        self.blocks = set()
        self.active = True

    def stop(self) -> str:
        self.active = False
        return path_hash(self.blocks)


def path_hash(blocks) -> str:
    import hashlib
    data = b''.join(struct.pack('<I', b) for b in sorted(blocks))
    return hashlib.blake2b(data, digest_size=8).hexdigest()


def eq(a, b) -> bool:
    """Result equality for probing (Missing values compare by reason)."""
    if isinstance(a, Missing) or isinstance(b, Missing):
        return isinstance(a, Missing) and isinstance(b, Missing) and a.reason == b.reason
    if type(a) is not type(b):
        return False
    if isinstance(a, float):
        return a == b or (math.isnan(a) and math.isnan(b))
    return bulkplans.same(a, b) if a is not None else b is None


class SynthMemory:
    """Zero-filled synthetic objects; region 0 holds the record."""

    def __init__(self):
        self.pages = {}
        self.parent = [None]           # region -> pointer slot address holding its base (None: record)

    def base(self, region):
        return SYN + region * REGION

    def region_of(self, address):
        return (address - SYN) // REGION

    def new_region(self, slot):
        self.parent.append(slot)
        return self.base(len(self.parent) - 1)

    def read(self, address, length):
        out = bytearray()
        while length > 0:
            page = address & ~(PAGE - 1)
            off = address - page
            n = min(length, PAGE - off)
            data = self.pages.get(page)
            out += data[off:off + n] if data is not None else bytes(n)
            address += n
            length -= n
        return bytes(out)

    def write(self, address, data):
        while data:
            page = address & ~(PAGE - 1)
            off = address - page
            n = min(len(data), PAGE - off)
            buf = self.pages.setdefault(page, bytearray(PAGE))
            buf[off:off + n] = data[:n]
            address += n
            data = data[n:]

    def chain(self, address, record):
        """bulkplans chain of a synthetic address (pointer offsets, then the field offset)."""
        region = self.region_of(address)
        if region == 0:
            return [address - record]
        return self.chain(self.parent[region], record) + [address - self.base(region)]


class _Reader:
    """Synthetic objects from SynthMemory, everything else from the live page cache."""

    def __init__(self, memory, synth):
        self.memory, self.synth = memory, synth

    def read(self, address, length):
        if SYN <= address < SYN + MAX_REGIONS * REGION:
            return self.synth.read(address, length)
        return self.memory.cached_read(address, length)


@dataclass
class Compiled:
    code: str
    plan: dict | None
    reason: str = ''
    runs: int = 0
    seconds: float = 0.0
    loads: int = 0
    inputs: list = field(default_factory=list)
    paths: dict = field(default_factory=dict)       # path hash -> what selects it (compile runs)


class Compiler:
    """Compiles plans for one record class (one VM, one synthetic record per field)."""

    def __init__(self, engine, cls: str, *, binary=None, budget=200_000):
        from . import platform_model, tables
        from .vm import PropertyVM
        self.engine, self.cls = engine, cls
        entry = next(((rva, e) for rva, e in tables.CLASSES.items() if e[0] == cls), None)
        if entry is None:
            raise KeyError(f'unknown record class {cls}')
        self.table_vtable, (_name, _getter, primary) = entry[0], entry[1]
        self.binary = binary or platform_model.load_binary(engine.plugin_path)
        mangled = f'N2db{len(cls)}{cls}E'
        self.group = self.binary.vtables.get(self.binary.type_key(mangled), [])
        offsets = [off for ap, off in self.group if ap == self.table_vtable]
        self.primary = offsets[0] if offsets else (primary or 0)
        self.synth = SynthMemory()
        self.vm = PropertyVM(_Reader(engine.memory, self.synth), engine.base, engine.image, budget=budget,
                             file_resolver=engine.file_resolver())
        self.loads = []
        self._tracing = False
        self.vm.uc.hook_add(UC_HOOK_MEM_READ, self._on_read, begin=SYN, end=SYN + MAX_REGIONS * REGION - 1)
        self.record = self.synth.base(0) + RECORD_OFFSET
        self.runs = 0
        self.paths = PathTracer(self.vm)
        self.log = []                   # (label, value, path) of the runs after the skeleton

    def _on_read(self, uc, access, address, size, value, user):
        if self._tracing and len(self.loads) < 4096:
            self.loads.append((address, size))

    # ---------------------------------------------------------------- synthetic state
    def _reset(self):
        """A fresh synthetic record of this class: its vtable group, zeros elsewhere."""
        self.synth.pages.clear()
        del self.synth.parent[1:]
        primary = self.record - self.primary
        for ap, off in self.group:
            self.synth.write(primary + off, struct.pack('<Q', self.engine.base + ap))
        self._sync()

    def _synthetic_pages(self):
        return [p for p in self.vm.live_pages if SYN <= p < SYN + MAX_REGIONS * REGION]

    def _sync(self):
        """Make the VM see the synthetic memory as it is now: undo the last call's stores, then
        copy every mapped synthetic page (unmapped ones fault in from SynthMemory)."""
        self.vm._restore()
        for page in self._synthetic_pages():
            self.vm._poke(page, self.synth.read(page, PAGE))

    def _set(self, address, data):
        self.vm._restore()
        self.synth.write(address, data)
        for page in range(address & ~(PAGE - 1), address + len(data), PAGE):
            if page in self.vm.live_pages:
                self.vm._poke(page, self.synth.read(page, PAGE))

    def run(self, code, label=None):
        self.loads = []
        self._tracing = True
        self.runs += 1
        self.paths.start()
        try:
            result = self.vm.get_property(self.record, code)
        finally:
            self._tracing = False
            path = self.paths.stop()
        value = bulkplans.canonical(result)
        if label is not None:
            self.log.append((label, value, path))
        self.last_path = path
        return value, list(self.loads)

    def call(self, record, code):
        """(canonical value, path hash) of the getter on any record (a real one for verification)."""
        self.vm._restore()
        self.paths.start()
        try:
            result = self.vm.get_property(record, code)
        finally:
            path = self.paths.stop()
        return bulkplans.canonical(result), path

    # ---------------------------------------------------------------- compile one field
    def compile(self, code) -> Compiled:
        started, runs0 = time.time(), self.runs
        self.runs = 0
        self.log = []
        self._reset()
        out = self._compile(code)
        out.runs, out.seconds = self.runs, time.time() - started
        if out.plan is not None:
            out.paths = self._covered_paths(out.plan)
            out.plan['paths'] = out.paths
        return out

    def _vtable_words(self):
        primary = self.record - self.primary
        return {primary + off for _ap, off in self.group}

    def _compile(self, code) -> Compiled:
        fixed = self._vtable_words()
        value, loads = self.run(code)
        pointers, tried = {}, set()
        # 1. pointer skeleton
        changed = True
        limit = self.runs + SKELETON_RUNS
        while changed and self.runs < limit and len(self.synth.parent) < MAX_REGIONS:
            changed = False
            for address, size in loads:
                if size != 8 or address % 8 or address in fixed or address in pointers or address in tried:
                    continue
                if self.synth.read(address, 8) != bytes(8):
                    continue
                tried.add(address)
                region = len(self.synth.parent)
                base = self.synth.new_region(address)
                self._set(address, struct.pack('<Q', base))
                new_value, new_loads = self.run(code)
                if any(self.synth.region_of(a) == region for a, _ in new_loads):
                    pointers[address] = base
                    value, loads = new_value, new_loads
                    changed = True
                    break
                self.synth.parent.pop()
                self._set(address, bytes(8))
                if self.runs >= limit:
                    break
        self.run(code, label='baseline: every field the arm reads is 0, every pointer it follows is set')
        data = []
        seen = set()
        for address, size in loads:
            if address in fixed or address in pointers or (address, size) in seen:
                continue
            seen.add((address, size))
            data.append((address, size))
        result = Compiled(code, None, loads=len(data))
        # string / record reference through a pointer slot
        plan = self._pointer_plan(code, value, pointers, loads)
        if plan is not None:
            result.plan = plan
            return result
        # 2. data probes
        inputs = []
        observations = {}
        for address, size in data:
            if size not in TESTS or self.runs >= MAX_RUNS:
                continue
            original = self.synth.read(address, size)
            outs = []
            where = self._where(address, size)
            for test in TESTS[size]:
                self._set(address, test.to_bytes(size, 'little'))
                got, _ = self.run(code, label=f'{where} = {test:#x}')
                outs.append((test, got))
            self._set(address, original)
            observations[(address, size)] = outs
            if any(not eq(got, value) for _t, got in outs):
                inputs.append((address, size))
        result.inputs = [(self.synth.chain(a, self.record), s) for a, s in inputs]
        if not inputs:
            result.reason = ('result does not depend on the record' if not isinstance(value, Missing)
                             else f'getter gives {value.reason!r} on the synthetic record')
            return result
        if len(inputs) > 1:
            result.reason = f'{len(inputs)} record fields feed the result'
            return result
        address, size = inputs[0]
        base_bytes = self.synth.read(address, size)
        samples = [(int.from_bytes(base_bytes, 'little'), value)] + observations[(address, size)]
        plan = self._fit(address, size, samples, code)
        if plan is None:
            result.reason = 'no plan form reproduces the probes'
            return result
        problem = self._null_links(address, code)
        if problem:
            result.reason = problem
            return result
        result.plan = plan
        return result

    def _null_links(self, address, code):
        """Each pointer on the plan's chain set to null: the plan reads that as unset (None), so
        the getter must give None too. These runs add the 'pointer is null' branch paths."""
        region = self.synth.region_of(address)
        while region:
            slot = self.synth.parent[region]
            saved = self.synth.read(slot, 8)
            self._set(slot, bytes(8))
            got, _ = self.run(code, label=f'{self._where(slot, 8)} = null')
            self._set(slot, saved)
            if got is not None:
                return f'a null pointer on the chain gives {got!r}, the plan gives None'
            region = self.synth.region_of(slot)
        return None

    def _pointer_plan(self, code, value, pointers, loads):
        """string / record_ptr plans: a pointer slot whose object is read as the value."""
        for slot, base in pointers.items():
            region = self.synth.region_of(base)
            touched = {a - base: s for a, s in loads if self.synth.region_of(a) == region}
            chain = self.synth.chain(slot, self.record)
            mark = len(self.log)
            if touched.get(0) in (4, 8, 16) and (isinstance(value, str) or value is None):
                self._set(base, struct.pack('<I', 3) + b'abc')
                got, _ = self.run(code, label=f'{self._where(slot, 8)} -> 3-byte string')
                self._set(base, bytes(8))
                if got == 'abc':
                    plan = self._finish({'chain': chain, 'width': 8, 'signed': False, 'type': 'string',
                                         'transform': 'identity'}, code, slot)
                    if plan is not None:
                        return plan
                del self.log[mark:]
            if 0xC in touched and isinstance(value, (Ref, type(None))):
                self._set(base + 0xC, struct.pack('<II', 0x1234, 0x5678))
                got, _ = self.run(code, label=f'{self._where(slot, 8)} -> record 0x1234/0x5678')
                self._set(base + 0xC, bytes(8))
                if isinstance(got, Ref) and got.unique_id == 0x1234 and got.random_id == 0x5678:
                    plan = self._finish({'chain': chain, 'width': 8, 'signed': False, 'type': 'record_ptr',
                                         'transform': 'identity'}, code, slot)
                    if plan is not None:
                        return plan
                del self.log[mark:]
        return None

    def _finish(self, plan, code, slot):
        """Null behaviour of a pointer plan: what the getter gives with the pointer cleared."""
        saved = self.synth.read(slot, 8)
        self._set(slot, bytes(8))
        got, _ = self.run(code, label=f'{self._where(slot, 8)} = null')
        self._set(slot, saved)
        if plan['type'] == 'string':
            if got == '':
                return plan
            if got is None:
                return {**plan, 'zero_null': True}
            return None
        return plan if got is None else None

    def _fit(self, address, size, samples, code):
        chain = self.synth.chain(address, self.record)
        forms = [('int', False, 'identity'), ('int', True, 'identity'), ('bool', False, 'nonzero')]
        if size == 4:
            forms += [('float', False, 'identity'), ('sidate', False, 'identity'), ('date_yd', False, 'identity'),
                      ('colour', False, 'identity')]
        if size == 8:
            forms += [('double', False, 'identity')]
        forms += [('float', False, 'div10'), ('float', True, 'div10')]
        for kind, signed, transform in forms:
            for zero_null in (False, True):
                plan = {'chain': chain, 'width': size, 'signed': signed, 'type': kind, 'transform': transform}
                if zero_null:
                    plan['zero_null'] = True
                if all(self._agrees(plan, n, got) for n, got in samples):
                    return plan
        # bool from one bit: find the bit that the result follows
        if all(isinstance(got, bool) or got in (0, 1) for _n, got in samples):
            for bit in range(8 * size):
                plan = {'chain': chain, 'width': size, 'signed': False, 'type': 'bool', 'transform': f'bit:{bit}'}
                original = self.synth.read(address, size)
                self._set(address, (1 << bit).to_bytes(size, 'little'))
                got, _ = self.run(code, label=f'{self._where(address, size)} = bit {bit}')
                self._set(address, original)
                if all(self._agrees(plan, n, g) for n, g in samples + [(1 << bit, got)]):
                    return plan
        return None

    def _where(self, address, size):
        chain = self.synth.chain(address, self.record)
        return 'u%d@[%s]' % (8 * size, ','.join(f'{c:#x}' for c in chain))

    def _covered_paths(self, plan):
        """{path hash: selector} of the compile runs after the skeleton. Every such run is
        consistent with the plan (the plan was fitted to all of them), so these are the branch
        paths the plan was derived on; the selector names the probe that first reached each."""
        out = {}
        for label, _value, path in self.log:
            out.setdefault(path, label)
        return out

    @staticmethod
    def _agrees(plan, n, got):
        data = n.to_bytes(plan['width'], 'little')
        try:
            expected = bulkplans._finish(bulkplans.decode_terminal(plan, data))
        except Exception:  # noqa: BLE001
            return False
        if isinstance(got, Missing) or isinstance(expected, Missing):
            return isinstance(got, Missing) and isinstance(expected, Missing)
        return eq(expected, got) or bulkplans.same(expected, got)


# --------------------------------------------------------------------------- batch + verification
def emulated_codes(plans_by_class: dict) -> dict:
    """{class: [code]} of fields that are emulated today and could take a direct plan (scalar
    results the getter handles; lists/records and unhandled codes are left out)."""
    skip = ('getter does not handle this code', 'non-scalar kind', 'not handled')
    out = {}
    for cls, codes in plans_by_class.items():
        todo = [c for c, p in codes.items() if p.get('status') != 'direct'
                and not str(p.get('reason', '')).startswith(skip)]
        if todo:
            out[cls] = sorted(todo)
    return out


def compile_class(engine, cls, codes, *, binary=None, log=None) -> dict:
    """{code: Compiled} for one class."""
    compiler = Compiler(engine, cls, binary=binary)
    out = {}
    for code in codes:
        try:
            out[code] = compiler.compile(code)
        except Exception as exc:  # noqa: BLE001 - a field that cannot be compiled stays emulated
            out[code] = Compiled(code, None, f'compile error: {type(exc).__name__}: {exc}')
    if log:
        n = sum(1 for c in out.values() if c.plan)
        log(f'compile {cls}: {n} of {len(out)} fields compiled')
    return out


def verify(engine, records: list, plans: dict, *, minimum=10, compiler=None) -> dict:
    """{code: (verdict, compared, distinct, example, paths)}: each compiled plan against the
    getter on `records` (real records of the class, none used to compile).

    verdict: 'verified' | 'demoted' (a value disagreed) | 'uncovered path' (values agreed, but
    a record took a branch path the plan was not derived on, so the plan would serve records
    of that path unproven) | 'too few records'. With `compiler` (the class's Compiler) the
    getter runs on its VM with the path tracer; `paths` counts the paths the records took."""
    if not plans:
        return {}
    values = bulkplans.evaluate(engine.read_many, records, plans)
    out = {}
    for code, plan in plans.items():
        compared, distinct, example, bad, uncovered, seen = 0, set(), None, 0, 0, {}
        covered = set(plan.get('paths') or ())
        for record, got in zip(records, values[code]):
            if compiler is not None:
                expected, path = compiler.call(record, code)
                seen[path] = seen.get(path, 0) + 1
            else:
                expected, path = bulkplans.canonical(engine.get_property(record, code)), None
            if isinstance(expected, Missing) and plan.get('fallback') and expected.reason.endswith('_fseeko'):
                continue
            compared += 1
            distinct.add(repr(expected))
            if not bulkplans.same(got, expected):
                bad += 1
                if example is None:
                    example = f'record {record:#x}: plan {got!r} vs getter {expected!r}'
            elif path is not None and covered and path not in covered:
                uncovered += 1
                if example is None:
                    example = f'record {record:#x} took path {path}, not among the {len(covered)} compiled paths'
        if bad:
            out[code] = ('demoted', compared, len(distinct), f'{bad} of {compared} disagreed ({example})', seen)
        elif uncovered:
            out[code] = ('uncovered path', compared, len(distinct), f'{uncovered} of {compared}: {example}', seen)
        elif compared < minimum:
            out[code] = ('too few records', compared, len(distinct), None, seen)
        else:
            out[code] = ('verified', compared, len(distinct), None, seen)
    return out


def audit_paths(compiler, records: list, plans: dict) -> dict:
    """Branch paths of existing (traced) direct plans over many real records:
    {code: {'paths': {hash: records}, 'disagree': {hash: records}}}. A plan whose records take
    several paths, or whose disagreements sit on a rare path, is the review's 'right on samples,
    wrong on a rare path' case."""
    from collections import Counter
    values = bulkplans.evaluate(compiler.engine.read_many, records, plans)
    out = {}
    for code in plans:
        paths, disagree = Counter(), Counter()
        for record, got in zip(records, values[code]):
            expected, path = compiler.call(record, code)
            paths[path] += 1
            if not bulkplans.same(got, expected) and not (got is None and expected is None):
                disagree[path] += 1
        out[code] = {'paths': dict(paths), 'disagree': dict(disagree)}
    return out


def store_compiled(store, cls, compiled: dict, verdicts: dict):
    """Write verified compiled plans into a PlanStore (origin 'compiled'); others are left alone,
    so the tracer still sees them as missing."""
    n = 0
    for code, (verdict, compared, distinct, _example, _seen) in verdicts.items():
        c = compiled[code]
        if verdict != 'verified' or c.plan is None:
            continue
        store.plans.setdefault(cls, {})[code] = {
            **c.plan, 'status': 'direct', 'origin': 'compiled', 'v': bulkplans.DERIVE_VERSION,
            'verified': compared, 'mismatches': 0, 'distinct_values': distinct,
            'compile_runs': c.runs, 'paths': c.paths}
        n += 1
    return n


COMPILE_VERSION = 1
VERIFY_RECORDS = 50
SKIP_REASONS = ('getter does not handle this code', 'non-scalar kind', 'not handled')


def wanted(store, cls, codes) -> list:
    """Codes of one class worth compiling: missing from the store (a new build), or emulated
    today for a reason a compiled plan can address and not yet tried by this compiler version."""
    plans = store.plans.get(cls, {})
    out = []
    for code in codes:
        p = plans.get(code)
        if p is None:
            out.append(code)
        elif p.get('status') != 'direct' and not str(p.get('reason', '')).startswith(SKIP_REASONS) \
                and p.get('compile') != COMPILE_VERSION:
            out.append(code)
    return out


def upgrade(engine, store, cls, records, codes, *, budget_s=None, binary=None, log=None) -> dict:
    """Compile, verify and store plans for one class (see module docstring).

    Verified plans become `status: direct, origin: compiled`; a demoted or uncompilable field
    that already has an entry gets `compile: COMPILE_VERSION` and `compile_reason`, so later
    builds do not try it again; a missing field stays missing for the tracer."""
    import random
    todo = wanted(store, cls, codes)
    pool = [r for r in dict.fromkeys(records) if r]
    if not todo or len(pool) < 10:
        return {'compiled': 0, 'verified': 0, 'demoted': 0, 'tried': 0, 'seconds': 0.0}
    started = time.time()
    try:
        compiler = Compiler(engine, cls, binary=binary)
    except Exception as exc:  # noqa: BLE001 - no compiler for this engine/class: tracing derives the plans
        if log:
            log(f'compile {cls}: skipped ({type(exc).__name__}: {exc})')
        return {'compiled': 0, 'verified': 0, 'demoted': 0, 'tried': 0, 'seconds': 0.0}
    compiled = {}
    for code in todo:
        if budget_s is not None and time.time() - started > budget_s:
            break
        try:
            compiled[code] = compiler.compile(code)
        except Exception as exc:  # noqa: BLE001 - the field stays emulated
            compiled[code] = Compiled(code, None, f'compile error: {type(exc).__name__}: {exc}')
    rng = random.Random(f'{store.sha256}:{cls}:compiled')
    check = rng.sample(pool, min(VERIFY_RECORDS, len(pool)))
    verdicts = verify(engine, check, {c: r.plan for c, r in compiled.items() if r.plan}, compiler=compiler)
    verified = store_compiled(store, cls, compiled, verdicts)
    demoted = 0
    plans = store.plans.setdefault(cls, {})
    for code, c in compiled.items():
        verdict = verdicts.get(code)
        if verdict and verdict[0] == 'verified':
            continue
        reason = c.reason if verdict is None else f'{verdict[0]}: {verdict[3] or verdict[1]}'
        demoted += bool(verdict)
        if code in plans:
            plans[code] = {**plans[code], 'compile': COMPILE_VERSION, 'compile_reason': reason[:300]}
    store.save()
    seconds = time.time() - started
    if log:
        log(f'compile {cls}: {len(compiled)} fields tried, {sum(1 for c in compiled.values() if c.plan)} compiled, '
            f'{verified} verified on {len(check)} records, {demoted} demoted, {seconds:.1f}s')
    return {'compiled': sum(1 for c in compiled.values() if c.plan), 'verified': verified, 'demoted': demoted,
            'tried': len(compiled), 'seconds': seconds}
