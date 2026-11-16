import json
import sqlite3
import pytest
from fm_live_mcp.match_dataset import export_dataset
from fm_live_mcp import captured_match_sources as sources
from fm_live_mcp.captured_match_query import CapturedMatchQueries
from fm_live_mcp.captured_match_tools import register_captured_match_tools

SOURCE='newcastle_2030_10_28'

def original(tmp_path,monkeypatch,*,source_id=SOURCE,count=20,competition=11,payload=''):
    path=tmp_path/(source_id+'.sqlite')
    capture={'save':dict(sources.EXPECTED_CAREER,current_date='2030-11-02',last_saved_date='2030-10-30'),
             'source_kind':'running_session_active_fd','fixtures':[{'native_match_key':i+1,'fixture':{'date':'2030-10-01' if i<10 else '2030-10-20','home_team':{'native_id':688},'away_team':{'native_id':999},'competition':{'native_id':competition}}} for i in range(count)]}
    rows=[dict(fixture_key=i+1,side_index=side,person_index_word=side+10,stored_player_slot=0,person_name='Own' if side==0 else 'Opponent',minutes=90,payload=payload) for i in range(count) for side in (0,1)]
    export_dataset(path,capture,source='bounded_live_export',retained_players=rows)
    monkeypatch.setattr(sources,'SOURCES',{source_id:path})
    with sources.open_source(source_id) as (_,provenance):pass
    return path,provenance

def test_source_catalog_dates_columns_career_scope_and_no_paths(tmp_path,monkeypatch):
    _,p=original(tmp_path,monkeypatch)
    catalog=sources.catalog_sources()['sources'][0]
    assert catalog['source_kind']=='captured_live_export' and catalog['captured_save']['current_date']=='2030-11-02'
    assert catalog['date_coverage']=={'from':'2030-10-01','to':'2030-10-20'}
    assert 'minutes' in catalog['available_tables']['retained_players']
    with pytest.raises(ValueError,match='Unknown named'):
        with sources.open_source('/tmp/other.sqlite'):pass
    with pytest.raises(ValueError,match='career pin'):
        with sources.open_source(SOURCE,p['capture_id'],'a'*64):pass

def test_filtered_pinned_deterministic_pages_and_both_sides(tmp_path,monkeypatch):
    _,p=original(tmp_path,monkeypatch);q=CapturedMatchQueries()
    args=dict(table='retained_players',fields=['native_match_key','side_index','person_name'],date_from='2030-10-15',date_to='2030-10-28',competition_native_id=11,team_native_id=688,limit=3)
    first=q.query(SOURCE,p['capture_id'],**args);rows=first['rows'];page=first
    while page['next_cursor']:
        page=q.query(SOURCE,p['capture_id'],cursor=page['next_cursor'],**args);rows+=page['rows']
    assert len(rows)==20 and rows==sorted(rows,key=lambda x:(x['native_match_key'],x['side_index']))
    assert {r['person_name'] for r in rows}=={'Own','Opponent'}
    assert 'BOTH' in first['team_filter_semantics']
    with pytest.raises(ValueError,match='changed captured selectors'):
        q.query(SOURCE,p['capture_id'],cursor=first['next_cursor'],**dict(args,team_native_id=999))
    assert q.query(SOURCE,p['capture_id'],table='player_match_analysis',fields=['minutes'],limit=1)['rows']==[{'minutes':90}]

def test_reject_changed_bytes_schema_career_and_wrong_scope(tmp_path,monkeypatch):
    path,p=original(tmp_path,monkeypatch);q=CapturedMatchQueries();first=q.query(SOURCE,p['capture_id'],limit=1)
    db=sqlite3.connect(path);db.execute("UPDATE metadata SET value_json='4' WHERE key='schema_version'");db.commit();db.close()
    with pytest.raises(ValueError,match='export changed'):
        q.query(SOURCE,p['capture_id'],cursor=first['next_cursor'],limit=1)
    db=sqlite3.connect(path);db.execute("UPDATE metadata SET value_json='99' WHERE key='schema_version'");db.commit();db.close()
    with pytest.raises(ValueError,match='schema version'):
        with sources.open_source(SOURCE):pass
    db=sqlite3.connect(path);db.execute("UPDATE metadata SET value_json='1' WHERE key='schema_version'");db.execute('UPDATE metadata SET value_json=? WHERE key=?',(json.dumps(dict(sources.EXPECTED_CAREER,name='Other career')),'save'));db.commit();db.close()
    with pytest.raises(ValueError,match='career does not match'):
        with sources.open_source(SOURCE):pass
    # A valid same-career PL original cannot impersonate Newcastle's20-fixture source.
    other,pp=original(tmp_path,monkeypatch,source_id='premier_league_2030_10_28',count=91)
    monkeypatch.setattr(sources,'SOURCES',{SOURCE:other})
    with pytest.raises(ValueError,match='Newcastle source scope'):
        with sources.open_source(SOURCE):pass

def test_byte_bound_unknown_fields_and_sql_rejected(tmp_path,monkeypatch):
    _,p=original(tmp_path,monkeypatch,payload='x'*270000);q=CapturedMatchQueries()
    with pytest.raises(ValueError,match='One row exceeds'):
        q.query(SOURCE,p['capture_id'],table='retained_players',fields=['raw_json'])
    for table,fields in [('fixtures;DROP TABLE fixtures',None),('fixtures',['date;DROP TABLE fixtures'])]:
        with pytest.raises(ValueError):q.query(SOURCE,p['capture_id'],table=table,fields=fields)
    with pytest.raises(ValueError):q.query(SOURCE,p['capture_id'],limit=501)

def test_tools_discoverable_readonly_without_session_or_sql():
    from mcp.server.fastmcp import FastMCP
    import asyncio
    mcp=FastMCP('offline');register_captured_match_tools(mcp)
    tools={t.name:t for t in asyncio.run(mcp.list_tools())}
    assert set(tools)=={'fm_list_captured_match_sources','fm_query_captured_match_data'}
    schema=tools['fm_query_captured_match_data'].inputSchema['properties']
    assert 'capture_id' in schema and not({'session_id','path','sql'}&schema.keys())
    assert tools['fm_query_captured_match_data'].annotations.readOnlyHint


def test_older_sources_keep_optional_shot_tables_unavailable(tmp_path,monkeypatch):
    _,p=original(tmp_path,monkeypatch)
    assert p['retained_shot_coverage']=={'state':'not_captured','scope':'whole_registered_capture','side_rows':None,'states':None}
    assert 'shots' not in p['available_tables']
    with pytest.raises(ValueError,match='Table unavailable'):
        CapturedMatchQueries().query(SOURCE,p['capture_id'],table='shots')
