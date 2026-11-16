"""Read-only access to a running process's memory on Windows.

``WindowsMemory`` is the Windows counterpart of ``memory.LiveMemory`` (part 4 of the platform
boundary in ``platform_model.py``). It inherits LiveMemory's read interface and page cache and
replaces only the transport: there is no helper process, the reads are ``ReadProcessMemory``
calls made from this interpreter through ctypes. Windows lets a process read another process of
the same user (or any process, as an administrator), so nothing is loaded into the game.

Differences from macOS that callers can see:

* ``page_size`` is the system page size (4096), not 16384.
* ``Region.protection`` uses the same three bits as macOS (read 1, write 2, execute 4), mapped
  from the Windows page protection; a guard or no-access page has protection 0.
  ``Region.user_tag`` carries the Windows region type (``MEM_IMAGE``, ``MEM_MAPPED``,
  ``MEM_PRIVATE``); only committed regions are listed. ``pages_resident`` is always 0.
* ``modules()`` lists the loaded images with their load addresses, which is how a plugin's base
  is found here (macOS matches the Mach-O UUID instead).

The handle is opened with query and read rights only; this module never writes to the target.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from collections.abc import Sequence
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import PureWindowsPath

from .memory import (
    ST_OK, ST_PATH_MISMATCH, ST_READ_FAILED, VM_PROT_EXECUTE, VM_PROT_READ, VM_PROT_WRITE,
    LiveMemory, MemoryReadError, ProcessGoneError, Region, Stats, _join_windows,
)

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
# Windows flag bits at or above 0x10000 are written as shifts: the address census
# (address_census.py) treats a hex literal in the game image's range as a possible game address.
SYNCHRONIZE = 1 << 20

MEM_COMMIT = 0x1000
MEM_PRIVATE, MEM_MAPPED, MEM_IMAGE = 1 << 17, 1 << 18, 1 << 24

PAGE_GUARD = 0x100
_PROTECTION = {
    0x01: 0,                                                    # PAGE_NOACCESS
    0x02: VM_PROT_READ,                                         # PAGE_READONLY
    0x04: VM_PROT_READ | VM_PROT_WRITE,                         # PAGE_READWRITE
    0x08: VM_PROT_READ | VM_PROT_WRITE,                         # PAGE_WRITECOPY
    0x10: VM_PROT_EXECUTE,                                      # PAGE_EXECUTE
    0x20: VM_PROT_READ | VM_PROT_EXECUTE,                       # PAGE_EXECUTE_READ
    0x40: VM_PROT_READ | VM_PROT_WRITE | VM_PROT_EXECUTE,       # PAGE_EXECUTE_READWRITE
    0x80: VM_PROT_READ | VM_PROT_WRITE | VM_PROT_EXECUTE,       # PAGE_EXECUTE_WRITECOPY
}

LIST_MODULES_ALL = 3
WAIT_OBJECT_0 = 0
MAX_PATH_WIDE = 32768


def protection_bits(protect: int) -> int:
    """macOS-style read/write/execute bits for a Windows page protection value."""
    if protect & PAGE_GUARD:
        return 0
    return _PROTECTION.get(protect & 0xFF, 0)


class _MemoryBasicInformation(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_uint64),
        ("AllocationBase", ctypes.c_uint64),
        ("AllocationProtect", wintypes.DWORD),
        ("PartitionId", wintypes.WORD),
        ("RegionSize", ctypes.c_uint64),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


class _ModuleInfo(ctypes.Structure):
    _fields_ = [
        ("lpBaseOfDll", ctypes.c_void_p),
        ("SizeOfImage", wintypes.DWORD),
        ("EntryPoint", ctypes.c_void_p),
    ]


class _SystemInfo(ctypes.Structure):
    _fields_ = [
        ("wProcessorArchitecture", wintypes.WORD),
        ("wReserved", wintypes.WORD),
        ("dwPageSize", wintypes.DWORD),
        ("lpMinimumApplicationAddress", ctypes.c_void_p),
        ("lpMaximumApplicationAddress", ctypes.c_void_p),
        ("dwActiveProcessorMask", ctypes.c_size_t),
        ("dwNumberOfProcessors", wintypes.DWORD),
        ("dwProcessorType", wintypes.DWORD),
        ("dwAllocationGranularity", wintypes.DWORD),
        ("wProcessorLevel", wintypes.WORD),
        ("wProcessorRevision", wintypes.WORD),
    ]


@dataclass(frozen=True)
class Module:
    """One image loaded in the target: its load address, mapped size and file path."""

    base: int
    size: int
    path: str

    @property
    def name(self) -> str:
        return PureWindowsPath(self.path).name

    @property
    def end(self) -> int:
        return self.base + self.size


_API = None


def _api():
    """kernel32 with the argument types this module uses, bound once."""
    global _API
    if _API is None:
        if sys.platform != "win32":
            raise MemoryReadError("WindowsMemory needs Windows; this is " + sys.platform)
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            raise MemoryReadError("WindowsMemory needs a 64-bit Python to read a 64-bit game")
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        handle, dword, size_t, void_p = wintypes.HANDLE, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p
        k.OpenProcess.argtypes, k.OpenProcess.restype = (dword, wintypes.BOOL, dword), handle
        k.CloseHandle.argtypes, k.CloseHandle.restype = (handle,), wintypes.BOOL
        k.ReadProcessMemory.argtypes = (handle, void_p, void_p, size_t, ctypes.POINTER(size_t))
        k.ReadProcessMemory.restype = wintypes.BOOL
        k.VirtualQueryEx.argtypes = (handle, void_p, ctypes.POINTER(_MemoryBasicInformation), size_t)
        k.VirtualQueryEx.restype = size_t
        k.WaitForSingleObject.argtypes, k.WaitForSingleObject.restype = (handle, dword), dword
        k.GetSystemInfo.argtypes, k.GetSystemInfo.restype = (ctypes.POINTER(_SystemInfo),), None
        k.QueryFullProcessImageNameW.argtypes = (handle, dword, wintypes.LPWSTR, ctypes.POINTER(dword))
        k.QueryFullProcessImageNameW.restype = wintypes.BOOL
        k.K32EnumProcesses.argtypes = (ctypes.POINTER(dword), dword, ctypes.POINTER(dword))
        k.K32EnumProcesses.restype = wintypes.BOOL
        k.K32EnumProcessModulesEx.argtypes = (handle, ctypes.POINTER(void_p), dword, ctypes.POINTER(dword), dword)
        k.K32EnumProcessModulesEx.restype = wintypes.BOOL
        k.K32GetModuleFileNameExW.argtypes = (handle, void_p, wintypes.LPWSTR, dword)
        k.K32GetModuleFileNameExW.restype = dword
        k.K32GetModuleInformation.argtypes = (handle, void_p, ctypes.POINTER(_ModuleInfo), dword)
        k.K32GetModuleInformation.restype = wintypes.BOOL
        _API = k
    return _API


def _last_error(action: str) -> str:
    code = ctypes.get_last_error()
    return f"{action}: {ctypes.FormatError(code).strip()} (Windows error {code})"


def _image_path(api, handle) -> str:
    size = wintypes.DWORD(MAX_PATH_WIDE)
    buffer = ctypes.create_unicode_buffer(size.value)
    if not api.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
        return ""
    return buffer.value


def processes() -> list[tuple[int, str]]:
    """(pid, executable path) of every process; the path is '' where Windows refuses the query."""
    api = _api()
    count = 4096
    while True:
        pids = (wintypes.DWORD * count)()
        used = wintypes.DWORD()
        if not api.K32EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(used)):
            raise MemoryReadError(_last_error("cannot list processes"))
        if used.value < ctypes.sizeof(pids):
            break
        count *= 2
    found = []
    for pid in pids[:used.value // ctypes.sizeof(wintypes.DWORD)]:
        if not pid:
            continue
        handle = api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            found.append((pid, ""))
            continue
        try:
            found.append((pid, _image_path(api, handle)))
        finally:
            api.CloseHandle(handle)
    return found


def find_processes(*names: str) -> list[tuple[int, str]]:
    """The running processes whose executable file name is one of `names` (case-insensitive)."""
    wanted = {name.lower() for name in names}
    return [(pid, path) for pid, path in processes() if path and PureWindowsPath(path).name.lower() in wanted]


class WindowsMemory(LiveMemory):
    """LiveMemory over ``ReadProcessMemory``. Context manager; ``close()`` releases the handle."""

    def __init__(self, pid: int, *, expected_executable: str | None = None,
                 max_cache_pages: int | None = None):
        api = _api()
        self.pid = pid
        self.timeout = 0.0
        self.max_cache_pages = max_cache_pages
        self.stats = Stats()
        self.helper = None
        self.route = "read_process_memory"
        self._lock = threading.RLock()
        self._cache: dict[int, bytes] = {}
        self._bad_pages: set[int] = set()
        self._regions: list[Region] | None = None
        self._modules: list[Module] | None = None
        self._child = None
        self._closed = False
        info = _SystemInfo()
        api.GetSystemInfo(ctypes.byref(info))
        self.page_size = info.dwPageSize
        self._address_limit = info.lpMaximumApplicationAddress or 0x7FFFFFFEFFFF
        self._handle = api.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION | SYNCHRONIZE, False, pid)
        if not self._handle:
            self._closed = True
            raise MemoryReadError(_last_error(f"cannot open process {pid} for reading"))
        self.executable = _image_path(api, self._handle)
        if expected_executable is not None and self.executable.lower() != str(expected_executable).lower():
            self.close()
            raise MemoryReadError(f"process {pid} runs {self.executable!r}, not {expected_executable!r}",
                                  ST_PATH_MISMATCH)

    @classmethod
    def attach(cls, *names: str, **kwargs) -> "WindowsMemory":
        """Attach to the first running process whose executable is named one of `names`."""
        found = find_processes(*names)
        if not found:
            raise MemoryReadError(f"no running process named {' or '.join(names)}")
        pid, path = found[0]
        return cls(pid, expected_executable=path, **kwargs)

    # -- transport ---------------------------------------------------------------

    def _exited(self) -> bool:
        return _api().WaitForSingleObject(self._handle, 0) == WAIT_OBJECT_0

    def _open_handle(self):
        if self._closed:
            raise MemoryReadError("WindowsMemory is closed")
        return self._handle

    def _gone(self) -> None:
        raise ProcessGoneError(f"process {self.pid} has exited")

    def _readv(self, items: Sequence[tuple[int, int]]) -> list[tuple[int, bytes | None]]:
        """One ReadProcessMemory call per item. An item is whole or failed, as on macOS: Windows
        fails the call when any byte of the range is unreadable."""
        with self._lock:
            handle = self._open_handle()
            read = _api().ReadProcessMemory
            got = ctypes.c_size_t()
            got_ref = ctypes.byref(got)
            results: list[tuple[int, bytes | None]] = []
            total = failed = 0
            started = time.monotonic()
            for address, length in items:
                buffer = ctypes.create_string_buffer(length)
                if read(handle, address, buffer, length, got_ref) and got.value == length:
                    results.append((ST_OK, buffer.raw))
                    total += length
                else:
                    results.append((ST_READ_FAILED, None))
                    failed += 1
            if failed and self._exited():
                self._gone()
            self.stats.round_trips += 1
            self.stats.seconds += time.monotonic() - started
            self.stats.items += len(items)
            self.stats.bytes += total
            self.stats.failed_items += failed
            return results

    def _windows_scatter(self, addresses: Sequence[int], length: int) -> tuple[bytes, list[int]]:
        return _join_windows(self.read_many([(a, length) for a in addresses]), length)

    # -- regions and modules -----------------------------------------------------

    def regions(self, *, refresh: bool = False) -> list[Region]:
        """The target's committed regions, sorted by address."""
        if self._regions is None or refresh:
            with self._lock:
                handle = self._open_handle()
                query = _api().VirtualQueryEx
                info = _MemoryBasicInformation()
                size = ctypes.sizeof(info)
                found, address = [], 0
                while address < self._address_limit:
                    if not query(handle, address, ctypes.byref(info), size):
                        break
                    if info.State == MEM_COMMIT:
                        found.append(Region(info.BaseAddress, info.RegionSize, protection_bits(info.Protect),
                                            protection_bits(info.AllocationProtect), info.Type, 0))
                    following = info.BaseAddress + info.RegionSize
                    if following <= address:
                        break
                    address = following
                if not found and self._exited():
                    self._gone()
                self._regions = found
        return list(self._regions)

    def modules(self, *, refresh: bool = False) -> list[Module]:
        """Images loaded in the target, in load order (the executable first)."""
        if self._modules is None or refresh:
            with self._lock:
                handle = self._open_handle()
                api = _api()
                count = 1024
                while True:
                    handles = (ctypes.c_void_p * count)()
                    needed = wintypes.DWORD()
                    if not api.K32EnumProcessModulesEx(handle, handles, ctypes.sizeof(handles),
                                                       ctypes.byref(needed), LIST_MODULES_ALL):
                        if self._exited():
                            self._gone()
                        raise MemoryReadError(_last_error(f"cannot list the modules of process {self.pid}"))
                    used = needed.value // ctypes.sizeof(ctypes.c_void_p)
                    if used <= count:
                        break
                    count = used
                found = []
                path = ctypes.create_unicode_buffer(MAX_PATH_WIDE)
                info = _ModuleInfo()
                for module in handles[:used]:
                    if not module:
                        continue
                    if not api.K32GetModuleInformation(handle, module, ctypes.byref(info), ctypes.sizeof(info)):
                        continue
                    length = api.K32GetModuleFileNameExW(handle, module, path, MAX_PATH_WIDE)
                    found.append(Module(info.lpBaseOfDll or 0, info.SizeOfImage, path.value if length else ""))
                self._modules = found
        return list(self._modules)

    def module(self, name: str) -> Module | None:
        """The loaded image with this file name (case-insensitive), or None."""
        wanted = name.lower()
        return next((m for m in self.modules() if m.name.lower() == wanted), None)

    def invalidate(self) -> None:
        super().invalidate()
        self._modules = None

    # -- lifecycle ---------------------------------------------------------------

    def ping(self) -> bool:
        return not self._closed and not self._exited()

    def close(self) -> None:
        """Idempotent. Releases the process handle."""
        with self._lock:
            if not self._closed:
                self._closed = True
                _api().CloseHandle(self._handle)
            self._cache.clear()
