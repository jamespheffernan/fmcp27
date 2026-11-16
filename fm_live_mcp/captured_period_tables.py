"""Exact retained shot/period joins in an explicitly registered capture."""
import json
import re

PERIOD_TABLES=('match_period_evidence','match_periods','shot_periods','match_period_team_totals','shot_period_analysis')
PERIOD_VIEW='shot_period_analysis'
REQUIRED={
 'match_period_evidence':{'fixture_id':'TEXT','native_match_key':'INTEGER','capture_id':'TEXT','source_kind':'TEXT','confidence':'TEXT','official_match_unique_id':'TEXT','clock_domain':'TEXT','raw_json':'TEXT'},
 'match_periods':{'fixture_id':'TEXT','period':'TEXT','start_tick':'INTEGER','end_tick':'INTEGER','boundary_policy':'TEXT'},
 'shot_periods':{'fixture_id':'TEXT','side_index':'INTEGER','record_index':'INTEGER','event_id':'INTEGER','period':'TEXT','native_clock_start_raw':'INTEGER','native_clock_end_raw':'INTEGER','assignment_state':'TEXT','shooter_person_id':'INTEGER','shooter_name':'TEXT','raw_json':'TEXT'},
 'match_period_team_totals':{'fixture_id':'TEXT','period':'TEXT','side_index':'INTEGER','state':'TEXT','shots':'INTEGER','shots_on_target':'INTEGER','shot_goals':'INTEGER','expected_goals_sum_computed':'REAL','header_count':'INTEGER','feet_count':'INTEGER','unclassified_body_part_count':'INTEGER','source':'TEXT'},
}
PRIMARY_KEYS={'match_period_evidence':['fixture_id'],'match_periods':['fixture_id','period'],'shot_periods':['fixture_id','side_index','record_index'],'match_period_team_totals':['fixture_id','period','side_index']}
DEFAULT_FIELDS={name:[column for column in columns if column!='raw_json'] for name,columns in REQUIRED.items()}
DEFAULT_FIELDS[PERIOD_VIEW]=['date','home_team','away_team']+DEFAULT_FIELDS['shot_periods']+['expected_goals','native_x','native_y','body_part','outcome','official_location']


def validate(db,schema,version):
 if not any(schema.get(name) for name in PERIOD_TABLES):
  return {'state':'not_captured'}
 if version not in(3,4) or not schema.get('shots') or not schema.get('shot_map_coverage'):
  raise ValueError('Captured period evidence requires schema3 and retained shots')
 for name,columns in REQUIRED.items():
  if schema.get(name)!=columns:
   raise ValueError('Captured period schema differs: '+name)
  primary=[row[1] for row in sorted(db.execute(f'PRAGMA table_info("{name}")'),key=lambda row:row[5]) if row[5]]
  if primary!=PRIMARY_KEYS[name]:raise ValueError('Captured period primary key differs: '+name)
 expected='CREATE VIEW shot_period_analysis AS SELECT f.date,f.home_team,f.away_team,p.*,s.expected_goals, s.native_x,s.native_y,s.body_part,s.outcome,s.official_location FROM shot_periods p JOIN shots s USING(fixture_id,side_index,record_index) JOIN fixtures f USING(fixture_id)'
 actual=db.execute('SELECT type,sql FROM sqlite_master WHERE name=?',(PERIOD_VIEW,)).fetchone()
 normalize=lambda s:re.sub(r'\s+',' ',s).strip().lower()
 if actual is None or actual[0]!='view' or normalize(actual[1])!=normalize(expected):raise ValueError('Captured period analysis view differs')
 def reject(sql,message):
  if db.execute(sql).fetchone() is not None:raise ValueError(message)
 reject("SELECT 1 FROM match_period_evidence e LEFT JOIN fixtures f USING(fixture_id) WHERE f.fixture_id IS NULL OR e.native_match_key IS NOT f.native_match_key OR e.confidence IS NOT 'verified_retrospective_continuity' OR e.clock_domain IS NOT 'native_playback_time_slice' OR e.capture_id IS NULL OR e.capture_id='' LIMIT 1",'Captured period source identity/confidence differs')
 reject("SELECT 1 FROM match_periods p LEFT JOIN match_period_evidence e USING(fixture_id) WHERE e.fixture_id IS NULL OR p.period NOT IN('FirstHalf','SecondHalf') OR p.period IS NULL OR typeof(p.start_tick)!='integer' OR typeof(p.end_tick)!='integer' OR NOT(0<=p.start_tick AND p.start_tick<p.end_tick AND p.end_tick<65536) LIMIT 1",'Captured period intervals are invalid')
 reject('SELECT 1 FROM match_periods a JOIN match_periods b ON a.fixture_id=b.fixture_id AND a.period<b.period WHERE max(a.start_tick,b.start_tick)<min(a.end_tick,b.end_tick) LIMIT 1','Captured period intervals overlap')
 reject("SELECT 1 FROM shot_periods WHERE side_index NOT IN(0,1) OR side_index IS NULL OR record_index<0 OR typeof(native_clock_start_raw)!='integer' OR typeof(native_clock_end_raw)!='integer' OR native_clock_start_raw<0 OR native_clock_end_raw>=65536 LIMIT 1",'Captured period shot clock/side is invalid')
 reject('SELECT 1 FROM shot_periods p LEFT JOIN shots s USING(fixture_id,side_index,record_index) WHERE s.fixture_id IS NULL OR p.event_id IS NOT s.event_id LIMIT 1','Captured period shot identity differs')
 reject('SELECT 1 FROM shots s JOIN match_period_evidence e USING(fixture_id) LEFT JOIN shot_periods p USING(fixture_id,side_index,record_index) WHERE p.fixture_id IS NULL LIMIT 1','Captured period assignments omit retained shots')
 for fid,side,index,event,period,start,end,state,person,name,raw in db.execute('SELECT p.fixture_id,p.side_index,p.record_index,p.event_id,p.period,p.native_clock_start_raw,p.native_clock_end_raw,p.assignment_state,p.shooter_person_id,p.shooter_name,s.raw_json FROM shot_periods p JOIN shots s USING(fixture_id,side_index,record_index)'):
  shot=json.loads(raw);actor=shot.get('actor') or {}
  if start!=shot.get('native_clock_start_raw') or end!=shot.get('native_clock_end_raw') or person!=actor.get('canonical_person_id') or name!=actor.get('person_name'):
   raise ValueError('Captured period shot clocks/actor differ from retained source')
  intervals=[p for (p,) in db.execute('SELECT period FROM match_periods WHERE fixture_id=? AND start_tick<=? AND ?<=? AND ?<end_tick',(fid,start,start,end,end))]
  expected=intervals[0] if len(intervals)==1 else None
  if period!=expected or state!=('verified_native_stop_interval' if expected else 'unknown_boundary_or_unavailable_interval'):
   raise ValueError('Captured period assignment violates native interval boundaries')
 reject("SELECT 1 FROM match_period_team_totals t LEFT JOIN match_periods p USING(fixture_id,period) WHERE p.fixture_id IS NULL OR t.side_index NOT IN(0,1) OR t.state NOT IN('available_derived_retained_attempts','unavailable_shot_source') OR (t.state='unavailable_shot_source' AND (t.shots IS NOT NULL OR t.shots_on_target IS NOT NULL OR t.shot_goals IS NOT NULL OR t.expected_goals_sum_computed IS NOT NULL OR t.header_count IS NOT NULL OR t.feet_count IS NOT NULL OR t.unclassified_body_part_count IS NOT NULL)) LIMIT 1",'Captured period totals coverage differs')
 reject("SELECT 1 FROM match_period_team_totals t LEFT JOIN shot_map_coverage c USING(fixture_id,side_index) WHERE t.state IS NOT CASE WHEN c.state='available' THEN 'available_derived_retained_attempts' ELSE 'unavailable_shot_source' END LIMIT 1",'Captured period totals disagree with retained shot-source coverage')
 reject('SELECT 1 FROM match_periods p WHERE (SELECT count(*) FROM match_period_team_totals t WHERE t.fixture_id=p.fixture_id AND t.period=p.period)!=2 LIMIT 1','Captured period side coverage is incomplete')
 reject("SELECT 1 FROM match_period_team_totals t WHERE t.state='available_derived_retained_attempts' AND t.shots IS NOT(SELECT count(*) FROM shot_periods p WHERE p.fixture_id=t.fixture_id AND p.period=t.period AND p.side_index=t.side_index) LIMIT 1",'Captured period shot totals disagree with assignments')
 return {'state':'captured_verified_retrospective_periods','claim':'Exact source-linked retained attempts by verified native period intervals; never inferred from elapsed minute magnitudes or live runtime state.'}
