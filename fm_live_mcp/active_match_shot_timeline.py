"""Completed native shot events before one bound playback cursor.

No minute conversion, chronological sorting, actor identity inference, or
rendered-screen claim. Caller owns one authoritative clock/period sample and
must verify its whole ReadSet and native career/process epoch after capture.
"""
from collections import Counter
import math
import struct

from . import active_match_shots as shots, players
from .retained_shot_outcomes import outcome_counts


def _q(read, address):
    return players.u64(read(address, 8))


def _verify_bound(read, base, client, engine, bound):
    for rva, expected in DOMAIN_SPANS:
        if read(base+rva, len(expected)) != expected:
            raise ValueError('Active event/playback clock domain native binding changed')
    address = bound['playback_address']
    if _q(read, address) != base+0x54ec490 or _q(read, address+0x10) != address:
        raise ValueError('Unexpected bound playback native type')
    provider = _q(read, address+0x1408)
    if provider != bound['frame_provider_address']:
        raise ValueError('Bound playback provider changed')
    source_match = _q(read, provider+0x28)
    if _q(read, source_match) != base+0x55fa258:
        raise ValueError('Unexpected playback source GAME_MATCH type')
    identity = bound['official_match_unique_id']
    if not identity or any(_q(read, pointer) != identity for pointer in
                           (source_match+0x20, engine+0x20, client+0x138)):
        raise ValueError('Playback and shot match identities differ')
    current, maximum = struct.unpack('<II', read(address+0x1dc0, 8))
    if (current != bound['current_time_slice'] or maximum != bound['buffered_max_time_slice']
            or current > maximum):
        raise ValueError('Bound playback cursor changed')


def inspect_bound(read, base, client, engine, bound_playback, *, period_split=None, shot_source=None, capture_observation=False, actor_binding=None):
    """Reuse caller's sole bound playback/period sample; do not recapture clocks."""
    _verify_bound(read, base, client, engine, bound_playback)
    source = shot_source if shot_source is not None else shots.capture_source(read, base, client, engine)
    if source['state'] == 'available_engine_source' and source['source_identity'][:2] != (client, engine):
        raise ValueError('Shot source belongs to another client/engine')
    result = project(source, bound_playback, period_split=period_split, actor_binding=actor_binding)
    if capture_observation and result.get('state') == 'available':
        result['_host_period_source'] = source
    return result


def _summary(rows, coverage):
    result = []
    for side in range(2):
        confidence = coverage[side].get('metric_confidence', {})
        known = confidence.get('shots') == 'verified' if confidence else coverage[side]['state'] == 'available'
        xg_known = confidence.get('expected_goals') == 'verified' if confidence else known
        selected = [row for row in rows if row['side_index'] == side]
        body = Counter(row['body_part'] or 'unclassified' for row in selected)
        result.append({'side_index': side, 'state': 'available_completed_native_attempts' if xg_known else 'available_completed_native_counts_only' if known else 'unavailable_engine_side_unreconciled',
                       'metric_confidence': dict(confidence),
                       'shots': len(selected) if known else None,
                       'shots_on_target': sum(row['native_category_code'] in (1, 4) for row in selected) if known else None,
                       'shot_goals': sum(row['outcome'] == 'goal' for row in selected) if known else None,
                       'expected_goals_sum_computed': math.fsum(row['expected_goals'] for row in selected) if xg_known else None,
                       'body_part_counts': {key: body[key] if known else None for key in ('head', 'feet', 'unclassified')},
                       'outcome_counts': outcome_counts(selected) if known else None,
                       'scope': 'Derived from reconciled engine CBE attempts; own-goal markers excluded; no independent period aggregate oracle'})
    return result


def _intervals(split, identity, cursor):
    result = []
    for row in (split or {}).get('period_intervals', []):
        if (row.get('official_match_unique_id') != identity
                or row.get('time_slice_domain') != 'native_playback_time_slice'):
            raise ValueError('Period boundary belongs to another match/time domain')
        period = row.get('period')
        expected = {'FirstHalf': 'verified_first_half_boundary', 'SecondHalf': 'verified_second_half_start'}
        if period not in expected or row.get('state') != expected[period]:
            raise ValueError('Unverified period boundary source')
        start, end = row.get('start_tick'), row.get('end_tick')
        if type(start) is not int or start < 0 or (end is not None and (type(end) is not int or end <= start)):
            raise ValueError('Invalid period interval')
        # Future simulator stops do not expose a future interval or extend past playback.
        if start >= cursor:
            continue
        result.append({'period': period, 'start_tick': start,
                       'end_tick': min(end, cursor) if end is not None else cursor,
                       'end_is_playback_cursor': end is None or end >= cursor})
    if len({row['period'] for row in result}) != len(result):
        raise ValueError('Ambiguous period intervals')
    for left in result:
        for right in result:
            if left is right:
                continue
            if max(left['start_tick'], right['start_tick']) < min(left['end_tick'], right['end_tick']):
                raise ValueError('Overlapping period intervals')
    return result


def project(source, bound_playback, *, period_split=None, actor_binding=None):
    """Pure projection after inspect_bound has checked native ownership/domain."""
    packet = shots.project(source, actor_binding=actor_binding) if actor_binding is not None else shots.project(source)
    out = {'state': 'unavailable', 'source_kind': 'GAME_MATCH_CBE_bound_to_native_playback_cursor',
           'temporal_scope': 'completed_native_events_strictly_before_playback_cursor',
           'displayed_time_statistics_verified': False, 'rendered_presentation_verified': False,
           'replay_exclusion_verified': False, 'clock_units': 'native_time_slice',
           'clock_conversion': None, 'shots': None, 'own_goal_markers': None,
           'sides': None, 'periods': [], 'period_assignment_unknown': [],
           'boundary_policy': 'start<=end<cursor; period start<=event start and event end<period end; equality at end excluded',
           'actor_policy': packet.get('actor_policy'),
           'source_validation': packet.get('side_coverage') and
             [{'side_index': row['side_index'], 'state': row['state'], 'checks': row['checks'],
               'metric_confidence': row.get('metric_confidence', {})}
              for row in packet['side_coverage']]}
    if source['state'] != 'available_engine_source':
        out['reason'] = source['state']; return out
    identity = source.get('match_unique_id')
    if not identity or identity != bound_playback.get('official_match_unique_id'):
        raise ValueError('Shot source and playback identities differ')
    cursor = bound_playback['current_time_slice']
    maximum = bound_playback['buffered_max_time_slice']
    frontier = source['engine_frontier_raw']
    if (any(type(value) is not int for value in (cursor, maximum, frontier))
            or not 0 <= cursor <= frontier < 65536 or not cursor <= maximum <= 0xffffffff):
        out['reason'] = 'unavailable_clock_range_or_u16_wrap'; return out
    completed = lambda row: row['native_clock_start_raw'] <= row['native_clock_end_raw'] < cursor
    selected = [dict(row, temporal_scope=out['temporal_scope']) for row in packet['shots'] if completed(row)]
    markers = [dict(row, temporal_scope=out['temporal_scope']) for row in packet['own_goal_markers'] if completed(row)]
    intervals = _intervals(period_split, identity, cursor)
    for row in selected:
        matches = [interval['period'] for interval in intervals
                   if interval['start_tick'] <= row['native_clock_start_raw']
                   and row['native_clock_end_raw'] < interval['end_tick']]
        row['period'] = matches[0] if len(matches) == 1 else None
        row['period_state'] = 'verified_native_stop_interval' if len(matches) == 1 else 'unknown_boundary_or_unavailable_interval'
    out.update(state='available' if packet['state'] == 'available' else 'available_partial',
               reason=None, official_match_unique_id=identity, current_time_slice=cursor,
               native_event_clock_domain_verified=True, native_ended_exclusive_cutoff_verified=True,
               shots=selected, own_goal_markers=markers, sides=_summary(selected, packet['side_coverage']),
               period_assignment_unknown=[row['event_id'] for row in selected if row['period'] is None],
               periods=[dict(interval, sides=_summary([row for row in selected if row['period'] == interval['period']], packet['side_coverage']))
                        for interval in intervals],
               completeness='Conservative native cutoff; cursor/period-end ties and crossed boundaries are not assigned; each metric retains its own side reconciliation; unknown is not zero')
    return out


DOMAIN_SPANS = ((71954192, b'\xf3\x03\x00\xaa\x08P@\x91\x15\xa1/\x91\xa1\xf6H\xb9\x08P@\x91\x00a)\x91\x8a\xd6\x10\x94'), (76368240, b'\xe1S\x00\xb9'), (76377040, b'\xe1C\x02\x91\xe0\x03\x1a\xaa\xe2S@\xb9\xa3\x08\x00\x94'), (76385928, b'\xf3\x03\x02\xaa'), (76386160, b'\xe0\x03\x00\x91\xe1\x03\x15\xaa\xe3\x03\x13\xaa\x8a\xc5\xfe\x97'), (76064200, b'\xf6\x03\x03\xaa'), (76064592, b'w.\x00\xb9\x7fb\x00yvf\x00y'), (76068904, b'\x00d@y\xc0\x03_\xd6'), (76386188, b'\xe8\xab@9\x88\x03\x004\x80"B\xf9\x08\xa4\xc0\xa9'), (7870980, b'\x08\x04@\xf9\xe8\x00\x00\xb4\x08\x91\x03\x91\x08\xfd\xdf\x88\x1f\x05\x001`\x00\x00T\xe0\x03\x08\xaa\xc0\x03_\xd6\x08\x14@\xf9\x89\x9b\x8aR)\x00\xa0r\x08ii\xb8\xe0\x03\x08\xaa\xc0\x03_\xd6'), (7581880, b'`\x06J\xf9R\x1a\x01\x94`\xc6\x1d\xb9'), (7580084, b'`\x06J\xf9\x13\x1c\x01\x94\xf5\x03\x00\xaat\xc2]\xb9$\x1c\x01\x94\x08\x00\x14\x0b\xbf\x02\x08k\x8a\x00\x00T'), (7580180, b'`\x06J\xf9\xfb\x1b\x01\x94\x9f\x02\x00k\x88\xb2\x80\x1ah\xe2\x1d\xb9'))
