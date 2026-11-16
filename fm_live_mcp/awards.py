"""Stored AWARD definitions; no actual winner inferred from a definition."""
import struct

from . import database, geography, competitions, players, world

VTABLE = 0x559b4a0
GETTER = 0xd82d7c
RTTI = b'N2db5AWARDE'
ENUMS = {'AWty': {-1: 'Ignore', 0: 'Not Set', 1: 'Club', 3: 'Manager', 4: 'Top Goalscorer', 5: 'Most Player Of The Match', 14: 'Personality', 15: 'Goal', 16: 'Referee', 19: 'Recruitment Policy', 30: 'Most Assists', 31: 'Quickest Goal', 33: 'Flair Player', 37: 'Highest Average Rating', 38: 'Highest Reputation', 39: 'Least Goals Conceded', 44: 'Most Clean Sheets', 41: 'Most Improved', 42: 'Fair Play Team', 43: 'Comeback'}, 'AWdr': {0: 'Invalid', 1: 'Of The Week', 2: 'Of The Month', 3: 'Of The Season', 4: 'Of The Competition', 5: 'Of The Year', 6: 'On Specified Date', 8: 'Of The Opening Or Closing Season'}, 'AWrt': {0: 'Not Set', 1: 'Player', 2: 'Non Player', 3: 'Player or Non Player', 4: 'Referee', 6: 'Rookie Player', 7: 'Squad Of Players', 8: 'Club or Nation'}}
SCOPE = ('Stored award definitions only. Award period/category/recipient type configure the award; '
         'they do not establish that it took place or identify an actual winner. '
         'Winner history and runtime award decisions are not decoded. Names are stored native strings, '
         'not generated or localized display composition. Nullable links retain canonical identities. '
         'Unknown enum codes remain unmapped. Reads are non-atomic and consumed bytes are rechecked.')


def classification(code, prop):
    return dict(native_code=code, label=ENUMS[prop].get(code), native_property=prop,
                state='mapped' if code in ENUMS[prop] else 'unmapped')


def identity(read, base, address):
    if address < 4096 or address % 8:
        raise ValueError('Invalid award pointer')
    if players.u64(read(address,8)) != base+VTABLE:
        raise ValueError('Unexpected award type')
    metadata = read(base+VTABLE-16,16)
    if struct.unpack_from('<q',metadata)[0] != 0:
        raise ValueError('Unexpected award displacement')
    ti = players.u64(metadata,8)
    name = players.u64(read(ti+8,8))
    if read(name,len(RTTI)+1) != RTTI+b'\0':
        raise ValueError('Unexpected award RTTI')
    if players.u64(read(base+VTABLE+24,8)) != base+GETTER:
        raise ValueError('Award property getter changed')
    raw = read(address+8,12)
    index,native_id,secondary = struct.unpack('<III',raw)
    info = database.table(read,base,'awards')
    if not native_id or index>=info['count'] or world.pointer(read,info['start']+index*8)!=address:
        raise ValueError('Award canonical identity or membership changed')
    return dict(kind='award',address=address,database_index=index,native_id=native_id,identity=raw)


def record(read,base,address,*,cache=None):
    binding=identity(read,base,address)
    cache={} if cache is None else cache
    row=dict(native_id=binding['native_id'],database_index=binding['database_index'],
             random_id=struct.unpack('<III',binding['identity'])[2],
             name=geography.optional_string(read,address+0x30),
             short_name=geography.optional_string(read,address+0x38),
             name_source='stored_native_strings',record_scope='award_definition',
             award_category=classification(int.from_bytes(read(address+0x85,1),'little',signed=True),'AWty'),
             award_period=classification(int.from_bytes(read(address+0x86,1),'little',signed=True),'AWdr'),
             recipient_type=classification(int.from_bytes(read(address+0x8d,1),'little',signed=True),'AWrt'),
             winner_history=dict(state='not_decoded',winners=None))
    for kind,offset in [('continent',0x50),('competition',0x58),('nation',0x60)]:
        pointer=players.u64(read(address+offset,8))
        if not pointer:
            row[kind]=None
            continue
        if pointer<4096 or pointer%8:raise ValueError('Invalid award '+kind+' pointer')
        key=(kind,pointer)
        if key not in cache:
            if kind=='competition':
                i=int.from_bytes(read(pointer+8,4),'little')
                linked=competitions.by_index(read,base,i)
                table=database.table(read,base,'competitions')
                if world.pointer(read,table['start']+i*8)!=pointer:raise ValueError('Award competition membership changed')
            else:linked=geography.record(read,base,pointer,kind)
            cache[key]=linked
        row[kind]=cache[key]
    return row,binding
