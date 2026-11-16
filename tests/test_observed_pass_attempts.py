"""Explicit synthetic recorder originals; no fresh game capture claim."""
from copy import deepcopy
import hashlib
import json
import sqlite3
import struct

import pytest
from fm_live_mcp import observed_pass_attempts as attempts, active_pass_attempts
from fm_live_mcp import observed_run_registry as registry, observed_run_recorder as recorder
from fm_live_mcp.observed_match_runs import open_run, ObservedRunQueries
from test_observed_run_recorder import packet


def enable(p):
    p['events'].append({'event_id':3,'side_index':0,'stored_player_slot':0,'recipient_slot':255,
        'category':10,'flags_word':256,'start':80,'end':90})
    for e in p['events']:
        if not e['flags_word']&8:e['location_xy_hex']=struct.pack('<ff',-10,20).hex()
    p['pass_attempt_observation']=attempts.capture_document(p,{'pass_attempt_policy':active_pass_attempts.source_policy(),
        'pitch_geometry':{'half_width_native':32.5,'half_length_native':50}})
    return p


def record(p,tmp_path,monkeypatch,*,attest=True):
    monkeypatch.setattr(registry,'REGISTRY_PATH',tmp_path/'registry.json')
    receipt=recorder.write_prefix(p,tmp_path/'store')
    proof=attempts.attestation(p,receipt) if attest else None
    registry.register_original(receipt['path'],receipt['source_id'],receipt['sha256'],pass_attempt_attestation=proof)
    return receipt,proof


def test_attested_attempts_preserve_schema1_completed_table_and_exact_points(packet,tmp_path,monkeypatch):
    enable(packet);r,proof=record(packet,tmp_path,monkeypatch)
    before=hashlib.sha256(open(r['path'],'rb').read()).hexdigest()
    with open_run(r['source_id'],r['sha256']) as (db,p):
        assert p['counts']['completed_pass_events']==1 and p['counts'][attempts.TABLE]==2
        assert json.loads(db.execute("SELECT value_json FROM metadata WHERE key='schema_version'").fetchone()[0])==1
        assert p['optional_derivations'][attempts.TABLE]['state']=='verified_derived_view'
    result=ObservedRunQueries().query(r['source_id'],r['sha256'],attempts.TABLE,limit=1)
    assert result['rows'][0]['outcome']=='completed' and result['next_cursor']
    q=ObservedRunQueries();first=q.query(r['source_id'],r['sha256'],attempts.TABLE,limit=1)
    last=q.query(r['source_id'],r['sha256'],attempts.TABLE,limit=1,cursor=first['next_cursor'])['rows'][0]
    assert last['outcome']=='not_completed' and last['receiver_slot'] is last['receiver_person_native_id'] is None
    assert last['native_secondary_byte']==255 and last['sender_person_native_id']==70
    assert (last['native_event_x'],last['native_event_y'],last['analytical_pitch_third'])==(-10.,20.,'attacking')
    assert last['period'] is None
    assert registry.load_registrations()[r['source_id']]['pass_attempt_attestation']==proof
    assert hashlib.sha256(open(r['path'],'rb').read()).hexdigest()==before
    assert recorder.write_prefix(packet,tmp_path/'store')['state']=='already_recorded'


@pytest.mark.parametrize('mode',['historical_without_xy','new_without_attestation'])
def test_unattested_not_promoted_to_checked_empty(packet,tmp_path,monkeypatch,mode):
    if mode=='new_without_attestation':enable(packet)
    r,_=record(packet,tmp_path,monkeypatch,attest=False)
    with open_run(r['source_id']) as (_,p):
        assert attempts.TABLE not in p['available_tables']
        assert p['optional_derivations'][attempts.TABLE]['state']=='unavailable'
    with pytest.raises(ValueError,match='not captured'):ObservedRunQueries().query(r['source_id'],r['sha256'],attempts.TABLE)


def test_explicit_attested_empty_has_verified_zero_rows(packet,tmp_path,monkeypatch):
    packet['events']=[];enable(packet);packet['events']=[];packet['pass_attempt_observation']['events']=[]
    r,_=record(packet,tmp_path,monkeypatch)
    with open_run(r['source_id']) as (_,p):
        assert p['counts'][attempts.TABLE]==0
        assert p['optional_derivations'][attempts.TABLE]['state']=='verified_derived_view'


@pytest.mark.parametrize('field',['policy','xy','events','actor','fixture','career','cursor','incarnation','geometry'])
def test_source_doc_disagreement_refuses_before_any_publication(packet,tmp_path,field):
    enable(packet);doc=packet['pass_attempt_observation']=deepcopy(packet['pass_attempt_observation'])
    if field=='policy':doc['policy']['native_guard_digest']='0'*64
    if field=='xy':del doc['events'][0]['location_xy_hex']
    if field=='events':doc['events']=[]
    if field=='actor':doc['actors'][0]['canonical_person_id']=999
    if field=='fixture':doc['fixture']['home_team_id']=999
    if field=='career':doc['career']['name']='Other'
    if field=='cursor':doc['fixed_time_slice']=99
    if field=='incarnation':doc['source_incarnation_id']='0'*64
    if field=='geometry':doc['pitch_geometry']['half_length_native']=0
    with pytest.raises(ValueError):recorder.write_prefix(packet,tmp_path/'store')
    assert not (tmp_path/'store').exists()


@pytest.mark.parametrize('field',['document_hash','policy','selection','incarnation'])
def test_attestation_changes_refuse_registration(packet,tmp_path,monkeypatch,field):
    enable(packet);monkeypatch.setattr(registry,'REGISTRY_PATH',tmp_path/'registry.json')
    r=recorder.write_prefix(packet,tmp_path/'store');proof=attempts.attestation(packet,r)
    if field=='document_hash':proof['source_document_sha256']='0'*64
    if field=='policy':proof['policy']['completed_category']=6
    if field=='selection':proof['selection_id']='0'*64
    if field=='incarnation':proof['source_incarnation_id']='0'*64
    with pytest.raises(ValueError):registry.register_original(r['path'],r['source_id'],r['sha256'],pass_attempt_attestation=proof)
    assert not registry.REGISTRY_PATH.exists()


@pytest.mark.parametrize('field',['native_event','actor_table','completed_table','terminal','doc','metadata'])
def test_independent_relational_crosschecks_reject_altered_database(packet,tmp_path,field):
    enable(packet);r=recorder.write_prefix(packet,tmp_path/'store');proof=attempts.attestation(packet,r)
    with sqlite3.connect(r['path']) as db:
        if field=='native_event':db.execute('UPDATE native_pass_events SET record_json=? WHERE event_id=3',(json.dumps({**packet['events'][-1],'end':91}),))
        if field=='actor_table':db.execute("UPDATE pass_actors SET person_name='Other' WHERE stored_player_slot=0")
        if field=='completed_table':db.execute('DELETE FROM completed_pass_events')
        if field=='terminal':
            terminal=json.loads(db.execute("SELECT document_json FROM source_documents WHERE source_id='terminal'").fetchone()[0]);terminal['fixture']['home_team_id']=999
            raw=recorder._json(terminal);db.execute("UPDATE source_documents SET document_json=?,sha256=? WHERE source_id='terminal'",(raw,hashlib.sha256(raw.encode()).hexdigest()))
        if field=='doc':db.execute("UPDATE source_documents SET document_json='{}' WHERE source_id='pass_attempt_samples'")
        if field=='metadata':db.execute("UPDATE metadata SET value_json='99' WHERE key='fixed_time_slice'")
        db.commit()
        with pytest.raises(ValueError):attempts.derive_pass_attempts(db,{'source_document_hashes':dict(db.execute('SELECT source_id,sha256 FROM source_documents'))},attestation=proof)


def test_recorder_tool_opt_in_schema_and_dispatch(monkeypatch):
    import asyncio
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp import observed_run_record_tools as tools
    calls=[];monkeypatch.setattr(tools,'record_current_match',lambda *a,**kw:calls.append(kw) or {'state':'unavailable'})
    async def check():
        m=FastMCP('attempt-recorder');tools.register_observed_run_record_tools(m,None)
        t=next(t for t in await m.list_tools() if t.name=='fm_record_current_match')
        assert t.inputSchema['properties']['include_incomplete_passes']['default'] is False
        assert not t.annotations.readOnlyHint
        await m.call_tool(t.name,{'session_id':'s','include_incomplete_passes':True,'include_tactics':False})
        assert calls==[{'include_tactics':False,'include_incomplete_passes':True}]
    asyncio.run(check())


@pytest.mark.parametrize('field',['xy','geometry','sender'])
def test_recorder_real_scope_exit_checks_incomplete_operands(monkeypatch,field):
    from test_observed_run_moving_prefix import controlled
    from fm_live_mcp import bridge as api
    c=controlled(monkeypatch)
    c.packet['source'].update(events=[{'event_id':999,'side_index':0,'stored_player_slot':0,'recipient_slot':255,
        'category':6,'flags_word':0,'start':1,'end':2,'location_xy_hex':struct.pack('<ff',1,2).hex()}],
        pitch_geometry={'half_width_native':32.5,'half_length_native':50},pass_attempt_policy=active_pass_attempts.source_policy())
    # Actual native scope calls the lifetime callback at exit; transport is synthetic.
    closed=[];calls=[]
    class Stream:
        def __init__(self,*a):pass
        def close(self):closed.append(True)
    monkeypatch.setattr(api,'ReadStream',Stream)
    c.bridge._reader=None;c.bridge.helper='/synthetic/never-executed'
    c.bridge._read_scope=api.Bridge._read_scope.__get__(c.bridge)
    original_current=c.bridge._current
    def current(sid):
        calls.append(1)
        if len(calls)==4:
            if field=='xy':c.packet['source']['events'][0]['location_xy_hex']=struct.pack('<ff',3,4).hex()
            elif field=='geometry':c.packet['source']['pitch_geometry']['half_width_native']=33
            else:c.fresh_actors['players'][0]['person_name']='Late incomplete sender'
        return original_current(sid)
    c.bridge._current=current
    monkeypatch.setattr(recorder.passes,'_capture_components',lambda *a,**kw:({},deepcopy(c.packet)))
    with pytest.raises(ValueError,match='prefix changed|geometry changed|actor changed'):
        recorder.capture_prefix(c.bridge,'controlled',include_tactics=False,include_incomplete_passes=True)
    assert len(calls)==4 and closed==[True] and c.bridge._reader is None


@pytest.mark.parametrize('failure',[False,True])
def test_cli_opt_in_and_literal_detach_on_unavailable_or_failure(monkeypatch,tmp_path,failure):
    from fm_live_mcp import bridge as api
    calls=[]
    class Bridge:
        def attach(self,pid):calls.append(('attach',pid));return {'session_id':'synthetic'}
        def detach(self):calls.append(('detach',));return {'detached':True}
    monkeypatch.setattr(api,'Bridge',Bridge)
    def capture(*a,**kw):
        calls.append(('capture',kw))
        if failure:raise ValueError('Explicit synthetic drift')
        return {'state':'unavailable'}
    monkeypatch.setattr(recorder,'capture_prefix',capture)
    monkeypatch.setattr('sys.argv',['recorder','--store',str(tmp_path/'store'),'--include-incomplete-passes','--without-tactics'])
    if failure:
        with pytest.raises(ValueError,match='synthetic drift'):recorder.main()
    else:recorder.main()
    assert calls==[('attach',None),('capture',{'include_tactics':False,'include_incomplete_passes':True}),('detach',)]
    assert not (tmp_path/'store').exists()


def test_attested_recorder_mask8_opaque_sender_without_xy_full_roundtrip(packet,tmp_path,monkeypatch):
    enable(packet)
    masked={'event_id':4,'side_index':0,'stored_player_slot':255,'recipient_slot':255,
            'category':6,'flags_word':8,'start':90,'end':91}
    packet['events'].append(masked)
    # Rebuild an explicitly synthetic coherent document; no historical bytes refilled.
    packet['pass_attempt_observation']=attempts.capture_document(packet,{
        'pass_attempt_policy':active_pass_attempts.source_policy(),
        'pitch_geometry':{'half_width_native':32.5,'half_length_native':50}})
    r,_=record(packet,tmp_path,monkeypatch)
    out=ObservedRunQueries().query(r['source_id'],r['sha256'],attempts.TABLE)
    assert [row['event_id'] for row in out['rows']]==[1,3]
    assert [row['outcome'] for row in out['rows']]==['completed','not_completed']
    with sqlite3.connect(r['path']) as db:
        assert json.loads(db.execute('SELECT record_json FROM native_pass_events WHERE event_id=4').fetchone()[0])==masked
        assert db.execute('SELECT count(*) FROM completed_pass_events').fetchone()==(1,)
    # Dedupe still checks all raw metadata, including excluded events.
    assert recorder.write_prefix(packet,tmp_path/'store')['state']=='already_recorded'
    included=deepcopy(packet);included['events'][-1]['flags_word']=0
    included['events'][-1]['location_xy_hex']=struct.pack('<ff',1,2).hex()
    included['pass_attempt_observation']['events']=included['events']
    with pytest.raises(ValueError):recorder.write_prefix(included,tmp_path/'included_invalid')
    assert not (tmp_path/'included_invalid').exists()
    # Default old-path validation remains unchanged.
    legacy=deepcopy(packet);del legacy['pass_attempt_observation']
    with pytest.raises(ValueError,match='Ambiguous pass identity'):recorder.write_prefix(legacy,tmp_path/'legacy')
