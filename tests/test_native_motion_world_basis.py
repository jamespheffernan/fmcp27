"""Original cached restore, endpoint window and entity copy; no game calls."""
import hashlib,struct
import pytest
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2,UC_ARM64_REG_X19,UC_ARM64_REG_X20,UC_ARM64_REG_X21,UC_ARM64_REG_X22,UC_ARM64_REG_SP,UC_ARM64_REG_LR,UC_ARM64_REG_PC
from fm_live_mcp import native_motion_world_basis as basis
from test_frame_attack_direction import PLUGIN

BASE,PLAYER,ENGINE,BUFFER,PACKET,ENTITY,STACK,STOP=0x100000000,0x30000000,0x31000000,0x32000000,0x33000000,0x34000000,0x80000000,0x90000000


@pytest.fixture(scope='module')
def native():
    with PLUGIN.open('rb') as f:
        assert hashlib.file_digest(f,'sha256').hexdigest()=='774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
        for at,raw in basis.NATIVE_SPANS:f.seek(0x5ED4000+at);assert f.read(len(raw))==raw
    return dict(basis.NATIVE_SPANS)


@pytest.mark.parametrize('xyz',[(-20.12,-40.0,0.0),(0.0,40.0,0.3),(34.0,52.5,1.25),(-34.0,-52.5,0.0)])
@pytest.mark.parametrize('start,end,tick',[(10,20,10),(10,20,15),(10,20,20),(100,20,96),(100,20,97),(100,20,98),(100,20,99)])
def test_cached_xyz_restores_player_point_and_builds_bit_identical_frame_endpoint(native,xyz,start,end,tick):
    uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    for page in {BASE+(at&~4095) for at in native}|{PLAYER,ENGINE+0x15000,BUFFER,PACKET,ENTITY,STACK,STOP}:uc.mem_map(page,4096)
    for at,raw in native.items():uc.mem_write(BASE+at,raw)
    motion=PLAYER+0x80
    uc.mem_write(motion+0x180,struct.pack('<i',start));uc.mem_write(motion+0x188,struct.pack('<i',end))
    uc.mem_write(motion+0xF0,struct.pack('<Q',BUFFER));uc.mem_write(motion+0xE0,struct.pack('<Q',ENGINE))
    # Native restore's ring clamp is explicit: requested ticks96..99 remain
    # within the last4 slots relative to frontier100. No old-ring attestation.
    uc.mem_write(ENGINE+0x154DC,struct.pack('<i',100))
    address=motion+0x100+32*(tick&3) if start>tick else BUFFER+32*(tick-start)
    pose=struct.pack('<3f',*xyz)+bytes(range(13));uc.mem_write(address,pose)
    allowed={(motion+0x180,4),(motion+0x188,4),(motion+0xF0,8),(motion+0xE0,8),(ENGINE+0x154DC,4)}
    stage='restore';reached=[]
    def rd(machine,kind,at,n,value,extra):
        valid=(at,n) in allowed or (address<=at and at+n<=address+25) or (STACK<=at and at+n<=STACK+4096)
        if stage=='endpoint':valid|=(at,n)==(PACKET,4)
        if stage=='entity':valid|=PACKET<=at and at+n<=PACKET+0x50
        assert valid,(stage,hex(at),n);reached.append((at,n))
    def wr(machine,kind,at,n,value,extra):
        valid=STACK<=at and at+n<=STACK+4096
        if stage=='restore':valid|=(at,n) in {(motion+0xC0,8),(motion+0xC8,4),(motion+0x1A8,4),(motion+0x1A0,4)}
        elif stage=='endpoint':valid|=PACKET<=at and at+n<=PACKET+0x50
        else:valid|=ENTITY+0x10<=at and at+n<=ENTITY+0x60
        assert valid,(stage,hex(at),n)
    uc.hook_add(UC_HOOK_MEM_READ,rd);uc.hook_add(UC_HOOK_MEM_WRITE,wr)
    for reg,value in [(UC_ARM64_REG_X0,motion),(UC_ARM64_REG_X1,0),(UC_ARM64_REG_X2,tick),(UC_ARM64_REG_SP,STACK+0xF00),(UC_ARM64_REG_LR,STOP)]:uc.reg_write(reg,value)
    uc.emu_start(BASE+0x47D2078,STOP,count=120);assert uc.reg_read(UC_ARM64_REG_PC)==STOP
    assert bytes(uc.mem_read(PLAYER+0x140,12))==pose[:12]
    stage='endpoint'
    for reg,value in [(UC_ARM64_REG_X19,PACKET),(UC_ARM64_REG_X20,tick),(UC_ARM64_REG_X21,ENGINE),(UC_ARM64_REG_X22,PLAYER),(UC_ARM64_REG_SP,STACK+0xF00)]:uc.reg_write(reg,value)
    uc.emu_start(BASE+0x4ABD9DC,BASE+0x4ABDA5C,count=150);assert uc.reg_read(UC_ARM64_REG_PC)==BASE+0x4ABDA5C
    assert struct.unpack('<I',uc.mem_read(PACKET,4))[0]==1
    assert bytes(uc.mem_read(PACKET+0x10,12))==pose[:12]
    assert bytes(uc.mem_read(PACKET+0x20,4))==struct.pack('<f',1.0)
    stage='entity';uc.reg_write(UC_ARM64_REG_X0,ENTITY);uc.reg_write(UC_ARM64_REG_X1,PACKET);uc.reg_write(UC_ARM64_REG_LR,STOP)
    uc.emu_start(BASE+0x4AB1F78,STOP,count=20);assert uc.reg_read(UC_ARM64_REG_PC)==STOP
    assert bytes(uc.mem_read(ENTITY+0x20,12))==pose[:12]==bytes(uc.mem_read(PLAYER+0x140,12))
    assert bytes(uc.mem_read(ENTITY+0x30,4))==struct.pack('<f',1.0)


def test_source_guard_does_not_claim_attacked_end_units_or_participation(native):
    result=basis.verify_native(lambda at,n:native[at-BASE],BASE)
    assert result['same_native_xyz_representation'] is True and result['physical_units'] is None
    assert result['positive_y_attacked_end_verified'] is result['active_participation_verified'] is result['historical_pose_tick_attested'] is False
    for at,raw in native.items():
        changed=native|{at:bytes([raw[0]^1])+raw[1:]}
        with pytest.raises(ValueError):basis.verify_native(lambda address,n:changed[address-BASE],BASE)
