import gzip,json
from pathlib import Path

from fm_live_mcp.live_retained_shots import decode_attempts,_validated_actors
from fm_live_mcp.retained_shot_observations import verify_observed_side

H=Path(__file__).parent/'fixtures'
CONTROL=next(r for r in json.loads(gzip.decompress((H/'retained_shot_maps.json.gz').read_bytes()))if r['key']==136157)
ROSTER=json.loads(gzip.decompress((H/'retained_player_closure_136157.json.gz').read_bytes()))['players']


def controls():
    c=CONTROL;r=decode_attempts([bytes.fromhex(v)for v in c['vectors']],bytes.fromhex(c['events']),c['teams'],_retain_candidates=True)
    return r,_validated_actors(ROSTER,c['teams'])


def test_real_three_shots_close_every_player_count_but_do_not_promote_xg():
    r,actors=controls();d=r['side_coverage'][1]
    assert d['state']=='unavailable_unreconciled_retained_side'and d['xg_float32_ulp_distance']==2
    shots,coverage=verify_observed_side(r['_candidates_by_side'][1],ROSTER,actors,CONTROL['teams'][1],d)
    assert len(shots)==3 and coverage['rostered_players_checked']==20
    assert coverage['zero_shot_players_checked']==19 and not coverage['verified_shots_promoted']
    assert all(s['actor']['person_name']=='Matěj Šín'for s in shots)
    assert all(s['actor']['person_index_word']==43597 and s['actor']['canonical_person_id']==2000130424 for s in shots)
    assert all('expected_goals'not in s and 'native_expected_goals'in s for s in shots)
    assert all(s['xg_reconciliation']['team_float32_ulp_distance']==2 and s['xg_reconciliation']['player_float32_ulp_distance']==2 and s['xg_reconciliation']['player_nonpenalty_float32_ulp_distance']==2 for s in shots)
    assert all(s['outcome_state']=='official_native_end_shot_category'for s in shots)
    assert len(r['shots'])==6 and all(s['side_index']==0 for s in r['shots'])


def test_actual_matej_sin_amine_adli_numeric_slot_swap_is_rejected():
    r,actors=controls();actors=dict(actors);actors[1,7],actors[1,9]=actors[1,9],actors[1,7]
    shots,c=verify_observed_side(r['_candidates_by_side'][1],ROSTER,actors,CONTROL['teams'][1],r['side_coverage'][1])
    assert not shots and c['state']=='unavailable_source_observed_verification'
    assert c['unavailable_reason']=='canonical_PERSON_TEAM_identity_not_proved'


def test_zero_shot_players_are_required_for_complete_closure():
    r,actors=controls();roster=json.loads(json.dumps(ROSTER));zero=next(p for p in roster if p['side_index']==1 and p['stored_player_slot']==0)
    raw=bytearray.fromhex(zero['raw_child_hex']);delta=4 if zero['person_reference_tag']<2 else 0;raw[41+delta]=1;zero['raw_child_hex']=raw.hex()
    shots,c=verify_observed_side(r['_candidates_by_side'][1],roster,actors,CONTROL['teams'][1],r['side_coverage'][1])
    assert not shots and c['unavailable_reason']=='complete_player_shots_targets_goals_do_not_close'


def test_default_decoder_has_no_observed_candidates_or_semantic_changes():
    c=CONTROL;strict=decode_attempts([bytes.fromhex(v)for v in c['vectors']],bytes.fromhex(c['events']),c['teams'])
    assert '_candidates_by_side'not in strict and 'source_observed_shots'not in strict
    assert len(strict['shots'])==6 and strict['side_coverage'][1]['shot_count']is None


def test_getter_opt_in_keeps_verified_paging_and_caps_separate_collection(monkeypatch):
    from fm_live_mcp import live_retained_shots as q
    calls=[]
    def capture(*args,**kwargs):
        calls.append(kwargs['include_source_observed'])
        r={'source_id':'a'*64,'shots':[{'id':1},{'id':2}],'own_goal_markers':[]}
        if kwargs['include_source_observed']:
            r['source_observed_shots']=[{'native_expected_goals':.1}for _ in range(101)]
        return {'records':[r]}
    monkeypatch.setattr(q,'capture_retained_shot_maps',capture)
    default=q.get_retained_shot_map(None,'s','ref',limit=1)
    observed=q.get_retained_shot_map(None,'s','ref',limit=1,include_source_observed=True)
    assert calls==[False,True]
    assert default['shots']==observed['shots']==[{'id':1}]
    assert default['total_available_shots']==observed['total_available_shots']==2
    assert default['next_offset']==observed['next_offset']==1
    assert 'source_observed_shots'not in default
    assert len(observed['source_observed_shots'])==100 and observed['source_observed_shots_truncated']
    assert observed['total_source_observed_shots']==101


def test_observed_rows_preserve_typed_detail_without_entering_strict_quality():
    from fm_live_mcp.retained_shot_quality import summarize_shot_quality
    c=CONTROL
    result=decode_attempts([bytes.fromhex(v) for v in c['vectors']],bytes.fromhex(c['events']),c['teams'],
                          pitch_geometry={'half_length_native':52.5},_retain_candidates=True)
    candidates=result.pop('_candidates_by_side')
    actors=_validated_actors(ROSTER,c['teams'])
    observed,coverage=verify_observed_side(candidates[1],ROSTER,actors,c['teams'][1],result['side_coverage'][1])
    assert len(observed)==3 and coverage['verified_shots_promoted'] is False
    assert all(s['body_part']=='feet' and s['location_state']=='native_renderer_predicate' for s in observed)
    assert all(s['outcome_state']=='official_native_end_shot_category' for s in observed)
    teams=[{'native_id':t['team_identity_word'],'owner':{'name':str(t['team_identity_word'])}} for t in c['teams']]
    packet={**result,'source_observed_shots':observed,'native_match_key':136157,'fixture_ref':'selected',
            'fixture':{'date':'2030-10-29','home_team':teams[0],'away_team':teams[1]}}
    selected=teams[1]['native_id']
    own=summarize_shot_quality([packet],selected,'for',.20,15)
    assert own['coverage']=='unavailable' and own['covered_fixture_totals'] is None
    against=summarize_shot_quality([packet],selected,'against',.20,15)
    assert against['covered_fixture_totals']['shots']==6
    assert against['fixtures'][0]['metrics']['shots']==6
    assert 'expected_goals' not in observed[0] and 'native_expected_goals' in observed[0]
