"""Resident-path controls execute the complete original native getter."""
import hashlib
import struct

import pytest
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_X5, UC_ARM64_REG_LR, UC_ARM64_REG_SP, UC_ARM64_REG_PC
from fm_live_mcp import native_motion_cache as motion
from test_frame_attack_direction import PLUGIN, Source

BASE, PLAYER, BUFFER, OUTPUT, STACK, STOP = 0x100000000, 0x30000000, 0x31000000, 0x32000000, 0x80000000, 0x90000000


@pytest.fixture(scope='module')
def original():
    at, expected = motion.NATIVE_GETTER
    with PLUGIN.open('rb') as f:
        assert hashlib.file_digest(f,'sha256').hexdigest() == '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
        f.seek(0x5ED4000+at)
        assert f.read(len(expected)) == expected
    return {at:expected}


def source(original, start=10, end=20, tick=15, pointer=BUFFER):
    obj=Source.__new__(Source);obj.values={};obj.reads=[]
    for at,raw in original.items():obj.put(BASE+at,raw)
    obj.put(PLAYER+0x200,struct.pack('<i',start))
    obj.put(PLAYER+0x208,struct.pack('<i',end))
    obj.put(PLAYER+0x170,struct.pack('<Q',pointer))
    pose=struct.pack('<3f',12.25,-45.5,0.375)+bytes(range(13))
    address=PLAYER+0x180+32*(tick&3) if start>tick else pointer+32*(tick-start)
    if pointer or start>tick:obj.put(address,pose)
    return obj,pose


def oracle(obj,tick):
    at,code=motion.NATIVE_GETTER
    uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    pages={(a&~4095) for a in obj.values}|{OUTPUT,STACK,STOP}
    for page in sorted(pages):uc.mem_map(page,4096)
    for a,b in obj.values.items():uc.mem_write(a,bytes([b]))
    reads=[]
    def rd(machine,kind,address,size,value,extra):
        if STACK<=address<STACK+4096:return
        assert all(address+i in obj.values for i in range(size)),(hex(address),size)
        assert bytes(machine.mem_read(address,size))==bytes(obj.values[address+i] for i in range(size))
        reads.append((address,size))
    def wr(machine,kind,address,size,value,extra):
        assert (STACK<=address and address+size<=STACK+4096) or (OUTPUT<=address and address+size<=OUTPUT+25)
    uc.hook_add(UC_HOOK_MEM_READ,rd);uc.hook_add(UC_HOOK_MEM_WRITE,wr)
    for reg,v in [(UC_ARM64_REG_X0,PLAYER+0x80),(UC_ARM64_REG_X3,OUTPUT),(UC_ARM64_REG_X4,tick),(UC_ARM64_REG_X5,0),(UC_ARM64_REG_LR,STOP),(UC_ARM64_REG_SP,STACK+0xF00)]:uc.reg_write(reg,v)
    uc.emu_start(BASE+at,STOP,count=80)
    assert uc.reg_read(UC_ARM64_REG_PC)==STOP
    return bytes(uc.mem_read(OUTPUT,25)),reads


@pytest.mark.parametrize('start,end,tick',[(10,20,10),(10,20,15),(10,20,20),(0,1199,1199),(-1,20,0),(100,20,0),(100,20,1),(100,20,2),(100,20,3)])
def test_complete_original_resident_paths(original,start,end,tick):
    obj,pose=source(original,start,end,tick)
    native,reads=oracle(obj,tick)
    result=motion.capture(obj.read,BASE,PLAYER,fixed_tick=tick)
    assert native==pose==bytes.fromhex(result['pose_rawhex'])
    assert result['native_xyz']==[12.25,-45.5,0.375]
    assert result['historical_tick_attested'] is False
    assert result['actor_on_pitch'] is None
    # Removing each original external operand makes passive selection fail.
    for address,size in reads:
        saved=obj.values.pop(address)
        with pytest.raises(KeyError):motion.capture(obj.read,BASE,PLAYER,fixed_tick=tick)
        obj.values[address]=saved
    assert motion.verify_capture(obj.read,BASE,PLAYER,result)['native_motion_bytes_physically_reselected'] is True


@pytest.mark.parametrize('start,end,tick,pointer,state',[(10,-1,15,BUFFER,'generation_or_secondary_clock'),(10,14,15,BUFFER,'generation_or_secondary_clock'),(10,20,15,0,'buffer_allocation'),(0,2000,1200,BUFFER,'bounded_motion_buffer_range')])
def test_constructor_and_unbounded_paths_unavailable_without_pose_reads(original,start,end,tick,pointer,state):
    obj,_=source(original,start,end,tick,pointer)
    result=motion.capture(obj.read,BASE,PLAYER,fixed_tick=tick)
    expected = 'unavailable_'+state if state=='bounded_motion_buffer_range' else 'unavailable_requires_'+state
    assert result['state']==expected
    assert result['pose_rawhex'] is None
    assert all(n!=25 for _,n in obj.reads)


def test_mutation_is_rejected(original):
    obj,_=source(original)
    result=motion.capture(obj.read,BASE,PLAYER,fixed_tick=15)
    obj.put(PLAYER+0x208,struct.pack('<i',21))
    with pytest.raises(ValueError,match='selection changed'):motion.verify_capture(obj.read,BASE,PLAYER,result)


@pytest.mark.parametrize('tick',[True,-1,2**31,None])
def test_invalid_tick_refuses(original,tick):
    obj,_=source(original)
    with pytest.raises(ValueError):motion.capture(obj.read,BASE,PLAYER,fixed_tick=tick)


def test_nonfinite_pose_and_native_drift(original):
    obj,_=source(original)
    obj.put(BUFFER+32*5,struct.pack('<f',float('nan')))
    assert motion.capture(obj.read,BASE,PLAYER,fixed_tick=15)['state']=='unavailable_nonfinite_native_motion_pose'
    at,_=motion.NATIVE_GETTER;obj.put(BASE+at,b'\0')
    with pytest.raises(ValueError,match='getter changed'):motion.capture(obj.read,BASE,PLAYER,fixed_tick=15)
