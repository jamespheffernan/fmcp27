import hashlib
import json
import sqlite3
import pytest
from fm_live_mcp import captured_match_registry as registry
from fm_live_mcp import captured_match_sources as sources
from fm_live_mcp.captured_match_query import CapturedMatchQueries
from fm_live_mcp.captured_pass_attempt_tables import REQUIRED,PRIMARY_KEYS
from fm_live_mcp.match_dataset import export_dataset


def pass_original(tmp_path,monkeypatch,change=None):
    monkeypatch.setattr(registry,'REGISTRY_PATH',tmp_path/'registry.json')
    path=tmp_path/'passes.sqlite'
    capture={'save':dict(sources.EXPECTED_CAREER),'fixtures':[{'native_match_key':42,'fixture':{'date':'2030-11-02','competition':{'native_id':11},'home_team':{'native_id':688},'away_team':{'native_id':713}}}]}
    players=[dict(fixture_key=42,side_index=0,canonical_person_id=7,person_index_word=7,stored_player_slot=0,person_name='Captured Passer',minutes=90)]
    export_dataset(path,capture,source='bounded_live_export',retained_players=players)
    with sqlite3.connect(path) as db:
        fid=db.execute('SELECT fixture_id FROM fixtures').fetchone()[0]
        db.execute("UPDATE metadata SET value_json='3' WHERE key='schema_version'")
        db.execute('UPDATE retained_players SET passes_attempted=2,passes_completed=1')
        for table,columns in REQUIRED.items():
            definition=','.join(f'{column} {kind}' for column,kind in columns.items())+',PRIMARY KEY('+','.join(PRIMARY_KEYS[table])+')'
            db.execute(f'CREATE TABLE {table}({definition})')
        db.execute('CREATE VIEW pass_attempt_analysis AS SELECT f.date,f.home_team,f.away_team,p.* FROM pass_attempts p JOIN fixtures f USING(fixture_id)')
        def insert(table,row):
            names=list(row);db.execute(f'INSERT INTO {table}('+','.join(names)+') VALUES('+','.join('?' for _ in names)+')',[row[c] for c in names])
        insert('pass_attempt_sources',dict(fixture_id=fid,native_match_key=42,state='available',source_kind='retained_cbe',raw_json='{}'))
        for side in (0,1):
            insert('pass_attempt_coverage',dict(fixture_id=fid,side_index=side,state='available',attempts=2 if side==0 else 0,completed=1 if side==0 else 0,not_completed=1 if side==0 else 0,raw_json='{}'))
        for index in (0,1):
            insert('pass_attempts',dict(fixture_id=fid,event_id=index,record_index=index,side_index=0,stored_player_slot=0,person_id=7,person_name='Captured Passer',native_category_code=7 if index==0 else 6,completed=1 if index==0 else 0,outcome='completed' if index==0 else 'not_completed',native_flags_word=0,geometry_state='raw_native_sampled_path',origin_destination_state='not_proved',raw_json='{}'))
            insert('pass_path_points',dict(fixture_id=fid,event_id=index,point_index=0,native_x=.2,native_y=.3))
        if change:db.executescript(change)
    return path,hashlib.sha256(path.read_bytes()).hexdigest()


def test_pass_attempt_query_is_distinct_and_retains_unknown_path_semantics(tmp_path,monkeypatch):
    path,digest=pass_original(tmp_path,monkeypatch)
    registry.register_capture(path,'captured_passes',digest)
    result=CapturedMatchQueries().query('captured_passes',digest,table='pass_attempt_analysis',limit=1)
    assert result['rows'][0]['person_name']=='Captured Passer'
    assert result['rows'][0]['origin_destination_state']=='not_proved'
    assert result['rows'][0]['coordinate_units'] is None
    assert result['selected_pass_attempt_coverage']['sides'][0]['attempts']==2
    assert result['source']['retained_pass_attempt_coverage']['state']=='captured_counter_reconciled_attempts'
    assert 'distinct from official pass-map edges' in result['pass_attempt_semantics']
    points=CapturedMatchQueries().query('captured_passes',digest,table='pass_path_points',team_native_id=688)
    assert len(points['rows'])==2


@pytest.mark.parametrize('sql,message',[
    ('UPDATE pass_attempts SET completed=0 WHERE native_category_code=7','semantics exceed'),
    ("UPDATE pass_attempts SET person_name='Other'",'actor identity differs'),
    ("UPDATE pass_attempts SET origin_destination_state='proved'",'semantics exceed'),
    ("UPDATE pass_attempts SET phase='FirstHalf'",'semantics exceed'),
    ('UPDATE retained_players SET passes_attempted=3','player counters'),
    ('UPDATE pass_path_points SET event_id=99 WHERE event_id=0','path reference differs'),
])
def test_pass_attempt_validation_rejects_counter_identity_or_geometry_promotions(tmp_path,monkeypatch,sql,message):
    path,digest=pass_original(tmp_path,monkeypatch,sql)
    with pytest.raises(ValueError,match=message):registry.register_capture(path,'bad_captured_passes',digest)
