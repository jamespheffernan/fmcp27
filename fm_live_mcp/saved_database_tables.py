"""Walk the checked FM27 raw32 AWARD and fixed CITY wire profiles.

The caller establishes supported source encoding and forwards the metadata
cursor to AWARD count. AWARD's four-byte reference words are a checked corpus
profile, not interpreted reference identities. Other encodings, gaps, subtypes
and table flags are unsupported and fail closed; no byte-pattern recovery runs.
"""
import struct

MAX_TABLE_ROWS = 100_000
MAX_AUXILIARY_ROWS = 100_000
CHUNK_ROWS = 1024


def _count(reader, maximum, label):
    count = reader.u32()
    if type(count) is not int or not 0 <= count <= maximum:
        raise ValueError(f'{label} count exceeds supported budget')
    return count


def read_table_footer(reader):
    """Consume bounded auxiliary triples and the native byte/word suffix."""
    count = _count(reader, MAX_AUXILIARY_ROWS, 'Table auxiliary')
    reader.skip(count * 12)
    final_byte = reader.u8()
    final_word = reader.u32()
    return {
        'auxiliary_count': count,
        'final_byte': final_byte,
        'final_word': final_word,
    }


def _table(reader, label, stride):
    count = _count(reader, MAX_TABLE_ROWS, label)
    if reader.u8() != 0:
        raise ValueError(f'Unsupported {label} table flags')
    identity_offset = stride - 12
    ordinal = 0
    while ordinal < count:
        chunk_count = min(CHUNK_ROWS, count - ordinal)
        raw = reader.take(chunk_count * stride)
        if len(raw) != chunk_count * stride:
            raise ValueError(f'Truncated {label} row chunk')
        for local in range(chunk_count):
            start = local * stride
            if raw[start] != 0:
                raise ValueError(f'Unsupported {label} subtype at ordinal {ordinal + local}')
            stored, _primary, _secondary = struct.unpack_from(
                '<III', raw, start + identity_offset
            )
            if stored != ordinal + local:
                raise ValueError(f'{label} stored ordinal mismatch at {ordinal + local}')
            # Do not equate primary and secondary words or reject independent IDs.
            # Their interpretation is outside this cursor-only table walker.
        ordinal += chunk_count
    read_table_footer(reader)
    return count


def reach_clubs(reader):
    """Leave the sequential reader exactly at CLUB's count after two tables."""
    award_count = _table(reader, 'AWARD raw32 profile', 77)
    city_count = _table(reader, 'CITY fixed profile', 43)
    return {'award_count': award_count, 'city_count': city_count}
