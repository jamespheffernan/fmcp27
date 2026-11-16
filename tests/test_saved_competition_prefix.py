import struct

import pytest

from fm_live_mcp import saved_competition_prefix as prefix


class Reader:
    def __init__(self, data):
        self.data = data
        self.offset = 0

    def take(self, count):
        if count < 0 or self.offset + count > len(self.data):
            raise ValueError('truncated')
        value = self.data[self.offset:self.offset + count]
        self.offset += count
        return value

    def skip(self, count):
        self.take(count)

    def u8(self):
        return self.take(1)[0]

    def i8(self):
        return struct.unpack('<b', self.take(1))[0]

    def i16(self):
        return struct.unpack('<h', self.take(2))[0]

    def u32(self):
        return struct.unpack('<I', self.take(4))[0]

    def text(self, max_bytes=8192):
        length = self.u32()
        if length > max_bytes:
            raise ValueError('text exceeds bound')
        return self.take(length).decode('utf-8')


def wire(*, branch=0, level=0, reputation=158, short_name='', name='',
         settings=0, encoding=0, vector=()):
    data = bytearray(14)
    data.extend(struct.pack('<Bb', branch, level))
    data.extend(bytes(3))
    data.append(settings)
    data.extend(bytes(6 if settings <= 1 else 7))
    data.append(encoding)
    data.extend(bytes(12 if encoding < 2 else 14 if encoding == 2 else 15))
    data.extend(bytes(9))
    if branch == 4:
        for text in (short_name, name):
            raw = text.encode('utf-8')
            data.extend(struct.pack('<I', len(raw)))
            data.extend(raw)
    data.extend(bytes(16 + 2))
    data.extend(struct.pack('<h', reputation))
    data.extend(bytes(4 + 1 + 6 + 24))
    data.extend(struct.pack('<I', len(vector)))
    for value in vector:
        data.extend(struct.pack('<H', value))
    return bytes(data)


def test_inline_name_order_and_exact_history_boundary():
    data = wire(branch=4, short_name='Short é', name='Full competition name',
                level=2, reputation=187, vector=(0, 65535))
    reader = Reader(data + b'\1HISTORY')
    assert prefix.read_prefix(reader) == {
        'name': 'Full competition name', 'short_name': 'Short é',
        'stored_name_state': 'serialized_branch4', 'reputation': 187,
        'native_level_code': 2, 'level': 3,
    }
    assert reader.offset == len(data)
    assert reader.take(8) == b'\1HISTORY'


def test_absent_and_empty_names_remain_distinct():
    absent = prefix.read_prefix(Reader(wire(branch=14)))
    empty = prefix.read_prefix(Reader(wire(branch=4)))
    assert absent['name'] is None and absent['short_name'] is None
    assert absent['stored_name_state'] == 'not_serialized_by_this_record'
    assert empty['name'] == empty['short_name'] == ''
    assert empty['stored_name_state'] == 'serialized_branch4'


@pytest.mark.parametrize('level,mapped', [(-128, -127), (-1, 0), (0, 1), (99, 100), (100, None), (127, 128)])
@pytest.mark.parametrize('reputation', [-32768, -1, 0, 32767])
def test_native_signed_semantics_and_level_sentinel(level, mapped, reputation):
    result = prefix.read_prefix(Reader(wire(level=level, reputation=reputation)))
    assert result['native_level_code'] == level and result['level'] == mapped
    assert result['reputation'] == reputation


@pytest.mark.parametrize('settings', [0, 1, 2, 255])
@pytest.mark.parametrize('encoding', [0, 1, 2, 3, 255])
def test_variable_prefix_widths(settings, encoding):
    data = wire(branch=4, settings=settings, encoding=encoding,
                name='Distinct name', short_name='S', vector=range(6))
    reader = Reader(data + b'\0')
    result = prefix.read_prefix(reader)
    assert result['name'] == 'Distinct name' and reader.offset == len(data)
    assert reader.u8() == 0


def test_every_prefix_truncation_is_rejected():
    data = wire(branch=4, short_name='Short', name='Longer',
                settings=2, encoding=3, vector=range(6))
    for end in range(len(data)):
        with pytest.raises(ValueError):
            prefix.read_prefix(Reader(data[:end]))
    assert prefix.read_prefix(Reader(data))['name'] == 'Longer'


def test_names_are_bounded_and_strict_utf8():
    maximum = 'x' * 8192
    assert prefix.read_prefix(Reader(wire(branch=4, name=maximum)))['name'] == maximum
    with pytest.raises(ValueError):
        prefix.read_prefix(Reader(wire(branch=4, short_name='x' * 8193)))
    data = bytearray(wire(branch=4, short_name='x'))
    data[52] = 255  # First short-name byte after the minimal fixed prefix and u32 length.
    with pytest.raises(UnicodeDecodeError):
        prefix.read_prefix(Reader(data))


def test_first_vector_count_rejects_unproved_wider_source():
    with pytest.raises(ValueError, match='native bound'):
        prefix.read_prefix(Reader(wire(vector=range(7))))
