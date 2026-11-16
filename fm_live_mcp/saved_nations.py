"""Bounded NATION rows for the verified source3754/minor9 full-loader stream.

The caller establishes source context and consumes the subtype. Opaque children
are skipped in stream order, without retaining their records or projecting names.
Native signed nonpositive populations consume no child rows.
"""

SUPPORTED_SOURCE = (3754, 9)
MAX_DATABASE_SLOTS = 10_000
MAX_CHILD_ITEMS = 100_000
MAX_RECORD_ITEMS = 200_000
MAX_RECORD_BYTES = 16 * 1024 * 1024
MAX_TEXT_BYTES = 8192


class _Budget:
    def __init__(self, reader):
        self.reader = reader
        self.start = reader.offset
        self.items = 0

    def count(self, value):
        count = max(value, 0)
        if count > MAX_CHILD_ITEMS:
            raise ValueError('Saved NATION child exceeds item budget')
        self.items += count
        if self.items > MAX_RECORD_ITEMS:
            raise ValueError('Saved NATION record exceeds item budget')
        return count

    def skip(self, size):
        if self.reader.offset - self.start + size > MAX_RECORD_BYTES:
            raise ValueError('Saved NATION record exceeds byte budget')
        self.reader.skip(size)

    def text(self):
        size = self.reader.u32()
        if size > MAX_TEXT_BYTES:
            raise ValueError('Saved NATION child text exceeds byte budget')
        self.skip(size)


def read_nation_identity(reader, ordinal, kind):
    """Consume one kind-zero NATION body and verify its stored table ordinal.

    13AED54 full-loader order, including versioned opaque children and the
    terminal 11B011C identity. Memory strides/padding are not serialized widths.
    No semantic meaning is assigned to skipped fields or child text. Identity
    words remain independent; a zero secondary ID is not replaced by primary.
    """
    if type(ordinal) is not int or not 0 <= ordinal < MAX_DATABASE_SLOTS:
        raise ValueError('Invalid saved NATION ordinal')
    if type(kind) is not int or kind != 0:
        raise ValueError('Unsupported saved NATION record subtype')
    budget = _Budget(reader)
    budget.skip(4)  # +120.
    budget.skip(budget.count(reader.i16()) * 4)  # +130.
    budget.skip(budget.count(reader.i32()) * 4)  # +160.
    for _ in range(budget.count(reader.i16())):  # +178: marker,4strings,20B.
        budget.skip(1)
        for _ in range(4):
            budget.text()
        budget.skip(20)
    budget.skip(12 * 4)  # Source>=3601 twelve native u32 fields.
    for _ in range(budget.count(reader.i32())):  # +60; unsigned child version.
        version = reader.u8()
        budget.skip(22 + (2 if version >= 2 else 0))
    budget.skip(budget.count(reader.u32()) * 12)  # +D8.
    budget.skip(budget.count(reader.u32()) * 14)  # +78.
    budget.skip(24)  # Flags/references +1F3 through +1F5.
    budget.skip(budget.count(reader.i8()) * 5)  # +48.
    for width in (28, 28, 12):  # +A8,+90,+C0.
        budget.skip(budget.count(reader.i32()) * width)
    budget.skip(40 + 2 + 1 + 11)
    if reader.offset - budget.start + 12 > MAX_RECORD_BYTES:
        raise ValueError('Saved NATION record exceeds byte budget')
    stored_ordinal = reader.u32()
    native_id = reader.u32()
    secondary_id = reader.u32()
    if stored_ordinal != ordinal:
        raise ValueError('Saved NATION database ordinal mismatch')
    return {'database_index': ordinal, 'native_id': native_id,
            'secondary_id': secondary_id}


def skip_nation(reader, ordinal, kind):
    """Consume a supported NATION row without projecting its identity."""
    read_nation_identity(reader, ordinal, kind)
