"""Collect a checked roster comparison using existing public read queries only."""
from copy import deepcopy

from . import performance_metrics

SNAPSHOT = ('Non-atomic interval with repeated current-statistics, selected-history when requested, ordered-roster '
            'and save checks; unchanged observations do not establish an atomic snapshot.')
LIMITATIONS = (
    'The selected native team roster differs from UI senior squads, whole clubs, ownership and match eligibility. '
    'Only regular actual-player current League statistics are supported. Unknown values limit ranking to '
    'known qualifying players; unsupported records prevent a definitive whole-roster ranking. '
    'Archived League rows remain separate, preserving source order, duplicates and native year values. '
    'No categories, clubs or archive/current records are added together. ' + SNAPSHOT)


def _binding(bridge, reference):
    saved = bridge.player_refs.get(reference)
    if not isinstance(saved, dict) or any(key not in saved for key in ('address', 'identity', 'tables')):
        raise ValueError('Performance player reference expired during collection')
    return deepcopy(tuple(saved[key] for key in ('address', 'identity', 'tables')))


def _roster(bridge, response):
    if not isinstance(response, dict):
        raise ValueError('Invalid performance roster response')
    rows = response.get('players')
    if (not isinstance(rows, list) or len(rows) > 256 or type(response.get('count')) is not int
            or response['count'] != len(rows)
            or response.get('complete_native_roster') is not True):
        raise ValueError('Performance comparison requires the complete bounded native roster')
    bindings, public = [], []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('player_ref'), str):
            raise ValueError('Invalid performance roster row')
        binding = _binding(bridge, row['player_ref'])
        if binding in bindings:
            raise ValueError('Duplicate native player binding in performance roster')
        bindings.append(binding)
        public.append(deepcopy({key:value for key,value in row.items() if key != 'player_ref'}))
    return bindings, public


def _save(response, expected):
    if not isinstance(response, dict) or response.get('save') != expected:
        raise ValueError('Loaded save changed during performance comparison')


def _source_response(bridge, response, expected_save, reference, binding, roster_row):
    _save(response, expected_save)
    if response.get('player_ref') != reference or _binding(bridge, reference) != binding:
        raise ValueError('Performance source player binding changed')
    player = response.get('player')
    expected_player = {'name': roster_row.get('name'), 'birth_date': roster_row.get('birth_date'),
                       'record_kind': 'actual'}
    if player != expected_player:
        raise ValueError('Performance source player summary disagrees with roster')


def _without_links(value):
    if isinstance(value, dict):
        return {key:_without_links(item) for key,item in value.items()
                if key not in ('team_ref', 'competition_ref')}
    if isinstance(value, list):
        return [_without_links(item) for item in value]
    return deepcopy(value)


def _history(history):
    if not isinstance(history, dict) or any(key not in history for key in
            ('state', 'reason', 'source_coverage', 'limitations')):
        raise ValueError('Invalid performance history source metadata')
    rows = history.get('rows')
    if not isinstance(rows, list):
        raise ValueError('Invalid performance history row collection')
    filtered = []
    for row in rows:
        if not isinstance(row, dict) or type(row.get('native_category_code')) is not int:
            raise ValueError('Invalid archived performance category')
        if row['native_category_code'] == 1:
            filtered.append(deepcopy(row))
    result = {key:deepcopy(history[key]) for key in ('state', 'reason', 'source_coverage', 'limitations')}
    for key, value in history.items():
        if key not in ('state', 'reason', 'source_coverage', 'limitations', 'rows'):
            result['source_'+key] = deepcopy(value)
    result.update(rows=filtered, filtered_row_count=len(filtered))
    return result


def _child_binding(bridge, kind, row):
    if not isinstance(row, dict):
        raise ValueError('Invalid performance history child reference')
    reference = row.get(kind+'_ref')
    if not isinstance(reference, str) or not reference:
        raise ValueError('Invalid performance history child reference')
    cache = bridge.team_refs if kind == 'team' else bridge.competition_refs
    saved = cache.get(reference)
    if not isinstance(saved, dict):
        raise ValueError('Performance history child reference expired')
    index, primary, secondary = (row.get('database_index'), row.get('native_id'), row.get('random_id'))
    secondary = primary if secondary is None else secondary
    if any(type(value) is not int or not 0 <= value <= 0xFFFFFFFF for value in (index, primary, secondary)):
        raise ValueError('Invalid performance history child identity')
    expected = b''.join(value.to_bytes(4, 'little') for value in (index, primary, secondary))
    if saved.get('identity') != expected or saved.get('database_index') != index:
        raise ValueError('Performance history child cached identity disagrees')
    for field in ('native_id', 'random_id'):
        if field in saved and saved[field] != row.get(field):
            raise ValueError('Performance history child cached ID disagrees')
    return kind, reference, deepcopy(saved)


def _history_bindings(bridge, history):
    result = []
    for row in history['rows']:
        for kind in ('team', 'competition'):
            if row.get(kind) is not None:
                result.append(_child_binding(bridge, kind, row[kind]))
    return result


def _player_summary(row, statistics):
    summary = {key:deepcopy(row[key]) for key in
               ('name', 'display_name', 'birth_date', 'player_ref', 'clubs', 'native_identity',
                'profile_state', 'profile_unavailable_reason', 'unavailable_fields', 'field_sources', 'roster_context') if key in row}
    summary['record_kind'] = row.get('record_kind', 'actual')
    summary['current_team'] = deepcopy(statistics.get('current_team')) if isinstance(statistics, dict) else None
    summary['current_team_state'] = (statistics.get('current_team_state', 'unavailable_statistics_source')
                                    if isinstance(statistics, dict) else 'unavailable_statistics_source'
                                    if summary['record_kind'] == 'actual' else 'unsupported_record_kind')
    return summary


def _team_context(response):
    return {key:deepcopy(response[key]) for key in ('label', 'club', 'team') if key in response}


def collect(bridge, session_id, team_ref, minimum_minutes=450, limit=5, include_history=True) -> dict:
    """Caller holds Bridge.lock; public queries own their individual read scopes."""
    if not isinstance(team_ref, str) or not team_ref:
        raise ValueError('team_ref must be a nonempty string')
    if type(minimum_minutes) is not int or not 0 <= minimum_minutes <= 32767:
        raise ValueError('minimum_minutes must be an integer from 0 to 32767')
    if type(limit) is not int or not 1 <= limit <= 25:
        raise ValueError('limit must be an integer from 1 to 25')
    if type(include_history) is not bool:
        raise ValueError('include_history must be a boolean')
    caches = (bridge.player_refs, bridge.team_refs, bridge.competition_refs)
    previous = [set(cache) for cache in caches]
    try:
        initial = bridge.get_team_squad(session_id, team_ref, include_clubs=True, profile_policy='available')
        bindings, public = _roster(bridge, initial)
        save = deepcopy(initial.get('save'))
        if not isinstance(save, dict):
            raise ValueError('Invalid performance roster save metadata')
        context = _team_context(initial)
        sources, candidates = {}, []
        for index, row in enumerate(initial['players']):
            kind = row.get('record_kind', 'actual')
            if kind == 'actual':
                response = bridge.get_current_player_statistics(session_id, row['player_ref'])
                _source_response(bridge, response, save, row['player_ref'], bindings[index], row)
                if 'statistics' not in response:
                    raise ValueError('Missing current performance statistics source')
                sources[index] = deepcopy(response)
            candidates.append({'roster_index': index, 'record_kind': kind,
                               'statistics': sources[index]['statistics'] if index in sources else None})
        ranking = performance_metrics.rank_current_players(candidates, minimum_minutes, limit)
        first_history, final_history = {}, {}
        if include_history:
            for row in ranking['rows']:
                index = row['roster_index']
                player = initial['players'][index]
                response = bridge.get_player_statistics_history(session_id, player['player_ref'])
                _source_response(bridge, response, save, player['player_ref'], bindings[index], player)
                first_history[index] = deepcopy(response)
        for index, first in sources.items():
            player = initial['players'][index]
            response = bridge.get_current_player_statistics(session_id, player['player_ref'])
            _source_response(bridge, response, save, player['player_ref'], bindings[index], player)
            if any(response.get(key) != first.get(key) for key in ('player', 'statistics')):
                raise ValueError('Current statistics changed during performance comparison')
        child_bindings = []
        for index, first in first_history.items():
            player = initial['players'][index]
            response = bridge.get_player_statistics_history(session_id, player['player_ref'])
            _source_response(bridge, response, save, player['player_ref'], bindings[index], player)
            if (_without_links(response.get('history')) != _without_links(first.get('history'))
                    or response.get('player') != first.get('player')):
                raise ValueError('Archived statistics changed during performance comparison')
            final_history[index] = _history(response.get('history'))
            child_bindings.extend(_history_bindings(bridge, final_history[index]))
        final = bridge.get_team_squad(session_id, team_ref, include_clubs=True, profile_policy='available')
        _save(final, save)
        final_bindings, final_public = _roster(bridge, final)
        if final_bindings != bindings or final_public != public or _team_context(final) != context:
            raise ValueError('Ordered native roster changed during performance comparison')
        final_save = bridge.get_save(session_id)
        _save(final_save, save)
        for row, expected in zip(final['players'], final_bindings):
            if _binding(bridge, row['player_ref']) != expected:
                raise ValueError('Final performance player reference expired')
        if team_ref not in bridge.team_refs:
            raise ValueError('Performance input team reference expired')
        for kind, reference, expected in child_bindings:
            cache = bridge.team_refs if kind == 'team' else bridge.competition_refs
            if cache.get(reference) != expected:
                raise ValueError('Performance history child reference expired or changed')
        summaries = {index:_player_summary(row, sources[index]['statistics'] if index in sources else None)
                     for index,row in enumerate(final['players'])}
        output_rows = []
        for row in ranking['rows']:
            index = row['roster_index']
            output_rows.append({**row, 'player':summaries[index], 'archived_league_history':
                               final_history[index] if include_history else {'state':'not_requested'}})
        comparison = {**ranking, 'population':'selected_native_team_roster',
                      'selected_team':context,
                      'metric': {'name':'league_goals_plus_assists_per_90', 'native_category_code':1,
                                 'category_name':'League', 'formula':'90 * (goals + assists) / minutes',
                                 'minimum_minutes':minimum_minutes,
                                 'tie_rule':['per90_descending', 'minutes_descending', 'roster_index_ascending']},
                      'rows':output_rows,
                      'classifications':[{**row, 'player':summaries[row['roster_index']]}
                                         for row in ranking['classifications']],
                      'limitations':LIMITATIONS}
        return {'session_id':session_id, 'team_ref':team_ref, 'observed_at':final_save['observed_at'],
                'save':save, 'save_identity':'native_binding_rechecked', 'snapshot':SNAPSHOT,
                'comparison':comparison}
    except BaseException:
        for cache, before in zip(caches, previous):
            for reference in set(cache)-before:
                cache.pop(reference, None)
        raise
