"""Causal generation-drift rejection around lazy task ports; no game reads."""
import ctypes
from io import BytesIO
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from fm_live_mcp import knowledge_field_firewall as c
from fm_live_mcp import knowledge_generation_transport as g



def identity(generation=1,version=1):
    return dict(pid=42,process_unique_id=generation,idversion_bits=version,executable_uuid_hex='11'*16,
        kernel_token_rawhex=('11'*16)+generation.to_bytes(8,'little').hex()+'00'*32)


class Environment:
    def __init__(self,*,replace_on_open=0,close_error=False):
        self.current=identity();self.ports=[];self.replace_on_open=replace_on_open;self.close_error=close_error
        self.bridge=SimpleNamespace(process=SimpleNamespace(pid=42,started='same-second'),session='same-session',helper=Path('/same/helper'),transport_segments=[])
    def kernel(self,pid):
        assert pid==42
        if self.close_error:raise OSError('metadata denied')
        return self.current.copy()
    def native(self,helper,pid):
        env=self
        class Port:
            closed=False
            def __init__(self):env.ports.append(self);self.ordinal=len(env.ports)
            def read(self,a,n):
                if self.ordinal==env.replace_on_open:env.current=identity(2)
                return b'X'*n
            def close(self):self.closed=True
        return Port()
    def stream(self,new=True):
        kind=g.bound_stream_type(c.SegmentedStream,self.kernel,identity())if new else c.SegmentedStream
        return kind(self.bridge,self.native,self.bridge.helper,42)


def run_rotation(new):
    env=Environment(replace_on_open=2);stream=env.stream(new)
    journal=c.Journal(stream.read,BytesIO())
    try:
        for index in range(90001):journal(4096+index,1)
        return env,journal
    finally:stream.close()


def test_old_stream_accepts_same_pid_replacement_and_identical_bytes():
    env,journal=run_rotation(False)
    assert env.current['process_unique_id']==2
    assert journal.phase_counts=={0:90001,1:0,2:0}
    assert all(row['process_started']=='same-second'for row in env.bridge.transport_segments)
    assert len(env.ports)==2 and all(port.closed for port in env.ports)


def test_new_stream_rejects_same_pid_replacement_after_lazy_port_open():
    env=Environment(replace_on_open=2);stream=env.stream()
    journal=c.Journal(stream.read,BytesIO())
    try:
        with pytest.raises(ValueError,match='incarnation changed'):
            for index in range(90001):journal(4096+index,1)
    finally:
        with pytest.raises(ValueError,match='incarnation changed'):stream.close()
    assert len(env.ports)==2 and all(port.closed for port in env.ports)
    assert all(row['closed']for row in env.bridge.transport_segments)
    assert 'after_first_physical_read'in env.bridge.transport_segments[-1]['kernel_generation_errors']


def test_generation_changed_before_first_open_rejects_without_task_read():
    env=Environment();stream=env.stream();env.current=identity(2)
    try:
        with pytest.raises(ValueError,match='incarnation changed'):stream.read(4096,1)
    finally:
        with pytest.raises(ValueError,match='incarnation changed'):stream.close()
    assert all(port.closed for port in env.ports)
    assert env.bridge.transport_segments[-1]['kernel_generation_errors']['before_lazy_port_open']


def test_generation_changed_after_last_read_rejects_but_closes_port():
    env=Environment();stream=env.stream();stream.read(4096,1);env.current=identity(2)
    with pytest.raises(ValueError,match='incarnation changed'):stream.close()
    assert env.ports[0].closed and env.bridge.transport_segments[0]['closed']


def test_kernel_metadata_failure_at_close_still_closes_port():
    env=Environment();stream=env.stream();stream.read(4096,1);env.close_error=True
    with pytest.raises(OSError,match='denied'):stream.close()
    assert env.ports[0].closed and env.bridge.transport_segments[0]['closed']


def test_first_read_metadata_failure_rejects_and_still_closes_port():
    env=Environment();stream=env.stream();env.close_error=True
    with pytest.raises(OSError,match='denied'):stream.read(4096,1)
    with pytest.raises(OSError,match='denied'):stream.close()
    assert all(p.closed for p in env.ports)
    assert env.bridge.transport_segments[0]['closed']


def test_replacement_before_later_port_open_rejects_old_port_close(monkeypatch):
    monkeypatch.setattr(c,'STREAM_REQUESTS',1)
    env=Environment();stream=env.stream();stream.read(4096,1);env.current=identity(2)
    with pytest.raises(ValueError,match='incarnation changed'):stream.read(4096,1)
    stream.close()
    assert len(env.ports)==1 and env.ports[0].closed


def test_native_read_failure_with_stable_generation_closes_and_refuses():
    env=Environment();original=env.native
    def factory(helper,pid):
        port=original(helper,pid)
        def fail(a,n):raise OSError('native read refused')
        port.read=fail
        return port
    env.native=factory;stream=env.stream()
    with pytest.raises(OSError,match='native read refused'):stream.read(4096,1)
    stream.close()
    assert env.ports[0].closed


def test_exec_idversion_changes_reject_even_same_uniqueid_and_uuid():
    env=Environment();stream=env.stream();stream.read(4096,1);env.current=identity(1,2)
    with pytest.raises(ValueError,match='incarnation changed'):stream.close()
    assert env.ports[0].closed


def test_unchanged_generation_receipts_cover_open_and_close(monkeypatch):
    monkeypatch.setattr(c,'STREAM_REQUESTS',2)
    env=Environment();stream=env.stream()
    for _ in range(5):stream.read(4096,1)
    stream.close()
    assert [r['requests']for r in env.bridge.transport_segments]==[2,2,1]
    for row in env.bridge.transport_segments:
        assert row['closed']
        assert set(row['kernel_generation_checks'])=={'before_lazy_port_open','after_first_physical_read','before_port_close'}
        assert row['kernel_generation_baseline']==identity()


@pytest.mark.parametrize('returned',[-1,0,55,57,4096])
def test_kernel_metadata_short_oversize_or_failure_rejected(returned):
    class PidInfo:
        def __call__(self,*args):return returned
    api=g.KernelIdentity(SimpleNamespace(proc_pidinfo=PidInfo()))
    with pytest.raises(OSError,match='length differs'):api(42)


def test_signed_idversion_preserves_all_bits():
    class PidInfo:
        def __call__(self,pid,flavor,arg,buffer,size):
            assert (pid,flavor,arg,size)==(42,17,0,56)
            info=ctypes.cast(buffer,ctypes.POINTER(g.ProcUniqueIdentifier)).contents
            info.uniqueid=123;info.idversion=-1
            return size
    result=g.KernelIdentity(SimpleNamespace(proc_pidinfo=PidInfo()))(42)
    assert result['idversion_bits']==0xffffffff
    assert len(result['kernel_token_rawhex'])==112


def test_real_kernel_abi_on_own_process_only():
    api=g.KernelIdentity();before=api(os.getpid());after=api(os.getpid())
    assert g.token(before)==g.token(after)
    assert before['returned_bytes']==56 and before['process_unique_id']>0
