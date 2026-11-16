"""Conditional saved-file criteria scan over original contiguous PERSON slots."""
from array import array
from dataclasses import replace
from hashlib import sha256
import base64
import datetime as dt
import hmac
import json
import secrets
import struct
import time
from . import saved_population as population, saved_player_ratings as ratings, player_profile
_SECRET = secrets.token_bytes(32)
_CATEGORIES = ('matched', 'predicate_excluded', 'rating_missing', 'age_missing', 'class_excluded', 'unsupported')
_FIELDS = {
    'attributes': set(ratings.ATTRIBUTES),
    'positions': set(ratings.POSITIONS),
    'ability': {'current', 'potential'},
}

def _criteria(criteria, min_age, max_age):
    if not isinstance(criteria, dict) or len(criteria) > 64:
        raise ValueError('criteria must contain at most64 named rating bounds')
    normalized_criteria = {}
    for criterion_key, field_bounds in criteria.items():
        if type(criterion_key) is not str or '.' not in criterion_key:
            raise ValueError('Use group.field criteria names')
        rating_group, field_name = criterion_key.split('.', 1)
        if field_name not in _FIELDS.get(rating_group, ()):
            raise ValueError('Unknown saved rating criterion')
        if (
            not isinstance(field_bounds, dict)
            or not field_bounds
            or set(field_bounds) - {'min', 'max'}
        ):
            raise ValueError('Each criterion requires min and/or max')
        if any(
            (type(bound_value) is not int or not -32768 <= bound_value <= 32767 for bound_value in field_bounds.values()),
        ):
            raise ValueError('Rating bounds must be exact signed16 integers')
        if field_bounds.get('min', -32768) > field_bounds.get('max', 32767):
            raise ValueError('Reversed rating bounds')
        normalized_criteria[criterion_key] = dict(sorted(field_bounds.items()))
    for age_bound in (min_age, max_age):
        if (
            age_bound is not None
            and (type(age_bound) is not int or not 0 <= age_bound <= 150)
        ):
            raise ValueError('Age bounds must be integers0..150')
    if min_age is not None and max_age is not None and (min_age > max_age):
        raise ValueError('Reversed age bounds')
    if not normalized_criteria and min_age is None and (max_age is None):
        raise ValueError('Supply at least one rating or age criterion')
    return dict(sorted(normalized_criteria.items()))

def _token(value):
    payload_bytes = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
    return base64.urlsafe_b64encode(payload_bytes + hmac.digest(_SECRET, payload_bytes, 'sha256')).decode(
    )

def _restore(token):
    try:
        if type(token) is not str or len(token) > 4096:
            raise ValueError()
        signed_payload_bytes = base64.b64decode(token, altchars=b'-_', validate=True)
        if (
            len(signed_payload_bytes) < 33
            or not hmac.compare_digest(
                signed_payload_bytes[-32:],
                hmac.digest(_SECRET, signed_payload_bytes[:-32], 'sha256'),
            )
        ):
            raise ValueError()
        return json.loads(signed_payload_bytes[:-32])
    except (ValueError, TypeError, UnicodeError) as error:
        raise ValueError('Invalid or stale scouting cursor; restart without cursor on this server') from error

def _birth(raw, comparison_date):
    day_of_year, birth_year = struct.unpack('<HH', raw)
    birth_context = {
        'state': 'invalid_date_of_birth',
        'date': None,
        'age': None,
    }
    if not 1850 <= birth_year <= 2200 or not 1 <= day_of_year <= 366:
        return birth_context
    birth_date = dt.date(birth_year, 1, 1) + dt.timedelta(days=day_of_year - 1)
    if birth_date.year != birth_year:
        return birth_context
    birth_context['date'] = birth_date.isoformat()
    if comparison_date is None:
        return {**birth_context, 'state': 'comparison_date_unavailable'}
    if birth_date > comparison_date:
        return {**birth_context, 'state': 'future_date_of_birth'}
    return {
        **birth_context,
        'state': 'available',
        'age': comparison_date.year - birth_date.year - ((comparison_date.month, comparison_date.day) < (birth_date.month, birth_date.day)),
    }

def _evaluate(row, criteria, min_age, max_age, comparison_date):
    scouting_fields = row.get('_scouting')
    if scouting_fields is None:
        return ('rating_missing' if criteria else 'age_missing', {}, None)
    decoded_ratings = ratings.decode(scouting_fields['raw69'], scouting_fields['scale_byte'])
    matched_values = {}
    rating_missing = False
    predicate_failed = False
    for criterion_key, field_bounds in criteria.items():
        rating_group, field_name = criterion_key.split('.')
        if rating_group == 'ability':
            stored_ability_code = scouting_fields.get(field_name)
            potential_is_encoded_range = (
                field_name == 'potential'
                and stored_ability_code in player_profile.POTENTIAL_RANGES
            )
            rating_value = (
                stored_ability_code
                if (
                    type(stored_ability_code) is int
                    and 0 <= stored_ability_code <= 200
                    and (not potential_is_encoded_range)
                )
                else None
            )
        else:
            rating_value = decoded_ratings[rating_group][field_name]['value']
        matched_values[criterion_key] = rating_value
        if rating_value is None:
            rating_missing = True
        elif (
            rating_value < field_bounds.get('min', -32768)
            or rating_value > field_bounds.get('max', 32767)
        ):
            predicate_failed = True
    birth_context = _birth(scouting_fields['birth_raw'], comparison_date)
    age_missing = False
    if min_age is not None or max_age is not None:
        if birth_context['age'] is None:
            age_missing = True
        elif (
            birth_context['age'] < (min_age if min_age is not None else 0)
            or birth_context['age'] > (max_age if max_age is not None else 150)
        ):
            predicate_failed = True
    predicate_state = (
        'predicate_excluded'
        if predicate_failed
        else (
            'rating_missing'
            if rating_missing
            else 'age_missing' if age_missing else 'matched'
        )
    )
    return (predicate_state, matched_values, birth_context)

def find_players(
    filename,
    expected_snapshot_id,
    *,
    criteria=None,
    min_age=None,
    max_age=None,
    cursor=None,
    limit=20,
    scan_limit=10000,
    directory=None,
    _seconds=2.0,
):
    """Read a bounded original-slot page; empty partial pages can continue."""
    criteria = _criteria({} if criteria is None else criteria, min_age, max_age)
    if (
        type(limit) is not int
        or not 1 <= limit <= 50
        or type(scan_limit) is not int
        or (not 1 <= scan_limit <= 10000)
    ):
        raise ValueError('Invalid scouting match or scan limit')
    query_context = {
        'criteria': criteria,
        'min_age': min_age,
        'max_age': max_age,
    }
    query_hash = sha256(json.dumps(query_context, sort_keys=True).encode()).hexdigest()
    cursor_context = None if cursor is None else _restore(cursor)
    if not population._LOCK.acquire(blocking=False):
        raise ValueError('Another saved population scan is in progress; retry')
    try:
        component_digest = None

        def locate(data):
            nonlocal component_digest
            component_digest = sha256(data).digest()
            if (
                population._LAST_LAYOUT is not None
                and population._LAST_LAYOUT[0] == component_digest
            ):
                return replace(population._LAST_LAYOUT[1], _data=data)
            return population.saved_name_vectors.locate(data)
        with population.checked_name_source(
            filename,
            expected_snapshot_id,
            directory,
            locate=locate,
        ) as (data, layout, snapshot_id, saved_metadata):
            prefix_cache_key = (snapshot_id, component_digest, layout.person_offset, layout.person_count)
            cached_record_ends = population._PREFIXES.get(prefix_cache_key, array('I'))
            prior_category_counts = {category: 0 for category in _CATEGORIES}
            first_ordinal = 0
            if cursor_context is not None:
                if (
                    cursor_context.get('pin') != snapshot_id
                    or cursor_context.get('digest') != component_digest.hex()
                    or cursor_context.get('query') != query_hash
                ):
                    raise ValueError('Scouting cursor source or criteria changed')
                first_ordinal = cursor_context['next']
                prior_category_counts = cursor_context['counts']
                if first_ordinal > len(cached_record_ends):
                    raise ValueError('Scouting cursor prefix expired; restart without cursor')
            comparison_date = None
            if saved_metadata.get('status') == 'verified':
                try:
                    comparison_date = dt.date.fromisoformat(saved_metadata['saved_simulation_date'])
                except (KeyError, ValueError):
                    pass
            record_offset = (
                cached_record_ends[first_ordinal - 1]
                if first_ordinal
                else layout.person_records_offset
            )
            new_record_ends = array('I')
            page_category_counts = {category: 0 for category in _CATEGORIES}
            matched_players = []
            ordinal = first_ordinal
            source_frontier = None
            stop_reason = None
            decode_started_at = time.monotonic()
            while ordinal < layout.person_count and ordinal - first_ordinal < scan_limit:
                if (
                    ordinal > first_ordinal
                    and time.monotonic() - decode_started_at >= _seconds
                ):
                    stop_reason = 'elapsed_work_budget'
                    break
                person_record = population._read_record(data, record_offset, ordinal, include_scouting=True)
                if person_record['state'] == 'unsupported':
                    page_category_counts['unsupported'] += 1
                    source_frontier = {
                        'ordinal': ordinal,
                        'tag_offset': record_offset,
                        'signed_tag': person_record['signed_tag'],
                        'reason': person_record.get('reason'),
                    }
                    stop_reason = 'unsupported_source_frontier'
                    break
                record_end = person_record['end']
                if ordinal < len(cached_record_ends):
                    if cached_record_ends[ordinal] != record_end:
                        raise ValueError('Cached scouting extent differs from source')
                else:
                    new_record_ends.append(record_end)
                if person_record['signed_tag'] not in (2, 3):
                    page_category_counts['class_excluded'] += 1
                else:
                    predicate_state, matched_values, birth_context = _evaluate(person_record, criteria, min_age, max_age, comparison_date)
                    page_category_counts[predicate_state] += 1
                    if predicate_state == 'matched':
                        matched_person = population._project(data, layout, person_record)
                        matched_person.update(
                            database_index=ordinal,
                            matched_values=matched_values,
                            date_of_birth=birth_context,
                        )
                        matched_players.append(matched_person)
                record_offset = record_end
                ordinal += 1
                if len(matched_players) >= limit:
                    stop_reason = 'match_page_limit'
                    break
            all_declared_slots_decoded = ordinal == layout.person_count
            table_footer = (
                population._footer(data, record_offset)
                if all_declared_slots_decoded
                else {'state': 'not_reached'}
            )
            table_audit_complete = (
                all_declared_slots_decoded
                and table_footer['state'] == 'source_footer_read'
            )
            if table_audit_complete:
                stop_reason = 'declared_table_end'
            elif stop_reason is None:
                stop_reason = 'slot_work_budget'
            cumulative_category_counts = {category: prior_category_counts[category] + page_category_counts[category] for category in _CATEGORIES}
            next_cursor = (
                None
                if table_audit_complete or source_frontier
                else _token(
                    {
                        'pin': snapshot_id,
                        'digest': component_digest.hex(),
                        'query': query_hash,
                        'next': ordinal,
                        'counts': cumulative_category_counts,
                    },
                )
            )
            response = {
                'filename': filename,
                'snapshot_id': snapshot_id,
                'component_sha256': component_digest.hex(),
                'saved_metadata': saved_metadata,
                'matches': matched_players,
                'match_count': len(matched_players),
                'counts': page_category_counts,
                'cumulative_counts': cumulative_category_counts,
                'state': (
                    'complete_declared_table'
                    if table_audit_complete
                    else 'stopped' if source_frontier else 'partial'
                ),
                'scanned_slot_count': sum(page_category_counts.values()),
                'attempted_slot_count': sum(page_category_counts.values()),
                'cumulative_attempted_slot_count': sum(cumulative_category_counts.values()),
                'decoded_slot_count': sum(page_category_counts.values()) - page_category_counts['unsupported'],
                'cumulative_decoded_slot_count': sum(cumulative_category_counts.values()) - cumulative_category_counts['unsupported'],
                'first_scanned_ordinal': first_ordinal,
                'last_scanned_ordinal': (
                    ordinal
                    if source_frontier
                    else ordinal - 1 if ordinal > first_ordinal else None
                ),
                'next_original_ordinal': ordinal,
                'next_cursor': next_cursor,
                'stop_reason': stop_reason,
                'source_frontier': source_frontier,
                'declared_person_slots': layout.person_count,
                'footer': table_footer,
                'all_declared_slots_decoded': all_declared_slots_decoded,
                'declared_table_audit_complete': table_audit_complete,
                'whole_declared_table_scanned': table_audit_complete and first_ordinal == 0,
                'cumulative_declared_table_scanned': table_audit_complete,
                'comparison_date': comparison_date.isoformat() if comparison_date else None,
                'comparison_date_source': (
                    'same-file verified save_game_summary.dat'
                    if comparison_date
                    else 'unavailable'
                ),
                'query': query_context,
                'ability_criteria_policy': 'fixed_CA_PA_0_to_200_only; negative_PA_ranges_and_unavailable_codes_unresolved_regardless_of_bounds',
                'wire_profile_is_conditional': True,
                'native_loader_globals_proved': False,
                'membership_scope': 'contiguous original slots; regular and combined PLAYER classes only',
                'elapsed_decode_seconds': time.monotonic() - decode_started_at,
            }
            if len(json.dumps(response, ensure_ascii=True)) > 2 * 1024 ** 2:
                raise ValueError('Scouting response exceeds budget; lower limit')
        population._LAST_LAYOUT = (component_digest, replace(layout, _data=None))
        cached_record_ends.extend(new_record_ends)
        population._PREFIXES[prefix_cache_key] = cached_record_ends
        population._PREFIXES.move_to_end(prefix_cache_key)
        while len(population._PREFIXES) > population._MAX_CACHES:
            population._PREFIXES.popitem(last=False)
        return response
    finally:
        population._LOCK.release()
