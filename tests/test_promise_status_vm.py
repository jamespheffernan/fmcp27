"""Original-code VM controls over explicitly synthetic inputs, never live proof."""
import importlib.util
import hashlib
import json
from pathlib import Path
import struct
import pytest

P=Path(__file__).resolve().parents[1]/'evidence/social-promises-20261109/native_status_vm.py'
spec=importlib.util.spec_from_file_location('promise_status_vm',P);vm=importlib.util.module_from_spec(spec);spec.loader.exec_module(vm)
import _pinned_build
PLUGIN=_pinned_build.PLUGIN
BASE,RECORD,GUARD=0x100000000,0x200000000,0x200020000

class Source:
    def __init__(self):
        self.cells={};self.calls=[]
        with PLUGIN.open('rb')as stream:
            for page in range(0x246a000,0x246e000,4096):
                stream.seek(0x5ed4000+page);self.write(BASE+page,stream.read(4096))
        self.write(RECORD,b'\0'*0x60)
        self.write(BASE+0x54b05b0,struct.pack('<Q',GUARD))
        self.write(GUARD,struct.pack('<Q',0x1122334455667788))
    def write(self,at,raw):
        for i,value in enumerate(raw):self.cells[at+i]=value
    def read(self,at,size):
        self.calls.append((at,size))
        try:return bytes(self.cells[at+i]for i in range(size))
        except KeyError as error:raise ValueError('Unprovided synthetic operand')from error


def test_full_original_entry_null_subject_branch_returns_without_stubs_or_heap_writes():
    source=Source();result=vm.execute(source.read,BASE,RECORD)
    assert result['state']=='complete_original_status_predicate_return'
    assert result['native_return']==8 and result['native_output_flag']==0
    assert result['trace'][0]==0x246a250 and result['trace'][-1]==0x246dea8
    assert result['callee_stubs']is result['non_stack_writes']is result['game_calls']is False
    assert any(at==BASE+0x54b05b0 for at,size in source.calls)
    assert source.read(RECORD,0x60)==b'\0'*0x60


def test_unknown_native_data_never_uses_zero_fill():
    source=Source();source.cells.pop(GUARD)
    with pytest.raises(ValueError,match='Unprovided synthetic operand'):vm.execute(source.read,BASE,RECORD)


def test_unknown_native_instruction_never_uses_zero_fill():
    source=Source();source.cells.pop(BASE+0x246a250)
    with pytest.raises(ValueError,match='Unprovided synthetic operand'):vm.execute(source.read,BASE,RECORD)


def test_altered_control_nonstack_write_is_refused_before_any_native_result():
    source=Source();source.write(BASE+0x246a250,struct.pack('<I',0x3900001f))
    result=vm.execute(source.read,BASE,RECORD)
    assert result['state']=='unsupported_original_status_path'
    assert 'non-stack write' in result['reason']
    assert result['native_return']is None and source.read(RECORD,0x60)==b'\0'*0x60


def test_altered_control_external_branch_is_refused_without_a_callee_stub():
    source=Source();delta=vm.TEXT_END-0x246a250;word=0x14000000|((delta>>2)&0x3ffffff)
    source.write(BASE+0x246a250,struct.pack('<I',word));result=vm.execute(source.read,BASE,RECORD)
    assert result['state']=='unsupported_original_status_path'and 'External original callee'in result['reason']
    assert result['native_return']is None


def test_instruction_budget_does_not_publish_a_partial_return():
    source=Source();result=vm.execute(source.read,BASE,RECORD,instruction_limit=1)
    assert result['state']=='unsupported_original_status_path'and result['native_return']is None
    assert 'budget'in result['reason']


def test_captured_source_cannot_introduce_a_fake_pointer_into_owned_vm_stack():
    source=Source();source.write(RECORD+0x20,struct.pack('<Q',vm.STACK+0x1000))
    result=vm.execute(source.read,BASE,RECORD)
    assert result['state']=='unsupported_original_status_path'and result['native_return']is None
    assert 'reserved host VM'in result['reason']


def test_uninitialized_vm_stack_cannot_supply_zero_filled_operands():
    source=Source();source.write(BASE+0x246a250,struct.pack('<I',0xf94003e8))
    result=vm.execute(source.read,BASE,RECORD)
    assert result['state']=='unsupported_original_status_path'
    assert 'uninitialized host VM stack'in result['reason']
    assert result['native_return']is None


@pytest.mark.parametrize('base,promise',[(BASE,vm.STACK),(vm.STACK,RECORD),(1<<64,RECORD),(BASE,1<<64)])
def test_invalid_or_reserved_binding_rejects_before_provider_reads(base,promise):
    source=Source();source.calls.clear()
    with pytest.raises(ValueError,match='binding'):vm.execute(source.read,base,promise)
    assert source.calls==[]


@pytest.mark.parametrize('word,reason',[
    (0xd53bd042,'system instruction'), # MRS TPIDR_EL0
    (0xd51bd042,'system instruction'), # MSR TPIDR_EL0
    (0xd53b4402,'system instruction'), # MRS FPCR
    (0xd50342df,'system instruction'), # MSR DAIFSet immediate
    (0xd50b7b20,'system instruction'), # SYS DC CVAU
    (0xd503205f,'system instruction'), # WFE
    (0xd503233f,'system instruction'), # PACIASP
    (0xd4000001,'exception instruction'), # SVC
    (0xd69f03e0,'authenticated/exception branch'), # ERET
    (0xdac10002,'pointer-authentication/tag'), # PACIA
    (0x9ac01002,'pointer-authentication/tag'), # IRG
    (0xf8200402,'pointer-authentication/tag'), # LDRAA
    (0x1e202802,'floating/SIMD FPCR'), # FADD
    (0x1e220002,'floating/SIMD FPCR'), # SCVTF
    (0x54000020,'NZCV condition/carry'), # B.EQ
    (0x9a020042,'NZCV condition/carry'), # ADC
    (0x04bf5022,'reserved/SVE/SME'), # RDVL
])
def test_uncaptured_architectural_state_never_uses_cpu_reset_defaults(word,reason):
    source=Source()
    # Replace the non-taken output-null branch; the stack/return path is intact.
    source.write(BASE+0x246a28c,struct.pack('<I',word))
    result=vm.execute(source.read,BASE,RECORD)
    assert result['state']=='unsupported_original_status_path'
    assert reason in result['reason']and result['native_return']is None


@pytest.mark.parametrize('word',[0xd503201f,0xd5033b9f,0xd5033bbf,0xd5033fdf])
def test_explicit_nop_and_memory_barriers_need_no_uncaptured_value(word):
    assert vm.architectural_state(word,False)==(None,False)


def test_implicit_flags_are_unknown_until_original_code_defines_them():
    assert 'NZCV'in vm.architectural_state(0x54000020,False)[0]
    assert vm.architectural_state(0x7100041f,False)==(None,True) # CMP W0,1
    assert vm.architectural_state(0x54000020,True)==(None,True)


def test_finite_integer_simd_policy_is_literal_pinned_original_words_only():
    proof=json.loads(P.with_name('status-simd-policy-proof.json').read_text())
    assert vm.SAFE_SIMD_WORDS=={int(word,16)for word in proof['allowed_words']}
    original=set()
    with PLUGIN.open('rb')as stream:
        for rva,size,digest in proof['source_spans']:
            stream.seek(0x5ed4000+rva);raw=stream.read(size)
            assert hashlib.sha256(raw).hexdigest()==digest
            original.update(word[0]for word in struct.iter_unpack('<I',raw))
    assert vm.SAFE_SIMD_WORDS<=original
    assert all(vm.architectural_state(word,True)==(None,True)for word in vm.SAFE_SIMD_WORDS)
    assert all(row['mnemonic']in proof['allowed_mnemonics']for row in proof['allowed_examples'])


@pytest.mark.parametrize('limit',[None,True,False,0,-1,1000001])
def test_invalid_instruction_budgets_refuse_before_provider_reads(limit):
    source=Source();source.calls.clear()
    with pytest.raises(ValueError,match='instruction bound'):vm.execute(source.read,BASE,RECORD,instruction_limit=limit)
    assert source.calls==[]
