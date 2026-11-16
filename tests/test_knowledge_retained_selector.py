"""Full original17bb4c0 retained selector, typed source and no lower stubs."""
from _knowledge_stream_fixture import native_stream_transport
import hashlib
import struct
import pytest
from fm_live_mcp import knowledge_person_selector as selector,knowledge_retained_person as retained
from test_knowledge_person_selector import memory as prefix_memory
from test_knowledge_context_score_source import SyntheticBridge
from _knowledge_state_native import execute


def memory():
    m=prefix_memory()
    for rva,n,digest in selector.NATIVE_GUARDS+retained.NATIVE_GUARDS:
        raw=m.disk(rva,n);assert hashlib.sha256(raw).hexdigest()==digest;m.put(m.base+rva,raw)
    cookie=m.allocate(8);m.q(cookie,0x1234);m.q(m.base+0x54b05b0,cookie)
    m.cookie=cookie
    auxiliary=m.allocate(0x50);m.q(m.club+0xb0,auxiliary);m.container=m.allocate(24);m.q(auxiliary+0x48,m.container)
    m.node=m.allocate(16);m.put(m.node,struct.pack('<iBB3xB',1,0x6f,255,1));m.vec(m.container,[m.node])
    rules=m.allocate(16);m.native_type(rules,0x55dd068);m.q(m.base+0x56d57d0,rules)
    for person in(m.person,m.human_person):
        table=int.from_bytes(m.read(person,8),'little');rva=table-m.base
        for slot in(0x6d0,):m.q(table+slot,m.base+(int.from_bytes(m.disk(rva+slot,8),'little')&0xffffffff))
        m.put(table-0x6e0,m.disk(rva-0x6e0,8))
    for rva,(delta,info,name,raw)in m.metadata.items():
        m.put(m.base+rva-16,struct.pack('<qQ',delta,m.base+info));m.q(m.base+info+8,m.base+name);m.put(m.base+name,raw)
    return m


def source(m,bridge=None):
    return selector.SelectorSource(bridge or SyntheticBridge(m),'synthetic',m.person,m.person_ref,'Private Coach',18)


def compare(m):
    m.blocked=[(m.primary+0x148,m.primary+0x18d)];m.reads.clear()
    s=source(m);result=s.select_person6f(s.owner_club);s.verify()
    consumed={p for at,n in m.reads for p in range(at,at+n)}
    value,_,reads,writes,code=execute(m,0x17bb4c0,[m.club,0x6f,0,1,1],extra=selector.NATIVE_GUARDS+retained.NATIVE_GUARDS)
    assert value==result['person_address']
    assert all(p in consumed for at,n in reads for p in range(at,at+n)),[(hex(at),n)for at,n in reads if not all(p in consumed for p in range(at,at+n))]
    assert 0x15c18a4 in code and 0x17bbfc8 in code
    return result,code


def test_full_native_retained_HUMAN_person_selector_matches_typed_source():
    m=memory();result,code=compare(m)
    assert result['person_address']==m.human_person and result['non_player_address']==m.human
    assert 0x17bc488 not in code and 0x15b6470 not in code


def test_first_matching_node_wins_and_later_null_selection_is_not_substituted():
    m=memory();later=m.allocate(16);m.put(later,struct.pack('<iBB3xB',-1,0x6f,255,1));m.vec(m.container,[m.node,later]);compare(m)


@pytest.mark.parametrize('case',['missing_container','no_match','negative_ordinal','wrong_context'])
def test_retained_absence_is_cold_unknown_not_full_selector_null(case):
    m=memory()
    if case=='missing_container':aux=int.from_bytes(m.read(m.club+0xb0,8),'little');m.q(aux+0x48,0)
    elif case=='no_match':m.vec(m.container,[])
    elif case=='negative_ordinal':m.put(m.node,struct.pack('<i',-1))
    else:m.put(m.node+5,b'\0')
    s=source(m)
    with pytest.raises(ValueError,match='cold source'):s.select_person6f(s.owner_club)


def test_wrong_main_contract_owner_rejects_instead_of_accepting_retained_person():
    m=memory();m.put(m.node,struct.pack('<i',0));m.q(m.main+8,m.human_person);s=source(m)
    with pytest.raises(ValueError):s.select_person6f(s.owner_club)


def test_final_lifetime_change_to_retained_node_rejects():
    m=memory();b=SyntheticBridge(m);s=source(m,b);assert s.select_person6f(s.owner_club)['person_address']==m.human_person
    b.on_current=lambda _:m.put(m.node,struct.pack('<i',-1))
    with pytest.raises(ValueError,match='changed'):s.verify()


@pytest.mark.parametrize('kind',['staff','player_staff','actual','human_manager'])
def test_full_original_selector_accepts_existing_canonical_person_families(kind):
    from fm_live_mcp import staff
    m=memory()
    fields={'staff':(0x5583660,0x55849d8,0x208),'player_staff':(0x558ef38,0x55908e0,0x480),
            'actual':(0x5588ee8,0x558a780,0x388),'human_manager':(0x55ac480,0x55ad820,0x548)}
    primary_table,person_table,offset=fields[kind]
    primary=m.allocate(0x700);person=primary+offset;m.native_type(primary,primary_table);m.native_type(person,person_table)
    m.identity(person,2,5001,5002)
    if kind=='player_staff':m.native_type(primary+0x278,0x558f568)
    m.q(m.base+person_table+0x6d0,m.base+(0xca4a50 if kind=='actual'else 0xca4e8c))
    m.put(m.base+person_table-0x6e0,m.disk(person_table-0x6e0,8))
    contract=m.contract('full_contract',person,m.team);m.put(contract+0x26,b'\2');m.q(person-0x98,contract)
    m.vec(m.tables['people'][1],[m.person,m.human_person,person]);m.put(m.node,struct.pack('<i',2))
    for rva,(delta,info,name,raw)in m.metadata.items():
        m.put(m.base+rva-16,struct.pack('<qQ',delta,m.base+info));m.q(m.base+info+8,m.base+name);m.put(m.base+name,raw)
    result,_=compare(m);assert result['person_address']==person
    assert result['non_player_address']==(0 if kind=='actual'else primary+0x278 if kind=='player_staff'else primary)


@pytest.mark.parametrize('offset',[0,4])
def test_retained_plain_nodes_at_both_native_word_alignments_match_original(offset):
    m=memory();storage=m.allocate(24);node=storage+offset;m.put(node,struct.pack('<iBB3xB',1,0x6f,255,1));m.vec(m.container,[node]);compare(m)


def test_non_word_aligned_retained_plain_node_rejects():
    m=memory();storage=m.allocate(24);node=storage+2;m.put(node,struct.pack('<iBB3xB',1,0x6f,255,1));m.vec(m.container,[node]);s=source(m)
    with pytest.raises(ValueError,match='packed retained PERSON node'):s.select_person6f(s.owner_club)
