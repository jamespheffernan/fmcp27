import copy,gzip,json
from pathlib import Path
import pytest
from fm_live_mcp import active_heatmap


def frozen():
    with gzip.open(Path(__file__).parent/'fixtures/active_lille_tracking_cursor.json.gz','rt')as f:r=json.load(f)
    assert r['observed_readset_verified']and r['fixture']['home_team']['native_id']==858
    s=r['source'];s['fixture_identity']=active_heatmap._fixture_identity(r['fixture'])
    for name in('orientation_profile','possession_samples'):s['tracking'][name]=bytes.fromhex(s['tracking'][name])
    for row in s['tracking']['players']:row['samples']=bytes.fromhex(row['samples'])
    b=r['bound'];v=dict(state='verified_fixed_prefix_under_monotonic_same_match_playback',official_match_unique_id=b['official_match_unique_id'],
        current_time_slice=b['current_time_slice'],verified_at_time_slice=b['current_time_slice'],selected_sample_count=4158,
        canonical_actor_ids_rechecked=True,same_match_ownership_rechecked=True)
    return r,v


def run(r,v,**kwargs):
    return active_heatmap.project(r['source'],r['bound'],r['actors'],r['fixture'],prefix_verification=v,team_native_id=858,**kwargs)


def test_real_22_lille_players_frozen_prefix_compact_shape_and_count_closure():
    r,v=frozen();out=run(r,v);h=out['heat_map']
    assert out['state']=='available'and out['current_time_slice']==4559
    assert len(out['selected_players'])==11 and h['coverage']['verified_prefix_sample_count_all_sides']==4158
    assert h['grid_width']==13 and h['grid_length']==20
    assert len(h['counts_by_length_then_width'])==20 and all(len(x)==13 for x in h['counts_by_length_then_width'])
    assert sum(map(sum,h['counts_by_length_then_width']))==h['coverage']['binned_samples']
    assert h['coverage']['selected_samples']==2079
    assert out['computed_offline_after_source_verification']and out['saved_file_fallback']is False


def test_future_points_phases_and_entrants_cannot_change_output():
    r,v=frozen();before=run(r,v);changed=copy.deepcopy(r)
    for row in changed['source']['tracking']['players']:row['samples']+=bytes.fromhex('ff7fff7f')*100
    changed['source']['tracking']['players'].append(dict(side_index=0,stored_player_slot=25,start_tick=5000,samples=b'\0'*400))
    changed['source']['tracking']['possession_samples']+=bytes((255,))*100
    assert run(changed,v)==before


def test_fixed_prefix_end_verification_must_precede_projection():
    r,v=frozen()
    for change in({'state':'unverified'},{'canonical_actor_ids_rechecked':False},{'same_match_ownership_rechecked':False},
                   {'selected_sample_count':1},{'official_match_unique_id':1},{'current_time_slice':4560},{'verified_at_time_slice':4558}):
        with pytest.raises(ValueError):run(r,{**v,**change})


def test_wrong_fixture_and_future_or_wrong_team_player_have_no_named_heatmap():
    r,v=frozen();r['source']['fixture_identity']=('2030-11-06',99,(1,858),(2,688))
    with pytest.raises(ValueError,match='fixture'):run(r,v)
    r,v=frozen();out=run(r,v,person_native_id=999999999)
    assert out['heat_map']is None and not out.get('selected_players')
    away=next(x for x in r['actors']['players']if x['side_index']==1)['canonical_person_id']
    assert run(r,v,person_native_id=away)['heat_map']is None


def test_native_resolution_requires_single_player_and_interpolated_method_is_explicit():
    r,v=frozen()
    with pytest.raises(ValueError,match='requires one player'):run(r,v,grid='native')
    player=next(x for x in r['actors']['players']if x['side_index']==0)
    out=run(r,v,person_native_id=player['canonical_person_id'],grid='native',method='interpolated')
    h=out['heat_map'];assert len(out['selected_players'])==1 and h['method']=='interpolated'
    assert len(h['mean_intensity_by_length_then_width'])==100 and all(len(x)==65 for x in h['mean_intensity_by_length_then_width'])
    assert 'normalization'in h and h['ui_verified']is False


def test_unresolved_current_slot_remains_partial_and_never_becomes_zero_coverage():
    r,v=frozen();r['actors']['players']=[x for x in r['actors']['players']if(x['side_index'],x['stored_player_slot'])!=(0,0)]
    out=run(r,v)
    assert out['state']=='available_partial'and out['heat_map']['coverage']['unresolved_selected_side_player_count']==1
    assert out['heat_map']['coverage']['unresolved_selected_side_sample_count']==189


def test_invalid_selection_and_missing_geometry_are_explicit():
    r,v=frozen()
    for kwargs in({'grid':'unbounded'},{'method':'touches'},{'person_native_id':True}):
        with pytest.raises(ValueError):run(r,v,**kwargs)
    r['source']['pitch_geometry']=None
    assert run(r,v)['reason']=='unavailable_active_pitch_geometry'
