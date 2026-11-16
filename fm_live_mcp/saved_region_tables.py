"""Forward generic name, REGION and LOCAL_REGION source3754/minor9 rows.

The caller verifies source context and owns entity-table headers and footers.
These readers retain no names, maps or entity collections.
"""

import struct

MAX_NAME_ROWS = 2_000_000
MAX_DATABASE_SLOTS = 2_000_000
MAX_LANGUAGES = 4096
NAME_CHUNK_ROWS = 4096
_NAME_ROW = struct.Struct('<Hi4sH')


def skip_name_tables(reader):
    """Consume root+C8/D0/D8 mode0 containers, validating every original index.

    Native14C3A2C rejects negative indices and repairs other ordinal mismatches.
    The saved reader rejects repairs/disorder explicitly rather than silently
    treating a repaired index as the original saved identity.
    """
    counts = []
    for _ in range(3):
        count = reader.u32()
        if count > MAX_NAME_ROWS:
            raise ValueError('Saved generic name table exceeds row budget')
        ordinal = 0
        while ordinal < count:
            amount = min(NAME_CHUNK_ROWS, count - ordinal)
            raw = reader.take(amount * _NAME_ROW.size)
            for _, stored_index, _, _ in _NAME_ROW.iter_unpack(raw):
                if stored_index < 0:
                    raise ValueError('Saved generic name table has negative original index')
                if stored_index != ordinal:
                    raise ValueError('Saved generic name table requires unverified index repair or disorder')
                ordinal += 1
        counts.append(count)
    return tuple(counts)


def _validate(ordinal, kind, label, *, zero_subtype):
    if type(ordinal) is not int or not 0 <= ordinal < MAX_DATABASE_SLOTS:
        raise ValueError(f'Invalid saved {label} ordinal')
    if type(kind) is not int or not -128 <= kind <= 127 or (zero_subtype and kind != 0):
        raise ValueError(f'Unsupported saved {label} subtype')


def _identity(reader, ordinal, label):
    stored_index = reader.u32()
    reader.skip(8)
    if stored_index != ordinal:
        raise ValueError(f'Saved {label} database ordinal mismatch')


def skip_region(reader, ordinal, kind):
    """Consume type19 REGION body; its native factory ignores subtype."""
    _validate(ordinal, kind, 'REGION', zero_subtype=False)
    reader.skip(16 * 4 + 2)
    _identity(reader, ordinal, 'REGION')


def skip_local_region(reader, ordinal, kind):
    """Consume LOCAL_REGION body including its variable language links."""
    _validate(ordinal, kind, 'LOCAL_REGION', zero_subtype=True)
    #13796C0: nation/population, eleven bytes, u16, one byte.
    reader.skip(4 + 4 + 11 + 2 + 1)
    count = reader.i16()
    if not 0 <= count <= MAX_LANGUAGES:
        raise ValueError('Saved LOCAL_REGION language count exceeds supported bounds')
    reader.skip(count * 5 + 4)  # u32 language index/u8 weight; weather index.
    _identity(reader, ordinal, 'LOCAL_REGION')
