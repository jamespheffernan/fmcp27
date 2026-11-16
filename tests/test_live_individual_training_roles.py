"""Actual158 Bridge/runtime Mach-O/ReadSet publication for opt-in training roles.

Physical/process I/O is synthetic. Genuine29 scalar replay lives in the pure
source tests; this rig exercises runtime admission, refs and callback order.
"""
import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path
import struct
import subprocess
import types

import pytest
from mcp.server.fastmcp import FastMCP
from fm_live_mcp import live_individual_training as query,individual_training_tools as tools,players,world,virtual_identity
from fm_live_mcp import individual_training_ip_role as ip,individual_training_position as position
from fm_live_mcp import individual_training_role_position as roles
from fm_live_mcp.bridge import BridgeError
from fm_live_mcp.reader import ReaderError
from test_runtime_publication_seal import (
    strict_training,focus_memory,prepared_tactics_memory,bridge,memory,
    database_memory,member_memory,team_memory,world_memory,native_image,
    default_memory,training_source_memory)


@pytest.fixture
def roles_rig(strict_training,native_image):
    rig=strict_training;m=rig.m
    for rva,n,digest in ip.NATIVE_GUARDS+position.NATIVE_GUARDS+roles.NATIVE_GUARDS:
        raw=native_image[0x5ED4000+rva:0x5ED4000+rva+n]
        assert hashlib.sha256(raw).hexdigest()==digest;rig.put(m['base']+rva,raw)
    header=m['allocate'](24);entries=m['allocate'](24);oop=m['allocate'](12)
    row=bytearray(24);struct.pack_into('<Hh',row,8,((-31&127)<<6)|6,1)
    rig.put(entries,bytes(row));rig.put(header,struct.pack('<QQQ',entries,entries+24,entries+24))
    rig.put(oop,bytes(6)+struct.pack('<h',-22)+bytes(4))
    m['q'](0x11A0,header);m['q'](0x1198,oop)
    m.update(role_ip_header=header,role_ip_entries=entries,role_oop_child=oop)
    return rig


def train(rig,refs=None,**kwargs):
    return query.get_player_individual_training(rig.bridge,rig.bridge.session,
        ['p1']if refs is None else refs,include_role_position=True,**kwargs)


def test_real_runtime_opt_in_has_native_values_no_labels_and_final_fences(roles_rig):
    rig=roles_rig;out=train(rig);row=out['players'][0];fields=row['role_position']
    assert row['additional_focus']['english_definition_name']=='Crossing'
    assert fields['ip_training']['native_role_mask']=='0x0000000000000001'
    assert fields['ip_training']['native_position_mask']=='0x00001000'
    assert fields['oop_training']['native_code']==-22 and fields['oop_training']['raw_code']==65514
    assert fields['ip_training']['role_name'] is fields['ip_training']['position_name'] is fields['oop_training']['role_name'] is None
    assert fields['label_state']=='not_proved_for_training_namespace'
    assert out['atomic'] is out['saved_file_fallback'] is False
    assert len(rig.read_sets)==2
    assert all((rig.m['base'],16384)in read.observed for read in rig.read_sets)
    last=max(i for i,event in enumerate(rig.events)if event[0]not in ('physical','close'))
    assert all(event[0]in ('physical','close')for event in rig.events[last+1:])
    assert any(event[0]=='physical'for event in rig.events[last+1:])
    rig.closed()


@pytest.mark.parametrize('include_default',[False,True])
def test_default_payload_equal_exact158_with_no_role_source_reads(default_memory,roles_rig,include_default):
    rig=roles_rig;assert rig.m is default_memory
    raw=subprocess.check_output(['git','show','c49a531c9f418174f14930b7644fa6376b2bc727:fm_live_mcp/live_individual_training.py'])
    baseline=types.ModuleType('fm_live_mcp._training_role_baseline158');baseline.__package__='fm_live_mcp'
    exec(compile(raw,'exact158_training.py','exec'),baseline.__dict__)
    expected=baseline.get_player_individual_training(rig.bridge,rig.bridge.session,['p1'],include_default_resolution=include_default)
    rig.reset_trace()
    actual=query.get_player_individual_training(rig.bridge,rig.bridge.session,['p1'],include_default_resolution=include_default)
    assert expected.pop('observed_at') and actual.pop('observed_at');assert actual==expected
    assert 'role_position'not in actual['players'][0]
    assert not any(event[0]=='physical'and event[1]in (0x1198,0x11A0,rig.m['role_ip_header'])for event in rig.events)
    rig.closed()


def test_opt_in_and_existing_default_policy_keep_independent_sources(default_memory,roles_rig):
    rig=roles_rig;assert rig.m is default_memory
    row=train(rig,include_default_resolution=True)['players'][0]
    assert row['club_training_intensity']['native_code']==-1
    assert row['default_intensity_resolution']['native_code']==1
    assert row['role_position']['ip_training']['native_role_mask']=='0x0000000000000001'
    assert row['club_training_intensity']['applied_intensity'] is None
    assert row['role_position']['applied_training_evaluated'] is False
    rig.closed()


@pytest.mark.parametrize('late',[3,4,5])
@pytest.mark.parametrize('fault',['IP_pointer','IP_capacity','IP_position','IP_level','OOP_pointer','OOP_code','OOP_pool_code','native_code','ref_expiry'])
def test_real_scope_refuses_role_source_changes_at_each_late_callback(roles_rig,late,fault):
    rig=roles_rig
    def mutate(r):
        m=r.m
        if fault=='IP_pointer':m['q'](0x11A0,0)
        elif fault=='IP_capacity':m['q'](m['role_ip_header']+16,m['role_ip_entries']+48)
        elif fault=='IP_position':r.put(m['role_ip_entries']+8,struct.pack('<H',((-31&127)<<6)|7))
        elif fault=='IP_level':r.put(m['role_ip_entries']+10,bytes(2))
        elif fault=='OOP_pointer':m['q'](0x1198,0)
        elif fault=='OOP_code':r.put(m['role_oop_child']+6,struct.pack('<h',50))
        elif fault=='OOP_pool_code':r.put(m['base']+0x17F5E00,b'\0')
        elif fault=='native_code':r.put(m['base']+0x2CF5728,b'\0')
        else:r.bridge.player_refs.pop('p1')
    rig.hooks[late]=mutate
    with pytest.raises(BridgeError,match='no partial result'):train(rig)
    rig.closed()


@pytest.mark.parametrize('operand',['uuid','rtti_displacement','rtti_name'])
def test_roles_do_not_bypass_actual_final_runtime_MachO_checks(roles_rig,operand):
    rig=roles_rig;rig.hooks[5]=lambda r:r.mutate(operand)
    with pytest.raises(BridgeError,match='no partial result'):train(rig)
    rig.closed()


def test_distinct_reference_aliases_preserve_order_and_last_expiry_rejects_whole_batch(roles_rig):
    rig=roles_rig;rig.bridge.player_refs['alias']=deepcopy(rig.bridge.player_refs['p1'])
    out=train(rig,['alias','p1']);a,b=out['players']
    assert [a['player_ref'],b['player_ref']]==['alias','p1']
    assert a['role_position']==b['role_position'] and a['role_position']is not b['role_position']
    a['role_position']['ip_training']['native_role_code']=999
    assert b['role_position']['ip_training']['native_role_code']==-31
    def expire(r):r.bridge.player_refs.pop('alias')
    rig.reset_trace();rig.hooks[5]=expire
    with pytest.raises(BridgeError,match='reference binding changed'):train(rig,['p1','alias'])
    rig.closed()


@pytest.mark.parametrize('kind',['player_staff','virtual'])
def test_unsupported_records_do_not_read_role_children_or_gain_fallback_codes(roles_rig,monkeypatch,kind):
    rig=roles_rig;m=rig.m
    primary,person=m['add_person'](kind,1,77,0,'Combined')
    m['vec'](m['headers']['people'],[0x1388,person]);m['vec'](m['team']+0x38,[0x1000,primary])
    binding=dict(address=primary,tables=m['tables'],record_kind=kind,database_index=1)
    if kind=='player_staff':binding['identity']=('player_staff',77,'Combined','','2000-02-29',0)
    else:binding.update(binding_kind=virtual_identity.BINDING_KIND,identity=(virtual_identity.BINDING_KIND,1,77,0))
    rig.bridge.player_refs['other']=binding;read=rig.read
    def physical(at,n):
        if any(at<=primary+offset<at+n for offset in (0x190,0x198,0x1A0)):
            pytest.fail('Unsupported role source was inspected')
        return read(at,n)
    monkeypatch.setattr(rig,'read',physical)
    out=train(rig,['p1','other']);row=out['players'][1]
    assert row['record_kind']==kind and row['native_identity']['native_id']==77
    assert row['role_position']['state']=='unavailable'
    assert row['role_position']['ip_training'] is row['role_position']['oop_training'] is None
    rig.closed()


@pytest.mark.parametrize('bad',[None,0,1,'true',[],{}])
def test_invalid_opt_in_rejects_before_any_runtime_or_stream_read(roles_rig,bad):
    rig=roles_rig
    with pytest.raises(BridgeError,match='include_role_position must be a Boolean'):
        query.get_player_individual_training(rig.bridge,rig.bridge.session,['p1'],include_role_position=bad)
    assert rig.events==[] and rig.bridge._reader is None


@pytest.mark.parametrize('fault',['EOF','cancel'])
def test_role_transport_failure_closes_reader_and_keeps_no_partial_result(roles_rig,monkeypatch,fault):
    rig=roles_rig;read=rig.read
    def physical(at,n):
        if at==rig.m['role_ip_header']:
            if fault=='cancel':raise KeyboardInterrupt('synthetic training role cancellation')
            raise ReaderError('synthetic training role EOF')
        return read(at,n)
    monkeypatch.setattr(rig,'read',physical)
    with pytest.raises(KeyboardInterrupt if fault=='cancel'else BridgeError):train(rig)
    rig.closed()


def test_SDK_existing_tool_strict_opt_in_and_unknown_namespace(roles_rig):
    rig=roles_rig
    async def run():
        mcp=FastMCP('stored training roles');tools.register_individual_training_tools(mcp,rig.bridge)
        tool,=await mcp.list_tools()
        assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint and not tool.annotations.openWorldHint
        assert tool.inputSchema['properties']['include_role_position']=={'default':False,'title':'Include Role Position','type':'boolean'}
        _,result=await mcp.call_tool(tool.name,dict(session_id=rig.bridge.session,player_refs=['p1'],include_role_position=True))
        assert result['players'][0]['role_position']['oop_training']['role_name'] is None
        rig.closed();rig.reset_trace()
        with pytest.raises(Exception,match='valid boolean'):
            await mcp.call_tool(tool.name,dict(session_id=rig.bridge.session,player_refs=['p1'],include_role_position=1))
        assert rig.events==[]
    asyncio.run(run())
