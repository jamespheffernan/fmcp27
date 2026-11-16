import copy
import struct

import pytest
from fm_live_mcp import active_match_shot_timeline as query
from fm_live_mcp import live_retained_shots as retained


def sample():
    events = []; shots = []
    for identity, start, end, kind in [(1, 2, 5, 1), (2, 8, 10, 4), (3, 11, 12, 5), (4, 14, 16, 2), (5, 17, 20, 3)]:
        event = bytearray(56); struct.pack_into('<ff', event, 24, 1., 45.)
        struct.pack_into('<H', event, 34, start); event[39] = 7; event[40] = 0; event[42] = kind
        struct.pack_into('<I', event, 44, identity); struct.pack_into('<H', event, 50, end)
        shot = bytearray(48); struct.pack_into('<I', shot, 0, identity)
        struct.pack_into('<f', shot, 32, .1); struct.pack_into('<I', shot, 36, identity)
        struct.pack_into('<I', shot, 40, start); shot[44] = 2 if identity == 1 else 0
        events.append(bytes(event)); shots.append(bytes(shot))
    total = 0.
    for _ in shots:
        total = retained._f32(total + retained._f32(.1))
    sides = [dict(team_index=10, shots=5, shots_on_target=2, expected_goals=total),
             dict(team_index=11, shots=0, shots_on_target=0, expected_goals=0.)]
    source = dict(state='available_engine_source', vectors=[b''.join(shots), b''], events=b''.join(events),
                  engine_totals=sides, client_snapshot_totals=copy.deepcopy(sides), pitch_geometry=None,
                  engine_frontier_raw=30, source_identity=(100, 200, ('match',)), match_unique_id=123)
    clock = dict(official_match_unique_id=123, current_time_slice=20, buffered_max_time_slice=25)
    split = {'period_intervals': [dict(state='verified_first_half_boundary', official_match_unique_id=123,
                                     time_slice_domain='native_playback_time_slice', period='FirstHalf', start_tick=1, end_tick=10),
                                 dict(state='verified_second_half_start', official_match_unique_id=123,
                                     time_slice_domain='native_playback_time_slice', period='SecondHalf', start_tick=12, end_tick=None)]}
    return source, clock, split


def test_ended_exclusive_and_period_crossing_remain_unknown_without_sorting():
    source, clock, split = sample(); result = query.project(source, clock, period_split=split)
    assert [row['event_id'] for row in result['shots']] == [1, 2, 3, 4]
    assert result['sides'][0]['shots'] == 4 and result['sides'][1]['shots'] == 0
    assert result['period_assignment_unknown'] == [2, 3]
    assert result['periods'][0]['sides'][0]['shots'] == 1
    assert result['periods'][0]['sides'][0]['body_part_counts']['head'] == 1
    assert result['periods'][1]['sides'][0]['shots'] == 1
    assert result['native_ended_exclusive_cutoff_verified']
    assert not result['rendered_presentation_verified'] and not result['replay_exclusion_verified']


def test_future_and_equal_clock_events_never_released():
    source, clock, _ = sample(); clock['current_time_slice'] = 10
    result = query.project(source, clock)
    assert [row['event_id'] for row in result['shots']] == [1]
    assert result['sides'][0]['shots'] == 1 and result['sides'][0]['shot_goals'] == 1
    assert result['shots'][0]['actor'] is None


def test_verified_zero_counts_survive_independent_xg_failure_without_tolerance_widening():
    source, clock, _ = sample(); source['engine_totals'][1]['expected_goals'] = 1.
    result = query.project(source, clock)
    assert result['state'] == 'available_partial'
    assert result['sides'][1]['shots'] == 0 and result['sides'][1]['expected_goals_sum_computed'] is None
    assert result['sides'][1]['metric_confidence']['expected_goals'] == 'unavailable_strict_side_xg_reconciliation'


@pytest.mark.parametrize('field,value', [('engine_frontier_raw',65536), ('engine_frontier_raw',19)])
def test_no_u16_wrap_or_future_cursor_inference(field, value):
    source, clock, _ = sample(); source[field] = value
    result = query.project(source, clock)
    assert result['state'] == 'unavailable' and result['shots'] is None


def test_foreign_or_unverified_periods_fail_closed():
    source, clock, split = sample(); split['period_intervals'][0]['official_match_unique_id'] = 124
    with pytest.raises(ValueError, match='another match'):
        query.project(source, clock, period_split=split)
    clock['official_match_unique_id'] = 124
    with pytest.raises(ValueError, match='identities'):
        query.project(source, clock)


def test_overlapping_intervals_fail_and_missing_periods_stay_unknown():
    source, clock, split = sample(); split['period_intervals'][1]['start_tick'] = 9
    with pytest.raises(ValueError, match='Overlapping'):
        query.project(source, clock, period_split=split)
    result = query.project(source, clock)
    assert result['periods'] == [] and len(result['period_assignment_unknown']) == 4


def test_own_goal_marker_is_preserved_without_adding_a_statistical_shot():
    source, clock, _ = sample()
    event = bytearray(56); struct.pack_into('<ff', event, 24, 2., 44.)
    struct.pack_into('<H', event, 34, 3); event[39] = 3; event[40] = 1; event[42] = 49
    struct.pack_into('<I', event, 44, 6); struct.pack_into('<H', event, 50, 4)
    marker = bytearray(48); struct.pack_into('<I', marker, 0, 6); struct.pack_into('<I', marker, 36, 6)
    source['events'] += bytes(event); source['vectors'][0] += bytes(marker)
    result = query.project(source, clock)
    assert len(result['own_goal_markers']) == 1
    assert result['own_goal_markers'][0]['beneficiary_side_index'] == 0
    assert result['sides'][0]['shots'] == 4 and result['sides'][0]['shot_goals'] == 1


def test_native_domain_guard_rejects_drift_before_following_any_pointer():
    with pytest.raises(ValueError, match='native binding'):
        query._verify_bound(lambda address, size: bytes(size), 0x10000000, 1, 2, {})


def test_buffered_maximum_can_be_ahead_of_the_engine_counter():
    source, clock, _ = sample()
    clock['buffered_max_time_slice'] = 100
    source['engine_frontier_raw'] = clock['current_time_slice']
    result = query.project(source, clock)
    assert result['state'] == 'available'
    assert all(row['native_clock_end_raw'] < clock['current_time_slice'] for row in result['shots'])


def test_count_and_sot_failure_stays_unknown_even_if_other_integer_counter_agrees():
    for field in ('shots', 'shots_on_target'):
        source, clock, _ = sample()
        source['engine_totals'][0][field] += 1
        result = query.project(source, clock)
        assert result['sides'][0]['shots'] is None
        assert result['sides'][0]['shots_on_target'] is None
        assert result['sides'][0]['expected_goals_sum_computed'] is None
        assert all(row['side_index'] == 1 for row in result['shots'])


def test_xg_failure_keeps_exact_count_and_sot_at_playback_with_null_row_xg():
    source, clock, split = sample()
    source['engine_totals'][0]['expected_goals'] += .01
    result = query.project(source, clock, period_split=split)
    assert result['sides'][0]['shots'] == 4
    assert result['sides'][0]['shots_on_target'] == 2
    assert result['sides'][0]['expected_goals_sum_computed'] is None
    assert all(row['expected_goals'] is None for row in result['shots'])
    assert result['periods'][0]['sides'][0]['shots'] == 1
    assert result['periods'][0]['sides'][0]['expected_goals_sum_computed'] is None
    clock['current_time_slice'] = 1
    empty = query.project(source, clock)
    assert empty['sides'][0]['shots'] == 0
    assert empty['sides'][0]['expected_goals_sum_computed'] is None


@pytest.mark.parametrize('hostility', ['duplicate_reference', 'missing_event', 'wrong_side'])
def test_identity_or_side_link_failure_blocks_count_only_recovery(hostility):
    source, clock, _ = sample()
    source['engine_totals'][0]['expected_goals'] += .01
    if hostility == 'duplicate_reference':
        source['vectors'][0] += source['vectors'][0][:48]
        source['engine_totals'][0]['shots'] += 1
        source['engine_totals'][0]['shots_on_target'] += 1
    elif hostility == 'missing_event':
        source['events'] = source['events'][56:]
    else:
        raw = bytearray(source['events']); raw[40] = 1; source['events'] = bytes(raw)
    result = query.project(source, clock)
    assert result['sides'][0]['shots'] is None
    assert result['sides'][0]['shots_on_target'] is None
    assert result['sides'][0]['expected_goals_sum_computed'] is None
    assert result['shots'] == []


def test_actual_lille_candidate_control_recovers_counts_at_recorded_cursor_only(monkeypatch):
    from test_active_match_shots import actual_lille_metric_packet
    from fm_live_mcp import active_match_shots
    decoded = active_match_shots._metric_projection(actual_lille_metric_packet())
    monkeypatch.setattr(query.shots, 'project', lambda source: copy.deepcopy(decoded))
    source = dict(state='available_engine_source', match_unique_id=123, engine_frontier_raw=4559)
    cursor = dict(official_match_unique_id=123, current_time_slice=4559, buffered_max_time_slice=4631)
    result = query.project(source, cursor)
    assert [row['shots'] for row in result['sides']] == [3, 2]
    assert [row['shots_on_target'] for row in result['sides']] == [0, 2]
    assert [row['expected_goals_sum_computed'] for row in result['sides']] == [None, None]
    assert [row['event_id'] for row in result['shots']] == [168, 171, 295, 57, 337]
    cursor['current_time_slice'] = 1000
    prefix = query.project(source, cursor)
    assert [row['shots'] for row in prefix['sides']] == [0, 1]
    assert prefix['shots'][0]['event_id'] == 57
    assert prefix['sides'][0]['expected_goals_sum_computed'] is None


def test_own_goal_marker_remains_opposite_actor_side_and_not_statistical_when_xg_fails():
    source, clock, _ = sample()
    event = bytearray(56); struct.pack_into('<ff', event, 24, 2., 44.)
    struct.pack_into('<H', event, 34, 3); event[39] = 3; event[40] = 1; event[42] = 49
    struct.pack_into('<I', event, 44, 6); struct.pack_into('<H', event, 50, 4)
    marker = bytearray(48); struct.pack_into('<I', marker, 0, 6); struct.pack_into('<I', marker, 36, 6)
    source['events'] += bytes(event); source['vectors'][0] += bytes(marker)
    source['engine_totals'][0]['expected_goals'] += .01
    result = query.project(source, clock)
    assert result['sides'][0]['shots'] == 4 and result['sides'][0]['shots_on_target'] == 2
    assert len(result['own_goal_markers']) == 1
    own = result['own_goal_markers'][0]
    assert own['actor_side_index'] == 1 and own['beneficiary_side_index'] == 0
    assert own['statistical_shot'] is False and own['kind'] == 'own_goal_marker'
    assert own['native_expected_goals'] is None
    assert all(row['event_id'] != 6 for row in result['shots'])


def test_unmapped_terminal_category_stays_unmapped_under_count_only_recovery():
    source, clock, _ = sample()
    raw = bytearray(source['events']); raw[42] = 250; source['events'] = bytes(raw)
    source['engine_totals'][0]['shots_on_target'] -= 1
    source['engine_totals'][0]['expected_goals'] += .01
    result = query.project(source, clock)
    assert result['sides'][0]['shots'] == 4
    first = result['shots'][0]
    assert first['native_category_code'] == 250
    assert first['outcome'] is None and first['native_outcome_label'] is None
    assert first['outcome_state'] == 'unmapped_native_end_shot_category'
    assert first['expected_goals'] is None


def test_actual_terminal_forest_largest_chance_names_original_slot14_not_slot5():
    import gzip,json
    from pathlib import Path
    actual=json.loads(gzip.decompress((Path(__file__).parent/'fixtures/active_forest_terminal_actors.json.gz').read_bytes()))
    source=actual['source']
    source['events']=bytes.fromhex(source['events']['hex'])
    source['vectors']=[bytes.fromhex(r['hex']) for r in source['vectors']]
    result=query.project(source,actual['bound_playback'],period_split=actual['period_split'],actor_binding=actual['actor_binding'])
    forest=[r for r in result['shots'] if r['event_side_index']==1]
    best=max(forest,key=lambda r:r['expected_goals'])
    assert best['event_id']==1719 and best['native_actor_slot']==14
    assert best['actor']['canonical_person_id']==19342183 and best['actor']['person_name']=='Evanilson'
    assert best['expected_goals']==0.8903838396072388
    assert best['official_location']=='LocationSixYardBox' and best['outcome']=='goal'
    assert best['period']=='SecondHalf'
    assert best['actor']['person_name']!='Nicolás Domínguez'
    assert len(result['shots'])==len(query.project(source,actual['bound_playback'])['shots'])
    assert all(r['native_clock_end_raw']<actual['bound_playback']['current_time_slice'] for r in result['shots'])
