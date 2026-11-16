"""Crossing permitted endpoints against original Range/H; no public mode."""
from _knowledge_stream_fixture import native_stream_transport
import hashlib
import json
import struct

import pytest

from fm_live_mcp import knowledge_crossing_view as source
from test_knowledge_crossing_state import memory as state_memory
from test_knowledge_passing_state import report,low_K,full_subject_contract
from test_knowledge_context_score_source import SyntheticBridge
from _knowledge_state_native import execute


def memory(combined=False):
    m=state_memory(combined);m.blocked=[]
    for rva,n,digest in source.inherited.NATIVE_GUARDS:
        raw=m.disk(rva,n);assert hashlib.sha256(raw).hexdigest()==digest;m.put(m.base+rva,raw)
    for person in(m.person,m.human_person):
        table=int.from_bytes(m.read(person,8),'little');rva=table-m.base
        target=int.from_bytes(m.disk(rva+0x658,8),'little')&0xffffffff
        m.q(table+0x658,m.base+target);m.put(table-0x668,m.disk(rva-0x668,8))
    m.put(m.primary+0x157,b'\x0a');m.put(m.primary+0x270,b'\0')
    m.put(m.common+0x58,struct.pack('<HH',200,2000));m.put(m.base+0x56d4951,b'\0')
    return m


def collect(m,bridge=None):
    return source.collect(bridge or SyntheticBridge(m),'synthetic',subject_person=m.person,
        subject_identity=m.person_ref,coach_name='Private Coach')


@pytest.mark.parametrize('combined',[False,True])
@pytest.mark.parametrize('route',['exact','unknown','range','human_assessor','subject_assessor'])
def test_full_original_crossing_range_H_and_reached_callees(combined,route):
    m=memory(combined);assessment=assessor=0
    if route=='exact':full_subject_contract(m)
    elif route=='unknown':low_K(m)
    else:
        low_K(m)
        assessor=m.human_person if route=='human_assessor'else m.person if route=='subject_assessor'else 0
        assessment=report(m,40,assessor);m.vec(m.human+0x128,[assessment])
    # A Crossing source may never borrow the Passing getter byte.
    m.blocked=[(m.primary+0x15e,m.primary+0x15f)]
    result=collect(m)
    output=m.allocate(8)
    _,raw,reads,writes,trace=execute(m,0x2386eac,[m.record,output,m.primary,11,assessor,assessment,1],
        score_pointer=output,output_width=3,extra=source.inherited.NATIVE_GUARDS+source.state.thresholds.NATIVE_GUARDS)
    lower,upper,_=struct.unpack('bbb',raw)
    expected=({'state':'unknown'}if route=='unknown'else{'state':'exact','value':lower}if route=='exact'
        else{'state':'range','minimum':lower,'maximum':upper})
    assert result['value']==expected
    assert 0x23871f0 in trace and 0xd19eb0 in trace
    assert result['person_ui_caller_evaluated']is False and result['manager_knowledge_verified']is False
    serialized=json.dumps(result)
    assert all(word not in serialized for word in('getter','private_score','rawhex','native_values','primary'))


def test_unknown_is_independent_of_all_256_hidden_crossing_bytes():
    m=memory();low_K(m);m.blocked=[(m.primary+0x148,m.primary+0x18d)]
    for stored in range(256):
        m.put(m.primary+0x157,bytes([stored]))
        assert collect(m)['value']=={'state':'unknown'}


def test_last_callback_hidden_crossing_getter_change_rejects():
    baseline=memory();full_subject_contract(baseline);bridge=SyntheticBridge(baseline);collect(baseline,bridge)
    m=memory();full_subject_contract(m);changed=SyntheticBridge(m)
    def mutate(count):
        if count==bridge.lifetimes:m.put(m.primary+0x157,b'\x0b')
    changed.on_current=mutate
    with pytest.raises(ValueError,match='changed'):collect(m,changed)
    assert changed._reader is None
