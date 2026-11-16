import itertools
import random

import pytest

from fm_live_mcp.simultaneous_bench_cover import PHASES, _best_assignment, solve_cover


def person(i, name, *, grades=None, phases=None, health=92, flag=False):
    row = dict(slot_index=i, person_index=i, native_id=i+10000, display_name=name)
    if grades is not None:
        row.update(positions=grades, health={'condition_percent':health}, injury_status={'flagged':flag})
    if phases is not None:
        row['phases'] = {key: {'general_position_field': field, 'position': field}
                         for key,field in zip(PHASES,phases,strict=True)}
    return row


def lineup():
    return {'targets':[person(1,'Alex Goal',phases=('cf','cf')),person(2,'Sam Ten',phases=('am','am')),
                       person(3,'Alex Wing',phases=('rw','rm'))],
            'bench':[person(11,'Both Forwards',grades={'cf':20,'am':20,'rw':1,'rm':1}),
                     person(12,'Wide Player',grades={'rw':19,'rm':15,'cf':1,'am':1}),
                     person(13,'Wide Attacker',grades={'rw':20,'rm':9,'cf':4,'am':3})]}


def test_shared_cover_and_both_phases():
    r=solve_cover(lineup(),['Wing','Sam Ten','Alex Goal'])
    assert r['state']=='insufficient_distinct_cover'
    assert r['maximum_verified_distinct_cover']==r['distinct_cover_upper_bound']==2
    for slot in r['slot_options'][:2]:
        assert [c['name'] for c in slot['candidates']]==['Both Forwards']
    assert [c['name'] for c in r['slot_options'][2]['candidates']]==['Wide Player']
    assert len({pair['incoming']['person_index'] for pair in r['assignments']})==2


def test_complete_and_strict_health_unknowns():
    c=lineup()
    c['bench'].append(person(14,'Other Forward',grades={'cf':16,'am':0,'rw':0,'rm':0},health=90))
    r=solve_cover(c,[1,2,3],minimum_condition_percent=90)
    assert r['state']=='complete' and r['verified_complete_plans']==1 and r['complete_plan_count_exact']
    assert [row['incoming']['slot_index'] for row in r['assignments']]==[14,11,12]
    c['bench'][-1]['health']['condition_percent']=None
    r=solve_cover(c,[1,2,3],minimum_condition_percent=90)
    assert r['state']=='unresolved' and r['maximum_verified_distinct_cover']==2 and r['distinct_cover_upper_bound']==3
    c['bench'][-1]['injury_status']['flagged']=True
    assert solve_cover(c,[1,2,3],require_clear_injury_flag=True)['state']=='insufficient_distinct_cover'
    assert solve_cover(c,[1,2,3],require_clear_injury_flag=False)['state']=='complete'


def test_duplicates_and_unavailable_inputs():
    c=lineup()
    c['bench'].append({**c['bench'][0],'slot_index':19})
    c['bench'].append({**c['bench'][0],'slot_index':20,'person_index':1})
    c['bench'].append({**c['bench'][0],'slot_index':21,'person_index':None})
    r=solve_cover(c,[1,2])
    assert r['state']=='unresolved' and r['maximum_verified_distinct_cover']==1
    assert len(r['omitted_bench_entries'])==3
    assert solve_cover({'targets':None,'bench':None,'unavailable_reason':'no_edit_session'},[1])['assignments'] is None
    c['targets'][1]['display_name']='Sam Goal'
    with pytest.raises(ValueError,match='exactly one'):
        solve_cover(c,['Goal'])
    with pytest.raises(ValueError,match='distinct'):
        solve_cover(c,[1,'Alex Goal'])


def test_missing_phase_is_unknown_not_zero():
    c=lineup()
    del c['targets'][2]['phases']['out_of_possession']
    r=solve_cover(c,[3])
    assert r['state']=='unresolved' and r['maximum_verified_distinct_cover']==0
    assert r['slot_options'][0]['unresolved_candidates'][0]['out_of_possession'] is None


def test_exact_optimizer_matches_brute_force_on_small_reproducible_matrices():
    rng=random.Random(91)
    for _ in range(60):
        n,m=rng.randrange(1,5),rng.randrange(1,5)
        edges=[{i:(rng.randrange(15,21),rng.randrange(15,21)) for i in range(m) if rng.random()<.5} for _ in range(n)]
        def score(pairs):
            return len(pairs),sum(min(edges[i][j]) for i,j in pairs),sum(sum(edges[i][j]) for i,j in pairs)
        all_scores=[]
        for selected in itertools.product(range(-1,m),repeat=n):
            pairs=[(i,j) for i,j in enumerate(selected) if j>=0]
            if len({j for _,j in pairs})==len(pairs) and all(j in edges[i] for i,j in pairs):
                all_scores.append(score(pairs))
        picked, ways = _best_assignment(edges,m)
        assert score(picked)==max(all_scores)
        assert ways == sum(result[0] == n for result in all_scores)
