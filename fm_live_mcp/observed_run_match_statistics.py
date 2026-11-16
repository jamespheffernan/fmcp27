"""Optional same-cursor shots and official score for an observed host prefix.

Player rows are derived from completed attempts, never engine-frontier PLAYER
counters. Score incidents are inclusive at the cursor; attempts end strictly
before it. Those two independent boundaries are intentionally not reconciled.
"""
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

from . import active_match_people, active_match_score, active_match_shots, active_match_shot_timeline, players
from . import active_match_half_boundaries, live_retained_shots, retained_shot_outcomes
from .current_match_report import ReportReadSet

POLICY_ID = 'observed_fixed_cursor_attempts_and_official_score_v1'


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def policy():
    modules = (active_match_people, active_match_score, active_match_shots,
               active_match_shot_timeline, active_match_half_boundaries,
               live_retained_shots, retained_shot_outcomes)
    return {'policy_id': POLICY_ID, 'source_policy_digest': hashlib.sha256(_json([
        (module.__name__, hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest())
        for module in modules]).encode()).hexdigest()}


def unavailable(reason):
    return {'state': 'unavailable', 'reason': reason}


def actor_statistics(chances):
    """Counts over observed attempts; unknown canonical identity stays null."""
    groups = defaultdict(list)
    for row in chances.get('shots') or []:
        groups[row['event_side_index'], row['native_actor_slot']].append(row)
    output = []
    for (side, slot), rows in sorted(groups.items()):
        actors = [row.get('actor') for row in rows]
        actor = actors[0]
        if any(value != actor for value in actors):
            raise ValueError('Shot actor identity changed within one observed slot')
        output.append({'side_index': side, 'native_actor_slot': slot,
            'canonical_person_id': actor.get('canonical_person_id') if actor else None,
            'person_index_word': actor.get('person_index_word') if actor else None,
            'person_name': actor.get('person_name') if actor else None,
            'identity_state': 'canonical_original_roster_PERSON' if actor else 'unresolved',
            'shots': len(rows),
            'shots_on_target': sum(row['native_category_code'] in (1, 4) for row in rows),
            'shot_goals': sum(row['outcome'] == 'goal' for row in rows),
            'expected_goals_sum_computed': (math.fsum(row['expected_goals'] for row in rows)
                if all(row['expected_goals'] is not None for row in rows) else None),
            'counter_scope': 'derived_completed_attempts_strictly_before_fixed_cursor',
            'native_PLAYER_counter_read': False})
    return output


def project(source, bound, split, actors, score):
    """Pure projection after the existing native owner/cursor guards passed."""
    chances = active_match_shot_timeline.project(
        source, bound, period_split=split, actor_binding=actors)
    if chances['state'] not in ('available', 'available_partial'):
        return unavailable(chances.get('reason', 'attempt_projection_unavailable'))
    return {'state': 'available' if chances['state'] == 'available' else 'partial',
        'schema_version': 1, 'policy': policy(),
        'official_match_unique_id': bound['official_match_unique_id'],
        'fixed_time_slice': bound['current_time_slice'],
        'shots': chances, 'score': score,
        'pitch_geometry': source.get('pitch_geometry'),
        'player_shot_statistics': actor_statistics(chances),
        'native_player_statistics': unavailable('engine_frontier_counters_not_bound_to_recorded_prefix'),
        'score_attempt_boundary_policy': 'official_score_time<=cursor; attempt_start<=end<cursor; equality_can_differ',
        'rendered_screen_verified': False, 'replay_exclusion_verified': False,
        'full_match_completeness_verified': False}


def capture(read, base, packet, split):
    """Strict optional sample. A moving source withholds only this new scope."""
    checked = ReportReadSet(read)
    binding, bound = packet['binding'], packet['bound']
    try:
        active_match_shot_timeline._verify_bound(
            checked, base, binding['client'], binding['engine'], bound)
        if players.u64(checked(binding['engine'] + 0x14E98, 8)) != packet['source']['cbe']:
            raise ValueError('Shot and passing CBE owners differ')
        source = active_match_shots.capture_source(
            checked, base, binding['client'], binding['engine'])
        if source['state'] != 'available_engine_source':
            return unavailable(source['state']), None
        expected = packet['fixture']
        identity = (expected['date'], expected['competition']['native_id'],
            *((expected[key]['database_index'], expected[key]['native_id'])
              for key in ('home_team', 'away_team')))
        if source['fixture_identity'] != identity:
            raise ValueError('Shot fixture differs from recorded fixture')
        score = active_match_score.capture(checked, base, bound_playback=bound,
            trusted_first_half_boundary=split.get('first_half_boundary'))
        actors = active_match_people.inspect_actor_bindings(
            checked, base, binding['engine'],
            expected_match_unique_id=bound['official_match_unique_id'])
        if actors != packet['actors']:
            raise ValueError('Shot and passing original-roster actor bindings differ')
        document = project(source, bound, split, actors, score)
        checked.verify()
        return document, checked
    except ValueError as exc:
        return unavailable(str(exc)), None


def finish(document, proof):
    """Recheck optional bytes after the base recorder's prefix verification."""
    if proof is None:
        return document
    try:
        proof.verify()
    except ValueError as exc:
        return unavailable('optional_match_statistics_changed: ' + str(exc))
    return document


def validate(document, packet):
    if document.get('state') == 'unavailable' or not document:
        return
    if (document.get('state') not in ('available', 'partial')
            or document.get('schema_version') != 1 or document.get('policy') != policy()
            or document.get('fixture') != packet['fixture']
            or document.get('source_incarnation_id') != packet['incarnation_id']
            or document.get('fixed_time_slice') != packet['cursor']
            or document.get('official_match_unique_id') != packet['fixture']['official_match_unique_id']):
        raise ValueError('Observed match statistics source binding differs')
    chances = document['shots']
    if chances.get('state') not in ('available', 'available_partial'):
        raise ValueError('Unavailable attempts cannot authorize observed statistics')
    if chances.get('official_match_unique_id') != document['official_match_unique_id']:
        raise ValueError('Observed attempts belong to another match')
    actors = {(r['side_index'], r['stored_player_slot']): r for r in packet['actors']}
    seen = set()
    for row in (chances.get('shots') or []) + (chances.get('own_goal_markers') or []):
        key = row['event_id']
        if key in seen or row['side_index'] not in (0, 1):
            raise ValueError('Ambiguous observed shot identity or side')
        seen.add(key)
        start, end = row['native_clock_start_raw'], row['native_clock_end_raw']
        if not 0 <= start <= end < packet['cursor']:
            raise ValueError('Observed shot exceeds fixed cursor')
        actor = row.get('actor')
        if actor is not None:
            old = actors.get((row['event_side_index'], row['native_actor_slot']))
            if old is None or any(actor.get(k) != old.get(k)
                                  for k in ('canonical_person_id', 'person_index_word', 'person_name')):
                raise ValueError('Observed shot canonical actor differs')
    for side in chances['sides']:
        rows = [r for r in chances['shots'] if r['side_index'] == side['side_index']]
        if side['shots'] is not None and side['shots'] != len(rows):
            raise ValueError('Observed side count differs from recorded attempts')
    if actor_statistics(chances) != document['player_shot_statistics']:
        raise ValueError('Observed actor statistics differ from recorded attempts')
    score = document['score']
    if (score.get('official_match_unique_id') != document['official_match_unique_id']
            or score.get('current_time_slice') != packet['cursor']):
        raise ValueError('Observed official score belongs to another cursor or match')
    current = score.get('current_score') or {}
    if current.get('state') == 'available' and (
            current.get('at_time_slice') != packet['cursor']
            or any(type(current.get(k)) is not int or not 0 <= current[k] <= 255
                   for k in ('home_goals', 'away_goals'))):
        raise ValueError('Invalid observed official score')
