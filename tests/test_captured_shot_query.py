import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from fm_live_mcp import captured_match_sources as sources
from fm_live_mcp.captured_match_query import CapturedMatchQueries
from fm_live_mcp.match_dataset import export_dataset


SOURCE=sources.PINNED_SHOT_SOURCE


def shot_original(tmp_path,monkeypatch,*,unavailable=False):
    path=tmp_path/'approved.sqlite'
    capture={'save':dict(sources.EXPECTED_CAREER,current_date='2030-11-02'),
             'fixtures':[{'native_match_key':135904,'fixture':{'date':'2030-10-26',
                          'competition':{'native_id':11},'home_team':{'native_id':713},'away_team':{'native_id':692}}}]}
    export_dataset(path,capture,source='bounded_live_export')
    with sqlite3.connect(path) as db:
        fid=db.execute('SELECT fixture_id FROM fixtures').fetchone()[0]
        db.executescript('''
        CREATE TABLE shots(fixture_id TEXT,native_match_key INTEGER,side_index INTEGER,
          record_index INTEGER,source_id TEXT,native_x REAL,native_y REAL,expected_goals REAL,raw_json TEXT);
        CREATE TABLE shot_map_coverage(fixture_id TEXT,native_match_key INTEGER,side_index INTEGER,
          team_native_id INTEGER,team_index INTEGER,source_id TEXT,state TEXT,shot_count INTEGER,
          shots_on_target INTEGER,expected_goals REAL,own_goal_marker_count INTEGER,raw_json TEXT);
        CREATE TABLE own_goal_markers(fixture_id TEXT,native_match_key INTEGER,beneficiary_side_index INTEGER,
          event_side_index INTEGER,record_index INTEGER,source_id TEXT,native_x REAL,native_y REAL,native_expected_goals REAL,raw_json TEXT);
        ''')
        row={'actor':{'person_name':'Known Player','canonical_person_id':7,'identity_state':'same_snapshot_canonical_PERSON'},'actor_identity_state':'same_snapshot_canonical_PERSON','expected_goals':0.687,'clock':None,'outcome':None}
        db.execute('INSERT INTO shots VALUES (?,?,?,?,?,?,?,?,?)',(fid,135904,0,12,'native-source',-1,49,0.687,json.dumps(row)))
        db.execute('INSERT INTO own_goal_markers VALUES (?,?,?,?,?,?,?,?,?,?)',(fid,135904,0,1,2,'native-source',3,50,0,'{}'))
        db.execute('INSERT INTO shot_map_coverage VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(fid,135904,0,713,570,'native-source','available',1,1,0.687,1,'{}'))
        away=(fid,135904,1,692,99,'native-source','unavailable_not_retained',None,None,None,None,'{}') if unavailable else (fid,135904,1,692,99,'native-source','available',0,0,0.0,0,'{}')
        db.execute('INSERT INTO shot_map_coverage VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',away)
        db.execute("UPDATE metadata SET value_json='2' WHERE key='schema_version'")
    pin={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'date':'2030-10-26','competition_id':11,'fixtures':1,
         'table_counts':{'shots':1,'shot_map_coverage':2,'own_goal_markers':1}}
    monkeypatch.setattr(sources,'SOURCES',{SOURCE:path})
    monkeypatch.setattr(sources,'SOURCE_PINS',{SOURCE:pin})
    with sources.open_source(SOURCE) as (_,p):pass
    return path,p


def test_new_source_defaults_include_checked_actor_and_side_coverage(tmp_path,monkeypatch):
    _,p=shot_original(tmp_path,monkeypatch)
    q=CapturedMatchQueries()
    result=q.query(SOURCE,p['capture_id'],table='shots',team_native_id=713)
    assert result['rows'][0]['raw_json']['actor']['person_name']=='Known Player'
    assert result['rows'][0]['expected_goals']==0.687
    assert 'is_penalty' not in result['fields']  # older optional columns stay absent
    assert result['selected_shot_coverage']['sides'][1]['shot_count']==0
    marker=q.query(SOURCE,p['capture_id'],table='own_goal_markers')
    assert marker['rows'][0]['beneficiary_side_index']==0 and marker['rows'][0]['event_side_index']==1
    assert p['retained_shot_coverage']['states']=={'available':2}
    assert set(p['available_tables'])>=set(('shots','shot_map_coverage','own_goal_markers'))


def test_missing_retained_side_stays_null_even_when_attempt_rows_are_empty(tmp_path,monkeypatch):
    _,p=shot_original(tmp_path,monkeypatch,unavailable=True)
    result=CapturedMatchQueries().query(SOURCE,p['capture_id'],table='shots')
    coverage=result['selected_shot_coverage']['sides']
    assert coverage[1]['state']=='unavailable_not_retained' and coverage[1]['shot_count'] is None
    assert result['row_count']==1
    filtered=CapturedMatchQueries().query(SOURCE,p['capture_id'],table='shots',team_native_id=999)
    assert filtered['rows']==[] and filtered['selected_shot_coverage']['sides']==[]


def test_original_bytes_and_career_scope_are_strict_and_connection_is_readonly(tmp_path,monkeypatch):
    path,p=shot_original(tmp_path,monkeypatch)
    with sources.open_source(SOURCE,p['capture_id']) as (db,_):
        with pytest.raises(sqlite3.OperationalError):db.execute('DELETE FROM shots')
    assert hashlib.sha256(path.read_bytes()).hexdigest()==p['capture_id']
    with sqlite3.connect(path) as db:db.execute('UPDATE shots SET expected_goals=0.9')
    with pytest.raises(ValueError,match='fingerprint'):
        with sources.open_source(SOURCE):pass


def test_wrong_date_rejected_even_when_test_registration_hash_matches(tmp_path,monkeypatch):
    path,_=shot_original(tmp_path,monkeypatch)
    with sqlite3.connect(path) as db:db.execute("UPDATE fixtures SET date='2030-10-25'")
    sources.SOURCE_PINS[SOURCE]['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='date, competition or table scope'):
        with sources.open_source(SOURCE):pass


def test_registered_original_rejects_symlink_and_active_journal(tmp_path,monkeypatch):
    path,_=shot_original(tmp_path,monkeypatch)
    alias=tmp_path/'alias.sqlite';alias.symlink_to(path)
    monkeypatch.setitem(sources.SOURCES,SOURCE,alias)
    with pytest.raises(ValueError,match='regular original'):
        with sources.open_source(SOURCE):pass
    monkeypatch.setitem(sources.SOURCES,SOURCE,path)
    Path(str(path)+'-journal').write_bytes(b'active')
    with pytest.raises(ValueError,match='active SQLite journal'):
        with sources.open_source(SOURCE):pass


def test_source_catalog_does_not_scan_unrelated_reference_files(tmp_path,monkeypatch):
    _,_=shot_original(tmp_path,monkeypatch)
    def forbidden(*args,**kwargs):raise AssertionError('directory scan is not permitted')
    monkeypatch.setattr(Path,'iterdir',forbidden)
    assert sources.catalog_sources()['sources'][0]['state']=='available'
