import copy
import gzip
import json
import struct
from pathlib import Path

import pytest

from fm_live_mcp.tracking_lateral_width import project_lateral_width
from fm_live_mcp.retained_spatial_report import spatial_view


def packet(pairs=((1000, 1), (-1000, 1), (0, 0)), phases=b'\x01\x01\x00'):
    tracking = dict(orientation_profile=struct.pack('<iii4B', -1, -1, -1, 0, 0, 0, 0),
                    possession_samples=phases, players=[dict(side_index=1, stored_player_slot=0,
                    start_tick=0, samples=b''.join(struct.pack('<hh', *p) for p in pairs))])
    players = [dict(side_index=1, stored_player_slot=0, canonical_person_id=12, person_name='A')]
    return tracking, players


def test_flank_switching_does_not_cancel_and_zero_tail_is_in_denominator():
    t, p = packet()
    row, = project_lateral_width(t, p)['players']
    assert row['all_samples']['sample_count'] == 3
    assert row['all_samples']['mean_absolute_lateral_native'] == pytest.approx(20 / 3)
    assert row['in_possession']['sample_count'] == 2
    assert row['in_possession']['mean_absolute_lateral_native'] == 10
    assert row['out_of_possession']['mean_absolute_lateral_native'] == 0
    assert row['out_of_possession']['zero_pair_sample_count'] == 1
    assert row['out_of_possession']['trailing_zero_pair_sample_count'] == 1
    assert row['coverage']['on_pitch_time_coverage_verified'] is False
    mirrored = copy.deepcopy(t)
    mirrored['players'][0]['samples'] = b''.join(struct.pack('<hh', -x, -y) for x, y in ((1000, 1), (-1000, 1), (0, 0)))
    assert project_lateral_width(mirrored, p) == project_lateral_width(t, p)


def test_actual_phase_unknowns_do_not_become_out_of_possession_or_clamped_samples():
    t, p = packet(pairs=((100, 2),) * 5, phases=bytes([1, 255, 2, 0]))
    row, = project_lateral_width(t, p)['players']
    assert row['all_samples']['sample_count'] == 5
    assert row['in_possession']['sample_count'] == row['out_of_possession']['sample_count'] == 1
    assert row['coverage']['phase_unclassified_sample_count'] == 1
    assert row['coverage']['phase_other_sample_count'] == 1
    assert row['coverage']['phase_uncovered_sample_count'] == 1
    t['possession_samples'] = b''
    missing, = project_lateral_width(t, p)['players']
    assert missing['all_samples']['mean_absolute_lateral_native'] == 1
    assert missing['in_possession']['sample_count'] is None
    assert missing['in_possession']['mean_absolute_lateral_native'] is None
    assert missing['out_of_possession']['state'] == 'unavailable_possession_stream'


def test_absent_track_empty_track_and_observed_centreline_are_distinct():
    t, p = packet(pairs=((0, 10),), phases=b'\x01')
    p.append(dict(side_index=1, stored_player_slot=1, canonical_person_id=13, person_name='B'))
    rows = project_lateral_width(t, p)['players']
    assert rows[0]['all_samples']['mean_absolute_lateral_native'] == 0
    assert rows[0]['all_samples']['zero_pair_sample_count'] == 0
    assert rows[1]['state'] == 'unavailable_no_tracking_stream'
    assert rows[1]['all_samples'] is None
    t['players'][0]['samples'] = b''
    empty = project_lateral_width(t, p)['players'][0]
    assert empty['all_samples']['sample_count'] == 0
    assert empty['all_samples']['mean_absolute_lateral_native'] is None


@pytest.mark.parametrize('change', ['truncated', 'duplicate', 'wrong_actor', 'bad_phase', 'bad_profile', 'overflow'])
def test_malformed_source_cannot_produce_named_width(change):
    t, p = packet()
    if change == 'truncated': t['players'][0]['samples'] += b'\x00'
    if change == 'duplicate': t['players'] *= 2
    if change == 'wrong_actor': t['players'][0]['stored_player_slot'] = 3
    if change == 'bad_phase': t['possession_samples'] = '1'
    if change == 'bad_profile': t['orientation_profile'] = b'\x00'
    if change == 'overflow': t['players'][0]['start_tick'] = 0x7fffffff
    with pytest.raises(ValueError): project_lateral_width(t, p)


def decode(value):
    if isinstance(value, dict):
        if set(value) == {'_bytes_hex'}: return bytes.fromhex(value['_bytes_hex'])
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list): return [decode(v) for v in value]
    return value


def lille():
    path = Path(__file__).parent / 'fixtures/lille_paired_width.json.gz'
    return decode(json.loads(gzip.decompress(path.read_bytes())))


def test_historical_lille_all_canonical_players_and_independent_sample_arithmetic():
    f = lille()
    assert f['source']['native_match_key'] == 136941
    result = project_lateral_width(f['tracking'], f['players'])
    assert len(result['players']) == len(f['players']) == 43
    streams = {(r['side_index'], r['stored_player_slot']): r for r in f['tracking']['players']}
    assert len(streams) == 31
    for row in result['players']:
        source = streams.get((row['side_index'], row['stored_player_slot']))
        if source is None:
            assert row['all_samples'] is None
            continue
        pairs = list(struct.iter_unpack('<hh', source['samples']))
        assert row['all_samples']['sample_count'] == len(pairs)
        assert row['all_samples']['mean_absolute_lateral_native'] == pytest.approx(sum(abs(x) for x, _ in pairs) * .01 / len(pairs), rel=2e-7)
        known = 0
        for phase_name, phase_id in [('in_possession', row['side_index']), ('out_of_possession', 1 - row['side_index'])]:
            selected = [xy for i, xy in enumerate(pairs) if (source['start_tick'] + i * 24) // 24 < len(f['tracking']['possession_samples']) and f['tracking']['possession_samples'][(source['start_tick'] + i * 24) // 24] == phase_id]
            n = len(selected)
            known += n
            assert row[phase_name]['sample_count'] == n
            assert row[phase_name]['mean_absolute_lateral_native'] == pytest.approx(sum(abs(x) for x, _ in selected) * .01 / n, rel=2e-7) if n else row[phase_name]['mean_absolute_lateral_native'] is None
        assert known + sum(row['coverage'][k] for k in ('phase_uncovered_sample_count', 'phase_unclassified_sample_count', 'phase_other_sample_count')) == len(pairs)
    newcastle = [p for p in result['players'] if p['side_index'] == 1]
    assert len(newcastle) == 20
    assert sum(p['state'] == 'unavailable_no_tracking_stream' for p in newcastle) == 5
    assert result['physical_units'] is result['human_left_right'] is None


def test_existing_spatial_view_filters_width_to_exact_side_and_person_without_mutation():
    f = lille()
    width = project_lateral_width(f['tracking'], f['players'])
    source = dict(fixture=f['source']['fixture'], native_match_key=136941, source_kind='historical_fixture_regression',
                  saved_file_fallback=False, captured_save={}, pitch_geometry=f['pitch_geometry'], state='available',
                  pass_network=None, average_positions=None, sample_density=None, lateral_width=width)
    before = copy.deepcopy(source)
    team = spatial_view(source, 688, grid='none')['lateral_width']
    assert len(team['players']) == 20
    person = next(p for p in team['players'] if p['person_name'] == 'Alberto Costa')
    selected = spatial_view(source, 688, person['canonical_person_id'], grid='none')['lateral_width']
    assert selected['players'] == [person]
    other = next(p for p in width['players'] if p['side_index'] == 0)
    missing = spatial_view(source, 688, other['canonical_person_id'], grid='none')['lateral_width']
    assert missing['players'] == []
    assert missing['state'] == 'unavailable_no_selected_tracking_player'
    assert source == before


def test_width_axis_binding_guard_rejects_drift_instead_of_labelling_raw_axis():
    from contextlib import nullcontext
    from unittest.mock import Mock
    from fm_live_mcp.tracking_lateral_width import verify_axes
    from fm_live_mcp import current_spatial_axes, players
    base = 0x100000000
    spans = {base + at: data for at, data in current_spatial_axes.NATIVE_SPANS}
    read = Mock(side_effect=lambda at, n: spans[at][:n])
    bridge = Mock()
    bridge.lock = nullcontext()
    bridge._read_scope.return_value = nullcontext()
    bridge._player_layout.return_value = (base + players.RVA[0],)
    bridge._world_state.return_value = (read, {}, None)
    verify_axes(bridge, 'session')
    read.verify.assert_called_once()
    first = next(iter(spans))
    spans[first] = bytes([spans[first][0] ^ 1]) + spans[first][1:]
    with pytest.raises(ValueError, match='width/length native source changed'):
        verify_axes(bridge, 'session')


def test_native_unavailable_tracking_cannot_fabricate_width_rows():
    t, p = packet()
    t['players'] = []
    result = project_lateral_width(t, p)
    assert result['state'] == 'unavailable_no_position_samples'
    assert result['players'][0]['state'] == 'unavailable_no_tracking_stream'
    assert result['players'][0]['all_samples'] is None
