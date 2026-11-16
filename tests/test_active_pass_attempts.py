"""Original fixture bytes plus explicit synthetic mutation/transport controls."""
from contextlib import nullcontext
from copy import deepcopy
import gzip
import json
from pathlib import Path
import struct
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fm_live_mcp import active_pass_attempts as attempts, active_pass_network as network
from fm_live_mcp import active_pass_locations as locations
from test_active_pass_network import event, actors, fixture, packet, mock_verify


def located(i=0, **kw):
    raw=bytearray(event(i,**kw));struct.pack_into('<ff',raw,24,10,20);return bytes(raw)


def selected(raw):
    return network.select_events(raw,100,include_locations=True,include_pass_attempts=True)


def project(raw, **kw):
    return attempts.project(selected(raw),kw.get('actors',actors()),fixture(),
        {'half_width_native':32.5,'half_length_native':50},cursor=100,official_match_unique_id=42)


def test_native_outcomes_and_secondary_not_recipient():
    rows=project(b''.join(located(i,category=cat,receiver=255 if cat!=7 else 1) for i,cat in enumerate(range(6,12))))
    assert len(rows)==6
    assert [r['outcome'] for r in rows]==['not_completed','completed','not_completed','not_completed','not_completed','not_completed']
    for r in rows:
        assert r['native_pass_map_location']=={'native_x':10.,'native_y':20.}
        assert r['analytical_pitch_third']=='defensive' and r['from_person_native_id']==100
        assert r['possession_loss_event_link'] is r['specific_failure_reason'] is r['tactical_cause'] is None
        if not r['completed']:
            assert r['recipient_slot'] is r['to_person_native_id'] is r['to_name'] is None
            assert r['native_secondary_byte']==255 and r['recipient_state']=='not_decoded_for_not_completed_attempt'
    assert attempts.summarize(rows)['not_completed_event_count']==5


def test_mask8_ties_future_and_unrelated_categories_excluded():
    raw=located(0,category=6,flags=8)+located(1,category=6,end=100)+located(2,category=6,end=101)+located(3,category=52)+located(4,category=6)
    assert [r['event_id'] for r in project(raw)]==[4]
    # Default completed-only location inputs do not change.
    assert all('location_xy_hex' not in r for r in network.select_events(raw,100,include_locations=True))


def test_unknown_sender_and_completed_recipient_are_separate():
    a=actors();a['players']=[p for p in a['players'] if p['stored_player_slot']!=1]
    rows=project(located(0,category=6)+located(1,category=7)+located(2,category=6,sender=1),actors=a)
    assert rows[0]['sender_state']=='canonical_original_slot'
    assert rows[1]['sender_state']=='canonical_original_slot' and rows[1]['recipient_state']=='unresolved_completed_recipient'
    assert rows[2]['sender_state']=='unresolved_original_slot' and rows[2]['from_person_native_id'] is None


@pytest.mark.parametrize('change',['missing_xy','nan','duplicate','bad_slot','reversed','bad_actor','bool_field'])
def test_malformed_consumed_sources_refused(change):
    events=selected(located(category=6));a=actors()
    if change=='missing_xy':del events[0]['location_xy_hex']
    if change=='nan':events[0]['location_xy_hex']=struct.pack('<ff',float('nan'),0).hex()
    if change=='duplicate':events*=2
    if change=='bad_slot':events[0]['stored_player_slot']=26
    if change=='reversed':events[0]['start']=99
    if change=='bad_actor':a['players'].append(deepcopy(a['players'][0]))
    if change=='bool_field':events[0]['flags_word']=False
    with pytest.raises(ValueError):attempts.project(events,a,fixture(),{'half_width_native':32.5,'half_length_native':50},cursor=100,official_match_unique_id=42)


def test_native_guard_every_span_exact():
    spans=attempts.live_retained_pass_events.ATTEMPT_NATIVE_SPANS+attempts.pass_field_position.NATIVE_SPANS
    memory={at+i:b for at,raw in spans for i,b in enumerate(raw)}
    read=lambda a,n:bytes(memory[a+i] for i in range(n))
    attempts.verify_native(read,0)
    for at,raw in spans:
        memory[at]^=1
        with pytest.raises(ValueError,match='native source'):attempts.verify_native(read,0)
        memory[at]^=1


def test_original_genuine_raw_fixture_all_attempt_points_independent_oracle():
    f=json.loads(gzip.decompress((Path(__file__).parent/'fixtures/active_pass_locations_185.json.gz').read_bytes()))
    raw=bytes.fromhex(f['raw_event_hex']);events=network.select_events(raw,f['cursor'],include_locations=True,include_pass_attempts=True)
    rows=attempts.project(events,f['actors'],f['fixture'],f['pitch_geometry'],cursor=f['cursor'],official_match_unique_id=f['match_unique_id'])
    expected={}
    for at in range(0,len(raw),56):
        e=raw[at:at+56];flags=int.from_bytes(e[48:50],'little')
        if e[42] not in range(6,12) or flags&8 or int.from_bytes(e[50:52],'little')>=f['cursor']:continue
        expected[int.from_bytes(e[44:48],'little')]=(e[42]==7,struct.unpack_from('<ff',e,24),e[41])
    assert len(rows)==len(expected)>1020 and sum(r['completed'] for r in rows)==1020
    assert any(not r['completed'] for r in rows)
    for r in rows:
        success,xy,secondary=expected[r['event_id']]
        assert r['completed']==success and tuple(r['native_pass_map_location'].values())==xy
        assert r['native_secondary_byte']==secondary
        assert success or r['to_person_native_id'] is None


def test_current_api_independent_sender_coverage_pagination_and_selectors(monkeypatch):
    p=packet();p['source'].update(events=selected(located(0,category=6)+located(1,category=6,sender=1)+located(2,category=7,receiver=9)),pitch_geometry={'half_width_native':32.5,'half_length_native':50},pass_attempt_policy=attempts.source_policy())
    result=network.project(p['source']['events'],p['actors'],p['fixture'],cursor=100,match_unique_id=42)
    assert result['sides'][0]['state']=='unavailable_actor_coverage'
    result.update(source_id='fixed',observed_at='original',prefix_verification={'verified_at_time_slice':100})
    capture=Mock(return_value=(result,p,('epoch',)));monkeypatch.setattr(network,'current_pass_network',capture)
    verify=Mock();monkeypatch.setattr(locations,'_verify_page',verify);attempts._CACHE.clear()
    b=SimpleNamespace(lock=nullcontext())
    first=locations.current_pass_events(b,'s',pass_outcome='not_completed',limit=1)
    second=locations.current_pass_events(b,'s',pass_outcome='not_completed',limit=1,cursor=first['next_cursor'])
    assert [r['event_id'] for page in (first,second) for r in page['events']]==[0,1]
    assert first['state']=='available' and first['capture_id']==second['capture_id']=='fixed'
    assert capture.call_count==1 and verify.call_count==1
    assert capture.call_args.kwargs['_include_pass_attempts'] is True
    with pytest.raises(ValueError,match='selectors'):locations.current_pass_events(b,'s',pass_outcome='all',limit=1,cursor=first['next_cursor'])
    with pytest.raises(ValueError,match='Recipient'):locations.current_pass_events(b,'s',pass_outcome='not_completed',to_person_native_id=101)


def native_scope(monkeypatch,p,mutate,*,exit_count=4):
    """Real Bridge._read_scope, explicit synthetic transport, no helper/process calls."""
    from fm_live_mcp import bridge as api, players
    fresh_source=deepcopy(p['source']);fresh_actors=deepcopy(p['actors'])
    read=mock_verify(monkeypatch,p)
    monkeypatch.setattr(network,'capture_source',lambda *a,**k:deepcopy(fresh_source))
    monkeypatch.setattr(network.active_match_people,'inspect_actor_bindings',lambda *a,**k:deepcopy(fresh_actors))
    closed=[];calls=[]
    class Stream:
        def __init__(self,*a):pass
        def close(self):closed.append(True)
    monkeypatch.setattr(api,'ReadStream',Stream)
    b=api.Bridge.__new__(api.Bridge);b._reader=None;b.helper=Path('/synthetic/never-executed');b.lock=nullcontext();b.world_identity='career'
    process=SimpleNamespace(pid=1,version='v',executable='synthetic')
    def current(sid):
        calls.append(sid)
        if len(calls)==exit_count:mutate(fresh_source,fresh_actors)
        return process
    b._current=current;b._player_layout=lambda p:(players.RVA[0],)
    save={'current_date':'2030-11-06'}
    b._world_state=lambda *a:(SimpleNamespace(verify=lambda:None),save,None)
    b._public_save=lambda s:s;b._read_memory=lambda proc,a,n:read(a,n)
    monkeypatch.setattr(network,'_capture_components',lambda *a,**k:(network.project(p['source']['events'],p['actors'],p['fixture'],cursor=100,match_unique_id=42),deepcopy(p)))
    return b,closed,calls


@pytest.mark.parametrize('field',['xy','geometry','sender'])
@pytest.mark.parametrize('route',['network','page'])
def test_real_bridge_scope_exit_callback_changes_are_fatal(monkeypatch,field,route):
    p=packet();p['source'].update(events=selected(located(category=6,sender=1,receiver=255)),pitch_geometry={'half_width_native':32.5,'half_length_native':50},pass_attempt_policy=attempts.source_policy())
    def mutate(source,a):
        if field=='xy':source['events'][0]['location_xy_hex']=struct.pack('<ff',11,20).hex()
        elif field=='geometry':source['pitch_geometry']['half_width_native']=33
        else:a['players'][1]['person_name']='changed incomplete sender'
    b,closed,calls=native_scope(monkeypatch,p,mutate,exit_count=4)
    with pytest.raises(ValueError,match='prefix changed|geometry changed|actor changed'):
        if route=='network':network.current_pass_network(b,'s',_include_locations=True,_include_pass_attempts=True)
        else:locations._verify_page(b,'s',{'packet':p,'epoch':(1,'v','synthetic',(network.players.RVA[0],),'career'),'last_cursor':100})
    assert len(calls)==4 and closed==[True] and b._reader is None


def test_real_bridge_scope_stable_no_callback_after_seal(monkeypatch):
    p=packet();p['source'].update(events=selected(located(category=6)),pitch_geometry={'half_width_native':32.5,'half_length_native':50},pass_attempt_policy=attempts.source_policy())
    b,closed,calls=native_scope(monkeypatch,p,lambda *args:None)
    assert network.current_pass_network(b,'s',_include_locations=True,_include_pass_attempts=True)['same_session_fixed_event_selection_verified'] is True
    assert len(calls)==4 and closed==[True]


def test_attempt_capture_id_binds_incomplete_sender_identity(monkeypatch):
    p=packet();p['source'].update(events=selected(located(category=6,sender=1)),pitch_geometry={'half_width_native':32.5,'half_length_native':50},pass_attempt_policy=attempts.source_policy())
    b,_,_=native_scope(monkeypatch,p,lambda *a:None)
    first=network.current_pass_network(b,'s',_include_locations=True,_include_pass_attempts=True)['source_id']
    p['actors']['players'][1]['person_name']='Different canonical sender sample'
    b,_,_=native_scope(monkeypatch,p,lambda *a:None)
    second=network.current_pass_network(b,'s',_include_locations=True,_include_pass_attempts=True)['source_id']
    assert first!=second


def test_person_filter_cannot_turn_unknown_senders_into_checked_zero(monkeypatch):
    p=packet();p['source'].update(events=selected(located(category=6,sender=7)),pitch_geometry={'half_width_native':32.5,'half_length_native':50},pass_attempt_policy=attempts.source_policy())
    result=network.project(p['source']['events'],p['actors'],p['fixture'],cursor=100,match_unique_id=42)
    result.update(source_id='fixed',observed_at='original',prefix_verification={'verified_at_time_slice':100})
    monkeypatch.setattr(network,'current_pass_network',lambda *a,**kw:(result,p,('epoch',)))
    b=SimpleNamespace(lock=nullcontext())
    out=locations.current_pass_events(b,'s',pass_outcome='not_completed',from_person_native_id=100)
    assert out['events']==[] and out['state']=='available_partial'
    assert out['unresolved_source_sender_count']==1
    assert out['person_filter_coverage']=='partial_unknown_senders_cannot_be_attributed'


def test_current_mask8_opaque_sender_without_xy_ignored_but_included_invalid_refused(monkeypatch):
    raw=located(0,category=6,flags=8,sender=255)+located(1,category=6)
    p=packet();p['source'].update(events=selected(raw),pitch_geometry={'half_width_native':32.5,'half_length_native':50},pass_attempt_policy=attempts.source_policy())
    assert 'location_xy_hex' not in p['source']['events'][0]
    result=network.project(p['source']['events'],p['actors'],p['fixture'],cursor=100,match_unique_id=42)
    result.update(source_id='masked',observed_at='original',prefix_verification={'verified_at_time_slice':100})
    assert result['state']=='available'  # Existing completed semantics ignore the masked record.
    monkeypatch.setattr(network,'current_pass_network',lambda *a,**kw:(result,p,('epoch',)))
    out=locations.current_pass_events(SimpleNamespace(lock=nullcontext()),'s',pass_outcome='not_completed')
    assert [r['event_id'] for r in out['events']]==[1]
    assert out['events'][0]['from_person_native_id']==100
    included=selected(located(0,category=6,sender=255)+located(1,category=6))
    with pytest.raises(ValueError,match='identity/actor/clock'):
        attempts.project(included,p['actors'],p['fixture'],p['source']['pitch_geometry'],cursor=100,official_match_unique_id=42)
    p['source']['events'][0]['stored_player_slot']=256
    with pytest.raises(ValueError,match='stored_player_slot'):
        attempts.project(p['source']['events'],p['actors'],p['fixture'],p['source']['pitch_geometry'],cursor=100,official_match_unique_id=42)
