"""Package attribute-byte firewall: forbidden intervals, cached reads, fences, poisoning."""
import struct
from types import SimpleNamespace

import pytest

from fm_live_mcp import knowledge_field_firewall as fw


class Physical:
    def __init__(self,data=None):
        self.data=data or {};self.calls=[]
    def __call__(self,address,size):
        self.calls.append((address,size))
        return bytes(self.data.get(address+i,0x41) for i in range(size))


def journal(physical=None,forbidden=((8192,8192+0x45),)):
    j=fw.Journal(physical or Physical())
    j.forbidden=fw.Intervals(forbidden)
    return j


def test_intervals_merge_and_detect_overlap_at_both_edges():
    i=fw.Intervals([(100*4096,100*4096+10),(100*4096+10,100*4096+20),(200*4096,200*4096+4)])
    assert i.ranges==((100*4096,100*4096+20),(200*4096,200*4096+4))
    assert i.intersects(100*4096-1,2) and i.intersects(100*4096+19,5) and not i.intersects(100*4096+20,5)
    assert not i.intersects(100*4096-4,4) and i.intersects(200*4096+3,1)
    for bad in [(1,5),(8192,8192),(8192,1<<64)]:
        with pytest.raises(ValueError):fw.Intervals([bad])


@pytest.mark.parametrize('address,size',[(8192,1),(8192+0x44,1),(8190,4),(8192+0x30,8)])
def test_forbidden_attribute_bytes_are_never_read_physically(address,size):
    physical=Physical();j=journal(physical)
    with pytest.raises(ValueError,match='forbidden'):j(address,size)
    assert physical.calls==[]


def test_read_just_outside_the_attribute_block_is_allowed():
    j=journal();assert j(8192-4,4)==b'AAAA' and j(8192+0x45,4)==b'AAAA'


def test_repeated_region_is_read_once_and_fences_read_every_distinct_region_twice():
    physical=Physical();j=journal(physical)
    for _ in range(1000):j(20000,8)
    j(30000,4)
    assert len(physical.calls)==2 and len(j.observed)==2
    j.verify(1);j.verify(2)
    assert len(physical.calls)==2+2*2 and j.phase_counts=={0:2,1:2,2:2}


def test_new_forbidden_geometry_cannot_cover_an_already_consumed_region():
    j=journal(forbidden=());j(20000,8)
    with pytest.raises(ValueError,match='consumed before forbidden geometry'):
        j.forbidden=fw.Intervals([(20004,20008)])
    j.forbidden=fw.Intervals([(30000,30008)])
    with pytest.raises(ValueError,match='forbidden'):j(30000,8)


def test_cached_hit_cannot_bypass_forbidden_geometry_after_rebinding():
    # Binding more geometry later re-checks every consumed region, so the fast
    # path for repeated regions can never serve a byte inside it.
    j=journal(forbidden=((9000,9008),));j(20000,8)
    j.forbidden=fw.Intervals([(9000,9008),(21000,21008)])
    assert j(20000,8)==b'A'*8
    with pytest.raises(ValueError):j(21000,8)


@pytest.mark.parametrize('address,size',[(0,1),(4095,1),(4096,0),(4096,-1),(4096,16385),(1<<64,1),('a',1),(4096.0,1)])
def test_geometry_is_rejected_before_any_physical_read(address,size):
    physical=Physical();j=journal(physical)
    with pytest.raises(ValueError):j(address,size)
    assert physical.calls==[]


def test_budgets_refuse_before_the_read(monkeypatch):
    monkeypatch.setattr(fw,'JOURNAL_REGIONS',2)
    physical=Physical();j=journal(physical);j(20000,1);j(20001,1)
    with pytest.raises(ValueError,match='Consumed source budget'):j(20002,1)
    assert len(physical.calls)==2
    monkeypatch.setattr(fw,'PHYSICAL_READS',2)
    with pytest.raises(ValueError,match='Physical audit budget'):j.verify(1)


def test_audit_stream_records_each_physical_read_with_header_and_bytes():
    from io import BytesIO
    audit=BytesIO();j=fw.Journal(Physical(),audit);j.forbidden=fw.Intervals(());j(20000,3);j(20000,3)
    header=fw.AUDIT_HEADER.size
    assert len(audit.getvalue())==header+3
    assert fw.AUDIT_HEADER.unpack(audit.getvalue()[:header])==(20000,3,0,1)


def test_attribute_intervals_cover_every_primary_in_all_three_vectors():
    base=1<<40;memory={}
    def put(address,data):
        for i,b in enumerate(data):memory[address+i]=b
    rows=[[0x10000,0x20000],[0x20008],[]]
    slab=0x30000
    for rva,vector_rows in zip(fw.PRIMARY_VECTOR_RVAS,rows):
        for index,primary in enumerate(vector_rows):put(slab+index*8,struct.pack('<Q',primary))
        end=slab+8*len(vector_rows)
        put(base+rva,struct.pack('<QQQ',slab,end,end) if vector_rows else struct.pack('<QQQ',0,0,0))
        slab+=0x100
    j=fw.Journal(lambda a,n:bytes(memory.get(a+i,0) for i in range(n)))
    players=SimpleNamespace(ATTRIBUTES={'a':0x10,'b':0x44})
    result=fw.attribute_intervals(j,base,players)
    assert result.ranges==((0x10000+0x148,0x10000+0x18d),(0x20000+0x148,0x20008+0x18d))
    for primary in (0x10000,0x20000,0x20008):
        assert result.intersects(primary+0x148,1) and result.intersects(primary+0x148+0x44,1)
    assert not result.intersects(0x10000+0x18d,1) and not result.intersects(0x10000+0x147,1)


def test_attribute_intervals_reject_malformed_vectors_and_primaries():
    base=1<<40
    def run(vector,rows=b''):
        memory={base+fw.PRIMARY_VECTOR_RVAS[0]:vector}
        j=fw.Journal(lambda a,n:(memory.get(a) or rows)[:n].ljust(n,b'\0'))
        return fw.attribute_intervals(j,base,SimpleNamespace(ATTRIBUTES={'a':0x44}))
    with pytest.raises(ValueError,match='vector geometry'):run(struct.pack('<QQQ',0x30001,0x30009,0x30009))
    with pytest.raises(ValueError,match='vector geometry'):run(struct.pack('<QQQ',0x30000,0x30010,0x30008))
    with pytest.raises(ValueError,match='primary pointer'):run(struct.pack('<QQQ',0x30000,0x30008,0x30008),struct.pack('<Q',0x10001))
