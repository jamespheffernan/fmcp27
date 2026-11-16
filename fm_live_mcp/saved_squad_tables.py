"""Stream simple table rows in the source3754/minor9 full-loader profile.

The caller verifies source/build context, table count and footer. Each callback
starts after the subtype byte and consumes one complete row, checking its saved
ordinal without native identity repair. No names or references are resolved.
"""

from . import (
    saved_competition_records, saved_currency_records, saved_database,
    saved_national_containers, saved_nations, saved_region_tables,
)

SUPPORTED_SOURCE = (3754, 9)
MAX_DATABASE_SLOTS = 2_000_000
MAX_TEXT_BYTES = 8192
MAX_MEDIA_ITEMS = 10_000
MAX_MEDIA_WORK = 50_000


def _validate(ordinal, kind, label, *, any_signed_subtype=False):
    if type(ordinal) is not int or not 0 <= ordinal < MAX_DATABASE_SLOTS:
        raise ValueError(f'Invalid saved {label} ordinal')
    valid_kind = type(kind) is int and (
        -128 <= kind <= 127 if any_signed_subtype else kind == 0
    )
    if not valid_kind:
        raise ValueError(f'Unsupported saved {label} subtype')


def _identity(reader, ordinal, label):
    stored = reader.u32()
    reader.skip(8)  # Independent primary/secondary words have no added constraints.
    if stored != ordinal:
        raise ValueError(f'Saved {label} database ordinal mismatch')


def skip_injury(reader, ordinal, kind):
    """13287D4 full-loader body: 35 bytes then the shared identity."""
    _validate(ordinal, kind, 'INJURY')
    reader.skip(35)
    _identity(reader, ordinal, 'INJURY')


def skip_media_source(reader, ordinal, kind):
    """Consume MEDIA_SOURCE's name and bounded collections in wire order."""
    _validate(ordinal, kind, 'MEDIA_SOURCE')
    work = 0

    def count(*, byte=False):
        nonlocal work
        value = reader.u8() if byte else reader.u32()
        work += value
        if value > MAX_MEDIA_ITEMS or work > MAX_MEDIA_WORK:
            raise ValueError('Saved MEDIA_SOURCE collection exceeds work budget')
        return value

    reader.text(max_bytes=MAX_TEXT_BYTES)
    reader.skip(1)  # +C1.
    reader.skip(count())  # +20 byte vector.
    reader.skip(2)  # +C2/+C0.
    reader.skip(count() * 4)  # +38.
    reader.skip(4)  # +B0.
    reader.skip(count() * 4)  # +68.
    reader.skip(count() * 4)  # +50.
    reader.skip(4)  # +B8.
    reader.skip(count() * 8)  # +98 pairs.
    reader.skip(2 + 4)  # +E0/+E1 and packed date +C4.
    reader.skip(count(byte=True) * 4)  # +C8.
    reader.skip(count() * 4)  # +80.
    reader.skip(1)  # +C3.
    _identity(reader, ordinal, 'MEDIA_SOURCE')


def skip_language(reader, ordinal, kind):
    """Consume the stored name, 17-byte body and shared identity."""
    _validate(ordinal, kind, 'LANGUAGE')
    reader.text(max_bytes=MAX_TEXT_BYTES)
    reader.skip(17)
    _identity(reader, ordinal, 'LANGUAGE')


def skip_stadium(reader, ordinal, kind):
    """16C63C0: exact optional-child and inline-name branches, then identity."""
    _validate(ordinal, kind, 'STADIUM')
    reader.skip(63)
    if reader.u8() == 1:
        reader.skip(66)  # 493789C consumes 66 bytes despite caller argument 0x4C.
    reader.skip(13)
    flags = reader.u16()
    if flags & 16:
        reader.text(max_bytes=MAX_TEXT_BYTES)
    reader.skip(23)
    _identity(reader, ordinal, 'STADIUM')


def skip_stadium_change(reader, ordinal, kind):
    """16D3F44 full-loader body: 66 bytes then the shared identity."""
    _validate(ordinal, kind, 'STADIUM_CHANGE')
    reader.skip(66)
    _identity(reader, ordinal, 'STADIUM_CHANGE')


def skip_stage_name(reader, ordinal, kind):
    """Consume every signed subtype; type23's factory ignores that argument."""
    _validate(ordinal, kind, 'STAGE_NAME', any_signed_subtype=True)
    if reader.u8() & 1:
        reader.text(max_bytes=MAX_TEXT_BYTES)
    _identity(reader, ordinal, 'STAGE_NAME')


def reach_names_after_clubs(reader, *, read_nation_context=None, read_currency_context=None):
    """Stop before the three original-name vectors; preserve optional context."""
    def read_currency(reader, ordinal, kind):
        row = saved_currency_records.read_currency(reader, ordinal, kind)
        if read_currency_context is not None:
            read_currency_context(row)
        return row

    for label, decoder in (
        ('COMP', saved_competition_records.read_competition),
        ('CONTINENT', saved_currency_records.skip_continent),
        ('CURRENCY', read_currency),
        ('INJURY', skip_injury),
        ('MEDIA_SOURCE', skip_media_source),
        ('LANGUAGE', skip_language),
    ):
        saved_database.skip_table(reader, label, decoder)
    context = None
    if read_nation_context is None:
        saved_database.skip_table(reader, 'NATION', saved_nations.skip_nation)
        saved_database.skip_table(reader, 'NATIONAL_TEAM_CONTAINER', saved_national_containers.skip_national_container)
    else:
        context = read_nation_context(reader)
    return context


def reach_teams_after_clubs(reader, *, read_nation_context=None):
    context = reach_names_after_clubs(reader, read_nation_context=read_nation_context)
    saved_region_tables.skip_name_tables(reader)
    for label, decoder in (
        ('REGION', saved_region_tables.skip_region),
        ('LOCAL_REGION', saved_region_tables.skip_local_region),
        ('STADIUM', skip_stadium),
        ('STADIUM_CHANGE', skip_stadium_change),
        ('STAGE_NAME', skip_stage_name),
    ):
        saved_database.skip_table(reader, label, decoder)
    return context
