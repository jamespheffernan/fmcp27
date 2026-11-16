from copy import deepcopy
from unittest.mock import patch

import pytest

from fm_live_mcp.retained_shot_quality import report_shot_quality, summarize_shot_quality


def packet(ref, key, home, away, sides):
    teams = [{'native_id': tid, 'owner': {'name': str(tid)}} for tid in (home, away)]
    shots, coverage = [], []
    for side, values in enumerate(sides):
        coverage.append(dict(side_index=side, team_native_id=teams[side]['native_id'],
                             state='missing' if values is None else 'available',
                             shot_count=None if values is None else len(values)))
        for event, (person, xg, penalty) in enumerate(values or []):
            actor = {'canonical_person_id': person, 'person_name': str(person),
                     'canonical_team_id': teams[side]['native_id']} if person else None
            shots.append(dict(event_id=event, side_index=side, expected_goals=xg, is_penalty=penalty, actor=actor))
    return dict(fixture_ref=ref, native_match_key=key, side_coverage=coverage, shots=shots,
                fixture=dict(date='2030-10-26', home_team=teams[0], away_team=teams[1]),
                own_goal_markers=[{'expected_goals': 0}], observed_save_first={'day': 1},
                observed_save_last={'day': 1})


def test_against_across_venues_includes_real_zero_and_excludes_missing_and_own_goals():
    a = packet('a', 1, 7, 8, [None, [(22, .5, True), (None, .25, False), (11, .2, False)]])
    b = packet('b', 2, 9, 7, [[], [(55, .8, False)]])
    c = packet('c', 3, 10, 7, [None, []])
    r = summarize_shot_quality([a,b,c], 7, 'against', .2, 1)
    assert r['coverage'] == 'partial' and r['fixtures_with_verified_side'] == 2
    assert [i['metrics'] and i['metrics']['shots'] for i in r['fixtures']] == [3, 0, None]
    assert r['covered_fixture_totals']['non_penalty_shots_at_or_above_threshold'] == 2
    assert r['covered_fixture_totals']['non_penalty_xg'] == pytest.approx(.45)
    assert r['covered_fixture_totals']['best_non_penalty_shot_xg'] == .25
    assert r['covered_fixture_totals']['expected_goals'] == pytest.approx(.95)
    assert r['fixtures'][0]['best_chance']['shooter_id'] == 22
    assert r['fixtures'][0]['best_chance']['is_penalty'] is True
    assert r['unattributed_attempts_in_covered_fixtures'] == 1
    assert r['players_truncated'] and r['known_shooters_total'] == 2
    assert r['shooters_by_xg'][0]['person_id'] == 22


def test_team_for_unknown_penalty_and_tied_best():
    a = packet('a', 1, 7, 8, [[(11,.4,None),(11,.4,False)], []])
    r = summarize_shot_quality([a], 7, 'for', .5, 10)
    assert r['coverage'] == 'complete'
    assert r['covered_fixture_totals']['penalties'] is None
    assert r['covered_fixture_totals']['non_penalty_xg'] is None
    assert r['fixtures'][0]['best_chance']['equally_valued_attempts'] == 2
    assert r['shooters_by_xg'][0]['shots_at_or_above_threshold'] == 0


def test_no_coverage_returns_null():
    a = packet('a', 1, 7, 8, [None, []])
    r = summarize_shot_quality([a], 7, 'for', .2, 10)
    assert r['coverage'] == 'unavailable'
    assert r['covered_fixture_totals'] is r['known_shooters_total'] is None


def test_scope_and_changed_observation_fail_closed():
    a = packet('a', 1, 7, 8, [[], []])
    alias = deepcopy(a)
    alias['fixture_ref'] = 'another'
    with pytest.raises(ValueError, match='same result'):
        summarize_shot_quality([a, alias], 7, 'for', .2, 10)
    with pytest.raises(ValueError, match='contain'):
        summarize_shot_quality([a], 10, 'against', .2, 10)
    a['observed_save_last'] = {'day': 2}
    with patch('fm_live_mcp.retained_shot_quality.capture_retained_shot_maps', return_value={'records':[a]}):
        with pytest.raises(ValueError, match='career changed'):
            report_shot_quality(None, 'session', ['a'], 7, 'for')


def test_body_part_and_exclusive_outcome_breakdowns_preserve_unknowns():
    match = packet('a', 123, 7, 8, [[], [(21,.42,True), (22,.2,False), (22,.1,False), (99,.05,False)]])
    for shot, part, outcome in zip(match['shots'], (None,'head','head','feet'),
                                   ('saved','goal','missed_target',None), strict=True):
        shot.update(body_part=part, outcome=outcome)
    match['shots'][0]['body_part_state'] = 'native_type_unclassified'
    missing = packet('b', 124, 7, 9, [[],None])
    result = summarize_shot_quality([match, missing], 7, 'against', .20, 10)
    breakdown = result['covered_shot_breakdown']
    assert result['fixtures'][0]['shot_breakdown'] == breakdown
    assert result['fixtures'][1]['shot_breakdown'] is None
    assert result['fixtures'][0]['best_chance']['body_part'] is None
    assert result['fixtures'][0]['best_chance']['body_part_state'] == 'native_type_unclassified'
    assert result['fixtures'][0]['best_chance']['outcome'] == 'saved'
    headers = breakdown['by_body_part']['head']
    assert headers['shots'] == 2 and headers['goals'] == headers['shots_on_target'] == 1
    assert headers['best_shot_xg'] == .20 and headers['shots_at_or_above_threshold'] == 1
    assert headers['expected_goals'] == headers['non_penalty_xg'] == pytest.approx(.30)
    assert breakdown['by_body_part']['feet']['shots_on_target'] is None
    assert breakdown['by_body_part']['unclassified']['shots_on_target'] == 1
    assert sum(breakdown['terminal_outcome_counts'].values()) == 4
    assert breakdown['terminal_outcome_counts']['unclassified'] == 1
    assert breakdown['terminal_outcome_counts']['blocked'] == 0


def test_area_breakdown_keeps_native_boundary_fallback_out_of_known_outside_count():
    match = packet('a', 123, 7, 8, [[], [(21, .42, True), (22, .2, False),
                                           (22, .1, False), (99, .05, False)]])
    locations = ('inside_area', 'outside_area', 'outside_area_or_native_fallback', None)
    for shot, location in zip(match['shots'], locations, strict=True):
        shot['location_group'] = location
    report = summarize_shot_quality([match], 7, 'against', .20, 10)
    areas = report['covered_shot_breakdown']['by_area']
    assert {k: v['shots'] for k, v in areas.items()} == {k: 1 for k in (
        'inside_area', 'outside_area', 'outside_area_or_native_fallback', 'unclassified')}
    assert areas['outside_area']['expected_goals'] == .20
    assert report['fixtures'][0]['best_chance']['location_group'] == 'inside_area'
    assert areas['inside_area']['non_penalty_xg'] == 0
    assert report['fixtures'][0]['best_non_penalty_chance']['location_group'] == 'outside_area'
