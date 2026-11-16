"""Recording output stream for the game's own save code, emulated on copied live memory.

docs/fmdb/PERSIST.md has the whole route. In short: SAVE_SYSTEM (vtable 0x55F4AC8) slot function
0x2583DCC calls the save walker 0x256D728, which hands every manager singleton to that manager's
own save function `save(manager, holder)`; `holder` is a cell that points at an archive item
(`siapplication::ARCHIVE_ITEM`, vtable 0x5694CE0). Save code opens named child items through the
item's virtual +0xE8, opens a writer for an item with 0x4319C00 (tag, &item, version, mode) and
writes every value through the writer's virtual +0x30 `write(this, buffer, length)`; after each
write it tests the error word at writer +0x10. Nothing else of the stream is needed.

`SaveRecorderVM` is a `vm.PropertyVM` that answers those calls itself:

* the archive item and the writer are VM-private objects whose virtual functions point into a
  VM-private page of `ret` instructions; a code hook on that page runs the model of the slot
  (child item, writer position, write). A slot without a model stops the call with
  `save stream: <object> slot N not modelled` (docs/fmdb/REFUSALS.md "Save stream").
* 0x4319C00 is answered by the model (a recording writer bound to the item) instead of the
  shipped code, which would wrap the item's file stream; this is the only shipped function that
  is replaced, and it only builds stream objects.
* every write is kept in order: writer, offset in that writer, length, bytes, the return
  addresses on the frame-pointer chain (which save function wrote it) and the provenance of the
  bytes: the live address they were loaded from when the bytes were stored to the buffer by a
  store whose value equals a recent load (`exact` when the load ran in the function that stored
  the value, `callee` when the load ran in a function it called), the address itself when the
  buffer is live memory, else `computed`.

Writes stay inside the VM (copy-on-write); file and network calls are refused by PropertyVM, so
the emulated save cannot touch a file.
"""
from __future__ import annotations

import bisect
from collections import deque
from dataclasses import dataclass, field
import ctypes
import struct

from unicorn import UC_HOOK_BLOCK, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_PROT_READ, UC_PROT_EXEC
from unicorn import unicorn_const as UCC
import unicorn.arm64_const as A

from .vm import FILE_EXTERNALS, PropertyVM, _Stop, PRIVATE, PRIVATE_END, STACK, STACK_SIZE, HEAP, HEAP_SIZE, NULL_LIMIT, PAGE, _cstr
from . import fastvm

HOOKS = PRIVATE + 0x2100_0000           # VM-private page of `ret` instructions (model entry points)
ITEM_VT_CODE = HOOKS                    # archive item slots: HOOKS + 4 k
STREAM_VT_CODE = HOOKS + 0x400          # writer slots: HOOKS + 0x400 + 4 k
ITEM_SLOTS, STREAM_SLOTS = 64, 32
OPEN_WRITER_RVA = 0x4319C00             # (tag*, ITEM_REF*, version, mode) -> x8: OUTPUT_STREAM ref
STRING_FROM_CSTR_RVA = 0x4388EF8        # sicore string from a C string: the chunk names are literals
ITEM_SIZE, STREAM_SIZE = 0x80, 0x80
MODELLED = frozenset((OPEN_WRITER_RVA,))    # answered by the recorder: never a save function
REFCOUNT = 1 << 30                      # never reaches the release branch
ERROR_WORD = 0x10                       # writer +0x10: nonzero after a failed write
LOAD_WINDOW = 1 << 15                   # loads kept for provenance
MATCH_DISTANCE = 4096                   # a store's source load is at most this many loads earlier
MASK64 = (1 << 64) - 1
BIG_HEAP = PRIVATE + 0x2200_0000        # second VM heap for long saves (frees are no-ops in the VM)
BIG_HEAP_SIZE = 0x0C00_0000             # 192 MiB, below TLS (PRIVATE + 0x3000_0000)
NO_PARTS = ()                           # provenance off: the bytes come from Write.buffer
TEMPORARY_ARCHIVES = ('.obs',)         # Temporary/<name>.obs archive files the save copies
RET_PAGE = b'\xc0\x03\x5f\xd6' * (PAGE // 4)

ITEM_SLOT_NAMES = {1: 'release', 29: 'child'}
STREAM_SLOT_NAMES = {0: 'destroy', 1: 'release', 2: 'size', 3: 'position', 4: 'seek', 5: 'flags',
                     6: 'write'}


# Host file-system entry points the save code must never reach inside the recorder, even read-only:
# a save writes, so any file call here is the save system's own file handling, not data.
SAVE_REFUSED = {name: 'file-system call inside the emulated save' for name in (
    '_fopen', '_open', '_mkdir', '_opendir', '_readdir', '_stat', '_access', '_rename', '_unlink', '_remove',
    '_fwrite', '_write', '_pwrite', '_ftruncate', '_fsync')}


@dataclass(slots=True)
class Write:
    seq: int
    stream: int                 # writer id
    offset: int                 # byte offset in that writer
    data: bytes
    frames: tuple               # return-address RVAs, innermost first (frames[0]: the caller of write)
    parts: list                 # [(start, length, kind, live address | None, load pc RVA | None, store pc RVA | None)]
    call: int | None = None     # innermost Call active at the write
    buffer: int = 0             # address of the bytes handed to write()


@dataclass(slots=True)
class Call:
    """A function entered with a recorder item/writer in x1 or x2: save(x0, ...)."""
    id: int
    function: int               # RVA
    obj: int                    # x0 at entry
    arg: int                    # 1 or 2: which argument held the recorder object
    target: str                 # 'item' | 'stream'
    target_id: int
    sp: int
    parent: int | None
    site: int                   # return address RVA (the call site + 4)
    seq: int = 0                # order among writes and calls


@dataclass
class Stream:
    id: int
    item: int                   # item id
    tag: bytes                  # the 8-byte tag record handed to 0x4319C00
    version: int
    mode: int
    size: int = 0
    writes: list = field(default_factory=list)


@dataclass
class Item:
    id: int
    parent: int | None
    name: str | None
    address: int


class _Recorder:
    """The recording archive (see module docstring), mixed into PropertyVM or FastVM."""
    provenance = False
    max_writes = None           # stop the save after this many writes (memory bound for whole-database roots)

    def __init__(self, reader, base, image, *, function_starts=(), provenance=None, **kwargs):
        self.function_starts = function_starts
        if provenance is not None:
            self.provenance = bool(provenance)
        kwargs.setdefault('file_resolver', False)
        super().__init__(reader, base, image, **kwargs)

    def _map_hook_page(self):
        raise NotImplementedError

    def _init_uc(self):
        super()._init_uc()
        uc = self.uc
        self._map_hook_page()
        uc.hook_add(UC_HOOK_CODE, self._on_model, begin=HOOKS, end=HOOKS + PAGE - 1)
        for rva in (OPEN_WRITER_RVA, STRING_FROM_CSTR_RVA):
            uc.hook_add(UC_HOOK_CODE, self._on_plugin_hook, begin=self.base + rva, end=self.base + rva)
        # Load/store provenance hooks (a Python call per load and store of live memory, several times
        # slower) are installed only with provenance=True: Unicorn decides at translation time.
        if self.provenance:
            lo, hi = self._read_hook_range()
            uc.hook_add(UC_HOOK_MEM_READ, self._on_read, begin=lo, end=hi)
            uc.hook_add(UC_HOOK_MEM_WRITE, self._on_store, begin=PRIVATE, end=PRIVATE_END - 1)
        self.tracking = False
        self._load_forms = {}
        self._starts = frozenset(self.function_starts)
        self._reset_recording()

    def _entry(self, uc, address):
        """A function entered with a recorder object (or a cell holding one) in x1 or x2 is a save
        function of the object in x0: kept as a Call, nested by stack pointer."""
        for arg, reg in ((1, A.UC_ARM64_REG_X1), (2, A.UC_ARM64_REG_X2)):
            v = uc.reg_read(reg)
            target = self._stream_at.get(v) or self._item_at.get(v)
            if target is None and (HEAP <= v < HEAP + HEAP_SIZE - 8 or STACK <= v < STACK + STACK_SIZE - 8):
                cell = struct.unpack('<Q', self.read(v, 8))[0]
                target = self._stream_at.get(cell) or self._item_at.get(cell)
            if target is not None:
                break
        else:
            return
        sp = uc.reg_read(A.UC_ARM64_REG_SP)
        stack = self._active
        while stack and stack[-1].sp <= sp:
            stack.pop()
        self.seq += 1
        call = Call(len(self.calls), address - self.base, uc.reg_read(A.UC_ARM64_REG_X0), arg,
                    'stream' if isinstance(target, Stream) else 'item', target.id, sp,
                    stack[-1].id if stack else None, uc.reg_read(A.UC_ARM64_REG_LR) - self.base, self.seq)
        self.calls.append(call)
        stack.append(call)

    def _current_call(self):
        sp = self.uc.reg_read(A.UC_ARM64_REG_SP)
        stack = self._active
        # a save function that called write() has a frame: below its entry SP while it runs; a
        # write at its entry SP is its caller's, after it returned
        while stack and stack[-1].sp <= sp:
            stack.pop()
        return stack[-1].id if stack else None

    def _external(self, name):
        if name in SAVE_REFUSED:
            self.refused[name] += 1
            raise _Stop(f'save stream: {SAVE_REFUSED[name]}', name)
        if name in FILE_EXTERNALS and self.file_resolver is not None and self._temporary_archive(name):
            return
        if name == '_mach_absolute_time':
            # progress timing of long saves: a VM-private clock from the instruction count (marked)
            self.stubbed[name] += 1
            self.marked['host clock: instruction count'] += 1
            self._ret(self._instructions() * 16)
            return
        super()._external(name)

    def _temporary_archive(self, name):
        """Save code copies the game's archive files (`Temporary/*.obs`: retired-person history,
        news archive pages, season summaries) into the save through the FILE* the game holds open.
        The recorder reads them read-only with the same stdio models vm.py uses for `.fmf` and
        `Temporary/*_dt.cmt`; any other file keeps vm.py's refusal. True when handled here."""
        from . import ui_vm
        stream = self._x(3) if name == '_fread' else self._x(0)
        fd = struct.unpack('<h', self.read(stream + 0x12, 2))[0]
        if fd in (getattr(self, '_vm_files', None) or {}):
            return False
        path = self.file_resolver(fd)
        if not path or '/Temporary/' not in str(path) or not str(path).endswith(TEMPORARY_ARCHIVES):
            return False
        inner = {'_fseeko': ui_vm._fseeko, '_fseek': ui_vm._fseeko, '_ftello': ui_vm._ftello,
                 '_ftell': ui_vm._ftello, '_fread': ui_vm._fread, '_ferror': ui_vm._ferror}[name]
        self.stubbed[name] += 1
        self.files_read.add(str(path))
        inner(self)
        return True

    def _session_setup(self):
        super()._session_setup()
        # vtables: 16-byte header (no typeinfo) + slots, in the session's static area
        self.item_vtable = self._static(bytes(16) + b''.join(
            struct.pack('<Q', ITEM_VT_CODE + 4 * k) for k in range(ITEM_SLOTS))) + 16
        self.stream_vtable = self._static(bytes(16) + b''.join(
            struct.pack('<Q', STREAM_VT_CODE + 4 * k) for k in range(STREAM_SLOTS))) + 16

    def _reset_recording(self):
        self.loads = deque(maxlen=LOAD_WINDOW)
        self.stores = {}
        self.seq = 0
        self.items, self.streams = [], []
        self._item_at, self._stream_at = {}, {}
        self.writes = []
        self.calls, self._active = [], []
        self._frame_pool = {}
        self.names = deque(maxlen=8)        # recent C-string literals turned into sicore strings
        self.model_calls = {}

    # ------------------------------------------------------------------ objects
    def _new_item(self, parent, name):
        address = self.alloc(ITEM_SIZE)
        self._poke(address, struct.pack('<QI', self.item_vtable, REFCOUNT))
        item = Item(len(self.items), parent, name, address)
        self.items.append(item)
        self._item_at[address] = item
        return item

    def _new_stream(self, item, tag, version, mode):
        address = self.alloc(STREAM_SIZE)
        self._poke(address, struct.pack('<QI', self.stream_vtable, REFCOUNT))
        stream = Stream(len(self.streams), item, tag, version, mode)
        self.streams.append(stream)
        self._stream_at[address] = stream
        return stream, address

    # ------------------------------------------------------------------ hooks
    def _read_hook_range(self):
        return NULL_LIMIT, PRIVATE - 1

    def _guest(self, uc, address, pc):
        return address

    def _on_read(self, uc, access, address, size, value, user):
        if self.tracking:
            pc = uc.reg_read(A.UC_ARM64_REG_PC)
            guest = self._guest(uc, address, pc)
            if guest is not None:
                self.seq += 1
                self.loads.append((self.seq, guest, size, pc))

    def _on_store(self, uc, access, address, size, value, user):
        if self.tracking:
            self.seq += 1
            if len(self.stores) > 1_000_000:
                self.stores.clear()
            self.stores[address] = (self.seq, size, value & MASK64, uc.reg_read(A.UC_ARM64_REG_PC))

    def _on_plugin_hook(self, uc, address, size, user):
        rva = address - self.base
        try:
            if rva == STRING_FROM_CSTR_RVA:
                try:
                    text = _cstr(self, self._x(1), 256) if self._x(1) >= NULL_LIMIT else None
                except _Stop:
                    text = None
                if text is not None:
                    self.names.append(text.decode('latin-1'))
                return          # the shipped function runs on
            if rva == OPEN_WRITER_RVA:
                self._open_writer()
                uc.reg_write(A.UC_ARM64_REG_PC, uc.reg_read(A.UC_ARM64_REG_LR))
        except _Stop as stop:
            self._fail(uc, stop.reason, stop.detail)

    def _open_writer(self):
        tag_ptr, ref, version, mode, out = self._x(0), self._x(1), self._x(2), self._x(3), self._x(8)
        tag = self.read(tag_ptr, 8)
        item_address = self.read_u64(ref)
        item = self._item_at.get(item_address)
        if item is None:
            raise _Stop('save stream: writer opened on an item the recorder did not create', hex(item_address))
        _, address = self._new_stream(item.id, tag, version & 0xFFFFFFFF, mode & 0xFFFFFFFF)
        self.write(out, struct.pack('<Q', address))
        self._ret(out)

    def _on_model(self, uc, address, size, user):
        try:
            off = address - HOOKS
            if off < 0x400:
                self._item_slot(off // 4)
            else:
                self._stream_slot((off - 0x400) // 4)
        except _Stop as stop:
            self._fail(uc, stop.reason, stop.detail)

    def _item_slot(self, slot):
        this = self._x(0)
        item = self._item_at.get(this)
        key = ('item', slot)
        self.model_calls[key] = self.model_calls.get(key, 0) + 1
        if item is None:
            raise _Stop('save stream: item slot called on an unknown object', hex(this))
        if slot == 1:
            return
        if slot == 29:          # child(this, key*, name string*, x8 out)
            name = self.names[-1] if self.names else None
            child = self._new_item(item.id, name)
            self.write(self._x(8), struct.pack('<Q', child.address))
            return
        raise _Stop(f'save stream: archive item slot {slot} (+{8 * slot:#x}) not modelled', hex(slot))

    def _stream_slot(self, slot):
        this = self._x(0)
        stream = self._stream_at.get(this)
        key = ('stream', slot)
        self.model_calls[key] = self.model_calls.get(key, 0) + 1
        if stream is None:
            raise _Stop('save stream: writer slot called on an unknown object', hex(this))
        if slot in (0, 1):
            return
        if slot in (2, 3):
            self._ret(stream.size)
            return
        if slot == 5:
            self._ret(0)
            return
        if slot == 4:           # seek: only to the current end
            target = self._x(1)
            if target != stream.size:
                raise _Stop('save stream: writer seek away from the end', f'{target} != {stream.size}')
            self._ret(1)
            return
        if slot == 6:
            buffer, length = self._x(1), self._x(2)
            if length > 1 << 26:
                raise _Stop('save stream: write longer than 64 MiB', str(length))
            if self.max_writes is not None and len(self.writes) >= self.max_writes:
                raise _Stop('save stream: write cap reached (the recording holds the first part of the save)',
                            str(self.max_writes))
            data = self.read(buffer, length) if length else b''
            self.seq += 1
            w = Write(self.seq, stream.id, stream.size, data, self._frames(),
                      self._provenance(buffer, data) if self.provenance else NO_PARTS,
                      self._current_call(), buffer)
            stream.writes.append(w)
            self.writes.append(w)
            stream.size += length
            self._ret(length)
            return
        raise _Stop(f'save stream: writer slot {slot} (+{8 * slot:#x}) not modelled', hex(slot))

    # ------------------------------------------------------------------ provenance
    def _frames(self, limit=48):
        rvas = [self.uc.reg_read(A.UC_ARM64_REG_LR) - self.base]
        fp = self.uc.reg_read(A.UC_ARM64_REG_X29)
        for _ in range(limit):
            if not STACK <= fp < STACK + STACK_SIZE:
                break
            prev, lr = struct.unpack('<QQ', self.read(fp, 16))
            lr &= (1 << 47) - 1
            if lr < self.base or lr >= self.text_end:
                break
            rvas.append(lr - self.base)
            if prev <= fp:
                break
            fp = prev
        rvas = tuple(rvas)
        return self._frame_pool.setdefault(rvas, rvas)       # many writes share one call chain

    @staticmethod
    def _live_only(buffer, data):
        if data and not PRIVATE <= buffer < PRIVATE_END:
            return [(0, len(data), 'live', buffer, None, None)]
        return [(0, len(data), 'vm', None, None, None)] if data else []

    def _provenance(self, buffer, data):
        n = len(data)
        if not n:
            return []
        if not PRIVATE <= buffer < PRIVATE_END:
            return [(0, n, 'live', buffer, None, None)]
        parts, at = [], 0
        while at < n:
            st = self.stores.get(buffer + at)
            if st is None:
                parts.append((at, n - at, 'unknown', None, None, None))
                break
            seq, size, value, pc = st
            size = min(size, n - at)
            value &= (1 << (8 * size)) - 1
            parts.append(self._match(at, size, value, seq, pc))
            at += size
        return parts

    def _match(self, at, size, value, store_seq, store_pc):
        store_rva = store_pc - self.base
        for seq, address, width, pc in reversed(self.loads):
            if seq > store_seq:
                continue
            if store_seq - seq > MATCH_DISTANCE:
                break
            try:
                raw = self.read(address, width)
            except _Stop:
                continue
            for k in range(0, width, max(1, min(width, size))) if width > size else (0,):
                piece = raw[k:k + min(width, size)] if width > size else raw
                if int.from_bytes(piece, 'little') == value and (value or width == size):
                    return (at, size, 'load', address + k, pc - self.base, store_rva)
        return (at, size, 'computed', None, None, store_rva)

    # ------------------------------------------------------------------ run
    def run(self, function_rva: int, obj: int, *, extra_args=(), holder_only=False):
        """Run `save(obj, holder)` at plugin RVA `function_rva` against a recording root item
        (`save(holder)` with holder_only: a static save function that loads its manager itself; the
        root Call then carries `obj`). Returns (x0, CallStats); raises _Stop with the refusal reason."""
        self._restore()
        self._reset_recording()
        root = self._new_item(None, None)
        holder = self.alloc(16)
        self._poke(holder, struct.pack('<Q', root.address))
        if holder_only:
            call = Call(0, function_rva, obj, 0, 'item', root.id, PRIVATE_END, None, 0, 0)
            self.calls.append(call)
            self._active.append(call)
        self.tracking = True
        try:
            args = (holder,) if holder_only else (obj, holder)
            return self.call(self.base + function_rva, args + tuple(extra_args))
        finally:
            self.tracking = False

    def _restore(self):
        # call() restores pages and the heap first; the recording objects live on the VM heap,
        # so run() allocates them after its own restore and call() must not wipe them.
        if getattr(self, '_keep_heap', False):
            return
        super()._restore()
        used = getattr(self, 'big_top', BIG_HEAP) - BIG_HEAP
        if used:
            self._zero_big_heap(used)
        self.big_top = BIG_HEAP

    def alloc(self, size, align=16):
        """The VM heap, then a second VM-private heap: a save allocates far more than a getter."""
        try:
            return super().alloc(size, align)
        except _Stop:
            size = max(int(size), 1)
            top = (getattr(self, 'big_top', BIG_HEAP) + align - 1) & ~(align - 1)
            if top + size > BIG_HEAP + BIG_HEAP_SIZE:
                raise _Stop('VM heap exhausted', f'{size} (both VM heaps, {(HEAP_SIZE + BIG_HEAP_SIZE) >> 20} MiB)')
            self.big_top = top + size
            self.allocations[top] = size
            return top

    def call(self, address, args=(), *, fargs=()):
        self._keep_heap = True
        try:
            return super().call(address, args, fargs=fargs)
        finally:
            self._keep_heap = False


class SaveRecorderClassicVM(_Recorder, PropertyVM):
    """Recorder on PropertyVM with load/store provenance hooks (slow: for samples)."""
    provenance = True

    def _map_hook_page(self):
        self.uc.mem_map(HOOKS, PAGE, UC_PROT_READ | UC_PROT_EXEC)
        self.uc.mem_write(HOOKS, RET_PAGE)
        self.uc.mem_map(BIG_HEAP, BIG_HEAP_SIZE, UC_PROT_READ | UC_PROT_WRITE)

    def _zero_big_heap(self, used):
        self.uc.mem_write(BIG_HEAP, bytes(used))

    def _on_block(self, uc, address, size, user):
        super()._on_block(uc, address, size, user)
        if self.tracking and address - self.base in self._starts and address - self.base not in MODELLED:
            self._entry(uc, address)

    def _instructions(self):
        return self._icount


class SaveRecorderVM(_Recorder, fastvm.FastVM):
    """Recorder on FastVM (pools, C budget and copy-on-write); a Python block hook only for the
    entry check of save functions."""

    def _map_hook_page(self):
        rx = UCC.UC_PROT_READ | UCC.UC_PROT_EXEC
        host = self._lib.fm_accel_add_range(self._a, HOOKS, PAGE, rx)
        if not host:
            raise MemoryError('fm_vm_accel could not reserve the recorder page')
        self.uc.mem_map_ptr(HOOKS, PAGE, rx, host)
        ctypes.memmove(host, RET_PAGE, PAGE)
        self._private[HOOKS] = host
        rw = UCC.UC_PROT_READ | UCC.UC_PROT_WRITE
        big = self._lib.fm_accel_add_range(self._a, BIG_HEAP, BIG_HEAP_SIZE, rw)
        if not big:
            raise MemoryError('fm_vm_accel could not reserve the recorder heap')
        self.uc.mem_map_ptr(BIG_HEAP, BIG_HEAP_SIZE, rw, big)
        self._private[BIG_HEAP] = big
        self.uc.hook_add(UC_HOOK_BLOCK, self._on_py_block)

    def _read_hook_range(self):
        # virtual-TLB mode: hooks see the pool ("physical") address; live pages sit in the data pool
        return fastvm.DATA_PHYS, fastvm.DATA_PHYS + fastvm.DATA_SLOTS * PAGE - 1

    def _guest(self, uc, address, pc):
        """The guest address of a load from its pool address: the page offset is the same, the
        page comes from the load instruction's base register (decoded once per pc)."""
        form = self._load_forms.get(pc)
        if form is None:
            form = self._load_forms[pc] = _load_form(self.image, pc - self.base)
        if not form:
            return None
        kind, rn, rm, imm, shift = form
        if rn == 31:
            return None                             # stack (VM-private)
        base = uc.reg_read(_XREG[rn])
        if kind == 'imm':
            cands = (base + imm, base)
        elif kind == 'post':
            cands = (base, base + imm)
        elif kind == 'reg':
            cands = (base + ((uc.reg_read(_XREG[rm]) & MASK64) << shift), base)
        else:
            cands = (base,)
        low = address & (PAGE - 1)
        for c in cands:
            for d in (0, 4, 8):                     # second register of a load pair
                if ((c + d) & (PAGE - 1)) == low:
                    return (c + d) & MASK64
        return None

    def _zero_big_heap(self, used):
        ctypes.memset(self._private[BIG_HEAP], 0, used)

    def _on_py_block(self, uc, address, size, user):
        if self.tracking and address - self.base in self._starts and address - self.base not in MODELLED:
            try:
                self._entry(uc, address)
            except BaseException as exc:  # noqa: BLE001 - never unwind through C
                self._fail(uc, 'save stream: recorder error', repr(exc)[:200])

    def _instructions(self):
        return self._st.icount


_XREG = [getattr(A, f'UC_ARM64_REG_X{i}') for i in range(29)] + [A.UC_ARM64_REG_X29, A.UC_ARM64_REG_X30]


def _load_form(image, rva):
    """(kind, Rn, Rm, imm, shift) of an ARM64 load at `rva`, or () when not decoded."""
    try:
        w = struct.unpack('<I', image.file_bytes(rva, 4))[0]
    except Exception:  # noqa: BLE001 - outside the image
        return ()
    rn = (w >> 5) & 31
    size = w >> 30
    if w & 0x3B000000 == 0x39000000:                        # LDR/STR (unsigned immediate)
        return ('imm', rn, 0, ((w >> 10) & 0xFFF) << size, 0)
    if w & 0x3B200000 == 0x38000000:                        # unscaled / pre / post / unprivileged
        imm = (w >> 12) & 0x1FF
        imm -= (1 << 9) if imm & 0x100 else 0
        mode = (w >> 10) & 3
        return ('post' if mode == 1 else 'imm', rn, 0, imm, 0)
    if w & 0x3B200C00 == 0x38200800:                        # register offset
        return ('reg', rn, (w >> 16) & 31, 0, size if (w >> 12) & 1 else 0)
    if w & 0x3A000000 == 0x28000000:                        # load/store pair
        scale = 2 + (w >> 31) if not (w >> 26) & 1 else 2 + ((w >> 30) & 3)
        imm = (w >> 15) & 0x7F
        imm -= (1 << 7) if imm & 0x40 else 0
        mode = (w >> 23) & 3
        return ('post' if mode == 1 else 'imm', rn, 0, imm << scale, 0)
    if w & 0x3F000000 == 0x08000000 or w & 0x3B200C00 == 0x38200000:   # exclusive/acquire, atomics
        return ('base', rn, 0, 0, 0)
    return ()


def recorder_class():
    """SaveRecorderVM when the accelerator is built, else SaveRecorderClassicVM."""
    return SaveRecorderVM if fastvm.available() else SaveRecorderClassicVM


def function_of(starts: list, rva: int) -> int | None:
    k = bisect.bisect_right(starts, rva) - 1
    return starts[k] if k >= 0 else None
