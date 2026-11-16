"""Original captured-only VM equivalence and missing-byte refusal in owned RAM."""
import importlib.util
from pathlib import Path

import pytest

from fm_live_mcp import knowledge_club_admission_source as club
from fm_live_mcp import knowledge_club_score_source as score
from fm_live_mcp import knowledge_competition_context_source as competition
from fm_live_mcp import knowledge_context_score as core
from fm_live_mcp import knowledge_context_score_source as context
from fm_live_mcp import knowledge_transfer_predicate as transfer
from fm_live_mcp import knowledge_passing_state as state
from test_knowledge_club_admission_source import memory_fixture,ordinary,full,native
from test_knowledge_complete_recorded import record,row,v

HERE=Path(__file__).resolve().parents[1]/'evidence/knowledge-complete-identity-20261109'
spec=importlib.util.spec_from_file_location('recorded_original',HERE/'original_recorded.py')
vm=importlib.util.module_from_spec(spec);spec.loader.exec_module(vm)


def journal(memory):
    rows=[];start=None;raw=bytearray();last=0
    for address,value in sorted(memory.cells.items()):
        if start is None or address!=last+1 or len(raw)==16384:
            if start is not None:rows.append(row(start,bytes(raw)))
            start=address;raw=bytearray()
        raw.append(value);last=address
    if start is not None:rows.append(row(start,bytes(raw)))
    return v.Journal(record(rows))


def spans():
    guards=club.NATIVE_GUARDS+score.NATIVE_GUARDS+competition.NATIVE_GUARDS+core.NATIVE_GUARDS+context.EXTRA_GUARDS+transfer.NATIVE_GUARDS+state.NATIVE_GUARDS
    return [(a,n)for a,n,_ in guards]+[(a,len(raw))for a,raw in context.aggregate.NATIVE_SPANS]


@pytest.mark.parametrize('combined',[False,True])
@pytest.mark.parametrize('positive',[False,True])
def test_lazy_recorded_vm_matches_original_full_predicate(combined,positive):
    m=memory_fixture(combined);ordinary(m);full(m)
    if positive:m.put(m.personal+0xda4,b'\7')
    expected,trace=native(m)
    observed,reads,writes,replayed=vm.execute(journal(m),m.base,0xe58e5c,[m.club,m.primary,0],spans())
    assert bool(observed)==expected==positive
    assert replayed==trace and reads
    assert all(0x200000000<=a<a+n<=0x200010000 for _,a,n in writes)


def test_missing_operand_in_mapped_page_rejects_original_execution():
    m=memory_fixture();j=journal(m)
    j.excluded.add(m.base+0x56d4951)
    with pytest.raises(ValueError,match='Missing recorded operand'):
        vm.execute(j,m.base,0xe58e5c,[m.club,m.primary,0],spans())
