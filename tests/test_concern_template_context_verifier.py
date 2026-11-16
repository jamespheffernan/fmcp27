"""New strict context closure on the labelled static carrier fixture."""
import importlib.util
import pytest
pytest.importorskip('capstone')
from test_concern_template_carrier_verifier import carrier_memory,H

SPEC=importlib.util.spec_from_file_location('independent_context_complete_carrier_controls',H/'verify_recorded_concern_template_carriers_context.py')
SOURCE=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(SOURCE)


def test_actual_independent_graph_templates_and_full_context_getters(carrier_memory):
    old,packet,r=carrier_memory;graph=SOURCE.graph(packet,r)
    assert len(SOURCE.template_oracles(packet,r,graph['contexts']))==20
    for context in graph['contexts']:
        domain=SOURCE.hard.Domains(SOURCE.VM,old.base,'concern-context');domain.ret=old.base+SOURCE.VM.RET;SOURCE.VM.Uc=domain.factory
        result=SOURCE.VM.execute(domain.native_reader(r.read),old.base,context['primary']+0x388,context['club'])
        assert result['state']=='complete_original_concern_context_return'and result['native_contract_private']==context['contract']
        assert result['instruction_count']==42


def test_removing_operational_byte_recreates_the_real_refusal(carrier_memory):
    old,packet,r=carrier_memory;context=SOURCE.graph(packet,r)['contexts'][0]
    old.cells.pop(context['club']+0xba)
    domain=SOURCE.hard.Domains(SOURCE.VM,old.base,'concern-context');domain.ret=old.base+SOURCE.VM.RET;SOURCE.VM.Uc=domain.factory
    with pytest.raises(ValueError,match='Missing literal retained'):
        SOURCE.VM.execute(domain.native_reader(r.read),old.base,context['primary']+0x388,context['club'])
