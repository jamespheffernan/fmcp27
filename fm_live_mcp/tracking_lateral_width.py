"""Derived sample-weighted lateral width, distinct from absolute mean position."""
import struct

from .live_average_positions import decode_tracking_average_positions, _f32


def verify_axes(bridge, session_id):
    from . import current_spatial_axes, players
    with bridge.lock, bridge._read_scope(session_id):
        process = bridge._current(session_id)
        tables = bridge._player_layout(process)
        read, _, _ = bridge._world_state(process, tables)
        current_spatial_axes.verify_native(read, tables[0] - players.RVA[0])
        read.verify()
        bridge._current(session_id)


def project_lateral_width(tracking, players):
    """Use actual possession bytes, without clamping or guessed on-pitch time."""
    checked = decode_tracking_average_positions(tracking, players)
    if sum(p['sample_count'] for p in checked['players']) > 1_000_000:
        raise ValueError('Lateral width total sample budget exceeded')
    named = {(p['side_index'], p['stored_player_slot']): p for p in checked['players']}
    streams = {(r['side_index'], r['stored_player_slot']): r for r in tracking['players']}
    phases = tracking.get('possession_samples')
    output = []
    for player in players:
        key = player['side_index'], player['stored_player_slot']
        identity = {k: player[k] for k in ('side_index', 'stored_player_slot', 'canonical_person_id', 'person_name')}
        if key not in streams:
            output.append(dict(identity, state='unavailable_no_tracking_stream', all_samples=None,
                               in_possession=None, out_of_possession=None, coverage=None))
            continue
        source, native = streams[key], named[key]
        buckets = {k: {'sample_count': 0, 'absolute_raw_sum': 0, 'zero_pair_sample_count': 0,
                       'trailing_zero_pair_sample_count': 0} for k in ('all_samples', 'in_possession', 'out_of_possession')}
        coverage = dict(native['coverage'], phase_uncovered_sample_count=0,
                        phase_unclassified_sample_count=0, phase_other_sample_count=0)
        tail_start = native['sample_count'] - native['coverage']['trailing_zero_pair_sample_count']
        for index, pair in enumerate(struct.iter_unpack('<hh', source['samples'])):
            selected = ['all_samples']
            phase_index = (source['start_tick'] + index * 24) // 24
            if not phases or phase_index >= len(phases):
                coverage['phase_uncovered_sample_count'] += 1
            elif phases[phase_index] == 255:
                coverage['phase_unclassified_sample_count'] += 1
            elif phases[phase_index] not in (0, 1):
                coverage['phase_other_sample_count'] += 1
            else:
                selected.append('in_possession' if phases[phase_index] == key[0] else 'out_of_possession')
            for bucket in selected:
                item = buckets[bucket]
                item['sample_count'] += 1
                item['absolute_raw_sum'] += abs(pair[0])
                item['zero_pair_sample_count'] += pair == (0, 0)
                item['trailing_zero_pair_sample_count'] += index >= tail_start
        for name, bucket in buckets.items():
            n, total = bucket['sample_count'], bucket.pop('absolute_raw_sum')
            bucket['mean_absolute_lateral_native'] = _f32(total * _f32(.01) / n) if n else None
            bucket['state'] = 'available' if n else 'unavailable_no_selected_samples'
            if name != 'all_samples' and not phases:
                bucket.update(state='unavailable_possession_stream', sample_count=None,
                              zero_pair_sample_count=None, trailing_zero_pair_sample_count=None)
        output.append(dict(identity, state=native['state'], **buckets, coverage=coverage))
    return dict(state='available' if any(p['state'] == 'available' for p in output) else 'unavailable_no_position_samples',
                players=output, measure='sample_weighted_mean_absolute_lateral_native',
                definition='mean(abs(raw signed16 axis0) * float32(0.01)); absolute value before averaging',
                lateral_axis='native_axis_0_verified_pitch_width', physical_units=None, human_left_right=None,
                sample_step_native_ticks=24,
                phase_policy='Actual possession byte at native tick//24: 0/1 only;255/other/missing/beyond-stream excluded from subsets and counted; no end-byte clamping.',
                coverage_policy='Each player uses its own stored samples. Zero pairs and post-exit tails remain included; sample counts are not on-pitch minutes. Different player denominators are not a synchronous comparison.',
                interpretation='Derived tracking width from the centreline, not the absolute signed mean, official AveragePositionMap, movement distance, receiving space, tactical role or effect.')
