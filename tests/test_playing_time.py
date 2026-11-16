import asyncio
import struct

import pytest

from fm_live_mcp import playing_time, players, world
from fm_live_mcp.bridge import BridgeError
from test_assessment_public import (public_assessment_memory, shortlist_public_memory,
    prepared_tactics_memory, bridge, database_memory, memory, team_memory, world_memory)


@pytest.fixture
def agreed_memory(public_assessment_memory):
    m = public_assessment_memory
    person = 0x1388
    table = m['base'] + players.RVA[2]
    m['q'](table + 121 * 8, m['base'] + 0xCB3724)
    m['put'](table - 0x3D8, struct.pack('<q', -0x110))
    contract = m['typed']('full_contract', 0xC8)
    m['q'](person - 0x98, contract)
    m['q'](contract + 8, person)
    m['q'](m['base'] + world.TYPES['full_contract'][0] + 32 * 8, m['base'] + 0x1005C78)
    m['put'](m['base'] + 0x1005C78, bytes.fromhex('00504139c0035fd6'))
    m['put'](contract + 0x54, bytes([2]))
    m['put'](contract + 0xC4, bytes([255]))
    m.update(agreed_contract=contract, agreed_person=person)
    return m


def query(bridge, m):
    return playing_time.get_player_playing_time(bridge, bridge.session, [m['assessment_player_ref']])


def test_canonical_current_contract_field_and_unknown_promises(bridge, agreed_memory):
    m = agreed_memory
    result = query(bridge, m)
    row = result['players'][0]
    assert row['native_identity']['native_id'] == 12345
    assert row['display_name'] == 'Test Müller'
    assert row['agreed_playing_time'] == {'native_code': 2, 'title': 'Important Player',
        'player_type_native_id': 3201, 'translation_id': 482653,
        'label_source': 'compiled_native_english_fallback', 'state': 'decoded_compiled_english'}
    assert result['active_player_promises'] is result['active_club_promises'] is None
    assert result['promises_state'] == 'not_decoded'
    # PMsq at+C4 and neighbouring actual/previous fields cannot select the value.
    m['put'](m['agreed_contract'] + 0x55, bytes([1,22,13]))
    m['put'](m['agreed_contract'] + 0xC4, bytes([1]))
    assert query(bridge,m)['players'][0]['agreed_playing_time'] == row['agreed_playing_time']


@pytest.mark.parametrize('code,title', [(1,'Star Player'),(3,'Regular Starter'),(4,'Squad Player'),
    (6,'Squad Player'),(7,'Fringe Player'),(8,'Fringe Player'),(9,'Emergency Backup'),
    (10,'Breakthrough Prospect'),(11,'Future Prospect'),(20,'Backup'),(22,'Surplus to Requirements')])
def test_opposite_and_equal_label_native_codes_are_preserved(bridge, agreed_memory, code, title):
    m = agreed_memory; m['put'](m['agreed_contract'] + 0x54, bytes([code]))
    result = query(bridge,m)['players'][0]['agreed_playing_time']
    assert result['native_code'] == code and result['title'] == title


@pytest.mark.parametrize('code,state', [(0,'native_empty_display'),(14,'contextual_display_unavailable'),
    (23,'native_scouting_required'),(24,'unmapped_native_code'),(255,'unmapped_native_code')])
def test_no_guessed_label_for_contextual_or_unknown_codes(bridge, agreed_memory, code, state):
    m = agreed_memory; m['put'](m['agreed_contract'] + 0x54, bytes([code]))
    result = query(bridge,m)['players'][0]['agreed_playing_time']
    assert result['native_code'] == code and result['title'] is None and result['state'] == state


def test_null_and_basic_contract_are_explicit_unknowns(bridge, agreed_memory):
    m = agreed_memory
    m['q'](m['agreed_person'] - 0x98,0)
    assert query(bridge,m)['players'][0]['agreed_playing_time']['state'] == 'no_current_contract'
    basic = m['typed']('basic_contract', 0x28)
    m['q'](basic+8,m['agreed_person']);m['q'](m['agreed_person']-0x98,basic)
    result = query(bridge,m)['players'][0]['agreed_playing_time']
    assert result['native_code'] is None and result['state'] == 'basic_contract_playing_time_unavailable'


@pytest.mark.parametrize('fault',['owner','type','person_getter','adjustment','getter','native','canonical_slot','identity'])
def test_wrong_owner_type_accessor_or_canonical_identity_rejects(bridge, agreed_memory, fault):
    m = agreed_memory;table=m['base']+players.RVA[2]
    if fault=='owner':m['q'](m['agreed_contract']+8,0x8000)
    elif fault=='type':m['q'](m['agreed_contract'],m['base']+world.TYPES['club'][0])
    elif fault=='person_getter':m['q'](table+121*8,0)
    elif fault=='adjustment':m['put'](table-0x3D8,struct.pack('<q',0))
    elif fault=='getter':m['q'](m['base']+world.TYPES['full_contract'][0]+32*8,0)
    elif fault=='native':m['put'](m['base']+0x1005C78,b'\0'*8)
    elif fault=='identity':m['put'](m['agreed_person']+12,struct.pack('<I',999))
    else:
        start=struct.unpack('<Q',m['read'](m['headers']['people'],8))[0]
        m['q'](start,m['manager']+0x548)
    with pytest.raises(BridgeError):query(bridge,m)


def test_changed_source_bytes_return_no_partial_result(bridge, agreed_memory, monkeypatch):
    m = agreed_memory; original = playing_time.decode
    def drift(read,base,person):
        result=original(read,base,person)
        m['put'](m['agreed_contract']+0x54,bytes([3]))
        return result
    monkeypatch.setattr(playing_time,'decode',drift)
    with pytest.raises(BridgeError,match='changed during read'):query(bridge,m)


@pytest.mark.parametrize('refs',[[],[''],['x']*101,None,[1]])
def test_query_bounds_and_references_fail_closed(bridge,refs):
    with pytest.raises(BridgeError):playing_time.get_player_playing_time(bridge,bridge.session,refs)


def test_tool_contract_is_readonly_and_explicit():
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp.playing_time_tools import register_playing_time_tools
    mcp=FastMCP('playing time');register_playing_time_tools(mcp,object())
    tool=asyncio.run(mcp.list_tools())[0]
    assert tool.name=='fm_get_player_playing_time' and tool.annotations.readOnlyHint
    assert tool.inputSchema['properties']['player_refs']['maxItems']==100
    assert set(tool.inputSchema['properties'])=={'session_id','player_refs'}
