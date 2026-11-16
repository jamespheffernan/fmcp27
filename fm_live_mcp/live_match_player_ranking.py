"""Exact, source-bound rankings of named additive retained match counters."""
from collections import Counter, OrderedDict, defaultdict
from datetime import date, datetime, timezone
from fractions import Fraction
import secrets
import threading
import time

from .match_data_query import capture_epoch, capture_live

METRICS = (
    'dribbles_made', 'progressive_passes', 'passes_attempted', 'passes_completed', 'key_passes',
    'open_play_key_passes', 'chances_created', 'shots', 'shots_on_target',
    'goals', 'assists', 'crosses_attempted', 'crosses_completed',
    'open_play_crosses_attempted', 'open_play_crosses_completed',
    'tackles_attempted', 'tackles_completed', 'interceptions', 'clearances',
    'aerial_duels_attempted', 'aerial_duels_completed', 'possession_won',
    'possession_lost', 'pressures_attempted', 'pressures_completed', 'fouls_committed',
    'yellow_cards_received', 'red_cards_received',
)
NORMALIZATIONS = ('total', 'per90', 'per_100_pass_attempts', 'per_100_pressure_attempts')

def metric_normalizations(name):
    return NORMALIZATIONS[:3] if name == 'progressive_passes' else (NORMALIZATIONS[0], NORMALIZATIONS[1], NORMALIZATIONS[3]) if name == 'pressures_completed' else NORMALIZATIONS[:2]
PAGE_SIZE = 100
MAX_FIXTURES = 512


def metric_catalog():
    from .saved_match_player_dribbling import dribbling_field_registry
    from .saved_match_player_progression import progression_field_registry
    from .saved_match_player_recoveries import recovery_field_registry
    return {'metrics': {name: {
        'unit': 'additive observed stored count',
        'normalizations': list(metric_normalizations(name)),
        'scope': ('FM-defined progressive passes; no proved distance/angle threshold, carries, final-third entry or role split'
                  if name == 'progressive_passes' else 'Named individual match counter; no played-role or current-roster interpretation'),
        'provenance': dribbling_field_registry()[name] if name == 'dribbles_made' else progression_field_registry()[name] if name == 'progressive_passes' else recovery_field_registry()[name] if name in ('pressures_attempted', 'pressures_completed') else {'source': 'existing named retained-player field catalog'},
    } for name in METRICS},
        'defaults': {'total_minimum_minutes': 0, 'normalized_minimum_minutes': 450},
        'per_100_pass_attempts': '100 * sum(progressive_passes) / sum(passes_attempted); activity ratio, not accuracy or success percentage',
        'per_100_pressure_attempts': '100 * sum(pressures_completed) / sum(pressures_attempted); statistical pressure completion, not possession regains or causal press effectiveness',
        'grouping': 'canonical PERSON ID plus historical fixture TEAM native ID and database index; no current-club join',
        'limits': {'maximum_selected_fixtures': MAX_FIXTURES, 'maximum_rows_per_page': PAGE_SIZE}}


def _valid_count(value):
    return type(value) is int and value >= 0


def rank_capture(captured, metric, normalization, minimum_minutes, team_native_id=None):
    """Pure ranking over one checked capture; never drops zero-minute actions."""
    if metric not in METRICS or normalization not in metric_normalizations(metric):
        raise ValueError('Unsupported metric normalization')
    fixtures = {}
    fixture_receipts = {}
    duplicate_fixtures = 0
    duplicate_players = 0
    team_sides = defaultdict(set)
    team_names = defaultdict(set)
    unresolved_fixture_sides = []
    for item in captured['capture'].get('fixtures', []):
        key = item.get('native_match_key')
        if key in fixtures:
            receipt = (item['fixture'], item.get('raw_sha256'))
            if fixture_receipts[key] != receipt:
                raise ValueError('Conflicting duplicate native fixture key cannot authorize player grouping')
            duplicate_fixtures += 1
            continue
        fixture_receipts[key] = (item['fixture'], item.get('raw_sha256'))
        fixtures[key] = item['fixture']
        for side, field in enumerate(('home_team', 'away_team')):
            team = item['fixture'].get(field) or {}
            identity = (team.get('native_id'), team.get('database_index'))
            if not all(_valid_count(v) for v in identity) or identity[0] == 0:
                unresolved_fixture_sides.append({'native_match_key': key, 'side_index': side})
                continue
            if team_native_id is not None and identity[0] != team_native_id:
                continue
            team_sides[identity].add((key, side))
            name = (team.get('owner') or {}).get('short_name') or (team.get('owner') or {}).get('name')
            if name:
                team_names[identity].add(name)
    groups = defaultdict(list)
    available_sides = set()
    unidentified = []
    seen = {}
    row_count = 0
    for row in captured.get('retained_players', []):
        key, side = row.get('fixture_key'), row.get('side_index')
        if key not in fixtures or type(side) is not int or side not in (0, 1):
            raise ValueError('Player row lacks an unambiguous selected fixture side')
        fixture = fixtures[key]
        team = fixture.get(('home_team', 'away_team')[side]) or {}
        tid, index = team.get('native_id'), team.get('database_index')
        if team_native_id is not None and tid != team_native_id:
            continue
        row_count += 1
        available_sides.add((key, side))
        source_identity = (key, side, row.get('person_index_word'))
        if source_identity in seen:
            if seen[source_identity] != row:
                raise ValueError('Conflicting duplicate stored player identity in a fixture side')
            duplicate_players += 1
            row_count -= 1
            continue
        seen[source_identity] = row
        person = row.get('canonical_person_id')
        if not all(_valid_count(v) for v in (person, tid, index)) or person == 0 or tid == 0:
            unidentified.append({'native_match_key': key, 'side_index': side,
                                 'person_index_word': row.get('person_index_word'), 'reason': 'unresolved_person_or_historical_team_identity'})
            continue
        if row.get('team_index_word') != index:
            raise ValueError('Retained player TEAM word differs from canonical fixture side')
        groups[(person, tid, index)].append(row)
    coverage = []
    for identity, sides in sorted(team_sides.items()):
        coverage.append({'team_native_id': identity[0], 'team_database_index': identity[1],
                         'names': sorted(team_names[identity])[:8], 'selected_fixture_sides': len(sides),
                         'available_player_sides': len(sides & available_sides),
                         'missing_player_sides': len(sides - available_sides)})
    coverage_by_team = {(r['team_native_id'], r['team_database_index']): r for r in coverage}
    classifications = Counter()
    excluded = []
    uncertain_groups = 0
    qualified = []
    for (person, tid, index), rows in groups.items():
        reasons = []
        missing_metric = sum(not _valid_count(r.get(metric)) for r in rows)
        known_minutes = 0
        unknown_minutes = 0
        unused = 0
        for row in rows:
            minute = row.get('minutes')
            if _valid_count(minute):
                known_minutes += minute
            elif minute is None and row.get('appearance_kind') == 'unused_substitute':
                unused += 1
            else:
                unknown_minutes += 1
        if missing_metric:
            reasons.append('missing_selected_metric')
        if coverage_by_team[(tid, index)]['missing_player_sides']:
            reasons.append('historical_team_side_coverage_missing')
        if known_minutes < minimum_minutes:
            reasons.append('unknown_minimum_minutes_eligibility' if unknown_minutes else 'below_minimum_minutes')
        if unknown_minutes and normalization == 'per90':
            reasons.append('unknown_active_minutes')
        denominator = None
        if normalization == 'per90':
            denominator = known_minutes
            if not denominator and not unknown_minutes:
                reasons.append('zero_minutes_denominator')
        elif normalization == 'per_100_pass_attempts':
            if any(not _valid_count(r.get('passes_attempted')) for r in rows):
                reasons.append('missing_pass_attempts_denominator')
            else:
                denominator = sum(r['passes_attempted'] for r in rows)
                if not denominator:
                    reasons.append('zero_pass_attempts_denominator')
        elif normalization == 'per_100_pressure_attempts':
            if any(not _valid_count(r.get('pressures_attempted')) for r in rows):
                reasons.append('missing_pressure_attempts_denominator')
            elif any(_valid_count(r.get(metric)) and r[metric] > r['pressures_attempted'] for r in rows):
                reasons.append('pressure_completions_exceed_attempts')
            else:
                denominator = sum(r['pressures_attempted'] for r in rows)
                if not denominator:
                    reasons.append('zero_pressure_attempts_denominator')
        # A decisive known exclusion cannot make the ranking uncertain because of unused fields.
        complete_team = not coverage_by_team[(tid,index)]['missing_player_sides']
        if complete_team and not unknown_minutes and known_minutes < minimum_minutes:
            reasons = ['below_minimum_minutes']
        elif complete_team and normalization == 'per90' and not unknown_minutes and known_minutes == 0:
            reasons = ['zero_minutes_denominator']
        elif complete_team and normalization == 'per_100_pass_attempts' and denominator == 0:
            reasons = ['zero_pass_attempts_denominator']
        elif complete_team and normalization == 'per_100_pressure_attempts' and denominator == 0:
            reasons = ['zero_pressure_attempts_denominator']
        names = sorted({r['person_name'] for r in rows if r.get('person_name')})
        identity = {'person_native_id': person, 'person_name': names[0] if names else None,
                    'names': names[:8], 'name_alias_count': len(names), 'name_state': 'available' if names else 'canonical_id_name_unavailable',
                    'historical_team_native_id': tid, 'historical_team_database_index': index,
                    'historical_team_names': sorted(team_names[(tid, index)])[:8]}
        if reasons:
            uncertain = any(reason not in ('below_minimum_minutes','zero_minutes_denominator','zero_pass_attempts_denominator','zero_pressure_attempts_denominator') for reason in reasons)
            uncertain_groups += uncertain
            for reason in set(reasons):
                classifications[reason] += 1
            excluded.append({**identity, 'classification': 'uncertain' if uncertain else 'defined_exclusion', 'reasons': sorted(set(reasons)), 'known_minutes': known_minutes,
                             'unknown_active_minute_rows': unknown_minutes, 'missing_metric_rows': missing_metric})
            continue
        total = sum(r[metric] for r in rows)
        value = (Fraction(total) if normalization == 'total' else
                 Fraction((90 if normalization == 'per90' else 100) * total, denominator))
        result = {**identity, 'metric': metric, 'normalization': normalization,
                  'unit': 'count' if normalization=='total' else 'count_per_90_native_minutes' if normalization=='per90' else 'pressure_completion_percentage_computed' if normalization=='per_100_pressure_attempts' else 'count_per_100_pass_attempts',
                  'observed_total': total, 'minutes': None if unknown_minutes else known_minutes,
                  'known_minutes': known_minutes, 'unknown_active_minute_rows': unknown_minutes,
                  'unused_bench_null_minute_rows': unused, 'stored_match_rows': len(rows),
                  'denominator': denominator, 'value': float(value),
                  'exact_value': {'numerator': value.numerator, 'denominator': value.denominator}}
        qualified.append((value, result))
    qualified.sort(key=lambda item: (-item[0], item[1]['person_native_id'], item[1]['historical_team_native_id'], item[1]['historical_team_database_index']))
    last = None
    rank = None
    for position, (value, row) in enumerate(qualified, 1):
        if value != last:
            rank, last = position, value
        row['rank'] = rank
    return {'ranked': qualified, 'team_coverage': coverage,
            'counts': {'selected_fixtures': len(fixtures), 'selected_player_rows': row_count, 'deduplicated_fixture_rows': duplicate_fixtures, 'deduplicated_player_rows': duplicate_players, 'unresolved_fixture_sides': len(unresolved_fixture_sides),
                       'canonical_player_team_groups': len(groups), 'qualifying_groups': len(qualified),
                       'unclassified_groups': uncertain_groups, 'defined_excluded_groups': len(excluded)-uncertain_groups, 'unresolved_identity_rows': len(unidentified)},
            'unclassified_reason_counts': dict(classifications),
            'excluded': excluded, 'unclassified_groups': [row for row in excluded if row['classification']=='uncertain'][:100], 'unresolved_fixture_side_examples': unresolved_fixture_sides[:20], 'unresolved_identity_examples': unidentified[:20]}


def capture_rank_scope(bridge, session_id, team_id, first, last, competition_id, *, metric, normalization):
    from .export_live_matches import capture_scope
    counters = {metric} | ({'passes_attempted'} if normalization == 'per_100_pass_attempts' else {'pressures_attempted'} if normalization == 'per_100_pressure_attempts' else set())
    identity_fields = {'fixture_key','side_index','team_index_word','person_index_word',
                       'canonical_person_id','person_name','minutes','appearance_kind'}
    def batch_capture(b, s, refs):
        batch = capture_live(b, s, refs, include_players=True)
        slim = []
        for item in batch['capture']['fixtures']:
            fixture = {'date': item['fixture'].get('date')}
            for side in ('home_team','away_team'):
                team = item['fixture'].get(side) or {}
                fixture[side] = {key:team.get(key) for key in ('native_id','database_index','native_type_code')}
                fixture[side]['owner'] = {key:(team.get('owner') or {}).get(key) for key in ('name','short_name')}
            source = item.get('source') or {}
            slim.append({'fixture':fixture,'native_match_key':item['native_match_key'],
                         'source_state':source.get('state'),'raw_sha256':source.get('raw_sha256')})
        return {'capture': {'save':batch['capture']['save'],'fixtures':slim,
                            'source_kind':batch['capture'].get('source_kind'),
                            'metric_provenance':batch['capture'].get('action_field_provenance',{}).get(metric)},
                'retained_players':[{key:row.get(key) for key in identity_fields | counters} for row in batch.get('retained_players',[])],
                'team_totals':{'records':[]},'raw_frames':[]}
    return capture_scope(bridge, session_id, team_id, first, last, competition_id,
                         capture=batch_capture, max_matches=MAX_FIXTURES, max_pages=2048,
                         capture_batch_size=16,
                         fixture_query=lambda sid, **query: bridge.find_fixtures(sid, selector_prefilter=True, **query))


class LiveMatchPlayerRanks:
    def __init__(self, capture=None, epoch=None):
        self.capture = capture or capture_rank_scope
        self.epoch = epoch or capture_epoch
        self.pages = OrderedDict()
        self.lock = threading.RLock()

    def rank(self, bridge, session_id, competition_native_id, date_from, date_to, metric,
             normalization='per90', minimum_minutes=None, team_native_id=None, limit=10, cursor=None, highlight_person_native_ids=None):
        if metric not in METRICS:
            raise ValueError('Unsupported metric; use fm_get_live_match_rank_metrics')
        allowed = metric_normalizations(metric)
        if normalization not in allowed:
            raise ValueError('Unsupported metric normalization')
        minimum = (0 if normalization == 'total' else 450) if minimum_minutes is None else minimum_minutes
        if type(minimum) is not int or not 0 <= minimum <= 1000000:
            raise ValueError('minimum_minutes must be 0–1000000 or null')
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('limit must be 1–100')
        if type(competition_native_id) is not int or not 1 <= competition_native_id <= 2**32-1:
            raise ValueError('competition_native_id must be a positive native ID')
        if team_native_id is not None and (type(team_native_id) is not int or not 1 <= team_native_id <= 2**32-1):
            raise ValueError('team_native_id must be a positive native ID')
        for value in (date_from, date_to):
            if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                raise ValueError('Dates must use canonical YYYY-MM-DD')
        if date_from > date_to:
            raise ValueError('Date bounds are reversed')
        highlights = [] if highlight_person_native_ids is None else highlight_person_native_ids
        if not isinstance(highlights,list) or len(highlights)>8 or any(type(value) is not int or not 1<=value<=2**32-1 for value in highlights) or len(set(highlights))!=len(highlights):
            raise ValueError('Select at most 8 distinct positive highlight PERSON native IDs')
        selectors = (session_id, competition_native_id, date_from, date_to, metric, normalization, minimum, team_native_id, limit, tuple(highlights))
        with self.lock:
            now = time.monotonic()
            for token in list(self.pages):
                if now - self.pages[token]['created'] > 300:
                    del self.pages[token]
            if cursor is not None:
                snapshot = self.pages.get(cursor)
                if snapshot is None or snapshot['selectors'] != selectors:
                    raise ValueError('Expired rank cursor or changed selectors')
                if self.epoch(bridge, session_id) != snapshot['epoch']:
                    del self.pages[cursor]
                    raise ValueError('Career/load epoch changed; start a fresh ranking')
                offset = snapshot['offset']
            else:
                from .live_crossing_report import _enumeration
                epoch = self.epoch(bridge, session_id)
                initial = bridge.get_save(session_id)['save']
                if date_to > initial['current_date']:
                    raise ValueError('Ranking dates must not exceed the active career date')
                captured = self.capture(bridge, session_id, team_native_id, date_from, date_to, competition_native_id, metric=metric, normalization=normalization)
                if self.epoch(bridge, session_id) != epoch:
                    raise ValueError('Career/load epoch changed during ranking')
                projection = rank_capture(captured, metric, normalization, minimum, team_native_id)
                ranked = projection.pop('ranked')
                excluded = projection.pop('excluded')
                highlighted = []
                for person in highlights:
                    matches = [row for _,row in ranked if row['person_native_id']==person]
                    failures = [row for row in excluded if row['person_native_id']==person]
                    highlighted.append({'person_native_id':person,'state':'ranked' if matches else 'excluded' if failures else 'not_observed_in_captured_rows',
                                        'ranked_groups':matches,'excluded_groups':failures})
                cutoff = ranked[min(limit, len(ranked))-1][0] if ranked else None
                selected = [row for value, row in ranked if value >= cutoff] if ranked else []
                enumeration = _enumeration(captured, date_from, date_to)
                incomplete = any(t['missing_player_sides'] for t in projection['team_coverage'])
                partial = incomplete or projection['counts']['unclassified_groups'] or projection['counts']['unresolved_identity_rows'] or projection['counts']['unresolved_fixture_sides'] or enumeration['state'] != 'complete_resident_groups'
                snapshot = {'selectors': selectors, 'epoch': epoch, 'created': time.monotonic(),
                            'rows': selected, 'capture_id': secrets.token_urlsafe(16),
                            'observed_at': datetime.now(timezone.utc).isoformat(),
                            'state': 'available_partial' if partial else 'available_observed_scope',
                            'active_save_first': initial, 'active_save_last': bridge.get_save(session_id)['save'],
                            'enumeration': enumeration, 'highlighted_players': highlighted,
                            'ranking_complete_among_observed_groups': not (projection['counts']['unclassified_groups'] or projection['counts']['unresolved_identity_rows'] or projection['counts']['unresolved_fixture_sides']),
                            'whole_season_completeness': 'not_established',
                            'metric_provenance': captured['capture'].get('metric_provenance'), **projection,
                            'cutoff': None if cutoff is None else {'numerator': cutoff.numerator, 'denominator': cutoff.denominator, 'value': float(cutoff)}}
                if self.epoch(bridge, session_id) != epoch:
                    raise ValueError('Career/load epoch changed before returning ranking')
                offset = 0
            end = offset + PAGE_SIZE
            next_cursor = None
            if end < len(snapshot['rows']):
                next_cursor = secrets.token_urlsafe(24)
                self.pages[next_cursor] = {**snapshot, 'offset': end}
                while len(self.pages) > 32:
                    self.pages.popitem(last=False)
            return {key: value for key, value in snapshot.items() if key not in ('selectors', 'epoch', 'created', 'rows', 'offset')} | {
                'rows': snapshot['rows'][offset:end], 'next_cursor': next_cursor,
                'selected_with_cutoff_ties': len(snapshot['rows']), 'requested_limit': limit,
                'minimum_minutes': minimum, 'metric': metric, 'normalization': normalization,
                'ranking_policy': 'Exact rational competition ranks1,1,3; limit includes every cutoff tie across fixed100-row pages.',
                'scope': 'Available retained records for historical fixture teams, not current roster, played role, eligibility or whole-season completeness.',
                'source_kind': 'active_running_session_only', 'atomic': False, 'disk_capture_fallback': False,
                'response_bounds': {'maximum_rows_per_page': PAGE_SIZE, 'unclassified_examples': 100, 'identity_examples': 20},
            }
