"""Bounded source-explicit projections from named captured-live SQLite exports."""
from collections import OrderedDict
from datetime import date
import json
import secrets
import threading
import time

from .captured_match_sources import TABLES, open_source
from .match_scope_query import DEFAULT_FIELDS
from .captured_pass_attempt_tables import PASS_TABLES, PASS_VIEW, DEFAULT_FIELDS as PASS_DEFAULT_FIELDS
from .captured_period_tables import PERIOD_TABLES, PERIOD_VIEW, DEFAULT_FIELDS as PERIOD_DEFAULT_FIELDS
from .captured_spatial_tables import SPATIAL_TABLES, SPATIAL_VIEWS, GRID_CHILDREN, ROW_BUDGETS, DEFAULT_FIELDS as SPATIAL_DEFAULT_FIELDS

CAPTURED_DEFAULT_FIELDS={**DEFAULT_FIELDS,**SPATIAL_DEFAULT_FIELDS,**PERIOD_DEFAULT_FIELDS,**PASS_DEFAULT_FIELDS,
    'shots':['fixture_id','native_match_key','side_index','record_index','source_id','native_x','native_y','expected_goals','native_shot_type','is_penalty','shot_situation','shot_situation_state','raw_json'],
    'shot_map_coverage':['fixture_id','native_match_key','side_index','team_native_id','team_index','source_id','state','shot_count','shots_on_target','expected_goals','own_goal_marker_count','raw_json'],
    'own_goal_markers':['fixture_id','native_match_key','beneficiary_side_index','event_side_index','record_index','source_id','native_x','native_y','native_expected_goals','raw_json'],
}
SHOT_TABLES=('shots','shot_map_coverage','own_goal_markers','shot_field_coverage','shot_attempt_analysis','shot_map_analysis',
             'source_observed_shots','source_observed_shot_coverage','source_observed_field_coverage','source_observed_shot_analysis')
OBSERVED_TABLES=tuple(name for name in SHOT_TABLES if name.startswith('source_observed_'))
CAPTURED_VIEWS=('player_match_analysis','shot_attempt_analysis','shot_map_analysis','source_observed_shot_analysis')+SPATIAL_VIEWS+(PERIOD_VIEW,PASS_VIEW)
DETAIL_FIELDS=['event_id','native_category_code','body_part','is_header','body_part_state','outcome','native_outcome_label','outcome_state','native_location_bin','official_location','location_group','location_state','attacked_goal_positive_native_y']
CAPTURED_DEFAULT_FIELDS['shots']+=DETAIL_FIELDS
CAPTURED_DEFAULT_FIELDS.update({
    'shot_field_coverage':['fixture_id','side_index','field_group','state','known_attempt_count','unknown_attempt_count'],
    'source_observed_shots':['fixture_id','native_match_key','side_index','record_index','source_id','canonical_person_id','person_name','stored_player_slot','native_expected_goals','verification_scope','team_xg_ulp_distance','player_xg_ulp_distance','player_nonpenalty_xg_ulp_distance','is_penalty','shot_situation','raw_json']+DETAIL_FIELDS,
    'source_observed_shot_coverage':['fixture_id','native_match_key','side_index','source_id','state','strict_side_state','observed_shot_count','rostered_players_checked','zero_shot_players_checked','team_xg_ulp_distance','verified_shots_promoted','xg_tolerance_widened','raw_json'],
})
CAPTURED_DEFAULT_FIELDS['source_observed_field_coverage']=CAPTURED_DEFAULT_FIELDS['shot_field_coverage']
CAPTURED_DEFAULT_FIELDS['shot_attempt_analysis']=['date','competition','home_team','away_team']+CAPTURED_DEFAULT_FIELDS['shots']+['shot_source_state']
CAPTURED_DEFAULT_FIELDS['shot_map_analysis']=['date','competition','home_team','away_team']+CAPTURED_DEFAULT_FIELDS['shot_map_coverage']
CAPTURED_DEFAULT_FIELDS['source_observed_shot_analysis']=['date','competition','home_team','away_team']+CAPTURED_DEFAULT_FIELDS['source_observed_shots']
PRESSURE_FIELDS = ('pressures_attempted', 'pressure_completion_percentage_computed', 'pressure_completion_state')
PRESSURE_TABLES = ('retained_players', 'player_match_analysis')
MAX_RESPONSE_BYTES=262144

def _pin(value,name):
    if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError(f'{name} must be the exact catalog SHA256 identifier')

def _date(value):
    if value is not None and (not isinstance(value,str) or date.fromisoformat(value).isoformat()!=value):
        raise ValueError('Use ISO dates YYYY-MM-DD')

class CapturedMatchQueries:
    def __init__(self):
        self.pages=OrderedDict();self.lock=threading.RLock()

    def query(self,source_id,capture_id,table='fixtures',fields=None,*,career_id=None,
              date_from=None,date_to=None,competition_native_id=None,team_native_id=None,
              limit=100,cursor=None,grid_id=None):
        _pin(capture_id,'capture_id')
        if career_id is not None:_pin(career_id,'career_id')
        if table not in TABLES:raise ValueError('Unsupported captured table; use the source catalog')
        if grid_id is not None and (type(grid_id) is not int or grid_id<=0 or table not in (*GRID_CHILDREN,'heatmap_grids')):
            raise ValueError('grid_id selects a positive heatmap_grids/cells/interpolation grid only')
        _date(date_from);_date(date_to)
        if date_from and date_to and date_from>date_to:raise ValueError('date_from must not follow date_to')
        for value in (competition_native_id,team_native_id):
            if value is not None and(type(value)is not int or value<=0):raise ValueError('Select positive native competition/team IDs')
        if type(limit)is not int or not 1<=limit<=500:raise ValueError('limit must be1–500')
        selectors=json.dumps([source_id,capture_id,career_id,table,fields,date_from,date_to,competition_native_id,team_native_id,grid_id],sort_keys=True)
        with self.lock,open_source(source_id,capture_id,career_id) as (db,provenance):
            now=time.monotonic()
            for token in list(self.pages):
                if now-self.pages[token]['created']>300:del self.pages[token]
            if cursor is not None:
                page=self.pages.get(cursor)
                if page is None or page['selectors']!=selectors:raise ValueError('Expired cursor or changed captured selectors')
                offset=page['offset'];created=page['created']
            else:offset=0;created=now
            columns=provenance['available_tables'].get(table)
            if not columns:raise ValueError('Table unavailable in this captured source')
            physical_columns = set(columns)
            supported_columns = set(columns) | (set(PRESSURE_FIELDS + ('dribbles_made',)) if table in PRESSURE_TABLES else set())
            selected=fields if fields is not None else [c for c in CAPTURED_DEFAULT_FIELDS.get(table,DEFAULT_FIELDS['retained_players']) if c in columns]
            if not isinstance(selected,list) or not selected or any(type(c)is not str or c not in supported_columns for c in selected) or len(set(selected))!=len(selected):
                raise ValueError('Select distinct available column names from this source catalog')
            filters=[];params=[]
            for value,clause in ((date_from,'f.date>=?'),(date_to,'f.date<=?'),(competition_native_id,'f.competition_id=?')):
                if value is not None:filters.append(clause);params.append(value)
            if team_native_id is not None:filters.append('(f.home_team_id=? OR f.away_team_id=?)');params.extend((team_native_id,team_native_id))
            fixture_filter=' AND '.join(filters) or '1'
            if table=='fixtures':condition=fixture_filter.replace('f.','t.')
            elif table in GRID_CHILDREN:
                condition='EXISTS(SELECT 1 FROM heatmap_grids g JOIN fixtures f USING(fixture_id) WHERE g.grid_id=t.grid_id AND '+fixture_filter+')'
            elif table=='player_matches':
                condition='EXISTS(SELECT1 FROM player_fixture_candidates c JOIN fixtures f USING(fixture_id) WHERE c.row_id=t.row_id AND '+fixture_filter+')'
                condition=condition.replace('SELECT1','SELECT 1')
            else:condition='EXISTS(SELECT 1 FROM fixtures f WHERE f.fixture_id=t.fixture_id AND '+fixture_filter+')'
            pass_attempt_coverage=None
            if table in PASS_TABLES:
                context=db.execute('SELECT c.fixture_id,f.native_match_key,f.date,c.side_index,c.state,c.attempts,c.completed,c.not_completed FROM pass_attempt_coverage c JOIN fixtures f USING(fixture_id) WHERE '+fixture_filter+' ORDER BY f.native_match_key,c.fixture_id,c.side_index LIMIT 257',params).fetchall()
                if len(context)>256:
                    raise ValueError('Captured pass coverage exceeds its budget; narrow selectors')
                names=('fixture_id','native_match_key','date','side_index','state','attempts','completed','not_completed')
                pass_attempt_coverage={'scope':'all fixture sides matching these selectors','sides':[dict(zip(names,row)) for row in context]}
            spatial_coverage=None
            if table in SPATIAL_TABLES:
                context=db.execute('SELECT c.fixture_id,f.native_match_key,f.date,c.source,c.state,c.row_count FROM spatial_coverage c JOIN fixtures f USING(fixture_id) WHERE '+fixture_filter+' ORDER BY f.native_match_key,c.fixture_id,c.source LIMIT 1025',params).fetchall()
                if len(context)>1024:
                    raise ValueError('Captured spatial coverage exceeds its budget; narrow selectors')
                names=('fixture_id','native_match_key','date','source','state','row_count')
                spatial_coverage={'scope':'all fixtures matching these selectors','sources':[dict(zip(names,row)) for row in context],
                    'claim':'Distinct stored source states. Missing sources/rows are unknown, not zero; normalized heat intensity and sample counts are different quantities.'}
            shot_coverage=None
            if table in SHOT_TABLES+PERIOD_TABLES:
                coverage_columns=provenance['available_tables'].get('shot_map_coverage')
                if coverage_columns:
                    coverage_rows=db.execute('SELECT c.fixture_id,c.native_match_key,f.date,f.home_team_id,f.away_team_id,c.side_index,c.team_native_id,c.state,c.shot_count,c.shots_on_target,c.expected_goals,c.own_goal_marker_count FROM shot_map_coverage c JOIN fixtures f USING(fixture_id) WHERE '+fixture_filter+' ORDER BY c.native_match_key,c.fixture_id,c.side_index LIMIT 257',params).fetchall()
                    if len(coverage_rows)>256:raise ValueError('Captured shot coverage context exceeds its budget; narrow selectors')
                    names=('fixture_id','native_match_key','date','home_team_id','away_team_id','side_index','team_native_id','state','shot_count','shots_on_target','expected_goals','own_goal_marker_count')
                    shot_coverage={'state':'captured_per_side','scope':'all fixture sides matching these selectors','sides':[dict(zip(names,row)) for row in coverage_rows]}
                else:shot_coverage={'state':'not_captured','sides':None}
            observed_coverage=None
            if table in OBSERVED_TABLES:
                observed_columns=provenance['available_tables'].get('source_observed_shot_coverage')
                if observed_columns:
                    observed_rows=db.execute('SELECT c.fixture_id,c.native_match_key,f.date,f.home_team_id,f.away_team_id,c.side_index,c.state,c.strict_side_state,c.observed_shot_count,c.team_xg_ulp_distance,c.verified_shots_promoted,c.xg_tolerance_widened FROM source_observed_shot_coverage c JOIN fixtures f USING(fixture_id) WHERE '+fixture_filter+' ORDER BY c.native_match_key,c.fixture_id,c.side_index LIMIT 257',params).fetchall()
                    if len(observed_rows)>256:raise ValueError('Source-observed coverage exceeds its budget; narrow selectors')
                    names=('fixture_id','native_match_key','date','home_team_id','away_team_id','side_index','state','strict_side_state','observed_shot_count','team_xg_ulp_distance','verified_shots_promoted','xg_tolerance_widened')
                    observed_coverage={'scope':'all fixture sides matching these selectors','sides':[dict(zip(names,row)) for row in observed_rows],
                                       'claim':'Separate source observations: counts and actors verified; native xG unreconciled. Never add to strict shots or claim strict xG reconciliation.'}
            selected_grid=None
            if grid_id is not None:
                grid=db.execute('SELECT g.grid_id,g.fixture_id,g.side_index,CASE g.side_index WHEN 0 THEN f.home_team_id ELSE f.away_team_id END,g.scope,g.person_id,g.person_name,g.source_kind,g.state FROM heatmap_grids g JOIN fixtures f USING(fixture_id) WHERE '+fixture_filter+' AND g.grid_id=?',params+[grid_id]).fetchone()
                if grid is None:
                    raise ValueError('Selected grid is not retained in the selected fixture scope')
                selected_grid=dict(zip(('grid_id','fixture_id','side_index','team_native_id','scope','person_id','person_name','source_kind','state'),grid))
                condition+=' AND t.grid_id=?'
                params.append(grid_id)
            count=db.execute(f'SELECT count(*) FROM "{table}" t WHERE '+condition,params).fetchone()[0]
            if count>ROW_BUDGETS.get(table,100000):raise ValueError('Captured projection exceeds row budget; narrow selectors')
            order=[c for c in ('date','native_match_key','fixture_id','side_index','beneficiary_side_index','event_side_index','person_index_word','stored_player_slot','event_id','point_index','grid_id','axis_0_index','axis_1_index','from_person_id','to_person_id','period','source','source_index','record_index','row_id','person_id') if c in columns]
            if table not in CAPTURED_VIEWS:order.append('rowid')
            order_sql=','.join('t."'+c+'"' for c in order)
            select=','.join('t."'+c+'"' if c in physical_columns else "'unavailable_not_in_registered_capture' AS \""+c+'\"' if c == 'pressure_completion_state' else 'NULL AS \"'+c+'\"' for c in selected)
            result=db.execute(f'SELECT {select} FROM "{table}" t WHERE '+condition+' ORDER BY '+order_sql+' LIMIT ? OFFSET ?',params+[limit,offset])
            rows=[];size=len(json.dumps({'source':provenance,'selected_shot_coverage':shot_coverage,'selected_source_observed_coverage':observed_coverage,'selected_spatial_coverage':spatial_coverage,'selected_grid':selected_grid,'selected_pass_attempt_coverage':pass_attempt_coverage},ensure_ascii=False).encode())+4096
            if size>=MAX_RESPONSE_BYTES:raise ValueError('Captured provenance exceeds response budget')
            for values in result:
                row=dict(zip(selected,values))
                for json_field in ('raw_json','normalization_json','axes_json'):
                    if json_field in row and row[json_field] is not None:row[json_field]=json.loads(row[json_field])
                n=len(json.dumps(row,ensure_ascii=False).encode())
                if n+size>MAX_RESPONSE_BYTES:
                    if not rows:raise ValueError('One row exceeds response budget; select fewer fields')
                    break
                rows.append(row);size+=n
            end=offset+len(rows);next_cursor=None
            if end<count:
                next_cursor=secrets.token_urlsafe(24)
                self.pages[next_cursor]={'selectors':selectors,'offset':end,'created':created}
                while len(self.pages)>32:self.pages.popitem(last=False)
            response={'source':provenance,'table':table,'fields':selected,'row_count':count,'rows':rows,'next_cursor':next_cursor,
                    'selectors':{'date_from':date_from,'date_to':date_to,'competition_native_id':competition_native_id,'team_native_id':team_native_id,'grid_id':grid_id},
                    'team_filter_semantics':'team_native_id selects fixtures containing the team; player and team tables include BOTH ordered sides. Join side_index=0 to fixture home_team_id and side_index=1 to away_team_id before attributing contributions. Shot attempts use side_index; own-goal marker beneficiary_side_index is the credited side and event_side_index is its actor side.',
                    'claim':'Pinned read-only historical live capture; compute arbitrary analysis from returned rows. It is not the current runtime or last disk save.'}
            if table in PRESSURE_TABLES:
                response['dribbling_field_availability'] = 'recorded_column_preserve_nulls' if 'dribbles_made' in physical_columns else 'unknown_not_in_registered_capture'
                response['pressure_field_availability'] = {name: ('recorded_column_preserve_nulls' if name in physical_columns else 'unknown_not_in_registered_capture') for name in PRESSURE_FIELDS}
                response['pressure_semantics'] = 'Native statistical pressure attempts/completions; rate is100*completed/attempted with unknown/zero/inconsistent denominators withheld. No possession-regain, failed-press, location or tactical-cause inference.'
            if table in SPATIAL_TABLES:
                response['selected_spatial_coverage']=spatial_coverage
                response['selected_grid']=selected_grid
                response['spatial_semantics']='Native average positions, official pass-map counts, observed sample density and native normalized heat intensity remain separate sources. Heatmap cells join heatmap_grids by grid_id for fixture/side/player/axes/normalization provenance; team_native_id filters fixtures and includes BOTH sides. No inferred physical units, human left/right, pressure locations or official-render equivalence.'
            if table in PASS_TABLES:
                response['selected_pass_attempt_coverage']=pass_attempt_coverage
                response['pass_attempt_semantics']='Counter-reconciled captured attempts/completions, distinct from official pass-map edges. Native path samples do not prove pass origins/destinations, coordinate units, phase or displayed time; unavailable failure reasons/recipients stay unknown.'
            if table in PERIOD_TABLES:
                response['period_semantics']='Verified retrospective native period assignments for exact retained shot rows. Preserve confidence, boundary policy, unknown boundary/crossing assignments and shot-source coverage; computed expected_goals_sum_computed is a sum of retained attempts, not an official halftime xG counter.'
            if table in SHOT_TABLES+PERIOD_TABLES:response['selected_shot_coverage']=shot_coverage
            if table in OBSERVED_TABLES:
                response['selected_source_observed_coverage']=observed_coverage
                response['analysis_scope']='source_observed_counts_actors_verified_xg_unreconciled'
                response['expected_goals_semantics']='native_expected_goals is an unreconciled source value; strict shots and their reconciled expected_goals remain separate'
            return response
