"""Independent strict disk-code -> owned-RAM machine, never a game call."""
from pathlib import Path
import hashlib
import struct
import sys

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn import arm64_const as R

import _pinned_build
BINARY = _pinned_build.PLUGIN
PLUGIN_SHA = '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
SLICE, BASE = 0x5ed4000, 0x100000000


def need(value, message):
    if not value: raise AssertionError(message)


class Image:
    def __init__(self):
        with BINARY.open('rb') as file:
            need(hashlib.file_digest(file, 'sha256').hexdigest() == PLUGIN_SHA, 'Plugin changed')
            file.seek(SLICE); header = struct.unpack('<8I', file.read(32))
            need(header[:2] == (0xfeedfacf, 0x100000c), 'Wrong ARM64 image')
            self.segments = []; encoded = None
            for _ in range(header[4]):
                command, size = struct.unpack('<II', file.read(8)); payload = file.read(size - 8)
                if command == 0x19: self.segments.append(struct.unpack('<16s4Q', payload[:48]))
                if command == 0x26: encoded = struct.unpack('<II', payload[:8])
            need(encoded is not None, 'No function metadata')
            file.seek(SLICE + encoded[0]); data = file.read(encoded[1])
        starts, address, value, shift = [], 0, 0, 0
        for byte in data:
            value |= (byte & 127) << shift
            if byte & 128: shift += 7; continue
            if not value: break
            address += value; starts.append(address); value = shift = 0
        self.bounds = dict(zip(starts, starts[1:]))

    def read(self, address, size):
        for _, va, _, offset, count in self.segments:
            if va <= address and address + size <= va + count:
                with BINARY.open('rb') as file:
                    file.seek(SLICE + offset + address - va); raw = file.read(size)
                need(len(raw) == size, 'Truncated disk source'); return raw
        raise AssertionError('Unbacked disk source')


class Machine:
    STACK, OUTPUT, STOP, ALLOCATOR = 0x72000000, 0x73000000, 0x74000000, BASE + 0x4355a04

    def __init__(self, fixture, code, image):
        self.vm = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        self.vm.ctl_set_cpu_model(R.UC_CPU_ARM64_MAX)
        self.known, self.pages, self.visited, self.reads, self.stores = set(), set(), set(), set(), []
        self.expected = {BASE + start + i: byte for start, raw in code.items() for i, byte in enumerate(raw)}
        for start, raw in code.items():
            need(image.bounds[start] == start + len(raw), f'Not a whole function: {start:x}')
            need(image.read(start, len(raw)) == raw, f'Code fixture differs from disk: {start:x}')
        # All fixture data are explicit; unmapped/implicit page zeros are unknown.
        values = dict(fixture.data)
        values.update(self.expected)
        values.update({BASE+0x56a4a90+i: b for i,b in enumerate(struct.pack('<Q', 0x75000000))})
        values.update({BASE+0x56a49f8+i: b for i,b in enumerate(struct.pack('<Q', fixture.manager))})
        ordered = sorted(values); i = 0
        while i < len(ordered):
            start = ordered[i]; end = i + 1
            while end < len(ordered) and ordered[end] == ordered[end-1]+1: end += 1
            self.seed(start, bytes(values[a] for a in ordered[i:end])); i = end
        self.map(self.STACK, 0x10000); self.map(self.OUTPUT, 4096); self.map(self.STOP, 4096)
        self.map(self.ALLOCATOR, 4); self.vm.mem_write(self.ALLOCATOR, image.read(0x4355a04,4))
        self.seed(self.OUTPUT, struct.pack('<I', 7))
        self.vm.hook_add(UC_HOOK_CODE, self.instruction)
        self.vm.hook_add(UC_HOOK_MEM_READ, self.read)
        self.vm.hook_add(UC_HOOK_MEM_WRITE, self.write)

    def map(self, address, size):
        for page in range(address & ~4095, (address+size+4095) & ~4095, 4096):
            if page not in self.pages: self.vm.mem_map(page, 4096); self.pages.add(page)

    def seed(self, address, raw):
        self.map(address, len(raw)); self.vm.mem_write(address, raw); self.known.update(range(address, address+len(raw)))

    def instruction(self, vm, address, size, user):
        if address == self.ALLOCATOR:
            self.allocator_boundary = True; vm.emu_stop(); return
        need(size == 4 and all(a in self.expected for a in range(address,address+4)), f'Unexpected callee {address:x}')
        need(bytes(vm.mem_read(address,4)) == bytes(self.expected[a] for a in range(address,address+4)), 'Executed code changed')
        self.visited.add(address)

    def read(self, vm, access, address, size, value, user):
        need(all(a in self.known for a in range(address,address+size)), f'Unknown byte read {address:x}/{size}')
        self.reads.add((address,size))

    def write(self, vm, access, address, size, value, user):
        need(self.STACK <= address and address+size <= self.STACK+0x10000
             or self.OUTPUT <= address and address+size <= self.OUTPUT+4, f'Unexpected native store {address:x}/{size}')
        self.known.update(range(address,address+size)); self.stores.append((address,size))

    def run(self, fixture, start=0x1febc8c):
        self.allocator_boundary = False
        for index in range(29): self.vm.reg_write(getattr(R,f'UC_ARM64_REG_X{index}'), 0)
        args = (fixture.team,) if start == 0x175e508 else (fixture.service,fixture.club,0,0,self.OUTPUT)
        for index,value in enumerate(args): self.vm.reg_write(getattr(R,f'UC_ARM64_REG_X{index}'),value)
        self.vm.reg_write(R.UC_ARM64_REG_SP,self.STACK+0x8000)
        self.vm.reg_write(R.UC_ARM64_REG_LR,self.STOP)
        self.vm.reg_write(R.UC_ARM64_REG_FPCR,0)
        self.vm.emu_start(BASE+start,self.STOP,count=30000)
        pc = self.vm.reg_read(R.UC_ARM64_REG_PC)
        need(pc == (self.ALLOCATOR if self.allocator_boundary else self.STOP), 'Native instruction bound exhausted')
        result = dict(completed=not self.allocator_boundary,
                      return_value=None if self.allocator_boundary else self.vm.reg_read(R.UC_ARM64_REG_X0),
                      out_amount=None if self.allocator_boundary else int.from_bytes(self.vm.mem_read(self.OUTPUT,4),'little'),
                      stop=hex(pc), instructions=len(self.visited), consumed_ranges=len(self.reads))
        if self.allocator_boundary:
            result['incomplete_register_x0'] = hex(self.vm.reg_read(R.UC_ARM64_REG_X0))
            result['incomplete_output_bytes'] = bytes(self.vm.mem_read(self.OUTPUT,4)).hex()
        return result
