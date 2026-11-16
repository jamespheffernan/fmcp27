import pytest

from fm_live_mcp import league_scorers as source


def row(index, goals, **extra):
    return {'person_index': index, 'source_ordinal': index, 'goals': goals, **extra}


def test_goals_only_no_ga90_or_minutes_prefilter():
    candidates = [row(i, 1, assists=20, minutes=1) for i in range(30)]
    candidates.append(row(30, 7, assists=0, minutes=9000))
    result = source.rank_candidates(candidates, 1)
    assert [person['person_index'] for person in result['rows']] == [30]
    assert result['candidate_count'] == 31 and result['metric'] == 'goals'
    assert not result['minutes_filter_applied'] and not result['assists_filter_applied']


def test_cutoff_ties_included_with_competition_ranks():
    candidates = [row(0, 7), row(1, 6), row(2, 6), row(3, 5), row(4, 5)]
    result = source.rank_candidates(candidates, 2)
    assert [person['person_index'] for person in result['rows']] == [0, 1, 2]
    assert [person['rank'] for person in result['rows']] == [1, 2, 2]
    assert result['cutoff_ties_added'] == 1 and result['cutoff_goals'] == 6


def test_unknown_and_zero_separate_and_not_silently_negative():
    result = source.rank_candidates([row(0, None), row(1, 0), row(2, 2)])
    assert result['unknown_goals_count'] == 1 and result['zero_goals_count'] == 1
    assert result['unknown_candidates_present'] and len(result['rows']) == 1


def test_equal_scores_order_by_canonical_person_not_prefilter_order():
    candidates = [row(10, 5), row(3, 5), row(9, 5)]
    assert [person['person_index'] for person in source.rank_candidates(candidates, 1)['rows']] == [3, 9, 10]


def test_duplicate_person_or_ordinal_requires_explicit_collector_resolution():
    duplicate_person = [row(0, 1), {**row(0, 1), 'source_ordinal': 1}]
    duplicate_ordinal = [row(0, 1), {**row(1, 2), 'source_ordinal': 0}]
    for candidates in (duplicate_person, duplicate_ordinal):
        with pytest.raises(ValueError):
            source.rank_candidates(candidates)


def test_complete_large_tie_cannot_be_silently_cut():
    with pytest.raises(ValueError, match='Complete cutoff tie'):
        source.rank_candidates([row(i, 1) for i in range(source.MAX_OUTPUT_ROWS + 1)], 1)


def test_empty_or_zero_only_does_not_invent_positive_scorers():
    for candidates in ([], [row(0, 0)]):
        result = source.rank_candidates(candidates)
        assert result['rows'] == [] and result['cutoff_goals'] is None


@pytest.mark.parametrize('limit', [True, 0, -1, 51, '10', None])
def test_strict_limit(limit):
    with pytest.raises(ValueError):
        source.rank_candidates([], limit)


@pytest.mark.parametrize('goals', [True, -1, 1.0, '1', 2**31])
def test_normalized_scalar_validation(goals):
    with pytest.raises(ValueError):
        source.rank_candidates([row(0, goals)])


def test_unresolved_identity_allowed_only_as_unknown():
    result = source.rank_candidates([{'person_index': None, 'source_ordinal': 0, 'goals': None}])
    assert result['unknown_goals_count'] == 1
    with pytest.raises(ValueError):
        source.rank_candidates([{'person_index': None, 'source_ordinal': 0, 'goals': 1}])
