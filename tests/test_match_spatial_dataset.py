import copy
import json
import pytest
from fm_live_mcp.match_dataset import build_connection, export_dataset
from fm_live_mcp.export_live_matches import capture_scope


def fixture():
    return {'native_match_key':1,'fixture':{'fixture_ref':'ref','date':'2030-11-02',
            'competition':{'native_id':11},'home_team':{'native_id':688,'database_index':545,'native_type_code':0},
            'away_team':{'native_id':713,'database_index':570,'native_type_code':0}}}


def players():
    return [dict(fixture_key=1,side_index=0,stored_player_slot=slot,canonical_person_id=person,person_name=name,
                 person_index_word=person,passes_attempted=5,passes_completed=4,expected_assists=.2,progressive_passes=2)
            for slot,person,name in ((0,100,'One'),(1,101,'Two'))]


def report():
    return dict(state='available',native_match_key=1,fixture=fixture()['fixture'],source_kind='retained_spatial',
      average_positions={'state':'available','source_kind':'official_average_position_map_all_tracking_samples',
        'players':[dict(side_index=0,stored_player_slot=0,canonical_person_id=100,person_name='One',state='available',
                        sample_count=3,sample_start_tick=1,sample_step_native_ticks=24,native_axis_0=1.5,native_axis_1=-2.)]},
      pass_network={'sides':[{'side_index':0,'state':'unavailable_completed_counter_reconciliation','edges':[
        dict(from_person_native_id=100,from_name='One',to_person_native_id=101,to_name='Two',official_map_count=4,
             counter_reconciled_completed_passes=None,excluded_unlabelled_mask8_count=1)]}]},
      sample_density={'state':'available','source_kind':'derived_retained_tracking_sample_density',
        'official_rendered_heatmap_equivalence':False,
        'axes':{'axis_0':{'bins':2,'minimum':-34.,'maximum':34.},'axis_1':{'bins':3,'minimum':-52.5,'maximum':52.5}},
        'players':[dict(side_index=0,stored_player_slot=0,canonical_person_id=100,person_name='One',state='available',
                        coverage={'retained_samples':3,'selected_samples':3,'binned_samples':3},
                        cells=[{'axis_0_index':0,'axis_1_index':1,'sample_count':3}])], 'teams':[]})


def test_named_independent_sources_roundtrip_and_unknown_pass_subset():
    db=build_connection({'fixtures':[fixture()]},retained_players=players(),spatial_reports=[report()])
    assert json.loads(db.execute("select value_json from metadata where key='schema_version'").fetchone()[0])==3
    assert db.execute('select person_name,native_axis_0,native_axis_1 from average_positions').fetchone()==('One',1.5,-2.)
    assert db.execute('select from_name,to_name,official_map_count,counter_reconciled_completed_passes from pass_edges').fetchone()==('One','Two',4,None)
    assert db.execute('select source_kind,official_rendered_heatmap_equivalence,binned_samples from heatmap_grids').fetchone()==('derived_retained_tracking_sample_density',0,3)
    assert db.execute('select sum(sample_count) from heatmap_cells').fetchone()==(3,)
    assert db.execute('select expected_assists,progressive_passes from retained_players limit 1').fetchone()==(.2,2)
    assert db.execute('pragma foreign_key_check').fetchall()==[]
    assert db.execute('pragma integrity_check').fetchone()==('ok',)


@pytest.mark.parametrize('mutation', ['key','date','actor','duplicate_cell','cell_sum','nan'])
def test_corrupt_spatial_identity_or_grid_fails_without_output(tmp_path,mutation):
    value=report()
    if mutation=='key':value['native_match_key']=2
    if mutation=='date':value['fixture']['date']='2030-11-03'
    if mutation=='actor':value['average_positions']['players'][0]['canonical_person_id']=999
    if mutation=='duplicate_cell':value['sample_density']['players'][0]['cells']*=2
    if mutation=='cell_sum':value['sample_density']['players'][0]['cells'][0]['sample_count']=2
    if mutation=='nan':value['average_positions']['players'][0]['native_axis_0']=float('nan')
    output=tmp_path/'data.sqlite'
    with pytest.raises(ValueError):export_dataset(output,{'fixtures':[fixture()]},retained_players=players(),spatial_reports=[value])
    assert not output.exists()


def test_absent_source_stays_not_captured_and_old_default_does_not_add_tables():
    db=build_connection({'fixtures':[fixture()]},spatial_reports=[])
    assert db.execute('select state,row_count from spatial_coverage').fetchall()==[('not_captured',None)]*4
    db=build_connection({'fixtures':[fixture()]})
    assert db.execute("select name from sqlite_master where name='spatial_packets'").fetchall()==[]


def test_spatial_capture_reuses_selected_batch_without_shot_dependency():
    class Source:
        def get_save(self,s):return {'save':{'name':'Career','current_date':'2030-11-02'}}
        def get_fixture_coverage(self,s):return {'years':[{'year':2030}]}
        def find_fixtures(self,*a,**k):return {'save':self.get_save('s')['save'],'fixtures':[fixture()['fixture']],'next_cursor':None}
    batch={'capture':{'save':Source().get_save('s')['save'],'fixtures':[fixture()]},'retained_players':players()}
    calls=[]
    def spatial(b,s,ref,*,fixture_captures,include_native_heat_map):
        assert fixture_captures is batch and include_native_heat_map;calls.append(ref);return dict(report(),captured_save=b.get_save(s)['save'])
    result=capture_scope(Source(),'s',688,'2030-11-02','2030-11-02',capture=lambda *a:batch,include_spatial=True,spatial_capture=spatial)
    assert calls==['ref'] and len(result['spatial_reports'])==1
    assert 'shot_maps' not in result
    assert result['capture']['spatial_coverage']=='per_fixture_guarded_retained_spatial_sources'


def test_native_intensity_stays_separate_from_sample_counts():
    value=report(); native=copy.deepcopy(value['sample_density'])
    native.update(source_kind='official_native_interpolated_normalized_heatmap',official_rendered_heatmap_equivalence=True,
                  normalization={'method':'native_maximum_scaled'},ui_oracle_verified=False,players=[],teams=[dict(side_index=0,state='available',cells=[
                    dict(axis_0_index=0,axis_1_index=1,normalized_intensity=.75)])])
    value['native_heat_map']=native
    db=build_connection({'fixtures':[fixture()]},retained_players=players(),spatial_reports=[value])
    assert db.execute("select sample_count,value,value_kind from heatmap_cells where value_kind='native_normalized_intensity'").fetchone()==(None,.75,'native_normalized_intensity')
    assert json.loads(db.execute('select normalization_json from heatmap_grids where official_rendered_heatmap_equivalence=1').fetchone()[0])=={'method':'native_maximum_scaled'}
