import hashlib
import json
import sqlite3
import pytest
from fm_live_mcp import captured_match_registry as registry
from fm_live_mcp import captured_match_sources as sources
from fm_live_mcp.captured_match_query import CapturedMatchQueries
from fm_live_mcp.captured_period_tables import REQUIRED,PRIMARY_KEYS
from fm_live_mcp.match_dataset import export_dataset


def period_original(tmp_path,monkeypatch,change=None):
    monkeypatch.setattr(registry,'REGISTRY_PATH',tmp_path/'registry.json')
    path=tmp_path/'period.sqlite'
    capture={'save':dict(sources.EXPECTED_CAREER),'fixtures':[{'native_match_key':42,'fixture':{'date':'2030-11-02','competition':{'native_id':11},'home_team':{'native_id':688},'away_team':{'native_id':713}}}]}
    export_dataset(path,capture,source='bounded_live_export')
    with sqlite3.connect(path) as db:
        fid=db.execute('SELECT fixture_id FROM fixtures').fetchone()[0]
        db.execute("UPDATE metadata SET value_json='3' WHERE key='schema_version'")
        db.execute('CREATE TABLE shots(fixture_id TEXT,side_index INTEGER,record_index INTEGER,event_id INTEGER,raw_json TEXT,expected_goals REAL,native_x REAL,native_y REAL,body_part TEXT,outcome TEXT,official_location TEXT,PRIMARY KEY(fixture_id,side_index,record_index))')
        shot={'native_clock_start_raw':100,'native_clock_end_raw':101,'actor':{'canonical_person_id':7,'person_name':'Captured Actor'}}
        db.execute('INSERT INTO shots VALUES(?,?,?,?,?,?,?,?,?,?,?)',(fid,0,0,9,json.dumps(shot),.2,1.,2.,'feet','goal','six_yard_box'))
        db.execute('CREATE TABLE shot_map_coverage(fixture_id TEXT,native_match_key INTEGER,side_index INTEGER,team_native_id INTEGER,state TEXT,shot_count INTEGER,shots_on_target INTEGER,expected_goals REAL,own_goal_marker_count INTEGER)')
        for side in (0,1):
            db.execute('INSERT INTO shot_map_coverage VALUES(?,?,?,?,?,?,?,?,?)',(fid,42,side,688 if side==0 else 713,'available',1 if side==0 else 0,1 if side==0 else 0,.2 if side==0 else 0.,0))
        for table,columns in REQUIRED.items():
            definition=','.join(f'{column} {kind}' for column,kind in columns.items())+',PRIMARY KEY('+','.join(PRIMARY_KEYS[table])+')'
            db.execute(f'CREATE TABLE {table}({definition})')
        db.execute('CREATE VIEW shot_period_analysis AS SELECT f.date,f.home_team,f.away_team,p.*,s.expected_goals, s.native_x,s.native_y,s.body_part,s.outcome,s.official_location FROM shot_periods p JOIN shots s USING(fixture_id,side_index,record_index) JOIN fixtures f USING(fixture_id)')
        db.execute('INSERT INTO match_period_evidence VALUES(?,?,?,?,?,?,?,?)',(fid,42,'a'*64,'host_capture','verified_retrospective_continuity','123','native_playback_time_slice','{}'))
        db.execute('INSERT INTO match_periods VALUES(?,?,?,?,?)',(fid,'FirstHalf',0,11544,'start<=event_start<=event_end<end; ties/crossings unknown'))
        db.execute('INSERT INTO shot_periods VALUES(?,?,?,?,?,?,?,?,?,?,?)',(fid,0,0,9,'FirstHalf',100,101,'verified_native_stop_interval',7,'Captured Actor','{}'))
        for side in (0,1):
            db.execute('INSERT INTO match_period_team_totals VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(fid,'FirstHalf',side,'available_derived_retained_attempts',1 if side==0 else 0,1 if side==0 else 0,1 if side==0 else 0,.2 if side==0 else 0.,0,1 if side==0 else 0,0,'derived_retained_attempts'))
        if change:db.executescript(change)
    return path,hashlib.sha256(path.read_bytes()).hexdigest()


def test_period_query_preserves_confidence_exact_shot_join_and_computed_scope(tmp_path,monkeypatch):
    path,digest=period_original(tmp_path,monkeypatch)
    registry.register_capture(path,'period_capture',digest)
    result=CapturedMatchQueries().query('period_capture',digest,table='shot_period_analysis')
    assert result['rows'][0]['period']=='FirstHalf'
    assert result['rows'][0]['shooter_name']=='Captured Actor'
    assert result['rows'][0]['expected_goals']==.2
    assert result['source']['retained_period_evidence']['state']=='captured_verified_retrospective_periods'
    assert 'not an official halftime xG' in result['period_semantics']
    assert CapturedMatchQueries().query('period_capture',digest,table='match_period_team_totals')['rows'][1]['shots']==0


@pytest.mark.parametrize('sql,message',[
    ("UPDATE match_period_evidence SET confidence='guessed'",'confidence differs'),
    ("UPDATE shot_periods SET shooter_name='Other'",'clocks/actor differ'),
    ("UPDATE shot_periods SET native_clock_end_raw=102",'clocks/actor differ'),
    ("UPDATE match_periods SET end_tick=101",'interval boundaries'),
    ("DELETE FROM shot_periods",'omit retained shots'),
    ("UPDATE match_period_team_totals SET shots=99",'totals disagree'),
])
def test_invalid_retrospective_periods_cannot_register(tmp_path,monkeypatch,sql,message):
    path,digest=period_original(tmp_path,monkeypatch,sql)
    with pytest.raises(ValueError,match=message):registry.register_capture(path,'bad_period_capture',digest)
