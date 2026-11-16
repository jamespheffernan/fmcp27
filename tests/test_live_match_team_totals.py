import gzip
from pathlib import Path
import struct

import pytest

from fm_live_mcp import live_match_team_totals as totals

FIXTURES = Path(__file__).parent / 'fixtures'


def frame():
    return gzip.decompress((FIXTURES / 'saved_match_stats_135195.bin.gz').read_bytes())


def test_real_retained_frame_validates_both_sides():
    result = totals.decode_team_totals(frame())
    assert result['result_key'] == 135195
    assert len(result['teams']) == 2
    assert [row['side'] for row in result['teams']] == ['home', 'away']
    assert result['coverage']['complete_side_sections']
    assert not result['coverage']['whole_payload_wire_parsed']
    assert all(row['shots'] >= row['shots_on_target'] for row in result['teams'])


@pytest.mark.parametrize('raw', [b'', b'\x01', b'\0' * ((1 << 20) + 1), bytearray(b'x')])
def test_rejects_invalid_or_unbounded_frames(raw):
    with pytest.raises(ValueError):
        totals.decode_team_totals(raw)


def test_truncated_second_side_never_exposes_first_side():
    raw = frame()
    end = totals.decode_team_totals(raw)['coverage']['parsed_until']
    with pytest.raises(ValueError):
        totals.decode_team_totals(raw[:end - 1])


def test_native_named_pass_corner_and_possession_fields_on_real_frame():
    result = totals.decode_team_totals(frame())
    home, away = result['teams']
    assert (home['team_identity_word'], home['passes_attempted'], home['passes_completed'],
            home['corners'], home['possession_time_raw']) == (688, 559, 504, 9, 7361)
    assert (away['passes_attempted'], away['passes_completed'], away['corners'],
            away['possession_time_raw']) == (513, 441, 3, 6062)
    assert home['pass_completion_percentage_derived'] == pytest.approx(100 * 504 / 559)
    assert [row['possession_share_percentage_computed'] for row in result['teams']] == [55, 45]
    assert not result['coverage']['official_displayed_possession_percentage_verified']
    assert result['coverage']['possession_time_raw_units'] is None


@pytest.mark.parametrize('raw_values,expected', [([0, 0], [0, 0]), ([1, 1], [50, 50]),
                                               ([1, 7], [13, 88]), ([0, 90], [0, 100])])
def test_native_possession_rounding_preserves_independent_side_rounding(raw_values, expected):
    shares = totals._possession_shares(raw_values)
    assert [share for share, _ in shares] == expected
    assert all(state == 'native_ratio_computed' for _, state in shares)


@pytest.mark.parametrize('raw_values,state', [([-1, 100], 'unavailable_negative_raw_counter'),
                                             ([0x7fffffff, 1], 'unavailable_denominator_overflow')])
def test_unproved_possession_counter_domains_remain_unavailable(raw_values, state):
    assert totals._possession_shares(raw_values) == [(None, state), (None, state)]


@pytest.mark.parametrize('attempts,completed', [(-1, 0), (0, -1), (10, 11)])
def test_invalid_signed_pass_counters_fail_without_partial_team_rows(monkeypatch, attempts, completed):
    original = totals.wire.side

    def invalid_side(*args, **kwargs):
        row = original(*args, **kwargs)
        row['fields']['0xd8'] = struct.pack('<h', attempts).hex()
        row['fields']['0xda'] = struct.pack('<h', completed).hex()
        return row

    monkeypatch.setattr(totals.wire, 'side', invalid_side)
    with pytest.raises(ValueError, match='pass counters'):
        totals.decode_team_totals(frame())


def test_native_team_crossing_aggregation_on_real_frame():
    result = totals.decode_team_totals(frame())
    home, away = result['teams']
    assert (home['crosses_attempted'], home['crosses_completed']) == (41, 5)
    assert (away['crosses_attempted'], away['crosses_completed']) == (16, 2)
    assert home['cross_completion_percentage_derived'] == pytest.approx(500 / 41)
    assert home['crossing_counts_state'] == 'native_aggregate_available'
    assert not result['coverage']['crossing_locations_verified']


def crossing_child(attempts, completed, *, wide=False):
    raw = bytearray(95)
    delta = 4 if wide else 0
    raw[89 + delta] = attempts
    raw[90 + delta] = completed
    return bytes(raw), {'start': 0, 'end': len(raw), 'reference': {'tag': 0 if wide else 2}}


@pytest.mark.parametrize('wide', [False, True])
def test_crossing_unsigned_player_width_and_zero_unknown_accuracy(wide):
    raw, child = crossing_child(255, 4, wide=wide)
    assert totals._crossing_counts(raw, [child]) == (255, 4, 'native_aggregate_available')
    raw, child = crossing_child(0, 0, wide=wide)
    assert totals._crossing_counts(raw, [child]) == (0, 0, 'native_aggregate_available')


def test_signed_team_crossing_overflow_withholds_only_crossing_fields(monkeypatch):
    original = totals._crossing_counts
    raw, child = crossing_child(255, 1)
    assert original(raw, [child] * 128) == (32640, 128, 'native_aggregate_available')
    assert original(raw, [child] * 129) == (None, None, 'unavailable_signed16_overflow')
    monkeypatch.setattr(totals, '_crossing_counts', lambda *_: original(raw, [child] * 129))
    result = totals.decode_team_totals(frame())
    assert result['teams'][0]['crosses_attempted'] is None
    assert result['teams'][0]['cross_completion_percentage_derived'] is None
    assert result['teams'][0]['shots'] > 0
    assert result['teams'][0]['expected_goals'] > 0


def test_inconsistent_player_crossing_counts_withhold_aggregate():
    raw, child = crossing_child(1, 2)
    assert totals._crossing_counts(raw, [child]) == (None, None, 'unavailable_inconsistent_player_counters')


def test_common_crossing_registry_preserves_source_and_unknown_limits():
    registry = totals.crossing_field_registry()
    assert not registry['independent_serialized_team_oracle']
    assert registry['crosses_attempted']['native_player_offset'] == '0xb5'
    assert registry['crosses_completed']['property_key'] == '0x20726763'
    assert 'No delivery-side' in registry['limits'][0]
    registry['limits'].clear()
    assert totals.crossing_field_registry()['limits']
