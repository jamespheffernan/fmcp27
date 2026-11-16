from contextlib import nullcontext
from unittest.mock import Mock
from pathlib import Path
import gzip,json
import pytest
from fm_live_mcp import current_spatial_report as report


def live_control():
    with gzip.open(Path(__file__).parent/'fixtures/active_lille_tracking_cursor.json.gz','rt')as f:return json.load(f)


def test_real_lille_public_rows_preserve_all_prefix_values_without_scores_or_private_addresses():
    packet=live_control();fixture={**packet['fixture'],'scores':{'final_score':{'home':9,'away':8}}}
    result=report.project_spatial(fixture,packet['expected'])
    assert result['state']=='available'and result['current_time_slice']==4559
    assert len(result['sides'][0]['players'])==len(result['sides'][1]['players'])==11
    assert sum(s['coverage']['sample_count']for s in result['sides'])==4158
    expected={(r['side_index'],r['stored_player_slot']):r for r in packet['expected']['players']}
    for side in result['sides']:
        for row in side['players']:
            source=expected[side['side_index'],row['stored_player_slot']]
            assert all(row[k]==source[k]for k in row)
    assert 'scores'not in result['fixture']
    assert result['finding_space']is result['instantaneous_team_shape']is result['heatmaps']is None
    assert result['displayed_minute']is result['physical_units']is result['pitch_axis_names']is None
    assert 'engine'not in result and 'frame_provider_address'not in str(result)


def test_unresolved_selected_player_mask_preserves_known_rows_without_a_zero_average():
    packet=live_control();tracking=packet['expected'];first=tracking['players'].pop(0)
    tracking.update(state='available_partial',unresolved_tracking_actors=[dict(side_index=first['side_index'],stored_player_slot=first['stored_player_slot'],sample_count=first['sample_count'],state='unresolved_active_tracking_actor_join')])
    result=report.project_spatial(packet['fixture'],tracking)
    side=result['sides'][first['side_index']]
    assert side['coverage']['unresolved_tracking_player_count']==1
    assert side['unresolved_players'][0]['sample_count']==189
    assert all(r['stored_player_slot']!=first['stored_player_slot']for r in side['players'])


def test_unbound_or_ended_client_does_not_read_other_sources(monkeypatch):
    monkeypatch.setattr(report.active_match_source,'inspect_context',lambda *a,**k:({'source_state':'inactive','reason':'checked_empty_current_client_inventory'},None))
    monkeypatch.setattr(report.active_match_playback,'capture',Mock(side_effect=AssertionError))
    value=report._inspect(Mock(),10,'2030-11-06')
    assert value['state']=='unavailable'and value['fixture']is None and value['sides']is None


def test_no_matching_cursor_returns_unknown_without_actor_or_tracking_read(monkeypatch):
    packet=live_control();fixture=packet['fixture'];binding={'client':10000,'engine':20000,'team_indices':[fixture[s]['database_index']for s in('home_team','away_team')]}
    monkeypatch.setattr(report.active_match_source,'inspect_context',lambda *a,**k:({'source_state':'available_fixture_bound','bound_active_fixture':fixture},binding))
    monkeypatch.setattr(report.active_match_playback,'capture',lambda *a,**k:{'state':'no_matching_playback'})
    monkeypatch.setattr(report.active_match_people,'inspect_actor_bindings',Mock(side_effect=AssertionError))
    value=report._inspect(Mock(),10,'2030-11-06')
    assert value['reason']=='unavailable_bound_playback_cursor'and value['fixture']is None


def test_strict_source_change_retries_one_complete_capture_then_verifies(monkeypatch):
    read=Mock();read.verify.side_effect=[ValueError('Game state changed during read; retry'),None,None]
    bridge=Mock();bridge.lock=nullcontext();bridge._read_scope.side_effect=lambda _:nullcontext()
    bridge._player_layout.return_value=[100];bridge._world_state.return_value=(read,{'current_date':'2030-11-06'},None)
    packet={'source':{'state':'available_engine_tracking_source'}}
    monkeypatch.setattr(report,'_capture_components',Mock(side_effect=[({'state':'discarded'},None),({'state':'available'},packet)]))
    monkeypatch.setattr(report,'_verify_components',Mock(return_value={'state':'verified','current_time_slice':10,'verified_at_time_slice':12,'selected_sample_count':1}))
    result=report.current_spatial_report(bridge,'s')
    assert result['state']=='available'and result['same_session_spatial_prefix_verified']
    assert report._capture_components.call_count==2 and read.verify.call_count==3


def test_wrong_side_is_not_assigned_to_a_team():
    packet=live_control();packet['expected']['players'][0]['side_index']=2
    with pytest.raises(ValueError,match='side differs'):report.project_spatial(packet['fixture'],packet['expected'])


def test_new_tool_is_read_only_and_minimal_schema():
    import asyncio
    from fm_live_mcp.server import mcp
    tool=next(t for t in asyncio.run(mcp.list_tools())if t.name=='fm_get_current_match_spatial')
    assert set(tool.inputSchema['properties'])=={'session_id','heatmap_team_native_id','heatmap_person_native_id','heatmap_method','heatmap_grid'}
    assert tool.inputSchema['required']==['session_id']
    assert tool.inputSchema['properties']['heatmap_team_native_id']['default']is None
    assert tool.inputSchema['properties']['heatmap_method']['default']=='sample_density'
    assert tool.inputSchema['properties']['heatmap_grid']['default']=='compact'
    assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint
    assert 'finding space'in tool.description and 'Future samples'in tool.description

def test_verified_width_labels_abs_of_mean_not_mean_abs_and_no_forward_sign():
    packet=live_control();tracking=packet['expected']
    r=report.project_spatial(packet['fixture'],tracking,axes_verified=True)
    row=r['sides'][0]['players'][0]
    original=tracking['players'][0]
    assert row['lateral_displacement_of_mean_native']==abs(original['native_axis_0'])
    assert r['pitch_axis_names']['native_axis_0']=='lateral_pitch_width'
    assert r['positive_forward_sign']is r['human_left_right']is r['physical_units']is None
    assert 'lateral_displacement_of_mean_native'not in original
    assert 'lateral_displacement_of_mean_native'not in original['possession_means']['in_possession']


def verify_packet():
    fixture=live_control()['fixture']
    row={'side_index':0,'stored_player_slot':0,'canonical_person_id':7,'person_index_word':4,'person_name':'Known'}
    binding={'client':10000,'engine':20000,'team_indices':[fixture[k]['database_index']for k in('home_team','away_team')]}
    return {'fixture':fixture,'binding':binding,'bound':{'official_match_unique_id':11},
            'actors':{'players':[row]},'source':{'tracking':{'players':[{'side_index':0,'stored_player_slot':0}]}}},row


def test_end_actor_change_rejected_before_a_prefix_is_published(monkeypatch):
    packet,row=verify_packet()
    monkeypatch.setattr(report.active_match_people,'inspect_actor_bindings',lambda *a,**k:{'players':[{**row,'canonical_person_id':8}]})
    with pytest.raises(ValueError,match='canonical actor changed'):
        report._verify_components(Mock(),0,'2030-11-06',packet)


def test_future_actor_changes_do_not_invalidate_known_consumed_actors(monkeypatch):
    packet,row=verify_packet()
    monkeypatch.setattr(report.active_match_people,'inspect_actor_bindings',lambda *a,**k:{'players':[row,dict(side_index=1,stored_player_slot=25,canonical_person_id=999)]})
    monkeypatch.setattr(report.active_match_source,'inspect_context',lambda *a,**k:({'bound_active_fixture':packet['fixture']},packet['binding']))
    monkeypatch.setattr(report.active_match_tracking,'verify_prefix',lambda *a,**k:{'state':'verified','current_time_slice':1,'verified_at_time_slice':2})
    assert report._verify_components(Mock(),0,'2030-11-06',packet)['state']=='verified'


def test_end_fixture_closed_or_relinked_rejected(monkeypatch):
    packet,row=verify_packet()
    monkeypatch.setattr(report.active_match_people,'inspect_actor_bindings',lambda *a,**k:{'players':[row]})
    monkeypatch.setattr(report.active_match_source,'inspect_context',lambda *a,**k:({'reason':'gone'},None))
    with pytest.raises(ValueError,match='ownership or fixture changed'):
        report._verify_components(Mock(),0,'2030-11-06',packet)


def test_build_pinned_width_consumer_drift_rejected():
    with pytest.raises(ValueError,match='width/length native source changed'):
        report.current_spatial_axes.verify_native(lambda a,n:bytes(n),0)
