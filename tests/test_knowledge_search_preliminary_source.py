"""Typed source and complete original preliminary/alias/association callees.

Synthetic initialized alias trees contain the source initializer's re-extracted
constants. Original13B7CBC searches those nodes; no lower result is stubbed.
No game process, native live call, cache creation or public mode is used.
"""
from _knowledge_stream_fixture import native_stream_transport
import hashlib
import struct

import pytest
from unicorn.arm64_const import UC_CPU_ARM64_MAX

from fm_live_mcp import knowledge_search_preliminary_source as source
from fm_live_mcp import knowledge_search_association_source as association
from test_knowledge_search_association_source import memory as association_memory,rows
from _knowledge_state_native import execute


@pytest.fixture
def memory(association_memory):
    m=association_memory
    for rva,n,digest in source.NATIVE_GUARDS:
        raw=m.disk(rva,n);assert hashlib.sha256(raw).hexdigest()==digest;m.put(m.base+rva,raw)
    table=int.from_bytes(m.read(m.person,8),'little')
    primary_table=int.from_bytes(m.read(m.primary,8),'little')
    for slot,target in ((0x2c8,0xd30ff8),(0x338,0xd2cde8)):m.q(primary_table+slot,m.base+target)
    m.q(table+0x1d0,m.base+0xca4674)
    m.put(table-0x1e0,struct.pack('<q',-0x110))
    m.put(m.person+0x18,bytes(8));m.put(m.container+0xb9,b'\0')
    m.put(m.base+0x56d4992,b'\x01')
    pairs=list(struct.iter_unpack('<II',m.disk(0x5396de0,160)))+[(380,784)]
    def tree(items):
        if not items:return 0
        i=len(items)//2;node=m.allocate(0x28)
        m.q(node,tree(items[:i]));m.q(node+8,tree(items[i+1:]))
        m.put(node+0x1c,struct.pack('<II',*items[i]));return node
    m.q(m.base+0x56d39f8,tree(sorted(pairs)));m.put(m.base+0x56d3a08,b'\x01')
    canary=m.allocate(8);m.q(canary,0x1111222233334444);m.q(m.base+0x54b05b0,canary)
    m.alias_pairs=pairs
    return m


def identity(m,address):return struct.unpack('<III',m.read(address+8,12))


def evaluate(m,context=None,**kwargs):
    context=m.container if context is None else context
    return source.evaluate(m.read,m.base,m.person,m.person_ref,context,
                          identity(m,context)if context else None,
                          check_current=kwargs.pop('check_current',lambda:('process','save','build')),**kwargs)


def native(m,context=None):
    value,_,reads,writes,instructions=execute(m,0x14fb918,[m.primary,m.container if context is None else context,0],
                                            extra=source.NATIVE_GUARDS+association.NATIVE_GUARDS,
                                            cpu_model=UC_CPU_ARM64_MAX)
    assert 0x14fb918 in instructions
    assert all(0x200000000<=at<at+n<=0x200010000 for _,at,n in writes)
    return bool(value),reads,instructions


def alternate_context(m,nation=None,uid=None):
    at=m.typed('national_team_container',0x600)
    m.identity(at,1,identity(m,m.nation)[1]if uid is None else uid,9999)
    m.q(at+0x170,m.nation if nation is None else nation);m.put(at+0xb9,b'\0')
    m.database('national_team_containers',[m.container,at])
    restore_metadata(m)
    return at


def restore_metadata(m):
    # The fixture seeds broad virtual-slot ranges. Adding a type after its
    # constructor can overlap neighboring RTTI, so restore the original rows.
    for rva,(delta,info,name,raw) in m.metadata.items():
        m.put(m.base+rva-16,struct.pack('<qQ',delta,m.base+info))
        m.q(m.base+info+8,m.base+name);m.put(m.base+name,raw)


def test_same_projection_all_status_bytes_match_complete_native(memory):
    m=memory
    for raw in range(256):
        m.put(m.primary+0x266,bytes([raw]))
        expected,_,instructions=native(m)
        assert evaluate(m)['native_result'] is expected is (raw not in (0x52,0x56,0x58,0x5a,0x5b))
        assert 0xd5c590 in instructions and 0x13b7cbc not in instructions


def test_cross_projection_all_status_bytes_match_full_lower_alias_and_id_calls(memory):
    m=memory;context=alternate_context(m)
    for raw in range(256):
        m.put(m.primary+0x266,bytes([raw]))
        expected,_,instructions=native(m,context)
        assert evaluate(m,context)['native_result'] is expected
        assert expected is (raw in (0,0x50,0x54,0x55))
        assert 0x13b7cbc in instructions
        if raw not in (0x53,0x59):assert 0xcf3c90 in instructions


def test_every_discriminator_byte_preserves_only_native_low_bit_test(memory):
    m=memory
    for raw in range(256):
        m.put(m.container+0xb9,bytes([raw]))
        assert evaluate(m)['native_result'] is native(m)[0] is (not bool(raw&1))


def test_kind10_rows_are_rejected_before_alias_or_status_admission(memory):
    m=memory
    for category in range(16):
        rows(m,[(0,0,category,0)])
        assert evaluate(m)['native_result'] is native(m)[0] is (category!=10)


def test_mode_and_person_flag_select_alternate_then_fallback_projection(memory):
    m=memory;context=alternate_context(m);m.q(m.nation+0x118,context)
    for mode,flags,selected in ((1,0,m.container),(1,0x1000,context),(0,0x1000,m.container),(2,0x1000,m.container)):
        m.put(m.base+0x56d4992,bytes([mode]));m.put(m.person+0x18,struct.pack('<Q',flags))
        m.put(selected+0xb9,bytes([(flags>>12)&1]))
        assert evaluate(m,selected)['native_result'] is native(m,selected)[0] is True
        m.put(selected+0xb9,b'\0')
    m.put(m.base+0x56d4992,b'\x01');m.put(m.person+0x18,struct.pack('<Q',0x1000))
    m.q(m.nation+0x118,0);m.put(m.container+0xb9,b'\x01')
    assert evaluate(m)['native_result'] is native(m)[0] is True


def test_special_raw_association_bypasses_the_later_status_rejection(memory):
    m=memory;index,_,secondary=identity(m,m.nation);m.identity(m.nation,index,0x23716,secondary)
    context=alternate_context(m);m.put(m.primary+0x266,b'\x53')
    actual=evaluate(m,context);expected,_,instructions=native(m,context)
    assert actual['native_result'] is expected is True
    assert 0x13b7cbc in instructions and 0xd2cde8 not in instructions


def test_2fe_247_exception_cannot_be_dropped(memory):
    m=memory;index,_,secondary=identity(m,m.nation);m.identity(m.nation,index,0x2fe,secondary)
    context=alternate_context(m)
    assert evaluate(m,context)['native_result'] is native(m,context)[0] is True
    other=m.typed('nation',0x220);m.identity(other,1,0x247,0x247)
    m.database('nations',[m.nation,other]);rows(m,[(other,8,9,0x50)])
    restore_metadata(m)
    actual=evaluate(m,context);expected,_,instructions=native(m,context)
    assert actual['native_result'] is expected is False
    assert 0xcf3c90 in instructions


def test_all_initializer_aliases_and_unmapped_ids_match_full_original_lookup(memory):
    m=memory
    for raw in [k for k,_ in m.alias_pairs]+[110,390,145174,784,111111]:
        index,_,secondary=identity(m,m.nation);m.identity(m.nation,index,raw,secondary)
        reader=source.Reader(m.read,m.base)
        value,_,_,_,instructions=execute(m,0x13b7cbc,[m.nation],extra=source.NATIVE_GUARDS,cpu_model=UC_CPU_ARM64_MAX)
        assert reader.normalized(m.nation)==value
        assert 0x13b7d60 not in instructions
    assert dict(m.alias_pairs)==source.ALIASES


def test_null_subject_association_context_and_projection_match_native_false(memory):
    m=memory
    assert evaluate(m,0)['native_result'] is native(m,0)[0] is False
    m.q(m.nation+0x110,0);m.q(m.nation+0x118,0)
    assert evaluate(m)['native_result'] is native(m)[0] is False
    m.q(m.common+0x38,0)
    assert evaluate(m)['native_result'] is native(m)[0] is False


@pytest.mark.parametrize('fault',['context_identity','context_type','source','alias_constants','malformed_rows','null_lower_nation'])
def test_bad_sources_are_unavailable_not_native_false(memory,fault):
    m=memory
    if fault=='context_identity':
        with pytest.raises(ValueError):source.evaluate(m.read,m.base,m.person,m.person_ref,m.container,(99,99,99),check_current=lambda:('bound',))
        return
    if fault=='context_type':m.q(m.container,0)
    if fault=='source':m.put(m.base+0x14fb918,b'\0')
    if fault=='alias_constants':m.put(m.base+0x5396de0,b'\0')
    if fault=='malformed_rows':
        at,holder=rows(m,[]);m.q(holder+8,at+1)
    if fault=='null_lower_nation':
        context=alternate_context(m);m.q(context+0x170,0)
        with pytest.raises(ValueError):evaluate(m,context)
        return
    with pytest.raises(ValueError):evaluate(m)


def test_final_callback_must_not_change_consumed_discriminator(memory):
    m=memory;calls=[]
    def lifetime():
        calls.append(1)
        if len(calls)==2:m.put(m.container+0xb9,b'\x01')
        return ('bound','save','build')
    with pytest.raises(ValueError,match='changed'):evaluate(m,check_current=lifetime)
