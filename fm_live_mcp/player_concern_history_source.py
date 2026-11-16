"""Private strict main-contract/current-CLUB concern-history projection.

No production registration, native game call, profile generation or write.
Callers bind the save, roster and every consumed byte through the last callback.
Only the full main-contract branch whose CLUB matches the current TEAM's CLUB
is supported. Missing context or other contract families stay unavailable.
"""
import hashlib
import struct
from . import assessment_people,database,players,world

SOURCE = (
    (0x24a9e1c, 456, 'b7f651fb613a54925ff591ba62f59fa6eb49d218fd2d3b9dd2edc9db654e1855'),
    (0xcb85fc, 1664, '469bb49191044a24cdedee68a0efe82828f8582b1aacbe5e97ca034742c9de51'),
    (0x129fffc, 8, '2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a'),
    (0xfede78, 460, '39a13e729c45a1bc5a286b84dc35f43f7dd3ed3a582d3c3ae6578c5cacccfb8f'),
    (0xfeda88, 68, '3e55315bf5387d6da077b115c5003cafd937250032ed05578cd290fa41eec0db'),
    (0xfedd04, 92, '417db05e02c23172ba4d271446cb96d5fcfc931cd11ed76d2365197291892356'),
    (0x52dd8e8, 8, 'b9d57933f84794ab4d542ec3a79ad9ad2b678f4e3ea46e9eb7670fa02c2dca2e'),
    (0x154525c, 40, 'adc3bf8f3c4f8f1dccc0fe4c7e31e9d50fc7e2da51a294ad46054d8a18d0df0f'),
    (0x539ba90, 863, 'ac18cb44b2b25a776bc2d289bef18cdab06de7ebf94de22acbaaed9acb610d0e'),
    (0xfedd74, 44, '4d6e6e754817a9d19f933b36805e1b136c5d37ba0cfbcc52b936cb2bcd4ffd6c'),
    (0x4356b50, 32, 'f4e86cf5b82b7f535508bea766944b677db15b75fc4aec3aa275047edea13c33'),
    (0x4356ba4, 52, '9b8d6e00bd05baa2936954f985da5fa50e97ba431525a63df886be2b976b06f4'),
    (0xfeda3c, 44, '06c37f2e2d5d4263071b9f68f6476f616ac2be064a78c24ccc83b1aa381352a9'),
    (0x435801c, 12, '602c93f97b8c958654fbcd0a200fee933b06801e9ebb8fded68abe49f20f4c5b'),
    (0x43580d8, 44, '7d71f47452ed54bf6505eface8f9b62003b3cc79026347d0c9d4e63e8b2a34f9'),
)
RULE=b'52OWN_PLAYER_DOES_NOT_HAVE_SPECIFIC_UNHAPPINESS_REASON\0'
SCOPE=('Stored current main FULL_CONTRACT concern-history ring in the current TEAM/CLUB context, '
       'newest first, bounded to its native ten slots, including dated and unset-end records. '
       'Dates, reason/category codes, linked scalars and flags retain their raw source values. '
       'The native unset-end filter is exposed separately from UI happiness, satisfaction, '
       'complaint wording, promise fulfilment, future outcomes and a complete historical population. '
       'Other contract contexts are unavailable. No game function, profile generation or game write.')


def pointer(value):
    if type(value)is not int or value<4096 or value%8 or value>=1<<64:
        raise ValueError('Invalid concern source object pointer')
    return value


def pod_record_pointer(value):
    # Only the native 28-byte concern POD family has this qualification. Native
    # FEDD88 pool stride28, 4356BD4 stored stride and 43580F0 freelist arithmetic
    # are source-pinned alongside the consuming named rule. Objects stay8-aligned.
    if type(value)is not int or value<4096 or value%4 or value+28>1<<64:
        raise ValueError('Invalid qualified 28-byte concern POD record pointer')
    return value


def q(read,address):return players.u64(read(address,8))


def verify_native(read,base):
    pointer(base)
    if base%4096 or base+0x55edf68>=1<<64:raise ValueError('Invalid concern source base')
    for rva,size,digest in SOURCE:
        if hashlib.sha256(read(base+rva,size)).hexdigest()!=digest:
            raise ValueError('Native concern source changed at '+hex(rva))
    if(struct.unpack('<q',read(base+0x55edf40,8))[0]!=0
            or q(read,base+0x55edf48)!=base+0x55edae0
            or q(read,base+0x55edf60)!=base+0x24a9e1c
            or q(read,base+0x55edae8)!=base+0x53bce67
            or read(base+0x53bce67,len(RULE))!=RULE):
        raise ValueError('Named native unhappiness-reason rule changed')
    assessment_people.verify_native(read,base)


def date_field(raw,role):
    packed=int.from_bytes(raw,'little')
    try:value=world.packed_date(raw)
    except ValueError:value=None
    return dict(value=value,raw_hex=raw.hex(),stored_year=packed>>16,stored_day_of_year=packed&511,
        unmapped_low_word_flags=packed&0xfe00,role=role,
        state='stored_native_date'if value else'unavailable_native_date')


def stored_name(read,primary):
    first,last,common=(q(read,primary+offset)for offset in(0x298,0x2a0,0x2a8))
    given,family=players.name_part(read,first),players.name_part(read,last)
    common=players.common_name(read,common)
    full=' '.join(value for value in(given,family)if value)or common
    if not full:raise ValueError('Canonical concern owner has no stored name')
    return dict(display_name=common or full,full_name=full,name_source='stored_ACTUAL_PLAYER_name_handles')


def inspect(read,base,primary,kind,*,include_stored_name=False):
    if type(include_stored_name)is not bool:raise ValueError('Invalid concern name policy')
    verify_native(read,base)
    common=dict(owner=None,native_ring_entry_count=None,native_unset_end_filter_count=None,records=None,
        whole_manager_population_verified=False,UI_or_fulfilment_evaluated=False,scope=SCOPE)
    if kind!='actual':return dict(common,state='unsupported_record_kind')
    primary=pointer(primary);people=database.table(read,base,'people');person=primary+0x388
    found,offset,owner,*_=assessment_people._person(read,base,people,person)
    if found!=primary or offset!=0x388 or owner['record_kind']!='actual':raise ValueError('Concern canonical PLAYER owner changed')
    owner=dict(owner)
    if include_stored_name:owner.update(stored_name(read,primary))
    common['owner']=owner
    table=pointer(q(read,person))
    if(q(read,table+0x3c0)!=base+0xcb8c68 or struct.unpack('<q',read(table-0x3d0,8))[0]!=-0x110):
        raise ValueError('Native concern PERSON/context-contract dispatch changed')
    normalized=person-0x110
    if(q(read,normalized)!=base+0x5589a90 or struct.unpack('<q',read(base+0x5589a90-16,8))[0]!=-0x278):
        raise ValueError('Concern normalized PLAYER subobject changed')
    current_team=q(read,primary+0x128)
    if not current_team:return dict(common,state='current_team_unavailable')
    current_team=pointer(current_team);world.typed(read,base,current_team,'team')
    current_club=pointer(q(read,current_team+0x30));world.typed(read,base,current_club,'club')
    if current_team not in world.vector(read,current_club+0x18,64):raise ValueError('Concern current TEAM is absent from CLUB teams')
    contract=q(read,normalized+0x78)
    if not contract:return dict(common,state='main_contract_unavailable')
    contract=pointer(contract);contract_table=pointer(q(read,contract))
    if contract_table!=base+world.TYPES['full_contract'][0]:
        return dict(common,state='non_FULL_CONTRACT_context_unavailable')
    world.typed(read,base,contract,'full_contract')
    if q(read,contract+8)!=person:raise ValueError('Concern main-contract owner changed')
    if q(read,contract_table+0x90)!=base+0x129fffc:
        raise ValueError('Concern FULL_CONTRACT type getter changed')
    main_team=q(read,contract+0x10)
    if not main_team:return dict(common,state='main_contract_team_unavailable')
    main_team=pointer(main_team);world.typed(read,base,main_team,'team')
    main_club=pointer(q(read,main_team+0x30));world.typed(read,base,main_club,'club')
    if main_team not in world.vector(read,main_club+0x18,64):raise ValueError('Concern main-contract TEAM is absent from CLUB teams')
    if main_club!=current_club:return dict(common,state='main_contract_outside_current_CLUB_context')
    # Original CB85FC calls this FULL_CONTRACT type getter (raw0), then returns
    # the main pointer at CB8C50 once the two CLUB pointers match. The auxiliary
    # holder/affiliate paths are not consulted on this supported branch.
    ring=q(read,contract+0x30)
    common.update(contract_context='owned_main_FULL_CONTRACT_matches_current_TEAM_CLUB',
        native_current_club_id=struct.unpack('<I',read(current_club+0xc,4))[0])
    if not common['native_current_club_id']:raise ValueError('Concern context CLUB identity is missing')
    if not ring:return dict(common,state='absent_native_ring',native_ring_entry_count=0,native_unset_end_filter_count=0,records=[])
    ring=pointer(ring);header=read(ring,96)
    if len(header)!=96:raise ValueError('Incomplete native concern ring')
    count,head=header[0],header[0x58]
    if count>10 or head>9:raise ValueError('Native concern ring geometry rejected')
    category_table=read(base+0x539ba90,863)
    if len(category_table)!=863:raise ValueError('Incomplete native concern category table')
    rows=[];open_count=0
    for ordinal in range(count):
        slot=(count+head-1-ordinal)%10;record=struct.unpack_from('<Q',header,8+slot*8)[0]
        decoded=None
        if record:
            record=pod_record_pointer(record);raw=read(record,28)
            if len(raw)!=28:raise ValueError('Incomplete native concern record')
            start,end=date_field(raw[:4],'stored_native_start_or_creation_date'),date_field(raw[4:8],'stored_native_end_date')
            unset=end['stored_year']==1900 and end['stored_day_of_year']==1
            reason=struct.unpack_from('<H',raw,0x16)[0]
            decoded=dict(stored_start_date=start,stored_end_date=end,matches_native_unset_end_date=unset,
                native_reason_code=reason,reason_title=None,reason_title_state='not_decoded',
                native_stored_category_code=raw[0x19],compiled_reason_category_code=category_table[reason-500]if 500<=reason<=1362 else 0,
                native_scalar08=struct.unpack_from('<i',raw,8)[0],native_scalar0c=struct.unpack_from('<i',raw,0xc)[0],
                native_scalar10=struct.unpack_from('<I',raw,0x10)[0],native_scalar14=struct.unpack_from('<H',raw,0x14)[0],
                native_scalar18=struct.unpack_from('<b',raw,0x18)[0],native_byte1a=raw[0x1a],native_flags1b=raw[0x1b],
                satisfaction=None,promise_fulfilled=None,UI_or_fulfilment_evaluated=False)
            open_count+=int(unset)
        rows.append(dict(entry_index=ordinal,native_physical_slot=slot,
            state='observed_native_record'if decoded is not None else'null_native_ring_slot',record=decoded))
    return dict(common,state='observed_native_ring'if count else'observed_empty_native_ring',
        native_ring_entry_count=count,native_unset_end_filter_count=open_count,records=rows)
