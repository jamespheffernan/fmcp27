"""Named native completed-pass events through a checked active playback cursor.

No cumulative engine counter is used as an observed-play denominator. The
caller reprojects a fixed semantic event prefix while that same match advances.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import struct

from . import (active_match_people, active_match_playback, active_match_shots,
               active_match_shot_timeline, active_match_source, live_retained_passes,
               live_retained_shots, players, pass_field_position)

MAX_EVENTS = 8192
PASS_CATEGORIES = frozenset(range(6, 12))


def _bound_identity(bound):
    return tuple(bound.get(k) for k in ('playback_address', 'frame_provider_address',
        'source_match_address', 'local_playback_handle', 'official_match_unique_id'))


def _fixture_identity(fixture):
    return (fixture['date'], tuple((fixture[k].get('database_index'), fixture[k].get('native_id'))
            for k in ('home_team', 'away_team')), (fixture.get('competition') or {}).get('native_id'))


def select_events(raw, cursor, *, include_locations=False, include_pass_attempts=False):
    """Select completed native event records, not events at/future of the cursor."""
    if not isinstance(raw, bytes) or len(raw) % 56 or len(raw) > MAX_EVENTS * 56:
        raise ValueError('Unsupported active event extent')
    if type(cursor) is not int or not 0 <= cursor < 65536:
        raise ValueError('Unsupported active pass cursor domain')
    selected = []
    identities = set()
    for offset in range(0, len(raw), 56):
        event = raw[offset:offset + 56]
        if event[42] not in PASS_CATEGORIES:
            continue
        start = struct.unpack_from('<H', event, 0x22)[0]
        end = struct.unpack_from('<H', event, 0x32)[0]
        if end >= cursor:
            continue
        if start > end:
            raise ValueError('Active pass clock range is reversed or wrapped')
        identity = struct.unpack_from('<I', event, 44)[0]
        if identity in identities:
            raise ValueError('Duplicate consumed active pass event identity')
        identities.add(identity)
        if event[40] not in (0, 1):
            raise ValueError('Invalid consumed active pass side')
        selected.append({'event_id': identity, 'side_index': event[40],
                         'stored_player_slot': event[39], 'recipient_slot': event[41],
                         'category': event[42], 'flags_word': struct.unpack_from('<H', event, 48)[0],
                         'start': start, 'end': end})
    if include_locations:
        locations = {struct.unpack_from('<I', raw, at + 44)[0]: raw[at:at+56]
                     for at in range(0, len(raw), 56)
                     if (raw[at+42] in PASS_CATEGORIES if include_pass_attempts else raw[at+42] == 7)
                     and not struct.unpack_from('<H', raw, at+48)[0] & 8
                     and struct.unpack_from('<H', raw, at+50)[0] < cursor}
        for event in selected:
            if event['event_id'] in locations:
                # Only consumed location bytes; never path pointers or future geometry.
                event['location_xy_hex'] = locations[event['event_id']][24:32].hex()
    # Native array insertion can be by event start; source order is not clock order.
    return sorted(selected, key=lambda e: e['event_id'])


def _actor_map(actors):
    if actors.get('state') != 'validated_native_stored_slots':
        raise ValueError('Active original-slot actor binding is unverified')
    result = {}
    people = set()
    for player in actors['players']:
        side, slot, identity = (player.get('side_index'), player.get('stored_player_slot'),
                               player.get('canonical_person_id'))
        if (type(side) is not int or side not in (0, 1) or type(slot) is not int or not 0 <= slot < 26
                or type(identity) is not int or identity <= 0 or (side, slot) in result or identity in people):
            raise ValueError('Invalid or duplicate active pass actor')
        result[side, slot] = player
        people.add(identity)
    return result


def project(events, actors, fixture, *, cursor, match_unique_id):
    """Canonical side/original-slot joins only; unresolved pairs stay explicit."""
    roster = _actor_map(actors)
    if actors.get('official_match_unique_id') != match_unique_id:
        raise ValueError('Active passing actors belong to another match')
    sides = []
    for side, team_key in enumerate(('home_team', 'away_team')):
        own = [e for e in events if e['side_index'] == side and e['category'] == 7 and not e['flags_word'] & 8]
        pairs = Counter()
        names = {}
        unresolved = []
        for event in own:
            sender, recipient = (roster.get((side, event[key])) for key in ('stored_player_slot', 'recipient_slot'))
            if (sender is None or recipient is None
                    or not sender.get('person_name') or not recipient.get('person_name')):
                unresolved.append({'event_id': event['event_id'], 'state': 'unresolved_same_side_original_slot_actor'})
                continue
            key = sender['canonical_person_id'], recipient['canonical_person_id']
            pairs[key] += 1
            names[key] = sender['person_name'], recipient['person_name']
        rows = [{'from_person_native_id': a, 'from_name': names[a, b][0],
                 'to_person_native_id': b, 'to_name': names[a, b][1],
                 'native_completed_pass_event_count': count}
                for (a, b), count in sorted(pairs.items(), key=lambda pair: (-pair[1], pair[0]))]
        state = 'available' if not unresolved else 'unavailable_actor_coverage'
        sides.append({'side_index': side, 'team': fixture[team_key], 'state': state,
                      'pairs': rows if not unresolved else [], 'unresolved_events': unresolved,
                      'source_completed_pass_event_count': len(own),
                      'named_completed_pass_event_count': sum(pairs.values()),
                      'all_selected_completed_pass_actors_resolved': not unresolved,
                      'passes_attempted': None, 'official_passes_completed': None,
                      'completion_percentage': None,
                      'counter_reconciliation': 'unavailable_at_playback_cursor'})
    return {'state': 'available' if all(s['state'] == 'available' for s in sides) else 'available_partial',
            'fixture': {k: fixture[k] for k in ('date', 'competition', 'home_team', 'away_team')},
            'official_match_unique_id': match_unique_id, 'current_time_slice': cursor, 'sides': sides,
            'source_kind': 'active_GAME_MATCH_CBE_at_bound_playback_cursor',
            'temporal_scope': 'completed_native_pass_events_strictly_before_checked_playback_cursor',
            'boundary_policy': 'native_start<=native_end<fixed_cursor; equality withheld',
            'native_event_clock_domain_verified': True,
            'source_coverage': 'complete_bounded_native_vector_reselected_at_fixed_cursor',
            'actor_policy': 'same-side canonical PERSON plus independently verified native original roster slot',
            'rendered_presentation_verified': False, 'replay_exclusion_verified': False,
            'displayed_minute': None, 'phase': None, 'coordinates': None,
            'limits': ['Counts describe selected native completed-pass events; no observed-play aggregate counter oracle or completion denominator is asserted.',
                       'Unlabelled mask8 records and not-completed events do not form named completed-pass pairs.',
                       'Missing actor names remain unresolved events, never zero evidence for that player.',
                       'Past native event pairs do not establish current on-pitch membership, assists, route, pressing success or tactical causality.']}


def capture_source(read, base, client, engine, *, fixed_cursor, include_locations=False, include_pass_attempts=False):
    """Read the entire bounded current event vector; never read aggregate counters."""
    for at, expected in (active_match_shots.NATIVE_SPANS + active_match_shot_timeline.DOMAIN_SPANS
                         + live_retained_passes.PASS_NATIVE_SPANS + PASS_CLOCK_SPANS):
        if read(base + at, len(expected)) != expected:
            raise ValueError('Active pass event/clock native source changed')
    if include_pass_attempts:
        from .active_pass_attempts import verify_native
        verify_native(read, base)
    q = lambda address: struct.unpack('<Q', read(address, 8))[0]
    active_match_shots._type(read, base, client, 0x55FAC38)
    active_match_shots._type(read, base, engine, 0x55FA258)
    wrapper = active_match_shots._pointer(q(client + 0xF8))
    if q(wrapper + 0x18) != engine or q(client + 0x138) != q(engine + 0x20):
        raise ValueError('Active pass client/engine identity changed')
    stats = active_match_shots._pointer(q(engine + 0x14E90))
    active_match_shots._type(read, base, stats, 0x55FA850)
    active_match_shots._type(read, base, client + 8, 0x56A2380)
    fixture = active_match_shots._fixture_identity(read, base, active_match_shots._pointer(q(stats + 0x18)))
    if active_match_shots._fixture_identity(read, base, active_match_shots._pointer(q(client + 0x20))) != fixture:
        raise ValueError('Active pass engine/client fixtures differ')
    cbe = q(engine + 0x14E98)
    if not cbe:
        return {'state': 'unavailable_engine_cbe_absent'}
    active_match_shots._pointer(cbe)
    frontier = struct.unpack('<I', read(engine + 0x154DC, 4))[0]
    if not fixed_cursor <= frontier < 65536:
        raise ValueError('Active pass engine does not cover the cursor or clock wrapped')
    geometry = None
    if include_locations:
        pass_field_position.verify_native(read, base)
        width, length = struct.unpack('<ff', read(cbe + 0x100, 8))
        if not all(math.isfinite(v) and 0 < v <= 1000 for v in (width, length)):
            raise ValueError('Invalid active pass native pitch geometry')
        geometry = {'half_width_native': width, 'half_length_native': length}
    raw = live_retained_shots._records(read, cbe + 8, 56, MAX_EVENTS)
    result = {'state': 'available', 'events': select_events(raw, fixed_cursor, include_locations=include_locations,
                                                         include_pass_attempts=include_pass_attempts), 'cbe': cbe,
            'fixture_identity': fixture, 'match_unique_id': q(engine + 0x20)}
    if include_locations:
        result['pitch_geometry'] = geometry
    if include_pass_attempts:
        from .active_pass_attempts import source_policy
        result['pass_attempt_policy'] = source_policy()
    return result


def _capture_components(read, base, current_date, *, include_locations=False, include_pass_attempts=False):
    context, binding = active_match_source.inspect_context(read, base, expected_current_date=current_date)
    unavailable = {'state': 'unavailable', 'reason': context.get('reason') or context['source_state'],
                   'fixture': None, 'sides': None, 'current_time_slice': None}
    if binding is None:
        return unavailable, None
    fixture = context['bound_active_fixture']
    if list(binding['team_indices']) != [fixture[k]['database_index'] for k in ('home_team', 'away_team')]:
        raise ValueError('Active pass fixture side ordering changed')
    playback = active_match_playback.capture(read, base, client=binding['client'])
    if playback['state'] != 'bound_playback_cursor':
        return {**unavailable, 'reason': 'unavailable_bound_playback_cursor'}, None
    bound = playback['bound_playback']
    cursor = bound['current_time_slice']
    if not 0 <= cursor <= bound['buffered_max_time_slice'] < 65536:
        return {**unavailable, 'reason': 'unavailable_u16_event_clock_domain'}, None
    actors = active_match_people.inspect_actor_bindings(read, base, binding['engine'],
                    expected_match_unique_id=bound['official_match_unique_id'])
    options = {**({'include_locations': True} if include_locations else {}),
               **({'include_pass_attempts': True} if include_pass_attempts else {})}
    source = capture_source(read, base, binding['client'], binding['engine'], fixed_cursor=cursor, **options)
    if source['state'] != 'available':
        return {**unavailable, 'reason': source['state']}, None
    if source['match_unique_id'] != bound['official_match_unique_id']:
        raise ValueError('Active passing and playback match identities differ')
    expected_fixture = (fixture['date'], fixture['competition']['native_id'],
                        *((fixture[key]['database_index'], fixture[key]['native_id'])
                          for key in ('home_team', 'away_team')))
    if source['fixture_identity'] != expected_fixture:
        raise ValueError('Active pass statistics fixture differs from bound current context')
    result = project(source['events'], actors, fixture, cursor=cursor, match_unique_id=source['match_unique_id'])
    return result, {'fixture': fixture, 'binding': binding, 'bound': bound, 'actors': actors, 'source': source}


def _verify_components(read, base, current_date, packet):
    binding, bound = packet['binding'], packet['bound']
    current = active_match_playback.capture(read, base, client=binding['client'])
    if current['state'] != 'bound_playback_cursor':
        raise ValueError('Active pass playback disappeared')
    now = current['bound_playback']
    fixed = bound['current_time_slice']
    if (_bound_identity(now) != _bound_identity(bound)
            or not fixed <= now['current_time_slice'] <= now['buffered_max_time_slice'] < 65536):
        raise ValueError('Active pass playback relinked or moved backwards')
    context, fresh_binding = active_match_source.inspect_context(read, base, expected_current_date=current_date)
    if (fresh_binding is None or any(fresh_binding.get(k) != binding.get(k) for k in ('client', 'engine', 'team_indices'))
            or _fixture_identity(context['bound_active_fixture']) != _fixture_identity(packet['fixture'])):
        raise ValueError('Active pass current fixture or owner changed')
    options = {**({'include_locations': True} if 'pitch_geometry' in packet['source'] else {}),
               **({'include_pass_attempts': True} if 'pass_attempt_policy' in packet['source'] else {})}
    source = capture_source(read, base, binding['client'], binding['engine'], fixed_cursor=fixed, **options)
    if (source['state'] != 'available' or any(source[k] != packet['source'][k]
            for k in ('events', 'cbe', 'fixture_identity', 'match_unique_id'))):
        raise ValueError('Consumed active pass event prefix changed')
    if source.get('pitch_geometry') != packet['source'].get('pitch_geometry'):
        raise ValueError('Active pass native pitch geometry changed')
    if source.get('pass_attempt_policy') != packet['source'].get('pass_attempt_policy'):
        raise ValueError('Active pass attempt native policy changed')
    actors = active_match_people.inspect_actor_bindings(read, base, binding['engine'],
                    expected_match_unique_id=bound['official_match_unique_id'])
    selected_slots = {(e['side_index'], e[key]) for e in source['events']
                      if e['category'] == 7 and not e['flags_word'] & 8
                      for key in ('stored_player_slot', 'recipient_slot')}
    if 'pass_attempt_policy' in packet['source']:
        selected_slots.update((e['side_index'], e['stored_player_slot']) for e in source['events']
                              if e['category'] in PASS_CATEGORIES and not e['flags_word'] & 8)
    signature = lambda rows: {key: (p.get('canonical_person_id'), p.get('person_index_word'), p.get('person_name'))
                             for key, p in _actor_map(rows).items() if key in selected_slots}
    if signature(actors) != signature(packet['actors']):
        raise ValueError('Consumed active pass canonical actor changed')
    end = active_match_playback.capture(read, base, client=binding['client'])
    if (end['state'] != 'bound_playback_cursor' or _bound_identity(end['bound_playback']) != _bound_identity(bound)
            or not now['current_time_slice'] <= end['bound_playback']['current_time_slice'] <= end['bound_playback']['buffered_max_time_slice'] < 65536):
        raise ValueError('Active pass playback changed during prefix verification')
    q = lambda address: struct.unpack('<Q', read(address, 8))[0]
    if (q(binding['engine'] + 0x20) != source['match_unique_id']
            or q(binding['client'] + 0x138) != source['match_unique_id']
            or q(binding['engine'] + 0x14E98) != source['cbe']
            or q(q(binding['client'] + 0xF8) + 0x18) != binding['engine']
            or not fixed <= struct.unpack('<I', read(binding['engine'] + 0x154DC, 4))[0] < 65536):
        raise ValueError('Active pass owner changed after prefix verification')
    return {'state': 'verified_fixed_event_selection_under_monotonic_same_match_playback',
            'fixed_time_slice': fixed, 'verified_at_time_slice': end['bound_playback']['current_time_slice']}


def current_pass_network(bridge, session_id, *, _include_locations=False, _return_private=False, _include_pass_attempts=False):
    for attempt in range(2):
        try:
            packet = output = None
            def final_verify():
                if packet is not None:
                    late = _verify_components(fresh, base, save['current_date'], packet)
                    if output is not None:
                        output['prefix_verification'] = late
                        output['same_session_fixed_event_selection_verified'] = True
            with bridge.lock, bridge._read_scope(session_id, final_verify=final_verify):
                process = bridge._current(session_id)
                layout = bridge._player_layout(process)
                world_read, save, _ = bridge._world_state(process, layout)
                epoch = process.pid, process.version, process.executable, layout, bridge.world_identity
                base = layout[0] - players.RVA[0]
                fresh = lambda address, length: bridge._read_memory(process, address, length)
                options = {**({'include_locations': True} if _include_locations else {}),
                           **({'include_pass_attempts': True} if _include_pass_attempts else {})}
                result, packet = _capture_components(fresh, base, save['current_date'], **options)
                world_read.verify()
                final_process = bridge._current(session_id)
                final_layout = bridge._player_layout(final_process)
                end_read, _, _ = bridge._world_state(final_process, final_layout)
                end_read.verify()
                if epoch != (final_process.pid, final_process.version, final_process.executable, final_layout, bridge.world_identity):
                    raise ValueError('Active passing process or career epoch changed')
                public_save = bridge._public_save(save)
                verified = _verify_components(fresh, base, save['current_date'], packet) if packet else None
                attempt_identity = {}
                if packet is not None and _include_pass_attempts:
                    from .active_pass_attempts import actor_manifest
                    attempt_identity = {'pass_attempt_actor_bindings': actor_manifest(packet['source']['events'], packet['actors'])}
                output = {**result, 'save': public_save, 'observed_at': datetime.now(timezone.utc).isoformat(),
                        'atomic': False, 'saved_file_fallback': False, 'prefix_verification': verified,
                        'readset_verified': True,
                        'verification_scope': 'world_epoch_and_fixture_actor_bookends_and_semantic_event_selection',
                        'same_session_fixed_event_selection_verified': verified is not None,
                        'source_id': hashlib.sha256(json.dumps({'fixture': _fixture_identity(packet['fixture']),
                            'match': packet['source']['match_unique_id'], 'cursor': packet['bound']['current_time_slice'],
                            'events': packet['source']['events'], 'projection': result['sides'],
                            **attempt_identity,
                            **({'pass_attempt_policy': packet['source']['pass_attempt_policy']} if _include_pass_attempts else {}),
                            **({'pitch_geometry': packet['source']['pitch_geometry']} if _include_locations else {})}, sort_keys=True).encode()).hexdigest() if packet else None}
                return (output, packet, epoch) if _return_private else output
        except ValueError as error:
            if attempt or str(error) != 'Game state changed during read; retry':
                raise


PASS_CLOCK_SPANS = (
    (0x488a730, bytes.fromhex(
        '89a241393f5500710009407ae0500054201d0013011d00135922009460aa0039772e00b97f62007976660079ea0314aa'
    )),
    (0x1a5490, bytes.fromhex(
        'e00318aae5981b95281340f908014039a800003608ab40391f1d0071c1feff5408000014e89b41b9e99f41b90aab4039'
        '1f00086b00a0497a40d9477ac1fdff5408a34039e94340f91f01296b41fdff54'
    )),
    (0x488b828, bytes.fromhex('00644079c0035fd6')),
    (0x48d8f48, bytes.fromhex(
        'a8a241391f6d0071e8000054290080522821c81a290080520920a1721f01096a01120054826644b9e0030091e10315aa'
        'e30313aa8ac5fe97'
    )),
    (0x488abd4, bytes.fromhex('081b2837e00313aa')),
    (0x488af34, bytes.fromhex('6862407908011d3268620079')),
    (0x493c9b4, bytes.fromhex('88f72837')),
)
