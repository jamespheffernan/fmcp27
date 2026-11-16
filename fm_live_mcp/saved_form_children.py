"""Bounded pre-form child geometry for the pinned3754/9 F0 writer profile.

No identities are resolved. The typed-reference profile is conditional on the
same explicit native branch state used by the verified source controls: stream
bit1 set, local2C98=1, root80A clear, global3522=0/global3523=1. It is not inferred
from a parent raw64 parameter. Sources:154DD68/154E184,3F94FC0,
11E8640/11EA0F8,11E8EFC/11EA670,11E9524/11EAA78.
"""
import struct


class UnsupportedFormChild(ValueError):
    def __init__(self, native_reader, offset, reason):
        self.native_reader = native_reader
        self.offset = offset
        self.reason = reason
        super().__init__(f'{reason} at {offset} ({native_reader})')


class BoundedReader:
    """An absolute-coordinate reader restricted to one caller-supplied span."""
    def __init__(self, data, start, limit):
        try:
            view = memoryview(data)
        except TypeError as error:
            raise ValueError('Saved form input must be a byte buffer') from error
        try:
            if view.ndim != 1 or view.itemsize != 1:
                raise ValueError('Saved form input must use byte offsets')
            size = view.nbytes
        finally:
            view.release()
        if (type(start) is not int or type(limit) is not int
                or not 0 <= start <= limit <= size):
            raise ValueError('Invalid bounded saved form span')
        self.data = data
        self.offset = start
        self.size = limit

    def skip(self, size):
        if type(size) is not int or size < 0 or size > self.size - self.offset:
            raise ValueError('Truncated saved form container inside record bound')
        self.offset += size

    def take(self, size):
        start = self.offset
        self.skip(size)
        return bytes(self.data[start:self.offset])

    def u8(self):
        return self.take(1)[0]

    def u16(self):
        return struct.unpack('<H', self.take(2))[0]

    def i16(self):
        return struct.unpack('<h', self.take(2))[0]

    def u32(self):
        return struct.unpack('<I', self.take(4))[0]

    def current_version(self, expected, native):
        start = self.offset
        if self.u8() != expected:
            raise ValueError(f'Unsupported current-writer {native} version at {start}')

    def presence(self, name):
        offset = self.offset
        value = self.u8()
        if value not in (0, 1):
            raise ValueError(f'Invalid current-writer {name} presence at {offset}')
        return value


def _group_reference(reader):
    marker_offset = reader.offset
    marker = reader.u8()
    if marker not in (0, 1):
        raise UnsupportedFormChild(
            '0x11073A8', marker_offset,
            'tagged group reference outside supported0/1 profile')
    index = reader.u32()
    if marker == 1 and index != 0xFFFFFFFF:
        reader.skip(4)


def skip_vector00_row(reader):
    """154E184, including the encountered optional3F94FC0 row."""
    reader.current_version(3, '154E184')
    root_index = reader.i16()  #1118718/root40 compact signed16 branch.
    if root_index == -2:
        reader.skip(4)
    if reader.presence('154E184 extra'):
        reader.current_version(1, '3F94FC0')
        reader.skip(4)  #native+18
        reader.skip(4)  #1104D70 PERSON raw32 in this explicit local profile.
        reader.skip(1)
        _group_reference(reader)
        _group_reference(reader)
        reader.skip(6)  #native+21,+20,+1C
    reader.skip(11)  #native+20 raw4,+2A/+28 raw2 each,+2E/+30/+32
    reader.skip(4)  #1104FB0 PERSON raw32, not parent raw64.
    _group_reference(reader)
    reader.skip(9)  #native+2F,+24 raw4,+2C/+2D,+31/+33


def skip_optional30(reader):
    reader.current_version(4, '11E8640')
    reader.skip(41)


def skip_optional38(reader):
    reader.current_version(5, '11E8A6C')
    reader.skip(58)


def skip_optional40(reader):
    reader.current_version(4, '11E8EFC')
    #Four raw4 fields; two1117820 raw4 references under streambit1/localC98=1;
    #raw8 at+8/+C,raw8+30,raw4+38,raw8+0,four bytes,raw8+40/raw4+48.
    reader.skip(68)


def skip_optional48(reader):
    reader.current_version(1, '11E9354')
    reader.skip(12)  #raw4+4,1117820 raw4+8,raw4+0.


def skip_optional50(reader):
    reader.current_version(1, '11E9524')
    reader.skip(16)  #raw4+4,two1117820 raw4 references,raw4+0.
