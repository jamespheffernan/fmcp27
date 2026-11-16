"""Mean absolute width by prospectively witnessed native normal-half stops."""
import struct

from . import active_match_tracking, current_spatial_axes, live_retained_shots as retained, players
from .live_average_positions import decode_tracking_average_positions, _f32
from .match_data_query import capture_epoch, capture_live
from .match_period_observations import career_identity, fixture_identity, digest, process_epoch
from .spatial_period_observations import SpatialPeriodStore
from .spatial_period_witness import WITNESS_KEY, tracking_fingerprint, validate_witness, verify_period_clock


def _period_players(tracking, actors, start, end):
    checked = decode_tracking_average_positions(tracking, actors)
    coverage = {(row['side_index'], row['stored_player_slot']): row['coverage'] for row in checked['players']}
    streams = {(row['side_index'], row['stored_player_slot']): row for row in tracking['players']}
    phases = tracking.get('possession_samples')
    result = []
    for actor in actors:
        identity = {key: actor[key] for key in ('side_index', 'stored_player_slot', 'canonical_person_id', 'person_name')}
        key = actor['side_index'], actor['stored_player_slot']
        stream = streams.get(key)
        if stream is None:
            result.append(dict(identity, state='unavailable_no_observed_tracking_stream', all_samples=None,
                               in_possession=None, out_of_possession=None, coverage=None))
            continue
        pairs = list(struct.iter_unpack('<hh', stream['samples']))
        tail_start = len(pairs) - coverage[key]['trailing_zero_pair_sample_count']
        buckets = {name: dict(sample_count=0, absolute_raw_sum=0, zero_pair_sample_count=0,
                              trailing_zero_pair_sample_count=0)
                   for name in ('all_samples', 'in_possession', 'out_of_possession')}
        unknown = dict(phase_unclassified_sample_count=0, phase_other_sample_count=0,
                       phase_uncovered_sample_count=0, on_pitch_time_coverage_verified=False)
        for index, pair in enumerate(pairs):
            tick = stream['start_tick'] + index * 24
            if not start <= tick < end:
                continue
            selected = ['all_samples']
            phase_index = tick // 24
            if not phases or phase_index >= len(phases): unknown['phase_uncovered_sample_count'] += 1
            elif phases[phase_index] == 255: unknown['phase_unclassified_sample_count'] += 1
            elif phases[phase_index] not in (0, 1): unknown['phase_other_sample_count'] += 1
            else: selected.append('in_possession' if phases[phase_index] == key[0] else 'out_of_possession')
            for name in selected:
                bucket = buckets[name]
                bucket['sample_count'] += 1
                bucket['absolute_raw_sum'] += abs(pair[0])
                bucket['zero_pair_sample_count'] += pair == (0, 0)
                bucket['trailing_zero_pair_sample_count'] += index >= tail_start
        for name, bucket in buckets.items():
            count, total = bucket['sample_count'], bucket.pop('absolute_raw_sum')
            bucket.update(mean_absolute_lateral_native=_f32(total * _f32(.01) / count) if count else None,
                          state='available' if count else 'unavailable_no_selected_samples')
            if name != 'all_samples' and not phases:
                bucket.update(state='unavailable_possession_stream', sample_count=None,
                              zero_pair_sample_count=None, trailing_zero_pair_sample_count=None)
        result.append(dict(identity, state='available' if buckets['all_samples']['sample_count']
                           else 'unavailable_no_selected_samples', **buckets, coverage=unknown))
    return result


def project(tracking, actors, observation, *, save, fixture):
    """A possession/pass/shot-only observation cannot authorize spatial periods."""
    unavailable = dict(state='unavailable_no_verified_spatial_period_source', periods=None)
    witness = validate_witness(observation)
    if witness is None:
        return dict(unavailable, reason='prospective_tracking_specific_period_witness_required')
    if observation['career'] != career_identity(save) or observation['fixture'] != fixture_identity(fixture):
        raise ValueError('Spatial period observation career or fixture differs')
    cursor = observation['fingerprint_cursor']
    if tracking_fingerprint(tracking, actors, cursor) != witness['tracking_fingerprint']:
        return dict(unavailable, reason='complete_observed_tracking_semantics_differ')
    selected = active_match_tracking.clip_tracking(tracking, cursor)
    periods = []
    for interval in observation['intervals']:
        start, end = interval['start_tick'], interval['end_tick']
        if not 0 <= start < end <= cursor:
            raise ValueError('Spatial period extends outside its observed terminal prefix')
        periods.append(dict(period=interval['period'], start_tick=start, end_tick=end,
                            players=_period_players(selected, actors, start, end)))
    assigned = sum(row['all_samples']['sample_count'] for period in periods
                   for row in period['players'] if row['all_samples'] is not None)
    return dict(state='available', periods=periods, source_kind='retained_tracking_with_prospective_spatial_period_witness',
                clock_domain='native_playback_time_slice', minute_conversion=None,
                boundary_policy='native period start <= start_tick + sample_index*24 < native period end',
                sample_step_native_ticks=24, physical_units=None, human_left_right=None,
                lateral_axis='native_axis_0_verified_pitch_width',
                capture_id=digest(observation), source_process_load_epoch=witness['process_load_epoch'],
                official_match_unique_id=witness['official_match_unique_id'],
                tracking_semantic_sha256=witness['tracking_fingerprint']['semantic_sha256'],
                fixture_observed_sample_count=witness['tracking_fingerprint']['position_sample_count'],
                fixture_unassigned_observed_sample_count=witness['tracking_fingerprint']['position_sample_count'] - assigned,
                coverage_policy='Each player/period uses its own observed sample denominator; zero pairs and the observed terminal-prefix zero tail remain included. Samples are not elapsed time or on-pitch coverage.',
                phase_policy='Actual 0/1 byte at tick//24 only;255/other/missing/beyond-stream excluded from subsets and counted; no clamping.',
                measure='sample_weighted_mean_absolute_lateral_native',
                limits='A normal-period sample comparison, not synchronous participation, metres, human left/right, movement distance, tactical roles or causal effect. Unwitnessed sources remain unavailable.')


def report(bridge, session_id, fixture_ref, team_native_id, *, store=None):
    """Read existing prospective witnesses only; never finalize/import host data."""
    if type(team_native_id) is not int or team_native_id <= 0:
        raise ValueError('Select a positive canonical fixture team ID')
    epoch = capture_epoch(bridge, session_id)
    packet = capture_live(bridge, session_id, [fixture_ref], include_players=True)
    if packet.get('_live_capture_epoch') != epoch:
        raise ValueError('Spatial period capture epoch differs')
    item, = packet['capture']['fixtures']
    fixture, key = item['fixture'], item['native_match_key']
    if fixture['fixture_ref'] != fixture_ref:
        raise ValueError('Exact selected spatial period fixture required')
    sides = [i for i, name in enumerate(('home_team', 'away_team')) if fixture[name]['native_id'] == team_native_id]
    if len(sides) != 1:
        raise ValueError('Selected spatial period team is outside the fixture')
    unavailable = dict(state='unavailable_no_verified_spatial_period_source', periods=None,
                       fixture=fixture, native_match_key=key, team_native_id=team_native_id,
                       saved_file_fallback=False)
    totals = [row for row in packet['team_totals']['records'] if row['result_key'] == key]
    if len(totals) != 1:
        return dict(unavailable, reason='unavailable_fixture_team_oracle')
    retained._validate_team_oracle(fixture, totals[0]['teams'])
    actors = [row for row in packet['retained_players'] if row.get('native_match_key', row.get('fixture_key')) == key]
    if not actors or len(retained._validated_actors(actors, totals[0]['teams'])) != len(actors):
        return dict(unavailable, reason='unavailable_canonical_fixture_roster')
    with bridge.lock, bridge._read_scope(session_id):
        process = bridge._current(session_id); tables = bridge._player_layout(process)
        read, _, _ = bridge._world_state(process, tables)
        base = tables[0] - players.RVA[0]
        current_spatial_axes.verify_native(read, base)
        verify_period_clock(read, base)
        for rva, expected in active_match_tracking.CLOCK_BINDING_SPANS:
            if read(base + rva, len(expected)) != expected:
                raise ValueError('Spatial period native tracking clock changed')
        current_epoch = process_epoch(bridge)
        read.verify()
    source = retained.capture_source(bridge, session_id, fixture_ref, key, fixture, include_tracking=True)
    if source.get('state') != 'available' or source.get('tracking', {}).get('state') != 'available':
        return dict(unavailable, reason='unavailable_retained_tracking_source')
    save = packet['capture']['save']
    documents = (store or SpatialPeriodStore()).observations(save, fixture)['observations']
    matched = []
    for capture_id, observation in documents.items():
        if digest(observation) != capture_id:
            raise ValueError('Spatial period observation content changed')
        if WITNESS_KEY not in observation:
            continue
        result = project(source['tracking'], actors, observation, save=save, fixture=fixture)
        if result['state'] == 'available': matched.append(result)
    if not matched:
        return dict(unavailable, reason='prospective_tracking_specific_period_witness_missing_or_unmatched')
    if len({digest([result['official_match_unique_id'], [(p['period'], p['start_tick'], p['end_tick'])
                for p in result['periods']]]) for result in matched}) != 1:
        return dict(unavailable, reason='conflicting_spatial_period_observations')
    result = matched[0]
    observation = documents[result['capture_id']]
    fresh = retained.capture_source(bridge, session_id, fixture_ref, key, fixture, include_tracking=True)
    # Actor ordinals/names/IDs are consumed by the witness and the output,
    # including roster rows without tracking. Reacquire their canonical frame;
    # a process/load epoch alone cannot detect same-epoch slot replacement.
    fresh_packet = capture_live(bridge, session_id, [fixture_ref], include_players=True)
    fresh_items = fresh_packet['capture']['fixtures']
    if (fresh_packet.get('_live_capture_epoch') != epoch or len(fresh_items) != 1
            or fresh_items[0]['native_match_key'] != key
            or fresh_items[0]['fixture']['fixture_ref'] != fixture_ref
            or fixture_identity(fresh_items[0]['fixture']) != fixture_identity(fixture)
            or career_identity(fresh_packet['capture']['save']) != career_identity(save)):
        raise ValueError('Spatial period canonical fixture or career changed')
    fresh_totals = [row for row in fresh_packet['team_totals']['records'] if row['result_key'] == key]
    if len(fresh_totals) != 1:
        raise ValueError('Spatial period canonical team oracle changed')
    retained._validate_team_oracle(fixture, fresh_totals[0]['teams'])
    fresh_actors = [row for row in fresh_packet['retained_players']
                    if row.get('native_match_key', row.get('fixture_key')) == key]
    if not fresh_actors or len(retained._validated_actors(fresh_actors, fresh_totals[0]['teams'])) != len(fresh_actors):
        raise ValueError('Spatial period canonical roster changed')
    consumed_actor_fields = ('side_index', 'stored_player_slot', 'canonical_person_id',
                             'person_index_word', 'person_name')
    identities = lambda rows: sorted(tuple(row[field] for field in consumed_actor_fields) for row in rows)
    if identities(fresh_actors) != identities(actors):
        raise ValueError('Spatial period canonical actor identities changed')
    owner_fields = ('owner_team_native_id', 'coach_index', 'coach_name')
    if (fresh.get('state') != 'available' or fresh.get('tracking', {}).get('state') != 'available'
            or any(fresh.get(key) != source.get(key) for key in owner_fields)
            or tracking_fingerprint(fresh['tracking'], fresh_actors, observation['fingerprint_cursor'])
                != observation[WITNESS_KEY]['tracking_fingerprint']
            or capture_epoch(bridge, session_id) != epoch):
        raise ValueError('Spatial period source or process/save epoch changed')
    for period in result['periods']:
        period['players'] = [row for row in period['players'] if row['side_index'] == sides[0]]
    return dict(result, fixture=fixture, native_match_key=key, team_native_id=team_native_id,
                captured_save=save, saved_file_fallback=False, source_rechecked=True, atomic=False,
                source_epoch_matches_current=result['source_process_load_epoch'] == current_epoch,
                binding='Complete observed tracking semantics match the prospective native-period capture; fixture UID alone is never an epoch.')
