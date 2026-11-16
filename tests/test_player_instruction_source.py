import asyncio
import gzip
import json
from pathlib import Path
import struct
from unittest.mock import Mock

import pytest
from fm_live_mcp import player_instruction_source as source, world
from test_live_personal_overrides import personal, node, record
from test_live_tactical_assignments_source import two_phase
from test_live_in_possession_source import context


def actual():
    with gzip.open(Path(__file__).parent/'fixtures/player_instruction_source_181.json.gz','rt')as f:
        return json.load(f)


def offline_read(row):
    raw=bytes.fromhex(row['record_hex']);memory={}
    for offset,key in((8,'primary_hex'),(40,'secondary_hex')):
        start,end,cap=struct.unpack_from('<QQQ',raw,offset)
        memory[start,end-start]=bytes.fromhex(row[key])
    return raw,lambda address,size:memory[address,size]


def test_actual22_phase_records_keep_personal_absence_bits_and_role_rules_separate():
    f=actual();assert f['native_capture_date']=='2030-11-11'
    assert all(p['person_key_count']==0 for p in f['personal_map_context']['phases'].values())
    rows=[source.decode_record(offline_read(r)[1],offline_read(r)[0],r['phase'])for r in f['base_position_records']]
    assert len(rows)==22
    for index in(1,4):
        row=rows[index]
        assert row['get_forward_often_explicitly_selected'] is False
        assert row['hold_position_explicitly_selected'] is False
        assert [p['native_id']for p in row['selected_options']]==[3,7,15]
        assert row['get_forward_often_role_rule']['selected_by_role_rule'] is True
        assert row['get_forward_often_role_rule']['native_rule_state']==3
        assert row['effective_instruction_state']=='not_established'
    names=[f['phase_assignments']['in_possession'][i]['person']['display_name']for i in(1,4)]
    assert names==['Alberto Costa','El Hadji Malick Diouf']
    assert f['native_option_groups']['3']['option_ids']==[22,0,23]


def synthetic(role=0x400004,position=4,bits=0,key=None):
    raw=bytearray(72);struct.pack_into('<I',raw,0,position);struct.pack_into('<QQQ',raw,8,0x10000,0x10018,0x10018)
    struct.pack_into('<Q',raw,64,role);data=struct.pack('<QQII',role&source.ROLE_KEY_MASK if key is None else key,bits,0,255)
    return bytes(raw),lambda address,size:data if(address,size)==(0x10000,24)else b''


def test_explicit_positive_get_forward_is_distinct_from_native_role_default_and_hold():
    raw,read=synthetic(bits=1<<22)
    r=source.decode_record(read,raw,'in_possession')
    assert r['get_forward_often_explicitly_selected'] is True
    assert r['get_forward_often_role_rule']['selected_by_role_rule'] is False
    assert r['selected_options']==[{'native_id':22,'native_symbol':'PI_GET_FORWARD_OFTEN'}]
    raw,read=synthetic(bits=1<<23)
    r=source.decode_record(read,raw,'in_possession')
    assert r['hold_position_explicitly_selected'] is True and r['get_forward_often_explicitly_selected'] is False


def test_missing_role_key_is_not_a_clear_bit_and_wrong_entry_is_not_borrowed():
    raw,read=synthetic(role=0x400008,key=4,bits=1<<22)
    r=source.decode_record(read,raw,'in_possession')
    assert r['state']=='no_stored_current_role_entry'
    assert r['selected_option_bits_hex'] is None and r['get_forward_often_explicitly_selected'] is None
    assert r['get_forward_often_role_rule']['selected_by_role_rule'] is True


def test_unknown_role_rule_phase_and_high_instruction_bits_remain_unknown():
    raw,read=synthetic(role=0x800008,bits=(1<<3)|(1<<55))
    r=source.decode_record(read,raw,'in_possession')
    assert r['get_forward_often_role_rule']['selected_by_role_rule'] is None
    assert r['unmapped_selected_bit_indices']==[55]
    raw,read=synthetic(role=0x400008)
    assert source.decode_record(read,raw,'out_of_possession')['get_forward_often_role_rule']['native_rule_state'] is None


@pytest.mark.parametrize('mode',['unaligned','oversized','truncated','duplicate'])
def test_broken_instruction_source_never_becomes_empty_selection(mode):
    raw,read=synthetic();raw=bytearray(raw)
    if mode=='unaligned':struct.pack_into('<Q',raw,8,0x10001)
    elif mode=='oversized':struct.pack_into('<QQ',raw,16,0x10000+129*24,0x10000+129*24)
    elif mode=='truncated':read=lambda a,n:b'x'
    else:
        struct.pack_into('<QQ',raw,16,0x10030,0x10030);read=lambda a,n:struct.pack('<QQII',4,0,0,255)*2
    with pytest.raises(ValueError):source.decode_record(read,bytes(raw),'in_possession')


def initialize_native(c):
    memory,base=c['memory'],c['base']
    for at,data in source.NATIVE_SPANS+source.ROLE_RULE_SPANS:memory.put(base+at,data)
    memory.pack(base+0x56a0c60+72,'<QQ',0xf0000,3);memory.pack(0xf0000,'<III',22,0,23)


def test_public_projection_keeps_both_phases_and_stored_personal_positive_separate(personal):
    initialize_native(personal)
    # Other bytes default to zero in the sparse fixture. No getter creates keys.
    node(personal,'in_possession',1,[record(4,1,0x400004)])
    personal['memory'].pack(0xc0000+8,'<QQQ',0xe0010,0xe0028,0xe0028)
    personal['memory'].put(0xe0010,struct.pack('<QQII',4,1<<22,0,255))
    read=world.ReadSet(personal['memory'].read)
    r=source.inspect(read,personal['base'],personal['coach']);read.verify()
    row=r['phases']['in_possession']['assignments'][1]
    assert row['personal_override']['state']=='present'
    assert row['stored_personal_instruction_records']['exact_position_lookup']['stored_selection']['raw_role_word']=='0x0000000000400004'
    assert row['stored_personal_instruction_records']['exact_position_lookup']['stored_selection']['get_forward_often_explicitly_selected'] is True
    assert row['stored_base_role']['raw_encoding']=='0x0000000000000001'
    assert r['effective_match_instructions'] is None


def test_absent_working_creator_never_reads_native_groups_or_prepared_fallback(personal,monkeypatch):
    personal['memory'].pack(0x20000,'<Q',0)
    monkeypatch.setattr(source,'verify_native',Mock(side_effect=AssertionError))
    r=source.inspect(personal['memory'].read,personal['base'],personal['coach'])
    assert r['player_instruction_source_state']=='unavailable_working_assignment_source'
    assert all(p['assignments'] is None for p in r['phases'].values())


def test_native_guards_and_forward_group_ids_fail_closed(personal):
    initialize_native(personal);source.verify_native(personal['memory'].read,personal['base'])
    personal['memory'].pack(0xf0000,'<I',21)
    with pytest.raises(ValueError,match='option IDs'):source.verify_native(personal['memory'].read,personal['base'])
    initialize_native(personal);at,data=source.ROLE_RULE_SPANS[0]
    personal['memory'].put(personal['base']+at,bytes([data[0]^1]))
    with pytest.raises(ValueError,match='native binding'):source.verify_native(personal['memory'].read,personal['base'])


def test_readonly_tool_schema_and_source_provenance_description(monkeypatch):
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp import player_instruction_tools as tools
    calls=[];monkeypatch.setattr(tools,'capture',lambda *a:(calls.append(a)or {'player_instruction_source_state':'unavailable'}))
    async def run():
        mcp=FastMCP('test');tools.register_player_instruction_tools(mcp,None)
        tool,=await mcp.list_tools()
        assert tool.name=='fm_get_managed_player_instructions' and tool.annotations.readOnlyHint
        assert set(tool.inputSchema['properties'])=={'session_id','coach_name','phase'}
        assert 'clear stored bit does not imply' in tool.description
        await mcp.call_tool(tool.name,{'session_id':'s'})
        assert calls==[(None,'s',None,'both')]
    asyncio.run(run())
