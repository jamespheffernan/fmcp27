"""Independent whole-native payroll oracle over reviewer-owned RAM.

No production CPU/calculation/predicate or wage formula is used. Graph.read
supplies typed fixture bytes only; actual pinned instructions execute in a
separate Unicorn machine, including native selector and reducer bodies.
Allocator/free/copy/sort imports act only on owned RAM. Unknown callees,
thread/HUMAN services and exhausted execution bounds reject explicitly.
"""
import ast
import hashlib
import json
from pathlib import Path
import struct

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_INVALID
from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_LR, UC_ARM64_REG_PC,
                                UC_ARM64_REG_SP, UC_ARM64_REG_X29, UC_CPU_ARM64_MAX)

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent


class Unproved(Exception):pass


def spans():
    result=[]
    for module in ('committed_wage_spending_core','committed_wage_payroll_core'):
        tree=ast.parse((ROOT/'fm_live_mcp'/f'{module}.py').read_text())
        result+=list(next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
            and any(isinstance(t,ast.Name) and t.id=='_SPANS' for t in n.targets)))
    tree=ast.parse((ROOT/'fm_live_mcp/committed_wage_offer_selection.py').read_text())
    selected=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=='SOURCE' for t in n.targets))
    result += [(at,at+size,digest) for at,size,digest in selected]
    approved=ROOT/'tests/fixtures/committed-wage-selection-native.json'
    assert hashlib.sha256(approved.read_bytes()).hexdigest()=='6495f21adbf760337c4c3507b2a013ef4e8022ed5834335d4c90b68806c342c3'
    for at,code in json.loads(approved.read_text()).items():
        raw=bytes.fromhex(code);start=int(at,0)
        result.append((start,start+len(raw),hashlib.sha256(raw).hexdigest()))
    return sorted(set(result))


class WholeNative:
    def __init__(self,graph,base):
        self.graph,self.base=graph,base
        self.vm=Uc(UC_ARCH_ARM64,UC_MODE_ARM);self.vm.ctl_set_cpu_model(UC_CPU_ARM64_MAX)
        self.mapped=set();self.allowed={};self.seen=set();self.trace=[];self.instructions=0
        self.heap=0x71000000;self.allocations={};self.native_calls=[];self.failure=None
        with open(graph.image[0],'rb') as image:
            for start,end,digest in spans():
                image.seek(0x5ed4000+start);raw=image.read(end-start)
                assert len(raw)==end-start and hashlib.sha256(raw).hexdigest()==digest
                self.allowed[start]=(end,raw)
        self.map_owned(0x70000000,0x200000)
        self.map_owned(0x71000000,0x200000)
        self.sentinel=0x701ff000
        self.vm.hook_add(UC_HOOK_MEM_INVALID,self.fault)
        self.vm.hook_add(UC_HOOK_CODE,self.code)

    def map_owned(self,address,size):
        for page in range(address&-4096,(address+size+4095)&-4096,4096):
            if page not in self.mapped:self.vm.mem_map(page,4096);self.mapped.add(page)

    def fault(self,vm,access,address,size,value,user):
        try:
            page=address&-4096
            if page not in self.mapped:
                if len(self.mapped)>=2048:raise Unproved('oracle page bound')
                raw=self.graph.read(page,4096)
                if len(raw)!=4096:raise Unproved('truncated fixture page')
                vm.mem_map(page,4096);vm.mem_write(page,raw);self.mapped.add(page)
            return True
        except Exception as error:
            self.failure=str(error);raise

    def owned(self,address,size):
        return any(start<=address and address+size<=start+count for start,count in self.allocations.items())

    def code(self,vm,pc,size,user):
        if pc==self.sentinel:vm.emu_stop();return
        self.instructions+=1
        if self.instructions>600000:raise Unproved('oracle instruction bound')
        at=pc-self.base
        if at in (0x4AEF0E0,0x4AEEFD8):raise Unproved('native thread/HUMAN gate')
        lr=vm.reg_read(UC_ARM64_REG_LR)-self.base
        x0,x1,x2=[vm.reg_read(UC_ARM64_REG_X0+i) for i in range(3)]
        if at==0x4355A04:
            if lr not in (0xE83570,0xE838FC) or not 0<=x1<=40000:raise Unproved('oracle unknown allocation')
            out=self.heap;self.heap+=(max(16,x1)+15)&-16
            if self.heap>0x71200000:raise Unproved('oracle heap bound')
            self.allocations[out]=x1
        elif at==0x4355ED4:
            # Exact native vector frees; null/empty vector is a real no-op.
            if x1==0 and x2==0:out=0
            elif self.allocations.get(x1)==x2:self.allocations.pop(x1);out=0
            else:raise Unproved(f'oracle unowned free {x1:#x}/{x2}')
        elif at==0x4AEEDB0:
            if lr!=0xE8392C or x2>40000 or not self.owned(x0,x2) or not self.owned(x1,x2):raise Unproved('oracle unowned copy')
            vm.mem_write(x0,bytes(vm.mem_read(x1,x2)));out=x0
        elif at==0x4AEE5F4:
            count=x1-x0
            if lr!=0xE83A48 or count<0 or count%4 or not self.owned(x0,count):raise Unproved('oracle unowned sort')
            values=struct.unpack(f'<{count//4}i',vm.mem_read(x0,count))
            vm.mem_write(x0,struct.pack(f'<{len(values)}i',*sorted(values)));out=0
        else:
            if at==0x1826544:
                output=vm.reg_read(UC_ARM64_REG_X0+2)
                header=struct.unpack('<QQQ',vm.mem_read(output,24))
                if header==(0,0,0):
                    # Supply empty owned capacity, as in the separate native
                    # selector oracle. Actual native membership/predicates and
                    # intrusive reference writes still execute unmodified.
                    out=self.heap;self.heap+=4096
                    if self.heap>0x71200000:raise Unproved('oracle vector capacity bound')
                    self.allocations[out]=4096
                    vm.mem_write(output,struct.pack('<QQQ',out,out,out+4096))
            start=next((start for start,(end,_) in self.allowed.items() if start<=at<end),None)
            if start is None:raise Unproved(f'oracle unknown callee {at:#x} LR{lr:#x}')
            if start not in self.seen:
                end,raw=self.allowed[start]
                if self.graph.read(self.base+start,end-start)!=raw:raise Unproved('oracle loaded code differs')
                self.seen.add(start);self.native_calls.append(start)
            return
        # Source-loaded import stub bytes must also agree with disk.
        with open(self.graph.image[0],'rb') as image:
            image.seek(0x5ed4000+at);expected=image.read(12)
        if self.graph.read(self.base+at,12)!=expected:raise Unproved('oracle loaded import differs')
        self.trace.append(dict(import_rva=hex(at),return_rva=hex(lr)))
        vm.reg_write(UC_ARM64_REG_X0,out);vm.reg_write(UC_ARM64_REG_PC,self.base+lr)

    def run(self,entry,*args):
        for i in range(29):self.vm.reg_write(UC_ARM64_REG_X0+i,0)
        self.vm.reg_write(UC_ARM64_REG_X29,0)
        for i,value in enumerate(args):self.vm.reg_write(UC_ARM64_REG_X0+i,value)
        self.vm.reg_write(UC_ARM64_REG_SP,0x70100000)
        self.vm.reg_write(UC_ARM64_REG_LR,self.sentinel)
        self.vm.emu_start(self.base+entry,self.sentinel,count=600001)
        if self.vm.reg_read(UC_ARM64_REG_PC)!=self.sentinel:raise Unproved('oracle did not return')
        return struct.unpack('<i',struct.pack('<I',self.vm.reg_read(UC_ARM64_REG_X0)&0xffffffff))[0]

    def payroll(self,total=True):
        self.run(0xE830E4,self.graph.finance,self.graph.club,0)
        value=self.run(0xE83ED0,self.graph.finance,self.graph.club,int(total),1)
        fields=struct.unpack('<6i',self.vm.mem_read(self.graph.finance+0x810,24))
        return value,fields
