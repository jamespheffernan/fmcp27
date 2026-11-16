"""Independent owning-query acceptance: typed source and handwritten populations."""
import asyncio
from copy import deepcopy
import struct

import pytest

from fm_live_mcp import virtual
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import bind, database_memory
from test_players import memory
from test_virtual import virtual_memory
from test_virtual_identity import compact_virtual_memory
from test_world import world_memory


REASONS = {'match': 'all_required_values_match', 'nonmatch': 'known_predicate_failed',
           'typeexcluded': 'virtual_excluded', 'unclassified': 'required_values_unavailable'}


def partition(result, states):
    assert [(c['roster_index'], c['state']) for c in result['classifications']] == list(enumerate(states))
    assert all(c['reason'] == REASONS[c['state']] for c in result['classifications'])
    expected = {'roster_count': len(states), **{f'{state}_count': states.count(state)
                for state in ('match', 'nonmatch', 'typeexcluded', 'unclassified')}}
    assert result['counts'] == expected
    assert result['roster_count'] == len(states)
    assert sum(expected[k] for k in expected if k != 'roster_count') == len(states)
    assert result['matched_count'] == expected['match_count']
    assert result['returned_count'] == len(result['players'])
    assert result['unclassified_count'] == expected['unclassified_count']
    assert result['complete_for_included_population'] is (expected['unclassified_count'] == 0)


@pytest.fixture
def typed_team(bridge, monkeypatch, compact_virtual_memory):
    m = compact_virtual_memory
    bind(bridge, monkeypatch, m)
    reference = bridge.get_club_squads(bridge.session)['squads'][0]['team_ref']
    return m, reference


def test_default_excludes_cold_before_rich_predicates_and_retains_actual_readback(bridge, typed_team):
    m, reference = typed_team
    result = bridge.query_team_players(bridge.session, reference,
        minimum_attributes={'dribbling': 16}, sort_by='dribbling')
    partition(result, ['match', 'typeexcluded'])
    row = result['players'][0]
    assert row['attributes']['dribbling'] == 16
    assert row['profile_state'] == 'stored_direct'
    assert bridge.get_player(bridge.session, row['player_ref'])['player']['attributes'] == row['attributes']
    # The rich reader still has its original strict default.
    with pytest.raises(BridgeError):
        bridge.get_team_squad(bridge.session, reference)


@pytest.mark.parametrize('kwargs,paths', [
    ({}, ['birth_date', 'display_name']),
    ({'minimum_attributes': {'passing': 15, 'vision': 15}, 'sort_by': 'decisions'},
     ['attributes.decisions', 'attributes.passing', 'attributes.vision', 'birth_date', 'display_name']),
    ({'loan_status': 'on_loan'}, ['birth_date', 'clubs.on_loan', 'display_name']),
    ({'loan_status': 'not_on_loan'}, ['birth_date', 'clubs.on_loan', 'display_name']),
    ({'minimum_profile': {'ability.current': 150}}, ['ability.current', 'birth_date', 'display_name']),
    ({'sort_by': 'ability.potential'}, ['ability.potential', 'birth_date', 'display_name']),
    ({'minimum_health': {'condition': 9000}}, ['birth_date', 'display_name', 'health.condition']),
    ({'maximum_health': {'fatigue': 0}}, ['birth_date', 'display_name', 'health.fatigue']),
    ({'sort_by': 'health.match_sharpness'}, ['birth_date', 'display_name', 'health.match_sharpness']),
    ({'injury_records': 'with_records'}, ['birth_date', 'display_name', 'health.injury_record_count']),
    ({'injury_records': 'without_records'}, ['birth_date', 'display_name', 'health.injury_record_count']),
])
def test_typed_cold_nulls_are_unknown_for_each_requested_group(bridge, typed_team, kwargs, paths):
    m, reference = typed_team
    m['vec'](m['team'] + 0x38, [m['compact']])
    result = bridge.query_team_players(bridge.session, reference, include_virtual=True, **kwargs)
    partition(result, ['unclassified'])
    unknown = result['unclassified_players'][0]
    assert unknown['unavailable_fields'] == paths
    assert result['classifications'][0]['unavailable_fields'] == paths
    row = unknown['player']
    assert row['name'] is row['display_name'] is row['birth_date'] is row['attributes'] is None
    assert row['native_identity'] == {'database_index': 1, 'native_id': 12345, 'random_id': None}
    assert row['roster_context']['team_native_id'] == 1478
    assert row['profile_state'] == 'identity_only'
    assert row['profile_unavailable_reason'] == 'negative_cache_index'
    assert bridge.get_player(bridge.session, row['player_ref'], profile_policy='available')['player']['native_identity'] == row['native_identity']
    for field, requested in [('clubs', 'loan_status' in kwargs),
                             ('profile', 'minimum_profile' in kwargs or kwargs.get('sort_by', '').startswith('ability.')),
                             ('health', any(k in kwargs for k in ('minimum_health', 'maximum_health', 'injury_records')) or kwargs.get('sort_by', '').startswith('health.'))]:
        if requested:
            assert row[field] is None
            assert field in row['unavailable_fields']
        else:
            assert field not in row


def rich(index, name='Alpha', *, kind='actual', passing=15, decisions=16, loan=False):
    return {'roster_index': index, 'player_ref': f'p{index}', 'record_kind': kind,
        'name': name, 'display_name': name, 'birth_date': '2000-01-01',
        'attributes': {'passing': passing, 'vision': 15, 'decisions': decisions},
        'clubs': {'on_loan': loan}, 'profile_state': 'cached' if kind == 'virtual' else 'stored_direct',
        'unavailable_fields': [], 'native_identity': {'database_index': index, 'native_id': index + 100, 'random_id': 0},
        'roster_context': {'team_native_id': 1478},
        'profile': {'ability': {'current': 150, 'potential': 180, 'potential_state': 'fixed',
                                'potential_native_code': 180, 'potential_range': None}},
        'health': {'state': 'stored_without_refresh', 'condition': 9000, 'match_sharpness': 9500,
                   'fatigue': -100, 'injury_record_count': 0, 'unavailable_fields': []}}


def cold(index):
    row = rich(index, kind='virtual')
    for key in ('name', 'display_name', 'birth_date', 'attributes', 'profile', 'health', 'clubs'):
        row[key] = None
    row.update(profile_state='identity_only', profile_unavailable_reason='negative_cache_index',
               unavailable_fields=['name', 'display_name', 'birth_date', 'attributes', 'profile', 'health', 'clubs'])
    return row


def source(bridge, monkeypatch, rows, *, failure=None, count=None):
    """Source transport fake only; real public query and production selector execute."""
    original = deepcopy(rows)
    calls = []
    def read(*args, **kwargs):
        calls.append(kwargs)
        for row in rows:
            bridge.player_refs[row.get('player_ref', 'malformed')] = {'source': row.get('roster_index')}
        if failure:
            failure()
        return {'players': deepcopy(rows), 'count': len(rows) if count is None else count,
                'observed_at': 'synthetic-observation', 'save': {'current_date': '2030-10-28'},
                'club': {'name': 'FC Porto'}, 'label': 'Senior', 'limitations': 'Synthetic source.'}
    monkeypatch.setattr(bridge, 'get_team_squad', read)
    return original, calls


def test_full_partition_limit_and_combined_support_are_independent_of_names(bridge, monkeypatch):
    rows = [rich(0, 'C', passing=14), rich(1, 'b', kind='player_staff'),
            rich(2, 'A'), cold(3), rich(4, 'D', kind='virtual', decisions=20)]
    before, calls = source(bridge, monkeypatch, rows)
    kwargs = {'minimum_attributes': {'passing': 15, 'vision': 15}, 'sort_by': 'decisions', 'limit': 1}
    result = bridge.query_team_players(bridge.session, 'team', **kwargs)
    partition(result, ['nonmatch', 'match', 'match', 'typeexcluded', 'typeexcluded'])
    assert [p['roster_index'] for p in result['players']] == [2]
    assert result['matched_count'] == 2 and result['truncated'] is True
    result = bridge.query_team_players(bridge.session, 'team', include_virtual=True, **kwargs)
    partition(result, ['nonmatch', 'match', 'match', 'unclassified', 'match'])
    assert [p['roster_index'] for p in result['players']] == [4]
    assert result['matched_count'] == 3
    assert rows == before
    assert all(c == {'include_clubs': False, 'profile_policy': 'available'} for c in calls)


def test_synthetic_sixteen_population_includes_both_combined_rows_before_limit(bridge, monkeypatch):
    rows = [rich(i, f'Player {i:02}', kind='actual' if i < 13 else 'player_staff') for i in range(15)]
    rows.append(cold(15))
    source(bridge, monkeypatch, rows)
    query = {'minimum_attributes': {'passing': 15, 'vision': 15}, 'sort_by': 'decisions'}
    result = bridge.query_team_players(bridge.session, 'team', limit=1, **query)
    partition(result, ['match'] * 15 + ['typeexcluded'])
    assert result['matched_count'] == 15 and result['returned_count'] == 1
    included = bridge.query_team_players(bridge.session, 'team', include_virtual=True, **query)
    partition(included, ['match'] * 15 + ['unclassified'])
    assert [row['roster_index'] for row in included['players']] == list(range(15))
    assert [row['record_kind'] for row in included['players'][-2:]] == ['player_staff', 'player_staff']
    assert included['unclassified_players'][0]['player']['native_identity']['database_index'] == 15


def test_empty_complete_roster_has_explicit_zero_partition(bridge, monkeypatch):
    source(bridge, monkeypatch, [])
    result = bridge.query_team_players(bridge.session, 'team')
    partition(result, [])
    assert result['players'] == result['unclassified_players'] == []
    assert result['truncated'] is False


@pytest.mark.parametrize('kwargs,mutate', [
    ({'minimum_attributes': {'passing': 15}}, lambda r: r['attributes'].update(passing=14)),
    ({'loan_status': 'not_on_loan'}, lambda r: r['clubs'].update(on_loan=True)),
    ({'injury_records': 'without_records'}, lambda r: r['health'].update(injury_record_count=1)),
    ({'minimum_health': {'fatigue': 0}}, lambda r: None),
    ({'maximum_health': {'fatigue': -101}}, lambda r: None),
    ({'minimum_profile': {'ability.current': 151}}, lambda r: None),
])
def test_known_nonmatch_dominates_valid_unknown_potential(bridge, monkeypatch, kwargs, mutate):
    row = rich(0)
    row['profile']['ability'].update(potential=None, potential_state='range', potential_native_code=-95,
                                     potential_range=[160, 190])
    mutate(row)
    source(bridge, monkeypatch, [row])
    options = dict(kwargs)
    minima = {'ability.potential': 180, **options.pop('minimum_profile', {})}
    result = bridge.query_team_players(bridge.session, 'team', minimum_profile=minima, **options)
    partition(result, ['nonmatch'])
    assert result['unclassified_players'] == []


def test_inclusive_profile_health_loan_and_injury_predicates_keep_signed_fatigue(bridge, monkeypatch):
    rows = [rich(0, 'B', kind='player_staff'), rich(1, 'A', loan=True), rich(2, 'C')]
    rows[2]['health']['injury_record_count'] = 1
    source(bridge, monkeypatch, rows)
    result = bridge.query_team_players(bridge.session, 'team', minimum_profile={'ability.current': 150},
        minimum_health={'condition': 9000, 'fatigue': -100}, maximum_health={'fatigue': -100},
        loan_status='not_on_loan', injury_records='without_records', sort_by='health.fatigue')
    partition(result, ['match', 'nonmatch', 'nonmatch'])
    assert result['players'][0]['record_kind'] == 'player_staff'
    assert result['players'][0]['health']['fatigue'] == -100


@pytest.mark.parametrize('sort_by', [None, 'decisions', 'ability.current', 'health.condition'])
def test_rich_sort_ties_keep_casefold_dob_and_native_stability(bridge, monkeypatch, sort_by):
    rows = [rich(0, 'beta'), rich(1, 'ALPHA'), rich(2, 'alpha'), rich(3, 'Alpha')]
    rows[1]['birth_date'] = '2001-01-01'
    source(bridge, monkeypatch, rows)
    result = bridge.query_team_players(bridge.session, 'team', sort_by=sort_by, limit=3)
    partition(result, ['match'] * 4)
    assert [p['roster_index'] for p in result['players']] == [2, 3, 1]
    assert result['truncated'] is True and result['matched_count'] == 4


@pytest.mark.parametrize('sort_by,key', [('decisions', 'attributes'), ('ability.current', 'profile'),
                                       ('health.condition', 'health')])
def test_rich_numeric_sort_is_descending_before_name(bridge, monkeypatch, sort_by, key):
    rows = [rich(0, 'A'), rich(1, 'Z')]
    if key == 'attributes': rows[1][key]['decisions'] = 17
    elif key == 'profile': rows[1][key]['ability']['current'] = 151
    else: rows[1][key]['condition'] = 9001
    source(bridge, monkeypatch, rows)
    result = bridge.query_team_players(bridge.session, 'team', sort_by=sort_by)
    assert [p['roster_index'] for p in result['players']] == [1, 0]


def test_partial_virtual_health_and_range_potential_are_explicit_unknowns(bridge, monkeypatch):
    rows = [rich(0), rich(1, kind='virtual')]
    rows[0]['profile']['ability'].update(potential=None, potential_state='unmapped_range',
        potential_native_code=-11, potential_range=None)
    rows[1]['health'].update(state='partial_virtual', condition=None, match_sharpness=None,
        unavailable_fields=['condition', 'match_sharpness'])
    source(bridge, monkeypatch, rows)
    result = bridge.query_team_players(bridge.session, 'team', include_virtual=True,
        minimum_profile={'ability.potential': 170}, minimum_health={'condition': 8000})
    partition(result, ['unclassified', 'unclassified'])
    assert [p['unavailable_fields'] for p in result['unclassified_players']] == [
        ['ability.potential'], ['health.condition']]


@pytest.mark.parametrize('fault', ['missing_attribute', 'bool_attribute', 'null_actual', 'unmarked_cold',
    'missing_ref', 'duplicate_index', 'unknown_kind', 'bool_index', 'profile_null', 'bad_range',
    'bad_health_null', 'bad_loan', 'missing_name', 'bad_dob', 'population_count'])
def test_malformed_source_fails_without_new_refs_or_accepted_partial(bridge, monkeypatch, fault):
    rows = [rich(0), rich(1)]
    count = None
    if fault == 'missing_attribute': del rows[1]['attributes']['passing']
    if fault == 'bool_attribute': rows[1]['attributes']['passing'] = True
    if fault == 'null_actual': rows[1]['attributes'] = None
    if fault == 'unmarked_cold': rows[1] = cold(1); rows[1]['unavailable_fields'].remove('attributes')
    if fault == 'missing_ref': del rows[1]['player_ref']
    if fault == 'duplicate_index': rows[1]['roster_index'] = 0
    if fault == 'unknown_kind': rows[1]['record_kind'] = 'unknown'
    if fault == 'bool_index': rows[1]['roster_index'] = True
    if fault == 'profile_null': rows[1]['profile'] = None
    if fault == 'bad_range': rows[1]['profile']['ability']['potential'] = None
    if fault == 'bad_health_null': rows[1]['health']['condition'] = None
    if fault == 'bad_loan': rows[1]['clubs']['on_loan'] = 0
    if fault == 'missing_name': del rows[1]['display_name']
    if fault == 'bad_dob': rows[1]['birth_date'] = 2000
    if fault == 'population_count': count = 3
    # A known failing predicate does not authorize accepting malformed requested fields.
    rows[1]['attributes'] = rows[1].get('attributes')
    if isinstance(rows[1]['attributes'], dict): rows[1]['attributes']['vision'] = 1
    bridge.player_refs['keep'] = {'identity': 'preexisting'}
    source(bridge, monkeypatch, rows, count=count)
    with pytest.raises(BridgeError):
        bridge.query_team_players(bridge.session, 'team', include_virtual=True,
            minimum_attributes={'passing': 15, 'vision': 15}, minimum_profile={'ability.potential': 170},
            minimum_health={'condition': 8000}, loan_status='not_on_loan')
    assert bridge.player_refs == {'keep': {'identity': 'preexisting'}}


def test_late_source_failure_removes_new_refs_without_resurrecting_invalid_old(bridge, monkeypatch):
    bridge.player_refs.update(keep={'identity': 1}, stale={'identity': 2})
    def fail():
        bridge.player_refs.pop('stale')
        raise BridgeError('source bytes changed after first row')
    source(bridge, monkeypatch, [rich(0), rich(1)], failure=fail)
    with pytest.raises(BridgeError, match='source bytes changed'):
        bridge.query_team_players(bridge.session, 'team')
    assert bridge.player_refs == {'keep': {'identity': 1}}


@pytest.mark.parametrize('fault', ['membership', 'intra_read_drift', 'late_classification'])
def test_typed_native_errors_remain_errors_and_cleanup(bridge, monkeypatch, typed_team, fault):
    m, reference = typed_team
    before = dict(bridge.player_refs)
    if fault == 'membership': m['q'](m['compact_person'] + 8, 0xFFFFFFFF)
    if fault == 'intra_read_drift':
        original = virtual.decode
        def changing(*a, **kw):
            result = original(*a, **kw)
            m['put'](m['compact'] + 0x30, struct.pack('<I', 0))
            return result
        monkeypatch.setattr(virtual, 'decode', changing)
    if fault == 'late_classification':
        original = bridge.get_team_squad
        def malformed(*a, **kw):
            result = original(*a, **kw)
            result['players'][0]['attributes']['dribbling'] = True
            return result
        monkeypatch.setattr(bridge, 'get_team_squad', malformed)
    with pytest.raises(BridgeError):
        bridge.query_team_players(bridge.session, reference, include_virtual=True,
            minimum_attributes={'dribbling': 15})
    assert bridge.player_refs == before


@pytest.mark.parametrize('kwargs', [{'minimum_attributes': {'passing': True}}, {'include_virtual': 1},
    {'loan_status': 'unknown'}, {'limit': 0}, {'sort_by': 'name'},
    {'minimum_profile': {'ability.current': 201}}, {'minimum_health': {'condition': -1}},
    {'maximum_health': {'fatigue': -32769}}, {'injury_records': 'fit'}])
def test_public_validation_precedes_source_reads(bridge, monkeypatch, kwargs):
    monkeypatch.setattr(bridge, 'get_team_squad', lambda *a, **kw: pytest.fail('Invalid query collected source'))
    with pytest.raises(BridgeError): bridge.query_team_players(bridge.session, 'team', **kwargs)


def test_mcp_existing_query_schema_defaults_and_read_annotation():
    from fm_live_mcp.server import mcp
    tool = next(t for t in asyncio.run(mcp.list_tools()) if t.name == 'fm_query_team_players')
    assert set(tool.inputSchema['required']) == {'session_id', 'team_ref'}
    props = tool.inputSchema['properties']
    assert set(props) == {'session_id', 'team_ref', 'minimum_attributes', 'sort_by', 'limit',
        'include_virtual', 'loan_status', 'minimum_profile', 'minimum_health', 'maximum_health', 'injury_records'}
    assert props['include_virtual']['default'] is False
    assert props['limit']['default'] == 20
    assert props['loan_status']['default'] == props['injury_records']['default'] == 'any'
    assert 'profile_policy' not in props
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.openWorldHint is False


def test_typed_foreign_cache_is_unclassified_without_borrowing_rich_fields(bridge, typed_team):
    m, reference = typed_team
    m['put'](m['compact'] + 0x14, struct.pack('<h', 0))
    m['put'](m['warm_cache_address'] + 0x394, struct.pack('<I', 999))
    result = bridge.query_team_players(bridge.session, reference, include_virtual=True,
        minimum_attributes={'dribbling': 15})
    partition(result, ['match', 'unclassified'])
    row = result['unclassified_players'][0]['player']
    assert row['native_identity']['native_id'] == 12345
    assert row['profile_unavailable_reason'] == 'cache_identity_mismatch'
    assert all(row[field] is None for field in ('name', 'display_name', 'birth_date', 'attributes'))
    with pytest.raises(BridgeError):
        bridge.get_player(bridge.session, row['player_ref'], profile_policy='required')
