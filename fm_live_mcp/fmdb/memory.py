"""Fast, read-only bulk access to a running game's memory via ``fm_fast_reader``.

``LiveMemory`` owns one persistent ``fm_fast_reader`` subprocess (attached once with
``task_for_pid``) and speaks its binary protocol (see ``native/fm_fast_reader.c``):

    request : u32 magic 'FMRQ', u32 op, u32 count, count x {u64 address, u32 length}
    response: u32 magic 'FMRS', u32 status, u32 count,
              READV   -> count x {u32 item_status, u32 length}, then the payloads
              REGIONS -> count x {u64 start, u64 size, u32 prot, u32 max_prot, u32 user_tag, u32 pages_resident}

``SnapshotMemory`` offers the same read interface over a dict of pages, for tests and
emulators. Both derive from ``MemoryBase``, which holds the decode helpers.
"""

from __future__ import annotations

import os
import select
import struct
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

REQ_MAGIC = 0x51524D46
RESP_MAGIC = 0x53524D46
HELLO_MAGIC = 0x4C484D46
PROTOCOL_VERSION = 1

OP_READV, OP_PING, OP_QUIT, OP_REGIONS = 1, 2, 3, 4

ST_OK = 0
ST_BAD_MAGIC = 1
ST_BAD_OP = 2
ST_TOO_MANY_ITEMS = 3
ST_BATCH_TOO_LARGE = 4
ST_ITEM_TOO_LARGE = 5
ST_READ_FAILED = 6
ST_PARTIAL = 7
ST_PROCESS_GONE = 8
ST_BAD_ADDRESS = 9
ST_NO_MEMORY = 10
ST_ATTACH_FAILED = 11
ST_PATH_MISMATCH = 12
ST_BAD_LENGTH = 13

STATUS_NAMES = {
    ST_OK: "ok", ST_BAD_MAGIC: "bad_magic", ST_BAD_OP: "bad_op",
    ST_TOO_MANY_ITEMS: "too_many_items", ST_BATCH_TOO_LARGE: "batch_too_large",
    ST_ITEM_TOO_LARGE: "item_too_large", ST_READ_FAILED: "read_failed",
    ST_PARTIAL: "partial_read", ST_PROCESS_GONE: "process_gone",
    ST_BAD_ADDRESS: "bad_address", ST_NO_MEMORY: "no_memory",
    ST_ATTACH_FAILED: "attach_failed", ST_PATH_MISMATCH: "path_mismatch",
    ST_BAD_LENGTH: "bad_length",
}

# The hello's mach_code field carries the attach route on success (see
# native/fm_fast_reader.c: FMCP_ROUTE_IS_*). 0 stays task_for_pid for old readers.
ROUTE_NAMES = {0: "task_for_pid", 1: "injected"}

MAX_ITEM_BYTES = 16 * 1024 * 1024
MAX_BATCH_BYTES = 256 * 1024 * 1024
MAX_BATCH_ITEMS = 1_000_000
DEFAULT_TIMEOUT = 45.0
DEFAULT_PAGE_SIZE = 16384

ROOT = Path(__file__).resolve().parents[2]

_HELLO = struct.Struct("<7I")
_HEADER = struct.Struct("<3I")
_ITEM = struct.Struct("<QI")
_RESULT = struct.Struct("<II")
_REGION = struct.Struct("<QQIIII")

VM_PROT_READ, VM_PROT_WRITE, VM_PROT_EXECUTE = 1, 2, 4


class MemoryReadError(RuntimeError):
    """A memory read or the helper transport failed."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ProcessGoneError(MemoryReadError):
    """The target process (or the helper) is gone."""


def launch_fix() -> tuple[str, bool]:
    """How to start the game so the in-game library is loaded, and whether this is the Mac
    download (whose launcher sits at its top, and whose README gives the Steam launch line)."""
    launcher = Path(__file__).resolve().parents[2] / 'fm_launch.sh'
    if not launcher.is_file():
        return 'start the game with the FMCP launcher (scripts/fm_launch.sh, or that file as the Steam launch option)', False
    line, home = str(launcher), str(Path.home())
    if line.startswith(home + '/'):
        line = '~' + line[len(home):]
    return ("in Steam set Football Manager 27 > Properties > General > Launch Options to  "
            f"{line} %command%  and start the game from Steam"), True


def status_name(status: int) -> str:
    return STATUS_NAMES.get(status, f"status_{status}")


@dataclass(frozen=True)
class Region:
    start: int
    size: int
    protection: int
    max_protection: int
    user_tag: int = 0
    pages_resident: int = 0

    @property
    def end(self) -> int:
        return self.start + self.size

    @property
    def readable(self) -> bool:
        return bool(self.protection & VM_PROT_READ)

    @property
    def writable(self) -> bool:
        return bool(self.protection & VM_PROT_WRITE)

    @property
    def executable(self) -> bool:
        return bool(self.protection & VM_PROT_EXECUTE)

    def contains(self, address: int, length: int = 1) -> bool:
        return self.start <= address and address + length <= self.end


@dataclass
class Stats:
    round_trips: int = 0
    items: int = 0
    bytes: int = 0
    seconds: float = 0.0
    failed_items: int = 0
    cache_hits: int = 0
    cache_misses: int = 0

    @property
    def items_per_second(self) -> float:
        return self.items / self.seconds if self.seconds else 0.0

    @property
    def mib_per_second(self) -> float:
        return self.bytes / (1024 * 1024) / self.seconds if self.seconds else 0.0


class MemoryBase:
    """Shared read interface. Decode helpers read through ``cached_read``.

    Decoders (``u8`` ... ``pointer``) use the page cache, so repeated decodes of nearby
    fields cost one batched page fault in total. Call ``invalidate()`` (or use ``read``)
    when you need fresh bytes from the live process.
    """

    page_size: int = DEFAULT_PAGE_SIZE

    def read(self, address: int, length: int) -> bytes:  # pragma: no cover - interface
        raise NotImplementedError

    def read_many(self, requests: Sequence[tuple[int, int]]) -> list[bytes | None]:  # pragma: no cover
        raise NotImplementedError

    def page(self, address: int) -> bytes:  # pragma: no cover
        raise NotImplementedError

    def cached_read(self, address: int, length: int) -> bytes:  # pragma: no cover
        raise NotImplementedError

    def regions(self) -> list[Region]:  # pragma: no cover
        raise NotImplementedError

    def invalidate(self) -> None:  # pragma: no cover
        raise NotImplementedError

    def page_base(self, address: int) -> int:
        return address & ~(self.page_size - 1)

    def windows(self, addresses: Sequence[int], length: int) -> tuple[bytes, list[int]]:
        """`length` bytes at every address as one buffer with a fixed stride (`length`), and the
        positions that could not be read (their bytes are zero). Bulk decoders unpack the buffer
        with one `struct.iter_unpack` instead of handling one `bytes` object per address."""
        return _join_windows(self.read_many([(a, length) for a in addresses]), length)

    def _unpack(self, fmt: struct.Struct, address: int):
        return fmt.unpack(self.cached_read(address, fmt.size))[0]

    def u8(self, address: int) -> int:
        return self._unpack(_U8, address)

    def u16(self, address: int) -> int:
        return self._unpack(_U16, address)

    def u32(self, address: int) -> int:
        return self._unpack(_U32, address)

    def u64(self, address: int) -> int:
        return self._unpack(_U64, address)

    def i8(self, address: int) -> int:
        return self._unpack(_I8, address)

    def i16(self, address: int) -> int:
        return self._unpack(_I16, address)

    def i32(self, address: int) -> int:
        return self._unpack(_I32, address)

    def i64(self, address: int) -> int:
        return self._unpack(_I64, address)

    def f32(self, address: int) -> float:
        return self._unpack(_F32, address)

    def pointer(self, address: int) -> int:
        """A 64-bit little-endian pointer value (same as ``u64``)."""
        return self._unpack(_U64, address)

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        pass


_U8, _U16, _U32, _U64 = (struct.Struct(f) for f in ("<B", "<H", "<I", "<Q"))
_I8, _I16, _I32, _I64 = (struct.Struct(f) for f in ("<b", "<h", "<i", "<q"))
_F32 = struct.Struct("<f")


def _join_windows(items, length: int) -> tuple[bytes, list[int]]:
    bad = [k for k, data in enumerate(items) if data is None]
    if bad:
        zero = bytes(length)
        items = [zero if data is None else data for data in items]
    return b''.join(items), bad


WINDOW_PAGE_RATIO = 6      # read whole pages when they hold at most this many times the bytes asked for


def _check_range(address: int, length: int) -> None:
    if (type(address) is not int or type(length) is not int
            or length < 1 or address < 1 or address > 2**64 - length):
        raise MemoryReadError(f"invalid read of {length!r} bytes at {address!r}")


class LiveMemory(MemoryBase):
    """Context manager owning one ``fm_fast_reader`` subprocess."""

    def __init__(self, pid: int, *, helper: Path | None = None,
                 expected_executable: str | None = None,
                 timeout: float = DEFAULT_TIMEOUT, max_cache_pages: int | None = None,
                 route: str | None = None):
        self.pid = pid
        self.timeout = timeout
        self.max_cache_pages = max_cache_pages
        self.stats = Stats()
        self.executable = ""
        # Which attach route the reader used: "injected" (the in-game library over
        # a Mach channel; no task_for_pid) or "task_for_pid". The reader prefers the
        # injected route and falls back to task_for_pid unless ``route`` forces one.
        self.route: str | None = None
        self.helper = self._locate_helper(helper)
        self._lock = threading.RLock()
        self._cache: dict[int, bytes] = {}
        self._bad_pages: set[int] = set()
        self._regions: list[Region] | None = None
        self._child: subprocess.Popen | None = None
        self._closed = False
        chosen_route = route if route is not None else os.environ.get("FMCP_ATTACH_ROUTE")
        if chosen_route is not None and chosen_route not in ("auto", "injected", "task-for-pid", "task_for_pid"):
            raise MemoryReadError(f"invalid attach route {chosen_route!r}; use auto, injected or task-for-pid")
        args = [str(self.helper), "--pid", str(pid)]
        if expected_executable is not None:
            args += ["--expect-path", expected_executable]
        if chosen_route is not None:
            args += ["--route", chosen_route.replace("_", "-")]
        try:
            self._child = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.DEVNULL, bufsize=0)
        except OSError as exc:
            raise MemoryReadError(f"cannot launch {self.helper}: {exc}") from exc
        try:
            os.set_blocking(self._child.stdin.fileno(), False)
            self._hello(expected_executable)
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _locate_helper(helper: Path | None) -> Path:
        candidate = (Path(helper) if helper is not None
                     else Path(os.environ["FM_FAST_READER"]) if os.environ.get("FM_FAST_READER")
                     else ROOT / "build" / "fm_fast_reader")
        if not candidate.is_file():
            raise MemoryReadError(f"fm_fast_reader not found at {candidate}. Run sh scripts/build_fast_reader.sh.")
        return candidate

    @classmethod
    def attach(cls, **kwargs) -> "LiveMemory":
        """Attach to the running FM process found by ``find_fm_process``."""
        process = find_fm_process()
        if process is None:
            raise MemoryReadError("no running Football Manager process found")
        return cls(process.pid, expected_executable=process.executable, **kwargs)

    # -- transport ---------------------------------------------------------------

    def _fail(self, message: str, *, gone: bool = False) -> None:
        """Tear the helper down (its channel is unusable) and raise."""
        code = self._reap()
        if code == 3 and not gone:
            gone, message = True, f"{message} (target process gone)"
        raise (ProcessGoneError if gone else MemoryReadError)(message)

    def _reap(self) -> int | None:
        child, self._child = self._child, None
        self._closed = True
        if child is None:
            return None
        for stream in (child.stdin, child.stdout):
            try:
                stream.close()
            except OSError:
                pass
        try:
            return child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            child.kill()
            return child.wait(timeout=5)

    def _write(self, data: bytes) -> None:
        fd = self._child.stdin.fileno()
        view, deadline = memoryview(data), time.monotonic() + self.timeout
        while view:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [fd], [], remaining)[1]:
                self._fail("fm_fast_reader did not accept the request in time")
            try:
                view = view[os.write(fd, view[:1 << 20]):]
            except BlockingIOError:
                continue
            except OSError as exc:
                self._fail(f"fm_fast_reader pipe closed while writing: {exc}")
            deadline = time.monotonic() + self.timeout

    def _read_exact(self, size: int) -> memoryview:
        out = bytearray(size)
        view, filled = memoryview(out), 0
        stream = self._child.stdout
        while filled < size:
            if not select.select([stream], [], [], self.timeout)[0]:
                self._fail(f"fm_fast_reader timed out after {self.timeout:g}s with no data")
            try:
                got = stream.readinto(view[filled:filled + (1 << 22)])
            except OSError as exc:
                self._fail(f"fm_fast_reader pipe error: {exc}")
            if not got:
                self._fail("fm_fast_reader exited before completing its response")
            filled += got
        return view

    def _hello(self, expected_executable: str | None) -> None:
        magic, status, version, pid, page, mach, path_len = _HELLO.unpack(self._read_exact(_HELLO.size))
        path = bytes(self._read_exact(path_len)).decode("utf-8", "replace") if path_len else ""
        if magic != HELLO_MAGIC or version != PROTOCOL_VERSION:
            self._fail("fm_fast_reader sent an unrecognised hello")
        if status == ST_PATH_MISMATCH:
            self._fail(f"target executable {path!r} is not the expected {expected_executable!r}")
        if status != ST_OK:
            detail = ""
            if status == ST_ATTACH_FAILED:
                # Neither route attached. The one fix is to start the game with the
                # FMCP launcher so the in-game library is loaded; task_for_pid needs
                # the desktop login session and a permissive SIP configuration.
                fix, download = launch_fix()
                detail = f" - {fix} so the in-game attach library is loaded"
                if not download:
                    detail += "; otherwise task_for_pid needs the desktop login session"
            self._fail(f"fm_fast_reader could not attach to pid {self.pid}: {status_name(status)}{detail}",
                       gone=status == ST_PROCESS_GONE)
        if pid != self.pid:
            self._fail("fm_fast_reader attached to a different pid")
        if expected_executable is not None and path != expected_executable:
            self._fail(f"target executable {path!r} is not the expected {expected_executable!r}")
        self.executable = path
        self.page_size = page or DEFAULT_PAGE_SIZE
        self.route = ROUTE_NAMES.get(mach, "task_for_pid")

    def _call(self, op: int, items: Sequence[tuple[int, int]] = ()) -> tuple[int, int, object]:
        """One round trip. Returns (status, count, body): (table, payload) for READV,
        the raw region records for REGIONS."""
        with self._lock:
            if self._closed or self._child is None:
                raise MemoryReadError("LiveMemory is closed")
            started = time.monotonic()
            request = bytearray(_HEADER.pack(REQ_MAGIC, op, len(items)))
            for address, length in items:
                request += _ITEM.pack(address, length)
            self._write(bytes(request))
            magic, status, count = _HEADER.unpack(self._read_exact(_HEADER.size))
            if magic != RESP_MAGIC:
                self._fail("fm_fast_reader sent a corrupt response header")
            body: object = memoryview(b"")
            if status in (ST_OK, ST_PROCESS_GONE):
                if op == OP_READV:
                    table = self._read_exact(count * _RESULT.size)
                    total = sum(struct.unpack_from("<I", table, i * 8 + 4)[0] for i in range(count)) if count else 0
                    payload = self._read_exact(total) if total else memoryview(b"")
                    body = (table, payload)
                elif op == OP_REGIONS:
                    body = self._read_exact(count * _REGION.size)
            self.stats.round_trips += 1
            self.stats.seconds += time.monotonic() - started
            return status, count, body

    # -- reads -------------------------------------------------------------------

    def _readv(self, items: Sequence[tuple[int, int]]) -> list[tuple[int, bytes | None]]:
        """One batch within the C limits. Returns (item_status, bytes|None) per item."""
        status, count, body = self._call(OP_READV, items)
        if status == ST_PROCESS_GONE:
            self._fail("target process is gone", gone=True)
        if status != ST_OK:
            self._fail(f"fm_fast_reader refused the batch: {status_name(status)}")
        if count != len(items):
            self._fail("fm_fast_reader returned the wrong item count")
        table, payload = body
        results, offset = [], 0
        for i in range(count):
            item_status, length = _RESULT.unpack_from(table, i * 8)
            if item_status == ST_OK:
                results.append((ST_OK, bytes(payload[offset:offset + length])))
                offset += length
            else:
                results.append((item_status, None))
                self.stats.failed_items += 1
        self.stats.items += count
        self.stats.bytes += offset
        return results

    def read_many(self, requests: Sequence[tuple[int, int]]) -> list[bytes | None]:
        """Scatter read. ``None`` marks an unreadable item. Chunks to the C limits;
        items over 16 MiB are split into pieces and rejoined (any failed piece -> None)."""
        return [data for _, data in self.read_many_status(requests)]

    def read_many_status(self, requests: Sequence[tuple[int, int]]) -> list[tuple[int, bytes | None]]:
        pieces: list[tuple[int, int, int]] = []  # (request index, address, length)
        results: list[list[tuple[int, bytes | None]]] = [[] for _ in requests]
        for index, (address, length) in enumerate(requests):
            _check_range(address, length)
            for start in range(0, length, MAX_ITEM_BYTES):
                pieces.append((index, address + start, min(MAX_ITEM_BYTES, length - start)))
        batch: list[tuple[int, int, int]] = []
        batch_bytes = 0

        def flush() -> None:
            nonlocal batch, batch_bytes
            if batch:
                done = self._readv([(a, n) for _, a, n in batch])
                for (index, _, _), result in zip(batch, done):
                    results[index].append(result)
            batch, batch_bytes = [], 0

        for piece in pieces:
            if batch and (len(batch) >= MAX_BATCH_ITEMS or batch_bytes + piece[2] > MAX_BATCH_BYTES):
                flush()
            batch.append(piece)
            batch_bytes += piece[2]
        flush()
        merged: list[tuple[int, bytes | None]] = []
        for parts in results:
            failed = next((s for s, d in parts if d is None), None)
            if failed is not None:
                merged.append((failed, None))
            elif len(parts) == 1:
                merged.append(parts[0])
            else:
                merged.append((ST_OK, b"".join(d for _, d in parts)))
        return merged

    def windows(self, addresses: Sequence[int], length: int) -> tuple[bytes, list[int]]:
        """See MemoryBase.windows. Two routes with the same result:

        * pages: when the addresses are dense (record arrays inside allocator arenas), the pages
          they touch are faulted into the page cache with one batched read and the windows are
          sliced out locally;
        * scatter: otherwise one READV item per address, with the request built and the response
          checked as whole buffers (no per-item Python objects when every item is readable).

        Like `cached_read`, the page route serves bytes already in the page cache."""
        n = len(addresses)
        if not n:
            return b'', []
        for a in (min(addresses), max(addresses)):       # as read_many: an invalid address is an error
            _check_range(a, length)
        size = self.page_size
        mask = size - 1
        if length <= size and self.max_cache_pages is not None:
            cache = self._cache
            pages = {a & ~mask for a in addresses}
            pages.update((a + length - 1) & ~mask for a in addresses)
            missing = [b for b in pages if b not in cache]
            if len(pages) <= self.max_cache_pages // 2 and len(missing) * size <= WINDOW_PAGE_RATIO * n * length + (1 << 20):
                retry = [b for b in missing if b not in self._bad_pages]
                if retry:
                    self._fault(retry)
                empty = b''
                get = cache.get
                parts = [get(a & ~mask, empty)[a & mask:(a & mask) + length] for a in addresses]
                payload = b''.join(parts)
                if len(payload) == n * length:
                    return payload, []
                # short slices: the window crosses a page boundary or its page is unreadable
                bad = []
                zero = bytes(length)
                for k, part in enumerate(parts):
                    if len(part) != length:
                        try:
                            parts[k] = self.cached_read(addresses[k], length)
                        except MemoryReadError:
                            parts[k] = zero
                            bad.append(k)
                return b''.join(parts), bad
        return self._windows_scatter(addresses, length)

    def _windows_scatter(self, addresses: Sequence[int], length: int) -> tuple[bytes, list[int]]:
        if length > MAX_ITEM_BYTES:
            return _join_windows(self.read_many([(a, length) for a in addresses]), length)
        out, bad = [], []
        step = max(1, min(MAX_BATCH_ITEMS, MAX_BATCH_BYTES // length))
        tail = struct.pack('<I', length)
        for start in range(0, len(addresses), step):
            chunk = addresses[start:start + step]
            n = len(chunk)
            request = bytearray(_ITEM.size * n)
            packed = struct.pack(f'<{n}Q', *chunk)
            for k in range(8):
                request[k::12] = packed[k::8]
            for k in range(4):
                request[8 + k::12] = tail[k:k + 1] * n
            with self._lock:
                if self._closed or self._child is None:
                    raise MemoryReadError("LiveMemory is closed")
                started = time.monotonic()
                self._write(_HEADER.pack(REQ_MAGIC, OP_READV, n) + bytes(request))
                magic, status, count = _HEADER.unpack(self._read_exact(_HEADER.size))
                if magic != RESP_MAGIC:
                    self._fail("fm_fast_reader sent a corrupt response header")
                if status == ST_PROCESS_GONE:
                    self._fail("target process is gone", gone=True)
                if status != ST_OK:
                    self._fail(f"fm_fast_reader refused the batch: {status_name(status)}")
                if count != n:
                    self._fail("fm_fast_reader returned the wrong item count")
                table = bytes(self._read_exact(n * _RESULT.size))
                if table == _RESULT.pack(ST_OK, length) * n:
                    payload = bytes(self._read_exact(n * length))
                    total = n * length
                else:
                    sizes = [size if code == ST_OK else 0 for code, size in _RESULT.iter_unpack(table)]
                    total = sum(sizes)
                    raw = self._read_exact(total) if total else memoryview(b"")
                    parts, offset = [], 0
                    zero = bytes(length)
                    for k, size in enumerate(sizes):
                        if size == length:
                            parts.append(bytes(raw[offset:offset + size]))
                        else:
                            parts.append(zero)
                            bad.append(start + k)
                            self.stats.failed_items += 1
                        offset += size
                    payload = b''.join(parts)
                self.stats.round_trips += 1
                self.stats.seconds += time.monotonic() - started
                self.stats.items += n
                self.stats.bytes += total
            out.append(payload)
        return (out[0] if len(out) == 1 else b''.join(out)), bad

    def read(self, address: int, length: int) -> bytes:
        """Uncached read of exactly ``length`` bytes. Raises ``MemoryReadError``."""
        (status, data), = self.read_many_status([(address, length)])
        if data is None:
            raise MemoryReadError(f"cannot read {length} bytes at {address:#x}: {status_name(status)}", status)
        return data

    # -- page cache --------------------------------------------------------------

    def page(self, address: int) -> bytes:
        """The page-aligned page containing ``address``, cached for the object's lifetime."""
        base = self.page_base(address)
        cached = self._cache.get(base)
        if cached is not None:
            self.stats.cache_hits += 1
            return cached
        if base not in self._bad_pages:
            self._fault([base])
        if base not in self._cache:
            raise MemoryReadError(f"page {base:#x} is unreadable", ST_READ_FAILED)
        return self._cache[base]

    def _fault(self, bases: Sequence[int]) -> None:
        """Fetch the given page bases with one batched read, in sorted order.

        A base outside the readable range is marked unreadable without a read. Page 0 is asked for
        when a record holds a small integer where a pointer was expected: one such person record
        made every snapshot build fail with "invalid read of 16384 bytes at 0" (12 November 2026)."""
        bases = sorted(set(bases))
        limit = 2**64 - self.page_size
        outside = [b for b in bases if not 0 < b <= limit]
        if outside:
            self._bad_pages.update(outside)
            bases = [b for b in bases if 0 < b <= limit]
            if not bases:
                return
        for base, (status, data) in zip(bases, self.read_many_status([(b, self.page_size) for b in bases])):
            if data is None:
                self._bad_pages.add(base)
            else:
                self._cache[base] = data
        self.stats.cache_misses += len(bases)
        if self.max_cache_pages is not None:
            while len(self._cache) > self.max_cache_pages:
                self._cache.pop(next(iter(self._cache)))

    def prefetch(self, ranges: Sequence[tuple[int, int]]) -> int:
        """Fault in every page touched by ``ranges`` with one batched read (unreadable
        pages are remembered and skipped). Returns the number of pages newly fetched."""
        wanted = set()
        for address, length in ranges:
            _check_range(address, length)
            wanted.update(range(self.page_base(address), address + length, self.page_size))
        missing = [b for b in wanted if b not in self._cache and b not in self._bad_pages]
        if missing:
            self._fault(missing)
        return len(missing)

    def cached_read(self, address: int, length: int) -> bytes:
        """Bytes served from the page cache; missing pages fault in with one batched read."""
        _check_range(address, length)
        first, last = self.page_base(address), self.page_base(address + length - 1)
        bases = range(first, last + 1, self.page_size)
        missing = [b for b in bases if b not in self._cache]
        if missing:
            retry = [b for b in missing if b not in self._bad_pages]
            if retry:
                self._fault(retry)
            bad = [b for b in missing if b not in self._cache]
            if bad:
                raise MemoryReadError(f"cannot read {length} bytes at {address:#x}: page {bad[0]:#x} unreadable",
                                      ST_READ_FAILED)
        else:
            self.stats.cache_hits += len(bases)
        if first == last:
            offset = address - first
            return self._cache[first][offset:offset + length]
        data = b"".join(self._cache[b] for b in bases)
        offset = address - first
        return data[offset:offset + length]

    def invalidate(self) -> None:
        """Drop the page cache (and remembered unreadable pages and the region list)."""
        self._cache.clear()
        self._bad_pages.clear()
        self._regions = None

    def reread(self, bases: Sequence[int]) -> set[int]:
        """Read the given cached pages again from the process with one batched read and replace
        them in the page cache. Returns the bases whose bytes changed (a page that became
        unreadable counts as changed and leaves the cache). Pages that are not cached are skipped."""
        bases = sorted(b for b in set(bases) if b in self._cache)
        changed = set()
        for base, (status, data) in zip(bases, self.read_many_status([(b, self.page_size) for b in bases])):
            if data is None:
                del self._cache[base]
                self._bad_pages.add(base)
                changed.add(base)
            elif data != self._cache[base]:
                self._cache[base] = data
                changed.add(base)
        return changed

    # -- regions -----------------------------------------------------------------

    def regions(self, *, refresh: bool = False) -> list[Region]:
        """The target's VM region list (all regions, any protection), sorted by address."""
        if self._regions is None or refresh:
            status, count, body = self._call(OP_REGIONS)
            if status == ST_PROCESS_GONE:
                self._fail("target process is gone", gone=True)
            if status != ST_OK:
                self._fail(f"fm_fast_reader refused REGIONS: {status_name(status)}")
            self._regions = [Region(*_REGION.unpack_from(body, i * _REGION.size)) for i in range(count)]
        return list(self._regions)

    def ping(self) -> bool:
        status, _, _ = self._call(OP_PING)
        return status == ST_OK

    # -- lifecycle ---------------------------------------------------------------

    def close(self) -> None:
        """Idempotent. Asks the helper to quit, then reaps it."""
        with self._lock:
            child = self._child
            if child is not None and not self._closed:
                try:
                    os.write(child.stdin.fileno(), _HEADER.pack(REQ_MAGIC, OP_QUIT, 0))
                except OSError:
                    pass
            self._reap()
            self._cache.clear()


class SnapshotMemory(MemoryBase):
    """The same read interface over a dict of ``{page_base: page_bytes}``."""

    def __init__(self, pages: Mapping[int, bytes] | None = None, *, page_size: int = DEFAULT_PAGE_SIZE):
        if page_size < 1 or page_size & (page_size - 1):
            raise ValueError("page_size must be a power of two")
        self.page_size = page_size
        self.pages: dict[int, bytes] = {}
        self.stats = Stats()
        for base, data in (pages or {}).items():
            self.add_page(base, data)

    def add_page(self, base: int, data: bytes) -> None:
        if base % self.page_size or len(data) != self.page_size:
            raise ValueError(f"page at {base:#x} must be {self.page_size} bytes and page aligned")
        self.pages[base] = bytes(data)

    def load(self, address: int, data: bytes) -> None:
        """Place ``data`` at ``address``, creating zero-filled pages as needed."""
        end = address + len(data)
        for base in range(self.page_base(address), end, self.page_size):
            page = bytearray(self.pages.get(base, bytes(self.page_size)))
            lo, hi = max(address, base), min(end, base + self.page_size)
            page[lo - base:hi - base] = data[lo - address:hi - address]
            self.pages[base] = bytes(page)

    @classmethod
    def capture(cls, source: MemoryBase, bases: Sequence[int]) -> "SnapshotMemory":
        """Copy the given page bases out of another memory (unreadable pages are skipped)."""
        snap = cls(page_size=source.page_size)
        for base, data in zip(bases, source.read_many([(b, source.page_size) for b in bases])):
            if data is not None:
                snap.add_page(base, data)
        return snap

    def read(self, address: int, length: int) -> bytes:
        _check_range(address, length)
        first, last = self.page_base(address), self.page_base(address + length - 1)
        missing = [b for b in range(first, last + 1, self.page_size) if b not in self.pages]
        if missing:
            raise MemoryReadError(f"cannot read {length} bytes at {address:#x}: page {missing[0]:#x} not in snapshot",
                                  ST_READ_FAILED)
        data = b"".join(self.pages[b] for b in range(first, last + 1, self.page_size))
        offset = address - first
        self.stats.items += 1
        self.stats.bytes += length
        return data[offset:offset + length]

    def read_many(self, requests: Sequence[tuple[int, int]]) -> list[bytes | None]:
        out: list[bytes | None] = []
        for address, length in requests:
            try:
                out.append(self.read(address, length))
            except MemoryReadError:
                out.append(None)
                self.stats.failed_items += 1
        return out

    def page(self, address: int) -> bytes:
        base = self.page_base(address)
        if base not in self.pages:
            raise MemoryReadError(f"page {base:#x} not in snapshot", ST_READ_FAILED)
        return self.pages[base]

    def cached_read(self, address: int, length: int) -> bytes:
        return self.read(address, length)

    def regions(self) -> list[Region]:
        """Contiguous runs of snapshot pages, reported readable and writable."""
        runs: list[Region] = []
        for base in sorted(self.pages):
            if runs and runs[-1].end == base:
                last = runs[-1]
                runs[-1] = Region(last.start, last.size + self.page_size, last.protection, last.max_protection)
            else:
                runs.append(Region(base, self.page_size, VM_PROT_READ | VM_PROT_WRITE, VM_PROT_READ | VM_PROT_WRITE))
        return runs

    def invalidate(self) -> None:
        pass


def find_fm_process():
    """The running FM27 ``bridge.Process`` (first match), else any FM process, else None.
    Reuses ``bridge.discover_processes`` so process identity rules stay in one place."""
    from ..bridge import discover_processes  # heavy import, deferred

    found = discover_processes()
    for process in found:
        if process.bundle_id == "com.SportsInteractive.FootballManager27":
            return process
    return found[0] if found else None
