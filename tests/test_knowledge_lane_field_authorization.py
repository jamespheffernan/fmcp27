"""Getter grants use fresh H state; swallowed byte failures poison the capture."""
from _knowledge_stream_fixture import native_stream_transport
from io import BytesIO
import importlib.util
from pathlib import Path

import pytest

from test_knowledge_attribute_ui_caller import memory,source
from test_knowledge_passing_state import full_subject_contract,low_K,report
from test_knowledge_context_score_source import SyntheticBridge
from test_knowledge_complete_collector import c

PATH=Path(__file__).resolve().parents[1]/'evidence/knowledge-attribute-fields-20261109/field_authorization.py'
spec=importlib.util.spec_from_file_location('field_authorization',PATH)
auth=importlib.util.module_from_spec(spec);spec.loader.exec_module(auth)


def fixture(route='exact',field=1):
    m=memory()
    if route=='exact':full_subject_contract(m)
    else:
        low_K(m)
        if route=='range':m.vec(m.human+0x128,[report(m,40)])
    bridge=SyntheticBridge(m)
    journal=auth.journal_type(c.Journal,source.AttributeUiCallerSource,source.catalog)(m.read,BytesIO(),bridge)
    journal.forbidden=c.Intervals([(m.primary+0x148,m.primary+0x18d)])
    bridge._read_memory=lambda process,address,size:journal(address,size)
    controlled=auth.source_type(source.AttributeUiCallerSource,journal)
    value=controlled(bridge,'synthetic',m.person,m.person_ref,'Private Coach',field)
    return m,bridge,journal,value


@pytest.mark.parametrize('route',['exact','range'])
def test_authorized_getter_reads_one_byte_only_after_fresh_known_state(route):
    m,bridge,journal,value=fixture(route)
    result=value.permitted();value.verify()
    assert result['state']==route
    assert set(journal.permissions)=={(m.primary+0x148+source.catalog.FIELDS[1][1],1)}
    receipt=journal.authorization_receipts[0]
    assert receipt['native_H_state']==(2 if route=='exact' else 1)
    assert receipt['native_field_id']==1
    assert journal.authorized_attribute_physical_reads>0
    journal.verify(1);journal.verify(2)
    assert journal.record()['no_journal_failure_swallowed']


def test_unknown_never_requests_or_grants_any_attribute_byte():
    m,bridge,journal,value=fixture('unknown')
    assert value.permitted()=={'state':'unknown'}
    value.verify();journal.verify(1);journal.verify(2)
    assert journal.permissions=={} and journal.authorized_attribute_physical_reads==0
    assert journal.record()['field_authorization_receipts']==[]


def test_direct_getter_before_state_refuses_without_read_and_poison_is_permanent():
    m,bridge,journal,value=fixture()
    with pytest.raises(ValueError,match='before a permitted-state'):value.getter()
    assert journal.permissions=={} and journal.authorized_attribute_physical_reads==0
    with pytest.raises(ValueError,match='poisoned'):journal.record()


def test_caller_cannot_forge_known_boolean_when_fresh_H_is_unknown():
    m,bridge,journal,value=fixture('unknown')
    value._latest_decision=(2,0,'forged')
    with pytest.raises(ValueError,match='Fresh native H state'):value.getter()
    assert journal.permissions=={} and journal.authorized_attribute_physical_reads==0


def test_known_getter_grant_does_not_authorize_neighbour_or_attribute_block():
    m,bridge,journal,value=fixture()
    value.permitted()
    at=next(iter(journal.permissions))[0]
    with pytest.raises(ValueError,match='Unpermitted'):journal(at,2)
    assert journal.first_failure is not None


def test_field_metadata_alias_cannot_move_grant_to_a_different_byte():
    m,bridge,journal,value=fixture()
    value.state();value.field_metadata=value.field_metadata|{'primary_offset':0x15e}
    with pytest.raises(ValueError,match='metadata/lifetime'):value.getter()
    assert journal.permissions=={}


def test_transient_changed_byte_cannot_be_swallowed_and_accepted_as_unavailable():
    values=[b'A'];journal=auth.journal_type(c.Journal,source.AttributeUiCallerSource,source.catalog)(lambda a,n:values[0]*n,BytesIO(),None)
    journal(4096,1);values[0]=b'B'
    try:journal(4096,1)
    except ValueError:pass  # Simulate a source mapping an intermediate fault to unavailable.
    values[0]=b'A'
    with pytest.raises(ValueError,match='poisoned'):journal.verify(1)
    with pytest.raises(ValueError,match='poisoned'):journal.record()


def test_conflicting_overlapping_shapes_refuse_even_without_repeating_a_key():
    values=[b'AB']
    journal=auth.journal_type(c.Journal,source.AttributeUiCallerSource,source.catalog)(lambda a,n:values[0][:n],BytesIO(),None)
    journal(4096,2);values[0]=b'Z'
    with pytest.raises(ValueError,match='overlapping read shapes'):journal(4097,1)
    with pytest.raises(ValueError,match='poisoned'):journal.record()


def test_field_bridge_keeps_one_journal_without_physical_recursion():
    from types import SimpleNamespace
    path=PATH.parent/'collect_fields.py'
    spec=importlib.util.spec_from_file_location('field_collector_controls',path)
    collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)
    calls=[]
    class ApiBridge:
        def __init__(self,helper):self.helper=helper
        def _read_memory(self,process,address,size):
            calls.append((process,address,size))
            return b'X'*size
    api=SimpleNamespace(Bridge=ApiBridge)
    journal_class=auth.journal_type(collector.Journal,source.AttributeUiCallerSource,source.catalog)
    bridge=collector.field_bridge(api,None,BytesIO(),journal_class)()
    process=object()
    assert bridge._read_memory(process,4096,4)==b'XXXX'
    assert bridge._read_memory(process,4096,4)==b'XXXX'
    assert len(calls)==2 and bridge.journal.physical_reads==2
    assert len(bridge.journal.observed)==1
    with pytest.raises(ValueError,match='process identity changed'):
        bridge._read_memory(object(),4096,4)
