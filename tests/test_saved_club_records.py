import struct

import pytest

from fm_live_mcp.saved_club_records import read_club


class Reader:
    def __init__(self, data):
        self.data = data
        self.offset = 0

    def take(self, size):
        if type(size) is not int or size < 0 or size > len(self.data) - self.offset:
            raise ValueError('Truncated test input')
        result = self.data[self.offset:self.offset + size]
        self.offset += size
        return result

    def skip(self, size):
        self.take(size)

    def u8(self):
        return int.from_bytes(self.take(1), 'little')

    def i8(self):
        return int.from_bytes(self.take(1), 'little', signed=True)

    def i16(self):
        return int.from_bytes(self.take(2), 'little', signed=True)

    def u32(self):
        return int.from_bytes(self.take(4), 'little')

    def text(self, max_bytes=8192):
        length = self.u32()
        if length > max_bytes:
            raise ValueError('Text budget exceeded')
        return self.take(length).decode('utf-8')


def text(value):
    raw = value.encode()
    return struct.pack('<I', len(raw)) + raw


def stats(marker=2, version=2):
    return bytes([marker]) + bytes(40) + bytes([version]) + bytes((18 + (version > 1)) * 4 + 4 + 48 + 24 + 16 + 4 + (12 if marker >= 2 else 0) + 4)


def extended():
    group = bytes(5) + stats() + b'\1' + bytes(8) + b'\0'
    result = bytes(66) + group * 4 + bytes(67)
    result += b'\1' + stats() + struct.pack('<I', 2) + bytes(98)
    result += bytes(71) + b'\1' + bytes(19) + bytes(67)
    return result


def record(*, ordinal=7, kind=0, selector=2, name='Stored Club', short_name='Club', base_count=0):
    prefix = (bytes(4) if kind == 12 else b'') + bytes(26) + text(name) + text(short_name)
    front = bytes(8) + b'\1' + struct.pack('<I', 19) + bytes([selector])
    if selector == 0:
        front += bytes(45)
    elif selector == 1:
        front += extended()
    middle = b'\2' + b'\1' + bytes(18 + 1 + 4) + b'\2' + bytes(18 + 2 + 4)
    end = b'\1' + bytes(12) + bytes(6)
    base = bytes(3) + bytes([base_count]) + bytes(4 * base_count) + bytes(7) + b'\1' + bytes(16) + struct.pack('<h', 1) + bytes(28)
    return prefix + front + middle + end + base + struct.pack('<III', ordinal, 688, 123)


@pytest.mark.parametrize('kind', [0, 12])
@pytest.mark.parametrize('selector', [0, 1, 2, 255])
def test_complete_records(kind, selector):
    data = record(kind=kind, selector=selector, base_count=2)
    reader = Reader(data)
    assert read_club(reader, 7, kind) == {
        'database_index': 7, 'native_id': 688, 'secondary_id': 123,
        'record_kind': 'club' if kind == 0 else 'league_body_club',
        'name': 'Stored Club', 'short_name': 'Club',
    }
    assert reader.offset == len(data)


def test_empty_names_are_unknown():
    result = read_club(Reader(record(name='', short_name='')), 7, 0)
    assert result['name'] is None and result['short_name'] is None


def test_every_truncated_extended_record_fails():
    data = record(selector=1)
    for end in range(len(data)):
        with pytest.raises((ValueError, UnicodeError)):
            read_club(Reader(data[:end]), 7, 0)


def test_identity_mismatch_fails():
    with pytest.raises(ValueError, match='ordinal'):
        read_club(Reader(record(ordinal=8)), 7, 0)


@pytest.mark.parametrize('ordinal,kind', [(True, 0), (-1, 0), (2_000_000, 0), (0, True), (0, -1), (0, 3)])
def test_bad_selector_or_ordinal_fails_before_reads(ordinal, kind):
    with pytest.raises(ValueError):
        read_club(Reader(b''), ordinal, kind)


def test_signed_vector_and_text_budget_fail():
    prefix = bytes(26) + text('x') + text('y')
    with pytest.raises(ValueError, match='reference count'):
        read_club(Reader(prefix + bytes(8) + b'\xff'), 0, 0)
    with pytest.raises(ValueError, match='Text budget'):
        read_club(Reader(bytes(26) + struct.pack('<I', 8193)), 0, 0)


@pytest.mark.parametrize('bad_count', [-1, 4097])
def test_base_count_bounds_reject_corrupt_records(bad_count):
    data = bytearray(record())
    base_start = len(data) - 70
    struct.pack_into('<h', data, base_start + 5, bad_count)
    with pytest.raises(ValueError, match='base vector count'):
        read_club(Reader(bytes(data)), 7, 0)


def test_extended_native_history_limit_rejects_corrupt_record():
    data = bytearray(record(selector=1))
    front_start = 26 + len(text('Stored Club')) + len(text('Club'))
    delegate_start = front_start + 8 + 1 + 4 + 1
    group_size = 5 + len(stats()) + 1 + 8 + 1
    history_offset = delegate_start + 66 + 4 * group_size + 67 + 1 + len(stats())
    struct.pack_into('<I', data, history_offset, 61)
    with pytest.raises(ValueError, match='history count'):
        read_club(Reader(bytes(data)), 7, 0)


@pytest.mark.parametrize('signed_count', [-128, -1, 0])
def test_native_nonpositive_middle_and_end_counts_are_empty(signed_count):
    data = record()
    middle_start = 26 + len(text('Stored Club')) + len(text('Club')) + 14
    original_middle_size = 1 + 24 + 25
    end_start = middle_start + original_middle_size
    count = struct.pack('<b', signed_count)
    data = data[:middle_start] + count + count + bytes(6) + data[end_start + 19:]
    reader = Reader(data)
    result = read_club(reader, 7, 0)
    assert result['native_id'] == 688 and reader.offset == len(data)


def test_opt_in_team_indices_preserve_default_projection_and_signed_slots():
    data = bytearray(record(base_count=4))
    # Replace only the first shared-base vector's four signed words.
    base_length = 3 + 1 + 4 * 4 + 7 + 1 + 16 + 2 + 28 + 12
    start = len(data) - base_length
    struct.pack_into('<4i', data, start + 4, 545, -1, -2, 545)
    plain_reader = Reader(data)
    plain = read_club(plain_reader, 7, 0)
    rich_reader = Reader(data)
    rich = read_club(rich_reader, 7, 0, include_team_indices=True)
    assert rich.pop('team_indices') == [545, None, -2, 545]
    assert rich.pop('unverified_negative_team_indices') == [{'native_slot': 2, 'raw_word': -2}]
    assert rich == plain and rich_reader.offset == plain_reader.offset == len(data)


def test_shared_base_export_and_empty_opt_in_vector():
    from fm_live_mcp.saved_club_records import read_base
    wire = bytes(3 + 8 + 1 + 2) + struct.pack('<III', 7, 123, 456)
    reader = Reader(wire)
    assert read_base(reader, 7, include_team_indices=True) == {
        'native_id': 123, 'secondary_id': 456, 'team_indices': [],
    }
    assert reader.offset == len(wire)


def test_invalid_team_index_selection_rejected_before_reading():
    with pytest.raises(ValueError, match='selection'):
        read_club(Reader(b''), 7, 0, include_team_indices=1)
