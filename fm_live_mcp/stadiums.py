"""Build-pinned stored stadium data; never execute contextual native getters."""
from datetime import date, timedelta
import math
import struct

from . import database, players, world

PROPERTY_GETTER = 0x16C8BC8
PITCH_TYPES = {1:'Grass', 2:'Synthetic (New Type - Soft)', 3:'Synthetic (Old Type - Hard)',
               4:'Gravel/Clay/Sand', 5:'Gravel', 6:'Clay', 7:'Sand', 8:'Grass/Synthetic Mix'}
DETERIORATION = {1:'Slow', 2:'Medium', 3:'Fast'}
CONDITIONS = {1:'Very Good', 2:'Good', 3:'Average', 4:'Poor', 5:'Very Poor'}
ENVIRONMENTS = {0:'Not Set', 1:'Basic', 2:'Standard', 3:'High End', 4:'State Of The Art'}
OWNER_TYPES = {1:'Club', 2:'Council', 3:'Private', 4:'Chairperson', 5:'Fans'}
NATIONAL_USAGE = {0:'No Matches', 1:'All Matches', 2:'Major Matches', 3:'Medium Matches',
                  4:'Minor Matches', 5:'Major Matches And Some Medium Matches',
                  6:'Minor Matches and Some Medium Matches'}
SCOPE = ('Stored stadium names, capacities, coordinates, pitch fields, facility flags and dates. '
         'Continental names are separate; no contextual display-name selection is performed. '
         'Used/all-seater capacities <=0 are unspecified; zero seating remains a stored value. '
         'Capacity is not attendance, availability or match suitability. Dates retain native years, including future/outlier values. '
         'Pitch dimensions are metres decoded from stored tenths. Default and international fields remain separate. '
         'Covered is a stored flag, not current roof state; native getters can apply contextual overrides. '
         'Stadium search/readback adds stored city, owner-club and nearby-stadium references. '
         'Owner-club links do not establish legal ownership; nearby links do not prove distance, groundsharing or fixture allocation. '
         'Linked fields refresh without replacing the parent identity; each returned reference binds to its own record. '
         'Linked stadiums are summaries, so cyclic links do not expand recursively. '
         'Stadium sides and contextual construction status remain undecoded; separate stadium-change tools expose stored move records. '
         'References are save/session-bound; reads are non-atomic with consumed-byte rechecks.')


def _enum(code, labels, unspecified=None):
    return {'native_code':code, 'name':labels.get(code),
            'state':'not_specified' if code == unspecified else 'decoded' if code in labels else 'unmapped'}


def _date(raw):
    packed = int.from_bytes(raw, 'little')
    year, day = packed >> 16, packed & 511
    result = {'date':None, 'state':'invalid_native_date', 'native_year':year, 'native_day':day}
    if (year,day) == (1900,1):
        return {**result, 'state':'not_specified'}
    if not 1 <= year <= 9999 or not 1 <= day <= 366:
        return result
    try:
        value = date(year,1,1)+timedelta(days=day-1)
    except (ValueError,OverflowError):
        return result
    if value.year != year:
        return result
    return {**result,'date':value.isoformat(),'state':'stored'}


def _dimension(value, kind):
    available = value >= 1 if kind == 'international' else value > -10 if kind == 'bounds' else True
    return {'value':value/10 if available else None, 'native_tenths':value,
            'state':'stored' if available else 'not_specified'}


def identity(read, base, address):
    if address < 4096 or address % 8:
        raise ValueError('Invalid stadium pointer')
    world.typed(read,base,address,'stadium')
    if world.pointer(read,base+world.TYPES['stadium'][0]+24) != base+PROPERTY_GETTER:
        raise ValueError('Stadium property getter changed')
    raw = read(address+8,12)
    index, native_id, random_id = struct.unpack('<III',raw)
    info = database.table(read,base,'stadiums')
    if not native_id or index >= info['count'] or world.pointer(read,info['start']+index*8) != address:
        raise ValueError('Stadium identity or membership changed')
    return {'address':address,'database_index':index,'native_id':native_id,'identity':raw}


def record(read, base, address, *, include_details=False):
    binding = identity(read,base,address)
    names = {}
    for field,offset in (('name',0x40),('continental_name',0x48)):
        pointer = players.u64(read(address+offset,8))
        if not pointer:
            names[field] = None
        elif read(pointer,4) == bytes(4):
            if read(pointer+4,1) != b'\0':
                raise ValueError('Invalid empty stadium string')
            names[field] = ''
        else:
            names[field] = world.string(read,pointer)
    raw = read(address+0xAB,1)[0]
    row = {'database_index':binding['database_index'],'native_id':binding['native_id'],
           **names,'name_source':'stored_native_strings','is_extinct':bool(raw&1),'is_training_ground':bool(raw&4)}
    if include_details:
        capacities = {}
        for field,offset in (('total',0x7C),('seated',0x80),('used',0x84),('all_seater_competitions',0x88),('expansion',0x8C)):
            value = int.from_bytes(read(address+offset,4),'little',signed=True)
            missing = field in ('used','all_seater_competitions') and value <= 0
            capacities[field] = {'value':None if missing else value,'native_value':value,
                                 'state':'not_specified' if missing else 'stored'}
        coordinate_raw = read(address+0x70,8)
        latitude,longitude = struct.unpack('<2f',coordinate_raw)
        valid = math.isfinite(latitude) and math.isfinite(longitude) and -90<=latitude<=90 and -180<=longitude<=180
        coordinates = {'latitude':latitude if valid else None,'longitude':longitude if valid else None,
                       'state':'stored' if valid else 'invalid_native_coordinates'}
        if not valid: coordinates['native_hex'] = coordinate_raw.hex()
        dimensions = {}
        for name,offset,kind in (('default',0x98,'default'),('international',0x9C,'international'),
                                ('minimum',0xA0,'bounds'),('maximum',0xA4,'bounds')):
            length,width = struct.unpack('<hh',read(address+offset,4))
            dimensions[name] = {'length':_dimension(length,kind),'width':_dimension(width,kind)}
        codes = struct.unpack('<9b',read(address+0xAC,9))
        flags = int.from_bytes(read(address+0xB6,2),'little')
        row.update(capacities=capacities,coordinates=coordinates,
            pitch={'type':_enum(codes[1],PITCH_TYPES),'condition':int.from_bytes(read(address+0xA8,2),'little',signed=True),
                   'deterioration_rate':_enum(codes[0],DETERIORATION),'recovery_rate':codes[2],
                   'dimensions':dimensions,'dimension_unit':'metres'},
            stadium_condition=_enum(codes[3],CONDITIONS),environment=_enum(codes[4],ENVIRONMENTS,0),
            owner_type=_enum(codes[8],OWNER_TYPES,0),
            national_team_usage={name:_enum(code,NATIONAL_USAGE) for name,code in zip(('senior','under21','under19'),codes[5:8])},
            decay=int.from_bytes(read(address+0xAA,1),'little',signed=True),
            facilities={'has_digital_advertising':bool(raw&64),'has_undersoil_heating':bool(flags&2),
                        'has_retractable_roof':bool(flags&64),'stored_covered':bool(flags&1)},
            dates={name:_date(read(address+offset,4)) for name,offset in
                   (('built',0x30),('rebuilt',0x34),('pitch_relay_required',0x2C))})
    return row,binding


def by_index(read, base, index, *, include_details=False):
    info = database.table(read,base,'stadiums')
    if type(index) is not int or not 0 <= index < info['count']:
        raise ValueError('Stadium index is outside its native table')
    return record(read,base,world.pointer(read,info['start']+index*8),include_details=include_details)
