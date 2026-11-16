"""Stored MEDIA_SOURCE properties in the active FM27 database."""
import struct

from . import cities, geography, players

PERIODS = dict(enumerate(('Anytime', 'Weekday Morning', 'Sunday', 'Weekly', 'Monthly', 'Bi Monthly',
                          'Quarterly', 'Yearly', 'Weekday Evening', 'Monday', 'Tuesday', 'Wednesday',
                          'Thursday', 'Friday', 'Saturday'), start=1))
SCOPES = dict(enumerate(('Club', 'Local', 'Regional', 'National', 'Continental', 'Worldwide',
                         'Competition'), start=1))
STYLES = dict(enumerate(('Not Set', 'Tabloid', 'Broadsheet', 'Formal', 'Casual', 'Popular', 'Analytical')))
SCOPE = ('Stored media source definitions and direct nation, city and continent links. The press conference '
         'flag is a configured attribute. An individual appearance, assignment or published story requires separate evidence.')


def _classification(code, labels):
    return {'code': code, 'label': labels.get(code)}


def record(read, base, address, *, include_details=False):
    binding = geography.identity(read, base, address, 'media_source')
    row = {'native_id': binding['native_id'], 'database_index': binding['database_index'],
           'name': geography.optional_string(read, address + 0x18)}
    if not include_details:
        return row, binding

    style = int.from_bytes(read(address + 0xC0, 1), 'little', signed=True)
    fake, attends = read(address + 0xC2, 2)
    period, scope = struct.unpack('<bb', read(address + 0xE0, 2))
    city, continent = struct.unpack('<QQ', read(address + 0xB0, 16))
    start, end, capacity = struct.unpack('<QQQ', read(address + 0x50, 24))
    if start or end or capacity:
        if (start < 4096 or any(p % 8 for p in (start, end, capacity)) or
                not start <= end <= capacity or capacity - start > 4096 * 8):
            raise ValueError('Invalid media source nations vector')
    nation_bytes = read(start, end - start) if end > start else b''
    nations = [geography.record(read, base, pointer, 'nation') if pointer else None
               for (pointer,) in struct.iter_unpack('<Q', nation_bytes)]
    row.update(style=_classification(style, STYLES), scope=_classification(scope, SCOPES),
               publication_period=_classification(period, PERIODS), is_fake_code=fake,
               is_fake={0: False, 1: True}.get(fake), attends_press_conferences_code=attends,
               attends_press_conferences={0: False, 1: True}.get(attends), nations=nations,
               city=cities.record(read, base, city)[0] if city else None,
               continent=geography.record(read, base, continent, 'continent') if continent else None)
    return row, binding
