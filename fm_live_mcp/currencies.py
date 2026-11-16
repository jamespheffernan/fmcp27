"""Stored currency records and historical rates, without formatter execution."""
import math
import struct

from . import database, geography, players, world

PROPERTY_GETTER = 0x1010480
MAX_HISTORY = 2048
SCOPE = ('Stored currency names, exchange rates relative to GBP and complete historical year/rate entries. '
         'Rates are game data, not real-world quotes. Names omit native localization overrides. '
         'Three additional serialized text fields retain their native offsets and unverified meanings. '
         'Historical entries retain native order, duplicates, zero rates and invalid years; no interpolation '
         'or historical cash formatter is executed. Non-finite rates retain their raw bits and null values. '
         'A currency record does not establish UI selectability or an ISO code. Current stored rates can differ '
         'from runtime formatter state. References bind native identity and canonical table membership; '
         'ordinary fields refresh. Reads are non-atomic with consumed-byte rechecks.')


def identity(read, base, address):
    if address < 4096 or address % 8:
        raise ValueError('Invalid currency pointer')
    world.typed(read, base, address, 'currency')
    if players.u64(read(base + world.TYPES['currency'][0] + 24, 8)) != base + PROPERTY_GETTER:
        raise ValueError('Currency property getter changed')
    raw = read(address + 8, 12)
    index, native_id, random_id = struct.unpack('<III', raw)
    info = database.table(read, base, 'currencies')
    if not native_id or index >= info['count'] or world.pointer(read, info['start'] + index * 8) != address:
        raise ValueError('Currency identity or membership changed')
    return {'address': address, 'database_index': index, 'native_id': native_id, 'identity': raw}


def rate(raw):
    value = struct.unpack('<f', raw)[0]
    return {'value': value if math.isfinite(value) else None, 'native_float32_hex': raw.hex(),
            'state': 'non_finite' if not math.isfinite(value) else 'negative_native_rate' if value < 0 else 'stored',
            'basis': 'currency_units_per_GBP'}


def record(read, base, address, *, include_details=False):
    binding = identity(read, base, address)
    _, native_id, random_id = struct.unpack('<III', binding['identity'])
    row = {'kind': 'currency', 'database_index': binding['database_index'], 'native_id': native_id,
           'random_id': None if random_id == native_id else random_id,
           'name': geography.optional_string(read, address + 0x18), 'name_source': 'stored_native_string',
           'exchange_rate': rate(read(address + 0x38, 4))}
    if include_details:
        row['unmapped_text_fields'] = [{'native_offset': hex(offset), 'value': geography.optional_string(read, address + offset),
                                       'meaning': 'unverified'} for offset in (0x20, 0x28, 0x30)]
        start, end, capacity = struct.unpack('<QQQ', read(address + 0x40, 24))
        if (start, end, capacity) != (0, 0, 0) and (
                start < 4096 or any(p % 8 for p in (start, end, capacity))
                or not start <= end <= capacity or capacity-start > MAX_HISTORY*8):
            raise ValueError('Invalid or oversized currency history vector')
        raw = read(start, end-start) if end > start else b''
        history = []
        for i in range((end-start)//8):
            year = struct.unpack_from('<H', raw, i*8)[0]
            history.append({'native_index': i, 'native_year': year, 'year': year if 1 <= year <= 9999 else None,
                            'year_state': 'stored' if 1 <= year <= 9999 else 'invalid_native_year',
                            'exchange_rate': rate(raw[i*8+4:i*8+8])})
        row.update(history=history, history_count=len(history), complete_native_history=True)
    return row, binding


def by_index(read, base, index, *, include_details=False):
    info = database.table(read, base, 'currencies')
    if type(index) is not int or not 0 <= index < info['count']:
        raise ValueError('Currency index is outside the native table')
    row, binding = record(read, base, world.pointer(read, info['start'] + index*8), include_details=include_details)
    if binding['database_index'] != index:
        raise ValueError('Currency database index changed')
    return row, binding
