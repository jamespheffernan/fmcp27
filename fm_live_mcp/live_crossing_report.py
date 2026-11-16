"""Crossing reports from one checked scope of the active native career only."""
from datetime import date, datetime, timezone
import secrets

from .match_data_query import capture_epoch
from .match_scope_query import scoped_capture
from .match_crossing_report import report_connection
from .match_dataset import build_connection


def _anchor_identity(f):
    return (f.get('date'), f.get('record_kind'), (f.get('competition') or {}).get('native_id'),
            tuple(((f.get(side) or {}).get('database_index'), (f.get(side) or {}).get('native_id'))
                  for side in ('home_team', 'away_team')), f.get('scores'))


def _refresh_anchor(bridge, session_id, reference, anchor, team_id):
    try:
        return bridge.get_fixture(session_id, reference)['fixture']
    except (ValueError, RuntimeError) as error:
        if not any(word in str(error).lower() for word in ('inventory changed', 'expired fixture', 'expired fixture reference')):
            raise
    args = dict(year=int(anchor['date'][:4]), team_native_id=team_id,
                competition_native_id=(anchor.get('competition') or {}).get('native_id'),
                date_from=anchor['date'], date_to=anchor['date'], max_matches=100,
                record_budget=1000, bucket_budget=4096, selector_prefilter=True)
    matches = []
    for _ in range(20):
        page = bridge.find_fixtures(session_id, **args)
        matches.extend(f for f in page['fixtures'] if _anchor_identity(f) == _anchor_identity(anchor))
        if not page.get('next_cursor'):
            break
        args['cursor'] = page['next_cursor']
    else:
        raise ValueError('Live matchup recheck page budget exceeded')
    if len(matches) != 1:
        raise ValueError('Live matchup is changed, missing or ambiguous after reference expiry')
    return bridge.get_fixture(session_id, matches[0]['fixture_ref'])['fixture']


def _bound_report(value, truncated, path='report'):
    if isinstance(value, dict):
        return {key: _bound_report(item, truncated, f'{path}.{key}') for key, item in value.items()}
    if isinstance(value, list):
        if len(value) > 100:
            truncated.append({'path': path, 'total_rows': len(value), 'returned_rows': 100,
                              'cutoff_ties_may_be_truncated': True})
        return [_bound_report(item, truncated, f'{path}[{i}]') for i, item in enumerate(value[:100])]
    return value


def _enumeration(captured, first, last):
    c = captured['capture']; coverage = c.get('fixture_coverage', {})
    years = {r['year']: r for r in coverage.get('years', [])}
    requested = range(date.fromisoformat(first).year, date.fromisoformat(last).year + 1)
    gaps = [year for year in requested if year not in years or not years[year].get('all_groups_materialized')]
    return {'state': 'complete_resident_groups' if not gaps else 'incomplete_resident_groups',
            'unavailable_or_unmaterialized_years': gaps,
            'unavailable_years': c.get('unavailable_years', []),
            'pages': c.get('pages'), 'completed_windows': c.get('completed_windows'),
            'scope': 'Every selected resident result page was consumed; unloaded native groups remain unknown.'}


class LiveCrossingReports:
    def __init__(self, capture=None, epoch=None):
        self.capture = capture or scoped_capture
        self.epoch = epoch or capture_epoch

    def report(self, bridge, session_id, team_native_id, date_from, date_to,
               competition_native_id=None, fixture_ref=None, venue='all',
               leaders=10, minimum_minutes=0, leader_sort='attempted'):
        for value in (date_from, date_to):
            if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                raise ValueError('Dates must use canonical YYYY-MM-DD')
        if date_from > date_to:
            raise ValueError('Date bounds are reversed')
        if type(team_native_id) is not int or team_native_id <= 0:
            raise ValueError('Select a positive native team ID')
        if venue not in ('all', 'home', 'away', 'matchup'):
            raise ValueError('Unsupported venue selector')
        if type(leaders) is not int or not 1 <= leaders <= 20:
            raise ValueError('leaders must be1–20')
        if type(minimum_minutes) is not int or minimum_minutes < 0:
            raise ValueError('minimum_minutes must be nonnegative')
        if leader_sort not in ('attempted', 'completed', 'accuracy'):
            raise ValueError('Unsupported leader sort')
        epoch = self.epoch(bridge, session_id)
        save = bridge.get_save(session_id)['save']
        if date_to > save['current_date']:
            raise ValueError('Benchmark dates must not exceed the active career date')
        anchor = None
        if fixture_ref is not None:
            anchor = bridge.get_fixture(session_id, fixture_ref)['fixture']
            sides = [s for s in ('home_team', 'away_team')
                     if (anchor.get(s) or {}).get('native_id') == team_native_id]
            if len(sides) != 1:
                raise ValueError('Selected team does not uniquely match live fixture')
            if competition_native_id is None:
                competition_native_id = (anchor.get('competition') or {}).get('native_id')
            if venue == 'matchup':
                venue = 'home' if sides[0] == 'home_team' else 'away'
        elif venue == 'matchup':
            raise ValueError('matchup venue requires a current live fixture_ref')
        if type(competition_native_id) is not int or competition_native_id <= 0:
            raise ValueError('Select a native competition ID or a live fixture with one')
        league = self.capture(bridge, session_id, None, date_from, date_to,
                              competition_native_id, False, True)
        if self.epoch(bridge, session_id) != epoch:
            raise ValueError('Career/load epoch changed during capture')
        if anchor is not None:
            refreshed = _refresh_anchor(bridge, session_id, fixture_ref, anchor, team_native_id)
            if _anchor_identity(refreshed) != _anchor_identity(anchor):
                raise ValueError('Live matchup identity changed during report')
            anchor = refreshed
        db = build_connection(league['capture'], source='active_live_crossing_report',
                              team_totals=league.get('team_totals'),
                              retained_players=league.get('retained_players', []))
        try:
            report = report_connection(db, competition_id=competition_native_id,
                                       team_id=team_native_id, date_from=date_from, date_to=date_to,
                                       venue=venue, leaders=leaders, minimum_minutes=minimum_minutes,
                                       leader_sort=leader_sort)
        finally:
            db.close()
        final_save = bridge.get_save(session_id)['save']
        if self.epoch(bridge, session_id) != epoch:
            raise ValueError('Career/load epoch changed before returning report')
        enumeration = _enumeration(league, date_from, date_to)
        totals = league.get('team_totals', {}).get('records', [])
        available_keys = {row['result_key'] for row in totals}
        missing = [item['native_match_key'] for item in league['capture']['fixtures']
                   if item['native_match_key'] not in available_keys]
        counts = {'selected_fixtures': len(league['capture']['fixtures']),
                  'team_sides': sum(len(row['teams']) for row in totals),
                  'retained_player_rows': len(league.get('retained_players', [])),
                  'missing_backing_keys': missing}
        truncated = []
        report = _bound_report(report, truncated)
        return {'state': 'available' if enumeration['state'] == 'complete_resident_groups' and not missing else 'available_partial',
                'source_kind': 'active_running_session_only', 'capture_id': secrets.token_urlsafe(16),
                'observed_at': datetime.now(timezone.utc).isoformat(),
                'active_save_first': save, 'active_save_last': final_save,
                'matchup': anchor, 'enumeration': enumeration, 'capture_counts': counts,
                'capture_strategy': 'one competition capture with team totals and canonical players on both sides',
                'scope_consistency': 'one shared native scoped capture and verified load epoch',
                'league_player_rankings_scope': 'Every available captured fixture side; missing-side unavailability remains explicit.',
                'atomic': False, 'game_writes': False, 'native_functions_executed': False,
                'disk_capture_fallback': False, 'report': report,
                'response_bounds': {'maximum_rows_per_list': 100, 'truncated_lists': truncated},
                'claim': 'Fresh active-career historical results only. Current fixture anchor is rechecked when supplied; player delivery counts do not establish current tactical roles or delivery flank.'}
