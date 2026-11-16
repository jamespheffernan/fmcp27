"""PropertyVM: emulate a native record's own property getter on copied live bytes.

Every native `db::` record class answers `vtable[3](this, key, out)` (vtable+0x18):
`this` in x0, the FourCC key as a big-endian u32 in w1 ('PCAB' -> 0x50434142),
and a pointer to a 16-byte `sicore` typed value in x2. The getter destroys the
old value through `out->traits->vtable[3]` and stores `{traits*, payload}`
(see variant.py). w0 returns nonzero when the key was handled.

Trust model: the game's getter is the oracle. A value is accepted only when the
unmodified shipped getter, emulated here, produced it from live data; anything
else becomes `Unavailable(reason)`.

Memory model (one Unicorn instance reused across calls):
* Code: the plugin __TEXT segment is paged in from the verified on-disk ARM64
  slice (`image.PluginImage`), mapped R+X. Live code bytes are never executed.
* Data: every other address is faulted in lazily from the live process in 4 KiB
  pages through the supplied reader and cached for the VM session; such pages
  are mapped read/write but never executable.
* Writes: a write hook snapshots a cached live page before its first store in a
  call (copy-on-write inside the VM); the page is restored at the start of the next
  call. Stores to shipped code stop the call. Nothing is ever written to
  the game. Private stack, heap (bump allocator) and TLS live in a window
  (PRIVATE) far above the addresses the game uses.
* External calls: calls through the plugin's import stubs (or to a live address
  bound to an import) run a Python model for a small whitelist (allocation, free,
  locks, static-init guards, mem/str helpers, libm). Any other external call, a
  C++ throw, a fault, an instruction outside the shipped code or budget excess
  stops the call with a typed `Unavailable`.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import math
import os
import struct
import time

from unicorn import (Uc, UcError, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_BLOCK, UC_HOOK_CODE,
                     UC_HOOK_MEM_UNMAPPED, UC_HOOK_MEM_WRITE_PROT, UC_HOOK_MEM_FETCH_PROT,
                     UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_PROT_READ, UC_PROT_WRITE, UC_PROT_EXEC, UC_PROT_ALL)
from unicorn import unicorn_const as UCC
import unicorn.arm64_const as A

PAGE = 4096
PRIVATE = 0x7E00_0000_0000
STACK = PRIVATE
STACK_SIZE = 0x40_0000
HEAP = PRIVATE + 0x1000_0000
HEAP_SIZE = 0x400_0000
TRAP = PRIVATE + 0x2000_0000
TLS = PRIVATE + 0x3000_0000
STATIC = PRIVATE + 0x3800_0000      # persistent VM-private data (overlay objects)
STATIC_SIZE = 0x10_0000
PRIVATE_END = PRIVATE + 0x4000_0000
NULL_LIMIT = 0x1_0000_0000          # macOS __PAGEZERO: no valid user pointer below 4 GiB
GETTER_SLOT = 3
VARIANT_REGISTRY_RVA = 0x573BBA0    # global set by 0x4403cd4: sicore typed-traits registry
DEFAULT_BUDGET = 2_000_000
# Application context. GAME_PLAYER (pointer at global 0x56D2B50) intercepts PERSON
# properties: the base player getter 0x1503624 asks its slot 7 (0x20F2D34, `mov w0,#0`)
# whether to bypass, and otherwise lets slot 9 (0x20BB788) answer, which masks fields
# such as PCAB/PPAB in a running career. view='database' answers slot 7 with the
# shipped `mov w0,#1; ret` at 0x4406A6C through a VM-private copy of the vtable, so the
# record's own database getter runs unmodified. view='game' keeps the interceptor.
#
# GAME_PERSON (pointer at global 0x56D2CC8) is the same pattern one level down: the PERSON
# property tree 0x148F9B8 asks its slot 7 (0x20859A8, `mov w0,#0`) whether to bypass and
# otherwise lets slot 11 (0x206C8E4) answer. Slot 11 masks the eight personality ratings
# (Pada, Pamb, Pcvy, Ploy, Ppre, Ppro, Pspo, Ptem) with a NULL value unless game-option
# flags around 0x56D4987/0x56D498B are set, i.e. the game hides them from the UI.
#
# Every record class getter follows this pattern with its own game-layer object: a static
# scan of the shipped code for `adrp; ldr x0,[global]; ldr x8,[x0]; ldr x8,[x8,#0x38];
# blr x8; tbnz/tbz w0,#0` finds the 15 globals in INTERCEPTORS, each with slot 7 the
# shipped `mov w0,#0; ret`. GAME_ACTUAL_NON_PLAYER hides staff tendencies, board
# attributes and versatility (Natt, Nbus, Npvr ...) the same way; GAME_CLUB answers Csth
# and stadium fields only after a bypass. view='database' bypasses all of them. When the
# record's own getter does not claim a key (w0 == 0), the call is repeated with the
# interceptors in place, so keys only the game layer answers stay available; such a
# result has `PropertyResult.view == 'game'`.
APP_GLOBAL_RVA = 0x56D2B50
APP_RTTI = '11GAME_PLAYER'
APP_BYPASS_SLOT = 7
APP_BYPASS_ORIGINAL_RVA = 0x20F2D34
RETURN_TRUE_RVA = 0x4406A6C
APP_VTABLE_SLOTS = 96
# (global RVA, RTTI, bypass slot, shipped bypass function) for every interceptor the
# database view answers with RETURN_TRUE_RVA.
INTERCEPTORS = (
    (APP_GLOBAL_RVA, APP_RTTI, APP_BYPASS_SLOT, APP_BYPASS_ORIGINAL_RVA),
    (0x56D2CC8, '11GAME_PERSON', 7, 0x20859A8),
    (0x56D2CB0, '22GAME_ACTUAL_NON_PLAYER', 7, 0x1F56BC8),
    (0x56D2D08, '18GAME_ACTUAL_PLAYER', 7, 0x1F9F69C),
    (0x56D2CA0, '21GAME_HUMAN_NON_PLAYER', 7, 0x204E3C0),
    (0x56D2CD8, '19GAME_RETIRED_PERSON', 7, 0x20F5D64),
    (0x56D2CE8, '9GAME_CLUB', 7, 0x1FC7914),
    (0x56D2CC0, '28GAME_NATIONAL_TEAM_CONTAINER', 7, 0x2065310),
    (0x56D2CF8, '19GAME_TEAM_CONTAINER', 7, 0x2206E18),
    (0x56D2D10, '9GAME_COMP', 7, 0x2014024),
    (0x56D2CE0, '12GAME_STADIUM', 7, 0x2114E00),
    (0x56D2C90, '10GAME_AWARD', 7, 0x1FA1CD4),
    (0x56D2CA8, '17GAME_MEDIA_SOURCE', 7, 0x20602CC),
    (0x56D3838, '14GAME_DB_RECORD', 7, 0x2019554),
    (0x56D3840, '14GAME_CONTINENT', 7, 0x201895C),
)
# Thread context. Getters compare pthread_self() with the game's owning thread
# (flag 0x56C10E8 == 1: stored word 0x56C10F0, else pthread_equal with 0x56D66B0).
# On the owning thread some getters lazily bring cached state up to date (e.g. player
# condition/fitness recovery, which draws on a thread-local RNG). thread='reader'
# (default) answers with a VM-private thread id, i.e. a non-owning reader thread, so
# stored values are returned; thread='owner' answers with the owning thread's word
# (the model used by knowledge_relation_fixes).
THREAD_FLAG_RVA = 0x56C10E8
THREAD_MAIN_RVA = 0x56C10F0
THREAD_OTHER_RVA = 0x56D66B0
INT_REGS = [getattr(A, f'UC_ARM64_REG_X{i}') for i in range(29)]
# Long list walks (competition team lists, region city lists) are repeated once with a larger
# budget and timeout (PropertyVM.get_property); the result is cached per (record, key).
LONG_BUDGET_FACTOR = 25
LONG_TIMEOUT_FACTOR = 12
LONG_REASONS = ('instruction budget exceeded', 'emulation stopped early (timeout)')


# Stops that a pointer read from a page copied earlier than its neighbours produces (the game has
# since replaced it): get_property repeats such a call once on fresh pages.
STALE_SYMPTOMS = ('unreadable live memory', 'call into non-plugin code', 'write to shipped code',
                  'write to protected memory')


def _stale_symptom(reason):
    return reason in STALE_SYMPTOMS or reason.startswith('cpu fault')


def _is_long(result):
    value = result.value
    return isinstance(value, Unavailable) and value.reason in LONG_REASONS


class Unavailable:
    """A value the emulated getter did not (or could not) produce, with the reason."""
    __slots__ = ('reason', 'raw', 'detail')

    def __init__(self, reason, raw=None, detail=None):
        self.reason, self.raw, self.detail = reason, raw, detail

    def __bool__(self):
        return False

    def __eq__(self, other):
        return isinstance(other, Unavailable) and other.reason == self.reason

    def __hash__(self):
        return hash(self.reason)

    def __repr__(self):
        return f'Unavailable({self.reason!r})'

    def to_json(self):
        out = {'unavailable': self.reason}
        if self.detail:
            out['detail'] = self.detail
        if self.raw is not None:
            out['raw'] = self.raw.hex() if isinstance(self.raw, (bytes, bytearray)) else self.raw
        return out


class _Stop(Exception):
    def __init__(self, reason, detail=None):
        super().__init__(reason)
        self.reason, self.detail = reason, detail


@dataclass
class CallStats:
    instructions: int = 0
    seconds: float = 0.0
    externals: list = field(default_factory=list)
    mutated_pages: int = 0
    new_pages: int = 0
    returned: int | None = None
    rng_draws: int = 0            # accesses to the thread-local RNG / std::random_device (RNG.md)
    marked: list = field(default_factory=list)   # modelled externals whose value is a stand-in


@dataclass
class PropertyResult:
    key: str
    value: object                 # decoded Python value, or Unavailable
    kind: str | None              # traits class short name, e.g. 'int', 'string', 'record'
    handled: bool | None          # getter's w0
    stats: CallStats
    view: str | None = None       # 'database', or 'game' when only the game layer claimed the key
    # None: the call drew no random numbers. 'stable': it drew, and the value was identical under
    # two different private generators (rng='isolate'; the two-seed rule, REFUSALS.md).
    # 'private': drawn from a VM-private generator and not checked: not what the game shows.
    rng: str | None = None

    @property
    def ok(self):
        return not isinstance(self.value, Unavailable)

    @property
    def marks(self) -> list:
        """Stand-ins that reached this call (vm.mark): host clock, offline Steam, host stat."""
        return list(self.stats.marked)


class RetryReader:
    """A failed live read is asked once more after a short pause before the VM calls the page
    unreadable. The game runs while the VM reads, so a page can be briefly unmapped or remapped
    (allocator churn); a second, fresh read separates that race from a real hole (guard page,
    freed or never-mapped memory). A page the inner reader remembers as bad is forgotten first.
    Counts: `retried` (second reads), `recovered` (second read succeeded)."""

    def __init__(self, inner, pause=0.005):
        self.inner, self.pause = inner, pause
        self.retried = self.recovered = 0

    def read(self, address, length):
        try:
            return self.inner.read(address, length)
        except Exception:  # noqa: BLE001 - any refusal; the second refusal propagates
            self.retried += 1
            for holder in (self.inner, getattr(self.inner, 'memory', None)):
                bad = getattr(holder, '_bad_pages', None)
                if isinstance(bad, set):
                    page_size = getattr(holder, 'page_size', PAGE)
                    bad.difference_update(range(address - address % page_size, address + max(length, 1), page_size))
            time.sleep(self.pause)
            data = self.inner.read(address, length)
            self.recovered += 1
            return data

    def __getattr__(self, name):
        return getattr(self.inner, name)


def _u64(b, o=0):
    return struct.unpack_from('<Q', b, o)[0]


class PropertyVM:
    def __init__(self, reader, base: int, image, *, budget: int = DEFAULT_BUDGET,
                 timeout_us: int = 5_000_000, view: str = 'database', thread: str = 'reader',
                 file_resolver=None, rng: str | None = None, retry_long: bool | None = None):
        if view not in ('database', 'game'):
            raise ValueError("view must be 'database' or 'game'")
        if thread not in ('reader', 'owner'):
            raise ValueError("thread must be 'reader' or 'owner'")
        self.view, self.thread = view, thread
        # Random numbers (docs/fmdb/REFUSALS.md "RNG"): 'isolate' (default) gives the code a
        # VM-private generator and keeps a value only when a second private generator gives the
        # same value; 'private' keeps the first value (marked); 'refuse' stops at the first draw.
        # Subclasses may set self.rng first (UiHandlerVM adds 'copy').
        if rng is not None or not hasattr(self, 'rng'):
            self.rng = rng or DEFAULT_RNG
        if self.rng not in RNG_POLICIES + ('copy',):
            raise ValueError(f'rng must be one of {RNG_POLICIES}')
        for name, value in (('rng_uses', 0), ('rng_seed', RNG_SEEDS[0]), ('_rng_cell', None),
                            ('marked', Counter())):
            if not hasattr(self, name):
                setattr(self, name, value)
        self.retry_long = (not LEGACY) if retry_long is None else retry_long
        # stale-page retry (get_property); UiHandlerVM turns it off: it would drop committed state
        self.retry_stale = self.retry_long
        self._stale_checked, self.stale_retries, self.stale_recovered = set(), 0, 0
        self.owner_retries = 0
        self._long_results = {}     # (record, key) -> PropertyResult after a raised budget
        # Read-only game files (see FILE_EXTERNALS). Without an explicit resolver, one is made
        # from the reader's process id when the reader has one (live.StreamReader, LiveMemory
        # and engine._VMReader do): `.fmf` data files are then read wherever a session exists.
        # file_resolver=False turns file access off. Subclasses may set these first.
        if file_resolver is None and not getattr(self, 'file_resolver', None) and not LEGACY:
            file_resolver = _auto_file_resolver(reader)
        if file_resolver is False:
            file_resolver = None
        if file_resolver is not None or not hasattr(self, 'file_resolver'):
            self.file_resolver = file_resolver
        for name, value in (('_open_files', {}), ('_fpos', {}), ('files_read', set()), ('bytes_from_files', 0)):
            if not hasattr(self, name):
                setattr(self, name, value)
        if not NULL_LIMIT <= base < PRIVATE - 0x1_0000_0000:
            raise ValueError('Plugin base overlaps the VM private window')
        if not LEGACY and not isinstance(reader, RetryReader):
            reader = RetryReader(reader)
        self.reader, self.base, self.image = reader, base, image
        self.budget, self.timeout_us = budget, timeout_us
        self.text_end = base + image.segment('__TEXT').vmsize
        self.stub_start = base + image.stub_range[0]
        self.stub_end = base + image.stub_range[1]
        self.static_top = STATIC
        self.overlays = {}          # live address -> bytes, re-applied after invalidate()
        self.code_pages = set()
        self.live_pages = {}        # page -> True (cached, mapped read-only)
        self.unreadable = set()     # pages the reader refused
        self.dirty = {}             # page -> original bytes (copy-on-write inside the VM)
        self.heap_top = HEAP
        self.allocations = {}
        self._tlv_block = None
        self._typeinfo_vtables = None
        self.live_imports = None    # live address -> import name (lazy)
        self.stubbed = Counter()    # modelled external calls, all calls
        self.refused = Counter()    # external calls that stopped a call
        self.trace = None           # optional list for load tracing (plans.py)
        self.block_trace = None     # optional list of executed block addresses (debugging)
        self._stop = None
        self._pending = None
        self._icount = 0
        self._call = None
        self._rtti = {}
        self._init_uc()
        self._session_setup()

    def _init_uc(self):
        """Create the Unicorn instance, map the private areas and install the hooks
        (fastvm.FastVM replaces this with a pool-backed instance and C callbacks)."""
        self.uc = uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        uc.ctl_set_cpu_model(A.UC_CPU_ARM64_MAX)
        uc.mem_map(STACK, STACK_SIZE, UC_PROT_READ | UC_PROT_WRITE)
        uc.mem_map(HEAP, HEAP_SIZE, UC_PROT_READ | UC_PROT_WRITE)
        uc.mem_map(TLS, PAGE, UC_PROT_READ | UC_PROT_WRITE)
        uc.mem_map(STATIC, STATIC_SIZE, UC_PROT_READ | UC_PROT_WRITE)
        uc.mem_map(TRAP, PAGE, UC_PROT_READ | UC_PROT_EXEC)
        uc.mem_write(TRAP, b'\xc0\x03\x5f\xd6' * (PAGE // 4))   # ret (never executed: stop address)
        uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._on_unmapped)
        uc.hook_add(UC_HOOK_MEM_WRITE_PROT, self._on_write_prot)
        uc.hook_add(UC_HOOK_MEM_WRITE, self._on_write, begin=NULL_LIMIT, end=PRIVATE - 1)
        uc.hook_add(UC_HOOK_MEM_FETCH_PROT, self._on_fetch_prot)
        uc.hook_add(UC_HOOK_BLOCK, self._on_block)
        uc.hook_add(UC_HOOK_CODE, self._on_stub, begin=self.stub_start, end=self.stub_end - 1)

    def _session_setup(self):
        # every new snapshot (also FastVM.invalidate, which does not call PropertyVM.invalidate)
        self._long_results = {}
        self.registry = self.read_u64(self.base + VARIANT_REGISTRY_RVA)
        if self.registry < NULL_LIMIT:
            raise ValueError('sicore typed-traits registry is not initialised in the live game')
        self._interceptors = []
        if self.view == 'database':
            self._database_view()

    def _static(self, data: bytes, align=16):
        top = (self.static_top + align - 1) & ~(align - 1)
        if top + len(data) > STATIC + STATIC_SIZE:
            raise ValueError('VM static area exhausted')
        self.uc.mem_write(top, data)
        self.static_top = top + len(data)
        return top

    def set_overlay(self, address: int, data: bytes):
        """Replace live bytes inside the VM for the whole session (never written to the game)."""
        self.ensure(address, len(data))
        for page in range(address & ~(PAGE - 1), address + len(data), PAGE):
            if page in self.code_pages:
                raise ValueError('Overlays may not touch shipped code')
        self._poke(address, data)
        self.overlays[address] = data

    def _database_view(self):
        if self.image.file_bytes(RETURN_TRUE_RVA, 8) != bytes.fromhex('20008052c0035fd6'):
            raise ValueError('Shipped return-true helper changed; database view refused')
        for global_rva, rtti, slot, original in INTERCEPTORS:
            app = self.read_u64(self.base + global_rva)
            if app < NULL_LIMIT and global_rva != APP_GLOBAL_RVA:
                continue            # game-layer object not created (no running game): nothing to bypass
            vtable = self.read_u64(app)
            name = rtti.lstrip('0123456789')
            if self.rtti_name(vtable) != rtti:
                raise ValueError(f'Application object is not {name}; database view refused')
            if self.read_u64(vtable + slot * 8) != self.base + original:
                raise ValueError(f'{name} bypass slot changed; database view refused')
            if self.image.file_bytes(original, 8) != bytes.fromhex('00008052c0035fd6'):
                raise ValueError(f'{name} bypass function changed; database view refused')
            header = self.read(vtable - 16, 16)
            slots = bytearray(self.read(vtable, APP_VTABLE_SLOTS * 8))
            struct.pack_into('<Q', slots, slot * 8, self.base + RETURN_TRUE_RVA)
            copy = self._static(header + bytes(slots)) + 16
            self.set_overlay(app, struct.pack('<Q', copy))
            self._interceptors.append((app, vtable, copy))

    def _use_interceptors(self, bypassed: bool):
        """Point each interceptor object at its bypass copy (True) or its shipped vtable (False)."""
        self._restore()   # a later restore must not bring back the other pointer
        for app, vtable, copy in self._interceptors:
            value = struct.pack('<Q', copy if bypassed else vtable)
            self._poke(app, value)
            self.overlays[app] = value

    # ------------------------------------------------------------------ memory
    def _poke(self, address: int, data: bytes):
        """Store bytes in mapped VM memory without copy-on-write (overlays, the out value)."""
        self.uc.mem_write(address, data)

    def _fault_in(self, page):
        if page in self.live_pages or page in self.code_pages:
            return
        if PRIVATE <= page < PRIVATE_END:  # every private range is pre-mapped
            raise _Stop('access to unmapped VM-private memory', hex(page))
        if page < NULL_LIMIT:
            raise _Stop('null or low pointer dereference', hex(page))
        rva = page - self.base
        if 0 <= rva < self.image.segment('__TEXT').vmsize:
            self.uc.mem_map(page, PAGE, UC_PROT_READ | UC_PROT_EXEC)
            self.uc.mem_write(page, self.image.file_bytes(rva, PAGE))
            self.code_pages.add(page)
            return
        if page in self.unreadable:
            raise _Stop('unreadable live memory', hex(page))
        try:
            data = self.reader.read(page, PAGE)
        except Exception as exc:  # noqa: BLE001 - any reader refusal is a fault
            self.unreadable.add(page)
            raise _Stop('unreadable live memory', f'{page:#x}: {exc}') from None
        self.uc.mem_map(page, PAGE, UC_PROT_READ | UC_PROT_WRITE)
        self.uc.mem_write(page, data)
        self.live_pages[page] = True
        if self._call is not None:
            self._call.new_pages += 1

    def ensure(self, address, length):
        for page in range(address & ~(PAGE - 1), address + max(length, 1), PAGE):
            self._fault_in(page)

    def read(self, address: int, length: int) -> bytes:
        """VM view of memory: VM-private data, copied-on-write pages, else live (faulted in)."""
        if length <= 0:
            return b''
        if not (PRIVATE <= address < PRIVATE_END):
            self.ensure(address, length)
        return bytes(self.uc.mem_read(address, length))

    def read_u64(self, address):
        return _u64(self.read(address, 8))

    def write(self, address: int, data: bytes):
        """Write inside the VM only (copy-on-write for cached live pages)."""
        if not data:
            return
        if not (PRIVATE <= address < PRIVATE_END):
            for page in range(address & ~(PAGE - 1), address + len(data), PAGE):
                if page in self.code_pages:
                    raise _Stop('write to shipped code', hex(page))
                self._fault_in(page)
                self._make_dirty(page)
        self.uc.mem_write(address, bytes(data))

    def _make_dirty(self, page):
        if page not in self.dirty:
            self.dirty[page] = bytes(self.uc.mem_read(page, PAGE))
            if self._call is not None:
                self._call.mutated_pages += 1

    def invalidate(self):
        """Forget every cached live page (start a new snapshot)."""
        self._restore()
        for page in list(self.live_pages):
            self.uc.mem_unmap(page, PAGE)
        self.live_pages.clear()
        self.unreadable.clear()
        self.live_imports = None
        self._typeinfo_vtables = None
        self._rtti.clear()
        self.overlays.clear()
        self.static_top = STATIC
        self._session_setup()

    def refresh_pages(self):
        """Drop every copied page, here and in the reader's page cache, so the next call reads
        the game's current memory."""
        seen = set()
        for holder in (self.reader, getattr(self.reader, 'inner', None), getattr(self.reader, 'memory', None)):
            drop = getattr(holder, 'invalidate', None)
            if callable(drop) and id(holder) not in seen and holder is not self:
                seen.add(id(holder))
                try:
                    drop()
                except Exception:  # noqa: BLE001 - a reader without a cache
                    pass
        self.invalidate()

    def _restore(self):
        for page, original in self.dirty.items():
            self.uc.mem_write(page, original)
        self.dirty.clear()
        if self.heap_top != HEAP:
            used = self.heap_top - HEAP
            self.uc.mem_write(HEAP, b'\0' * used)
        self.heap_top = HEAP
        self.allocations.clear()
        self._tlv_block = None
        self._rng_cell = None
        self._rd_count = 0

    def rtti_name(self, vtable: int) -> str | None:
        """Itanium RTTI name of a vtable (vtable[-1] -> type_info -> name)."""
        if vtable in self._rtti:
            return self._rtti[vtable]
        name = None
        try:
            info = self.read_u64(vtable - 8)
            ptr = self.read_u64(info + 8) & ((1 << 63) - 1)
            raw = self.read(ptr, 160)
            name = raw.split(b'\0', 1)[0].decode('latin-1')
        except _Stop:
            name = None
        self._rtti[vtable] = name
        return name

    # ------------------------------------------------------------------ hooks
    def _fail(self, uc, reason, detail=None):
        if self._stop is None:
            self._stop = _Stop(reason, detail)
        uc.emu_stop()
        return False

    def _on_unmapped(self, uc, access, address, size, value, user):
        try:
            if access == UCC.UC_MEM_FETCH_UNMAPPED:
                if self.base <= address < self.text_end:
                    self._fault_in(address & ~(PAGE - 1))
                    return True
                return self._external_jump(uc, address)
            for page in range(address & ~(PAGE - 1), address + max(size, 1), PAGE):
                self._fault_in(page)
                if access == UCC.UC_MEM_WRITE_UNMAPPED:
                    if page in self.code_pages:
                        raise _Stop('write to shipped code', hex(address))
                    self._make_dirty(page)
            return True
        except _Stop as stop:
            return self._fail(uc, stop.reason, stop.detail)

    def _on_write(self, uc, access, address, size, value, user):
        # Fires before the store: snapshot each live page once per call (copy-on-write).
        try:
            for page in range(address & ~(PAGE - 1), address + max(size, 1), PAGE):
                if page in self.dirty:
                    continue
                if page in self.code_pages:
                    raise _Stop('write to shipped code', hex(address))
                self._fault_in(page)
                if page in self.code_pages:
                    raise _Stop('write to shipped code', hex(address))
                self._make_dirty(page)
        except _Stop as stop:
            self._fail(uc, stop.reason, stop.detail)

    def _on_write_prot(self, uc, access, address, size, value, user):
        return self._fail(uc, 'write to shipped code' if (address & ~(PAGE - 1)) in self.code_pages
                          else 'write to protected memory', hex(address))

    def _on_fetch_prot(self, uc, access, address, size, value, user):
        return self._external_jump(uc, address)

    def _external_jump(self, uc, address):
        name = self._live_import(address)
        if name is None:
            return self._fail(uc, 'call into non-plugin code', hex(address))
        self._pending = name
        uc.emu_stop()
        return False

    def _live_import(self, address):
        if self.live_imports is None:
            table = {}
            for rva, name in self.image.binds.items():
                try:
                    table.setdefault(self.read_u64(self.base + rva) & ((1 << 47) - 1), name)
                except _Stop:
                    continue
            self.live_imports = table
        return self.live_imports.get(address)

    def _on_block(self, uc, address, size, user):
        self._icount += size >> 2
        if self.block_trace is not None:
            self.block_trace.append(address)
        if self._icount > self.budget:
            self._fail(uc, 'instruction budget exceeded', str(self.budget))

    def _on_stub(self, uc, address, size, user):
        name = self.image.stubs.get(address - self.base)
        if name is None:
            return
        # Run the model in the hook and continue at the caller: a PC write inside a code
        # hook ends the current block and resumes there (Unicorn >= 2), avoiding an
        # emu_start restart per external call.
        try:
            self._external(name)
        except _Stop as stop:
            self._fail(uc, stop.reason, stop.detail)
            return
        uc.reg_write(A.UC_ARM64_REG_PC, uc.reg_read(A.UC_ARM64_REG_LR))

    # ------------------------------------------------------------------ externals
    def _x(self, i):
        return self.uc.reg_read(INT_REGS[i])

    def _ret(self, value=0):
        self.uc.reg_write(A.UC_ARM64_REG_X0, value & (2**64 - 1))

    def alloc(self, size, align=16):
        size = max(int(size), 1)
        top = (self.heap_top + align - 1) & ~(align - 1)
        if top + size > HEAP + HEAP_SIZE:
            raise _Stop('VM heap exhausted', str(size))
        self.heap_top = top + size
        self.allocations[top] = size
        return top

    def _external(self, name):
        model = EXTERNALS.get(name)
        if model is None and self.file_resolver is not None and name in FILE_EXTERNALS:
            model = _file_model(name)
        if model is None:
            self.refused[name] += 1
            raise _Stop(REFUSALS.get(name, f'external call {name}'), name)
        self.stubbed[name] += 1
        if self._call is not None:
            self._call.externals.append(name)
        model(self)

    # ------------------------------------------------------------------ calls
    def call(self, address: int, args=(), *, fargs=()):
        """Run one function at an absolute address; returns (x0, CallStats) or raises _Stop."""
        uc = self.uc
        self._restore()
        self._stop = self._pending = None
        self._icount = 0
        stats = self._call = self.last_stats = CallStats()
        started = time.perf_counter()
        for reg in INT_REGS:
            uc.reg_write(reg, 0)
        for i, value in enumerate(args):
            uc.reg_write(INT_REGS[i], value & (2**64 - 1))
        for i, value in enumerate(fargs):
            uc.reg_write(getattr(A, f'UC_ARM64_REG_D{i}'), struct.unpack('<Q', struct.pack('<d', value))[0])
        uc.reg_write(A.UC_ARM64_REG_SP, STACK + STACK_SIZE - 0x1000)
        uc.reg_write(A.UC_ARM64_REG_X29, 0)
        uc.reg_write(A.UC_ARM64_REG_LR, TRAP)
        uc.reg_write(A.UC_ARM64_REG_TPIDRRO_EL0, TLS)
        uc.reg_write(A.UC_ARM64_REG_TPIDR_EL0, TLS)
        pc = address
        try:
            while True:
                try:
                    uc.emu_start(pc, TRAP, timeout=self.timeout_us)
                except UcError as exc:
                    if self._stop is not None:
                        raise self._stop from None
                    if self._pending is None:
                        at = uc.reg_read(A.UC_ARM64_REG_PC)
                        raise _Stop(f'cpu fault: {exc}', f'pc={at - self.base:#x}') from None
                if self._stop is not None:
                    raise self._stop
                if self._pending is not None:
                    name, self._pending = self._pending, None
                    self._external(name)
                    if self._stop is not None:
                        raise self._stop
                    pc = uc.reg_read(A.UC_ARM64_REG_LR)
                    continue
                pc = uc.reg_read(A.UC_ARM64_REG_PC)
                if pc != TRAP:
                    raise _Stop('emulation stopped early (timeout)', f'pc={pc - self.base:#x}')
                break
            if uc.reg_read(A.UC_ARM64_REG_SP) != STACK + STACK_SIZE - 0x1000:
                raise _Stop('callee did not restore SP')
            result = uc.reg_read(A.UC_ARM64_REG_X0)
        finally:
            stats.instructions = self._icount
            stats.seconds = time.perf_counter() - started
            self._call = None
        stats.returned = result
        return result, stats

    def getter_address(self, record: int) -> int:
        vtable = self.read_u64(record)
        return self.read_u64(vtable + GETTER_SLOT * 8)

    def get_property(self, record: int, key, *, game_fallback: bool = True) -> PropertyResult:
        """Emulate `record.vtable[3](record, key, out)` and decode `out`.

        In the database view a key the record's own getter does not claim is asked again
        with the game-layer interceptors in place (result view 'game'), unless
        `game_fallback` is False.

        Random draws follow `self.rng` (see RNG_POLICIES). A call stopped by the instruction
        budget or the timeout (long list walks) is repeated once with LONG_BUDGET_FACTOR times
        the budget and LONG_TIMEOUT_FACTOR times the timeout; that result is kept per
        (record, key) until invalidate().

        A call stopped by unreadable live memory is repeated once on fresh pages (the VM's and
        the reader's caches dropped): the game runs while the VM copies pages, so pages copied at
        different times can hold a pointer the game has already replaced (`stale_retries`,
        `stale_recovered`)."""
        result = self._get_property_rng(record, key)
        if (self.retry_stale and isinstance(result.value, Unavailable)
                and _stale_symptom(result.value.reason) and (record, key) not in self._stale_checked):
            self._stale_checked.add((record, key))
            self.refresh_pages()
            result = self._get_property_rng(record, key)
            self.stale_retries += 1
            self.stale_recovered += int(result.ok)
        if (self.retry_stale and self.thread == 'reader' and isinstance(result.value, Unavailable)
                and result.value.reason == OWNER_THREAD):
            self.thread = 'owner'
            try:
                result = self._get_property_rng(record, key)
            finally:
                self.thread = 'reader'
            self.owner_retries += 1
        if self.retry_long and _is_long(result):
            cached = self._long_results.get((record, key))
            if cached is None:
                budget, timeout = self.budget, self.timeout_us
                self.budget, self.timeout_us = budget * LONG_BUDGET_FACTOR, timeout * LONG_TIMEOUT_FACTOR
                st = getattr(self, '_st', None)        # FastVM keeps its timeout in C state ticks
                ticks = st.timeout_ticks if st is not None else None
                if st is not None:
                    st.timeout_ticks = ticks * LONG_TIMEOUT_FACTOR
                try:
                    cached = self._get_property_rng(record, key)
                finally:
                    self.budget, self.timeout_us = budget, timeout
                    if st is not None:
                        st.timeout_ticks = ticks
                if _is_long(cached):
                    detail = (f'budget {budget * LONG_BUDGET_FACTOR} instructions, '
                              f'{timeout * LONG_TIMEOUT_FACTOR // 1_000_000} s')
                    cached.value = Unavailable(cached.value.reason, detail=detail)
                self._long_results[(record, key)] = cached
            result = cached
        result.view = self.view
        if (game_fallback and self._interceptors and result.handled is False
                and result.value is None):
            self._use_interceptors(False)
            try:
                game = self._get_property_rng(record, key)
            finally:
                self._use_interceptors(True)
            if game.handled:
                game.view = 'game'
                return game
        return result

    def _get_property_rng(self, record: int, key) -> PropertyResult:
        """_get_property under the RNG policy (isolate: a second run with another seed)."""
        if self.rng not in ('private', 'isolate'):
            return self._get_property(record, key)
        self.rng_seed = RNG_SEEDS[0]
        first = self._get_property(record, key)
        if not first.stats.rng_draws:
            return first
        if self.rng == 'private' or not first.ok:
            first.rng = 'private' if first.ok else None
            return first
        self.rng_seed = RNG_SEEDS[1]
        try:
            second = self._get_property(record, key)
        finally:
            self.rng_seed = RNG_SEEDS[0]
        from . import variant
        same = second.ok and second.kind == first.kind and second.handled == first.handled
        if same:
            try:
                same = variant.to_json(first.value) == variant.to_json(second.value)
            except Exception:  # noqa: BLE001 - undecodable: treat as different
                same = False
        if same:
            first.rng = 'stable'
            return first
        first.value = Unavailable(RNG_DEPENDS, detail=f'{first.stats.rng_draws} draws; '
                                  'the game draws from a per-thread generator seeded by std::random_device')
        return first

    def _get_property(self, record: int, key) -> PropertyResult:
        from . import variant
        from ._editor_fields import fourcc, fourcc_text
        code = key if isinstance(key, str) else fourcc_text(key)
        number = fourcc(key) if isinstance(key, str) else key
        stats = CallStats()
        self.last_stats = None
        try:
            self._restore()  # read the vtable from the snapshot, not a previous call's stores
            getter = self.getter_address(record)
            if not (self.base + self.image.text_range[0] <= getter < self.base + self.image.text_range[1]):
                return PropertyResult(code, Unavailable('getter outside shipped code', detail=hex(getter)),
                                      None, None, stats)
            out = STACK + 0x100      # below the stack top used by the callee frame
            self._restore()
            self._poke(out, struct.pack('<QQ', self.registry + 8, 0) + b'\0' * 16)
            returned, stats = self.call(getter, (record, number, out))
        except _Stop as stop:
            stats = getattr(self, 'last_stats', None) or stats
            return PropertyResult(code, Unavailable(stop.reason, detail=stop.detail), None, None, stats)
        try:
            kind, value = variant.decode(self, out)
        except _Stop as stop:
            kind, value = None, Unavailable('variant decode fault: ' + stop.reason, detail=stop.detail)
        except (ValueError, struct.error, UcError, UnicodeError) as exc:
            kind, value = None, Unavailable('variant decode error', detail=str(exc))
        return PropertyResult(code, value, kind, bool(returned & 0xFFFFFFFF), stats)


# ---------------------------------------------------------------------- external models
def _bits_d(vm, i=0):
    return struct.unpack('<d', struct.pack('<Q', vm.uc.reg_read(getattr(A, f'UC_ARM64_REG_D{i}'))))[0]


def _bits_s(vm, i=0):
    return struct.unpack('<f', struct.pack('<I', vm.uc.reg_read(getattr(A, f'UC_ARM64_REG_D{i}')) & 0xFFFFFFFF))[0]


def _ret_d(vm, value):
    vm.uc.reg_write(A.UC_ARM64_REG_D0, struct.unpack('<Q', struct.pack('<d', value))[0])


def _ret_s(vm, value):
    vm.uc.reg_write(A.UC_ARM64_REG_D0, struct.unpack('<I', struct.pack('<f', value))[0])


def _malloc(vm):
    vm._ret(vm.alloc(vm._x(0)))


def _calloc(vm):
    vm._ret(vm.alloc(vm._x(0) * vm._x(1)))


def _realloc(vm):
    old, size = vm._x(0), vm._x(1)
    new = vm.alloc(size)
    if old:
        keep = min(vm.allocations.get(old, size), size)
        vm.write(new, vm.read(old, keep))
    vm._ret(new)


def _aligned_new(vm):
    vm._ret(vm.alloc(vm._x(0), max(16, vm._x(1))))


def _posix_memalign(vm):
    pointer = vm.alloc(vm._x(2), max(16, vm._x(1)))
    vm.write(vm._x(0), struct.pack('<Q', pointer))
    vm._ret(0)


def _noop(vm):
    vm._ret(0)


def _true(vm):
    vm._ret(1)


def _pthread_self(vm):
    if vm.thread == 'reader':
        vm._ret(TLS)
        return
    flag = vm.read(vm.base + THREAD_FLAG_RVA, 1)[0]
    vm._ret(vm.read_u64(vm.base + (THREAD_MAIN_RVA if flag == 1 else THREAD_OTHER_RVA)))


def _pthread_equal(vm):
    vm._ret(int(vm._x(0) == vm._x(1)))


def _preserve(vm):
    """Stack probe (___chkstk_darwin, frame size in x9): preserves every register."""
    if vm._x(9) > STACK_SIZE // 2:
        raise _Stop('stack frame larger than the VM stack', str(vm._x(9)))


def _tlv_get_addr(vm):
    """dyld's TLV accessor (bound as __tlv_bootstrap): x0 = descriptor -> address.

    Reader-thread model: a fresh thread's block, initialised from the plugin's live
    TLV template (__thread_data, then zeroed __thread_bss), allocated per call. The
    thread-local RNG descriptors are refused (their values are random by design).
    """
    desc = vm._x(0) - vm.base
    if vm.thread != 'reader':
        if LEGACY:
            raise _Stop('thread-local state of the owning thread is not readable', hex(desc))
        from .ui_vm import _tlv_get_addr as owner_tlv   # the owner thread's own block (dyld's lookup)
        return owner_tlv(vm)
    if desc in TLV_REFUSED:
        if vm.rng not in ('private', 'isolate'):
            raise _Stop(TLV_REFUSED[desc], hex(desc))
        vm._ret(rng_cell(vm, desc))
        return
    start, end = vm.image.tlv_vars
    if not (start <= desc < end and (desc - start) % 24 == 0):
        raise _Stop('unknown thread-local descriptor', hex(desc))
    offset = struct.unpack('<Q', vm.image.file_bytes(desc + 16, 8))[0]
    if vm._tlv_block is None:
        t_start, t_size, bss = vm.image.tlv_template
        block = vm.alloc(t_size + bss)
        vm.write(block, vm.read(vm.base + t_start, t_size))
        vm._tlv_block = block
    if offset >= sum(vm.image.tlv_template[1:]):
        raise _Stop('thread-local offset outside the template', hex(desc))
    vm._ret(vm._tlv_block + offset)


def _memcpy(vm):
    dst, src, n = vm._x(0), vm._x(1), vm._x(2)
    if n > 0x100_0000:
        raise _Stop('oversized memcpy', str(n))
    if n:
        vm.write(dst, vm.read(src, n))
    vm._ret(dst)


def _memset(vm):
    dst, c, n = vm._x(0), vm._x(1) & 0xFF, vm._x(2)
    if n > 0x100_0000:
        raise _Stop('oversized memset', str(n))
    if n:
        vm.write(dst, bytes([c]) * n)
    vm._ret(dst)


def _memset_pattern16(vm):
    dst, pattern, n = vm._x(0), vm.read(vm._x(1), 16), vm._x(2)
    if n > 0x100_0000:
        raise _Stop('oversized memset_pattern16', str(n))
    if n:
        vm.write(dst, (pattern * (n // 16 + 1))[:n])


def _bzero(vm):
    dst, n = vm._x(0), vm._x(1)
    if n > 0x100_0000:
        raise _Stop('oversized bzero', str(n))
    if n:
        vm.write(dst, b'\0' * n)


def _cstr(vm, address, limit=1 << 20):
    out = bytearray()
    while len(out) < limit:
        chunk = vm.read(address + len(out), 64)
        cut = chunk.find(b'\0')
        if cut >= 0:
            return bytes(out + chunk[:cut])
        out += chunk
    raise _Stop('unterminated string')


def _strlen(vm):
    vm._ret(len(_cstr(vm, vm._x(0))))


def _strcmp(vm):
    a, b = _cstr(vm, vm._x(0)), _cstr(vm, vm._x(1))
    vm._ret(0 if a == b else (-1 if a < b else 1))


def _memcmp(vm):
    n = vm._x(2)
    a, b = vm.read(vm._x(0), n), vm.read(vm._x(1), n)
    vm._ret(0 if a == b else (-1 if a < b else 1))


def _guard_acquire(vm):
    guard = vm._x(0)
    vm._ret(0 if vm.read(guard, 1)[0] else 1)


def _guard_release(vm):
    vm.write(vm._x(0), b'\x01')


def _libm_d(fn):
    def model(vm):
        _ret_d(vm, fn(_bits_d(vm, 0)))
    return model


def _libm_dd(fn):
    def model(vm):
        _ret_d(vm, fn(_bits_d(vm, 0), _bits_d(vm, 1)))
    return model


def _libm_f(fn):
    def model(vm):
        _ret_s(vm, fn(_bits_s(vm, 0)))
    return model


def _libm_ff(fn):
    def model(vm):
        _ret_s(vm, fn(_bits_s(vm, 0), _bits_s(vm, 1)))
    return model


def _c_round(x):
    return math.copysign(math.floor(abs(x) + 0.5), x) if math.isfinite(x) else x


def _lround_f(vm):
    vm._ret(int(_c_round(_bits_s(vm, 0))))


def _lround_d(vm):
    vm._ret(int(_c_round(_bits_d(vm, 0))))


def _strtol(vm, unsigned=False):
    text, end, radix = _cstr(vm, vm._x(0), 4096), vm._x(1), vm._x(2)
    i = 0
    while i < len(text) and text[i:i + 1] in b' \t\n\r\f\v':
        i += 1
    j = i + (1 if text[i:i + 1] in (b'+', b'-') else 0)
    if radix in (0, 16) and text[j:j + 2].lower() == b'0x':
        radix, j = 16, j + 2
    elif radix == 0:
        radix = 8 if text[j:j + 1] == b'0' else 10
    digits = b'0123456789abcdefghijklmnopqrstuvwxyz'[:radix]
    k = j
    while k < len(text) and text[k:k + 1].lower() in digits:
        k += 1
    value = int(text[j:k], radix) if k > j else 0
    if unsigned:
        value = min(value, (1 << 64) - 1)               # ULLONG_MAX on overflow
        if text[i:i + 1] == b'-':
            value = -value                              # C: negation in the unsigned type
    else:
        if text[i:i + 1] == b'-':
            value = -value
        value = max(-(1 << 63), min((1 << 63) - 1, value))
    if end:
        vm.write(end, struct.pack('<Q', vm._x(0) + (k if k > j else 0)))
    vm._ret(value)


def _strtoull(vm):
    """strtoull/strtoul (64-bit long on arm64): strtol's parse in the unsigned type."""
    _strtol(vm, unsigned=True)


def _atoi(vm):
    text = _cstr(vm, vm._x(0), 4096).lstrip(b' \t\n\r\f\v')
    sign, digits = (-1, text[1:]) if text[:1] == b'-' else (1, text[1:] if text[:1] == b'+' else text)
    n = 0
    for c in digits:
        if not 48 <= c <= 57:
            break
        n = n * 10 + c - 48
    vm._ret((sign * n) & 0xFFFFFFFF)


def _strchr(vm):
    address, c = vm._x(0), vm._x(1) & 0xFF
    text = _cstr(vm, address)
    i = len(text) if c == 0 else text.find(bytes([c]))
    vm._ret(address + i if i >= 0 else 0)


def _strrchr(vm):
    address, c = vm._x(0), vm._x(1) & 0xFF
    text = _cstr(vm, address)
    i = len(text) if c == 0 else text.rfind(bytes([c]))
    vm._ret(address + i if i >= 0 else 0)


def _strstr(vm):
    address = vm._x(0)
    i = _cstr(vm, address).find(_cstr(vm, vm._x(1)))
    vm._ret(address + i if i >= 0 else 0)


def _strcpy(vm):
    dst = vm._x(0)
    vm.write(dst, _cstr(vm, vm._x(1)) + b'\0')
    vm._ret(dst)


def _strncpy(vm):
    dst, n = vm._x(0), vm._x(2)
    if n > 0x100_0000:
        raise _Stop('oversized strncpy', str(n))
    text = _cstr(vm, vm._x(1), max(n, 1))[:n]
    vm.write(dst, text + b'\0' * (n - len(text)))
    vm._ret(dst)


def _strcat(vm):
    dst = vm._x(0)
    vm.write(dst + len(_cstr(vm, dst)), _cstr(vm, vm._x(1)) + b'\0')
    vm._ret(dst)


def _is_prime(n):
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0:
            return n == p
    d, s = n - 1, 0
    while not d & 1:
        d, s = d >> 1, s + 1
    for a in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):   # deterministic below 3.3e24
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(s - 1):
            x = x * x % n
            if x == n - 1:
                break
        else:
            return False
    return True


def _next_prime(vm):
    """libc++ std::__next_prime(n): the smallest prime >= n (hash-table bucket counts). libc++
    throws overflow_error above 0xFFFFFFFFFFFFFFC5, the largest 64-bit prime."""
    n = vm._x(0)
    if n > 0xFFFF_FFFF_FFFF_FFC5:
        raise _Stop('c++ exception thrown', '__next_prime overflow')
    while not _is_prime(n):
        n += 1
    vm._ret(n)


def mark(vm, text):
    """Record that a modelled external returned a stand-in the game itself would not see
    (CallStats.marked, PropertyResult.marks)."""
    vm.marked[text] += 1
    if vm._call is not None and text not in vm._call.marked:
        vm._call.marked.append(text)


HOST_CLOCK = 'host clock (gettimeofday/time): the current wall-clock time of this machine'
STEAM_OFFLINE = 'Steam context modelled as offline (every Steam interface NULL)'


def _host_gettimeofday(vm):
    """Wall clock. The game reads the host clock here, never the game date (that is a database
    field), so the model returns this machine's current time, i.e. what the game would read if it
    ran the code now; the result is marked."""
    now = time.time_ns()
    if vm._x(0):
        vm.write(vm._x(0), struct.pack('<qi4x', now // 1_000_000_000, now // 1000 % 1_000_000))
    mark(vm, HOST_CLOCK)
    vm._ret(0)


def _host_time(vm):
    now = int(time.time())
    if vm._x(0):
        vm.write(vm._x(0), struct.pack('<q', now))
    mark(vm, HOST_CLOCK)
    vm._ret(now)


def _host_localtime_r(vm):
    """localtime_r(const time_t*, struct tm*) on this machine's time zone (the person history
    getters format a host-clock time this way); marked as host clock. Returns the struct."""
    seconds = struct.unpack('<q', vm.read(vm._x(0), 8))[0]
    t = time.localtime(seconds)
    zone = vm.alloc(16)
    vm.write(zone, (t.tm_zone or '').encode()[:15] + b'\0')
    vm.write(vm._x(1), struct.pack('<9i4xqQ', t.tm_sec, t.tm_min, t.tm_hour, t.tm_mday, t.tm_mon - 1,
                                   t.tm_year - 1900, (t.tm_wday + 1) % 7, t.tm_yday - 1, max(t.tm_isdst, 0),
                                   t.tm_gmtoff or 0, zone))
    mark(vm, HOST_CLOCK)
    vm._ret(vm._x(1))


LOG_DISCARDED = 'console output (stdout/stderr) discarded'
# FILE_LLIST::get_list (0x14A0FB0) pages history lists (playing history, non-playing history ...)
# in from the game's Temporary/*_dt.cmt files on the owning thread only; on any other thread it
# logs "outside of main thread" and loads nothing. get_property then repeats the call as the owning
# thread (owner TLV block, read-only file models).
OWNER_THREAD = 'needs the owning thread (FILE_LLIST::get_list pages the list in on the main thread only)'


def _std_stream(vm, stream):
    """True for the game's own stdout/stderr FILE* (the GOT values of ___stdoutp/___stderrp)."""
    std = getattr(vm, '_std_streams', None)
    if std is None:
        std = set()
        for rva, name in vm.image.binds.items():
            if name in ('___stdoutp', '___stderrp'):
                try:
                    std.add(vm.read_u64(vm.read_u64(vm.base + rva)))
                except _Stop:
                    pass
        vm._std_streams = std
    return stream in std


def _console(kind):
    """printf/vfprintf/fprintf/fputs/fputc/putchar/fwrite/fflush/write to the console: the text is
    formatted (so the return value is the game's) and discarded; marked. Any other stream or file
    descriptor stops the call (the VM never writes files)."""
    def model(vm):
        if kind == 'printf':
            text = _format(vm, vm._x(0), vm.uc.reg_read(A.UC_ARM64_REG_SP))
            if b'outside of main thread' in text:
                raise _Stop(OWNER_THREAD, text.strip().decode('utf-8', 'replace')[:200])
            n = len(text)
        elif kind == 'putchar':
            n = vm._x(0) & 0xFF
        elif kind == 'write':
            if vm._x(0) not in (1, 2):
                raise _Stop('external call _write', f'fd {vm._x(0)}')
            n = vm._x(2)
        else:
            stream = {'fprintf': 0, 'vfprintf': 0, 'fputs': 1, 'fputc': 1, 'fwrite': 3, 'fflush': 0}[kind]
            if not _std_stream(vm, vm._x(stream)):
                raise _Stop(f'external call _{kind}', 'stream other than stdout/stderr')
            if kind == 'fprintf':
                n = len(_format(vm, vm._x(1), vm.uc.reg_read(A.UC_ARM64_REG_SP)))
            elif kind == 'vfprintf':
                n = len(_format(vm, vm._x(1), vm._x(2)))
            elif kind == 'fputs':
                n = 1
            elif kind == 'fputc':
                n = vm._x(0) & 0xFF
            elif kind == 'fwrite':
                n = vm._x(2)
            else:
                n = 0
        mark(vm, LOG_DISCARDED)
        vm._ret(n)
    return model


def _getpid(vm):
    """getpid() inside the game is the game's own process id (known to the reader)."""
    pid = _reader_pid(vm.reader)
    if pid is None:
        raise _Stop('external call _getpid', 'the reader does not know the game process id')
    vm._ret(pid)


def _steam_context_init(vm):
    """SteamInternal_ContextInit(init_data) -> CSteamAPIContext*. Steam interfaces live in the
    Steam client library, outside the plugin, so they can never run here. The model is an
    offline Steam API: a VM-private context whose interface pointers are all NULL (the code's
    own `if (!SteamFriends())` branches then run). Marked."""
    mark(vm, STEAM_OFFLINE)
    vm._ret(vm.alloc(0x200))


# CFString path helpers: 0x44293AC turns a game path string into its file-system representation
# (CFStringCreateWithCStringNoCopy -> GetMaximumSizeOfFileSystemRepresentation ->
# GetFileSystemRepresentation -> CFRelease) before `stat`. A VM-private object holds the UTF-8
# bytes: {u64 magic, u64 length, bytes}.
CFSTRING_MAGIC = 0x4346_5354_5249_4E47   # 'CFSTRING'


def _cfstring_create(vm):
    text = _cstr(vm, vm._x(1), 1 << 16)
    obj = vm.alloc(16 + len(text) + 1)
    vm.write(obj, struct.pack('<QQ', CFSTRING_MAGIC, len(text)) + text + b'\0')
    vm._ret(obj)


def _cfstring_text(vm, obj):
    if not obj or obj not in vm.allocations or vm.read_u64(obj) != CFSTRING_MAGIC:
        raise _Stop('CoreFoundation object not made by the VM', hex(obj))
    return vm.read(obj + 16, vm.read_u64(obj + 8))


def _cfstring_max_fs(vm):
    vm._ret(len(_cfstring_text(vm, vm._x(0))) * 3 + 1)


def _cfstring_get_fs(vm):
    text, buffer, size = _cfstring_text(vm, vm._x(0)), vm._x(1), vm._x(2)
    if len(text) + 1 > size:
        vm._ret(0)
        return
    vm.write(buffer, text + b'\0')
    vm._ret(1)


STAT_ROOTS = None


def _stat(vm):
    """stat(path, buf): metadata of a file the game asks about (directory checks of its own data
    folders), answered from this machine's file system read-only. Only paths under the user's
    home folder or the game application are answered; others stop the call."""
    import os
    global STAT_ROOTS
    if STAT_ROOTS is None:
        STAT_ROOTS = (os.path.expanduser('~') + os.sep,)
    path = _cstr(vm, vm._x(0), 4096).decode('utf-8', 'surrogateescape')
    real = os.path.realpath(path)
    if not real.startswith(STAT_ROOTS):
        raise _Stop('stat outside the user and game folders', path)
    try:
        st = os.stat(real)
    except OSError as exc:
        set_errno(vm, 'ENOENT')
        vm._ret(0xFFFFFFFF)
        mark(vm, f'host file system: stat {exc.__class__.__name__}')
        return
    def ts(t):
        return struct.pack('<qq', int(t), int(t * 1e9) % 1_000_000_000)
    buf = struct.pack('<iHHQIIi4x', st.st_dev & 0x7FFFFFFF, st.st_mode, min(st.st_nlink, 0xFFFF), st.st_ino,
                      st.st_uid, st.st_gid, getattr(st, 'st_rdev', 0) & 0x7FFFFFFF)
    buf += ts(st.st_atime) + ts(st.st_mtime) + ts(st.st_ctime) + ts(getattr(st, 'st_birthtime', st.st_ctime))
    buf += struct.pack('<qqiIIi', st.st_size, st.st_blocks, st.st_blksize, getattr(st, 'st_flags', 0), 0, 0)
    buf += b'\0' * 16
    vm.write(vm._x(1), buf)
    mark(vm, 'host file system: stat')
    vm._ret(0)


def _access(vm):
    """access(path, mode): the same read-only question about this machine's file system as
    `_stat` (same folder limit); the answer is the host's. Marked."""
    import os
    global STAT_ROOTS
    if STAT_ROOTS is None:
        STAT_ROOTS = (os.path.expanduser('~') + os.sep,)
    path = _cstr(vm, vm._x(0), 4096).decode('utf-8', 'surrogateescape')
    if not os.path.realpath(path).startswith(STAT_ROOTS):
        raise _Stop('access outside the user and game folders', path)
    mark(vm, 'host file system: access')
    vm._ret(0 if os.access(path, vm._x(1) & 7) else 0xFFFFFFFF)


_ENVIRONMENTS = {}


def game_environment(pid):
    """The game process's environment (KERN_PROCARGS2, read-only; same user), cached per pid."""
    if pid in _ENVIRONMENTS:
        return _ENVIRONMENTS[pid]
    import sys
    if sys.platform != 'darwin':
        # KERN_PROCARGS2 is macOS only. Elsewhere the environment is unknown (None), which the
        # callers already handle; a Windows reader would take it from the process's PEB.
        _ENVIRONMENTS[pid] = None
        return None
    import ctypes
    import ctypes.util
    libc = ctypes.CDLL(ctypes.util.find_library('c'), use_errno=True)
    mib = (ctypes.c_int * 3)(1, 49, pid)            # CTL_KERN, KERN_PROCARGS2
    size = ctypes.c_size_t(1 << 20)
    buf = ctypes.create_string_buffer(size.value)
    env = None
    if libc.sysctl(mib, 3, buf, ctypes.byref(size), None, 0) == 0:
        raw = buf.raw[:size.value]
        argc = struct.unpack_from('<i', raw)[0]
        parts = [x for x in raw[4:].split(b'\0') if x]
        env = {}
        for item in parts[1 + argc:]:                  # exec path, argv[argc], then KEY=VALUE
            key, eq, value = item.partition(b'=')
            if eq:
                env.setdefault(key, value)
    _ENVIRONMENTS[pid] = env
    return env


def _getenv(vm):
    """getenv(name) answered from the game's own environment (read with sysctl, read-only); the
    returned string is a VM-private copy. Stops when the environment cannot be read."""
    pid = _reader_pid(vm.reader)
    env = game_environment(pid) if pid else None
    if env is None:
        raise _Stop('external call _getenv', 'the game environment is not readable')
    value = env.get(_cstr(vm, vm._x(0), 1024))
    if value is None:
        vm._ret(0)
        return
    out = vm.alloc(len(value) + 1)
    vm.write(out, value + b'\0')
    vm._ret(out)


def _gethostname(vm):
    """gethostname(buf, len): this machine's host name (the game runs on it); marked."""
    import socket
    name = socket.gethostname().encode()[:max(vm._x(1) - 1, 0)]
    vm.write(vm._x(0), name + b'\0')
    mark(vm, 'host name')
    vm._ret(0)


def _home_path(vm, what):
    import os
    global STAT_ROOTS
    if STAT_ROOTS is None:
        STAT_ROOTS = (os.path.expanduser('~') + os.sep,)
    path = _cstr(vm, vm._x(0), 4096).decode('utf-8', 'surrogateescape')
    if not os.path.realpath(path).startswith(STAT_ROOTS):
        raise _Stop(f'{what} outside the user and game folders', path)
    return path


ERRNO = {'EEXIST': 17, 'ENOENT': 2}


def _errno_cell(vm):
    """The thread's errno (libc ___error()): a VM-private int that lives for one call."""
    cell = getattr(vm, '_errno', None)
    if cell is None or cell[1] is not vm._call:
        vm._errno = cell = (vm.alloc(8), vm._call)
    return cell[0]


def set_errno(vm, name):
    vm.write(_errno_cell(vm), struct.pack('<i', ERRNO[name]))


def _error(vm):
    vm._ret(_errno_cell(vm))


VM_FD_BASE = 30000


def _fopen(vm):
    """fopen(path, mode) for reading a file on this machine (mode r/rb, no '+'; same folder limit
    as `_stat`): a VM-private FILE (flags __SRD, a VM file descriptor from 30000 up, position 0)
    that the read-only stdio models (fseeko/fread/ftello/ferror) serve; fclose is a no-op. Any
    mode that writes stops the call. Marked."""
    import os
    path = _home_path(vm, 'fopen')
    mode = _cstr(vm, vm._x(1), 16)
    if not mode.startswith(b'r'):                    # w truncates/creates, a creates
        raise _Stop('the game would write a file', f'{path} {mode.decode("latin-1")}')
    if not os.path.isfile(path):
        set_errno(vm, 'ENOENT')
        vm._ret(0)
        return
    files = getattr(vm, '_vm_files', None)
    if files is None:
        files = vm._vm_files = {}
    fd = VM_FD_BASE + len(files)
    files[fd] = path
    stream = vm.alloc(0x98)
    vm.write(stream + 0x10, struct.pack('<Hh', 0x4, fd))       # _flags = __SRD, _file
    vm._open_files[fd] = open(path, 'rb')                       # noqa: SIM115 - read-only, kept for the session
    vm._fpos[stream] = 0
    vm.files_read.add(path)
    mark(vm, 'host file system: read')
    vm._ret(stream)


def _fileno(vm):
    vm._ret(struct.unpack('<h', vm.read(vm._x(0) + 0x12, 2))[0] & 0xFFFFFFFF)


def _fstat(vm):
    """fstat on a file the VM opened read-only (`_fopen`): the host file's metadata."""
    fd = vm._x(0) & 0xFFFFFFFF
    path = (getattr(vm, '_vm_files', None) or {}).get(fd)
    if path is None:
        raise _Stop('external call _fstat', f'fd {fd} not opened by the VM')
    import os
    st = os.stat(path)
    def ts(t):
        return struct.pack('<qq', int(t), int(t * 1e9) % 1_000_000_000)
    buf = struct.pack('<iHHQIIi4x', st.st_dev & 0x7FFFFFFF, st.st_mode, min(st.st_nlink, 0xFFFF), st.st_ino,
                      st.st_uid, st.st_gid, 0)
    buf += ts(st.st_atime) + ts(st.st_mtime) + ts(st.st_ctime) + ts(getattr(st, 'st_birthtime', st.st_ctime))
    buf += struct.pack('<qqiIIi', st.st_size, st.st_blocks, st.st_blksize, getattr(st, 'st_flags', 0), 0, 0) + bytes(16)
    vm.write(vm._x(1), buf)
    mark(vm, 'host file system: stat')
    vm._ret(0)


def _open(vm):
    """open(path, flags) of an existing file on this machine, same folder limit: a VM file descriptor
    served by _read/_pread/_lseek/_close. Opening for update changes nothing by itself, so O_RDWR
    is accepted; O_TRUNC, creating a missing file, and every later write stop the call. Marked."""
    import os
    path = _home_path(vm, 'open')
    flags = vm._x(1) & 0xFFFFFFFF
    if flags & 0x400 or (flags & 0x200 and not os.path.exists(path)):     # O_TRUNC; O_CREAT of a new file
        raise _Stop('the game would write a file', f'{path} flags {flags:#x}')
    if not os.path.exists(path):
        set_errno(vm, 'ENOENT')
        vm._ret(0xFFFFFFFF)
        return
    files = getattr(vm, '_vm_files', None)
    if files is None:
        files = vm._vm_files = {}
    fd = VM_FD_BASE + len(files)
    files[fd] = path
    vm._open_files[fd] = open(path, 'rb')               # noqa: SIM115 - read-only
    vm._fdpos = getattr(vm, '_fdpos', {})
    vm._fdpos[fd] = 0
    vm.files_read.add(path)
    mark(vm, 'host file system: read')
    vm._ret(fd)


def _vm_fd(vm, fd):
    handle = vm._open_files.get(fd) if fd in (getattr(vm, '_vm_files', None) or {}) else None
    if handle is None:
        raise _Stop('file descriptor not opened by the VM', str(fd))
    return handle


def _read_fd(vm):
    fd, buf, n = vm._x(0) & 0xFFFFFFFF, vm._x(1), vm._x(2)
    handle = _vm_fd(vm, fd)
    if n > 0x400_0000:
        raise _Stop('oversized read', str(n))
    handle.seek(vm._fdpos.get(fd, 0))
    data = handle.read(n)
    if data:
        vm.write(buf, data)
    vm._fdpos[fd] = vm._fdpos.get(fd, 0) + len(data)
    vm._ret(len(data))


def _pread(vm):
    fd, buf, n, off = vm._x(0) & 0xFFFFFFFF, vm._x(1), vm._x(2), vm._x(3)
    handle = _vm_fd(vm, fd)
    if n > 0x400_0000:
        raise _Stop('oversized read', str(n))
    handle.seek(off)
    data = handle.read(n)
    if data:
        vm.write(buf, data)
    vm._ret(len(data))


def _lseek(vm):
    import os
    fd, off, whence = vm._x(0) & 0xFFFFFFFF, vm._x(1), vm._x(2) & 0xFFFFFFFF
    off -= (1 << 64) if off >> 63 else 0
    handle = _vm_fd(vm, fd)
    size = os.fstat(handle.fileno()).st_size
    pos = {0: off, 1: vm._fdpos.get(fd, 0) + off, 2: size + off}.get(whence)
    if pos is None or pos < 0:
        vm._ret(0xFFFF_FFFF_FFFF_FFFF)
        return
    vm._fdpos[fd] = pos
    vm._ret(pos)


def _mkdir(vm):
    """mkdir(path, mode) for a folder that already exists answers -1 (EEXIST) and changes nothing,
    as on the game's machine. A folder that does not exist would be created: the VM never writes
    the file system, so that call stops."""
    import os
    path = _home_path(vm, 'mkdir')
    if not os.path.isdir(path):
        raise _Stop('the game would create a folder', path)
    mark(vm, 'host file system: mkdir of an existing folder')
    set_errno(vm, 'EEXIST')
    vm._ret(0xFFFFFFFF)


DIR_MAGIC = 0x4449_5245_4E54_5259   # 'DIRENTRY'


def _opendir(vm):
    """opendir/readdir/closedir: a read-only listing of a game folder on this machine (same
    folder limit as `_stat`), held VM-private: {magic, count, next, dirent buffer, names}. Marked."""
    import os
    path = _home_path(vm, 'opendir')
    try:
        names = sorted(os.listdir(path))
    except OSError:
        vm._ret(0)
        return
    names = ['.', '..'] + names
    table = [n.encode('utf-8', 'surrogateescape')[:1023] for n in names]
    blob = b''.join(n + b'\0' for n in table)
    handle = vm.alloc(32 + 1048 + len(blob) + 8 * len(table))
    offsets, at = [], handle + 32 + 1048 + 8 * len(table)
    for n in table:
        offsets.append(at)
        at += len(n) + 1
    vm.write(handle, struct.pack('<QQQQ', DIR_MAGIC, len(table), 0, 0) + bytes(1048)
             + b''.join(struct.pack('<Q', o) for o in offsets) + blob)
    vm._dirpaths = getattr(vm, '_dirpaths', {})
    vm._dirpaths[handle] = path
    mark(vm, 'host file system: directory listing')
    vm._ret(handle)


def _readdir(vm):
    import os
    handle = vm._x(0)
    if not handle or vm.read_u64(handle) != DIR_MAGIC:
        raise _Stop('readdir on a directory the VM did not open', hex(handle))
    count, nxt = struct.unpack('<QQ', vm.read(handle + 8, 16))
    if nxt >= count:
        vm._ret(0)
        return
    name = _cstr(vm, vm.read_u64(handle + 32 + 1048 + 8 * nxt), 1024)
    full = os.path.join(vm._dirpaths.get(handle, ''), name.decode('utf-8', 'surrogateescape'))
    kind = 4 if os.path.isdir(full) else 8               # DT_DIR / DT_REG
    entry = handle + 32
    vm.write(entry, struct.pack('<QQHHB', nxt + 1, nxt + 1, 21 + len(name), len(name), kind) + name + b'\0')
    vm.write(handle + 16, struct.pack('<Q', nxt + 1))
    vm._ret(entry)


_FORMAT = None


def _format(vm, fmt_address, args_address):
    """C printf formatting with Apple arm64 variadic slots (8 bytes each, from args_address)."""
    import re
    global _FORMAT
    if _FORMAT is None:
        _FORMAT = re.compile(rb'%([-+ 0#]*)(\*|\d+)?(?:\.(\*|\d+))?(hh|h|ll|l|j|z|t|q|L)?([diouxXcspfFeEgG%])')
    fmt = _cstr(vm, fmt_address, 4096)
    out, pos, slot = bytearray(), 0, args_address

    def take():
        nonlocal slot
        value = vm.read_u64(slot)
        slot += 8
        return value

    while True:
        index = fmt.find(b'%', pos)
        if index < 0:
            break
        match = _FORMAT.match(fmt, index)
        if match is None:
            raise _Stop('unsupported printf format', fmt[index:index + 16].decode('latin-1'))
        out += fmt[pos:index]
        pos = match.end()
        flags, width, precision, length, conv = match.groups()
        if conv == b'%':
            out += b'%'
            continue
        width = take() if width == b'*' else (int(width) if width else None)
        precision = take() if precision == b'*' else (int(precision) if precision else None)
        if (width or 0) > 4096 or (precision or 0) > 4096:
            raise _Stop('implausible printf width or precision')
        spec = '%' + flags.decode() + (str(width) if width is not None else '') \
            + ('.' + str(precision) if precision is not None else '')
        raw = take()
        bits = {b'hh': 8, b'h': 16, None: 32}.get(length, 64)
        mask = (1 << bits) - 1
        if conv in b'di':
            n = raw & mask
            n -= (1 << bits) if n >> (bits - 1) else 0
            out += (spec + 'd') .__mod__(n).encode()
        elif conv in b'ouxX':
            out += (spec + conv.decode()).__mod__(raw & mask).encode()
        elif conv == b'c':
            out += (spec + 'c').__mod__(chr(raw & 0xFF)).encode('latin-1')
        elif conv == b's':
            text = _cstr(vm, raw, 1 << 16) if raw else b'(null)'
            out += (spec + 's').__mod__(text.decode('utf-8', 'surrogateescape')).encode('utf-8', 'surrogateescape')
        elif conv == b'p':
            out += ('0x%x' % raw).encode()
        else:
            value = struct.unpack('<d', struct.pack('<Q', raw))[0]
            out += (spec + conv.decode()).__mod__(value).encode()
    out += fmt[pos:]
    return bytes(out)


def _write_formatted(vm, buffer, size, text):
    if size:
        keep = text[:size - 1]
        vm.write(buffer, keep + b'\0')
    vm._ret(len(text))


def _vsnprintf(vm):
    _write_formatted(vm, vm._x(0), vm._x(1), _format(vm, vm._x(2), vm._x(3)))


def _snprintf(vm):
    _write_formatted(vm, vm._x(0), vm._x(1), _format(vm, vm._x(2), vm.uc.reg_read(A.UC_ARM64_REG_SP)))


def _vsprintf(vm):
    _write_formatted(vm, vm._x(0), 1 << 30, _format(vm, vm._x(1), vm._x(2)))


def _sprintf(vm):
    _write_formatted(vm, vm._x(0), 1 << 30, _format(vm, vm._x(1), vm.uc.reg_read(A.UC_ARM64_REG_SP)))


TYPEINFO_KINDS = {
    '__ZTVN10__cxxabiv117__class_type_infoE': 'class',
    '__ZTVN10__cxxabiv120__si_class_type_infoE': 'si',
    '__ZTVN10__cxxabiv121__vmi_class_type_infoE': 'vmi',
}


def _typeinfo_kind(vm, info):
    if vm._typeinfo_vtables is None:
        table = {}
        for rva, name in vm.image.binds.items():
            if name in TYPEINFO_KINDS:
                # type_info slots bind the vtable with addend 16 (address point); GOT slots
                # bind it with addend 0. Either way the address point is value or value+16.
                value = vm.read_u64(vm.base + rva)
                table[value] = table[value + 16] = TYPEINFO_KINDS[name]
        vm._typeinfo_vtables = table
    return vm._typeinfo_vtables.get(vm.read_u64(info))


def _same_type(vm, a, b):
    if a == b:
        return True
    return _cstr(vm, vm.read_u64(a + 8) & ((1 << 63) - 1), 512) == _cstr(vm, vm.read_u64(b + 8) & ((1 << 63) - 1), 512)


def _bases(vm, info, address, depth=0):
    """Yield (type_info, subobject address) for `info` at `address` and all public bases."""
    if depth > 32:
        raise _Stop('dynamic_cast hierarchy too deep')
    yield info, address
    kind = _typeinfo_kind(vm, info)
    if kind == 'si':
        yield from _bases(vm, vm.read_u64(info + 16), address, depth + 1)
    elif kind == 'vmi':
        count = struct.unpack('<I', vm.read(info + 20, 4))[0]
        for i in range(min(count, 64)):
            base_info, flags = struct.unpack('<Qq', vm.read(info + 24 + 16 * i, 16))
            if not flags & 2:          # __public_mask
                continue
            offset = flags >> 8
            if flags & 1:              # __virtual_mask: offset is in the vtable
                offset = struct.unpack('<q', vm.read(vm.read_u64(address) + offset, 8))[0]
            yield from _bases(vm, base_info, address + offset, depth + 1)
    elif kind != 'class':
        raise _Stop('dynamic_cast on an unknown type_info kind')


def _dynamic_cast(vm):
    """Itanium __dynamic_cast(src, src_type, dst_type, hint) over live RTTI (public bases only)."""
    src, dst_type = vm._x(0), vm._x(2)
    if not src:
        vm._ret(0)
        return
    vtable = vm.read_u64(src)
    whole = src + struct.unpack('<q', vm.read(vtable - 16, 8))[0]
    dynamic = vm.read_u64(vtable - 8)
    hits = {address for info, address in _bases(vm, dynamic, whole) if _same_type(vm, info, dst_type)}
    vm._ret(hits.pop() if len(hits) == 1 else 0)


# Read-only game files. Translated names (currency, region, award, competition, team names
# ...) that are not cached in memory are read on demand from the plugin's
# `Resources/data/game_simulation/languages.fmf` through the game's own FILE*. With a
# file_resolver (fd -> path, e.g. ui_vm.lsof_resolver) the VM reuses the UI VM's stdio
# models: the copied FILE* is mapped to its path and the file is opened read-only here;
# only `.fmf` data files are allowed. Without a resolver these calls refuse as before.
FILE_EXTERNALS = ('_fseeko', '_fseek', '_ftello', '_ftell', '_fread', '_ferror')
FILE_SUFFIXES = ('.fmf',)
# History lists paged in by FILE_LLIST::get_list on the owning thread (pl_hist_dt.cmt,
# non_pl_hist_dt.cmt ...): the game's own Temporary folder, read-only (2026-11-11).
TEMPORARY_LISTS = ('/Temporary/', '_dt.cmt')


def _allowed_file(path):
    if path.endswith(FILE_SUFFIXES):
        return True
    return not LEGACY and TEMPORARY_LISTS[0] in path and path.endswith(TEMPORARY_LISTS[1])


def _file_model(name):
    from . import ui_vm
    inner = {'_fseeko': ui_vm._fseeko, '_fseek': ui_vm._fseeko, '_ftello': ui_vm._ftello,
             '_ftell': ui_vm._ftello, '_fread': ui_vm._fread, '_ferror': ui_vm._ferror}[name]

    def model(vm):
        stream = vm._x(3) if name == '_fread' else vm._x(0)
        fd = struct.unpack('<h', vm.read(stream + 0x12, 2))[0]
        vm_files = getattr(vm, '_vm_files', None) or {}
        if fd in vm_files:                       # opened read-only by the VM's own _fopen
            inner(vm)
            return
        path = vm.file_resolver(fd)
        if not path or not _allowed_file(str(path)):
            raise _Stop('game file outside the allowed data files', str(path))
        inner(vm)
    return model


TLV_REFUSED = {
    0x56C44F8: 'thread-local RNG state', 0x56C4510: 'thread-local RNG state',
}

# ---------------------------------------------------------------------- random numbers
# The game keeps one pcg32 (XSH-RR, multiplier 0x5851F42D4C957F2D) per thread: thread-local
# 0x56C44F8 is {u32 seed, u64 state @+8, u64 increment @+0x10}, 0x56C4510 its "seeded" flag.
# The first use on a thread seeds it from std::random_device (0x4360CC8: state = seed *
# 0xA4E7735A4C957F2D + 0x5851F42D4C957F2E, increment 1). Draws therefore differ between
# threads and runs: no reader can know them. Policies (docs/fmdb/REFUSALS.md):
#   'refuse'  stop at the first draw (the behaviour before 2026-11-11);
#   'private' seed a VM-private generator the same way with a fixed seed; every result that
#             drew is marked PropertyResult.rng == 'private' (never what the game shows);
#   'isolate' as 'private', then repeat the call with a second seed: the value is kept (marked
#             'stable') only when both agree, otherwise Unavailable(RNG_DEPENDS, 'generated at
#             read ...'). The default: draws that do not reach the value cost nothing.
#   'copy'    (UiHandlerVM, thread='owner' only) a private copy of the game thread's own state:
#             what the game would draw next.
RNG_POLICIES = ('refuse', 'private', 'isolate')
LEGACY = os.environ.get('FMDB_VM_REFUSALS', '').lower() == 'legacy'
DEFAULT_RNG = 'refuse' if LEGACY else 'isolate'
RNG_SEEDS = (0x5EED_0001, 0x5EED_0002)
RNG_FLAG_TLV, RNG_STATE_TLV = 0x56C4510, 0x56C44F8
PCG_MULT = 0x5851F42D4C957F2D
PCG_SEED_MULT, PCG_SEED_ADD = 0xA4E7735A4C957F2D, 0x5851F42D4C957F2E
RNG_DEPENDS = 'generated at read: the value changes with the random draws (two-seed rule)'


def rng_note(vm):
    vm.rng_uses += 1
    if vm._call is not None:
        vm._call.rng_draws += 1


def rng_cell(vm, desc):
    """Address the code gets for a thread-local RNG descriptor under 'private'/'isolate': a
    per-call VM-private {flag, generator} seeded from vm.rng_seed like 0x4360CC8 seeds the
    game's (reset with the heap at the start of every call)."""
    rng_note(vm)
    # The cell lives on the per-call heap: it belongs to the call that made it (FastVM's _restore
    # does not know about it, so ownership is checked here rather than reset there).
    if vm._rng_cell is None or vm._rng_cell[1] is not vm._call:
        cell = vm.alloc(0x40)
        seed = vm.rng_seed & 0xFFFFFFFF
        state = (seed * PCG_SEED_MULT + PCG_SEED_ADD) & 0xFFFF_FFFF_FFFF_FFFF
        vm.write(cell, b'\x01' + b'\0' * 15 + struct.pack('<I4xQQ', seed, state, 1) + b'\0' * 24)
        vm._rng_cell = (cell, vm._call)
    return vm._rng_cell[0] + (0 if desc == RNG_FLAG_TLV else 0x10)


def _splitmix(x):
    x = (x + 0x9E3779B97F4A7C15) & 0xFFFF_FFFF_FFFF_FFFF
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFF_FFFF_FFFF_FFFF
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & 0xFFFF_FFFF_FFFF_FFFF
    return x ^ (x >> 31)


RANDOM_DEVICE = 'std::random_device: fresh entropy in the game; a VM-private sequence here'


def _random_device_ctor(vm):
    """std::random_device(const string&): the game reads /dev/urandom (0x4360638 / 0x4360A48 seed
    a fresh mt19937 per use, 0x4360CC8 seeds a thread's pcg32 on its first draw). That entropy
    is new on every use, so no reader can know it, and under 'copy' there is no game state to
    copy either. Under 'refuse' the call stops; otherwise the device is VM-private (see
    _random_device_draw), every draw counts as an RNG draw and the result is marked."""
    if vm.rng == 'refuse':
        raise _Stop('random number source (std::random_device)', 'random_device')
    rng_note(vm)
    mark(vm, RANDOM_DEVICE)
    vm._rd_count = 0
    vm._ret(vm._x(0))


def _random_device_draw(vm):
    """random_device::operator(): a fixed private sequence derived from vm.rng_seed (and, for a
    UiHandlerVM sensitivity run, vm.rng_salt)."""
    count = getattr(vm, '_rd_count', 0)
    vm._rd_count = count + 1
    rng_note(vm)
    seed = vm.rng_seed ^ (getattr(vm, 'rng_salt', 0) * 0x9E3779B1)
    vm._ret(_splitmix((seed << 16) + count) & 0xFFFFFFFF)


def _reader_pid(reader):
    """The game's process id as the reader knows it (live.StreamReader, LiveMemory, _VMReader)."""
    for holder in (reader, getattr(reader, 'memory', None), getattr(reader, 'reader', None)):
        pid = getattr(holder, 'pid', None)
        if isinstance(pid, int) and pid > 0:
            return pid
    return None


def _auto_file_resolver(reader):
    pid = _reader_pid(reader)
    if pid is None:
        return None
    from .ui_vm import lsof_resolver
    return lsof_resolver(pid)

REFUSALS = {
    '___cxa_allocate_exception': 'c++ exception thrown', '___cxa_throw': 'c++ exception thrown',
    '___stack_chk_fail': 'stack check failure', '_abort': 'abort',
}

EXTERNALS = {
    '_malloc': _malloc, '__Znwm': _malloc, '__Znam': _malloc,
    '__ZnwmRKSt9nothrow_t': _malloc, '__ZnamRKSt9nothrow_t': _malloc,
    '__ZnwmSt11align_val_t': _aligned_new, '__ZnamSt11align_val_t': _aligned_new,
    '_calloc': _calloc, '_realloc': _realloc, '_posix_memalign': _posix_memalign,
    '_free': _noop, '__ZdlPv': _noop, '__ZdaPv': _noop, '__ZdlPvm': _noop,
    '__ZdlPvSt11align_val_t': _noop, '__ZdaPvSt11align_val_t': _noop, '__ZdlPvmSt11align_val_t': _noop,
    '_memcpy': _memcpy, '_memmove': _memcpy, '_memset': _memset, '_bzero': _bzero,
    '_memset_pattern16': _memset_pattern16,
    '___bzero': _bzero, '_strlen': _strlen, '_strcmp': _strcmp, '_memcmp': _memcmp,
    '_pthread_mutex_lock': _noop, '_pthread_mutex_unlock': _noop, '_pthread_mutex_trylock': _noop,
    '_pthread_rwlock_rdlock': _noop, '_pthread_rwlock_wrlock': _noop, '_pthread_rwlock_unlock': _noop,
    '_os_unfair_lock_lock': _noop, '_os_unfair_lock_unlock': _noop, '_os_unfair_lock_trylock': _true,
    '_os_unfair_recursive_lock_lock_with_options': _noop, '_os_unfair_recursive_lock_unlock': _noop,
    '__ZNSt3__15mutex4lockEv': _noop, '__ZNSt3__15mutex6unlockEv': _noop,
    '__ZNSt3__15mutex8try_lockEv': _true,
    '__ZNSt3__115recursive_mutex4lockEv': _noop, '__ZNSt3__115recursive_mutex6unlockEv': _noop,
    '__ZNSt3__115recursive_mutex8try_lockEv': _true,
    '__ZNSt3__112shared_mutex4lockEv': _noop, '__ZNSt3__112shared_mutex6unlockEv': _noop,
    '__ZNSt3__112shared_mutex11lock_sharedEv': _noop, '__ZNSt3__112shared_mutex13unlock_sharedEv': _noop,
    '__ZNSt3__119__shared_mutex_base4lockEv': _noop, '__ZNSt3__119__shared_mutex_base6unlockEv': _noop,
    '__ZNSt3__119__shared_mutex_base11lock_sharedEv': _noop,
    '__ZNSt3__119__shared_mutex_base13unlock_sharedEv': _noop,
    '___cxa_guard_acquire': _guard_acquire, '___cxa_guard_release': _guard_release,
    '_pthread_self': _pthread_self, '_pthread_equal': _pthread_equal,
    '___chkstk_darwin': _preserve, '__tlv_bootstrap': _tlv_get_addr, '___cxa_guard_abort': _noop, '___cxa_atexit': _noop,
    # dyld registers a thread_local destructor on the variable's first use in a thread; the
    # VM's thread block lives for one call and is never torn down, so registration is a no-op.
    '__tlv_atexit': _noop,
    '_floor': _libm_d(math.floor), '_ceil': _libm_d(math.ceil), '_trunc': _libm_d(math.trunc),
    '_round': _libm_d(_c_round), '_sqrt': _libm_d(math.sqrt), '_exp': _libm_d(math.exp),
    '_log': _libm_d(math.log), '_log10': _libm_d(math.log10), '_fmod': _libm_dd(math.fmod),
    '_pow': _libm_dd(math.pow), '_atan2': _libm_dd(math.atan2), '_sin': _libm_d(math.sin),
    '_cos': _libm_d(math.cos),
    '_floorf': _libm_f(math.floor), '_ceilf': _libm_f(math.ceil), '_truncf': _libm_f(math.trunc),
    '_roundf': _libm_f(_c_round), '_sqrtf': _libm_f(math.sqrt), '_expf': _libm_f(math.exp),
    '_logf': _libm_f(math.log), '_fmodf': _libm_ff(math.fmod), '_powf': _libm_ff(math.pow),
    '_sinf': _libm_f(math.sin), '_cosf': _libm_f(math.cos), '_strtol': _strtol,
    '___dynamic_cast': _dynamic_cast,
    '_vsnprintf': _vsnprintf, '_snprintf': _snprintf, '_vsprintf': _vsprintf, '_sprintf': _sprintf,
    '_lroundf': _lround_f, '_lround': _lround_d, '_llroundf': _lround_f, '_llround': _lround_d,
}

# 2026-11-11 (docs/fmdb/REFUSALS.md). FMDB_VM_REFUSALS=legacy leaves these out, together with the
# 'isolate' default, the long-walk retry and the automatic file resolver (before/after runs).
EXTERNALS_2026_11_11 = {
    '__ZNSt3__113random_deviceC1ERKNS_12basic_stringIcNS_11char_traitsIcEENS_9allocatorIcEEEE':
        _random_device_ctor,
    '__ZNSt3__113random_deviceclEv': _random_device_draw, '__ZNSt3__113random_deviceD1Ev': _noop,
    # pure library functions with exact C semantics ...
    '_strtoll': _strtol, '_strtoull': _strtoull, '_strtoul': _strtoull, '_atoi': _atoi,
    '_strchr': _strchr, '_strrchr': _strrchr, '_strstr': _strstr, '_strcpy': _strcpy,
    '_strncpy': _strncpy, '_strcat': _strcat, '__ZNSt3__112__next_primeEm': _next_prime,
    '_asinf': _libm_f(math.asin), '_asin': _libm_d(math.asin), '_acosf': _libm_f(math.acos),
    '_acos': _libm_d(math.acos), '_atan': _libm_d(math.atan), '_atan2f': _libm_ff(math.atan2),
    '_tan': _libm_d(math.tan), '_exp2': _libm_d(lambda x: 2.0 ** x), '_exp2f': _libm_f(lambda x: 2.0 ** x),
    '_log2f': _libm_f(math.log2), '_log10f': _libm_f(math.log10),
    # ... lock set-up whose objects only feed the no-op lock models above ...
    '_pthread_mutexattr_init': _noop, '_pthread_mutexattr_settype': _noop, '_pthread_mutexattr_destroy': _noop,
    '_pthread_mutex_init': _noop, '_pthread_mutex_destroy': _noop,
    '_pthread_cond_init': _noop, '_pthread_cond_destroy': _noop, '_sched_yield': _noop,
    # (2026-11-14) the attribute object of a condition variable: it only feeds pthread_cond_init
    # above. The game's memory pools hold one (mutex + condition); a pool that the running game has
    # not built yet (a function-local static, e.g. PAST_TRADE for a past transfer with a trade part)
    # is built inside the VM by the read that first needs it (docs/fmdb/HISTORIES.md).
    '_pthread_condattr_init': _noop, '_pthread_condattr_destroy': _noop,
    # ... the game's own process id, and stand-ins that mark their results (PropertyResult.marks)
    '_getpid': _getpid, '_gettimeofday': _host_gettimeofday, '_time': _host_time,
    '_localtime_r': _host_localtime_r,
    # the diagnostic log record (0x43F24EC: time, local time, call stack) of a reader-thread warning:
    # no frames are available inside the VM
    '_backtrace': _noop,
    **{f'_{k}': _console(k) for k in ('printf', 'fprintf', 'vfprintf', 'fputs', 'fputc', 'putchar',
                                      'fwrite', 'fflush', 'write')},
    '_SteamInternal_ContextInit': _steam_context_init,
    '_CFStringCreateWithCStringNoCopy': _cfstring_create, '_CFStringCreateWithCString': _cfstring_create,
    '_CFStringGetMaximumSizeOfFileSystemRepresentation': _cfstring_max_fs,
    '_CFStringGetFileSystemRepresentation': _cfstring_get_fs, '_CFRelease': _noop,
    '_stat': _stat,
    '_access': _access,
    '_opendir': _opendir, '_readdir': _readdir, '_closedir': _noop,
    '_mkdir': _mkdir,
    '_fopen': _fopen, '_fclose': _noop,
    '_fileno': _fileno, '_fstat': _fstat,
    '_open': _open, '_read': _read_fd, '_pread': _pread, '_lseek': _lseek, '_close': _noop,
    '_nanosleep': _noop,                    # a pause: nothing to wait for in the VM
    '___error': _error, '_pthread_cond_signal': _noop, '_pthread_cond_broadcast': _noop,
    '_NSBeep': _noop,                       # an interface beep: no state, no value
    '_getenv': _getenv, '_gethostname': _gethostname,
    # libc++ shared_ptr control block: the last weak release frees it (frees are no-ops here)
    '__ZNSt3__119__shared_weak_count14__release_weakEv': _noop,
}
if not LEGACY:
    EXTERNALS.update(EXTERNALS_2026_11_11)
