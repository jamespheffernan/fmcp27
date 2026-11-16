import itertools
import pytest
from fm_live_mcp.goal_assist_bounds import goal_assist_bounds


def report(goals, assists, **kwargs):
    rows = [dict(fixture_id='f', team_native_id=688, canonical_person_id=i+1,
                 goals=g, assists=a) for i, (g,a) in enumerate(zip(goals, assists))]
    args=dict(fixture_id='f', team_native_id=688, credited_goal_total=sum(goals),
              coverage_state='complete_canonical_player_counters')
    args.update(kwargs)
    return goal_assist_bounds(rows, **args)


def test_exact_single_goal_and_explicit_unassisted():
    r = report([1,0], [0,1])
    assert r['state'] == 'available_conditional_exact_bounds'
    assert next(x for x in r['bounds'] if x['scorer_person_id']==1 and x['supplier_person_id']==2)['minimum']==1
    r = report([1], [0])
    assert r['unassisted_goal_total']==1
    assert r['bounds'][-1]['minimum']==r['bounds'][-1]['maximum']==1
    assert r['event_attribution_supported'] is False


def test_zero_is_known_and_no_self_assist():
    r = report([0,0], [0,0])
    assert all(x['minimum']==x['maximum']==0 for x in r['bounds'])
    assert report([1,0],[1,0])['state']=='infeasible_under_model'
    assert report([1,0],[0,2])['reason']=='assists_exceed_credited_goals'


def test_source_unknown_and_scoreline_mismatch():
    assert report([1],[0], coverage_state='partial')['bounds'] is None
    assert report([1],[0], credited_goal_total=2)['state']=='unavailable_goal_total_mismatch'


@pytest.mark.parametrize('change', [
    {'goals':None}, {'goals':True}, {'goals':-1}, {'assists':1.5},
    {'canonical_person_id':0}, {'canonical_person_id':True},
    {'canonical_person_id':2**32}, {'fixture_id':'other'}, {'team_native_id':713},
])
def test_malformed_or_foreign_rows(change):
    row=dict(fixture_id='f',team_native_id=688,canonical_person_id=1,goals=0,assists=0)
    row.update(change)
    with pytest.raises(ValueError):
        goal_assist_bounds([row],fixture_id='f',team_native_id=688,credited_goal_total=0,
                           coverage_state='complete_canonical_player_counters')


def test_duplicates_and_order_independence():
    row=dict(fixture_id='f',team_native_id=688,canonical_person_id=1,goals=0,assists=0)
    with pytest.raises(ValueError):
        goal_assist_bounds([row,row],fixture_id='f',team_native_id=688,credited_goal_total=0,
                           coverage_state='complete_canonical_player_counters')
    assert report([1,1,0],[0,0,1])['unassisted_goal_total']==1


def test_exhaustive_small_integer_allocations():
    # Independent labelled-goal enumeration. Each slot chooses any other player
    # or explicit unassisted. Group only by observed marginal assist totals.
    for n in range(1,4):
        for goals in itertools.product(range(5), repeat=n):
            if sum(goals)>4:
                continue
            scorers=[j for j,g in enumerate(goals) for _ in range(g)]
            allocations={}
            for assignment in itertools.product(*[[i for i in range(n+1) if i!=j] for j in scorers]):
                assists=tuple(assignment.count(i) for i in range(n))
                matrix=tuple(sum(s==j and a==i for s,a in zip(scorers,assignment))
                    for j in range(n) for i in range(n+1))
                allocations.setdefault(assists,[]).append(matrix)
            for assists in itertools.product(range(sum(goals)+1), repeat=n):
                r=report(goals,assists)
                possible=allocations.get(assists)
                if not possible:
                    assert r['state']=='infeasible_under_model', (goals,assists)
                    continue
                assert r['state']=='available_conditional_exact_bounds'
                for k,edge in enumerate(r['bounds']):
                    assert (edge['minimum'],edge['maximum'])==(min(m[k]for m in possible),max(m[k]for m in possible)), (goals,assists,edge)


@pytest.mark.parametrize('kwargs', [dict(fixture_id=''),dict(team_native_id=True),
    dict(credited_goal_total=True),dict(model='multiple_assists')])
def test_invalid_selection_or_model(kwargs):
    with pytest.raises(ValueError):
        report([0],[0],**kwargs)


def test_empty_or_over_budget_census():
    with pytest.raises(ValueError):
        report([],[])
    with pytest.raises(ValueError):
        report([1025],[0])
    with pytest.raises(ValueError):
        report([0]*65,[0]*65)
