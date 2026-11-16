import struct

import pytest

from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import database_memory, bind
from test_players import memory
from test_world import world_memory


def bind_club(bridge, monkeypatch, m):
    bind(bridge, monkeypatch, m)
    m['vec'](m['team'] + 0x38, [0x1000])
    monkeypatch.setattr(bridge, '_run', lambda *a: {
        'matches': [{'address': hex(m['club'])}], 'next_index': 1, 'scanned_records': 1,
        'clubs_examined': 1, 'other_club_records': 0, 'stop_reason': 'table_end'})
    return bridge.find_clubs(bridge.session, 'Test')['clubs'][0]['club_ref']


def test_found_club_roster_reuses_current_squad_decoder(bridge, monkeypatch, database_memory):
    m = database_memory
    ref = bind_club(bridge, monkeypatch, m)
    listing = bridge.get_club_squads(bridge.session, club_ref=ref)
    assert listing['club']['name'] == 'Test United'
    team = listing['squads'][0]['team_ref']
    assert bridge.get_team_squad(bridge.session, team)['players'][0]['name'] == 'Test Müller'
    with pytest.raises(BridgeError, match='either club_ref or coach_name'):
        bridge.get_club_squads(bridge.session, 'Test Coach', ref)
    bridge.detach()
    assert bridge.club_refs == {}


def test_club_membership_changes_expire_club_and_team_refs(bridge, monkeypatch, database_memory):
    m = database_memory
    ref = bind_club(bridge, monkeypatch, m)
    team = bridge.get_club_squads(bridge.session, club_ref=ref)['squads'][0]['team_ref']
    m['vec'](m['headers']['clubs'], [m['manager']])
    with pytest.raises(BridgeError, match='Club reference rejected'):
        bridge.get_club_squads(bridge.session, club_ref=ref)
    with pytest.raises(BridgeError, match='live table index'):
        bridge.get_team_squad(bridge.session, team)
    assert ref not in bridge.club_refs and team not in bridge.team_refs


def test_reused_club_identity_rejects_existing_refs(bridge, monkeypatch, database_memory):
    m = database_memory
    opponent, team_address = m['allocate'](0x170), m['allocate'](0xB8)
    m['put'](opponent, m['read'](m['club'], 0x170))
    m['put'](team_address, m['read'](m['team'], 0xB8))
    m['q'](team_address + 0x30, opponent)
    m['vec'](opponent + 0x18, [team_address])
    m['vec'](m['headers']['clubs'], [opponent])
    m = {**m, 'club': opponent, 'team': team_address}
    ref = bind_club(bridge, monkeypatch, m)
    team = bridge.get_club_squads(bridge.session, club_ref=ref)['squads'][0]['team_ref']
    m['put'](m['club'] + 12, struct.pack('<II', 99, 99))
    with pytest.raises(BridgeError, match='Club identity changed'):
        bridge.get_club_squads(bridge.session, club_ref=ref)
    with pytest.raises(BridgeError, match='club identity changed'):
        bridge.get_team_squad(bridge.session, team)
