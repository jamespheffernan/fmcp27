"""Forward saved CLUB records for the verified source3754/minor9 full loader.

Call only after the component/header reader establishes SUPPORTED_SOURCE and
full-loader mode. Input is immediately after a table subtype byte. This module
never seeks, opens files, resolves live identities or returns opaque wire fields.
"""
import struct

SUPPORTED_SOURCE = (3754, 9)
MAX_BASE_VALUES = 4096
MAX_DATABASE_SLOTS = 2_000_000


def _count(value, maximum, label):
    if not 0 <= value <= maximum:
        raise ValueError(f'{label} exceeds supported saved CLUB bounds')
    return value


def _stats(reader):
    marker = reader.u8()
    reader.skip(40)
    version = reader.u8()
    reader.skip((18 + (version > 1)) * 4 + 4 + 48 + 24 + 16 + 4)
    if marker >= 2:
        reader.skip(12)
    reader.skip(4)


def _stats_group(reader):
    reader.skip(5)
    _stats(reader)
    for _ in range(2):
        reader.skip(reader.u8() * 8)


def _extended_delegate(reader):
    reader.skip(4 + 4 + 4 + 1 + 40 + 1 + 8 + 4)
    for _ in range(4):
        _stats_group(reader)
    reader.skip(20 + 4 + 2 + 4 + 4 + 1 + 1 + 3 + 4 + 4 + 3 + 1 + 8 + 4 + 4)
    optional = _count(reader.i8(), 127, 'Extended stats count')
    for _ in range(optional):
        _stats(reader)
    reader.skip(_count(reader.u32(), 60, 'Extended history count') * 49)
    reader.skip(4 + 1 + 20 + 4 + 4 + 8 + 4 + 4 + 2 + 12 + 8)
    reader.skip(_count(reader.i8(), 127, 'Extended item count') * 19)
    reader.skip(4 + 12 + 4 + 2 + 45)


def _front(reader):
    reader.skip(1 + 2 + 4 + 1)
    reader.skip(_count(reader.i8(), 127, 'CLUB reference count') * 4)
    selector = reader.u8()
    if selector == 0:
        reader.skip(45)
    elif selector == 1:
        _extended_delegate(reader)
    # Other selector bytes take the verified native null-delegate branch.


def _middle(reader):
    # Native DF1B78 skips the population for signed count <= 0.
    count = max(reader.i8(), 0)
    for _ in range(count):
        version = reader.u8()
        reader.skip(1 + 4 + 4 + 1 + 4 + 2 + 1 + 1)
        reader.skip(2 if version >= 2 else 1)
        reader.skip(4)


def _body_end(reader):
    # Native DF2374 population uses the same signed <= 0 empty branch.
    count = max(reader.i8(), 0)
    reader.skip(count * 12 + 6)


def read_base(reader, ordinal, *, include_team_indices=False):
    """Read the shared CLUB/NATIONAL container base and optional TEAM keys.

    The first vector is native CLUB_BASE+0x18. Its signed-i32 words resolve
    against the same-file TEAM_BASE table. Null and unverified negatives retain
    their source positions; the caller validates the selected table population.
    """
    if type(ordinal) is not int or not 0 <= ordinal < MAX_DATABASE_SLOTS:
        raise ValueError('Invalid saved CLUB base ordinal')
    if type(include_team_indices) is not bool:
        raise ValueError('Invalid CLUB team-index selection')
    reader.skip(3)
    team_words = None
    for index in range(5):
        count = reader.u8() if index < 2 else reader.i16()
        count = _count(count, MAX_BASE_VALUES, 'CLUB base vector count')
        if index == 0 and include_team_indices:
            team_words = [word for (word,) in struct.iter_unpack('<i', reader.take(count * 4))]
        else:
            reader.skip(count * 4)
    reader.skip(_count(reader.u8(), MAX_BASE_VALUES, 'CLUB opaque vector count') * 16)
    reader.skip(_count(reader.i16(), MAX_BASE_VALUES, 'CLUB detail count') * 28)
    stored_index = reader.u32()
    native_id = reader.u32()
    secondary_id = reader.u32()
    if stored_index != ordinal:
        raise ValueError('Saved CLUB database ordinal mismatch')
    result = {'native_id': native_id, 'secondary_id': secondary_id}
    if team_words is not None:
        result['team_indices'] = [None if word == -1 else word for word in team_words]
        unverified = [{'native_slot': index, 'raw_word': word}
                      for index, word in enumerate(team_words) if word < -1]
        if unverified:
            result['unverified_negative_team_indices'] = unverified
    return result


def read_club(reader, ordinal, kind, *, include_team_indices=False):
    """Consume one full record and return stored names and raw same-file identity.

    The caller verifies source3754/minor9, table ownership/count, subtype and the
    surrounding table footer. Empty stored strings become None; identity words
    are preserved without sentinel interpretation or joining another snapshot.
    """
    if type(ordinal) is not int or not 0 <= ordinal < MAX_DATABASE_SLOTS:
        raise ValueError('Invalid saved CLUB ordinal')
    if type(kind) is not int or kind not in (0, 12):
        raise ValueError('Unsupported saved CLUB record subtype')
    if type(include_team_indices) is not bool:
        raise ValueError('Invalid CLUB team-index selection')
    if kind == 12:
        reader.skip(4)
    reader.skip(20 + 6)
    name = reader.text(max_bytes=8192)
    short_name = reader.text(max_bytes=8192)
    _front(reader)
    _middle(reader)
    _body_end(reader)
    base = read_base(reader, ordinal, include_team_indices=include_team_indices)
    return {
        'database_index': ordinal,
        **base,
        'record_kind': 'club' if kind == 0 else 'league_body_club',
        'name': name or None,
        'short_name': short_name or None,
    }
