"""Official event bytes/count/copy controls, not lineup reconstruction."""
import hashlib
import struct

import pytest
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_LR,UC_ARM64_REG_PC
from fm_live_mcp import playback_event_source as events
from test_frame_attack_direction import PLUGIN,Source

BASE,PLAYBACK,PROVIDER,ENGINE,BUFFER,OUTPUT,DESC,STOP=(0x100000000,0x30000000,0x31000000,0x32000000,0x33000000,0x34000000,0x35000000,0x90000000)


@pytest.fixture(scope='module')
def native():
    with PLUGIN.open('rb') as f:
        assert hashlib.file_digest(f,'sha256').hexdigest()=='774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
        for at,expected in events.NATIVE_SPANS:
            f.seek(0x5ED4000+at);assert f.read(len(expected))==expected
    return dict(events.NATIVE_SPANS)


def source(native,count=3,consumed=0):
    obj=Source.__new__(Source);obj.values={};obj.reads=[]
    for at,raw in native.items():obj.put(BASE+at,raw)
    obj.bound={'playback_address':PLAYBACK,'frame_provider_address':PROVIDER,
        'source_match_address':ENGINE,'official_match_unique_id':123,'local_playback_handle':456}
    for address,value in [(BASE+0x54EC490+0xE0,BASE+0x73DA90),(PLAYBACK,BASE+0x54EC490),
        (PLAYBACK+0x10,PLAYBACK),(PLAYBACK+0x18,456),(PLAYBACK+0x1408,PROVIDER),
        (PROVIDER+0x28,ENGINE),(ENGINE+0x20,123)]:obj.put(address,struct.pack('<Q',value))
    obj.put(PLAYBACK+0x1418,struct.pack('<5Q',consumed,0,BUFFER,BUFFER+44*count,BUFFER+44*count))
    obj.put(PLAYBACK+0x1CE8,b'\x01') # Native update tactical-change byte, collector never writes it.
    raw=bytes((i*37)%256 for i in range(44*count))
    obj.put(BUFFER,raw)
    return obj,raw


def original(obj,at,output_size=4096):
    uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    for page in {a&~4095 for a in obj.values}|{OUTPUT,DESC,STOP}:uc.mem_map(page,4096)
    for address,value in obj.values.items():uc.mem_write(address,bytes([value]))
    uc.mem_write(DESC,struct.pack('<Q',OUTPUT))
    def rd(machine,kind,address,size,value,extra):
        if DESC<=address and address+size<=DESC+8:return
        assert bytes(machine.mem_read(address,size))==bytes(obj.values[address+i] for i in range(size))
    def wr(machine,kind,address,size,value,extra):
        assert (OUTPUT<=address and address+size<=OUTPUT+output_size) or (address,size) in [(PLAYBACK+0x1418,8),(PLAYBACK+0x1CE8,1)]
    uc.hook_add(UC_HOOK_MEM_READ,rd);uc.hook_add(UC_HOOK_MEM_WRITE,wr)
    for reg,value in [(UC_ARM64_REG_X0,PLAYBACK+0x1418),(UC_ARM64_REG_X1,DESC),(UC_ARM64_REG_LR,STOP)]:uc.reg_write(reg,value)
    uc.emu_start(BASE+at,STOP,count=300)
    assert uc.reg_read(UC_ARM64_REG_PC)==STOP
    return uc.reg_read(UC_ARM64_REG_X0),bytes(uc.mem_read(OUTPUT,output_size))


@pytest.mark.parametrize('count,consumed',[(0,0),(1,0),(3,0),(3,1),(3,3),(8,2)])
def test_complete_original_count_and_full_update_copy_preserve_exact44bytes(native,count,consumed):
    obj,raw=source(native,count,consumed)
    assert original(obj,0x73F1D8)[0]==count
    returned,copied=original(obj,0x73F43C)
    assert returned&0xFFFFFFFF==consumed and returned>>32==1
    assert copied[:44*(count-consumed)]==raw[44*consumed:]
    captured=events.capture(obj.read,BASE,obj.bound)
    assert len(captured['rows'])==count
    for i,row in enumerate(captured['rows']):
        item=raw[i*44:(i+1)*44]
        assert row['player_ids_raw']==list(struct.unpack_from('<6I',item))
        assert row['player_teams_bits_raw']==item[24]
        assert row['commentary_event_raw']==struct.unpack_from('<H',item,26)[0]
        assert row['time_slice_raw']==struct.unpack_from('<I',item,28)[0]
        assert row['duration_time_slices_raw']==struct.unpack_from('<I',item,32)[0]
        assert row['flags_raw']==item[36] and row['data1_raw']==struct.unpack_from('<I',item,40)[0]
    projected=events.project(events.verify_capture(obj.read,BASE,captured,obj.bound))
    assert projected['on_pitch_population_verified'] is False and projected['history_complete'] is None
    assert not any(n.startswith('_') for n in projected)


def test_zero_and_unknown_fields_are_preserved(native):
    obj,_=source(native,1);obj.put(BUFFER,bytes(44))
    row=events.capture(obj.read,BASE,obj.bound)['rows'][0]
    assert row['player_ids_raw']==[0]*6 and row['time_slice_raw']==0
    obj.put(BUFFER+26,b'\xff\xff')
    assert events.capture(obj.read,BASE,obj.bound)['rows'][0]['commentary_event_raw']==65535


def test_null_storage_empty_is_distinct_from_budget_unavailable(native):
    obj,_=source(native);obj.put(PLAYBACK+0x1418,bytes(40))
    assert events.capture(obj.read,BASE,obj.bound)['state']=='available_empty_native_storage'
    obj.put(PLAYBACK+0x1418,struct.pack('<5Q',0,0,BUFFER,BUFFER+44*8193,BUFFER+44*8193))
    result=events.capture(obj.read,BASE,obj.bound)
    assert result['state']=='unavailable_native_event_budget' and result['rows'] is None
    assert all(address!=BUFFER for address,_ in obj.reads)


@pytest.mark.parametrize('words',[(0,0,BUFFER,BUFFER+1,BUFFER+44),(4,0,BUFFER,BUFFER+132,BUFFER+132),(0,4,BUFFER,BUFFER+132,BUFFER+132),(0,0,BUFFER,BUFFER+88,BUFFER+44),(1,0,0,0,0)])
def test_bounds_and_processing_index_mismatch_refuse(native,words):
    obj,_=source(native);obj.put(PLAYBACK+0x1418,struct.pack('<5Q',*words))
    with pytest.raises(ValueError):events.capture(obj.read,BASE,obj.bound)


def test_owner_mutation_native_drift_and_unverified_projection_refuse(native):
    obj,_=source(native);captured=events.capture(obj.read,BASE,obj.bound)
    with pytest.raises(ValueError):events.project(captured)
    obj.put(BUFFER,b'\x99')
    with pytest.raises(ValueError,match='bytes changed'):events.verify_capture(obj.read,BASE,captured,obj.bound)
    obj.put(PLAYBACK+0x18,bytes(8))
    with pytest.raises(ValueError,match='owner changed'):events.capture(obj.read,BASE,obj.bound)
    obj.put(BASE+0x73F1D8,b'\x00')
    with pytest.raises(ValueError,match='source changed'):events.capture(obj.read,BASE,obj.bound)


@pytest.mark.parametrize('at,expected',events.NATIVE_SPANS)
def test_each_native_code_and_named_layout_guard_refuses_drift(native,at,expected):
    obj,_=source(native);obj.put(BASE+at,bytes([expected[0]^1]))
    with pytest.raises(ValueError,match='source changed'):events.capture(obj.read,BASE,obj.bound)
