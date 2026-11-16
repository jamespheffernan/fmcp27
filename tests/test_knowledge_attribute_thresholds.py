"""All47 fields/seven category tables against the complete original dispatcher."""
import pytest

from fm_live_mcp import knowledge_attribute_thresholds as source
from fm_live_mcp import knowledge_crossing_thresholds as crossing
from fm_live_mcp import knowledge_passing_range as passing
from test_knowledge_passing_state import memory
from _knowledge_state_native import execute


@pytest.fixture(scope='module')
def memories():
    result={}
    for combined in(False,True):
        m=memory(combined)
        m.put(m.base+0x5399406,m.disk(0x5399406,343))
        source.verify_native(m.read,m.base)
        result[combined]=m
    return result


@pytest.mark.parametrize('combined',[False,True])
@pytest.mark.parametrize('field',range(47))
@pytest.mark.parametrize('category',[0,3,2,5,6,10,12])
def test_all_field_pairs_match_full_original_dispatcher_and_primary_getter(memories,combined,field,category):
    m=memories[combined];m.put(m.primary+0x268,bytes([category]))
    expected=source.thresholds(field,category)
    for flag in(0,1):
        value,_,reads,writes,trace=execute(m,0x14e98e4,[field,flag,m.primary])
        assert value==expected[flag]
        assert 0xd5c4bc in trace
        assert all(0x200000000<=a<a+n<=0x200010000 for _,a,n in writes)
        assert not any(a<m.primary+0x18d and a+n>m.primary+0x148 for a,n in reads)


def test_existing_passing_and_crossing_components_match_every_raw_category():
    for category in range(256):
        assert source.thresholds(18,category)==passing.passing_thresholds(category)
        assert source.thresholds(11,category)==crossing.crossing_thresholds(category)


@pytest.mark.parametrize('field,category',[(False,0),(47,0),(-1,0),(11,True),(11,-1),(11,256)])
def test_field_and_category_require_exact_bounded_native_integers(field,category):
    with pytest.raises(ValueError):source.thresholds(field,category)
