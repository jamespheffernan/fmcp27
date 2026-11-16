"""Locate PLAYER+F0 from a corroborated, bounded tag2 source record.

Source3754/minor9 raw64 is conditional; neither PERSON identity nor native
loader acceptance follows from this walk. Native CFD388/CFEFE4,17F1BB8,
17F090C,43FC9B4,1326EC4,157E834,17F2174; evidence B34/B36/B43/B44.
"""
import struct
from . import saved_player_wire_prefix, saved_properties

_MAX_ROWS = 4096
_MAX_TEXT = 8192


class _BoundedReader:
    def __init__(self, data, start, limit):
        self.data, self.offset, self.limit = data, start, limit

    def take(self, size):
        if size < 0 or size > self.limit - self.offset:
            raise ValueError('Truncated PLAYER F0 locator inside record bound')
        start = self.offset
        self.offset += size
        return bytes(self.data[start:self.offset])

    def skip(self, size):
        if size < 0 or size > self.limit - self.offset:
            raise ValueError('Truncated PLAYER F0 locator inside record bound')
        self.offset += size

    def u8(self):
        return self.take(1)[0]

    def u32(self):
        return int.from_bytes(self.take(4), 'little')


def _fixed(size):
    def child(data, start, limit):
        reader = _BoundedReader(data, start, limit)
        reader.skip(size)
        return {'end': reader.offset}
    return child


def _training(data, start, limit):
    reader = _BoundedReader(data, start, limit)
    version = reader.u8()
    reader.skip(10 if version >= 2 else 8)
    return {'end': reader.offset}


def _typed(data, start, limit):
    reader = _BoundedReader(data, start, limit)
    reader.u8()  # 17F090C container version has no wire-width branch here.
    count = struct.unpack('<i', reader.take(4))[0]
    if count < 0:
        raise ValueError('Negative typed-vector count differs from source writer')
    if count > _MAX_ROWS:
        return {'end': reader.offset, 'state': 'stopped',
                'next_native_reader': '0x17F090C', 'stop_reason': 'typed_vector_work_budget'}
    # Reuse the production bounded property walker; the same budget covers all
    # values, including recursive maps/vectors, across this serialized vector.
    walker = saved_properties._Walker(reader)
    for _ in range(count):
        reader.skip(6)  # row version, raw byte14 and raw4 field10
        try:
            walker.variant(0)
        except ValueError as error:
            if str(error).startswith('Unsupported saved property variant '):
                return {'end': int(str(error).rsplit(' at ', 1)[1]), 'state': 'stopped',
                        'next_native_reader': '0x43FC9B4',
                        'stop_reason': str(error)}
            raise
    return {'end': reader.offset}


def locate_f0(data, record_start, limit):
    """Return present/absent/stopped with absolute offsets and exclusive bound.

    The caller supplies a corroborated tag2 boundary and enclosing maximum end.
    No scanning, pointer inference, identity lookup or native globals are used.
    Unsupported positive children stop explicitly; malformed/truncated inputs
    raise ValueError. Absent means the checked serialized presence byte is zero.
    """
    packet = saved_player_wire_prefix.prefix_probe(
        data, record_start, limit, _child_readers={
            '0x17F090C': _typed, '0x157E834': _fixed(7),
            '0x1326EC4': _training, '0x17F2174': _fixed(13)})
    out = {'start': record_start, 'end': packet['end'], 'limit': limit,
           'state': 'stopped', 'f0_start': None, 'payload_start': None,
           'wire_profile': packet['wire_profile'], 'wire_profile_is_conditional': True,
           'native_build_sha256': packet['native_build_sha256'],
           'native_loader_acceptance': False, 'complete_person': False,
           'validated_markers': packet['validated_markers'], 'counts': packet['counts']}
    if packet['next_native_reader'] != '0x43836A4':
        out.update(next_native_reader=packet['next_native_reader'],
                   stop_reason=packet['stop_reason'])
        return out
    reader = _BoundedReader(data, packet['end'], limit)
    length = reader.u32()
    if length > _MAX_TEXT:
        out.update(end=reader.offset, next_native_reader='0x43836A4',
                   stop_reason='player_e8_text_work_budget')
        return out
    try:
        reader.take(length).decode('utf-8')
    except UnicodeDecodeError as error:
        raise ValueError('Invalid PLAYER+E8 UTF-8') from error
    reader.skip(12)  # native+238..243, opaque source fields
    marker_offset = reader.offset
    marker = reader.u8()
    if marker not in (0, 1):
        raise ValueError('Invalid current-writer PLAYER+108 presence')
    out['validated_markers'].append({'offset': marker_offset, 'kind': 'player108_presence', 'value': marker})
    if marker:
        reader.skip(30)
    marker_offset = reader.offset
    marker = reader.u8()
    if marker not in (0, 1):
        raise ValueError('Invalid current-writer PLAYER+F0 presence')
    out['validated_markers'].append({'offset': marker_offset, 'kind': 'player_f0_presence', 'value': marker})
    out.update(end=reader.offset, state='present' if marker else 'absent',
               f0_presence_offset=marker_offset, stop_reason=None,
               next_native_reader='0x11E7C4C' if marker else None)
    if marker:
        out.update(f0_start=reader.offset, payload_start=reader.offset)
    return out
