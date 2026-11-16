import struct

import pytest

from fm_live_mcp import current_player_statistics as current, player_statistics, players, world
from test_database import database_memory
from test_players import memory
from test_teams import team_memory
from test_world import world_memory


@pytest.fixture
def current_statistics_memory(team_memory):
    m = team_memory
    base = m['base']
    for rva, data in current.NATIVE_SPANS.items():
        m['put'](base+rva, bytes.fromhex(data))
    for rva, data in player_statistics.NATIVE_SPANS:
        m['put'](base+rva, data)
    service = m['allocate'](8)
    m['q'](service, base+current.GAME_PLAYER_TABLE)
    m['q'](base+current.GAME_PLAYER_ROOT, service)
    service_info, service_name = m['allocate'](16), m['allocate'](24)
    m['put'](service_name, b'18GAME_ACTUAL_PLAYER\0')
    m['q'](service_info+8, service_name)
    m['put'](base+current.GAME_PLAYER_TABLE-16, struct.pack('<qQ', 0, service_info))
    m['q'](base+current.GAME_PLAYER_TABLE+0x208, base+0x1F89560)
    m['put'](m['tables'][0]-0x18, struct.pack('<q', 0x388))
    m['q'](0x1128, m['team_addresses'][0])
    m['q'](base+world.TYPES['club'][0]+0x168, base+0x17BFB5C)
    # Leave the complex nation/runtime branch explicitly unavailable by default.
    m['q'](m['club']+0xD8, 0)
    resident = m['allocate'](0xA8)
    m['q'](0x1100, resident)
    m['put'](resident+0x60, struct.pack('<i', 0))
    stat = m['allocate'](32)
    indirect = m['allocate'](136)
    values = [-1, -32768, 32767] + [7]*65
    m['put'](indirect, struct.pack('<68h', *values))
    m['q'](stat, indirect)
    m['put'](stat+8, struct.pack('<hh', -123, -200))
    m['put'](stat+12, bytes([4, 2, 3, 5, 255, 1, 2, 1, 0, 0, 2, 1, 0]))
    m['q'](resident+0x20, stat)
    m.update(stats_resident=resident, stats_record=stat, stats_indirect=indirect,
             stats_service=service)
    return m


def decode(m, read=None):
    return current.decode(read or m['read'], m['base'], 0x1000, m['tables'])


def test_current_resident_stats_preserve_categories_signed_values_and_team(current_statistics_memory):
    m = current_statistics_memory
    result = decode(m)
    assert result['state'] == 'stored_without_refresh'
    assert [v['native_code'] for v in result['categories']] == list(range(6))
    assert [v['name'] for v in result['categories']] == list(current.CATEGORY_LABELS)
    stats = result['categories'][0]['statistics']
    assert stats['starting_appearances'] == 4 and stats['total_appearances'] == 6
    assert stats['assists'] is None and stats['minutes'] == -200
    assert stats['advanced']['raw_signed16'][:3] == [-1, -32768, 32767]
    assert result['categories'][1]['availability'] == 'unavailable_null_category'
    assert result['categories'][1]['statistics'] is None
    assert result['current_team']['native_id'] == 50
    assert result['current_team']['owner']['name'] == 'Test United'
    assert result['additional_team_rows'] == []
    assert result['additional_team_rows_state'] == 'null_vector'
    assert result['club_runtime_season_year']['value'] is None
    assert '0x' not in str(result)


def test_null_resident_is_unavailable_and_never_reads_zero_address(current_statistics_memory):
    m = current_statistics_memory
    m['q'](0x1100, 0)
    result = decode(m)
    assert result['state'] == 'unavailable_not_resident'
    assert result['additional_team_rows_state'] == 'unavailable_not_resident'
    assert all(v['statistics'] is None for v in result['categories'])
    assert all(v['availability'] == 'unavailable_not_resident' for v in result['categories'])


def test_additional_team_rows_preserve_presence_empty_and_null_teams(current_statistics_memory):
    m = current_statistics_memory
    header = m['allocate'](24)
    m['q'](m['stats_resident']+0x18, header)
    m['vec'](header, [])
    assert decode(m)['additional_team_rows'] == []
    assert decode(m)['additional_team_rows_state'] == 'resident_vector'
    entry, null_entry = m['allocate'](56), m['allocate'](56)
    m['q'](entry, m['team_addresses'][1])
    m['q'](entry+16, m['stats_record'])
    m['vec'](header, [entry, null_entry])
    rows = decode(m)['additional_team_rows']
    assert len(rows) == 2 and rows[0]['team']['random_id'] == 901
    assert rows[0]['categories'][1]['statistics']['goals'] == 5
    assert rows[1]['team'] is None and rows[1]['team_state'] == 'unassigned'


@pytest.mark.parametrize('fault', ['owner', 'virtual', 'combined', 'playing_type', 'person_type',
    'displacement', 'service', 'getter', 'instructions', 'record_pointer', 'array_pointer',
    'team_membership', 'team_type', 'identity', 'label_route', 'service_rtti'])
def test_bad_current_stats_routes_fail_closed(current_statistics_memory, fault):
    m = current_statistics_memory
    if fault == 'owner': m['put'](m['stats_resident']+0x60, struct.pack('<i', 1))
    elif fault == 'virtual': m['q'](0x1000, m['base']+world.TYPES['virtual_player'][0])
    elif fault == 'combined': m['q'](0x1000, m['base']+players.STAFF_RVA[0])
    elif fault == 'playing_type': m['q'](0x1140, 0)
    elif fault == 'person_type': m['q'](0x1388, 0)
    elif fault == 'displacement': m['put'](m['tables'][0]-0x18, struct.pack('<q', 0x480))
    elif fault == 'service': m['q'](m['stats_service'], 0)
    elif fault == 'getter': m['q'](m['base']+current.GAME_PLAYER_TABLE+0x208, 0)
    elif fault == 'instructions': m['put'](m['base']+0xF21930, bytes(4))
    elif fault == 'record_pointer': m['q'](m['stats_resident']+0x20, 3)
    elif fault == 'array_pointer': m['q'](m['stats_record'], 9)
    elif fault == 'team_membership': m['vec'](m['headers']['teams'], [m['team_addresses'][1]])
    elif fault == 'team_type': m['q'](m['team_addresses'][0], 0)
    elif fault == 'identity': m['put'](0x1390, struct.pack('<i', -1))
    elif fault == 'label_route': m['put'](m['base']+0xF88D10, bytes(4))
    elif fault == 'service_rtti': m['put'](m['base']+current.GAME_PLAYER_TABLE-16, struct.pack('<q', -8))
    with pytest.raises(ValueError): decode(m)


@pytest.mark.parametrize('bounds', [(0x10000, 0xFFFF, 0x10000),
    (0x10000, 0x10001, 0x10008), (0x10000, 0x10000, 0x10000+129*8)])
def test_additional_team_vector_bounds_rejected(current_statistics_memory, bounds):
    m = current_statistics_memory
    header = m['allocate'](24)
    m['q'](m['stats_resident']+0x18, header)
    m['put'](header, struct.pack('<QQQ', *bounds))
    with pytest.raises(ValueError): decode(m)


def test_null_indirect_keeps_codec_native_default_state(current_statistics_memory):
    m = current_statistics_memory
    m['q'](m['stats_record'], 0)
    stats = decode(m)['categories'][0]['statistics']
    assert stats['advanced']['state'] == 'native_zero_default_null_indirect'
    assert stats['starting_appearances'] == 4


def test_readset_detects_consumed_stat_changes(current_statistics_memory):
    m = current_statistics_memory
    read = world.ReadSet(m['read'])
    decode(m, read)
    m['put'](m['stats_record']+15, b'\x07')
    with pytest.raises(ValueError, match='changed'): read.verify()


def test_normal_club_runtime_year_and_explicit_fallback(current_statistics_memory):
    m = current_statistics_memory
    nation = m['typed']('nation', 0x150)
    context, runtime, season = m['allocate'](0x180), m['allocate'](0x48), m['allocate'](0x248)
    m['q'](m['club']+0xD8, nation)
    m['q'](nation+0x110, context)
    m['q'](context+0x170, nation)
    m['q'](nation+0x128, runtime)
    m['q'](runtime+0x38, season)
    m['put'](season+0x234, struct.pack('<H', 2030))
    m['put'](season+0x242, b'\x01')
    result = decode(m)['club_runtime_season_year']
    assert result == {'value': 2030, 'state': 'decoded', 'reason': 'stored_normal_club_runtime'}
    m['q'](nation+0x128, 0)
    assert decode(m)['club_runtime_season_year']['reason'] == 'missing_runtime_requires_fallback'
