"""Typed TEAM handles versus complete original lookup; no game calls."""
from _knowledge_stream_fixture import native_stream_transport
import struct
import pytest
from fm_live_mcp import database,knowledge_relation_mask_source as relation
from test_knowledge_relation_mask_source import memory,source,native_node,check
from _knowledge_state_native import execute


def lookup_memory():
    m=memory();old,header,start=m.tables['teams']
    root=m.allocate(0xb0);m.q(root,m.base+database.TABLES['teams'][1]);m.q(root+0x88,header)
    m.q(m.base+database.TABLES['teams'][0],root);m.tables['teams']=(root,header,start)
    for i,(team,uid,secondary)in enumerate([(m.team,10,40),(m.national,20,0),(m.external_team,30,50)]):m.identity(team,i,uid,secondary)
    m.handle=m.allocate(8);m.team_root=root
    return m


def resolve(m,primary,secondary):
    m.put(m.handle,struct.pack('<II',primary&0xffffffff,secondary&0xffffffff));m.reads.clear()
    s=source(m);result=s.resolve_team_handle(m.handle);s.verify()
    consumed={p for at,n in m.reads for p in range(at,at+n)}
    actual,_,reads,_,code=execute(m,0x10b2328,[m.team_root,m.handle],extra=relation.NATIVE_GUARDS)
    assert actual==(result.address if result else 0)
    assert all(p in consumed for at,n in reads for p in range(at,at+n))
    return result,code


@pytest.mark.parametrize('primary,secondary,kind',[(10,40,'team'),(20,20,'national'),(30,50,'external'),
 (10,0,'team'),(20,0,'national'),(30,0,'external'),(10,10,None),(10,50,None),(20,21,None),
 (0,0,None),(-1,40,None),(-2147483648,1,None),(40,0,None),(40,50,None),(10,-1,None)])
def test_primary_secondary_and_empty_alias_cases_match_original(primary,secondary,kind):
    m=lookup_memory();result,_=resolve(m,primary,secondary)
    expected={'team':m.team,'national':m.national,'external':m.external_team,None:0}[kind]
    assert (result.address if result else 0)==expected


@pytest.mark.parametrize('secondary_flag',[0,2,255])
def test_secondary_lookup_vector_uses_native_flag_and_not_canonical_order(secondary_flag):
    m=lookup_memory();m.put(m.team_root+0x64,b'\1');m.put(m.team_root+0xa8,bytes([secondary_flag]))
    m.vec(m.team_root+0x90,[m.external_team,m.team,m.national])
    # Native binary search follows this physical order even if malformed as a
    # sorted index. The adapter reproduces it, never silently locally repairs.
    result,_=resolve(m,10,40);assert result.address==m.team


def test_same_uid_different_secondary_uses_physical_native_midpoint():
    m=lookup_memory();m.identity(m.national,1,10,60)
    result,_=resolve(m,10,60);assert result.address==m.national
    result,_=resolve(m,10,40);assert result is None


def test_empty_canonical_table_cannot_bind_the_selected_coach():
    m=lookup_memory();m.vec(m.tables['teams'][1],[])
    m.blocked=[(m.handle,m.handle+8),(m.team_root+8,m.team_root+0x18)]
    # The original lower helper returns null, but the full collector cannot
    # establish a selected coach with a missing canonical TEAM table.
    with pytest.raises(ValueError,match='Team index is outside'):source(m)
    actual,_,reads,_,_=execute(m,0x10b2328,[m.team_root,m.handle],extra=relation.NATIVE_GUARDS)
    assert actual==0 and not any(at<m.handle+8 and at+n>m.handle for at,n in reads)


def test_nonempty_alias_vector_is_unavailable_even_when_no_primary_match_is_obvious():
    m=lookup_memory();aliases=m.allocate(12);m.put(aliases,struct.pack('<iii',999,30,50));m.q(m.team_root+8,aliases);m.q(m.team_root+0x10,aliases+12)
    m.put(m.handle,struct.pack('<II',10,50))
    with pytest.raises(relation.core.SourceUnavailable,match='nonempty TEAM alias'):source(m).resolve_team_handle(m.handle)


def test_lazy_secondary_sort_is_unavailable_and_never_mutates_game_source():
    m=lookup_memory();m.put(m.team_root+0x64,b'\1');m.put(m.team_root+0xa8,b'\1');before=dict(m.cells)
    m.put(m.handle,struct.pack('<II',10,40));before=dict(m.cells)
    with pytest.raises(relation.core.SourceUnavailable,match='lazy TEAM UID sort'):source(m).resolve_team_handle(m.handle)
    assert m.cells==before


def test_recent_node_handle_resolving_other_team_continues_reverse_scan():
    m=lookup_memory();node=native_node(m,0x55bd358,m.external_team);m.put(node+0x48,struct.pack('<II',30,50));m.vec(m.nodes,[node])
    code=check(m);assert 0x10b2328 in code


def test_recent_node_exact_or_null_handle_requires_real_next_selection():
    for primary,secondary in [(10,40),(10,0),(0,0),(40,0),(40,50)]:
        m=lookup_memory();node=native_node(m,0x55bd358,m.external_team);m.put(node+0x48,struct.pack('<II',primary,secondary));m.vec(m.nodes,[node])
        with pytest.raises(relation.core.SourceUnavailable,match='17bb4c0'):source(m).relation_mask()


def test_final_lifetime_change_to_visited_team_secondary_rejects():
    from test_knowledge_context_score_source import SyntheticBridge
    m=lookup_memory();m.put(m.handle,struct.pack('<II',10,40));b=SyntheticBridge(m);s=source(m,b)
    assert s.resolve_team_handle(m.handle).address==m.team
    b.on_current=lambda _:m.put(m.team+0x10,struct.pack('<I',41))
    with pytest.raises(ValueError,match='changed'):s.verify()
