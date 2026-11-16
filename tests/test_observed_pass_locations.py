import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
from collections import Counter

import pytest
from fm_live_mcp import observed_match_runs as runs, observed_pass_locations as locations


@pytest.fixture
def observed(tmp_path,monkeypatch):
    f=json.loads(gzip.decompress((Path(__file__).parent/'fixtures/active_pass_locations_185.json.gz').read_bytes()))
    raw=bytes.fromhex(f['raw_event_hex']);actors={(p['side_index'],p['stored_player_slot']):p for p in f['actors']['players']};path=tmp_path/'observed.sqlite';db=sqlite3.connect(path)
    db.executescript('''CREATE TABLE metadata(key TEXT,value_json TEXT);CREATE TABLE fixtures(date TEXT,competition_id INTEGER,home_team_id INTEGER,away_team_id INTEGER,official_match_unique_id INTEGER);
    CREATE TABLE source_documents(source_id TEXT,sha256 TEXT,document_json TEXT);CREATE TABLE table_scopes(table_name TEXT,scope TEXT);
    CREATE TABLE match_periods(period TEXT,start_tick INTEGER,end_tick INTEGER);
    CREATE TABLE pass_actors(side_index INTEGER,stored_player_slot INTEGER,canonical_person_id INTEGER,person_name TEXT,source_id TEXT);
    CREATE TABLE completed_pass_events(event_id INTEGER,side_index INTEGER,sender_slot INTEGER,receiver_slot INTEGER,sender_name TEXT,receiver_name TEXT,start_tick INTEGER,end_tick INTEGER,period TEXT,source_id TEXT);''')
    meta={'product_type':'observed_native_match_run','schema_version':1,'not_retained_match_export':True,'registered_retained_capture':False};db.executemany('INSERT INTO metadata VALUES(?,?)',[(k,json.dumps(v))for k,v in meta.items()]);db.execute('INSERT INTO fixtures VALUES(?,?,?,?,?)',('2030-11-11',11,688,692,f['match_unique_id']))
    terminal={'raw_source':{'events':{'hex':raw.hex(),'sha256':hashlib.sha256(raw).hexdigest()},'pitch_geometry':f['pitch_geometry'],'match_unique_id':f['match_unique_id'],'fixture_identity':['2030-11-11',11,[545,688],[549,692]]},'bound_playback':{'current_time_slice':23929,'official_match_unique_id':f['match_unique_id']},'period_split':{'period_intervals':[{'period':'FirstHalf','start_tick':1,'end_tick':11655},{'period':'SecondHalf','start_tick':11715,'end_tick':None}]},'save':{'name':'Career','created_date':'2025-01-01','created_version':1,'current_date':'2030-11-11','last_saved_date':'2030-11-06'}}
    db.executemany('INSERT INTO source_documents VALUES(?,?,?)',[('terminal','a'*64,json.dumps(terminal)),('pass_actors','b'*64,json.dumps({'actors':f['actors']}))]);db.executemany('INSERT INTO match_periods VALUES(?,?,?)',[('FirstHalf',1,11655),('SecondHalf',11715,23929)])
    db.executemany('INSERT INTO pass_actors VALUES(?,?,?,?,?)',[(p['side_index'],p['stored_player_slot'],p['canonical_person_id'],p['person_name'],'pass_actors')for p in f['actors']['players']])
    rows=[]
    for at in range(0,len(raw),56):
        e=raw[at:at+56];flags=int.from_bytes(e[48:50],'little');end=int.from_bytes(e[50:52],'little')
        if e[42]!=7 or flags&8 or end>=23929:continue
        start=int.from_bytes(e[34:36],'little');side=e[40];sender,recipient=e[39],e[41];period='FirstHalf'if 1<=start<=end<11655 else'SecondHalf'if 11715<=start<=end<23929 else None
        rows.append((int.from_bytes(e[44:48],'little'),side,sender,recipient,actors[side,sender]['person_name'],actors[side,recipient]['person_name'],start,end,period,'terminal'))
    db.executemany('INSERT INTO completed_pass_events VALUES(?,?,?,?,?,?,?,?,?,?)',rows);db.commit();db.close()
    policy={'terminal_payload_sha256':hashlib.sha256(json.dumps(terminal,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest(),'actor_payload_sha256':hashlib.sha256(json.dumps({'actors':f['actors']},sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest(),'version':locations.POLICY_VERSION,'native_plugin_sha256':locations.NATIVE_SHA256,'raw_event_sha256':hashlib.sha256(raw).hexdigest(),'terminal_sha256':'a'*64,'actor_document_sha256':'b'*64,'event_count':1020,'official_match_unique_id':f['match_unique_id'],'proof':'portable independently checked1020control'}
    registration={'path':path,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'fixture':('2030-11-11',11,688,692),'pass_location_policy':policy};monkeypatch.setattr(runs,'SOURCES',{'test':registration});return path,registration,f


def test_actual1020_derived_rows_phase_and_Baas_Enciso_locations_preserve_source(observed):
    path,reg,f=observed;before=path.read_bytes();catalog=runs.catalog_runs()['sources'][0]
    assert catalog['counts'][locations.TABLE]==1020 and '_derived_views'not in catalog
    assert catalog['optional_derivations'][locations.TABLE]['same_capture_base_event_actor_clock_period_checks']==1020
    q=runs.ObservedRunQueries();rows=[];cursor=None
    while True:
        page=q.query('test',reg['sha256'],locations.TABLE,side_index=1,limit=200,cursor=cursor);rows.extend(page['rows']);cursor=page['next_cursor']
        assert page['source']['capture_id']==reg['sha256'] and page['derived_projection']['original_database_unchanged']
        if cursor is None:break
    assert len(rows)==512 and len({r['event_id']for r in rows})==512
    assert Counter(r['period']for r in rows)=={'FirstHalf':286,'SecondHalf':226}
    pair=[r for r in rows if r['sender_person_native_id']==37076141 and r['receiver_person_native_id']==79034187]
    assert len(pair)==28 and Counter(r['analytical_pitch_third']for r in pair)=={'defensive':14,'middle':13,'attacking':1}
    assert Counter(r['analytical_lateral_channel']for r in pair)=={'outer':25,'central':3}
    assert path.read_bytes()==before and not Path(str(path)+'-wal').exists()


@pytest.mark.parametrize('mutation',['clock','identity','side','sender','recipient','canonical_id','name','period','raw','geometry','actor_document','policy','missing_event','duplicate_event'])
def test_optional_derivation_fails_closed_without_breaking_base_tables(observed,mutation):
    path,reg,_=observed;db=sqlite3.connect(path)
    sql={'clock':'UPDATE completed_pass_events SET start_tick=start_tick+1 WHERE event_id=0','identity':'UPDATE completed_pass_events SET event_id=99999 WHERE event_id=0','side':'UPDATE completed_pass_events SET side_index=0 WHERE event_id=0','sender':'UPDATE completed_pass_events SET sender_slot=25 WHERE event_id=0','recipient':'UPDATE completed_pass_events SET receiver_slot=25 WHERE event_id=0','canonical_id':'UPDATE pass_actors SET canonical_person_id=1 WHERE side_index=0 AND stored_player_slot=0','name':"UPDATE pass_actors SET person_name='wrong' WHERE side_index=0 AND stored_player_slot=0",'period':"UPDATE match_periods SET end_tick=end_tick-1 WHERE period='FirstHalf'",'missing_event':'DELETE FROM completed_pass_events WHERE event_id=0','duplicate_event':'INSERT INTO completed_pass_events SELECT * FROM completed_pass_events WHERE event_id=0'}
    if mutation in sql:db.execute(sql[mutation])
    elif mutation in('raw','geometry'):
        doc=json.loads(db.execute("SELECT document_json FROM source_documents WHERE source_id='terminal'").fetchone()[0])
        if mutation=='raw':doc['raw_source']['events']['hex']='ff'+doc['raw_source']['events']['hex'][2:]
        else:doc['raw_source']['pitch_geometry']['half_length_native']=float('nan')
        db.execute("UPDATE source_documents SET document_json=? WHERE source_id='terminal'",(json.dumps(doc),))
    elif mutation=='actor_document':db.execute("UPDATE source_documents SET sha256=? WHERE source_id='pass_actors'",('c'*64,))
    else:reg['pass_location_policy']['native_plugin_sha256']='f'*64
    db.commit();db.close();reg['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    catalog=runs.catalog_runs()['sources'][0]
    assert catalog['state']=='available'and locations.TABLE not in catalog['available_tables']
    assert catalog['optional_derivations'][locations.TABLE]['state']=='unavailable'
    assert runs.ObservedRunQueries().query('test',reg['sha256'],'fixtures')['row_count']==1
    with pytest.raises(ValueError,match='not captured'):runs.ObservedRunQueries().query('test',reg['sha256'],locations.TABLE)


def test_unattested_capture_does_not_infer_locations(observed):
    _,reg,_=observed;del reg['pass_location_policy'];catalog=runs.catalog_runs()['sources'][0]
    assert locations.TABLE not in catalog['available_tables']and catalog['optional_derivations'][locations.TABLE]['state']=='unavailable'


def test_derived_filter_sort_and_cursor_selector_guards(observed):
    _,reg,_=observed;q=runs.ObservedRunQueries();fields=['event_id','side_index','period','native_event_x']
    page=q.query('test',reg['sha256'],locations.TABLE,fields,side_index=1,period='SecondHalf',sort_by='native_event_x',descending=True,limit=10)
    assert len(page['rows'])==10 and all(r['side_index']==1 and r['period']=='SecondHalf'for r in page['rows'])
    assert page['rows']==sorted(page['rows'],key=lambda r:r['native_event_x'],reverse=True)
    with pytest.raises(ValueError,match='changed selectors'):q.query('test',reg['sha256'],locations.TABLE,fields,side_index=0,cursor=page['next_cursor'])
    with pytest.raises(ValueError):q.query('test',reg['sha256'],locations.TABLE,['native_event_x;DROP TABLE fixtures'])
