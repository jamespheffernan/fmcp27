"""Independent arithmetic and source-state cases for stored League rankings."""
from copy import deepcopy

import pytest

from fm_live_mcp.performance_metrics import rank_current_players


def candidate(index, minutes=450, goals=1, assists=0, *, kind='actual'):
    return {'roster_index': index, 'record_kind': kind,
            'statistics': {'state': 'stored_without_refresh', 'categories': [
                {'native_code': 1, 'name': 'League', 'availability': 'resident',
                 'statistics': {'minutes': minutes, 'goals': goals, 'assists': assists}}]}}


def league(row):
    return row['statistics']['categories'][0]['statistics']


def test_partition_limit_and_exact_ties_preserve_input_classification_order():
    candidates = [candidate(9, 900, 3, 2), candidate(2, 450, 2, 1),
                  candidate(7, 600, 3, 1), candidate(3, 600, 1, 3),
                  candidate(8, 450, 0, 0), candidate(11, 449, None, None),
                  candidate(12, 0, None, None), candidate(13, -1),
                  candidate(14, None), candidate(15, 450, None, 1),
                  {'roster_index': 16, 'record_kind': 'actual', 'statistics': None},
                  {'roster_index': 17, 'record_kind': 'virtual', 'statistics': 'unsupported is ignored'},
                  candidate(18, kind='player_staff'),
                  {'roster_index': 20, 'record_kind': 'actual',
                   'statistics': {'state': 'unavailable_not_resident', 'categories': []}},
                  {'roster_index': 21, 'record_kind': 'actual',
                   'statistics': {'state': 'stored_without_refresh', 'categories': []}},
                  {'roster_index': 22, 'record_kind': 'actual', 'statistics': {
                      'categories': [{'native_code': 1, 'name': 'League', 'statistics': None}]}}]
    before = deepcopy(candidates)
    result = rank_current_players(candidates, minimum_minutes=450, limit=3)
    assert result['rows'] == [
        {'roster_index': 3, 'rank': 1, 'minutes': 600, 'goals': 1, 'assists': 3,
         'goals_plus_assists': 4, 'per90': {'numerator': 3, 'denominator': 5, 'value': 0.6}},
        {'roster_index': 7, 'rank': 2, 'minutes': 600, 'goals': 3, 'assists': 1,
         'goals_plus_assists': 4, 'per90': {'numerator': 3, 'denominator': 5, 'value': 0.6}},
        {'roster_index': 2, 'rank': 3, 'minutes': 450, 'goals': 2, 'assists': 1,
         'goals_plus_assists': 3, 'per90': {'numerator': 3, 'denominator': 5, 'value': 0.6}}]
    assert result['counts'] == {'roster_count': 16, 'actual_count': 14, 'unsupported_count': 2,
                                'unknown_count': 7, 'below_minimum_count': 2,
                                'qualifying_count': 5, 'returned_count': 3}
    assert [row['roster_index'] for row in result['classifications']] == [row['roster_index'] for row in candidates]
    assert [row['state'] for row in result['classifications']] == (
        ['qualified'] * 5 + ['below_minimum'] * 2 + ['unknown'] * 4 +
        ['unsupported'] * 2 + ['unknown'] * 3)
    assert result['ranking_complete_among_supported'] is False
    assert result['ranking_complete_for_roster'] is False
    assert candidates == before


def test_native_league_only_ignores_other_categories_extra_teams_and_archives():
    row = candidate(0, 500, 2, 3)
    row['statistics']['categories'] += [
        {'native_code': 0, 'name': 'Non Competitive', 'statistics': {'goals': 200}},
        {'native_code': 5, 'name': 'Overall (Club)', 'statistics': {'goals': 250}}]
    row['statistics']['additional_team_rows'] = [{'statistics': {'goals': 254}}]
    row['statistics']['archive'] = {'goals': 254}
    result = rank_current_players([row])['rows'][0]
    assert result['goals_plus_assists'] == 5
    assert result['per90'] == {'numerator': 9, 'denominator': 10, 'value': 0.9}


def test_exact_fraction_orders_close_values_before_minutes_tie_break():
    result = rank_current_players([candidate(0, 32767), candidate(1, 32766)], minimum_minutes=0)
    assert [row['roster_index'] for row in result['rows']] == [1, 0]
    assert result['rows'][0]['per90']['numerator'] == 15
    assert result['rows'][0]['per90']['denominator'] == 5461
    assert result['rows'][1]['per90']['numerator'] == 90
    assert result['rows'][1]['per90']['denominator'] == 32767
    assert result['rows'][0]['per90']['value'] > result['rows'][1]['per90']['value']


def test_threshold_boundary_zero_and_missing_counters_have_distinct_states():
    result = rank_current_players([candidate(0, 449, None, None),
                                   candidate(1, 450, None, 0),
                                   candidate(2, 450, 0, 0), candidate(3, 0, None, None)])
    assert result['classifications'] == [
        {'roster_index': 0, 'state': 'below_minimum', 'reason': 'below_minimum_minutes'},
        {'roster_index': 1, 'state': 'unknown', 'reason': 'missing_goals_or_assists'},
        {'roster_index': 2, 'state': 'qualified', 'reason': 'meets_minimum_minutes'},
        {'roster_index': 3, 'state': 'below_minimum', 'reason': 'no_playing_time'}]
    assert result['rows'][0]['per90'] == {'numerator': 0, 'denominator': 1, 'value': 0.0}
    zero_threshold = rank_current_players([candidate(0, 0, None, None), candidate(1, 1)], minimum_minutes=0)
    assert zero_threshold['classifications'][0]['state'] == 'below_minimum'
    assert zero_threshold['rows'][0]['per90'] == {'numerator': 90, 'denominator': 1, 'value': 90.0}


@pytest.mark.parametrize('minutes,reason', [(None, 'missing_minutes'), (-1, 'negative_minutes'),
                                            (-32768, 'negative_minutes')])
def test_missing_or_negative_minutes_remain_unknown(minutes, reason):
    result = rank_current_players([candidate(0, minutes)])
    assert result['classifications'] == [{'roster_index': 0, 'state': 'unknown', 'reason': reason}]
    assert result['counts']['unknown_count'] == 1 and result['rows'] == []


def test_missing_minutes_key_is_unknown():
    row = candidate(0)
    del league(row)['minutes']
    assert rank_current_players([row])['classifications'][0]['reason'] == 'missing_minutes'


@pytest.mark.parametrize('source,reason', [
    (None, 'missing_statistics_source'),
    ({'state': 'unavailable_not_resident'}, 'unavailable_statistics_source'),
    ({}, 'missing_league_category'), ({'categories': []}, 'missing_league_category'),
    ({'categories': [{'native_code': 2, 'statistics': {'minutes': 900, 'goals': 254}}]}, 'missing_league_category'),
    ({'categories': [{'native_code': 1, 'name': 'League', 'statistics': None}]}, 'unavailable_league_category'),
    ({'categories': [{'native_code': 1, 'availability': 'unavailable_null_category', 'statistics': None}]}, 'unavailable_league_category'),
])
def test_missing_source_and_category_states_are_unknown(source, reason):
    result = rank_current_players([{'roster_index': 4, 'record_kind': 'actual', 'statistics': source}])
    assert result['classifications'] == [{'roster_index': 4, 'state': 'unknown', 'reason': reason}]


def test_optional_category_name_may_be_omitted():
    row = candidate(0)
    del row['statistics']['categories'][0]['name']
    assert rank_current_players([row])['counts']['qualifying_count'] == 1


def test_duplicate_league_codes_reject_even_when_source_unavailable():
    row = candidate(0)
    row['statistics']['state'] = 'unavailable_not_resident'
    row['statistics']['categories'] *= 2
    with pytest.raises(ValueError, match='Duplicate'):
        rank_current_players([row])


@pytest.mark.parametrize('kind', ['virtual', 'player_staff', 'unrecognized'])
def test_unsupported_records_are_classified_before_statistics_validation(kind):
    result = rank_current_players([{'roster_index': 0, 'record_kind': kind, 'statistics': object()}])
    assert result['classifications'] == [{'roster_index': 0, 'state': 'unsupported', 'reason': 'unsupported_record_kind'}]
    assert result['counts']['actual_count'] == 0
    assert result['ranking_complete_among_supported'] is True
    assert result['ranking_complete_for_roster'] is False


def test_empty_and_fully_classified_rosters_are_complete_even_when_limited():
    empty = rank_current_players([])
    assert empty['ranking_complete_among_supported'] is empty['ranking_complete_for_roster'] is True
    assert set(empty['counts'].values()) == {0}
    result = rank_current_players([candidate(0, 449, None, None), candidate(1, 600), candidate(2, 900)], limit=1)
    assert result['counts']['qualifying_count'] == 2 and result['counts']['returned_count'] == 1
    assert result['ranking_complete_among_supported'] is result['ranking_complete_for_roster'] is True


@pytest.mark.parametrize('field', ['goals', 'assists'])
@pytest.mark.parametrize('value', [-1, 255, True, False, 1.0, '1', [], {}])
@pytest.mark.parametrize('minutes', [0, 449, 450])
def test_known_malformed_counters_reject_even_below_threshold(field, value, minutes):
    row = candidate(0, minutes)
    league(row)[field] = value
    with pytest.raises(ValueError, match=field):
        rank_current_players([row])


def test_largest_proved_counter_values_and_threshold_boundaries():
    result = rank_current_players([candidate(0, 32767, 254, 254)], minimum_minutes=32767, limit=25)
    assert result['rows'][0]['goals_plus_assists'] == 508
    assert result['rows'][0]['per90']['numerator'] == 45720
    assert result['rows'][0]['per90']['denominator'] == 32767


@pytest.mark.parametrize('minutes', [True, False, 450.0, '450', [], {}])
def test_malformed_minutes_reject(minutes):
    with pytest.raises(ValueError, match='minutes'):
        rank_current_players([candidate(0, minutes)])


@pytest.mark.parametrize('minimum', [-1, 32768, True, False, 450.0, '450', None])
def test_invalid_minimum_minutes_reject(minimum):
    with pytest.raises(ValueError, match='minimum_minutes'):
        rank_current_players([], minimum_minutes=minimum)


@pytest.mark.parametrize('limit', [0, 26, True, False, 5.0, '5', None])
def test_invalid_limit_reject(limit):
    with pytest.raises(ValueError, match='limit'):
        rank_current_players([], limit=limit)


@pytest.mark.parametrize('candidates', [None, (), {}, [None], [{}],
    [{'roster_index': True, 'record_kind': 'actual'}],
    [{'roster_index': -1, 'record_kind': 'actual'}],
    [{'roster_index': 1.0, 'record_kind': 'actual'}],
    [{'roster_index': 0, 'record_kind': None}],
    [{'roster_index': 0, 'record_kind': ''}],
    [candidate(0), candidate(0)]])
def test_invalid_candidate_structure_and_duplicate_indices_reject(candidates):
    with pytest.raises(ValueError):
        rank_current_players(candidates)


@pytest.mark.parametrize('source', [
    [], {'state': 'unknown_state'}, {'categories': {}}, {'categories': [None]},
    {'categories': [{'native_code': True}]}, {'categories': [{'native_code': 1.0}]},
    {'categories': [{'statistics': {}}]},
    {'categories': [{'native_code': 1, 'name': 'Cup', 'statistics': {}}]},
    {'categories': [{'native_code': 1, 'name': None, 'statistics': {}}]},
    {'categories': [{'native_code': 1, 'availability': 'unknown', 'statistics': {}}]},
    {'categories': [{'native_code': 1, 'statistics': []}]},
    {'categories': [{'native_code': 1, 'statistics': None}, {'native_code': 1, 'statistics': None}]},
])
def test_malformed_league_source_rejects(source):
    with pytest.raises(ValueError):
        rank_current_players([{'roster_index': 0, 'record_kind': 'actual', 'statistics': source}])
