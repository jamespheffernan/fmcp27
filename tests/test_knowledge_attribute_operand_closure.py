"""All reached original operands must be captured by the typed field source."""
from _knowledge_stream_fixture import native_stream_transport
import struct

import pytest

from test_knowledge_attribute_ui_caller import memory,source
from test_knowledge_passing_state import full_subject_contract,low_K,report
from test_knowledge_context_score_source import SyntheticBridge
from test_knowledge_person_ui_caller import native_ui_selection
from _knowledge_state_native import execute


@pytest.mark.parametrize('field',range(47))
@pytest.mark.parametrize('route',['exact','unknown','range'])
def test_all_original_reached_field_operands_are_in_source_consumed_bytes(field,route):
    m=memory();assessment=0
    if route=='exact':full_subject_contract(m)
    else:
        low_K(m)
        if route=='range':assessment=report(m,40);m.vec(m.human+0x128,[assessment])
    if route=='unknown':m.blocked=[(m.primary+0x148,m.primary+0x18d)]
    m.reads.clear()
    result=source.collect(SyntheticBridge(m),'synthetic',subject_person=m.person,
        subject_identity=m.person_ref,field=field,coach_name='Private Coach')
    consumed={a+i for a,n in m.reads for i in range(n)}
    selected,assessor,ui_reads,_=native_ui_selection(m)
    assert selected==assessment
    assert all(a+i in consumed for a,n in ui_reads for i in range(n))
    output=m.allocate(8)
    extra=(source.inherited.NATIVE_GUARDS+source.inherited.inherited.NATIVE_GUARDS+
        source.inherited.inherited.inherited.view.NATIVE_GUARDS+source.native_thresholds.NATIVE_GUARDS)
    _,raw,native_reads,_,_=execute(m,0x2386eac,[m.record,output,m.primary,field,assessor,selected,1],
        score_pointer=output,output_width=3,extra=extra)
    missing=[]
    for a,n in native_reads:
        for address in range(a,a+n):
            if route=='unknown'and(m.primary+0x148<=address<m.primary+0x18d or address==m.primary+0x270):continue
            if address not in consumed:missing.append(hex(address))
    assert not missing,missing
