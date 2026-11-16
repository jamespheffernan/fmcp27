"""Typed synthetic career plus static native bytes from retained evidence.

Process/reader I/O is replaced; the adapter uses the real reader156 scope,
canonical binding, world callbacks, pure decoders and final byte journals.
"""
from copy import deepcopy
import json
from pathlib import Path
import struct
from types import MethodType
import pytest

from fm_live_mcp import bridge as bridge_module, player_concern_history_source as source
from fm_live_mcp import player_concern_history_templates_source as templates, players, world
from fm_live_mcp.bridge import Bridge

# Older shared fixtures stub runtime verification for field-only tests; concern
# history needs the real journaled verifier to prove late header/RTTI mutation.
REAL_VERIFY_RUNTIME = players.verify_runtime
from test_playing_time import (agreed_memory,public_assessment_memory,shortlist_public_memory,
    prepared_tactics_memory,bridge,database_memory,memory,team_memory,world_memory)
from test_shortlist_members import member_memory

H=Path(__file__).resolve().parents[1]/'evidence/concern-history158/inputs'


@pytest.fixture
def live_concerns(agreed_memory,prepared_tactics_memory,member_memory,bridge,monkeypatch):
    m=agreed_memory;assert m is prepared_tactics_memory and m is member_memory
    packet=json.loads((H/'live-concern-template-carriers-context-1.json').read_text())
    old_base=int(packet['plugin_base_private'],16);literal={}
    for row in packet['journal']['regions']:
        address=int(row['address'],16)
        literal.update({address+offset:value for offset,value in enumerate(bytes.fromhex(row['raw_hex']))})
    for rva,size,digest in source.SOURCE+templates.SOURCE:
        m['put'](m['base']+rva,bytes(literal[old_base+rva+offset]for offset in range(size)))
    base=m['base'];primary=m['agreed_person']-0x388;person_table=base+players.RVA[2]
    uuid=b'fixture uuid 16b'
    m['put'](base,bytes(16384))
    m['put'](base,struct.pack('<8I',0xfeedfacf,0x100000c,0,6,1,24,0,0)+struct.pack('<II',0x1b,24)+uuid)
    info=m['allocate'](16);name=m['allocate'](len(b'N2db12PLAYING_DATAE\0'))
    m['put'](name,b'N2db12PLAYING_DATAE\0');m['q'](info+8,name)
    m['put'](base+players.RVA[1]-16,struct.pack('<qQ',0,info))
    m['put'](base+0x55edf40,struct.pack('<q',0));m['q'](base+0x55edf48,base+0x55edae0)
    m['q'](base+0x55edf60,base+0x24a9e1c);m['q'](base+0x55edae8,base+0x53bce67)
    m['put'](base+0x53bce67,source.RULE)
    m['q'](person_table+0x3c0,base+0xcb8c68);m['put'](person_table-0x3d0,struct.pack('<q',-0x110))
    m['q'](primary+0x278,base+0x5589a90);m['put'](base+0x5589a90-16,struct.pack('<q',-0x278))
    m['q'](primary+0x128,m['team']);m['q'](m['agreed_contract']+0x10,m['team'])
    m['q'](base+world.TYPES['full_contract'][0]+0x90,base+0x129fffc)
    ring=m['allocate'](96);a=m['allocate'](64)+4;b=m['allocate'](32)
    assert a%8==4
    raw=bytearray(28);struct.pack_into('<IIiiIH',raw,0,(2030<<16)|300,(1900<<16)|1|0xfe00,-1,42,7,99)
    struct.pack_into('<H',raw,22,648);raw[24:]=bytes([255,7,12,4]);m['put'](a,raw)
    raw_b=bytearray(raw);struct.pack_into('<I',raw_b,4,(2030<<16)|320);struct.pack_into('<H',raw_b,22,667);m['put'](b,raw_b)
    header=bytearray(96);header[0]=10;header[0x58]=3
    pointers=[a,0,a,b,0,0,0,0,0,b]
    struct.pack_into('<10Q',header,8,*pointers);m['put'](ring,header);m['q'](m['agreed_contract']+0x30,ring)
    reference=m['assessment_player_ref'];binding=deepcopy(bridge.player_refs[reference]);binding['world_bound']=True
    bridge.player_refs['p1']=binding
    bridge.plugin_identity=(('/synthetic/Contents/MacOS/plugin',1,2,3,4),uuid)
    monkeypatch.setattr(players,'verify_runtime',REAL_VERIFY_RUNTIME)
    events=[];streams=[];m.update(concern_primary=primary,concern_ring=ring,concern_a=a,concern_b=b,
        concern_ref='p1',events=events,streams=streams,bridge=bridge,initial_binding=deepcopy(binding))

    class SyntheticStream:
        def __init__(self,helper,pid):self.pid=pid;self.closed=False;streams.append(self);events.append(('open',pid))
        def read(self,address,size):
            if address<primary+0x18d and address+size>primary+0x148:pytest.fail('No player attribute/profile reads')
            events.append(('read',address,size));return m['read'](address,size)
        def close(self):self.closed=True;events.append(('close',))
    monkeypatch.setattr(bridge_module,'ReadStream',SyntheticStream)
    monkeypatch.setattr(bridge,'_read_scope',MethodType(Bridge._read_scope,bridge))
    monkeypatch.setattr(bridge,'_read_memory',MethodType(Bridge._read_memory,bridge))
    original_current=bridge._current
    def current(session_id):
        events.append(('current',));m['current_calls']=m.get('current_calls',0)+1
        hook=m.get('on_current')
        if hook:hook(m['current_calls'])
        return original_current(session_id)
    monkeypatch.setattr(bridge,'_current',current)
    def layout(process):events.append(('layout',));return m['tables']
    monkeypatch.setattr(bridge,'_player_layout',layout)
    original_public=bridge._public_save
    def public(record):
        events.append(('public_save',))
        if m.get('on_public'):m['on_public']()
        return original_public(record)
    monkeypatch.setattr(bridge,'_public_save',public)
    original_verify=world.ReadSet.verify
    def verify(readset):
        events.append(('verify_start',id(readset)));original_verify(readset);events.append(('verify_end',id(readset)))
    monkeypatch.setattr(world.ReadSet,'verify',verify)
    monkeypatch.setattr(bridge,'_decode_player',lambda *args,**kwargs:pytest.fail('No profile generation'))
    monkeypatch.setattr(players,'decode',lambda *args,**kwargs:pytest.fail('No profile generation'))
    return m
