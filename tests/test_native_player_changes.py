"""Typed change decoding and original exact on/off-slot selector controls."""
import hashlib,struct
import pytest
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X19,UC_ARM64_REG_X24,UC_ARM64_REG_X26,UC_ARM64_REG_X27,UC_ARM64_REG_PC
from fm_live_mcp import native_player_changes as changes
from test_frame_attack_direction import PLUGIN,Source
BASE,ENGINE,ARRAY,SUB,PUT,SIDE,PLAYERS=(0x100000000,0x30000000,0x31000000,0x32000000,0x33000000,0x34000000,0x35000000)


@pytest.fixture(scope='module')
def native():
    with PLUGIN.open('rb') as f:
        assert hashlib.file_digest(f,'sha256').hexdigest()=='774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
        for at,raw in changes.NATIVE_SPANS:f.seek(0x5ED4000+at);assert f.read(len(raw))==raw
    return dict(changes.NATIVE_SPANS)


def source(native):
    obj=Source.__new__(Source);obj.values={};obj.reads=[]
    for at,raw in native.items():obj.put(BASE+at,raw)
    for i,(address,table,name) in enumerate([(ENGINE,0x55FA258,b'10GAME_MATCH'),(SUB,0x569F7E0,b'N7simatch26SUBSTITUTION_TACTIC_CHANGEE'),(PUT,0x569F628,b'N7simatch13PLAYER_PUT_ONE')]):
        info,text=0x36000000+4096*i,0x37000000+4096*i
        obj.put(address,struct.pack('<Q',BASE+table));obj.put(BASE+table-16,struct.pack('<qQ',0,info));obj.put(info+8,struct.pack('<Q',text));obj.put(text,name+b'\0')
    for table,(_,_,apply,_) in changes.TYPES.items():obj.put(BASE+table+0x20,struct.pack('<Q',BASE+apply))
    obj.put(ENGINE+0x20,struct.pack('<Q',123));obj.put(ENGINE+0x147F0,struct.pack('<3Q',ARRAY,ARRAY+24,ARRAY+24))
    obj.put(ARRAY,struct.pack('<3Q',SUB,PUT,0))
    obj.put(SUB+8,struct.pack('<iHbbb',100,4<<8,1,13,2))
    obj.put(PUT+8,struct.pack('<iHbbb',-1,22<<8,0,8,4))
    obj.bound={'source_match_address':ENGINE,'official_match_unique_id':123}
    return obj


def test_typed_on_off_slots_native_clock_and_sentinel_unavailable(native):
    obj=source(native);captured=changes.capture(obj.read,BASE,obj.bound);sub,put,null=captured['rows']
    assert (sub['kind'],sub['side_index'],sub['native_change_tick'],sub['player_on_original_slot'],sub['player_off_original_slot'])==('SUBSTITUTION',1,100,13,2)
    assert put['kind']=='PLAYER_PUT_ON' and put['player_on_original_slot']==8 and put['formation_index_raw']==4
    assert put['native_change_tick'] is put['player_off_original_slot'] is None
    assert put['state']=='typed_original_slot_change_clock_unavailable'
    assert null['state']=='unavailable_null_change_object'
    assert captured['history_complete'] is None and captured['pending_vs_executed_verified'] is captured['fixed_frame_participation_verified'] is False
    assert changes.verify_capture(obj.read,BASE,obj.bound,captured)['native_change_source_physically_reselected'] is True


@pytest.mark.parametrize('on,off',[(0,25),(25,0),(13,2)])
def test_original_complete_slot_getters_and_exact_selector_window(native,on,off):
    uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    required={at:raw for at,raw in native.items() if at in (0x4A7AA5C,0x16C16E0)}
    for page in {BASE+(at&~4095) for at in required}|{SUB,SIDE}:uc.mem_map(page,4096)
    for at,raw in required.items():uc.mem_write(BASE+at,raw)
    uc.mem_write(SUB+0xF,bytes([on,off]));uc.mem_write(SIDE+0x140,struct.pack('<26Q',*(PLAYERS+i*4096 for i in range(26))))
    def rd(machine,kind,address,size,value,extra):assert (SUB+0xF<=address and address+size<=SUB+0x11) or (SIDE+0x140<=address and address+size<=SIDE+0x210)
    def wr(*args):raise AssertionError('Original slot selector unexpectedly writes')
    uc.hook_add(UC_HOOK_MEM_READ,rd);uc.hook_add(UC_HOOK_MEM_WRITE,wr)
    uc.reg_write(UC_ARM64_REG_X26,SIDE);uc.reg_write(UC_ARM64_REG_X27,SUB)
    uc.emu_start(BASE+0x4A7AA5C,BASE+0x4A7AA78,count=30);assert uc.reg_read(UC_ARM64_REG_PC)==BASE+0x4A7AA78
    assert uc.reg_read(UC_ARM64_REG_X19)==PLAYERS+off*4096 and uc.reg_read(UC_ARM64_REG_X24)==PLAYERS+on*4096


@pytest.mark.parametrize('side,on,off',[(-1,13,2),(2,13,2),(0,-1,2),(0,26,2),(1,13,-1),(1,13,26)])
def test_unmatched_typed_sides_and_slots_do_not_publish_matched_facts(native,side,on,off):
    obj=source(native);obj.put(SUB+14,struct.pack('<3b',side,on,off));row=changes.capture(obj.read,BASE,obj.bound)['rows'][0]
    assert row['state']=='unavailable_typed_change_side_or_original_slot'
    assert row['side_index'] is row['player_on_original_slot'] is row['player_off_original_slot'] is row['native_change_tick'] is None


def test_unknown_type_preserves_unknown_without_reading_generic_fields(native):
    obj=source(native);obj.put(SUB,struct.pack('<Q',BASE+0x123456));result=changes.capture(obj.read,BASE,obj.bound)
    assert result['rows'][0]['state']=='unavailable_unclassified_native_change_type'
    assert all(address!=SUB+8 and address!=SUB+14 for address,n in obj.reads)


def test_fixture_drift_final_mutation_and_source_guards_refuse(native):
    obj=source(native);captured=changes.capture(obj.read,BASE,obj.bound)
    obj.put(SUB+8,struct.pack('<i',101))
    with pytest.raises(ValueError,match='storage changed'):changes.verify_capture(obj.read,BASE,obj.bound,captured)
    obj.put(ENGINE+0x20,struct.pack('<Q',124))
    with pytest.raises(ValueError,match='fixture identity'):changes.capture(obj.read,BASE,obj.bound)
    at=next(iter(native));obj.values[BASE+at]^=1
    with pytest.raises(ValueError,match='source changed'):changes.capture(obj.read,BASE,obj.bound)


def test_empty_and_budget_unavailable_are_distinct(native):
    obj=source(native);obj.put(ENGINE+0x147F0,bytes(24))
    assert changes.capture(obj.read,BASE,obj.bound)['rows']==[]
    obj.put(ENGINE+0x147F0,struct.pack('<3Q',ARRAY,ARRAY+8*4097,ARRAY+8*4097))
    assert changes.capture(obj.read,BASE,obj.bound)['rows'] is None
