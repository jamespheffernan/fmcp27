"""Stored geographic identities and names with canonical table membership."""
import struct

from . import database, players, world

FIELDS = {
    'media_source': (0x1394488, 'media_sources', (('name', 0x18),)),
    'language': (0x1369C14, 'languages', (('name', 0x18),)),
    'local_region': (0x137A600, 'local_regions', (('name', 0x18),)),
    'weather': (0x18B2768, 'weather', (('name', 0x18),)),
    'nation': (0x13B1D14, 'nations', (('short_name', 0x20), ('abbreviation', 0x28))),
    'continent': (0xFE05C0, 'continents', (('name', 0x18), ('abbreviation', 0x20))),
}


def optional_string(read, address):
    """Preserve null/empty SI strings; string buffers need not be aligned."""
    pointer = players.u64(read(address, 8))
    if not pointer:
        return None
    if read(pointer, 4) == bytes(4):
        if read(pointer + 4, 1) != b'\0':
            raise ValueError('Invalid empty geography string')
        return ''
    return world.string(read, pointer)


def identity(read, base, address, kind):
    if address < 4096 or address % 8:
        raise ValueError(f'Invalid {kind} pointer')
    getter, table_kind, _ = FIELDS[kind]
    world.typed(read, base, address, kind)
    vtable = world.pointer(read, address)
    if players.u64(read(vtable + 3 * 8, 8)) != base + getter:
        raise ValueError(f'{kind.title()} property getter changed')
    raw = read(address + 8, 12)
    index, native_id, secondary = struct.unpack('<III', raw)
    if not native_id:
        raise ValueError(f'{kind.title()} primary identity is missing')
    info = database.table(read, base, table_kind)
    if index >= info['count'] or world.pointer(read, info['start'] + index * 8) != address:
        raise ValueError(f'{kind.title()} table membership changed')
    return {'kind': kind, 'address': address, 'native_id': native_id,
            'database_index': index, 'identity': raw}


def record(read, base, address, kind):
    binding = identity(read, base, address, kind)
    names = FIELDS[kind][2]
    return {'native_id': binding['native_id'], 'database_index': binding['database_index'],
            **{field: optional_string(read, address + offset) for field, offset in names},
            'name_source': 'stored_native_strings'}
