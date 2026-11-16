import struct

import pytest

from fm_live_mcp import player_health, players, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import database_memory, bind
from test_player_staff import staff_memory
from test_players import memory
from test_virtual import virtual_memory
from test_world import world_memory


def populate(m, address):
    table = players.u64(m['read'](address, 8))
    for slot, getter in ((21, 0xD09BB0), (138, 0xD3012C), (139, 0xD19E70), (141, 0xD3016C)):
        m['q'](table + slot*8, m['base'] + getter)
    m['put'](address + 0x250, struct.pack('<hhh', 9500, -100, 9000))
    m['q'](address + 0xF0, 0)


@pytest.fixture(params=['database_memory', 'staff_memory'])
def health_memory(request):
    m = request.getfixturevalue(request.param)
    populate(m, 0x1000)
    m['vec'](m['team'] + 0x38, [0x1000])
    definition = m['typed']('injury', 0x28)
    m['put'](definition + 8, struct.pack('<III', 0, 17, 17))
    m['q'](definition + 0x18, m['text']('thigh strain'))
    m['q'](definition + 0x20, m['text']('a thigh strain'))
    m['q'](m['base'] + world.TYPES['injury'][0] + 3*8, m['base'] + 0x1329D64)
    m['vec'](m['headers']['injuries'], [definition])
    record = m['allocate'](0x38)
    m['q'](record + 8, definition)
    m['put'](record + 0x20, struct.pack('<I', (2030 << 16) | 0x4000 | 249))
    header = m['allocate'](24)
    m['vec'](header, [record])
    m['q'](0x10F0, header)
    m.update(injury_record=record, injury_definition=definition, injury_header=header)
    return m


def test_health_reads_names_dates_values_defaults_and_freshness(bridge, monkeypatch, health_memory):
    m = health_memory
    bind(bridge, monkeypatch, m)
    plain = bridge.get_managed_squad(bridge.session)
    assert 'health' not in plain['players'][0]
    full = bridge.get_managed_squad(bridge.session, include_health=True)['players'][0]
    health = full['health']
    assert (health['condition'], health['match_sharpness'], health['fatigue']) == (9000, 9500, -100)
    assert health['state'] == 'stored_without_refresh' and health['injury_record_count'] == 1
    assert health['injuries'][0]['name'] == 'thigh strain' and health['injuries'][0]['started'] == '2030-09-06'
    assert bridge.get_player(bridge.session, full['player_ref'], include_health=True)['player']['health'] == health
    m['put'](0x1254, struct.pack('<h', 9100))
    assert bridge.get_player(bridge.session, full['player_ref'], include_health=True)['player']['health']['condition'] == 9100
    m['q'](0x10F0, 0)
    assert bridge.get_player(bridge.session, full['player_ref'], include_health=True)['player']['health']['injuries'] == []


@pytest.mark.parametrize('fault', ['getter', 'condition', 'sharpness', 'vector', 'duplicate', 'type', 'identity', 'membership', 'property', 'date', 'string'])
def test_health_invalid_records_fail_without_partial_roster(bridge, monkeypatch, health_memory, fault):
    m = health_memory
    bind(bridge, monkeypatch, m)
    if fault == 'getter': m['q'](players.u64(m['read'](0x1000, 8)) + 138*8, 0)
    if fault == 'condition': m['put'](0x1254, struct.pack('<h', -1))
    if fault == 'sharpness': m['put'](0x1250, struct.pack('<h', 10001))
    if fault == 'vector': m['q'](m['injury_header'] + 16, 0)
    if fault == 'duplicate': m['vec'](m['injury_header'], [m['injury_record']]*2)
    if fault == 'type': m['q'](m['injury_definition'], 0)
    if fault == 'identity': m['put'](m['injury_definition'] + 12, bytes(4))
    if fault == 'membership': m['vec'](m['headers']['injuries'], [m['club']])
    if fault == 'property': m['q'](m['base'] + world.TYPES['injury'][0] + 3*8, 0)
    if fault == 'date': m['put'](m['injury_record'] + 0x20, bytes(4))
    if fault == 'string': m['q'](m['injury_definition'] + 0x18, m['text']('bad\nname'))
    with pytest.raises(BridgeError): bridge.get_managed_squad(bridge.session, include_health=True)
    assert not bridge.player_refs


@pytest.mark.parametrize('mutation', ['fitness', 'injury', 'definition'])
def test_health_mutation_expires_references(bridge, monkeypatch, health_memory, mutation):
    m = health_memory
    bind(bridge, monkeypatch, m)
    ref = bridge.get_managed_squad(bridge.session)['players'][0]['player_ref']
    original = player_health.decode
    def mutate(*a, **kw):
        result = original(*a, **kw)
        address = {'fitness': 0x1254, 'injury': m['injury_record'] + 0x20, 'definition': m['injury_definition'] + 12}[mutation]
        m['put'](address, b'\x13')
        return result
    monkeypatch.setattr(player_health, 'decode', mutate)
    with pytest.raises(BridgeError, match='changed'): bridge.get_player(bridge.session, ref, include_health=True)
    assert ref not in bridge.player_refs


def test_virtual_health_constants_and_unavailable_fields(bridge, monkeypatch, virtual_memory):
    m = virtual_memory
    populate(m, m['regular'])
    table = m['base'] + world.TYPES['virtual_player'][0]
    m['q'](table + 21*8, m['base'] + 0xD5BEA8)
    m['q'](table + 141*8, m['base'] + 0xD5C1A4)
    bind(bridge, monkeypatch, m)
    full = bridge.get_managed_squad(bridge.session, include_health=True)
    row = next(p for p in full['players'] if p.get('record_kind') == 'virtual')
    health = row['health']
    assert health['condition'] is None and health['match_sharpness'] is None and health['fatigue'] == 0
    assert health['injuries'] == [] and health['state'] == 'partial_virtual'
    m['q'](table + 21*8, 0)
    with pytest.raises(BridgeError, match='getter'): bridge.get_player(bridge.session, row['player_ref'], include_health=True)


@pytest.mark.parametrize('args', [{'minimum_health': []}, {'minimum_health': {'condition': True}},
    {'minimum_health': {'condition': -1}}, {'maximum_health': {'match_sharpness': 10001}},
    {'maximum_health': {'fatigue': -32769}}, {'minimum_health': {'invented': 1}},
    {'minimum_health': {'condition': 9000}, 'maximum_health': {'condition': 8000}}, {'injury_records': 'healthy'}])
def test_health_query_validation_before_reads(bridge, monkeypatch, args):
    monkeypatch.setattr(bridge, 'get_team_squad', lambda *a, **kw: pytest.fail('read before validation'))
    with pytest.raises(BridgeError): bridge.query_team_players(bridge.session, 'team', **args)


def test_health_queries_sort_boundaries_and_unknown_after_known_exclusions(bridge, monkeypatch):
    def row(name, condition, sharpness, fatigue, injuries, potential, virtual=False):
        return {'display_name': name, 'birth_date': '2000-01-01', 'record_kind': 'virtual' if virtual else 'actual',
            'attributes': {'passing': 15}, 'profile': {'ability': {'potential': potential,
                'potential_state': 'range' if potential is None else 'fixed',
                 'potential_native_code': -95 if potential is None else potential,
                 'potential_range': [160, 190] if potential is None else None}},
            'health': {'condition': condition, 'match_sharpness': sharpness, 'fatigue': fatigue, 'injury_record_count': injuries,
                'state': 'partial_virtual' if virtual else 'stored_without_refresh',
                'unavailable_fields': ['condition', 'match_sharpness'] if virtual else []}}
    rows = [row('A', 9000, 9500, -100, 0, 180), row('B', 9500, 9000, 0, 1, 190),
            row('C', 8999, 9500, 0, 0, None), row('D', None, None, 0, 0, 180, True)]
    for index, player in enumerate(rows):
        player.update(roster_index=index, player_ref=f'player-{index}',
                      profile_state='cached' if player['record_kind'] == 'virtual' else 'stored_direct')
    monkeypatch.setattr(bridge, 'get_team_squad', lambda *a, **kw: {'players': rows, 'count': 4, 'save': {},
        'club': {}, 'observed_at': 'now', 'label': 'Senior', 'limitations': ''})
    result = bridge.query_team_players(bridge.session, 'team', minimum_health={'condition': 9000},
        maximum_health={'fatigue': 0}, minimum_profile={'ability.potential': 170}, sort_by='health.condition', limit=1, include_virtual=True)
    assert result['matched_count'] == 2 and result['truncated'] and result['players'][0]['display_name'] == 'B'
    assert result['unclassified_count'] == 1 and result['unclassified_players'][0]['player']['display_name'] == 'D'
    assert result['unclassified_players'][0]['unavailable_fields'] == ['health.condition']
    result = bridge.query_team_players(bridge.session, 'team', minimum_health={'condition': 9000}, injury_records='without_records')
    assert result['matched_count'] == 1 and result['players'][0]['display_name'] == 'A'
    assert bridge.query_team_players(bridge.session, 'team', injury_records='with_records')['matched_count'] == 1


def test_health_option_strict(bridge):
    for value in (None, 1, 'true'):
        with pytest.raises(BridgeError, match='boolean'): bridge.get_player(bridge.session, 'bad', include_health=value)
        with pytest.raises(BridgeError, match='boolean'): bridge.get_team_squad(bridge.session, 'bad', include_health=value)
        with pytest.raises(BridgeError, match='boolean'): bridge.get_managed_squad(bridge.session, include_health=value)
