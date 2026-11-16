"""Forward CONTINENT/CURRENCY rows in source3754/minor9 full-loader streams.

The caller establishes the build, source version, table count and footer. Input
starts after the subtype byte. Names and rates are stored game data; this module
does not run localization overrides or currency formatter/cache updates.
"""

from . import currencies, saved_properties

SUPPORTED_SOURCE = (3754, 9)
MAX_DATABASE_SLOTS = 2_000_000
MAX_HISTORY = currencies.MAX_HISTORY
MAX_TEXT_BYTES = 8192


def _validate(ordinal, kind, label):
    if type(ordinal) is not int or not 0 <= ordinal < MAX_DATABASE_SLOTS:
        raise ValueError(f'Invalid saved {label} ordinal')
    if type(kind) is not int or kind != 0:
        raise ValueError(f'Unsupported saved {label} record subtype')


def _identity(reader, ordinal, label):
    stored_index = reader.u32()
    native_id = reader.u32()
    secondary_id = reader.u32()
    # Native readers can repair this word; an offline reader must not hide it.
    if stored_index != ordinal:
        raise ValueError(f'Saved {label} database ordinal mismatch')
    return native_id, secondary_id


def skip_continent(reader, ordinal, kind):
    """Consume one full CONTINENT row, including its bounded property trees."""
    _validate(ordinal, kind, 'CONTINENT')
    # FDC660: +F0/F1/F2, +E4, source>=3719 +F3/F4; EEFB40 colours.
    reader.skip(3 + 4 + 2 + 12)
    for _ in range(6):
        # FDC9E8..9F0 accepts exactly 1; other marker values have no payload.
        if reader.u8() == 1:
            saved_properties.skip_property_vector(reader)
    saved_properties.skip_property_map(reader)
    saved_properties.skip_property_map(reader)
    _identity(reader, ordinal, 'CONTINENT')


def read_currency(reader, ordinal, kind, *, include_history=False):
    """Consume a currency and return its same-file identity and stored rates.

    101006C reads four UTF-8 strings, a float32 rate, 1010EA8 history and the
    11B011C identity. Only the first string's name meaning is projected. Empty
    strings remain explicit. Historical order, duplicate/invalid years and all
    float32 bits are preserved; rates are currency units per GBP, without any
    interpolation. The history transport marker is ignored by the native reader.
    """
    _validate(ordinal, kind, 'CURRENCY')
    if type(include_history) is not bool:
        raise ValueError('include_history must be a Boolean')
    name = reader.text(max_bytes=MAX_TEXT_BYTES)
    for _ in range(3):
        reader.text(max_bytes=MAX_TEXT_BYTES)
    exchange_rate = currencies.rate(reader.take(4))
    count = reader.u32()
    if count > MAX_HISTORY:
        raise ValueError('Saved CURRENCY history exceeds supported bounds')
    history = []
    if include_history:
        for index in range(count):
            reader.u8()  # 1010FBC..FC8 discards this byte, including non-1 values.
            year = reader.u16()
            valid_year = 1 <= year <= 9999
            history.append({
                'native_index': index,
                'native_year': year,
                'year': year if valid_year else None,
                'year_state': 'stored' if valid_year else 'invalid_native_year',
                'exchange_rate': currencies.rate(reader.take(4)),
            })
    else:
        reader.skip(count * 7)
    native_id, secondary_id = _identity(reader, ordinal, 'CURRENCY')
    row = {
        'database_index': ordinal,
        'native_id': native_id,
        'secondary_id': secondary_id,
        'name': name,
        'exchange_rate': exchange_rate,
        'history_count': count,
    }
    if include_history:
        row['history'] = history
    return row
