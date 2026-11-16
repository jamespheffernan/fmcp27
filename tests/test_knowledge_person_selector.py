"""Original predicate and typed selector prefix checks in owned memory."""
from _knowledge_stream_fixture import native_stream_transport
import hashlib
import struct
import pytest
from fm_live_mcp import knowledge_person_selector as selector
from test_knowledge_team_handle import lookup_memory
from test_knowledge_context_score_source import SyntheticBridge
from _knowledge_state_native import execute


def memory():
    m=lookup_memory()
    for rva,n,digest in selector.NATIVE_GUARDS:
        raw=m.disk(rva,n);assert hashlib.sha256(raw).hexdigest()==digest;m.put(m.base+rva,raw)
    m.q(m.base+0x559cf48+0x150,m.base+0xe2767c);m.q(m.base+0x559cf48+0x158,m.base+0xe27754)
    m.q(m.base+0x54b05b0,0)
    m.payload=m.allocate(0x520);m.q(m.competition+0xb0,m.payload);m.put(m.base+0x56d3518,struct.pack('<I',1))
    return m


def source(m):
    return selector.SelectorSource(SyntheticBridge(m),'synthetic',m.person,m.person_ref,'Private Coach',18)


@pytest.mark.parametrize('case,expected',[('no_payload',True),('no_definition',True),('empty_teams',True),
 ('mode_equal',False),('flag6',True),('state3',True),('flag17',True),('pointer510',True),
 ('inner3',True),('inner_minus3',True),('inner0',False),('no_inner_minus3',True),('default',False)])
def test_club150_matches_original_predicate_with_all_native_inputs(case,expected):
    m=memory()
    if case=='no_payload':m.q(m.competition+0xb0,0)
    elif case=='no_definition':m.q(m.team+0x50,0)
    elif case=='empty_teams':m.vec(m.other+0x18,[])
    elif case=='mode_equal':m.put(m.base+0x56d3518,struct.pack('<I',0xffffffff))
    elif case=='flag6':m.put(m.payload+0x4c,struct.pack('<I',64))
    elif case=='state3':m.put(m.payload+0x4c0,b'\3')
    elif case=='flag17':m.put(m.payload+0x4c,struct.pack('<I',1<<17))
    elif case=='pointer510':m.q(m.payload+0x510,m.allocate(8))
    elif case.startswith('inner'):
        nested=m.allocate(0x240);m.q(m.payload+0x388,nested)
        m.put(nested+0x23c,b'\3'if case=='inner3'else b'\0')
        if case=='inner_minus3':m.put(m.payload+0x3b6,struct.pack('<h',-3))
    elif case=='no_inner_minus3':m.put(m.payload+0x3b6,struct.pack('<h',-3))
    m.reads.clear();s=source(m);club=s.entity(m.other if case=='empty_teams'else m.club,'club')
    assert s.club150(club)is expected;s.verify();consumed={p for at,n in m.reads for p in range(at,at+n)}
    actual,_,reads,_,_=execute(m,0xe2767c,[club.address],extra=selector.NATIVE_GUARDS)
    assert bool(actual)==expected and actual in(0,1)
    assert all(p in consumed for at,n in reads for p in range(at,at+n))


def test_nested_state1_remains_unavailable_without_native_helper_result():
    m=memory();nested=m.allocate(0x240);m.q(m.payload+0x388,nested);m.put(nested+0x23c,b'\1');s=source(m)
    with pytest.raises(selector.core.SourceUnavailable,match='3ab45dc'):s.club150(s.owner_club)


def test_direct_selector_prefix_distinguishes_158_and_retained_cold_edges():
    m=memory();s=source(m)
    with pytest.raises(selector.core.SourceUnavailable,match='Missing selector stack guard source'):s.select_person6f(s.owner_club)
    m=memory();m.q(m.competition+0xb0,0);s=source(m)
    with pytest.raises(selector.core.SourceUnavailable,match='CLUB158'):s.select_person6f(s.owner_club)


@pytest.mark.parametrize('fault',['owner_primary_displacement','owner_1b0','club150','predicate_guard'])
def test_selector_dispatch_and_code_drift_refuse(fault):
    m=memory()
    if fault=='owner_primary_displacement':m.put(m.base+0x55ac480-0x20,struct.pack('<q',0x438))
    elif fault=='owner_1b0':m.q(m.base+0x55ad820+0x1b0,m.base+0xca4638)
    elif fault=='club150':m.q(m.base+0x559cf48+0x150,m.base+0xca4638)
    else:m.put(m.base+0xe2767c,bytes(4))
    with pytest.raises(ValueError):
        s=source(m);s.select_person6f(s.owner_club)
