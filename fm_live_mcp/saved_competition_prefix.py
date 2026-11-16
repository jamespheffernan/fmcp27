"""Read the checked 3754/minor-9 COMP prefix, stopping before history presence.

The caller establishes the full-loader, mode-zero source context. Names appear
only in serialized branch four; missing strings are not resolved from live data.
"""

MAX_NAME_BYTES = 8192
MAX_FIRST_VECTOR_ITEMS = 6


def read_prefix(reader):
    reader.skip(14)  # Two scalar bytes and the twelve-byte packed-colour transport.
    name_branch = reader.u8()
    native_level_code = reader.i8()  # COMP+0x1AA, signed native level getter.
    reader.skip(3)

    settings_marker = reader.u8()
    reader.skip(6 if settings_marker <= 1 else 7)
    encoding = reader.u8()
    reader.skip(12 if encoding < 2 else 14 if encoding == 2 else 15)
    reader.skip(9)

    name = short_name = None
    if name_branch == 4:
        short_name = reader.text(max_bytes=MAX_NAME_BYTES)  # Native COMP+0x48 first.
        name = reader.text(max_bytes=MAX_NAME_BYTES)  # Then COMP+0x40.

    reader.skip(16 + 2)
    reputation = reader.i16()  # COMP+0x188, signed native reputation getter.
    reader.skip(4 + 1 + 6 + 24)
    count = reader.u32()
    if type(count) is not int or not 0 <= count <= MAX_FIRST_VECTOR_ITEMS:
        raise ValueError('Saved competition prefix vector exceeds native bound')
    reader.skip(count * 2)

    return {
        'name': name,
        'short_name': short_name,
        'stored_name_state': (
            'serialized_branch4' if name_branch == 4 else 'not_serialized_by_this_record'
        ),
        'reputation': reputation,
        'native_level_code': native_level_code,
        'level': None if native_level_code == 100 else native_level_code + 1,
    }
