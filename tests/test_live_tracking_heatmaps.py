import struct
import pytest
from fm_live_mcp.live_tracking_heatmaps import decode_tracking_heatmaps


def packet(pairs=((0,0),(100,100),(100,100))):
    profile=bytearray(16);struct.pack_into('<iii',profile,0,1000,-1,-1);profile[13]=1
    return {'orientation_profile':bytes(profile),'players':[{'side_index':0,'stored_player_slot':0,'start_tick':24,'samples':b''.join(struct.pack('<hh',*v)for v in pairs)}]}


PLAYERS=[{'side_index':0,'stored_player_slot':0,'canonical_person_id':7,'person_name':'Player'}]
GEOMETRY={'half_width_native':34.,'half_length_native':52.5}


def decode(p=None,**kwargs):return decode_tracking_heatmaps(p or packet(),PLAYERS,GEOMETRY,**kwargs)


def test_sample_density_keeps_stationary_samples_not_native_motion_interpolation():
    r=decode();p=r['players'][0]
    assert p['coverage']['binned_samples']==3
    assert sum(c['sample_count']for c in p['cells'])==3
    assert not r['official_rendered_heatmap_equivalence']
    assert sum(c['sample_count']for c in r['teams'][0]['cells'])==3
    assert r['teams'][1]['coverage']['binned_samples']==0


def test_exact_tick_cutoffs_and_empty_selection_do_not_become_full_match():
    r=decode(start_tick=48,end_tick=48);c=r['players'][0]['coverage']
    assert c['selected_samples']==1 and c['outside_selected_ticks']==2
    assert c['first_selected_tick']==c['last_selected_tick']==48
    assert decode(start_tick=100)['players'][0]['state']=='unavailable_no_in_bounds_selected_samples'


def test_bounds_and_invalid_geometry_preserve_coverage():
    r=decode(packet(((0,0),(32767,32767))))
    assert r['players'][0]['coverage']['outside_native_pitch_bounds']==1
    with pytest.raises(ValueError):decode_tracking_heatmaps(packet(),PLAYERS,{'half_width_native':0,'half_length_native':52.5})


def test_orientation_is_per_sample_before_binning():
    p=packet(((1000,1000),(1000,1000)));profile=bytearray(p['orientation_profile']);struct.pack_into('<iii',profile,0,48,1000,-1);p['orientation_profile']=bytes(profile)
    r=decode(p);cells=r['players'][0]['cells']
    assert len(cells)==2 and cells[0]['axis_0_index']<32<cells[1]['axis_0_index']


@pytest.mark.parametrize('args',[{'start_tick':True},{'start_tick':-1},{'start_tick':48,'end_tick':24}])
def test_bad_native_cutoffs_reject(args):
    with pytest.raises(ValueError):decode(**args)


def test_wrong_or_duplicate_player_slot_cannot_acquire_a_name():
    with pytest.raises(ValueError):decode_tracking_heatmaps(packet(),PLAYERS+PLAYERS,GEOMETRY)
    p=packet();p['players'][0]['stored_player_slot']=9
    with pytest.raises(ValueError):decode(p)


def test_native_interpolation_skips_stationary_points_and_has_exact_60_steps():
    from fm_live_mcp.live_tracking_heatmaps import decode_native_tracking_heatmaps
    r=decode_native_tracking_heatmaps(packet(((0,0),(1000,0),(1000,0))),PLAYERS,GEOMETRY)
    p=r['players'][0]
    assert p['coverage']['interpolated_segments']==1
    assert p['coverage']['duplicate_position_segments_skipped']==1
    assert sum(x['interpolation_count']for x in p['raw_cells'])==60
    assert sum(x['interpolation_count']for x in r['teams'][0]['raw_cells'])==60
    assert not r['ui_oracle_verified']


def test_native_quantile_scaling_and_smoothed_threshold():
    from collections import Counter
    from fm_live_mcp.live_tracking_heatmaps import _native_normalize_smooth
    cells,meta=_native_normalize_smooth(Counter({(32,50):10,(32,51):20,(32,52):100}))
    assert meta['lower_count_quantile']==10 and meta['upper_count_quantile']==20
    assert meta['normalization_denominator']==10
    assert cells and all(.01<=c['normalized_intensity']<=1 for c in cells)
    assert any(c['axis_0_index']==30 for c in cells)


def test_native_overlarge_segment_and_cutoff_remain_explicit():
    from fm_live_mcp.live_tracking_heatmaps import decode_native_tracking_heatmaps
    r=decode_native_tracking_heatmaps(packet(((-32000,0),(32000,0))),PLAYERS,GEOMETRY)
    assert r['players'][0]['coverage']['over_60_native_unit_segments_skipped']==1
    assert not r['players'][0]['raw_cells']


def test_native_zero_tail_skips_repeats_but_preserves_explicit_center_transition():
    from fm_live_mcp.live_tracking_heatmaps import decode_native_tracking_heatmaps
    r=decode_native_tracking_heatmaps(packet(((1000,0),(0,0),(0,0),(0,0))),PLAYERS,GEOMETRY)
    c=r['players'][0]['coverage']
    assert c['trailing_zero_pairs']==3 and c['nonzero_to_zero_segments']==1
    assert c['duplicate_position_segments_skipped']==2 and c['interpolated_segments']==1
    assert sum(x['interpolation_count']for x in r['players'][0]['raw_cells'])==60
