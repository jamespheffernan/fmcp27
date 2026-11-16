"""Bounded streaming consumption of the verified saved-property wire subset.

Callers establish the supported serializer/build context. Scalar payloads remain
opaque; unproved native extension types fail rather than guessing their size.
"""

MAX_PROPERTY_NODES = 100_000
MAX_PROPERTY_DEPTH = 16
MAX_PROPERTY_BYTES = 4 * 1024 * 1024
MAX_PROPERTY_TEXT_BYTES = 8192

_SCALAR_WIDTHS = {
    1: 4,
    2: 4,
    3: 1,
    5: 8,
    15: 8,
    17: 1,
    18: 2,
    19: 1,
    20: 2,
    21: 4,
    24: 8,
    25: 4,
    27: 8,
    # Registered native extension32 callback42F07DC reads four payload bytes.
    32: 4,
}
_EMPTY_TYPES = frozenset((0, 6, 7))


class _Walker:
    def __init__(self, reader):
        self.reader = reader
        self.start = reader.offset
        self.nodes = 0

    def _check_bytes(self, amount):
        if self.reader.offset - self.start + amount > MAX_PROPERTY_BYTES:
            raise ValueError("Saved property byte budget exhausted")

    def _u8(self):
        self._check_bytes(1)
        return self.reader.u8()

    def _u32(self):
        self._check_bytes(4)
        return self.reader.u32()

    def _skip(self, amount):
        self._check_bytes(amount)
        self.reader.skip(amount)

    def _count(self):
        count = self._u32()
        if count > MAX_PROPERTY_NODES - self.nodes:
            raise ValueError("Saved property collection exceeds node budget")
        return count

    def _check_depth(self, depth):
        if depth > MAX_PROPERTY_DEPTH:
            raise ValueError("Saved property nesting budget exhausted")

    def vector(self, depth):
        self._check_depth(depth)
        count = self._count()
        for _ in range(count):
            self.variant(depth)

    def mapping(self, depth):
        self._check_depth(depth)
        count = self._count()
        for _ in range(count):
            self._skip(4)  # Native unsigned property key.
            self.variant(depth)

    def variant(self, depth):
        self._check_depth(depth)
        self.nodes += 1
        if self.nodes > MAX_PROPERTY_NODES:
            raise ValueError("Saved property node budget exhausted")
        start = self.reader.offset
        self._u8()  # Native serializer marker, not generally checked for equality.
        kind = self._u8()
        if kind in _SCALAR_WIDTHS:
            self._skip(_SCALAR_WIDTHS[kind])
        elif kind in _EMPTY_TYPES:
            return
        elif kind == 10:
            self.mapping(depth + 1)
        elif kind == 11:
            self.vector(depth + 1)
        elif kind == 26:
            length = self._u32()
            if length > MAX_PROPERTY_TEXT_BYTES:
                raise ValueError("Saved property text exceeds byte budget")
            self._check_bytes(length)
            try:
                self.reader.take(length).decode("utf-8")
            except UnicodeDecodeError as error:
                raise ValueError("Invalid saved property UTF-8 text") from error
        else:
            raise ValueError(f"Unsupported saved property variant {kind} at {start}")


def skip_property_vector(reader):
    """Consume one vector with shared nested node/depth/byte limits."""
    _Walker(reader).vector(0)


def skip_property_map(reader):
    """Consume one u32-keyed map with shared nested node/depth/byte limits."""
    _Walker(reader).mapping(0)
