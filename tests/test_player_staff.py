import struct

import pytest

from fm_live_mcp import players, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import database_memory, bind, receipt
from test_players import memory
from test_world import world_memory


@pytest.fixture
def staff_memory(database_memory):
    m = database_memory
    old = m['read'](0x1000, players.SIZE)
    raw = bytearray(0x4A0)
    raw[:0x278] = old[:0x278]
    raw[0x370:] = old[0x278:]
    m['put'](0x1000, raw)
    for offset, rva in zip((0, 0x140, 0x480), players.STAFF_RVA):
        m['q'](0x1000 + offset, m['base'] + rva)
    for rva, displacement in ((players.STAFF_RVA[0], 0), (players.STAFF_RVA[2], -0x480)):
        info = m['allocate'](16)
        name = b'N2db28ACTUAL_PLAYER_AND_NON_PLAYERE\0'
        name_address = m['allocate'](len(name))
        m['put'](name_address, name)
        m['q'](info + 8, name_address)
        m['put'](m['base'] + rva - 16, struct.pack('<qQ', displacement, info))
    for slot, adjustment in ((40, 0x150), (41, 0x158), (42, 0x160), (55, 0x1C8)):
        m['q'](m['base'] + players.RVA[2] + slot * 8, 0x8000 + slot * 8)
        m['q'](m['base'] + players.STAFF_RVA[2] + slot * 8, 0x8000 + slot * 8)
        m['put'](m['base'] + players.STAFF_RVA[2] - adjustment, struct.pack('<q', -0x110))
    m['vec'](m['headers']['people'], [0x1480])
    m['vec'](m['team'] + 0x38, [0x1000])
    contract = m['typed']('full_contract', 32)
    m['q'](contract + 8, 0x1480)
    m['q'](contract + 16, m['team'])
    m['q'](contract + 24, m['team'])
    m['q'](0x13E8, contract)
    m['q'](0x1128, m['team'])
    m['staff_contract'] = contract
    return m


def test_staff_uses_shared_fields_but_separate_identity_and_contract_owner(bridge, monkeypatch, staff_memory):
    m = staff_memory
    bind(bridge, monkeypatch, m)
    roster = bridge.get_managed_squad(bridge.session, include_clubs=True)
    player = roster['players'][0]
    assert player['name'] == 'Test Müller' and player['birth_date'] == '2000-02-29'
    assert player['attributes']['dribbling'] == 16
    assert player['record_kind'] == 'player_staff'
    assert player['clubs']['current_club']['name'] == 'Test United'
    monkeypatch.setattr(bridge, '_run', lambda *a: receipt(player_staff_examined=1))
    found = bridge.find_save_players(bridge.session, 'Test')
    fresh = bridge.get_player(bridge.session, found['players'][0]['player_ref'], include_clubs=True)['player']
    assert fresh['attributes'] == player['attributes'] and fresh['clubs'] == player['clubs']


@pytest.mark.parametrize('fault', ['primary_type', 'person_type', 'displacement', 'getter', 'adjustment', 'identity', 'contract_owner'])
def test_wrong_staff_layout_rejects_entire_roster(bridge, monkeypatch, staff_memory, fault):
    m = staff_memory
    bind(bridge, monkeypatch, m)
    if fault == 'primary_type': m['q'](0x1000, 0)
    if fault == 'person_type': m['q'](0x1480, m['base'] + players.RVA[2])
    if fault == 'displacement': m['q'](m['base'] + players.STAFF_RVA[2] - 16, 0)
    if fault == 'getter': m['q'](m['base'] + players.STAFF_RVA[2] + 40*8, 0)
    if fault == 'adjustment': m['q'](m['base'] + players.STAFF_RVA[2] - 0x150, 0)
    if fault == 'identity': m['put'](0x148c, bytes(4))
    if fault == 'contract_owner': m['q'](m['staff_contract'] + 8, 0x1388)
    with pytest.raises(BridgeError): bridge.get_managed_squad(bridge.session, include_clubs=True)
    assert bridge.player_refs == {}
