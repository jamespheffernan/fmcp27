"""Selected retained pass attempts with exact individual-counter closure.

CBE categories6..11 are the native converter's engine-event-kind12 family.
Category7 is independently named CBE_END_PASS_COMPLETED. Other family members
are not-completed attempts; their specific interception/out-of-play labels are
unknown. Native sampled paths are exposed as raw geometry, without route or
unit claims.
"""
from collections import Counter
import hashlib
import json
import math
import struct

from .live_retained_passes import MAX_EVENTS, _verify_pass_native, decode_pass_network
from . import pass_field_position, pass_field_zones

PASS_CATEGORIES = frozenset(range(6, 12))
MAX_PATH_POINTS = 4096


def decode_pass_attempts(event_bytes, players, paths=None, *, pitch_geometry=None):
    """Pure complete-source projection; unavailable sides produce no attempts."""
    network = decode_pass_network(event_bytes, players)
    records = [event_bytes[at:at + 56] for at in range(0, len(event_bytes), 56)]
    if any(e[42] in PASS_CATEGORIES and e[40] not in (0, 1) for e in records):
        raise ValueError('Unsupported attempted-pass side')
    if paths is not None:
        if not isinstance(paths, list) or len(paths) != len(records):
            raise ValueError('Native path selection differs from event source')
        for index, (raw, path) in enumerate(zip(records, paths)):
            if (type(path.get('record_index')) is not int or path['record_index'] != index
                    or type(path.get('event_id')) is not int or path['event_id'] != struct.unpack_from('<I', raw, 44)[0]
                    or not isinstance(path.get('raw_xy_pairs'), bytes)
                    or len(path['raw_xy_pairs']) % 8 or len(path['raw_xy_pairs']) > MAX_PATH_POINTS * 8):
                raise ValueError('Native path identity or width differs')
    sides, rows = [], []
    for side in (0, 1):
        source = network['sides'][side]
        own = [p for p in players if p.get('side_index') == side]
        roster = {p['stored_player_slot']: p for p in own}
        candidates = [(i, e) for i, e in enumerate(records)
                      if e[42] in PASS_CATEGORIES and e[40] == side and not e[48] & 8]
        attempted = Counter(e[39] for _, e in candidates)
        completed = Counter(e[39] for _, e in candidates if e[42] == 7)
        missing = sorted(set(attempted) - roster.keys())
        valid = (bool(own) and not missing and source['state'] == 'available'
                 and all(type(p.get('passes_attempted')) is int
                         and p['passes_attempted'] >= p['passes_completed']
                         and attempted[slot] == p['passes_attempted']
                         and completed[slot] == p['passes_completed'] for slot, p in roster.items()))
        state = 'available' if valid else 'unavailable_attempt_counter_reconciliation'
        if source['state'] != 'available':
            state = source['state']
        counters = source.get('player_counters', [])
        for counter in counters:
            slot = counter['stored_player_slot']
            counter['incomplete_native_category_counts'] = ({str(code): sum(e[39] == slot and e[42] == code for _, e in candidates)
                                                            for code in (6, 8, 9, 10, 11)} if valid else None)
            counter['specific_failure_reasons_state'] = 'not_decoded'
        sides.append({'side_index': side, 'state': state,
                      'attempt_count': len(candidates) if valid else None,
                      'completed_count': source['counter_reconciled_completed_passes'] if valid else None,
                      'not_completed_count': sum(e[42] != 7 for _, e in candidates) if valid else None,
                      'excluded_unlabelled_mask8_count': sum(e[42] in PASS_CATEGORIES and e[40] == side and bool(e[48] & 8) for e in records),
                      'captured_player_counter_checks': len(own),
                      'all_captured_player_attempt_counters_match': bool(valid),
                      'all_captured_player_completion_counters_match': source['all_captured_player_counters_match'],
                      'missing_actor_slots': missing,
                      'player_counters': counters})
        if not valid:
            continue
        for index, e in candidates:
            player = roster[e[39]]
            # Only category7 has the official recipient-slot consumer proof.
            recipient = roster.get(e[41]) if e[42] == 7 else None
            xy = struct.unpack_from('<ff', e, 24)
            points = list(struct.iter_unpack('<ff', paths[index]['raw_xy_pairs'])) if paths is not None else None
            if not all(math.isfinite(v) for v in xy) or (points is not None and not all(math.isfinite(v) for point in points for v in point)):
                raise ValueError('Nonfinite native event geometry')
            start, end = (points[0], points[-1]) if points else ((None, None), (None, None))
            rows.append({'record_index': index, 'event_id': struct.unpack_from('<I', e, 44)[0],
                         'side_index': side, 'stored_player_slot': e[39],
                         'person_native_id': player['canonical_person_id'], 'person_name': player['person_name'],
                         'native_category_code': e[42], 'completed': e[42] == 7,
                         'outcome': 'completed' if e[42] == 7 else 'not_completed',
                         'native_outcome_symbol': 'CBE_END_PASS_COMPLETED' if e[42] == 7 else None,
                         'specific_failure_reason': None,
                         'specific_failure_reason_state': 'not_applicable_completed_pass' if e[42] == 7 else 'unmapped_native_incomplete_category',
                         'tactical_cause': None,
                         'recipient_person_native_id': recipient['canonical_person_id'] if recipient else None,
                         'recipient_name': recipient['person_name'] if recipient else None,
                         'recipient_state': 'canonical_completed_pass_recipient' if recipient else 'not_decoded',
                         'native_flags_word': struct.unpack_from('<H', e, 48)[0],
                         'native_event_x': xy[0], 'native_event_y': xy[1],
                         'native_path_points': [{'x': x, 'y': y} for x, y in points] if points is not None else None,
                         'native_path_start_x': start[0], 'native_path_start_y': start[1],
                         'native_path_end_x': end[0], 'native_path_end_y': end[1],
                         'geometry_state': 'raw_native_sampled_path' if points else 'unavailable_native_path',
                         'origin_destination_state': 'not_proved', 'coordinate_units': None,
                         'phase': None, 'displayed_time': None,
                         'field_position': pass_field_position.project_event_location(
                             e, pitch_geometry, expected_event_id=struct.unpack_from('<I', e, 44)[0],
                             expected_side_index=side, expected_player_slot=e[39],
                             path=paths[index] if paths is not None else None) if pitch_geometry is not None else None})
    rows.sort(key=lambda r: r['record_index'])
    _add_decoded_outcomes(rows, event_bytes, players, paths)
    return {'state': 'available' if all(s['state'] == 'available' for s in sides) else 'partial',
            'side_coverage': sides, 'attempts': rows, 'native_event_count': len(records),
            'pass_field_summary': pass_field_zones.aggregate_pass_zones(rows, sides),
            'limits': ['Category7 completed; other native pass-family categories6..11 are not completed after every individual counter closes.',
                       'Mask8 events are throw-ins (every captured one starts on the touchline); the game leaves them '
                       'out of pass attempts and completions, and so do these rows (excluded_unlabelled_mask8_count).',
                       'restart is corner or free_kick from the flags word, else null. key_pass, chance_created and '
                       'assist_marked are markers the game sets on some records only: false does not show a pass was not one.',
                       'Native sampled path order and raw start/end are preserved. The start is where the pass was played from; '
                       'field_position.sampled_path_endpoint is where it ended, with its third, channel and semantics '
                       '(a completed pass: the named recipient taking the ball). Units and normalization are unproved.',
                       'Failed passes carry a decoded outcome (intercepted, blocked, out_of_play, not_completed_other), '
                       'the opponent who won the ball and the displayed minute (fmdb/match_pass_decode.py); the game '
                       'stores no intended recipient for them. Phase of play is not decoded.',
                       'Unavailable sources/sides are unknown, never zero.']}


def _capture_paths(bridge, session_id, source):
    """Copy bounded nested XY vectors from a fresh checked source, without UI."""
    with bridge.lock, bridge._read_scope(session_id):
        process = bridge._current(session_id)
        tables = bridge._player_layout(process)
        read, _, _ = bridge._world_state(process, tables)
        raw = source['events']
        if len(raw) % 56 or len(raw) // 56 > MAX_EVENTS:
            raise ValueError('Unsupported source event width or budget')
        paths = []
        total = 0
        for i in range(0, len(raw), 56):
            start, end, cap = struct.unpack_from('<QQQ', raw, i)
            if not start:
                if end or cap:
                    raise ValueError('Invalid null event path')
                payload = b''
            else:
                if (start < 4096 or start % 8 or end % 8 or cap % 8
                        or not start <= end <= cap or cap - start > MAX_PATH_POINTS * 8):
                    raise ValueError('Invalid native event path vector')
                total += end - start
                if total > 16 * 1024 * 1024:
                    raise ValueError('Native event path byte budget exceeded')
                payload = read(start, end - start) if end > start else b''
                if len(payload) != end - start:
                    raise ValueError('Truncated native event path')
            paths.append({'record_index': i // 56, 'event_id': struct.unpack_from('<I', raw, i + 44)[0],
                          'raw_xy_pairs': payload})
        read.verify()
        bridge._current(session_id)
        return paths


def _unavailable(base, state):
    coverage = []
    for index, label in enumerate(('home_team', 'away_team')):
        team = base['fixture'][label]
        coverage.append({'side_index': index, 'team_native_id': team['native_id'],
                         'team_name': (team.get('owner') or {}).get('name'), 'state': state,
                         'attempt_count': None, 'completed_count': None, 'not_completed_count': None,
                         'captured_player_counter_checks': None,
                         'all_captured_player_attempt_counters_match': False,
                         'all_captured_player_completion_counters_match': False})
    return {**base, 'state': state, 'side_coverage': coverage}


def capture_retained_pass_attempts(bridge, session_id, fixture_ref, *, offset=0, limit=100,
                                   expected_source_id=None, fixture_captures=None, coach_index=None):
    """One exact historical fixture, epoch checked and source-pinned pagination."""
    from .match_data_query import capture_epoch, capture_live
    from .live_retained_shots import capture_source, _validate_team_oracle, _validated_actors
    if not isinstance(fixture_ref, str) or not fixture_ref:
        raise ValueError('Select one exact live result fixture reference')
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('offset must be nonnegative and limit1..500')
    if expected_source_id is not None and (not isinstance(expected_source_id, str) or len(expected_source_id) != 64
                                           or any(c not in '0123456789abcdef' for c in expected_source_id)):
        raise ValueError('Invalid expected source ID')
    if offset and expected_source_id is None:
        raise ValueError('Use the first page source_id for every later page')
    epoch = capture_epoch(bridge, session_id)
    packet = fixture_captures if fixture_captures is not None else capture_live(bridge, session_id, [fixture_ref], include_players=True)
    if packet.get('_live_capture_epoch') != epoch:
        raise ValueError('Frame packet belongs to another native capture epoch')
    items = packet['capture']['fixtures']
    if len(items) != 1 or items[0]['fixture']['fixture_ref'] != fixture_ref:
        raise ValueError('Select exactly one matching frame packet')
    item = items[0]
    fixture, key = item['fixture'], item['native_match_key']
    base = {'fixture': fixture, 'native_match_key': key, 'source_kind': 'active_human_retained_cbe',
            'captured_save': packet['capture']['save'], 'saved_file_fallback': False,
            'atomic': False, 'offset': offset, 'limit': limit, 'total_count': None,
            'next_offset': None, 'attempts': [], 'side_coverage': [], 'source_id': None,
            'pass_field_summary': None}
    totals = [r for r in packet['team_totals']['records'] if r['result_key'] == key]
    if len(totals) != 1:
        return _unavailable(base, 'unavailable_team_oracle')
    _validate_team_oracle(fixture, totals[0]['teams'])
    players = [p for p in packet['retained_players'] if p.get('fixture_key', p.get('native_match_key')) == key]
    if len(_validated_actors(players, totals[0]['teams'])) != len(players):
        return _unavailable(base, 'unavailable_actor_team_identity')
    _verify_pass_native(bridge, session_id)
    _verify_attempt_native(bridge, session_id)
    source = capture_source(bridge, session_id, fixture_ref, key, fixture, coach_index)
    if source['state'] != 'available':
        return _unavailable(base, source['state'])
    paths = _capture_paths(bridge, session_id, source)
    fresh = capture_source(bridge, session_id, fixture_ref, key, fixture, coach_index)
    if (fresh.get('state') != 'available' or fresh['events'] != source['events']
            or fresh.get('pitch_geometry') != source.get('pitch_geometry')
            or capture_epoch(bridge, session_id) != epoch):
        raise ValueError('Retained event source changed during path capture')
    decoded = decode_pass_attempts(source['events'], players, paths, pitch_geometry=source.get('pitch_geometry'))
    for side in decoded['side_coverage']:
        team = fixture['home_team' if side['side_index'] == 0 else 'away_team']
        side.update(team_native_id=team['native_id'], team_name=(team.get('owner') or {}).get('name'))
    digest = hashlib.sha256(struct.pack('<i', key) + source['events'] + json.dumps(players, sort_keys=True).encode())
    digest.update(json.dumps(source.get('pitch_geometry'), sort_keys=True).encode())
    for path in paths:
        digest.update(struct.pack('<I', len(path['raw_xy_pairs'])))
        digest.update(path['raw_xy_pairs'])
    source_id = digest.hexdigest()
    if expected_source_id is not None and source_id != expected_source_id:
        raise ValueError('Retained pass source changed; restart pagination')
    all_rows = decoded.pop('attempts')
    total = len(all_rows) if decoded['state'] == 'available' else None
    selected = all_rows[offset:offset + limit]
    return {**base, **decoded, 'source_id': source_id, 'total_count': total,
            'available_row_count': len(all_rows), 'attempts': selected,
            'next_offset': offset + limit if offset + limit < len(all_rows) else None}


def _verify_attempt_native(bridge, session_id):
    from . import players
    with bridge.lock, bridge._read_scope(session_id):
        process = bridge._current(session_id)
        tables = bridge._player_layout(process)
        read, _, _ = bridge._world_state(process, tables)
        base = tables[0] - players.RVA[0]
        for rva, expected in ATTEMPT_NATIVE_SPANS + pass_field_position.NATIVE_SPANS:
            if read(base + rva, len(expected)) != expected:
                raise ValueError('Native pass-attempt binding changed')
        read.verify()
        bridge._current(session_id)


ATTEMPT_NATIVE_SPANS = (
    (0x48930ac, bytes.fromhex(
        '090400513f71007188050054280380526a5b00f04a110f918b0000104c6969386b090c8b60011fd63f240071c2000054'
        '685b00f008a90f9108c96138001d0013c0035fd648018052fdffff17a8068052fbffff1788068052f9ffff17a8038052'
        '3f38007108019f1a890380523f3400712801881af2ffff173f240071a2020054685b00f008850f91ecffff17e8038052'
        'ebffff17280c00511f190071e200005408117dd3496080d289a0a0f229a0c0f22825c89ae2ffff1708008052e0ffff17'
        'c8068052deffff1708038052dcffff17e8018052daffff1748048052d8ffff17680380523f38007108019f1a49038052'
        'dfffff1728240051091d00126a02805208117dd38ba282526be2a2726825c81a3f11007108318a1ac9ffff1748028052'
        'c7ffff17e8058052c5ffff17880480523f58007108019f1a690480523f540071ccffff17c8048052bdffff17a8048052'
        'bbffff17a8058052b9ffff17e8048052b7ffff17c8028052b5ffff1728068052b3ffff17e8068052b1ffff17'
    )),
    (0x54023c4, bytes.fromhex('05281426333d2424190d51002c0b09242449474d1b2e41243f4b53244f')),
    (0x54023ea, bytes.fromhex('070a0a0b060a090a08')),
    (0x493c4d8, bytes.fromhex('3f750071481e01544b5600b06bb10b918c0000106d7969788c090d8b80011fd6')),
    (0x5405304, bytes.fromhex('2f01')),
    (0x493c9b4, bytes.fromhex('88f7283708008092ea1b40f9491940f9893300b44bb941394b330036')),
    (0x493d034, bytes.fromhex('48a541391f010071e4179f1ae00318aae10319aae20316aae30317aa24090094')),
    (0x493f508, bytes.fromhex(
        '48b041790805001148b001799f0400718101005488b641790805001188b60179330500b468ea42390805001168ea0239'
        '68ee42390805001168ee023905000014330400b468ea42390805001168ea0239'
    )),
    (0x488abd4, bytes.fromhex('081b2837e00313aa')),
    (0x488af34, bytes.fromhex('6862407908011d3268620079')),
    (0x488a768, bytes.fromhex('400140fd600e00fd')),
    (0x488a900, bytes.fromhex('f70b40f9680317cb19fd439329fb41d31f4100f1e8179f1a3f0b00f13681889a78a240a9')),
    (0x488a97c, bytes.fromhex('e97a76f8f80308aa098700f8')),
)


def _add_decoded_outcomes(rows, event_bytes, players, paths):
    """Additive (match lane): fill each row's outcome, ball winner and displayed minute from
    fmdb/match_pass_decode, replacing the earlier 'not decoded' states. Unknown stays unknown."""
    from .fmdb import match_pass_decode as mpd
    roster = {(p.get('side_index'), p.get('stored_player_slot')): p.get('canonical_person_id') for p in players}
    names = {(p.get('side_index'), p.get('stored_player_slot')): p.get('person_name') for p in players}
    points = ({path['record_index']: list(struct.iter_unpack('<ff', path['raw_xy_pairs'])) for path in paths}
              if paths is not None else None)
    decoded = {r['record_index']: r for r in mpd.decode(event_bytes, points, roster)}
    for row in rows:
        d = decoded.get(row['record_index'])
        if d is None:
            continue
        row['displayed_minute'] = d['displayed_minute']
        row['displayed_second'] = d['second']
        row['displayed_time_state'] = 'decoded_elapsed_minute_plus_one'
        # flags word (fmdb/match_pass_decode.py, Flags): corner or free kick, and the game's markers
        row['restart'] = d['restart']
        row['key_pass'], row['chance_created'], row['assist_marked'] = d['key_pass'], d['chance_created'], d['assist_marked']
        if row['completed']:
            continue
        row['specific_failure_reason'] = d['outcome']
        row['specific_failure_reason_state'] = 'decoded_linked_event_and_path'
        row['failure_reason_evidence'] = d['outcome_evidence']
        row['recipient_state'] = 'not_stored_by_game'
        row['recipient_state_evidence'] = ('CBE builder 0x488A5A4 writes the linked actor slot only for completed '
                                           'passes; incomplete passes keep 0xFF')
        won = (d['won_by_side'], d['won_by_slot'])
        row['won_by_person_native_id'] = roster.get(won) if d['won_by_side'] is not None else None
        row['won_by_name'] = names.get(won) if d['won_by_side'] is not None else None
        row['won_by_state'] = ('linked_opponent_event' if d['won_by_side'] is not None else
                               'not_applicable' if d['outcome'] in ('out_of_play', 'not_completed_other') else 'unknown')
        if d['target_x'] is not None:
            row['intended_target_point'] = {'x': d['target_x'], 'y': d['target_y'],
                                            'source': 'engine pass event +0x10 copied by CBE builder 0x488AF2C'}
        if d['end_state'] == 'linked_event_location':
            row['origin_destination_state'] = 'proved_start_is_pass_location_end_is_linked_event_location'
