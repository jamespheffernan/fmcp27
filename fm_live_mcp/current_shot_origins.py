"""Shot-origin zones from the current report's checked playback event prefix."""
import math

from .current_match_report import current_match_report
from .retained_shot_location import LOCATION_NAMES

AREA_NAMES = ('inside_area', 'outside_area', 'outside_area_or_native_fallback', 'unclassified')


def _metrics(rows, total, xg_known):
    values = [row.get('expected_goals') for row in rows]
    if xg_known and any(type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1 for value in values):
        raise ValueError('Verified shot-origin xG contains an unsupported value')
    return {'shots': len(rows),
            'share_of_selected_shots_pct': 100.0 * len(rows) / total if total else None,
            'shots_on_target': sum(row['native_category_code'] in (1, 4) for row in rows),
            'shot_goals': sum(row['native_category_code'] == 1 for row in rows),
            'expected_goals_sum_computed': math.fsum(values) if xg_known else None}


def _side(rows, summary, team):
    confidence = summary.get('metric_confidence') or {}
    counts_known = confidence.get('shots') == 'verified' and confidence.get('shots_on_target') == 'verified'
    xg_known = counts_known and confidence.get('expected_goals') == 'verified'
    result = {'side_index': summary['side_index'], 'team': team,
              'state': 'unavailable_source_count_reconciliation',
              'metric_confidence': dict(confidence), 'shots': None, 'shots_on_target': None,
              'expected_goals_sum_computed': None, 'by_native_zone': None, 'by_area': None,
              'unclassified_shots': None, 'location_coverage': 'unavailable_source'}
    if not counts_known:
        return result
    if (len(rows) != summary['shots']
            or sum(row['native_category_code'] in (1, 4) for row in rows) != summary['shots_on_target']):
        raise ValueError('Shot-origin rows differ from the checked playback integer counts')
    zones = {name: [] for name in LOCATION_NAMES}
    areas = {name: [] for name in AREA_NAMES}
    unknown = []
    for row in rows:
        if row.get('statistical_shot') is False or row.get('kind') == 'own_goal_marker' or row['native_category_code'] == 49:
            raise ValueError('Own-goal marker cannot enter a statistical shot-origin zone')
        index = row.get('native_location_bin')
        if row.get('location_state') != 'native_renderer_predicate' or index is None:
            unknown.append(row); areas['unclassified'].append(row)
            continue
        if type(index) is not int or not 0 <= index < len(LOCATION_NAMES) or row.get('official_location') != LOCATION_NAMES[index]:
            raise ValueError('Shot-origin native bin and official name disagree')
        area = 'inside_area' if index < 6 else 'outside_area' if index < 12 else 'outside_area_or_native_fallback'
        if row.get('location_group') != area:
            raise ValueError('Shot-origin native zone and area disagree')
        zones[LOCATION_NAMES[index]].append(row); areas[area].append(row)
    total = len(rows)
    return {**result, 'state': 'available_partial_locations' if unknown else 'available',
            **_metrics(rows, total, xg_known),
            'by_native_zone': {name: _metrics(group, total, xg_known) for name, group in zones.items()},
            'by_area': {name: _metrics(group, total, xg_known) for name, group in areas.items()},
            'unclassified_shots': len(unknown),
            'location_coverage': 'partial' if unknown else 'complete_for_selected_statistical_attempts',
            'zone_count_policy': 'Counts cover assigned native bins; unclassified shots remain separate and may belong to any zone'}


def project_shot_origins(report):
    """Pure grouping of one report; counters from other temporal scopes are unused."""
    chance = report.get('chance_breakdown') or {}
    fixture = report.get('fixture')
    result = {'state': 'unavailable', 'reason': chance.get('reason') or report.get('reason'),
              'fixture': fixture, 'current_time_slice': chance.get('current_time_slice'),
              'temporal_scope': chance.get('temporal_scope'), 'sides': None, 'periods': [],
              'boundary_policy': chance.get('boundary_policy'), 'displayed_minute': None,
              'displayed_pixels_verified': False, 'human_left_right': None, 'physical_units': None,
              'own_goal_policy': 'Own-goal markers are excluded from all statistical shot-origin groups',
              'fallback_policy': 'Native bin12 includes boundary gaps; it is not a definite outside-area or long-range classification',
              'xg_policy': 'A group xG sum is available only when the same side passes the unchanged strict native aggregate xG reconciliation'}
    if not fixture or chance.get('state') not in ('available', 'available_partial') or chance.get('shots') is None:
        return result
    if (chance.get('native_event_clock_domain_verified') is not True
            or chance.get('native_ended_exclusive_cutoff_verified') is not True):
        return {**result, 'reason': 'unavailable_verified_playback_event_cutoff'}
    cursor = chance.get('current_time_slice')
    if type(cursor) is not int or not 0 <= cursor < 65536:
        raise ValueError('Unsupported shot-origin playback cursor')
    rows = chance['shots']
    if any(not 0 <= row['native_clock_start_raw'] <= row['native_clock_end_raw'] < cursor for row in rows):
        raise ValueError('Shot-origin row is outside the checked completed-event prefix')
    identities = [row['event_id'] for row in rows]
    if len(set(identities)) != len(identities) or any(row.get('side_index') not in (0, 1) for row in rows):
        raise ValueError('Shot-origin event identity or side is ambiguous')
    summaries = chance.get('sides')
    if not isinstance(summaries, list) or [row.get('side_index') for row in summaries] != [0, 1]:
        raise ValueError('Shot-origin side summaries differ from ordered fixture')
    teams = [fixture['home_team'], fixture['away_team']]
    sides = [_side([row for row in rows if row['side_index'] == side], summaries[side], teams[side]) for side in (0, 1)]
    periods = []
    period_names = [period.get('period') for period in chance.get('periods') or []]
    if len(set(period_names)) != len(period_names):
        raise ValueError('Duplicate shot-origin period intervals')
    for period in chance.get('periods') or []:
        name = period['period']
        if name not in ('FirstHalf', 'SecondHalf'):
            raise ValueError('Unsupported checked shot-origin period')
        periods.append({'period': name, 'start_tick': period['start_tick'], 'end_tick': period['end_tick'],
                        'sides': [_side([row for row in rows if row['side_index'] == side and row.get('period') == name],
                                         period['sides'][side], teams[side]) for side in (0, 1)]})
    return {**result, 'state': 'available' if all(side['state'] == 'available' for side in sides) else 'available_partial',
            'reason': None, 'sides': sides, 'periods': periods,
            'period_assignment_unknown_event_ids': list(chance.get('period_assignment_unknown') or []),
            'native_event_clock_domain_verified': chance.get('native_event_clock_domain_verified', False),
            'native_ended_exclusive_cutoff_verified': chance.get('native_ended_exclusive_cutoff_verified', False),
            'playback_observation_policy': (report.get('playback') or {}).get('observation_policy'),
            'cursor_still_current_verified': (report.get('playback') or {}).get('cursor_still_current_verified', False),
            'replay_exclusion_verified': chance.get('replay_exclusion_verified', False),
            'scope': 'Completed statistical attempts ending strictly before the checked playback cursor; native shot-origin predicates only',
            'classification_policy': 'Native Left/Right zone names retain native direction labels; they do not establish the viewer left or right'}


def current_shot_origins(bridge, session_id):
    report = current_match_report(bridge, session_id, include_tactics=False, include_shot_events=True)
    result = project_shot_origins(report)
    for key in ('save', 'observed_at', 'saved_file_fallback', 'snapshot_consistency'):
        if key in report:
            result[key] = report[key]
    return result
