import struct
import pytest
from fm_live_mcp.saved_database_header import read_header


class BytesReader:
    def __init__(self, data):
        self.data = data
        self.offset = 0

    def take(self, n):
        if n < 0 or self.offset + n > len(self.data):
            raise ValueError("truncated")
        b = self.data[self.offset:self.offset + n]
        self.offset += n
        return b

    def skip(self, n):
        self.take(n)

    def u8(self):
        return int.from_bytes(self.take(1), "little")
    def i8(self):
        return int.from_bytes(self.take(1), "little", signed=True)
    def u16(self):
        return int.from_bytes(self.take(2), "little")
    def u32(self):
        return int.from_bytes(self.take(4), "little")
    def i32(self):
        return int.from_bytes(self.take(4), "little", signed=True)
    def text(self, max_bytes=8192):
        n = self.u32()
        if n > max_bytes:
            raise ValueError("string budget")
        return self.take(n).decode("utf8")


def u32(n):
    return struct.pack("<I", n)
def text(s):
    b = s.encode("utf8")
    return u32(len(b)) + b


def sample(*, positive=False, late_version=10, final_count=0):
    b = b"\x03\x01tad." + struct.pack("<HHH", 4000, 3754, 9)
    b += bytes(10) + text("different build length") + bytes(34)
    # Zero optional presence must consume no nested version/payload.
    b += b"\1\2\0\1\1" + bytes(69)
    b += b"\1" + u32(1) + b"\1" + u32(2) + bytes(8)
    if positive:
        b += struct.pack("<HiiHiHi", 1, 1, -7, 1, 1, 1, 2) + bytes(10)
        b += b"\1" + u32(1) + struct.pack("<i", -9) + b"\1" + u32(3) + bytes(12)
        b += b"\1" + u32(1) + b"\xfe\0"
        b += b"".join(b"\1" + u32(n) + bytes(4*n) for n in (0, 1, 2))
    else:
        b += b"\1\0" + bytes(4) + (b"\1" + bytes(4))*2
    b += u32(3) + b"abc"
    b += b"\2\2\0\1" + bytes([late_version]) + bytes(51 + (late_version > 9))
    b += u32(1) + text("été") + u32(0) + u32(final_count)
    b += b"\0\1" + u32(1) + bytes(6) + u32(0)*3 + bytes(4)
    return b


@pytest.mark.parametrize("positive", [False, True])
@pytest.mark.parametrize("late_version", [1, 10])
def test_dynamic_metadata_boundary(positive, late_version):
    data = sample(positive=positive, late_version=late_version)
    r = BytesReader(data + u32(12345))
    assert read_header(r) == {"serializer_version": 4000, "source_major": 3754, "source_minor": 9}
    assert r.offset == len(data)
    assert r.u32() == 12345


def test_reject_every_truncated_prefix():
    data = sample(positive=True)
    for n in range(len(data)):
        with pytest.raises(ValueError):
            read_header(BytesReader(data[:n]))


def test_reject_unproved_final_collection():
    with pytest.raises(ValueError, match="nonempty final"):
        read_header(BytesReader(sample(final_count=1)))


@pytest.mark.parametrize("offset,value", [(6, 3999), (8, 3753), (10, 8)])
def test_reject_other_sources(offset, value):
    data = bytearray(sample())
    data[offset:offset+2] = struct.pack("<H", value)
    with pytest.raises(ValueError, match="source version"):
        read_header(BytesReader(bytes(data)))


def test_reject_large_string_before_allocation():
    data = sample()[:22] + u32(8193)
    with pytest.raises(ValueError):
        read_header(BytesReader(data))


def test_reject_nonzero_initial_cursor():
    r = BytesReader(sample())
    r.offset = 1
    with pytest.raises(ValueError, match="offset zero"):
        read_header(r)
