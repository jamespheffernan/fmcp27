"""Independent public acceptance for bounded team performance composition."""
import asyncio

import pytest

from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge


@pytest.mark.parametrize('arguments', [
    {'team_ref': None}, {'team_ref': ''}, {'team_ref': 1}, {'team_ref': True},
    {'team_ref': []}, {'team_ref': {}},
    {'minimum_minutes': None}, {'minimum_minutes': -1}, {'minimum_minutes': 32768},
    {'minimum_minutes': True}, {'minimum_minutes': 450.0}, {'minimum_minutes': '450'},
    {'limit': 0}, {'limit': 26}, {'limit': True}, {'limit': 5.0}, {'limit': None},
    {'include_history': None}, {'include_history': 0}, {'include_history': 'true'},
])
def test_performance_input_validation_precedes_collection(bridge, monkeypatch, arguments):
    def forbidden(*args, **kwargs):
        pytest.fail('Invalid input reached roster collection')
    monkeypatch.setattr(bridge, 'get_team_squad', forbidden)
    inputs = {'team_ref': 'team', **arguments}
    with pytest.raises(BridgeError):
        bridge.compare_team_league_performance(bridge.session, **inputs)


def test_performance_mcp_input_schema_and_read_only_annotations():
    from fm_live_mcp.server import mcp
    tool = next(t for t in asyncio.run(mcp.list_tools())
                if t.name == 'fm_compare_team_league_performance')
    schema = tool.inputSchema
    assert set(schema['required']) == {'session_id', 'team_ref'}
    assert schema['properties']['team_ref']['type'] == 'string'
    minimum = schema['properties']['minimum_minutes']
    assert (minimum['type'], minimum['minimum'], minimum['maximum'], minimum['default']) == ('integer', 0, 32767, 450)
    limit = schema['properties']['limit']
    assert (limit['type'], limit['minimum'], limit['maximum'], limit['default']) == ('integer', 1, 25, 5)
    history = schema['properties']['include_history']
    assert history['type'] == 'boolean' and history['default'] is True
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.openWorldHint is False


class PerformanceSources:
    """Independent public-source transcripts plus real reference-cache state changes."""
    def __init__(self):
        from collections import defaultdict
        self.player_refs = {'preexisting-player': {'address': -1}}
        self.team_refs = {'selected-team': {'address': 9000}, 'preexisting-team': {'address': -2}}
        self.competition_refs = {'preexisting-competition': {'address': -3}}
        self.save = {'name': 'Synthetic career', 'current_date': '2030-10-28', 'save_count': 424}
        self.entries = [
            {'minutes': 450, 'goals': 2, 'assists': 1},
            {'minutes': 900, 'goals': 4, 'assists': 2},
            {'minutes': 900, 'goals': 3, 'assists': 3},
            {'minutes': 449, 'goals': None, 'assists': None},
            {'minutes': 800, 'goals': None, 'assists': 1},
            None,
            {'minutes': 0, 'goals': 0, 'assists': 0},
        ]
        self.current_calls, self.history_calls = defaultdict(int), defaultdict(int)
        self.roster_calls = 0
        self.after_roster = self.after_current = self.after_history = self.before_save = None
        self.roll_players = False
        self.history_refs = {}

    def _public_player(self, index, reference=None):
        row = {'name': 'Same Name', 'display_name': 'Same Name', 'birth_date': '2000-01-01',
               'record_kind': 'virtual' if self.entries[index] is None else 'actual',
               'attributes': {'passing': 12}, 'clubs': {'contract_club': {'name': 'Selected Club'},
               'current_club': {'name': 'Borrower' if index == 1 else 'Selected Club'}, 'on_loan': index == 1}}
        if reference is not None:
            row['player_ref'] = reference
        return row

    def _index(self, reference):
        from fm_live_mcp.bridge import BridgeError
        if reference not in self.player_refs:
            raise BridgeError('Unknown or expired player reference')
        return self.player_refs[reference]['address'] - 1000

    def _response(self, reference, key, value):
        from copy import deepcopy
        index = self._index(reference)
        return {'session_id': 'ignored', 'player_ref': reference, 'observed_at': 'source-observation',
                'save': deepcopy(self.save), 'save_identity': 'native_binding_rechecked',
                'player': {'name': 'Same Name', 'birth_date': '2000-01-01', 'record_kind': 'actual'}, key: value}

    def get_team_squad(self, session_id, team_ref, include_clubs=False, profile_policy='required'):
        assert profile_policy == 'available'
        from copy import deepcopy
        if team_ref not in self.team_refs:
            raise BridgeError('Unknown or expired team reference')
        self.roster_calls += 1
        if self.roll_players and self.roster_calls == 2:
            self.player_refs.clear()
        rows = []
        for index in range(len(self.entries)):
            reference = f'player-{self.roster_calls}-{index}'
            self.player_refs[reference] = {'address': 1000 + index,
                'identity': (700 + index, 'Same', 'Name', '2000-01-01', 900 + index), 'tables': (1, 2, 3)}
            rows.append(self._public_player(index, reference))
        response = {'save': deepcopy(self.save), 'players': rows, 'count': len(rows),
                    'complete_native_roster': True, 'observed_at': 'roster', 'team_ref': team_ref}
        if self.after_roster:
            self.after_roster(response, self.roster_calls)
        return response

    def get_current_player_statistics(self, session_id, reference):
        from copy import deepcopy
        index = self._index(reference)
        assert self.entries[index] is not None, 'Unsupported subtype queried for current statistics'
        self.current_calls[index] += 1
        statistics = {'state': 'stored_without_refresh', 'current_team_state': 'decoded',
                      'current_team': {'native_id': index + 500, 'owner': {'name': 'Borrower' if index == 1 else 'Selected Club'}},
                      'club_runtime_season_year': {'value': 2030, 'state': 'decoded'},
                      'categories': [{'native_code': 1, 'name': 'League', 'availability': 'resident',
                                      'statistics': deepcopy(self.entries[index])},
                                     {'native_code': 5, 'name': 'Overall (Club)', 'availability': 'resident',
                                      'statistics': {'minutes': 1, 'goals': 200, 'assists': 200}}],
                      'additional_team_rows': [{'categories': [{'native_code': 1,
                                      'statistics': {'minutes': 1, 'goals': 200, 'assists': 200}}]}]}
        response = self._response(reference, 'statistics', statistics)
        if self.after_current:
            self.after_current(index, self.current_calls[index], response)
        return response

    def get_player_statistics_history(self, session_id, reference):
        from copy import deepcopy
        index = self._index(reference)
        self.history_calls[index] += 1
        count = self.history_calls[index]
        team_ref, competition_ref = f'history-team-{index}-{count}', f'history-competition-{index}-{count}'
        rows = []
        linked = {}
        for kind, ref, cache, primary in (('team', team_ref, self.team_refs, index + 50),
                                        ('competition', competition_ref, self.competition_refs, index + 100)):
            identity = b''.join(value.to_bytes(4, 'little') for value in (index, primary, primary))
            cache[ref] = {'address': (7000 if kind == 'team' else 8000) + index,
                          'database_index': index, 'native_id': primary, 'random_id': None,
                          'identity': identity, 'tables': (1, 2, 3)}
            linked[kind] = {'database_index': index, 'native_id': primary, 'random_id': None,
                            kind + '_ref': ref, 'name': 'Archive context'}
        for offset, category in ((0, 1), (168, 2), (0, 1)):
            rows.append({'native_offset': offset, 'native_year': 2030, 'native_category_code': category,
                         'category_name': 'League' if category == 1 else 'Cup',
                         'statistics': {'minutes': 90, 'goals': 99, 'assists': 1}, **deepcopy(linked)})
        history = {'state': 'decoded', 'reason': None, 'rows': rows, 'native_entry_count': 5,
                   'returned_row_count': 3, 'skipped_entries': [
                    {'entry_index': 1, 'native_offset': -1, 'reason': 'native_negative_offset_skipped'},
                    {'entry_index': 4, 'native_offset': -2, 'reason': 'native_negative_offset_skipped'}],
                   'source_coverage': 'indexed_disk_stats_archive_only_no_current_or_starting_history',
                   'limitations': 'Stored native year and contextual competition; separate archived rows.'}
        self.history_refs[index, count] = team_ref, competition_ref
        response = self._response(reference, 'history', history)
        if self.after_history:
            self.after_history(index, count, response)
        return response

    def get_save(self, session_id):
        from copy import deepcopy
        result = {'save': deepcopy(self.save), 'observed_at': 'final-save-observation'}
        if self.before_save:
            self.before_save(result)
        return result


@pytest.fixture
def performance_sources(bridge, monkeypatch):
    sources = PerformanceSources()
    for name in ('player_refs', 'team_refs', 'competition_refs', 'get_team_squad',
                 'get_current_player_statistics', 'get_player_statistics_history', 'get_save'):
        monkeypatch.setattr(bridge, name, getattr(sources, name))
    return sources


def test_performance_public_exact_ranks_full_partition_final_refs_and_separate_history(
        bridge, monkeypatch, performance_sources):
    from fm_live_mcp import server
    sources = performance_sources
    sources.roll_players = True
    monkeypatch.setattr(server, 'bridge', bridge)
    response = server.fm_compare_team_league_performance(bridge.session, 'selected-team', limit=2)
    comparison = response['comparison']
    assert response['save_identity'] == 'native_binding_rechecked'
    assert response['observed_at'] == 'final-save-observation'
    assert 'non-atomic' in response['snapshot'].lower()
    assert comparison['population'] == 'selected_native_team_roster'
    assert comparison['counts'] == {'roster_count': 7, 'actual_count': 6, 'unsupported_count': 1,
        'unknown_count': 1, 'below_minimum_count': 2, 'qualifying_count': 3, 'returned_count': 2}
    assert comparison['ranking_complete_among_supported'] is False
    assert comparison['ranking_complete_for_roster'] is False
    assert [row['roster_index'] for row in comparison['rows']] == [1, 2]
    assert [row['rank'] for row in comparison['rows']] == [1, 2]
    for row in comparison['rows']:
        assert row['per90'] == {'numerator': 3, 'denominator': 5, 'value': 0.6}
        assert row['goals_plus_assists'] == 6 and row['minutes'] == 900
        reference = row['player']['player_ref']
        assert reference == f"player-2-{row['roster_index']}" and reference in bridge.player_refs
        assert bridge.player_refs[reference]['address'] == 1000 + row['roster_index']
        history = row['archived_league_history']
        assert history['source_native_entry_count'] == 5 and history['source_returned_row_count'] == 3
        assert len(history['source_skipped_entries']) == 2
        assert history['filtered_row_count'] == 2
        assert [r['native_offset'] for r in history['rows']] == [0, 0]
        assert all(r['native_year'] == 2030 and r['statistics']['goals'] == 99 for r in history['rows'])
        for archived in history['rows']:
            assert archived['team']['team_ref'].endswith('-2')
            assert archived['team']['team_ref'] in bridge.team_refs
            assert archived['competition']['competition_ref'] in bridge.competition_refs
    # Same names and DOBs cannot cross-wire private identities or loan/current-team context.
    first = comparison['rows'][0]['player']
    assert first['clubs']['on_loan'] is True and first['current_team']['native_id'] == 501
    assert [r['state'] for r in comparison['classifications']] == [
        'qualified', 'qualified', 'qualified', 'below_minimum', 'unknown', 'unsupported', 'below_minimum']
    assert all(r['player']['player_ref'] in bridge.player_refs for r in comparison['classifications'])
    assert 'preexisting-player' not in bridge.player_refs  # Rollover is not undone.
    assert sources.current_calls == {0: 2, 1: 2, 2: 2, 3: 2, 4: 2, 6: 2}
    assert sources.history_calls == {1: 2, 2: 2}


def test_performance_history_not_requested_and_cutoff_boundary(bridge, performance_sources):
    result = bridge.compare_team_league_performance(bridge.session, 'selected-team', limit=25, include_history=False)
    rows = result['comparison']['rows']
    assert [row['roster_index'] for row in rows] == [1, 2, 0]
    assert rows[-1]['minutes'] == 450 and rows[-1]['per90']['value'] == 0.6
    assert all(row['archived_league_history'] == {'state': 'not_requested'} for row in rows)
    assert performance_sources.history_calls == {}


def _cache_keys(sources):
    return tuple(set(getattr(sources, key)) for key in ('player_refs', 'team_refs', 'competition_refs'))


@pytest.mark.parametrize('fault', [
    'incomplete_roster', 'duplicate_binding', 'current_drift', 'history_drift',
    'source_save_drift', 'source_player_mismatch', 'roster_reorder', 'roster_replacement',
    'roster_public_drift', 'final_save_drift', 'late_history_failure', 'late_current_failure',
    'child_eviction', 'child_rebound', 'final_player_eviction', 'source_binding_rebound',
])
def test_performance_consistency_failures_discard_ranks_and_clean_new_refs(
        bridge, performance_sources, fault):
    from copy import deepcopy
    sources = performance_sources
    before = _cache_keys(sources)
    def roster(response, count):
        if fault == 'incomplete_roster' and count == 1:
            response['complete_native_roster'] = False
        elif fault == 'duplicate_binding' and count == 1:
            sources.player_refs[response['players'][1]['player_ref']] = deepcopy(
                sources.player_refs[response['players'][0]['player_ref']])
        elif fault == 'roster_reorder' and count == 2:
            response['players'].reverse()
        elif fault == 'roster_replacement' and count == 2:
            sources.player_refs[response['players'][1]['player_ref']]['address'] = 99999
        elif fault == 'roster_public_drift' and count == 2:
            response['players'][1]['attributes']['passing'] = 13
    def current(index, count, response):
        if fault == 'current_drift' and index == 0 and count == 2:
            response['statistics']['categories'][0]['statistics']['goals'] += 1
        elif fault == 'source_save_drift' and index == 1 and count == 1:
            response['save']['save_count'] += 1
        elif fault == 'source_player_mismatch' and index == 0 and count == 1:
            response['player']['name'] = 'A different person'
        elif fault == 'late_current_failure' and index == 6 and count == 2:
            raise BridgeError('Synthetic late current source failure')
        elif fault == 'source_binding_rebound' and index == 0 and count == 1:
            sources.player_refs[response['player_ref']]['address'] = 99999
    def history(index, count, response):
        if fault == 'history_drift' and index == 1 and count == 2:
            # Even a non-returned Cup row is part of the repeated full source comparison.
            response['history']['rows'][1]['statistics']['goals'] += 1
        elif fault == 'late_history_failure' and index == 2 and count == 2:
            raise BridgeError('Synthetic late archive source failure')
        elif fault in ('child_eviction', 'child_rebound') and index == 2 and count == 2:
            reference = sources.history_refs[1, 2][0]
            if fault == 'child_eviction':
                sources.team_refs.pop(reference)
            else:
                sources.team_refs[reference]['identity'] = b'forged-rebound'
    def final_save(response):
        if fault == 'final_save_drift':
            response['save']['current_date'] = '2030-10-29'
        elif fault == 'final_player_eviction':
            sources.player_refs.pop('player-2-1')
    sources.after_roster, sources.after_current = roster, current
    sources.after_history, sources.before_save = history, final_save
    with pytest.raises(BridgeError):
        bridge.compare_team_league_performance(bridge.session, 'selected-team', limit=2)
    assert _cache_keys(sources) == before


def test_performance_failure_cleanup_never_resurrects_invalidated_old_refs(bridge, performance_sources):
    sources = performance_sources
    def fail(index, count, response):
        if index == 2 and count == 2:
            sources.player_refs.pop('preexisting-player')
            sources.team_refs.pop('preexisting-team')
            sources.competition_refs.pop('preexisting-competition')
            raise BridgeError('Synthetic source invalidated its old refs')
    sources.after_history = fail
    with pytest.raises(BridgeError, match='invalidated'):
        bridge.compare_team_league_performance(bridge.session, 'selected-team', limit=2)
    assert sources.player_refs == {}
    assert set(sources.team_refs) == {'selected-team'}
    assert sources.competition_refs == {}


@pytest.mark.parametrize('population', ['all_known', 'empty'])
def test_performance_completeness_claims_follow_the_whole_observed_population(
        bridge, performance_sources, population):
    sources = performance_sources
    sources.entries = sources.entries[:3] if population == 'all_known' else []
    comparison = bridge.compare_team_league_performance(
        bridge.session, 'selected-team', limit=2, include_history=False)['comparison']
    assert comparison['ranking_complete_among_supported'] is True
    assert comparison['ranking_complete_for_roster'] is True
    assert comparison['counts']['roster_count'] == (3 if population == 'all_known' else 0)
    assert comparison['counts']['unknown_count'] == comparison['counts']['unsupported_count'] == 0
    assert comparison['counts']['qualifying_count'] == (3 if population == 'all_known' else 0)
    assert comparison['counts']['returned_count'] == (2 if population == 'all_known' else 0)


def test_performance_unavailable_archive_is_explicit_successful_data(bridge, performance_sources):
    sources = performance_sources
    def unavailable(index, count, response):
        response['history'].update(state='unavailable', reason='native_resident_source_not_decoded',
            rows=[], native_entry_count=None, returned_row_count=0, skipped_entries=[])
    sources.after_history = unavailable
    comparison = bridge.compare_team_league_performance(
        bridge.session, 'selected-team', limit=2)['comparison']
    for row in comparison['rows']:
        history = row['archived_league_history']
        assert history['state'] == 'unavailable'
        assert history['reason'] == 'native_resident_source_not_decoded'
        assert history['source_native_entry_count'] is None
        assert history['filtered_row_count'] == 0 and history['rows'] == []
        assert row['per90']['value'] == 0.6  # Archived absence cannot alter current metrics.


@pytest.mark.parametrize('method', ['get_team_squad','get_managed_squad','get_player'])
@pytest.mark.parametrize('policy', [None, True, 0, [], {}, 'cold', 'AVAILABLE'])
def test_profile_policy_rejects_invalid_literals_before_any_read(bridge, monkeypatch, method, policy):
    monkeypatch.setattr(bridge,'_current',lambda *args:pytest.fail('Policy reached native read'))
    args = [bridge.session] + ([] if method == 'get_managed_squad' else ['reference'])
    with pytest.raises(BridgeError,match='profile_policy'):
        getattr(bridge,method)(*args,profile_policy=policy)
