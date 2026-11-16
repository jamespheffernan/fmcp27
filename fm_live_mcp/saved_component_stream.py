"""Bounded sequential reading of one already selected FMF8 Zstandard member.

The caller owns archive/path/identity validation and the open handle. Context exit
frees decoder state without draining or claiming validation of unconsumed bytes.
"""

from contextlib import contextmanager
import ctypes
import ctypes.util
from functools import lru_cache
import struct

BLOCK_SIZE = 128 * 1024
MAX_RAW_SIZE = 512 * 1024 * 1024
MAX_PACKED_SIZE = 256 * 1024 * 1024
MAX_TAKE = 4 * 1024 * 1024
MAX_WINDOW_LOG = 26  # Bound decoder-owned history to 64 MiB.


class _Input(ctypes.Structure):
    _fields_ = [
        ("src", ctypes.c_void_p),
        ("size", ctypes.c_size_t),
        ("pos", ctypes.c_size_t),
    ]


class _Output(ctypes.Structure):
    _fields_ = [
        ("dst", ctypes.c_void_p),
        ("size", ctypes.c_size_t),
        ("pos", ctypes.c_size_t),
    ]


@lru_cache(maxsize=1)
def _library():
    name = ctypes.util.find_library("zstd")
    if not name:
        raise ValueError("Zstandard library unavailable; install libzstd")
    try:
        lib = ctypes.CDLL(name)
        signatures = {
            "ZSTD_createDStream": ([], ctypes.c_void_p),
            "ZSTD_freeDStream": ([ctypes.c_void_p], ctypes.c_size_t),
            "ZSTD_initDStream": ([ctypes.c_void_p], ctypes.c_size_t),
            "ZSTD_DCtx_setParameter": (
                [ctypes.c_void_p, ctypes.c_int, ctypes.c_int],
                ctypes.c_size_t,
            ),
            "ZSTD_decompressStream": (
                [ctypes.c_void_p, ctypes.POINTER(_Output), ctypes.POINTER(_Input)],
                ctypes.c_size_t,
            ),
            "ZSTD_getFrameContentSize": (
                [ctypes.c_void_p, ctypes.c_size_t],
                ctypes.c_ulonglong,
            ),
            "ZSTD_isError": ([ctypes.c_size_t], ctypes.c_uint),
        }
        for symbol, (args, result) in signatures.items():
            function = getattr(lib, symbol)
            function.argtypes, function.restype = args, result
    except (OSError, AttributeError) as error:
        raise ValueError(
            "Compatible Zstandard streaming library unavailable"
        ) from error
    return lib


class _Decoder:
    def __init__(self, handle, entry):
        for value in (entry.start, entry.compressed_size, entry.uncompressed_size):
            if type(value) is not int or value < 0:
                raise ValueError("Invalid component extent")
        if (
            not 1 <= entry.compressed_size <= MAX_PACKED_SIZE
            or not 1 <= entry.uncompressed_size <= MAX_RAW_SIZE
        ):
            raise ValueError("Component exceeds supported size budget")
        self.handle = handle
        self.start = 26 + entry.start
        self.packed_size, self.raw_size = entry.compressed_size, entry.uncompressed_size
        self.packed_read = self.raw_read = 0
        self.calls = 0
        self.max_calls = 64 + 4 * (
            (self.packed_size + BLOCK_SIZE - 1) // BLOCK_SIZE
            + (self.raw_size + BLOCK_SIZE - 1) // BLOCK_SIZE
        )
        self.pending = b""
        self.position = 0
        self.finished = False
        self.closed = False
        self.lib = _library()
        self.state = self.lib.ZSTD_createDStream()
        if not self.state:
            raise ValueError("Unable to allocate Zstandard decoder")
        try:
            self._check(self.lib.ZSTD_initDStream(self.state))
            self._check(
                self.lib.ZSTD_DCtx_setParameter(self.state, 100, MAX_WINDOW_LOG)
            )
        except BaseException:
            self.close()
            raise
        self.output = ctypes.create_string_buffer(BLOCK_SIZE)

    def _check(self, result):
        if self.lib.ZSTD_isError(result):
            raise ValueError("Invalid or unsupported Zstandard component")
        return result

    def close(self):
        if not self.closed:
            self.closed = True
            self.lib.ZSTD_freeDStream(self.state)
            self.pending = b""

    def read(self, size):
        if self.closed:
            raise ValueError("Component reader is closed")
        if self.finished:
            return b""
        while True:
            self.calls += 1
            if self.calls > self.max_calls:
                raise ValueError("Component decoder work budget exhausted")
            if (
                self.position == len(self.pending)
                and self.packed_read < self.packed_size
            ):
                amount = min(BLOCK_SIZE, self.packed_size - self.packed_read)
                self.handle.seek(self.start + self.packed_read)
                self.pending = self.handle.read(amount)
                if len(self.pending) != amount:
                    raise ValueError("Truncated compressed component")
                self.packed_read += amount
                self.position = 0
                if self.packed_read == amount:
                    if self.pending[:4] != bytes.fromhex("28b52ffd"):
                        raise ValueError("Invalid component frame magic")
                    frame_size = self.lib.ZSTD_getFrameContentSize(
                        self.pending, len(self.pending)
                    )
                    if frame_size == (1 << 64) - 2:
                        raise ValueError("Invalid component frame header")
                    if frame_size != (1 << 64) - 1 and frame_size != self.raw_size:
                        raise ValueError(
                            "Frame size differs from declared component size"
                        )
            # An empty-input call may release output buffered inside libzstd.
            source = ctypes.c_char_p(self.pending)
            incoming = _Input(
                ctypes.cast(source, ctypes.c_void_p), len(self.pending), self.position
            )
            outgoing = _Output(
                ctypes.cast(self.output, ctypes.c_void_p), min(size, BLOCK_SIZE), 0
            )
            old_position = incoming.pos
            remaining = self._check(
                self.lib.ZSTD_decompressStream(
                    self.state, ctypes.byref(outgoing), ctypes.byref(incoming)
                )
            )
            self.position = incoming.pos
            self.raw_read += outgoing.pos
            if self.raw_read > self.raw_size:
                raise ValueError("Component exceeds declared uncompressed size")
            if remaining == 0:
                self.finished = True
                if self.raw_read != self.raw_size:
                    raise ValueError("Component uncompressed size mismatch")
                if (
                    self.packed_read - len(self.pending) + self.position
                    != self.packed_size
                ):
                    raise ValueError("Trailing bytes or multiple component frames")
            if outgoing.pos:
                return self.output.raw[: outgoing.pos]
            if self.finished:
                return b""
            if self.position == old_position:
                raise ValueError("Truncated or stalled Zstandard component")


class Reader:
    """Buffered wire primitives over a binary read(size) source of declared size."""

    def __init__(self, source, size):
        if type(size) is not int or not 0 <= size <= MAX_RAW_SIZE:
            raise ValueError("Invalid raw reader size")
        self.source, self.size = source, size
        self.offset = 0
        self._buffer = b""
        self._position = 0
        self._closed = False

    def _validate(self, n):
        if self._closed:
            raise ValueError("Component reader is closed")
        if type(n) is not int or n < 0 or n > self.size - self.offset:
            raise ValueError("Read exceeds declared component extent")

    def _fill(self):
        self._buffer = self.source.read(min(BLOCK_SIZE, self.size - self.offset))
        self._position = 0
        if not isinstance(self._buffer, bytes) or not self._buffer:
            raise ValueError("Truncated uncompressed component")
        if len(self._buffer) > min(BLOCK_SIZE, self.size - self.offset):
            raise ValueError("Source exceeded requested read size")

    def take(self, n):
        self._validate(n)
        if n > MAX_TAKE:
            raise ValueError("Single read exceeds supported allocation budget")
        if n == 0:
            return b""
        if len(self._buffer) - self._position >= n:
            result = self._buffer[self._position : self._position + n]
            self._position += n
            self.offset += n
            return result
        pieces = []
        left = n
        while left:
            if self._position == len(self._buffer):
                self._fill()
            amount = min(left, len(self._buffer) - self._position)
            pieces.append(self._buffer[self._position : self._position + amount])
            self._position += amount
            self.offset += amount
            left -= amount
        return b"".join(pieces)

    def skip(self, n):
        self._validate(n)
        while n:
            if self._position == len(self._buffer):
                self._fill()
            amount = min(n, len(self._buffer) - self._position)
            self._position += amount
            self.offset += amount
            n -= amount

    def u8(self):
        return self.take(1)[0]

    def i8(self):
        return struct.unpack("<b", self.take(1))[0]

    def u16(self):
        return struct.unpack("<H", self.take(2))[0]

    def i16(self):
        return struct.unpack("<h", self.take(2))[0]

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def i32(self):
        return struct.unpack("<i", self.take(4))[0]

    def text(self, max_bytes=8192):
        if type(max_bytes) is not int or not 0 <= max_bytes <= MAX_TAKE:
            raise ValueError("Invalid text budget")
        length = self.u32()
        if length > max_bytes:
            raise ValueError("Text exceeds supported byte budget")
        try:
            return self.take(length).decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("Invalid UTF-8 component text") from error


@contextmanager
def open_component(handle, entry):
    decoder = _Decoder(handle, entry)
    reader = Reader(decoder, entry.uncompressed_size)
    try:
        yield reader
    finally:
        reader._closed = True
        reader._buffer = b""
        decoder.close()
