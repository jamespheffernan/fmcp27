"""Allowlisted schema-3 spatial capture projections and source-preserving gates."""
import json
import math
import re

SPATIAL_TABLES = ('spatial_packets', 'spatial_coverage', 'average_positions', 'pass_edges',
                  'heatmap_grids', 'heatmap_cells', 'heatmap_interpolation_cells',
                  'pass_edge_analysis', 'average_position_analysis')
SPATIAL_VIEWS = ('pass_edge_analysis', 'average_position_analysis')
ROW_BUDGETS = {'heatmap_cells':250000}
GRID_CHILDREN = ('heatmap_cells', 'heatmap_interpolation_cells')
REQUIRED = {
    'spatial_packets': {'fixture_id':'TEXT','native_match_key':'INTEGER','state':'TEXT','source_kind':'TEXT','raw_json':'TEXT'},
    'spatial_coverage': {'fixture_id':'TEXT','source':'TEXT','state':'TEXT','row_count':'INTEGER','raw_json':'TEXT'},
    'average_positions': {'fixture_id':'TEXT','native_match_key':'INTEGER','side_index':'INTEGER','stored_player_slot':'INTEGER','person_id':'INTEGER','person_name':'TEXT','state':'TEXT','sample_count':'INTEGER','sample_start_tick':'INTEGER','sample_step_native_ticks':'INTEGER','native_axis_0':'REAL','native_axis_1':'REAL','source_kind':'TEXT','raw_json':'TEXT'},
    'pass_edges': {'fixture_id':'TEXT','native_match_key':'INTEGER','side_index':'INTEGER','from_person_id':'INTEGER','from_name':'TEXT','to_person_id':'INTEGER','to_name':'TEXT','official_map_count':'INTEGER','counter_reconciled_completed_passes':'INTEGER','excluded_unlabelled_mask8_count':'INTEGER','source_state':'TEXT','raw_json':'TEXT'},
    'heatmap_grids': {'grid_id':'INTEGER','fixture_id':'TEXT','native_match_key':'INTEGER','source_kind':'TEXT','scope':'TEXT','side_index':'INTEGER','stored_player_slot':'INTEGER','person_id':'INTEGER','person_name':'TEXT','state':'TEXT','axis_0_bins':'INTEGER','axis_1_bins':'INTEGER','axis_0_min':'REAL','axis_0_max':'REAL','axis_1_min':'REAL','axis_1_max':'REAL','official_rendered_heatmap_equivalence':'INTEGER','ui_oracle_verified':'INTEGER','retained_samples':'INTEGER','selected_samples':'INTEGER','binned_samples':'INTEGER','interpolated_points_binned':'INTEGER','normalization_json':'TEXT','axes_json':'TEXT','raw_json':'TEXT'},
    'heatmap_cells': {'grid_id':'INTEGER','axis_0_index':'INTEGER','axis_1_index':'INTEGER','sample_count':'INTEGER','value':'REAL','value_kind':'TEXT','raw_json':'TEXT'},
    'heatmap_interpolation_cells': {'grid_id':'INTEGER','axis_0_index':'INTEGER','axis_1_index':'INTEGER','interpolation_count':'INTEGER','raw_json':'TEXT'},
}
PRIMARY_KEYS = {'spatial_packets':['fixture_id'], 'spatial_coverage':['fixture_id','source'], 'average_positions':['fixture_id','side_index','stored_player_slot'], 'pass_edges':['fixture_id','side_index','from_person_id','to_person_id'], 'heatmap_grids':['grid_id'], 'heatmap_cells':['grid_id','axis_0_index','axis_1_index'], 'heatmap_interpolation_cells':['grid_id','axis_0_index','axis_1_index']}
DEFAULT_FIELDS = {name:list(columns) for name,columns in REQUIRED.items()}
# Whole packets can exceed a page: explicit raw_json remains available, never implicit.
for name in DEFAULT_FIELDS:
    DEFAULT_FIELDS[name].remove('raw_json')
for view,table in [('pass_edge_analysis','pass_edges'),('average_position_analysis','average_positions')]:
    DEFAULT_FIELDS[view]=['date','home_team','away_team']+DEFAULT_FIELDS[table]


def validate(db, schema, version):
    if not any(schema.get(name) for name in SPATIAL_TABLES):
        return {'state':'not_captured','scope':'whole_registered_capture'}
    if version not in (3,4):
        raise ValueError('Captured spatial tables require schema 3 or later supported schema')
    for name,columns in REQUIRED.items():
        if schema.get(name) != columns:
            raise ValueError('Captured spatial schema differs: '+name)
        primary=[row[1] for row in sorted(db.execute(f'PRAGMA table_info("{name}")'),key=lambda row:row[5]) if row[5]]
        if primary != PRIMARY_KEYS[name]:
            raise ValueError('Captured spatial primary key differs: '+name)
    for view,table in [('pass_edge_analysis','pass_edges'),('average_position_analysis','average_positions')]:
        row=db.execute('SELECT type,sql FROM sqlite_master WHERE name=?',(view,)).fetchone()
        expected=f'CREATE VIEW {view} AS SELECT f.date,f.home_team,f.away_team,p.* FROM {table} p JOIN fixtures f USING(fixture_id)'
        normalize=lambda sql:re.sub(r'\s+',' ',sql).strip().lower()
        if row is None or row[0]!='view' or normalize(row[1])!=normalize(expected):
            raise ValueError('Captured spatial analysis view differs: '+view)
    def reject(sql, message):
        if db.execute(sql).fetchone() is not None:
            raise ValueError(message)
    for table in ('spatial_packets','spatial_coverage','average_positions','pass_edges','heatmap_grids'):
        reject(f'SELECT 1 FROM {table} t LEFT JOIN fixtures f USING(fixture_id) WHERE f.fixture_id IS NULL LIMIT 1','Captured spatial fixture reference is broken')
        if 'native_match_key' in REQUIRED[table]:
            reject(f'SELECT 1 FROM {table} t JOIN fixtures f USING(fixture_id) WHERE t.native_match_key IS NOT f.native_match_key LIMIT 1','Captured spatial native fixture identity differs')
    for table in ('average_positions','pass_edges','heatmap_grids'):
        reject(f'SELECT 1 FROM {table} WHERE side_index NOT IN(0,1) OR side_index IS NULL LIMIT 1','Captured spatial side is invalid')
    for table,person,name,slot,condition in [
        ('average_positions','person_id','person_name','stored_player_slot','1'),
        ('pass_edges','from_person_id','from_name',None,'1'),
        ('pass_edges','to_person_id','to_name',None,'1'),
        ('heatmap_grids','person_id','person_name','stored_player_slot',"t.scope='player'")]:
        slot_check=f' AND p.stored_player_slot IS t.{slot}' if slot else ''
        reject(f'SELECT 1 FROM {table} t WHERE {condition} AND (SELECT count(*) FROM retained_players p WHERE p.fixture_id=t.fixture_id AND p.side_index=t.side_index AND p.canonical_person_id IS t.{person} AND p.person_name IS t.{name}{slot_check})!=1 LIMIT 1','Captured spatial actor identity differs')
    reject('SELECT 1 FROM fixtures f WHERE (SELECT count(*) FROM spatial_coverage c WHERE c.fixture_id=f.fixture_id)!=4 LIMIT 1','Captured spatial source coverage is incomplete')
    reject("SELECT 1 FROM spatial_coverage WHERE source NOT IN('average_positions','pass_network','sample_density','native_heat_map') OR row_count<0 OR (state='not_captured' AND row_count IS NOT NULL) LIMIT 1",'Captured spatial coverage state/count differs')
    reject("SELECT 1 FROM heatmap_grids WHERE scope NOT IN('player','team') OR axis_0_bins<=0 OR axis_1_bins<=0 OR axis_0_bins*axis_1_bins>1000000 OR official_rendered_heatmap_equivalence NOT IN(0,1) OR ui_oracle_verified NOT IN(0,1) OR (scope='team' AND (person_id IS NOT NULL OR person_name IS NOT NULL OR stored_player_slot IS NOT NULL)) LIMIT 1",'Captured spatial grid scope/bounds differ')
    for table in GRID_CHILDREN:
        reject(f'SELECT 1 FROM {table} c LEFT JOIN heatmap_grids g USING(grid_id) WHERE g.grid_id IS NULL OR c.axis_0_index IS NULL OR c.axis_1_index IS NULL OR c.axis_0_index<0 OR c.axis_1_index<0 OR c.axis_0_index>=g.axis_0_bins OR c.axis_1_index>=g.axis_1_bins LIMIT 1','Captured spatial grid cell reference/bounds differ')
    reject("SELECT 1 FROM heatmap_cells WHERE value_kind NOT IN('native_normalized_intensity','observed_sample_count','native_value') OR sample_count<0 OR (value_kind='native_normalized_intensity' AND (sample_count IS NOT NULL OR value IS NULL)) OR (value_kind='observed_sample_count' AND sample_count IS NULL) LIMIT 1",'Captured native heat intensity is not a sample count')
    reject('SELECT 1 FROM heatmap_interpolation_cells WHERE interpolation_count<0 OR interpolation_count IS NULL LIMIT 1','Captured interpolation count is invalid')
    for table, columns in REQUIRED.items():
        numeric=[column for column, kind in columns.items() if kind in ('INTEGER','REAL')]
        for row in db.execute('SELECT '+','.join('"'+column+'"' for column in numeric)+' FROM "'+table+'"'):
            for column,value in zip(numeric,row):
                if value is None:
                    continue
                kind=columns[column]
                if (kind=='INTEGER' and type(value) is not int) or (kind=='REAL' and (type(value) not in (int,float) or not math.isfinite(value))):
                    raise ValueError('Captured spatial numeric value is invalid')
    for table in REQUIRED:
        for column in ('raw_json','axes_json','normalization_json'):
            if column in REQUIRED[table]:
                for row in db.execute(f'SELECT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL'):
                    json.loads(row[0])
    return {'state':'captured_per_source','scope':'whole_registered_capture',
            'states':[{'source':source,'state':state,'fixture_rows':count} for source,state,count in db.execute('SELECT source,state,count(*) FROM spatial_coverage GROUP BY source,state ORDER BY source,state')],
            'claim':'Stored spatial sources remain distinct. Native heat values are normalized intensity, never observed sample counts; missing sources remain unknown.'}
