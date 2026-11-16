import struct
import pytest

from fm_live_mcp.live_average_positions import (
    decode_tracking_average_positions, tracking_positive_orientation,
)


def profile(first=48, second=96, third=-1, side0=1, side1=0):
    raw = bytearray(16)
    struct.pack_into('<iii', raw, 0, first, second, third)
    raw[13:15] = bytes((side0, side1))
    return bytes(raw)


def player(side=0, slot=0):
    return dict(side_index=side, stored_player_slot=slot,
                canonical_person_id=100 + side * 26 + slot, person_name=f'Player {side}-{slot}')


def tracking(samples, side=0, start=24):
    return dict(orientation_profile=profile(), players=[dict(side_index=side,
                stored_player_slot=0, start_tick=start, samples=samples)])


def test_native_orientation_boundaries_are_strict_and_side_specific():
    p = profile()
    assert [tracking_positive_orientation(p, 0, tick) for tick in (24, 48, 72, 96)] == [True, False, False, True]
    assert [tracking_positive_orientation(p, 1, tick) for tick in (24, 48, 72, 96)] == [False, True, True, False]


def test_tracking_denominator_counts_samples_including_stationary_positions():
    raw = struct.pack('<hhhhhh', 1000, 2000, 1000, 2000, 1000, 2000)
    result = decode_tracking_average_positions(tracking(raw), [player()])['players'][0]
    assert result['sample_count'] == 3
    assert result['native_axis_0'] == pytest.approx(-10 / 3)
    assert result['native_axis_1'] == pytest.approx(-20 / 3)
    assert result['sample_step_native_ticks'] == 24


def test_empty_tracking_is_unknown_and_has_no_fabricated_zero_mean():
    result = decode_tracking_average_positions(tracking(b''), [player()])['players'][0]
    assert result['state'] == 'unavailable_no_position_samples'
    assert result['native_axis_0'] is None


def test_decode_rejects_truncated_stream_unresolved_actor_and_duplicate_slot():
    with pytest.raises(ValueError, match='row'):
        decode_tracking_average_positions(tracking(b'x'), [player()])
    with pytest.raises(ValueError, match='Unresolved'):
        decode_tracking_average_positions(tracking(bytes(4)), [])
    with pytest.raises(ValueError, match='identity'):
        decode_tracking_average_positions(tracking(bytes(4)), [player(), player()])


def test_orientation_rejects_unknown_side_and_corrupt_profile():
    with pytest.raises(ValueError):
        tracking_positive_orientation(profile(), 2, 0)
    with pytest.raises(ValueError):
        tracking_positive_orientation(profile(first=-2), 0, 0)


def test_real_newcastle_southampton_32_tracking_rows_are_distinct_from_events():
    import gzip
    import json
    from pathlib import Path
    with gzip.open(Path(__file__).parent / 'fixtures/retained_tracking_average_positions.json.gz', 'rt') as f:
        packet = json.load(f)
    tracking_packet = packet['tracking']
    tracking_packet['orientation_profile'] = bytes.fromhex(tracking_packet['orientation_profile'])
    tracking_packet['possession_samples'] = bytes.fromhex(tracking_packet['possession_samples'])
    for row in tracking_packet['players']:
        row['samples'] = bytes.fromhex(row['samples'])
    output = decode_tracking_average_positions(tracking_packet, packet['players'])
    assert len(output['players']) == 32
    assert sum(r['sample_count'] for r in output['players']) == 23953
    assert {r['person_name']: r for r in output['players']}['Aaron Ramsdale']['native_axis_1'] == -39.131019592285156
    assert output['players'] == packet['expected']['players']


def test_phase_counts_use_native_tick_division_unknown_exclusion_and_last_clamp():
    packet = tracking(struct.pack('<hhhhhhhh', 1000, 2000, 2000, 3000, 3000, 4000, 4000, 5000))
    packet['possession_samples'] = bytes((255, 0, 255, 1))
    row = decode_tracking_average_positions(packet, [player()])['players'][0]
    phases = row['possession_means']
    assert row['sample_count'] == 4
    assert phases['in_possession']['sample_count'] == 1
    assert phases['out_of_possession']['sample_count'] == 2
    assert phases['unclassified_sample_count'] == 1
    assert phases['in_possession']['native_axis_0'] == 10.0
    assert phases['out_of_possession']['native_axis_0'] == 4.999999523162842


def test_unmapped_phase_values_follow_native_out_branch_with_explicit_caveat():
    packet = tracking(struct.pack('<hh', 1000, 2000))
    packet['possession_samples'] = bytes((8,))
    phases = decode_tracking_average_positions(packet, [player()])['players'][0]['possession_means']
    assert phases['state'] == 'native_phase_branch_with_unmapped_values'
    assert phases['unmapped_native_phase_sample_count'] == 1
    assert phases['out_of_possession']['sample_count'] == 1


def test_capture_possession_byte_vector_accepts_real_unaligned_end_pointer():
    from fm_live_mcp.live_average_positions import read_tracking_source
    cbe, start = 0x10000, 0x20000
    memory = {cbe + 0xd0: bytes(24), cbe + 0x108: profile(),
              cbe + 0xe8: struct.pack('<QQQ', start, start + 3, start + 8), start: bytes((0, 1, 255))}
    def read(address, size):
        result = memory[address]
        assert len(result) == size
        return result
    assert read_tracking_source(read, cbe)['possession_samples'] == bytes((0, 1, 255))


def test_official_denominator_preserves_zero_tails_and_reports_time_uncertainty():
    packet = tracking(struct.pack('<hhhhhh', 1000, 2000, 0, 0, 0, 0))
    row = decode_tracking_average_positions(packet, [player()])['players'][0]
    assert row['sample_count'] == 3
    assert row['native_axis_0'] == pytest.approx(10 / 3)
    assert row['coverage']['zero_pair_sample_count'] == 2
    assert row['coverage']['trailing_zero_pair_sample_count'] == 2
    assert row['coverage']['last_nonzero_sample_tick'] == 24
    assert row['coverage']['on_pitch_time_coverage_verified'] is False
