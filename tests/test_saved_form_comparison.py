"""Observed-rate policy, bounded composition and public registration."""
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

from fm_live_mcp import saved_form_comparison as comparison


def row(start, *, day='2030-07-01', goals=1, assists=0, minutes=90,
        competition=7, group=0, state='stored'):
    return dict(start=start, end=start + 54, group_ordinal=group,
                date=dict(value=day), competition_index_word=competition,
                stats=dict(state=state, goals=goals, assists=assists,
                           played_minutes=minutes,
                           played_minutes_state='stored' if minutes is not None else 'outside_current_producer_profile'))


def form(rows, owners=(545,)):
    return dict(state='available', form_groups_complete=True, total_row_count=len(rows),
                groups=[dict(group_ordinal=i, owner_reference_word=owner) for i, owner in enumerate(owners)],
                rows=rows, next_offset=None, checked_ranges={})


def aggregate(rows, **kwargs):
    return comparison._aggregate(form(rows, owners=(545, 640)), 545,
                                 '2030-07-01', '2030-10-19', kwargs.get('competition'), 180)


def test_same_row_numerator_denominator_missing_zero_unknown():
    out = aggregate([row(1), row(2, state='not_stored', minutes=None, goals=None, assists=None),
                     row(3, minutes=0, goals=0), row(4, minutes=None, goals=255)])
    assert (out['goals'], out['observed_minutes']) == (1, 90)
    assert out['coverage']['observed_stats_rows'] == 2
    assert out['coverage']['missing_stats_rows'] == out['coverage']['unsupported_stats_rows'] == 1
    assert out['coverage']['present_zero_minute_rows'] == 1
    assert out['state'] == 'below_minimum'
    assert out['per90_exact'] == dict(numerator=1, denominator=1)


def test_owner_date_competition_and_duplicate_dates():
    rows = [row(1), row(2, competition=131), row(3, day='2030-10-19'),
            row(4, day='2030-06-30'), row(5, day='2030-10-20'),
            row(6, group=1), row(7, day=None)]
    out = aggregate(rows)
    assert out['observed_minutes'] == 270 and out['goals'] == 3
    assert out['coverage']['same_date_additional_rows'] == 1
    assert out['coverage']['unmapped_date_rows'] == 1
    assert out['coverage']['outside_interval_rows'] == 2
    assert out['coverage']['excluded_other_owner_rows'] == 1
    out = aggregate(rows, competition=7)
    assert out['observed_minutes'] == 180 and out['state'] == 'eligible'
    assert out['coverage']['excluded_competition_rows'] == 1
    empty = aggregate([])
    assert empty['observed_minutes'] == 0 and empty['goal_contributions_per90'] is None


@pytest.fixture
def composed(monkeypatch):
    calls = []
    packets = {1: form([row(1), row(2)]),
               2: form([row(3), row(4), row(5)]),
               3: form([row(6, minutes=127)]),
               4: dict(state='absent', form_groups_complete=False, reason='not_stored'),
               5: dict(state='stopped', form_groups_complete=False, reason='unknown child')}
    targets = {i: dict(person_index=i, candidates=[], search_complete=True,
                      neighbour_corroboration={'search_complete': True}, budget_reasons=[]) for i in range(1, 9)}
    targets[8]['search_complete'] = False
    @contextmanager
    def checked(filename, indices, pin, **kwargs):
        calls.append(('context', filename, indices, pin))
        yield dict(data=b'source', layout=SimpleNamespace(person_count=20),
                   ranked=[targets[i] for i in indices], snapshot_id=pin, saved_metadata={})
        calls.append(('source_rechecked',))
    def starts(data, layout, target):
        i = target['person_index']
        return ([dict(record_start=i, identity={'stored_index': i})] * (2 if i == 7 else 0 if i == 6 else 1), {}, False)
    def decode(data, geometry, offset, limit):
        i = geometry['record_start']; calls.append(('decode', i, offset, limit))
        return deepcopy(packets[i])
    monkeypatch.setattr(comparison.saved_person_search, 'checked_person_context', checked)
    monkeypatch.setattr(comparison.saved_player_form_query, '_starts', starts)
    monkeypatch.setattr(comparison.saved_player_form_query, '_decode', decode)
    return calls


def compare(indices, **kwargs):
    args = dict(team_index=545, date_from='2030-07-01', date_to='2030-10-19', minimum_observed_minutes=180)
    args.update(kwargs)
    return comparison.compare_player_form('source.fm', indices, 'pin', **args)


def test_one_context_dedup_exact_ties_all_states_and_exit_recheck(composed):
    out = compare([2, 1, 1, 3, 4, 5, 6, 7, 8])
    assert out['evaluated_person_indices'] == [2, 1, 3, 4, 5, 6, 7, 8]
    assert out['ranking_person_indices'] == [1, 2]
    assert [p['rank'] for p in out['people'][:2]] == [1, 1]
    assert [p['state'] for p in out['people']] == ['eligible', 'eligible', 'below_minimum',
            'form_absent', 'stopped', 'unavailable', 'competing_candidates', 'incomplete_candidates']
    assert out['people'][3]['observed_minutes'] is None
    assert len([c for c in composed if c[0] == 'context']) == 1
    assert [c[1] for c in composed if c[0] == 'decode'] == [2, 1, 3, 4, 5]
    assert composed[-1] == ('source_rechecked',)
    assert not out['all_selected_form_groups_decoded']


@pytest.mark.parametrize('changes', [dict(date_from='20300701'), dict(date_to='2030-02-30'),
    dict(date_from='2031-01-01'), dict(minimum_observed_minutes=0),
    dict(minimum_observed_minutes=True), dict(team_index=True), dict(team_index=0xffffffff),
    dict(competition_index=-1)])
def test_validation_before_source(changes):
    with pytest.raises(ValueError): compare([1], **changes)


@pytest.mark.parametrize('indices', [[], list(range(33)), [True], [-1], [2**31], (1,)])
def test_cohort_validation(indices):
    with pytest.raises(ValueError): compare(indices)


def test_truncated_internal_page_never_ranked(composed, monkeypatch):
    bad = form([row(1)]); bad['next_offset'] = 1
    monkeypatch.setattr(comparison.saved_player_form_query, '_decode', lambda *args: bad)
    with pytest.raises(ValueError, match='every decoded form row'): compare([1])


def test_public_dispatch():
    from fm_live_mcp import server
    from unittest.mock import patch
    with patch.object(comparison, 'compare_player_form', return_value={'ok': True}) as call:
        assert server.fm_compare_saved_player_form('source.fm', [1], 'pin', 545,
                    '2030-07-01', '2030-10-19', 180, 7) == {'ok': True}
        assert call.call_args.kwargs == dict(team_index=545, date_from='2030-07-01',
            date_to='2030-10-19', minimum_observed_minutes=180, competition_index=7)


def test_source_exit_failure_never_returns_reply(composed, monkeypatch):
    original = comparison.saved_person_search.checked_person_context
    @contextmanager
    def changed(*args, **kwargs):
        with original(*args, **kwargs) as ctx:
            yield ctx
        raise ValueError('Snapshot changed during read')
    monkeypatch.setattr(comparison.saved_person_search, 'checked_person_context', changed)
    with pytest.raises(ValueError, match='Snapshot changed'): compare([1])


def test_public_schema_validation():
    import asyncio
    from fm_live_mcp.server import mcp
    tool = next(t for t in asyncio.run(mcp.list_tools()) if t.name == 'fm_compare_saved_player_form')
    schema = tool.inputSchema
    assert set(schema['required']) == {'filename', 'person_indices', 'expected_snapshot_id',
        'team_index', 'date_from', 'date_to', 'minimum_observed_minutes'}
    assert schema['properties']['person_indices']['maxItems'] == 32
    assert schema['properties']['minimum_observed_minutes']['exclusiveMinimum'] == 0
    assert schema['properties']['competition_index']['default'] is None
    assert tool.annotations.readOnlyHint


@pytest.mark.parametrize('competition,key', [(None, 'main'), (7, 'competition7_control')])
def test_optional_pinned_independent_oracle(competition, key):
    import json
    import os
    from pathlib import Path
    oracle_path = os.environ.get('FM_SAVED_FORM_COMPARISON_ORACLE')
    if not oracle_path:
        pytest.skip('Set FM_SAVED_FORM_COMPARISON_ORACLE to the independent pinned comparison oracle')
    expected = json.loads(Path(oracle_path).read_text())
    cohort = expected['main']['people']
    actual = comparison.compare_player_form(expected['filename'],
        [p['person_index'] for p in cohort], expected['snapshot_id'],
        team_index=545, date_from='2030-07-01', date_to='2030-10-19',
        minimum_observed_minutes=180, competition_index=competition,
        directory=os.environ.get('FM_SAVED_CAREER_DIRECTORY'))
    assert actual['all_selected_form_groups_decoded']
    assert actual['ranking_person_indices'] == expected[key]['ranking_person_indices']
    by_index = {p['person_index']: p for p in actual['people']}
    for person in expected[key]['people']:
        observed = by_index[person['person_index']]
        for field in ['goals', 'assists', 'goal_contributions', 'observed_minutes', 'per90_exact']:
            assert observed[field] == person[field]
        for field in ['interval_rows', 'observed_stats_rows', 'missing_stats_rows', 'present_zero_minute_rows']:
            assert observed['coverage'][field] == person[field]
        assert observed['rank'] == person.get('rank')
