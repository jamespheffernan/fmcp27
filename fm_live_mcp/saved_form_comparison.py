"""Bounded observed G+A per90 over one pinned cohort's retained form rows."""
from datetime import date
from fractions import Fraction
import json

from . import saved_form_rows, saved_person_search, saved_player_form_query

MAX_PEOPLE = 32
MAX_RESPONSE_BYTES = 512 * 1024


def _day(value, field):
    if not isinstance(value, str):
        raise ValueError(f'{field} must be an ISO date YYYY-MM-DD')
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f'{field} must be an ISO date YYYY-MM-DD') from error
    if parsed.isoformat() != value:
        raise ValueError(f'{field} must be an ISO date YYYY-MM-DD')
    return value


def _index(value, field, maximum=2**31 - 1):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f'Invalid {field}')


def _aggregate(form, team_index, date_from, date_to, competition_index, minimum):
    """Use the identical supported row set for numerator and denominator."""
    owners = {g['group_ordinal']: g['owner_reference_word'] for g in form['groups']}
    coverage = dict(retained_rows=form['total_row_count'], retained_owner_rows=0,
                    excluded_other_owner_rows=0, excluded_competition_rows=0,
                    unmapped_date_rows=0, outside_interval_rows=0, interval_rows=0,
                    observed_stats_rows=0, missing_stats_rows=0,
                    unsupported_stats_rows=0, present_zero_minute_rows=0,
                    retained_owner_first_date=None, retained_owner_last_date=None,
                    observed_first_date=None, observed_last_date=None,
                    same_date_additional_rows=0)
    goals = assists = minutes = 0
    owner_dates, observed_dates, dates = [], [], {}
    competitions = {}
    for row in form['rows']:
        if owners[row['group_ordinal']] != team_index:
            coverage['excluded_other_owner_rows'] += 1
            continue
        coverage['retained_owner_rows'] += 1
        day = row['date']['value']
        if day is not None:
            owner_dates.append(day)
        if competition_index is not None and row['competition_index_word'] != competition_index:
            coverage['excluded_competition_rows'] += 1
            continue
        if day is None:
            coverage['unmapped_date_rows'] += 1
            continue
        if not date_from <= day <= date_to:
            coverage['outside_interval_rows'] += 1
            continue
        coverage['interval_rows'] += 1
        dates[day] = dates.get(day, 0) + 1
        comp = row['competition_index_word']
        competitions[comp] = competitions.get(comp, 0) + 1
        stats = row['stats']
        if stats['state'] == 'not_stored':
            coverage['missing_stats_rows'] += 1
            continue
        duration = stats.get('played_minutes')
        if (stats.get('state') != 'stored' or stats.get('played_minutes_state') != 'stored'
                or type(duration) is not int or not 0 <= duration <= 127
                or any(type(stats.get(key)) is not int or not 0 <= stats[key] <= 255
                       for key in ('goals', 'assists'))):
            coverage['unsupported_stats_rows'] += 1
            continue
        coverage['observed_stats_rows'] += 1
        coverage['present_zero_minute_rows'] += duration == 0
        goals += stats['goals']
        assists += stats['assists']
        minutes += duration
        observed_dates.append(day)
    for prefix, values in [('retained_owner', owner_dates), ('observed', observed_dates)]:
        coverage[prefix + '_first_date'] = min(values, default=None)
        coverage[prefix + '_last_date'] = max(values, default=None)
    coverage['same_date_additional_rows'] = sum(n - 1 for n in dates.values())
    rate = Fraction(90 * (goals + assists), minutes) if minutes else None
    return dict(state='eligible' if minutes >= minimum else 'below_minimum',
                goals=goals, assists=assists, goal_contributions=goals + assists,
                observed_minutes=minutes, goal_contributions_per90=float(rate) if rate is not None else None,
                per90_exact=dict(numerator=rate.numerator, denominator=rate.denominator) if rate is not None else None,
                rank=None, coverage=coverage,
                interval_competition_counts=[dict(competition_index_word=key, rows=value)
                                             for key, value in sorted(competitions.items())])


def _person(context, target, team_index, date_from, date_to, competition_index, minimum):
    geometries, rejected, exhausted = saved_player_form_query._starts(
        context['data'], context['layout'], target)
    neighbours = target.get('neighbour_corroboration', {})
    complete = (target.get('search_complete', False)
                and neighbours.get('search_complete', False) and not exhausted)
    state = ('incomplete_candidates' if not complete else
             'competing_candidates' if len(geometries) > 1 else
             'unavailable' if not geometries else 'ready')
    result = dict(person_index=target['person_index'], state=state, rank=None,
                  goals=None, assists=None, goal_contributions=None,
                  observed_minutes=None, goal_contributions_per90=None,
                  per90_exact=None, coverage=None, interval_competition_counts=None,
                  identity=None, name_context=None, checked_ranges={},
                  candidate_search=dict(search_complete=target.get('search_complete', False),
                      neighbour_search_complete=neighbours.get('search_complete', False),
                      typed_start_summary_complete=not exhausted,
                      typed_start_count=len(geometries), rejected_packet_counts=rejected,
                      budget_reasons=target.get('budget_reasons', [])))
    if state != 'ready':
        return result
    geometry = geometries[0]
    result['identity'] = geometry['identity']
    witness = next((w for w in target['candidates']
                    if w['common_start'] == geometry['common_start']
                    and w['identity_offset'] == geometry['identity_offset']), None)
    if witness is not None:
        result['name_context'] = witness.get('names')
    form = saved_player_form_query._decode(
        context['data'], geometry, 0, saved_form_rows.MAX_TOTAL_ROWS)
    result['form_state'] = form['state']
    result['checked_ranges'] = form.get('checked_ranges', {})
    result['form_groups_complete'] = form['form_groups_complete']
    if form['state'] != 'available':
        result['state'] = 'form_absent' if form['state'] == 'absent' else form['state']
        result['reason'] = form.get('reason')
        return result
    if (not form['form_groups_complete'] or form['next_offset'] is not None
            or len(form['rows']) != form['total_row_count']):
        raise ValueError('Saved comparison requires every decoded form row within the row budget')
    result.update(_aggregate(form, team_index, date_from, date_to, competition_index, minimum))
    return result


def compare_player_form(filename, person_indices, expected_snapshot_id, *, team_index,
                        date_from, date_to, minimum_observed_minutes,
                        competition_index=None, directory=None):
    """Compare a deduplicated selected cohort in one checked source context."""
    if not isinstance(person_indices, list) or not 1 <= len(person_indices) <= MAX_PEOPLE:
        raise ValueError('Supply between 1 and 32 saved PERSON indices')
    for index in person_indices:
        _index(index, 'saved PERSON index')
    _index(team_index, 'saved TEAM_BASE index', 2**32 - 2)
    if competition_index is not None:
        _index(competition_index, 'saved COMP index')
    date_from, date_to = _day(date_from, 'date_from'), _day(date_to, 'date_to')
    if date_from > date_to:
        raise ValueError('date_from must not follow date_to')
    if type(minimum_observed_minutes) is not int or minimum_observed_minutes <= 0:
        raise ValueError('minimum_observed_minutes must be a positive integer')
    unique = list(dict.fromkeys(person_indices))
    with saved_person_search.checked_person_context(
            filename, unique, expected_snapshot_id, directory=directory) as context:
        targets = {target['person_index']: target for target in context['ranked']}
        if len(targets) != len(context['ranked']) or set(targets) != set(unique):
            raise ValueError('Saved PERSON search did not return the exact selected cohort')
        people = [_person(context, targets[index], team_index, date_from, date_to,
                          competition_index, minimum_observed_minutes) for index in unique]
        eligible = sorted((p for p in people if p['state'] == 'eligible'),
                          key=lambda p: (-Fraction(**p['per90_exact']), p['person_index']))
        prior = None
        rank = 0
        for position, person in enumerate(eligible, 1):
            ratio = Fraction(**person['per90_exact'])
            if ratio != prior:
                rank, prior = position, ratio
            person['rank'] = rank
        reply = dict(source='on-disk save snapshot', filename=filename,
            snapshot_id=context['snapshot_id'], saved_metadata=context['saved_metadata'],
            requested_person_indices=person_indices, evaluated_person_indices=unique,
            filters=dict(team_index=team_index, owner_reference_table='TEAM_BASE',
                         date_from_inclusive=date_from, date_to_inclusive=date_to,
                         competition_index=competition_index,
                         minimum_observed_minutes=minimum_observed_minutes),
            metric='goals_plus_assists_per90_observed', people=people,
            ranking_person_indices=[p['person_index'] for p in eligible],
            eligible_count=len(eligible), evaluated_count=len(people),
            all_selected_form_groups_decoded=all(p.get('form_groups_complete', False) for p in people),
            evidence_scope=dict(
                cohort='supplied same-snapshot PERSON indices; duplicate requests evaluated once',
                group_filter='exact stored TEAM_BASE owner index; row team words are not owner filters',
                competition_filter='exact stored COMP index when supplied; no competition identity inferred',
                time_scope='inclusive stored row dates; retained coverage only, not whole-season coverage',
                denominator='only rows with supported goals, assists and stored playing minutes; no missing-stat imputation',
                minutes='native stored playing duration in the event-minute clock; no completion or stoppage-time precision claim',
                ordering='exact rational descending, competition ranks with all ties; PERSON index orders equal rates',
                duplicates='distinct serialized rows retained, including duplicate dates; no fixture-ID inference',
                senior_squad_status_inferred=False, whole_population_coverage=False,
                wire_profile_is_conditional=True, certified_person_records=False,
                native_loader_acceptance=False),
            resource_limits=dict(max_people=MAX_PEOPLE,
                                 max_form_rows_per_person=saved_form_rows.MAX_TOTAL_ROWS,
                                 max_response_bytes=MAX_RESPONSE_BYTES))
        if len(json.dumps(reply, ensure_ascii=True).encode('ascii')) > MAX_RESPONSE_BYTES:
            raise ValueError('Saved comparison response exceeds output budget; select a smaller cohort')
    return reply
