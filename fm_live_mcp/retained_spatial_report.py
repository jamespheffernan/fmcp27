"""Join one selected result's retained tracking streams, match roster and passing network."""
from . import live_retained_shots as retained
from .live_average_positions import decode_tracking_average_positions
from .live_retained_passes import _verify_pass_native, decode_pass_network
from .live_tracking_heatmaps import decode_native_tracking_heatmaps, decode_tracking_heatmaps
from .match_data_query import capture_epoch, capture_live
from .passing_outlets import passing_outlets
from .tracking_lateral_width import project_lateral_width, verify_axes


def capture_spatial(bridge, session_id, fixture_ref, *, coach_index=None, fixture_captures=None,
                    include_native_heat_map=False, native_team_id=None, native_person_id=None):
    if not isinstance(fixture_ref, str) or not fixture_ref:
        raise ValueError('Select one retained result fixture.')
    epoch = capture_epoch(bridge, session_id)
    packet = fixture_captures if fixture_captures is not None else capture_live(bridge, session_id, [fixture_ref])
    if packet.get('_live_capture_epoch') != epoch:
        raise ValueError('Retained match capture belongs to a different career or process.')
    items = [item for item in packet['capture']['fixtures'] if item['fixture']['fixture_ref'] == fixture_ref]
    if len(items) != 1:
        raise ValueError('Expected the selected result exactly once.')
    item, = items
    fixture, key = item['fixture'], item['native_match_key']
    result = {'fixture': fixture, 'native_match_key': key, 'captured_save': packet['capture']['save'],
              'source_kind': 'active_human_retained_cbe', 'saved_file_fallback': False,
              'average_positions': None, 'lateral_width': None, 'sample_density': None, 'pass_network': None, 'pitch_geometry': None, 'native_heat_map': None}
    totals = [row for row in packet['team_totals']['records'] if key is not None and row['result_key'] == key]
    if len(totals) != 1:
        return dict(result, state='unavailable_team_oracle')
    teams = totals[0]['teams']
    retained._validate_team_oracle(fixture, teams)
    players = [p for p in packet['retained_players'] if p.get('native_match_key') == key]
    if not players or len(retained._validated_actors(players, teams)) != len(players):
        return dict(result, state='unavailable_fixture_roster')
    _verify_pass_native(bridge, session_id)
    verify_axes(bridge, session_id)
    source = retained.capture_source(bridge, session_id, fixture_ref, key, fixture, coach_index, include_tracking=True,
                                     include_native_heat_map=include_native_heat_map)
    if capture_epoch(bridge, session_id) != epoch:
        raise ValueError('Career or process changed during tracking capture.')
    if source['state'] != 'available':
        return dict(result, state=source['state'])
    network = decode_pass_network(source['events'], players)
    result.update(pass_network=network, pitch_geometry=source['pitch_geometry'])
    tracking = source['tracking']
    if tracking['state'] != 'available':
        return dict(result, state=tracking['state'])
    # The HUMAN-owned CBE is dated and team-owned. Check the slot population
    # against the individual counters in the selected fixture before naming tracks.
    if any(side['state'] != 'available' for side in network['sides']):
        return dict(result, state='unavailable_tracking_roster_reconciliation')
    averages = decode_tracking_average_positions(tracking, players)
    width = project_lateral_width(tracking, players)
    density = (decode_tracking_heatmaps(tracking, players, source['pitch_geometry'])
               if source['pitch_geometry'] is not None else None)
    if include_native_heat_map and source['pitch_geometry'] is not None:
        side = _side(fixture, native_team_id) if native_team_id is not None else None
        selected = [p for p in averages['players'] if p['side_index'] == side and p['canonical_person_id'] == native_person_id]
        if native_person_id is None or selected:
            slot = selected[0]['stored_player_slot'] if native_person_id is not None else None
            result['native_heat_map'] = decode_native_tracking_heatmaps(
                tracking, players, source['pitch_geometry'], side_index=side, stored_player_slot=slot)
    return dict(result, state=averages['state'], average_positions=averages, lateral_width=width, sample_density=density)


def _side(fixture, team_native_id):
    sides = [i for i, k in enumerate(('home_team', 'away_team')) if fixture[k]['native_id'] == team_native_id]
    if len(sides) != 1:
        raise ValueError('Select exactly one team from this fixture.')
    return sides[0]


def spatial_view(capture, team_native_id, person_native_id=None, *, grid='compact', method='sample_density'):
    if grid not in ('compact', 'native', 'none'):
        raise ValueError('Unknown tracking grid resolution.')
    if method not in ('sample_density', 'interpolated'):
        raise ValueError('Unknown heat map method.')
    side = _side(capture['fixture'], team_native_id)
    result = {k: capture[k] for k in ('state', 'fixture', 'native_match_key', 'source_kind', 'saved_file_fallback', 'pitch_geometry', 'captured_save')}
    result.update(team_native_id=team_native_id, person_native_id=person_native_id,
                  average_positions=None, lateral_width=None, heat_map=None, top_passing_connections=None, passing_outlets=None)
    def matches(row):
        return row['side_index'] == side and (person_native_id is None or row['canonical_person_id'] == person_native_id)
    network = capture['pass_network']
    if network and network['sides'][side]['state'] == 'available':
        result['passing_outlets'] = passing_outlets(network['sides'][side], person_native_id)
        edges = network['sides'][side]['edges']
        edges = [row for row in edges if row['counter_reconciled_completed_passes'] and
                 (person_native_id is None or person_native_id in (row['from_person_native_id'], row['to_person_native_id']))]
        edges.sort(key=lambda row: (-row['counter_reconciled_completed_passes'], row['from_person_native_id'], row['to_person_native_id']))
        result['top_passing_connections'] = [{key: row[key] for key in ('from_name', 'to_name', 'counter_reconciled_completed_passes')} for row in edges[:10]]
    width = capture.get('lateral_width')
    if width is not None:
        selected_width = [row for row in width['players'] if matches(row)]
        result['lateral_width'] = {**width, 'players': selected_width}
        if not selected_width:
            result['lateral_width']['state'] = 'unavailable_no_selected_tracking_player'
    averages = capture['average_positions']
    if not averages:
        return result
    result['average_positions'] = [row for row in averages['players'] if matches(row)]
    if not result['average_positions']:
        result['state'] = 'no_tracking_for_selected_player_or_team'
        return result
    result['position_coverage'] = averages.get('coverage_policy')
    interpolated = method == 'interpolated'
    density = capture['native_heat_map'] if interpolated else capture['sample_density']
    if density is None or grid == 'none':
        return result
    rows = density['teams'] if person_native_id is None else density['players']
    selected, = [row for row in rows if matches(row)]
    resolution = (65, 100) if grid == 'native' else (13, 20)
    bins = [[0] * resolution[0] for _ in range(resolution[1])]
    for cell in selected['cells']:
        x = cell['axis_0_index'] * resolution[0] // 65
        y = cell['axis_1_index'] * resolution[1] // 100
        bins[y][x] += cell['normalized_intensity'] if interpolated else cell['sample_count']
    heat = {'method': method, 'coverage': selected['coverage'], 'axes': density['axes'],
            'grid_width': resolution[0], 'grid_length': resolution[1], 'ui_verified': False,
            'tracking_note': 'Stored streams can include a stationary zero tail after a substitution. This can bias density and averages. Interpolated maps can retain a final line towards the centre.'}
    if interpolated:
        cells_per_bin = 6500 // (resolution[0] * resolution[1])
        heat['mean_intensity_by_length_then_width'] = [[v / cells_per_bin for v in row] for row in bins]
        heat['normalization'] = selected['postprocessing']
        heat['source_kind'] = selected.get('source_kind', density['source_kind'])
        heat['scope'] = 'team pool of player movement' if person_native_id is None else 'individual FM movement algorithm'
    else:
        heat.update(counts_by_length_then_width=bins, description=density['method'])
    result['heat_map'] = heat
    return result
