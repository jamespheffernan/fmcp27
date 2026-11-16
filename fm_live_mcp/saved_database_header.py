"""Bounded source-3754 database metadata walker, without entity interpretation."""

from typing import Protocol


class Reader(Protocol):
    offset: int

    def take(self, n: int) -> bytes: ...
    def skip(self, n: int) -> None: ...
    def u8(self) -> int: ...
    def i8(self) -> int: ...
    def u16(self) -> int: ...
    def u32(self) -> int: ...
    def i32(self) -> int: ...
    def text(self, max_bytes: int = 8192) -> str: ...


class _Budget:
    def __init__(self, reader: Reader) -> None:
        self.reader = reader
        self.start = reader.offset
        self.work = 0

    def count(self, value: int, maximum: int = 100_000) -> int:
        if not 0 <= value <= maximum:
            raise ValueError("Saved metadata count exceeds supported bounds")
        self.work += value
        if self.work > 500_000:
            raise ValueError("Saved metadata cumulative work budget exhausted")
        if self.reader.offset - self.start > 16 * 1024 * 1024:
            raise ValueError("Saved metadata byte budget exhausted")
        return value


def _optional_block(reader: Reader, budget: _Budget, *, first: bool) -> None:
    reader.u8()  # Opaque native serializer marker.
    slots = budget.count(reader.u8() if first else reader.i8(), 127)
    for _ in range(slots):
        present = reader.u8()
        if present == 0:
            continue
        if present != 1:
            raise ValueError("Unsupported saved metadata presence flag")
        version = reader.u8()
        if first:
            reader.skip(69)
        else:
            reader.skip(51 + (version > 9))


def read_header(reader: Reader) -> dict[str, int]:
    """Consume metadata from stream start, stopping before the AWARD count.

    The supported branch is serializer 4000/source 3754/minor 9, cold full-load
    constants version 1. Unknown final metadata records are rejected explicitly.
    Counts and marker bytes carry no invented domain labels.
    """
    if reader.offset != 0:
        raise ValueError("Saved database header must start at stream offset zero")
    if reader.take(6) != b"\x03\x01tad.":
        raise ValueError("Unsupported saved database stream")
    serializer, major, minor = reader.u16(), reader.u16(), reader.u16()
    if (serializer, major, minor) != (4000, 3754, 9):
        raise ValueError("Unsupported saved database source version")
    budget = _Budget(reader)
    reader.skip(2 + 4 + 2 + 2)
    reader.text(max_bytes=8192)
    reader.skip(4 + 4 + 8 + 2 + 2 + 4 + 4 + 1 + 1 + 4)
    _optional_block(reader, budget, first=True)
    reader.u8()
    for _ in range(budget.count(reader.u32())):
        reader.u8()
        reader.skip(4 * budget.count(reader.u32()))
    # Native 1460850: signed-key tree of groups of signed-byte/u32 pairs.
    reader.u16()
    for _ in range(budget.count(reader.i32())):
        reader.i32()
        reader.u16()
        for _ in range(budget.count(reader.i32(), 10)):
            reader.u16()
            reader.skip(5 * budget.count(reader.i32()))
    # Native 13CC9E0: signed-key tree with bounded u32 arrays.
    reader.u8()
    for _ in range(budget.count(reader.u32())):
        reader.i32()
        reader.u8()
        reader.skip(4 * budget.count(reader.u32(), 70))
    # Native 157E2E8: signed-byte key, extra byte and three bounded arrays.
    reader.u8()
    for _ in range(budget.count(reader.u32())):
        reader.skip(2)
        for _ in range(3):
            reader.u8()
            reader.skip(4 * budget.count(reader.u32(), 70))
    reader.skip(budget.count(reader.u32(), 1_048_576))
    _optional_block(reader, budget, first=False)
    for _ in range(2):
        for _ in range(budget.count(reader.u32(), 65_536)):
            reader.text(max_bytes=8192)
            budget.count(0)
    # Native 102CFA0 reads this u32 even when the following collection is empty.
    if reader.u32() != 0:
        raise ValueError("Unsupported nonempty final saved metadata collection")
    reader.u8()
    if reader.i8() != 1:
        raise ValueError("Unsupported saved constants serializer version")
    for _ in range(4):
        reader.skip(6 * budget.count(reader.u32()))
    reader.skip(4)
    budget.count(0)
    return {
        "serializer_version": serializer,
        "source_major": major,
        "source_minor": minor,
    }
