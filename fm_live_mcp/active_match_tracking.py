"""Passive native tracking points at or before one checked playback cursor.

Caller owns one ReadSet and its final career/process verification. An inactive
match stays unavailable. Frozen historical prefix controls do not establish a
positive active-match runtime observation.
"""
import hashlib
import math
import struct

from . import active_match_shots, active_match_shot_timeline, live_average_positions


def clip_tracking(tracking, cursor):
    """Pure native point cutoff; preserve zero pairs and native phase handling."""
    if type(cursor) is not int or not 0 <= cursor < 65536:
        raise ValueError('Unsupported tracking/playback clock range')
    rows = tracking.get('players')
    if not isinstance(rows, list) or len(rows) > live_average_positions.MAX_TRACKING_PLAYERS:
        raise ValueError('Unsupported tracking player budget')
    clipped = []
    for row in rows:
        start = row.get('start_tick')
        samples = row.get('samples')
        if (type(start) is not int or not 0 <= start <= 0x7fffffff
                or not isinstance(samples, bytes) or len(samples) % 4
                or len(samples) // 4 > live_average_positions.MAX_TRACKING_SAMPLES):
            raise ValueError('Unsupported tracking sample geometry')
        count = min(len(samples) // 4, (cursor - start) // 24 + 1) if start <= cursor else 0
        # A future entrant has no past tracking row, actor name or position.
        if count:
            clipped.append({**row, 'samples': samples[:count * 4]})
    phases = tracking.get('possession_samples')
    if phases is not None and not isinstance(phases, bytes):
        raise ValueError('Unsupported tracking possession bytes')
    return {**tracking, 'players': clipped,
            'possession_samples': phases[:cursor // 24 + 1] if phases else phases}


def _read_prefix(read, cbe, cursor):
    from .live_retained_shots import _records
    entries = _records(read, cbe + 0xd0, 40, live_average_positions.MAX_TRACKING_PLAYERS)
    rows, seen = [], set()
    for offset in range(0, len(entries), 40):
        entry = entries[offset:offset + 40]
        key = struct.unpack_from('<b', entry)[0]
        if not 0 <= key < 52 or key in seen:
            raise ValueError('Unsupported or duplicate active tracking key')
        seen.add(key)
        start = struct.unpack_from('<I', entry, 8)[0]
        first, last, capacity = struct.unpack_from('<QQQ', entry, 16)
        if (not first <= last <= capacity or (last - first) % 4 or (capacity - first) % 4
                or capacity - first > live_average_positions.MAX_TRACKING_SAMPLES * 4
                or (first and (first < 4096 or first % 8)) or (not first and (last or capacity))):
            raise ValueError('Unsupported active tracking vector')
        count = min((last - first) // 4, (cursor - start) // 24 + 1) if start <= cursor else 0
        if count:
            end = first + count * 4
            samples = b''.join(read(at, min(8192, end - at)) for at in range(first, end, 8192))
            rows.append({'side_index': key % 2, 'stored_player_slot': key // 2,
                         'start_tick': start, 'samples': samples})
    first, last, capacity = struct.unpack('<QQQ', read(cbe + 0xe8, 24))
    phases = b''
    if (first, last, capacity) != (0, 0, 0):
        if (first < 4096 or first % 8 or not first <= last <= capacity
                or capacity - first > live_average_positions.MAX_TRACKING_SAMPLES):
            raise ValueError('Unsupported active possession vector')
        end = first + min(last - first, cursor // 24 + 1)
        phases = b''.join(read(at, min(8192, end - at)) for at in range(first, end, 8192))
    return {'orientation_profile': read(cbe + 0x108, 16), 'possession_samples': phases, 'players': rows}


def capture_source(read, base, client, engine, *, current_time_slice):
    """Read only the selected tracking prefix under GAME_MATCH/client ownership.

    Exact fixture identity stays independent of changing cumulative statistics.
    Caller binds the supplied cursor through inspect_bound and verifies reads.
    """
    if type(current_time_slice) is not int or not 0 <= current_time_slice < 65536:
        raise ValueError('Unsupported active tracking cursor')
    for rva, expected in (CLOCK_BINDING_SPANS + live_average_positions.TRACKING_NATIVE_SPANS
                          + active_match_shots.NATIVE_SPANS):
        if read(base + rva, len(expected)) != expected:
            raise ValueError('Active tracking/playback clock native binding changed')
    q = lambda address: struct.unpack('<Q', read(address, 8))[0]
    active_match_shots._type(read, base, client, 0x55fac38)
    active_match_shots._type(read, base, engine, 0x55fa258)
    wrapper = active_match_shots._pointer(q(client + 0xf8))
    if q(wrapper + 0x18) != engine:
        raise ValueError('Active tracking client/engine ownership changed')
    match_id = q(engine + 0x20)
    if not match_id or q(client + 0x138) != match_id:
        raise ValueError('Active tracking match identities differ')
    stats = active_match_shots._pointer(q(engine + 0x14e90))
    active_match_shots._type(read, base, stats, 0x55fa850)
    active_match_shots._type(read, base, client + 8, 0x56a2380)
    identity = active_match_shots._fixture_identity(read, base, active_match_shots._pointer(q(stats + 0x18)))
    if active_match_shots._fixture_identity(read, base, active_match_shots._pointer(q(client + 0x20))) != identity:
        raise ValueError('Active tracking engine/client fixtures differ')
    cbe = q(engine + 0x14e98)
    if not cbe:
        return {'state': 'unavailable_engine_cbe_absent'}
    active_match_shots._pointer(cbe)
    width, length = struct.unpack('<ff', read(cbe + 0x100, 8))
    geometry = ({'half_width_native': width, 'half_length_native': length}
                if all(math.isfinite(v) and v > 0 for v in (width, length)) else None)
    return {'state': 'available_engine_tracking_source',
            'tracking': _read_prefix(read, cbe, current_time_slice),
            'source_identity': (client, engine, identity), 'fixture_identity': identity, 'cbe_address': cbe,
            'match_unique_id': match_id, 'pitch_geometry': geometry,
            'engine_frontier_raw': struct.unpack('<I', read(engine + 0x154dc, 4))[0]}


def project(source, bound_playback, players, *, actor_binding=None):
    """Pure projection of a caller's guarded source; actor provenance stays explicit.

    actor_binding must be independently established for this match. Current
    tactical-array indices never authorize named historical tracking means.
    """
    result = {'state': 'unavailable', 'source_kind': 'GAME_MATCH_CBE_tracking_at_playback_cursor',
              'temporal_scope': 'native_tracking_sample_points_at_or_before_playback_cursor',
              'boundary_policy': 'start_tick + sample_index*24 <= current_time_slice',
              'native_tracking_clock_domain_verified': False,
              'displayed_pixels_verified': False, 'live_vs_replay_verified': False,
              'online_positive_control_verified': False, 'players': None,
              'clock_units': 'native_playback_time_slice', 'minute_conversion': None}
    if source.get('state') != 'available_engine_tracking_source':
        return {**result, 'reason': source.get('state', 'unavailable_tracking_source')}
    identity = source.get('match_unique_id')
    if type(identity) is not int or identity <= 0 or identity != bound_playback.get('official_match_unique_id'):
        raise ValueError('Tracking source and playback match identities differ')
    cursor, maximum, frontier = (bound_playback.get('current_time_slice'),
                                 bound_playback.get('buffered_max_time_slice'), source.get('engine_frontier_raw'))
    if (any(type(value) is not int for value in (cursor, maximum, frontier))
            or not 0 <= cursor <= maximum < 65536 or not cursor <= frontier < 65536):
        return {**result, 'reason': 'unavailable_clock_range_or_wrap'}
    if (not isinstance(actor_binding, dict) or actor_binding.get('state') != 'validated_native_stored_slots'
            or actor_binding.get('official_match_unique_id') != identity):
        return {**result, 'reason': 'unavailable_active_tracking_actor_join',
                'native_tracking_clock_domain_verified': True}
    selected = clip_tracking(source['tracking'], cursor)
    if not isinstance(players, list):
        raise ValueError('Expected canonical active actor rows')
    known = {(row.get('side_index'), row.get('stored_player_slot')) for row in players}
    unresolved = [{'side_index': row['side_index'], 'stored_player_slot': row['stored_player_slot'],
                   'sample_count': len(row['samples']) // 4, 'state': 'unresolved_active_tracking_actor_join'}
                  for row in selected['players']
                  if (row['side_index'], row['stored_player_slot']) not in known]
    joined = {**selected, 'players': [row for row in selected['players']
              if (row['side_index'], row['stored_player_slot']) in known]}
    decoded = live_average_positions.decode_tracking_average_positions(joined, players)
    digest = hashlib.sha256()
    for row in selected['players']:
        digest.update(struct.pack('<BBI', row['side_index'], row['stored_player_slot'], row['start_tick']))
        digest.update(row['samples'])
        digest.update(bytes(live_average_positions.tracking_positive_orientation(
            selected['orientation_profile'], row['side_index'], row['start_tick'] + index * 24)
            for index in range(len(row['samples']) // 4)))
    digest.update(selected.get('possession_samples') or b'')
    return {**result, **decoded, 'state': ('available_partial' if decoded['players'] else 'unavailable_active_tracking_actor_join') if unresolved else decoded['state'],
            'reason': 'unresolved_selected_tracking_actors' if unresolved else None,
            'unresolved_tracking_actors': unresolved,
            'source_kind': result['source_kind'], 'current_time_slice': cursor,
            'official_match_unique_id': identity, 'pitch_geometry': source.get('pitch_geometry'),
            'native_tracking_clock_domain_verified': True, 'selected_source_sha256': digest.hexdigest(),
            'actor_binding_state': actor_binding['state'],
            'coverage_policy': decoded['coverage_policy'] + '; future samples and future entrants are omitted'}


def inspect_bound(read, base, client, engine, bound_playback, players, *, actor_binding=None):
    """Use the caller's single checked playback context and final shared ReadSet."""
    active_match_shot_timeline._verify_bound(read, base, client, engine, bound_playback)
    source = capture_source(read, base, client, engine, current_time_slice=bound_playback['current_time_slice'])
    return project(source, bound_playback, players, actor_binding=actor_binding)


def _prefix_signature(tracking):
    """Only consumed sample/phase/sign evidence; future profile fields stay free."""
    result = {}
    phases = tracking.get('possession_samples')
    for row in tracking['players']:
        key = row['side_index'], row['stored_player_slot']
        start, samples = row['start_tick'], row['samples']
        ticks = [start + index * 24 for index in range(len(samples) // 4)]
        signs = bytes(live_average_positions.tracking_positive_orientation(
            tracking['orientation_profile'], row['side_index'], tick) for tick in ticks)
        selected_phases = (bytes(phases[min(tick // 24, len(phases) - 1)] for tick in ticks)
                           if phases else None)
        result[key] = start, samples, signs, selected_phases
    return result


def verify_prefix(fresh_read, base, client, engine, bound_playback, source):
    """Reverify a fixed prefix while its same-match cursor can move forwards.

    fresh_read must obtain fresh headers/bytes, bypassing an earlier ReadSet's
    changing-vector memo or page cache. Reallocation of backing buffers is fine:
    capture_source reselects current headers at the original fixed cursor.
    Caller separately revalidates canonical actors and its process/career epoch.
    """
    from . import active_match_playback
    fixed = bound_playback['current_time_slice']
    if source.get('state') != 'available_engine_tracking_source':
        raise ValueError('Cannot verify an unavailable active tracking prefix')
    if source.get('match_unique_id') != bound_playback.get('official_match_unique_id'):
        raise ValueError('Tracking prefix and playback match identities differ')
    if source.get('source_identity', ())[:2] != (client, engine):
        raise ValueError('Tracking prefix belongs to another client/engine')
    current = active_match_playback.capture(fresh_read, base, client=client)
    if current.get('state') != 'bound_playback_cursor':
        raise ValueError('Tracking playback owner is no longer bound')
    bound = current['bound_playback']
    identity_fields = ('playback_address', 'frame_provider_address', 'source_match_address',
                       'local_playback_handle', 'official_match_unique_id')
    if any(bound.get(key) != bound_playback.get(key) for key in identity_fields):
        raise ValueError('Tracking playback source relinked')
    now, maximum = bound['current_time_slice'], bound['buffered_max_time_slice']
    if (any(type(value) is not int for value in (fixed, now, maximum))
            or not 0 <= fixed <= now <= maximum < 65536):
        raise ValueError('Tracking playback cursor moved backwards or left its domain')
    checked = capture_source(fresh_read, base, client, engine, current_time_slice=fixed)
    if (checked.get('state') != 'available_engine_tracking_source'
            or checked['source_identity'] != source['source_identity']
            or checked['match_unique_id'] != source['match_unique_id']
            or checked.get('cbe_address') != source.get('cbe_address')
            or checked.get('pitch_geometry') != source.get('pitch_geometry')):
        raise ValueError('Tracking prefix ownership or fixture source changed')
    if not fixed <= checked['engine_frontier_raw'] < 65536:
        raise ValueError('Tracking engine frontier does not cover the fixed cursor')
    if _prefix_signature(checked['tracking']) != _prefix_signature(source['tracking']):
        raise ValueError('Consumed tracking position, phase or orientation prefix changed')
    # Re-read the playback anchor after the prefix. This catches a seek/relink
    # during the verification window without requiring a stationary cursor.
    after = active_match_playback.capture(fresh_read, base, client=client)
    if after.get('state') != 'bound_playback_cursor':
        raise ValueError('Tracking playback owner disappeared during prefix verification')
    end = after['bound_playback']
    if (any(end.get(key) != bound_playback.get(key) for key in identity_fields)
            or not now <= end['current_time_slice'] <= end['buffered_max_time_slice'] < 65536):
        raise ValueError('Tracking playback source changed during prefix verification')
    q = lambda address: struct.unpack('<Q', fresh_read(address, 8))[0]
    if (q(engine + 0x20) != source['match_unique_id'] or q(client + 0x138) != source['match_unique_id']
            or q(engine + 0x14e98) != source['cbe_address']
            or q(q(client + 0xf8) + 0x18) != engine
            or not fixed <= struct.unpack('<I', fresh_read(engine + 0x154dc, 4))[0] < 65536):
        raise ValueError('Tracking owner changed after prefix verification')
    return {'state': 'verified_fixed_prefix_under_monotonic_same_match_playback',
            'current_time_slice': fixed, 'verified_at_time_slice': end['current_time_slice'],
            'official_match_unique_id': checked['match_unique_id'],
            'selected_sample_count': sum(len(row['samples']) // 4 for row in source['tracking']['players']),
            'backing_buffer_reselected': True, 'canonical_actor_reverification_owned_by_caller': True}


CLOCK_BINDING_SPANS = (
    (0x781e70, bytes.fromhex('600e41f9e10314aa1e520495600e41f9e10314aa19520495600e41f9e10314aaff510495600e41f9e10314aa29520495')),
    (0x48966e8, bytes.fromhex('004003912aeeff17')),
    (0x4891ffc, bytes.fromhex('695595524955a572897e299b2afd7fd329fd62d329010a0b0a0380520b038052382d0a1be9830091')),
    (0x4892038, bytes.fromhex('48835eb80903086bed060054287d3b9b0afd7fd308fd629308010a0b087d40934a037fa915000acbabfe42931f0995eb890600541c010bcb')),
    (0x4892138, bytes.fromhex('1f010beb020100544809088b48831ff805000014')),
    (0x489668c, bytes.fromhex('e80300aa6a5595524a55a5722a7c2a9b4bfd7fd34afd62934a010b0b09adcea96b0109cb6c0500514a7daa0a5f010c6b4ab18c1a4a0500114a7d4093')),
)
