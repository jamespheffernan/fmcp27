"""Bounded PLAYER tail, source3754/minor9 conditional raw64 writer profile.

Starts after the F0 optional child and ends before ACTUAL_PERSON. Raw references
are consumed without resolving identities or claiming native loader globals.
"""

MAX_ROWS = 4096


class UnsupportedTail(ValueError):
    """An unproved native child or writer version, with its exact cursor."""

    def __init__(self, native, offset):
        self.native = native
        self.offset = offset
        super().__init__(f'Unsupported PLAYER tail {native} at {offset}')


def read_tail(reader, *, source_major=3754, minor=9,
              reference_mode='raw64', direct_references=True):
    """Consume the supported tail and expose the stored native+270 scale byte."""
    if (type(source_major) is not int or type(minor) is not int or
            (source_major, minor) != (3754, 9)):
        raise ValueError('Unsupported PLAYER tail source')
    if reference_mode != 'raw64' or direct_references is not True:
        raise ValueError('Unsupported PLAYER tail reference profile')
    start = reader.offset
    work = 0

    def count(width=4):
        nonlocal work
        n = reader.u32() if width == 4 else reader.u8()
        work += n
        if work > MAX_ROWS:
            raise ValueError('PLAYER tail aggregate work budget')
        return n

    def version(actual, expected, native):
        if actual != expected:
            raise UnsupportedTail(native, reader.offset)

    def present():
        marker = reader.u8()
        if marker not in (0, 1):
            raise ValueError('Invalid PLAYER current-writer presence')
        return marker == 1

    if present():  # 13AC958; current version4.
        version(reader.u8(), 4, '13AC958 version')
        reader.skip(23 + 1 + 4 + 8 + 21)
    if present():  # 1347364.
        version(reader.i16(), 31, '1347364 version')
        reader.skip(2)
        for _ in range(count()):
            reader.skip(2 + 1 + 4 + 1 + 8 + 8)
        for _ in range(count()):
            version(reader.u8(), 2, '15739B8 version')
            reader.skip(7)
        reader.skip(43)
        version(reader.u8(), 2, '13486E4 version')
        reader.skip(4 + 4 + 1 + 4)
        if present():
            reader.skip(1 + 16)
        version(reader.i16(), 2, 'D8A570 version')
        for _ in range(count()):
            version(reader.u8(), 0, 'D8A570 writer marker')
            reader.skip(8 + 2 + 2 + 1)  # NATIONAL_TEAM_CONTAINER raw64.
        reader.skip(4 + 1 + 4 + 4 + 4 + 4)
    rows = reader.i8()
    for _ in range(max(rows, 0)):
        subtype = reader.i8()
        if subtype == -1:
            continue
        if subtype != 0:
            raise UnsupportedTail('40608E4 subtype ' + str(subtype), reader.offset)
        reader.skip(4)
    flag = reader.u8()
    if flag & 1:  # 138EBE4 / 47FD68C modern4.
        wrapper_version = reader.u8()
        version(reader.u8(), 4, '47FD68C version')
        reader.skip(count() * 19)
        for _ in range(6):
            reader.skip(count() * 5)
        reader.skip(4)
        if wrapper_version >= 2:
            reader.skip(1)
    reader.skip(8)  # PLAYER+130/+138.
    reader.skip(14)  # 154F2F0 before15944C0.
    reader.skip(count() * 6)
    reader.skip(8)
    scale_offset = reader.offset
    scale_byte = reader.u8()
    reader.skip(7)
    return {
        'start': start, 'end': reader.offset,
        'actual_person_start': reader.offset,
        'scale_offset': scale_offset, 'scale_byte': scale_byte,
        'stored_attribute_scale_flag_bit7': bool(scale_byte & 128),
        'source_profile': 'source3754_minor9_conditional_raw64',
        'complete_player_specific_tail': True,
    }
