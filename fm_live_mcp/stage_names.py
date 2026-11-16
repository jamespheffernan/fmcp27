"""Stored stage-name components; native display composition remains separate."""
import struct

from . import database, players, world

PROPERTY_GETTER = 0x16E2D4C


def record(read, base, address):
    if address < 4096 or address % 8:
        raise ValueError('Invalid stage-name pointer')
    world.typed(read, base, address, 'stage_name')
    vtable = world.pointer(read, address)
    if players.u64(read(vtable+3*8, 8)) != base+PROPERTY_GETTER:
        raise ValueError('Stage-name property getter changed')
    index, native_id = struct.unpack('<II', read(address+8, 8))
    info = database.table(read, base, 'stage_names')
    if not native_id or index >= info['count'] or world.pointer(read, info['start']+index*8) != address:
        raise ValueError('Stage-name identity or membership changed')
    names = {}
    for field, offset in (('name', 0x18), ('short_name', 0x20), ('plural_name', 0x28)):
        pointer = players.u64(read(address+offset, 8))
        if not pointer:
            names[field] = None
        elif read(pointer, 4) == bytes(4):
            if read(pointer+4, 1) != b'\0':
                raise ValueError('Invalid empty stage-name string')
            names[field] = ''
        else:
            names[field] = world.string(read, pointer)
    return {'native_id': native_id, 'database_index': index, **names,
            'name_source': 'stored_native_strings'}
