"""Synthetic typed and original ARM64 controls; no game attachment or UI."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct

import pytest
from mcp.server.fastmcp import FastMCP
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X8, UC_ARM64_REG_X30, UC_ARM64_REG_SP

from fm_live_mcp import live_player_morale as query, player_career_morale as morale, player_morale_tools
from fm_live_mcp.bridge import BridgeError
from test_live_individual_training import live_focus, focus_memory, prepared_tactics_memory
from test_individual_training_focus import native_image, member_memory, team_memory, database_memory, memory, world_memory
from test_bridge import bridge

SLICE = 0x5ed4000


@pytest.fixture
def morale_memory(live_focus, native_image):
    m = live_focus
    for rva, n, digest in morale.NATIVE_GUARDS:
        raw = native_image[SLICE+rva:SLICE+rva+n]
        assert hashlib.sha256(raw).hexdigest() == digest
        m['put'](m['base']+rva,raw)
    m['q'](m['tables'][0]+142*8,m['base']+0xd32ba8)
    m['put'](0x1264,b'\x0d')
    return m


def get(m, refs=None):
    return query.get_player_morale(m['bridge'],m['bridge'].session,['p1'] if refs is None else refs)


def test_read_current_bound_career_value_without_attributes_or_writes(morale_memory):
    m = morale_memory
    cells = dict(m['cells'])
    result = get(m)
    row, = result['players']
    assert row['display_name'] == 'Test Müller'
    assert row['native_identity']['native_id'] == 12345
    assert row['morale']['native_code'] == 13
    assert row['morale']['english_definition_name'] == 'Good'
    assert row['morale']['native_getter_mode'] == 0
    assert row['morale']['refreshed'] is False
    assert result['save']['current_date'] == '2030-09-19'
    assert result['count'] == 1 and result['atomic'] is False
    assert result['saved_file_fallback'] is False
    assert 'overall happiness' in result['scope']
    assert not any(k in json.dumps(result) for k in ('team_address','manager_address','attributes'))
    assert cells == m['cells']
    m['put'](0x1264,b'\x14')
    assert get(m)['players'][0]['morale']['english_definition_name'] == 'Perfect'


@pytest.mark.parametrize('raw',range(256))
def test_all_signed_codes_preserve_their_state(morale_memory,raw):
    m = morale_memory
    m['put'](0x1264,bytes([raw]))
    value = get(m)['players'][0]['morale']
    assert value['raw_code'] == raw
    assert value['native_code'] == (raw if raw<128 else raw-256)
    if 1<=raw<=20:
        assert value['state'] == 'stored_named_morale'
    elif raw>=128:
        assert value['state'] == 'native_negative_code'
        assert value['english_definition_name'] == 'Scouting Required'
    else:
        assert value['state'] == 'outside_named_scale'
        assert value['english_definition_name'] is None


@pytest.mark.parametrize('fault',['getter','source','identity','membership','roster','unknown_ref'])
def test_bad_sources_reject_the_whole_batch(morale_memory,fault):
    m = morale_memory
    if fault=='getter':m['q'](m['tables'][0]+142*8,0)
    if fault=='source':m['put'](m['base']+0xd32ba8,b'\0')
    if fault=='identity':m['bridge'].player_refs['p1']['identity']=(777,'Test','Müller','2000-02-29',12345)
    if fault=='membership':m['vec'](m['headers']['people'],[])
    if fault=='roster':m['vec'](m['team_addresses'][0]+0x38,[])
    refs=['p1','unknown'] if fault=='unknown_ref' else ['p1']
    with pytest.raises(BridgeError,match='no partial result'):get(m,refs)


@pytest.mark.parametrize('at_final_callback',[False,True])
def test_source_drift_is_rejected_after_last_lifetime_callback(morale_memory,monkeypatch,at_final_callback):
    m = morale_memory
    if at_final_callback:
        original=m['bridge']._current;calls=[]
        def current(*args):
            calls.append(1)
            if len(calls)==3:m['put'](0x1264,b'\x01')
            return original(*args)
        monkeypatch.setattr(m['bridge'],'_current',current)
    else:
        original=morale.inspect
        def inspect(*args):
            result=original(*args);m['put'](0x1264,b'\x01');return result
        monkeypatch.setattr(morale,'inspect',inspect)
    with pytest.raises(BridgeError,match='changed'):get(m)


@pytest.mark.parametrize('refs',[[],['p1','p1'],[None],[''],['p1']*101,None])
def test_invalid_requests_rejected_before_reads(morale_memory,monkeypatch,refs):
    m=morale_memory
    monkeypatch.setattr(m['bridge'],'_read_scope',lambda *_:pytest.fail('Invalid request read game'))
    with pytest.raises(BridgeError,match='distinct nonempty'):
        query.get_player_morale(m['bridge'],m['bridge'].session,refs)


def test_unsupported_kind_does_not_read_a_guessed_field():
    for kind in ('virtual','player_staff'):
        result=morale.inspect(lambda *_:pytest.fail('Unsupported kind read'),0,0,kind)
        assert result['state']=='unsupported_record_kind' and result['native_code'] is None


def test_actual_original_career_getter_all_256_bytes_without_alternate_source(native_image):
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    u.mem_map(0xd32000,4096);u.mem_write(0xd32000,native_image[SLICE+0xd32000:SLICE+0xd33000])
    primary,stack,stop=0x700000000000,0x700000010000,0x700000020000
    for at in (primary,stack,stop):u.mem_map(at,4096)
    reads=[];writes=[]
    u.hook_add(UC_HOOK_MEM_READ,lambda vm,access,a,n,value,data:reads.append((a,n)))
    u.hook_add(UC_HOOK_MEM_WRITE,lambda vm,access,a,n,value,data:writes.append((a,n)))
    for raw in range(256):
        reads.clear();writes.clear();u.mem_write(primary+0x264,bytes([raw]))
        u.reg_write(UC_ARM64_REG_X0,primary);u.reg_write(UC_ARM64_REG_X1,0)
        u.reg_write(UC_ARM64_REG_X30,stop);u.reg_write(UC_ARM64_REG_SP,stack+0x800)
        u.emu_start(0xd32ba8,stop,count=100)
        assert u.reg_read(UC_ARM64_REG_X0)&0xffffffff == (raw if raw<128 else raw-256)&0xffffffff
        assert (primary+0x264,1) in reads
        assert all(a==primary+0x264 or stack<=a<a+n<=stack+4096 for a,n in reads)
        assert all(stack<=a<a+n<=stack+4096 for a,n in writes)


def test_registered_tool_reads_real_adapter_and_preserves_annotations(morale_memory):
    m=morale_memory;mcp=FastMCP('morale')
    player_morale_tools.register_player_morale_tools(mcp,m['bridge'])
    async def call():
        tool,=await mcp.list_tools()
        assert tool.name=='fm_get_player_morale'
        assert tool.annotations.readOnlyHint is True and tool.annotations.destructiveHint is False
        assert tool.inputSchema['properties']['player_refs']['maxItems']==100
        _,value=await mcp.call_tool(tool.name,{'session_id':m['bridge'].session,'player_refs':['p1']})
        return value
    assert asyncio.run(call())['players'][0]['morale']['native_code']==13


def test_labels_match_original_formatter_dispatch_and_pinned_english(native_image):
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    for page in (0x154a000,0x154b000,0x539b000):
        u.mem_map(page,4096);u.mem_write(page,native_image[SLICE+page:SLICE+page+4096])
    # Loaded global is not consumed before the localization call where we stop.
    for at,n in ((0x56a4000,4096),(0x700000000000,65536),(0x43db000,8192)):u.mem_map(at,n)
    hit=[]
    def code(vm,address,size,data):
        if address==0x43db8b8:hit.append(vm.reg_read(UC_ARM64_REG_X1));vm.emu_stop()
    u.hook_add(UC_HOOK_CODE,code)
    import _pinned_build
    plugin=_pinned_build.PLUGIN
    language=_pinned_build.language_template()
    assert hashlib.sha256(language.read_bytes()).hexdigest()==morale.ENGLISH_SHA256
    labels={}
    for line in language.read_text(encoding='utf-8-sig').splitlines():
        if line.startswith('KEY-'):
            key,label=line[4:].split(': ',1)
            if key.isdecimal():labels[int(key)]=label.split('[COMMENT')[0]
    for raw in range(256):
        value=morale.decode(raw);hit.clear()
        u.reg_write(UC_ARM64_REG_SP,0x700000008000)
        u.reg_write(UC_ARM64_REG_X0,value['native_code']&0xffffffff)
        u.reg_write(UC_ARM64_REG_X1,0);u.reg_write(UC_ARM64_REG_X8,0x700000000100)
        u.emu_start(0x154ab00,0,count=100)
        assert len(hit)==1
        if value['state']=='outside_named_scale':
            assert hit[0]==321175 and labels[hit[0]]=='Abysmal'
            assert value['english_resource_key'] is None
        else:
            assert value['english_resource_key']==hit[0]
            assert value['english_definition_name']==labels[hit[0]]
