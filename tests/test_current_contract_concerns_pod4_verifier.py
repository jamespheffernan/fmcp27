"""Actual independent graph and original consumer with qualified POD4 rows."""
from copy import deepcopy
import importlib.util
import struct
import pytest
pytest.importorskip('capstone')
from test_current_contract_concerns_recorded_verifier import (verifier_memory,concern_memory,agreed_memory,public_assessment_memory,
    shortlist_public_memory,prepared_tactics_memory,bridge,database_memory,memory,team_memory,world_memory,H,PLUGIN)
from test_current_contract_concerns_pod4 import NEW,single


@pytest.fixture
def qualified_verifier_memory(verifier_memory):
    m,old,packet,r=verifier_memory
    with PLUGIN.open('rb')as native:
        for rva,size,digest in NEW.SOURCE:
            native.seek(0x5ed4000+rva);m['put'](m['base']+rva,native.read(size))
    record=m['allocate'](64)+4;assert record%8==4;single(m,record)
    history=NEW.inspect(m['read'],m['base'],m['concern_primary'],'actual',include_stored_name=True)
    packet=deepcopy(packet);packet['players'][0]['concern_history']=history;packet['observed_native_ring_entries']=1
    packet['source_before']['evidence_sources']={'concern-pod4-source-spans.json':dict(utf8=(H/'concern-pod4-source-spans.json').read_text())}
    spec=importlib.util.spec_from_file_location('independent_concern_pod4_verifier_test',H/'verify_recorded_current_contract_concerns_pod4.py')
    verifier=importlib.util.module_from_spec(spec);spec.loader.exec_module(verifier)
    return m,verifier,packet,r,record


def test_actual_independent_graph_and_original_rule_accept_4mod8_record(qualified_verifier_memory):
    m,verifier,packet,r,record=qualified_verifier_memory
    result=verifier.graph(packet,r)
    assert result['nonnull_records']==result['entries']==1
    assert result['first_named_nonnull_record']['name']=='Test Müller'
    assert verifier.context_replay(packet,r,result['contexts'])['native_contract_private']==m['agreed_contract']
    native=verifier.original_open_filter(r,m['base'],result['contexts'][0])
    assert native['raw_rule_result_before_cleanup']==1
    assert any(record<=address<record+28 for address,size in native['operand_reads'])


@pytest.mark.parametrize('increment',[1,2,3])
def test_independent_verifier_rejects_non_pod4_record_addresses(qualified_verifier_memory,increment):
    m,verifier,packet,r,record=qualified_verifier_memory;m['q'](m['concern_ring']+8,record+increment)
    with pytest.raises(AssertionError):verifier.graph(packet,r)


def test_independent_verifier_refuses_changed_stride_qualifier(qualified_verifier_memory):
    m,verifier,packet,r,record=qualified_verifier_memory;m['put'](m['base']+0xfedd88,b'\0'*4)
    with pytest.raises(AssertionError):verifier.graph(packet,r)


def test_independent_verifier_retains_owner_binding(qualified_verifier_memory):
    m,verifier,packet,r,record=qualified_verifier_memory;m['q'](m['agreed_contract']+8,m['manager']+0x548)
    with pytest.raises(AssertionError):verifier.graph(packet,r)
