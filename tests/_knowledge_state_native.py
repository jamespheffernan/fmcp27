"""Strict original H/callee execution in owned Unicorn memory, no lower stubs."""
import struct
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE,UC_HOOK_MEM_INVALID
import unicorn.arm64_const as regs
from _unicorn_pages import map_pages,page_images
from fm_live_mcp import knowledge_context_score as core,knowledge_context_score_source as source,knowledge_transfer_predicate as transfer,knowledge_passing_state as state


_INSIDE={}


def execute(memory,entry,arguments,*,score_pointer=None,extra=(),output_width=1,cpu_model=None):
    uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    if cpu_model is not None:uc.ctl_set_cpu_model(cpu_model)
    known=set(memory.cells);images=page_images(memory.cells);pages=set(images);stack,stop=0x200000000,0x300000000
    pages.update(range(stack,stack+0x10000,4096));pages.add(stop)
    map_pages(uc,pages)
    for page in sorted(images):uc.mem_write(page,images[page])
    executable=[(memory.base+a,memory.base+a+n)for a,n,_ in core.NATIVE_GUARDS+source.EXTRA_GUARDS+transfer.NATIVE_GUARDS+state.NATIVE_GUARDS+extra]
    executable +=[(memory.base+a,memory.base+a+len(raw))for a,raw in source.aggregate.NATIVE_SPANS]
    reads=[];writes=[];instructions=[];derived=set()
    # Instruction addresses already found inside `executable` (the same list gives the same answer).
    inside=_INSIDE.setdefault(tuple(executable),set())
    def code(machine,address,size,user):
        if address==stop:machine.emu_stop();return
        if address not in inside:
            assert any(a<=address<b for a,b in executable),('uncaptured native callee',hex(address-memory.base))
            inside.add(address)
        instructions.append(address-memory.base)
    def read(machine,access,address,size,value,user):
        assert all(at in known for at in range(address,address+size)),('missing original native operand',hex(address),size,hex(machine.reg_read(regs.UC_ARM64_REG_PC)-memory.base))
        if not stack<=address<stack+0x10000 and not any(at in derived for at in range(address,address+size)):reads.append((address,size))
    def write(machine,access,address,size,value,user):
        pc=machine.reg_read(regs.UC_ARM64_REG_PC)-memory.base
        allowed=stack<=address and address+size<=stack+0x10000
        allowed |= score_pointer is not None and score_pointer<=address and address+size<=score_pointer+output_width
        allowed |= pc in (0x23872e0,0x20ee74c) and address==memory.national+0xe2 and size==1
        # The selector's placeholder resolution is local in this VM only.
        allowed |= pc in (0x12d9f14,0x12da030,0x12da1e0) and size==8
        assert allowed,('unexpected owned native write',hex(pc),hex(address),size)
        known.update(range(address,address+size));derived.update(range(address,address+size));writes.append((pc,address,size))
    def invalid(machine,access,address,size,value,user):raise AssertionError(('unmapped original native operand',hex(address),size,hex(machine.reg_read(regs.UC_ARM64_REG_PC)-memory.base)))
    uc.hook_add(UC_HOOK_CODE,code);uc.hook_add(UC_HOOK_MEM_READ,read);uc.hook_add(UC_HOOK_MEM_WRITE,write);uc.hook_add(UC_HOOK_MEM_INVALID,invalid)
    uc.reg_write(regs.UC_ARM64_REG_SP,stack+0xf000);uc.reg_write(regs.UC_ARM64_REG_LR,stop)
    for i,value in enumerate(arguments):uc.reg_write(getattr(regs,'UC_ARM64_REG_X'+str(i)),value)
    uc.emu_start(memory.base+entry,stop,count=100000)
    assert uc.reg_read(regs.UC_ARM64_REG_PC)==stop
    return uc.reg_read(regs.UC_ARM64_REG_X0), (uc.mem_read(score_pointer,1)[0]if output_width==1 else bytes(uc.mem_read(score_pointer,output_width)))if score_pointer else None, reads,writes,instructions


def native_state(memory,assessment=0):
    output=memory.allocate(8)
    value,score,reads,writes,code=execute(memory,0x23871f0,[memory.record,memory.person,18,output,assessment,1],score_pointer=output)
    return core._signed(value,32),core._signed(score,8),reads,writes,code
