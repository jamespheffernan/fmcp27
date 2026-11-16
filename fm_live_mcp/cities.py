"""Build-pinned stored CITY records and checked geographic identities."""
import math
import struct

from . import database, geography, players, world

PROPERTY_GETTER = 0xDD548C
POPULATION_RANGES = {0:'Not Set', 1:'0 - 1000', 2:'1001 - 2500', 3:'2501 - 5000',
    4:'5001 - 10000', 5:'10001 - 25000', 6:'25001 - 50000', 7:'50001 - 100000',
    8:'100001 - 250000', 9:'250001 - 500000', 10:'500001 - 1000000',
    11:'1000001 - 2500000', 12:'2500001 - 5000000', 13:'5000001 - 10000000',
    14:'10000001 - 20000000', 15:'20000001 +'}
SCOPE = ('Stored city names, coordinates, population categories, attraction and geographic links. '
         'Population is a database category, not an observed current population. Attraction is the stored native rating. '
         'Altitude preserves the signed native integer; its physical unit is unverified. '
         'Deleted is the stored DELE flag, not a claim that the record is absent from the table. '
         'Nation, language, local-region and weather summaries recheck type and canonical membership; '
         'language and local-region references open their stored details. Weather details and current match weather remain undecoded. '
         'Language filters use direct city links without regional fallback; region filters reproduce native reverse city membership. '
         'Names omit contextual/localized formatting. '
         'References bind to city identity and membership; ordinary fields and links refresh on readback. '
         'Reads are non-atomic with consumed-byte rechecks. Continue every cursor with identical selectors, including empty pages.')


def identity(read, base, address):
    if address < 4096 or address % 8:
        raise ValueError('Invalid city pointer')
    world.typed(read,base,address,'city')
    # Function pointers need four-byte alignment; CITY's getter is not eight-byte aligned.
    if players.u64(read(base+world.TYPES['city'][0]+24,8)) != base+PROPERTY_GETTER:
        raise ValueError('City property getter changed')
    raw = read(address+8,12)
    index,native_id,duplicate = struct.unpack('<III',raw)
    info = database.table(read,base,'cities')
    if not native_id or index >= info['count'] or world.pointer(read,info['start']+index*8) != address:
        raise ValueError('City identity or membership changed')
    return {'address':address,'database_index':index,'native_id':native_id,'identity':raw}


def record(read, base, address, *, include_details=False, context_cache=None):
    binding = identity(read,base,address)
    row = {'database_index':binding['database_index'],'native_id':binding['native_id'],
           'name':geography.optional_string(read,address+0x18),'name_source':'stored_native_strings',
           'is_deleted':bool(read(address+0x55,1)[0]&1)}
    if include_details:
        cache = {} if context_cache is None else context_cache
        related = {}
        for kind,offset in (('nation',0x20),('weather',0x28),('language',0x30),('local_region',0x38)):
            pointer = players.u64(read(address+offset,8))
            if not pointer:
                related[kind] = None
                continue
            if pointer < 4096 or pointer % 8:
                raise ValueError(f'Invalid city {kind} pointer')
            key = (kind,pointer)
            if key not in cache:
                cache[key] = geography.record(read,base,pointer,kind)
            related[kind] = {**cache[key],'kind':kind}
        raw = read(address+0x48,8)
        latitude,longitude = struct.unpack('<ff',raw)
        valid = math.isfinite(latitude) and math.isfinite(longitude) and -90<=latitude<=90 and -180<=longitude<=180
        coordinates = {'latitude':latitude if valid else None,'longitude':longitude if valid else None,
                       'state':'stored' if valid else 'invalid_native_coordinates'}
        if not valid:coordinates['native_hex'] = raw.hex()
        population = int.from_bytes(read(address+0x52,1),'little',signed=True)
        row.update(**related,coordinates=coordinates,
            altitude={'native_value':int.from_bytes(read(address+0x50,2),'little',signed=True),
                      'unit':None,'state':'unit_unverified'},
            population={'native_code':population,'name':POPULATION_RANGES.get(population),
                        'state':'not_specified' if population==0 else 'decoded' if population in POPULATION_RANGES else 'unmapped'},
            attraction=int.from_bytes(read(address+0x54,1),'little',signed=True))
    return row,binding


def by_index(read, base, index, *, include_details=False, context_cache=None):
    info = database.table(read,base,'cities')
    if type(index) is not int or not 0 <= index < info['count']:
        raise ValueError('City index is outside its native table')
    return record(read,base,world.pointer(read,info['start']+index*8),
                  include_details=include_details,context_cache=context_cache)
