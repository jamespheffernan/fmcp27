import pytest

from fm_live_mcp.bridge import BridgeError
from fm_live_mcp import bridge as module
from test_bridge import bridge


@pytest.fixture
def roster():
    def player(name, passing, vision, virtual=False, loan=False):
        return {'display_name': name, 'name': name, 'birth_date': '2000-01-01',
                'attributes': {'passing': passing, 'vision': vision}, 'clubs': {'on_loan': loan},
                'record_kind': 'virtual' if virtual else 'actual'}
    rows = [player('B', 18, 12), player('A', 18, 15),
            player('C', 20, 20, virtual=True), player('D', 17, 18, loan=True)]
    for index, row in enumerate(rows):
        row.update(roster_index=index, player_ref=f'player-{index}',
                   profile_state='cached' if row['record_kind'] == 'virtual' else 'stored_direct')
    return {'observed_at': 'now', 'save': {}, 'club': {}, 'label': 'Senior', 'count': 4,
            'limitations': 'Native roster.', 'players': rows}


def test_thresholds_sort_counts_and_virtual_exclusion(bridge, monkeypatch, roster):
    monkeypatch.setattr(bridge, 'get_team_squad', lambda *a, **kw: roster)
    result = bridge.query_team_players(bridge.session, 'team', {'vision': 15}, 'passing', 1)
    assert result['matched_count'] == 2 and result['roster_count'] == 4
    assert result['returned_count'] == 1 and result['truncated'] is True
    assert [p['name'] for p in result['players']] == ['A']
    assert result['counts'] == {'roster_count': 4, 'match_count': 2, 'nonmatch_count': 1,
                                'typeexcluded_count': 1, 'unclassified_count': 0}
    assert result['complete_for_included_population'] is True
    assert [row['state'] for row in result['classifications']] == ['nonmatch', 'match', 'typeexcluded', 'match']
    assert bridge.query_team_players(bridge.session, 'team', sort_by='passing', include_virtual=True)['players'][0]['name'] == 'C'


def test_loan_filter_requests_and_uses_verified_clubs(bridge, monkeypatch, roster):
    options = []
    def read(*a, **kw):
        options.append(kw)
        return roster
    monkeypatch.setattr(bridge, 'get_team_squad', read)
    result = bridge.query_team_players(bridge.session, 'team', loan_status='on_loan')
    assert options == [{'include_clubs': True, 'profile_policy': 'available'}]
    assert [p['name'] for p in result['players']] == ['D']
    assert result['matched_count'] == 1


@pytest.mark.parametrize('kwargs', [
    {'minimum_attributes': {'unknown': 10}}, {'minimum_attributes': {'passing': True}},
    {'minimum_attributes': {'passing': 21}}, {'minimum_attributes': []},
    {'sort_by': 'potential_ability'}, {'limit': 0}, {'limit': True},
    {'include_virtual': 1}, {'loan_status': 'available'},
])
def test_invalid_queries_fail_before_reading_roster(bridge, monkeypatch, kwargs):
    monkeypatch.setattr(bridge, 'get_team_squad', lambda *a, **kw: pytest.fail('read before validation'))
    with pytest.raises(BridgeError): bridge.query_team_players(bridge.session, 'team', **kwargs)


def test_composition_holds_lock_without_outer_read_scope(bridge, monkeypatch, roster):
    def source(*args, **kwargs):
        assert bridge.lock._is_owned()
        assert kwargs == {'include_clubs': False, 'profile_policy': 'available'}
        return roster
    original_select = module.team_player_selection.select
    def select(*args):
        assert bridge.lock._is_owned()
        return original_select(*args)
    monkeypatch.setattr(bridge, 'get_team_squad', source)
    monkeypatch.setattr(module.team_player_selection, 'select', select)
    monkeypatch.setattr(bridge, '_read_scope', lambda *a: pytest.fail('nested query read scope'))
    assert bridge.query_team_players(bridge.session, 'team')['matched_count'] == 3


@pytest.mark.parametrize('phase', ['source', 'selector', 'population'])
def test_failure_removes_only_new_refs_without_restoring_expired_refs(bridge, monkeypatch, roster, phase):
    bridge.player_refs.update(kept={'identity': 'kept'}, expired={'identity': 'expired'})
    def source(*args, **kwargs):
        bridge.player_refs.pop('expired')
        bridge.player_refs['new'] = {'identity': 'new'}
        if phase == 'source':
            raise BridgeError('source corrupted')
        if phase == 'population':
            return {**roster, 'count': 9}
        return roster
    monkeypatch.setattr(bridge, 'get_team_squad', source)
    if phase == 'selector':
        def reject(*args):
            raise ValueError('malformed selector source')
        monkeypatch.setattr(module.team_player_selection, 'select', reject)
    with pytest.raises(BridgeError):
        bridge.query_team_players(bridge.session, 'team')
    assert bridge.player_refs == {'kept': {'identity': 'kept'}}


def test_optional_groups_requested_only_when_needed(bridge, monkeypatch, roster):
    options = []
    def source(*args, **kwargs):
        options.append(kwargs)
        return roster
    monkeypatch.setattr(bridge, 'get_team_squad', source)
    monkeypatch.setattr(module.team_player_selection, 'select', lambda *args: {})
    bridge.query_team_players(bridge.session, 'team', minimum_profile={'ability.current': 100})
    bridge.query_team_players(bridge.session, 'team', sort_by='health.fatigue')
    assert options == [
        {'include_clubs': False, 'profile_policy': 'available', 'include_profile': True},
        {'include_clubs': False, 'profile_policy': 'available', 'include_health': True},
    ]


def test_included_cold_identity_remains_explicitly_unclassified(bridge, monkeypatch, roster):
    cold = {'roster_index': 4, 'player_ref': 'cold', 'record_kind': 'virtual',
            'name': None, 'display_name': None, 'birth_date': None, 'attributes': None,
            'profile_state': 'identity_only', 'profile_unavailable_reason': 'negative_cache_index',
            'native_identity': {'database_index': 70, 'native_id': 1234, 'random_id': 5678},
            'unavailable_fields': ['name', 'display_name', 'birth_date', 'attributes'],
            'roster_context': {'team': {'database_index': 9}}}
    for player in roster['players']:
        player['attributes']['decisions'] = 15
    roster['players'].append(cold)
    roster['count'] = 5
    monkeypatch.setattr(bridge, 'get_team_squad', lambda *args, **kwargs: roster)
    query = {'minimum_attributes': {'passing': 15, 'vision': 15}, 'sort_by': 'decisions'}
    excluded = bridge.query_team_players(bridge.session, 'team', **query)
    assert excluded['counts']['typeexcluded_count'] == 2
    assert excluded['unclassified_count'] == 0
    included = bridge.query_team_players(bridge.session, 'team', include_virtual=True, **query)
    assert included['counts'] == {'roster_count': 5, 'match_count': 3, 'nonmatch_count': 1,
                                  'typeexcluded_count': 0, 'unclassified_count': 1}
    assert included['complete_for_included_population'] is False
    unknown = included['unclassified_players'][0]
    assert unknown['player'] == cold
    assert unknown['unavailable_fields'] == ['attributes.decisions', 'attributes.passing',
                                             'attributes.vision', 'birth_date', 'display_name']
