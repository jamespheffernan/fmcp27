"""Adapter/lifecycle tests use the real156 read scope with synthetic I/O."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
import struct
import pytest
from mcp.server.fastmcp import FastMCP

from fm_live_mcp import live_player_concern_history as query, player_concern_history_tools as tools, world
from fm_live_mcp.bridge import BridgeError
from concern_history_fixture import (live_concerns,agreed_memory,public_assessment_memory,shortlist_public_memory,
    prepared_tactics_memory,member_memory,bridge,database_memory,memory,team_memory,world_memory)


def get(m,refs=None,**kwargs):
    bridge=m['bridge']
    return bridge.get_player_concern_history(bridge.session,['p1']if refs is None else refs,**kwargs)


def test_raw_default_preserves_ten_slots_repeats_dates_unknowns_and_real_scope(live_concerns,monkeypatch):
    m=live_concerns;before=dict(m['cells'])
    monkeypatch.setattr(query,'_english_binding',lambda *_:pytest.fail('Raw mode must not access English'))
    result=get(m,coach_name=' test COACH ');row,=result['players'];history=row['concern_history']
    assert row['name']=='Test Müller'and row['native_identity']['native_id']==12345
    assert history['native_ring_entry_count']==10
    assert[entry['native_physical_slot']for entry in history['records']]==[2,1,0,9,8,7,6,5,4,3]
    assert history['records'][0]['record']==history['records'][2]['record']
    assert history['records'][1]['record']is None and history['records'][1]['state']=='null_native_ring_slot'
    assert history['native_unset_end_filter_count']==2
    assert history['records'][0]['record']['stored_end_date']['unmapped_low_word_flags']==0xfe00
    assert history['records'][0]['record']['reason_title']is None
    assert result['templates_requested']is False and result['english_resource_sha256']is None
    assert result['atomic']is result['native_calls']is result['profile_expansion']is False
    assert result['current_unhappiness_evaluated']is result['promise_fulfilment_evaluated']is False
    assert m['cells']==before and m['bridge']._reader is None
    assert len(m['streams'])==1 and m['streams'][0].closed
    assert not any(key in json.dumps(result)for key in('team_address','manager_address','attributes'))


def test_requested_order_and_100_distinct_aliases_are_bounded(live_concerns):
    m=live_concerns;refs=[f'alias-{index}'for index in range(100)]
    m['bridge'].player_refs.update({ref:deepcopy(m['initial_binding'])for ref in refs})
    result=get(m,refs)
    assert result['count']==100 and[row['player_ref']for row in result['players']]==refs
    assert all(row['concern_history']['native_ring_entry_count']==10 for row in result['players'])


@pytest.mark.parametrize('refs',[[],['p1']*101,['p1','p1'],('p1',),'p1',[None],[True],[''],None])
def test_invalid_references_fail_before_scope(live_concerns,monkeypatch,refs):
    bridge=live_concerns['bridge'];monkeypatch.setattr(bridge,'_read_scope',lambda *args,**kwargs:pytest.fail('No scope'))
    with pytest.raises(BridgeError,match='distinct nonempty'):bridge.get_player_concern_history(bridge.session,refs)


@pytest.mark.parametrize('value',[None,True,'','x'*129])
def test_invalid_session_fails_before_scope(live_concerns,monkeypatch,value):
    bridge=live_concerns['bridge'];monkeypatch.setattr(bridge,'_read_scope',lambda *args,**kwargs:pytest.fail('No scope'))
    with pytest.raises(BridgeError,match='session_id'):bridge.get_player_concern_history(value,['p1'])


@pytest.mark.parametrize('value',['',True,1,'x'*257])
def test_invalid_coach_fails_before_scope(live_concerns,monkeypatch,value):
    bridge=live_concerns['bridge'];monkeypatch.setattr(bridge,'_read_scope',lambda *args,**kwargs:pytest.fail('No scope'))
    with pytest.raises(BridgeError,match='coach_name'):get(live_concerns,coach_name=value)


@pytest.mark.parametrize('value',[None,0,1,'true',[]])
def test_template_switch_requires_real_boolean(live_concerns,monkeypatch,value):
    bridge=live_concerns['bridge'];monkeypatch.setattr(bridge,'_read_scope',lambda *args,**kwargs:pytest.fail('No scope'))
    with pytest.raises(BridgeError,match='Boolean'):get(live_concerns,include_templates=value)


@pytest.mark.parametrize('fault',['unknown','unbound','outside_roster','wrong_identity','wrong_owner'])
def test_invalid_or_stale_source_never_publishes_partial_batch(live_concerns,fault):
    m=live_concerns
    if fault=='unknown':
        with pytest.raises(BridgeError,match='no partial'):get(m,['p1','missing'])
        assert m['streams'][0].closed;return
    binding=m['bridge'].player_refs['p1']
    if fault=='unbound':binding['world_bound']=False
    elif fault=='outside_roster':m['vec'](m['team']+0x38,[])
    elif fault=='wrong_identity':binding['identity']=(999,*binding['identity'][1:])
    else:m['q'](m['agreed_contract']+8,m['manager']+0x548)
    with pytest.raises(BridgeError,match='no partial'):get(m)
    assert m['streams'][0].closed and m['bridge']._reader is None


@pytest.mark.parametrize('mode',['empty','null','foreign'])
def test_empty_and_unavailable_contexts_keep_distinct_states(live_concerns,mode):
    m=live_concerns
    if mode=='empty':m['put'](m['concern_ring'],b'\0')
    elif mode=='null':m['q'](m['agreed_contract']+0x30,0)
    else:
        club=m['typed']('club',0x170);team=m['typed']('team',0xb8);m['q'](team+0x30,club);m['vec'](club+0x18,[team]);m['q'](m['agreed_contract']+0x10,team)
    result=get(m)['players'][0]['concern_history']
    if mode=='foreign':assert result['records']is result['native_ring_entry_count']is None
    else:assert result['records']==[]and result['native_ring_entry_count']==0


@pytest.mark.parametrize('stage',[3,5])
def test_byte_mutation_in_actual_post_yield_or_final_lifetime_callback_rejects(live_concerns,stage):
    m=live_concerns
    def mutate(call):
        if call==stage:m['put'](m['concern_a']+22,(649).to_bytes(2,'little'))
    m['on_current']=mutate
    with pytest.raises(BridgeError,match='changed during read'):get(m)
    assert m['current_calls']>=stage and m['streams'][0].closed


def test_public_save_callback_is_before_final_fences(live_concerns):
    m=live_concerns;m['on_public']=lambda:m['put'](m['concern_b']+27,b'\x80')
    with pytest.raises(BridgeError,match='changed during read'):get(m)
    assert m['streams'][0].closed


@pytest.mark.parametrize('source',['runtime_header','runtime_type','native_rule'])
@pytest.mark.parametrize('stage',[3,5])
def test_late_runtime_and_native_source_changes_are_physically_rechecked(live_concerns,source,stage):
    m=live_concerns
    address={'runtime_header':m['base']+40,'runtime_type':m['base']+query.players.RVA[1]-8,
        'native_rule':m['base']+query.history.SOURCE[0][0]}[source]
    def mutate(call):
        if call==stage:m['put'](address,bytes([m['read'](address,1)[0]^1]))
    m['on_current']=mutate
    with pytest.raises(BridgeError,match='changed during read'):get(m)
    assert m['streams'][0].closed and m['bridge']._reader is None


def test_process_restart_in_real_post_yield_callback_closes_and_returns_no_result(live_concerns):
    m=live_concerns
    def restart(call):
        if call==3:m['bridge'].process=replace(m['bridge'].process,started='different lifetime')
    m['on_current']=restart
    with pytest.raises(BridgeError,match='restarted'):get(m)
    assert m['streams'][0].closed and m['bridge']._reader is None


def test_real_scope_has_no_post_fence_native_or_presentation_callback(live_concerns):
    m=live_concerns;get(m);events=m['events']
    assert m['current_calls']==5
    last_current=max(index for index,event in enumerate(events)if event[0]=='current')
    final_starts=[index for index,event in enumerate(events)if event[0]=='verify_start'][-2:]
    assert last_current<final_starts[0]<final_starts[1]
    assert all(event[0]in('verify_start','verify_end','read','close')for event in events[final_starts[0]:])
    assert events[-1]==('close',)


def test_mcp_contract_registers_only_requested_surface_and_dispatches_real_adapter(live_concerns):
    m=live_concerns;mcp=FastMCP('concern-history');tools.register_player_concern_history_tools(mcp,m['bridge'])
    async def check():
        tool,=await mcp.list_tools();schema=tool.inputSchema
        assert tool.name=='fm_get_player_concern_history'
        assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint and not tool.annotations.openWorldHint
        assert set(schema['properties'])=={'session_id','player_refs','coach_name','include_templates','include_promises'}
        assert set(schema['required'])=={'session_id','player_refs'}
        assert schema['properties']['include_templates']['default']is False
        assert schema['properties']['include_promises']['default']is False
        refs=schema['properties']['player_refs'];assert(refs['minItems'],refs['maxItems'],refs['uniqueItems'])==(1,100,True)
        content,structured=await mcp.call_tool(tool.name,{'session_id':m['bridge'].session,'player_refs':['p1']})
        assert structured['players'][0]['concern_history']['native_ring_entry_count']==10
        assert structured['templates_requested']is False
    asyncio.run(check())
