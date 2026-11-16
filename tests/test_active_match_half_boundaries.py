import json
from pathlib import Path
import struct

import pytest

from fm_live_mcp import active_match_half_boundaries as half
from test_active_match_period import source


def row(tick, reason):
    raw = bytearray(20)
    struct.pack_into('<i', raw, 0, tick)
    raw[8] = reason
    return bytes(raw)


def test_actual_second_half_recovers_independently_observed_interval():
    fixture = json.loads((Path(__file__).parent / 'fixtures/active_match_half_boundaries.json').read_text())
    result = half.decode(bytes.fromhex(fixture['raw_hex']), current_time_slice=fixture['current_time_slice'],
                         simulation_period=fixture['simulation_period'])
    assert result['state'] == 'available'
    assert result['first_half_end_time_slice'] == fixture['expected_first_half_end']
    assert result['second_half_start_time_slice'] == fixture['expected_second_half_start']


def test_cutoff_is_source_defined_and_not_fixed_at_positive_control():
    raw = row(1, 3) + row(12345, 1) + row(12405, 3)
    result = half.decode(raw, current_time_slice=13000, simulation_period='SecondHalf')
    assert result['first_half_end_time_slice'] == 12345
    assert result['second_half_start_time_slice'] == 12405


def test_future_marker_does_not_leak_into_current_half():
    result = half.decode(row(1, 3) + row(20000, 1), current_time_slice=10000,
                         simulation_period='FirstHalf')
    assert result['state'] == 'unknown'
    assert result['first_half_end_time_slice'] is None
    assert result['future_stop_info_count_withheld'] == 1
    assert all(r['stop_time_slice'] <= 10000 for r in result['period_markers'])


@pytest.mark.parametrize('raw', [b'', row(100, 2) + row(1000, 1),
                               row(1, 3) + row(1000, 1),
                               row(1, 3) + row(1000, 1) + row(1010, 3) + row(2000, 1),
                               row(1, 3) + row(1000, 99) + row(1010, 1) + row(1020, 3)])
def test_missing_truncated_ambiguous_or_unmapped_history_stays_unknown(raw):
    result = half.decode(raw, current_time_slice=2500, simulation_period='SecondHalf')
    assert result['state'] == 'unknown'
    assert result['first_half_end_time_slice'] is None


def test_extra_time_is_not_normal_first_half():
    result = half.decode(row(1, 3) + row(1000, 1) + row(1010, 3), current_time_slice=2000,
                         simulation_period='ExtraTimeSecondHalf')
    assert result['state'] == 'unknown'


@pytest.mark.parametrize('raw', [b'bad', row(-1, 3), row(100, 3) + row(99, 1)])
def test_invalid_extent_or_clock_order_rejected(raw):
    with pytest.raises(ValueError):
        half.decode(raw, current_time_slice=1000, simulation_period='SecondHalf')


def test_shared_source_accepts_odd_record_count_and_rechecks_period(source):
    s = source
    for a, data in half.NATIVE_SPANS:
        s['put'](s['base'] + a, data)
    s['put'](s['state'] + 0x3C, b'\7')
    raw = row(1, 3) + row(11000, 1) + row(11060, 3)
    start = 0x50000000
    s['put'](start, raw)
    s['put'](s['provider'] + 0x1A0, struct.pack('<QQQ', start, start + len(raw), start + len(raw)))
    match = 0x60000000
    s['put'](s['provider'] + 0x28, struct.pack('<Q', match))
    s['put'](match, struct.pack('<Q', s['base'] + 0x55FA258))
    s['put'](match + 0x20, struct.pack('<Q', 1234567))
    s['context'].update(source_match_address=match, official_match_unique_id=1234567)
    result = half.inspect(s['read'], s['base'], s['context'])
    assert result['first_half_end_time_slice'] == 11000
    assert result['second_half_start_time_slice'] == 11060
    assert result['first_half_boundary']['official_match_unique_id'] == 1234567
    assert result['first_half_boundary']['end_tick'] == 11000
    assert result['period_intervals'][1]['start_tick'] == 11060
    s['put'](s['state'] + 0x38, struct.pack('<i', 11543))
    unavailable = half.inspect(s['read'], s['base'], s['context'])
    assert unavailable['first_half_end_time_slice'] is None
    assert unavailable['first_half_boundary'] is None
    assert unavailable['period_intervals'] == []


def test_regular_full_time_requires_exact_complete_terminal_sequence():
    raw = row(1, 3) + row(11000, 1) + row(11060, 3) + row(24003, 5)
    result = half.decode(raw, current_time_slice=24003, simulation_period='FullTime')
    assert result['state'] == 'available'
    assert result['first_half_end_time_slice'] == 11000
    assert result['second_half_start_time_slice'] == 11060
    assert half.decode(raw, current_time_slice=24004, simulation_period='FullTime')['state'] == 'unknown'
    extra = raw[:-20] + row(22000, 1) + row(22060, 3) + row(24003, 5)
    assert half.decode(extra, current_time_slice=24003, simulation_period='FullTime')['state'] == 'unknown'


def test_terminal_frame_lag_preserves_historical_boundary_only_at_maximum(source):
    s = source
    for a, data in half.NATIVE_SPANS:
        s['put'](s['base'] + a, data)
    s['put'](s['state'] + 0x38, struct.pack('<iB', 24000, 5))
    s['put'](s['playback'] + 0x1DC0, struct.pack('<ii', 24003, 24003))
    raw = row(1, 3) + row(11000, 1) + row(11060, 3) + row(24003, 5)
    start = 0x50000000
    s['put'](start, raw)
    s['put'](s['provider'] + 0x1A0, struct.pack('<QQQ', start, start + len(raw), start + len(raw)))
    match = 0x60000000
    s['put'](s['provider'] + 0x28, struct.pack('<Q', match))
    s['put'](match, struct.pack('<Q', s['base'] + 0x55FA258))
    s['put'](match + 0x20, struct.pack('<Q', 1234567))
    s['context'].update(source_match_address=match, official_match_unique_id=1234567,
                        current_time_slice=24003, buffered_max_time_slice=24003)
    result = half.inspect(s['read'], s['base'], s['context'])
    assert result['state'] == 'available'
    assert result['first_half_boundary']['end_tick'] == 11000
    assert result['period_source']['source_state'] == 'partial'
    s['put'](s['playback'] + 0x1DC4, struct.pack('<i', 24004))
    assert half.inspect(s['read'], s['base'], s['context'])['state'] == 'unknown'
