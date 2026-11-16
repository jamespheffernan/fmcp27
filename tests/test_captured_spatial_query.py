import hashlib
import json
import sqlite3
import pytest

from fm_live_mcp import captured_match_registry as registry
from fm_live_mcp import captured_match_sources as sources
from fm_live_mcp.captured_match_query import CapturedMatchQueries
from fm_live_mcp.captured_spatial_tables import REQUIRED, PRIMARY_KEYS
from fm_live_mcp.match_dataset import export_dataset


def spatial_original(tmp_path, monkeypatch, mutate=None):
    monkeypatch.setattr(registry,'REGISTRY_PATH',tmp_path/'registry.json')
    path=tmp_path/'spatial.sqlite'
    fixtures=[{'native_match_key':1,'fixture':{'date':'2030-11-02','competition':{'native_id':11},'home_team':{'native_id':688},'away_team':{'native_id':713}}},
              {'native_match_key':2,'fixture':{'date':'2030-11-03','competition':{'native_id':12},'home_team':{'native_id':713},'away_team':{'native_id':692}}}]
    rows=[dict(fixture_key=i,side_index=0,person_index_word=100,canonical_person_id=100,stored_player_slot=0,person_name='Captured Player',minutes=90) for i in (1,2)]
    capture={'save':dict(sources.EXPECTED_CAREER,current_date='2030-11-03'),'observed_at':'2026-11-07T21:00:00Z','fixtures':fixtures}
    export_dataset(path,capture,source='bounded_live_export',retained_players=rows)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE metadata SET value_json='3' WHERE key='schema_version'")
        for name,columns in REQUIRED.items():
            definition=','.join(f'{column} {kind}'+(' REFERENCES fixtures' if column=='fixture_id' else ' REFERENCES heatmap_grids' if column=='grid_id' and name!='heatmap_grids' else '') for column,kind in columns.items())
            definition+=',PRIMARY KEY('+','.join(PRIMARY_KEYS[name])+')'
            db.execute(f'CREATE TABLE {name}({definition})')
        for view,table in [('pass_edge_analysis','pass_edges'),('average_position_analysis','average_positions')]:
            db.execute(f'CREATE VIEW {view} AS SELECT f.date,f.home_team,f.away_team,p.* FROM {table} p JOIN fixtures f USING(fixture_id)')
        ids=db.execute('SELECT fixture_id,native_match_key FROM fixtures ORDER BY native_match_key').fetchall()
        def insert(table,row):
            columns=list(row)
            db.execute(f'INSERT INTO {table}('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',[row[c] for c in columns])
        for number,(fid,key) in enumerate(ids,1):
            insert('spatial_packets',dict(fixture_id=fid,native_match_key=key,state='available',source_kind='retained',raw_json='{}'))
            for source in ('average_positions','pass_network','sample_density','native_heat_map'):
                insert('spatial_coverage',dict(fixture_id=fid,source=source,state='not_captured' if source=='sample_density' else 'available',row_count=None if source=='sample_density' else 1,raw_json='{}'))
            insert('average_positions',dict(fixture_id=fid,native_match_key=key,side_index=0,stored_player_slot=0,person_id=100,person_name='Captured Player',state='available',sample_count=10,native_axis_0=.2,native_axis_1=.7,source_kind='average_position',raw_json='{}'))
            insert('pass_edges',dict(fixture_id=fid,native_match_key=key,side_index=0,from_person_id=100,from_name='Captured Player',to_person_id=100,to_name='Captured Player',official_map_count=3,source_state='available',raw_json='{}'))
            insert('heatmap_grids',dict(grid_id=number,fixture_id=fid,native_match_key=key,source_kind='native_normalized_heat',scope='player',side_index=0,stored_player_slot=0,person_id=100,person_name='Captured Player',state='available',axis_0_bins=2,axis_1_bins=2,official_rendered_heatmap_equivalence=0,ui_oracle_verified=0,normalization_json='{"scope":"native"}',axes_json='{"units":null}',raw_json='{}'))
            for axis in (0,1):
                insert('heatmap_cells',dict(grid_id=number,axis_0_index=axis,axis_1_index=0,sample_count=None,value=.5,value_kind='native_normalized_intensity',raw_json='{}'))
                insert('heatmap_interpolation_cells',dict(grid_id=number,axis_0_index=axis,axis_1_index=0,interpolation_count=4,raw_json='{}'))
        if mutate:mutate(db)
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    return path,digest


def register(tmp_path,monkeypatch,mutate=None):
    path,digest=spatial_original(tmp_path,monkeypatch,mutate)
    registry.register_capture(path,'chosen_spatial',digest,label='Chosen captured spatial match')
    return path,digest


def test_registered_spatial_catalog_provenance_and_grid_filter_pagination(tmp_path,monkeypatch):
    _,digest=register(tmp_path,monkeypatch)
    query=CapturedMatchQueries()
    result=query.query('chosen_spatial',digest,table='heatmap_cells',team_native_id=688,limit=1)
    assert result['row_count']==2 and len(result['rows'])==1
    assert result['rows'][0]['grid_id']==1
    assert result['rows'][0]['sample_count'] is None
    assert result['source']['capture_observed_at_utc']=='2026-11-07T21:00:00Z'
    assert 'path' not in result['source']
    assert result['source']['retained_spatial_coverage']['state']=='captured_per_source'
    assert next(row for row in result['selected_spatial_coverage']['sources'] if row['source']=='sample_density')['row_count'] is None
    page=query.query('chosen_spatial',digest,table='heatmap_cells',team_native_id=688,limit=1,cursor=result['next_cursor'])
    assert page['rows'][0]['axis_0_index']==1 and page['next_cursor'] is None
    with pytest.raises(ValueError,match='changed captured selectors'):
        query.query('chosen_spatial',digest,table='heatmap_cells',team_native_id=713,cursor=result['next_cursor'])
    away=query.query('chosen_spatial',digest,table='heatmap_interpolation_cells',date_from='2030-11-03',competition_native_id=12)
    assert {row['grid_id'] for row in away['rows']}=={2}
    grid=query.query('chosen_spatial',digest,table='heatmap_grids',team_native_id=688)['rows'][0]
    assert grid['axes_json']=={'units':None} and grid['normalization_json']=={'scope':'native'}
    selected=query.query('chosen_spatial',digest,table='heatmap_cells',grid_id=1,team_native_id=688)
    assert selected['row_count']==2 and selected['selected_grid']['team_native_id']==688
    with pytest.raises(ValueError,match='selected fixture scope'):
        query.query('chosen_spatial',digest,table='heatmap_cells',grid_id=2,team_native_id=688)
    with pytest.raises(ValueError,match='grid_id selects'):
        query.query('chosen_spatial',digest,table='average_positions',grid_id=1)
    view=query.query('chosen_spatial',digest,table='pass_edge_analysis',team_native_id=688)
    assert view['row_count']==1 and view['rows'][0]['official_map_count']==3


@pytest.mark.parametrize('sql,message',[
    ("UPDATE heatmap_cells SET sample_count=5",'intensity is not a sample count'),
    ("UPDATE heatmap_cells SET axis_0_index=9 WHERE axis_0_index=0",'bounds differ'),
    ("UPDATE pass_edges SET from_name='Different'",'actor identity differs'),
    ("UPDATE spatial_packets SET native_match_key=99",'fixture identity differs'),
    ("UPDATE spatial_coverage SET row_count=0 WHERE state='not_captured'",'coverage state/count'),
    ("UPDATE heatmap_grids SET grid_id=99 WHERE grid_id=1",'references|reference/bounds'),
    ("DROP VIEW pass_edge_analysis; CREATE VIEW pass_edge_analysis AS SELECT * FROM retained_players",'analysis view differs'),
])
def test_bad_spatial_sources_cannot_register(tmp_path,monkeypatch,sql,message):
    path,digest=spatial_original(tmp_path,monkeypatch,lambda db:db.executescript(sql))
    with pytest.raises(ValueError,match=message):
        registry.register_capture(path,'bad_spatial',digest)
    assert registry.load_registrations()=={}
