"""Goldens obtained by offline ARM64 emulation of the hash-pinned renderer."""
import json
from pathlib import Path
import pytest
from fm_live_mcp.retained_shot_location import classify_location, LOCATION_NAMES


def test_original_native_predicate_goldens():
    rows = json.loads((Path(__file__).parent/'fixtures/retained_shot_location_native.json').read_text())
    seen = set()
    for x, y, direction, length, expected in rows:
        actual = classify_location(x, y, direction, length)
        assert actual['native_location_bin'] == expected
        assert actual['official_location'] == LOCATION_NAMES[expected]
        assert actual['location_group'] == ('inside_area' if expected < 6 else 'outside_area' if expected < 12 else 'outside_area_or_native_fallback')
        assert actual['coordinate_units'] is None
        assert actual['coordinate_viewpoint'] is None
        assert actual['distance_to_goal'] is None
        seen.add(expected)
    assert seen == set(range(13))


def test_exact_native_boundary_is_not_forced_inside_box():
    result = classify_location(9.144, 50., True, 52.5)
    assert result['native_location_bin'] == 12
    assert result['location_group'] == 'outside_area_or_native_fallback'


@pytest.mark.parametrize('args',[(0, 0, None, 52.5),(0, float('nan'), True, 52.5),(0, 0, True, 0)])
def test_unknown_direction_or_invalid_geometry_is_not_classified(args):
    with pytest.raises(ValueError):
        classify_location(*args)


def test_missing_geometry_preserves_verified_attempts_and_known_zero_values():
    from test_live_retained_shots import values
    from fm_live_mcp.live_retained_shots import decode_attempts
    c, v, e = values(135904)
    plain = decode_attempts(v, e, c['teams'])
    located = decode_attempts(v, e, c['teams'], pitch_geometry={'half_width_native':33.,'half_length_native':52.5})
    assert len(plain['shots']) == len(located['shots'])
    assert all(r['location_state'] == 'unavailable_pitch_geometry' for r in plain['shots'])
    assert all(r['official_location'] in LOCATION_NAMES for r in located['shots'])
    assert all(r['location_state'] == 'native_renderer_predicate' for r in located['shots'])
    assert [r['expected_goals'] for r in plain['shots']] == [r['expected_goals'] for r in located['shots']]
    assert all(r.get('official_location') is None for r in located['own_goal_markers'])
