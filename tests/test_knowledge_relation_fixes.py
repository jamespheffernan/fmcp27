"""Controls for the relation-fixes overlay against the original on-disk ARM64 bytes."""
import hashlib
import importlib.util
from pathlib import Path
import pytest

import _pinned_build
GAME=_pinned_build.PLUGIN
ARM64_OFFSET=99434496
from fm_live_mcp import knowledge_relation_fixes as overlay

pytestmark=pytest.mark.skipif(not GAME.is_file(),reason='installed FM27 plugin bytes are required')


class Unavailable(ValueError):pass


class FakeSource:
    base=0x7000000000
    def __init__(self,uid,nation,empty_nation=False):
        data=GAME.read_bytes()
        self.image=data[ARM64_OFFSET:ARM64_OFFSET+0x5a69000]
        self.club=0x500000000;self.nation=0x500001000
        self.mem={self.club+0xd8:(0 if empty_nation else self.nation).to_bytes(8,'little'),
                  self.club+0xc:uid.to_bytes(4,'little'),self.nation+0xc:nation.to_bytes(4,'little')}
        self.log=[]
    def read(self,address,size):
        self.log.append((address,size))
        if self.base<=address<self.base+0x5a69000:
            return self.image[address-self.base:address-self.base+size]
        out=bytearray()
        for i in range(size):
            for a,v in self.mem.items():
                if a<=address+i<a+len(v):out.append(v[address+i-a]);break
            else:out.append(0)
        return bytes(out)


def test_pinned_function_bytes():
    rva,size,digest=overlay.FUNCTION
    source=FakeSource(1,0x186)
    assert hashlib.sha256(source.read(source.base+rva,size)).hexdigest()==digest


@pytest.mark.parametrize('uid',[72053036,1,0,0x7fffffff])
@pytest.mark.parametrize('nation',[0x186,0x16c])
def test_unlisted_club_returns_null(uid,nation):
    source=FakeSource(uid,nation)
    assert overlay.replay_special_club(source,source.club,Unavailable)==0
    # No byte outside the function, the club row and the nation row was read.
    allowed=lambda a:source.base+0xe02f00<=a<source.base+0xe02f00+0x37c or a in(source.club+0xd8,source.club+0xc,source.nation+0xc)\
        or source.base+0x4587a40<=a<source.base+0x4587a40+14
    assert all(allowed(a) for a,_ in source.log)


@pytest.mark.parametrize('uid',[0x44afec1,0x44afec4,0x44afef2,0x44b5bb0,0x77361af6])
def test_listed_club_reaches_lookup_and_refuses(uid):
    source=FakeSource(uid,0x186)
    with pytest.raises(Unavailable):
        overlay.replay_special_club(source,source.club,Unavailable)


def test_changed_code_would_refuse():
    source=FakeSource(72053036,0x186)
    original=source.read
    def tampered(address,size):
        data=bytearray(original(address,size))
        if address==source.base+0xe02f00 and size==0x37c:data[0x28:0x2c]=bytes.fromhex('010080d2')
        return bytes(data)
    source.read=tampered
    # The overlay's source_type guard compares the pinned SHA before running.
    rva,size,digest=overlay.FUNCTION
    assert hashlib.sha256(source.read(source.base+rva,size)).hexdigest()!=digest


def test_lazy_replay_matches_pinned_replay_for_unlisted_club():
    source=FakeSource(72053036,0x186)
    overlay.RECEIPTS.clear()
    assert overlay.replay_lazy(source,source.club and 0xe02f00,(source.club,),Unavailable,'control')==0
    receipt=overlay.RECEIPTS[-1]
    assert receipt['result']=='0x0' and receipt['instructions']<60 and receipt['data_reads']<=8
    assert all(len(h)==64 for h in receipt['code_pages'].values())


def test_lazy_replay_refuses_outside_text_and_stack_writes():
    source=FakeSource(72053036,0x186)
    # Start in the middle of the data/const area: not original __text.
    with pytest.raises(Unavailable):
        overlay.replay_lazy(source,0x5700000,(source.club,),Unavailable,'outside')


def test_lazy_replay_refuses_heap_write():
    source=FakeSource(1,0x186)
    # e02f0c..: craft a call into a function known to write to its first argument? Use a store opcode via patching.
    original=source.read
    def patched(address,size):
        data=bytearray(original(address,size))
        a0=source.base+0xe02f00
        if address<=a0<address+size:
            off=a0-address
            data[off:off+4]=bytes.fromhex('000000f9')  # str x0,[x0]
        return bytes(data)
    source.read=patched
    with pytest.raises(Unavailable):
        overlay.replay_lazy(source,0xe02f00,(source.club,),Unavailable,'write')


def test_thread_model_stubs_encode_expected_behaviour():
    from unicorn import Uc,UC_ARCH_ARM64 as A,UC_MODE_ARM as M
    import unicorn.arm64_const as regs
    base=0x7000000000;owner=0x17005f000
    for global_rva in (overlay.THREAD_MAIN,overlay.THREAD_OTHER):
        models=overlay.thread_stub_models(global_rva)
        assert len(models[overlay.PTHREAD_SELF_STUB])==12 and len(models[overlay.PTHREAD_EQUAL_STUB])==12
        uc=Uc(A,M);uc.mem_map(base+0x4aef000,0x1000);uc.mem_map(base+(global_rva&~0xfff),0x1000)
        uc.mem_write(base+overlay.PTHREAD_SELF_STUB,models[overlay.PTHREAD_SELF_STUB])
        uc.mem_write(base+global_rva,owner.to_bytes(8,'little'))
        uc.reg_write(regs.UC_ARM64_REG_X30,base+0x4af0000);uc.mem_map(base+0x4af0000,0x1000)
        uc.emu_start(base+overlay.PTHREAD_SELF_STUB,base+0x4af0000)
        assert uc.reg_read(regs.UC_ARM64_REG_X0)==owner
    def run(code,x0,x1):
        uc=Uc(A,M);uc.mem_map(0x1000,0x1000);uc.mem_write(0x1000,code)
        uc.reg_write(regs.UC_ARM64_REG_X0,x0);uc.reg_write(regs.UC_ARM64_REG_X1,x1)
        uc.reg_write(regs.UC_ARM64_REG_X30,0x1ff0);uc.emu_start(0x1000,0x1ff0)
        return uc.reg_read(regs.UC_ARM64_REG_X0)
    for x0,x1,want in ((5,5,1),(5,6,0)):
        assert run(overlay.thread_stub_models(overlay.THREAD_MAIN)[overlay.PTHREAD_EQUAL_STUB],x0,x1)==want


def _decode_adrp_ldr(word_adrp,pc,word_ldr):
    immlo=(word_adrp>>29)&3;immhi=(word_adrp>>5)&0x7ffff
    imm=((immhi<<2)|immlo)<<12
    if imm>=1<<32:imm-=1<<33
    page=(pc&~0xfff)+imm
    size=(word_ldr>>30)&3
    offset=((word_ldr>>10)&0xfff)<<size
    return page+offset


def test_thread_globals_decode_from_the_original_instructions():
    source=FakeSource(1,0x186)
    code=source.image[0x17743b8:0x17743b8+0x60]
    word=lambda off:int.from_bytes(code[off:off+4],'little')
    assert _decode_adrp_ldr(word(0x18),0x17743d0,word(0x1c))==overlay.THREAD_FLAG     # ldrb w8,[x8,#0xe8]
    assert _decode_adrp_ldr(word(0x28),0x17743e0,word(0x2c))==overlay.THREAD_MAIN     # ldr x21,[x8,#0xf0]
    assert _decode_adrp_ldr(word(0x44),0x17743fc,word(0x48))==overlay.THREAD_OTHER    # ldr x1,[x8,#0x6b0]


def test_modelled_stub_callers_match_original_call_sites():
    source=FakeSource(1,0x186)
    code=source.image[0x17743b8:0x17743b8+0x60]
    def target(off):
        w=int.from_bytes(code[off:off+4],'little')
        assert w>>26==0b100101
        imm=w&0x3ffffff
        if imm>=1<<25:imm-=1<<26
        return 0x17743b8+off+imm*4
    assert target(0x30)==overlay.PTHREAD_SELF_STUB and 0x17743b8+0x30+4 in overlay.SELF_CALLERS
    assert target(0x40)==overlay.PTHREAD_SELF_STUB and 0x17743b8+0x40+4 in overlay.SELF_CALLERS
    assert target(0x4c)==overlay.PTHREAD_EQUAL_STUB and 0x17743b8+0x4c+4 in overlay.EQUAL_CALLERS
