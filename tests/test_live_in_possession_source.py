from copy import deepcopy
import struct

import pytest

from fm_live_mcp import live_in_possession_source as source, world
from test_live_team_sheet_source import Memory


@pytest.fixture
def context(monkeypatch):
    memory=Memory()
    base,session,creator=0x100000000,0x10000,0x40000
    for module in (source,source.fields,source.roles):
        for rva,raw in module.NATIVE_SPANS:
            memory.put(base+rva,raw)
    team={'database_index':545,'native_id':688}
    slots=[{'slot_index':i,'state':'selected_person','person':{'database_index':i,
             'native_id':100+i,'secondary_id':0,'name':f'Player {i}'}}for i in range(26)]
    sheet={'team':team,'source_state':'available','unavailable_reason':None,
        'role_boundary_state':'native_first_11_and_stored_selected_end',
        'formation_boundary_state':'native_first_11',
        'duplicate_person_indices':[],'slots':slots}
    def selected(read,*args):
        read(session+0x2200,104)
        return deepcopy(sheet)
    monkeypatch.setattr(source.selection,'inspect',selected)
    monkeypatch.setattr(source.tactics,'_team_and_human',lambda *args:(team,0x30000))
    monkeypatch.setattr(source.selection,'_existing_session',lambda *args:(session,None))
    payload=session+0x11e0
    memory.pack(payload+0x1000,'<QQQ',0x20000,0x20008,0x20008)
    memory.pack(0x20000,'<Q',creator)
    memory.put(payload+0x1018,b'\0')
    memory.pack(creator+0x790,'<Q',0x80000)
    memory.put(0x80000,struct.pack('<I',4)+b'Name\0')
    masks=[1,4,0x200010,0x100010,8,0x200080,0x100080,0x800,0x2000,0x1000,0x4000]
    for i,mask in enumerate(masks):
        memory.pack(creator+0x120+i*0x48,'<I',mask)
        memory.pack(creator+0x160+i*0x48,'<Q',1)
    coach={'team_address':0x90000}
    return dict(memory=memory,base=base,session=session,creator=creator,payload=payload,
                sheet=sheet,coach=coach)


def inspect(c):
    read=world.ReadSet(c['memory'].read)
    result=source.inspect(read,c['base'],c['coach'])
    read.verify()
    return result


def test_exact_eleven_pairings_and_repeated_roles_preserved(context):
    result=inspect(context)
    assert result['source_state']=='available' and result['complete_named_assignments']
    assert [r['slot_index']for r in result['assignments']]==list(range(11))
    assert [r['person']['database_index']for r in result['assignments']]==list(range(11))
    assert result['assignments'][0]['position']['name']=='GK'
    assert result['assignments'][10]['position']['name']=='ST(C)'
    assert result['duplicate_role_encodings']==['0x0000000000000001']
    assert result['out_of_possession_pairing_state']=='not_established'
    assert result['foreground_screen_state']=='not_observed'


def test_no_oop_position_reads(context):
    reads=[]
    def read(address,size):
        reads.append((address,size))
        return context['memory'].read(address,size)
    source.inspect(read,context['base'],context['coach'])
    low=context['creator']+0x440
    high=context['creator']+0x750
    assert not any(address<high and address+size>low for address,size in reads)


@pytest.mark.parametrize('index',[0,10])
def test_empty_slot_retains_position_and_is_not_a_player(context,index):
    context['sheet']['slots'][index].update(person=None,state='empty_slot')
    r=inspect(context)
    assert r['source_state']=='partial'
    assert r['assignments'][index]['person'] is None
    assert r['assignments'][index]['pairing_state']=='empty_slot'
    assert r['assignment_count']==11 and r['named_assignment_count']==10


def test_duplicate_person_is_not_certified_twice(context):
    context['sheet']['slots'][1]['person']=context['sheet']['slots'][0]['person']
    result=inspect(context)
    assert result['source_state']=='partial'
    assert [r['pairing_state']for r in result['assignments'][:2]]==['ambiguous_duplicate_person']*2
    assert result['named_assignment_count']==9


def test_unknown_position_mask_retained_without_guess(context):
    context['memory'].pack(context['creator']+0x120,'<I',0xffffffff)
    row=inspect(context)['assignments'][0]
    assert row['position']=={'position_index':0,'native_mask':0xffffffff,'name':None,'state':'unmapped_native_mask'}
    assert not row['named_assignment_available']


def test_unknown_role_retains_raw_and_null_label(context):
    context['memory'].pack(context['creator']+0x160,'<Q',0)
    result=inspect(context)
    assert result['source_state']=='partial' and result['named_assignment_count']==10
    role=result['assignments'][0]['stored_base_role']
    assert role['compiled_english_name'] is None
    assert role['name_state']=='no_matching_native_branch'


@pytest.mark.parametrize('selector,count,pointer,reason',[(3,1,True,'creator_selector_unmapped'),
    (1,1,True,'selected_creator_beyond_count'),(0,1,False,'selected_creator_null')])
def test_missing_selected_creator_is_partial_not_empty(context,selector,count,pointer,reason):
    context['memory'].put(context['payload']+0x1018,bytes([selector]))
    if not pointer:context['memory'].pack(0x20000,'<Q',0)
    r=inspect(context)
    assert r['source_state']=='partial' and r['unavailable_reason']==reason
    assert r['assignments'] is None and len(r['ordered_selection'])==11


def test_unresolved_selection_boundary_preserves_selection(context):
    context['sheet']['role_boundary_state']='stored_boundary_unmapped'
    context['sheet']['formation_boundary_state']='unresolved'
    r=inspect(context)
    assert r['source_state']=='partial' and r['assignments'] is None
    assert len(r['ordered_selection'])==26


def test_proved_formation_boundary_does_not_require_bench_extent(context):
    context['sheet'].update(role_boundary_state='stored_boundary_unmapped',
                            formation_boundary_state='native_first_11')
    r=inspect(context)
    assert r['source_state']=='available'
    assert r['formation_boundary_state']=='native_first_11'
    assert r['selection_boundary_state']=='stored_boundary_unmapped'
    assert len(r['assignments'])==11
    assert r['match_submission_state']=='not_established'


def test_mapped_bench_boundary_cannot_substitute_for_unproved_formation(context):
    context['sheet'].pop('formation_boundary_state')
    r=inspect(context)
    assert r['source_state']=='partial' and r['assignments'] is None


def test_missing_existing_session_is_unavailable(context):
    context['sheet'].update(source_state='unavailable',unavailable_reason='missing',slots=None)
    r=inspect(context)
    assert r['source_state']=='unavailable' and r['assignments'] is None
    assert r['assignment_count'] is None


def test_team_context_change_rejected(context,monkeypatch):
    monkeypatch.setattr(source.tactics,'_team_and_human',lambda *args:({'database_index':546},0x30000))
    with pytest.raises(ValueError,match='TEAM changed'):inspect(context)


def test_duplicate_or_disordered_slot_rejected(context):
    context['sheet']['slots'][1]['slot_index']=0
    with pytest.raises(ValueError,match='slot order'):inspect(context)


def test_each_native_guard_is_required(context):
    for rva,raw in source.NATIVE_SPANS:
        context['memory'].put(context['base']+rva,bytes([raw[0]^1]))
        with pytest.raises(ValueError,match='native source changed'):inspect(context)
        context['memory'].put(context['base']+rva,raw)


def test_changed_selection_detected_before_publication(context):
    read=world.ReadSet(context['memory'].read)
    source.inspect(read,context['base'],context['coach'])
    context['memory'].put(context['session']+0x2200,b'X')
    with pytest.raises(ValueError):read.verify()


def test_unknown_phase_never_selected_and_private_addresses_not_exposed(context):
    import json
    r=inspect(context)
    assert r['phase']=='in_possession'
    public=json.dumps(r)
    for key in ('creator_address','manager_address','team_address','session_address'):
        assert key not in public
