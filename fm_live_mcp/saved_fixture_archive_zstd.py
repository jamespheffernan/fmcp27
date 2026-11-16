"""Decode one bounded historical frame with the existing libzstd dependency."""
import ctypes

from .saved_component_stream import (
    BLOCK_SIZE, MAX_WINDOW_LOG, _Input, _Output, _library,
)

MAX_COMPRESSED_FRAME = 16 * 1024 * 1024
MAX_EXPANDED_FRAME = 16 * 1024 * 1024


def expand_frame(raw):
    if not isinstance(raw, bytes) or not 4 <= len(raw) <= MAX_COMPRESSED_FRAME:
        raise ValueError('Historical fixture compressed-frame size budget exceeded')
    if raw[:4] != bytes.fromhex('28b52ffd'):
        raise ValueError('Invalid historical fixture Zstandard frame magic')
    lib = _library()
    state = lib.ZSTD_createDStream()
    if not state:
        raise ValueError('Unable to allocate historical fixture decoder')
    try:
        for result in (lib.ZSTD_initDStream(state),
                       lib.ZSTD_DCtx_setParameter(state, 100, MAX_WINDOW_LOG)):
            if lib.ZSTD_isError(result):
                raise ValueError('Unable to initialize historical fixture decoder')
        source = ctypes.c_char_p(raw)
        incoming = _Input(ctypes.cast(source, ctypes.c_void_p), len(raw), 0)
        buffer = ctypes.create_string_buffer(BLOCK_SIZE)
        pieces = []
        total = 0
        max_calls = 64 + 4 * (len(raw) // BLOCK_SIZE + MAX_EXPANDED_FRAME // BLOCK_SIZE)
        for _ in range(max_calls):
            previous = incoming.pos
            outgoing = _Output(ctypes.cast(buffer, ctypes.c_void_p), BLOCK_SIZE, 0)
            remaining = lib.ZSTD_decompressStream(
                state, ctypes.byref(outgoing), ctypes.byref(incoming))
            if lib.ZSTD_isError(remaining):
                raise ValueError('Invalid historical fixture Zstandard frame')
            total += outgoing.pos
            if total > MAX_EXPANDED_FRAME:
                raise ValueError('Historical fixture expanded-frame size budget exceeded')
            if outgoing.pos:
                pieces.append(buffer.raw[:outgoing.pos])
            if remaining == 0:
                if incoming.pos != len(raw):
                    raise ValueError('Trailing bytes or multiple historical fixture frames')
                return b''.join(pieces)
            if incoming.pos == previous and not outgoing.pos:
                raise ValueError('Truncated or stalled historical fixture frame')
        raise ValueError('Historical fixture decompressor work budget exceeded')
    finally:
        lib.ZSTD_freeDStream(state)
