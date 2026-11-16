"""Sequential NATIONAL_TEAM_CONTAINER records for source3754/minor9.

The caller establishes the supported source, full-loader mode and table bounds.
Input follows the subtype byte; output leaves the next subtype/footer untouched.
Only ordinary kind-zero containers are proved. No saved references are resolved.
"""

from . import saved_club_records, saved_competition_records, saved_properties

SUPPORTED_SOURCE = (3754, 9)
MAX_DATABASE_SLOTS = 2_000_000
MAX_VECTOR_ITEMS = 100_000
MAX_RECORD_ITEMS = 200_000
MAX_TEXT_BYTES = 8192
MAX_RECORD_TEXT_BYTES = 1024 * 1024


class _Budget:
    def __init__(self):
        self.items = 0
        self.text_bytes = 0

    def count(self, count, maximum=MAX_VECTOR_ITEMS):
        if not 0 <= count <= maximum:
            raise ValueError('Saved national container vector exceeds bounds')
        self.items += count
        if self.items > MAX_RECORD_ITEMS:
            raise ValueError('Saved national container exceeds item budget')
        return count

    def text(self, reader):
        size = reader.u32()
        self.text_bytes += size
        if size > MAX_TEXT_BYTES or self.text_bytes > MAX_RECORD_TEXT_BYTES:
            raise ValueError('Saved national container text exceeds byte budget')
        try:
            reader.take(size).decode('utf-8')
        except UnicodeDecodeError as error:
            raise ValueError('Invalid saved national container UTF-8 text') from error


def _vector(reader, budget, count, stride, maximum=MAX_VECTOR_ITEMS):
    reader.skip(budget.count(count, maximum) * stride)


def _prefix(reader, budget):
    reader.skip(14)
    # Native signed nonpositive populations skip these transport loops.
    _vector(reader, budget, max(reader.i32(), 0), 8)
    reader.skip(33)
    saved_properties.skip_property_map(reader)
    saved_properties.skip_property_vector(reader)
    for stride in (2, 4):
        _vector(reader, budget, reader.u32(), stride, 120)
    _vector(reader, budget, max(reader.i8(), 0), 4, 127)
    for _ in range(20):
        _vector(reader, budget, max(reader.i8(), 0), 4, 127)
    _vector(reader, budget, max(reader.i16(), 0), 4, 32767)


def _named_child(reader, budget):
    # Native12A91D4. Version is an unsigned byte, not a source version.
    version = reader.u8()
    for _ in range(3):
        budget.text(reader)
    reader.skip(13)
    if version >= 2:
        reader.skip(4)
        _vector(reader, budget, reader.u32(), 7)
        reader.skip(5)
    reader.skip(4)
    if version >= 5:
        reader.skip(5)
    reader.skip(19 + (version >= 3) + (version >= 4) + (version >= 6))


def _named_and_identity_children(reader, budget):
    for _ in range(2):
        # These signed counts feed native allocations; negatives are rejected.
        for _ in range(budget.count(reader.i16(), 32767)):
            _named_child(reader, budget)
    if reader.u8() == 1:
        reader.skip(1)
        _vector(reader, budget, reader.i32(), 9)
    _vector(reader, budget, reader.i16(), 9, 32767)


def _middle(reader, budget):
    # Each1400A50 row: marker,u8,u32,marker,eleven raw bytes.
    for _ in range(2):
        _vector(reader, budget, reader.u32(), 18)
    _vector(reader, budget, reader.i16(), 14, 32767)
    _vector(reader, budget, reader.u32(), 10)
    reader.skip(1 + 4)
    if reader.u8() == 1:
        # Same15C08EC numeric child as COMP; signed row-version branches.
        saved_competition_records._secondary(reader, budget)


def _tail(reader, budget, *, include_nation_index=False):
    reader.skip(4 + 5 + 2)
    # 13DFE08..34 reads +170. Paired writer13E31D8..3210 writes
    # NATION+8 (same-file database index), or FFFFFFFF for a null pointer.
    nation_word = None
    if include_nation_index:
        nation_word = reader.u32()
    else:
        reader.skip(4)
    reader.skip(1 + 4)
    for stride in (9, 8, 8):
        _vector(reader, budget, reader.i8(), stride, 127)
    reader.skip(8 + 28 + 1 + 4 + 1 + 2 + 1)
    for _ in range(3):
        _vector(reader, budget, reader.u8(), 4, 20)
    reader.skip(13 + 8 + 2 + 2 + 2)
    return nation_word


def _consume(reader, ordinal, kind, *, project):
    if type(ordinal) is not int or not 0 <= ordinal < MAX_DATABASE_SLOTS:
        raise ValueError('Invalid saved national container ordinal')
    if type(kind) is not int or kind != 0:
        raise ValueError('Unsupported saved national container subtype')
    budget = _Budget()
    _prefix(reader, budget)
    _named_and_identity_children(reader, budget)
    _middle(reader, budget)
    nation_word = _tail(reader, budget, include_nation_index=project)
    base = saved_club_records.read_base(reader, ordinal,
                                        include_team_indices=project)
    if project:
        if nation_word != 0xffffffff and nation_word & 0x80000000:
            raise ValueError('Unsupported negative saved NATION reference')
        return {'database_index': ordinal, **base,
                'nation_index': None if nation_word == 0xffffffff else nation_word}


def read_national_container(reader, ordinal, kind):
    """Read identity, saved NATION index and ordered TEAM backlink slots.

    The caller establishes source3754/minor9/full-loader and checks nonnull
    reference indices against the same-file table populations. Null TEAM slots
    and unverified negative words retain their positions via the shared base.
    No native-ID equality is used to resolve either reference.
    """
    return _consume(reader, ordinal, kind, project=True)


def skip_national_container(reader, ordinal, kind):
    """Consume one supported container without projecting reference values."""
    _consume(reader, ordinal, kind, project=False)
