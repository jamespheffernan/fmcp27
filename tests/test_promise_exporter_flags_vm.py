"""Original exporter-core controls, never genuine game evidence."""
import importlib.util
from pathlib import Path
import struct
import pytest
from unicorn import Uc

H=Path(__file__).resolve().parents[1]/'evidence/social-promises-20261109'
SPEC=importlib.util.spec_from_file_location('exporter_flag_vm_test',H/'native_promise_exporter_flags_vm.py')
VM=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(VM)
import _pinned_build
PLUGIN=_pinned_build.PLUGIN

@pytest.fixture
def operands():
    base,promise,person,primary,context,team=0x100000000,0x200000000,0x300000388,0x300000000,0x400000000,0x500000000
    cells={}
    def put(at,raw):cells.update({at+i:b for i,b in enumerate(raw)})
    def q(at,value):put(at,struct.pack('<Q',value))
    def read(at,size):
        try:return bytes(cells[at+i]for i in range(size))
        except KeyError as error:raise ValueError('Missing literal synthetic flag operand '+hex(error.args[0]))from error
    with PLUGIN.open('rb')as native:
        for rva in (0x2468000,0xd5c000,0x14fc000,0xcff000,0xd00000):
            native.seek(0x5ed4000+rva);put(base+rva,native.read(4096))
    q(promise+0x20,person);q(promise+0x28,context)
    q(person,base+0x558a780);put(person+0xc,struct.pack('<I',123))
    q(base+0x558a780+0x6e0,base+0xd5c610);put(base+0x558a780-0x6f0,struct.pack('<q',-0x388))
    q(primary,base+0x5588ee8);put(base+0x5588ee8-0x20,struct.pack('<q',0x278))
    q(base+0x5588ee8+0x2e8,base+0xcffffc);q(base+0x5588ee8+0x300,base+0xcfff70)
    q(primary+0x2f8,0);put(context+0x2f,b'\0');q(context+0x30,team)
    VM.Uc=Uc
    return dict(base=base,promise=promise,person=person,primary=primary,context=context,team=team,put=put,q=q,read=read,cells=cells)

def run(m):return VM.execute(m['read'],m['base'],m['promise'])

def test_original_no_extra_contract_path_returns_two_false_flags(operands):
    result=run(operands)
    assert result['state']=='complete_original_exporter_flag_core'
    assert result['native_PMlo']is result['native_PMto']is False
    assert result['whole_function_executed']is result['property_setters_executed']is False
    assert 0x14fcab0 in result['trace']and 0xcffffc in result['trace']and 0xcfff70 in result['trace']

@pytest.mark.parametrize('branch',['null_party_B','null_context','virtual_context','null_context_team'])
def test_original_direct_false_flag_branches(operands,branch):
    m=operands
    if branch=='null_party_B':m['q'](m['promise']+0x20,0)
    elif branch=='null_context':m['q'](m['promise']+0x28,0)
    elif branch=='virtual_context':m['put'](m['context']+0x2f,b'\x01')
    else:m['q'](m['context']+0x30,0)
    result=run(m)
    assert result['state']=='complete_original_exporter_flag_core'
    assert result['native_PMlo']is result['native_PMto']is False

@pytest.mark.parametrize('field',['cast_slot','cast_displacement','extra_contract_member','context_byte','original_code'])
def test_missing_original_operand_refuses_no_flag_fallback(operands,field):
    m=operands
    addresses={'cast_slot':m['base']+0x558a780+0x6e0,'cast_displacement':m['base']+0x558a780-0x6f0,'extra_contract_member':m['primary']+0x2f8,'context_byte':m['context']+0x2f,'original_code':m['base']+0x2468000}
    del m['cells'][addresses[field]]
    with pytest.raises(ValueError,match='Missing literal'):run(m)
