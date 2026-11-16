"""Re-extract all fields through original native dispatch, no live process."""
from _knowledge_stream_fixture import native_stream_transport
import hashlib

import pytest
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X19,UC_ARM64_REG_X21,UC_ARM64_REG_X22,UC_ARM64_REG_X23,UC_ARM64_REG_PC,UC_ARM64_REG_X30

from fm_live_mcp import knowledge_field_catalog as catalog,players,player_profile
from test_individual_training_focus import native_image,SLICE


def test_all_names_and_offsets_match_original_name_dispatch_and_getter_table(native_image):
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    pages=(0x1567000,0x1568000,0x539d000,0x5404000,0x4acf000,0x700000000000)
    for page in pages:
        u.mem_map(page,4096)
        if page!=0x700000000000:u.mem_write(page,native_image[SLICE+page:SLICE+page+4096])
    def code(vm,address,n,data):
        if address==0x1568844:vm.emu_stop()
    u.hook_add(UC_HOOK_CODE,code)
    for field in range(47):
        u.reg_write(UC_ARM64_REG_X23,field);u.reg_write(UC_ARM64_REG_X22,2)
        u.reg_write(UC_ARM64_REG_X21,1);u.reg_write(UC_ARM64_REG_X19,0)
        u.reg_write(UC_ARM64_REG_X1,0)
        u.emu_start(0x1567ee0,0,count=50)
        assert u.reg_read(UC_ARM64_REG_PC)==0x1568844
        at=u.reg_read(UC_ARM64_REG_X1)
        name=native_image[SLICE+at:SLICE+at+128].split(b'\0',1)[0].decode('ascii')
        u.reg_write(UC_ARM64_REG_X0,field);u.reg_write(UC_ARM64_REG_X30,0x700000000000)
        u.emu_start(0x4acf834,0x700000000000,count=20)
        assert u.reg_read(UC_ARM64_REG_PC)==0x700000000000
        offset=u.reg_read(UC_ARM64_REG_X0)
        actual=catalog.field(field)
        assert actual==dict(native_field_id=field,compiled_name=name,stored_offset=offset,
                            primary_offset=0x148+offset,field_visibility_evaluated=False)
    assert len(set(n for n,_,_ in catalog.FIELDS))==47
    assert len(set(o for _,o,_ in catalog.FIELDS))==47
    assert {o for _,o,_ in catalog.FIELDS}==set(players.ATTRIBUTES.values())|{a-0x148 for a,_,_ in player_profile.GOALKEEPING.values()}


def test_guard_pins_code_tables_and_each_exact_name_without_player_values(native_image):
    def read(at,n):return native_image[SLICE+at:SLICE+at+n]
    catalog.verify_native(read,0)
    for a,n,digest in catalog.NATIVE_GUARDS:
        assert hashlib.sha256(read(a,n)).hexdigest()==digest
    for bad in (catalog.NATIVE_GUARDS[0][0],catalog.FIELDS[18][2]):
        def changed(at,n):
            raw=read(at,n)
            return bytes([raw[0]^1])+raw[1:] if at==bad else raw
        with pytest.raises(ValueError,match='changed'):catalog.verify_native(changed,0)


@pytest.mark.parametrize('invalid',[-1,47,255,True,None,'18',18.0])
def test_invalid_field_ids_do_not_alias_other_attributes(invalid):
    with pytest.raises(ValueError):catalog.field(invalid)


def test_caller_cannot_mutate_catalog_by_editing_returned_metadata():
    value=catalog.field(18);value['stored_offset']=0
    assert catalog.field(18)['compiled_name']=='Passing'
    assert catalog.field(18)['stored_offset']==0x16
