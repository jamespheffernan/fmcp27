import struct

import pytest

from fm_live_mcp import saved_database_tables as tables

class Reader:
    def __init__(self, data):
        self.data = data
        self.offset = 0
        self.largest_take = 0

    def take(self, n):
        if type(n) is not int or n < 0 or self.offset + n > len(self.data):
            raise ValueError('truncated')
        self.largest_take = max(self.largest_take, n)
        result = self.data[self.offset:self.offset + n]
        self.offset += n
        return result

    def skip(self, n):
        self.take(n)

    def u8(self):
        return self.take(1)[0]

    def u32(self):
        return struct.unpack('<I', self.take(4))[0]


def table(stride, count=1, *, flags=0, subtype=0, auxiliary=0):
    rows = []
    for index in range(count):
        row = bytearray(stride)
        row[0] = subtype
        struct.pack_into('<III', row, stride - 12, index, 102406 + index, index)
        rows.append(row)
    return (struct.pack('<IB', count, flags) + b''.join(rows)
            + struct.pack('<I', auxiliary) + bytes(auxiliary * 12) + struct.pack('<BI', 1, 17))


def test_exact_downstream_cursor_and_independent_identity_words():
    wire = table(77, 2, auxiliary=2) + table(43, 3, auxiliary=1)
    reader = Reader(wire + b'CLUB')
    assert tables.reach_clubs(reader) == {'award_count': 2, 'city_count': 3}
    assert reader.offset == len(wire)
    assert reader.take(4) == b'CLUB'


def test_empty_tables_and_chunk_boundaries():
    for count in [0, 1023, 1024, 1025]:
        wire = table(77, count) + table(43, count)
        reader = Reader(wire)
        assert tables.reach_clubs(reader) == {'award_count': count, 'city_count': count}
        assert reader.offset == len(wire)
        assert reader.largest_take <= 1024 * 77


@pytest.mark.parametrize('label,stride', [('award', 77), ('city', 43)])
@pytest.mark.parametrize('change', ['flags', 'subtype', 'ordinal', 'count', 'auxiliary'])
def test_malformed_profiles_fail_without_recovery(label, stride, change):
    bad = bytearray(table(stride))
    if change == 'flags':
        bad[4] = 1
    elif change == 'subtype':
        bad[5] = 12
    elif change == 'ordinal':
        struct.pack_into('<I', bad, 5 + stride - 12, 5)
    elif change == 'count':
        struct.pack_into('<I', bad, 0, 100001)
    else:
        struct.pack_into('<I', bad, 5 + stride, 100001)
    wire = bytes(bad) + table(43) if label == 'award' else table(77) + bytes(bad)
    with pytest.raises(ValueError):
        tables.reach_clubs(Reader(wire))


def test_every_truncation_rejected():
    wire = table(77, 2, auxiliary=1) + table(43, 2, auxiliary=1)
    for end in range(len(wire)):
        with pytest.raises(ValueError):
            tables.reach_clubs(Reader(wire[:end]))


def test_mismatched_reference_width_fails_alignment():
    wire = bytearray(table(77))
    wire[5 + 24:5 + 24] = b'\0\0\0\0'  # A widened field invalidates fixed profile alignment.
    with pytest.raises(ValueError):
        tables.reach_clubs(Reader(bytes(wire) + table(43)))


def test_footer_nonzero_auxiliary_and_zero_suffix_values():
    reader = Reader(struct.pack('<I', 2) + bytes(24) + bytes(5) + b'N')
    assert tables.read_table_footer(reader) == {'auxiliary_count': 2, 'final_byte': 0, 'final_word': 0}
    assert reader.take(1) == b'N'
