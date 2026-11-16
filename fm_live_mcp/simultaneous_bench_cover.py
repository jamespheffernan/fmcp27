"""Distinct substitutes for the current manager's selected tactical slots."""


PHASES = ('in_possession', 'out_of_possession')


def _resolve_targets(targets, selectors):
    if not 1 <= len(selectors) <= 11:
        raise ValueError('Select one to eleven outgoing starters by name or original slot index.')
    resolved = []
    for selector in selectors:
        if type(selector) is int:
            matches = [t for t in targets if t['slot_index'] == selector]
        elif isinstance(selector, str) and selector.strip():
            text = ' '.join(selector.casefold().split())
            names = [(t, ' '.join((t.get('display_name') or '').casefold().split())) for t in targets]
            matches = [t for t, name in names if name == text]
            if not matches:
                matches = [t for t, name in names if name.endswith(' ' + text)]
        else:
            raise ValueError('Each outgoing starter must be a nonempty name or a slot index.')
        if len(matches) != 1:
            raise ValueError(f'Outgoing selection {selector!r} does not identify exactly one starter. Use the original team-sheet slot index.')
        target, = matches
        if target.get('person_index') is None:
            raise ValueError(f'Starting slot {target["slot_index"]} has no checked outgoing player.')
        if any(t['person_index'] == target['person_index'] for t in resolved):
            raise ValueError('Each outgoing starter must be distinct.')
        resolved.append(target)
    return sorted(resolved, key=lambda t: t['slot_index'])


def _best_assignment(edges, bench_count):
    """Use each bench row once. For a fixed target mask keep the highest scoring assignment."""
    empty = (0,) * len(edges)
    states = {0: (0, 0, empty)}
    ways = {0: 1}
    for bench in range(bench_count):
        next_states = states.copy()
        next_ways = ways.copy()
        for mask, (weaker_phase_sum, rating_sum, picked) in states.items():
            for index, options in enumerate(edges):
                grades = options.get(bench)
                if grades is None or mask & (1 << index):
                    continue
                new_mask = mask | (1 << index)
                next_ways[new_mask] = next_ways.get(new_mask, 0) + ways[mask]
                # Earlier bench slots have higher priority when ratings tie. Zero denotes an empty slot.
                assignment = picked[:index] + (bench_count - bench,) + picked[index + 1:]
                candidate = (weaker_phase_sum + min(grades), rating_sum + sum(grades), assignment)
                if new_mask not in next_states or candidate > next_states[new_mask]:
                    next_states[new_mask] = candidate
        states, ways = next_states, next_ways
    mask, (_, _, slots) = max(states.items(), key=lambda item: (item[0].bit_count(), item[1]))
    pairs = [(i, bench_count - priority) for i, priority in enumerate(slots) if mask & (1 << i)]
    return pairs, ways.get((1 << len(edges)) - 1, 0)


def _player_summary(row):
    return {'slot_index': row['slot_index'], 'native_id': row.get('native_id'),
            'person_index': row.get('person_index'), 'name': row.get('display_name')}


def solve_cover(captured, outgoing, minimum_rating=15, minimum_condition_percent=None,
                require_clear_injury_flag=False):
    if type(minimum_rating) is not int or not 1 <= minimum_rating <= 20:
        raise ValueError('Minimum positional familiarity must be 1–20.')
    if minimum_condition_percent is not None and not 0 <= minimum_condition_percent <= 100:
        raise ValueError('Minimum condition must be 0–100 percent.')
    if captured['targets'] is None or captured['bench'] is None:
        return {'state': 'unavailable', 'reason': captured.get('unavailable_reason'),
                'maximum_verified_distinct_cover': None, 'verified_complete_plans': None,
                'complete_plan_count_exact': False, 'assignments': None, 'slot_options': None}
    targets = _resolve_targets(captured['targets'], outgoing)
    starters = {t['person_index'] for t in captured['targets'] if t.get('person_index') is not None}
    bench = []
    omitted = []
    seen = set()
    for row in sorted(captured['bench'], key=lambda b: b['slot_index']):
        person = row.get('person_index')
        if person is None:
            if row.get('display_name') or row.get('native_id') is not None:
                omitted.append({**_player_summary(row), 'reason': 'unresolved_bench_identity'})
            continue
        if person in starters or person in seen:
            omitted.append({**_player_summary(row), 'reason': 'already_starting_or_duplicate_bench_player'})
            continue
        bench.append(row)
        seen.add(person)
    edges = []
    possible_edges = []
    slots = []
    for target in targets:
        phase_rows = target.get('phases') or {}
        fields = [(phase_rows.get(phase) or {}).get('general_position_field') for phase in PHASES]
        candidates = []
        unknown = []
        options = {}
        possible = {}
        for j, row in enumerate(bench):
            positions = row.get('positions') or {}
            grades = tuple(positions.get(field) for field in fields)
            health = row.get('health') or {}
            condition = health.get('condition_percent')
            flagged = (row.get('injury_status') or {}).get('flagged')
            if require_clear_injury_flag and flagged is True:
                continue
            if minimum_condition_percent is not None and condition is not None and condition < minimum_condition_percent:
                continue
            if any(v is not None and v < minimum_rating for v in grades):
                continue
            reasons = []
            if any(v is None for v in grades):
                reasons.append('unavailable_phase_position_or_familiarity')
            if minimum_condition_percent is not None and condition is None:
                reasons.append('unavailable_condition')
            if require_clear_injury_flag and flagged is None:
                reasons.append('unavailable_injury_flag')
            entry = {**_player_summary(row), **dict(zip(PHASES, grades, strict=True)),
                     'condition_percent': condition, 'injury_flag': flagged}
            possible[j] = (0, 0)
            if reasons:
                unknown.append({**entry, 'reasons': reasons})
            else:
                candidates.append(entry)
                options[j] = grades
        compact_positions = {phase: {key: (phase_rows.get(phase) or {}).get(key)
                                     for key in ('position', 'general_position_field', 'state')}
                             for phase in PHASES}
        slots.append({'outgoing': _player_summary(target), 'working_positions': compact_positions,
                      'candidates': candidates, 'unresolved_candidates': unknown})
        edges.append(options)
        possible_edges.append(possible)

    selected, verified_plans = _best_assignment(edges, len(bench))
    covered = len(selected)
    uncertain = any(s['unresolved_candidates'] for s in slots)
    optimistic, possible_plans = _best_assignment(possible_edges, len(bench)) if uncertain else (selected, verified_plans)
    maximum_possible = len(optimistic)
    # Unknown identity cannot be used as a distinct person in a verified assignment.
    unknown_count = sum(r['reason'] == 'unresolved_bench_identity' for r in omitted)
    upper_bound = min(len(slots), maximum_possible + unknown_count)
    state = 'complete' if covered == len(slots) else (
        'unresolved' if upper_bound == len(slots) else 'insufficient_distinct_cover')
    assignments = []
    for i, j in selected:
        person = bench[j]['person_index']
        replacement = next(candidate for candidate in slots[i]['candidates'] if candidate['person_index'] == person)
        assignments.append({'outgoing': slots[i]['outgoing'], 'incoming': replacement})
    return {'state': state, 'requested_starters': len(slots), 'maximum_verified_distinct_cover': covered,
            'distinct_cover_upper_bound': upper_bound, 'verified_complete_plans': verified_plans,
            'complete_plan_count_exact': not unknown_count and verified_plans == possible_plans,
            'assignments': assignments,
            'slot_options': slots, 'omitted_bench_entries': omitted,
            'minimum_rating': minimum_rating, 'minimum_condition_percent': minimum_condition_percent,
            'require_clear_injury_flag': require_clear_injury_flag,
            'ranking': 'Maximize the number covered, then the sum of the weaker phase ratings, then both phase ratings combined. Equal-scoring complete plans prefer earlier bench slots.',
            'limits': 'Hypothetical straight swaps at the current working positions. The two phase ratings use general positional familiarity. Individual role quality, medical clearance, fixture eligibility, match substitution limits and tactical reshuffles are separate.'}
