"""Forward COMP records in the verified 3754/minor-9, full-loader mode zero.

The caller establishes table ownership and source context. Opaque children are
consumed without materializing their vectors; identities remain same-file words.
"""

from . import saved_competition_prefix, saved_properties

SUPPORTED_SOURCE = (3754, 9)
MAX_DATABASE_SLOTS = 2_000_000
MAX_CHILD_ITEMS = 10_000
MAX_RECORD_ITEMS = 20_000


class _Budget:
    def __init__(self):
        self.items = 0

    def count(self, value):
        if not 0 <= value <= MAX_CHILD_ITEMS:
            raise ValueError('Saved COMP child exceeds item budget')
        self.items += value
        if self.items > MAX_RECORD_ITEMS:
            raise ValueError('Saved COMP record exceeds cumulative item budget')
        return value


def _history(reader):
    if reader.u8() != 1:
        return
    version = reader.u8()
    reader.skip(4 + 2 + 2 + 6 * 4)
    if version >= 2:
        reader.skip(4)
    reader.skip(8 + 1 + (2 if version >= 3 else 1) + 4 + 4)


def _secondary(reader, budget):
    reader.skip(4)  # Child version affects native cleanup, not the wire cursor.
    for _ in range(budget.count(reader.u32())):
        version = reader.i16()
        reader.skip(4 + 1 + 1 + (2 if version >= 2 else 1) + 1)
        if version >= 3:
            reader.skip(1)


def _body(reader, budget, *, owner_projection=None):
    owner_offset = reader.offset
    owner_key = reader.i32()  # COMP+F0, signed fixed competition-history key.
    if owner_projection is not None:
        owner_projection.update(value=owner_key, source_offset=owner_offset, source_field='COMP+0xF0')
    is_extinct = bool(reader.u8() & 0x04)  # COMP+1A9 getter UBFX #2,#1.
    reader.skip(1)  # COMP+103.
    type_code, gender_code = reader.i8(), reader.u8()  # COMP+F8 / +F9.
    if reader.u8() == 1:
        saved_properties.skip_property_vector(reader)

    # Native signed nonpositive counts skip these loops, including negatives.
    for _ in range(budget.count(max(reader.i32(), 0))):
        version = reader.i8()
        reader.skip(7 + (version >= 2))
    if reader.u8() == 1:
        _secondary(reader, budget)

    if reader.u8() & 1:
        reader.skip(1)
        for _ in range(budget.count(reader.u32())):
            reader.skip(2)  # Marker and native one-byte key.
            reader.skip(budget.count(reader.u32()) * 12)
    if reader.u8() == 1:
        reader.skip(1 + 4 * 6)
    reader.skip(1)  # COMP+102.
    for _ in range(2):
        if reader.u8() == 1:
            reader.skip(15)  # EF0024 mode-zero reference/field payload.
    reader.skip(budget.count(max(reader.i16(), 0)) * 5)
    reader.skip(budget.count(reader.u8()) * 13)
    reader.skip(4 + 5 * 2 + 4 * 4)
    if reader.u8() == 1:
        reader.skip(2)
    reader.skip(8 + 3)
    return type_code, gender_code, is_extinct


def read_competition(reader, ordinal, kind, *, include_history_key=False):
    """Consume one kind-zero record, leaving the next subtype/footer untouched."""
    if type(ordinal) is not int or not 0 <= ordinal < MAX_DATABASE_SLOTS:
        raise ValueError('Invalid saved COMP ordinal')
    if type(kind) is not int or kind != 0:
        raise ValueError('Unsupported saved COMP record subtype')
    if type(include_history_key) is not bool:
        raise ValueError('Invalid saved COMP history-key selection')
    fields = saved_competition_prefix.read_prefix(reader)
    _history(reader)
    owner = {} if include_history_key else None
    type_code, gender_code, is_extinct = _body(reader, _Budget(), owner_projection=owner)
    stored_index, native_id, secondary_id = reader.u32(), reader.u32(), reader.u32()
    if stored_index != ordinal:
        raise ValueError('Saved COMP database ordinal mismatch')
    result = {
        **fields,
        'database_index': ordinal,
        'native_id': native_id,
        'secondary_id': secondary_id,
        'type_code': type_code,
        'gender_code': gender_code,
        'is_extinct': is_extinct,
    }
    if owner is not None:
        result['history_owner'] = owner
    return result
