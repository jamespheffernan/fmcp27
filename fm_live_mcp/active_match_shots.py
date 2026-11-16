"""Bounded current GAME_MATCH-owned CBE source; never a display-time verdict.

Caller owns one current-client ReadSet and its final process/career verification.
No historical file, retained HUMAN entry, clock conversion or playback inference.
"""
from collections import Counter
import hashlib
import math
import struct

from . import live_retained_shots as retained, players, fixtures

from .retained_shot_outcomes import outcome_fields, outcome_counts

MAX_EVENTS = 8192
MAX_SHOTS = 1024


def _pointer(value):
    if type(value) is not int or not 4096 <= value < 1 << 48 or value % 8:
        raise ValueError('Invalid active shot source pointer')
    return value


def _word(read, address):
    return players.u64(read(address, 8))


def _type(read, base, address, table):
    if _word(read, address) != base + table:
        raise ValueError('Active shot source native type changed')


def _totals(read, base, address, table):
    _type(read, base, address, table)
    fixture = _pointer(_word(read, address + 0x18))
    teams = []
    for side in range(2):
        pointer = _pointer(_word(read, address + 0x68 + side * 8))
        team = struct.unpack('<I', read(pointer + 0x5c, 4))[0]
        xg = struct.unpack('<f', read(pointer + 0x60, 4))[0]
        shots, target = read(pointer + 0x16f, 2)
        if target > shots or not math.isfinite(xg) or xg < 0:
            raise ValueError('Invalid active shot cumulative totals')
        teams.append({'team_index': team, 'shots': shots,
                      'shots_on_target': target, 'expected_goals': xg})
    return fixture, teams


def _fixture_identity(read, base, pointer):
    table = _word(read, pointer)
    kind = next((kind for kind in ('fixture', 'result')
                 if table == base + fixtures.TYPES[kind][0]), None)
    if kind is None:
        raise ValueError('Unsupported active shot fixture type')
    fixtures.typed(read, base, pointer, kind)
    packed = struct.unpack('<I', read(pointer + 0x4c, 4))[0]
    year, day = packed >> 16, packed & 511
    row = fixtures.record(read, base, pointer, year, day, {})
    fixture = fixtures.detail(read, base, pointer, year, day, row, {}, False)[0]
    return (fixture['date'], fixture['competition']['native_id'],
            *((fixture[side]['database_index'], fixture[side]['native_id'])
              for side in ('home_team', 'away_team')))


def capture_source(read, base, client, engine):
    """Capture strict source bytes; every read participates in caller's ReadSet."""
    for rva, expected in NATIVE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError('Active CBE owner native binding changed')
    retained._verify_native(read, base)
    _type(read, base, client, 0x55fac38)
    _type(read, base, engine, 0x55fa258)
    wrapper = _pointer(_word(read, client + 0xf8))
    if _word(read, wrapper + 0x18) != engine:
        raise ValueError('Active shot client/engine ownership changed')
    match_id = _word(read, engine + 0x20)
    if not match_id or _word(read, client + 0x138) != match_id:
        raise ValueError('Active shot client/engine match identities differ')
    stats = _pointer(_word(read, engine + 0x14e90))
    fixture, totals = _totals(read, base, stats, 0x55fa850)
    client_fixture, client_totals = _totals(read, base, client + 8, 0x56a2380)
    identity = _fixture_identity(read, base, fixture)
    if (_fixture_identity(read, base, client_fixture) != identity
            or [x['team_index'] for x in totals] != [x['team_index'] for x in client_totals]
            or [x['team_index'] for x in totals] != [identity[2][0], identity[3][0]]):
        raise ValueError('Active shot engine/client fixture or sides differ')
    cbe = _word(read, engine + 0x14e98)
    if not cbe:
        return {'state': 'unavailable_engine_cbe_absent', 'shots': None}
    _pointer(cbe)
    events = retained._records(read, cbe + 8, 56, MAX_EVENTS)
    vectors = [retained._records(read, cbe + offset, 48, MAX_SHOTS)
               for offset in (0x20, 0x38)]
    width, length = struct.unpack('<ff', read(cbe + 0x100, 8))
    geometry = ({'half_width_native': width, 'half_length_native': length}
                if all(math.isfinite(v) and v > 0 for v in (width, length)) else None)
    return {'state': 'available_engine_source', 'events': events, 'vectors': vectors,
            'engine_totals': totals, 'client_snapshot_totals': client_totals,
            'pitch_geometry': geometry,
            'source_identity': (client, engine, identity),
            'fixture_identity': identity, 'match_unique_id': match_id,
            'engine_frontier_raw': struct.unpack('<I', read(engine + 0x154dc, 4))[0],
            'native_event_identifier_counter_raw': struct.unpack('<I', read(engine + 0x14ebc, 4))[0]}


def _metric_projection(packet, *, _retain_candidates=False):
    """Release event/count evidence independently of the unchanged strict xG gate."""
    result = {**packet, 'side_coverage': [], 'shots': [], 'own_goal_markers': []}
    candidates = packet['_candidates_by_side']
    marker_candidates = packet['_marker_candidates_by_side']
    for coverage in packet['side_coverage']:
        side = coverage['side_index']
        # Every candidate must still have an exact unique event/side link. Both
        # independent cumulative integer counters must reconcile for this side.
        checks = coverage['checks']
        count_known = (not coverage['link_errors'] and checks['shot_count_matches'] is True
                       and checks['shots_on_target_matches'] is True)
        xg_known = count_known and checks['xg_sum_within_one_float32_ulp'] is True
        rows = [dict(row) for row in candidates[side]]
        markers = [dict(row) for row in marker_candidates[side]]
        confidence = {'event_links_and_side': 'verified' if not coverage['link_errors'] else 'unavailable',
                      'shots': 'verified' if count_known else 'unavailable',
                      'shots_on_target': 'verified' if count_known else 'unavailable',
                      'expected_goals': 'verified' if xg_known else 'unavailable_strict_side_xg_reconciliation'}
        if count_known:
            for row in rows:
                row.update(outcome_fields(row['native_category_code']))
                row['expected_goals'] = row['expected_goals'] if xg_known else None
                row['metric_confidence'] = confidence.copy()
            for row in markers:
                # OwnGoal49 remains an opposite-side marker, never an attempt.
                row['metric_confidence'] = confidence.copy()
                if not xg_known:
                    row['native_expected_goals'] = None
            result['shots'].extend(rows)
            result['own_goal_markers'].extend(markers)
        body = Counter(row['body_part'] or 'unclassified' for row in rows)
        outcomes = outcome_counts(rows) if count_known else None
        result['side_coverage'].append({**coverage,
            'state': 'available' if xg_known else 'available_counts_only' if count_known else 'unavailable_unreconciled_active_side',
            'metric_confidence': confidence,
            'shot_count': len(rows) if count_known else None,
            'shots_on_target': sum(row['native_category_code'] in (1, 4) for row in rows) if count_known else None,
            'own_goal_marker_count': len(markers) if count_known else None,
            'outcome_counts': outcomes,
            'outcome_coverage': ('complete_known_end_states' if not outcomes['unknown'] else 'partial_unmapped_categories') if outcomes is not None else 'unavailable_side',
            'body_part_counts': {key: body[key] if count_known else None for key in ('head', 'feet', 'unclassified')},
            'expected_goals': coverage['native_float32_attempt_xg_sum'] if xg_known else None})
    result['state'] = 'available' if all(row['state'] == 'available' for row in result['side_coverage']) else 'available_partial'
    if not _retain_candidates:
        result.pop('_candidates_by_side', None)
        result.pop('_marker_candidates_by_side', None)
    return result


def _actors(binding, source):
    if binding is None:
        return {}
    if (binding.get('state') != 'validated_native_stored_slots'
            or not source.get('match_unique_id')
            or binding.get('official_match_unique_id') != source['match_unique_id']):
        raise ValueError('Shot actor binding belongs to another official match')
    actors = {}; identities = set()
    for row in binding.get('players', []):
        side, slot = row.get('side_index'), row.get('stored_player_slot')
        person, index = row.get('canonical_person_id'), row.get('person_index_word')
        if (type(side) is not int or side not in (0, 1) or type(slot) is not int or not 0 <= slot < 26
                or type(person) is not int or person <= 0 or type(index) is not int or index < 0
                or (side, slot) in actors or person in identities):
            raise ValueError('Ambiguous canonical shot actor roster binding')
        actors[side, slot] = {key: row.get(key) for key in
            ('side_index', 'stored_player_slot', 'canonical_person_id', 'person_index_word', 'person_name', 'identity_state')}
        identities.add(person)
    return actors


def project(source, *, _retain_candidates=False, actor_binding=None):
    """Reconcile integer counts independently; retain the one-ULP xG threshold."""
    if source['state'] != 'available_engine_source':
        return dict(source, temporal_scope='engine_source_unavailable',
                    displayed_time_statistics_verified=False)
    decoded = retained.decode_attempts(source['vectors'], source['events'],
                                      source['engine_totals'],
                                      pitch_geometry=source['pitch_geometry'], _retain_candidates=True)
    packet = _metric_projection(decoded, _retain_candidates=_retain_candidates)
    actors = _actors(actor_binding, source)
    for row in packet['shots'] + packet['own_goal_markers']:
        row['native_actor_slot'] = row.pop('stored_player_slot')
        actor = actors.get((row['event_side_index'], row['native_actor_slot']))
        row.update(actor=actor, actor_identity_state=('canonical_original_roster_PERSON' if actor else 'unresolved_active_event_roster_join'),
                   temporal_scope='engine_cumulative_may_be_ahead_of_display')
    packet.update(source_kind='resident_GAME_MATCH_owned_CBE',
                  temporal_scope='engine_cumulative_may_be_ahead_of_display',
                  engine_frontier_raw=source['engine_frontier_raw'],
                  match_unique_id=source.get('match_unique_id'),
                  frontier_units=None, displayed_time_statistics_verified=False,
                  displayed_snapshot_shots=None,
                  client_snapshot_prefix=prefix_candidate(source),
                  source_hashes={'events': hashlib.sha256(source['events']).hexdigest(),
                                 'side_vectors': [hashlib.sha256(raw).hexdigest()
                                                  for raw in source['vectors']]},
                  actor_policy='Primary native event side/original roster slot. Canonical names require a same-read-set typed PERSON/player-stats binding; unresolved actors remain null. Own-goal actor is separate from beneficiary/scorer credit; no current tactics slot, on-pitch or reception inference.',
                  clock_policy='Raw native clocks only; no minute/period conversion or sorting',
                  historical_or_file_fallback=False)
    return packet


def inspect(read, base, client, engine):
    """Convenience adapter; caller still verifies its complete readset/epoch."""
    return project(capture_source(read, base, client, engine))


def prefix_candidate(source):
    """Measure stored-order prefix reconciliation; never promote to display time.

    This diagnostic does not prove append order, time domains, uniqueness among
    subsets, or that the client's snapshot is the manager's displayed snapshot.
    """
    prefixes = []
    for raw, totals in zip(source['vectors'], source['client_snapshot_totals']):
        count = totals['shots']
        # Own-goal markers can occupy vector positions; raw count is not shots.
        # Refuse those cases rather than guessing which records to omit.
        if count > len(raw) // 48:
            return {'state': 'unavailable_snapshot_exceeds_engine_vectors',
                    'display_verified': False}
        prefixes.append(raw[:count * 48])
    result = retained.decode_attempts(prefixes, source['events'],
                                      source['client_snapshot_totals'])
    matched = all(row['state'] == 'available' for row in result['side_coverage'])
    return {'state': ('matching_stored_order_candidate_unproved_display_binding' if matched
                      else 'unavailable_snapshot_prefix_mismatch'),
            'display_verified': False,
            'side_checks': result['side_coverage'],
            'rows_released_as_display_snapshot': False}


def compare_observations(previous, current):
    """Stored-order byte stability only; explicitly no temporal/display proof."""
    if previous['state'] != 'available_engine_source' or current['state'] != 'available_engine_source':
        return {'state': 'unavailable_source', 'display_verified': False}
    if previous.get('source_identity') != current.get('source_identity'):
        raise ValueError('Different active shot source identity')
    if [x['team_index'] for x in previous['engine_totals']] != [x['team_index'] for x in current['engine_totals']]:
        raise ValueError('Different active shot sides')
    checks = [new.startswith(old) for old, new in zip(previous['vectors'], current['vectors'])]
    return {'state': 'stored_order_prefix_stable' if all(checks) else 'stored_order_changed',
            'side_prefix_stable': checks, 'display_verified': False,
            'scope': 'Two observations only; no general append law or displayed frontier inference'}


NATIVE_SPANS = ((71855804, b'\x08K\x89R(\x00\xa0r\x7f\x1b\x0c\xb9`\x02\x08\x8b\x874\x11\x94'), (76366712, b'\xc2\x9b\x01\x94\xf6\x03\x00\xaa`\x1e\x02\xf9\x00#\x80R\xe9h\x08\x94\xf5\x03\x00\xaa6\x00\x80R!\x00\x80R\x95\xff\xfe\x97u"\x02\xf9\xa8\x026\xb8'), (76386156, b'\x82fD\xb9\xe0\x03\x00\x91\xe1\x03\x15\xaa\xe3\x03\x13\xaa\x8a\xc5\xfe\x97\x88fD\xb9\x08\x05\x00\x11\x88f\x04\xb9\xe8\xab@9\x88\x03\x004\x80"B\xf9\x08\xa4\xc0\xa9)\x01\x08\xcb)\xfdC\x93\xea\xb6\x8d\xd2j\xdb\xb6\xf2\xaam\xdb\xf2\xca\xb6\xed\xf2*}\n\x9b\xebG@y\xec\x03\n*I}\x8a\n\r\x07\x80R\x8c}\xad\x9b\x8cY\x00\xd1J\x05\x00q\xcb\x00\x00T\rilx\x8c\xe1\x00\xd1\x7f\x01\rkc\xff\xffTI\x05\x00\x11\n\x07\x80R!!*\x9b\xf7\x03\x00\x91\xe2\x03\x00\x91\x14\xf7\xfe\x97'))
