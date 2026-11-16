"""Complete private identity join; partial source never becomes complete."""
from _knowledge_stream_fixture import native_stream_transport
import struct

import pytest

from fm_live_mcp import knowledge_search_identity_source as source
from fm_live_mcp import knowledge_search_population_source as population
from fm_live_mcp import knowledge_search_retained_union as retained
from test_knowledge_search_base_admission import memory_fixture,population_fixture
from test_knowledge_club_admission_source import foreign
from test_knowledge_context_score_source import SyntheticBridge


def fixture(show_all):
    m=memory_fixture()
    foreign(m)
    coach=population_fixture(m)
    m.put(m.listing+0x101,bytes([show_all]))
    for rva,raw in retained.NATIVE_SPANS:
        m.put(m.base+rva,raw)
    listing=m.allocate(0x110)
    m.put(listing+0x4c,b'\3')
    m.q(listing+0xd0,m.human)
    entry=m.allocate(0x38)
    m.q(entry,m.person)
    m.vec(listing+0x80,[entry,entry])
    m.vec(m.human+0x248,[m.listing,listing])
    for name in population.BASE_VECTORS:
        m.vec(m.base+population.BASE_VECTORS[name],[m.primary,0,m.primary])
    return m,coach


@pytest.mark.parametrize('show_all',[False,True])
@pytest.mark.parametrize('page_size',[1,2,2048])
def test_complete_join_preserves_base_duplicates_and_retained_dedup(show_all,page_size):
    m,coach=fixture(show_all)
    result=source.observe_complete(m.read,m.base,coach,check_current=lambda:('fixture',),page_size=page_size)
    assert result['complete_native_identity_source'] is True
    assert result['base_source_slots']==3 and result['retained_source_slots']==2
    assert [r['native_origin'] for r in result['subjects']]==(['base','base'] if show_all else ['retained'])
    assert not result['complete_search_population'] and not result['field_visibility_evaluated']
    assert not result['manager_knowledge_verified']


def test_bridge_owned_complete_join_rechecks_source_after_last_callback():
    first,_=fixture(False)
    baseline=SyntheticBridge(first)
    assert source.collect(baseline,'synthetic',coach_name='Private Coach',page_size=1)['complete_native_identity_source']
    m,_=fixture(False)
    bridge=SyntheticBridge(m)
    def change(count):
        if count==baseline.lifetimes:
            m.identity(m.person,m.person_ref[0],m.person_ref[1]+1,m.person_ref[2])
    bridge.on_current=change
    with pytest.raises(ValueError,match='changed'):
        source.collect(bridge,'synthetic',coach_name='Private Coach',page_size=1)
    assert bridge._reader is None


def test_incomplete_or_unknown_native_actor_refuses_whole_join():
    m,coach=fixture(False)
    m.q(m.primary,0)
    with pytest.raises(ValueError):
        source.observe_complete(m.read,m.base,coach,check_current=lambda:('fixture',),page_size=1)
