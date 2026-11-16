"""Complete original F0F038 and3AB45DC in owned RAM; no native live calls."""
from _knowledge_stream_fixture import native_stream_transport
import hashlib
import struct

import pytest

from fm_live_mcp import knowledge_competition_context_source as source
from test_knowledge_context_score_source import Memory
from test_knowledge_search_preliminary_source import identity
from _knowledge_state_native import execute


@pytest.fixture
def memory():
    m=Memory()
    for rva,n,digest in source.NATIVE_GUARDS:
        raw=m.disk(rva,n);assert hashlib.sha256(raw).hexdigest()==digest;m.put(m.base+rva,raw)
    m.context=m.allocate(0x520);m.settings=m.allocate(0x240);m.context_group=m.allocate(16)
    m.q(m.competition+0xb0,m.context);m.q(m.context+0x388,m.settings);m.q(m.context+0x138,m.context_group)
    m.put(m.context_group+0xc,struct.pack('<I',101));m.put(m.base+0x56d3518,struct.pack('<I',202))
    m.put(m.settings+0x23c,b'\1');m.put(m.context+0x3be,b'\0')
    return m


def actual(m,**kwargs):
    return source.evaluate(m.read,m.base,m.competition,identity(m,m.competition),
                          check_current=kwargs.pop('check_current',lambda:('process','save','build')),**kwargs)


def native(m):
    result,_,reads,writes,trace=execute(m,0xf0f038,[m.competition],extra=source.NATIVE_GUARDS)
    assert all(0x200000000<=at<at+n<=0x200010000 for _,at,n in writes)
    return bool(result),reads,trace


def test_all_classification_bytes_match_whole_original_helper(memory):
    m=memory
    for code in range(256):
        m.put(m.context+0x3be,bytes([code]));expected,reads,trace=native(m)
        result=actual(m)
        assert result['native_result'] is expected is not source._classified(code)
        assert 0x3ab45dc in trace
        assert set(result)=={'scope','native_result','club_score_evaluated','field_visibility_evaluated','non_atomic'}


@pytest.mark.parametrize('same_group',[False,True])
def test_all_direct_status_and_flag_bytes_match_original(memory,same_group):
    m=memory
    if same_group:m.put(m.base+0x56d3518,struct.pack('<I',101))
    m.q(m.context+0x388,0)
    for code in range(256):
        m.put(m.context+0x4c0,bytes([code]))
        assert actual(m)['native_result'] is native(m)[0] is (code==1)
    m.put(m.context+0x4c0,b'\0')
    for flags in range(256):
        m.put(m.context+0x4d,bytes([flags]))
        assert actual(m)['native_result'] is native(m)[0] is bool(flags&32)


@pytest.mark.parametrize('same_group',[False,True])
def test_all_settings_codes_and_exact_flag_gates(memory,same_group):
    m=memory
    if same_group:m.put(m.base+0x56d3518,struct.pack('<I',101))
    for code in range(256):
        m.put(m.settings+0x23c,bytes([code]))
        assert actual(m)['native_result'] is native(m)[0] is (code==1)
    m.put(m.settings+0x23c,b'\1')
    for flags in (0,1,32,64,0x10000,0x20000,0x20040,0x80000000,0xffffffff):
        m.put(m.context+0x4c,struct.pack('<I',flags))
        assert actual(m)['native_result'] is native(m)[0] is (same_group or not flags&0x20040)


@pytest.mark.parametrize('value',[-32768,-4,-3,-2,0,32767])
def test_signed_sentinel_blocks_only_different_group(memory,value):
    m=memory;m.put(m.context+0x3b6,struct.pack('<h',value))
    assert actual(m)['native_result'] is native(m)[0] is (value!=-3)
    m.put(m.base+0x56d3518,struct.pack('<I',101))
    assert actual(m)['native_result'] is native(m)[0] is True


def test_null_projection_and_null_group_have_native_meaning(memory):
    m=memory;m.q(m.context+0x138,0);m.put(m.base+0x56d3518,struct.pack('<I',0xffffffff))
    m.put(m.context+0x4c0,b'\1');m.put(m.context+0x4c,struct.pack('<I',0x20040))
    assert actual(m)['native_result'] is native(m)[0] is True
    m.q(m.competition+0xb0,0)
    assert actual(m)['native_result'] is native(m)[0] is False


def test_retained_pointer_and_later_status_gates_preserve_direct_group_branch(memory):
    m=memory;m.q(m.context+0x510,m.settings)
    assert actual(m)['native_result'] is native(m)[0] is False
    m.put(m.base+0x56d3518,struct.pack('<I',101))
    assert actual(m)['native_result'] is native(m)[0] is True


@pytest.mark.parametrize('fault',['code','identity','type','pointer','callback'])
def test_invalid_source_remains_unavailable(memory,fault):
    m=memory;wanted=identity(m,m.competition)
    if fault=='code':m.put(m.base+0xf0f038,b'\0')
    if fault=='identity':wanted=(999,1,1)
    if fault=='type':m.q(m.competition,0)
    if fault=='pointer':m.q(m.competition+0xb0,2)
    with pytest.raises(ValueError):source.evaluate(m.read,m.base,m.competition,wanted,check_current=None if fault=='callback'else lambda:('process','save','build'))


def test_consumed_settings_rechecked_after_last_callback(memory):
    m=memory;calls=[]
    def lifetime():
        calls.append(1)
        if len(calls)==2:m.put(m.settings+0x23c,b'\0')
        return ('process','save','build')
    with pytest.raises(ValueError,match='changed'):actual(m,check_current=lifetime)
