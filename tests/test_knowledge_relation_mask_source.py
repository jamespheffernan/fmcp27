"""Typed passive relations versus whole original native paths in owned RAM."""
from _knowledge_stream_fixture import native_stream_transport
import hashlib
import struct
import pytest
from fm_live_mcp import knowledge_relation_mask_source as relation
from test_knowledge_passing_view import memory as view_memory
from test_knowledge_passing_state import full_subject_contract
from test_knowledge_context_score_source import SyntheticBridge
from _knowledge_state_native import execute


def memory(combined=False):
    m=view_memory(combined)
    for rva,n,digest in relation.NATIVE_GUARDS:
        raw=m.disk(rva,n);assert hashlib.sha256(raw).hexdigest()==digest;m.put(m.base+rva,raw)
    # Reuse already restored vtables, never seed overlapping metadata again.
    team=m.allocate(0x180);m.q(team,m.base+0x55c2e40);m.identity(team,2,3001,4001)
    m.q(team+0x30,m.other);m.put(team+0x2f,b'\0');m.vec(m.other+0x18,[team])
    root,header,_=m.tables['teams'];m.vec(header,[m.team,m.national,team]);m.external_team=team
    full_subject_contract(m);m.q(m.main+0x10,team);m.q(m.main+0x18,team);m.q(m.primary+0x128,team)
    nodes=m.allocate(24);m.vec(nodes,[]);m.q(m.other+0xb0,nodes);m.nodes=nodes
    m.put(m.base+0x56d4953,b'\0');m.put(m.base+0x56d498a,b'\0');m.put(m.base+0x56d498b,b'\0')
    return m


def source(m,bridge=None):
    return relation.RelationSource(bridge or SyntheticBridge(m),'synthetic',m.person,m.person_ref,'Private Coach',18)


def check(m,expected=0):
    m.blocked=[(m.primary+0x148,m.primary+0x18d)]
    m.reads.clear();s=source(m);assert s.relation_mask()==expected;s.verify()
    producer={p for at,n in m.reads for p in range(at,at+n)}
    result,_,reads,writes,code=execute(m,0x20ee608,[m.human,m.primary],extra=relation.NATIVE_GUARDS)
    assert result==expected
    assert all(p in producer for at,n in reads for p in range(at,at+n)),[(hex(at),n)for at,n in reads if not all(p in producer for p in range(at,at+n))]
    return code


@pytest.mark.parametrize('combined',[False,True])
def test_distinct_club_zero_matches_all_five_original_negative_fanouts(combined):
    m=memory(combined);code=check(m)
    for entry in (0x20ef198,0x20ef3e8,0x20ef4d4,0x20ef7d8,0x20efa74,0x17800dc,0x17db1d8):assert entry in code
    assert 0x17bb4c0 not in code


@pytest.mark.parametrize('mode',[1,2])
def test_mode_one_two_skips_first_team_special_even_when953is_one(mode):
    m=memory();m.put(m.base+0x56d4951,bytes([mode]));m.put(m.base+0x56d4953,b'\1');check(m)


@pytest.mark.parametrize('mode',[0,3,255])
def test_other_modes_do_not_skip_unproved_first_team_branch(mode):
    m=memory();m.put(m.base+0x56d4951,bytes([mode]));m.put(m.base+0x56d4953,b'\1');m.identity(m.competition,0,40,4003)
    with pytest.raises(relation.core.SourceUnavailable,match='first-team special'):source(m).relation_mask()


def test_same_club_precedes_auxiliary_and_all_fanouts():
    m=memory();m.q(m.primary+0x128,m.team);m.q(m.main+0x10,m.team);m.q(m.main+0x18,m.team)
    m.blocked=[(m.human+0x4b8,m.human+0x4c0),(m.club+0x118,m.club+0x130)]
    check(m)


def test_native_global_mode_precedes_same_club_and_fanouts():
    m=memory();m.put(m.human+0x422,b'\0');m.put(m.base+0x56d498a,b'\1');m.put(m.base+0x56d498b,b'\1')
    check(m,0x5fe)


def row(m,first,second,kind=0,flags=0,byte15=0):
    at=m.allocate(0x38);m.q(at,first);m.q(at+8,second);m.put(at+0x30,bytes([kind]));m.put(at+0x15,bytes([byte15]));m.put(at+0x1c,struct.pack('<I',flags));return at


@pytest.mark.parametrize('kind,flags,byte15',[(17,1<<24,0),(24,1<<24,0),(0,1<<30,0),(0,1<<24,32),(0,0,0)])
def test_relation_skip_or_first_matching_null_preserves_native_zero(kind,flags,byte15):
    m=memory();r=row(m,m.club,m.other,kind,flags,byte15);m.vec(m.club+0x118,[r]);check(m)


def test_first_matching_nonsupplying_relation_stops_scan_before_later_selection():
    m=memory();a=row(m,m.club,m.other);b=row(m,m.club,m.other,flags=1<<24);m.vec(m.club+0x118,[a,b]);check(m)


@pytest.mark.parametrize('flags',[1<<3,1<<24,(1<<24)|(1<<3)])
def test_reached_selection_refuses_instead_of_fabricating_zero(flags):
    m=memory();m.vec(m.club+0x118,[row(m,m.club,m.other,flags=flags)])
    with pytest.raises(relation.core.SourceUnavailable,match='17bb4c0'):source(m).relation_mask()


@pytest.mark.parametrize('country',[0x186,0x16c])
def test_special_country_lookup_remains_unavailable(country):
    m=memory();m.q(m.other+0xd8,m.nation);m.identity(m.nation,0,country,4002)
    with pytest.raises(relation.core.SourceUnavailable,match='special-country'):source(m).relation_mask()


def test_nonempty_owned_recent_nodes_are_not_empty_lookup():
    m=memory();m.vec(m.nodes,[m.allocate(0x60)])
    with pytest.raises(relation.core.SourceUnavailable,match='owned CLUB node family'):source(m).relation_mask()


def test_missing_owned_node_container_is_unavailable():
    m=memory();m.q(m.other+0xb0,0)
    with pytest.raises(relation.core.SourceUnavailable,match='Missing owned'):source(m).relation_mask()


def test_nonnull_owner_parent_and_subject_parent_remain_distinct_unsupported_routes():
    m=memory();m.vec(m.club+0x118,[row(m,m.other,m.club,kind=4)])
    with pytest.raises(relation.core.SourceUnavailable,match='owner-parent'):source(m).relation_mask()
    m=memory();m.vec(m.other+0x118,[row(m,m.club,m.other,kind=4)])
    with pytest.raises(relation.core.SourceUnavailable,match='subject-parent'):source(m).relation_mask()


def test_final_callback_change_to_consumed_relation_flag_rejects():
    m=memory();r=row(m,m.club,m.other,kind=17);m.vec(m.club+0x118,[r]);b=SyntheticBridge(m)
    s=source(m,b);assert s.relation_mask()==0
    b.on_current=lambda n:m.put(r+0x30,b'\0')
    with pytest.raises(ValueError,match='changed'):s.verify()


@pytest.mark.parametrize('combined',[False,True])
def test_distinct_club_collector_composes_real_K_and_H_without_lower_stubs(combined):
    m=memory(combined);s=source(m);result=relation.core.evaluate(s)
    assert result.score is not None,result.reason
    s.verify()
    native,_,reads,_,code=execute(m,0x2386548,[m.human_person,m.primary],extra=relation.NATIVE_GUARDS)
    assert result.score==native
    assert 0x20ee608 in code and 0x2388658 in code
    # Continue through the exact same typed state collector, rather than
    # accepting a separately supplied relation Boolean or score operand.
    native_state,score,route=s.state();assert route=='threshold'
    output=m.allocate(8)
    h,hscore,_,_,hcode=execute(m,0x23871f0,[m.record,m.person,18,output,0,1],score_pointer=output,extra=relation.NATIVE_GUARDS)
    assert (native_state,score)==(h,relation.core._signed(hscore,8))
    assert 0x20ee608 in hcode


@pytest.mark.parametrize('kind',['equal','both_null','different','expired','flag_two'])
def test_auxiliary_association_equality_and_strict_expiry_match_original(kind):
    m=memory();m.put(m.base+0x56d4993,b'\1')
    wrapper=m.allocate(0x18);m.q(wrapper+0x10,m.owner_contract);m.q(m.human_common+0x80,wrapper)
    m.q(m.primary+0x120,m.national);m.put(m.national+0xe2,b'\1');m.put(m.national+0xb8,struct.pack('<HH',318,2030))
    if kind=='both_null':m.q(m.club+0xd8,0);m.q(m.container+0x170,0)
    elif kind=='different':m.q(m.container+0x170,0)
    elif kind=='expired':m.put(m.national+0xb8,struct.pack('<HH',317,2030))
    elif kind=='flag_two':m.put(m.national+0xe2,b'\2')
    expected=0x5fe if kind in ('equal','both_null')else 0
    check(m,expected)
    # Any native E2 clear happened only inside the owned VM.
    assert m.cells[m.national+0xe2]==(2 if kind=='flag_two'else 1)


@pytest.mark.parametrize('combined',[False,True])
@pytest.mark.parametrize('scalar,expected_state',[(8000,'exact'),(6500,'range')])
def test_distinct_club_permitted_view_matches_whole_original_range(combined,scalar,expected_state):
    from test_knowledge_passing_view import assert_public_shape
    m=memory(combined);m.put(m.primary+0x25a,struct.pack('<h',scalar));m.reads.clear()
    actual=relation.collect(SyntheticBridge(m),'synthetic',subject_person=m.person,subject_identity=m.person_ref,coach_name='Private Coach')
    assert actual['value']['state']==expected_state;assert_public_shape(actual)
    producer={p for at,n in m.reads for p in range(at,at+n)}
    output=m.allocate(8)
    _,raw,reads,_,code=execute(m,0x2386eac,[m.record,output,m.primary,18,0,0,1],score_pointer=output,output_width=3,
        extra=relation.NATIVE_GUARDS+relation.view.NATIVE_GUARDS)
    low,high,_=struct.unpack('bbb',raw)
    assert actual['value']==({'state':'exact','value':low}if expected_state=='exact'else {'state':'range','minimum':low,'maximum':high})
    assert 0x20ee608 in code
    assert all(p in producer for at,n in reads for p in range(at,at+n))


@pytest.mark.parametrize('mode',[0,3,255])
def test_first_team_non_special_definition_skips_selection(mode):
    m=memory();m.put(m.base+0x56d4951,bytes([mode]));m.put(m.base+0x56d4953,b'\1');check(m)


def test_first_team_alternate_definition_is_checked_before_refusing_selection():
    m=memory();m.put(m.base+0x56d4953,b'\1');m.q(m.team+0x58,m.competition);check(m)
    m.identity(m.competition,0,40,4003)
    with pytest.raises(relation.core.SourceUnavailable,match='first-team special'):source(m).relation_mask()



def native_node(m,table,team=0,day=317,year=2030):
    at=m.allocate(0x60);m.native_type(at,table)
    _,target,kind=relation.NODE_TYPES[table];m.q(m.base+table+0x28,m.base+target)
    m.q(at+0x38,team);m.put(at+0x50,struct.pack('<HH',day,year))
    # Restore relocated metadata after fixture-only broad vtable seeding.
    for rva,(displacement,info,name,raw) in m.metadata.items():
        m.put(m.base+rva-16,struct.pack('<qQ',displacement,m.base+info))
        m.q(m.base+info+8,m.base+name);m.put(m.base+name,raw)
    return at


@pytest.mark.parametrize('table',list(relation.NODE_TYPES))
def test_every_bound_owned_node_kind_matches_its_original_getter_and_negative_scan(table):
    m=memory();node=native_node(m,table,m.team);m.vec(m.nodes,[0,node]);check(m)


def test_matching_stale_node_stops_before_older_current_match():
    m=memory();fresh=native_node(m,0x55bd358,m.external_team,317);stale=native_node(m,0x55bd358,m.external_team,296)
    m.vec(m.nodes,[fresh,stale]);check(m)


@pytest.mark.parametrize('day,year',[(297,2030),(317,2030),(318,2030),(317,2031)])
def test_matching_current_or_future_node_requires_real_handle_resolution(day,year):
    m=memory();node=native_node(m,0x55bd358,m.external_team,day,year);m.vec(m.nodes,[node])
    with pytest.raises(relation.core.SourceUnavailable,match='17bb4c0'):source(m).relation_mask()


@pytest.mark.parametrize('fault',['dispatch','metadata','getter'])
def test_owned_node_dispatch_type_and_literal_getter_drift_refuse(fault):
    m=memory();node=native_node(m,0x55c3910,m.team);m.vec(m.nodes,[node])
    if fault=='dispatch':m.q(m.base+0x55c3910+0x28,m.base+0x166b40c)
    elif fault=='metadata':m.put(m.base+0x55c3910-16,struct.pack('<q',8))
    else:m.put(m.base+0x18039c4,bytes.fromhex('e0038052'))
    with pytest.raises(ValueError):source(m).relation_mask()
