"""FastVM: PropertyVM with the hot paths in C (`native/fm_vm_accel.c`).

Same trust model, same results and the same stop reasons as `vm.PropertyVM`; the differences
are mechanical (see docs/fmdb/PERFORMANCE.md):

* Unicorn runs in virtual-TLB mode over three host-memory areas that are mapped once: the
  code pool (plugin __TEXT, filled lazily from the verified on-disk image), the data pool
  (copied live pages) and the private ranges. PropertyVM maps every 4 KiB page on its own,
  and Unicorn's mapping cost grows with the number of regions (16 s for 3,000 regions).
* The per-basic-block instruction budget, the copy-on-write of live pages and the TLB fill
  run in C. Python is entered for a page that is not in a pool yet, for modelled external
  calls and for refusals.
* The per-call timeout is checked in the block hook (every 1,024 blocks) instead of by a
  timer thread per `emu_start`.
* Dropping the copied live pages (`invalidate`, `drop_live_pages`) keeps the instance and its
  translated code.

Differences that are visible: `Unavailable.detail` of a refused store or load names the
1 KiB block Unicorn asked for, not the exact byte (the reason text is unchanged), and
`CallStats.mutated_pages` counts pages stored to by emulated code or models.

`available()` is False when the library has not been built (`scripts/build_vm_accel.sh`);
callers then use PropertyVM.
"""
from __future__ import annotations

import ctypes
import os
import struct
import time
from pathlib import Path

from unicorn import Uc, UcError, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_BLOCK, UC_HOOK_CODE
from unicorn import unicorn_const as UCC
import unicorn.arm64_const as A
from unicorn.unicorn_py3 import unicorn as _ucpy

from .vm import (PropertyVM, CallStats, _Stop, PAGE, PRIVATE, PRIVATE_END, STACK, STACK_SIZE, HEAP,
                 HEAP_SIZE, TRAP, TLS, STATIC, STATIC_SIZE, NULL_LIMIT, EXTERNALS, _noop, _true, _preserve)

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = 'libfm_vm_accel.dylib'
LIBRARY_V2 = 'libfm_vm_accel2.dylib'    # version 2: read tracking (the same API plus fm_accel_touch_*)
CODE_PHYS = 0x2000_0000_0000        # "physical" bases of the pools (never guest-visible)
DATA_PHYS = 0x3000_0000_0000
PAD_PHYS = 0x3800_0000_0000
DATA_SLOTS = 1 << 17                # 512 MiB of address space, committed only when touched
LIVE_PAGE_LIMIT = 1 << 15           # drop_live_pages() threshold used by Engine (128 MiB)
WHY_UNMAPPED, WHY_FETCH_PROT, WHY_WRITE_CODE, WHY_WRITE_PROT = range(4)
STOP_BUDGET, STOP_TIMEOUT, STOP_STACK_PROBE, STOP_NON_PLUGIN = 1, 2, 3, 4
ACT_PYTHON, ACT_RETURN_0, ACT_RETURN_1, ACT_STACK_PROBE = range(4)
EXT_LOG_MAX = 4096
PEEK_MISSING, PEEK_CODE = 1, 2
MASK64 = (1 << 64) - 1
SP_START = STACK + STACK_SIZE - 0x1000
# Stop address: inside the trap page, because Unicorn also resolves the block before the stop
# address when a run ends and an unanswered TLB fill is an error in virtual-TLB mode.
STOP_AT = TRAP + 0x800

_FAULT = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_uint64, ctypes.c_int, ctypes.c_int)
_STUB = ctypes.CFUNCTYPE(None, ctypes.c_uint64)


class _State(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        'icount', 'budget', 'timeout_ticks', 'deadline', 'stop', 'pc', 'lr', 'sp', 'x0',
        'fills', 'faults', 'new_pages', 'tlb_flushes', 'blocks', 'data_used', 'data_slots', 'ndirty',
        'miss_addr', 'ext_n', 'pending_id', 'stop_addr')]


_lib = None


def library_path() -> Path:
    """`$FMDB_VM_ACCEL`, else version 2 of the accelerator when it is built, else version 1."""
    env = os.environ.get('FMDB_VM_ACCEL')
    if env:
        return Path(env)
    v2 = ROOT / 'build' / LIBRARY_V2
    return v2 if v2.is_file() else ROOT / 'build' / LIBRARY


def _load():
    global _lib
    if _lib is None:
        lib = ctypes.CDLL(str(library_path()))
        u64, ptr, c_int = ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int
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
        lib.fm_accel_set_action.argtypes = [ptr, ctypes.c_uint32, c_int]
        lib.fm_accel_set_import.argtypes = [ptr, u64, ctypes.c_uint32]
        lib.fm_accel_set_stubs.restype = ptr
        lib.fm_accel_set_stubs.argtypes = [ptr, u64, u64, ptr, u64, u64, _STUB, ptr]
        lib.fm_accel_ext_log.restype = ctypes.POINTER(ctypes.c_uint16)
        lib.fm_accel_ext_log.argtypes = [ptr]
        lib.tracks_reads = hasattr(lib, 'fm_accel_touch_dump')
        if lib.tracks_reads:
            lib.fm_accel_track.argtypes = [ptr, c_int]
            lib.fm_accel_touch_clear.argtypes = [ptr]
            lib.fm_accel_touch_count.restype = u64
            lib.fm_accel_touch_count.argtypes = [ptr]
            lib.fm_accel_touch_dump.restype = u64
            lib.fm_accel_touch_dump.argtypes = [ptr, ptr, u64]
            lib.fm_accel_touch_words.restype = ctypes.c_uint
            lib.fm_accel_words_hash.argtypes = [ctypes.c_char_p, ptr, ptr, u64, ptr]
        _lib = lib
    return _lib


def tracks_reads() -> bool:
    """True when the loaded accelerator can record which lines of live memory a call read."""
    return available() and bool(_load().tracks_reads)


def available() -> bool:
    """True when the accelerator library is built and loads (and FMDB_VM is not 'classic')."""
    if os.environ.get('FMDB_VM', '').lower() == 'classic':
        return False
    try:
        _load()
    except OSError:
        return False
    return True


def vm_class():
    """FastVM when the accelerator is available, else PropertyVM (same constructor)."""
    return FastVM if available() else PropertyVM


class _TextPages:
    """`page in vm.code_pages`: every page of the plugin __TEXT range is shipped code."""

    def __init__(self, lo, hi):
        self.lo, self.hi = lo, hi

    def __contains__(self, page):
        return self.lo <= page < self.hi


class _LivePages:
    """`len(vm.live_pages)` / `page in vm.live_pages` over the C page table."""

    def __init__(self, vm):
        self._vm = vm

    def __len__(self):
        return self._vm._st.data_used

    def __contains__(self, page):
        return self._vm._lib.fm_accel_has(self._vm._a, page) == 1


class FastVM(PropertyVM):
    # TrackingFastVM sets this: a memory-read hook is installed when the VM is created (Unicorn
    # decides at translation time whether loads call hooks), and `touch_begin` / `touch_end`
    # bracket the calls whose read set is wanted.
    track_reads = False

    def _init_uc(self):
        lib = self._lib = _load()
        self.uc = uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        uc.ctl_set_cpu_model(A.UC_CPU_ARM64_MAX)
        uc.ctl_set_tlb_mode(UCC.UC_TLB_VIRTUAL)
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
        self._fault_cb = _FAULT(self._on_fault)        # keep the callback alive
        self._a = a = lib.fm_accel_new(uc._uch, fns, regs, out_regs, flush_code, self.base, text_size,
                                       CODE_PHYS, DATA_PHYS, DATA_SLOTS, self._fault_cb)
        if not a:
            raise MemoryError('fm_vm_accel could not reserve its pools')
        self._st = st = a.contents
        st.budget = self.budget
        st.timeout_ticks = int(self.timeout_us * lib.fm_accel_ticks_per_second() / 1_000_000)
        uc.mem_map_ptr(CODE_PHYS, text_size, UCC.UC_PROT_READ | UCC.UC_PROT_EXEC, lib.fm_accel_code_host(a))
        uc.mem_map_ptr(DATA_PHYS, DATA_SLOTS * PAGE, UCC.UC_PROT_READ | UCC.UC_PROT_WRITE,
                       lib.fm_accel_data_host(a))
        self._private = {}
        rw, rx = UCC.UC_PROT_READ | UCC.UC_PROT_WRITE, UCC.UC_PROT_READ | UCC.UC_PROT_EXEC
        for start, size, perms in ((STACK, STACK_SIZE, rw), (HEAP, HEAP_SIZE, rw), (TLS, PAGE, rw),
                                   (STATIC, STATIC_SIZE, rw), (TRAP, PAGE, rx)):
            host = lib.fm_accel_add_range(a, start, size, perms)
            if not host:
                raise MemoryError('fm_vm_accel could not reserve a private range')
            uc.mem_map_ptr(start, size, perms, host)
            self._private[start] = host
        ctypes.memmove(self._private[TRAP], b'\xc0\x03\x5f\xd6' * (PAGE // 4), PAGE)
        self._heap_host = self._private[HEAP]
        self.code_pages = _TextPages(self.base, self.base + text_size)
        self.live_pages = _LivePages(self)
        self._regs = (ctypes.c_uint64 * 34)()
        self._zero29 = bytes(29 * 8)
        self._cb_error = None
        self._peek_buf = ctypes.create_string_buffer(1 << 16)
        self._peek_view = memoryview(self._peek_buf)
        self._u64 = ctypes.c_uint64()
        self._u64_ref = ctypes.byref(self._u64)
        self._hooks = []
        for kind, name, cfunc in ((UCC.UC_HOOK_TLB_FILL, 'fm_accel_tlb_fill', None), (UC_HOOK_BLOCK, 'fm_accel_block', None)):
            handle = ctypes.c_size_t()
            status = uclib.uc_hook_add(uc._uch, ctypes.byref(handle), kind,
                                       ctypes.cast(getattr(lib, name), ctypes.c_void_p),
                                       ctypes.cast(a, ctypes.c_void_p), ctypes.c_uint64(1), ctypes.c_uint64(0))
            if status:
                raise UcError(status)
            self._hooks.append(handle)
        self._py_block_hook = None
        # externals: ids for every import name; the constant models run in C
        names = sorted(set(self.image.stubs.values()) | set(self.image.binds.values()))
        self._ext_names = [None] + names
        self._ext_ids = {name: i for i, name in enumerate(self._ext_names) if name}
        native = {_noop: ACT_RETURN_0, _true: ACT_RETURN_1, _preserve: ACT_STACK_PROBE}
        for name, i in self._ext_ids.items():
            action = native.get(EXTERNALS.get(name), ACT_PYTHON)
            if action:
                lib.fm_accel_set_action(a, i, action)
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
            raise MemoryError('fm_vm_accel could not reserve the import page')
        uc.mem_map_ptr(PAD_PHYS, PAGE, UCC.UC_PROT_EXEC, pad)
        self._ext_log = lib.fm_accel_ext_log(a)
        handle = ctypes.c_size_t()
        status = uclib.uc_hook_add(uc._uch, ctypes.byref(handle), UC_HOOK_CODE,
                                   ctypes.cast(lib.fm_accel_stub, ctypes.c_void_p), ctypes.cast(a, ctypes.c_void_p),
                                   ctypes.c_uint64(self.stub_start), ctypes.c_uint64(self.stub_end - 1))
        if status:
            raise UcError(status)
        self._hooks.append(handle)
        self.touch_record = None
        if self.track_reads and lib.tracks_reads:
            for kind, name in ((UCC.UC_HOOK_MEM_READ, 'fm_accel_mem_read'),
                               (UCC.UC_HOOK_MEM_WRITE, 'fm_accel_mem_write')):
                handle = ctypes.c_size_t()
                status = uclib.uc_hook_add(uc._uch, ctypes.byref(handle), kind,
                                           ctypes.cast(getattr(lib, name), ctypes.c_void_p),
                                           ctypes.cast(a, ctypes.c_void_p), ctypes.c_uint64(1), ctypes.c_uint64(0))
                if status:
                    raise UcError(status)
                self._hooks.append(handle)
            self.touch_record = 1 + int(lib.fm_accel_touch_words())     # u64 per record: page, masks

    # ------------------------------------------------------------------ read tracking
    def touch_begin(self):
        """Start recording the 8-byte words of live memory that calls and `read` touch."""
        self._lib.fm_accel_touch_clear(self._a)
        self._lib.fm_accel_track(self._a, 1)

    def touch_end(self) -> bytes:
        """Stop recording. The read set since `touch_begin` as packed records of
        `touch_record` little-endian u64: the address of a copied 4 KiB live page, then its
        word masks (bit k of mask m: the 8 bytes at offset (64 m + k) * 8 were read)."""
        lib, a = self._lib, self._a
        lib.fm_accel_track(a, 0)
        n = int(lib.fm_accel_touch_count(a))
        if not n:
            return b''
        buf = (ctypes.c_uint64 * (self.touch_record * n))()
        n = int(lib.fm_accel_touch_dump(a, buf, n))
        lib.fm_accel_touch_clear(a)
        return bytes(buf)[:n * self.touch_record * 8]

    def close(self):
        """Close Unicorn, then release the host memory behind it."""
        a, self._a = getattr(self, '_a', None), None
        if not a:
            return
        finalizer = getattr(self.uc, '_Uc__finalizer', None)
        if finalizer is None:
            return                          # cannot prove Unicorn is closed: keep the memory
        finalizer()
        self._lib.fm_accel_free(a)

    def __del__(self):
        try:
            self.close()
        except Exception:  # noqa: BLE001 - interpreter shutdown
            pass

    # ------------------------------------------------------------------ memory
    def _fault_in(self, page):
        lib, a = self._lib, self._a
        if lib.fm_accel_has(a, page):
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
        try:
            data = self.reader.read(page, PAGE)
        except Exception as exc:  # noqa: BLE001 - any reader refusal is a fault
            self.unreadable.add(page)
            raise _Stop('unreadable live memory', f'{page:#x}: {exc}') from None
        if lib.fm_accel_add_data(a, page, data) == -1:
            raise _Stop('VM live page pool exhausted', str(DATA_SLOTS))
        if self._call is not None:
            self._call.new_pages += 1

    def _on_fault(self, vaddr, access, why):
        """TLB miss the pools could not answer. True: the page is there now; False: stop."""
        try:
            page = vaddr & ~(PAGE - 1)
            if why == WHY_WRITE_CODE:
                raise _Stop('write to shipped code', hex(vaddr))
            if why == WHY_WRITE_PROT:
                raise _Stop('write to protected memory', hex(vaddr))
            if access == UCC.UC_MEM_FETCH:
                # the hook names the block Unicorn asked for (pointer tag removed); PC has the low bits
                address = page | (self.uc.reg_read(A.UC_ARM64_REG_PC) & (PAGE - 1))
                if why == WHY_UNMAPPED and self.base <= address < self.text_end:
                    self._fault_in(address & ~(PAGE - 1))
                    return True
                return self._external_jump(self.uc, address)
            self._fault_in(page)
            return True
        except _Stop as stop:
            if self._stop is None:
                self._stop = stop
            return False
        except BaseException as exc:  # noqa: BLE001 - never unwind through C
            if self._cb_error is None:
                self._cb_error = exc
            return False

    def _on_stub_address(self, address):
        """A plugin stub whose model is in Python (the C hook handled the constant ones)."""
        try:
            self._on_stub(self.uc, address, 4, None)
        except BaseException as exc:  # noqa: BLE001 - never unwind through C
            if self._cb_error is None:
                self._cb_error = exc
            self.uc.emu_stop()

    def _drain_externals(self):
        """Move the external calls C handled since the last drain into the per-call list and the
        session counter, in call order."""
        st = self._st
        n = st.ext_n
        if n:
            names = self._ext_names
            done = [names[i] for i in self._ext_log[:n]]
            st.ext_n = 0
            self.stubbed.update(done)
            if self._call is not None:
                self._call.externals.extend(done)

    def _external(self, name):
        self._drain_externals()
        super()._external(name)

    def _live_import(self, address):
        if self.live_imports is None:
            super()._live_import(address)                       # builds self.live_imports
            lib, a, ids = self._lib, self._a, self._ext_ids
            lib.fm_accel_clear_imports(a)
            for bound, name in self.live_imports.items():
                lib.fm_accel_set_import(a, bound, ids[name])
        return self.live_imports.get(address)

    def _external_jump(self, uc, address):
        name = self._live_import(address)
        if name is None:
            if self._stop is None:
                self._stop = _Stop('call into non-plugin code', hex(address))
            return False
        self._pending = name
        return False

    def _fail(self, uc, reason, detail=None):
        if self._stop is None:
            self._stop = _Stop(reason, detail)
        uc.emu_stop()
        return False

    def read(self, address: int, length: int) -> bytes:
        if length <= 0:
            return b''
        buf = self._peek_buf if length <= 1 << 16 else ctypes.create_string_buffer(length)
        lib, a = self._lib, self._a
        while lib.fm_accel_peek(a, address, buf, length):
            missing = self._st.miss_addr
            if PRIVATE <= missing < PRIVATE_END:
                raise UcError(UCC.UC_ERR_READ_UNMAPPED)      # as uc.mem_read in PropertyVM.read
            self._fault_in(missing & ~(PAGE - 1))
        return bytes(self._peek_view[:length]) if buf is self._peek_buf else buf.raw

    def read_u64(self, address):
        lib, a = self._lib, self._a
        while lib.fm_accel_peek(a, address, self._u64_ref, 8):
            missing = self._st.miss_addr
            if PRIVATE <= missing < PRIVATE_END:
                raise UcError(UCC.UC_ERR_READ_UNMAPPED)
            self._fault_in(missing & ~(PAGE - 1))
        return self._u64.value

    def _store(self, address, data, copy_on_write):
        lib, a = self._lib, self._a
        data = bytes(data)
        while True:
            status = lib.fm_accel_poke(a, address, data, len(data), copy_on_write)
            if not status:
                return
            missing = self._st.miss_addr
            if status == PEEK_CODE:
                raise _Stop('write to shipped code', hex(missing & ~(PAGE - 1)))
            if PRIVATE <= missing < PRIVATE_END:
                raise UcError(UCC.UC_ERR_WRITE_UNMAPPED)     # as uc.mem_write in PropertyVM.write
            self._fault_in(missing & ~(PAGE - 1))

    def write(self, address: int, data: bytes):
        if data:
            self._store(address, data, 1)

    def _poke(self, address: int, data: bytes):
        self._store(address, data, 0)

    def set_overlay(self, address: int, data: bytes):
        self.ensure(address, len(data))
        for page in range(address & ~(PAGE - 1), address + len(data), PAGE):
            if page in self.code_pages:
                raise ValueError('Overlays may not touch shipped code')
        self._poke(address, data)
        self.overlays[address] = data

    def _static(self, data: bytes, align=16):
        top = (self.static_top + align - 1) & ~(align - 1)
        if top + len(data) > STATIC + STATIC_SIZE:
            raise ValueError('VM static area exhausted')
        self._poke(top, data)
        self.static_top = top + len(data)
        return top

    def _make_dirty(self, page):      # copy-on-write lives in C
        pass

    def _restore(self):
        self._lib.fm_accel_restore(self._a)
        used = self.heap_top - HEAP
        if used:
            ctypes.memset(self._heap_host, 0, used)
        self.heap_top = HEAP
        if self.allocations:
            self.allocations.clear()
        self._tlv_block = None

    def settle(self):
        """Undo the stores of the last call now (they are otherwise undone when the next call
        starts), so `read` returns the copied bytes of live pages as the game had them."""
        self._restore()

    def drop_live_pages(self):
        """Forget the copied live pages without starting a new session (same snapshot source:
        pages come back from the reader's cache on the next touch). Overlays are re-applied."""
        self._restore()
        self._lib.fm_accel_reset_data(self._a)
        self.unreadable.clear()         # as a new PropertyVM: a page refused once is asked for again
        for address, data in self.overlays.items():
            if not (PRIVATE <= address < PRIVATE_END):
                self._poke(address, data)

    def invalidate(self):
        """Forget every cached live page (start a new snapshot)."""
        self._restore()
        self._lib.fm_accel_reset_data(self._a)
        self.unreadable.clear()
        self.live_imports = None
        self._lib.fm_accel_clear_imports(self._a)
        self._typeinfo_vtables = None
        self._rtti.clear()
        self.overlays.clear()
        self.static_top = STATIC
        self._session_setup()

    # ------------------------------------------------------------------ calls
    def call(self, address: int, args=(), *, fargs=()):
        st, lib, a = self._st, self._lib, self._a
        self._restore()
        self._stop = self._pending = self._cb_error = None
        st.icount = 0
        st.stop = 0
        st.ext_n = 0
        st.pending_id = 0
        st.budget = self.budget
        if self.block_trace is not None and self._py_block_hook is None:
            self._py_block_hook = self.uc.hook_add(UC_HOOK_BLOCK, lambda uc, addr, size, user:
                                                   self.block_trace is not None and self.block_trace.append(addr))
        stats = self._call = self.last_stats = CallStats()
        started = time.perf_counter()
        regs = self._regs
        ctypes.memmove(regs, self._zero29, 29 * 8)
        for i, value in enumerate(args):
            regs[i] = value & MASK64
        regs[29] = 0
        regs[30] = STOP_AT
        regs[31] = SP_START
        regs[32] = TLS
        regs[33] = TLS
        lib.fm_accel_set_regs(a, regs)
        for i, value in enumerate(fargs):
            self.uc.reg_write(getattr(A, f'UC_ARM64_REG_D{i}'), struct.unpack('<Q', struct.pack('<d', value))[0])
        pc = address
        try:
            while True:
                err = lib.fm_accel_run(a, pc, STOP_AT)
                if self._cb_error is not None:
                    raise self._cb_error
                if st.ext_n:
                    self._drain_externals()
                if self._stop is None and st.stop:
                    if st.stop == STOP_BUDGET:
                        self._stop = _Stop('instruction budget exceeded', str(self.budget))
                    elif st.stop == STOP_STACK_PROBE:
                        self._stop = _Stop('stack frame larger than the VM stack', str(st.stop_addr))
                    elif st.stop == STOP_NON_PLUGIN:
                        self._stop = _Stop('call into non-plugin code', hex(st.stop_addr))
                if self._stop is not None:
                    raise self._stop
                if st.pending_id:
                    self._pending, st.pending_id = self._ext_names[st.pending_id], 0
                if err and self._pending is None:
                    raise _Stop(f'cpu fault: {UcError(err)}', f'pc={st.pc - self.base:#x}')
                if self._pending is not None:
                    name, self._pending = self._pending, None
                    self._external(name)
                    if self._stop is not None:
                        raise self._stop
                    pc = self.uc.reg_read(A.UC_ARM64_REG_LR)
                    continue
                pc = st.pc
                if pc != STOP_AT:
                    raise _Stop('emulation stopped early (timeout)', f'pc={pc - self.base:#x}')
                break
            if st.sp != SP_START:
                raise _Stop('callee did not restore SP')
            result = st.x0
        finally:
            stats.instructions = self._icount = st.icount
            stats.mutated_pages = st.ndirty
            stats.seconds = time.perf_counter() - started
            self._call = None
        stats.returned = result
        return result, stats


class TrackingFastVM(FastVM):
    """FastVM whose loads go through the read-tracking hook (needs accelerator version 2).
    Results are the same as FastVM's; every emulated load takes Unicorn's slow path."""
    track_reads = True


def words_hash(buffer: bytes, offsets, records: bytes) -> list:
    """Hash of the marked words of each page: `records` as `touch_end` returns them, `offsets[i]`
    the offset in `buffer` of record i's 4 KiB page (None: not available, hash 0)."""
    lib = _load()
    width = 1 + int(lib.fm_accel_touch_words())
    n = len(records) // (8 * width)
    if not n:
        return []
    offs = (ctypes.c_uint64 * n)(*[MASK64 if o is None else o for o in offsets])
    recs = (ctypes.c_uint64 * (n * width)).from_buffer_copy(records)
    out = (ctypes.c_uint64 * n)()
    lib.fm_accel_words_hash(buffer, offs, recs, n, out)
    return list(out)
