"""Independent composed public acceptance for source-qualified role and shape names."""
import asyncio
from copy import deepcopy
import itertools
import json
from pathlib import Path
import struct

import pytest

from fm_live_mcp import prepared_tactic_roles as roles, prepared_tactic_formations as formations
from fm_live_mcp import prepared_tactics_source as source
from fm_live_mcp.bridge import BridgeError
from prepared_tactic_formation_fixture import add_formation_context
from prepared_tactic_instruction_fixture import add_instruction_context
from prepared_tactics_fixture import prepared_tactics_memory
from test_bridge import bridge
from test_database import bind, database_memory
from test_players import memory
from test_teams import team_memory
from test_world import world_memory

ROOT = Path(__file__).resolve().parents[1]
FROZEN = json.loads((ROOT/'evidence/batches/role-and-formation-names-13/acceptance/role-name-oracle.json').read_text())
# Internal flag bits of the stored role word (roles.DUTY_BRANCHES): fixed by the role, published
# only inside raw_encoding.
FLAG_BITS = [21,25,26,22,23,34]
ROLE_KEYS = {'raw_encoding','compiled_english_name','native_resource_key','name_state'}
PHASES = {'in_possession':0x120,'out_of_possession':0x440}


@pytest.fixture
def composed(bridge,monkeypatch,prepared_tactics_memory):
    m=prepared_tactics_memory
    add_formation_context(m);add_instruction_context(m)
    for rva,raw in roles.NATIVE_SPANS:m['put'](m['base']+rva,raw)
    for slot,creator in zip(FROZEN['slots'],m['creator_addresses'],strict=True):
        for phase,offset in PHASES.items():
            for row in slot['phases'][phase]['roles']:
                m['q'](creator+offset+0x48*row['position_index']+0x40,row['native_base_role_encoding'])
    bind(bridge,monkeypatch,m)
    bridge.player_refs['preexisting']={'identity':'untouched'}
    return m


def query(bridge,**kwargs):return bridge.get_managed_tactics(bridge.session,**kwargs)


def expected_role(row):
    raw=row['native_base_role_encoding']
    return {'raw_encoding':f'0x{raw:016x}','compiled_english_name':row['compiled_english_name'],
        'native_resource_key':row['compiled_label_key'],
        'name_state':'named' if row['compiled_english_name'] else 'no_matching_native_branch'}


@pytest.mark.parametrize('formation,instruction,role',list(itertools.product((False,True),repeat=3)))
def test_all_flag_combinations_real_ownership_and_66_roles(bridge,composed,formation,instruction,role):
    before=deepcopy(bridge.player_refs)
    result=query(bridge,include_formation=formation,include_instructions=instruction,include_roles=role)
    assert result['slot_count']==3 and result['complete_stored_slots'] is True
    assert result['primary_trained_tactic']['slot_index']==0
    for slot,frozen in zip(result['slots'],FROZEN['slots'],strict=True):
        for phase,phase_row in slot['phases'].items():
            assert phase_row['formation']==({'native_id':29,'state':'recognized','name':'4-2-3-1 DM AM Wide'} if formation else None)
            assert len(phase_row['positions'])==11
            for pos,want in zip(phase_row['positions'],frozen['phases'][phase]['roles'],strict=True):
                assert ('base_role' in pos) is role
                if role:assert pos['base_role']==expected_role(want)
        assert ('mentality' in slot) is instruction
        assert ('team_instructions' in slot) is instruction
    missing=['current_match_assignment','localized_formation_name' if formation else 'official_formation']
    missing+=['localized_role_name','effective_player_role'] if role else ['roles']
    missing+=['instruction_phase_applicability','effective_instructions'] if instruction else ['instructions']
    assert result['unavailable_fields']==missing+['familiarity','player_assignments']
    assert bridge.player_refs==before


def test_default_and_three_explicit_false_flags_equal(bridge,composed):
    left=query(bridge);right=query(bridge,include_formation=False,include_instructions=False,include_roles=False)
    for row in (left,right):row.pop('observed_at')
    assert left==right


@pytest.mark.parametrize('value',[None,0,1,'true','false',[],{}])
def test_role_flag_rejected_before_source_read(bridge,monkeypatch,value):
    monkeypatch.setattr(bridge,'_player_layout',lambda *a:pytest.fail('Invalid flag read source'))
    with pytest.raises(BridgeError,match='bool'):query(bridge,include_roles=value)


@pytest.mark.parametrize('phase,raw,name,key',[
    ('in_possession',0,None,None),('out_of_possession',1<<63,None,None),
    ('in_possession',8,'Wing-Back',688080),('out_of_possession',8,'Centre-Back',688071),
    ('in_possession',(1<<52)|8,'Inside Full-Back',688107),
    ('in_possession',1<<20,None,None),('out_of_possession',1<<24,None,None),
    ('in_possession',(1<<64)-1,'Goalkeeper',688068),
])
def test_phase_masks_priority_unknown_and_full_u64_precision(bridge,composed,phase,raw,name,key):
    m=composed;m['q'](m['creator_addresses'][0]+PHASES[phase]+0x40,raw)
    role=query(bridge,include_roles=True)['slots'][0]['phases'][phase]['positions'][0]['base_role']
    assert role['raw_encoding']==f'0x{raw:016x}'
    assert role['compiled_english_name']==name and role['native_resource_key']==key
    assert role['name_state']==('named' if name else 'no_matching_native_branch')


@pytest.mark.parametrize('bits',[0]+[1<<b for b in FLAG_BITS]+[
    (1<<21)|(1<<23),(1<<25)|(1<<22),(1<<26)|(1<<34)])
def test_internal_flag_bits_are_published_only_inside_the_stored_word(bridge,composed,bits):
    assert FLAG_BITS==[b for b,_key,_text in roles.DUTY_BRANCHES]
    m=composed;m['q'](m['creator_addresses'][0]+0x120+0x40,bits)
    row=query(bridge,include_roles=True)['slots'][0]['phases']['in_possession']['positions'][0]['base_role']
    assert row=={'raw_encoding':f'0x{bits:016x}','compiled_english_name':None,'native_resource_key':None,
                 'name_state':'no_matching_native_branch'}
    assert set(row)==ROLE_KEYS


def test_unrequested_role_resources_not_touched(bridge,composed):
    m=composed;m['put'](m['base']+roles.NATIVE_SPANS[0][0],b'\0')
    assert query(bridge,include_formation=True,include_instructions=True)['slot_count']==3
    with pytest.raises(BridgeError,match='no partial'):query(bridge,include_roles=True)


@pytest.mark.parametrize('kind',['unavailable','empty','nulls'])
def test_absent_or_null_slots_skip_role_resources_and_preserve_population(bridge,composed,kind):
    m=composed;m['put'](m['base']+roles.NATIVE_SPANS[0][0],b'\0')
    if kind=='unavailable':m['q'](m['base']+source.MANAGER_ROOT,0)
    else:m['vec'](m['tactics_payload']+0x1000,[] if kind=='empty' else [0,0,0])
    result=query(bridge,include_roles=True)
    assert result['slots']==[] if kind!='nulls' else len(result['slots'])==3
    if kind=='unavailable':assert result['slot_count'] is None and result['source_state']=='unavailable'
    if kind=='nulls':
        assert result['null_slot_count']==3 and result['primary_trained_tactic']['state']=='selected_slot_null'
        assert all(s['phases'] is None for s in result['slots'])


@pytest.mark.parametrize('selector',[0,1,2,3,255])
def test_roles_keep_all_slots_and_unsigned_primary_selection(bridge,composed,selector):
    m=composed;m['put'](m['tactics_payload']+0x1018,bytes([selector]))
    result=query(bridge,include_roles=True)
    assert [s['slot_index'] for s in result['slots']]==[0,1,2]
    assert result['primary_trained_tactic']['native_index']==selector
    assert result['primary_trained_tactic']['slot_index']==(selector if selector<=2 else None)


@pytest.mark.parametrize('mode',['service_null','cache_null','entry_null','empty','alternate'])
def test_legal_name_prerequisite_absence_retains_ids_and_roles(bridge,composed,mode):
    m=composed
    if mode=='service_null':m['q'](m['base']+formations.LOCALIZATION_RVA,0)
    if mode=='cache_null':m['q'](m['base']+formations.NUMERIC_CACHE_RVA,0)
    if mode=='entry_null':m['q'](m['formation_numeric_cache']+0x320+8,0)
    if mode in ('empty','alternate'):
        m['q'](m['formation_numeric_cache']+0x320+8,m['text']('' if mode=='empty' else 'one'))
    result=query(bridge,include_roles=True,include_formation=True)
    for slot in result['slots']:
        for phase in slot['phases'].values():
            assert phase['formation']=={'native_id':29,'state':'recognized','name':None}
            assert phase['positions'][0]['base_role']['name_state']=='named'


@pytest.mark.parametrize('mode',['pointer','length','utf8','nul','control'])
def test_malformed_name_cache_rejects_whole_composed_result(bridge,composed,mode):
    m=composed;p=m['formation_digits'][1]
    if mode=='pointer':m['q'](m['formation_numeric_cache']+0x320+8,1)
    if mode=='length':m['put'](p,struct.pack('<I',0x10000))
    if mode=='utf8':m['put'](p+4,b'\xff\0')
    if mode=='nul':m['put'](p+4,b'1x')
    if mode=='control':m['put'](p+4,b'\x01\0')
    before=deepcopy(bridge.player_refs)
    with pytest.raises(BridgeError,match='no partial'):query(bridge,include_formation=True,include_roles=True)
    assert bridge.player_refs==before


@pytest.mark.parametrize('mode',['no_match','uninitialized','unsupported_name_shape'])
def test_unneeded_name_resources_are_not_read(bridge,composed,mode):
    m=composed;m['q'](m['base']+formations.LOCALIZATION_RVA,1)
    if mode=='uninitialized':m['put'](m['base']+formations.METADATA_GUARD_RVA,b'\0')
    elif mode=='no_match':
        for creator in m['creator_addresses']:
            for offset in PHASES.values():m['put'](creator+offset,bytes(4))
    else:
        # Native recognition still succeeds but the name renderer domain does not.
        index=m['formation_identifiers'].index(29)
        m['put'](m['formation_templates']+index*24+22,b'\x05')
    result=query(bridge,include_formation=True,include_roles=True)
    assert all(phase['formation']['name'] is None for s in result['slots'] for phase in s['phases'].values())


@pytest.mark.parametrize('target',['role_word','native_role','name_data','name_pointer','selector','ownership'])
def test_late_readset_mutation_rejects_without_cache_mutation(bridge,monkeypatch,composed,target):
    m=composed;original=roles.decode;count=0
    def changing(*args,**kwargs):
        nonlocal count
        result=original(*args,**kwargs);count+=1
        if count==66:
            address={'role_word':m['creator_addresses'][0]+0x120+0x40,
                'native_role':m['base']+roles.NATIVE_SPANS[0][0],
                'name_data':m['formation_digits'][1]+4,
                'name_pointer':m['base']+formations.NUMERIC_CACHE_RVA,
                'selector':m['tactics_payload']+0x1018,'ownership':m['owner_container']+0x98}[target]
            byte=m['read'](address,1)[0];m['put'](address,bytes([byte^1]))
        return result
    monkeypatch.setattr(roles,'decode',changing)
    before=deepcopy(bridge.player_refs)
    with pytest.raises(BridgeError,match='changed|rejected'):query(bridge,include_roles=True,include_formation=True)
    assert count==66 and bridge.player_refs==before


def test_mcp_role_opt_in_boolean_default_read_schema():
    from fm_live_mcp.server import mcp
    tool=next(t for t in asyncio.run(mcp.list_tools()) if t.name=='fm_get_managed_tactics')
    assert tool.inputSchema['required']==['session_id']
    for flag in ('include_roles','include_formation','include_instructions'):
        assert tool.inputSchema['properties'][flag]['type']=='boolean'
        assert tool.inputSchema['properties'][flag]['default'] is False
    assert tool.annotations.readOnlyHint is True and tool.annotations.destructiveHint is False
    assert tool.annotations.openWorldHint is False
