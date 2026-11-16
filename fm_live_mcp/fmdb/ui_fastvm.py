"""FastUiHandlerVM: UiHandlerVM on the C-accelerated machinery (`native/fm_ui_accel.c`).

Same trust model, same results and the same stop reasons as `ui_vm.UiHandlerVM` (checked by
`scripts/fmdb_ui_vm_check.py`); `UiHandlerVM(...)` returns this class when the library is
built (`scripts/build_ui_accel.sh`) and `FMDB_UI_VM` is not `classic`. See docs/fmdb/UI_FAST.md.

What is different mechanically:

* Unicorn runs in virtual-TLB mode over pools mapped once (code, copied live pages, private
  ranges), as `fastvm.FastVM`; nothing is mapped per page and no store hook runs.
* Copy-on-write, the instruction count and budget, the hot imports (memcpy, memset, bzero,
  strlen, strcmp, strncmp, memcmp, malloc/new, pthread_self, the owner thread's TLV accessor)
  and the game's pool allocator run in C. A C model declines anything unusual and the Python
  model of `ui_vm`/`vm` then runs unchanged, so refusals keep their wording.
* The baseline (`commit()` / `_baseline` / `_restore()`) is an immutable snapshot in C: a
  commit or restore costs the pages written since the last one, not the heap size.
* Live memory is read where it is touched (16 KiB around a fault) instead of 512 KiB windows.
* Freshness (the stale-page fix): every copied live page belongs to a generation. `begin_read()`
  (and `reset()` once the generation is older than `generation_seconds`) starts a new one;
  pages of an older generation are read again from the game before any code or model sees
  them. A long-lived emulator therefore never mixes pages copied minutes apart, and keeps its
  translated code and page tables.
* Read sets: `trace_begin()` / `trace_pages()` list the live pages a computation touched and
  `fingerprint()` hashes their copied bytes (`ui_cache` validates stored answers with them).
  `vm.reader.read` serves the same copied pages, so what a recipe reads directly is part of
  the read set and of the same generation.
"""
from __future__ import annotations

import ctypes
import os
import struct
import time
import weakref
from collections import Counter
from pathlib import Path

from unicorn import Uc, UcError, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_BLOCK, UC_HOOK_CODE, UC_HOOK_INTR
from unicorn import unicorn_const as UCC
import unicorn.arm64_const as A
from unicorn.unicorn_py3 import unicorn as _ucpy

from . import ui_vm, vm as _vm
from .fastvm import (FastVM, _TextPages, _LivePages, CODE_PHYS, DATA_PHYS, PAD_PHYS, DATA_SLOTS,
                     STOP_AT, _FAULT, _STUB)
from .ui_vm import UiHandlerVM, INTERCEPTS, TICKS_START, PTHREAD_TSD_OFFSET
from .vm import (_Stop, PAGE, PRIVATE, PRIVATE_END, STACK, STACK_SIZE, HEAP, HEAP_SIZE, TRAP, TLS, STATIC,
                 STATIC_SIZE, NULL_LIMIT, THREAD_FLAG_RVA, THREAD_MAIN_RVA, THREAD_OTHER_RVA, TLV_REFUSED)

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = 'libfm_ui_accel2.dylib'      # ABI 2 (free-list sites); scripts/build_ui_accel.sh
ABI_VERSION = 2
MASK64 = (1 << 64) - 1
NO_LIMIT = 1 << 62
FAULT_WINDOW = 0x4000              # live memory is read 16 KiB (one host page) around a fault
WATCH_PHYS = 0x4000_0000_0000      # I/O region behind watched live pages (never guest-visible)
GENERATION_SECONDS = 5.0           # reset() starts a new generation after this long
(ACT_PYTHON, ACT_RETURN_0, ACT_RETURN_1, ACT_STACK_PROBE, ACT_MEMCPY, ACT_MEMSET, ACT_BZERO, ACT_STRLEN,
 ACT_STRCMP, ACT_MEMCMP, ACT_MALLOC, ACT_CALLOC, ACT_ALIGNED_NEW, ACT_PTHREAD_SELF, ACT_PTHREAD_EQUAL,
 ACT_TLV, ACT_STRNCMP, ACT_POOL_ALLOC, ACT_POOL_FREE, ACT_FIXED_POOL_ALLOC, ACT_POOL_GET,
 ACT_FREE_LIST_POP, ACT_FREE_LIST_PUSH) = range(23)
INTERCEPT_ACTIONS = {'pool_alloc': ACT_POOL_ALLOC, 'pool_free': ACT_POOL_FREE,
                     'fixed_pool_alloc': ACT_FIXED_POOL_ALLOC}
SITE_ACTIONS = {'pop': ACT_FREE_LIST_POP, 'push': ACT_FREE_LIST_PUSH, 'pool_get': ACT_POOL_GET,
                'pool_put': ACT_POOL_FREE}


class _State(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        'icount', 'budget', 'timeout_ticks', 'deadline', 'stop', 'pc', 'lr', 'sp', 'x0',
        'fills', 'faults', 'new_pages', 'tlb_flushes', 'blocks', 'data_used', 'data_slots', 'ndirty',
        'miss_addr', 'ext_n', 'pending_id', 'stop_addr',
        'heap_top', 'heap_lo', 'heap_hi', 'nalloc', 'gen', 'trace', 'sticky', 'native_calls', 'declined',
        'commits', 'restores', 'pages_committed', 'pages_restored', 'blobs_live', 'oom', 'current_serial',
        'nbase')]


_lib = None


def library_path() -> Path:
    env = os.environ.get('FMDB_UI_ACCEL')
    return Path(env) if env else ROOT / 'build' / LIBRARY


def _load():
    global _lib
    if _lib is None:
        lib = ctypes.CDLL(str(library_path()))
        u64, ptr, c_int, u32 = ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32
        lib.fm_accel_new.restype = ctypes.POINTER(_State)
        lib.fm_accel_new.argtypes = [ptr, ptr, ptr, ptr, c_int, u64, u64, u64, u64, u64, _FAULT]
        lib.fm_accel_free.argtypes = [ptr]
        for name in ('fm_accel_code_host', 'fm_accel_data_host'):
            getattr(lib, name).restype = ptr
            getattr(lib, name).argtypes = [ptr]
        lib.fm_accel_add_range.restype = ptr
        lib.fm_accel_add_range.argtypes = [ptr, u64, u64, c_int]
        lib.fm_accel_add_code.argtypes = [ptr, u64, ctypes.c_char_p]
        lib.fm_accel_add_data.restype = ctypes.c_int64
        lib.fm_accel_add_data.argtypes = [ptr, u64, ctypes.c_char_p]
        lib.fm_accel_has.argtypes = [ptr, u64]
        lib.fm_accel_restore.argtypes = [ptr]
        lib.fm_accel_reset_data.argtypes = [ptr]
        lib.fm_accel_peek.argtypes = [ptr, u64, ptr, u64]
        lib.fm_accel_poke.argtypes = [ptr, u64, ctypes.c_char_p, u64, c_int]
        lib.fm_accel_set_regs.argtypes = [ptr, ptr]
        lib.fm_accel_run.argtypes = [ptr, u64, u64]
        lib.fm_accel_ticks_per_second.restype = u64
        lib.fm_accel_clear_imports.argtypes = [ptr]
        lib.fm_accel_set_action.argtypes = [ptr, u32, c_int]
        lib.fm_accel_set_import.argtypes = [ptr, u64, u32]
        lib.fm_accel_set_stubs.restype = ptr
        lib.fm_accel_set_stubs.argtypes = [ptr, u64, u64, ptr, u64, u64, _STUB, ptr]
        lib.fm_accel_ext_log.restype = ctypes.POINTER(ctypes.c_uint16)
        lib.fm_accel_ext_log.argtypes = [ptr]
        lib.fm_ui_setup.argtypes = [ptr, u64]
        lib.fm_ui_commit.restype = ptr
        lib.fm_ui_commit.argtypes = [ptr]
        lib.fm_ui_restore.argtypes = [ptr, ptr]
        lib.fm_ui_release.argtypes = [ptr, ptr]
        lib.fm_ui_new_generation.argtypes = [ptr]
        lib.fm_ui_trace_begin.argtypes = [ptr, c_int]
        lib.fm_ui_trace_end.argtypes = [ptr]
        lib.fm_ui_set_watch_base.argtypes = [ptr, u64]
        lib.fm_ui_watch.restype = u64
        lib.fm_ui_watch.argtypes = [ptr, ptr, u64]
        lib.fm_ui_watch_add.argtypes = [ptr, u64]
        lib.fm_ui_debug_word.argtypes = [ptr, u64]
        lib.fm_ui_debug_hits.restype = u64
        lib.fm_ui_debug_hits.argtypes = [ptr, ptr, ptr]
        lib.fm_ui_trace_masks.argtypes = [ptr, ptr, u64, ptr]
        lib.fm_ui_hash_masked.argtypes = [ctypes.c_char_p, ptr, u64, ptr]
        lib.fm_ui_hash_live_masked.argtypes = [ptr, ptr, ptr, u64, ptr]
        lib.fm_ui_trace_collect.restype = u64
        lib.fm_ui_trace_collect.argtypes = [ptr, ptr, u64]
        lib.fm_ui_hash_pages.argtypes = [ctypes.c_char_p, u64, ptr]
        lib.fm_ui_hash_live.argtypes = [ptr, ptr, u64, ptr]
        lib.fm_ui_live_page.argtypes = [ptr, u64, ptr, u64, u64]
        lib.fm_ui_alloc.restype = u64
        lib.fm_ui_alloc.argtypes = [ptr, u64, u64]
        lib.fm_ui_alloc_size.restype = u64
        lib.fm_ui_alloc_size.argtypes = [ptr, u64]
        lib.fm_ui_set_owner_thread.argtypes = [ptr, u64, u64, u64, u64, u64, u64, ptr]
        lib.fm_ui_ext_counts.restype = u64
        lib.fm_ui_ext_counts.argtypes = [ptr, ptr, ptr, u64]
        lib.fm_ui_log_externals.argtypes = [ptr, c_int]
        lib.fm_ui_add_intercept.argtypes = [ptr, u64, c_int, _STUB]
        lib.fm_ui_intercept_count.restype = u64
        lib.fm_ui_intercept_count.argtypes = [ptr, c_int]
        version = getattr(lib, 'fm_ui_abi_version', None)
        if version is None or version() != ABI_VERSION:
            raise OSError(f'{library_path()} is not ABI {ABI_VERSION}: run scripts/build_ui_accel.sh')
        lib.fm_ui_add_site.argtypes = [ptr, u64, c_int, u64, c_int, u64, c_int, ptr, ptr, _STUB]
        _lib = lib
    return _lib


def available() -> bool:
    """True when the UI accelerator library is built and loads."""
    try:
        _load()
    except OSError:
        return False
    return True


def hash_pages(data: bytes) -> list:
    """64-bit fingerprints of consecutive 4 KiB pages (the hash `fingerprint()` uses)."""
    count = len(data) // PAGE
    out = (ctypes.c_uint64 * count)()
    _load().fm_ui_hash_pages(data, count, out)
    return list(out)


FULL_MASK = (MASK64,) * 8


def hash_masked(data: bytes, masks) -> list:
    """Fingerprints of consecutive 4 KiB pages over the 8-byte words selected by `masks`
    (8 x u64 per page; the hash `FastUiHandlerVM.fingerprint` uses)."""
    count = len(data) // PAGE
    flat = (ctypes.c_uint64 * (8 * max(1, count))).from_buffer_copy(
        b''.join(struct.pack('<8Q', *m) for m in masks) or bytes(64))
    out = (ctypes.c_uint64 * max(1, count))()
    _load().fm_ui_hash_masked(data, flat, count, out)
    return list(out[:count])


class _UcView:
    """`vm.uc` for code written against PropertyVM: stores into the VM heap go through the
    tracked path (so commit/restore see them) and loads outside the private ranges read the
    pools; everything else is the Unicorn instance."""

    __slots__ = ('_uc', '_vm')

    def __init__(self, uc, vm):
        object.__setattr__(self, '_uc', uc)
        object.__setattr__(self, '_vm', vm)

    def __getattr__(self, name):
        return getattr(self._uc, name)

    def mem_write(self, address, data):
        if PRIVATE <= address < PRIVATE_END and not HEAP <= address < HEAP + HEAP_SIZE:
            self._uc.mem_write(address, data)
        elif data:
            # the VM heap, or live memory (ui_recipes_screens.install_context replaces the UI
            # context record and puts it back): a tracked store, part of commit and restore
            self._vm._store(address, data, 1)

    def mem_read(self, address, size):
        if PRIVATE <= address < PRIVATE_END:
            return self._uc.mem_read(address, size)
        buf = ctypes.create_string_buffer(size)
        if self._vm._lib.fm_accel_peek(self._vm._a, address, buf, size):
            raise UcError(UCC.UC_ERR_READ_UNMAPPED)
        return bytearray(buf.raw)

    def ctl_remove_cache(self, begin, end):
        # translations are keyed by pool address here: drop them all (rare: hook installation)
        self._uc.ctl_flush_tb()


class _Allocations:
    """`vm.allocations` (the realloc model asks for the size of a block)."""

    def __init__(self, vm):
        self._vm = vm

    def get(self, address, default=None):
        size = self._vm._lib.fm_ui_alloc_size(self._vm._a, address)
        return default if size == MASK64 else size

    def __contains__(self, address):
        return self._vm._lib.fm_ui_alloc_size(self._vm._a, address) != MASK64

    def __getitem__(self, address):
        size = self._vm._lib.fm_ui_alloc_size(self._vm._a, address)
        if size == MASK64:
            raise KeyError(address)
        return size

    def __len__(self):
        return self._vm._st.nalloc

    def clear(self):
        pass


class _PoolReader:
    """`vm.reader` for recipes: reads the copied (pristine) live pages of this generation, so
    direct reads agree with what the emulated code sees and join the read set."""

    def __init__(self, vm, source):
        self._vm, self._source = vm, source

    def read(self, address, length):
        return self._vm.live_read(address, length)

    def __getattr__(self, name):
        return getattr(self._source, name)


class FastBaseline:
    """A committed VM-private state (snapshot handle in the C library)."""

    __slots__ = ('_vm', 'handle', 'heap_top', 'nalloc', 'tlv_block', 'fpos', 'ticks', '__weakref__')

    def __init__(self, vm, handle, heap_top, nalloc, tlv_block, fpos, ticks):
        self._vm = weakref.ref(vm)
        self.handle, self.heap_top, self.nalloc = handle, heap_top, nalloc
        self.tlv_block, self.fpos, self.ticks = tlv_block, fpos, ticks

    def __del__(self):
        handle, self.handle = self.handle, None
        if not handle or _lib is None:
            return
        try:
            vm = self._vm()
            _lib.fm_ui_release(getattr(vm, '_a', None) if vm is not None else None, handle)
        except Exception:  # noqa: BLE001 - interpreter shutdown
            pass


class FastUiHandlerVM(UiHandlerVM, FastVM):
    fast_window = FAULT_WINDOW
    generation_seconds = GENERATION_SECONDS
    _limited = False
    _intercepts = ()
    _watch_mapped = False
    _watched = frozenset()
    _tracing = False
    files_touched = None

    # ------------------------------------------------------------------ construction
    def _init_uc(self):
        lib = self._lib = _load()
        uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        uc.ctl_set_cpu_model(A.UC_CPU_ARM64_MAX)
        uc.ctl_set_tlb_mode(UCC.UC_TLB_VIRTUAL)
        self.uc = _UcView(uc, self)
        self._source = self.reader
        self.reader = _PoolReader(self, self._source)
        text_size = (self.text_end - self.base + PAGE - 1) & ~(PAGE - 1)
        uclib = _ucpy.uclib
        fns = (ctypes.c_void_p * 6)(*(ctypes.cast(f, ctypes.c_void_p) for f in (
            uclib.uc_emu_start, uclib.uc_emu_stop, uclib.uc_reg_write_batch, uclib.uc_reg_read_batch,
            uclib.uc_ctl, uclib.uc_reg_write)))
        regs = (ctypes.c_int * 34)(*([getattr(A, f'UC_ARM64_REG_X{i}') for i in range(29)]
                                     + [A.UC_ARM64_REG_X29, A.UC_ARM64_REG_LR, A.UC_ARM64_REG_SP,
                                        A.UC_ARM64_REG_TPIDR_EL0, A.UC_ARM64_REG_TPIDRRO_EL0]))
        out_regs = (ctypes.c_int * 4)(A.UC_ARM64_REG_PC, A.UC_ARM64_REG_LR, A.UC_ARM64_REG_SP, A.UC_ARM64_REG_X0)
        flush_code = (UCC.UC_CTL_IO_WRITE << 30) | UCC.UC_CTL_TLB_FLUSH
        self._fault_cb = _FAULT(self._on_fault)
        self._a = a = lib.fm_accel_new(uc._uch, fns, regs, out_regs, flush_code, self.base, text_size,
                                       CODE_PHYS, DATA_PHYS, DATA_SLOTS, self._fault_cb)
        if not a:
            raise MemoryError('fm_ui_accel could not reserve its pools')
        self._st = st = a.contents
        st.budget = self.budget
        self._ticks_per_us = lib.fm_accel_ticks_per_second() / 1_000_000
        st.timeout_ticks = int(self.timeout_us * self._ticks_per_us)
        uc.mem_map_ptr(CODE_PHYS, text_size, UCC.UC_PROT_READ | UCC.UC_PROT_EXEC, lib.fm_accel_code_host(a))
        uc.mem_map_ptr(DATA_PHYS, DATA_SLOTS * PAGE, UCC.UC_PROT_READ | UCC.UC_PROT_WRITE,
                       lib.fm_accel_data_host(a))
        self._private = {}
        rw, rx = UCC.UC_PROT_READ | UCC.UC_PROT_WRITE, UCC.UC_PROT_READ | UCC.UC_PROT_EXEC
        for start, size, perms in ((STACK, STACK_SIZE, rw), (HEAP, HEAP_SIZE, rw), (TLS, PAGE, rw),
                                   (STATIC, STATIC_SIZE, rw), (TRAP, PAGE, rx)):
            host = lib.fm_accel_add_range(a, start, size, perms)
            if not host:
                raise MemoryError('fm_ui_accel could not reserve a private range')
            uc.mem_map_ptr(start, size, perms, host)
            self._private[start] = host
        if lib.fm_ui_setup(a, HEAP):
            raise MemoryError('fm_ui_accel could not set up page tracking')
        ctypes.memmove(self._private[TRAP], b'\xc0\x03\x5f\xd6' * (PAGE // 4), PAGE)
        self._heap_host = self._private[HEAP]
        self.code_pages = _TextPages(self.base, self.base + text_size)
        self.live_pages = _LivePages(self)
        self._regs = (ctypes.c_uint64 * 34)()
        self._zero29 = bytes(29 * 8)
        self._cb_error = None
        self._peek_buf = ctypes.create_string_buffer(1 << 16)
        self._peek_view = memoryview(self._peek_buf)
        self._page_buf = ctypes.create_string_buffer(PAGE)
        self._u64 = ctypes.c_uint64()
        self._u64_ref = ctypes.byref(self._u64)
        self._hooks = []
        self._py_block_hook = None
        self._add_c_hook(UCC.UC_HOOK_TLB_FILL, lib.fm_accel_tlb_fill, 1, 0)
        self._add_c_hook(UC_HOOK_BLOCK, lib.fm_accel_block, 1, 0)
        # externals: an id for every import name; the models the library has run in C
        names = sorted(set(self.image.stubs.values()) | set(self.image.binds.values()))
        self._ext_names = [None] + names
        self._ext_ids = {name: i for i, name in enumerate(self._ext_names) if name}
        self.native_models = os.environ.get('FMDB_UI_NATIVE', '1') != '0'
        owner = self.thread == 'owner'
        native = {_vm._noop: ACT_RETURN_0, _vm._true: ACT_RETURN_1, _vm._preserve: ACT_STACK_PROBE}
        if self.native_models:
            native.update({
                _vm._memcpy: ACT_MEMCPY, _vm._memset: ACT_MEMSET, _vm._bzero: ACT_BZERO,
                _vm._strlen: ACT_STRLEN, _vm._strcmp: ACT_STRCMP, _vm._memcmp: ACT_MEMCMP,
                _vm._malloc: ACT_MALLOC, _vm._calloc: ACT_CALLOC, _vm._aligned_new: ACT_ALIGNED_NEW,
                _vm._pthread_equal: ACT_PTHREAD_EQUAL, ui_vm._strncmp: ACT_STRNCMP})
            if owner:
                native.update({_vm._pthread_self: ACT_PTHREAD_SELF, ui_vm._tlv_get_addr: ACT_TLV})
        self.native_imports = {}
        for name, i in self._ext_ids.items():
            action = native.get(self._resolve(name), ACT_PYTHON)
            if action:
                lib.fm_accel_set_action(a, i, action)
                self.native_imports[name] = action
        if owner:
            start, end = self.image.tlv_vars
            offsets = (ctypes.c_uint64 * max(1, (end - start) // 24))()
            for k, desc in enumerate(range(start, end, 24)):
                offsets[k] = MASK64 if desc in TLV_REFUSED else \
                    struct.unpack('<Q', self.image.file_bytes(desc + 16, 8))[0]
            if lib.fm_ui_set_owner_thread(a, self.base + THREAD_FLAG_RVA, self.base + THREAD_MAIN_RVA,
                                          self.base + THREAD_OTHER_RVA, PTHREAD_TSD_OFFSET,
                                          self.base + start, self.base + end, offsets):
                raise MemoryError('fm_ui_accel could not store the thread-local table')
        count = (self.stub_end - self.stub_start) // 4
        ids = (ctypes.c_uint16 * count)()
        for rva, name in self.image.stubs.items():
            k = (self.base + rva - self.stub_start) // 4
            if 0 <= k < count:
                ids[k] = self._ext_ids[name]
        self._stub_cb = _STUB(self._on_stub_address)
        regs4 = (ctypes.c_int * 4)(A.UC_ARM64_REG_X0, A.UC_ARM64_REG_X9, A.UC_ARM64_REG_PC, A.UC_ARM64_REG_LR)
        pad = lib.fm_accel_set_stubs(a, self.stub_start, count, ids, PAD_PHYS, STACK_SIZE // 2, self._stub_cb, regs4)
        if not pad:
            raise MemoryError('fm_ui_accel could not reserve the import page')
        uc.mem_map_ptr(PAD_PHYS, PAGE, UCC.UC_PROT_EXEC, pad)
        self._ext_log = lib.fm_accel_ext_log(a)
        self._add_c_hook(UC_HOOK_CODE, lib.fm_accel_stub, self.stub_start, self.stub_end - 1)
        self._count_ids = (ctypes.c_uint32 * 256)()
        self._count_values = (ctypes.c_uint32 * 256)()
        self._gen_started = time.monotonic()
        self.generations = 1
        self.pages_refreshed = self.pages_changed = self.windows_read = 0

    def _add_c_hook(self, kind, function, begin, end):
        handle = ctypes.c_size_t()
        status = _ucpy.uclib.uc_hook_add(self.uc._uch, ctypes.byref(handle), kind,
                                         ctypes.cast(function, ctypes.c_void_p),
                                         ctypes.cast(self._a, ctypes.c_void_p),
                                         ctypes.c_uint64(begin), ctypes.c_uint64(end))
        if status:
            raise UcError(status)
        self._hooks.append(handle)

    def _install_hooks(self):
        """UiHandlerVM's hooks, as far as the library does not serve them: the interrupt hook
        (unaligned LSE atomics) stays in Python; the pool allocator intercepts run in C."""
        self._fast_registers()
        self.uc.hook_add(UC_HOOK_INTR, self._on_intr)
        self.intercepted = Counter()
        self._intercepts = []
        self._intercept_cb = _STUB(self._on_intercept_address)
        for rva, (name, model) in INTERCEPTS.items():
            action = INTERCEPT_ACTIONS.get(name, ACT_PYTHON) if self.native_models else ACT_PYTHON
            index = self._lib.fm_ui_add_intercept(self._a, self.base + rva, action, self._intercept_cb)
            if index < 0:
                raise RuntimeError('too many intercepts for fm_ui_accel')
            self._intercepts.append((self.base + rva, name, model))
            self._add_c_hook(UC_HOOK_CODE, self._lib.fm_ui_intercept, self.base + rva, self.base + rva)
        self.free_list_sites = ui_vm.free_list_sites(self.image) if ui_vm.free_lists_wanted() else []
        for site in self.free_list_sites:
            action = SITE_ACTIONS[site.kind] if self.native_models else ACT_PYTHON
            address = self.base + site.rva
            if site.resume:
                regs = (ctypes.c_int * 2)(*(ui_vm.reg_id(r) for r, _ in site.sets))
                vals = (ctypes.c_uint64 * 2)(*(0 if v is None else self.base + v for _, v in site.sets))
                dest = ui_vm.reg_id(site.dest) if site.dest is not None else -1
                index = self._lib.fm_ui_add_site(self._a, address, action, self.base + site.resume, dest,
                                                 self.base + site.pool if site.pool else 0, len(site.sets),
                                                 regs, vals, self._intercept_cb)
            else:
                index = self._lib.fm_ui_add_intercept(self._a, address, action, self._intercept_cb)
            if index < 0:
                raise RuntimeError('too many intercepts for fm_ui_accel')
            self._intercepts.append((address, site.name, ui_vm._free_list_model(site)))
            self._add_c_hook(UC_HOOK_CODE, self._lib.fm_ui_intercept, address, address)
        self.native_stub_count = len(self.native_imports)
        self._limited = False

    def _on_intercept_address(self, address):
        try:
            for at, name, model in self._intercepts:
                if at == address:
                    self._on_intercept(self.uc, address, 4, (name, model))
                    return
        except BaseException as exc:  # noqa: BLE001 - never unwind through C
            if self._cb_error is None:
                self._cb_error = exc
            self.uc.emu_stop()

    def _code_word(self, uc, pc):
        return struct.unpack('<I', self.read(pc, 4))[0]

    # ------------------------------------------------------------------ attributes kept in C
    @property
    def heap_top(self):
        st = self.__dict__.get('_st')
        return st.heap_top if st is not None else HEAP

    @heap_top.setter
    def heap_top(self, value):
        st = self.__dict__.get('_st')
        if st is not None:
            st.heap_top = value

    @property
    def allocations(self):
        return self.__dict__.setdefault('_allocations', _Allocations(self))

    @allocations.setter
    def allocations(self, value):
        pass

    @property
    def timeout_us(self):
        return self.__dict__.get('_timeout_us', 0)

    @timeout_us.setter
    def timeout_us(self, value):
        self.__dict__['_timeout_us'] = value
        st = self.__dict__.get('_st')
        if st is not None:
            st.timeout_ticks = int(value * self._ticks_per_us)

    @property
    def dirty(self):
        return {}

    @dirty.setter
    def dirty(self, value):
        pass

    def alloc(self, size, align=16):
        size = max(int(size), 1)
        address = self._lib.fm_ui_alloc(self._a, size & MASK64, align) if size <= MASK64 else 0
        if not address:
            raise _Stop('VM heap exhausted', str(size))
        return address

    def fast(self):
        """No instruction limit (the count itself is kept in C and costs nothing)."""
        self.budget = NO_LIMIT
        self.counting = True
        return self

    def limit_instructions(self, count: int):
        """Stop a call after `count` instructions; shows as 'emulation stopped early (timeout)'
        like UiHandlerVM's limit (which counts per emulation segment, this one per call)."""
        count = int(count)
        if count <= 0:
            raise ValueError('instruction limit must be positive')
        self.budget = self.instruction_limit = count
        self._limited = True
        return self

    # ------------------------------------------------------------------ memory
    def _fault_in(self, page):
        lib, a = self._lib, self._a
        state = lib.fm_accel_has(a, page)
        if state in (1, 2, 3):
            return
        if PRIVATE <= page < PRIVATE_END:
            raise _Stop('access to unmapped VM-private memory', hex(page))
        if page < NULL_LIMIT:
            raise _Stop('null or low pointer dereference', hex(page))
        if page in self.code_pages:
            lib.fm_accel_add_code(a, page, self.image.file_bytes(page - self.base, PAGE))
            return
        if page in self.unreadable:
            raise _Stop('unreadable live memory', hex(page))
        size = self.fast_window
        start = page & ~(size - 1)
        data = None
        many = getattr(self._source, 'read_many_status', None) if size > PAGE else None
        if many is not None and not (start < self.text_end and start + size > self.base):
            try:
                (_, data), = many([(start, size)])
            except Exception:  # noqa: BLE001 - the single-page read below decides
                data = None
            if data is not None and len(data) != size:
                data = None
        if data is None:
            start, size = page, PAGE
            try:
                data = self._source.read(page, PAGE)
            except Exception as exc:  # noqa: BLE001 - any reader refusal is a fault
                self.unreadable.add(page)
                raise _Stop('unreadable live memory', f'{page:#x}: {exc}') from None
        self.windows_read += 1
        self._add_pages(start, data)

    def _add_pages(self, start, data):
        """Copy consecutive live pages into the pool (new or of an older generation)."""
        lib, a = self._lib, self._a
        added = 0
        for offset in range(0, len(data), PAGE):
            slot = lib.fm_accel_add_data(a, start + offset, data[offset:offset + PAGE])
            if slot >= 0:
                added += 1
                if self._watched and start + offset in self._watched:
                    lib.fm_ui_watch_add(a, start + offset)
            elif slot == -1:
                raise _Stop('VM live page pool exhausted', str(DATA_SLOTS))
            elif slot == -3:
                raise RuntimeError('a stale live page carries VM-private stores (reset() before a new generation)')
        if added and self.overlays:
            for address, value in self.overlays.items():
                if start <= address < start + len(data):
                    self._poke(address, value)
        if self._call is not None:
            self._call.new_pages += added
        return added

    def live_read(self, address: int, length: int) -> bytes:
        """Live bytes as copied in this generation (without any VM-private store)."""
        from .memory import MemoryReadError
        lib, a, buf = self._lib, self._a, self._page_buf
        out = []
        end = address + length
        page = address & ~(PAGE - 1)
        try:
            while page < end:
                lo, hi = max(address, page) - page, min(end, page + PAGE) - page
                while lib.fm_ui_live_page(a, page, buf, lo, hi):
                    self._fault_in(page)
                out.append(buf.raw[lo:hi])
                page += PAGE
        except _Stop as stop:
            raise MemoryReadError(f'cannot read {length} bytes at {address:#x}: {stop.reason} '
                                  f'{stop.detail or ""}') from None
        return out[0] if len(out) == 1 else b''.join(out)

    # ------------------------------------------------------------------ freshness and read sets
    def begin_read(self, prefetch=None, max_age=None):
        """Start a read: drop VM-private state and make every copied live page stale, so it is
        read again from the game before use. `prefetch` (page addresses, e.g. the read set of
        the same question last time) is read in one batched request. With `max_age` (seconds)
        a generation younger than that is kept: a burst of reads shares one copy of each page.
        Returns True when a new generation started."""
        self._baseline = None
        self._restore_state()
        if max_age is not None and time.monotonic() - self._gen_started <= max_age:
            return False
        self._lib.fm_ui_new_generation(self._a)
        self.unreadable.clear()
        self._gen_started = time.monotonic()
        self.generations += 1
        if prefetch:
            self.prefetch(prefetch)
        return True

    def prefetch(self, pages, data=None):
        """Bring the given live pages into this generation with one batched read (`data`:
        their bytes when the caller has just read them). Unreadable pages are skipped."""
        pages = sorted(set(p & ~(PAGE - 1) for p in pages))
        if data is None:
            many = getattr(self._source, 'read_many_status', None)
            if many is None:
                return 0
            runs, start, count = [], None, 0
            for p in pages:
                if start is not None and p == start + count * PAGE and count < 64:
                    count += 1
                    continue
                if start is not None:
                    runs.append((start, count * PAGE))
                start, count = p, 1
            if start is not None:
                runs.append((start, count * PAGE))
            done = 0
            for (start, size), (_, chunk) in zip(runs, many(runs)):
                if chunk is not None and len(chunk) == size:
                    done += self._add_pages(start, chunk)
            self.pages_refreshed += done
            return done
        done = 0
        for p, chunk in zip(pages, data):
            if chunk is not None:
                done += self._add_pages(p, chunk)
        self.pages_refreshed += done
        return done

    def watch(self, pages=()):
        """Record reads of exactly these live pages per 8-byte word during traces (their loads
        and stores take an I/O path; every other page keeps the direct path). The pages of the
        free-list heads the models replace are always watched, so their words never enter a
        fingerprint (see `read_set`)."""
        pages = set(pages) | {p & ~(PAGE - 1) for p in self.unfingerprinted_words()}
        if pages and not self._watch_mapped:
            uclib = _ucpy.uclib
            uclib.uc_mmio_map.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_size_t, ctypes.c_void_p,
                                          ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
            status = uclib.uc_mmio_map(
                self.uc._uch, WATCH_PHYS, DATA_SLOTS * PAGE,
                ctypes.cast(self._lib.fm_ui_watch_read, ctypes.c_void_p), ctypes.cast(self._a, ctypes.c_void_p),
                ctypes.cast(self._lib.fm_ui_watch_write, ctypes.c_void_p), ctypes.cast(self._a, ctypes.c_void_p))
            if status:
                raise UcError(status)
            self._lib.fm_ui_set_watch_base(self._a, WATCH_PHYS)
            self._watch_mapped = True
        pages = sorted(set(p & ~(PAGE - 1) for p in pages))
        self._watched = set(pages)
        array = (ctypes.c_uint64 * max(1, len(pages)))(*pages)
        return self._lib.fm_ui_watch(self._a, array, len(pages))

    def trace_begin(self):
        """Start recording the live pages touched (by emulated code, models and vm.reader).
        Reads by models and vm.reader are also recorded per 8-byte word, as are the loads of
        emulated code on watched pages (`watch`)."""
        self.files_touched = set()
        self._tracing = True
        self._lib.fm_ui_trace_begin(self._a, 1)

    def trace_end(self):
        self._tracing = False
        self._lib.fm_ui_trace_end(self._a)

    def trace_pages(self) -> list:
        """Addresses of the live pages touched since trace_begin()."""
        cap = self._st.data_used
        out = (ctypes.c_uint64 * max(1, cap))()
        count = self._lib.fm_ui_trace_collect(self._a, out, cap)
        return sorted(out[:count])

    def trace_masks(self, pages) -> list:
        """Per page, the 8-byte words read during the trace as eight 64-bit masks (complete
        only for watched pages and for pages no emulated code loaded from)."""
        count = len(pages)
        addresses = (ctypes.c_uint64 * max(1, count))(*pages)
        out = (ctypes.c_uint64 * (8 * max(1, count)))()
        self._lib.fm_ui_trace_masks(self._a, addresses, count, out)
        return [tuple(out[8 * i:8 * i + 8]) for i in range(count)]

    def debug_word(self, address=0):
        """Diagnostics: record who loads the watched 8-byte word at `address` (0: stop)."""
        self._lib.fm_ui_debug_word(self._a, address)

    def debug_hits(self) -> list:
        """[(pc RVA, lr RVA)] of the loads recorded since debug_word()."""
        pcs, lrs = (ctypes.c_uint64 * 32)(), (ctypes.c_uint64 * 32)()
        count = self._lib.fm_ui_debug_hits(self._a, pcs, lrs)
        return [(pcs[i] - self.base, lrs[i] - self.base) for i in range(count)]

    def read_set(self):
        """(pages, masks) of the running trace: the live pages touched and, for the watched
        ones, the words read ({page: 8 x u64})."""
        pages = self.trace_pages()
        watched = [p for p in pages if p in self._watched]
        masks = dict(zip(watched, self.trace_masks(watched)))
        for word in self.unfingerprinted_words():
            page, index = word & ~(PAGE - 1), (word & (PAGE - 1)) >> 3
            if page in masks:
                groups = list(masks[page])
                groups[index >> 6] &= ~(1 << (index & 63))
                masks[page] = tuple(groups)
        return pages, masks

    def unfingerprinted_words(self) -> tuple:
        """Absolute addresses of the free-list heads whose sites are modelled (ui_vm.FREE_LIST_SITES):
        emulated code no longer reads them, and a model's own read never decides an answer."""
        if not getattr(self, 'free_list_sites', None):
            return ()
        return tuple(self.base + rva for rva in ui_vm.FREE_LIST_HEADS)

    def fingerprint(self, pages, masks=None) -> list:
        """64-bit fingerprints of the copied bytes of the given live pages (0: not copied);
        `masks` ({page: 8 x u64}) restricts a page to the words read."""
        count = len(pages)
        masks = masks or {}
        addresses = (ctypes.c_uint64 * max(1, count))(*pages)
        full = struct.pack('<8Q', *FULL_MASK)
        flat = (ctypes.c_uint64 * (8 * max(1, count))).from_buffer_copy(
            b''.join(struct.pack('<8Q', *masks[p]) if p in masks else full for p in pages) or bytes(64))
        out = (ctypes.c_uint64 * max(1, count))()
        self._lib.fm_ui_hash_live_masked(self._a, addresses, flat, count, out)
        return list(out[:count])

    def rng_state_range(self):
        """(address, length) of the owner thread's random generator state as the TLV model
        finds it (the bytes rng='copy' reads), or None."""
        try:
            desc = _vm.RNG_STATE_TLV
            word = self.read_u64(self.base + desc + 8)
            owner = ui_vm.owner_pthread(self)
            block = self.read_u64(owner + PTHREAD_TSD_OFFSET + 8 * (word & 0xFFFFFFFF))
        except Exception:  # noqa: BLE001 - layout not readable: nothing to exclude
            return None
        return (block + (word >> 32), 0x18) if block >= NULL_LIMIT else None

    # ------------------------------------------------------------------ baseline state
    def _restore_state(self):
        st, base = self._st, self._baseline
        if base is None:
            self._fpos = {}
            self._ticks = TICKS_START
            self._lib.fm_ui_restore(self._a, None)
            st.heap_top = HEAP
            st.nalloc = 0
            self._tlv_block = None
        else:
            self._fpos = dict(base.fpos)
            if self._lib.fm_ui_restore(self._a, base.handle):
                raise RuntimeError('this baseline was committed before the live pages were dropped')
            st.heap_top = base.heap_top
            st.nalloc = base.nalloc
            self._tlv_block = base.tlv_block
            self._ticks = base.ticks
        self._rng_cell = None
        self._rd_count = 0

    def commit(self):
        """Make the current VM-private state the starting point of every later call."""
        handle = self._lib.fm_ui_commit(self._a)
        if not handle:
            raise MemoryError('fm_ui_accel could not snapshot the VM state')
        st = self._st
        self._baseline = FastBaseline(self, handle, st.heap_top, st.nalloc, self._tlv_block,
                                      dict(self._fpos), getattr(self, '_ticks', TICKS_START))

    def reset(self):
        """Drop the baseline: back to the pristine copy of live memory. A reset is the point
        where nothing built earlier survives, so an old generation ends here."""
        if not self._tracing and time.monotonic() - self._gen_started > self.generation_seconds:
            self.begin_read()                   # (never inside a trace: its read set is one generation)
            return
        self._baseline = None
        self._restore_state()

    def invalidate(self):
        self._baseline = None
        FastVM.invalidate(self)
        self.__dict__.pop('_factory', None)
        self._gen_started = time.monotonic()

    # ------------------------------------------------------------------ calls
    def call(self, address, args=(), *, fargs=()):
        st = self._st
        try:
            return FastVM.call(self, address, args, fargs=fargs)
        except _Stop as stop:
            if self._limited and stop.reason == 'instruction budget exceeded':
                raise _Stop('emulation stopped early (timeout)', f'pc={st.pc - self.base:#x}') from None
            raise
        finally:
            if st.native_calls:
                count = self._lib.fm_ui_ext_counts(self._a, self._count_ids, self._count_values, 256)
                names, stubbed = self._ext_names, self.stubbed
                for k in range(count):
                    stubbed[names[self._count_ids[k]]] += self._count_values[k]
            for index, (_, name, _) in enumerate(self._intercepts):
                done = self._lib.fm_ui_intercept_count(self._a, index)
                if done:
                    self.intercepted[name] += done
            if st.oom:
                st.oom = 0
                raise MemoryError('fm_ui_accel ran out of memory for page copies')

    def backtrace(self, depth=12):
        """Shipped return addresses (RVAs) on the frame-pointer chain at the last stop."""
        out = [self.uc.reg_read(A.UC_ARM64_REG_PC) - self.base]
        fp = self.uc.reg_read(A.UC_ARM64_REG_X29)
        buf = ctypes.create_string_buffer(16)
        for _ in range(depth):
            if not fp or self._lib.fm_accel_peek(self._a, fp, buf, 16):
                break
            fp, lr = struct.unpack('<QQ', buf.raw)
            if not lr:
                break
            out.append(lr - 4 - self.base)
        return [f'{a:#x}' for a in out]

    def vm_stats(self) -> dict:
        st = self._st
        return {name: getattr(st, name) for name in (
            'fills', 'faults', 'new_pages', 'tlb_flushes', 'data_used', 'commits', 'restores',
            'pages_committed', 'pages_restored', 'blobs_live', 'declined', 'gen', 'nbase')} | {
                'generations': self.generations, 'pages_refreshed': self.pages_refreshed,
                'windows_read': self.windows_read}


__all__ = ['FastUiHandlerVM', 'FastBaseline', 'available', 'library_path', 'hash_pages', 'hash_masked',
           'FULL_MASK']
