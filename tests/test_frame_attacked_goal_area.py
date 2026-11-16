"""Exact native area intersections, including strict edges and uncapped strips."""
import struct
import pytest
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X30
from fm_live_mcp import frame_attacked_goal_area as area
from test_frame_native_pitch_bounds import construct
from test_frame_pitch_setup import source, native_spans, BASE, PITCH, TICK, PLUGIN
from test_native_penalty_geometry import neighbors


def prepare(source, length=105.0, width=68.0, upfield=0, period=6):
    construct(source, length, width)
    with PLUGIN.open('rb') as stream:
        for at, expected in (*area.goals.NATIVE_SPANS, area.geometry.NATIVE_PREDICATE):
            stream.seek(0x5ED4000 + at)
            raw = stream.read(len(expected))
            assert raw == expected
            source.put(BASE + at, raw)
    source.put(BASE + 0x54EC0C8 + 0xD8, struct.pack('<Q', BASE + 0x7359B0))
    source.fields(period, upfield, (0, 1))


def project(source):
    initial = area.capture(source.read, BASE, source.bound, fixed_tick=TICK)
    return area.project(area.verify_capture(source.read, BASE, initial, source.bound))


def contains(rectangle, x, y):
    low_x = x >= rectangle['x_min'] if rectangle['x_min_inclusive'] else x > rectangle['x_min']
    high_x = x <= rectangle['x_max'] if rectangle['x_max_inclusive'] else x < rectangle['x_max']
    low_y = y >= rectangle['y_min'] if rectangle['y_min_inclusive'] else y > rectangle['y_min']
    high_y = y <= rectangle['y_max'] if rectangle['y_max_inclusive'] else y < rectangle['y_max']
    return low_x and high_x and low_y and high_y


@pytest.mark.parametrize('length,width', [(105.0, 68.0), (110.0, 75.0), (16.0, 30.0)])
def test_original_complete_native_predicate_matches_exact_intersection_rectangles(source, length, width):
    prepare(source, length, width)
    result = project(source)
    assert result['state'] == 'available_native_attacked_goal_area'
    uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    at, raw = area.geometry.NATIVE_PREDICATE
    shape, point, stop = 0x51000000, 0x52000000, 0x53000000
    for page in (BASE + (at & ~4095), shape, point, stop):
        uc.mem_map(page, 4096)
    uc.mem_write(BASE + at, raw)
    uc.mem_write(shape + 0xDC, struct.pack('<f', length / 2))
    threshold = area.geometry._f32(length / 2 + area.geometry._f32(-16.459))
    lateral = area.geometry._f32(20.13)
    xs = neighbors(lateral) + neighbors(-lateral) + neighbors(width / 2) + neighbors(-width / 2) + [0.0]
    ys = neighbors(threshold) + neighbors(-threshold) + neighbors(length / 2) + neighbors(-length / 2) + neighbors(0.0)
    for team in result['teams']:
        positive = team['attacked_end_positive_native_y']
        rectangle = team['native_pitch_intersection_rectangle']
        assert team['native_goal_centre_xyz'] == [0.0, length / 2 if positive else -length / 2, 0.0]
        assert team['native_goal_end_strip']['goal_line_cap_in_native_predicate'] is False
        for x in xs:
            for y in ys:
                uc.mem_write(point, struct.pack('<ff', x, y))
                for register, value in ((UC_ARM64_REG_X0, shape), (UC_ARM64_REG_X1, point),
                    (UC_ARM64_REG_X2, int(positive)), (UC_ARM64_REG_X30, stop)):
                    uc.reg_write(register, value)
                uc.emu_start(BASE + at, stop, count=100)
                expected = bool(uc.reg_read(UC_ARM64_REG_X0)) and abs(x) <= width / 2 and abs(y) <= length / 2
                assert contains(rectangle, x, y) is expected
    assert result['active_participation_verified'] is False
    assert result['physical_units'] is result['penalty_area_occupation'] is result['sustained_box_support'] is None


@pytest.mark.parametrize('upfield', [0, 1])
def test_exact_frame_orientations_select_opposite_native_rectangles(source, upfield):
    prepare(source, upfield=upfield)
    result = project(source)
    assert [r['attacked_end_positive_native_y'] for r in result['teams']] == [upfield == 0, upfield == 1]
    for team in result['teams']:
        rect = team['native_pitch_intersection_rectangle']
        assert contains(rect, 0.0, 45.0 if team['attacked_end_positive_native_y'] else -45.0)
        assert not contains(rect, 0.0, 60.0 if team['attacked_end_positive_native_y'] else -60.0)


def test_shootout_and_missing_geometry_are_unknown_not_empty_counts(source):
    prepare(source, period=4)
    result = project(source)
    assert result['state'] == 'unavailable_native_attacked_goal_area' and result['teams'] is None
    prepare(source)
    source.values[PITCH + 0x1A0 + 0x90] ^= 1
    result = project(source)
    assert result['state'] == 'unavailable_native_attacked_goal_area'
    assert result['teams'] is result['native_xy_bounds'] is None


def test_final_source_reselection_and_predicate_guards_are_required(source):
    prepare(source)
    initial = area.capture(source.read, BASE, source.bound, fixed_tick=TICK)
    with pytest.raises(ValueError, match='Final'):
        area.project(initial)
    source.values[PITCH + 0x1A0 + 0x40] ^= 1
    with pytest.raises(ValueError, match='geometry changed'):
        area.verify_capture(source.read, BASE, initial, source.bound)
    prepare(source)
    at, _ = area.geometry.NATIVE_PREDICATE
    source.values[BASE + at] ^= 1
    with pytest.raises(ValueError, match='predicate changed'):
        area.capture(source.read, BASE, source.bound, fixed_tick=TICK)
