"""Actual independent functions on labelled static-template fixture additions.

The old raw packet is refused as a genuine template packet. Extra code operands
here are supplied from the installed file, never credited as a live capture.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest
pytest.importorskip('capstone')
from test_player_concern_history_source import Original

H=Path(__file__).resolve().parents[1]/'evidence/social-promises-20261109'
sys.path.insert(0,str(H))
SPEC=importlib.util.spec_from_file_location('independent_template_carrier_verifier_controls',H/'verify_recorded_concern_template_carriers.py')
VERIFIER=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(VERIFIER)
COLLECT_SPEC=importlib.util.spec_from_file_location('template_carrier_projection_for_controls',H/'collect_concern_template_carriers.py')
COLLECT=importlib.util.module_from_spec(COLLECT_SPEC);COLLECT_SPEC.loader.exec_module(COLLECT)
PLUGIN=VERIFIER.PLUGIN


@pytest.fixture
def carrier_memory():
    old=Original();guards=json.loads((H/'concern-template-source-spans.json').read_text())
    with PLUGIN.open('rb')as native:
        for rva,size,digest in guards:
            native.seek(0x5ed4000+rva);raw=native.read(size)
            for offset,value in enumerate(raw):
                if old.base+rva+offset in old.cells:assert old.cells[old.base+rva+offset]==value
            old.put(old.base+rva,raw)
    old.put(old.base+0x56a4c20,(0x700000000000).to_bytes(8,'little'))
    packet=deepcopy(old.packet);packet['players']=[packet['players'][0],packet['players'][7]]
    packet['observed_native_ring_entries']=20;packet['available_context_owner_count']=2
    packet['unavailable_context_owner_count']=0;packet['nonempty_native_history_owners']=2
    packet['source_before']['evidence_sources']['concern-template-source-spans.json']=dict(utf8=(H/'concern-template-source-spans.json').read_text())
    for row in packet['players']:row['unrendered_templates']=COLLECT.unrendered_templates(old.read,old.base,row['concern_history'])
    packet['known_unrendered_templates']=sum(entry['compiled_unrendered_template']['translation_id']is not None for row in packet['players']for entry in row['unrendered_templates'])
    r=SimpleNamespace(read=old.read,u64=lambda address:int.from_bytes(old.read(address,8),'little'),i64=lambda address:int.from_bytes(old.read(address,8),'little',signed=True))
    return old,packet,r


def test_real_independent_selected_graph_and_native_wrapper_first_keys(carrier_memory):
    old,packet,r=carrier_memory;graph=VERIFIER.graph(packet,r)
    assert graph['entries']==20 and graph['available']==2
    rows=VERIFIER.template_oracles(packet,r,graph['contexts'])
    assert len(rows)==20 and any(row['translation_id']is not None for row in rows)
    assert{row['name']for row in rows}=={'Anthony Gordon','Lewis Miley'}
    assert all(row['wrapper_original']['original_category_callee_executed']for row in rows)
    assert all(row['wrapper_original']['translation_executed']is False for row in rows)


@pytest.mark.parametrize('rva',[0x20a3188,0x15472c4,0x539b3be])
def test_missing_literal_template_source_cannot_become_an_unknown_or_empty_success(carrier_memory,rva):
    old,packet,r=carrier_memory;graph=VERIFIER.graph(packet,r);old.cells.pop(old.base+rva)
    with pytest.raises(ValueError,match='Missing literal retained'):
        VERIFIER.template_oracles(packet,r,graph['contexts'])


def test_wrong_template_words_refuse_even_when_reason_and_key_match(carrier_memory):
    old,packet,r=carrier_memory;graph=VERIFIER.graph(packet,r)
    first=next(entry for row in packet['players']for entry in row['unrendered_templates']if entry['compiled_unrendered_template']['translation_id']is not None)
    first['compiled_unrendered_template']['english_template']='A guessed current status'
    with pytest.raises(AssertionError):VERIFIER.template_oracles(packet,r,graph['contexts'])


def test_context_sensitive_record_is_deliberately_unknown_despite_supplied_raw_fields(carrier_memory):
    old,packet,r=carrier_memory;first=packet['players'][0]
    contract=r.u64(first['primary_private']+0x2f0);ring=r.u64(contract+0x30);record=r.u64(ring+8+9*8)
    old.put(record+22,(649).to_bytes(2,'little'))
    first['concern_history']=COLLECT.CANDIDATE.inspect(old.read,old.base,first['primary_private'],'actual',include_stored_name=True)
    first['unrendered_templates']=COLLECT.unrendered_templates(old.read,old.base,first['concern_history'])
    packet['known_unrendered_templates']=sum(entry['compiled_unrendered_template']['translation_id']is not None for row in packet['players']for entry in row['unrendered_templates'])
    graph=VERIFIER.graph(packet,r);result=VERIFIER.template_oracles(packet,r,graph['contexts'])
    assert result[0]['native_reason_code']==649 and result[0]['translation_id']is None
    assert result[0]['state']=='unknown_context_controls_first_key_branch'


def test_old_raw_packet_never_gets_new_template_capture_credit():
    with pytest.raises(AssertionError):VERIFIER.pins(Original().packet)


def test_unrelated_named_owner_is_refused_by_actual_independent_graph(carrier_memory):
    old,packet,r=carrier_memory
    packet['players'][0]['concern_history']['owner']=deepcopy(packet['players'][1]['concern_history']['owner'])
    with pytest.raises(AssertionError):VERIFIER.graph(packet,r)
