"""Replay FM27's club financial report and IsPassingFfp in a private ARM64 VM.

The input is a read callback. All CPU stores, allocations and library operations
are local to Unicorn. Only the fingerprinted game's code can be fetched.
"""
from contextlib import contextmanager
from ._os_compat import pread
import os
import struct
import time

import unicorn as uc
from unicorn import arm64_const as arm

from . import financial_details

PAGE = 4096
ARM_SLICE = 0x5ED4000          # file offset of the arm64 slice of the 27.0.0.2493426 plugin (fallback)
CPU_TYPE_ARM64 = 0x100000C


def arm_slice(image):
    """File offset of the arm64 slice of the open plugin file `image`, from its fat header (the
    slice moves between builds: 0x5ED4000 on 27.0.0, 0x5F4C000 on 27.0.1). A file without a fat
    header (a test image) uses ARM_SLICE."""
    head = pread(image.fileno(), 8, 0)
    if len(head) != 8 or struct.unpack('>I', head[:4])[0] != 0xCAFEBABE:
        return ARM_SLICE
    count = struct.unpack('>I', head[4:])[0]
    if not 0 < count <= 8:
        raise UnsupportedProjection('invalid fat header of the plugin')
    table = pread(image.fileno(), 20 * count, 8)
    for k in range(count):
        cpu, _sub, offset, _size, _align = struct.unpack_from('>IIIII', table, 20 * k)
        if cpu == CPU_TYPE_ARM64:
            return offset
    raise UnsupportedProjection('the plugin has no arm64 slice')
TEXT_END = 0x4AEF800
IMPORT_START = 0x4AEE000
SCRATCH = 0x100000000000
SCRATCH_SIZE = 16 * 1024 * 1024
RETURN = SCRATCH - PAGE
MAX_COPY = 1024 * 1024


class UnsupportedProjection(ValueError):
    """The pinned, bounded calculation cannot produce a checked result."""


class FinanceCPU:
    def __init__(self, read, base, image):
        self.read_live = read
        self.base = base
        self.image = image
        self.vm = uc.Uc(uc.UC_ARCH_ARM64, uc.UC_MODE_ARM)
        self.vm.ctl_set_cpu_model(arm.UC_CPU_ARM64_MAX)
        self.vm.mem_map(SCRATCH, SCRATCH_SIZE, uc.UC_PROT_READ | uc.UC_PROT_WRITE)
        self.vm.mem_map(RETURN, PAGE, uc.UC_PROT_EXEC)
        self.heap = SCRATCH + 0x10000
        self.allocations = {}
        self.pages = {}
        self.code_pages = set()
        self.consumed = {}
        self.deadline = time.monotonic() + 25
        self.hooks = []
        self._hook(uc.UC_HOOK_MEM_INVALID, self._fault)
        self._hook(uc.UC_HOOK_MEM_READ, self._observe)
        self._hook(uc.UC_HOOK_BLOCK, self._block)
        self._hook(uc.UC_HOOK_INTR, self._interrupt)
        self._hook(uc.UC_HOOK_CODE, self._stack_probe, begin=base+0xD3E720, end=base+0xD3E720)

    def _hook(self, kind, callback, **bounds):
        self.hooks.append(self.vm.hook_add(kind, callback, **bounds))

    def close(self):
        for handle in self.hooks:
            self.vm.hook_del(handle)

    def _stack_probe(self, vm, pc, size, user):
        # ___chkstk_darwin only touches stack pages. The private stack is premapped.
        sp = vm.reg_read(arm.UC_ARM64_REG_SP)
        if sp-0x17e0 < SCRATCH+SCRATCH_SIZE-0x40000:
            raise UnsupportedProjection('private stack bound')
        vm.reg_write(arm.UC_ARM64_REG_LR, pc+4)
        vm.reg_write(arm.UC_ARM64_REG_PC, pc+4)

    def _interrupt(self, *_):
        raise UnsupportedProjection('unsupported CPU interrupt')

    def _page(self, page):
        if page in self.pages or page in self.code_pages or SCRATCH <= page < SCRATCH+SCRATCH_SIZE:
            return
        if page < PAGE or page == RETURN or len(self.pages)+len(self.code_pages) >= 3500:
            raise UnsupportedProjection('projection memory bound')
        offset = page - self.base
        if 0 <= offset < TEXT_END:
            data = pread(self.image.fileno(), min(PAGE, TEXT_END-offset), arm_slice(self.image)+offset)
            if len(data) != min(PAGE, TEXT_END-offset):
                raise UnsupportedProjection('incomplete pinned image')
            self.vm.mem_map(page, PAGE, uc.UC_PROT_READ | uc.UC_PROT_EXEC)
            self.code_pages.add(page)
        else:
            data = self.read_live(page, PAGE)
            if len(data) != PAGE:
                raise UnsupportedProjection('incomplete input page')
            self.pages[page] = data
            self.vm.mem_map(page, PAGE, uc.UC_PROT_READ | uc.UC_PROT_WRITE)
        self.vm.mem_write(page, data)

    def _fault(self, vm, access, address, size, value, user):
        if access == uc.UC_MEM_FETCH_UNMAPPED:
            if not 0 <= address-self.base < TEXT_END:
                raise UnsupportedProjection('external instruction fetch')
        elif access not in (uc.UC_MEM_READ_UNMAPPED, uc.UC_MEM_WRITE_UNMAPPED):
            raise UnsupportedProjection('protected projection memory')
        self._page(address & -PAGE)
        return True

    def _observe(self, vm, access, address, size, value, user):
        if SCRATCH <= address < SCRATCH+SCRATCH_SIZE or self.base <= address < self.base+TEXT_END:
            return
        while size:
            page = address & -PAGE
            offset = address-page
            count = min(size, PAGE-offset)
            self.consumed.setdefault(page, set()).add((offset, count))
            address += count
            size -= count

    def local_read(self, address, size):
        if not size:
            return b''
        for page in range(address & -PAGE, address+size, PAGE):
            self._page(page)
        self._observe(None, None, address, size, None, None)
        return bytes(self.vm.mem_read(address, size))

    def _string(self, address):
        data = bytearray()
        while len(data) < 16384:
            start = address+len(data)
            # Read through NUL only for the live-byte recheck.
            self._page(start & -PAGE)
            chunk = bytes(self.vm.mem_read(start, min(PAGE-start%PAGE, 16384-len(data))))
            end = chunk.find(b'\0')
            count = len(chunk) if end < 0 else end+1
            self._observe(None, None, start, count, None, None)
            data.extend(chunk[:count])
            if end >= 0:
                return bytes(data[:-1])
        raise UnsupportedProjection('projection string bound')

    def _block(self, vm, address, size, user):
        if time.monotonic() >= self.deadline:
            raise UnsupportedProjection('projection time bound')
        at = address-self.base
        if at < IMPORT_START and at not in (0x4355A04, 0x4355ED4):
            return
        x0, x1, x2 = [vm.reg_read(reg) for reg in (arm.UC_ARM64_REG_X0, arm.UC_ARM64_REG_X1, arm.UC_ARM64_REG_X2)]
        lr = vm.reg_read(arm.UC_ARM64_REG_LR)
        if at in (0x4AEE72C, 0x4355A04):
            size = x0 if at == 0x4AEE72C else x1
            out = self.heap
            self.heap += (max(16, size)+15) & -16
            if self.heap > SCRATCH+SCRATCH_SIZE-0x40000:
                raise UnsupportedProjection('projection allocation bound')
            self.allocations[out] = size
        elif at in (0x4AEE714, 0x4355ED4):
            self.allocations.pop(x0 if at == 0x4AEE714 else x1, None)
            out = 0
        elif at in (0x4AEE978, 0x4AEEDC8, 0x4AEEDBC, 0x4AEEDB0):
            count = x1 if at == 0x4AEE978 else x2
            if count > MAX_COPY:
                raise UnsupportedProjection('projection copy bound')
            if at in (0x4AEEDBC, 0x4AEEDB0):
                data = self.local_read(x1, count)
            else:
                data = bytes([0 if at == 0x4AEE978 else x1 & 255]) * count
            if count:
                for page in range(x0 & -PAGE, x0+count, PAGE):
                    self._page(page)
                    if page in self.code_pages:
                        raise UnsupportedProjection('attempted code overwrite')
                vm.mem_write(x0, data)
            out = x0
        elif at == 0x4AEF320:
            out = len(self._string(x0))
        elif at == 0x4AEF2CC:
            left, right = self._string(x0), self._string(x1)
            out = ((left > right) - (left < right)) & 0xffffffff
        elif at == 0x4AEE7EC:
            # This call casts a primary stage base to its exact concrete type.
            # Broader inheritance and alternate dynamic types require another proof.
            vt = int.from_bytes(self.local_read(x0, 8), 'little')
            if (lr-self.base, x1-self.base, x2-self.base, vt-self.base) != (
                    0x26AF2F4, 0x56708E8, 0x567CE58, 0x567CC60):
                raise UnsupportedProjection('unsupported projection stage cast')
            if struct.unpack('<qQ', self.local_read(vt-16, 16)) != (0, x2):
                raise UnsupportedProjection('projection stage RTTI changed')
            out = x0
        elif at == 0x4AEF0E0 and lr-self.base in (0xE83F0C, 0x3ABF340, 0x116F48C):
            # Use the native off-thread branch that reads stored wage spending.
            out = SCRATCH+0x8000
            if int.from_bytes(self.local_read(self.base+0x56C10F0, 8), 'little') == out:
                raise UnsupportedProjection('private thread token collision')
        else:
            raise UnsupportedProjection(f'unsupported projection call at {at:#x}')
        vm.reg_write(arm.UC_ARM64_REG_X0, out)
        vm.reg_write(arm.UC_ARM64_REG_PC, lr)

    def run(self, function, *args):
        self.vm.reg_write(arm.UC_ARM64_REG_SP, SCRATCH+SCRATCH_SIZE-0x110)
        self.vm.reg_write(arm.UC_ARM64_REG_LR, RETURN)
        for i, value in enumerate(args):
            self.vm.reg_write(arm.UC_ARM64_REG_X0+i, value)
        self.vm.emu_start(self.base+function, RETURN, timeout=25_000_000, count=5_000_000)
        if self.vm.reg_read(arm.UC_ARM64_REG_PC) != RETURN:
            raise UnsupportedProjection('projection did not finish within bounds')
        return self.vm.reg_read(arm.UC_ARM64_REG_X0)

    def ffp_verdict(self, address):
        # The named property has one failure exit. Record the actual branch that
        # reached it so the explanation follows the same comparisons as the bool.
        branches = {0x1A45684: 'assessment_below_zero',
                    0x1A456A8: 'assessment_below_minimum',
                    0x1A456BC: 'wage_threshold_exceeded',
                    0x1A456D0: 'spending_at_or_above_limit',
                    0x1A456E8: 'additional_native_rule_failed'}
        executed = []
        def track(vm, pc, size, user):
            executed.append(pc-self.base)
        hook = self.vm.hook_add(uc.UC_HOOK_CODE, track,
                                begin=self.base+0x1A45660, end=self.base+0x1A456F8)
        try:
            passed = self.run(0x1A45660, address)
        finally:
            self.vm.hook_del(hook)
        if passed == 1:
            return True, None
        if passed == 0 and 0x1A456EC in executed:
            branch = executed[executed.index(0x1A456EC)-1]
            if branch in branches:
                return False, branches[branch]
        raise UnsupportedProjection('unexpected IsPassingFfp exit')

    def verify(self):
        for page, spans in self.consumed.items():
            before = self.pages[page]
            after = self.read_live(page, PAGE)
            if before != after and any(before[i:i+n] != after[i:i+n] for i, n in spans):
                raise UnsupportedProjection('financial inputs changed during projection')


@contextmanager
def _cpu(read_live, base, image_stamp):
    with open(image_stamp[0], 'rb') as image:
        st = os.fstat(image.fileno())
        if (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) != image_stamp[1:]:
            raise UnsupportedProjection('pinned image changed')
        cpu = FinanceCPU(read_live, base, image)
        try:
            yield cpu
        finally:
            cpu.close()


def cash_properties(read_live, base, stamp, owner, getter, properties):
    results = {}
    for field, key in properties.items():
        try:
            with _cpu(read_live, base, stamp) as cpu:
                registry = cpu.run(0x4403CD4)
                cpu.vm.mem_write(SCRATCH, struct.pack('<QQ', registry+8, 0))
                ok = cpu.run(getter, owner, int.from_bytes(key.encode('ascii'), 'big'), SCRATCH)
                kind, raw = struct.unpack_from('<Qi', cpu.local_read(SCRATCH, 16))
                cpu.verify()
                if ok == 1 and kind == registry+0x28:
                    results[field] = financial_details.price(raw)
                    if results[field]['amount'] is not None:
                        results[field]['state'] = 'native_property'
                elif ok == 0 or kind == registry+8:
                    results[field] = {'amount': None, 'state': 'native_property_absent'}
                else:
                    raise UnsupportedProjection('unexpected native cash variant')
        except (UnsupportedProjection, uc.UcError) as exc:
            results[field] = {'amount': None, 'state': 'unavailable', 'reason': str(exc)}
    return results


def project(read_live, snapshot, base, club, image_stamp):
    """Report completed rows from the report-owned vector, never temporary allocations."""
    with _cpu(read_live, base, image_stamp) as cpu:
        try:
            cpu.run(0x1A3AA84, SCRATCH)
            cpu.run(0x1A3B2D0, SCRATCH, club)
            begin, end, capacity = struct.unpack('<QQQ', cpu.local_read(SCRATCH+0xD8, 24))
            if (not begin <= end <= capacity or (capacity-begin) % 8 or (end-begin) % 8
                    or (begin and cpu.allocations.get(begin, -1) < capacity-begin)
                    or capacity-begin > 32*8):
                raise UnsupportedProjection('unexpected finance report vector')
            rows = []
            cid = int.from_bytes(snapshot(club+12, 4), 'little')
            for (address,) in struct.iter_unpack('<Q', cpu.local_read(begin, end-begin)):
                if cpu.allocations.get(address) != 0x140:
                    raise UnsupportedProjection('unexpected finance report row')
                raw = cpu.local_read(address, 0x140)
                comp = struct.unpack_from('<Q', raw, 0xC8)[0]
                if not comp or struct.unpack_from('<I', raw, 0xFC)[0] != cid:
                    raise UnsupportedProjection('finance report owner mismatch')
                passed, failed_check = cpu.ffp_verdict(address)
                assessed, = struct.unpack_from('<q', raw, 0xD8)
                floor, = struct.unpack_from('<i', raw, 0x10C)
                rows.append({'assessment_amount_gbp': None if assessed == 0x7fffffff else assessed,
                             'minimum_result_gbp': None if floor == 0x7fffffff else floor,
                             'competition': financial_details.competition_record(snapshot, base, comp),
                             'is_passing_ffp': passed, 'failed_check': failed_check})
            cpu.verify()
        except uc.UcError as exc:
            raise UnsupportedProjection(f'unsupported isolated CPU operation ({exc})') from exc
    return {'state': 'decoded' if rows else 'no_competition_rows', 'competitions': rows,
            'basis': 'native_finance_report_using_stored_spending'}
