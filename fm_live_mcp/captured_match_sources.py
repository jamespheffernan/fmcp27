"""Named captured-live exports. No game attachment, arbitrary paths or saved-file aliases."""
from contextlib import contextmanager
from datetime import date
import hashlib
import json
import re
from pathlib import Path
import sqlite3
import stat
from .captured_pass_attempt_tables import PASS_TABLES, validate as validate_passes
from .captured_period_tables import PERIOD_TABLES, validate as validate_periods
from .captured_spatial_tables import SPATIAL_TABLES, ROW_BUDGETS, validate as validate_spatial
from ._os_compat import change_time_ns

REFERENCE=Path.home()/'Agent Outputs/Reference'
SOURCES={
    'newcastle_2030_10_28':REFERENCE/'Newcastle match data — 28 October 2030.sqlite',
    'premier_league_2030_10_28':REFERENCE/'Premier League match data — 28 October 2030.sqlite',
    'newcastle_2030_10_29_arsenal_cup':REFERENCE/'Newcastle v Arsenal — 29 October 2030.sqlite',
    'premier_league_2030_10_26_shots':REFERENCE/'2026-11-07 — PL matchday 2030-10-26 with shot maps.sqlite',
}
TABLES=('fixtures','team_totals','events','player_matches','retained_players','goal_crossings','sub_entry_context','player_match_analysis','shots','shot_map_coverage','own_goal_markers')
BUILTIN_TABLES=TABLES
REGISTERED_DETAIL_TABLES=('shot_field_coverage','shot_attempt_analysis','shot_map_analysis','source_observed_shots','source_observed_shot_coverage','source_observed_field_coverage','source_observed_shot_analysis')
TABLES=TABLES+REGISTERED_DETAIL_TABLES+SPATIAL_TABLES+PERIOD_TABLES+PASS_TABLES
MAX_BYTES=512*1024*1024
PINNED_SHOT_SOURCE='premier_league_2030_10_26_shots'
SOURCE_PINS={PINNED_SHOT_SOURCE:{
    'sha256':'ae9929753c2094a875e93a6bb1e77bfa535323b1dc264e6b0c112b349e800792',
    'date':'2030-10-26','competition_id':11,'fixtures':6,
    'table_counts':{'shots':42,'shot_map_coverage':12,'own_goal_markers':1},
}}
EXPECTED_CAREER={'name':'Cesar Jules - Newcastle','created_date':'2025-10-23','created_version':2223821}

def _fingerprint(path):
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=MAX_BYTES:
        raise ValueError('Captured source must be a bounded regular original file')
    with path.open('rb') as handle:digest=hashlib.file_digest(handle,'sha256').hexdigest()
    after=path.lstat()
    identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,change_time_ns(s))
    if identity(info)!=identity(after):raise ValueError('Captured source changed while hashing')
    return digest,identity(after)

def _registration(source_id):
    if not isinstance(source_id,str):
        raise ValueError('Unknown named capture source; use fm_list_captured_match_sources')
    if source_id in SOURCES:return None
    from .captured_match_registry import load_registrations
    registration=load_registrations().get(source_id)
    if registration is None:
        raise ValueError('Unknown named capture source; use fm_list_captured_match_sources')
    return registration

def _path(source_id,registration=None):
    if not isinstance(source_id,str):
        raise ValueError('Unknown named capture source; use fm_list_captured_match_sources')
    registration=registration if registration is not None else _registration(source_id)
    path=SOURCES[source_id] if registration is None else Path(registration['path'])
    if Path(str(path)+'-wal').exists() or Path(str(path)+'-journal').exists():
        raise ValueError('Captured source has an active SQLite journal')
    return path

@contextmanager
def open_source(source_id,expected_capture_id=None,expected_career_id=None):
    registration=_registration(source_id)
    with _open_capture(_path(source_id,registration),source_id,expected_capture_id,expected_career_id,registration) as result:
        yield result

@contextmanager
def _open_capture(path,source_id,expected_capture_id=None,expected_career_id=None,registration=None):
    if Path(str(path)+'-wal').exists() or Path(str(path)+'-journal').exists():
        raise ValueError('Captured source has an active SQLite journal')
    capture_id,identity=_fingerprint(path)
    if registration is not None and capture_id!=registration['sha256']:
        raise ValueError('Registered capture fingerprint differs; the original registration is immutable')
    pin=SOURCE_PINS.get(source_id)
    if pin is not None and capture_id!=pin['sha256']:
        raise ValueError('Approved shot export fingerprint differs from its registered original')
    if expected_capture_id is not None and expected_capture_id!=capture_id:
        raise ValueError('Captured export changed; select the current capture_id from the catalog')
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)
    try:
        db.execute('PRAGMA query_only=ON');db.execute('PRAGMA trusted_schema=OFF')
        db.execute('BEGIN')
        if db.execute('PRAGMA quick_check').fetchone()!=('ok',):raise ValueError('Captured SQLite integrity failed')
        metadata={k:json.loads(v) for k,v in db.execute('SELECT key,value_json FROM metadata')}
        save=metadata.get('save') or {};career={k:save.get(k) for k in EXPECTED_CAREER}
        expected_career=EXPECTED_CAREER if registration is None else registration.get('career')
        if not isinstance(career.get('name'),str) or not career['name'].strip() or not isinstance(career.get('created_date'),str) or type(career.get('created_version')) is not int:
            raise ValueError('Captured source has incomplete career identity')
        if expected_career is not None and career!=expected_career:
            raise ValueError('Captured source career does not match its named registration')
        career_id=hashlib.sha256(json.dumps(career,sort_keys=True).encode()).hexdigest()
        if expected_career_id is not None and expected_career_id!=career_id:
            raise ValueError('Captured career pin differs')
        if metadata.get('schema_version') not in (1,2,3,4):raise ValueError('Unsupported captured match schema version')
        schema={name:{row[1]:row[2] for row in db.execute(f'PRAGMA table_info("{name}")')} for name in (TABLES if registration is not None else BUILTIN_TABLES)}
        if any(not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',column) for columns in schema.values() for column in columns):
            raise ValueError('Unsupported captured schema column name')
        required={'fixture_id':'TEXT','native_match_key':'INTEGER','date':'TEXT','competition_id':'INTEGER','home_team_id':'INTEGER','away_team_id':'INTEGER'}
        if any(schema['fixtures'].get(k)!=v for k,v in required.items()):raise ValueError('Captured fixture schema differs')
        if any(schema['retained_players'].get(k)!=v for k,v in {'fixture_id':'TEXT','person_index_word':'INTEGER','minutes':'INTEGER'}.items()):
            raise ValueError('Captured player schema differs')
        if metadata.get('source') not in ('B142 bounded running-session capture','bounded_live_export'):
            raise ValueError('Source does not identify a supported captured-live export producer')
        counts={name:db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in schema if schema[name]}
        if any(n>ROW_BUDGETS.get(name,100000) for name,n in counts.items()):raise ValueError('Captured row budget exceeded')
        date_min,date_max=db.execute('SELECT min(date),max(date) FROM fixtures').fetchone()
        if registration is not None:
            fixture_identity=db.execute('SELECT fixture_id,native_match_key,date,competition_id,home_team_id,away_team_id FROM fixtures ORDER BY fixture_id').fetchall()
            if not fixture_identity:raise ValueError('Register a nonempty fixture capture')
            for fid,key,day,competition,home,away in fixture_identity:
                if not isinstance(fid,str) or not fid or any(type(value)is not int or value<=0 for value in (key,competition,home,away)):
                    raise ValueError('Registered fixture identity is incomplete')
                if not isinstance(day,str) or date.fromisoformat(day).isoformat()!=day:
                    raise ValueError('Registered fixture date must use YYYY-MM-DD')
            if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise ValueError('Registered capture has broken fixture references')
        if pin is not None:
            if (counts['fixtures']!=pin['fixtures'] or date_min!=pin['date'] or date_max!=pin['date']
                    or db.execute('SELECT count(*) FROM fixtures WHERE competition_id=?',(pin['competition_id'],)).fetchone()[0]!=pin['fixtures']
                    or any(counts.get(name)!=amount for name,amount in pin['table_counts'].items())):
                raise ValueError('Approved shot export date, competition or table scope differs')
        elif source_id=='newcastle_2030_10_29_arsenal_cup':
            if db.execute('SELECT count(*) FROM fixtures WHERE native_match_key=136159 AND date=?',('2030-10-29',)).fetchone()[0]!=1 or counts['fixtures']!=1:
                raise ValueError('Named cup fixture scope differs')
        elif registration is None and date_max is not None and date_max>'2030-10-28':raise ValueError('Named historical fixture window differs')
        if source_id=='newcastle_2030_10_28' and (counts['fixtures']!=20 or db.execute('SELECT count(*) FROM fixtures WHERE home_team_id=688 OR away_team_id=688').fetchone()[0]!=20):
            raise ValueError('Named Newcastle source scope differs')
        if source_id=='premier_league_2030_10_28' and (counts['fixtures']!=91 or db.execute('SELECT count(*) FROM fixtures WHERE competition_id=11').fetchone()[0]!=91):
            raise ValueError('Named Premier League source scope differs')
        shot_coverage={'state':'not_captured','scope':'whole_registered_capture','side_rows':None,'states':None}
        if schema['shot_map_coverage']:
            required_shots={'fixture_id':'TEXT','native_match_key':'INTEGER','side_index':'INTEGER','team_native_id':'INTEGER','state':'TEXT','shot_count':'INTEGER','shots_on_target':'INTEGER','expected_goals':'REAL','own_goal_marker_count':'INTEGER'}
            if any(schema['shot_map_coverage'].get(key)!=kind for key,kind in required_shots.items()):
                raise ValueError('Captured shot coverage schema differs')
            states={state:amount for state,amount in db.execute('SELECT state,count(*) FROM shot_map_coverage GROUP BY state')}
            if db.execute("SELECT count(*) FROM shot_map_coverage WHERE state!='available' AND (shot_count IS NOT NULL OR shots_on_target IS NOT NULL OR expected_goals IS NOT NULL OR own_goal_marker_count IS NOT NULL)").fetchone()[0]:
                raise ValueError('Unavailable captured shot sides contain misleading numeric counts')
            shot_coverage={'state':'captured_per_side','scope':'whole_registered_capture','side_rows':counts['shot_map_coverage'],'states':states}
        spatial_coverage={"state":"not_captured","scope":"whole_registered_capture"}
        period_coverage={"state":"not_captured"}
        pass_coverage={"state":"not_captured"}
        if registration is not None:
            _validate_observed_tables(db,schema)
            spatial_coverage=validate_spatial(db,schema,metadata["schema_version"])
            period_coverage=validate_periods(db,schema,metadata["schema_version"])
            pass_coverage=validate_passes(db,schema,metadata["schema_version"])
        competitions=[dict(native_id=i,name=n,fixtures=count) for i,n,count in db.execute('SELECT competition_id,competition,count(*) FROM fixtures GROUP BY competition_id,competition ORDER BY competition_id,competition')]
        provenance={'source_id':source_id,'source_kind':'captured_live_export','capture_id':capture_id,'career_id':career_id,
                    'filename':path.name,'bytes':identity[2],'capture_observed_at_utc':metadata.get('observed_at'),'capture_observed_at_scope':metadata.get('observed_at_scope'),'capture_time_state':'recorded' if metadata.get('observed_at') else 'wall_clock_capture_time_unrecorded','captured_save':save,'schema_version':metadata['schema_version'],
                    'available_tables':{k:list(v) for k,v in schema.items() if v},'counts':counts,
                    'date_coverage':{'from':date_min,'to':date_max},'competitions':competitions,
                    'retained_shot_coverage':shot_coverage,'retained_spatial_coverage':spatial_coverage,'retained_period_evidence':period_coverage,'retained_pass_attempt_coverage':pass_coverage,
                    'original_source':metadata['source'],'captured_scope':metadata.get('selectors',metadata.get('filters')),'field_provenance':metadata.get('field_provenance'),
                    'claim':'Read-only named historical live capture; not the current runtime or last disk save. Missing fields/rows remain unknown.'}
        pressure_columns = schema.get('retained_players') or {}
        known_pressure_rows = (db.execute('SELECT count(*) FROM retained_players WHERE pressures_attempted IS NOT NULL').fetchone()[0]
                               if 'pressures_attempted' in pressure_columns else 0)
        pressure_rows = counts.get('retained_players', 0)
        provenance['pressure_statistics_coverage'] = {
            'state': 'captured' if pressure_rows and known_pressure_rows == pressure_rows else 'captured_partial' if known_pressure_rows else 'not_captured',
            'known_attempt_rows': known_pressure_rows, 'unknown_attempt_rows': pressure_rows - known_pressure_rows,
            'optional_query_fields': ['pressures_attempted', 'pressure_completion_percentage_computed', 'pressure_completion_state'],
            'missing_field_policy': 'Explicit pressure-field requests return null (state explains missing capture), never a guessed zero or later native backfill'}
        if metadata.get('delivery_provenance') is not None:
            provenance['delivery_provenance']=metadata['delivery_provenance']
        if registration is not None:
            if schema.get('source_observed_shot_coverage'):
                provenance['source_observed_coverage']={'scope':'whole_registered_capture','states':dict(db.execute('SELECT state,count(*) FROM source_observed_shot_coverage GROUP BY state')),
                    'claim':'Separate source observations: counts and actors verified; native xG unreconciled. Strict shots remain separate.'}
            provenance['registration_kind']='explicit_local_cli'
            provenance['label']=registration.get('label',source_id)
            provenance['registered_at_utc']=registration.get('registered_at_utc')
            provenance['fixture_scope_id']=hashlib.sha256(json.dumps(fixture_identity,separators=(',',':')).encode()).hexdigest()
            scope=registration.get('scope')
            if scope is not None and registration_scope(provenance)!=scope:
                raise ValueError('Registered capture career, schema or fixture scope differs')
        yield db,provenance
        if _fingerprint(path)!=(capture_id,identity):raise ValueError('Captured export changed during read')
    finally:db.close()

def catalog_sources():
    sources=[]
    registered={};registry_state={'state':'available'}
    try:
        from .captured_match_registry import load_registrations
        registered=load_registrations()
    except (OSError,ValueError,json.JSONDecodeError) as error:
        registry_state={'state':'unavailable','reason':str(error)}
    for source_id in list(SOURCES)+[key for key in registered if key not in SOURCES]:
        if source_id=='newcastle_2030_10_29_arsenal_cup' and not SOURCES[source_id].exists():continue
        try:
            with open_source(source_id) as (_,provenance):sources.append(dict(provenance,state='available'))
        except (OSError,ValueError,sqlite3.Error,json.JSONDecodeError) as error:
            sources.append(dict(source_id=source_id,state='unavailable',reason=str(error)))
    return {'sources':sources,'registration_catalog':registry_state,'claim':'Explicit built-in and CLI-registered historical captured-live originals only. No directory scanning or running game is required; unregistered exports are not discovered. Missing fields and unavailable sides remain unknown.'}

def resolve_source(source_id,expected_capture_id=None,expected_career_id=None):
    with open_source(source_id,expected_capture_id,expected_career_id) as (_,provenance):
        return _path(source_id),provenance


def registration_scope(provenance):
    return {key:provenance[key] for key in ('career_id','schema_version','fixture_scope_id','date_coverage','competitions','original_source','captured_scope')} | {'fixture_count':provenance['counts']['fixtures']}


def _validate_observed_tables(db,schema):
    observed=schema.get('source_observed_shots') or {}
    coverage=schema.get('source_observed_shot_coverage') or {}
    if not observed and not coverage:return
    required={'fixture_id':'TEXT','native_match_key':'INTEGER','side_index':'INTEGER','record_index':'INTEGER',
              'native_expected_goals':'REAL','verification_scope':'TEXT','canonical_person_id':'INTEGER','person_name':'TEXT'}
    required_coverage={'fixture_id':'TEXT','native_match_key':'INTEGER','side_index':'INTEGER','state':'TEXT',
              'strict_side_state':'TEXT','observed_shot_count':'INTEGER','verified_shots_promoted':'INTEGER','xg_tolerance_widened':'INTEGER'}
    if 'expected_goals' in observed or any(observed.get(k)!=v for k,v in required.items()) or any(coverage.get(k)!=v for k,v in required_coverage.items()):
        raise ValueError('Source-observed shots must retain their separate native xG and coverage schema')
    available='available_source_observed_counts_verified_xg_unreconciled'
    if not schema.get('shot_map_coverage'):
        raise ValueError('Source-observed rows require separate strict coverage')
    if db.execute("SELECT count(*) FROM source_observed_shot_coverage c LEFT JOIN shot_map_coverage s USING(fixture_id,side_index) WHERE c.strict_side_state IS NOT s.state OR c.native_match_key IS NOT s.native_match_key").fetchone()[0]:
        raise ValueError('Source-observed coverage disagrees with its strict fixture side')
    if db.execute("SELECT count(*) FROM source_observed_shots s JOIN fixtures f USING(fixture_id) WHERE s.native_match_key IS NOT f.native_match_key OR s.side_index NOT IN(0,1)").fetchone()[0]:
        raise ValueError('Source-observed rows disagree with their canonical fixture')
    if db.execute("SELECT count(*) FROM source_observed_shot_coverage WHERE state=? AND (strict_side_state='available' OR observed_shot_count IS NULL OR observed_shot_count<0 OR verified_shots_promoted IS NOT 0 OR xg_tolerance_widened IS NOT 0)",(available,)).fetchone()[0]:
        raise ValueError('Source-observed coverage cannot promote strict shots or widen xG tolerance')
    if db.execute("SELECT count(*) FROM source_observed_shot_coverage WHERE state NOT IN(?,'not_needed_strict_side_available') AND observed_shot_count IS NOT NULL",(available,)).fetchone()[0]:
        raise ValueError('Unavailable source-observed sides require unknown counts')
    if db.execute("SELECT count(*) FROM source_observed_shots s LEFT JOIN source_observed_shot_coverage c USING(fixture_id,side_index) WHERE c.state IS NOT ? OR s.verification_scope IS NOT 'source_observed_counts_actors_verified_xg_unreconciled'",(available,)).fetchone()[0]:
        raise ValueError('Source-observed attempts require their distinct verified-counts scope')
    if db.execute("SELECT count(*) FROM source_observed_shot_coverage c WHERE c.state=? AND c.observed_shot_count!=(SELECT count(*) FROM source_observed_shots s WHERE s.fixture_id=c.fixture_id AND s.side_index=c.side_index)",(available,)).fetchone()[0]:
        raise ValueError('Source-observed attempt rows disagree with their own coverage')
