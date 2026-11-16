"""Shot quality for and against a team in explicitly selected live fixtures."""
from collections import defaultdict
from math import fsum

from .live_retained_shots import capture_retained_shot_maps


def _metrics(attempts, threshold):
    xg = [shot['expected_goals'] for shot in attempts]
    non_penalties = [shot['expected_goals'] for shot in attempts if shot.get('is_penalty') is False]
    penalties = [shot['expected_goals'] for shot in attempts if shot.get('is_penalty') is True]
    classified = len(non_penalties) + len(penalties) == len(attempts)
    return {
        'shots': len(attempts), 'expected_goals': fsum(xg),
        'xg_per_shot': fsum(xg) / len(xg) if xg else None,
        'shots_at_or_above_threshold': sum(v >= threshold for v in xg),
        'best_shot_xg': max(xg, default=None),
        'penalties': len(penalties) if classified else None,
        'non_penalty_shots': len(non_penalties) if classified else None,
        'non_penalty_xg': fsum(non_penalties) if classified else None,
        'best_non_penalty_shot_xg': max(non_penalties, default=None) if classified else None,
        'non_penalty_shots_at_or_above_threshold': (
            sum(v >= threshold for v in non_penalties) if classified else None),
    }


OUTCOME_NAMES = ('goal', 'saved', 'blocked', 'hit_woodwork', 'missed_target')


def _group_metrics(shots, threshold):
    outcomes = [shot.get('outcome') for shot in shots]
    known = all(o in OUTCOME_NAMES for o in outcomes)
    return {
        **_metrics(shots, threshold),
        'goals': outcomes.count('goal') if known else None,
        'shots_on_target': sum(o in ('goal', 'saved') for o in outcomes) if known else None,
    }


def _shot_breakdown(attempts, threshold):
    """Keep unknown classifications in the denominator and distinct from real zeros."""
    body = {name: [] for name in ('head', 'feet', 'unclassified')}
    area = {name: [] for name in ('inside_area', 'outside_area', 'outside_area_or_native_fallback', 'unclassified')}
    by_outcome = {name: 0 for name in (*OUTCOME_NAMES, 'unclassified')}
    for shot in attempts:
        part = shot.get('body_part')
        location = shot.get('location_group')
        outcome = shot.get('outcome')
        body[part if part in body else 'unclassified'].append(shot)
        area[location if location in area else 'unclassified'].append(shot)
        by_outcome[outcome if outcome in by_outcome else 'unclassified'] += 1
    return {
        'by_body_part': {name: _group_metrics(shots, threshold) for name, shots in body.items()},
        'by_area': {name: _group_metrics(shots, threshold) for name, shots in area.items()},
        'terminal_outcome_counts': by_outcome,
    }


def _best_chance(shots):
    if not shots:
        return None
    best = max(shots, key=lambda r: r['expected_goals'])
    actor = best.get('actor') or {}
    return {
        'event_id': best['event_id'], 'expected_goals': best['expected_goals'],
        'shooter': actor.get('person_name'), 'shooter_id': actor.get('canonical_person_id'),
        'is_penalty': best.get('is_penalty'), 'body_part': best.get('body_part'),
        'body_part_state': best.get('body_part_state'),
        'outcome': best.get('outcome'), 'official_location': best.get('official_location'),
        'location_group': best.get('location_group'),
        'equally_valued_attempts': sum(s['expected_goals'] == best['expected_goals'] for s in shots),
    }


def summarize_shot_quality(records, team_native_id, perspective, threshold, player_limit):
    fixtures = []
    attempts = []
    by_player = defaultdict(list)
    unavailable_actors = 0
    covered = 0
    seen_matches = set()
    for record in records:
        match = record['fixture']
        identity = record['native_match_key']
        if identity in seen_matches:
            raise ValueError('Selected references identify the same result twice')
        seen_matches.add(identity)
        teams = [match['home_team'], match['away_team']]
        selected = [i for i, team in enumerate(teams) if team['native_id'] == team_native_id]
        if len(selected) != 1:
            raise ValueError('Every selected fixture must contain the requested team exactly once')
        side = selected[0] if perspective == 'for' else 1 - selected[0]
        attacking = teams[side]
        coverage, = [row for row in record['side_coverage'] if row['side_index'] == side]
        if coverage['team_native_id'] != attacking['native_id']:
            raise ValueError('Shot coverage team differs from the selected fixture')
        fixture = {
            'fixture_ref': record['fixture_ref'], 'native_match_key': identity, 'date': match['date'],
            'competition': (match.get('competition') or {}).get('name'),
            'attacking_team': (attacking.get('owner') or {}).get('name'),
            'attacking_team_id': attacking['native_id'],
            'opponent': (teams[1-side].get('owner') or {}).get('name'),
            'state': coverage['state'], 'metrics': None, 'best_chance': None,
            'source_id': record.get('source_id'), 'shot_breakdown': None, 'best_non_penalty_chance': None,
        }
        fixtures.append(fixture)
        if coverage['state'] != 'available':
            continue
        shots = [r for r in record['shots'] if r['side_index'] == side]
        if len(shots) != coverage['shot_count']:
            raise ValueError('Reconciled side count differs from captured attempts')
        covered += 1
        attempts.extend(shots)
        fixture['metrics'] = _metrics(shots, threshold)
        fixture['shot_breakdown'] = _shot_breakdown(shots, threshold)
        fixture['best_chance'] = _best_chance(shots)
        if fixture['metrics']['non_penalty_shots'] is not None:
            fixture['best_non_penalty_chance'] = _best_chance([s for s in shots if s['is_penalty'] is False])
        for shot in shots:
            actor = shot.get('actor') or {}
            person = actor.get('canonical_person_id')
            if person is None or actor.get('canonical_team_id') != attacking['native_id']:
                unavailable_actors += 1
                continue
            by_player[(attacking['native_id'], person)].append(shot)
    players = []
    for (team, person), shots in by_player.items():
        players.append({'team_id': team, 'person_id': person,
                        'name': shots[-1]['actor'].get('person_name'),
                        **_metrics(shots, threshold)})
    players.sort(key=lambda p: (-p['expected_goals'], p['team_id'], p['person_id']))
    return {
        'team_native_id': team_native_id, 'perspective': perspective, 'threshold_xg': threshold,
        'fixtures_selected': len(fixtures), 'fixtures_with_verified_side': covered,
        'coverage': 'unavailable' if not covered else 'complete' if covered == len(fixtures) else 'partial',
        'covered_fixture_totals': _metrics(attempts, threshold) if covered else None,
        'covered_shot_breakdown': _shot_breakdown(attempts, threshold) if covered else None,
        'fixtures': fixtures, 'shooters_by_xg': players[:player_limit],
        'known_shooters_total': len(players) if covered else None,
        'unattributed_attempts_in_covered_fixtures': unavailable_actors if covered else None,
        'players_truncated': len(players) > player_limit,
        'source': 'live_retained_shot_maps', 'saved_file_fallback': False,
        'scope': 'Totals use available selected sides only. Own-goal markers are excluded. '
                 'Non-penalty shots include other set pieces. A penalty can have an unclassified body part. '
                 'Report that uncertainty when comparing it to headers or shots with feet. '
                 'Body part describes contact by the shooter. Delivery type is unknown. The threshold is user-defined.',
    }


def report_shot_quality(bridge, session_id, fixture_refs, team_native_id, perspective,
                        threshold=0.20, player_limit=15, coach_index=None):
    if not 1 <= len(fixture_refs) <= 16:
        raise ValueError('Select between one and 16 result fixtures')
    if perspective not in ('for', 'against'):
        raise ValueError('Perspective must be for or against')
    if not 0 <= threshold <= 1 or not 1 <= player_limit <= 100:
        raise ValueError('Invalid xG threshold or shooter limit')
    captured = capture_retained_shot_maps(bridge, session_id, fixture_refs, coach_index=coach_index)
    records = captured['records']
    first = records[0]['observed_save_first']
    if any(r['observed_save_first'] != first or r['observed_save_last'] != first for r in records):
        raise ValueError('Observed career changed during shot quality report; retry')
    return {**summarize_shot_quality(records, team_native_id, perspective, threshold, player_limit),
            'observed_save': first, 'atomic': False}
