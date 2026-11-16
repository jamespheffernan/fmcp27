"""Independent real-memory public acceptance for optional tactic detail groups."""
import asyncio
from copy import deepcopy
import struct

import pytest

from fm_live_mcp import prepared_tactic_formations as formations
from fm_live_mcp import prepared_tactic_instructions as instructions
from fm_live_mcp import prepared_tactics_fields as fields, prepared_tactics_source as source
from fm_live_mcp.bridge import BridgeError
from prepared_tactic_formation_fixture import add_formation_context
from prepared_tactic_instruction_fixture import add_instruction_context
from prepared_tactics_fixture import prepared_tactics_memory
from test_bridge import bridge
from test_database import bind, database_memory
from test_players import memory
from test_teams import team_memory
from test_world import world_memory


CANONICAL = [0x1,0x4,0x200010,0x10,0x100010,0x8,0x20,0x200080,0x80,0x100080,
             0x40,0x100,0x200400,0x400,0x100400,0x200,0x800,0x202000,0x2000,
             0x102000,0x1000,0x8000,0x204000,0x4000,0x104000,0x10000]
CURRENT_CODES = [-15,-13,-12,-10,-9,-7,-5,2,4,6,9]
OLD_GAPS = ['current_match_assignment','official_formation','roles','instructions',
            'familiarity','player_assignments']


@pytest.fixture
def composed(bridge, monkeypatch, prepared_tactics_memory):
    m=prepared_tactics_memory
    add_formation_context(m);add_instruction_context(m)
    bind(bridge,monkeypatch,m)
    bridge.player_refs['preexisting']={'identity':'unrelated'}
    return m


def query(bridge, **kwargs):
    return bridge.get_managed_tactics(bridge.session, **kwargs)


def write_masks(m, masks, *, slot=0, offset=0x120):
    for index,mask in enumerate(masks):
        m['put'](m['creator_addresses'][slot]+offset+index*0x48,struct.pack('<I',mask))


def clone_without_observed(result):
    return {k:v for k,v in result.items() if k!='observed_at'}


@pytest.mark.parametrize('formation,instruction',[(False,False),(True,False),(False,True),(True,True)])
def test_real_composed_selective_flags_exact_states(bridge, composed, formation, instruction):
    before=deepcopy(bridge.player_refs)
    result=query(bridge,include_formation=formation,include_instructions=instruction)
    assert result['source_state']=='available' and result['slot_count']==len(result['slots'])==3
    assert result['primary_trained_tactic']['slot_index']==0
    for index,slot in enumerate(result['slots']):
        for phase in slot['phases'].values():
            assert phase['formation']==({'native_id':29,'state':'recognized','name':'4-2-3-1 DM AM Wide'} if formation else None)
            assert len(phase['positions'])==11 and phase['positions'][0]['name']=='GK'
        if instruction:
            assert slot['mentality']=={'native_code':[3,5,6][index],
                'name':['Cautious','Positive','Attacking'][index],'state':'named'}
            settings=slot['team_instructions']
            assert settings['scope']=='shared_stored_options'
            assert settings['selected_count']==[12,14,14][index]
            assert [r['native_option_id'] for r in settings['selected_options']]==list(composed['instruction_samples'][index][1])
        else:
            assert 'mentality' not in slot and 'team_instructions' not in slot
    expected=list(OLD_GAPS)
    if formation: expected[expected.index('official_formation')]='localized_formation_name'
    if instruction:
        at=expected.index('instructions');expected[at:at+1]=['instruction_phase_applicability','effective_instructions']
    assert result['unavailable_fields']==expected
    assert bridge.player_refs==before


def test_default_and_explicit_false_payloads_are_identical(bridge, composed):
    plain=query(bridge)
    explicit=query(bridge,include_formation=False,include_instructions=False)
    assert clone_without_observed(plain)==clone_without_observed(explicit)
    assert plain['unavailable_fields']==OLD_GAPS


@pytest.mark.parametrize('flag',['include_formation','include_instructions'])
@pytest.mark.parametrize('value',[None,0,1,'true','false',[],{}])
def test_flags_strict_before_memory(bridge,monkeypatch,flag,value):
    monkeypatch.setattr(bridge,'_player_layout',lambda *a:pytest.fail('Invalid flag read native memory'))
    with pytest.raises(BridgeError,match='bool'):
        query(bridge,**{flag:value})


@pytest.mark.parametrize('resource',['formation','instruction'])
def test_disabled_resource_corruption_is_not_read(bridge,composed,resource):
    module=formations if resource=='formation' else instructions
    composed['put'](composed['base']+module.NATIVE_SPANS[0][0],b'\0')
    other={'include_instructions':True} if resource=='formation' else {'include_formation':True}
    result=query(bridge,**other)
    assert result['slot_count']==3
    with pytest.raises(BridgeError):
        query(bridge,include_formation=True,include_instructions=True)


@pytest.mark.parametrize('kind',['unavailable','empty','nulls'])
def test_no_nonnull_creators_skip_optional_resources(bridge,composed,kind):
    m=composed
    for module in (formations,instructions): m['put'](m['base']+module.NATIVE_SPANS[0][0],b'\0')
    if kind=='unavailable':m['q'](m['base']+source.MANAGER_ROOT,0)
    else:m['vec'](m['tactics_payload']+0x1000,[] if kind=='empty' else [0,0])
    result=query(bridge,include_formation=True,include_instructions=True)
    if kind=='unavailable':
        assert result['source_state']=='unavailable' and result['slot_count'] is None and result['slots']==[]
    else:
        assert result['source_state']=='available' and result['complete_stored_slots'] is True
        assert result['nonnull_slot_count']==0
        assert result['slot_count']==(0 if kind=='empty' else 2)
        for slot in result['slots']:
            assert slot['phases'] is slot['mentality'] is slot['team_instructions'] is None


def test_requested_contexts_verify_once_but_decode_each_owned_slot(bridge,monkeypatch,composed):
    calls={'formation_load':0,'instructions_verify':0,'instructions_decode':0}
    for module,name,label in [(formations,'load','formation_load'),(instructions,'verify_native','instructions_verify'),
                               (instructions,'decode','instructions_decode')]:
        original=getattr(module,name)
        def wrapper(*args,_original=original,_label=label,**kwargs):
            calls[_label]+=1
            return _original(*args,**kwargs)
        monkeypatch.setattr(module,name,wrapper)
    result=query(bridge,include_formation=True,include_instructions=True)
    assert result['slots'][0]['phases']['in_possession']['formation']['native_id']==29
    assert result['slots'][2]['mentality']['name']=='Attacking'
    assert calls=={'formation_load':1,'instructions_verify':1,'instructions_decode':3}


@pytest.mark.parametrize('guard',[formations.METADATA_GUARD_RVA,formations.TEMPLATE_GUARD_RVA])
def test_uninitialized_formation_keeps_other_details_available(bridge,composed,guard):
    m=composed;m['put'](m['base']+guard,b'\0')
    # The invalid missing context is not read past the known-uninitialized guard.
    m['put'](m['base']+formations.POLICY_RVA,bytes(24))
    result=query(bridge,include_formation=True,include_instructions=True)
    for slot in result['slots']:
        assert slot['mentality']['state']=='named'
        for phase in slot['phases'].values():
            assert phase['formation']=={'native_id':None,'state':'unavailable_uninitialized_templates','name':None}


@pytest.mark.parametrize('mask',CANONICAL)
def test_all_26_canonical_masks_through_composed_reader(bridge,composed,mask):
    # Replace the onlyGK: everyother canonical code removesGK, so none of the64
    # frozen native templates can match; this is independent of converter code.
    composed['put'](composed['creator_addresses'][0]+0x120,struct.pack('<I',mask))
    phase=query(bridge,include_formation=True)['slots'][0]['phases']['in_possession']
    assert phase['formation']=={'native_id':29 if mask==1 else 0,
        'state':'recognized' if mask==1 else 'no_eligible_template_match','name':'4-2-3-1 DM AM Wide' if mask==1 else None}


@pytest.mark.parametrize('mask,expected',[(0,0),(2,29),(0x80000000,29),(0xFFFFFFFF,29)])
def test_zero_unknown_alias_and_native_no_match_are_distinct(bridge,composed,mask,expected):
    composed['put'](composed['creator_addresses'][0]+0x120,struct.pack('<I',mask))
    phase=query(bridge,include_formation=True)['slots'][0]['phases']['in_possession']
    assert phase['formation']['native_id']==expected
    assert phase['positions'][0]['native_mask']==mask
    assert phase['positions'][0]['name'] is None and phase['positions'][0]['state']=='unmapped_native_mask'


@pytest.mark.parametrize('mode',['null_empty','allocated_empty','all_zero','short','only29'])
def test_empty_short_and_nonempty_policy_semantics(bridge,composed,mode):
    flags={'null_empty':None,'allocated_empty':b'','all_zero':bytes(70),
           'short':bytes([1]*29),'only29':bytes([0]*29+[1])}[mode]
    composed['formation_set_policy'](flags)
    result=query(bridge,include_formation=True)
    expected=0 if mode in ('all_zero','short') else 29
    assert result['slots'][0]['phases']['in_possession']['formation']['native_id']==expected


def test_first_eligible_candidate_and_missing_id_fallback3(bridge,composed):
    m=composed
    m['formation_set_template'](3,CURRENT_CODES);m['formation_set_template'](4,CURRENT_CODES)
    m['formation_set_policy'](bytes(1 if i in (3,4) else 0 for i in range(70)))
    assert query(bridge,include_formation=True)['slots'][0]['phases']['in_possession']['formation']['native_id']==3
    missing=min(set(range(1,70))-set(m['formation_identifiers']))
    m['formation_set_policy'](bytes(1 if i==missing else 0 for i in range(70)))
    assert query(bridge,include_formation=True)['slots'][0]['phases']['in_possession']['formation']['native_id']==missing


@pytest.mark.parametrize('code,name',[(1,'Very Defensive'),(2,'Defensive'),(3,'Cautious'),(4,'Balanced'),
    (5,'Positive'),(6,'Attacking'),(7,'Very Attacking'),(0,None),(-1,None),(8,None),(127,None),(-128,None)])
def test_signed_mentality_exact_labels_and_no_fallback(bridge,composed,code,name):
    m=composed;m['set_instruction_details'](m['creator_addresses'][0],code,())
    slot=query(bridge,include_instructions=True)['slots'][0]
    assert slot['mentality']=={'native_code':code,'name':name,'state':'named' if name else 'unmapped_native_code'}
    assert slot['team_instructions']['selected_count']==0


@pytest.mark.parametrize('bit,label',[(0,None),(1,'Much More Direct Passing'),(63,'Low Block'),(64,None),
    (65,'Trigger Press Much More Often'),(74,None),(75,None),(83,'Invite Crosses'),(84,None),(127,None)])
def test_instruction_word_boundaries_serialized_domain_and_no_text(bridge,composed,bit,label):
    m=composed;m['set_instruction_details'](m['creator_addresses'][0],5,[bit])
    settings=query(bridge,include_instructions=True)['slots'][0]['team_instructions']
    expected=[] if bit==0 or bit>83 else [{'native_option_id':bit,'name':label,
        'state':'named' if label is not None else 'no_native_label'}]
    assert settings=={'scope':'shared_stored_options','selected_count':len(expected),
        'selected_options':expected,'unmapped_serialized_bits':[0] if bit==0 else []}


def test_conflicting_stored_flags_preserved_in_ascending_order(bridge,composed):
    m=composed;m['set_instruction_details'](m['creator_addresses'][0],4,[83,4,1,3,2,64,75,74,0,127])
    settings=query(bridge,include_instructions=True)['slots'][0]['team_instructions']
    assert [v['native_option_id'] for v in settings['selected_options']]==[1,2,3,4,64,74,75,83]
    assert settings['selected_count']==8 and settings['unmapped_serialized_bits']==[0]


@pytest.mark.parametrize('fault',['native_formation','native_instruction','policy_order','policy_budget',
    'template_vector','metadata_duplicate','missing_template3','template_code','inverse'])
def test_malformed_requested_resources_reject_whole_result(bridge,composed,fault):
    m=composed;base=m['base']
    if fault=='native_formation':m['put'](base+formations.NATIVE_SPANS[0][0],b'\0')
    if fault=='native_instruction':m['put'](base+instructions.NATIVE_SPANS[0][0],b'\0')
    if fault=='policy_order':m['put'](base+formations.POLICY_RVA,struct.pack('<QQQ',0x5000,0x4000,0x5000))
    if fault=='policy_budget':m['put'](base+formations.POLICY_RVA,struct.pack('<QQQ',0x5000,0x5001,0x7000))
    if fault=='template_vector':m['q'](base+formations.TEMPLATE_VECTOR_RVA,0)
    if fault=='metadata_duplicate':m['put'](m['formation_metadata']+24,bytes([m['formation_identifiers'][0]]))
    if fault=='missing_template3':
        idx=m['formation_identifiers'].index(3);m['put'](m['formation_metadata']+24*idx,b'\x00')
    if fault=='template_code':m['put'](m['formation_templates'],struct.pack('<H',(-14)&63))
    if fault=='inverse':m['put'](base+formations.INVERSE_RVA,b'\0')
    before=deepcopy(bridge.player_refs)
    with pytest.raises(BridgeError):query(bridge,include_formation=True,include_instructions=True)
    assert bridge.player_refs==before


@pytest.mark.parametrize('target',['policy','template','metadata','guard','instruction','mentality','selector','mask'])
def test_late_optional_resource_and_fields_drift_fail(bridge,monkeypatch,composed,target):
    m=composed;original=instructions.decode;calls=[]
    def changing(*args,**kwargs):
        result=original(*args,**kwargs);calls.append(args[1])
        if len(calls)==3:
            address={'policy':m['formation_policy_address']+29,'template':m['formation_templates'],
                'metadata':m['formation_metadata'],'guard':m['base']+formations.METADATA_GUARD_RVA,
                'instruction':m['creator_addresses'][0]+0xE0,'mentality':m['creator_addresses'][0]+0x105,
                'selector':m['tactics_payload']+0x1018,'mask':m['creator_addresses'][0]+0x120}[target]
            byte=m['read'](address,1)[0];m['put'](address,bytes([byte^1]))
        return result
    monkeypatch.setattr(instructions,'decode',changing)
    before=deepcopy(bridge.player_refs)
    with pytest.raises(BridgeError,match='changed|rejected'):query(bridge,include_formation=True,include_instructions=True)
    assert len(calls)==3 and bridge.player_refs==before


def test_mcp_flags_optional_strict_boolean_defaults_and_read():
    from fm_live_mcp.server import mcp
    tool=next(t for t in asyncio.run(mcp.list_tools()) if t.name=='fm_get_managed_tactics')
    assert set(tool.inputSchema['required'])=={'session_id'}
    assert set(tool.inputSchema['properties'])=={'session_id','coach_name','include_formation','include_instructions','include_roles'}
    for flag in ('include_formation','include_instructions'):
        assert tool.inputSchema['properties'][flag]['type']=='boolean'
        assert tool.inputSchema['properties'][flag]['default'] is False
    assert tool.annotations.readOnlyHint is True and tool.annotations.destructiveHint is False
    assert tool.annotations.openWorldHint is False
