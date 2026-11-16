"""Complete original warm entry constructor and spare-capacity appender.

No native allocator, live game or lower-result stub is used. Capacity growth
and cold allocator paths are not claimed by these owned-memory executions.
"""
from _knowledge_stream_fixture import native_stream_transport
import struct

import pytest

from fm_live_mcp import knowledge_search_base_admission as source
from test_knowledge_search_base_admission import memory_fixture
from _knowledge_state_native import execute


@pytest.mark.parametrize('stored_count',[0,1,2,3])
def test_original_appender_preserves_entry_pointer_and_order_without_reading_person(stored_count):
    m=memory_fixture()
    listing=m.allocate(0x120)
    begin=listing+0xe0
    previous=[m.allocate(0x38) for _ in range(stored_count)]
    for index,entry in enumerate(previous):
        m.q(begin+index*8,entry)
    m.put(listing+0x80,struct.pack('<QQQ',begin,begin+stored_count*8,begin+4*8))
    entry=m.allocate(0x38)
    m.q(entry,m.person)
    _,output,reads,writes,trace=execute(m,0x14d8bfc,[listing,entry],
        score_pointer=listing+0x80,output_width=0x80,extra=source.NATIVE_GUARDS)
    assert int.from_bytes(output[8:16],'little')==begin+(stored_count+1)*8
    pointers=struct.unpack_from('<'+'Q'*(stored_count+1),output,0x60)
    assert pointers==tuple(previous+[entry])
    assert not any(at<entry+0x38 and at+size>entry for at,size in reads)
    assert all(0x200000000<=at<at+size<=0x200010000 or
        (at,size) in ((listing+0x88,8),(begin+stored_count*8,8)) for _,at,size in writes)
    assert 0x14d8bfc in trace and 0x14e1ea4 not in trace


@pytest.mark.parametrize('packed_date',[(2030<<16)|317,(1900<<16)|1])
def test_original_warm_entry_constructor_has_no_person_selection(packed_date):
    m=memory_fixture()
    allocator=m.allocate(8)
    m.q(m.base+0x56a4a90,allocator)
    m.put(m.base+0x56b1db8,struct.pack('<I',packed_date))
    entry=m.allocate(0x38)
    m.q(entry,m.person)
    value,output,reads,writes,trace=execute(m,0x163429c,[entry],
        score_pointer=entry,output_width=0x38,extra=source.NATIVE_GUARDS)
    assert value==entry and output[:0x20]==bytes(0x20)
    assert output[0x20:0x28]==struct.pack('<II',packed_date,0x076c0001)
    assert output[0x28:0x30]==struct.pack('<Q',0xffffffff00000000)
    assert output[0x30]==0
    assert not any(at<m.person+0x20 and at+size>m.person for at,size in reads)
    assert all(0x200000000<=at<at+size<=0x200010000 or entry<=at<at+size<=entry+0x38 for _,at,size in writes)
    assert 0x163429c in trace
