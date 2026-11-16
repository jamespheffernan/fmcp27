"""Actual Bridge scope/ReadSets with synthetic physical transport and process IO."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path
import struct
import types

import pytest

from fm_live_mcp import bridge as bridge_module, live_individual_training as query, world
from fm_live_mcp.bridge import Bridge, BridgeError
from fm_live_mcp.reader import ReaderError
from test_live_individual_training import (
    live_focus, focus_memory, prepared_tactics_memory, bridge, memory, database_memory,
    member_memory, team_memory, world_memory, native_image)
from test_default_training_intensity import default_memory, training_source_memory


@pytest.fixture(scope='module')
def baseline():
    path = Path(__file__).parent/'fixtures/live_individual_training155.py.txt'
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '7d40c197e107a217d75f23297165747241e67c91e08206e48070f521d742359e'
    module = types.ModuleType('fm_live_mcp._training155_baseline')
    module.__package__ = 'fm_live_mcp'
    exec(compile(raw,str(path),'exec'),module.__dict__)
    return module


@pytest.fixture
def real_training(live_focus,monkeypatch):
    m,b = live_focus,live_focus['bridge']
    events,streams,hooks = [],[],{}
    control = dict(error=None,error_at=None,close_error=None,calls=0)
    class Stream:
        def __init__(self,helper,pid):
            self.pid,self.closed = pid,False
            streams.append(self)
            events.append(('open',pid))
        def read(self,at,n):
            assert not self.closed
            events.append(('read',at,n))
            if control['error'] is not None and (control['error_at'] is None or control['error_at']==at):
                error = control['error']
                if isinstance(error,ReaderError):self.close()
                raise error
            if at < 0x118D and at+n > 0x1148:
                pytest.fail('Lifecycle test read unrelated player attributes')
            return m['read'](at,n)
        def close(self):
            self.closed = True
            events.append(('close',self.pid))
            if control['close_error'] is not None:
                raise control['close_error']
    monkeypatch.setattr(bridge_module,'ReadStream',Stream)
    monkeypatch.setattr(b,'_read_scope',Bridge._read_scope.__get__(b,Bridge))
    monkeypatch.setattr(b,'_read_memory',Bridge._read_memory.__get__(b,Bridge))
    current = b._current
    def checked(session):
        result = current(session)
        control['calls'] += 1
        number = control['calls']
        events.append(('callback',number))
        if number in hooks:
            replacement = hooks[number](m)
            if replacement is not None:result = replacement
        return result
    monkeypatch.setattr(b,'_current',checked)
    public = b._public_save
    def public_save(save):
        events.append(('public_save',))
        return public(save)
    monkeypatch.setattr(b,'_public_save',public_save)
    verify = world.ReadSet.verify
    def checked_verify(read):
        events.append(('verify',id(read)))
        return verify(read)
    monkeypatch.setattr(world.ReadSet,'verify',checked_verify)
    def invoke(module=query,**kwargs):
        return module.get_player_individual_training(b,b.session,['p1'],**kwargs)
    m.update(lifecycle_events=events,lifecycle_streams=streams,lifecycle_hooks=hooks,
             lifecycle_control=control,lifecycle_invoke=invoke)
    return m


def assert_closed(m):
    assert m['bridge']._reader is None
    assert m['lifecycle_streams'] and all(reader.closed for reader in m['lifecycle_streams'])
    assert m['lifecycle_events'][-1][0] == 'close'


def mutate(m,fault):
    b = m['bridge']
    if fault == 'focus':m['put'](m['focus_child']+6,b'\x19')
    elif fault == 'intensity':m['put'](0x11EB,b'\x02')
    elif fault == 'date':m['put'](m['base']+world.CURRENT_DATE,struct.pack('<I',(2030<<16)|263))
    elif fault == 'roster':m['vec'](m['team']+0x38,[])
    elif fault == 'root_reference':b.player_refs.pop('p1')
    elif fault == 'reference_identity':b.player_refs['p1']['identity'] = (77,'Other','','2000-02-29',77)
    elif fault == 'session':b.session = 'expired'
    elif fault == 'process_cache':b.process = replace(b.process,pid=b.process.pid+1)
    elif fault == 'plugin':b.plugin_identity = ('other',0)
    elif fault == 'world_cache':b.world_identity = ('other',0)
    elif fault == 'returned_pid':return replace(b.process,pid=b.process.pid+1)
    else:raise AssertionError(fault)


def test_clean_actual_scope_has_no_callback_or_public_save_after_final_byte_fences(real_training):
    m = real_training
    result = m['lifecycle_invoke']()
    assert result['players'][0]['additional_focus']['raw_code'] == 24
    assert 'default_intensity_resolution' not in result['players'][0]
    assert result['atomic'] is result['saved_file_fallback'] is False
    events = m['lifecycle_events']
    assert [event[1] for event in events if event[0]=='callback'] == [1,2,3,4,5]
    final = events.index(('callback',5))
    assert all(event[0] in ('verify','read','close') for event in events[final+1:])
    assert len([event for event in events[final+1:] if event[0]=='verify']) == 2
    assert events.index(('public_save',)) < events.index(('callback',3))
    assert_closed(m)


@pytest.mark.parametrize('callback',[3,4,5])
@pytest.mark.parametrize('fault',['focus','intensity','date','roster','root_reference',
    'reference_identity','session','process_cache','plugin','world_cache'])
def test_every_late_source_or_cache_change_rejects_before_publication(real_training,callback,fault):
    m = real_training
    m['lifecycle_hooks'][callback] = lambda memory:mutate(memory,fault)
    with pytest.raises(BridgeError,match='no partial result'):m['lifecycle_invoke']()
    assert_closed(m)


@pytest.mark.parametrize('callback',[4,5])
def test_returned_PID_mismatch_in_seal_rejects_and_closes(real_training,callback):
    m = real_training
    m['lifecycle_hooks'][callback] = lambda memory:mutate(memory,'returned_pid')
    with pytest.raises(BridgeError,match='lifetime changed'):m['lifecycle_invoke']()
    assert_closed(m)


@pytest.mark.parametrize('version',['baseline','candidate'])
@pytest.mark.parametrize('fault',['focus','root_reference'])
def test_identical_hidden_callback_mutants_are_old_red_and_new_green(real_training,baseline,version,fault):
    m = real_training
    m['lifecycle_hooks'][5] = lambda memory:mutate(memory,fault)
    if version == 'candidate':
        with pytest.raises(BridgeError,match='no partial result'):m['lifecycle_invoke']()
    else:
        result = m['lifecycle_invoke'](baseline)
        assert result['players'][0]['additional_focus']['raw_code'] == 24
        if fault == 'focus':
            assert m['read'](m['focus_child']+6,1) == b'\x19'
        else:
            assert 'p1' not in m['bridge'].player_refs
    assert_closed(m)


def test_original_last_in_body_focus_control_still_rejects(real_training,baseline):
    m = real_training
    m['lifecycle_hooks'][4] = lambda memory:mutate(memory,'focus')
    with pytest.raises(BridgeError,match='changed during read'):m['lifecycle_invoke'](baseline)
    assert_closed(m)


@pytest.mark.parametrize('version',['baseline','candidate'])
def test_clean_output_schema_values_and_default_match_installed155(real_training,baseline,version):
    result = real_training['lifecycle_invoke'](baseline if version=='baseline' else query)
    assert set(result) == {'session_id','observed_at','save','coach','club','team','players','count',
                          'source','field_sources','scope','atomic','saved_file_fallback'}
    assert result['source'] == 'stored_player_individual_training_additional_focus'
    assert result['players'][0]['additional_focus']['english_definition_name'] == 'Crossing'
    assert result['players'][0]['club_training_intensity']['state'] == 'stored_named_intensity'
    assert 'default_intensity_resolution' not in result['players'][0]
    assert_closed(real_training)


@pytest.mark.parametrize('include_default_resolution',[False,True])
def test_complete_clean_payload_matches_installed155_except_observation_time(default_memory,real_training,baseline,include_default_resolution):
    m = real_training
    assert m is default_memory
    expected = m['lifecycle_invoke'](baseline,include_default_resolution=include_default_resolution)
    m['lifecycle_control']['calls'] = 0
    actual = m['lifecycle_invoke'](include_default_resolution=include_default_resolution)
    assert expected.pop('observed_at') and actual.pop('observed_at')
    assert actual == expected
    assert_closed(m)


@pytest.mark.parametrize('fault',['source_error','eof','timeout','cancel'])
def test_failed_or_cancelled_source_never_returns_a_partial_result_or_retains_reader(real_training,fault):
    m = real_training
    errors = dict(source_error=ValueError('Incomplete synthetic source'),
        eof=ReaderError('Native read stream closed before its response.'),
        timeout=ReaderError('Native read timed out; no result accepted.'),cancel=asyncio.CancelledError())
    m['lifecycle_control'].update(error=errors[fault],error_at=m['focus_child'])
    if fault == 'cancel':
        with pytest.raises(asyncio.CancelledError):m['lifecycle_invoke']()
    else:
        with pytest.raises(BridgeError,match='no partial result'):m['lifecycle_invoke']()
    assert_closed(m)


def test_cancelled_final_callback_closes_without_consumed_reader_retention(real_training):
    m = real_training
    def cancel(memory):raise asyncio.CancelledError()
    m['lifecycle_hooks'][5] = cancel
    with pytest.raises(asyncio.CancelledError):m['lifecycle_invoke']()
    assert_closed(m)


def test_teardown_error_prevents_publication_and_clears_the_bridge_reader(real_training):
    m = real_training
    m['lifecycle_control']['close_error'] = OSError('Synthetic teardown failure')
    with pytest.raises(OSError,match='teardown failure'):m['lifecycle_invoke']()
    assert_closed(m)


def test_public_save_callback_mutation_occurs_before_final_fences(real_training,monkeypatch):
    m,b = real_training,real_training['bridge']
    original = b._public_save
    def changed(save):
        result = original(save)
        mutate(m,'focus')
        return result
    monkeypatch.setattr(b,'_public_save',changed)
    with pytest.raises(BridgeError,match='changed during read'):m['lifecycle_invoke']()
    assert_closed(m)


def test_default_resolution_stays_separate_and_late_policy_byte_drift_rejects(default_memory,real_training):
    m = real_training
    assert m is default_memory
    result = m['lifecycle_invoke'](include_default_resolution=True)
    assert result['players'][0]['default_intensity_resolution']['native_code'] == 1
    assert result['players'][0]['club_training_intensity']['applied_intensity'] is None
    m['lifecycle_control']['calls'] = 0
    m['lifecycle_hooks'][5] = lambda memory:memory['put'](memory['training_team_node']+0x8A,b'\x02')
    with pytest.raises(BridgeError,match='changed during read'):
        m['lifecycle_invoke'](include_default_resolution=True)
    assert_closed(m)
