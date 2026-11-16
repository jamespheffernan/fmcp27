"""Current managed-team stored penalty priorities; no working-copy/final-match claim."""
import struct
from . import assessment_people, database, live_team_sheet_source, players, prepared_tactics_source as source, world

MAX_TAKERS=64


def verify_native(read,base):
    source.verify_native(read,base)
    for rva,raw in NATIVE_SPANS:
        if read(base+rva,len(raw))!=raw:raise ValueError('Managed penalty priority native source changed')


def _clubs(read,base,people,index,person):
    if person['record_kind'] not in ('actual','player_staff'):
        return None,'unavailable_for_virtual_identity'
    address=world.pointer(read,people['start']+index*8)
    primary,_,_,native,secondary=assessment_people._person(read,base,people,address)
    if native!=person['native_id'] or secondary!=person['secondary_id']:
        raise ValueError('Penalty taker identity changed during club lookup')
    return world.player_clubs(read,base,primary,{},player_staff=person['record_kind']=='player_staff'),'decoded'


def inspect(read,base,coach):
    verify_native(read,base)
    team,human=source._team_and_human(read,base,coach)
    result={'team':team,'source_level':'current_managed_team_stored_penalty_priority',
            'source_state':'unavailable','unavailable_reason':None,'complete_stored_order':False,
            'ordered_takers':None,'stored_count':None,'duplicate_person_indices':None,
            'edit_session_override':{'state':'unknown','reason':'working_copy_penalty_order_not_bound'},
            'actual_match_taker_state':'not_established','shootout_outcome_state':'not_predicted'}
    manager=players.u64(read(base+source.MANAGER_ROOT,8))
    if not manager:result['unavailable_reason']='tactics_manager_missing';return result
    source._typed(read,base,manager,source.MANAGER_VTABLE,b'15TACTICS_MANAGER')
    owners=[p for p in source._vector(read,manager+0x20,source.OWNER_LIMIT) if p and players.u64(read(p+0x98,8))==human]
    if len(owners)>1:raise ValueError('Managed penalty owner container is ambiguous')
    if not owners:result['unavailable_reason']='owner_container_missing';return result
    payload=source._team_entry(read,owners[0],team['database_index'])
    if payload is None:result['unavailable_reason']='team_entry_missing';return result
    source._typed(read,base,payload+0xff8,source.PREPARED_VTABLE,b'N7simatch30PREPARED_TACTICS_CREATOR_ARRAYE')
    start,end,capacity=struct.unpack('<QQQ',read(payload+0x1e0,24))
    if (start,end,capacity)==(0,0,0):words=()
    else:
        if (start<4096 or any(x%4 for x in (start,end,capacity)) or not start<=end<=capacity
                or capacity-start>MAX_TAKERS*4):raise ValueError('Invalid managed penalty priority vector bounds')
        count=(end-start)//4
        words=struct.unpack(f'<{count}I',read(start,count*4)) if count else ()
    people=database.table(read,base,'people');rows=[];resolved={}
    for slot,index in enumerate(words):
        row={'priority':slot+1,'stored_slot_index':slot,'person_index_word':index,
             'state':'unresolved_person_reference','person':None,'unavailable_reason':None,
             'clubs':None,'clubs_state':'unavailable','is_first_stored_priority':slot==0}
        if index==0xffffffff:row.update(state='unassigned_sentinel',unavailable_reason='native_null_PERSON')
        elif index>=0x80000000:row['unavailable_reason']='negative_PERSON_reference'
        else:
            if index not in resolved:
                if index>=people['count']:resolved[index]=(None,'PERSON_index_outside_live_table')
                else:
                    # Unsupported PERSON classes retain the stored reference, never another identity.
                    try:resolved[index]=(live_team_sheet_source._person(read,base,people,index),None)
                    except ValueError as error:resolved[index]=(None,str(error))
            person,reason=resolved[index]
            row['person']=person;row['unavailable_reason']=reason
            if person is not None:
                row['state']='identified'
                try:row['clubs'],row['clubs_state']=_clubs(read,base,people,index,person)
                except ValueError as error:row['clubs_state']='unavailable: '+str(error)
        rows.append(row)
    result.update(source_state='available',complete_stored_order=True,ordered_takers=rows,stored_count=len(rows),
                  duplicate_person_indices=sorted({i for i in words if i<0x80000000 and words.count(i)>1}))
    return result


NATIVE_SPANS=(
    (0x2039c74,bytes.fromhex('f30302aaf40301aa68b301f0158941f9e00315aa020080d2e30313aa06622c94400200b4098c40f8490400b4680a40b9ea0300aa2b2140b97f01086beba79f1a4ab1899a29596bf869ffffb55f0100eb00030054492140b94aa100911f01096be0b38a9a14000014')),
    (0x26de5a8,bytes.fromhex('020340f9c05246f9080040f9084d40f9e10f40f900013fd6800900b4f40300aa09205ea9080109cb1f7d7ef2e0080054')),
    (0x26de5e8,bytes.fromhex('89225ea9080109cb29011b8b3f0b88eb28319c9a080140b91f050031')),
    (0x47fd58,bytes.fromhex('88898952e8a9ac721f03086b61790054e8a65ea91f0109eb409c0054e0a20791010080d2a62b1895080040b9297c029029412b91290140b91f01096b00119f5af59a2f94e09a00b4e8030b9101008052ee630794')),
)
