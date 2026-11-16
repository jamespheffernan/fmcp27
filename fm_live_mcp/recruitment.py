"""Validated save-wide player criteria shared by native prefilter and readback."""
from datetime import date

from . import personality, player_profile, players


FIELDS = {f'attributes.{name}': ('r', 0x148 + offset, 20) for name, offset in players.ATTRIBUTES.items()}
FIELDS.update({'ability.current': ('s', 0x25C, 200), 'ability.potential': ('s', 0x25E, 200)})
for group, mapping, kind in [('positions', player_profile.POSITIONS, 'b'),
    ('goalkeeping', player_profile.GOALKEEPING, 'r'), ('hidden_attributes', player_profile.HIDDEN, 'r'),
    ('feet', player_profile.FEET, 'r'), ('personality', personality.FIELDS, 'p')]:
    FIELDS.update({f'{group}.{name}': (kind, fields[0], 20) for name, fields in mapping.items()})


def date_number(value):
    if not isinstance(value, str):
        raise ValueError('Birth-date bounds must use YYYY-MM-DD')
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value or not 1850 <= parsed.year <= 2200:
        raise ValueError('Birth-date bounds must use YYYY-MM-DD in 1850–2200')
    return parsed.year * 512 + parsed.timetuple().tm_yday


def compile_filters(minimum_attributes=None, maximum_attributes=None, minimum_profile=None,
                    maximum_profile=None, born_on_or_after=None, born_on_or_before=None):
    criteria, bounds = {}, {}
    for label, supplied, attribute, lower in [
        ('minimum_attributes', minimum_attributes, True, True), ('maximum_attributes', maximum_attributes, True, False),
        ('minimum_profile', minimum_profile, False, True), ('maximum_profile', maximum_profile, False, False)]:
        values = {} if supplied is None else supplied
        allowed = players.ATTRIBUTES if attribute else player_profile.QUERY_FIELDS
        if not isinstance(values, dict) or len(values) > len(allowed):
            raise ValueError(f'{label} must map supported fields to integer bounds')
        criteria[label] = {}
        for key, value in values.items():
            if key not in allowed:
                raise ValueError(f'Unsupported {label} field: {key}')
            path = f'attributes.{key}' if attribute else key
            ceiling = FIELDS[path][2]
            if type(value) is not int or not 0 <= value <= ceiling:
                raise ValueError(f'{label}.{key} must be an integer from 0 to {ceiling}')
            criteria[label][key] = value
            bounds.setdefault(path, [0, ceiling])[0 if lower else 1] = value
    criteria.update(born_on_or_after=born_on_or_after, born_on_or_before=born_on_or_before)
    if born_on_or_after is not None or born_on_or_before is not None:
        bounds['birth_date'] = [date_number('1850-01-01' if born_on_or_after is None else born_on_or_after),
                                date_number('2200-12-31' if born_on_or_before is None else born_on_or_before)]
    if any(lo > hi for lo, hi in bounds.values()):
        raise ValueError('Minimum criteria must not exceed maximum criteria')
    native = []
    for path, (lo, hi) in sorted(bounds.items()):
        kind, offset, _ = ('d', 0x2D0, 0) if path == 'birth_date' else FIELDS[path]
        native.extend(['--player-filter', f'{kind}:{offset}:{lo}:{hi}'])
    return {'criteria': criteria, 'bounds': bounds, 'native': native}


def classify(player, filters):
    unknown = []
    for path, (lo, hi) in filters['bounds'].items():
        if path == 'birth_date':
            value = date_number(player['birth_date'])
        else:
            group, name = path.split('.')
            value = player['attributes'][name] if group == 'attributes' else player['profile'][group][name]
        if value is None:
            unknown.append(path)
        elif not lo <= value <= hi:
            return 'nonmatch', []
    return ('unknown_potential' if unknown else 'match'), sorted(unknown)
