"""Original empty selection core only; no full helper/lifecycle claim."""
import importlib.util
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
P=ROOT/'evidence/social-promises-20261109/native_promise_selector_vm.py'
spec=importlib.util.spec_from_file_location('native_selector',P);vm=importlib.util.module_from_spec(spec);spec.loader.exec_module(vm)
import _pinned_build
PLUGIN=_pinned_build.PLUGIN
BASE,RECORD=0x100000000,0x200000000


def original_source():
    cells={}
    with PLUGIN.open('rb')as stream:
        for page in [0x2469000,0x246a000]:
            stream.seek(0x5ed4000+page)
            for i,value in enumerate(stream.read(4096)):cells[BASE+page+i]=value
    def read(address,size):
        try:return bytes(cells[address+i]for i in range(size))
        except KeyError as error:raise ValueError('Missing synthetic selector operand')from error
    return read,cells


def test_empty_original_loop_produces_false_before_cleanup_without_stubs():
    read,_=original_source();result=vm.execute(read,BASE,RECORD,[])
    assert result['state']=='complete_original_selection_core'
    assert result['native_selection_result']==0
    assert result['whole_function_executed']is result['vector_cleanup_executed']is result['full_override_executed']is result['callee_stubs']is False


@pytest.mark.parametrize('bad',[None,(),[0],[True],[1<<64],[vm.CORE_SP],[0x300000]*121])
def test_invalid_or_oversized_native_query_output_refuses(bad):
    with pytest.raises(ValueError,match='event sequence'):vm.execute(None,BASE,RECORD,bad)


def test_missing_original_instruction_does_not_become_zero():
    read,cells=original_source();cells.pop(BASE+0x2469f70)
    with pytest.raises(ValueError,match='Missing synthetic'):vm.execute(read,BASE,RECORD,[])
