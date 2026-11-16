import struct

import pytest

from fm_live_mcp import players, virtual, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_players import memory
from test_world import world_memory


@pytest.fixture
def virtual_memory(world_memory, memory):
    m = world_memory
    tables = tuple(m['base'] + rva for rva in players.RVA)
    for offset, table in zip((0, 0x140, 0x388), tables):
        struct.pack_into('<Q', memory, 0x1000 + offset, table)
    m['put'](0x1000, memory[0x1000:])
    regular = m['allocate'](players.SIZE)
    m['put'](regular, memory[0x1000:0x1000 + players.SIZE])
    m['put'](regular + 0x394, struct.pack('<II', 678, 678))
    compact = m['typed']('virtual_player', 64)
    m['q'](compact + 0x20, m['base'] + virtual.PERSON_RVA)
    ti = m['allocate'](16)
    name = m['allocate'](21)
    m['put'](name, b'N2db14VIRTUAL_PLAYERE\0')
    m['q'](ti + 8, name)
    m['put'](m['base'] + virtual.PERSON_RVA - 16, struct.pack('<qQ', -32, ti))
    m['put'](compact + 0x2C, struct.pack('<II', 12345, 12345))
    manager = m['typed']('virtual_manager', 0x2A8)
    m['q'](m['base'] + virtual.MANAGER_ROOT, manager)
    m['vec'](manager + 8, [0x1000])
    m['put'](0x1390, struct.pack('<III', 0xFFFFFFFF, 12345, 0))
    m['put'](compact + 8, struct.pack('<I', 777))
    m['put'](m['team'] + 8, struct.pack('<I', 777))
    m['q'](0x1128, m['team'])
    m['vec'](m['team'] + 0x38, [regular, compact])
    m.update(tables=tables, compact=compact, cache_manager=manager, regular=regular)
    return m


def decode(m, include_clubs=False):
    snapshot = world.ReadSet(m['read'])
    result = virtual.decode(snapshot, m['compact'], m['tables'], include_clubs)
    snapshot.verify()
    return result


def test_virtual_resolves_identity_checked_cached_profile(virtual_memory):
    m = virtual_memory
    record, identity = decode(m, True)
    assert record['name'] == 'Test Müller'
    assert record['birth_date'] == '2000-02-29'
    assert record['attributes']['dribbling'] == 16
    assert record['record_kind'] == 'virtual'
    assert identity == ('virtual', 12345, 'Test', 'Müller', '2000-02-29', 12345)
    assert record['clubs']['contract_club'] is None
    assert record['clubs']['current_club'] is None
    assert record['clubs']['roster_club']['name'] == 'Test United'
    # Cached virtual profiles must never pass the ordinary player search decoder.
    with pytest.raises(ValueError, match='non-table cache'):
        players.decode(m['read'], 0x1000, m['tables'])


@pytest.mark.parametrize('fault', ['compact_identity', 'person_type', 'person_displacement',
                                  'cold_cache', 'cache_bounds', 'cache_reused', 'cache_duplicate',
                                  'manager_type', 'contract', 'team_identity'])
def test_invalid_virtual_paths_fail_closed(virtual_memory, fault):
    m = virtual_memory
    q, put = m['q'], m['put']
    if fault == 'compact_identity': put(m['compact'] + 0x2C, bytes(4))
    if fault == 'person_type': q(m['compact'] + 0x20, 0)
    if fault == 'person_displacement': q(m['base'] + virtual.PERSON_RVA - 16, 0)
    if fault == 'cold_cache': put(m['compact'] + 0x14, struct.pack('<h', -1))
    if fault == 'cache_bounds': put(m['compact'] + 0x14, struct.pack('<h', 3))
    if fault == 'cache_reused': put(0x1394, struct.pack('<I', 987))
    if fault == 'cache_duplicate': put(0x1398, struct.pack('<I', 12345))
    if fault == 'manager_type': q(m['cache_manager'], m['base'] + world.TYPES['team'][0])
    if fault == 'contract': q(0x12F0, m['contract'])
    if fault == 'team_identity': put(m['team'] + 8, struct.pack('<I', 778))
    with pytest.raises(ValueError): decode(m, True)


def test_virtual_recheck_rejects_cache_eviction(virtual_memory):
    m = virtual_memory
    reads = 0
    def read(a, n):
        nonlocal reads
        if a == m['compact'] and n == 64:
            reads += 1
            if reads == 2:
                m['put'](m['compact'] + 0x14, struct.pack('<h', -1))
        return m['read'](a, n)
    with pytest.raises(ValueError, match='changed'):
        virtual.decode(read, m['compact'], m['tables'])


def bind(bridge, monkeypatch, m):
    # This older virtual/cache fixture isolates field decoding, with no Mach-O.
    # Actual runtime enrollment is covered by test_core_roster_publication.
    bridge.plugin_identity = ('isolated-virtual-fields', b'fixture runtime')
    monkeypatch.setattr(players, 'verify_runtime', lambda read, base, uuid: m['tables'])
    monkeypatch.setattr(bridge, '_player_layout', lambda p: m['tables'])
    monkeypatch.setattr(bridge, '_read_memory', lambda p,a,n: m['read'](a,n))


def test_team_queries_include_every_record_and_fresh_virtual_read(bridge, monkeypatch, virtual_memory):
    m = virtual_memory
    bind(bridge, monkeypatch, m)
    listing = bridge.get_club_squads(bridge.session)
    assert len(listing['squads']) == 1
    team = listing['squads'][0]
    assert team['count'] == 2 and team['is_managed_team'] is True
    result = bridge.get_team_squad(bridge.session, team['team_ref'])
    assert result['count'] == 2 and result['virtual_player_count'] == 1
    virtual_record = next(p for p in result['players'] if p.get('record_kind') == 'virtual')
    fresh = bridge.get_player(bridge.session, virtual_record['player_ref'])
    assert fresh['player']['record_kind'] == 'virtual'
    assert fresh['player']['attributes'] == virtual_record['attributes']
    bridge.detach()
    assert bridge.team_refs == {}
    with pytest.raises(BridgeError): bridge.get_team_squad('old', team['team_ref'])


def test_bad_virtual_record_returns_no_partial_roster_or_refs(bridge, monkeypatch, virtual_memory):
    m = virtual_memory
    bind(bridge, monkeypatch, m)
    team = bridge.get_club_squads(bridge.session)['squads'][0]
    m['put'](0x1394, struct.pack('<I', 99))
    with pytest.raises(BridgeError, match='no partial roster'):
        bridge.get_team_squad(bridge.session, team['team_ref'])
    assert bridge.player_refs == {}


def test_virtual_reference_binds_independent_secondary_identity(bridge, monkeypatch, virtual_memory):
    m = virtual_memory
    bind(bridge, monkeypatch, m)
    m['put'](m['compact'] + 0x30, bytes(4))
    team = bridge.get_club_squads(bridge.session)['squads'][0]
    row = next(p for p in bridge.get_team_squad(bridge.session, team['team_ref'])['players']
               if p.get('record_kind') == 'virtual')
    ref = row['player_ref']
    assert bridge.get_player(bridge.session, ref)['player']['name'] == row['name']
    m['put'](m['compact'] + 0x30, struct.pack('<I', 999))
    with pytest.raises(BridgeError, match='identity changed'):
        bridge.get_player(bridge.session, ref)
    assert ref not in bridge.player_refs


def test_team_reference_rejects_identity_reuse(bridge, monkeypatch, virtual_memory):
    m = virtual_memory
    bind(bridge, monkeypatch, m)
    team = bridge.get_club_squads(bridge.session)['squads'][0]
    m['put'](m['team'] + 8, struct.pack('<I', 888))
    with pytest.raises(BridgeError, match='Team identity changed'):
        bridge.get_team_squad(bridge.session, team['team_ref'])
    assert bridge.player_refs == {}
    assert team['team_ref'] not in bridge.team_refs
