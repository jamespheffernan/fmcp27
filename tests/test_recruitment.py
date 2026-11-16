import struct

import pytest

from fm_live_mcp import personality, player_profile, players, recruitment
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import database_memory, bind, receipt
from test_player_profile import populate
from test_player_staff import staff_memory
from test_players import memory
from test_world import world_memory


@pytest.fixture(params=['database_memory', 'staff_memory'])
def recruitment_memory(request):
    m = request.getfixturevalue(request.param)
    populate(m, 0x1000)
    m['put'](0x115E, bytes([77]))
    for layout in (players.RVA, players.STAFF_RVA):
        for slot, getter in player_profile.GETTERS.items():
            m['q'](m['base'] + layout[0] + slot*8, m['base'] + getter)
        for _, slot, getter, _ in personality.FIELDS.values():
            m['q'](m['base'] + layout[2] + slot*8, m['base'] + getter)
            m['put'](m['base'] + layout[2] - (slot*8+16), struct.pack('<q', -0x110))
    return m


def native_receipt(state='match', **kwargs):
    return receipt(matches=[{'address': '0x1000', 'filter_state': state}], **kwargs)


def test_query_profiles_refs_and_filter_arguments(bridge, monkeypatch, recruitment_memory):
    m = recruitment_memory
    bind(bridge, monkeypatch, m)
    def run(command, process, *args):
        assert command == 'scan-player-index' and '--query-players' in args
        assert 's:604:140:160' in args and 'r:350:15:20' in args
        return native_receipt()
    monkeypatch.setattr(bridge, '_run', run)
    result = bridge.query_save_players(bridge.session, minimum_attributes={'passing':15},
        minimum_profile={'ability.current':140}, maximum_profile={'ability.current':160})
    assert result['count'] == result['candidate_count'] == 1 and result['complete_table_scan']
    assert result['globally_ranked'] is False and result['ordering'] == 'native_database_index'
    row = result['players'][0]
    assert row['profile']['ability']['current'] == 150
    assert bridge.get_player(bridge.session, row['player_ref'], include_profile=True)['player']['profile'] == row['profile']
    m['vec'](m['headers']['people'], [])
    with pytest.raises(BridgeError, match='membership changed'):
        bridge.get_player(bridge.session, row['player_ref'])


def test_unknown_potential_keeps_ref_and_pagination(bridge, monkeypatch, recruitment_memory):
    m = recruitment_memory
    bind(bridge, monkeypatch, m)
    m['put'](0x125E, struct.pack('<h', -95))
    person = 0x1000 + players.person_offset(m['read'], 0x1000, m['tables'])
    m['vec'](m['headers']['people'], [person, m['manager']])
    monkeypatch.setattr(bridge, '_run', lambda *a: native_receipt('unknown_potential', stop_reason='match_limit'))
    result = bridge.query_save_players(bridge.session, minimum_profile={'ability.potential': 170}, max_matches=1)
    assert result['count'] == 0 and result['candidate_count'] == result['unclassified_count'] == 1
    unknown = result['unclassified_players'][0]
    assert unknown['unavailable_fields'] == ['ability.potential'] and unknown['player']['player_ref']
    assert result['next_cursor'] and not result['complete_table_scan']
    with pytest.raises(BridgeError, match='different criteria'):
        bridge.query_save_players(bridge.session, minimum_profile={'ability.potential':169}, cursor=result['next_cursor'])
    monkeypatch.setattr(bridge, '_run', lambda *a: receipt(matches=[], next_index=2, actual_players_examined=0, other_person_records=1))
    final = bridge.query_save_players(bridge.session, minimum_profile={'ability.potential':170}, cursor=result['next_cursor'])
    assert final['next_cursor'] is None and final['count'] == 0 and final['scanned_records'] == 1


@pytest.mark.parametrize('secondary', [0, 999])
def test_independent_ids_decode_and_remain_bound_to_reference(bridge, monkeypatch, recruitment_memory, secondary):
    m = recruitment_memory
    bind(bridge, monkeypatch, m)
    person = 0x1000 + players.person_offset(m['read'], 0x1000, m['tables'])
    m['put'](person + 16, struct.pack('<I', secondary))
    monkeypatch.setattr(bridge, '_run', lambda *a: native_receipt())
    result = bridge.query_save_players(bridge.session, minimum_profile={'ability.current': 140})
    ref = result['players'][0]['player_ref']
    assert bridge.get_player(bridge.session, ref)['player']['name'] == result['players'][0]['name']
    m['put'](person + 16, struct.pack('<I', secondary + 1))
    with pytest.raises(BridgeError, match='identity changed'):
        bridge.get_player(bridge.session, ref)
    assert ref not in bridge.player_refs


@pytest.mark.parametrize('fault', ['nonmatch', 'state', 'profile_getter', 'personality_getter', 'mutation'])
def test_invalid_candidate_never_returns_partial_results(bridge, monkeypatch, recruitment_memory, fault):
    m = recruitment_memory
    bind(bridge, monkeypatch, m)
    monkeypatch.setattr(bridge, '_run', lambda *a: native_receipt('unknown_potential' if fault == 'state' else 'match'))
    if fault == 'nonmatch': m['put'](0x125C, struct.pack('<h', 139))
    if fault == 'profile_getter': m['q'](m['base'] + players.RVA[0] + 6*8, 0)
    if fault == 'personality_getter': m['q'](m['base'] + players.STAFF_RVA[2] + 176*8, 0)
    if fault == 'mutation':
        original = recruitment.classify
        def mutate(*args):
            result = original(*args)
            m['put'](0x125C, struct.pack('<h', 151))
            return result
        monkeypatch.setattr(recruitment, 'classify', mutate)
    with pytest.raises(BridgeError): bridge.query_save_players(bridge.session, minimum_profile={'ability.current':140})
    assert not bridge.player_refs


@pytest.mark.parametrize('criteria', [{'minimum_attributes': []}, {'minimum_attributes': {'passing':True}},
    {'maximum_attributes': {'passing':21}}, {'minimum_profile': {'positions.striker':21}},
    {'minimum_profile': {'ability.current':201}}, {'maximum_profile': {'ability.current':-1}},
    {'minimum_profile': {'invented':1}}, {'minimum_attributes': {'passing':15}, 'maximum_attributes': {'passing':14}},
    {'born_on_or_after':'2030-02-29'}, {'born_on_or_before':''}, {'born_on_or_after':False},
    {'born_on_or_after':'20300101'}, {'born_on_or_after':'1849-12-31'},
    {'born_on_or_after':'2000-01-02','born_on_or_before':'2000-01-01'}])
def test_invalid_criteria_precede_scan(bridge, monkeypatch, criteria):
    monkeypatch.setattr(bridge, '_find_database_records', lambda *a: pytest.fail('scan before validation'))
    with pytest.raises(BridgeError): bridge.query_save_players(bridge.session, **criteria)


def test_compile_every_supported_field_and_date_roundtrip():
    criteria = recruitment.compile_filters(minimum_attributes=dict.fromkeys(players.ATTRIBUTES, 0),
        maximum_profile=player_profile.QUERY_FIELDS, born_on_or_after='2000-02-29', born_on_or_before='2000-02-29')
    assert len(criteria['bounds']) == 79
    assert f'd:720:{2000*512+60}:{2000*512+60}' in criteria['native']
    assert recruitment.date_number('2200-12-31') == 2200*512+365
