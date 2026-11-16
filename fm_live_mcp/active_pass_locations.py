"""Immutable, bounded pages of completed native pass-map event locations."""
from collections import OrderedDict
from copy import deepcopy
import secrets
import struct
import time

from . import active_pass_network, pass_field_position, players

_CACHE = OrderedDict()
TTL_SECONDS = 120
MAX_SNAPSHOTS = 4


def project(packet, network):
    roster = active_pass_network._actor_map(packet['actors'])
    valid_sides = {s['side_index'] for s in network['sides'] if s['state'] == 'available'}
    rows = []
    for event in packet['source']['events']:
        if event['category'] != 7 or event['flags_word'] & 8 or event['side_index'] not in valid_sides:
            continue
        side = event['side_index']
        sender, recipient = (roster[side, event[k]] for k in ('stored_player_slot', 'recipient_slot'))
        raw = bytearray(56)
        raw[24:32] = bytes.fromhex(event['location_xy_hex'])
        raw[39:43] = bytes((event['stored_player_slot'], side, event['recipient_slot'], 7))
        struct.pack_into('<I', raw, 44, event['event_id'])
        struct.pack_into('<H', raw, 48, event['flags_word'])
        location = pass_field_position.project_event_location(bytes(raw), packet['source']['pitch_geometry'],
            expected_event_id=event['event_id'], expected_side_index=side,
            expected_player_slot=event['stored_player_slot'])
        team = network['fixture']['home_team' if side == 0 else 'away_team']
        rows.append({'event_id': event['event_id'], 'side_index': side, 'team_native_id': team['native_id'],
            'from_person_native_id': sender['canonical_person_id'], 'from_name': sender['person_name'],
            'to_person_native_id': recipient['canonical_person_id'], 'to_name': recipient['person_name'],
            'stored_player_slot': event['stored_player_slot'], 'recipient_slot': event['recipient_slot'],
            'native_start_time_slice': event['start'], 'native_end_time_slice': event['end'],
            'native_category_code': 7, 'native_flags_word': event['flags_word'],
            **{k: location[k] for k in ('native_pass_map_location', 'attacked_goal_positive_native_y',
                'attack_relative_longitudinal_coordinate', 'absolute_lateral_centerline_distance',
                'inside_native_pitch_extents', 'analytical_pitch_third', 'analytical_lateral_channel')}})
    return sorted(rows, key=lambda r: r['event_id'])


def _verify_page(bridge, session_id, snapshot):
    """Revalidate original prefix; never recapture new rows or advance the cutoff."""
    packet = snapshot['packet']
    def final_verify():
        verified = active_pass_network._verify_components(read, base, save['current_date'], packet)
        if verified['verified_at_time_slice'] < snapshot['last_cursor']:
            raise ValueError('Active pass event cursor expired after playback rewind')
        snapshot['last_cursor'] = verified['verified_at_time_slice']
    with bridge.lock, bridge._read_scope(session_id, final_verify=final_verify):
        process = bridge._current(session_id)
        layout = bridge._player_layout(process)
        readset, save, _ = bridge._world_state(process, layout)
        if (process.pid, process.version, process.executable, layout, bridge.world_identity) != snapshot['epoch']:
            raise ValueError('Active pass event cursor expired after process or career change')
        base = layout[0] - players.RVA[0]
        read = lambda a, n: bridge._read_memory(process, a, n)
        verified = active_pass_network._verify_components(read, base, save['current_date'], packet)
        if verified['verified_at_time_slice'] < snapshot['last_cursor']:
            raise ValueError('Active pass event cursor expired after playback rewind')
        readset.verify()
        end = bridge._current(session_id)
        end_layout = bridge._player_layout(end)
        end_read, _, _ = bridge._world_state(end, end_layout)
        end_read.verify()
        if (end.pid, end.version, end.executable, end_layout, bridge.world_identity) != snapshot['epoch']:
            raise ValueError('Active pass event cursor epoch changed during page read')
        snapshot['last_cursor'] = verified['verified_at_time_slice']


def current_pass_events(bridge, session_id, *, team_native_id=None, from_person_native_id=None,
                        to_person_native_id=None, limit=50, cursor=None, pass_outcome='completed'):
    if pass_outcome not in ('completed', 'not_completed', 'all'):
        raise ValueError('pass_outcome must be completed, not_completed or all')
    if pass_outcome != 'completed':
        from .active_pass_attempts import current_pass_attempt_events
        return current_pass_attempt_events(bridge, session_id, pass_outcome=pass_outcome,
            team_native_id=team_native_id, from_person_native_id=from_person_native_id,
            to_person_native_id=to_person_native_id, limit=limit, cursor=cursor)
    for value in (team_native_id, from_person_native_id, to_person_native_id):
        if value is not None and (type(value) is not int or value <= 0):
            raise ValueError('Positive canonical TEAM/PERSON IDs required')
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Active pass event limit must be 1..100')
    selectors = (team_native_id, from_person_native_id, to_person_native_id, limit)
    now = time.monotonic()
    with bridge.lock:
        for key in list(_CACHE):
            if _CACHE[key]['expires'] < now:
                del _CACHE[key]
        if cursor is not None:
            if not isinstance(cursor, str) or cursor not in _CACHE:
                raise ValueError('Active pass event cursor expired or invalid')
            snapshot = _CACHE[cursor]
            if snapshot['session_id'] != session_id or snapshot['selectors'] != selectors:
                raise ValueError('Active pass event cursor belongs to another session or selectors')
            _verify_page(bridge, session_id, snapshot)
            offset = snapshot['next_offset']
        else:
            network, packet, epoch = active_pass_network.current_pass_network(bridge, session_id,
                _include_locations=True, _return_private=True)
            if packet is None:
                return {**network, 'events': None, 'next_cursor': None, 'total_selected_events': None}
            if team_native_id is not None and team_native_id not in {network['fixture'][k]['native_id'] for k in ('home_team', 'away_team')}:
                raise ValueError('Selected team does not participate in this checked match')
            rows = [r for r in project(packet, network)
                    if (team_native_id is None or r['team_native_id'] == team_native_id)
                    and (from_person_native_id is None or r['from_person_native_id'] == from_person_native_id)
                    and (to_person_native_id is None or r['to_person_native_id'] == to_person_native_id)]
            metadata = {k: v for k, v in network.items() if k != 'sides'}
            metadata['side_coverage'] = [{k: s[k] for k in ('side_index', 'team', 'state', 'unresolved_events',
                'source_completed_pass_event_count', 'named_completed_pass_event_count')} for s in network['sides']]
            selected_sides = [s for s in network['sides'] if team_native_id is None or s['team']['native_id'] == team_native_id]
            metadata['selection_coverage_state'] = ('complete_named_selected_sides' if all(s['state'] == 'available' for s in selected_sides)
                else 'partial_unknown_actor_coverage')
            if team_native_id is not None and selected_sides[0]['state'] != 'available':
                return {**metadata, 'state': 'unavailable_actor_coverage', 'events': None,
                        'total_selected_events': None, 'next_cursor': None}
            metadata['location_semantics'] = pass_field_position.LOCATION_SEMANTICS
            metadata['analytical_bins'] = 'Equal longitudinal thirds; central width third versus outer thirds.'
            metadata['coordinates'] = 'native pass-map event point only: where the pass was played from'
            metadata['reception_location_state'] = ('not_read_at_a_playback_cutoff; after the match '
                                                    'fm_get_retained_pass_events gives each completed pass its reception point')
            metadata['coordinate_units'] = metadata['human_left_right'] = metadata['reception_location'] = metadata['trajectory'] = None
            metadata['selectors'] = dict(zip(('team_native_id', 'from_person_native_id', 'to_person_native_id'), selectors[:3]))
            snapshot = {'rows': rows, 'metadata': metadata, 'packet': packet, 'epoch': epoch,
                'session_id': session_id, 'selectors': selectors, 'expires': now+TTL_SECONDS,
                'last_cursor': network['prefix_verification']['verified_at_time_slice']}
            offset = 0
        end = min(offset+limit, len(snapshot['rows']))
        token = None
        if end < len(snapshot['rows']):
            token = secrets.token_urlsafe(24)
            _CACHE[token] = {**snapshot, 'next_offset': end}
            while len(_CACHE) > MAX_SNAPSHOTS:
                _CACHE.popitem(last=False)
        return deepcopy({**snapshot['metadata'], 'events': snapshot['rows'][offset:end],
            'offset': offset, 'total_selected_events': len(snapshot['rows']), 'next_cursor': token,
            'capture_id': snapshot['metadata']['source_id'], 'captured_observed_at': snapshot['metadata']['observed_at'],
            'pagination_policy': 'Immutable captured event rows; original prefix reverified, 120s expiry, original session/epoch/match and monotonic playback required.'})
