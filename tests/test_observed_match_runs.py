import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
from unittest.mock import Mock
import pytest
from fm_live_mcp import observed_match_runs as module


@pytest.fixture
def source(tmp_path,monkeypatch):
    path=tmp_path/'observed.sqlite';db=sqlite3.connect(path)
    db.executescript('CREATE TABLE metadata(key TEXT,value_json TEXT);CREATE TABLE fixtures(date TEXT,competition_id INTEGER,home_team_id INTEGER,away_team_id INTEGER,home_score INTEGER,away_score INTEGER);CREATE TABLE source_documents(source_id TEXT,sha256 TEXT,document_json TEXT);CREATE TABLE table_scopes(table_name TEXT,scope TEXT);CREATE TABLE shots(event_id INTEGER,side_index INTEGER,period TEXT,expected_goals REAL,actor_name TEXT,record_json TEXT);')
    meta={'product_type':'observed_native_match_run','schema_version':1,'not_retained_match_export':True,'registered_retained_capture':False}
    db.executemany('INSERT INTO metadata VALUES(?,?)',[(k,json.dumps(v))for k,v in meta.items()])
    db.execute('INSERT INTO fixtures VALUES(?,?,?,?,?,?)',('2030-11-11',11,688,692,4,1))
    terminal={'save':{'name':'Career','created_date':'2025-01-01','created_version':1,'current_date':'2030-11-11','last_saved_date':'2030-11-06'}}
    db.execute('INSERT INTO source_documents VALUES(?,?,?)',('terminal','a'*64,json.dumps(terminal)))
    db.execute('INSERT INTO table_scopes VALUES(?,?)',('shots','terminal attempts; actor names unresolved'))
    db.executemany('INSERT INTO shots VALUES(?,?,?,?,?,?)',[(i,i%2,'FirstHalf'if i<3 else'SecondHalf',i/10,None,json.dumps({'is_penalty':False,'location_group':'inside_area'}))for i in range(5)])
    db.commit();db.close()
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(module,'SOURCES',{'test_run':{'path':path,'sha256':digest,'fixture':('2030-11-11',11,688,692)}})
    return path,digest


def test_distinct_catalog_never_impersonates_retained_or_save(source):
    result=module.catalog_runs()['sources'][0]
    assert result['state']=='available'
    assert result['product_type']=='observed_native_match_run'
    assert result['captured_save']['last_saved_date']=='2030-11-06'
    assert 'source_documents'not in result['available_tables']
    assert 'record_json'not in result['available_tables']['shots']


def test_filter_sort_and_deterministic_pinned_paging(source):
    _,digest=source;q=module.ObservedRunQueries()
    first=q.query('test_run',digest,'shots',side_index=0,sort_by='expected_goals',descending=True,limit=2)
    assert [r['event_id']for r in first['rows']]==[4,2]
    assert first['rows'][0]['actor_name']is None
    second=q.query('test_run',digest,'shots',side_index=0,sort_by='expected_goals',descending=True,limit=2,cursor=first['next_cursor'])
    assert [r['event_id']for r in second['rows']]==[0]
    assert second['next_cursor']is None
    with pytest.raises(ValueError,match='changed selectors'):
        q.query('test_run',digest,'shots',side_index=1,cursor=first['next_cursor'])


@pytest.mark.parametrize('kwargs',[{'source_id':'/tmp/file.sqlite'},{'table':'shots;DROP TABLE shots'}, {'fields':['record_json']},{'sort_by':'expected_goals DESC;DROP TABLE shots'}, {'limit':201},{'side_index':True},{'table':'fixtures','period':'FirstHalf'}])
def test_no_arbitrary_paths_sql_raw_documents_or_silent_filter_ignoring(source,kwargs):
    _,digest=source;args={'source_id':'test_run','capture_id':digest,'table':'shots'};args.update(kwargs)
    with pytest.raises(ValueError):module.ObservedRunQueries().query(**args)


def test_changed_file_and_active_journal_reject(source):
    path,digest=source
    Path(str(path)+'-wal').touch()
    with pytest.raises(ValueError,match='journal'):module.ObservedRunQueries().query('test_run',digest)
    Path(str(path)+'-wal').unlink()
    db=sqlite3.connect(path);db.execute('UPDATE fixtures SET home_score=9');db.commit();db.close()
    with pytest.raises(ValueError,match='fingerprint'):module.ObservedRunQueries().query('test_run',digest)


def test_wrong_product_is_not_accepted_even_with_reapproved_hash(source):
    path,_=source;db=sqlite3.connect(path);db.execute("UPDATE metadata SET value_json='\"retained_export\"' WHERE key='product_type'");db.commit();db.close()
    module.SOURCES['test_run']['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    assert module.catalog_runs()['sources'][0]['state']=='unavailable'


def test_midread_replacement_rejected(source):
    path,_=source
    with pytest.raises(ValueError,match='changed during read'):
        with module.open_run('test_run'):
            with path.open('ab')as handle:handle.write(b'changed')


def test_model_discovery_exposes_only_two_bounded_source_tools():
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp.observed_match_tools import register_observed_match_tools
    mcp=FastMCP('observed-test');register_observed_match_tools(mcp)
    tools=asyncio.run(mcp.list_tools());assert len(tools)==2
    schemas={t.name:t.inputSchema for t in tools}
    assert 'path'not in schemas['fm_query_observed_match_run']['properties']
    assert 'sql'not in schemas['fm_query_observed_match_run']['properties']


def test_byte_budget_pages_without_partial_row_or_silent_truncation(source):
    path,_=source;db=sqlite3.connect(path);db.execute('UPDATE shots SET actor_name=?',('x'*70000,));db.commit();db.close()
    digest=hashlib.sha256(path.read_bytes()).hexdigest();module.SOURCES['test_run']['sha256']=digest
    q=module.ObservedRunQueries();page=q.query('test_run',digest,'shots',fields=['event_id','actor_name'],limit=200)
    assert len(page['rows'])==1 and page['next_cursor']
    assert len(json.dumps(page,ensure_ascii=False).encode())<=module.MAX_RESPONSE_BYTES
    q.pages[page['next_cursor']]['created']-=301
    with pytest.raises(ValueError,match='Expired'):
        q.query('test_run',digest,'shots',fields=['event_id','actor_name'],cursor=page['next_cursor'])
