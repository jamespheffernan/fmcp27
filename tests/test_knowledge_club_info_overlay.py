"""Literal type-getter and whole native consumer parity in owned fixtures."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys

import pytest

from fm_live_mcp import knowledge_relation_mask_source as relation
from test_knowledge_relation_mask_source import memory,native_node
from test_knowledge_context_score_source import SyntheticBridge
from _knowledge_state_native import execute

from fm_live_mcp import knowledge_club_info_overlay as candidate
Source=candidate.source_type(relation.RelationSource,relation)
EXTRA=tuple((target,8,hashlib.sha256(raw).hexdigest())for name,target,kind,raw in candidate.EXTRA_TYPES.values())


def source(m,new=True):
    Type=Source if new else relation.RelationSource
    return Type(SyntheticBridge(m),'synthetic',m.person,m.person_ref,'Private Coach',18)


def extra_node(m,table):
    name,target,kind,raw=candidate.EXTRA_TYPES[table]
    assert m.disk(target,8)==raw
    row=m.allocate(0x60);m.q(row,m.base+table)
    # Seed exact relocated RTTI/route facts only. The old fixture's broad700-
    # byte vtable seed overlaps neighbouring real types when54 are combined.
    displacement,info=struct.unpack('<qQ',m.disk(table-16,16));info&=0xffffffff
    text=int.from_bytes(m.disk(info+8,8),'little')&0xffffffff
    actual=m.disk(text,192).split(b'\0')[0]+b'\0';assert actual==name+b'\0'
    m.metadata[table]=(displacement,info,text,actual)
    m.q(m.base+table+0x28,m.base+target);m.put(m.base+target,raw)
    for rva,(displacement,info,text,actual)in m.metadata.items():
        m.put(m.base+rva-16,struct.pack('<qQ',displacement,m.base+info))
        m.q(m.base+info+8,m.base+text);m.put(m.base+text,actual)
    return row


def original_recent(m,club,team,expected):
    return execute(m,0x17db1d8,[club.address,expected.address,team.address],extra=relation.NATIVE_GUARDS+EXTRA)


@pytest.mark.parametrize('table',list(candidate.EXTRA_TYPES))
def test_old_refuses_new_proves_literal_kind_and_skips_all_payload(table):
    m=memory(False);row=extra_node(m,table);m.vec(m.nodes,[row])
    m.blocked=[(row+8,row+0x60),(m.primary+0x148,m.primary+0x18d)]
    with pytest.raises(relation.core.SourceUnavailable,match='owned CLUB node family'):source(m,False).relation_mask()
    s=source(m);m.reads.clear();assert s.relation_mask()==0;s.verify();typed=list(m.reads)
    result,_,reads,_,trace=execute(m,0x20ee608,[m.human,m.primary],extra=relation.NATIVE_GUARDS+EXTRA)
    assert result==0 and candidate.EXTRA_TYPES[table][1]in trace and 0x17db1d8 in trace
    assert not any(a<row+0x60 and row+8<a+n for a,n in typed+reads)


@pytest.mark.parametrize('table',[0x55c3850,0x55c6518])
def test_literal_kind_code_route_and_primary_type_displacement_are_mandatory(table):
    for fault in('getter_code','route','displacement','name'):
        m=memory();row=extra_node(m,table);m.vec(m.nodes,[row]);s=source(m)
        name,target,kind,raw=candidate.EXTRA_TYPES[table]
        if fault=='getter_code':m.put(m.base+target,bytes.fromhex('e0038052c0035fd6'))  # returns31
        elif fault=='route':m.q(m.base+table+0x28,m.base+target+4)
        elif fault=='displacement':m.put(m.base+table-16,struct.pack('<q',8))
        else:
            info=int.from_bytes(m.read(m.base+table-8,8),'little');text=int.from_bytes(m.read(info+8,8),'little');m.put(text,b'X')
        with pytest.raises(ValueError):s.relation_mask()


def test_reverse_first_matching_stale_node_stops_before_older_fresh_node():
    m=memory();fresh=native_node(m,0x55bd358,m.external_team,317);stale=native_node(m,0x55bd358,m.external_team,296)
    extras=[extra_node(m,table)for table in(0x55c3850,0x55c6518)]
    m.vec(m.nodes,[fresh,extras[0],stale,extras[1]])
    s=source(m);club=s.entity(m.other,'club');team=s.team(m.external_team);expected=s.team(m.team)
    assert s._recent_nodes(club,team,expected)is None;s.verify()
    result,_,reads,_,trace=original_recent(m,club,team,expected)
    assert result==0 and not any(fresh<=a<fresh+0x60 for a,n in reads)


def test_latest_fresh_matching_row_wins_after_skipped_kinds_and_nulls():
    m=memory();older=native_node(m,0x55bd358,m.external_team,316);newer=native_node(m,0x55bd358,m.external_team,317)
    extra=extra_node(m,0x55c3850);m.vec(m.nodes,[older,extra,newer,0])
    s=source(m);club=s.entity(m.other,'club');team=s.team(m.external_team);expected=s.team(m.team)
    assert s._recent_nodes(club,team,expected)==newer;s.verify()
    assert original_recent(m,club,team,expected)[0]==newer


def test_unproved_family_and_null_expected_caller_remain_unavailable():
    m=memory();unknown=m.allocate(0x60);m.vec(m.nodes,[unknown]);s=source(m)
    with pytest.raises(relation.core.SourceUnavailable,match='owned CLUB node family'):s.relation_mask()
    club=s.entity(m.other,'club');team=s.team(m.external_team)
    with pytest.raises(relation.core.SourceUnavailable,match='nonnull TEAM caller context'):s._recent_nodes(club,team,None)


@pytest.mark.parametrize('combined',[False,True])
def test_all_catalog_kinds_compose_into_complete_original_H_without_stubs(combined):
    m=memory(combined);rows=[extra_node(m,table)for table in candidate.EXTRA_TYPES];m.vec(m.nodes,rows)
    s=source(m);actual=s.state();s.verify();output=m.allocate(8)
    native,score,_,_,trace=execute(m,0x23871f0,[m.record,m.person,18,output,0,1],score_pointer=output,extra=relation.NATIVE_GUARDS+EXTRA)
    assert actual[:2]==(native,relation.core._signed(score,8))
    assert all(target in trace for name,target,kind,raw in candidate.EXTRA_TYPES.values())


def test_global_frozen_catalog_is_not_modified():
    assert len(relation.NODE_TYPES)==9 and not(set(candidate.EXTRA_TYPES)&set(relation.NODE_TYPES))
