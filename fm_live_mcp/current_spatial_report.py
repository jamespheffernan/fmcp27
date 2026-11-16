"""One guarded current-game observation of cursor-censored player positions."""
from datetime import datetime, timezone

from . import (active_match_people, active_match_playback, active_match_source,
               active_match_tracking, active_heatmap, current_spatial_axes, live_tracking_heatmaps, players)


def project_spatial(fixture, tracking, *, axes_verified=False):
    """Compact public values only; never expose engine counters or private pointers."""
    teams = [fixture['home_team'], fixture['away_team']]
    sides = [{'side_index': i, 'team': team, 'players': [], 'unresolved_players': []}
             for i, team in enumerate(teams)]
    for row in tracking.get('players') or []:
        side = row['side_index']
        if side not in (0, 1):
            raise ValueError('Spatial player side differs from bound fixture')
        sides[side]['players'].append({key: row.get(key) for key in (
            'stored_player_slot', 'canonical_person_id', 'person_name', 'sample_count',
            'state', 'sample_start_tick', 'sample_step_native_ticks', 'native_axis_0', 'native_axis_1', 'coverage', 'possession_means')
            if key in row})
    if axes_verified:
        for side in sides:
            for row in side['players']:
                row['lateral_displacement_of_mean_native'] = (abs(row['native_axis_0'])
                    if row.get('native_axis_0') is not None else None)
                for phase in ('in_possession', 'out_of_possession'):
                    value = (row.get('possession_means') or {}).get(phase)
                    if value is not None:
                        # Copy source dictionaries: the report does not mutate a capture.
                        row['possession_means'] = dict(row['possession_means'])
                        row['possession_means'][phase] = {**value,
                            'lateral_displacement_of_mean_native': abs(value['native_axis_0'])
                                if value.get('native_axis_0') is not None else None}
    for row in tracking.get('unresolved_tracking_actors') or []:
        side = row['side_index']
        if side not in (0, 1):
            raise ValueError('Unresolved spatial side differs from bound fixture')
        sides[side]['unresolved_players'].append(dict(row))
    for side in sides:
        side['players'].sort(key=lambda row: row['stored_player_slot'])
        side['coverage'] = {
            'named_tracking_player_count': len(side['players']),
            'unresolved_tracking_player_count': len(side['unresolved_players']),
            'sample_count': sum(row['sample_count'] for row in side['players']),
            'state': ('available_partial' if side['unresolved_players'] else 'available')
                     if side['players'] else 'unavailable_no_named_tracking_prefix',
            'current_on_pitch_population_verified': False,
        }
    return {'state': tracking['state'], 'reason': tracking.get('reason'),
            'fixture': {key: fixture[key] for key in ('date', 'competition', 'home_team', 'away_team')},
            'sides': sides, 'current_time_slice': tracking.get('current_time_slice'),
            'temporal_scope': tracking.get('temporal_scope'),
            'boundary_policy': tracking.get('boundary_policy'),
            'source_id': tracking.get('selected_source_sha256'),
            'coverage_policy': tracking.get('coverage_policy'),
            'possession_policy': tracking.get('possession_policy'),
            'native_tracking_clock_domain_verified': tracking.get('native_tracking_clock_domain_verified', False),
            'displayed_pixels_verified': False, 'displayed_minute': None,
            'pitch_axis_names': {'native_axis_0': 'lateral_pitch_width', 'native_axis_1': 'longitudinal_pitch_length'} if axes_verified else None,
            'positive_forward_sign': None, 'human_left_right': None, 'physical_units': None,
            'lateral_width_policy': 'Absolute mean coordinate is displacement of the mean from the centreline, not mean absolute displacement; switching flanks can cancel.' if axes_verified else None,
            'finding_space': None, 'instantaneous_team_shape': None, 'heatmaps': None,
            'interpretation': 'Measured stored-sample means through one checked playback cursor. '
                'All/in-possession/out-of-possession averages describe measured positions; verified lateral mean displacement can compare average width, not human left/right or individual roles, '
                'on-pitch durations, opponent proximity, space created, touches or receiving opportunities. '
                'Zero pairs and post-exit tails remain in the official denominator. '
                'No score, final result, simulation aggregates, future entrants or future points are returned.'}


def _capture_components(read, base, current_date, *, heatmap_method=None):
    context, binding = active_match_source.inspect_context(read, base, expected_current_date=current_date)
    unavailable = {'state': 'unavailable', 'reason': context.get('reason') or context['source_state'],
                   'fixture': None, 'sides': None, 'current_time_slice': None,
                   'native_tracking_clock_domain_verified': False,
                   'displayed_minute': None, 'finding_space': None}
    if binding is None:
        return unavailable, None
    fixture = context['bound_active_fixture']
    if list(binding['team_indices']) != [fixture[k]['database_index'] for k in ('home_team', 'away_team')]:
        raise ValueError('Spatial fixture side ordering changed')
    playback = active_match_playback.capture(read, base, client=binding['client'])
    if playback['state'] != 'bound_playback_cursor':
        return {**unavailable, 'reason': 'unavailable_bound_playback_cursor'}, None
    bound = playback['bound_playback']
    current_spatial_axes.verify_native(read, base)
    if heatmap_method == 'interpolated':
        live_tracking_heatmaps.verify_native_heatmap(read, base)
    actors = active_match_people.inspect_actor_bindings(
        read, base, binding['engine'], expected_match_unique_id=bound['official_match_unique_id'])
    named = [row for row in actors['players'] if isinstance(row.get('person_name'), str) and row['person_name']]
    # The cursor is an anchor, not a requirement that the simulation stops.
    # Source reads only coordinates and phases at/before this fixed cursor.
    source = active_match_tracking.capture_source(read, base, binding['client'], binding['engine'],
                                                  current_time_slice=bound['current_time_slice'])
    tracking = active_match_tracking.project(source, bound, named, actor_binding=actors)
    packet = {'fixture': fixture, 'binding': binding, 'bound': bound, 'actors': actors, 'source': source}
    return project_spatial(fixture, tracking, axes_verified=True), packet


def _inspect(read, base, current_date):
    return _capture_components(read, base, current_date)[0]


def _fixture_identity(fixture):
    return (fixture['date'], fixture.get('native_season_code'),
            tuple((fixture[k].get('database_index'), fixture[k].get('native_id')) for k in ('home_team', 'away_team')),
            (fixture.get('competition') or {}).get('database_index'),
            (fixture.get('competition') or {}).get('native_id'))


def _verify_components(fresh_read, base, current_date, packet):
    binding, bound = packet['binding'], packet['bound']
    # End actor bindings are independent fresh reads of exact original roster
    # slots/PERSONs. Future/unconsumed actor changes do not invalidate a prefix.
    actors = active_match_people.inspect_actor_bindings(
        fresh_read, base, binding['engine'], expected_match_unique_id=bound['official_match_unique_id'])
    selected = {(row['side_index'], row['stored_player_slot']) for row in packet['source'].get('tracking', {}).get('players', [])}
    def identities(rows):
        return {(row['side_index'], row['stored_player_slot']):
                (row.get('canonical_person_id'), row.get('person_index_word'), row.get('person_name'))
                for row in rows if (row['side_index'], row['stored_player_slot']) in selected}
    before, after = identities(packet['actors']['players']), identities(actors['players'])
    if any(after.get(key) != value for key, value in before.items()):
        raise ValueError('Spatial canonical actor changed for consumed tracking prefix')
    context, current = active_match_source.inspect_context(fresh_read, base, expected_current_date=current_date)
    if (current is None or any(current.get(key) != binding.get(key) for key in ('client', 'engine', 'team_indices'))
            or _fixture_identity(context['bound_active_fixture']) != _fixture_identity(packet['fixture'])):
        raise ValueError('Spatial current match ownership or fixture changed')
    return active_match_tracking.verify_prefix(fresh_read, base, binding['client'], binding['engine'],
                                               bound, packet['source'])


def _heatmap_options(team, person, method, grid):
    if method not in ('sample_density', 'interpolated') or grid not in ('compact', 'native'):
        raise ValueError('Choose a supported heat-map method and grid')
    if team is None:
        if person is not None or method != 'sample_density' or grid != 'compact':
            raise ValueError('Select heatmap_team_native_id to request a heat map')
        return None
    if type(team) is not int or team <= 0 or (person is not None and (type(person) is not int or person <= 0)):
        raise ValueError('Heat-map team and player IDs must be positive canonical native IDs')
    if grid == 'native' and person is None:
        raise ValueError('A native-resolution heat map requires one player')
    return dict(team_native_id=team, person_native_id=person, method=method, grid=grid)


def current_spatial_report(bridge, session_id, heatmap_team_native_id=None, heatmap_person_native_id=None,
                           heatmap_method='sample_density', heatmap_grid='compact'):
    heat_options = _heatmap_options(heatmap_team_native_id, heatmap_person_native_id, heatmap_method, heatmap_grid)
    for attempt in range(2):
        try:
            with bridge.lock, bridge._read_scope(session_id):
                process = bridge._current(session_id)
                layout = bridge._player_layout(process)
                world_read, save, _ = bridge._world_state(process, layout)
                epoch = (process.pid, process.version, process.executable, layout, bridge.world_identity)
                base = layout[0] - players.RVA[0]
                # Deliberately do not register advancing whole vector headers,
                # counters or presentation floats as immutable past-prefix data.
                fresh = lambda address, length: bridge._read_memory(process, address, length)
                result, packet = _capture_components(fresh, base, save['current_date'],
                    **({'heatmap_method': heatmap_method} if heat_options else {}))
                verification = None
                if packet is not None and packet['source'].get('state') == 'available_engine_tracking_source':
                    verification = _verify_components(fresh, base, save['current_date'], packet)
                world_read.verify()
                current_process = bridge._current(session_id)
                current_layout = bridge._player_layout(current_process)
                end_read, _, _ = bridge._world_state(current_process, current_layout)
                end_read.verify()
                if epoch != (current_process.pid, current_process.version, current_process.executable,
                             current_layout, bridge.world_identity):
                    raise ValueError('Spatial process or career epoch changed')
                if heat_options:
                    if verification is None:
                        result['heatmaps'] = {'state': 'unavailable', 'reason': result.get('reason') or
                            'unavailable_verified_current_tracking_prefix', 'heat_map': None,
                            'saved_file_fallback': False}
                    else:
                        verified = {**verification, 'canonical_actor_ids_rechecked': True,
                                    'same_match_ownership_rechecked': True}
                        result['heatmaps'] = active_heatmap.project(packet['source'], packet['bound'],
                            packet['actors'], packet['fixture'], prefix_verification=verified, **heat_options)
                return {**result, 'save': bridge._public_save(save),
                        'observed_at': datetime.now(timezone.utc).isoformat(),
                        'readset_verified': True, 'atomic': False, 'saved_file_fallback': False,
                        'verification_scope': 'world_epoch_and_fixture_actor_bookends_and_immutable_selected_prefix',
                        'prefix_verification': ({**{key: verification[key] for key in ('state', 'current_time_slice', 'verified_at_time_slice', 'selected_sample_count')},
                            'canonical_actor_ids_rechecked': True, 'same_match_ownership_rechecked': True} if verification else None),
                        'same_session_spatial_prefix_verified': verification is not None}
        except ValueError as error:
            if attempt or str(error) != 'Game state changed during read; retry':
                raise
