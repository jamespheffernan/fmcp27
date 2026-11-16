"""Captured Lille tracking bytes; synthetic moving transport, never fresh live proof."""
from contextlib import nullcontext
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sqlite3
import struct
from types import SimpleNamespace

import pytest

from fm_live_mcp import observed_run_recorder as recorder, active_match_period as period
from fm_live_mcp import active_match_playback, active_match_half_boundaries as halves


def controlled(monkeypatch):
    original=json.loads(gzip.decompress((Path(__file__).parent/'fixtures/active_lille_tracking_cursor.json.gz').read_bytes()))
    assert original['observed_readset_verified'] is True
    native=deepcopy(original['source'])
    for key in ('orientation_profile','possession_samples'):native['tracking'][key]=bytes.fromhex(native['tracking'][key])
    for row in native['tracking']['players']:row['samples']=bytes.fromhex(row['samples'])
    bound=original['bound'];fixed=bound['current_time_slice'];uid=bound['official_match_unique_id']
    client,engine,wrapper,cbe=10000,20000,30000,40000
    binding=dict(client=client,engine=engine,team_indices=[original['fixture'][key]['database_index'] for key in ('home_team','away_team')])
    native.update(source_identity=(client,engine,('controlled_owner',)),cbe_address=cbe,engine_frontier_raw=fixed+50)
    source=dict(state='available',events=[],cbe=cbe,match_unique_id=uid,fixture_identity=('controlled_fixture',))
    packet=dict(fixture=original['fixture'],binding=binding,bound=bound,actors=original['actors'],source=source)
    fresh_tracking=deepcopy(native);fresh_actors=deepcopy(original['actors']);playback=dict(bound,current_time_slice=fixed+5)
    memory={}
    def put(address,raw):
        for i,byte in enumerate(raw):
            assert address+i not in memory or memory[address+i]==byte
            memory[address+i]=byte
    for rva,raw in halves.NATIVE_SPANS+period.NATIVE_SPANS+recorder.passes.active_match_shot_timeline.DOMAIN_SPANS:put(rva,raw)
    put(bound['playback_address'],struct.pack('<Q',0x54ec490))
    put(bound['playback_address']+0x10,struct.pack('<Q',bound['playback_address']))
    put(bound['playback_address']+0x1408,struct.pack('<Q',bound['frame_provider_address']))
    put(bound['frame_provider_address']+0x28,struct.pack('<Q',bound['source_match_address']))
    put(bound['source_match_address'],struct.pack('<Q',0x55fa258))
    put(bound['source_match_address']+0x20,struct.pack('<Q',uid))
    # Actual unchanged optional getter sees a later cursor and raises its exact error.
    put(bound['playback_address']+0x1dc0,struct.pack('<I',fixed+5))
    for address,value in [(engine+0x20,uid),(client+0x138,uid),(engine+0x14e98,cbe),(client+0xf8,wrapper),(wrapper+0x18,engine)]:
        put(address,struct.pack('<Q',value))
    put(engine+0x154dc,struct.pack('<I',fixed+50))
    def read(address,size):return bytes(memory.get(address+i,0)for i in range(size))
    class World:
        def verify(self):pass
    process=SimpleNamespace(pid=1,version='27',executable='controlled')
    bridge=SimpleNamespace(lock=nullcontext(),world_identity=('captured_career',),
        _read_scope=lambda sid:nullcontext(),_current=lambda sid:process,
        _player_layout=lambda p:(recorder.players.RVA[0],),
        _world_state=lambda p,t:(World(),original['save'],None),_public_save=lambda save:save,
        _read_memory=lambda p,a,n:read(a,n))
    monkeypatch.setattr(recorder.passes,'_capture_components',lambda *args:({},deepcopy(packet)))
    # Preserve the real fixed-prefix monotonic verification implementations.
    monkeypatch.setattr(active_match_playback,'capture',lambda *args,**kwargs:dict(state='bound_playback_cursor',bound_playback=deepcopy(playback)))
    monkeypatch.setattr(recorder.passes.active_match_source,'inspect_context',lambda *args,**kwargs:({'bound_active_fixture':original['fixture']},binding))
    monkeypatch.setattr(recorder.passes,'capture_source',lambda *args,**kwargs:deepcopy(source))
    monkeypatch.setattr(recorder.passes.active_match_people,'inspect_actor_bindings',lambda *args,**kwargs:deepcopy(fresh_actors))
    count=[]
    def capture(*args,**kwargs):
        assert kwargs['current_time_slice']==fixed
        count.append(1)
        result=deepcopy(native if len(count)==1 else fresh_tracking)
        result['tracking']=recorder.tracking.clip_tracking(result['tracking'],fixed)
        return result
    monkeypatch.setattr(recorder.tracking,'capture_source',capture)
    return SimpleNamespace(original=original,bridge=bridge,packet=packet,native=native,fresh_tracking=fresh_tracking,
        fresh_actors=fresh_actors,playback=playback,memory=memory,read=read,fixed=fixed,uid=uid,count=count)


def capture(control):return recorder.capture_prefix(control.bridge,'controlled_session',include_tactics=False)


def test_captured_tracking_positive_with_controlled_monotonic_cursor_preserves_raw_prefix(tmp_path,monkeypatch):
    c=controlled(monkeypatch)
    with pytest.raises(ValueError,match='Checked playback time slice changed'):
        halves.inspect(c.read,0,c.packet['bound'])
    result=capture(c)
    assert result['state']=='verified_partial_prefix' and result['cursor']==4559
    assert result['period_state']=='unknown' and result['period_reason']=='optional_period_cursor_changed'
    assert result['period_markers']==[] and result['terminal_completeness_verified'] is False
    assert result['verification']['fixed_time_slice']==4559 and result['verification']['verified_at_time_slice']==4564
    assert result['match_statistics_observation']['state']=='unavailable'
    assert len(result['tracking']['players'])==22
    assert sum(len(bytes.fromhex(row['samples_hex']))//4 for row in result['tracking']['players'])==4158
    assert result['tracking']['orientation_profile_hex']==c.native['tracking']['orientation_profile'].hex()
    assert result['tracking']['possession_samples_hex']==c.native['tracking']['possession_samples'].hex()
    receipt=recorder.write_prefix(result,tmp_path/'synthetic_transport_artifact')
    with sqlite3.connect(receipt['path']) as db:
        stored=db.execute('SELECT side_index,stored_player_slot,start_tick,samples FROM tracking_sources ORDER BY side_index,stored_player_slot').fetchall()
        expected=sorted((row['side_index'],row['stored_player_slot'],row['start_tick'],row['samples']) for row in c.native['tracking']['players'])
        assert stored==expected
        assert db.execute("SELECT value_json FROM metadata WHERE key='period_reason'").fetchone()==('"optional_period_cursor_changed"',)


@pytest.mark.parametrize('field',['rewind','relink','incarnation','owner','xy','phase','profile','phase_extent',
    'tracking_actor','actor_ordinal','actor_name','actor_match'])
def test_nearby_source_drift_still_rejects_fixed_prefix(monkeypatch,field):
    c=controlled(monkeypatch)
    if field=='rewind':c.playback['current_time_slice']=c.fixed-1
    if field=='relink':c.playback['frame_provider_address']+=8
    if field=='incarnation':c.playback['local_playback_handle']+=1
    if field=='owner':
        address=10000+0x138
        for i,b in enumerate(struct.pack('<Q',c.uid+1)):c.memory[address+i]=b
    if field=='xy':
        row=c.fresh_tracking['tracking']['players'][0];row['samples']=bytes([row['samples'][0]^1])+row['samples'][1:]
    if field=='phase':
        raw=c.fresh_tracking['tracking']['possession_samples'];c.fresh_tracking['tracking']['possession_samples']=bytes([raw[0]^1])+raw[1:]
    if field=='profile':
        raw=c.fresh_tracking['tracking']['orientation_profile'];c.fresh_tracking['tracking']['orientation_profile']=raw[:8]+bytes([raw[8]^1])+raw[9:]
    if field=='phase_extent':c.fresh_tracking['tracking']['possession_samples']+=b'\xff'  # clipped when beyond fixed prefix
    if field=='tracking_actor':c.fresh_actors['players'][0]['canonical_person_id']+=999999
    if field=='actor_ordinal':c.fresh_actors['players'][0]['person_index_word']+=1
    if field=='actor_name':c.fresh_actors['players'][0]['person_name']='Replacement'
    if field=='actor_match':c.fresh_actors['official_match_unique_id']+=1
    if field=='phase_extent':
        # Changing beyond the fixed prefix is allowed; actual consumed bytes stay identical.
        assert capture(c)['cursor']==c.fixed
    else:
        with pytest.raises(ValueError):capture(c)


def test_appended_future_tracking_samples_do_not_enter_fixed_artifact(monkeypatch):
    c=controlled(monkeypatch)
    for row in c.fresh_tracking['tracking']['players']:row['samples']+=b'\xff\x7f\xff\x7f'
    result=capture(c)
    assert result['tracking']['players'][0]['samples_hex']==c.native['tracking']['players'][0]['samples'].hex()


def test_other_optional_period_native_error_is_not_swallowed(monkeypatch):
    c=controlled(monkeypatch)
    rva,_=halves.NATIVE_SPANS[0];c.memory[rva]^=1
    with pytest.raises(ValueError,match='native source changed'):capture(c)


def test_noncompleted_event_actor_is_part_of_recorded_population(monkeypatch):
    c=controlled(monkeypatch)
    tracked={(r['side_index'],r['stored_player_slot'])for r in c.native['tracking']['players']}
    actor=next(r for r in c.packet['actors']['players']if(r['side_index'],r['stored_player_slot'])not in tracked)
    c.packet['source']['events'].append(dict(event_id=999,category=10,flags_word=0,
        side_index=actor['side_index'],stored_player_slot=actor['stored_player_slot'],recipient_slot=0,start=1,end=2))
    replacement=next(r for r in c.fresh_actors['players']if(r['side_index'],r['stored_player_slot'])==
        (actor['side_index'],actor['stored_player_slot']))
    replacement['person_name']='Changed noncompleted-event actor'
    with pytest.raises(ValueError,match='recorded canonical actor'):capture(c)


@pytest.mark.parametrize('callback',['current','world_verify','public_save'])
@pytest.mark.parametrize('field',['profile','tracking_actor'])
def test_lifetime_callbacks_precede_final_consumed_source_checks(monkeypatch,callback,field):
    c=controlled(monkeypatch)
    def mutate():
        if field=='profile':
            raw=c.fresh_tracking['tracking']['orientation_profile']
            c.fresh_tracking['tracking']['orientation_profile']=raw[:8]+bytes([raw[8]^1])+raw[9:]
        else:c.fresh_actors['players'][0]['person_name']='Late lifetime callback actor'
    if callback=='current':
        original=c.bridge._current;calls=[]
        def current(sid):
            calls.append(sid)
            if len(calls)==2:mutate()
            return original(sid)
        c.bridge._current=current
    elif callback=='world_verify':
        original=c.bridge._world_state;calls=[]
        def state(*args):
            value=original(*args);calls.append(1)
            if len(calls)==2:
                verify=value[0].verify
                def final_verify():
                    verify();mutate()
                value[0].verify=final_verify
            return value
        c.bridge._world_state=state
    else:
        original=c.bridge._public_save
        def public(save):
            value=original(save);mutate();return value
        c.bridge._public_save=public
    with pytest.raises(ValueError,match='portable tracking|recorded canonical actor|Unsupported tracking orientation boundaries'):capture(c)


def test_optional_statistics_finish_follows_base_source_verification(monkeypatch):
    from test_observed_run_match_statistics import packet_and_document
    from fm_live_mcp import observed_run_match_statistics as statistics
    c=controlled(monkeypatch);_,document=packet_and_document(monkeypatch)
    document['official_match_unique_id']=c.uid;document['fixed_time_slice']=c.fixed
    document['shots']['official_match_unique_id']=c.uid
    document['score'].update(official_match_unique_id=c.uid,current_time_slice=c.fixed)
    document['score']['current_score']['at_time_slice']=c.fixed
    valid=[True]
    class Proof:
        def verify(self):
            if not valid[0]:raise ValueError('Base verifier observed optional byte drift')
    monkeypatch.setattr(statistics,'capture',lambda *args:(deepcopy(document),Proof()))
    original=recorder.passes._verify_components
    def verify(*args,**kwargs):
        result=original(*args,**kwargs);valid[0]=False;return result
    monkeypatch.setattr(recorder.passes,'_verify_components',verify)
    result=capture(c)
    assert result['match_statistics_observation']['state']=='unavailable'
    assert 'optional_match_statistics_changed' in result['match_statistics_observation']['reason']
