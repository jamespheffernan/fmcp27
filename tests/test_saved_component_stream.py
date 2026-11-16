"""Run with python -m unittest discover -s <staging directory>."""

import ctypes
import io
from types import SimpleNamespace
import struct
import unittest
from fm_live_mcp.saved_component_stream import (
    BLOCK_SIZE,
    MAX_RAW_SIZE,
    MAX_TAKE,
    Reader,
    _library,
    open_component,
)


def packed(raw):
    z = _library()
    z.ZSTD_compress.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_int,
    ]
    z.ZSTD_compress.restype = ctypes.c_size_t
    out = ctypes.create_string_buffer(len(raw) + 1024)
    n = z.ZSTD_compress(out, len(out), raw, len(raw), 1)
    assert not z.ZSTD_isError(n)
    return out.raw[:n]


def entry(p, raw_size):
    return SimpleNamespace(start=0, compressed_size=len(p), uncompressed_size=raw_size)


class StreamTests(unittest.TestCase):
    def test_primitives_text_and_offsets(self):
        raw = (
            struct.pack("<BbHhIiI", 255, -3, 65535, -42, 2**32 - 1, -123, 3)
            + b"caf"
            + b"x"
        )
        r = Reader(io.BytesIO(raw), len(raw))
        self.assertEqual(
            (r.u8(), r.i8(), r.u16(), r.i16(), r.u32(), r.i32(), r.text()),
            (255, -3, 65535, -42, 2**32 - 1, -123, "caf"),
        )
        self.assertEqual(r.offset, len(raw) - 1)
        r.skip(1)
        self.assertEqual(r.offset, len(raw))
        self.assertEqual(r.take(0), b"")
        with self.assertRaises(ValueError):
            r.u8()

    def test_multiblock_take_and_skip(self):
        raw = bytes(range(256)) * (BLOCK_SIZE // 64)
        p = packed(raw)
        with open_component(
            io.BytesIO(b"0" * 26 + p + b"outside"), entry(p, len(raw))
        ) as r:
            self.assertEqual(r.take(111), raw[:111])
            r.skip(BLOCK_SIZE + 17)
            self.assertEqual(
                r.take(333), raw[111 + BLOCK_SIZE + 17 : 111 + BLOCK_SIZE + 350]
            )
            r.skip(len(raw) - r.offset)
            self.assertEqual(r.offset, len(raw))
        with self.assertRaises(ValueError):
            r.take(0)

    def test_only_selected_packed_extent_read(self):
        raw = b"hello" * 1000
        p = packed(raw)

        class Guard(io.BytesIO):
            def read(self, n=-1):
                self.assert_bound(n)
                return super().read(n)

            def assert_bound(self, n):
                if n < 0 or self.tell() < 26 or self.tell() + n > 26 + len(p):
                    raise AssertionError("outside member")

        with open_component(Guard(b"0" * 26 + p + b"outside"), entry(p, len(raw))) as r:
            self.assertEqual(r.take(len(raw)), raw)

    def test_short_source_and_bad_frame(self):
        raw = b"hello" * 100
        p = packed(raw)
        for data, e in [
            (p[:-1], entry(p, len(raw))),
            (b"badframe", entry(b"badframe", len(raw))),
            (p[:-3], entry(p[:-3], len(raw))),
        ]:
            with self.subTest(data=data[:8]), self.assertRaises(ValueError):
                with open_component(io.BytesIO(b"0" * 26 + data), e) as r:
                    r.take(len(raw))

    def test_declared_sizes_and_multiple_frames(self):
        raw = b"abc" * 100
        p = packed(raw)
        for data, size in [(p, len(raw) - 1), (p, len(raw) + 1), (p + p, len(raw))]:
            with self.subTest(size=size), self.assertRaises(ValueError):
                with open_component(
                    io.BytesIO(b"0" * 26 + data), entry(data, size)
                ) as r:
                    r.take(size)

    def test_prefix_does_not_drain_member(self):
        raw = b"a" * (BLOCK_SIZE * 4)
        p = packed(raw)
        with open_component(io.BytesIO(b"0" * 26 + p), entry(p, len(raw))) as r:
            self.assertEqual(r.take(5), b"aaaaa")
            self.assertEqual(r.offset, 5)
            self.assertLessEqual(len(r._buffer), BLOCK_SIZE)

    def test_raw_reader_errors(self):
        for amount in (-1, True, MAX_TAKE + 1):
            with self.assertRaises(ValueError):
                Reader(io.BytesIO(b""), MAX_TAKE + 2).take(amount)
        with self.assertRaises(ValueError):
            Reader(io.BytesIO(b""), MAX_RAW_SIZE + 1)
        with self.assertRaises(ValueError):
            Reader(io.BytesIO(b"a"), 2).take(2)
        for raw in [struct.pack("<I", 9) + b"abc", struct.pack("<I", 1) + b"\xff"]:
            with self.assertRaises(ValueError):
                Reader(io.BytesIO(raw), len(raw)).text(max_bytes=4)

    def test_many_fields_are_buffered(self):

        class Count(io.BytesIO):
            calls = 0

            def read(self, n):
                self.calls += 1
                return super().read(n)

        source = Count(b"\x00" * 40000)
        r = Reader(source, 40000)
        for _ in range(10000):
            self.assertEqual(r.u32(), 0)
        self.assertEqual(source.calls, 1)

    def test_decoder_work_budget(self):
        raw = b"a" * 100
        p = packed(raw)
        with open_component(io.BytesIO(b"0" * 26 + p), entry(p, len(raw))) as r:
            r.source.max_calls = 0
            with self.assertRaises(ValueError):
                r.u8()

    def test_extent_guards(self):
        for start, packed_size, raw_size in [
            (-1, 2, 2),
            (False, 2, 2),
            (0, 0, 2),
            (0, 2, 0),
            (0, 2, MAX_RAW_SIZE + 1),
        ]:
            e = SimpleNamespace(
                start=start, compressed_size=packed_size, uncompressed_size=raw_size
            )
            with self.assertRaises(ValueError):
                with open_component(io.BytesIO(b""), e):
                    pass


if __name__ == "__main__":
    unittest.main()
