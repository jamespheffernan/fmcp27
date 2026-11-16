import struct

import pytest

from fm_live_mcp import player_profile, players, virtual, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import database_memory, bind
from test_player_staff import staff_memory
from test_players import memory, reader
from test_virtual import virtual_memory
from test_world import world_memory
from personality_fixture import populate as populate_personality, populate_virtual


def populate(m, address):
    table = players.u64(m['read'](address, 8))
    populate_personality(m, address, 0x480 if table == m['base'] + players.STAFF_RVA[0] else 0x388)
    for slot, getter in player_profile.GETTERS.items():
        m['q'](table + slot*8, m['base'] + getter)
    m['put'](address + 0x25C, struct.pack('<hh', 150, 180))
    m['put'](address + 0x270, b'\x80')
    for i, fields in enumerate(player_profile.POSITIONS.values()):
        m['put'](address + fields[0], bytes([i + 1]))
    for mapping in (player_profile.GOALKEEPING, player_profile.HIDDEN, player_profile.FEET):
        for offset, _, _ in mapping.values(): m['put'](address + offset, bytes([77]))


@pytest.fixture(params=['database_memory', 'staff_memory', 'virtual_memory'])
def profile_memory(request):
    m = request.getfixturevalue(request.param)
    populate(m, 0x1000)
    if request.param == 'virtual_memory':
        populate_virtual(m)
        populate(m, m['regular'])
        for slot, getter in player_profile.VIRTUAL_GETTERS.items():
            m['q'](m['base'] + world.TYPES['virtual_player'][0] + slot*8, m['base'] + getter)
    if request.param != 'virtual_memory':
        m['vec'](m['team'] + 0x38, [0x1000])
    m['is_virtual'] = request.param == 'virtual_memory'
    return m


def decode(m):
    if m['is_virtual']:
        return virtual.decode(m['read'], m['compact'], m['tables'], include_profile=True)[0]
    return players.decode(m['read'], 0x1000, m['tables'], include_profile=True)[0]


def test_profile_native_groups_and_ranges(profile_memory):
    m = profile_memory
    result = decode(m)['profile']
    assert result['ability']['current'] == 150 and result['ability']['potential'] == 180
    assert result['ability']['potential_state'] == 'fixed'
    assert len(result['positions']) == 14 and result['positions']['striker'] == 12
    assert result['goalkeeping']['reflexes'] == 15 and len(result['goalkeeping']) == 11
    assert result['hidden_attributes']['consistency'] == 15 and len(result['hidden_attributes']) == 5
    assert result['feet'] == {'left': 15, 'right': 15}
    m['put'](0x125E, struct.pack('<h', -95))
    ability = decode(m)['profile']['ability']
    assert ability['potential'] is None and ability['potential_native_code'] == -95
    assert ability['potential_range'] == [160, 190] and ability['potential_state'] == 'range'
    m['put'](0x125E, struct.pack('<h', -11))
    ability = decode(m)['profile']['ability']
    assert ability['potential'] is None and ability['potential_range'] is None
    assert ability['potential_state'] == 'unmapped_range'


@pytest.mark.parametrize('fault', ['current', 'potential', 'position', 'rating', 'getter', 'scale'])
def test_profile_rejects_invalid_values_and_dispatch(profile_memory, fault):
    m = profile_memory
    if fault == 'current': m['put'](0x125C, struct.pack('<h', 201))
    if fault == 'potential': m['put'](0x125E, struct.pack('<h', -101))
    if fault == 'position': m['put'](0x1148, bytes([21]))
    if fault == 'rating': m['put'](0x116C, bytes([101]))
    if fault == 'getter': m['q'](players.u64(m['read'](0x1000, 8)) + 16*8, 0)
    if fault == 'scale': m['put'](0x1270, bytes([0]))
    with pytest.raises(ValueError): decode(m)


def test_profile_virtual_dispatch_checked(virtual_memory):
    m = virtual_memory
    populate(m, 0x1000)
    m['q'](m['base'] + world.TYPES['virtual_player'][0] + 6*8, 0)
    with pytest.raises(ValueError, match='getter'):
        virtual.decode(m['read'], m['compact'], m['tables'], include_profile=True)


def test_profile_defaults_fresh_routes_and_mutation(bridge, monkeypatch, profile_memory):
    m = profile_memory
    bind(bridge, monkeypatch, m)
    roster = bridge.get_managed_squad(bridge.session)
    assert roster['count'] > 0 and all('profile' not in p for p in roster['players'])
    roster = bridge.get_managed_squad(bridge.session, include_profile=True)
    for row in roster['players']:
        assert bridge.get_player(bridge.session, row['player_ref'], include_profile=True)['player']['profile'] == row['profile']
    team = bridge.get_club_squads(bridge.session)['squads'][0]
    assert bridge.get_team_squad(bridge.session, team['team_ref'], include_profile=True)['count'] == roster['count']
    original = player_profile.decode
    def mutate(*a, **kw):
        result = original(*a, **kw)
        for address in {0x1000, m.get('regular', 0x1000)}:
            m['put'](address + 0x25C, struct.pack('<h', 151))
        return result
    monkeypatch.setattr(player_profile, 'decode', mutate)
    with pytest.raises(BridgeError, match='changed'):
        bridge.get_managed_squad(bridge.session, include_profile=True)


def test_profile_options_strict(bridge, monkeypatch, profile_memory):
    bind(bridge, monkeypatch, profile_memory)
    for value in (1, 'true', None):
        with pytest.raises(BridgeError, match='boolean'): bridge.get_player(bridge.session, 'ref', include_profile=value)
        with pytest.raises(BridgeError, match='boolean'): bridge.get_team_squad(bridge.session, 'ref', include_profile=value)
        with pytest.raises(BridgeError, match='boolean'): bridge.get_managed_squad(bridge.session, include_profile=value)


def test_native_scaling_branches_and_zero(memory):
    memory[0x1157] = 0
    assert players.decode(reader(memory), 0x1000, (0x11100, 0x22200, 0x33300))[0]['attributes']['crossing'] == 1
    for offset in players.ATTRIBUTES.values(): memory[0x1148 + offset] = 17
    memory[0x1270] = 0
    result = players.decode(reader(memory), 0x1000, (0x11100, 0x22200, 0x33300))[0]
    assert set(result['attributes'].values()) == {17} and result['attribute_scale'] == '0–20'
    memory[0x1157] = 0
    assert players.decode(reader(memory), 0x1000, (0x11100, 0x22200, 0x33300))[0]['attributes']['crossing'] == 0
    for raw in range(101):
        expected = max(1, min(20, (raw * 26215 + 52430) >> 17))
        assert player_profile.rating(raw, True) == expected


def test_profile_queries_ranges_sort_boundaries_and_loans(bridge, monkeypatch):
    def row(name, current, potential, gk, reflexes, loan=False, virtual=False):
        return {'display_name': name, 'birth_date': '2000-01-01', 'player_ref': name,
                'record_kind': 'virtual' if virtual else 'actual', 'attributes': {'passing': 12},
                'clubs': {'on_loan': loan}, 'profile': {'ability': {'current': current, 'potential': potential,
                 'potential_state': 'range' if potential is None else 'fixed',
                 'potential_native_code': -95 if potential is None else potential,
                 'potential_range': [160, 190] if potential is None else None},
                 'positions': {'goalkeeper': gk}, 'goalkeeping': {'reflexes': reflexes}}}
    rows = [row('A', 150, 180, 20, 15), row('B', 140, 170, 20, 14), row('C', 170, None, 20, 18),
            row('D', 180, 190, 1, 18), row('E', 190, 195, 20, 20, loan=True), row('F', 195, 200, 20, 20, virtual=True)]
    for index, player in enumerate(rows):
        player.update(roster_index=index, profile_state='cached' if player['record_kind'] == 'virtual' else 'stored_direct')
    monkeypatch.setattr(bridge, 'get_team_squad', lambda *a, **kw: {
        'observed_at': 'now', 'save': {}, 'club': {}, 'label': 'Senior', 'count': len(rows), 'players': rows, 'limitations': ''})
    result = bridge.query_team_players(bridge.session, 'team', minimum_attributes={'passing': 12},
        minimum_profile={'positions.goalkeeper': 15, 'goalkeeping.reflexes': 15}, sort_by='ability.current', loan_status='not_on_loan', limit=1)
    assert result['matched_count'] == 2 and result['truncated'] and result['players'][0]['display_name'] == 'C'
    result = bridge.query_team_players(bridge.session, 'team', minimum_profile={'ability.potential': 180}, sort_by='ability.potential', limit=1)
    assert result['matched_count'] == 3 and result['unclassified_count'] == 1
    assert result['unclassified_players'][0]['player']['display_name'] == 'C'
    assert result['players'][0]['display_name'] == 'E'
    result = bridge.query_team_players(bridge.session, 'team', sort_by='ability.current', include_virtual=True)
    assert result['players'][0]['display_name'] == 'F'


@pytest.mark.parametrize('args', [{'minimum_profile': []}, {'minimum_profile': {'ability.current': True}},
    {'minimum_profile': {'ability.current': 201}}, {'minimum_profile': {'positions.striker': 21}},
    {'minimum_profile': {'feet.left': -1}}, {'minimum_profile': {'unknown': 1}}, {'sort_by': 'ability.unknown'}])
def test_profile_query_validation_precedes_reads(bridge, monkeypatch, args):
    monkeypatch.setattr(bridge, 'get_team_squad', lambda *a, **kw: pytest.fail('read before validation'))
    with pytest.raises(BridgeError): bridge.query_team_players(bridge.session, 'ref', **args)
