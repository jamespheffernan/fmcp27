"""Exact rankings over decoded current League statistics; no source collection."""
from fractions import Fraction


def _integer(value, lower, upper, name):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f'{name} must be an integer from {lower} through {upper}')


def _league(statistics):
    if statistics is None:
        return None, 'missing_statistics_source'
    if not isinstance(statistics, dict):
        raise ValueError('Current statistics must be a dictionary or None')
    state = statistics.get('state', 'stored_without_refresh')
    if state not in ('stored_without_refresh', 'unavailable_not_resident'):
        raise ValueError('Unsupported current statistics source state')
    categories = statistics.get('categories')
    if categories is None:
        return None, ('unavailable_statistics_source' if state == 'unavailable_not_resident'
                      else 'missing_league_category')
    if not isinstance(categories, list):
        raise ValueError('Current statistics categories must be a list')
    league = []
    for category in categories:
        if not isinstance(category, dict) or type(category.get('native_code')) is not int:
            raise ValueError('Current statistics category must have an integer native_code')
        if category['native_code'] == 1:
            league.append(category)
    if len(league) > 1:
        raise ValueError('Duplicate current League statistics category')
    if league and 'name' in league[0] and league[0]['name'] != 'League':
        raise ValueError('Current League category name disagrees with native_code 1')
    if state == 'unavailable_not_resident':
        return None, 'unavailable_statistics_source'
    if not league:
        return None, 'missing_league_category'
    category = league[0]
    availability = category.get('availability', 'resident')
    if availability not in ('resident', 'unavailable_null_category', 'unavailable_not_resident'):
        raise ValueError('Unsupported current League category availability')
    if availability != 'resident' or category.get('statistics') is None:
        return None, 'unavailable_league_category'
    if not isinstance(category['statistics'], dict):
        raise ValueError('Current League statistics must be a dictionary or None')
    return category['statistics'], None


def rank_current_players(candidates, minimum_minutes=450, limit=5) -> dict:
    """Classify every roster entry before limiting exact goals-plus-assists/90 ranks."""
    _integer(minimum_minutes, 0, 32767, 'minimum_minutes')
    _integer(limit, 1, 25, 'limit')
    if not isinstance(candidates, list):
        raise ValueError('Performance candidates must be a list')
    counts = {'roster_count': len(candidates), 'actual_count': 0, 'unsupported_count': 0,
              'unknown_count': 0, 'below_minimum_count': 0, 'qualifying_count': 0,
              'returned_count': 0}
    classifications, qualified, indices = [], [], set()

    def classify(index, state, reason):
        classifications.append({'roster_index': index, 'state': state, 'reason': reason})
        key = 'qualifying_count' if state == 'qualified' else f'{state}_count'
        counts[key] += 1

    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError('Performance candidate must be a dictionary')
        index = candidate.get('roster_index')
        if type(index) is not int or index < 0 or index in indices:
            raise ValueError('Performance roster_index must be a unique nonnegative integer')
        indices.add(index)
        kind = candidate.get('record_kind')
        if not isinstance(kind, str) or not kind:
            raise ValueError('Performance candidate requires a record_kind string')
        if kind != 'actual':
            classify(index, 'unsupported', 'unsupported_record_kind')
            continue
        counts['actual_count'] += 1
        league, reason = _league(candidate.get('statistics'))
        if league is None:
            classify(index, 'unknown', reason)
            continue
        goals, assists = league.get('goals'), league.get('assists')
        for name, value in (('goals', goals), ('assists', assists)):
            if value is not None:
                _integer(value, 0, 254, f'Current League {name}')
        minutes = league.get('minutes')
        if minutes is None:
            classify(index, 'unknown', 'missing_minutes')
            continue
        if type(minutes) is not int:
            raise ValueError('Current League minutes must be an integer or None')
        if minutes < 0:
            classify(index, 'unknown', 'negative_minutes')
            continue
        if minutes == 0:
            classify(index, 'below_minimum', 'no_playing_time')
            continue
        if minutes < minimum_minutes:
            classify(index, 'below_minimum', 'below_minimum_minutes')
            continue
        if goals is None or assists is None:
            classify(index, 'unknown', 'missing_goals_or_assists')
            continue
        classify(index, 'qualified', 'meets_minimum_minutes')
        rate = Fraction(90 * (goals + assists), minutes)
        qualified.append((rate, {'roster_index': index, 'minutes': minutes,
                                'goals': goals, 'assists': assists,
                                'goals_plus_assists': goals + assists,
                                'per90': {'numerator': rate.numerator,
                                          'denominator': rate.denominator, 'value': float(rate)}}))
    qualified.sort(key=lambda item: (-item[0], -item[1]['minutes'], item[1]['roster_index']))
    rows = [{**row, 'rank': rank} for rank, (_, row) in enumerate(qualified[:limit], 1)]
    counts['returned_count'] = len(rows)
    return {'rows': rows, 'classifications': classifications, 'counts': counts,
            'ranking_complete_among_supported': counts['unknown_count'] == 0,
            'ranking_complete_for_roster': counts['unknown_count'] == counts['unsupported_count'] == 0}
