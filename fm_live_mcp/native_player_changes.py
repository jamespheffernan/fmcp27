"""Typed native participation changes from the checked engine change vector.

Native SUBSTITUTION on/off slots are source facts. The vector may contain
pending or archived changes: no completeness, execution order or fixed-frame
playing interval is inferred. PLAYER_PUT_ON is not a formal-starting-XI label.
"""
import struct
from . import active_match_people as people,frame_attack_direction as direction

MAX_CHANGES=4096
NATIVE_SPANS=(
    (0x4A7A9BC,bytes.fromhex("08008012080800b960c7072f000c00bde81f805208400039286100b008811f91080000f9c0035fd6")),
    (0x4A799DC,bytes.fromhex("08008012080800b9286100d008a11891080000f920c5072f000c00bde81f805208400039c0035fd6")),
    (0x4A7AA40,bytes.fromhex("08388039a80c088b096e8a522900a0721a6969f8")),
    (0x4A7AA5C,bytes.fromhex("54030591603f0091211b319793da60f8603f00911c1b319798da60f8")),
    (0x16C16E0,bytes.fromhex("0000c039c0035fd60004c039c0035fd6")),
    (0x4A79A54,bytes.fromhex("08388039a80c088b096e8a522900a072136969f8083c8039680e088b18a140f9")),
    (0x48BD7BC,bytes.fromhex("081c40f9480000b5c0035fd60851409100c11f9172370714")),
    (0x4A59AC8,bytes.fromhex("6852409101c11f91e20314aa0fc80094")),
    (0x4A8B248,bytes.fromhex("ff0301d1f65701a9f44f02a9fd7b03a9fdc30091f30308aa1f70007188020054e803002aa94b0090294d37918a0000102b6968384a090b8b")),
)
# The SUBSTITUTION constructor stores the vtable of simatch::SUBSTITUTION_TACTIC_CHANGE (vmi type info:
# TACTIC_CHANGE at +0, SUBSTITUTION at +0xf), so the RTTI name checked is that class's, not the base's.
TYPES={0x569F7E0:('SUBSTITUTION',b'N7simatch26SUBSTITUTION_TACTIC_CHANGEE',0x4A7A9E4,4),
       0x569F628:('PLAYER_PUT_ON',b'N7simatch13PLAYER_PUT_ONE',0x4A79A04,22)}


def verify_native(read,base):
    for at,expected in NATIVE_SPANS:
        if direction._read(read,base+at,len(expected))!=expected:
            raise ValueError('Native typed player-change source changed')
    for table,(_,_,apply,_) in TYPES.items():
        if direction._q(read,base+table+0x20)!=base+apply:
            raise ValueError('Native typed player-change apply route changed')


def capture(read,base,bound):
    verify_native(read,base)
    engine=bound['source_match_address']
    people._type(read,base,engine,0x55FA258,b'10GAME_MATCH')
    if direction._q(read,engine+0x20)!=bound['official_match_unique_id']:
        raise ValueError('Native player-change fixture identity changed')
    vector=direction._read(read,engine+0x147F0,24)
    first,last,capacity=struct.unpack('<3Q',vector)
    result={'state':'available_native_player_change_storage',
        'official_match_unique_id':bound['official_match_unique_id'],'rows':[],
        'history_complete':None,'pending_vs_executed_verified':False,
        'fixed_frame_participation_verified':False,'_source':(vector,)}
    if (first,last,capacity)==(0,0,0):return result
    direction._pointer(first)
    if not first<=last<=capacity or (last-first)%8 or (capacity-first)%8:
        raise ValueError('Unsupported native player-change vector bounds')
    if (capacity-first)//8>MAX_CHANGES:
        return result | {'state':'unavailable_native_player_change_budget','rows':None}
    pointers=b''.join(direction._read(read,at,min(8192,last-at)) for at in range(first,last,8192))
    objects=[];rows=[]
    for index,address in enumerate(struct.unpack(f'<{(last-first)//8}Q',pointers)):
        row={'native_change_index':index,'kind':None,'side_index':None,
            'native_change_tick':None,'player_on_original_slot':None,
            'player_off_original_slot':None,'formation_index_raw':None}
        if not address:rows.append(row | {'state':'unavailable_null_change_object'});objects.append(None);continue
        direction._pointer(address)
        table_raw=direction._read(read,address,8)
        table=struct.unpack('<Q',table_raw)[0]-base
        kind=TYPES.get(table)
        if kind is None:
            rows.append(row | {'state':'unavailable_unclassified_native_change_type'});objects.append((address,table_raw));continue
        name,typename,_,code=kind
        people._type(read,base,address,table,typename)
        raw=direction._read(read,address,17)
        if raw[13]!=code:raise ValueError('Typed native player-change kind disagrees with constructor')
        clock=struct.unpack_from('<i',raw,8)[0]
        side,on,other=struct.unpack_from('<3b',raw,14)
        objects.append((address,raw))
        if side not in (0,1) or not 0<=on<26 or (name=='SUBSTITUTION' and not 0<=other<26):
            rows.append(row | {'state':'unavailable_typed_change_side_or_original_slot','kind':name});continue
        rows.append(row | {'state':'typed_original_slot_change_with_native_clock' if clock>=0 else 'typed_original_slot_change_clock_unavailable',
            'kind':name,'side_index':side,'native_change_tick':clock if clock>=0 else None,
            'player_on_original_slot':on,'player_off_original_slot':other if name=='SUBSTITUTION' else None,
            'formation_index_raw':other if name=='PLAYER_PUT_ON' else None})
    return result | {'rows':rows,'_source':(vector,pointers,objects)}


def verify_capture(read,base,bound,captured):
    if capture(read,base,bound)!=captured:
        raise ValueError('Native player-change storage changed')
    return captured | {'native_change_source_physically_reselected':True}
