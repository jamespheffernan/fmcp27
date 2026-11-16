import struct

import pytest

from fm_live_mcp import players, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_players import memory, reader, TABLES


@pytest.fixture
def world_memory():
    cells = {}
    next_address = 0x10000
    base = 0x10000000
    def put(a, value):
        cells.update({a + i: byte for i, byte in enumerate(value)})
    def allocate(size):
        nonlocal next_address
        a = next_address
        next_address += (size + 7) & ~7
        put(a, bytes(size))
        return a
    def q(a, value):
        put(a, struct.pack('<Q', value))
    def text(value):
        data = value.encode()
        a = allocate(len(data) + 5)
        put(a, struct.pack('<I', len(data)) + data + b'\0')
        return a
    def typed(kind, size):
        a = allocate(size)
        rva, name = world.TYPES[kind]
        table = base + rva
        ti = allocate(16)
        name_address = allocate(len(name) + 1)
        put(name_address, name + b'\0')
        q(ti + 8, name_address)
        put(table - 16, struct.pack('<qQ', 0, ti))
        q(a, table)
        return a
    def vec(a, values):
        start = allocate(max(8, len(values) * 8))
        for i, value in enumerate(values):
            q(start + i * 8, value)
        put(a, struct.pack('<QQQ', start, start + 8 * len(values), start + 8 * len(values)))
    for rva, displacement in ((players.RVA[0],0x278),(players.STAFF_RVA[0],0x370)):
        q(base+rva+93*8,base+0xCFFFFC)
        put(base+rva-0x20,struct.pack('<q',displacement))
    for slot,getter in ((18,0x13781B8),(19,0x13781C0)):
        q(base+world.TYPES['loan_contract'][0]+slot*8,base+getter)
    q(base+world.TYPES['trial_contract'][0]+18*8,base+0x1006B44)
    game = typed('game', 0xD0)
    save = typed('save', 0x78)
    manager = typed('manager', 0x568)
    team = typed('team', 0xB8)
    club = typed('club', 0x170)
    user = allocate(0x150)
    info = allocate(24)
    contract = allocate(32)
    q(base + world.GAME_ROOT, game)
    q(base + world.SAVE_ROOT, save)
    q(save + 0x28, text('Synthetic career'))
    put(game + 0x38, struct.pack('<II', (2025 << 16) | 296, 2223821))
    put(game + 0xC8, struct.pack('<I', 418))
    put(save + 0x70, struct.pack('<I', (2030 << 16) | 261))
    put(base + world.CURRENT_DATE, struct.pack('<I', (2030 << 16) | 262))
    q(game + 0x58, info)
    vec(info, [user])
    q(user + 0x148, manager)
    vec(user + 0xC0, [manager])
    for offset, name in [(0x458, 'Test'), (0x460, 'Coach')]:
        handle = allocate(8)
        q(handle, text(name))
        q(manager + offset, handle)
    q(manager + 0x4B0, contract)
    q(contract + 8, manager + 0x548)
    q(contract + 0x10, team)
    q(contract + 0x18, team)
    q(team + 0x80, manager)
    q(team + 0x30, club)
    put(club + 0xC, struct.pack('<II', 688, 688))
    q(club + 0xC0, text('Test United'))
    q(club + 0xC8, text('Test'))
    vec(club + 0x18, [team])
    def read(a, n):
        return bytes(cells[a + i] for i in range(n))
    return locals()


def test_loaded_roots_resolve_metadata_and_coach_club(world_memory):
    m = world_memory
    snapshot = world.ReadSet(m['read'])
    record, identity = world.loaded(snapshot, m['base'])
    snapshot.verify()
    assert record['name'] == 'Synthetic career'
    assert record['created_date'] == '2025-10-23'
    assert record['last_saved_date'] == '2030-09-18'
    assert record['current_date'] == '2030-09-19'
    assert record['save_count'] == 418
    assert record['coaches'][0]['name'] == 'Test Coach'
    assert record['coaches'][0]['club']['name'] == 'Test United'
    assert 'game_date' not in record


@pytest.mark.parametrize('failure', ['team_manager', 'contract_owner', 'contract_team', 'club_identity', 'type', 'user_manager'])
def test_rejects_broken_root_relationships(world_memory, failure):
    m = world_memory
    q = m['q']
    if failure == 'team_manager': q(m['team'] + 0x80, m['manager'] + 8)
    if failure == 'contract_owner': q(m['contract'] + 8, m['manager'])
    if failure == 'contract_team': q(m['contract'] + 0x18, m['team'] + 8)
    if failure == 'club_identity': m['put'](m['club'] + 0xC, bytes(4))
    if failure == 'type': q(m['game'], m['base'] + world.TYPES['team'][0])
    if failure == 'user_manager': m['vec'](m['user'] + 0xC0, [])
    with pytest.raises(ValueError): world.loaded(m['read'], m['base'])


def test_unloaded_career_reports_missing_name_without_reading_null(world_memory):
    m = world_memory
    m['q'](m['save'] + 0x28, 0)
    with pytest.raises(ValueError, match='No named career is available'):
        world.loaded(m['read'], m['base'])


def test_recheck_detects_mutation(world_memory):
    m = world_memory
    snapshot = world.ReadSet(m['read'])
    world.loaded(snapshot, m['base'])
    m['put'](m['game'] + 0xC8, struct.pack('<I', 419))
    with pytest.raises(ValueError, match='changed'): snapshot.verify()


@pytest.mark.parametrize('year,day', [(0, 0), (1849, 1), (2201, 1), (2030, 0), (2030, 366), (1900, 1)])
def test_current_date_rejects_invalid_or_unset_values(world_memory, year, day):
    m = world_memory
    m['put'](m['base']+world.CURRENT_DATE, struct.pack('<I', year << 16 | day))
    with pytest.raises(ValueError, match='date|day'):
        world.loaded(m['read'], m['base'])


def test_current_date_change_during_snapshot_is_rejected(world_memory):
    m = world_memory
    snapshot = world.ReadSet(m['read'])
    world.loaded(snapshot, m['base'])
    m['put'](m['base']+world.CURRENT_DATE, struct.pack('<I', 2030 << 16 | 263))
    with pytest.raises(ValueError, match='changed'):
        snapshot.verify()


def test_date_progression_preserves_career_identity_and_existing_refs(bridge, monkeypatch, world_memory):
    m = world_memory
    monkeypatch.setattr(bridge, '_player_layout', lambda p: (m['base']+players.RVA[0], 0, 0))
    monkeypatch.setattr(bridge, '_read_memory', lambda p,a,n: m['read'](a,n))
    first = bridge.get_save(bridge.session)['save']
    identity = bridge.world_identity
    bridge.player_refs['existing'] = {'marker': True}
    m['put'](m['base']+world.CURRENT_DATE, struct.pack('<I', 2030 << 16 | 263 | 37 << 9))
    fresh = bridge.get_save(bridge.session)['save']
    assert first['current_date'] == '2030-09-19' and fresh['current_date'] == '2030-09-20'
    assert fresh['last_saved_date'] == first['last_saved_date'] == '2030-09-18'
    assert bridge.world_identity == identity
    assert bridge.player_refs['existing'] == {'marker': True}


@pytest.mark.parametrize('values', [(4096, 4088, 4096), (4096, 4097, 4104), (4096, 8192, 8192)])
def test_vector_rejects_bad_bounds(values):
    with pytest.raises(ValueError): world.vector(lambda a,n: struct.pack('<QQQ', *values), 1, 64)


def test_save_change_discards_session_and_references(bridge, monkeypatch, world_memory):
    m = world_memory
    tables = (m['base'] + players.RVA[0], 0, 0)
    monkeypatch.setattr(bridge, '_player_layout', lambda p: tables)
    monkeypatch.setattr(bridge, '_read_memory', lambda p,a,n: m['read'](a,n))
    session = bridge.session
    public = bridge.get_save(session)
    assert 'team_address' not in public['save']['coaches'][0]
    assert 'manager_address' not in public['save']['coaches'][0]
    bridge.player_refs['old'] = {}
    m['q'](m['save'] + 0x28, m['text']('Other career'))
    with pytest.raises(BridgeError, match='identity changed'): bridge.get_save(session)
    assert bridge.session is None
    assert bridge.player_refs == {}


def test_squad_returns_all_records_or_error_without_partial_refs(bridge, monkeypatch, memory):
    record = {'coaches': [{'name': 'Test Coach', 'club': {'name': 'Test'}, 'team_address': 0x4000}]}
    monkeypatch.setattr(bridge, '_player_layout', lambda p: TABLES)
    snapshot = world.ReadSet(reader(memory))
    monkeypatch.setattr(bridge, '_world_state', lambda *a: (snapshot, record, ()))
    # Deliberately isolated player projection; this fixture has no runtime image.
    bridge.world_identity = ()
    bridge.plugin_identity = ('isolated-world-fields', b'fixture runtime')
    monkeypatch.setattr(players, 'verify_runtime', lambda *_: TABLES)
    struct.pack_into('<QQQ', memory, 0x4038, 0x4100, 0x4108, 0x4108)
    struct.pack_into('<Q', memory, 0x4100, 0x1000)
    result = bridge.get_managed_squad(bridge.session)
    assert result['count'] == 1
    assert result['players'][0]['name'] == 'Test Müller'
    assert result['complete_native_roster'] is True
    assert 'team_address' not in result['save']['coaches'][0]
    bridge.player_refs.clear()
    snapshot = world.ReadSet(reader(memory))
    struct.pack_into('<Q', memory, 0x1000, 0)
    with pytest.raises(BridgeError, match='no partial roster'): bridge.get_managed_squad(bridge.session)
    assert bridge.player_refs == {}
