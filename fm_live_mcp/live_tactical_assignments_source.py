"""Two-phase working tactical assignments using the stored native OOP remap."""
from collections import Counter
from copy import deepcopy
import struct

from . import live_in_possession_source as ip
from . import live_personal_overrides

PHASES = ('in_possession','out_of_possession')


def verify_native(read,base):
    for rva,raw in NATIVE_SPANS:
        if read(base+rva,len(raw)) != raw:
            raise ValueError(f'Out-of-possession pairing native source changed at RVA {rva:#x}')


def phase_slot(raw,index):
    """The native FF fallback precedes signed conversion; no other sentinel exists."""
    if type(raw) is not int or not 0<=raw<=255 or type(index) is not int or not 0<=index<=10:
        raise ValueError('Invalid tactical phase map input')
    value=index if raw==255 else raw if raw<128 else raw-256
    return value if 0<=value<=10 else None


def _out_of_possession(read,base,creator,original):
    result=deepcopy(original)
    result.update(phase='out_of_possession',phase_mapping_state='native_creator_map',
                  duplicate_phase_slot_indices=None)
    result.pop('out_of_possession_pairing_state',None)
    if creator is None:
        result['phase_mapping_state']='source_unavailable'
        return result
    verify_native(read,base)
    raw=read(creator+0x7B4,11)
    if len(raw)!=11:
        raise ValueError('Incomplete tactical phase map')
    mapped=[phase_slot(value,index)for index,value in enumerate(raw)]
    counts=Counter(index for index in mapped if index is not None)
    positions,base_roles={},{}
    for index in dict.fromkeys(mapped):
        if index is None:
            continue
        mask=struct.unpack('<I',read(creator+0x440+index*0x48,4))[0]
        name=ip.fields.POSITION_NAMES.get(mask)
        positions[index]={'position_index':index,'native_mask':mask,'name':name,
                          'state':'named'if name is not None else 'unmapped_native_mask'}
        base_roles[index]=ip.roles.decode(read,creator,'out_of_possession',index)
    assignments=[]
    for index,row in enumerate(original['assignments']):
        target=mapped[index]
        result_row={'slot_index':index,'selection_state':row['selection_state'],
            'person':row['person'],'phase_map_raw_u8':raw[index],
            'phase_map_state':('identity_fallback'if raw[index]==255 else 'stored_index'
                               if target is not None else 'outside_supported_phase_extent'),
            'phase_slot_index':target,
            'phase_slot_shared':target is not None and counts[target]>1,
            'position':positions.get(target),'stored_base_role':base_roles.get(target)}
        pairing=('empty_slot'if row['person']is None else 'unsupported_phase_index'
                 if target is None else row['pairing_state']if row['pairing_state']!='paired_by_native_slot'
                 else 'paired_by_native_phase_map')
        named=(pairing=='paired_by_native_phase_map'and positions[target]['state']=='named'
               and base_roles[target]['name_state']=='named')
        result_row.update(pairing_state=pairing,named_assignment_available=named)
        assignments.append(result_row)
    named_count=sum(row['named_assignment_available']for row in assignments)
    duplicates=sorted(index for index,count in counts.items()if count>1)
    masks=Counter(row['position']['native_mask']for row in assignments if row['position']is not None)
    role_counts=Counter(row['stored_base_role']['raw_encoding']for row in assignments
                        if row['stored_base_role']is not None)
    result.update(assignments=assignments,assignment_count=11,named_assignment_count=named_count,
        complete_named_assignments=named_count==11,source_state='available'if named_count==11 else 'partial',
        duplicate_phase_slot_indices=duplicates,
        duplicate_position_masks=sorted(mask for mask,count in masks.items()if count>1),
        duplicate_role_encodings=sorted(role for role,count in role_counts.items()if count>1))
    return result


def inspect(read,base,coach,phase='both',*,include_personal_overrides=False):
    if type(include_personal_overrides)is not bool:
        raise ValueError('include_personal_overrides must be a boolean')
    if type(phase)is not str or phase not in ('both',*PHASES):
        raise ValueError('Select both, in_possession or out_of_possession')
    original,creator=ip._inspect_context(read,base,coach)
    phases={}
    if phase in ('both','in_possession'):
        first=deepcopy(original)
        first.pop('out_of_possession_pairing_state',None)
        first['phase_mapping_state']='native_same_selection_slot'
        phases['in_possession']=first
    if phase in ('both','out_of_possession'):
        phases['out_of_possession']=_out_of_possession(read,base,creator,original)
    states=[value['source_state']for value in phases.values()]
    state=('available'if all(value=='available'for value in states)else 'unavailable'
           if all(value=='unavailable'for value in states)else 'partial')
    result={'team':original['team'],'source_state':state,'requested_phase':phase,
        'source':'existing_human_tactic_edit_session_working_payload',
        'tactic':original['tactic'],'selected_creator_index':original['selected_creator_index'],
        'creator_count':original['creator_count'],'phases':phases,
        'complete_requested_named_assignments':all(value['complete_named_assignments']for value in phases.values()),
        'foreground_screen_state':'not_observed','match_submission_state':'not_established',
        'effective_player_role_overrides_state':'not_established'}
    if include_personal_overrides:
        result['personal_override_context']=live_personal_overrides.attach(read,base,creator,phases)
    return result


# Pinned working HUMAN/session path, remap producer/getter and both consumers.
NATIVE_SPANS = (
    (0x2392988, bytes.fromhex('880340f908815ef8c16a68b808048252a002088b9b7083941f04003100184a7a4c03005408038252a86a68381f0900f1c8020054aa0648f9a90248f94a0109cb1f0d8aeb22020054287968f8e80100b409c1208b29d15e393ffd03710900891a291d40930a09805228212a9b014144b9024142f9a08301d12d669694a0035a7827000014')),
    (0x4857a1c, bytes.fromhex('3f280071a80000545f2800716800005408c0218b02d11e39c0035fd6')),
    (0x48578f0, bytes.fromhex('08c0218b08d15e391ffd03712800881a001d0013c0035fd6')),
    (0x22cc610, bytes.fromhex('ba0100b468d25e391ffd0371e803881a081d409309098052097d299b896a69b8a9000034ea830d915a7928f8eac30c91497928b8b60100b468d65e391ffd037108159f1a081d409309098052097d299b896a69b8a9000034ea830d91567928f8eac30c91497928b8')),
    (0x484fd7c, bytes.fromhex('ff0301d1f44f02a9fd7b03a9fdc30091f30300aae82b009162eeff97e82b403968d21e39600211910100805259a60494e833403968d61e39600211912100805254a60494e83b403968da1e3960021191410080524fa60494e843403968de1e3960021191610080524aa60494e84b403968e21e39600211918100805245a60494e853403968e61e3960021191a100805240a60494e85b403968ea1e3960021191c10080523ba60494e863403968ee1e3960021191e100805236a60494e86b403968f21e39600211910101805231a60494e873403968f61e3960021191210180522ca60494e87b403968fa1e396002119141018052fd7b43a9f44f42a9ff03019124a60414')),
    (0x2ece150, bytes.fromhex('fa0300aaa83e01f013c940f9e00318aae1031aaa3dfcff97f40300aa')),
    (0x2ece234, bytes.fromhex('35010034080340f9086943f9e00318aa00013fd6800000b4e10300aae00314aae3f6cf97')),
    (0x22cbe10, bytes.fromhex('083f8452086868381f0900f108060054f60300aa0af450f909f050f94a0109cb1f0d8aeb42050054337968f8130500b4f70301aaf583109174021191e00314aa01008012020080d2030080520db39a94e00314aa210080520200801206b79a94bf0317f800e4006fa0833aada08339ada003923ca0c2813ce00f813de00b813dff0b02f9e0831fade0831eade0f3803d3aa001f0c80262b9')),
    (0x22cc678, bytes.fromhex('d90100b468da5e39490080521ffd03712801881a081d409309098052097d299b896a69b8a9000034ea830d91597928f8eac30c91497928b8cd0100b468de5e39690080521ffd03712801881a081d409309098052097d299b896a69b8a9000034ea830d914d7928f8eac30c91497928b8db0100b468e25e39890080521ffd03712801881a081d409309098052097d299b896a69b8a9000034ea830d915b7928f8eac30c91497928b8dc0100b468e65e39a90080521ffd03712801881a081d409309098052097d299b896a69b8a9000034ea830d915c7928f8eac30c91497928b8ce0100b468ea5e39c90080521ffd03712801881a081d409309098052097d299b896a69b8a9000034ea830d914e7928f8eac30c91497928b8cf0100b468ee5e39e90080521ffd03712801881a081d409309098052097d299b896a69b8a9000034ea830d914f7928f8eac30c91497928b8d70100b468f25e39090180521ffd03712801881a081d409309098052097d299b896a69b8a9000034ea830d91577928f8eac30c91497928b8e8c30c91d80100b469f65e392a0180523ffd03714901891a291d40930a0980522a7d2a9b8a6a6ab8aa000034eb830d91787929f8ebc30c916a7929b80aa1009109910091ea2700a90a81009109710091ea2701a90a61009109510091ea2702a90a41009109310091e9ab0ca90921009108110091e8a70ba9c00100b468fa5e39490180521ffd03712801881a081d409309098052097d299b896a69b8a9000034ea830d91407928f8eac30c91497928b8')),
)
