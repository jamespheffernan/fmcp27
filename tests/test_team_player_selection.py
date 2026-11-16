"""Handwritten selector expectations; no native collection or generated profiles."""
from copy import deepcopy

import pytest

from fm_live_mcp.team_player_selection import select


def criteria(**changes):
    return {'minimum_attributes': {}, 'minimum_profile': {}, 'minimum_health': {},
            'maximum_health': {}, 'include_virtual': False, 'loan_status': 'any',
            'injury_records': 'any', 'sort_by': None, **changes}


def rich(index, name='Player', birthday='2000-01-01', kind='actual'):
    return {'roster_index': index, 'player_ref': f'player-{index}', 'record_kind': kind,
            'name': name, 'display_name': name, 'birth_date': birthday,
            'attributes': {'passing': 16, 'vision': 16, 'decisions': 14, 'pace': 12},
            'profile': {'ability': {'current': 150, 'potential': 180, 'potential_native_code': 180,
                                    'potential_state': 'fixed', 'potential_range': None},
                        'positions': {'striker': 14}, 'goalkeeping': {'reflexes': 15},
                        'hidden_attributes': {'consistency': 10}, 'feet': {'left': 0, 'right': 20},
                        'personality': {'professionalism': 12}},
            'health': {'condition': 9000, 'match_sharpness': 8000, 'fatigue': -200,
                       'injury_record_count': 1, 'state': 'stored_without_refresh', 'unavailable_fields': []},
            'clubs': {'on_loan': False},
            'profile_state': 'cached' if kind == 'virtual' else 'stored_direct',
            'native_identity': {'database_index': index, 'native_id': index + 1000, 'random_id': None},
            'roster_context': {'team_database_index': 1155}, 'unavailable_fields': []}


def cold(index):
    row = rich(index, kind='virtual')
    row.update(profile_state='identity_only', profile_unavailable_reason='negative_cache_index',
               name=None, display_name=None, birth_date=None, attributes=None,
               profile=None, health=None, clubs=None,
               unavailable_fields=['attributes', 'birth_date', 'clubs', 'display_name', 'health', 'name', 'profile'])
    return row


def range_potential(row, code=-95, state='range'):
    row['profile']['ability'].update(potential=None, potential_native_code=code,
                                      potential_state=state, potential_range=[160, 190] if code == -95 else None)
    return row


def partial_health(row):
    row['health'].update(condition=None, match_sharpness=None, fatigue=0, injury_record_count=0,
                         state='partial_virtual', unavailable_fields=['condition', 'match_sharpness'])
    return row


def test_complete_partition_limit_and_original_rows_are_preserved():
    first, second = rich(0, 'Zulu'), rich(1, 'Alpha', kind='player_staff')
    second['attributes']['decisions'] = 18
    failed = rich(2);failed['attributes']['passing'] = 14
    unknown = range_potential(rich(4))
    rows = [first, second, failed, cold(3), unknown]
    before = deepcopy(rows)
    result = select(rows, criteria(minimum_attributes={'passing': 15, 'vision': 15},
                                   minimum_profile={'ability.potential': 170}, sort_by='decisions'), 1)
    assert result['players'] == [second] and result['players'][0] is second
    assert result['matched_count'] == 2 and result['returned_count'] == 1 and result['truncated'] is True
    assert result['unclassified_players'] == [{'player': unknown, 'unavailable_fields': ['ability.potential']}]
    assert result['classifications'] == [
        {'roster_index': 0, 'state': 'match', 'reason': 'all_required_values_match', 'unavailable_fields': []},
        {'roster_index': 1, 'state': 'match', 'reason': 'all_required_values_match', 'unavailable_fields': []},
        {'roster_index': 2, 'state': 'nonmatch', 'reason': 'known_predicate_failed', 'unavailable_fields': []},
        {'roster_index': 3, 'state': 'typeexcluded', 'reason': 'virtual_excluded', 'unavailable_fields': []},
        {'roster_index': 4, 'state': 'unclassified', 'reason': 'required_values_unavailable',
         'unavailable_fields': ['ability.potential']}]
    assert result['counts'] == {'roster_count': 5, 'match_count': 2, 'nonmatch_count': 1,
                                'typeexcluded_count': 1, 'unclassified_count': 1}
    assert result['complete_for_included_population'] is False
    assert rows == before


def test_cold_type_exclusion_precedes_any_field_inspection():
    row = cold(0)
    row.update(attributes='malformed but excluded', health=123, profile=[], clubs=True)
    del row['display_name'];del row['birth_date']
    result = select([row], criteria(minimum_attributes={'passing': 15}, minimum_profile={'ability.current': 100},
                                     minimum_health={'condition': 9000}, injury_records='with_records',
                                     loan_status='on_loan', sort_by='decisions'), 10)
    assert result['classifications'][0]['state'] == 'typeexcluded'
    assert result['complete_for_included_population'] is True


def test_included_cold_retains_all_required_unknown_paths_without_fake_values():
    row = cold(15)
    result = select([row], criteria(include_virtual=True, minimum_attributes={'passing': 15, 'vision': 15},
                                     sort_by='decisions', minimum_profile={'ability.current': 150},
                                     minimum_health={'condition': 9000}, maximum_health={'fatigue': 0},
                                     loan_status='on_loan', injury_records='with_records'), 1)
    missing = ['ability.current', 'attributes.decisions', 'attributes.passing', 'attributes.vision',
               'birth_date', 'clubs.on_loan', 'display_name', 'health.condition',
               'health.fatigue', 'health.injury_record_count']
    assert result['players'] == []
    assert result['unclassified_players'] == [{'player': row, 'unavailable_fields': missing}]
    assert result['classifications'][0]['unavailable_fields'] == missing
    assert row['attributes'] is None and row['clubs'] is None and row['native_identity']['native_id'] == 1015


def test_default_cold_name_sort_is_unknown_even_without_numeric_predicates():
    result = select([cold(0)], criteria(include_virtual=True), 1)
    assert result['unclassified_players'][0]['unavailable_fields'] == ['birth_date', 'display_name']


@pytest.mark.parametrize('failure', ['attributes', 'profile', 'minimum_health', 'maximum_health', 'loan', 'injury'])
def test_any_known_failure_dominates_other_valid_unknown_values(failure):
    row = partial_health(range_potential(rich(0, kind='virtual')))
    query = criteria(include_virtual=True, minimum_profile={'ability.potential': 170},
                     minimum_health={'condition': 9000})
    if failure == 'attributes':query['minimum_attributes'] = {'passing': 17}
    elif failure == 'profile':query['minimum_profile']['ability.current'] = 151
    elif failure == 'minimum_health':query['minimum_health']['fatigue'] = 1
    elif failure == 'maximum_health':query['maximum_health']['fatigue'] = -1
    elif failure == 'loan':query['loan_status'] = 'on_loan'
    else:query['injury_records'] = 'with_records'
    result = select([row], query, 10)
    assert result['classifications'][0] == {'roster_index': 0, 'state': 'nonmatch',
                                          'reason': 'known_predicate_failed', 'unavailable_fields': []}
    assert result['unclassified_count'] == 0 and result['complete_for_included_population'] is True


@pytest.mark.parametrize('field', ['passing', 'vision', 'decisions'])
def test_malformed_requested_value_is_error_even_after_a_known_failure(field):
    row = rich(0);row['attributes'].update(passing=1, vision=1, decisions=1)
    row['attributes'][field] = 'bad'
    with pytest.raises(ValueError):
        select([row], criteria(minimum_attributes={'passing': 15, 'vision': 15}, sort_by='decisions'), 1)


def test_legacy_numeric_name_date_and_stable_input_ties():
    rows = [rich(20, 'same', '2000-01-01'), rich(1, 'SAME', '2000-01-01'),
            rich(2, 'Same', '1999-01-01'), rich(3, 'Alpha'), rich(4, 'Zulu')]
    rows[4]['attributes']['decisions'] = 15
    ordered = select(rows, criteria(sort_by='decisions'), 100)['players']
    assert [row['roster_index'] for row in ordered] == [4, 3, 2, 20, 1]
    ordered = select(rows, criteria(), 100)['players']
    assert [row['roster_index'] for row in ordered] == [3, 2, 20, 1, 4]


@pytest.mark.parametrize('sort_by,first', [('ability.current', 1), ('positions.striker', 1),
                                        ('health.fatigue', 0), ('health.condition', 1)])
def test_profile_and_signed_health_sort_values(sort_by, first):
    a, b = rich(0, 'B'), rich(1, 'A')
    b['profile']['ability']['current'] = 151;b['profile']['positions']['striker'] = 15
    b['health'].update(condition=9001, fatigue=-300)
    result = select([a, b], criteria(sort_by=sort_by), 10)
    assert result['players'][0]['roster_index'] == first


def test_all_profile_groups_and_health_boundaries_are_inclusive():
    row = rich(0, kind='player_staff')
    query = criteria(minimum_profile={'ability.current': 150, 'ability.potential': 180,
                                      'positions.striker': 14, 'goalkeeping.reflexes': 15,
                                      'hidden_attributes.consistency': 10, 'feet.left': 0,
                                      'feet.right': 20, 'personality.professionalism': 12},
                     minimum_health={'condition': 9000, 'match_sharpness': 8000, 'fatigue': -200},
                     maximum_health={'fatigue': -200}, loan_status='not_on_loan', injury_records='with_records')
    assert select([row], query, 10)['matched_count'] == 1


@pytest.mark.parametrize('code,state', [(-95, 'range'), (-10, 'range'), (-100, 'unmapped_range')])
def test_fixed_potential_unknown_requires_the_verified_negative_code_state(code, state):
    row = range_potential(rich(0), code, state)
    result = select([row], criteria(sort_by='ability.potential'), 1)
    assert result['unclassified_players'][0]['unavailable_fields'] == ['ability.potential']


@pytest.mark.parametrize('code,state', [(180, 'fixed'), (-95, 'unmapped_range'), (-100, 'range'),
                                      (None, 'range'), (True, 'range'), (-101, 'unmapped_range')])
def test_unproved_potential_null_is_malformed(code, state):
    row = range_potential(rich(0), code, state)
    with pytest.raises(ValueError):select([row], criteria(minimum_profile={'ability.potential': 1}), 1)


def test_partial_virtual_health_preserves_unknown_condition_and_native_zero_injury_count():
    row = partial_health(rich(0, kind='virtual'))
    result = select([row], criteria(include_virtual=True, minimum_health={'condition': 1},
                                     injury_records='without_records'), 1)
    assert result['unclassified_players'][0]['unavailable_fields'] == ['health.condition']
    result = select([row], criteria(include_virtual=True, injury_records='with_records'), 1)
    assert result['counts']['nonmatch_count'] == 1


@pytest.mark.parametrize('group', ['attributes', 'profile', 'health', 'clubs'])
@pytest.mark.parametrize('fault', ['actual_null', 'missing_unavailable_marker', 'wrong_state', 'missing_group', 'wrong_type'])
def test_group_null_requires_explicit_cold_metadata_and_missing_structure_is_error(group, fault):
    row = cold(0)
    if fault == 'actual_null':row['record_kind'] = 'actual'
    elif fault == 'missing_unavailable_marker':row['unavailable_fields'].remove(group)
    elif fault == 'wrong_state':row['profile_state'] = 'cached'
    elif fault == 'missing_group':del row[group]
    else:row[group] = []
    queries = {'attributes': {'minimum_attributes': {'passing': 1}},
               'profile': {'minimum_profile': {'ability.current': 1}},
               'health': {'minimum_health': {'condition': 1}}, 'clubs': {'loan_status': 'on_loan'}}
    with pytest.raises(ValueError):select([row], criteria(include_virtual=True, **queries[group]), 1)


@pytest.mark.parametrize('path,value', [('attributes.passing', None), ('attributes.passing', True),
    ('attributes.passing', -1), ('attributes.passing', 21), ('ability.current', None),
    ('ability.current', 201), ('ability.current', 150.0), ('health.condition', None),
    ('health.condition', 10001), ('health.fatigue', -32769), ('clubs.on_loan', None),
    ('clubs.on_loan', 0), ('health.injury_record_count', None), ('health.injury_record_count', True),
    ('health.injury_record_count', -1)])
def test_requested_wrong_scalar_values_never_become_unknown(path, value):
    row = rich(0)
    group, key = path.split('.')
    target = row[group] if group in ('attributes', 'health', 'clubs') else row['profile'][group]
    target[key] = value
    if group == 'attributes':query = criteria(minimum_attributes={key: 1})
    elif group == 'clubs':query = criteria(loan_status='on_loan')
    elif key == 'injury_record_count':query = criteria(injury_records='with_records')
    else:query = criteria(sort_by=path)
    with pytest.raises(ValueError):select([row], query, 1)


@pytest.mark.parametrize('field,value', [('display_name', None), ('display_name', ''),
    ('display_name', 1), ('display_name', 'bad\nname'), ('birth_date', None),
    ('birth_date', '2001-02-29'), ('birth_date', '20000101'), ('birth_date', '1800-01-01')])
def test_missing_or_malformed_rich_sort_tie_fields_are_errors(field, value):
    row = rich(0);row[field] = value
    with pytest.raises(ValueError):select([row], criteria(), 1)


@pytest.mark.parametrize('key', ['display_name', 'birth_date'])
def test_absent_cold_sort_key_is_malformed_even_with_unavailable_marker(key):
    row = cold(0);del row[key]
    with pytest.raises(ValueError):select([row], criteria(include_virtual=True), 1)


def test_unclassified_entries_are_not_cut_off_by_match_limit():
    rows = [rich(0), rich(1), cold(2), cold(3)]
    result = select(rows, criteria(include_virtual=True), 1)
    assert result['matched_count'] == 2 and result['returned_count'] == 1
    assert result['unclassified_count'] == 2 and len(result['classifications']) == 4
    assert sum(result['counts'][key] for key in ('match_count', 'nonmatch_count', 'typeexcluded_count', 'unclassified_count')) == 4


@pytest.mark.parametrize('mutation', ['missing_ref', 'empty_ref', 'wrong_ref', 'duplicate_index',
                                     'negative_index', 'bool_index', 'unknown_kind', 'missing_kind'])
def test_invalid_identity_join_structure_rejects(mutation):
    rows = [rich(0), rich(1)]
    if mutation == 'missing_ref':del rows[0]['player_ref']
    elif mutation == 'empty_ref':rows[0]['player_ref'] = ''
    elif mutation == 'wrong_ref':rows[0]['player_ref'] = 1
    elif mutation == 'duplicate_index':rows[1]['roster_index'] = 0
    elif mutation == 'negative_index':rows[0]['roster_index'] = -1
    elif mutation == 'bool_index':rows[0]['roster_index'] = True
    elif mutation == 'unknown_kind':rows[0]['record_kind'] = 'unknown'
    else:del rows[0]['record_kind']
    with pytest.raises(ValueError):select(rows, criteria(), 1)


@pytest.mark.parametrize('limit', [0, 101, True, 1.0, None])
def test_invalid_limit_fails(limit):
    with pytest.raises(ValueError):select([], criteria(), limit)


def test_empty_roster_is_complete_and_partitioned():
    result = select([], criteria(), 1)
    assert result['players'] == [] and result['classifications'] == []
    assert result['complete_for_included_population'] is True
    assert set(result['counts'].values()) == {0}
