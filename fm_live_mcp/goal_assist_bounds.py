"""Exact integer partnership bounds, conditional on one assist and no self-assist.

Counter marginals never identify a particular event's provider. No second-PERSON
word, event ordering, current roster or inferred recipient participates here.
"""

MODEL = 'single_assist_no_self_assist'
MAX_PLAYERS = 64
MAX_GOALS = 1024


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{name} must be an integer >= {minimum}')
    return value


def goal_assist_bounds(players: list[dict] | tuple[dict, ...], *, fixture_id: str,
                       team_native_id: int, credited_goal_total: int,
                       coverage_state: str, model: str = MODEL) -> dict:
    """Return exact min/max counts for each scorer/supplier, never event links.

    Every row must have fixture_id, team_native_id, canonical_person_id, goals,
    assists. Rows must be the complete canonical same-fixture/team player census,
    including zeros. coverage_state='complete_canonical_player_counters' asserts
    that independently checked source contract; this helper cannot prove it.
    credited_goal_total excludes opposing own goals. Unknown coverage returns
    bounds=None; malformed rows raise ValueError; incompatible marginals return
    state='infeasible_under_model'. None supplier ID explicitly means unassisted.
    """
    if not isinstance(fixture_id, str) or not fixture_id.strip():
        raise ValueError('A nonempty fixture_id is required')
    _integer(team_native_id, 'team_native_id', 1)
    _integer(credited_goal_total, 'credited_goal_total')
    if model != MODEL:
        raise ValueError('Unsupported assist model')
    base = dict(fixture_id=fixture_id, team_native_id=team_native_id,
                model=model, model_is_assumption=True,
                event_attribution_supported=False, bounds=None)
    if coverage_state != 'complete_canonical_player_counters':
        return dict(base, state='unavailable_source_coverage', coverage_state=coverage_state)
    if not isinstance(players, (list, tuple)) or not 1 <= len(players) <= MAX_PLAYERS:
        raise ValueError('A bounded nonempty complete player census is required')
    rows, seen = [], set()
    for row in players:
        if not isinstance(row, dict):
            raise ValueError('Each player must be a mapping')
        if row.get('fixture_id') != fixture_id or type(row.get('team_native_id')) is not int or row['team_native_id'] != team_native_id:
            raise ValueError('Player source scope differs from the selected fixture/team')
        person = _integer(row.get('canonical_person_id'), 'canonical_person_id', 1)
        if person > 0xffffffff or person in seen:
            raise ValueError('Canonical PERSON ID is out of range or duplicated')
        seen.add(person)
        rows.append((person, _integer(row.get('goals'), 'goals'), _integer(row.get('assists'), 'assists')))
    rows.sort()
    goals = [r[1] for r in rows]
    supplies = [r[2] for r in rows]
    total = sum(goals)
    if total != credited_goal_total:
        return dict(base, state='unavailable_goal_total_mismatch', observed_player_goals=total,
                    credited_goal_total=credited_goal_total)
    if total > MAX_GOALS:
        raise ValueError('Goal total exceeds bounded helper capacity')
    unassisted = total-sum(supplies)
    if unassisted < 0:
        return dict(base, state='infeasible_under_model', reason='assists_exceed_credited_goals')
    supplies.append(unassisted)
    if any(goals[i] + supplies[i] > total for i in range(len(rows))):
        return dict(base, state='infeasible_under_model', reason='no_integer_allocation_without_self_assists')
    bounds = []
    for j, (scorer, goal_count, _) in enumerate(rows):
        # After reserving this scorer's goals, each other supplier must use any
        # credits it cannot give to the remaining scorers. Two distinct suppliers
        # together can reach every remaining scorer (only self-assists are barred),
        # so these individual limits and the column sum suffice for an allocation.
        remaining = total - goal_count
        floors = [max(0, supply - (remaining - own_goals)) if i != j else 0
                  for i, (supply, own_goals) in enumerate(zip(supplies, [*goals, 0]))]
        ceilings = [min(supply, goal_count) if i != j else 0 for i, supply in enumerate(supplies)]
        floor_total, ceiling_total = sum(floors), sum(ceilings)
        for i, (floor, ceiling) in enumerate(zip(floors, ceilings)):
            supplier = rows[i][0] if i < len(rows) else None
            lo = max(floor, goal_count - (ceiling_total - ceiling))
            hi = min(ceiling, goal_count - (floor_total - floor))
            bounds.append(dict(scorer_person_id=scorer, supplier_person_id=supplier,
                               supplier_kind='unassisted' if supplier is None else 'player',
                               minimum=lo, maximum=hi, exact=lo == hi))
    return dict(base, state='available_conditional_exact_bounds', bounds=bounds,
                credited_goal_total=total, recorded_assists=sum(supplies[:-1]),
                unassisted_goal_total=unassisted,
                joint_bounds_policy='Each edge range is exact; independent extremes need not coexist in one allocation.')
