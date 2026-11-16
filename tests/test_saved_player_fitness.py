"""Signed source words and strict field geometry; no runtime bridge required."""
import json
import os
from pathlib import Path
import struct

import pytest

from fm_live_mcp.saved_player_fitness import read_fitness


def packet(sharpness=9876, fatigue=-211, condition=2900, *, prefix=0):
    return bytes(prefix + 112) + struct.pack('<hhh', sharpness, fatigue, condition)


def test_geometry_and_signed_units():
    raw = packet(prefix=7)
    result = read_fitness(raw, 7, limit=len(raw))
    assert result['state'] == 'decoded'
    assert result['fields']['match_sharpness']['value'] == 9876
    assert result['fields']['fatigue']['value'] == -211
    assert result['fields']['condition']['value'] == 2900
    assert result['fields']['condition']['source_offset'] == 123
    assert result['fields']['fatigue']['native_offset'] == '0x252'
    assert result['native_refresh_executed'] is False
    assert result['availability_assessed'] is False


@pytest.mark.parametrize('fatigue', [-32768, -500, -1, 0, 32767])
def test_zero_and_signed_fatigue(fatigue):
    raw = packet(0, fatigue, 10000)
    fields = read_fitness(raw, 0, limit=len(raw))['fields']
    assert fields['match_sharpness']['value'] == 0
    assert fields['fatigue']['value'] == fatigue
    assert fields['condition']['value'] == 10000


@pytest.mark.parametrize('sharpness,condition', [(-1, 10000), (10001, 0), (0, -1), (0, 32767)])
def test_outside_profile_preserves_raw_and_other_fields(sharpness, condition):
    raw = packet(sharpness, -12, condition)
    result = read_fitness(raw, 0, limit=len(raw))
    assert result['state'] == 'partial'
    assert result['fields']['fatigue']['value'] == -12
    for name, value in [('match_sharpness', sharpness), ('condition', condition)]:
        field = result['fields'][name]
        assert field['raw_signed16'] == value
        assert field['value'] == (value if 0 <= value <= 10000 else None)
        assert field['raw_hex'] == struct.pack('<h', value).hex()


def test_every_truncation_obeys_exclusive_limit():
    raw = packet()
    for limit in range(118):
        with pytest.raises(ValueError):
            read_fitness(raw, 0, limit=limit)
        with pytest.raises(ValueError):
            read_fitness(raw[:limit], 0, limit=limit)


@pytest.mark.parametrize('start,limit', [(True, 118), (0, True), (-1, 118), (1, 118), (0, 119), (119, 118)])
def test_invalid_bounds(start, limit):
    with pytest.raises(ValueError):
        read_fitness(packet(), start, limit=limit)


@pytest.mark.parametrize('kwargs', [{'source_major': True}, {'source_major': 3753},
                                  {'minor': True}, {'minor': 8}, {'reference_mode': 'raw32'}])
def test_unsupported_profiles(kwargs):
    with pytest.raises(ValueError):
        read_fitness(packet(), 0, limit=118, **kwargs)


def test_independent_actual_oracle_opt_in():
    path = os.environ.get('FM_SAVED_FITNESS_ORACLE')
    if not path:
        pytest.skip('Set FM_SAVED_FITNESS_ORACLE for pinned original-word controls')
    oracle = json.loads(Path(path).read_text())
    assert len(oracle['rows']) == 84
    for row in oracle['rows']:
        values = [row['fields'][name]['signed16'] for name in
                  ('match_sharpness', 'fatigue', 'condition')]
        raw = packet(*values)
        result = read_fitness(raw, 0, limit=118)
        for name, expected in row['fields'].items():
            actual = result['fields'][name]
            assert actual['raw_signed16'] == expected['signed16']
            assert actual['raw_hex'] == expected['raw_hex']
            assert actual['value'] == expected['signed16']
