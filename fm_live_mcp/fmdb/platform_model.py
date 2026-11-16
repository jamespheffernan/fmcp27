"""The platform boundary of the reader: what it needs from "the operating system, the binary
format, the C++ ABI and the instruction set", in one place.

Today there is one implementation, macOS ARM64 (`platform_macos_arm64.py`: Mach-O, chained
fixups or LC_DYLD_INFO, Itanium RTTI, AArch64, `fm_fast_reader`/task ports). A Windows x86-64
build of the game would need a second implementation of the same five parts (PE/COFF, MSVC
RTTI, x86-64, ReadProcessMemory, the Windows x64 calling convention); nothing above this
boundary should have to change. No Windows code exists.

The five parts
--------------

1. Image model (`BinaryModel`, image half): load a plugin file and answer by RVA: bytes as
   stored on disk, the function containing an address (`function_of`, `starts`), which
   addresses are code, the import called by a stub, rebased pointer slots (`pointer`), the
   writable data range (`data_range`), the image end, the sha256 and version.
2. Type model (`BinaryModel`, RTTI half): type names are compared through `type_key(name)`,
   which maps the canonical key the modules use (Itanium mangling, e.g. `N2db6PERSONE`) to the
   platform's own spelling (MSVC: `.?AVPERSON@db@@`). `vtables` {type: [(address point,
   subobject offset)]}, `vtable(type, offset)`, `slot(vtable, i)`, `class_name(vtable)`,
   `base_offset(type, base)` (virtual bases included). Itanium and MSVC both put the vtable
   pointer at offset 0 of an object and both keep per-class type descriptors reachable from
   the vtable (vtable[-1] on Itanium, the COL at vtable[-1] on MSVC).
3. Code model (`BinaryModel`, instruction half): page references (`refs`: target ->
   [(site, use, kind)] with kinds `add`, `ldr<bits>`, `str<bits>`; `refs_in`), calls (`calls`,
   `callees`, `stub_for`), the address-independent function `fingerprint`, and the named
   shape questions the anchor recipes ask: `fourcc_constants(fn)`, `first_branch_target(fn)`,
   `constant_return_functions(value)`, `virtual_bool_check_globals(slot)`,
   `call_result_stores(import)`, `loads_by_width(bits)`. The recipes in anchors.py never decode
   an instruction themselves.
4. Process access (`ProcessAccess`): open a process, list regions, read, read many ranges in
   one call, find the load address of a given image (`find_plugin_base`: by Mach-O UUID here;
   by PE timestamp/size or the module list on Windows). `memory.LiveMemory` implements it on
   macOS through the native helper.
5. Calling convention (`CallingConvention`): which registers carry `this`, the arguments and
   the result, the link register and the stack pointer, for the emulator (`vm.py`, `fastvm.py`,
   `ui_vm.py` use AAPCS64 directly today) and for the 25 modelled external functions (libc,
   libc++, pthread, libm). Those models are platform-specific too: a Windows implementation
   models the MSVC runtime instead.

What stays platform-independent: the anchor recipes and the pinned anchor names (anchors.py),
plans and their verification (bulkplans.py, plancompile.py), the snapshot and everything above.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol


class PlatformError(RuntimeError):
    """No platform implementation for this file or process."""


class BinaryModel(Protocol):
    """Image + type + code model of one game plugin binary (parts 1-3 above)."""

    path: Path
    sha256: str
    starts: list
    pointer_size: int

    # image
    def version(self) -> str | None: ...
    def is_code(self, rva: int) -> bool: ...
    def function_of(self, rva: int) -> tuple[int, int] | None: ...
    def pointer(self, slot: int) -> int | None: ...
    def data_range(self) -> tuple[int, int]: ...
    def image_end(self) -> int: ...
    def stub_for(self, name: str) -> int | None: ...

    # types
    def type_key(self, canonical: str) -> str: ...
    vtables: dict
    def vtable(self, type_name: str, offset: int = 0) -> int | None: ...
    def slot(self, vtable: int, index: int) -> int | None: ...
    def class_name(self, vtable: int) -> str | None: ...
    def base_offset(self, type_name: str, base_name: str) -> int | None: ...

    # code
    refs: dict
    calls: dict
    def refs_in(self, start: int, end: int) -> list: ...
    def fingerprint(self, start: int, end: int | None = None) -> tuple[int, str]: ...
    def find_fingerprint(self, fp) -> list: ...
    def fourcc_constants(self, start: int, limit: int = 4096) -> set: ...
    def first_branch_target(self, start: int, window: int = 4) -> int | None: ...
    def constant_return_functions(self, value: int) -> list: ...
    def virtual_bool_check_globals(self, slot: int) -> dict: ...
    def call_result_stores(self, import_name: str) -> list: ...
    def loads_by_width(self, bits: int): ...


class ProcessAccess(Protocol):
    """Live process memory, read-only (part 4)."""

    def regions(self) -> list: ...
    def read(self, address: int, length: int) -> bytes: ...
    def read_many(self, requests: Iterable[tuple[int, int]]) -> list: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class CallingConvention:
    """Register roles for emulated calls (part 5)."""

    name: str
    this: str
    args: tuple
    result: str
    float_args: tuple
    float_result: str
    link: str | None
    stack: str


AAPCS64 = CallingConvention('AAPCS64 (macOS ARM64)', 'x0', ('x0', 'x1', 'x2', 'x3', 'x4', 'x5', 'x6', 'x7'),
                            'x0', ('d0', 'd1', 'd2', 'd3', 'd4', 'd5', 'd6', 'd7'), 'd0', 'x30', 'sp')
WIN64 = CallingConvention('Microsoft x64 (Windows, for reference only; no implementation)', 'rcx',
                          ('rcx', 'rdx', 'r8', 'r9'), 'rax', ('xmm0', 'xmm1', 'xmm2', 'xmm3'), 'xmm0', None, 'rsp')


def load_binary(path) -> BinaryModel:
    """The platform model of a plugin file, chosen by its header."""
    path = Path(path)
    with path.open('rb') as stream:
        magic = stream.read(4)
    if magic in (b'\xca\xfe\xba\xbe', b'\xcf\xfa\xed\xfe'):
        from .platform_macos_arm64 import Binary
        return Binary(path)
    if magic[:2] == b'MZ':
        raise PlatformError(f'{path.name} is a Windows PE image; there is no Windows platform model yet')
    raise PlatformError(f'{path.name}: unknown binary format {magic.hex()}')


def open_process(binary: BinaryModel, pid: int | None = None):
    """(ProcessAccess, load address of `binary`) for a running game, or (None, reason)."""
    from .platform_macos_arm64 import open_live
    return open_live(binary, pid)
