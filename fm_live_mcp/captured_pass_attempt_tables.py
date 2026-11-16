"""Registered captured pass attempts, distinct from pass-map edges and geometry claims."""
import math
import re

PASS_TABLES=('pass_attempt_sources','pass_attempt_coverage','pass_attempts','pass_path_points','pass_attempt_analysis')
PASS_VIEW='pass_attempt_analysis'
REQUIRED={
 'pass_attempt_sources':{'fixture_id':'TEXT','native_match_key':'INTEGER','state':'TEXT','source_kind':'TEXT','native_events_sha256':'TEXT','native_paths_sha256':'TEXT','raw_json':'TEXT'},
 'pass_attempt_coverage':{'fixture_id':'TEXT','side_index':'INTEGER','state':'TEXT','attempts':'INTEGER','completed':'INTEGER','not_completed':'INTEGER','raw_json':'TEXT'},
 'pass_attempts':{'fixture_id':'TEXT','event_id':'INTEGER','record_index':'INTEGER','side_index':'INTEGER','stored_player_slot':'INTEGER','person_id':'INTEGER','person_name':'TEXT','native_category_code':'INTEGER','completed':'INTEGER','outcome':'TEXT','specific_failure_reason':'TEXT','recipient_person_id':'INTEGER','recipient_name':'TEXT','recipient_state':'TEXT','native_flags_word':'INTEGER','native_event_x':'REAL','native_event_y':'REAL','native_path_start_x':'REAL','native_path_start_y':'REAL','native_path_end_x':'REAL','native_path_end_y':'REAL','geometry_state':'TEXT','origin_destination_state':'TEXT','coordinate_units':'TEXT','phase':'TEXT','displayed_time':'TEXT','raw_json':'TEXT'},
 'pass_path_points':{'fixture_id':'TEXT','event_id':'INTEGER','point_index':'INTEGER','native_x':'REAL','native_y':'REAL'},
}
PRIMARY_KEYS={'pass_attempt_sources':['fixture_id'],'pass_attempt_coverage':['fixture_id','side_index'],'pass_attempts':['fixture_id','event_id'],'pass_path_points':['fixture_id','event_id','point_index']}
DEFAULT_FIELDS={table:[column for column in columns if column!='raw_json'] for table,columns in REQUIRED.items()}
DEFAULT_FIELDS[PASS_VIEW]=['date','home_team','away_team']+DEFAULT_FIELDS['pass_attempts']


def validate(db,schema,version):
 if not any(schema.get(table) for table in PASS_TABLES):return {'state':'not_captured','scope':'whole_registered_capture'}
 if version not in(3,4):raise ValueError('Captured pass attempts require schema3')
 for table,columns in REQUIRED.items():
  if schema.get(table)!=columns:raise ValueError('Captured pass attempt schema differs: '+table)
  primary=[row[1] for row in sorted(db.execute(f'PRAGMA table_info("{table}")'),key=lambda row:row[5]) if row[5]]
  if primary!=PRIMARY_KEYS[table]:raise ValueError('Captured pass attempt primary key differs: '+table)
 expected='CREATE VIEW pass_attempt_analysis AS SELECT f.date,f.home_team,f.away_team,p.* FROM pass_attempts p JOIN fixtures f USING(fixture_id)'
 actual=db.execute('SELECT type,sql FROM sqlite_master WHERE name=?',(PASS_VIEW,)).fetchone()
 normalize=lambda s:re.sub(r'\s+',' ',s).strip().lower()
 if actual is None or actual[0]!='view' or normalize(actual[1])!=normalize(expected):raise ValueError('Captured pass attempt analysis view differs')
 def reject(sql,message):
  if db.execute(sql).fetchone() is not None:raise ValueError(message)
 reject("SELECT 1 FROM pass_attempt_sources s LEFT JOIN fixtures f USING(fixture_id) WHERE f.fixture_id IS NULL OR s.native_match_key IS NOT f.native_match_key OR s.state IS NOT 'available' LIMIT 1",'Captured pass attempt source identity differs')
 reject('SELECT 1 FROM pass_attempt_sources s WHERE (SELECT count(*) FROM pass_attempt_coverage c WHERE c.fixture_id=s.fixture_id)!=2 LIMIT 1','Captured pass attempt side coverage is incomplete')
 reject("SELECT 1 FROM pass_attempt_coverage c LEFT JOIN pass_attempt_sources s USING(fixture_id) WHERE s.fixture_id IS NULL OR c.side_index NOT IN(0,1) OR c.side_index IS NULL OR c.state IS NOT 'available' OR c.attempts IS NULL OR c.completed IS NULL OR c.not_completed IS NULL OR c.attempts<0 OR c.completed<0 OR c.not_completed<0 OR c.attempts!=c.completed+c.not_completed LIMIT 1",'Captured pass attempt coverage differs')
 reject("SELECT 1 FROM pass_attempts p LEFT JOIN pass_attempt_coverage c USING(fixture_id,side_index) WHERE c.fixture_id IS NULL OR p.event_id<0 OR p.event_id IS NULL OR p.completed IS NOT(p.native_category_code=7) OR p.native_category_code NOT BETWEEN 6 AND 11 OR (p.native_flags_word&8)!=0 OR p.origin_destination_state IS NOT 'not_proved' OR p.coordinate_units IS NOT NULL OR p.phase IS NOT NULL OR p.displayed_time IS NOT NULL LIMIT 1",'Captured pass attempt semantics exceed verified source')
 reject('SELECT 1 FROM pass_attempts a WHERE (SELECT count(*) FROM retained_players p WHERE p.fixture_id=a.fixture_id AND p.side_index=a.side_index AND p.canonical_person_id IS a.person_id AND p.person_name IS a.person_name AND p.stored_player_slot IS a.stored_player_slot)!=1 LIMIT 1','Captured pass attempt actor identity differs')
 reject('SELECT 1 FROM pass_attempts a WHERE a.recipient_person_id IS NOT NULL AND (a.completed IS NOT 1 OR (SELECT count(*) FROM retained_players p WHERE p.fixture_id=a.fixture_id AND p.side_index=a.side_index AND p.canonical_person_id IS a.recipient_person_id AND p.person_name IS a.recipient_name)!=1) LIMIT 1','Captured pass attempt recipient identity differs')
 reject('SELECT 1 FROM pass_attempt_coverage c WHERE c.attempts IS NOT(SELECT count(*) FROM pass_attempts p WHERE p.fixture_id=c.fixture_id AND p.side_index=c.side_index) OR c.completed IS NOT(SELECT count(*) FROM pass_attempts p WHERE p.fixture_id=c.fixture_id AND p.side_index=c.side_index AND p.completed=1) LIMIT 1','Captured pass attempt totals disagree with retained rows')
 reject('SELECT 1 FROM retained_players p JOIN pass_attempt_sources s USING(fixture_id) WHERE p.passes_attempted IS NOT(SELECT count(*) FROM pass_attempts a WHERE a.fixture_id=p.fixture_id AND a.side_index=p.side_index AND a.person_id=p.canonical_person_id) OR p.passes_completed IS NOT(SELECT count(*) FROM pass_attempts a WHERE a.fixture_id=p.fixture_id AND a.side_index=p.side_index AND a.person_id=p.canonical_person_id AND a.completed=1) LIMIT 1','Captured pass attempts disagree with captured player counters')
 reject('SELECT 1 FROM pass_path_points t LEFT JOIN pass_attempts p USING(fixture_id,event_id) WHERE p.fixture_id IS NULL OR t.point_index IS NULL OR t.point_index<0 LIMIT 1','Captured pass path reference differs')
 for table in ('pass_attempts','pass_path_points'):
  columns=[column for column,kind in REQUIRED[table].items() if kind=='REAL']
  for row in db.execute('SELECT '+','.join(columns)+' FROM '+table):
   if any(value is not None and (type(value) not in(int,float) or not math.isfinite(value)) for value in row):raise ValueError('Captured pass path numeric coordinate differs')
 return {'scope':'whole_registered_capture','state':'captured_counter_reconciled_attempts','claim':'Attempt/completion counters reconcile every captured player. Native sampled paths are not proved origins/destinations, physical units, phases or displayed times. Official pass-map edges remain separate.'}
