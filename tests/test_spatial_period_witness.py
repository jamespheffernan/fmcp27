from copy import deepcopy
import struct

import pytest

from fm_live_mcp import spatial_period_witness as witness
from fm_live_mcp.match_period_observations import digest, fixture_identity, career_identity


def synthetic():
    """Synthetic arithmetic/source-association controls, never observed play."""
    fixture = dict(date='2030-11-11', fixture_ref='fixture',
                   competition=dict(database_index=7, native_id=11),
                   home_team=dict(database_index=9, native_id=688),
                   away_team=dict(database_index=10, native_id=705))
    save = dict(name='Synthetic', created_date='2030-01-01', created_version=1)
    uid, cursor = 9001, 145
    markers = [dict(stop_time_slice=tick, next_stop_reason=reason) for tick, reason in (
        (1, 'StartOfPeriod'), (49, 'EndOfPeriod'), (73, 'StartOfPeriod'), (145, 'EndOfGame'))]
    intervals = [dict(period=name, start_tick=start, end_tick=end, official_match_unique_id=uid,
                      time_slice_domain='native_playback_time_slice', state=state) for name, start, end, state in (
        ('FirstHalf', 1, 49, 'verified_first_half_boundary'), ('SecondHalf', 73, 145, 'verified_second_half_start'))]
    parent = dict(schema_version=1, capture_method='normal_current_match_query_single_verified_readset',
                  career=career_identity(save), fixture=fixture_identity(fixture), official_match_unique_id=uid,
                  process_load_epoch='a' * 64, fingerprint_cursor=cursor,
                  clock_domain='native_playback_time_slice', period_markers=markers, intervals=intervals,
                  attempt_prefix=[dict(event_id=i, side_index=i % 2, start_tick=i + 1,
                                       end_tick=i + 2, semantic_sha256='b' * 64) for i in range(3)])
    actors = [dict(side_index=0, stored_player_slot=i, canonical_person_id=100 + i,
                   person_index_word=200 + i, person_name=f'Synthetic {i}') for i in range(3)]
    tracking = dict(orientation_profile=struct.pack('<iii4B', -1, -1, -1, 0, 0, 0, 0),
                    possession_samples=bytes([255, 0, 0, 1, 0, 2, 0]), players=[])
    for actor, points in zip(actors, [[(-1000, 1), (1000, 1), (3000, 1), (2000, 1), (0, 0), (0, 0)],
                                      [(500, 2)] * 6]):
        tracking['players'].append(dict(side_index=0, stored_player_slot=actor['stored_player_slot'],
                                       start_tick=24, samples=b''.join(struct.pack('<hh', *point) for point in points)))
    captured = dict(state='checked_terminal_spatial_period_source', cursor=cursor,
                    official_match_unique_id=uid, fixture_identity=parent['fixture'],
                    period_markers=markers, tracking_fingerprint=witness.tracking_fingerprint(tracking, actors, cursor))
    observation = dict(parent, spatial_period_witness=witness.make_witness(parent, captured))
    return save, fixture, parent, observation, actors, tracking, captured


def test_witness_binds_full_raw_pairs_actual_phase_extent_and_canonical_identities():
    _, _, parent, observation, actors, tracking, captured = synthetic()
    before = deepcopy((parent, captured))
    assert witness.validate_witness(observation)['tracking_fingerprint']['position_sample_count'] == 12
    assert (parent, captured) == before
    for mutation in ('coordinate', 'zero_pair_axis1', 'phase', 'phase_extent', 'ordinal', 'uid', 'name', 'profile'):
        t, people = deepcopy(tracking), deepcopy(actors)
        if mutation == 'coordinate': t['players'][0]['samples'] = b'\x01' + t['players'][0]['samples'][1:]
        if mutation == 'zero_pair_axis1':
            values = bytearray(t['players'][0]['samples']); values[-1] = 1; t['players'][0]['samples'] = bytes(values)
        if mutation == 'phase': t['possession_samples'] = b'\x01' + t['possession_samples'][1:]
        if mutation == 'phase_extent': t['possession_samples'] = t['possession_samples'][:-1]
        if mutation == 'ordinal': people[0]['person_index_word'] += 1
        if mutation == 'uid': people[0]['canonical_person_id'] += 100
        if mutation == 'name': people[0]['person_name'] += ' changed'
        if mutation == 'profile': t['orientation_profile'] = struct.pack('<iii4B', 100, -1, -1, 0, 0, 0, 0)
        assert witness.tracking_fingerprint(t, people, 145) != captured['tracking_fingerprint'], mutation


def test_future_points_do_not_change_witness_and_phase_clamping_cannot_hide_extent_changes():
    _, _, _, _, actors, tracking, captured = synthetic()
    tracking['players'][0]['samples'] += struct.pack('<hh', 32767, 32767)
    assert witness.tracking_fingerprint(tracking, actors, 145) == captured['tracking_fingerprint']
    short = deepcopy(tracking); long = deepcopy(tracking)
    short['possession_samples'] = b'\0'
    long['possession_samples'] = bytes(7)
    # The existing official-average prefix signature clamps both to the same
    # effective phase values. Width uses actual byte presence instead.
    a = witness.active_match_tracking.clip_tracking(short, 145)
    b = witness.active_match_tracking.clip_tracking(long, 145)
    assert witness.active_match_tracking._prefix_signature(a) == witness.active_match_tracking._prefix_signature(b)
    assert witness.tracking_fingerprint(short, actors, 145) != witness.tracking_fingerprint(long, actors, 145)


def test_off_grid_start_does_not_inherit_the_grid_aligned_native_trim_proof():
    _, _, _, _, actors, tracking, _ = synthetic()
    tracking['players'][0]['start_tick'] = 25
    with pytest.raises(ValueError, match='off-grid'): witness.tracking_fingerprint(tracking, actors, 145)


def test_period_clock_bridge_guard_checks_exact_instructions_and_rejects_drift():
    memory = dict(witness.PERIOD_CLOCK_SPANS)
    witness.verify_period_clock(lambda address, size: memory[address][:size], 0)
    first = next(iter(memory))
    memory[first] = bytes([memory[first][0] ^ 1]) + memory[first][1:]
    with pytest.raises(ValueError, match='clock bridge changed'):
        witness.verify_period_clock(lambda address, size: memory[address][:size], 0)


@pytest.mark.parametrize('mutation', ['epoch', 'uid', 'parent', 'cutoff', 'retroactive', 'nonterminal'])
def test_witness_rejects_parent_epoch_uid_and_retroactive_relabeling(mutation):
    _, _, _, observation, _, _, _ = synthetic()
    if mutation == 'epoch': observation['process_load_epoch'] = 'c' * 64
    if mutation == 'uid': observation['official_match_unique_id'] += 1
    if mutation == 'parent': observation['attempt_prefix'][0]['event_id'] = 99
    if mutation == 'cutoff': observation['spatial_period_witness']['tracking_fingerprint']['cutoff_inclusive'] -= 1
    if mutation == 'retroactive': observation['capture_method'] = 'verified_retrospective_authentic_bundle'
    if mutation == 'nonterminal': observation['spatial_period_witness']['parent_sha256'] = digest({
        **{k: v for k, v in observation.items() if k != 'spatial_period_witness'}, 'fingerprint_cursor': 146})
    with pytest.raises(ValueError): witness.validate_witness(observation)


def test_old_terminal_event_packet_is_not_a_spatial_capture():
    _, _, parent, _, _, _, _ = synthetic()
    with pytest.raises(ValueError, match='does not belong'):
        witness.make_witness(parent, dict(state='verified_terminal_resident_source', events=b'old events'))
    assert witness.validate_witness(parent) is None


def capture_control(monkeypatch):
    from fm_live_mcp import world
    _, fixture, parent, _, actors, tracking, _ = synthetic()
    bound = dict(current_time_slice=145, buffered_max_time_slice=145, official_match_unique_id=9001)
    split = dict(state='available', period_source=dict(simulation_period='FullTime'), period_markers=parent['period_markers'])
    candidate = dict(bound=bound, split=split, fixture=fixture, client=4096, engine=8192)
    source_fixture = ('2030-11-11', 11, (9, 688), (10, 705))
    source = dict(state='available_engine_tracking_source', source_identity=(4096, 8192, ('fixture',)),
                  cbe_address=12288, match_unique_id=9001, fixture_identity=source_fixture, tracking=tracking)
    binding = dict(state='validated_native_stored_slots', official_match_unique_id=9001, players=actors)
    monkeypatch.setattr(witness.active_match_shot_timeline, '_verify_bound', lambda *args: None)
    monkeypatch.setattr(witness.current_spatial_axes, 'verify_native', lambda *args: None)
    monkeypatch.setattr(witness, 'verify_period_clock', lambda *args: None)
    monkeypatch.setattr(witness.active_match_people, 'inspect_actor_bindings', lambda *args, **kwargs: deepcopy(binding))
    sources = [deepcopy(source), deepcopy(source)]
    monkeypatch.setattr(witness.active_match_tracking, 'capture_source', lambda *args, **kwargs: sources.pop(0))
    monkeypatch.setattr(witness.active_match_tracking, 'verify_prefix', lambda *args: dict(state='verified'))
    monkeypatch.setattr(witness.active_match_half_boundaries, 'inspect', lambda *args: deepcopy(split))
    read = world.ReadSet(lambda address, size: bytes(size))
    return candidate, sources, binding, split, read


def test_capture_hook_requires_coexisting_terminal_stops_and_rechecks_full_semantics(monkeypatch):
    candidate, sources, binding, split, read = capture_control(monkeypatch)
    result = witness.capture_terminal_source(read, 0, candidate)
    assert result['state'] == 'checked_terminal_spatial_period_source'
    assert result['cursor'] == 145 and result['tracking_fingerprint']['position_sample_count'] == 12


def test_spatial_zero_shot_context_does_not_weaken_legacy_shot_validation():
    from fm_live_mcp.match_period_observations import validate_observation
    save, fixture, parent, _, actors, tracking, captured = synthetic()
    parent['attempt_prefix'] = []
    with pytest.raises(ValueError, match='Invalid attempt continuity witnesses'):
        validate_observation(parent)  # unchanged legacy contract
    observation = dict(parent, spatial_period_witness=witness.make_witness(parent, captured))
    assert witness.validate_witness(observation) is not None
    del parent['attempt_prefix']
    assert witness.make_witness(parent, captured)['tracking_fingerprint'] == captured['tracking_fingerprint']


def test_spatial_only_observation_is_built_without_any_shot_or_pass_parent():
    save, fixture, parent, _, actors, tracking, captured = synthetic()
    candidate = dict(bound=dict(current_time_slice=145, official_match_unique_id=9001),
                     split=dict(period_markers=parent['period_markers']))
    observation = witness.make_observation(save, fixture, candidate, captured, 'a' * 64, '2030-11-11T20:00:00Z')
    assert observation['source_kind'] == 'host_captured_native_spatial_period_observation'
    assert 'attempt_prefix' not in observation and 'source_hashes' not in observation
    assert witness.validate_witness(observation)['tracking_fingerprint'] == captured['tracking_fingerprint']


@pytest.mark.parametrize('field', ['epoch', 'domain', 'marker', 'interval', 'uid', 'fixture'])
def test_zero_shot_does_not_relax_typed_native_context(field):
    _, _, parent, _, _, _, captured = synthetic()
    captured = deepcopy(captured)
    parent['attempt_prefix'] = []
    if field == 'epoch': parent['process_load_epoch'] = str(parent['official_match_unique_id'])
    if field == 'domain': parent['clock_domain'] = 'minutes'
    if field == 'marker': parent['period_markers'][1]['stop_time_slice'] += 1
    if field == 'interval': parent['intervals'][1]['end_tick'] -= 1
    if field == 'uid': parent['intervals'][0]['official_match_unique_id'] += 1
    if field == 'fixture': parent['fixture']['away_team']['native_id'] += 1
    with pytest.raises(ValueError): witness.make_witness(parent, captured)


@pytest.mark.parametrize('mutation', ['missing_stops', 'not_terminal', 'marker', 'point', 'phase_extent', 'actor'])
def test_capture_hook_changed_or_unavailable_source_cannot_become_witness(monkeypatch, mutation):
    candidate, sources, binding, split, read = capture_control(monkeypatch)
    if mutation == 'missing_stops': candidate['split']['state'] = 'unknown'
    if mutation == 'not_terminal': candidate['bound']['buffered_max_time_slice'] = 146
    if mutation == 'marker':
        changed = deepcopy(split); changed['period_markers'][-1]['stop_time_slice'] = 144
        monkeypatch.setattr(witness.active_match_half_boundaries, 'inspect', lambda *args: changed)
    if mutation == 'point': sources[1]['tracking']['players'][0]['samples'] = bytes(24)
    if mutation == 'phase_extent': sources[1]['tracking']['possession_samples'] = b'\0'
    if mutation == 'actor':
        original = deepcopy(binding)
        changed = deepcopy(binding); changed['players'][0]['canonical_person_id'] = 999
        bindings = [original, changed]
        monkeypatch.setattr(witness.active_match_people, 'inspect_actor_bindings', lambda *args, **kwargs: bindings.pop(0))
    with pytest.raises(ValueError): witness.capture_terminal_source(read, 0, candidate)
