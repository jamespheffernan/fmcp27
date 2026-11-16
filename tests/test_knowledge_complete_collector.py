"""Offline collector controls; never constructs a real Bridge or opens game memory."""
from contextlib import contextmanager
import importlib.util
from io import BytesIO
from pathlib import Path
import random
import struct
import threading
from types import SimpleNamespace

import pytest

PATH=Path(__file__).resolve().parents[1]/'evidence/knowledge-complete-identity-20261109/collect150.py'
spec=importlib.util.spec_from_file_location('complete_collector',PATH)
c=importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


def records(audit):
    raw=audit.getvalue();offset=0;result=[]
    while offset<len(raw):
        a,n,phase,sequence=c.AUDIT_HEADER.unpack_from(raw,offset)
        offset+=c.AUDIT_HEADER.size
        payload=raw[offset:offset+n]
        assert len(payload)==n
        result.append((a,n,phase,sequence,payload));offset+=n
    return result


def test_intervals_match_simple_overlap_across_boundaries():
    ranges=[(4096,4100),(4100,4110),(4120,4130),(4200,4300)]
    indexed=c.Intervals(ranges)
    assert indexed.ranges==((4096,4110),(4120,4130),(4200,4300))
    rng=random.Random(741)
    queries=[(4110,10),(4110,11),(4109,1),(4300,1),(4095,1),(4095,2),(4111,100)]
    queries +=[(rng.randrange(4000,4400),rng.randrange(1,500))for _ in range(5000)]
    for a,n in queries:
        assert indexed.intersects(a,n)==any(a<end and a+n>start for start,end in ranges)


@pytest.mark.parametrize('interval',[(0,10),(4096,4096),(4096,1<<64),(True,9999),(9999,4096)])
def test_invalid_interval_rejected(interval):
    with pytest.raises(ValueError):c.Intervals([interval])


def test_repeated_reads_are_physical_and_both_fences_audited():
    calls=[];audit=BytesIO()
    j=c.Journal(lambda a,n:(calls.append((a,n))or b'X'*n),audit)
    assert j(4096,4)==b'XXXX';j(4096,4);j(5000,2)
    j.verify(1);j.verify(2)
    result=records(audit)
    assert len(calls)==len(result)==7
    assert [r[2]for r in result]==[0,0,0,1,1,2,2]
    assert [r[3]for r in result]==list(range(1,8))
    assert len(j.observed)==2 and j.unique_bytes==6
    assert j.record()['physical_phase_counts']=={0:3,1:2,2:2}


@pytest.mark.parametrize('address,size',[(0,1),(4096,0),(4096,16385),(1<<64,1),(4096,True),(True,4)])
def test_read_geometry_rejected_before_physical(address,size):
    calls=[];j=c.Journal(lambda a,n:calls.append((a,n)),BytesIO())
    with pytest.raises(ValueError):j(address,size)
    assert calls==[]


@pytest.mark.parametrize('budget,value', [('JOURNAL_BYTES',3),('JOURNAL_REGIONS',0),('PHYSICAL_BYTES',3),('PHYSICAL_READS',0)])
def test_budgets_fail_before_read(monkeypatch,budget,value):
    calls=[];j=c.Journal(lambda a,n:calls.append((a,n)),BytesIO())
    monkeypatch.setattr(c,budget,value)
    with pytest.raises(ValueError,match='budget'):j(4096,4)
    assert calls==[]


def test_existing_region_not_charged_twice_to_unique_budget(monkeypatch):
    calls=[];j=c.Journal(lambda a,n:(calls.append((a,n))or b'X'*n),BytesIO())
    monkeypatch.setattr(c,'JOURNAL_BYTES',4);monkeypatch.setattr(c,'JOURNAL_REGIONS',1)
    j(4096,4);j(4096,4)
    with pytest.raises(ValueError,match='budget'):j(5000,1)
    assert len(calls)==2


def test_failed_physical_attempt_retains_header_but_never_consumed_source():
    def fail(a,n):raise RuntimeError('offline physical failure')
    audit=BytesIO();j=c.Journal(fail,audit)
    with pytest.raises(RuntimeError,match='physical failure'):j(4096,4)
    assert c.AUDIT_HEADER.unpack(audit.getvalue())==(4096,4,0,1)
    assert j.observed=={}


def test_incomplete_read_retains_returned_bytes_but_never_consumed_source():
    audit=BytesIO();j=c.Journal(lambda a,n:b'X',audit)
    with pytest.raises(ValueError,match='Incomplete'):j(4096,4)
    assert audit.getvalue()[c.AUDIT_HEADER.size:]==b'X'
    assert j.observed=={}


@pytest.mark.parametrize('when',['repeat','fence1','fence2'])
def test_changed_consumed_bytes_reject_and_remain_in_physical_audit(when):
    values=[b'A']
    audit=BytesIO();j=c.Journal(lambda a,n:values[0]*n,audit)
    j(4096,2)
    if when=='fence2':j.verify(1)
    values[0]=b'B'
    with pytest.raises(ValueError,match='changed'):
        if when=='repeat':j(4096,2)
        else:j.verify(1 if when=='fence1'else 2)
    assert records(audit)[-1][-1]==b'BB'


def test_attribute_ranges_reject_all_overlapping_reads_before_physical():
    calls=[];j=c.Journal(lambda a,n:(calls.append((a,n))or b'X'*n),BytesIO())
    j.forbidden=c.Intervals([(5000,5100),(6000,6010)])
    for a,n in [(5000,1),(4999,2),(5099,1),(5100,901)]:
        with pytest.raises(ValueError,match='attribute'):j(a,n)
    assert calls==[]
    j(4999,1);j(5100,1)
    assert len(calls)==2


def test_primary_vectors_bind_attributes_without_reading_values():
    base=0x10000000;primary=0x40000000;memory={}
    for ordinal,rva in enumerate((0x56d2e18,0x56d2e30,0x56d2e48)):
        vector=0x30000000+ordinal*0x1000
        memory[base+rva]=struct.pack('<QQQ',vector,vector+24,vector+24)
        memory[vector]=struct.pack('<QQQ',primary,0,primary)
    j=c.Journal(lambda a,n:memory[a],BytesIO())
    j.forbidden=c.attribute_intervals(j,base,SimpleNamespace(ATTRIBUTES={'passing':0x16}))
    assert j.forbidden.ranges==((primary+0x148,primary+0x15f),)
    assert len(j.observed)==6
    with pytest.raises(ValueError,match='attribute'):j(primary+0x15e,1)


def test_retained_only_identity_guard_retroactively_rejects_payload():
    j=c.Journal(lambda a,n:b'X'*n,BytesIO())
    j(0x40000000+0x15e,1)
    with pytest.raises(ValueError,match='attribute'):
        c.bind_result_intervals(j,{'subjects':[{'primary':0x40000000}]},SimpleNamespace(ATTRIBUTES={'passing':0x16}))


def test_capture_failure_detaches_literal_receipt(monkeypatch,tmp_path):
    class FakeBridge:
        last=None
        def __init__(self,helper=None):self.lock=threading.RLock();FakeBridge.last=self
        def attach(self):return {'session_id':'offline'}
        def _current(self,sid):raise ValueError('offline final callback control')
        def detach(self):self.detached=True;return {'detached':True}
    @contextmanager
    def stream(*args):yield
    monkeypatch.setattr(c,'runtime',lambda:(SimpleNamespace(Bridge=FakeBridge,ReadStream=None),None,None,None,None,SimpleNamespace(collection_stream=stream,ReadStream=None),{},{}))
    monkeypatch.setattr(c,'sha',lambda p:c.PLUGIN_SHA256)
    cleanup={}
    with pytest.raises(ValueError,match='offline final callback'):
        c.capture(tmp_path/'offline-audit.bin',cleanup=cleanup)
    assert cleanup=={'detach':{'detached':True}}
    assert FakeBridge.last.detached


def test_detach_failure_recorded_and_success_impossible():
    cleanup={}
    def fail():raise RuntimeError('offline cleanup failure')
    with pytest.raises(RuntimeError,match='cleanup failure'):
        c.detached_capture(SimpleNamespace(detach=fail),lambda:None,cleanup)
    assert cleanup['detach_error']=={'type':'RuntimeError','error':'offline cleanup failure'}


def test_identity_result_cannot_promote_field_or_population_claim():
    result=dict(scope='private_complete_native_club_kind1_identity_source_before_final_filters',complete_native_identity_source=True,
        complete_search_population=False,field_visibility_evaluated=False,manager_knowledge_verified=False,
        subjects=[dict(primary=4096,person=5000,native_identity={},record_kind='player',native_origin='base')])
    c.accept_result(result)
    for key in ('complete_search_population','field_visibility_evaluated','manager_knowledge_verified'):
        with pytest.raises(ValueError):c.accept_result(result|{key:True})
    with pytest.raises(ValueError):c.accept_result(result|{'subjects':[result['subjects'][0]|{'passing':20}]})


def transport_fixture(monkeypatch,*,requests=90000,byte_limit=60*1024*1024):
    monkeypatch.setattr(c,'STREAM_REQUESTS',requests)
    monkeypatch.setattr(c,'STREAM_BYTES',byte_limit)
    bridge=SimpleNamespace(process=SimpleNamespace(pid=42,started='offline-start'),session='offline',helper=Path('/offline/helper'),transport_segments=[])
    class Native:
        opened=[]
        def __init__(self,helper,pid):
            assert helper==bridge.helper and pid==42
            self.count=self.bytes=0;self.closed=False;Native.opened.append(self)
        def read(self,a,n):
            assert not self.closed
            self.count+=1;self.bytes+=n
            assert self.count<=100000 and self.bytes<=64*1024*1024
            return b'X'*n
        def close(self):self.closed=True
    return bridge,Native,c.SegmentedStream(bridge,Native,bridge.helper,42)


def test_segmented_transport_66065_slots_times_four_reads_stays_below_native_limits(monkeypatch):
    bridge,native,stream=transport_fixture(monkeypatch)
    for _ in range(66065*4):assert stream.read(4096,1)==b'X'
    stream.close()
    assert len(native.opened)==3
    assert [p.count for p in native.opened]==[90000,90000,84260]
    assert all(p.closed for p in native.opened)
    assert all(row['closed']for row in bridge.transport_segments)
    assert all(len(row['requests_and_raw_sha256'])==64 for row in bridge.transport_segments)
    assert all(row['process_started']=='offline-start'for row in bridge.transport_segments)


def test_segmented_transport_rotates_before_byte_budget(monkeypatch):
    bridge,native,stream=transport_fixture(monkeypatch,byte_limit=8)
    stream.read(4096,4);stream.read(5000,4);stream.read(6000,1)
    stream.close()
    assert [r.bytes for r in native.opened]==[8,1]
    assert all(r.closed for r in native.opened)


@pytest.mark.parametrize('field',['process','session','helper'])
def test_segmented_transport_rejects_binding_changes_before_rotation(monkeypatch,field):
    bridge,native,stream=transport_fixture(monkeypatch,requests=1)
    stream.read(4096,4)
    setattr(bridge,field,{'process':SimpleNamespace(pid=43),'session':'changed','helper':Path('/changed')}[field])
    with pytest.raises(ValueError,match='binding changed'):stream.read(5000,4)
    stream.close()
    assert len(native.opened)==1 and native.opened[0].closed


def test_segmented_close_prevents_new_port(monkeypatch):
    bridge,native,stream=transport_fixture(monkeypatch)
    stream.close()
    with pytest.raises(ValueError,match='closed'):stream.read(4096,1)
    assert native.opened==[]


def test_mutation_between_segments_rejects_whole_journal_on_fresh_fence(monkeypatch):
    bridge,native,stream=transport_fixture(monkeypatch,requests=1)
    memory={4096:b'A',5000:b'B'}
    original=native.read
    def read(self,a,n):
        original(self,a,n)
        return memory[a]
    monkeypatch.setattr(native,'read',read)
    audit=BytesIO();journal=c.Journal(stream.read,audit)
    try:
        journal(4096,1);journal(5000,1)
        assert len(native.opened)==2
        memory[4096]=b'Z'
        with pytest.raises(ValueError,match='final physical fence'):journal.verify(1)
        assert records(audit)[-1][-1]==b'Z'
    finally:stream.close()
    assert len(native.opened)==3 and all(row.closed for row in native.opened)
    assert all(row['closed'] for row in bridge.transport_segments)


def test_wrong_initial_pid_rejects_before_opening_native_port(monkeypatch):
    bridge,native,_=transport_fixture(monkeypatch)
    stream=c.SegmentedStream(bridge,native,bridge.helper,43)
    with pytest.raises(ValueError,match='binding changed'):stream.read(4096,1)
    stream.close()
    assert native.opened==[]
