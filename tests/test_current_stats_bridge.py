"""Public acceptance for resident-current statistics; synthetic memory, no game access."""
import asyncio
import struct

import pytest

from fm_live_mcp import players, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import bind, database_memory, receipt
from test_player_staff import staff_memory
from test_players import memory
from test_virtual import virtual_memory
from test_world import world_memory


def player_reference(bridge, monkeypatch, m):
    bind(bridge, monkeypatch, m)
    monkeypatch.setattr(bridge, '_run', lambda *args: receipt())
    return bridge.find_save_players(bridge.session, 'Test')['players'][0]['player_ref']


@pytest.mark.parametrize('reference', [None, '', 1, True, [], {}])
def test_current_statistics_rejects_invalid_reference_before_native_reads(bridge, monkeypatch, reference):
    def forbidden(*args, **kwargs):
        pytest.fail('Malformed reference reached native layout discovery')
    monkeypatch.setattr(bridge, '_player_layout', forbidden)
    with pytest.raises(BridgeError, match='player_ref|reference'):
        bridge.get_current_player_statistics(bridge.session, reference)


def test_current_statistics_rejects_unknown_and_detached_reference(bridge):
    with pytest.raises(BridgeError, match='Unknown|expired'):
        bridge.get_current_player_statistics(bridge.session, 'missing')
    session = bridge.session
    bridge.detach()
    with pytest.raises(BridgeError):
        bridge.get_current_player_statistics(session, 'missing')


@pytest.mark.parametrize('kind', ['virtual', 'player_staff'])
def test_current_statistics_rejects_real_unsupported_subtype(bridge, monkeypatch, request, kind):
    m = request.getfixturevalue('virtual_memory' if kind == 'virtual' else 'staff_memory')
    bind(bridge, monkeypatch, m)
    roster = bridge.get_managed_squad(bridge.session)
    row = next(p for p in roster['players'] if p.get('record_kind') == kind)
    reference = row['player_ref']
    with pytest.raises(BridgeError, match='unsupported|Unsupported|only'):
        bridge.get_current_player_statistics(bridge.session, reference)
    assert reference not in bridge.player_refs


@pytest.mark.parametrize('fault', ['identity', 'membership', 'save'])
def test_current_statistics_invalidates_previously_checked_reference(bridge, monkeypatch, database_memory, fault):
    m = database_memory
    reference = player_reference(bridge, monkeypatch, m)
    if fault == 'identity':
        m['put'](0x1394, struct.pack('<I', 54321))
    elif fault == 'membership':
        m['vec'](m['headers']['people'], [m['club']])
    else:
        m['q'](m['save'] + 0x28, m['text']('Different career'))
    with pytest.raises(BridgeError, match='changed|identity|membership|live table index'):
        bridge.get_current_player_statistics(bridge.session, reference)
    assert reference not in bridge.player_refs


def test_current_statistics_mcp_schema_and_read_only_annotations():
    from fm_live_mcp.server import mcp
    tools = asyncio.run(mcp.list_tools())
    tool = next(t for t in tools if t.name == 'fm_get_current_player_statistics')
    assert set(tool.inputSchema['required']) == {'session_id', 'player_ref'}
    assert tool.inputSchema['properties']['player_ref']['type'] == 'string'
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.openWorldHint is False


@pytest.fixture
def statistics_memory(database_memory):
    """Seed native layouts and source bytes; the real decoder/verifier runs unchanged."""
    from fm_live_mcp import current_player_statistics as current, player_statistics, teams
    m = database_memory
    service = m['allocate'](8)
    m['q'](m['base'] + current.GAME_PLAYER_ROOT, service)
    m['q'](service, m['base'] + current.GAME_PLAYER_TABLE)
    service_info, service_name = m['allocate'](16), m['allocate'](24)
    m['put'](service_name, b'18GAME_ACTUAL_PLAYER\0')
    m['q'](service_info + 8, service_name)
    m['put'](m['base'] + current.GAME_PLAYER_TABLE - 16, struct.pack('<qQ', 0, service_info))
    m['q'](m['base'] + current.GAME_PLAYER_TABLE + 0x208, m['base'] + 0x1F89560)
    for rva, encoded in current.NATIVE_SPANS.items():
        m['put'](m['base'] + rva, bytes.fromhex(encoded))
    for rva, expected in player_statistics.NATIVE_SPANS:
        m['put'](m['base'] + rva, expected)
    m['put'](m['tables'][0] - 0x18, struct.pack('<q', 0x388))
    m['put'](m['team'] + 8, struct.pack('<III', 0, 688, 688))
    m['put'](m['club'] + 8, struct.pack('<I', 0))
    m['vec'](m['headers']['teams'], [m['team']])
    m['q'](0x1128, m['team'])
    for kind in ('team', 'club'):
        m['q'](m['base'] + world.TYPES[kind][0] + 24, m['base'] + teams.GETTERS[kind])
    m['put'](m['base'] + teams.LOOKUP_MODE, b'\x01')
    m['q'](m['base'] + world.TYPES['club'][0] + 0x168, m['base'] + 0x17BFB5C)
    nation = m['typed']('nation', 0x130)
    context = m['allocate'](0x180)
    owner = m['typed']('nation', 0x130)
    runtime = m['allocate'](0x48)
    season = m['allocate'](0x248)
    m['q'](m['club'] + 0xD8, nation)
    m['q'](nation + 0x110, context)
    m['q'](context + 0x170, owner)
    m['q'](owner + 0x128, runtime)
    m['q'](runtime + 0x38, season)
    m['put'](season + 0x234, struct.pack('<H', 2030))
    m['put'](season + 0x242, b'\x01')
    resident = m['allocate'](0xA8)
    m['q'](0x1100, resident)
    m['put'](resident + 0x60, struct.pack('<i', 0))
    indirect = m['allocate'](136)
    array = [0] * 68
    array[4], array[47], array[55] = 41, -2, -12
    m['put'](indirect, struct.pack('<68h', *array))
    compact = m['allocate'](32)
    raw = bytearray(25)
    struct.pack_into('<Qhh', raw, 0, indirect, 327, 450)
    raw[0x0C:0x11] = bytes([3, 2, 5, 7, 4])
    m['put'](compact, raw)
    m['q'](resident + 0x20, compact)
    aggregate = m['allocate'](32)
    aggregate_raw = bytearray(25)
    struct.pack_into('<hh', aggregate_raw, 8, 640, 990)
    aggregate_raw[0x0C:0x11] = bytes([9, 1, 10, 11, 6])
    m['put'](aggregate, aggregate_raw)
    m['q'](resident + 0x48, aggregate)
    m.update(resident_stats=resident, compact_stats=compact, aggregate_stats=aggregate,
             indirect_stats=indirect, stats_season=season)
    return m


def test_current_statistics_returns_scoped_provenanced_real_decoding(bridge, monkeypatch, statistics_memory):
    from fm_live_mcp import server
    m = statistics_memory
    reference = player_reference(bridge, monkeypatch, m)
    monkeypatch.setattr(server, 'bridge', bridge)
    result = server.fm_get_current_player_statistics(bridge.session, reference)
    assert result['session_id'] == bridge.session and result['player_ref'] == reference
    assert result['observed_at'] and result['save_identity'] == 'native_binding_rechecked'
    assert result['save']['name'] == 'Synthetic career'
    assert result['save']['current_date'] == '2030-09-19'
    assert 'non-atomic' in result['snapshot'] and 'recheck' in result['snapshot']
    assert result['player'] == {'name': 'Test Müller', 'birth_date': '2000-02-29', 'record_kind': 'actual'}
    stats = result['statistics']
    assert stats['state'] == 'stored_without_refresh'
    assert stats['current_team']['native_id'] == 688
    assert stats['current_team']['owner']['name'] == 'Test United'
    assert stats['club_runtime_season_year'] == {
        'value': 2030, 'state': 'decoded', 'reason': 'stored_normal_club_runtime'}
    assert stats['source_coverage'] == 'resident_current_stats_only_no_archives_or_starting_history'
    assert 'must not be summed' in stats['limitations']
    assert 'without display-team normalization' in stats['limitations']
    assert [r['native_code'] for r in stats['categories']] == list(range(6))
    assert [r['name'] for r in stats['categories']] == [
        'Non Competitive', 'League', 'Cup', 'Continental', 'International', 'Overall (Club)']
    assert all(r['name_state'] == 'native_english_label' for r in stats['categories'])
    first = stats['categories'][0]['statistics']
    assert (first['starting_appearances'], first['sub_appearances'], first['total_appearances']) == (3, 2, 5)
    assert (first['goals'], first['assists'], first['minutes']) == (7, 4, 450)
    assert first['average_rating'] == pytest.approx(6.54)
    assert first['advanced']['named_raw_values']['expected_goals_prevented'] == -2
    assert first['advanced']['named_raw_values']['expected_goals_overperformance'] == -12
    assert first['advanced']['units'] == 'unverified_native_units'
    assert stats['categories'][1] == {'native_code': 1, 'name': 'League', 'name_state': 'native_english_label', 'availability': 'unavailable_null_category', 'statistics': None}
    assert stats['categories'][5]['statistics']['total_appearances'] == 10
    assert stats['categories'][5]['statistics']['goals'] == 11
    assert stats['additional_team_rows'] == []
    assert 'current_statistics' not in bridge.get_player(bridge.session, reference)['player']


def test_current_statistics_null_resident_is_unavailable_without_allocation(bridge, monkeypatch, statistics_memory):
    m = statistics_memory
    reference = player_reference(bridge, monkeypatch, m)
    m['q'](0x1100, 0)
    before = dict(m['cells'])
    result = bridge.get_current_player_statistics(bridge.session, reference)['statistics']
    assert result['state'] == 'unavailable_not_resident'
    assert result['additional_team_rows'] == []
    assert [r['native_code'] for r in result['categories']] == list(range(6))
    assert all(r['availability'] == 'unavailable_not_resident' and r['statistics'] is None
               for r in result['categories'])
    assert m['cells'] == before
    assert reference in bridge.player_refs


@pytest.mark.parametrize('fault', ['compact', 'indirect', 'resident_owner', 'season', 'person_table', 'current_date'])
def test_current_statistics_consumed_byte_change_rejects_result_and_expires_ref(
        bridge, monkeypatch, statistics_memory, fault):
    from fm_live_mcp import current_player_statistics as current
    m = statistics_memory
    reference = player_reference(bridge, monkeypatch, m)
    original = current.decode
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        if fault == 'compact':
            m['put'](m['compact_stats'] + 0x0F, b'\x08')
        elif fault == 'indirect':
            m['put'](m['indirect_stats'] + 47*2, struct.pack('<h', -3))
        elif fault == 'resident_owner':
            m['put'](m['resident_stats'] + 0x60, struct.pack('<i', 42))
        elif fault == 'season':
            m['put'](m['stats_season'] + 0x234, struct.pack('<H', 2031))
        elif fault == 'person_table':
            m['vec'](m['headers']['people'], [m['club']])
        else:
            m['put'](m['base'] + world.CURRENT_DATE, struct.pack('<I', (2030 << 16) | 263))
        return result
    monkeypatch.setattr(current, 'decode', mutate)
    with pytest.raises(BridgeError, match='changed'):
        bridge.get_current_player_statistics(bridge.session, reference)
    assert reference not in bridge.player_refs


@pytest.mark.parametrize('fault', ['owner', 'native_code'])
def test_current_statistics_rejects_wrong_owner_or_native_proof(bridge, monkeypatch, statistics_memory, fault):
    from fm_live_mcp import current_player_statistics as current
    m = statistics_memory
    reference = player_reference(bridge, monkeypatch, m)
    if fault == 'owner':
        m['put'](m['resident_stats'] + 0x60, struct.pack('<i', 999))
    else:
        m['put'](m['base'] + next(iter(current.NATIVE_SPANS)), b'\x00')
    with pytest.raises(BridgeError, match='identity|layout'):
        bridge.get_current_player_statistics(bridge.session, reference)
    assert reference not in bridge.player_refs


@pytest.mark.parametrize('member', [True, False])
def test_current_statistics_checks_live_membership_for_memory_search_reference(
        bridge, monkeypatch, statistics_memory, member):
    m = statistics_memory
    bind(bridge, monkeypatch, m)
    if not member:
        m['vec'](m['headers']['people'], [m['club']])
    monkeypatch.setattr(bridge, '_run', lambda *args: {
        'matches': [{'address': '0x1000'}], 'stop_reason': 'address_space_end'})
    search = bridge.find_players(bridge.session, 'Test')
    assert search['save_identity'] == 'unverified'
    reference = search['players'][0]['player_ref']
    assert 'database_index' not in bridge.player_refs[reference]
    if member:
        result = bridge.get_current_player_statistics(bridge.session, reference)
        assert result['save_identity'] == 'native_binding_rechecked'
        assert result['statistics']['categories'][0]['statistics']['goals'] == 7
    else:
        with pytest.raises(BridgeError, match='membership|live table index'):
            bridge.get_current_player_statistics(bridge.session, reference)
        assert reference not in bridge.player_refs
