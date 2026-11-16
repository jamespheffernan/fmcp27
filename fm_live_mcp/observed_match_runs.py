"""Approved observed native runs: separate from retained captures and disk saves."""
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time

from .captured_match_sources import _fingerprint
from .captured_match_query import _pin
from . import observed_pass_locations, observed_shot_actors, observed_tactical_settings, observed_assist_annotations, observed_pass_attempts

SOURCES = {
    'newcastle_forest_2030_11_11_observed_run_182': {
        'path': Path.home()/'Agent Outputs/Reference/Newcastle v Forest 2030-11-11 — observed run 182.sqlite',
        'sha256': '8e8a4d436d01525f20730c53b5abeaf67d75f8a762413e6da9ceb090236de873',
        'fixture': ('2030-11-11',11,688,692),
    },
}
BASE_TABLES = ('fixtures','match_periods','shots','match_period_team_totals','pass_actors',
          'completed_pass_events','pass_edges_by_period','average_positions','heatmap_cells',
          'own_goal_markers','player_shot_statistics','score_snapshots','match_prefix_team_totals')
TABLES = (*BASE_TABLES,observed_pass_attempts.TABLE,observed_pass_locations.TABLE,observed_shot_actors.TABLE,
          observed_tactical_settings.SNAPSHOTS_TABLE,observed_tactical_settings.CHANGES_TABLE,observed_assist_annotations.TABLE)
EXCLUDED_FIELDS = {'record_json','coverage_json'}
SHOT_FIELDS = ('is_penalty','shot_situation','official_location','location_group')
MAX_RESPONSE_BYTES = 131072
MAX_ROWS = 100000
CLAIM = ('Distinct observed_native_match_run, not a retained RESULT export, last disk save or current runtime. '
         'Native clocks are not proved displayed minutes. Base shot actor_name stays unknown; the optional named_shot_chances view supplies only independently resolved primary actors. '
         'Period xG is computed from captured attempts, not an official aggregate. '
         'Completed-pass tables retain completed-event scope; optional attested pass_attempt_events includes native not_completed event points without an independently reconciled attempts denominator; spatial and period completeness follow each table scope, never inferred full time.')


@contextmanager
def open_run(source_id, capture_id=None):
    from .observed_run_registry import load_registrations
    registrations = {**SOURCES, **load_registrations()}
    if type(source_id) is not str or source_id not in registrations:
        raise ValueError('Unknown approved observed run; use fm_list_observed_match_runs')
    registration = registrations[source_id];path = registration['path']
    if any(Path(str(path)+suffix).exists() for suffix in ('-wal','-journal')):
        raise ValueError('Observed run has an active SQLite journal')
    digest, identity = _fingerprint(path)
    if digest != registration['sha256'] or capture_id is not None and digest != capture_id:
        raise ValueError('Observed run fingerprint differs from the approved capture')
    db = sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=2)
    try:
        db.execute('PRAGMA query_only=ON');db.execute('PRAGMA trusted_schema=OFF');db.execute('BEGIN')
        if db.execute('PRAGMA quick_check').fetchone() != ('ok',):
            raise ValueError('Observed run integrity failed')
        metadata = {k:json.loads(v) for k,v in db.execute('SELECT key,value_json FROM metadata')}
        if (metadata.get('product_type') != 'observed_native_match_run'
                or metadata.get('schema_version') != 1
                or metadata.get('not_retained_match_export') is not True
                or metadata.get('registered_retained_capture') is not False):
            raise ValueError('Source is not the supported distinct observed-run product')
        fixtures = db.execute('SELECT date,competition_id,home_team_id,away_team_id FROM fixtures').fetchall()
        if fixtures != [tuple(registration['fixture'])]:
            raise ValueError('Observed run fixture scope differs')
        terminal_raw = db.execute("SELECT document_json FROM source_documents WHERE source_id='terminal'").fetchone()
        if terminal_raw is None:
            raise ValueError('Observed run terminal provenance is absent')
        terminal = json.loads(terminal_raw[0]);save = terminal.get('save')
        if not isinstance(save,dict) or not all(k in save for k in ('name','created_date','created_version','current_date','last_saved_date')):
            raise ValueError('Observed run career provenance is incomplete')
        if registration.get('career') is not None and registration['career'] != {k:save[k] for k in ('name','created_date','created_version')}:
            raise ValueError('Observed run career differs from registration')
        if registration.get('selection_id') is not None and registration['selection_id'] != metadata.get('selection_id'):
            raise ValueError('Observed run selection differs from registration')
        schema = {};counts = {}
        for table in BASE_TABLES:
            if db.execute('SELECT type FROM sqlite_master WHERE name=?',(table,)).fetchone() != ('table',):
                continue
            fields = [row[1] for row in db.execute(f'PRAGMA table_info("{table}")')]
            if any(not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',field) for field in fields):
                raise ValueError('Unsafe observed schema identifier')
            schema[table] = [field for field in fields if field not in EXCLUDED_FIELDS]
            if table == 'shots' and 'record_json' in fields:
                if db.execute('SELECT count(*) FROM shots WHERE NOT json_valid(record_json)').fetchone()[0]:
                    raise ValueError('Malformed observed shot diagnostic JSON')
                schema[table].extend(SHOT_FIELDS)
            counts[table] = db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
            if counts[table] > MAX_ROWS:
                raise ValueError('Observed run row budget exceeded')
        scopes = {name:scope for name,scope in db.execute('SELECT table_name,scope FROM table_scopes')}
        sources = dict(db.execute('SELECT source_id,sha256 FROM source_documents'))
        observed = terminal.get('observed_at_unix')
        provenance = {'source_id':source_id,'capture_id':digest,'product_type':'observed_native_match_run',
            'filename':path.name,'captured_save':save,'fixture_scope':dict(zip(
                ('date','competition_native_id','home_team_native_id','away_team_native_id'),fixtures[0])),
            'observed_at_utc':datetime.fromtimestamp(observed,timezone.utc).isoformat()
                              if isinstance(observed,(int,float)) else None,
            'available_tables':schema,'counts':counts,'table_scopes':scopes,
            'source_document_hashes':sources,'limitations':metadata,'claim':CLAIM}
        provenance['optional_derivations'] = {}
        projections = (
            (observed_pass_attempts.TABLE, observed_pass_attempts.derive_pass_attempts,
             {'attestation':registration.get('pass_attempt_attestation')}),
            (observed_assist_annotations.TABLE, observed_assist_annotations.derive_assist_annotations, {}),
            (observed_pass_locations.TABLE, observed_pass_locations.derive_pass_locations,
             {'policy':registration.get('pass_location_policy')}),
            (observed_shot_actors.TABLE, observed_shot_actors.derive_shot_actors, {}),
            (observed_tactical_settings.SNAPSHOTS_TABLE, observed_tactical_settings.derive_tactical_settings,
             {'table':observed_tactical_settings.SNAPSHOTS_TABLE,'producer_attestation':registration.get('producer_attestation')}),
            (observed_tactical_settings.CHANGES_TABLE, observed_tactical_settings.derive_tactical_settings,
             {'table':observed_tactical_settings.CHANGES_TABLE,'producer_attestation':registration.get('producer_attestation')}),
        )
        for table,derive,kwargs in projections:
            try:
                derived = derive(db,provenance,**kwargs)
                if derived:
                    columns = derived['columns']
                    if (len(derived['rows'])>MAX_ROWS or len(columns)!=len(set(columns))
                            or any(not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*',name) for name in columns)):
                        raise ValueError('Optional observed projection schema or row budget invalid')
                    provenance.setdefault('_derived_views',{})[table] = derived
                    schema[table] = columns
                    counts[table] = len(derived['rows'])
                    scopes[table] = derived['scope']
                provenance['optional_derivations'][table] = (derived['provenance'] if derived
                    else {'state':'unavailable','reason':'No approved native-source attestation for this capture.'})
            except (ValueError,KeyError,TypeError,sqlite3.Error,json.JSONDecodeError) as error:
                provenance['optional_derivations'][table] = {'state':'unavailable','reason':str(error)}
        yield db,provenance
        if _fingerprint(path) != (digest,identity):
            raise ValueError('Observed run changed during read')
    finally:
        db.close()


def catalog_runs():
    rows = []
    from .observed_run_registry import load_registrations
    for source_id in {**SOURCES, **load_registrations()}:
        try:
            with open_run(source_id) as (_,provenance):
                rows.append({'state':'available',**{k:v for k,v in provenance.items() if not k.startswith('_')}})
        except (OSError,ValueError,sqlite3.Error,json.JSONDecodeError) as error:
            rows.append({'source_id':source_id,'state':'unavailable','reason':str(error)})
    return {'sources':rows,'registration_scope':'Explicit approved observed-run originals only; no directory scanning.',
            'claim':CLAIM}


class ObservedRunQueries:
    def __init__(self):
        self.pages = OrderedDict();self.lock = threading.RLock()

    def query(self,source_id,capture_id,table='fixtures',fields=None,*,side_index=None,period=None,
              sort_by=None,descending=False,limit=100,cursor=None):
        _pin(capture_id,'capture_id')
        if table not in TABLES:
            raise ValueError('Unsupported observed-run table')
        if side_index is not None and (type(side_index) is not int or side_index not in (0,1)):
            raise ValueError('side_index must be0(home) or1(away)')
        if period is not None and period not in ('FirstHalf','SecondHalf','ExtraTimeFirstHalf','ExtraTimeSecondHalf'):
            raise ValueError('Select a named match period')
        if type(descending) is not bool or type(limit) is not int or not 1<=limit<=200:
            raise ValueError('Use a boolean descending and limit1–200')
        selectors = json.dumps([source_id,capture_id,table,fields,side_index,period,sort_by,descending])
        with self.lock,open_run(source_id,capture_id) as (db,provenance):
            now = time.monotonic()
            for token in list(self.pages):
                if now-self.pages[token]['created']>300:
                    del self.pages[token]
            if cursor is not None:
                page = self.pages.get(cursor)
                if page is None or page['selectors']!=selectors:
                    raise ValueError('Expired observed cursor or changed selectors')
                offset=page['offset'];created=page['created']
            else:
                offset=0;created=now
            available = provenance['available_tables'].get(table)
            if not available:
                raise ValueError('Table not captured in this observed run')
            selected = available if fields is None else fields
            if (not isinstance(selected,list) or not selected or len(selected)!=len(set(selected))
                    or any(type(field) is not str or field not in available for field in selected)):
                raise ValueError('Select distinct catalog columns only')
            if sort_by is not None and sort_by not in available:
                raise ValueError('sort_by must be an available column')
            clauses=[];params=[]
            for name,value in (('side_index',side_index),('period',period)):
                if value is not None:
                    if name not in available:
                        raise ValueError(f'{name} filter is unsupported for this table')
                    clauses.append(f'"{name}"=?');params.append(value)
            where=' AND '.join(clauses) or '1'
            def expression(field):
                return f"json_extract(record_json, '$.{field}')" if table=='shots' and field in SHOT_FIELDS else f'"{field}"'
            ordering=(expression(sort_by)+' '+('DESC' if descending else 'ASC')+',') if sort_by else ''
            derived = provenance.get('_derived_views',{}).get(table)
            prefix_params=[]
            if derived:
                # A SELECT-only in-memory JSON relation: no CREATE/TEMP/ATTACH or DB writes.
                source='(SELECT CAST(key AS INTEGER) AS rowid,'+','.join(
                    f"json_extract(value, '$.{field}') AS \"{field}\""for field in available)+ ' FROM json_each(?))'
                prefix_params=[json.dumps(derived['rows'],ensure_ascii=False,separators=(',',':'))]
            else:
                source=f'"{table}"'
            sql='SELECT '+','.join(expression(field)+f' AS "{field}"'for field in selected)+f' FROM {source} WHERE {where} ORDER BY {ordering}rowid LIMIT ? OFFSET ?'
            raw=db.execute(sql,(*prefix_params,*params,limit+1,offset)).fetchall()
            rows=[]
            for row in raw[:limit]:
                item=dict(zip(selected,row))
                if len(json.dumps(rows+[item],ensure_ascii=False).encode())>MAX_RESPONSE_BYTES-8192:
                    if not rows:
                        raise ValueError('One observed row exceeds the response byte budget')
                    break
                rows.append(item)
            more=len(raw)>len(rows)
            next_cursor=None
            if more:
                next_cursor=secrets.token_urlsafe(18)
                self.pages[next_cursor]={'selectors':selectors,'offset':offset+len(rows),'created':created}
                while len(self.pages)>512:
                    self.pages.popitem(last=False)
            compact={key:provenance[key]for key in ('source_id','capture_id','product_type','filename','captured_save','fixture_scope','observed_at_utc','claim')}
            result={'source':compact,'table':table,'table_scope':provenance['table_scopes'].get(table),
                'rows':rows,'row_count':len(rows),'next_cursor':next_cursor,'all_matching_rows_returned':not more and offset==0,
                'side_policy':'side_index0 is fixture home;1 is away. Without a side filter both sides are returned.',
                'limits':provenance['limitations']}
            if derived:
                result['derived_projection'] = derived['provenance']
            if len(json.dumps(result,ensure_ascii=False).encode())>MAX_RESPONSE_BYTES:
                raise ValueError('Observed response exceeds its byte budget; select fewer fields')
            return result
