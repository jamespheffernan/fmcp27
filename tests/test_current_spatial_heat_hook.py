from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import gzip,json
import pytest
from fm_live_mcp import current_spatial_report as report


def packet():
    with gzip.open(Path(__file__).parent/'fixtures/active_lille_tracking_cursor.json.gz','rt')as f:r=json.load(f)
    s=r['source'];s['fixture_identity']=report.active_heatmap._fixture_identity(r['fixture'])
    for key in('orientation_profile','possession_samples'):s['tracking'][key]=bytes.fromhex(s['tracking'][key])
    for row in s['tracking']['players']:row['samples']=bytes.fromhex(row['samples'])
    return {'fixture':r['fixture'],'source':s,'bound':r['bound'],'actors':r['actors'],'binding':{'client':10000,'engine':20000}}


def bridge_and_capture(monkeypatch):
    p=packet();order=[]
    process=SimpleNamespace(pid=123,version='27',executable='game')
    first=Mock();first.verify.side_effect=lambda:order.append('world_initial')
    last=Mock();last.verify.side_effect=lambda:order.append('world_end')
    b=Mock();b.lock=nullcontext();b.world_identity=('career',);b._current.return_value=process
    b._read_scope.side_effect=lambda _:nullcontext();b._player_layout.return_value=(report.players.RVA[0],)
    b._world_state.side_effect=[(first,{'current_date':'2030-11-06'},None),(last,{'current_date':'2030-11-06'},None)]
    b._public_save.side_effect=lambda x:x
    capture=Mock(return_value=({'state':'available','heatmaps':None},p));monkeypatch.setattr(report,'_capture_components',capture)
    verified={'state':'verified_fixed_prefix_under_monotonic_same_match_playback',
        'official_match_unique_id':p['bound']['official_match_unique_id'],'current_time_slice':4559,
        'verified_at_time_slice':4560,'selected_sample_count':4158}
    def verify(*a):order.append('prefix');return verified
    monkeypatch.setattr(report,'_verify_components',verify)
    return b,p,order,capture


def test_default_call_preserves_null_heatmaps_without_projection_or_extra_capture(monkeypatch):
    b,p,order,capture=bridge_and_capture(monkeypatch)
    monkeypatch.setattr(report.active_heatmap,'project',Mock(side_effect=AssertionError))
    result=report.current_spatial_report(b,'s')
    assert result['heatmaps']is None and capture.call_count==1
    assert capture.call_args.kwargs=={} and order==['prefix','world_initial','world_end']


def test_frozen_heat_hook_is_after_all_bookends_and_uses_exact_same_packet(monkeypatch):
    b,p,order,capture=bridge_and_capture(monkeypatch)
    original=report.active_heatmap.project
    def heat(source,bound,actors,fixture,**kw):
        assert order==['prefix','world_initial','world_end']
        assert source is p['source']and bound is p['bound']and actors is p['actors']
        assert kw['prefix_verification']['canonical_actor_ids_rechecked']and kw['prefix_verification']['same_match_ownership_rechecked']
        return original(source,bound,actors,fixture,**kw)
    monkeypatch.setattr(report.active_heatmap,'project',heat)
    result=report.current_spatial_report(b,'s',heatmap_team_native_id=858)
    h=result['heatmaps'];assert h['state']=='available'and h['current_time_slice']==4559
    assert h['heat_map']['coverage']['selected_samples']==2079
    assert capture.call_count==1 and capture.call_args.kwargs=={'heatmap_method':'sample_density'}


def test_missing_current_source_keeps_heat_unknown_not_empty_or_historical(monkeypatch):
    b,p,order,capture=bridge_and_capture(monkeypatch);capture.return_value=({'state':'unavailable','reason':'checked_empty_current_client_inventory','heatmaps':None},None)
    monkeypatch.setattr(report.active_heatmap,'project',Mock(side_effect=AssertionError))
    r=report.current_spatial_report(b,'s',heatmap_team_native_id=688)
    assert r['heatmaps']['state']=='unavailable'and r['heatmaps']['heat_map']is None
    assert r['heatmaps']['reason']=='checked_empty_current_client_inventory'


def test_failed_epoch_prevents_heat_projection(monkeypatch):
    b,p,order,capture=bridge_and_capture(monkeypatch)
    original=b._world_state.side_effect
    def state(*a):
        value=next(original)
        if order: b.world_identity=('another_career',)
        return value
    b._world_state.side_effect=state
    heat=Mock(side_effect=AssertionError);monkeypatch.setattr(report.active_heatmap,'project',heat)
    with pytest.raises(ValueError,match='epoch changed'):report.current_spatial_report(b,'s',heatmap_team_native_id=858)
    assert not heat.called

@pytest.mark.parametrize('kwargs',[{'heatmap_person_native_id':1},{'heatmap_team_native_id':True},
 {'heatmap_team_native_id':858,'heatmap_grid':'native'}, {'heatmap_method':'interpolated'},
 {'heatmap_team_native_id':858,'heatmap_method':'guess'}])
def test_invalid_selector_combinations_rejected_before_game_reads(kwargs):
    b=Mock()
    with pytest.raises(ValueError):report.current_spatial_report(b,'s',**kwargs)
    assert not b._current.called

@pytest.mark.parametrize('method,expected_calls',[('sample_density',0),('interpolated',1)])
def test_only_interpolated_request_adds_native_algorithm_guard_during_begin_capture(monkeypatch,method,expected_calls):
    p=packet();b=p['binding'];b['team_indices']=[p['fixture'][k]['database_index']for k in('home_team','away_team')]
    monkeypatch.setattr(report.active_match_source,'inspect_context',lambda *a,**k:({'bound_active_fixture':p['fixture'],'source_state':'available'},b))
    monkeypatch.setattr(report.active_match_playback,'capture',lambda *a,**k:{'state':'bound_playback_cursor','bound_playback':p['bound']})
    monkeypatch.setattr(report.current_spatial_axes,'verify_native',lambda *a:None)
    native=Mock();monkeypatch.setattr(report.live_tracking_heatmaps,'verify_native_heatmap',native)
    monkeypatch.setattr(report.active_match_people,'inspect_actor_bindings',lambda *a,**k:p['actors'])
    monkeypatch.setattr(report.active_match_tracking,'capture_source',lambda *a,**k:p['source'])
    result,captured=report._capture_components(Mock(),0,'2030-11-06',heatmap_method=method)
    assert result['state']=='available'and captured['source']is p['source']
    assert native.call_count==expected_calls
