from unittest.mock import Mock
import pytest
from fm_live_mcp import retained_spatial_report as report


def capture():
    avg = [{'side_index': side, 'canonical_person_id': person} for side, person in [(0, 123), (1, 456)]]
    cells = [{'axis_0_index': 64, 'axis_1_index': 99, 'sample_count': 5},
             {'axis_0_index': 60, 'axis_1_index': 98, 'sample_count': 3}]
    density = dict(method='position samples', axes={}, teams=[dict(side_index=0, cells=cells, coverage={'binned_samples': 8})],
                   players=[dict(side_index=0, canonical_person_id=123, cells=cells, coverage={'binned_samples': 8})])
    return dict(fixture={'home_team': {'native_id': 10}, 'away_team': {'native_id': 11}}, native_match_key=112,
                source_kind='native', captured_save={'current_date':'2030-11-03'}, saved_file_fallback=False, pitch_geometry={}, state='available',
                pass_network=None, average_positions={'players': avg}, sample_density=density)


def test_selection_conserves_every_binned_position_and_preserves_missing_person():
    source = capture()
    public = report.spatial_view(source, 10, grid='compact')
    assert public['captured_save'] == {'current_date':'2030-11-03'}
    assert public['average_positions'] == [{'side_index': 0, 'canonical_person_id': 123}]
    assert public['heat_map']['counts_by_length_then_width'][19][12] == 8
    assert sum(map(sum, public['heat_map']['counts_by_length_then_width'])) == 8
    fine = report.spatial_view(source, 10, 123, grid='native')['heat_map']
    assert fine['counts_by_length_then_width'][99][64] == 5
    assert report.spatial_view(source, 10, 456)['heat_map'] is None
    with pytest.raises(ValueError, match='team'):
        report.spatial_view(source, 123)


def test_stale_career_or_different_selected_fixture_rejected(monkeypatch):
    monkeypatch.setattr(report, 'capture_epoch', Mock(return_value=('new',)))
    with pytest.raises(ValueError, match='different career'):
        report.capture_spatial(Mock(), 'sid', 'ref', fixture_captures={'_live_capture_epoch': ('old',)})
    packet = {'_live_capture_epoch': ('new',), 'capture': {'fixtures': [{'fixture': {'fixture_ref': 'other'}}]}}
    with pytest.raises(ValueError, match='selected result'):
        report.capture_spatial(Mock(), 'sid', 'ref', fixture_captures=packet)


def test_coarse_interpolated_map_averages_normalized_cells_including_zeros():
    value = capture()
    value['native_heat_map'] = {'source_kind': 'reconstructed_native_all_phase_heatmap_algorithm', 'axes': {},
                                'teams': [{'side_index': 0, 'coverage': {}, 'postprocessing': {},
                                           'cells': [{'axis_0_index': 1, 'axis_1_index': 4,
                                                      'normalized_intensity': .75}]}]}
    viewed = report.spatial_view(value, 10, method='interpolated')
    heat = viewed['heat_map']
    assert heat['mean_intensity_by_length_then_width'][0][0] == .75 / 25
    assert heat['scope'] == 'team pool of player movement'
    assert 'counts_by_length_then_width' not in heat


def test_receivers_use_every_edge_and_keep_team_denominator_when_selecting_player():
    source = capture()
    roster = [{'person_native_id': i, 'person_name': str(i)} for i in range(1, 16)]
    edges = [dict(from_person_native_id=i, from_name=str(i), to_person_native_id=14,
                  to_name='14', counter_reconciled_completed_passes=2) for i in range(1, 14)]
    edges.append(dict(from_person_native_id=14, from_name='14', to_person_native_id=2,
                      to_name='2', counter_reconciled_completed_passes=3))
    side = dict(state='available', player_counters=roster, edges=edges, counter_reconciled_completed_passes=29)
    source.update(pass_network={'sides': [side]}, average_positions=None)
    result = report.spatial_view(source, 10, grid='none')
    assert len(result['top_passing_connections']) == 10
    outlets = result['passing_outlets']
    player = outlets['receivers'][0]
    assert player['completed_passes_received'] == 26
    assert player['share_of_team_completions'] == 26 / 29
    assert player['distinct_suppliers'] == len(player['leading_suppliers']) == 13
    assert sum(r['completed_passes_received'] for r in outlets['receivers']) == 29
    single = report.spatial_view(source, 10, 14, grid='none')['passing_outlets']
    assert single['receivers'] == [player]
    assert report.spatial_view(source, 10, 15)['passing_outlets']['receivers'][0]['completed_passes_received'] == 0
    assert report.spatial_view(source, 10, 16)['passing_outlets']['state'] == 'player_outside_selected_roster'
    side['counter_reconciled_completed_passes'] = 30
    incomplete = report.spatial_view(source, 10)['passing_outlets']
    assert incomplete['state'] == 'unavailable_incomplete_named_network'
    assert incomplete['receivers'] == []
    side.update(edges=[], counter_reconciled_completed_passes=0)
    empty = report.spatial_view(source, 10, 1)['passing_outlets']['receivers'][0]
    assert empty['share_of_team_completions'] is None and empty['leading_suppliers'] == []


def lille_network_source():
    import gzip
    import json
    from pathlib import Path
    from fm_live_mcp.live_retained_passes import decode_pass_network
    path = Path(__file__).parent / 'fixtures/retained_pass_network_136941.json.gz'
    packet = json.loads(gzip.decompress(path.read_bytes()))
    network = decode_pass_network(bytes.fromhex(packet['events']), packet['players'])
    assert packet['native_match_key'] == 136941
    assert network['sides'][1]['captured_player_counter_checks'] == 20
    assert network['sides'][1]['all_captured_player_counters_match']
    assert network['sides'][1]['counter_reconciled_completed_passes'] == 429
    return dict(state='available', fixture=packet['fixture'], native_match_key=136941,
                source_kind='frozen_retained_network_regression', saved_file_fallback=False,
                pitch_geometry=packet['pitch_geometry'], captured_save={}, pass_network=network,
                average_positions=None, sample_density=None), packet


def test_complete_lille_suppliers_survive_global_leader_limits_for_selected_receivers():
    source, packet = lille_network_source()
    expected = {
        2000307251: ('Konstantinos Karetsas', {
            'Chema Andrés': 5, 'Jay Robinson': 4, 'Beraldo': 3,
            'El Hadji Malick Diouf': 3, 'Chadi Riad': 3, 'Lewis Miley': 3,
            'Alberto Costa': 2, 'Luiz Henrique': 2, 'João Neves': 1, 'Nick Woltemade': 1,
        }),
        91187791: ('Nick Woltemade', {
            'Konstantinos Karetsas': 3, 'João Neves': 2, 'Luiz Henrique': 2,
            'Giovanni Fabbian': 2, 'Alberto Costa': 1, 'Beraldo': 1,
            'Shea Charles': 1, 'Chema Andrés': 1, 'Jay Robinson': 1,
        }),
    }
    canonical = {p['canonical_person_id']: p['person_name'] for p in packet['players']}
    for recipient, (name, counts) in expected.items():
        result = report.spatial_view(source, 688, recipient, grid='none')['passing_outlets']
        assert result['state'] == 'available'
        assert result['team_completed_passes'] == result['named_teammate_completions'] == 429
        receiver, = result['receivers']
        assert receiver['person_native_id'] == recipient and receiver['name'] == name
        feeds = receiver['suppliers']
        assert len(feeds) == receiver['distinct_suppliers'] == len(counts)
        assert {f['name']: f['completions'] for f in feeds} == counts
        assert all(canonical[f['person_native_id']] == f['name'] for f in feeds)
        assert feeds == sorted(feeds, key=lambda f: (-f['completions'], f['person_native_id']))
        assert sum(f['completions'] for f in feeds) == receiver['completed_passes_received'] == sum(counts.values())
        assert receiver['share_of_team_completions'] == sum(counts.values()) / 429
        assert receiver['leading_suppliers'] == [f for f in feeds if f['completions'] == max(counts.values())]
    assert len(expected[2000307251][1]) == 10 and sum(expected[2000307251][1].values()) == 27
    assert len(expected[91187791][1]) == 9 and sum(expected[91187791][1].values()) == 14


def test_complete_suppliers_preserve_known_zero_and_unknown_source_policies():
    import copy
    source, packet = lille_network_source()
    # All sender counters close. This canonical roster actor has known zero incoming completions.
    zero = report.spatial_view(source, 688, 28124573, grid='none')['passing_outlets']
    receiver, = zero['receivers']
    assert receiver['completed_passes_received'] == 0
    assert receiver['suppliers'] == receiver['leading_suppliers'] == []
    assert receiver['share_of_team_completions'] == 0.0
    assert zero['team_completed_passes'] == 429
    # A canonical actor from the opposite fixture side is outside the selected roster.
    other_id = next(p['canonical_person_id'] for p in packet['players'] if p['side_index'] == 0)
    wrong = report.spatial_view(source, 688, other_id, grid='none')['passing_outlets']
    assert wrong['state'] == 'player_outside_selected_roster' and wrong['receivers'] == []
    # Missing one named edge must withhold the complete supplier projection, rather than shrink its denominator.
    broken = copy.deepcopy(source)
    broken['pass_network']['sides'][1]['edges'].pop()
    incomplete = report.spatial_view(broken, 688, 2000307251, grid='none')['passing_outlets']
    assert incomplete['state'] == 'unavailable_incomplete_named_network'
    assert incomplete['receivers'] == [] and incomplete['team_completed_passes'] == 429
    # A failed individual-counter closure or absent retained source cannot publish a named supplier view.
    broken['pass_network']['sides'][1]['state'] = 'unavailable_completed_counter_reconciliation'
    assert report.spatial_view(broken, 688, 2000307251, grid='none')['passing_outlets'] is None
    missing = copy.deepcopy(source)
    missing.update(state='not_in_active_match_banks', pass_network=None)
    assert report.spatial_view(missing, 688, 2000307251, grid='none')['passing_outlets'] is None
