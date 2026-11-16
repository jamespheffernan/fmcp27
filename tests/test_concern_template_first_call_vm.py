"""Local native-code controls; additional template bytes are static fixtures.

The retained record is genuine. These controls do not credit a genuine live
template capture: the additional code bytes come from the installed file.
"""
from pathlib import Path
import importlib.util
import struct
import sys
import pytest
pytest.importorskip('capstone')
from test_player_concern_history_source import Original

H=Path(__file__).resolve().parents[1]/'evidence/social-promises-20261109'
sys.path.insert(0,str(H))
SPEC=importlib.util.spec_from_file_location('concern_first_call_vm_controls',H/'native_concern_template_first_call_vm.py')
VM=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(VM)
import _pinned_build
PLUGIN=_pinned_build.PLUGIN


def static_read(old):
    def read(address,size):
        if address==old.base+0x56a4c20:return(0x700000000000).to_bytes(8,'little')
        with PLUGIN.open('rb')as native:
            native.seek(0x5ed4000+address-old.base);return native.read(size)
    return read


def first_raw(old):
    primary=old.first()['primary_private'];contract=int.from_bytes(old.read(primary+0x2f0,8),'little')
    ring=int.from_bytes(old.read(contract+0x30,8),'little');record=int.from_bytes(old.read(ring+8+9*8,8),'little')
    return old.read(record,28)


def test_original_call_arguments_and_whole_wrapper_prefix_with_real_record_fields():
    old=Original();raw=first_raw(old);result=VM.execute(static_read(old),old.base,raw)
    assert result['branch']=='default_inner_formatter'
    assert result['original_category_callee_executed']is True
    assert result['whole_wrapper_executed']is result['translation_executed']is result['opaque_subject_role_evaluated']is False
    assert result['trace'][8]==0x20a31a8
    assert result['local_stack_write_count']==17


def test_original_flag_override_is_counterfactual_and_not_a_UI_status():
    old=Original();raw=bytearray(first_raw(old));read=static_read(old)
    table=read(old.base+0x539ba90,863);reason=500+table.index(8)
    struct.pack_into('<H',raw,22,reason);raw[27]=128
    result=VM.execute(read,old.base,bytes(raw))
    assert result['branch']=='override_translation_key'and result['translation_id']==714687
    assert result['compiled_reason_category']==8 and result['UI_or_lifecycle_evaluated']is False


@pytest.mark.parametrize('rva',[0x20a3188,0x15472c4,0x154525c,0x539ba90])
def test_argument_call_wrapper_and_category_source_changes_refuse(rva):
    old=Original();read=static_read(old)
    def changed(address,size):
        raw=read(address,size)
        return bytes([raw[0]^1])+raw[1:]if address==old.base+rva else raw
    with pytest.raises(ValueError,match='source changed'):VM.execute(changed,old.base,first_raw(old))


def test_native_translation_context_cannot_alias_private_stack():
    old=Original();raw=bytearray(first_raw(old));read=static_read(old)
    table=read(old.base+0x539ba90,863);struct.pack_into('<H',raw,22,500+table.index(8));raw[27]=128
    def aliased(address,size):
        return(VM.STACK+0x800).to_bytes(8,'little')if address==old.base+0x56a4c20 else read(address,size)
    with pytest.raises(ValueError,match='aliases local VM'):VM.execute(aliased,old.base,bytes(raw))
