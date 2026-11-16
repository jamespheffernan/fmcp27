"""Independent public policy/identity/lifecycle acceptance; synthetic typed memory."""
import asyncio
from copy import deepcopy
import itertools
import struct

import pytest

from fm_live_mcp import players, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import bind, database_memory
from test_players import memory
from test_world import world_memory


@pytest.mark.parametrize('method', ['get_player', 'get_team_squad', 'get_managed_squad'])
@pytest.mark.parametrize('policy', [None, '', 'allow', 'Available', 'available ', True, 1, [], {}])
def test_profile_policy_invalid_literal_precedes_native_reads(bridge, monkeypatch, method, policy):
    def forbidden(*args, **kwargs):
        pytest.fail('Invalid profile policy reached layout/native source discovery')
    monkeypatch.setattr(bridge, '_player_layout', forbidden)
    args = () if method == 'get_managed_squad' else ('reference',)
    with pytest.raises(BridgeError, match='profile_policy'):
        getattr(bridge, method)(bridge.session, *args, profile_policy=policy)


def test_three_public_policy_schemas_keep_required_default():
    from fm_live_mcp.server import mcp
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    for name, required in [('fm_get_player', {'session_id', 'player_ref'}),
                           ('fm_get_team_squad', {'session_id', 'team_ref'}),
                           ('fm_get_managed_squad', {'session_id'})]:
        tool = tools[name]
        assert set(tool.inputSchema['required']) == required
        policy = tool.inputSchema['properties']['profile_policy']
        assert policy['type'] == 'string'
        assert policy['enum'] == ['required', 'available']
        assert policy['default'] == 'required'
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.openWorldHint is False


class SixteenRosterSources:
    """Independent source transcript for the consumer; identity codec is tested below."""
    def __init__(self):
        self.player_refs = {}
        self.team_refs = {'porto': {'address': 9000}}
        self.competition_refs = {}
        self.save = {'name': 'Synthetic career', 'current_date': '2030-10-28'}
        self.roster_calls = []
        self.current_calls = []

    def get_team_squad(self, session_id, team_ref, include_clubs=False, profile_policy='required'):
        assert profile_policy == 'available' and include_clubs is True
        self.roster_calls.append(profile_policy)
        rows = []
        for index in range(16):
            reference = f'population-{len(self.roster_calls)}-{index}'
            kind = 'actual' if index < 13 else 'player_staff' if index < 15 else 'virtual'
            cold = kind == 'virtual'
            identity = ('stored_virtual_identity_v1', index, 700 + index, 900 + index) if cold else (700 + index, 'P', '2000-01-01')
            self.player_refs[reference] = {'address': 1000 + index, 'identity': identity, 'tables': (1, 2, 3)}
            row = {'player_ref': reference, 'roster_index': index, 'record_kind': kind,
                   'name': None if cold else f'Player {index}', 'display_name': None if cold else f'Player {index}',
                   'birth_date': None if cold else '2000-01-01', 'attributes': None if cold else {'passing': 12},
                   'native_identity': {'database_index': index, 'native_id': 700 + index, 'random_id': 900 + index},
                   'profile_state': 'identity_only' if cold else 'stored_direct',
                   'unavailable_fields': ['name', 'display_name', 'birth_date', 'attributes', 'clubs'] if cold else [],
                   'roster_context': {'team_database_index': 1155, 'team_native_id': 1478,
                                      'owner_club_database_index': 961, 'owner_club_native_id': 1478},
                   'clubs': None if cold else {'on_loan': False}}
            if cold:
                row['profile_unavailable_reason'] = 'negative_cache_index'
            rows.append(row)
        return {'save': deepcopy(self.save), 'players': rows, 'count': 16, 'native_slot_count': 16,
                'complete_native_roster': True, 'profile_counts': {'stored_direct': 15, 'cached': 0, 'identity_only': 1},
                'unavailable_profile_count': 1, 'complete_base_profiles': False,
                'label': 'Senior', 'club': {'name': 'FC Porto'}}

    def get_current_player_statistics(self, session_id, reference):
        index = self.player_refs[reference]['address'] - 1000
        assert index < 13, 'Unsupported combined/virtual statistics queried'
        self.current_calls.append(index)
        return {'save': deepcopy(self.save), 'player_ref': reference,
                'player': {'name': f'Player {index}', 'birth_date': '2000-01-01', 'record_kind': 'actual'},
                'statistics': {'state': 'stored_without_refresh', 'current_team': {'native_id': 1478},
                    'current_team_state': 'decoded', 'categories': [{'native_code': 1, 'name': 'League',
                    'availability': 'resident', 'statistics': {'minutes': 450, 'goals': 1, 'assists': 0}}]}}

    def get_player_statistics_history(self, *args, **kwargs):
        pytest.fail('History disabled or unsupported candidate was queried')

    def get_save(self, session_id):
        return {'save': deepcopy(self.save), 'observed_at': 'final-observation'}


def test_performance_uses_complete_sixteen_population_and_preserves_cold_identity(bridge, monkeypatch):
    sources = SixteenRosterSources()
    for name in ('player_refs', 'team_refs', 'competition_refs', 'get_team_squad',
                 'get_current_player_statistics', 'get_player_statistics_history', 'get_save'):
        monkeypatch.setattr(bridge, name, getattr(sources, name))
    comparison = bridge.compare_team_league_performance(
        bridge.session, 'porto', minimum_minutes=450, limit=5, include_history=False)['comparison']
    assert sources.roster_calls == ['available', 'available']
    assert comparison['counts'] == {'roster_count': 16, 'actual_count': 13, 'unsupported_count': 3,
        'unknown_count': 0, 'below_minimum_count': 0, 'qualifying_count': 13, 'returned_count': 5}
    assert [row['roster_index'] for row in comparison['rows']] == [0, 1, 2, 3, 4]
    assert comparison['ranking_complete_among_supported'] is True
    assert comparison['ranking_complete_for_roster'] is False
    assert len(comparison['classifications']) == 16
    assert sources.current_calls == list(range(13))*2
    cold = comparison['classifications'][15]
    assert cold['state'] == 'unsupported'
    assert cold['player']['name'] is None and cold['player']['record_kind'] == 'virtual'
    assert cold['player']['native_identity'] == {'database_index': 15, 'native_id': 715, 'random_id': 915}
    assert cold['player']['profile_state'] == 'identity_only'
    assert cold['player']['profile_unavailable_reason'] == 'negative_cache_index'
    assert cold['player']['roster_context']['team_native_id'] == 1478
    assert cold['player']['unavailable_fields'] == ['name', 'display_name', 'birth_date', 'attributes', 'clubs']
    assert cold['player']['player_ref'] == 'population-2-15'


from test_virtual import virtual_memory
from test_virtual_identity import compact_virtual_memory

BASE_FIELDS = ['name', 'display_name', 'birth_date', 'attributes']


@pytest.fixture
def compact_roster(bridge, monkeypatch, compact_virtual_memory):
    bind(bridge, monkeypatch, compact_virtual_memory)
    return compact_virtual_memory


def cold_only(m):
    m['vec'](m['team'] + 0x38, [m['compact']])


def team_reference(bridge):
    return bridge.get_club_squads(bridge.session)['squads'][0]['team_ref']


def cold_row(response):
    return next(row for row in response['players'] if row['record_kind'] == 'virtual')


def assert_cold(row, options, *, roster=True):
    assert row['record_kind'] == 'virtual' and row['profile_state'] == 'identity_only'
    assert row['native_identity'] == {'database_index': 1, 'native_id': 12345, 'random_id': None}
    assert row['profile_unavailable_reason'] == 'negative_cache_index'
    expected = BASE_FIELDS + [field for field, requested in options.items() if requested]
    assert set(row['unavailable_fields']) == set(expected)
    for field in expected:
        assert row[field] is None
        assert row['field_sources'][field] == 'unavailable_from_verified_sources'
    assert row['field_sources']['native_identity'] == 'stored_direct'
    for field, requested in options.items():
        if not requested:
            assert field not in row
    if roster:
        assert row['roster_context'] == {'team_database_index': 0, 'team_native_id': 1478,
            'owner_club_database_index': 0, 'owner_club_native_id': 688}
        assert row['field_sources']['roster_context'] == 'checked_selected_team_roster'
    else:
        assert 'roster_index' not in row and 'roster_context' not in row
        assert 'roster_context' not in row['field_sources']
    assert '_raw' not in row and 'address' not in row and 'cache_index' not in row


@pytest.mark.parametrize('method', ['managed', 'team'])
@pytest.mark.parametrize('clubs,profile,health', list(itertools.product([False, True], repeat=3)))
def test_cold_available_optional_union_skips_all_expanded_sources(
        bridge, monkeypatch, compact_roster, method, clubs, profile, health):
    from fm_live_mcp import player_health, player_profile, virtual
    m = compact_roster
    cold_only(m)
    reference = team_reference(bridge) if method == 'team' else None
    def forbidden(*args, **kwargs):
        pytest.fail('Cold identity-only request entered an expanded/dependent reader')
    monkeypatch.setattr(players, '_decode_record', forbidden)
    monkeypatch.setattr(player_health, 'decode', forbidden)
    monkeypatch.setattr(player_profile, 'decode', forbidden)
    original_read = bridge._read_memory
    def read(process, address, size):
        assert address != m['base'] + virtual.MANAGER_ROOT, 'Cold source looked up virtual cache manager'
        return original_read(process, address, size)
    monkeypatch.setattr(bridge, '_read_memory', read)
    kwargs = dict(include_clubs=clubs, include_profile=profile, include_health=health, profile_policy='available')
    response = (bridge.get_team_squad(bridge.session, reference, **kwargs) if method == 'team'
                else bridge.get_managed_squad(bridge.session, **kwargs))
    assert response['count'] == response['native_slot_count'] == len(response['players']) == 1
    assert response['complete_native_roster'] is True
    assert response['profile_counts'] == {'stored_direct': 0, 'cached': 0, 'identity_only': 1}
    assert response['unavailable_profile_count'] == 1 and response['complete_base_profiles'] is False
    assert response['base_profile_fields'] == BASE_FIELDS
    row = cold_row(response)
    assert row['roster_index'] == 0
    assert_cold(row, {'clubs': clubs, 'profile': profile, 'health': health})
    saved = bridge.player_refs[row['player_ref']]
    assert saved['binding_kind'] == 'stored_virtual_identity_v1'
    assert saved['identity'] == ('stored_virtual_identity_v1', 1, 12345, 12345)


@pytest.mark.parametrize('clubs,profile,health', list(itertools.product([False, True], repeat=3)))
def test_stored_cold_ref_readback_is_fresh_and_keeps_unavailable_requested_groups(
        bridge, monkeypatch, compact_roster, clubs, profile, health):
    from fm_live_mcp import database
    m = compact_roster
    cold_only(m)
    row = cold_row(bridge.get_managed_squad(bridge.session, profile_policy='available'))
    reference = row['player_ref']
    monkeypatch.setattr(database, 'player_membership', lambda *args: pytest.fail('Stored virtual dispatched to actual-only membership'))
    result = bridge.get_player(bridge.session, reference, profile_policy='available',
        include_clubs=clubs, include_profile=profile, include_health=health)
    assert_cold(result['player'], {'clubs': clubs, 'profile': profile, 'health': health}, roster=False)
    assert result['save_identity'] == 'native_binding_rechecked' and reference in bridge.player_refs


@pytest.mark.parametrize('cache_index', [-1, -2, -32768])
def test_all_signed_negative_cache_indexes_are_expected_absence(bridge, compact_roster, cache_index):
    m = compact_roster
    cold_only(m)
    m['put'](m['compact'] + 0x14, struct.pack('<h', cache_index))
    row = cold_row(bridge.get_managed_squad(bridge.session, profile_policy='available'))
    assert row['profile_state'] == 'identity_only'
    reference = row['player_ref']
    with pytest.raises(BridgeError, match='profile.*unavailable|unavailable.*profile') as caught:
        bridge.get_player(bridge.session, reference)
    assert 'available' in str(caught.value) and 'open the' not in str(caught.value).lower()
    assert reference in bridge.player_refs


@pytest.mark.parametrize('method', ['managed', 'team'])
def test_required_default_rejects_cold_without_partial_refs_or_availability_metadata(
        bridge, compact_roster, method):
    reference = team_reference(bridge) if method == 'team' else None
    before = dict(bridge.player_refs)
    with pytest.raises(BridgeError, match='profile|materialized'):
        if method == 'team':
            bridge.get_team_squad(bridge.session, reference)
        else:
            bridge.get_managed_squad(bridge.session)
    assert bridge.player_refs == before


def test_available_mixed_roster_native_identity_and_base_accounting(bridge, compact_roster):
    m = compact_roster
    m['put'](m['regular'] + 0x398, struct.pack('<I', 0))
    result = bridge.get_managed_squad(bridge.session, profile_policy='available')
    assert result['count'] == result['native_slot_count'] == 2
    assert result['profile_counts'] == {'stored_direct': 1, 'cached': 0, 'identity_only': 1}
    actual, cold = result['players']
    assert actual['record_kind'] == 'actual' and actual['profile_state'] == 'stored_direct'
    assert actual['native_identity'] == {'database_index': 0, 'native_id': 678, 'random_id': 0}
    assert actual['name'] == 'Test Müller' and len(actual['attributes']) == 36
    assert actual['unavailable_fields'] == []
    assert cold['roster_index'] == 1 and cold['profile_state'] == 'identity_only'


@pytest.mark.parametrize('secondary', [0, 999, 12345])
def test_independent_compact_identity_words_are_preserved_and_bound(bridge, compact_roster, secondary):
    m = compact_roster
    cold_only(m)
    m['put'](m['compact'] + 0x30, struct.pack('<I', secondary))
    row = cold_row(bridge.get_managed_squad(bridge.session, profile_policy='available'))
    assert row['native_identity']['random_id'] == (None if secondary == 12345 else secondary)
    reference = row['player_ref']
    assert bridge.player_refs[reference]['identity'] == ('stored_virtual_identity_v1', 1, 12345, secondary)
    assert bridge.get_player(bridge.session, reference, profile_policy='available')['player']['native_identity'] == row['native_identity']


def test_compact_ref_cold_warm_cold_transitions_across_calls_keep_core_identity(bridge, compact_roster):
    m = compact_roster
    cold_only(m)
    row = cold_row(bridge.get_managed_squad(bridge.session, profile_policy='available'))
    reference = row['player_ref']
    identity = bridge.player_refs[reference]['identity']
    m['put'](m['compact'] + 0x14, struct.pack('<h', 0))
    warm = bridge.get_player(bridge.session, reference, profile_policy='available')['player']
    assert warm['profile_state'] == 'cached' and warm['name'] == 'Test Müller'
    assert len(warm['attributes']) == 36 and warm['unavailable_fields'] == []
    assert warm['field_sources']['name'] == 'cached_generated_profile'
    assert bridge.get_player(bridge.session, reference)['player']['name'] == 'Test Müller'
    assert bridge.player_refs[reference]['identity'] == identity
    m['put'](m['compact'] + 0x14, struct.pack('<h', -1))
    cold = bridge.get_player(bridge.session, reference, profile_policy='available')['player']
    assert cold['name'] is None and cold['attributes'] is None and cold['profile_state'] == 'identity_only'
    with pytest.raises(BridgeError, match='unavailable'):
        bridge.get_player(bridge.session, reference)
    assert bridge.player_refs[reference]['identity'] == identity


def test_legacy_warm_rich_ref_cannot_be_downgraded_to_cold(bridge, compact_roster):
    m = compact_roster
    cold_only(m)
    m['put'](m['compact'] + 0x14, struct.pack('<h', 0))
    row = next(p for p in bridge.get_managed_squad(bridge.session)['players'] if p['record_kind'] == 'virtual')
    reference = row['player_ref']
    assert 'binding_kind' not in bridge.player_refs[reference]
    assert 'profile_state' not in row and 'native_identity' not in row
    m['put'](m['compact'] + 0x14, struct.pack('<h', -1))
    with pytest.raises(BridgeError):
        bridge.get_player(bridge.session, reference, profile_policy='available')
    assert reference not in bridge.player_refs


@pytest.mark.parametrize('flag', ['include_contract_dates', 'include_wage', 'include_contract_status',
    'include_contract_bonuses', 'include_contract_terms', 'include_loan_contract'])
@pytest.mark.parametrize('policy', ['required', 'available'])
def test_stored_virtual_optional_contract_requests_remain_unsupported(bridge, compact_roster, flag, policy):
    m = compact_roster
    cold_only(m)
    reference = cold_row(bridge.get_managed_squad(bridge.session, profile_policy='available'))['player_ref']
    with pytest.raises(BridgeError, match='unsupported'):
        bridge.get_player(bridge.session, reference, profile_policy=policy, **{flag: True})


@pytest.mark.parametrize('fault', ['primary', 'person_index', 'person_member', 'person_type', 'native_code',
    'team_index', 'duplicate', 'unknown_kind', 'roster_bounds', 'warm_index', 'warm_null',
    'warm_type', 'warm_marker', 'warm_secondary', 'warm_bounds', 'warm_team'])
def test_invalid_native_source_or_reused_cache_fails_without_partial_ref_publication(
        bridge, compact_roster, fault):
    from fm_live_mcp import virtual_identity
    m = compact_roster
    if fault.startswith('warm_'):
        m['put'](m['compact'] + 0x14, struct.pack('<h', 0))
    if fault == 'primary': m['put'](m['compact'] + 0x2C, struct.pack('<I', 0))
    elif fault == 'person_index': m['put'](m['compact'] + 0x28, struct.pack('<I', 99))
    elif fault == 'person_member': m['vec'](m['headers']['people'], [m['regular'] + 0x388, m['club']])
    elif fault == 'person_type': m['q'](m['compact'] + 0x20, m['tables'][2])
    elif fault == 'native_code':
        address = m['base'] + virtual_identity.NATIVE_SPANS[0][0]
        m['put'](address, bytes([m['read'](address, 1)[0] ^ 1]))
    elif fault == 'team_index': m['put'](m['compact'] + 8, struct.pack('<i', 1478))
    elif fault == 'duplicate': m['vec'](m['team'] + 0x38, [m['regular'], m['compact'], m['compact']])
    elif fault == 'unknown_kind': m['q'](m['compact'], m['base'] + world.TYPES['club'][0])
    elif fault == 'roster_bounds': m['q'](m['team'] + 0x40, 0)
    elif fault == 'warm_index': m['put'](m['compact'] + 0x14, struct.pack('<h', 1))
    elif fault == 'warm_null': m['q'](players.u64(m['read'](m['cache_manager'] + 8, 8)), 0)
    elif fault == 'warm_type': m['q'](m['warm_cache_address'], 0)
    elif fault == 'warm_marker': m['put'](m['warm_cache_address'] + 0x390, struct.pack('<I', 0))
    elif fault == 'warm_secondary': m['put'](m['warm_cache_address'] + 0x398, struct.pack('<I', 12345))
    elif fault == 'warm_bounds': m['q'](m['cache_manager'] + 16, 0)
    elif fault == 'warm_team': m['q'](m['warm_cache_address'] + 0x128, m['club'])
    before = dict(bridge.player_refs)
    with pytest.raises(BridgeError):
        bridge.get_managed_squad(bridge.session, profile_policy='available', include_clubs=fault == 'warm_team')
    assert bridge.player_refs == before


@pytest.mark.parametrize('fault', ['primary', 'secondary', 'person_member', 'native_type', 'binding_kind'])
def test_stored_ref_corruption_invalidates_instead_of_becoming_cold(bridge, compact_roster, fault):
    m = compact_roster
    cold_only(m)
    reference = cold_row(bridge.get_managed_squad(bridge.session, profile_policy='available'))['player_ref']
    if fault == 'primary': m['put'](m['compact'] + 0x2C, struct.pack('<I', 999))
    elif fault == 'secondary': m['put'](m['compact'] + 0x30, struct.pack('<I', 0))
    elif fault == 'person_member': m['vec'](m['headers']['people'], [m['regular'] + 0x388, m['club']])
    elif fault == 'native_type': m['q'](m['compact'], 0)
    else: bridge.player_refs[reference]['binding_kind'] = 'unknown_stored_variant'
    with pytest.raises(BridgeError):
        bridge.get_player(bridge.session, reference, profile_policy='available')
    assert reference not in bridge.player_refs


@pytest.mark.parametrize('fault', ['cache_transition', 'identity', 'roster', 'membership'])
def test_mid_read_source_drift_rejects_whole_roster_and_no_refs(bridge, monkeypatch, compact_roster, fault):
    from fm_live_mcp import virtual
    m = compact_roster
    original = virtual.decode
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        if fault == 'cache_transition': m['put'](m['compact'] + 0x14, struct.pack('<h', 0))
        elif fault == 'identity': m['put'](m['compact'] + 0x30, struct.pack('<I', 0))
        elif fault == 'roster': m['vec'](m['team'] + 0x38, [m['compact'], m['regular']])
        else: m['vec'](m['headers']['people'], [m['regular'] + 0x388, m['club']])
        return result
    monkeypatch.setattr(virtual, 'decode', mutate)
    before = dict(bridge.player_refs)
    with pytest.raises(BridgeError, match='changed|disagrees|index'):
        bridge.get_managed_squad(bridge.session, profile_policy='available')
    assert bridge.player_refs == before


def test_required_unavailable_does_not_preserve_ref_when_core_changes_mid_read(bridge, monkeypatch, compact_roster):
    from fm_live_mcp import virtual_identity
    m = compact_roster
    cold_only(m)
    reference = cold_row(bridge.get_managed_squad(bridge.session, profile_policy='available'))['player_ref']
    original = virtual_identity.inspect
    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        m['put'](m['compact'] + 0x30, struct.pack('<I', 0))
        return result
    monkeypatch.setattr(virtual_identity, 'inspect', mutate)
    with pytest.raises(BridgeError, match='changed'):
        bridge.get_player(bridge.session, reference)
    assert reference not in bridge.player_refs


def test_standalone_ref_does_not_replay_origin_roster_observation(bridge, compact_roster):
    m = compact_roster
    cold_only(m)
    reference = cold_row(bridge.get_managed_squad(bridge.session, profile_policy='available'))['player_ref']
    m['vec'](m['team'] + 0x38, [])
    row = bridge.get_player(bridge.session, reference, profile_policy='available')['player']
    assert_cold(row, {'clubs': False, 'profile': False, 'health': False}, roster=False)
    assert reference in bridge.player_refs


def test_available_public_path_accepts_unaligned_rtti_name(bridge, compact_roster):
    from fm_live_mcp import virtual_identity
    m = compact_roster
    metadata = m['read'](m['base'] + virtual_identity.PERSON_RVA - 16, 16)
    info = players.u64(metadata, 8)
    expected = b'N2db14VIRTUAL_PLAYERE\0'
    allocation = m['allocate'](len(expected) + 1)
    m['put'](allocation + 1, expected)
    m['q'](info + 8, allocation + 1)
    row = cold_row(bridge.get_managed_squad(bridge.session, profile_policy='available'))
    assert row['native_identity']['native_id'] == 12345


def test_reused_valid_cache_does_not_abort_available_roster_or_borrow_profile(bridge,compact_roster):
    m=compact_roster
    m['put'](m['compact']+0x14,struct.pack('<h',0))
    m['put'](m['warm_cache_address']+0x394,struct.pack('<I',999))
    result=bridge.get_managed_squad(bridge.session,profile_policy='available',include_clubs=True)
    cold=next(x for x in result['players'] if x['record_kind']=='virtual')
    assert result['complete_native_roster'] and result['count']==2
    assert result['unavailable_profile_count']==1
    assert result['unavailable_profiles']==[{'native_identity':cold['native_identity'],'roster_index':cold['roster_index'],'reason':'cache_identity_mismatch','unavailable_fields':cold['unavailable_fields']}]
    assert cold['native_identity']['native_id']==12345
    assert all(cold[k] is None for k in ('name','display_name','birth_date','attributes','clubs'))
    again=bridge.get_player(bridge.session,cold['player_ref'],profile_policy='available',include_health=True)['player']
    assert again['native_identity']==cold['native_identity'] and again['profile_unavailable_reason']=='cache_identity_mismatch'
    assert again['name'] is None and again['health'] is None
