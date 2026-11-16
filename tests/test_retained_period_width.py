from contextlib import nullcontext
from copy import deepcopy
from fractions import Fraction
import gzip
import json
from pathlib import Path
import struct

import pytest

from fm_live_mcp import retained_period_width as width
from fm_live_mcp import spatial_period_witness as witness
from fm_live_mcp.match_period_observations import digest
from test_spatial_period_witness import synthetic


def test_actual_native_tick_windows_mean_abs_phase_denominators_and_global_zero_tail():
    save, fixture, _, observation, actors, tracking, _ = synthetic()
    before = deepcopy((tracking, actors, observation))
    result = width.project(tracking, actors, observation, save=save, fixture=fixture)
    assert (tracking, actors, observation) == before
    assert result['state'] == 'available'
    first, second = result['periods']
    assert (first['start_tick'], first['end_tick'], second['start_tick'], second['end_tick']) == (1, 49, 73, 145)
    a, b = first['players'][0], second['players'][0]
    assert a['all_samples']['sample_count'] == 2  # includes tick48, not tick72
    assert a['all_samples']['mean_absolute_lateral_native'] == 10  # abs(mean) would be0
    assert a['in_possession']['mean_absolute_lateral_native'] == 10
    assert b['all_samples']['sample_count'] == 3
    assert b['all_samples']['mean_absolute_lateral_native'] == pytest.approx(float(Fraction(20, 3)))
    assert b['in_possession']['sample_count'] == 2
    assert b['in_possession']['mean_absolute_lateral_native'] == 10
    assert b['coverage']['phase_other_sample_count'] == 1
    assert b['all_samples']['zero_pair_sample_count'] == b['all_samples']['trailing_zero_pair_sample_count'] == 2
    assert a['all_samples']['trailing_zero_pair_sample_count'] == 0
    assert result['fixture_observed_sample_count'] == 12
    assert result['fixture_unassigned_observed_sample_count'] == 2  # both tick72 gap points
    assert all(period['players'][2]['all_samples'] is None for period in result['periods'])
    assert result['physical_units'] is result['human_left_right'] is result['minute_conversion'] is None
    assert b['coverage']['on_pitch_time_coverage_verified'] is False


@pytest.mark.parametrize('phases,unknown', [(None, 'phase_uncovered_sample_count'),
    (b'', 'phase_uncovered_sample_count'), (bytes([255]) * 7, 'phase_unclassified_sample_count'),
    (bytes([7]) * 7, 'phase_other_sample_count')])
def test_unknown_phase_is_counted_not_clamped_out_of_possession_or_measured_zero(phases, unknown):
    save, fixture, parent, _, actors, tracking, captured = synthetic()
    tracking['possession_samples'] = phases
    captured['tracking_fingerprint'] = witness.tracking_fingerprint(tracking, actors, 145)
    observation = dict(parent, spatial_period_witness=witness.make_witness(parent, captured))
    result = width.project(tracking, actors, observation, save=save, fixture=fixture)
    for period in result['periods']:
        row = period['players'][0]
        assert row['coverage'][unknown] == row['all_samples']['sample_count']
        assert row['in_possession']['mean_absolute_lateral_native'] is None
        assert row['out_of_possession']['mean_absolute_lateral_native'] is None
        assert row['in_possession']['sample_count'] is None if not phases else row['in_possession']['sample_count'] == 0


def test_partial_phase_stream_preserves_covered_byte_and_uncovered_denominator():
    save, fixture, parent, _, actors, tracking, captured = synthetic()
    tracking['possession_samples'] = bytes([0, 0])
    captured['tracking_fingerprint'] = witness.tracking_fingerprint(tracking, actors, 145)
    observation = dict(parent, spatial_period_witness=witness.make_witness(parent, captured))
    result = width.project(tracking, actors, observation, save=save, fixture=fixture)
    first = result['periods'][0]['players'][0]
    assert first['in_possession']['sample_count'] == first['coverage']['phase_uncovered_sample_count'] == 1
    assert first['out_of_possession']['sample_count'] == 0


def test_event_or_possession_only_period_source_cannot_authorize_spatial_width():
    save, fixture, parent, _, actors, tracking, _ = synthetic()
    parent['possession_period_attestation'] = dict(state='verified', semantic_sha256='c' * 64)
    result = width.project(tracking, actors, parent, save=save, fixture=fixture)
    assert result['periods'] is None
    assert result['reason'] == 'prospective_tracking_specific_period_witness_required'


@pytest.mark.parametrize('mutation', ['coordinates', 'phase', 'actor', 'fixture', 'career'])
def test_changed_same_uid_source_or_owner_cannot_inherit_witness(mutation):
    save, fixture, _, observation, actors, tracking, _ = synthetic()
    if mutation == 'coordinates': tracking['players'][0]['samples'] = bytes(24)
    if mutation == 'phase': tracking['possession_samples'] = b'\0'
    if mutation == 'actor': actors[0]['canonical_person_id'] += 100
    if mutation == 'fixture': fixture['away_team']['native_id'] += 1
    if mutation == 'career': save['created_date'] = '2030-01-02'
    if mutation in ('fixture', 'career'):
        with pytest.raises(ValueError): width.project(tracking, actors, observation, save=save, fixture=fixture)
    else:
        result = width.project(tracking, actors, observation, save=save, fixture=fixture)
        assert result['periods'] is None and result['reason'] == 'complete_observed_tracking_semantics_differ'


def decode(value):
    if isinstance(value, dict):
        if '_bytes_hex' in value: return bytes.fromhex(value['_bytes_hex'])
        return {key: decode(item) for key, item in value.items()}
    if isinstance(value, list): return [decode(item) for item in value]
    return value


def test_genuine_forest_retained_source_stays_unknown_without_prospective_spatial_witness():
    path = Path(__file__).parent / 'fixtures/forest_tracking_without_period_witness.json.gz'
    packet = decode(json.loads(gzip.decompress(path.read_bytes())))
    assert packet['source_class'] == 'historical_copied_retained_tracking_without_spatial_period_witness'
    assert packet['native_match_key'] == 137388 and len(packet['tracking']['players']) == 31
    assert [(p['start_tick'], p['end_tick']) for p in packet['period_observation']['intervals']] == [(1, 11655), (11715, 23929)]
    assert witness.WITNESS_KEY not in packet['period_observation']
    result = width.project(packet['tracking'], packet['players'], packet['period_observation'],
                           save=packet['save'], fixture=packet['fixture'])
    assert result['state'] == 'unavailable_no_verified_spatial_period_source'
    assert result['periods'] is None


def test_genuine_forest_numeric_window_arithmetic_only_never_authorizes_halves():
    path = Path(__file__).parent / 'fixtures/forest_tracking_without_period_witness.json.gz'
    packet = decode(json.loads(gzip.decompress(path.read_bytes())))
    streams = {(row['side_index'], row['stored_player_slot']): row for row in packet['tracking']['players']}
    phases = packet['tracking']['possession_samples']
    checked = 0
    # These are numeric-window regression controls only. The actual parent
    # lacks a spatial witness, and the public projector above stays unknown.
    for start, end in ((1, 11655), (11715, 23929)):
        result = width._period_players(packet['tracking'], packet['players'], start, end)
        for row in result:
            source = streams.get((row['side_index'], row['stored_player_slot']))
            if source is None:
                assert row['all_samples'] is None
                continue
            raw = source['samples']
            points = [(int.from_bytes(raw[i:i + 2], 'little', signed=True),
                       int.from_bytes(raw[i + 2:i + 4], 'little', signed=True)) for i in range(0, len(raw), 4)]
            tail = len(points)
            while tail and points[tail - 1] == (0, 0): tail -= 1
            positions = [index for index in range(len(points)) if start <= source['start_tick'] + index * 24 < end]
            buckets = {'all_samples': positions}
            for name, side in (('in_possession', row['side_index']), ('out_of_possession', 1 - row['side_index'])):
                buckets[name] = [index for index in positions
                    if (source['start_tick'] + index * 24) // 24 < len(phases)
                    and phases[(source['start_tick'] + index * 24) // 24] == side]
            for name, selected in buckets.items():
                n = len(selected)
                exact = Fraction(sum(abs(points[index][0]) for index in selected)) * Fraction(5368709, 536870912)
                expected = struct.unpack('<f', struct.pack('<f', float(exact / n)))[0] if n else None
                assert row[name]['mean_absolute_lateral_native'] == expected
                assert row[name]['sample_count'] == n
                assert row[name]['zero_pair_sample_count'] == sum(points[index] == (0, 0) for index in selected)
                assert row[name]['trailing_zero_pair_sample_count'] == sum(index >= tail for index in selected)
                checked += 1
    assert checked == len(streams) * 2 * 3
    assert width.project(packet['tracking'], packet['players'], packet['period_observation'],
                         save=packet['save'], fixture=packet['fixture'])['periods'] is None


def service_control(monkeypatch, *, include_witness=True, pass_counter=0, split_sides=False, spatial_only=False):
    save, fixture, parent, observation, actors, tracking, captured = synthetic()
    fixture['fixture_ref'] = 'selected'
    if split_sides:
        actors[1]['side_index'] = tracking['players'][1]['side_index'] = 1
        captured['tracking_fingerprint'] = witness.tracking_fingerprint(tracking, actors, 145)
        observation = dict(parent, spatial_period_witness=witness.make_witness(parent, captured))
    if spatial_only:
        candidate = dict(bound=dict(current_time_slice=145, official_match_unique_id=9001),
                         split=dict(period_markers=parent['period_markers']))
        observation = witness.make_observation(save, fixture, candidate, captured, 'a' * 64, '2030-11-11T20:00:00Z')
    source = dict(state='available', tracking=dict(tracking, state='available'), events=b'')
    actors = [dict(actor, fixture_key=7) for actor in actors]
    for actor in actors:
        actor.update(passes_completed=0, passes_attempted=0)
    actors[0]['passes_completed'] = pass_counter
    packet = dict(_live_capture_epoch='epoch', capture=dict(save=save,
        fixtures=[dict(fixture=fixture, native_match_key=7)]),
        team_totals=dict(records=[dict(result_key=7, teams=[])]), retained_players=actors)
    monkeypatch.setattr(width, 'capture_epoch', lambda *args: 'epoch')
    monkeypatch.setattr(width, 'capture_live', lambda *args, **kwargs: deepcopy(packet))
    monkeypatch.setattr(width.retained, '_validate_team_oracle', lambda *args: None)
    monkeypatch.setattr(width.retained, '_validated_actors', lambda rows, teams: {i: row for i, row in enumerate(rows)})
    monkeypatch.setattr(width.current_spatial_axes, 'verify_native', lambda *args: None)
    monkeypatch.setattr(width, 'verify_period_clock', lambda *args: None)
    monkeypatch.setattr(width, 'process_epoch', lambda *args: 'd' * 64)  # deliberately not the original epoch
    sources = [deepcopy(source), deepcopy(source)]
    monkeypatch.setattr(width.retained, 'capture_source', lambda *args, **kwargs: sources.pop(0))
    base = 4096
    class Read:
        def __call__(self, address, length):
            return dict(width.active_match_tracking.CLOCK_BINDING_SPANS)[address - base]
        def verify(self): pass
    class Bridge:
        lock = nullcontext()
        def _read_scope(self, session): return nullcontext()
        def _current(self, session): return object()
        def _player_layout(self, process): return (base + width.players.RVA[0],)
        def _world_state(self, process, tables): return Read(), None, None
    selected = observation if include_witness else parent
    class ReadOnlyStore:
        def observations(self, save, fixture): return dict(observations={digest(selected): selected})
        def save(self, *args): pytest.fail('Report wrote a normal period store')
        def finalize(self, *args): pytest.fail('Report finalized a normal period store')
    return Bridge(), ReadOnlyStore(), sources


def test_service_rechecks_full_source_and_filters_exact_team_without_store_writes(monkeypatch):
    bridge, store, sources = service_control(monkeypatch)
    result = width.report(bridge, 'session', 'selected', 688, store=store)
    assert result['state'] == 'available' and result['source_rechecked'] is True
    assert result['source_epoch_matches_current'] is False  # exact semantics, never fixtureUID-as-epoch
    assert all(len(period['players']) == 3 for period in result['periods'])
    assert sources == []


def test_service_without_spatial_witness_preserves_unknown_and_does_not_finalize(monkeypatch):
    bridge, store, sources = service_control(monkeypatch, include_witness=False)
    result = width.report(bridge, 'session', 'selected', 688, store=store)
    assert result['state'] == 'unavailable_no_verified_spatial_period_source' and result['periods'] is None
    assert len(sources) == 1


def test_zero_shot_spatial_service_ignores_unrelated_real_pass_counter_failure(monkeypatch):
    from fm_live_mcp.live_retained_passes import decode_pass_network
    bridge, store, _ = service_control(monkeypatch, split_sides=True, spatial_only=True)
    before = width.report(bridge, 'session', 'selected', 688, store=store)
    assert before['state'] == 'available'
    bridge, store, _ = service_control(monkeypatch, split_sides=True, spatial_only=True, pass_counter=1)
    captured = width.capture_live(bridge, 'session', ['selected'], include_players=True)
    real_pass_result = decode_pass_network(b'', captured['retained_players'])
    assert real_pass_result['sides'][0]['state'] == 'unavailable_completed_counter_reconciliation'
    observation, = store.observations(None, None)['observations'].values()
    assert 'attempt_prefix' not in observation
    after = width.report(bridge, 'session', 'selected', 688, store=store)
    assert after['state'] == 'available'
    assert after['periods'] == before['periods']
    assert after['periods'][0]['players'][0]['all_samples']['mean_absolute_lateral_native'] == 10


def test_final_recheck_binds_spatial_semantics_not_unconsumed_pass_events(monkeypatch):
    bridge, store, sources = service_control(monkeypatch, spatial_only=True)
    sources[1]['events'] = b'unrelated completed-pass flags changed'
    result = width.report(bridge, 'session', 'selected', 688, store=store)
    assert result['state'] == 'available' and result['source_rechecked'] is True


@pytest.mark.parametrize('mutation', ['person_id', 'ordinal', 'name', 'untracked_actor',
    'missing_actor', 'fixture', 'native_key', 'career', 'frame_epoch'])
def test_final_canonical_frame_rejects_same_epoch_consumed_identity_drift(monkeypatch, mutation):
    bridge, store, _ = service_control(monkeypatch, spatial_only=True)
    original_capture = width.capture_live
    calls = []
    def capture(*args, **kwargs):
        packet = original_capture(*args, **kwargs)
        calls.append(packet)
        if len(calls) == 2:
            actor = packet['retained_players'][2 if mutation == 'untracked_actor' else 0]
            if mutation in ('person_id', 'untracked_actor'): actor['canonical_person_id'] += 999
            if mutation == 'ordinal': actor['person_index_word'] += 999
            if mutation == 'name': actor['person_name'] = 'Replacement actor'
            if mutation == 'missing_actor': packet['retained_players'].pop()
            if mutation == 'fixture': packet['capture']['fixtures'][0]['fixture']['date'] = '2030-11-12'
            if mutation == 'native_key': packet['capture']['fixtures'][0]['native_match_key'] += 1
            if mutation == 'career': packet['capture']['save']['name'] = 'Another career'
            if mutation == 'frame_epoch': packet['_live_capture_epoch'] = 'changed'
        return packet
    monkeypatch.setattr(width, 'capture_live', capture)
    with pytest.raises(ValueError, match='Spatial period canonical'):
        width.report(bridge, 'session', 'selected', 688, store=store)
    assert len(calls) == 2


def test_final_canonical_frame_ignores_pass_counters_and_roster_order(monkeypatch):
    bridge, store, _ = service_control(monkeypatch, spatial_only=True)
    original_capture = width.capture_live
    calls = []
    def capture(*args, **kwargs):
        packet = original_capture(*args, **kwargs)
        calls.append(packet)
        if len(calls) == 2:
            packet['retained_players'][0]['passes_completed'] = 1
            packet['retained_players'].reverse()
        return packet
    monkeypatch.setattr(width, 'capture_live', capture)
    result = width.report(bridge, 'session', 'selected', 688, store=store)
    assert len(calls) == 2 and result['state'] == 'available'
    assert result['periods'][0]['players'][0]['all_samples']['mean_absolute_lateral_native'] == 10


@pytest.mark.parametrize('mutation', ['source', 'epoch', 'outside_team', 'clock_guard'])
def test_service_changed_source_epoch_and_clock_guard_do_not_publish_width(monkeypatch, mutation):
    bridge, store, sources = service_control(monkeypatch)
    team = 688
    if mutation == 'source': sources[1]['tracking']['players'][0]['samples'] = bytes(24)
    if mutation == 'epoch':
        values = iter(['epoch', 'changed'])
        monkeypatch.setattr(width, 'capture_epoch', lambda *args: next(values))
    if mutation == 'outside_team': team = 999
    if mutation == 'clock_guard':
        class BadRead:
            def __call__(self, address, length): return bytes(length)
            def verify(self): pass
        bridge._world_state = lambda *args: (BadRead(), None, None)
    with pytest.raises(ValueError): width.report(bridge, 'session', 'selected', team, store=store)
