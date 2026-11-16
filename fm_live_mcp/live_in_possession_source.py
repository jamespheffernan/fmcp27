"""Owned editable XI to stored in-possession positions; no OOP pairing claimed."""
from collections import Counter
import struct

from . import (live_team_sheet_source as selection, prepared_tactics_source as tactics,
               prepared_tactics_fields as fields, prepared_tactic_roles as roles)


def verify_native(read, base):
    for rva, raw in NATIVE_SPANS:
        if read(base+rva,len(raw)) != raw:
            raise ValueError(f'In-possession pairing native source changed at RVA {rva:#x}')


def _result(sheet):
    return {'team':sheet['team'],'source_state':sheet['source_state'],
        'unavailable_reason':sheet.get('unavailable_reason'),
        'phase':'in_possession','source':'existing_human_tactic_edit_session_working_payload',
        'assignments':None,'assignment_count':None,'named_assignment_count':None,
        'complete_named_assignments':False,'tactic':None,
        'selected_creator_index':None,'creator_count':None,
        'selection_boundary_state':sheet['role_boundary_state'],
        'formation_boundary_state':sheet.get('formation_boundary_state'),
        'duplicate_person_indices':sheet.get('duplicate_person_indices'),
        'duplicate_position_masks':None,'duplicate_role_encodings':None,
        'out_of_possession_pairing_state':'not_established',
        'foreground_screen_state':'not_observed','match_submission_state':'not_established',
        'effective_player_role_overrides_state':'not_established'}


def _assignments(slots, positions, base_roles):
    if len(slots)!=11 or len(positions)!=11 or len(base_roles)!=11:
        raise ValueError('In-possession pairing requires exactly eleven ordered slots')
    if [s['slot_index']for s in slots]!=list(range(11)) or [p['position_index']for p in positions]!=list(range(11)):
        raise ValueError('In-possession slot order changed or duplicated')
    counts=Counter(s['person']['database_index']for s in slots if s['person'] is not None)
    out=[]
    for slot, position, role in zip(slots,positions,base_roles,strict=True):
        person=slot['person']
        state=('empty_slot'if person is None else 'ambiguous_duplicate_person'
               if counts[person['database_index']]>1 else 'paired_by_native_slot')
        out.append({'slot_index':slot['slot_index'],'selection_state':slot['state'],
            'person':person,'pairing_state':state,'position':position,'stored_base_role':role,
            'named_assignment_available':state=='paired_by_native_slot'and position['state']=='named'
                and role['name_state']=='named'})
    return out


def inspect(read,base,coach):
    """Preserve the IP-only public view over the shared owned source."""
    result, _ = _inspect_context(read,base,coach)
    return result


def _inspect_context(read,base,coach):
    """Return the public IP view and private selected creator for phase readers."""
    verify_native(read,base)
    sheet=selection.inspect(read,base,coach)
    result=_result(sheet)
    if sheet['source_state']!='available':
        return result, None
    if sheet.get('formation_boundary_state') != 'native_first_11':
        result.update(source_state='partial',unavailable_reason='selection_boundary_unresolved',
                      ordered_selection=sheet['slots'])
        return result, None
    team,human=tactics._team_and_human(read,base,coach)
    if team!=sheet['team']:
        raise ValueError('In-possession managed TEAM changed')
    session,reason=selection._existing_session(read,base,human,coach['team_address'],team['database_index'])
    if reason:
        raise ValueError('In-possession edit-session ownership changed')
    payload=session+0x11E0
    creators=tactics._vector(read,payload+0x1000,tactics.SLOT_LIMIT)
    selected=read(payload+0x1018,1)[0]
    result.update(selected_creator_index=selected,creator_count=len(creators))
    if selected>2 or selected>=len(creators) or not creators[selected]:
        reason=('creator_selector_unmapped'if selected>2 else 'selected_creator_beyond_count'
                if selected>=len(creators) else 'selected_creator_null')
        result.update(source_state='partial',unavailable_reason=reason,
                      ordered_selection=sheet['slots'][:11])
        return result, None
    creator=creators[selected]
    fields._address(creator,0x7C0)
    fields.verify_native(read,base)
    roles.verify_native(read,base)
    name,name_state=fields._name(read,creator)
    positions=[]
    base_roles=[]
    for index in range(11):
        mask=struct.unpack('<I',read(creator+0x120+index*0x48,4))[0]
        label=fields.POSITION_NAMES.get(mask)
        positions.append({'position_index':index,'native_mask':mask,'name':label,
                          'state':'named'if label is not None else 'unmapped_native_mask'})
        base_roles.append(roles.decode(read,creator,'in_possession',index))
    assignments=_assignments(sheet['slots'][:11],positions,base_roles)
    masks=Counter(p['native_mask']for p in positions)
    role_counts=Counter(r['raw_encoding']for r in base_roles)
    named=sum(a['named_assignment_available']for a in assignments)
    result.update(source_state='available'if named==11 else 'partial',unavailable_reason=None,
        assignments=assignments,assignment_count=11,named_assignment_count=named,
        complete_named_assignments=named==11,tactic={'name':name,'name_state':name_state},
        duplicate_position_masks=sorted(m for m,c in masks.items()if c>1),
        duplicate_role_encodings=sorted(r for r,c in role_counts.items()if c>1))
    return result, creator


# Build-pinned player lookup, working payload builder, IP/OOP phase guards.
NATIVE_SPANS = (
    (0x23928e8, bytes.fromhex('880340f908815ef8c16a68b808048252a002088bc37083941f04003100184a7acc02005408038252a86a68381f0900f148020054aa0648f9a90248f94a0109cb1f0d8aeba2010054287968f8680100b4090980520820299b012141b902b140f9a08301d17f649694')),
    (0x22c8218, bytes.fromhex('e84340f9e00308aaf67740f9080200b5e83740f9086140391f0900f128010054e95740f92a0548f9290148f94a0109cb1f0d8aeb62000054207968f8800000b5e05f40f9e1031aaaa6272294f59f00b9fc5f00f9150080521c008052801400b4ea7f40b95f0500712b140054150080521c0080521b0080d208048252e95740f93a01088b08800491e84b00f9f9030a2af40315aa570b1b8be00317aae17b40f9eb382294f30300aa')),
    (0x22c8344, bytes.fromhex('7f2b00f1f50314aa28040054e84b40f90b09805273230b9b680240b9a91e4093aa8303d1487929b8680240b96a124039ec5740918c81219135312b9baa120039a80200b9')),
    (0x2e50df0, bytes.fromhex('090980522820299b09810491080111915f0000712801889a000140b9c0035fd6')),
    (0x2e50e28, bytes.fromhex('080980522808289b09810491080111917f0000712801889a000140b9')),
    (0x446ec08, bytes.fromhex('c100f837080040b91f01016ba1000054080080527f000014e81f80527d000014080440b91f01016b610000542800805278000014080840b91f01016b610000544800805273000014080c40b91f01016b61000054680080526e000014081040b91f01016b610000548800805269000014081440b91f01016b61000054a800805264000014081840b91f01016b61000054c80080525f000014081c40b91f01016b61000054e80080525a000014082040b91f01016b610000540801805255000014082440b91f01016b610000542801805250000014082840b91f01016b61000054480180524b000014082c40b91f01016b610000546801805246000014083040b91f01016b610000548801805241000014083440b91f01016b61000054a80180523c000014083840b91f01016b61000054c801805237000014083c40b91f01016b61000054e801805232000014084040b91f01016b61000054080280522d000014084440b91f01016b610000542802805228000014084840b91f01016b610000544802805223000014084c40b91f01016b61000054680280521e000014085040b91f01016b610000548802805219000014085440b91f01016b61000054a802805214000014085840b91f01016b61000054c80280520f000014085c40b91f01016b61000054e80280520a000014086040b91f01016b610000540803805205000014086440b91f01016b2803805208019f5a001d0013c0035fd6')),
)
