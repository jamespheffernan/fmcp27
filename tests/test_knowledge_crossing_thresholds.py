"""Crossing11 math against full original dispatcher; no callee result stubs."""
import hashlib

import pytest

from fm_live_mcp import knowledge_crossing_thresholds as source
from fm_live_mcp import knowledge_passing_range as passing
from test_knowledge_passing_state import memory
from _knowledge_state_native import execute


@pytest.mark.parametrize('combined',[False,True])
@pytest.mark.parametrize('category',[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,127,128,255])
def test_full_original_crossing_dispatch_and_real_primary_getter(combined,category):
    m=memory(combined)
    for rva,value in source.TABLE_BRANCHES:
        raw=m.disk(rva,1);assert raw==bytes([value]);m.put(m.base+rva,raw)
    source.verify_native(m.read,m.base)
    m.put(m.primary+0x268,bytes([category]))
    expected=source.crossing_thresholds(category)
    for flag in(0,1):
        value,_,reads,writes,trace=execute(m,0x14e98e4,[11,flag,m.primary])
        assert value==expected[flag]
        assert 0xd5c4bc in trace
        assert all(0x200000000<=a<a+n<=0x200010000 for _,a,n in writes)
        assert not any(a<m.primary+0x18d and a+n>m.primary+0x148 for a,n in reads)


def test_crossing_category_three_cannot_reuse_passing_thresholds():
    assert source.crossing_thresholds(3)==(36,74)
    assert passing.passing_thresholds(3)==(11,49)


@pytest.mark.parametrize('value',[False,True,-1,256,11.0,None])
def test_category_requires_exact_unsigned_byte(value):
    with pytest.raises(ValueError):source.crossing_thresholds(value)


def test_changed_crossing_dispatch_table_refuses_source():
    m=memory()
    for rva,value in source.TABLE_BRANCHES:m.put(m.base+rva,bytes([value]))
    rva,_=source.TABLE_BRANCHES[1];m.put(m.base+rva,b'\0')
    with pytest.raises(ValueError,match='branch changed'):source.verify_native(m.read,m.base)
