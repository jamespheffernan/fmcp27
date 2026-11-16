"""UiHandlerVM: build a game UI handler inside the property VM and read its properties.

The game's front end shows a screen through a pair of objects made by the plugin's
`GAME_UI_HANDLER_FACTORY` (vtable RVA 0x54BBBC8) from a `UI_RECORD`:

* the client handler (factory slot 3, 0x218258; base class vtable 0x54EDE08) answers
  `slot 4 get_property(this, request, out, inputs)` for the keys the screen shows;
* its `*_UI_HANDLER_SERVER` partner (factory slot 5, 0x21A960) runs on the game side
  and answers `slot 2 get(this, key, out, context)` with the values the client
  declares as inputs (client slot 16). The client consumes each value with
  `slot 17 set_input(this, key, value, ...)`.

`UiHandlerVM` emulates exactly that exchange on copied live memory: the factory,
constructors, server computation, the serialised value transfer and the client
getter are the unmodified shipped code (see docs/fmdb/UI_HANDLERS.md for the ABI as
verified). Nothing is written to the game.

State model: `PropertyVM.call` rolls every store back at the start of the next call.
A handler needs state across calls (construct, feed inputs, then read keys), so this
subclass keeps a *baseline*: `commit()` makes the VM's current private heap and
copy-on-write pages the state every later call starts from. `reset()` drops it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import os
import struct
import time

import unicorn.arm64_const as A

from . import variant
from collections import Counter

from unicorn import UC_HOOK_CODE, UC_HOOK_INTR, UC_HOOK_MEM_WRITE, UC_PROT_READ, UC_PROT_WRITE

from .vm import (HEAP, PropertyVM, PropertyResult, CallStats, Unavailable, _Stop, PAGE,
                 NULL_LIMIT, PRIVATE, PRIVATE_END, INT_REGS, TRAP, EXTERNALS,
                 THREAD_FLAG_RVA, THREAD_MAIN_RVA, THREAD_OTHER_RVA, TLV_REFUSED,
                 RNG_POLICIES, RNG_STATE_TLV, PCG_SEED_MULT, PCG_SEED_ADD, rng_cell, rng_note, mark)
from .vm import _tlv_get_addr as _vm_tlv

FACTORY_VTABLE_RVA = 0x54BBBC8      # game_plugin::GAME_UI_HANDLER_FACTORY
CLIENT_FACTORY_SLOT = 3             # 0x218258 (this, UI_RECORD&, x8 -> unique_ptr out)
SERVER_FACTORY_SLOT = 5             # 0x21A960 (this, UI_RECORD&, x8 -> unique_ptr out)
UI_HANDLER_BASE_VTABLE_RVA = 0x54EDE08
CLIENT_GET_SLOT = 4                 # (this, request{key u32 @+0x44}, out typed*, inputs)
CLIENT_DECLARE_SLOT = 16            # (this, ?, declarations)
CLIENT_INPUT_SLOT = 17              # (this, key, typed*, x3, x4 notify list, x5)
SERVER_GET_SLOT = 2                 # (this, key, out typed*, context)
SERVER_RECORD_OFFSET = 0x10         # UI_HANDLER_SERVER: UI_RECORD vector at +0x10
REQUEST_SIZE = 0x100
REQUEST_KEY_OFFSET = 0x44
TYPE_KEY = '110 '                   # UI_RECORD key whose value selects the handler type


UI_RECORD_KIND = 'UI_RECORD_TYPED_TRAITS'


class UiRecord(dict):
    """A UI_RECORD value: {fourcc: u32}; object references are UI object ids."""

    def to_json(self):
        return {'ui_record': {k: v for k, v in self.items()}}


FAULT_WINDOW = 0x8_0000            # live memory is faulted in by aligned 512 KiB windows
FAULT_ITEM = 0x10000               # ... read as 64 KiB items (an unreadable item is skipped)
OBJECT_REF_SLOT = 0x88 // 8        # database object -> {u32 UI object id, ...} (x8 result)
# VM-private code for imports whose Python model is a constant return (see _native_stubs):
NATIVE_RETURN_0 = 0x10             # TRAP + 0x10: mov x0, #0 ; ret
NATIVE_RETURN_1 = 0x20             # TRAP + 0x20: mov x0, #1 ; ret
TRAMPOLINE_START = 0x100           # TRAP + 0x100 + 8 * i: hooked entry of modelled import i

try:  # direct register access (the binding's reg_read/reg_write pick a register class per call)
    import ctypes
    from unicorn.unicorn_py3.unicorn import uclib as _uclib
except Exception:  # noqa: BLE001 - other binding layouts fall back to uc.reg_read/reg_write
    _uclib = None


def short_class(rtti: str | None) -> str | None:
    """'N11game_plugin26TEAM_CONFIDENCE_UI_HANDLERE' -> 'TEAM_CONFIDENCE_UI_HANDLER'."""
    if not rtti:
        return rtti
    import re
    parts, text = [], rtti[1:-1] if rtti.startswith('N') and rtti.endswith('E') else rtti
    while text and text[0].isdigit():
        digits = re.match(r'\d+', text).group()
        n = int(digits)
        parts.append(text[len(digits):len(digits) + n])
        text = text[len(digits) + n:]
    return parts[-1] if parts and not text else rtti


def fourcc(code: str) -> int:
    return int.from_bytes(code.encode('latin-1'), 'big')


def fourcc_text(key: int) -> str:
    return (key & 0xFFFFFFFF).to_bytes(4, 'big').decode('latin-1')


def object_id(table_type: int, index: int) -> int:
    """UI object id as packed by 0x11B8B0C: table type << 24 | index (23 bits)."""
    return ((table_type & 0xFF) << 24) | (index & 0x7FFFFF)


TICKS_START = 1_000_000


def _mach_absolute_time(vm):
    """Profiling clock: a fixed, strictly increasing tick count (values only feed timers)."""
    vm._ticks = getattr(vm, '_ticks', TICKS_START) + 1000
    vm._ret(vm._ticks)


FIXED_EPOCH = 0   # wall clock seen by emulated code: 1970-01-01T00:00:00Z


def _gettimeofday(vm):
    """Wall clock, read only by the diagnostic log-record constructor 0x43F24EC (from
    0x434B7C4, e.g. the reader-thread lock warning in `get_list` 0x14A0FB0). Fixed, so that
    committed handler state stays reproducible; marked (vm.mark)."""
    if vm._x(0):
        vm.write(vm._x(0), struct.pack('<qi4x', FIXED_EPOCH, 0))
    mark(vm, 'fixed wall clock (1970-01-01) for gettimeofday')
    vm._ret(0)


def _localtime_r(vm):
    """struct tm for the fixed epoch (UTC), written to x1; returns x1."""
    tm = struct.pack('<9i4xq8x', 0, 0, 0, 1, 0, 70, 4, 0, 0, 0)
    vm.write(vm._x(1), tm[:56])
    vm._ret(vm._x(1))


PTHREAD_TSD_OFFSET = 0xE0     # struct _pthread: tsd[] (tsd[0] == the pthread_t itself)


def owner_pthread(vm):
    flag = vm.read(vm.base + THREAD_FLAG_RVA, 1)[0]
    return vm.read_u64(vm.base + (THREAD_MAIN_RVA if flag == 1 else THREAD_OTHER_RVA))


def _tlv_get_addr(vm):
    """__tlv_bootstrap. thread='reader': PropertyVM's fresh-block model. thread='owner':
    the owning (game) thread's own TLV block, located the way dyld does: the descriptor's
    pthread key (live, low half of desc+8) indexes the owner's TSD array (pthread_t + 0xE0;
    verified by tsd[0] == pthread_t). Read through the same copy-on-write page cache as
    every other live page; the thread-local RNG descriptors stay refused."""
    if vm.thread != 'owner':
        return _vm_tlv(vm)
    desc = vm._x(0) - vm.base
    if desc in TLV_REFUSED:
        if vm.rng in ('private', 'isolate'):
            vm._ret(rng_cell(vm, desc))      # VM-private generator (vm.RNG_POLICIES)
            return
        if vm.rng != 'copy':
            raise _Stop(TLV_REFUSED[desc], hex(desc))
        # rng='copy': draw from a VM-private copy of the game thread's RNG state (the game's
        # own state is never advanced). Results are what the game would draw next, not
        # necessarily what an already-rendered screen drew; every reading notes it.
        rng_note(vm)
    start, end = vm.image.tlv_vars
    if not (start <= desc < end and (desc - start) % 24 == 0):
        raise _Stop('unknown thread-local descriptor', hex(desc))
    # dyld rewrites the descriptor at load: +8 = offset << 32 | pthread key,
    # +16 = block size << 32 | ... (observed: 0xC588_00000155 for file offset 0xC588).
    word = vm.read_u64(vm.base + desc + 8)
    key, offset = word & 0xFFFFFFFF, struct.unpack('<Q', vm.image.file_bytes(desc + 16, 8))[0]
    if word >> 32 != offset:
        raise _Stop('TLV descriptor layout not recognised', hex(desc))
    owner = owner_pthread(vm)
    tsd = owner + PTHREAD_TSD_OFFSET
    if vm.read_u64(tsd) != owner:
        raise _Stop('owner thread TSD layout not recognised', hex(owner))
    if not 0 < key < 1024:
        raise _Stop('implausible TLV pthread key', str(key))
    block = vm.read_u64(tsd + 8 * key)
    if block < 0x1_0000_0000:
        raise _Stop('owner thread has no TLV block for this image', hex(desc))
    if desc == RNG_STATE_TLV and vm.rng == 'copy' and getattr(vm, 'rng_salt', 0):
        _perturb_copy(vm, block + offset)
    vm._ret(block + offset)


def _perturb_copy(vm, cell):
    """rng='copy' with vm.rng_salt != 0: a sensitivity test (docs/fmdb/REFUSALS.md "RNG"). The
    VM-private copy of the owner thread's pcg32 state ({u32 seed, u64 state @+8, u64 inc @+0x10})
    is replaced once per call by a state derived from the salt, so a value that does not change
    is independent of the draws (class a) and one that changes depends on them (class b)."""
    if getattr(vm, '_perturbed_call', None) is vm._call:
        return
    vm._perturbed_call = vm._call
    state = (vm.rng_salt * PCG_SEED_MULT + PCG_SEED_ADD) & 0xFFFF_FFFF_FFFF_FFFF
    vm.write(cell + 8, struct.pack('<Q', state))


# ---------------------------------------------------------------------- game files (read-only)
# The game pages some history lists (FILE_LLIST, e.g. PLAYER_STATS_HISTORY) in from its
# Temporary/*_dt.cmt files on the owning thread. These models let the emulated loader read
# the same bytes: the FILE* is the game's own (copied) stdio object; its descriptor (_file,
# +0x12) is mapped to a path through the game's open-file table (`lsof`, read-only), and the
# file is opened read-only here. Positions are tracked per FILE* inside the VM; a read without
# a preceding seek is refused (the game's read buffer is not modelled).
#
# A FILE that holds write data libc has not flushed is read as the game would read it: the disk
# file with those bytes laid over it at the kernel's file offset, where that is established, and
# refused otherwise (fmdb/stdio_file.py; docs/fmdb/HISTORIES.md).
from .stdio_file import (FILE_BASE, FILE_FD, FILE_FLAGS, FILE_MOVED, FILE_OFFSET, FILE_P, FILE_SIZE,  # noqa: E402,F401
                         O_APPEND, SAPP, SOFF, SSTR, SWR, UNFLUSHED, fd_info as _proc_fd_info)
from . import stdio_file  # noqa: E402


def _proc_fd_path(pid, fd):
    """Path of a regular file open in another process as descriptor `fd` (stdio_file.fd_info)."""
    info = _proc_fd_info(pid, fd)
    return info[0] if info else info


def lsof_resolver(pid):
    """fd -> path of a regular file the game has open (read-only lookup): proc_pidfdinfo,
    falling back to `lsof` when that is not available. `resolver.position(fd)` is the
    descriptor's (kernel file offset, open flags) now, never cached, or None."""
    import subprocess
    cache = {}

    def resolve(fd):
        if fd not in cache:
            path = _proc_fd_path(pid, fd)
            if path is not False:
                cache[fd] = path
                return path
            out = subprocess.run(['lsof', '-p', str(pid), '-a', '-d', str(fd), '-Fftn'],
                                 capture_output=True, text=True, timeout=20).stdout
            fields = {line[:1]: line[1:] for line in out.splitlines() if line}
            cache[fd] = fields.get('n') if fields.get('t') == 'REG' else None
        return cache[fd]

    resolve.position = stdio_file.fd_position(pid)
    return resolve


def _process_read(vm):
    """read(address, length) of the game process as it is now, behind whatever page copies the
    VM's reader serves, or None when the reader is not a live process."""
    from .memory import LiveMemory
    reader = vm.reader
    for holder in (getattr(vm, '_source', None), reader, getattr(reader, 'inner', None),
                   getattr(reader, 'memory', None)):
        if isinstance(holder, LiveMemory):
            return holder.read
    return None


def _unflushed_write(vm, stream, head):
    """(file offset, bytes) of what the game has written to this FILE that libc has not passed
    to the kernel yet, or None when the FILE holds none (stdio_file.unflushed_write on the VM's
    copy of the FILE against the process now). Stops the call where that is not established."""
    from .memory import MemoryReadError
    try:
        return stdio_file.unflushed_write(vm.read, _process_read(vm), getattr(vm.file_resolver, 'position', None),
                                          stream, head)
    except stdio_file.NotPlaced as refused:
        raise _Stop(refused.reason, str(refused.fd)) from None
    except stdio_file.Moved as moved:
        raise _Stop(FILE_MOVED, str(moved.fd)) from None
    except MemoryReadError:
        raise _Stop(FILE_MOVED, str(struct.unpack_from('<h', head, FILE_FD)[0])) from None


class _GameFile:
    """One game FILE as the game would read it now: the file on disk, with the FILE's unflushed
    write data (if any) laid over it at the file offset where libc's flush will put it."""
    __slots__ = ('handle', 'unflushed')

    def __init__(self, handle, unflushed=None):
        self.handle, self.unflushed = handle, unflushed

    def _disk_size(self):
        return os.fstat(self.handle.fileno()).st_size

    def size(self):
        return stdio_file.size_with(self._disk_size(), self.unflushed)

    def read(self, position, total):
        self.handle.seek(position)
        data = self.handle.read(total)
        return stdio_file.lay_over(data, position, total, self._disk_size(), self.unflushed)


def _stdio_file(vm, stream):
    if vm.file_resolver is None:
        raise _Stop('game file read (no file resolver configured)')
    head = vm.read(stream, FILE_SIZE)
    fd, = struct.unpack_from('<h', head, FILE_FD)
    unflushed = _unflushed_write(vm, stream, head)
    handle = vm._open_files.get(fd)
    if handle is None:
        path = vm.file_resolver(fd)
        if not path:
            raise _Stop('game file descriptor is not a regular file', str(fd))
        handle = vm._open_files[fd] = open(path, 'rb')  # noqa: SIM115 - kept for the session
        vm.files_read.add(path)
    touched = getattr(vm, 'files_touched', None)
    if touched is not None:                 # the running trace's read set (ui_fastvm)
        touched.add(handle.name)
    return _GameFile(handle, unflushed)


def _fseeko(vm):
    stream, offset, whence = vm._x(0), vm._x(1), vm._x(2) & 0xFFFFFFFF
    offset -= (1 << 64) if offset >> 63 else 0
    file = _stdio_file(vm, stream)
    if whence == 0:
        pos = offset
    elif whence == 1 and stream in vm._fpos:
        pos = vm._fpos[stream] + offset
    elif whence == 2:
        pos = file.size() + offset
    else:
        raise _Stop('relative seek on a game file without a known position')
    if pos < 0:
        vm._ret(-1)
        return
    vm._fpos[stream] = pos
    vm._ret(0)


def _ftello(vm):
    stream = vm._x(0)
    _stdio_file(vm, stream)
    if stream not in vm._fpos:
        raise _Stop('ftell on a game file without a preceding seek')
    vm._ret(vm._fpos[stream])


def _fread(vm):
    buffer, size, count, stream = vm._x(0), vm._x(1), vm._x(2), vm._x(3)
    file = _stdio_file(vm, stream)
    if stream not in vm._fpos:
        raise _Stop('read from a game file without a preceding seek')
    total = size * count
    if total > 0x400_0000:
        raise _Stop('oversized game file read', str(total))
    data = file.read(vm._fpos[stream], total)
    if file.unflushed is not None:              # the stream is as it was before the disk read
        try:
            after = _unflushed_write(vm, stream, vm.read(stream, FILE_SIZE))
        except _Stop:
            after = None
        if after != file.unflushed:
            raise _Stop(FILE_MOVED, 'during the disk read')
    items = len(data) // size if size else 0
    data = data[:items * size]
    if data:
        vm.write(buffer, data)
    vm._fpos[stream] += len(data)
    vm.bytes_from_files += len(data)
    vm._ret(items)


def _ferror(vm):
    _stdio_file(vm, vm._x(0))
    vm._ret(0)


# libc++ std::sort instantiations on primitive arrays with std::__less (exported from
# libc++.dylib, e.g. __ZNSt3__16__sortIRNS_6__lessIaaEEPaEEvT0_S5_T_ for int8_t):
# sort [x0, x1) ascending in place. Equal primitives are indistinguishable, so the
# unstable order of std::sort cannot show (except -0.0/+0.0 and NaN, refused).
_SORT_TYPES = {'a': 'b', 'h': 'B', 's': 'h', 't': 'H', 'i': 'i', 'j': 'I', 'l': 'q', 'm': 'Q',
               'x': 'q', 'y': 'Q', 'f': 'f', 'd': 'd'}


def _sort_model(name):
    import re
    match = re.fullmatch(r'__ZNSt3__16__sortIRNS_6__lessI(\w)\1EEP\1EEvT0_S5_T_', name)
    if not match or match.group(1) not in _SORT_TYPES:
        return None
    code = _SORT_TYPES[match.group(1)]
    width = struct.calcsize(code)

    def model(vm):
        first, last = vm._x(0), vm._x(1)
        count = (last - first) // width
        if last < first or (last - first) % width or count > 1_000_000:
            raise _Stop('implausible std::sort range')
        values = list(struct.unpack(f'<{count}{code}', vm.read(first, count * width))) if count else []
        if code in 'fd' and any(v != v or (v == 0 and str(v).startswith('-')) for v in values):
            raise _Stop('std::sort on floats with NaN or -0.0')
        values.sort()
        if count:
            vm.write(first, struct.pack(f'<{count}{code}', *values))
    return model


# ---------------------------------------------------------------------- pool allocator
# The game's small-object pools hand out blocks from free lists that live in game memory
# (bucket+0x98 in 0x4355A04, pool+0x28 in 0x4356EB8). The running game allocates and frees
# all the time, so free-list heads and the blocks they point to are copied at different
# moments; following them handed the emulation blocks the game was using (observed as
# 'NULL'-tagged garbage pointers and flaky reads). These allocator entry points are
# therefore modelled on the VM heap, like malloc: same size-header contract, zeroed blocks.
def _pool_alloc(vm):
    """0x4355A04 alloc(pool, size): optional u32 size header of pool+0x30 bytes."""
    pool, size = vm._x(0), vm._x(1) & 0xFFFFFFFF
    header = struct.unpack('<I', vm.read(pool + 0x30, 4))[0]
    if header > 64 or size > 0x400_0000:
        raise _Stop('implausible pool allocation', f'{size}+{header}')
    block = vm.alloc(size + header)
    vm.write(block, b'\0' * (size + header))
    if header:
        vm.write(block, struct.pack('<I', size))
    vm._ret(block + header)


def _pool_free(vm):
    """0x4355ED4 free(pool, ptr, size): VM heap blocks are never reused."""
    vm._ret(0)


def _fixed_pool_alloc(vm):
    """0x4356EB8 alloc(fixed pool): element size u32 at pool+0x38, zeroed when pool+0x48."""
    pool = vm._x(0)
    size = struct.unpack('<I', vm.read(pool + 0x38, 4))[0]
    if not 0 < size <= 0x10_0000:
        raise _Stop('implausible fixed pool element size', str(size))
    block = vm.alloc(size)
    vm.write(block, b'\0' * size)
    vm._ret(block)


INTERCEPTS = {
    0x4355A04: ('pool_alloc', _pool_alloc),
    0x4355ED4: ('pool_free', _pool_free),
    0x4356EB8: ('fixed_pool_alloc', _fixed_pool_alloc),
}


# ---------------------------------------------------------------------- free lists (UI_ROUND2.md section 6)
# Three more pools of the plugin keep free lists in game memory: property-bag nodes (pool
# 0x56A4DF8), typed-value nodes (0x56A8A18, 0x56B1328) and any pool through 0x43569F8. The pops
# and pushes are inlined (`ldr xR, [pool+0x98]; cbz xR, slow; ldr x9, [xR]; str x9, [pool+0x98]`).
# The running game changes these heads many times a second, so emulated code that followed them
# read torn lists and every cached answer that read a head was invalid on its next check. Each
# site is modelled like the pool allocator: a pop yields a zeroed VM-heap block of the pool's
# element size (u32 at pool+0x12C; 16, 24, 24 bytes on the running game, whose pools neither
# count nor zero: flags +0x128 and +0x13C are 0), a push is dropped, and execution resumes after
# the skipped stores with the scratch registers as the skipped instructions leave them for that
# block. A site is installed only when the shipped bytes are the ones below (`code`), so another
# game build never gets a model at a wrong address. FMDB_UI_FREE_LISTS=0 turns the models off.
@dataclass(frozen=True)
class FreeListSite:
    name: str
    rva: int                   # first skipped instruction
    resume: int                # first instruction run after the model (0: return to lr)
    kind: str                  # 'pop', 'push', 'pool_get' (function entry), 'pool_put' (function entry)
    pool: int | None           # pool record RVA (pop), element size u32 at +0x12C
    dest: int | None           # register that receives the node (pop)
    sets: tuple = ()           # ((register, absolute RVA or None for 0), ...) scratch registers
    code: str = ''             # the shipped bytes of [rva, resume) (entries: the first 48 bytes)


FREE_LIST_SITES = (
    FreeListSite('bag_node_pop_a', 0x43F8374, 0x43F8388, 'pop', 0x56A4DF8, 21, ((8, 0x56A4000), (9, None)),
                 '68950090154947f9750000b4a90240f9094907f9'),
    FreeListSite('bag_node_pop_b', 0x43F70C4, 0x43F70D8, 'pop', 0x56A4DF8, 21, ((8, 0x56A4000), (9, None)),
                 '689500b0154947f9750000b4a90240f9094907f9'),
    FreeListSite('value_node_pop_a', 0x4404690, 0x44046A4, 'pop', 0x56A8A18, 22, ((8, 0x56A8000), (9, None)),
                 '28950090165945f9760000b4c90240f9095905f9'),
    FreeListSite('value_node_pop_b', 0x4409618, 0x440962C, 'pop', 0x56A8A18, 21, ((8, None), (9, 0x56A8000)),
                 'b52240f9950000b4a80240f9e99400f0285905f9'),
    FreeListSite('value_node_pop_c', 0x4404494, 0x44044A8, 'pop', 0x56A8A18, 22, ((8, None), (9, 0x56A8000)),
                 'd62240f9960000b4c80240f929950090285905f9'),
    FreeListSite('value_node_push_a', 0x44094DC, 0x44094E8, 'push', None, None, ((8, None),),
                 '882240f9a80200f9952200f9'),
    FreeListSite('value_node2_pop_a', 0x44042E0, 0x44042F4, 'pop', 0x56B1328, 22, ((8, 0x56B1000), (9, None)),
                 '689500b016e141f9760000b4c90240f909e101f9'),
    FreeListSite('value_node2_pop_b', 0x43EA324, 0x43EA338, 'pop', 0x56B1328, 21, ((8, None), (9, 0x56B1000)),
                 'b52240f9950000b4a80240f9299600f028e101f9'),
    FreeListSite('value_node2_push_a', 0x43EA1F0, 0x43EA1FC, 'push', None, None, ((8, None),),
                 '882240f9a80200f9952200f9'),
    FreeListSite('pool_get', 0x43569F8, 0, 'pool_get', None, None, (),
                 'f44fbea9fd7b01a9fd430091f30300aa0060019191611e94744e40f9740000b4880240f9684e00f9'),
    FreeListSite('pool_put', 0x4356AA0, 0, 'pool_put', None, None, (),
                 'f44fbea9fd7b01a9fd430091f40301aaf30300aa0060019166611e94684e40f9880200f9744e00f9'),
)
# the live words the models stop the emulation from reading (head = pool+0x98)
FREE_LIST_HEADS = (0x56A4E90, 0x56A8AB0, 0x56B13C0, 0x56A4D48)


def free_lists_wanted() -> bool:
    import os
    return os.environ.get('FMDB_UI_FREE_LISTS', '1') != '0'


def free_list_sites(image) -> list:
    """The sites whose shipped bytes match (the rest are not modelled on this build).
    FMDB_UI_FREE_LISTS=name,name,... (diagnostics) models only the named sites."""
    import os
    only = os.environ.get('FMDB_UI_FREE_LISTS', '1')
    only = set(only.split(',')) if only not in ('0', '1', '') else None
    out = []
    for site in FREE_LIST_SITES:
        if only is not None and site.name not in only:
            continue
        code = bytes.fromhex(site.code)
        try:
            if image.file_bytes(site.rva, len(code)) == code:
                out.append(site)
        except Exception:  # noqa: BLE001 - address outside this image
            continue
    return out


def reg_id(n: int) -> int:
    return getattr(A, f'UC_ARM64_REG_X{n}') if n <= 28 else (A.UC_ARM64_REG_X29 if n == 29 else A.UC_ARM64_REG_LR)


def _free_list_model(site):
    """Python model of one site (the reference emulator, and the C model's fallback). Returns the
    address to resume at (None: the function's return address)."""
    def model(vm):
        if site.kind in ('pop', 'pool_get'):
            pool = vm.base + site.pool if site.kind == 'pop' else vm._x(0)
            size = struct.unpack('<I', vm.read(pool + 0x12C, 4))[0]
            if not 0 < size <= 0x10_0000:
                raise _Stop('implausible pool element size', str(size))
            block = vm.alloc(size)
            vm.write(block, b'\0' * size)
            if site.kind == 'pool_get':
                vm._ret(block)
            else:
                vm._reg_set(reg_id(site.dest), block)
        elif site.kind == 'pool_put':
            vm._ret(0)
        for reg, rva in site.sets:
            vm._reg_set(reg_id(reg), 0 if rva is None else vm.base + rva)
        return vm.base + site.resume if site.resume else None
    return model


def _strncmp(vm):
    a, b, n = vm._x(0), vm._x(1), vm._x(2)
    if n > 1 << 20:
        raise _Stop('oversized strncmp', str(n))
    def prefix(address):
        out = bytearray()
        while len(out) < n:
            chunk = vm.read(address + len(out), min(64, n - len(out)))
            cut = chunk.find(b'\0')
            if cut >= 0:
                return bytes(out + chunk[:cut])
            out += chunk
        return bytes(out)
    x, y = prefix(a), prefix(b)
    vm._ret(0 if x == y else (-1 if x < y else 1))


def _memchr(vm):
    """memchr(s, c, n): first byte equal to (unsigned char)c in [s, s+n), else NULL.
    Called by the calendar event collector (0x3C95154 via 0x3AA9BB0)."""
    s, c, n = vm._x(0), vm._x(1) & 0xFF, vm._x(2)
    if n > 1 << 24:
        raise _Stop('oversized memchr', str(n))
    offset = 0
    while offset < n:
        chunk = vm.read(s + offset, min(4096, n - offset))
        hit = chunk.find(bytes([c]))
        if hit >= 0:
            vm._ret(s + offset + hit)
            return
        offset += len(chunk)
    vm._ret(0)


def _modff(vm):
    """float modff(float x [s0], float *iptr [x0]): fractional part, integral part stored.
    Used by the news age text ('NewsItemAgeString')."""
    import math
    from .vm import _bits_s, _ret_s
    x = _bits_s(vm, 0)
    if math.isinf(x):
        frac, whole = math.copysign(0.0, x), x
    else:
        frac, whole = math.modf(x)        # same signs as C; NaN gives NaN for both
    vm.write(vm._x(0), struct.pack('<f', whole))
    _ret_s(vm, frac)


_DECIMAL = None


def _strtod(vm):
    """double strtod(const char *s [x0], char **end [x1]) for plain decimal text (C locale);
    hex floats, inf and nan are refused. Python's float() rounds correctly, as libc does."""
    import re
    from .vm import _cstr, _ret_d
    global _DECIMAL
    if _DECIMAL is None:
        _DECIMAL = re.compile(rb'[ \t\n\r\f\v]*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)')
    text = _cstr(vm, vm._x(0), 4096)
    match = _DECIMAL.match(text)
    if match is None:
        stripped = text.lstrip(b' \t\n\r\f\v').lstrip(b'+-')[:3].lower()
        if stripped in (b'inf', b'nan') or stripped.startswith(b'0x'):
            raise _Stop('strtod on non-decimal text', text[:32].decode('latin-1'))
        value, used = 0.0, 0
    else:
        number = match.group(1)
        if re.fullmatch(rb'[+-]?0', number) and text[match.end(1):match.end(1) + 1] in (b'x', b'X'):
            raise _Stop('strtod on non-decimal text', text[:32].decode('latin-1'))
        value, used = float(number), match.end(1)
    if vm._x(1):
        vm.write(vm._x(1), struct.pack('<Q', vm._x(0) + used))
    _ret_d(vm, value)


# Externals the UI layer needs beyond PropertyVM's whitelist (looked up first).
UI_EXTERNALS = {
    '_strncmp': _strncmp, '_memchr': _memchr, '_modff': _modff, '_strtod': _strtod,
    '_fseeko': _fseeko, '_fseek': _fseeko, '_ftello': _ftello, '_ftell': _ftello,
    '_fread': _fread, '_ferror': _ferror,
    '__tlv_bootstrap': _tlv_get_addr,
    '_mach_absolute_time': _mach_absolute_time,
    '_gettimeofday': _gettimeofday,
    '_localtime_r': _localtime_r,
}


# Random-number consumers and their policy (docs/fmdb/REFUSALS.md "RNG"). Classes: (a) the value
# does not depend on the draws, (b) it is a function of the generator state the game would also
# use next, (c) drawn earlier and stored by the game. Evidence: scripts/fmdb_rng_classify.py (the
# screen read twice, the copied pcg32 state replaced by a salted one in the second run) on the
# reference save. Policy: 'copy' everywhere (UiHandlerVM default for the recipes); fields that
# drew are listed per answer in `fields_using_random_draws`.
RNG_CONSUMERS = {
    # screen recipe: (draws on the reference save, class, fields that drew)
    'medical': (136, 'a', ('team.exhausted_and_recurring',)),
    'youth_intake': (2, 'a', ('club.youth_intake_level',)),            # std::random_device (mt19937 seed)
    'manager_profile': (72, 'a', ('board.job_security_from_contract',)),
    'season_expectations': (4, 'a', ('expectations.competitions',)),
    # handler jobs of scripts/fmdb_ui_sweep.py (FMDB_RNG_SALT run against the plain run)
    'HIRE_INTERMEDIARY_UI_HANDLER': (440, 'a', ()),
    'TEAM_CONFIDENCE_UI_HANDLER': (16, 'a', ()),
    'RECRUITMENT_FOCUS_UI_HANDLER': (8, 'a', ()),
}


TWO_SEED_SALT = 0x1234
GENERATED_AT_READ = ('generated at read: the value changes when the copied random state is reseeded '
                     '(two-seed rule); withheld')


def leaves(value, path=()):
    """{path tuple: leaf} of a JSON-like answer (dict keys and list indexes)."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            out.update(leaves(v, path + (k,)))
        return out
    if isinstance(value, (list, tuple)):
        out = {}
        for i, v in enumerate(value):
            out.update(leaves(v, path + (i,)))
        return out
    return {path: value}


def _withhold(value, changed, path=()):
    if path in changed:
        return {'unavailable': GENERATED_AT_READ}
    if isinstance(value, dict):
        return {k: _withhold(v, changed, path + (k,)) for k, v in value.items()}
    if isinstance(value, list):
        return [_withhold(v, changed, path + (i,)) for i, v in enumerate(value)]
    return value


def two_seed(read, salt=TWO_SEED_SALT, *, ignore=frozenset()):
    """The two-seed rule for UI handler answers. `read(salt)` builds and reads a screen on a fresh
    (or reset) UiHandlerVM with `rng='copy'` and `vm.rng_salt = salt`, returning a JSON-like answer.
    It runs with salt 0 (the game's copied state) and with `salt`; every leaf that differs is
    replaced by {'unavailable': GENERATED_AT_READ}. Leaves whose key is in `ignore` (timings,
    draw counts) are not compared. Returns (answer, sorted changed paths)."""
    a, b = read(0), read(salt)
    la, lb = leaves(a), leaves(b)
    changed = {p for p in set(la) | set(lb)
               if la.get(p) != lb.get(p) and not any(k in ignore for k in p)}
    def exists(path):
        node = a
        for k in path:
            try:
                node = node[k]
            except (KeyError, IndexError, TypeError):
                return False
        return True
    present = set()
    for p in changed:                     # a path only the salted run has: withhold its parent in `a`
        while p and not exists(p):
            p = p[:-1]
        present.add(p)
    return _withhold(a, present), sorted(map(str, changed))


@dataclass
class Baseline:
    heap_top: int
    heap: bytes
    allocations: dict
    pages: dict           # page -> bytes at commit time
    origin: dict          # page -> original live bytes (copy-on-write source)
    tlv_block: int | None
    fpos: dict = field(default_factory=dict)
    ticks: int = 0


@dataclass
class Handler:
    """A client handler (and its server partner) built inside the VM."""
    handler_type: int
    record: dict                      # UI_RECORD as {fourcc text: u32}
    client: int                       # VM address of the client handler object
    server: int | None
    client_class: str | None
    server_class: str | None
    inputs: dict = field(default_factory=dict)   # key -> status text
    build_seconds: float = 0.0
    build_instructions: int = 0


_CLASSIC = []      # non-empty while UiHandlerVM.classic() constructs the reference implementation


def fast_wanted() -> bool:
    """True when `UiHandlerVM(...)` should build the C-accelerated subclass: the library is
    built (scripts/build_ui_accel.sh) and FMDB_UI_VM is not 'classic'."""
    import os
    if _CLASSIC or os.environ.get('FMDB_UI_VM', '').lower() == 'classic':
        return False
    from . import ui_fastvm
    return ui_fastvm.available()


class UiHandlerVM(PropertyVM):
    def __new__(cls, *args, **kwargs):
        # `UiHandlerVM(...)` is ui_fastvm.FastUiHandlerVM (a subclass: same interface, results
        # and stop reasons; docs/fmdb/UI_FAST.md) when its library is available.
        if cls is UiHandlerVM and fast_wanted():
            from .ui_fastvm import FastUiHandlerVM
            return super().__new__(FastUiHandlerVM)
        return super().__new__(cls)

    @classmethod
    def classic(cls, *args, **kwargs):
        """The Python-hooked reference implementation, whatever FMDB_UI_VM says."""
        _CLASSIC.append(True)
        try:
            return UiHandlerVM(*args, **kwargs)
        finally:
            _CLASSIC.pop()

    def __init__(self, reader, base, image, *, view='game', thread='owner', budget=200_000_000,
                 timeout_us=600_000_000, file_resolver=None, rng='refuse'):
        if rng not in RNG_POLICIES + ('copy',):
            raise ValueError(f"rng must be 'copy' or one of {RNG_POLICIES}")
        # 'isolate' is not applied per key here (a handler keeps state across calls); it
        # behaves as 'private' and consumers compare two seeds themselves (ui_recipes_*).
        self.rng, self.rng_uses = rng, 0
        self._baseline = None
        self.file_resolver = file_resolver
        self._open_files = {}
        self._fpos = {}
        self.files_read = set()
        self.bytes_from_files = 0
        self.counting = True
        self.text_size = image.segment('__TEXT').vmsize
        self.live_pages = {}
        self.code_pages = set()
        self.unreadable = set()
        self.fault_window = FAULT_WINDOW
        self._models = {}
        self._stub_at = {base + rva: name for rva, name in image.stubs.items()}
        self._reg = None
        super().__init__(reader, base, image, budget=budget, timeout_us=timeout_us,
                         view=view, thread=thread)
        self.retry_stale = False             # a page refresh would drop committed handler state
        self._install_hooks()

    def _install_hooks(self):
        """Hooks on top of PropertyVM's (ui_fastvm.FastUiHandlerVM installs its own)."""
        base = self.base
        # PropertyVM.__init__ adds six hooks in a fixed order (unmapped, write-prot, write,
        # fetch-prot, block, stub); keep their handles before more are added.
        self._base_hooks = list(self.uc._callbacks)
        self._fast_registers()
        self._fast_write_hook()
        self._native_stubs()
        self.uc.hook_add(UC_HOOK_INTR, self._on_intr)
        self.intercepted = Counter()
        for rva, (name, model) in INTERCEPTS.items():
            self.uc.hook_add(UC_HOOK_CODE, self._on_intercept, (name, model),
                             begin=base + rva, end=base + rva)
        self.free_list_sites = free_list_sites(self.image) if free_lists_wanted() else []
        for site in self.free_list_sites:
            self.uc.hook_add(UC_HOOK_CODE, self._on_intercept, (site.name, _free_list_model(site)),
                             begin=base + site.rva, end=base + site.rva)

    def _on_intercept(self, uc, address, size, user):
        name, model = user
        try:
            resume = model(self)
        except _Stop as stop:
            self._fail(uc, stop.reason, stop.detail)
            return
        self.intercepted[name] += 1
        self._reg_set(A.UC_ARM64_REG_PC, resume if resume else self._reg_get(A.UC_ARM64_REG_LR))

    # ------------------------------------------------------------------ speed
    def _fast_registers(self):
        """Register access straight through the C API with one reusable buffer (the binding's
        reg_read/reg_write select a register class per call: ~3 us of Python each)."""
        if _uclib is None:
            return
        self._reg = ctypes.c_uint64(0)
        self._reg_ref = ctypes.byref(self._reg)
        self._uch = self.uc._uch

    def _fast_write_hook(self):
        """Replace PropertyVM's copy-on-write store hook with a direct C callback.

        The hook fires before every store to live memory (2.7 M per TEAM_CONFIDENCE
        computation); almost all hit a page already copied in this call. The binding wraps
        each callback in two Python frames; this callback is called by Unicorn directly,
        returns at once for an already-copied page and otherwise runs the same
        `_on_write`. Exceptions never cross into C: they stop the call."""
        try:
            from unicorn.unicorn_py3.unicorn import HOOK_MEM_ACCESS_CFUNC
            add = self.uc._Uc__do_hook_add
        except Exception:  # noqa: BLE001 - other binding layouts keep the original hook
            return
        uc, on_write, mask = self.uc, self._on_write, ~(PAGE - 1)

        def raw(handle, access, address, size, value, key):
            page = address & mask
            if page in self.dirty and ((address + size - 1) & mask) == page:
                return
            try:
                on_write(uc, access, address, size, value, None)
            except BaseException as exc:  # noqa: BLE001
                self._fail(uc, 'copy-on-write hook error', repr(exc))

        self._raw_write = HOOK_MEM_ACCESS_CFUNC(raw)
        add(UC_HOOK_MEM_WRITE, self._raw_write, NULL_LIMIT, PRIVATE - 1)
        self.uc.hook_del(self._base_hooks[2])
        self._base_hooks[2] = None

    def _reg_get(self, reg):
        if self._reg is None:
            return self.uc.reg_read(reg)
        if _uclib.uc_reg_read(self._uch, reg, self._reg_ref):
            return self.uc.reg_read(reg)          # let the binding raise its own error
        return self._reg.value

    def _reg_set(self, reg, value):
        if self._reg is None:
            return self.uc.reg_write(reg, value)
        self._reg.value = value & 0xFFFF_FFFF_FFFF_FFFF
        if _uclib.uc_reg_write(self._uch, reg, self._reg_ref):
            self.uc.reg_write(reg, value)

    def _x(self, i):
        return self._reg_get(INT_REGS[i])

    def _ret(self, value=0):
        self._reg_set(A.UC_ARM64_REG_X0, value)

    def _resolve(self, name):
        """The Python model for an import (cached per name), or None."""
        try:
            return self._models[name]
        except KeyError:
            model = self._models[name] = UI_EXTERNALS.get(name) or _sort_model(name) or EXTERNALS.get(name)
            return model

    def _native_stubs(self):
        """Route modelled imports without stopping the emulation.

        * Imports whose model only returns a constant (`_noop`: locks, free/delete, atexit;
          `_true`: try-locks) run as `mov x0, #c ; ret` on the VM-private TRAP page instead
          of a Python call; the stub-range code hook is narrowed to skip their stubs.
          (pthread_mutex_lock/unlock alone were ~240,000 Python calls in one
          TEAM_CONFIDENCE computation.)
        * Every other modelled import gets a private trampoline address on the TRAP page
          with a code hook that runs the model and returns to LR. Code that calls an import
          through its pointer slot directly (`__tlv_bootstrap` through each thread-local
          descriptor, `___chkstk_darwin` through the GOT) used to fault on the live
          libsystem address and restart the emulation (~4,400 restarts per computation).

        Both work by overlaying the import's pointer slots (chained-fixup binds whose live
        value is that import) inside the VM; never written to the game. The live-address
        table for pointers copied elsewhere is built first, so those still resolve as
        before. Constant-return imports are no longer counted in `stubbed` or
        CallStats.externals."""
        from . import vm as _vm
        self.uc.mem_write(TRAP + NATIVE_RETURN_0, struct.pack('<II', 0xD2800000, 0xD65F03C0))
        self.uc.mem_write(TRAP + NATIVE_RETURN_1, struct.pack('<II', 0xD2800020, 0xD65F03C0))
        constant = {_vm._noop: TRAP + NATIVE_RETURN_0, _vm._true: TRAP + NATIVE_RETURN_1}
        self._live_import(0)                 # live address -> import table, before overlays
        live_value = {name: address for address, name in self.live_imports.items()}
        self._trampolines, slots = {}, {}
        for rva, name in self.image.binds.items():
            model = self._resolve(name)
            if model is None or name not in live_value:
                continue
            target = constant.get(model) if not (UI_EXTERNALS.get(name) or _sort_model(name)) else None
            if target is None:
                target = self._trampoline_for(name)
            try:
                if self.read_u64(self.base + rva) & ((1 << 47) - 1) != live_value[name]:
                    continue                 # not a plain pointer to the import (e.g. addend)
            except _Stop:
                continue
            slots[self.base + rva] = target
        self._native_slots = slots
        self._apply_native_slots()
        native = {self.base + rva for rva, name in self.image.stubs.items()
                  if constant.get(self._resolve(name)) and not UI_EXTERNALS.get(name)
                  and not _sort_model(name)}
        self.uc.hook_del(self._base_hooks[5])
        self._base_hooks[5] = None
        start = self.stub_start
        for address in sorted(native) + [self.stub_end]:
            if address > start:
                self.uc.hook_add(UC_HOOK_CODE, self._on_stub, begin=start, end=address - 1)
            start = address + 12
        if self._trampolines:
            first = TRAP + TRAMPOLINE_START
            self.uc.hook_add(UC_HOOK_CODE, self._on_trampoline, begin=first,
                             end=first + 8 * len(self._trampolines) - 1)
        self.native_stub_count = len(native)

    def _trampoline_for(self, name):
        if name not in self._trampolines:
            index = len(self._trampolines)
            if TRAMPOLINE_START + 8 * (index + 1) > PAGE:
                raise RuntimeError('too many import trampolines for the TRAP page')
            self._trampolines[name] = TRAP + TRAMPOLINE_START + 8 * index
        return self._trampolines[name]

    def _apply_native_slots(self):
        self._trampoline_at = {address: name for name, address in self._trampolines.items()}
        for address, target in self._native_slots.items():
            self.set_overlay(address, struct.pack('<Q', target))

    def _on_trampoline(self, uc, address, size, user):
        name = self._trampoline_at.get(address)
        if name is None:
            return
        self._on_stub_name(uc, name)

    def _on_stub_name(self, uc, name):
        try:
            self._external(name)
        except _Stop as stop:
            self._fail(uc, stop.reason, stop.detail)
            return
        self._reg_set(A.UC_ARM64_REG_PC, self._reg_get(A.UC_ARM64_REG_LR))

    def _on_stub(self, uc, address, size, user):
        name = self._stub_at.get(address)
        if name is not None:
            self._on_stub_name(uc, name)

    def _on_intr(self, uc, intno, user):
        """Unaligned LSE atomics (e.g. LDADD on a refcount at string-4, 0x43D2FBC) fault in
        Unicorn but are legal on the game's CPU (FEAT_LSE2, within 16 bytes). Emulate
        LD{ADD,CLR,EOR,SET} and SWP (32/64-bit) on the VM's memory and step over them;
        any other exception stops the call as before."""
        pc = uc.reg_read(A.UC_ARM64_REG_PC)
        try:
            word = self._code_word(uc, pc)
            swap_bad = bool(word & 0x8000) and (word >> 12) & 7
            if (word & 0x3F200C00) != 0x38200000 or swap_bad:
                raise _Stop('cpu exception', f'pc={pc - self.base:#x} insn={word:#010x}')
            size = 8 if word >> 30 == 3 else 4 if word >> 30 == 2 else 0
            if not size:
                raise _Stop('cpu exception (atomic width)', f'pc={pc - self.base:#x}')
            rs, rn, rt = (word >> 16) & 31, (word >> 5) & 31, word & 31
            if rt not in range(29) and rt != 31 or rs not in range(29) and rs != 31 or rn in (29, 30):
                raise _Stop('cpu exception (atomic register)', f'pc={pc - self.base:#x}')
            opc, swap = (word >> 12) & 7, bool(word & 0x8000)
            address = uc.reg_read(A.UC_ARM64_REG_SP) if rn == 31 else self._x(rn)
            if (address & 15) + size > 16:
                raise _Stop('unaligned atomic across 16 bytes', hex(address))
            mask = (1 << (8 * size)) - 1
            old = int.from_bytes(self.read(address, size), 'little')
            operand = 0 if rs == 31 else self._x(rs) & mask
            if swap:
                new = operand
            elif opc in (0, 1, 2, 3):
                new = ((old + operand), (old & ~operand), (old ^ operand), (old | operand))[opc] & mask
            else:
                raise _Stop('cpu exception (atomic min/max)', f'pc={pc - self.base:#x}')
            page = address & ~(PAGE - 1)
            if page in self.code_pages:
                raise _Stop('write to shipped code', hex(address))
            self.write(address, new.to_bytes(size, 'little'))
            if rt != 31:
                uc.reg_write(INT_REGS[rt], old)
            uc.reg_write(A.UC_ARM64_REG_PC, pc + 4)
        except _Stop as stop:
            self._fail(uc, stop.reason, stop.detail)

    def _code_word(self, uc, pc):
        return struct.unpack('<I', bytes(uc.mem_read(pc, 4)))[0]

    def begin_read(self, prefetch=None, max_age=None):
        """Start a read from current game memory. Here: forget every copied live page (the
        accelerated subclass keeps them and re-reads each before its first use instead)."""
        self.invalidate()
        self.__dict__.pop('_factory', None)

    def live_read(self, address: int, length: int) -> bytes:
        return self.reader.read(address, length)

    def fast(self):
        """Drop PropertyVM's per-basic-block Python hook (instruction budget and counts).

        Server computations run tens of millions of instructions and the block hook is a
        Python call per basic block. Without it only the wall-clock timeout bounds a call
        and CallStats.instructions stays 0. PropertyVM.__init__ adds exactly six hooks in a
        fixed order (unmapped, write-prot, write, fetch-prot, block, stub); the fifth goes.
        (The per-store copy-on-write hook stays: Unicorn does not retry a store after a
        write-protection fault handler returns True, so page protection cannot replace it.)"""
        if not self.counting:
            return self
        handles = self._base_hooks
        if len(handles) < 6:
            raise RuntimeError('unexpected PropertyVM hook layout; refusing to drop hooks')
        self.uc.hook_del(handles[4])
        handles[4] = None
        self.counting = False
        return self

    def limit_instructions(self, count: int):
        """Stop every emulation segment after `count` instructions (Unicorn's own counter).

        For fast() VMs, which have no Python instruction budget. Unicorn counts with a C
        hook compiled into each translated block, so this must be set before the first
        emulation of this VM (blocks translated earlier are not counted) and makes
        emulation about 2.3x slower. A stop shows as 'emulation stopped early'."""
        if getattr(self, '_emulated', False):
            raise RuntimeError('limit_instructions must be set before the first emulated call')
        count = int(count)
        if count <= 0:
            raise ValueError('instruction limit must be positive')
        start = type(self.uc).emu_start
        uc = self.uc

        def emu_start(begin, until, timeout=0, _count=0):
            return start(uc, begin, until, timeout, count)
        self.uc.emu_start = emu_start
        self.instruction_limit = count
        return self

    def call(self, address, args=(), *, fargs=()):
        self._emulated = True
        return super().call(address, args, fargs=fargs)

    # ------------------------------------------------------------------ memory
    def _fault_in(self, page):
        """Fault memory in by large runs instead of single pages.

        Unicorn's mem_map costs grow with the number of mapped regions (each map rebuilds
        the address-space view), so the total is roughly quadratic in the number of maps:
        4,282 maps took 17 s of a 40 s TEAM_CONFIDENCE computation. Two changes keep the
        region count low:

        * shipped code: the first fault anywhere in __TEXT maps the whole run of unmapped
          __TEXT pages around it from the verified on-disk slice (one map instead of ~1,150);
        * live data: the run of unmapped pages around `page` inside its aligned
          `fault_window` (512 KiB) is read with one batched request in 64 KiB items and every
          readable stretch is mapped once (~1,000 maps instead of ~3,000). An unreadable item
          is left unmapped; if it holds `page`, PropertyVM's single-page path decides."""
        if page in self.live_pages or page in self.code_pages:
            return None
        if page < NULL_LIMIT or PRIVATE <= page < PRIVATE_END:
            return super()._fault_in(page)
        if 0 <= page - self.base < self.text_size:
            return self._map_text(page)
        if page in self.unreadable:
            return super()._fault_in(page)
        size = self.fault_window
        window = page & ~(size - 1)

        def free(p):
            return (window <= p < window + size and p not in self.live_pages
                    and p not in self.code_pages and p not in self.unreadable
                    and not 0 <= p - self.base < self.text_size
                    and not PRIVATE <= p < PRIVATE_END)
        start = page
        while free(start - PAGE):
            start -= PAGE
        end = page + PAGE
        while free(end):
            end += PAGE
        if end - start == PAGE:
            return super()._fault_in(page)
        runs = self._read_runs(start, end)
        if not any(a <= page < a + len(d) for a, d in runs):
            return super()._fault_in(page)
        for address, data in runs:
            self.uc.mem_map(address, len(data), UC_PROT_READ | UC_PROT_WRITE)
            self.uc.mem_write(address, data)
            for p in range(address, address + len(data), PAGE):
                self.live_pages[p] = True
            if self._call is not None:
                self._call.new_pages += len(data) // PAGE
        return None

    def _read_runs(self, start, end):
        """[(address, bytes)] readable stretches of [start, end), read in one request."""
        many = getattr(self.reader, 'read_many_status', None)
        if many is None:
            try:
                return [(start, self.reader.read(start, end - start))]
            except Exception:  # noqa: BLE001 - some page is unreadable: page by page
                return []
        items, address = [], start
        while address < end:
            stop = min(end, (address & ~(FAULT_ITEM - 1)) + FAULT_ITEM)
            items.append((address, stop - address))
            address = stop
        try:
            results = many(items)
        except Exception:  # noqa: BLE001
            return []
        runs, run_start, chunks = [], None, []
        for (address, length), (_, data) in zip(items, results):
            if data is not None and len(data) == length:
                if run_start is None:
                    run_start = address
                chunks.append(data)
                continue
            if run_start is not None:
                runs.append((run_start, b''.join(chunks)))
            run_start, chunks = None, []
        if run_start is not None:
            runs.append((run_start, b''.join(chunks)))
        return runs

    def _map_text(self, page):
        """Map the run of unmapped __TEXT pages around `page` R+X from the on-disk slice."""
        lo, hi = self.base, self.base + self.text_size
        start = page
        while start - PAGE >= lo and (start - PAGE) not in self.code_pages \
                and (start - PAGE) not in self.live_pages:
            start -= PAGE
        end = page + PAGE
        while end < hi and end not in self.code_pages and end not in self.live_pages:
            end += PAGE
        from unicorn import UC_PROT_EXEC
        self.uc.mem_map(start, end - start, UC_PROT_READ | UC_PROT_EXEC)
        self.uc.mem_write(start, self.image.file_bytes(start - self.base, end - start))
        self.code_pages.update(range(start, end, PAGE))

    # ------------------------------------------------------------------ baseline state
    def _restore(self):
        self._restore_state()

    def _restore_state(self):
        base = self._baseline
        if base is None:
            self._fpos = {}
            self._ticks = TICKS_START
            return super()._restore()
        self._fpos = dict(base.fpos)
        for page, original in self.dirty.items():
            if page not in base.pages:
                self.uc.mem_write(page, original)
        for page, data in base.pages.items():
            self.uc.mem_write(page, data)
        self.dirty = dict(base.origin)
        if self.heap_top > base.heap_top:
            self.uc.mem_write(base.heap_top, b'\0' * (self.heap_top - base.heap_top))
        if base.heap:
            self.uc.mem_write(HEAP, base.heap)
        self.heap_top = base.heap_top
        self.allocations = dict(base.allocations)
        self._tlv_block = base.tlv_block
        self._ticks = base.ticks
        self._rng_cell = None
        self._rd_count = 0

    def commit(self):
        """Make the current VM-private state the starting point of every later call."""
        pages = {page: bytes(self.uc.mem_read(page, PAGE)) for page in self.dirty}
        self._baseline = Baseline(self.heap_top, bytes(self.uc.mem_read(HEAP, self.heap_top - HEAP)),
                                  dict(self.allocations), pages, dict(self.dirty), self._tlv_block,
                                  dict(self._fpos), getattr(self, '_ticks', TICKS_START))

    def reset(self):
        """Drop the baseline: back to the pristine snapshot of live memory."""
        self._baseline = None
        self._restore()
        super()._restore()

    def invalidate(self):
        self._baseline = None
        super().invalidate()
        self._live_import(0)                 # rebuild from live values before the overlays
        self._apply_native_slots()

    # ------------------------------------------------------------------ externals
    def _external(self, name):
        model = self._resolve(name)           # UI models, then PropertyVM's whitelist
        if model is None:
            try:
                return super()._external(name)
            except _Stop as stop:
                # Name the shipped call site (return address) of every refused external.
                lr = self.uc.reg_read(A.UC_ARM64_REG_LR) - 4 - self.base
                stop.detail = f'{stop.detail} at {lr:#x}'
                raise
        self.stubbed[name] += 1
        if self._call is not None:
            self._call.externals.append(name)
        model(self)

    # ------------------------------------------------------------------ helpers
    def heap_bytes(self, data: bytes, align=16) -> int:
        """Place bytes on the VM heap (part of the next commit)."""
        address = self.alloc(len(data), align)
        self.uc.mem_write(address, bytes(data))
        return address

    def null_value(self) -> int:
        """A fresh NULL typed value on the VM heap."""
        return self.heap_bytes(struct.pack('<QQ', self.registry + 8, 0))

    def ui_record(self, record: dict) -> int:
        """A UI_RECORD {begin, end, cap, u32 flags} with sorted (u32 key, u32 value) pairs."""
        pairs = sorted((fourcc(k) if isinstance(k, str) else k, v & 0xFFFFFFFF) for k, v in record.items())
        body = b''.join(struct.pack('<II', k, v) for k, v in pairs) or b'\0' * 8
        begin = self.heap_bytes(body, 8)
        end = begin + 8 * len(pairs)
        return self.heap_bytes(struct.pack('<QQQI4x', begin, end, end, 0))

    def vcall(self, obj: int, slot: int, args=(), *, x8=None):
        """Call obj->vtable[slot](obj, *args) (x8 = indirect result pointer if given)."""
        vtable = self.read_u64(obj)
        target = self.read_u64(vtable + 8 * slot)
        regs = [obj, *args]
        if x8 is not None:
            regs += [0] * (8 - len(regs))
            regs.append(x8)
        return self.call(target, regs)

    def backtrace(self, depth=12):
        """Shipped return addresses (RVAs) on the frame-pointer chain at the last stop."""
        out = [self.uc.reg_read(A.UC_ARM64_REG_PC) - self.base]
        fp = self.uc.reg_read(A.UC_ARM64_REG_X29)
        for _ in range(depth):
            if not fp:
                break
            try:
                fp, lr = struct.unpack('<QQ', bytes(self.uc.mem_read(fp, 16)))
            except Exception:  # noqa: BLE001
                break
            if not lr:
                break
            out.append(lr - 4 - self.base)
        return [f'{a:#x}' for a in out]

    def class_name(self, obj: int) -> str | None:
        """Short class name of an object (e.g. 'TEAM_CONFIDENCE_UI_HANDLER', 'TEAM')."""
        return short_class(self.rtti_name(self.read_u64(obj)))

    def object_ref(self, obj: int) -> int:
        """The u32 UI object id of a database object, from its own virtual +0x88 (slot 17).

        The server code turns objects into UI values the same way (e.g. 0x5520D8:
        `blr [vtable+0x88]` into an 8-byte {u32 id, ...} result, then 0x11B8784). The id
        is `table type << 24 | index` (packer 0x11B8B0C; resolver 0x111344C)."""
        out = self.heap_bytes(b'\0' * 32)
        self.commit()
        self.vcall(obj, OBJECT_REF_SLOT, (), x8=out)
        value = struct.unpack('<I', self.read(out, 4))[0]
        self.reset()
        return value

    def decode(self, address):
        try:
            kind, value = variant.decode(self, address)
            if kind and UI_RECORD_KIND in kind:
                kind = 'ui_record'
            return kind, self._ui_records(value)
        except _Stop as stop:
            return None, Unavailable('variant decode fault: ' + stop.reason, detail=stop.detail)

    def _ui_records(self, value, depth=0):
        """Decode nested siuihandler::UI_RECORD values (variant kind 34), which variant.py
        leaves as Unavailable with the raw bytes: payload -> UI_RECORD {begin, end, cap, u32}
        of sorted (u32 key, u32 value) pairs, returned as UiRecord({fourcc: u32})."""
        if depth > 8:
            return value
        if isinstance(value, Unavailable) and UI_RECORD_KIND in (value.reason or '') and value.raw:
            payload = struct.unpack_from('<Q', value.raw, 8)[0]
            begin, end, cap = struct.unpack('<QQQ', self.read(payload, 24))
            if begin == end:
                return UiRecord()
            if end < begin or (end - begin) % 8 or (end - begin) > 8 * 4096 or cap < end:
                return value
            pairs = struct.unpack(f'<{(end - begin) // 4}I', self.read(begin, end - begin))
            return UiRecord({fourcc_text(pairs[i]): pairs[i + 1] for i in range(0, len(pairs), 2)})
        if isinstance(value, list):
            return [self._ui_records(v, depth + 1) for v in value]
        if isinstance(value, dict) and not isinstance(value, UiRecord):
            return {k: self._ui_records(v, depth + 1) for k, v in value.items()}
        return value

    # ------------------------------------------------------------------ handler life cycle
    def factory(self) -> int:
        """A VM-private GAME_UI_HANDLER_FACTORY object (its methods do not use `this` state)."""
        if not hasattr(self, '_factory'):
            self._factory = self._static(struct.pack('<QQ', self.base + FACTORY_VTABLE_RVA, 0))
        return self._factory

    def build(self, handler_type: int, record: dict | None = None, *, server=True,
              client=True) -> Handler:
        """Construct client (and server) handlers for a UI_RECORD; commits the result."""
        started = time.perf_counter()
        self.reset()
        fields = dict(record or {})
        fields[TYPE_KEY] = handler_type
        icount = 0
        rec = self.ui_record(fields)
        out = self.heap_bytes(b'\0' * 16)
        self.commit()
        client_obj = None
        if client:
            _, stats = self.vcall(self.factory(), CLIENT_FACTORY_SLOT, (rec,), x8=out)
            icount += stats.instructions
            client_obj = self.read_u64(out)
            if not client_obj:
                raise _Stop('factory made no client handler', f'type {handler_type}')
            self.commit()
        server_obj = None
        if server:
            _, stats = self.vcall(self.factory(), SERVER_FACTORY_SLOT, (rec,), x8=out + 8)
            icount += stats.instructions
            server_obj = self.read_u64(out + 8) or None
            if server_obj:
                # The server's UI_RECORD lives at +0x10; the factory leaves it empty and the
                # caller copies the record in (see UI_HANDLERS.md). Point it at ours.
                self.write(server_obj + SERVER_RECORD_OFFSET, self.read(rec, 24))
            self.commit()
        handler = Handler(handler_type, {k if isinstance(k, str) else fourcc_text(k): v
                                         for k, v in fields.items()},
                          client_obj, server_obj, self.class_name(client_obj) if client_obj else None,
                          self.class_name(server_obj) if server_obj else None)
        handler.build_seconds = time.perf_counter() - started
        handler.build_instructions = icount
        return handler

    def server_value(self, handler: Handler, key, context=0):
        """Run server slot 2 for one key; returns (handled, typed value address, stats)."""
        number = fourcc(key) if isinstance(key, str) else key
        out = self.null_value()
        ctx = context or self.heap_bytes(b'\0' * 64)
        self.commit()
        returned, stats = self.vcall(handler.server, SERVER_GET_SLOT, (number, out, ctx))
        return bool(returned & 1), out, stats

    def feed(self, handler: Handler, key, value_address: int):
        """Run client slot 17 with a typed value; commits the handler state."""
        number = fourcc(key) if isinstance(key, str) else key
        notify = self.heap_bytes(b'\0' * 64)
        self.commit()
        returned, stats = self.vcall(handler.client, CLIENT_INPUT_SLOT,
                                     (number, value_address, 0, notify, 0))
        self.commit()
        return returned, stats

    def transfer(self, handler: Handler, key) -> str:
        """Server -> client transfer of one input key (the game's own exchange)."""
        try:
            handled, value, stats = self.server_value(handler, key)
            self.commit()
            kind, _ = self.decode(value)
            self.feed(handler, key, value)
            status = f'ok ({kind}, server {stats.instructions} insns)'
        except _Stop as stop:
            trace = self.backtrace()
            spent = self._icount
            self.reset_to_last()
            status = (f'unavailable: {stop.reason} {stop.detail or ""} after {spent} insns '
                      f'[{" < ".join(trace)}]')
        handler.inputs[key if isinstance(key, str) else fourcc_text(key)] = status
        return status

    def reset_to_last(self):
        """After a failed call: return to the last committed baseline."""
        self._restore()

    def get(self, handler: Handler, key) -> PropertyResult:
        """Client slot 4 for one key, from the committed handler state."""
        code = key if isinstance(key, str) else fourcc_text(key)
        number = fourcc(key) if isinstance(key, str) else key
        stats = CallStats()
        try:
            self._restore()
            request = self.alloc(REQUEST_SIZE)
            self.uc.mem_write(request, b'\0' * REQUEST_SIZE)
            self.uc.mem_write(request + REQUEST_KEY_OFFSET, struct.pack('<I', number))
            out = self.alloc(16)
            self.uc.mem_write(out, struct.pack('<QQ', self.registry + 8, 0))
            inputs = self.alloc(64)
            self.uc.mem_write(inputs, b'\0' * 64)
            # These allocations are made after _restore, so call() would roll them back;
            # keep them by committing first.
            self.commit()
            returned, stats = self.vcall(handler.client, CLIENT_GET_SLOT, (request, out, inputs))
        except _Stop as stop:
            self.last_trace = self.backtrace()
            stats = getattr(self, 'last_stats', None) or stats
            return PropertyResult(code, Unavailable(stop.reason, detail=stop.detail), None, None, stats)
        kind, value = self.decode(out)
        return PropertyResult(code, value, kind, bool(returned & 1), stats)
