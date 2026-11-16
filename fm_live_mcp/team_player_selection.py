"""Pure availability-aware selection over a complete checked team roster."""
from datetime import date

from . import player_health, player_profile, players


REASONS = {'match': 'all_required_values_match', 'nonmatch': 'known_predicate_failed',
           'typeexcluded': 'virtual_excluded', 'unclassified': 'required_values_unavailable'}


def _integer(value, lower, upper, path):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f'Invalid {path}: expected integer in {lower}..{upper}')
    return value


def _cold_null(row, field):
    unavailable = row.get('unavailable_fields')
    if (row['record_kind'] != 'virtual' or row.get('profile_state') != 'identity_only'
            or not isinstance(unavailable, list) or field not in unavailable):
        raise ValueError(f'Unproved unavailable player field: {field}')
    return None


def _group(row, name):
    if name not in row:
        raise ValueError(f'Missing required player group: {name}')
    group = row[name]
    if group is None:
        return _cold_null(row, name)
    if not isinstance(group, dict):
        raise ValueError(f'Invalid required player group: {name}')
    return group


def _value(row, path):
    if path in ('display_name', 'birth_date'):
        if path not in row:
            raise ValueError(f'Missing required player field: {path}')
        value = row[path]
        if value is None:
            return _cold_null(row, path)
        if not isinstance(value, str) or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError(f'Invalid required player field: {path}')
        if path == 'birth_date':
            try:
                parsed = date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError('Invalid player birth_date') from exc
            if parsed.isoformat() != value or not 1850 <= parsed.year <= 2200:
                raise ValueError('Invalid player birth_date')
        return value

    group_name, field = path.split('.', 1)
    group = _group(row, group_name if group_name in ('attributes', 'health', 'clubs') else 'profile')
    if group is None:
        return None
    if group_name not in ('attributes', 'health', 'clubs'):
        if group_name not in group or not isinstance(group[group_name], dict):
            raise ValueError(f'Missing or invalid profile group: {group_name}')
        group = group[group_name]
    if field not in group:
        raise ValueError(f'Missing required player value: {path}')
    value = group[field]
    if value is None:
        if path == 'ability.potential':
            code = group.get('potential_native_code')
            expected = 'range' if type(code) is int and code in player_profile.POTENTIAL_RANGES else 'unmapped_range'
            if type(code) is int and -100 <= code < 0 and group.get('potential_state') == expected:
                return None
        if (group_name == 'health' and field in ('condition', 'match_sharpness')
                and row['record_kind'] == 'virtual' and group.get('state') == 'partial_virtual'
                and isinstance(group.get('unavailable_fields'), list)
                and field in group['unavailable_fields']):
            return None
        raise ValueError(f'Unproved unavailable player value: {path}')
    if group_name == 'clubs':
        if type(value) is not bool:
            raise ValueError('Invalid clubs.on_loan: expected boolean')
        return value
    if group_name == 'health':
        if field == 'injury_record_count':
            if type(value) is not int or value < 0:
                raise ValueError('Invalid health.injury_record_count')
            return value
        _, lower, upper = player_health.FIELDS[field]
        return _integer(value, lower, upper, path)
    upper = 20 if group_name == 'attributes' else player_profile.QUERY_FIELDS[path]
    return _integer(value, 0, upper, path)


def _criteria(criteria):
    if not isinstance(criteria, dict):
        raise ValueError('Team selection criteria must be a dictionary')
    required = ('minimum_attributes', 'minimum_profile', 'minimum_health', 'maximum_health',
                'include_virtual', 'loan_status', 'injury_records', 'sort_by')
    if any(key not in criteria for key in required):
        raise ValueError('Team selection requires normalized criteria')
    bounds = []
    for label, prefix, allowed, lower_bound in (
            ('minimum_attributes', 'attributes.', players.ATTRIBUTES, True),
            ('minimum_profile', '', player_profile.QUERY_FIELDS, True),
            ('minimum_health', 'health.', player_health.FIELDS, True),
            ('maximum_health', 'health.', player_health.FIELDS, False)):
        values = criteria[label]
        if not isinstance(values, dict):
            raise ValueError(f'Invalid normalized {label}')
        for field, value in values.items():
            if not isinstance(field, str) or field not in allowed:
                raise ValueError(f'Unsupported {label} field')
            if label.endswith('health'):
                _, lower, upper = player_health.FIELDS[field]
            else:
                lower = 1 if label == 'minimum_attributes' else 0
                upper = 20 if prefix else player_profile.QUERY_FIELDS[field]
            _integer(value, lower, upper, label + '.' + field)
            bounds.append((prefix + field, value, lower_bound))
    if (type(criteria['include_virtual']) is not bool
            or criteria['loan_status'] not in ('any', 'on_loan', 'not_on_loan')
            or criteria['injury_records'] not in ('any', 'with_records', 'without_records')):
        raise ValueError('Invalid team selection type, loan or injury criteria')
    if any(criteria['minimum_health'][field] > value for field, value in criteria['maximum_health'].items()
           if field in criteria['minimum_health']):
        raise ValueError('Minimum health bounds exceed maximum bounds')
    sort = criteria['sort_by']
    sort_path = None
    if sort is not None:
        if not isinstance(sort, str):
            raise ValueError('Invalid team selection sort field')
        if sort in players.ATTRIBUTES:
            sort_path = 'attributes.' + sort
        elif sort in player_profile.QUERY_FIELDS or sort in {f'health.{key}' for key in player_health.FIELDS}:
            sort_path = sort
        else:
            raise ValueError('Unsupported team selection sort field')
    return bounds, sort_path


def select(rows, criteria, limit) -> dict:
    """Partition every row, preserve valid unknowns, then sort and limit full matches."""
    _integer(limit, 1, 100, 'limit')
    bounds, sort_path = _criteria(criteria)
    if not isinstance(rows, list):
        raise ValueError('Team selection rows must be a list')
    paths = {'display_name', 'birth_date', *(path for path, _, _ in bounds)}
    if sort_path:
        paths.add(sort_path)
    if criteria['loan_status'] != 'any':
        paths.add('clubs.on_loan')
    if criteria['injury_records'] != 'any':
        paths.add('health.injury_record_count')
    matches, unclassified, classifications, indices = [], [], [], set()
    counts = {'roster_count': len(rows), 'match_count': 0, 'nonmatch_count': 0,
              'typeexcluded_count': 0, 'unclassified_count': 0}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid team selection player row')
        index = row.get('roster_index')
        if type(index) is not int or index < 0 or index in indices:
            raise ValueError('Team selection requires unique nonnegative roster_index values')
        indices.add(index)
        if not isinstance(row.get('player_ref'), str) or not row['player_ref']:
            raise ValueError('Team selection player_ref is missing or invalid')
        if row.get('record_kind') not in ('actual', 'player_staff', 'virtual'):
            raise ValueError('Unsupported team selection record_kind')
        missing = []
        if row['record_kind'] == 'virtual' and not criteria['include_virtual']:
            state = 'typeexcluded'
        else:
            values = {path: _value(row, path) for path in sorted(paths)}
            failed = any(values[path] is not None and
                         (values[path] < bound if lower else values[path] > bound)
                         for path, bound, lower in bounds)
            if criteria['loan_status'] != 'any' and values['clubs.on_loan'] is not None:
                failed |= values['clubs.on_loan'] != (criteria['loan_status'] == 'on_loan')
            if criteria['injury_records'] != 'any' and values['health.injury_record_count'] is not None:
                failed |= bool(values['health.injury_record_count']) != (criteria['injury_records'] == 'with_records')
            if failed:
                state = 'nonmatch'
            else:
                missing = sorted(path for path, value in values.items() if value is None)
                state = 'unclassified' if missing else 'match'
            if state == 'match':
                matches.append((row, values))
            elif state == 'unclassified':
                unclassified.append({'player': row, 'unavailable_fields': missing})
        counts[state + '_count'] += 1
        classifications.append({'roster_index': index, 'state': state,
                                'reason': REASONS[state], 'unavailable_fields': missing})
    matches.sort(key=lambda item: (-(item[1][sort_path]) if sort_path else 0,
                                   item[1]['display_name'].casefold(), item[1]['birth_date']))
    return {'players': [row for row, _ in matches[:limit]], 'matched_count': len(matches),
            'returned_count': min(limit, len(matches)), 'truncated': len(matches) > limit,
            'unclassified_players': unclassified, 'unclassified_count': len(unclassified),
            'classifications': classifications, 'counts': counts,
            'complete_for_included_population': not unclassified}
