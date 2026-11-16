"""Promise-inventory option on the concern-history adapter; real read scope, synthetic I/O.

The static native bytes come from retained genuine captures. The typed career,
PLAYER vectors and promise records are synthetic and labelled as such; none of
this is a live game verification.
"""
import asyncio
from copy import deepcopy
import gzip
import json
from pathlib import Path
import struct
import pytest
from mcp.server.fastmcp import FastMCP

from fm_live_mcp import live_player_concern_history as query, player_concern_history_tools as tools
from fm_live_mcp import player_promise_inventory_source as source, promise_kind_definitions as kinds, players, world
from fm_live_mcp.bridge import BridgeError
from concern_history_fixture import (live_concerns,agreed_memory,public_assessment_memory,shortlist_public_memory,
    prepared_tactics_memory,member_memory,bridge,database_memory,memory,team_memory,world_memory)
from test_live_player_concern_history import get
from test_concern_history_english_and_seal import verified_english_precondition

H=Path(__file__).resolve().parents[1]/'evidence/social-promises-20261109'
FIXTURES=Path(__file__).parent/'fixtures'


def _literal(packet):
    base=int(packet['plugin_base_private'],16);cells={}
    for row in packet['journal']['regions']:
        at=int(row['address'],16)
        cells.update({at+i:v for i,v in enumerate(bytes.fromhex(row['raw_hex']))})
    return base,cells


@pytest.fixture
def live_promises(live_concerns):
    """Typed synthetic career with genuine promise/definition static bytes and a two-entry vector."""
    m=live_concerns;base=m['base']
    with gzip.open(FIXTURES/'player_promise_inventory148.json.gz','rt')as stream:old_base,cells=_literal(json.load(stream))
    for rva,size,digest in source.SOURCE:
        m['put'](base+rva,bytes(cells[old_base+rva+i]for i in range(size)))
    old_base,cells=_literal(json.loads((H/'live-promise-definitions-1.json').read_text()))
    for rva,size,digest in kinds.SOURCE:
        m['put'](base+rva,bytes(cells[old_base+rva+i]for i in range(size)))
    primary=m['concern_primary'];owner_person=primary+0x388;person_table=base+players.RVA[2]
    m['q'](base+0x55f1b18,base+0x55ef7c8);m['q'](base+0x55f1b30,base+0x24bfc18)
    m['q'](base+0x55ef7d0,base+0x53bf95f);m['put'](base+0x53bf95f,source.RULE_NAME)
    m['q'](person_table+0x668,base+0xd5c5fc);m['put'](person_table-0x678,struct.pack('<q',-0x388))
    m['put'](base+players.RVA[0]-0x20,struct.pack('<q',0x278))
    manager_person=m['manager']+0x548
    people=struct.unpack('<Q',m['read'](m['headers']['people'],8))[0]
    m['vec'](m['headers']['people'],[0x1388,manager_person])
    m['put'](manager_person+8,struct.pack('<III',1,777,777))
    def promise(kind,category,scalar,start_day,end_day,flag,*,a=manager_person,b=owner_person):
        record=m['allocate'](0x60);raw=bytearray(0x60);struct.pack_into('<I',raw,0,1)
        struct.pack_into('<QQ',raw,0x18,a,b)
        struct.pack_into('<I',raw,0x38,(2030<<16)|start_day);struct.pack_into('<I',raw,0x3c,(2031<<16)|end_day)
        struct.pack_into('<i',raw,0x44,scalar);struct.pack_into('<h',raw,0x4e,kind);raw[0x53]=flag;raw[0x56]=category
        m['put'](record,bytes(raw));return record
    first=promise(1,0,-5,100,0x1ff,1);second=promise(7,0,9,101,102,0,a=owner_person,b=manager_person)
    third=promise(120,2,3,50,60,0)
    vector=m['allocate'](24);slots=m['allocate'](8*3)
    m['put'](slots,struct.pack('<3Q',first,second,third))
    m['put'](vector,struct.pack('<QQQ',slots,slots+24,slots+24));m['q'](primary+0x278+0xa8,vector)
    m.update(promise_vector=vector,promise_records=(first,second,third),manager_person=manager_person)
    return m


def inventory(m,**kwargs):
    result=get(m,include_promises=True,**kwargs);return result,result['players'][0]['promise_inventory']


def test_default_has_no_promise_surface_and_raw_concern_result_is_unchanged(live_promises):
    result=get(live_promises);row,=result['players']
    assert'promise_inventory'not in row and result['promises_requested']is False
    assert result['source']=='stored_current_main_contract_concern_history'


def test_inventory_preserves_physical_order_raw_codes_neutral_links_and_unknowns(live_promises):
    m=live_promises;before=dict(m['cells']);result,inv=inventory(m)
    assert result['promises_requested']is True and result['atomic']is result['native_calls']is result['profile_expansion']is False
    assert result['promise_lifecycle_evaluated']is result['promise_fulfilment_evaluated']is False
    assert result['source']=='stored_current_main_contract_concern_history_and_player_promise_inventory'
    assert'neither a complete manager promise population'in result['scope']or'not a complete manager-wide promise population'in result['scope']
    assert inv['state']=='observed_native_vector'and inv['native_vector_entry_count']==3
    assert inv['complete_manager_population_verified']is False and inv['lifecycle_evaluated']is False and inv['active_count']is None
    assert[e['entry_index']for e in inv['promises']]==[0,1,2]
    first,second,third=inv['promises']
    assert(first['native_kind'],first['native_category_code'],first['native_linked_scalar'])==(1,0,-5)
    assert(second['native_kind'],second['native_linked_scalar'])==(7,9)and third['native_category_code']==2
    assert first['native_end_marker_bit0']is True and second['native_end_marker_bit0']is False
    assert first['stored_end_date']['unmapped_low_word_flags']==0 and first['stored_start_date']['stored_year']==2030
    assert first['party_A_matches_selected_view']is True and first['party_B_matches_vector_owner']is True
    assert second['party_A_matches_selected_view']is False and second['party_A_matches_vector_owner']is True
    assert second['party_B_matches_vector_owner']is False
    assert first['native_party_A']['record_kind']=='human_manager'and first['native_party_B']['record_kind']=='actual'
    for entry in inv['promises']:
        assert entry['promiser']is entry['recipient']is entry['subject']is None
        assert entry['party_role_state']=='not_evaluated_context_dependent_native_links'
        assert entry['active']is entry['ongoing']is entry['fulfilled']is entry['overdue']is None
        assert entry['kind_name']is None and entry['kind_definition']is None
        assert entry['kind_name_state']=='definition_not_requested'
    assert result['players'][0]['concern_history']['native_ring_entry_count']==10
    assert m['cells']==before and m['bridge']._reader is None and m['streams'][0].closed
    assert not any(key in json.dumps(result)for key in('team_address','manager_address','attributes'))


@pytest.mark.parametrize('mode,state,count',[('absent','absent_native_vector',0),('empty','observed_empty_native_vector',0)])
def test_absent_and_empty_vectors_stay_distinct_from_each_other_and_from_unknown(live_promises,mode,state,count):
    m=live_promises
    if mode=='absent':m['q'](m['concern_primary']+0x278+0xa8,0)
    else:
        slots=m['allocate'](8);m['put'](m['promise_vector'],struct.pack('<QQQ',slots,slots,slots))
    _,inv=inventory(m)
    assert inv['state']==state and inv['promises']==[]and inv['native_vector_entry_count']==count
    assert inv['active_count']is None and inv['complete_manager_population_verified']is False


def test_definitions_need_templates_and_known_kinds_only_get_unrendered_english(verified_english_precondition,live_promises):
    m=live_promises;result,inv=inventory(m,include_templates=True)
    assert len(m['english_calls'])==2 and result['english_resource_sha256']==query.ENGLISH_RESOURCE_SHA256
    first,second,third=inv['promises']
    assert first['kind_definition']['english_template']=='Fair increase in playing time'
    assert first['kind_name_state']=='compiled_english_definition_template'and first['kind_name']is None
    assert third['kind_definition']['english_template']=='Play loanee [%person#1] more often'
    assert third['kind_definition']['placeholder_people_resolved']is False
    assert second['kind_definition']['state']=='unmapped_native_kind'and second['kind_definition']['english_template']is None
    assert second['kind_name_state']=='unmapped_native_kind'
    events=m['events'];final_starts=[i for i,e in enumerate(events)if e[0]=='verify_start'][-2:]
    assert all(e[0]in('read','verify_start','verify_end','close')for e in events[final_starts[0]:])


@pytest.mark.parametrize('kind',['combined','virtual'])
def test_combined_or_virtual_record_keeps_unsupported_kind_and_no_promises(live_promises,monkeypatch,kind):
    m=live_promises;original=query._bound_person
    def labelled(*args,**kwargs):
        person,_,name,display=original(*args,**kwargs);return person,kind,name,display
    monkeypatch.setattr(query,'_bound_person',labelled)
    result,inv=inventory(m)
    assert inv['state']=='unsupported_record_kind'and inv['promises']is None and inv['native_vector_entry_count']is None
    assert inv['owner']is None and inv['active_count']is None and result['players'][0]['record_kind']==kind


@pytest.mark.parametrize('fault',['rule','source_span','owner_route','vector_geometry','promise_lifetime','selected_view'])
def test_corrupt_native_source_or_vector_rejects_whole_batch(live_promises,fault):
    m=live_promises;base=m['base']
    if fault=='rule':m['put'](base+0x53bf95f,b'X')
    elif fault=='source_span':m['put'](base+source.SOURCE[0][0],bytes([m['read'](base+source.SOURCE[0][0],1)[0]^1]))
    elif fault=='owner_route':m['q'](base+players.RVA[2]+0x668,0)
    elif fault=='vector_geometry':m['put'](m['promise_vector'],struct.pack('<QQQ',9,8,16))
    elif fault=='promise_lifetime':m['put'](m['promise_records'][1],struct.pack('<I',0))
    else:m['put'](m['manager_person']+8,struct.pack('<III',7,777,777))
    with pytest.raises(BridgeError,match='no partial'):get(m,include_promises=True)
    assert m['streams'][0].closed and m['bridge']._reader is None


@pytest.mark.parametrize('stage',[3,5])
def test_promise_byte_mutation_in_post_yield_or_final_callback_rejects(live_promises,stage):
    m=live_promises
    def mutate(call):
        if call==stage:m['put'](m['promise_records'][0]+0x4e,(2).to_bytes(2,'little'))
    m['on_current']=mutate
    with pytest.raises(BridgeError,match='changed during read'):get(m,include_promises=True)
    assert m['streams'][0].closed


@pytest.mark.parametrize('value',[None,0,1,'true',[]])
def test_promise_switch_requires_real_boolean(live_promises,monkeypatch,value):
    bridge=live_promises['bridge'];monkeypatch.setattr(bridge,'_read_scope',lambda *a,**k:pytest.fail('No scope'))
    with pytest.raises(BridgeError,match='include_promises must be a Boolean'):get(live_promises,include_promises=value)


def test_mcp_schema_and_dispatch_expose_the_promise_switch_without_a_new_tool(live_promises):
    m=live_promises;mcp=FastMCP('promise-inventory');tools.register_player_concern_history_tools(mcp,m['bridge'])
    async def check():
        tool,=await mcp.list_tools();schema=tool.inputSchema
        assert tool.name=='fm_get_player_concern_history'and tool.annotations.readOnlyHint
        assert set(schema['properties'])=={'session_id','player_refs','coach_name','include_templates','include_promises'}
        assert schema['properties']['include_promises']['default']is False
        assert set(schema['required'])=={'session_id','player_refs'}
        _,structured=await mcp.call_tool(tool.name,{'session_id':m['bridge'].session,'player_refs':['p1'],'include_promises':True})
        assert structured['players'][0]['promise_inventory']['native_vector_entry_count']==3
        with pytest.raises(Exception):
            await mcp.call_tool(tool.name,{'session_id':m['bridge'].session,'player_refs':['p1'],'include_promises':'yes'})
    asyncio.run(check())
