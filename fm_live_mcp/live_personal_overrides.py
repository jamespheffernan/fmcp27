"""Bounded stored personal position records under explicit native lookup policies."""
import struct

from . import prepared_tactic_roles as roles

MAP_OFFSETS={'in_possession':0x760,'out_of_possession':0x778}
MAX_NODES=256
MAX_RECORDS=128
MAX_TOTAL_RECORDS=2048


class UnsupportedSource(ValueError):
    """Incomplete optional source must never become an empty personal map."""


def verify_native(read,base):
    for rva,raw in NATIVE_SPANS:
        if read(base+rva,len(raw))!=raw:
            raise ValueError(f'Personal override native source changed at RVA {rva:#x}')


def _pointer(value):
    if value<4096 or value%8 or value+0x40>=1<<64:
        raise UnsupportedSource('invalid_map_pointer')


def _take(read,address,size):
    raw=read(address,size)
    if len(raw)!=size:raise UnsupportedSource('incomplete_personal_source')
    return raw


def _map(read,header,wanted):
    begin,root,count=struct.unpack('<QQQ',_take(read,header,24))
    if not root:
        if count or begin!=header+8:
            raise UnsupportedSource('malformed_empty_map')
        return {},0
    if not 1<=count<=MAX_NODES:
        raise UnsupportedSource('map_node_budget_or_count_unsupported')
    _pointer(begin)
    stack=[(root,None,None)]
    visited=set()
    nodes={}
    minimum=None
    while stack:
        node,lower,upper=stack.pop()
        _pointer(node)
        if node==header+8 or node in visited or len(visited)>=count:
            raise UnsupportedSource('map_cycle_or_node_count_mismatch')
        visited.add(node)
        raw=_take(read,node,0x40)
        left,right=struct.unpack_from('<QQ',raw)
        key=struct.unpack_from('<I',raw,0x20)[0]
        if (lower is not None and key<=lower)or(upper is not None and key>=upper):
            raise UnsupportedSource('map_duplicate_key_or_ordering_mismatch')
        if minimum is None or key<minimum[0]:minimum=(key,node)
        if key in wanted:nodes[key]=struct.unpack_from('<QQQ',raw,0x28)
        if right:stack.append((right,key,upper))
        if left:stack.append((left,lower,key))
    if len(visited)!=count or begin!=minimum[1]:
        raise UnsupportedSource('map_size_or_begin_mismatch')
    entries={}
    total=0
    for key,(start,end,capacity)in nodes.items():
        if (start,end,capacity)==(0,0,0):
            entries[key]=[]
            continue
        _pointer(start)
        if (not start<=end<=capacity or any(v%8 for v in(end,capacity))
                or(end-start)%72 or(capacity-start)%72):
            raise UnsupportedSource('invalid_personal_record_vector')
        count=(end-start)//72
        total+=count
        if capacity-start>MAX_RECORDS*72 or total>MAX_TOTAL_RECORDS:
            raise UnsupportedSource('personal_record_reader_budget_exhausted')
        raw=read(start,end-start)if end>start else b''
        if len(raw)!=end-start:raise UnsupportedSource('incomplete_personal_record_vector')
        entries[key]=[raw[at:at+72]for at in range(0,len(raw),72)]
    return entries,len(visited)


def _lookup(records,mask,phase,strict=False):
    profile=('normalized_position_mask_activation_equals_one'if strict
             else 'exact_position_mask_nonzero_activation')
    result={'state':'absent','reason':None,'lookup_profile':profile,'query_position_mask':mask,
            'record_index':None,'activation_raw_u8':None,'record_position_mask':None,
            'stored_role':None,'effective_role_state':'not_established',
            'instructions_state':'not_decoded'}
    if records is None:
        result['reason']='no_personal_entry'
        return result
    if mask is None:
        result.update(state='unavailable',reason='assignment_position_unavailable')
        return result
    for index,raw in enumerate(records):
        stored=struct.unpack_from('<I',raw)[0]
        if stored!=mask:continue
        activation=raw[0x20]
        active=activation==1 if strict else activation!=0
        result.update(state='present'if active else 'inactive',
            reason='stored_active_for_named_lookup_profile'if active else 'first_match_inactive_for_named_lookup_profile',
            record_index=index,activation_raw_u8=activation,record_position_mask=stored,
            stored_role=roles.decode_word(struct.unpack_from('<Q',raw,0x40)[0],phase))
        return result
    result['reason']='no_matching_position_record'
    return result


def _row(row,records,phase):
    if row['person']is None:
        return {'state':'unavailable','reason':'empty_selection_slot',
                'effective_role_state':'not_established','instructions_state':'not_decoded'}
    mask=row['position']['native_mask']if row['position']is not None else None
    exact=_lookup(records,mask,phase)
    out={'state':exact['state'],'reason':exact['reason'],'exact_position_lookup':exact,
         'effective_role_state':'not_established','instructions_state':'not_decoded'}
    if phase=='in_possession':
        strict=_lookup(records,None if mask is None else mask&0xffcfffff,phase,True)
        out['strict_ip_role_lookup']=strict
        signature=lambda result:(result['state'],result['record_index'])
        same=signature(exact)==signature(strict)
        out['lookup_policies_agree']=same
        if not same:out.update(state='policy_dependent',reason='named_native_lookup_policies_differ')
    return out


def attach(read,base,creator,phases):
    """Annotate requested phase rows only; base assignments are never replaced."""
    verify_native(read,base)
    context={}
    for phase,result in phases.items():
        if creator is None or result['assignments']is None:
            context[phase]={'state':'unavailable','reason':'working_creator_or_assignment_source_unavailable',
                            'person_key_count':None,'complete_for_requested_people':False}
            continue
        rows=result['assignments']
        wanted={row['person']['database_index']for row in rows if row['person']is not None}
        try:
            entries,count=_map(read,creator+MAP_OFFSETS[phase],wanted)
        except UnsupportedSource as exc:
            reason=str(exc)
            context[phase]={'state':'unavailable','reason':reason,'person_key_count':None,
                            'complete_for_requested_people':False}
            for row in rows:
                row['personal_override']={'state':'unavailable','reason':reason,
                    'effective_role_state':'not_established','instructions_state':'not_decoded'}
            continue
        context[phase]={'state':'available','reason':None,'person_key_count':count,
                        'complete_for_requested_people':True}
        for row in rows:
            person=row['person']
            records=None if person is None else entries.get(person['database_index'])
            row['personal_override']=_row(row,records,phase)
    return {'phases':context,'scope':'stored personal position records under named lookup policies; base instructions not inspected',
            'effective_roles_established':False,'all_instructions_established':False}


NATIVE_SPANS = (
    (0x484a810, bytes.fromhex('7fb603f9a84a45f9080100b5a87300f008a1199108c1bf3808060036a87300f008c11891a84a05f968a21d917fba03f968b203f968021e9100e4006f60e2813d68be03f976421e9160e6813d')),
    (0x2ed0cb0, bytes.fromhex('e8af40f9087974f8c83e00b4090140f929815ef80801098b150940b9353ef837084001d008c146f9c83d00b4094001f029815339e900003709a946a94a0109cbbf0e8aeb62000054280d158b08000014084540f9082540a9290108eb203c0054bf0e89ebe23b0054080d158b170140f9973b00b4')),
    (0x2ed0f4c, bytes.fromhex('080980528862089b08810491152000b94bb543f90b0400b4090140b94ca11d91ea030caa6d2140b9bf01156bed279f1a4a318b9a6b596df86bffffb55f010ceba00200544b2140b97f01156b480200544aad42a96b010aebe00100546bfd43932cc791d26c1ca7f2cc71dcf20cc7f1f26b7d0c9b7f0500f16b859f9a4c0140b99f01096be00d00544a2101916b0500f161ffff54090080d23f0100f10801899a150140b9182140f9')),
    (0x2ed118c, bytes.fromhex('498140393f01007149119f9a93ffff17')),
    (0x485a498, bytes.fromhex('09b443f9e90300b40aa01d91e8030aaa2b2140b97f01016beb279f1a0831899a29596bf869ffffb51f010aeba0020054092140b93f01016b4802005408a542a9290108ebe001005429fd43932ac791d26a1ca7f2ca71dcf20ac7f1f2297d0a9b3f0500f129859f9a0a0140b95f01026bc000005408210191290500f161ffff54000080d2c0035fd6098140393f01007100119f9ac0035fd6')),
    (0x485a530, bytes.fromhex('09c043f9e90300b40a001e91e8030aaa2b2140b97f01016beb279f1a0831899a29596bf869ffffb51f010aeba0020054092140b93f01016b4802005408a542a9290108ebe001005429fd43932ac791d26a1ca7f2ca71dcf20ac7f1f2297d0a9b3f0500f129859f9a0a0140b95f01026bc000005408210191290500f161ffff54000080d2c0035fd6098140393f01007100119f9ac0035fd6')),
    (0x4857a48, bytes.fromhex('e80300aa090980524900299b20b140f90ab543f94a0400b4292141b929750a120ba11d91e8030baa4c2140b99f01016bec279f1a08318a9a4a596cf86affffb51f010bebc00200540a2140b95f01016b6802005408a942a94a0108eb000200544afd43932bc791d26b1ca7f2cb71dcf20bc7f1f24a7d0b9b5f0500f14a859f9a080101910b015cb87f01096ba0000054082101914a0500f161ffff54c0035fd609015e383f050071a1ffff54000140f9c0035fd6')),
    (0x483c64c, bytes.fromhex('3f08007108030054297c4093080848f90b0448f908010bcb3f0d88eb42020054e80300aa000080d24a1c00125f29007168160054697969f8291600b44b4e82520b010b8b0c0980524c25ac9b808104916c0140399f010a6ba10000540a0080d27f000014000080d2c0035fd66c4142399f010a6b610000542a008052780000146c8144399f010a6b610000544a008052730000146cc146399f010a6b610000546a0080526e0000146c0149399f010a6b610000548a008052690000146c414b399f010a6b61000054aa008052640000146c814d399f010a6b61000054ca0080525f0000146cc14f399f010a6b61000054ea0080525a0000146c0152399f010a6b610000540a018052550000146c4154399f010a6b610000542a018052500000146c8156399f010a6b610000544a0180524b0000146cc158399f010a6b610000546a018052460000146c015b399f010a6b610000548a018052410000146c415d399f010a6b61000054aa0180523c0000146c815f399f010a6b61000054ca018052370000146cc161399f010a6b61000054ea018052320000146c0164399f010a6b610000540a0280522d0000146c4166399f010a6b610000542a028052280000146c8168399f010a6b610000544a028052230000146cc16a399f010a6b610000546a0280521e0000146c016d399f010a6b610000548a028052190000146c416f399f010a6b61000054aa028052140000146c8171399f010a6b61000054ca0280520f0000146cc173399f010a6b61000054ea0280520a0000146c0176399f010a6b610000540a038052050000146b4178397f010a6b410500542a03805208090a8b0a2950b95f050031a00400542bb543f90b0400b4080040b92ca11d91e9030caa6d2140b9bf010a6bed279f1a29318b9a6b596df86bffffb53f010ceba00200542b2140b97f010a6b4802005429a942a94a0109ebe00100544afd43932bc791d26b1ca7f2cb71dcf20bc7f1f24a7d0b9b5f0500f14a859f9a2b0140b97f01086b00010054292101914a0500f161ffff54080080d21f0100f10000889ac0035fd6288140391f01007128119f9afaffff17')),
    (0x483c95c, bytes.fromhex('3f080071c8060054297c4093080848f90a0448f908010acb3f0d88eb02060054e80300aa000080d24b1c00127f290071281d0054497969f8e91c00b44a4e82520a010a8b0c0980526c25ac9b800111912cd15e399f010b6b600400542cd55e399f010b6b400400542cd95e399f010b6b200400542cdd5e399f010b6b000400542ce15e399f010b6be00300542ce55e399f010b6bc00300542ce95e399f010b6ba00300542ced5e399f010b6b800300542cf15e399f010b6b600300542cf55e399f010b6b400300542cf95e394d0180529f010b6bab018b1a16000014000080d2c0035fd60b008052120000142b008052100000144b0080520e0000146b0080520c0000148b0080520a000014ab00805208000014cb00805206000014eb008052040000140b018052020000142b0180524c0140399f010b6b610000540a0080d27d0000144c4142399f010b6b610000542a008052780000144c8144399f010b6b610000544a008052730000144cc146399f010b6b610000546a0080526e0000144c0149399f010b6b610000548a008052690000144c414b399f010b6b61000054aa008052640000144c814d399f010b6b61000054ca0080525f0000144cc14f399f010b6b61000054ea0080525a0000144c0152399f010b6b610000540a018052550000144c4154399f010b6b610000542a018052500000144c8156399f010b6b610000544a0180524b0000144cc158399f010b6b610000546a018052460000144c015b399f010b6b610000548a018052410000144c415d399f010b6b61000054aa0180523c0000144c815f399f010b6b61000054ca018052370000144cc161399f010b6b61000054ea018052320000144c0164399f010b6b610000540a0280522d0000144c4166399f010b6b610000542a028052280000144c8168399f010b6b610000544a028052230000144cc16a399f010b6b610000546a0280521e0000144c016d399f010b6b610000548a028052190000144c416f399f010b6b61000054aa028052140000144c8171399f010b6b61000054ca0280520f0000144cc173399f010b6b61000054ea0280520a0000144c0176399f010b6b610000540a038052050000144a4178395f010b6b410500542a03805208090a8b0a2950b95f050031a00400542bc143f90b0400b4080040b92c011e91e9030caa6d2140b9bf010a6bed279f1a29318b9a6b596df86bffffb53f010ceba00200542b2140b97f010a6b4802005429a942a94a0109ebe00100544afd43932bc791d26b1ca7f2cb71dcf20bc7f1f24a7d0b9b5f0500f14a859f9a2b0140b97f01086b00010054292101914a0500f161ffff54080080d21f0100f10000889ac0035fd6288140391f01007128119f9afaffff17')),
    (0x2e5200c, bytes.fromhex('3f6400718800005408c8218b002950b9c0035fd600008012c0035fd6')),
    (0x2e52ad8, bytes.fromhex('e20301aa080482520168e838daa66714')),
    (0x2e52ae8, bytes.fromhex('e20301aa080482520168e8389aa76714')),
    (0x52e718, bytes.fromhex('ff4301d1f85f01a9f65702a9f44f03a9fd7b04a9fd030191f30308aa400400b43f40007108040054888b02d008813191090380522920299b280540f9480300b4f40300aa360140f917f57ed31860a352d50240b9880240b9e80f00b9822240f9f80700b9e1330091e3130091e4230091e00315aaf5121195e00314aae10315aa020080d2211c119520020037e80b40b91f0d0071c0010054d6120091f71200f181fdff54ff0f00b9e1330091e00313aa635bfb94fd7b44a9f44f43a9f65742a9f85f41a9ff430191c0035fd6f50f00b9f6ffff17')),
    (0x52e7ec, bytes.fromhex('ff4301d1f85f01a9f65702a9f44f03a9fd7b04a9fd030191f30308aa400400b43f40007108040054888b02d008813191090380522920299b280540f9480300b4f40300aa360140f917f57ed31860a352d50240b9880240b9e80f00b9822240f9f80700b9e1330091e3130091e4230091e00315aa3c1a1195e00314aae10315aa020080d2eec0169520020037e80b40b91f0d0071c0010054d6120091f71200f181fdff54ff0f00b9e1330091e00313aa2e5bfb94fd7b44a9f44f43a9f65742a9f85f41a9ff430191c0035fd6f50f00b9f6ffff17')),
    (0x51b91c, bytes.fromhex('e00314aae10316aae20315aa9ed4a494f80300aae00314aae10316aab5d9a494f50300aae2020052e00314aae10318aa1bd5a494e20300aab7000034e00313aae10315aacefa0c9504000014e00313aae10315aaf0fa0c951f0000f1f3079f1a')),
    (0x52e484, bytes.fromhex('a002188be10317aae20314aa3c3a0c95f60300aaa002188be10317aae20314aa6a380c95f40300aac21e0013a002188be10317aa29390c95f50300aa180080d2396e02b039e30891366bf838e00316aab2cb0e95c0000036e8630091e00315aae10316aac100009405000014e8630091e00314aae10316aa87000094')),
)
