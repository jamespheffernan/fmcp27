import copy
import json
import sqlite3

import pytest

from fm_live_mcp.observed_run_recorder import write_prefix
from fm_live_mcp import observed_run_registry as registry
from fm_live_mcp.observed_match_runs import open_run, catalog_runs, ObservedRunQueries


@pytest.fixture
def packet():
    return {'state':'verified_partial_prefix','same_career_epoch_verified':True,
        'incarnation_id':'1'*64,'cursor':100,
        'fixture':{'date':'2031-02-03','competition_id':9,'home_team_id':10,'away_team_id':20,'official_match_unique_id':123},
        'save':{'name':'Other career','created_date':'2030-01-01','created_version':'27','current_date':'2031-02-03','last_saved_date':'2031-02-02'},
        'actors':[{'side_index':0,'stored_player_slot':0,'canonical_person_id':70,'person_name':'Alice','identity_state':'verified'},
                  {'side_index':0,'stored_player_slot':1,'canonical_person_id':71,'person_name':None,'identity_state':'name_unavailable'}],
        'events':[{'event_id':1,'side_index':0,'stored_player_slot':0,'recipient_slot':1,'category':7,'flags_word':0,'start':50,'end':60},
                  {'event_id':2,'side_index':0,'stored_player_slot':0,'recipient_slot':1,'category':7,'flags_word':8,'start':70,'end':80}],
        'tracking':{'players':[{'side_index':0,'stored_player_slot':0,'start_tick':50,'samples_hex':'0000000001000200'}],
                    'orientation_profile_hex':'00'*16,'possession_samples_hex':'ff0000'},
        'period_markers':[],'period_state':'unknown','observed_at_unix':1234567890,'verification':{'fixed_time_slice':100,'verified_at_time_slice':101}}


def test_original_query_and_dedupe(packet,tmp_path,monkeypatch):
    monkeypatch.setattr(registry,'REGISTRY_PATH',tmp_path/'registry.json')
    receipt=write_prefix(packet,tmp_path/'store')
    assert receipt['completed_pass_events']==1
    registry.register_original(receipt['path'],receipt['source_id'],receipt['sha256'])
    with open_run(receipt['source_id'],receipt['sha256']) as (db,p):
        assert p['counts']['completed_pass_events']==1
        assert db.execute('SELECT receiver_name,period FROM completed_pass_events').fetchone()==(None,None)
        assert db.execute('SELECT samples FROM tracking_sources').fetchone()==(bytes.fromhex('0000000001000200'),)
    second=copy.deepcopy(packet);second['observed_at_unix']+=10;second['verification']['verified_at_time_slice']=105
    assert write_prefix(second,tmp_path/'store')['state']=='already_recorded'
    assert len(list((tmp_path/'store').glob('*.sqlite')))==1
    assert catalog_runs()['sources'][-1]['source_id']==receipt['source_id']
    result=ObservedRunQueries().query(receipt['source_id'],receipt['sha256'],'completed_pass_events')
    assert result


@pytest.mark.parametrize('change',['future_event','future_tracking','unverified'])
def test_rejects_unverified_selection(packet,tmp_path,change):
    if change=='future_event':packet['events'][0]['end']=100
    elif change=='future_tracking':packet['tracking']['players'][0]['start_tick']=100
    else:packet['same_career_epoch_verified']=False
    with pytest.raises(ValueError):write_prefix(packet,tmp_path)
    assert not list(tmp_path.glob('*.sqlite'))


def test_distinct_playthrough_and_changed_semantics_fork(packet,tmp_path):
    first=write_prefix(packet,tmp_path)
    packet['incarnation_id']='2'*64
    replay=write_prefix(packet,tmp_path)
    assert replay['source_id']!=first['source_id']
    packet['events'][0]['end']=61
    assert write_prefix(packet,tmp_path)['source_id']!=replay['source_id']


def test_registration_hash_and_protected_id(packet,tmp_path,monkeypatch):
    monkeypatch.setattr(registry,'REGISTRY_PATH',tmp_path/'registry.json')
    receipt=write_prefix(packet,tmp_path/'store')
    with pytest.raises(ValueError):registry.register_original(receipt['path'],'other','0'*64)
    with pytest.raises(ValueError):registry.register_original(receipt['path'],'newcastle_forest_2030_11_11_observed_run_182',receipt['sha256'])
    registry.register_original(receipt['path'],receipt['source_id'],receipt['sha256'])
    db=sqlite3.connect(receipt['path']);db.execute("UPDATE fixtures SET home_team_id=99");db.commit();db.close()
    with pytest.raises(ValueError):
        with open_run(receipt['source_id']):pass


def test_career_pin_and_corrupt_registry(packet,tmp_path,monkeypatch):
    monkeypatch.setattr(registry,'REGISTRY_PATH',tmp_path/'registry.json')
    receipt=write_prefix(packet,tmp_path/'store')
    registry.register_original(receipt['path'],receipt['source_id'],receipt['sha256'])
    document=json.loads(registry.REGISTRY_PATH.read_text())
    document['sources'][receipt['source_id']]['career']['name']='Wrong'
    registry.REGISTRY_PATH.write_text(json.dumps(document))
    with pytest.raises(ValueError,match='career'):
        with open_run(receipt['source_id']):pass


def test_dedupe_rejects_changed_analytical_cells(packet,tmp_path):
    receipt=write_prefix(packet,tmp_path)
    db=sqlite3.connect(receipt['path']);db.execute("UPDATE completed_pass_events SET sender_name='Other'");db.commit();db.close()
    with pytest.raises(ValueError,match='analytical'):
        write_prefix(packet,tmp_path)


def test_absent_and_failed_source_never_create_store(tmp_path,monkeypatch):
    from fm_live_mcp import observed_run_record_tools as tools
    monkeypatch.setenv('FM_LIVE_OBSERVED_STORE',str(tmp_path/'store'))
    monkeypatch.setattr(tools,'capture_prefix',lambda *args,**kwargs:{'state':'unavailable','reason':'absent','artifact_written':False})
    assert tools.record_current_match(None,'session')['artifact_written'] is False
    assert not (tmp_path/'store').exists()
    def drift(*args,**kwargs):raise ValueError('Consumed active pass event prefix changed')
    monkeypatch.setattr(tools,'capture_prefix',drift)
    with pytest.raises(ValueError,match='prefix changed'):tools.record_current_match(None,'session')
    assert not (tmp_path/'store').exists()


def test_capture_orchestration_and_epoch_rejection(packet,monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from fm_live_mcp import observed_run_recorder as recorder
    from fm_live_mcp import active_match_half_boundaries as periods
    process=SimpleNamespace(pid=12,version='27',executable='FM')
    class World:
        def verify(self):pass
    class Bridge:
        lock=nullcontext();world_identity=('career',)
        def _read_scope(self,sid):return nullcontext()
        def _current(self,sid):return process
        def _player_layout(self,p):return (recorder.players.RVA[0]+1000,)
        def _world_state(self,p,layout):return World(),packet['save'],None
        def _public_save(self,save):return save
        def _read_memory(self,p,a,n):return bytes(n)
    fixture={'date':'2031-02-03','competition':{'native_id':9},'home_team':{'native_id':10},'away_team':{'native_id':20}}
    private={'fixture':fixture,'binding':{'client':5000,'engine':6000},
        'bound':{'current_time_slice':100,'official_match_unique_id':123,'frame_provider_address':7000},
        'actors':{'state':'validated_native_stored_slots','official_match_unique_id':123,'players':packet['actors']},'source':{'cbe':8000,'events':packet['events']}}
    monkeypatch.setattr(recorder.passes,'_capture_components',lambda *args:({},private))
    monkeypatch.setattr(recorder.passes.active_match_people,'inspect_actor_bindings',lambda *args,**kwargs:copy.deepcopy(private['actors']))
    verified=[]
    monkeypatch.setattr(recorder.passes,'_verify_components',lambda *args:verified.append('passes') or {'state':'verified'})
    native={'state':'available_engine_tracking_source','tracking':{'players':[{'side_index':0,'stored_player_slot':0,'start_tick':50,'samples':bytes.fromhex('0000000001000200')}],'orientation_profile':bytes(16),'possession_samples':b'\xff'}}
    monkeypatch.setattr(recorder.tracking,'capture_source',lambda *args,**kwargs:native)
    monkeypatch.setattr(recorder.tracking,'verify_prefix',lambda *args:verified.append('tracking'))
    monkeypatch.setattr(periods,'inspect',lambda *args:{'state':'unknown','period_markers':[],'period_source':{'simulation_period':'FirstHalf'}})
    bridge=Bridge()
    captured=recorder.capture_prefix(bridge,'session')
    assert captured['fixture']==packet['fixture']
    assert verified==['tracking','passes']
    assert 'client' not in json.dumps(captured)
    original=bridge._current
    count=[0]
    def changed(sid):
        count[0]+=1
        return original(sid) if count[0]==1 else SimpleNamespace(pid=99,version='27',executable='FM')
    bridge._current=changed
    with pytest.raises(ValueError,match='epoch changed'):recorder.capture_prefix(bridge,'session')


def tactical_document(packet,monkeypatch):
    from fm_live_mcp import observed_run_tactical_capture as tactical
    flags=(1<<64)|(1<<84)
    plans={'content_sha256':'a'*64,'sides':[]}
    for side,team in enumerate((10,20)):
        instructions={'selected_options':[{'native_option_id':64,'name':None,'state':'no_native_label'}],
            'raw_selection_flags_hex':flags.to_bytes(11,'little').hex(),
            'unclassified_selected_bits':[84],'unmapped_serialized_bits':[]}
        plans['sides'].append({'side_index':side,'team':{'native_id':team},'plan':{
            'name':'Stored plan','mentality':{'native_code':9,'name':None,'state':'unmapped_native_code'},
            'team_instructions':instructions,'phases':{}}})
    bound={'current_time_slice':100,'official_match_unique_id':123,'playback_address':4000,'frame_provider_address':5000}
    calls=[]
    def playback(*args,**kwargs):
        calls.append(1)
        return {'state':'bound_playback_cursor','bound_playback':{**bound,'current_time_slice':100 if len(calls)%2 else 102}}
    monkeypatch.setattr(tactical.active_match_playback,'capture',playback)
    def inspect(*args,**kwargs):
        assert kwargs['include_raw_instructions'] is True
        return plans
    monkeypatch.setattr(tactical.resident_match_plans,'inspect',inspect)
    document=tactical.capture(lambda address,length:bytes(length),0,{'client':6000,'engine':7000,'team_indices':[1,2]},bound)
    assert document['state']=='available'
    document.update(fixture=packet['fixture'],source_incarnation_id=packet['incarnation_id'],
                    career={k:packet['save'][k] for k in ('name','created_date','created_version')})
    return document


def test_optional_tactics_preserve_unknown_flags_and_exact_attestation(packet,tmp_path,monkeypatch):
    from fm_live_mcp import observed_run_tactical_capture as tactical
    monkeypatch.setattr(registry,'REGISTRY_PATH',tmp_path/'registry.json')
    packet['tactical_observation']=tactical_document(packet,monkeypatch)
    receipt=write_prefix(packet,tmp_path/'store')
    proof=tactical.attestation(packet,receipt)
    registry.register_original(receipt['path'],receipt['source_id'],receipt['sha256'],producer_attestation=proof)
    loaded=registry.load_registrations()[receipt['source_id']]
    assert loaded['producer_attestation']['source_document_sha256']==proof['source_document_sha256']
    db=sqlite3.connect(receipt['path'])
    raw=db.execute("SELECT document_json FROM source_documents WHERE source_id='tactical_samples'").fetchone()[0]
    sample=json.loads(raw)['samples'][0]
    assert sample['score'] is None and sample['period'] is None
    assert sample['native_cursor_window']=={'start':100,'end':102}
    assert sample['sides'][0]['unclassified_selected_bits']==[84]
    assert sample['sides'][0]['options'][0]['name'] is None
    db.close()
    # Later verification time is not a new semantic observation or attestation.
    packet['tactical_observation']['samples'][0]['observed_at_unix']+=100
    reused=write_prefix(packet,tmp_path/'store')
    assert reused['state']=='already_recorded'
    assert tactical.attestation(packet,reused)==proof
    registry.register_original(reused['path'],reused['source_id'],reused['sha256'],producer_attestation=proof)


@pytest.mark.parametrize('change',['flags','career','incarnation','policy','cursor'])
def test_tactical_source_mismatch_rejects_before_publication(packet,tmp_path,monkeypatch,change):
    packet['tactical_observation']=tactical_document(packet,monkeypatch)
    document=packet['tactical_observation']
    if change=='flags':document['samples'][0]['sides'][0]['options']=[]
    elif change=='career':document['career']['name']='Other'
    elif change=='incarnation':document['source_incarnation_id']='3'*64
    elif change=='policy':document['policy']['native_guard_digest']='0'*64
    else:document['samples'][0]['native_cursor_window']['start']=99
    with pytest.raises(ValueError):write_prefix(packet,tmp_path)
    assert not list(tmp_path.glob('*.sqlite'))


def test_optional_tactical_failure_preserves_partial_prefix(packet,tmp_path):
    packet['tactical_observation']={'state':'unavailable','reason':'tactical_source_validation_failed'}
    receipt=write_prefix(packet,tmp_path)
    assert receipt['completed_pass_events']==1
    db=sqlite3.connect(receipt['path'])
    assert json.loads(db.execute("SELECT value_json FROM metadata WHERE key='tactical_collection_state'").fetchone()[0])=='unavailable'
    db.close()
