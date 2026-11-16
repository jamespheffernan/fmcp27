"""Private E830E4 payroll recomputation in owned Unicorn memory only.

The native E83ED0 caller's thread/HUMAN refresh routing remains unsupported.
Recompute explicitly runs the full pinned producer, then reads its newly
computed value through E83ED0's explicit force-no-refresh branch. Entering the
original getter gate keeps its unproved thread context unavailable. This is no public tool
or a complete committed-wage total. No process-call or process-write callback
exists. Unknown helpers, generation and unsupported source layouts reject.
"""
from dataclasses import dataclass
import hashlib
import os
import struct
import time

from . import committed_wage_offer_selection as selection
from . import committed_wage_spending_core as reducer
from . import assessment_people, database, live_transfer_offers as offers, players, teams, world


ffp, uc, arm = reducer.ffp, reducer.uc, reducer.arm
SourceUnavailable = reducer.SourceUnavailable
MAX_READ_BYTES = 64 * 1024 * 1024
MAX_READ_CALLS = 100_000
MAX_INSTRUCTIONS = 300_000
_SPANS = (
    (0xe830e4, 0xe83c80, 'b2208668a1975bc306c6c865598f752e2b5c9c5d1d1be4acb58d41e97de71014'),
    (0xe83ed0, 0xe83fd8, '10240f296c8bd7344068fe2ba19ae33572eba5db739d14c261c82deb4683c455'),
    (0xe08dc4, 0xe09018, '83ebb1892074224b010368764f0d16d4e36246fb65d53474013ea41714bf3d36'),
    (0x13e798c, 0x13e7aac, 'fb098a07207aa2b3c5a5255c7b8718e636e0c1edb545043c3e5c389c8a4f9372'),
    (0xd8788c, 0xd87988, '3980311723659f44f942062a875b34b687fa76875571feadecb933712adc7349'),
    (0xe89018, 0xe89648, 'ece3ba8658e7bff18268505b593853ebde1e2cdb18ba24482d3f8c62172923bd'),
    (0x14f78a0, 0x14f7a20, 'bfd6a1aac092e9e33f470e9b3c19313fcbe316e295269f29bef8b2ac0d134623'),
    (0x14f928c, 0x14f9918, '84c803d848904df121b6a2310c15a5be527317b9ec3f5f65999ebcf48f10e87d'),
    (0x42b5d74, 0x42b5e5c, '0cce607abc272f1e75b9b50e76ba0e714661443a9ae664dc498d2eee38160d10'),
    (0x42b5e5c, 0x42b5f44, '18c2076d3f4b2f89379c0ad09deb865a971c76e01962bd898d23ff13871ea618'),
    (0x1ffe24c, 0x1ffe294, 'ff5eed1c893e4e44838eb6ec2339d7f479c73e5ec08773f7cf8654575416026d'),
    (0xd09bd0, 0xd09d48, '0b25b581e88d61961e1420339d45cac9808c614037c6e14ff64f38d8cac580e5'),
    (0xe89648, 0xe89650, '70fde653dda55ad5cbb1449540a771693c8315fabbc903da8c9db276b15c217e'),
)


def _chunks(read, address, size):
    return b''.join(read(at, min(8192, address+size-at))
                    for at in range(address, address+size, 8192))


@dataclass(frozen=True)
class PayrollResult:
    spending_signed32: int
    field_810: int
    field_814: int
    field_818: int | None
    field_81c: int | None
    field_820: int | None
    field_824: int | None
    pending_reducer_ran: bool
    basis: str
    native_thread_refresh_route: str


class _PayrollCPU(ffp.FinanceCPU):
    """The approved reducer's validators, with payroll-specific entry guards."""
    _store = reducer._ReducerCPU._store
    _static_read = reducer._ReducerCPU._static_read
    _common = reducer._ReducerCPU._common
    _contract = reducer._ReducerCPU._contract

    def __init__(self, snapshot, read_live, base, image, finance, club):
        self.snapshot, self.finance, self.club = snapshot, finance, club
        self.people = self.team_table = None
        self.valid_persons, self.valid_contracts, self.valid_teams = set(), set(), set()
        self.roster_common = set()
        self.team_links, self.person_links = set(), set()
        self.allowed, self.checked = {}, set()
        self.instructions = 0
        self.source_failure = None
        self.selected = ()
        self.pending_reducer_ran = False
        self.static_bindings = reducer._StaticBindings(image, base)
        # Exact native write targets in E830E4/E89018; all are local VM stores.
        self.source_writes = [(finance+offset, finance+offset+size) for offset, size in (
            (0xC, 4), (0x318, 4), (0x548, 4), (0x810, 0x1C), (0x838, 8), (0x844, 8))]
        for start, end, digest in (*reducer._SPANS, *_SPANS):
            raw = os.pread(image.fileno(), end-start, ffp.ARM_SLICE+start)
            if len(raw) != end-start or hashlib.sha256(raw).hexdigest() != digest:
                raise SourceUnavailable(f'pinned payroll source changed at {start:#x}')
            self.allowed[start] = (end, raw)
        ffp.FinanceCPU.__init__(self, read_live, base, image)
        self.vm.reg_write(arm.UC_ARM64_REG_FPCR, 0)
        self.deadline = time.monotonic()+15
        self.selection_vector = ffp.SCRATCH+0x1000
        self.allocations[self.selection_vector] = 0
        self._hook(uc.UC_HOOK_CODE, self._instruction)
        self._hook(uc.UC_HOOK_MEM_WRITE, self._store)

    def _page(self, page):
        if page not in self.pages and len(self.pages) >= 1024:
            raise SourceUnavailable('payroll page bound')
        return super()._page(page)

    def _fault(self, vm, access, address, size, value, user):
        try:
            return super()._fault(vm, access, address, size, value, user)
        except Exception as error:
            self.source_failure = str(error)
            raise

    def _observe(self, vm, access, address, size, value, user):
        self._static_read(address, size)
        if vm is not None:
            for field in range((address+7) & -8, address+size-7, 8):
                if field in self.team_links:
                    target, = struct.unpack('<Q', vm.mem_read(field, 8))
                    if target:
                        self._team(target)
                if field in self.person_links:
                    target, = struct.unpack('<Q', vm.mem_read(field, 8))
                    if target and struct.unpack('<I', self.snapshot(target+0xC, 4))[0] != 0xFFFFFFFF:
                        self._person(target)
        return super()._observe(vm, access, address, size, value, user)

    def _person(self, address):
        if self.people is None:
            self.people = database.table(self.snapshot, self.base, 'people')
        return reducer._ReducerCPU._person(self, address)

    def _team(self, address):
        if self.team_table is None:
            self.team_table = teams.lookup(self.snapshot, self.base)
        return reducer._ReducerCPU._team(self, address)

    def _club(self, address):
        reducer._address(address)
        world.typed(self.snapshot, self.base, address, 'club')
        table = database.table(self.snapshot, self.base, 'clubs')
        index, native = struct.unpack('<II', self.snapshot(address+8, 8))
        if not native:
            raise SourceUnavailable('invalid payroll CLUB native identity')
        database.club_membership(self.snapshot, self.base, table, index, address)

    def _primary(self, primary):
        table = world.pointer(self.snapshot, reducer._address(primary))
        offset = next((fields[2] for fields in assessment_people._PERSON_TYPES.values()
                       if fields[0] in ('actual', 'player_staff') and self.base+fields[1] == table), None)
        if offset is None:
            raise SourceUnavailable('unsupported payroll roster primary type')
        self._person(primary+offset)

    def _club_rosters(self, club):
        self._club(club)
        first, last = reducer._vector(self.snapshot, club+0x18, limit=256)
        for (team,) in struct.iter_unpack('<Q', _chunks(self.snapshot, first, last-first)):
            self._team(team)
            if players.u64(self.snapshot(team+0x30, 8)) != club:
                raise SourceUnavailable('payroll roster TEAM owner changed')
            begin, end = reducer._vector(self.snapshot, team+0x38, limit=10_000)
            for (primary,) in struct.iter_unpack('<Q', _chunks(self.snapshot, begin, end-begin)):
                self._primary(primary)

    def _selector_read(self, address, size):
        if self.base <= address and address+size <= self.base+ffp.TEXT_END:
            # Code used by a host predicate must bind the loaded source too;
            # reading the VM's disk-backed text would prove only disk bytes.
            return self.snapshot(address, size)
        return self.local_read(address, size)

    def _prepare_reducer(self, vm):
        if [vm.reg_read(arm.UC_ARM64_REG_X0+i) for i in range(4)] != [
                reducer._full_finance_service(self.snapshot, self.base), self.finance, self.club, 0]:
            raise SourceUnavailable('payroll full-service reducer arguments changed')
        self.pending_reducer_ran = True
        begin, end = reducer._vector(self.snapshot, self.club+0x18, limit=256)
        team = players.u64(self.snapshot(begin, 8)) if begin != end else 0
        result = selection.select_offers(self._selector_read, self.base, team)
        if result.state != 'selected':
            raise SourceUnavailable(f'payroll offer selection unavailable: {result.reason}')
        self.selected = tuple(row.address for row in result.selected)
        if len(self.selected)*8 > 0xE000:
            raise SourceUnavailable('payroll selected-offer local vector bound')
        self.allocations[self.selection_vector] = len(self.selected)*8
        if self.selected:
            vm.mem_write(self.selection_vector, struct.pack(f'<{len(self.selected)}Q', *self.selected))
        for row in result.selected:
            self.source_writes.extend(((row.address+8, row.address+12),
                                       (row.address+0x38, row.address+0x40),
                                       (row.address+0x48, row.address+0x50)))
            self.team_links.update((row.address+0x40, row.address+0x48, row.address+0x50))
            self.person_links.add(row.address+0x38)
            self.local_read(row.address+0x38, 8)
            vm.mem_write(row.address+0x38, struct.pack('<Q', row.person_address))
            source, alternate = struct.unpack('<QQ', self.local_read(row.address+0x40, 16))
            # 1826978..1826990 caches source40 into a null alternate48 only
            # after the source!=original branch. Retain that native local
            # cache effect for downstream getters without modifying FM.
            if source != team and not alternate:
                vm.mem_write(row.address+0x48, struct.pack('<Q', source))

    def _owned(self, address, size):
        return any(start <= address and address+size <= start+count
                   for start, count in self.allocations.items())

    def _library(self, vm, at):
        lr = vm.reg_read(arm.UC_ARM64_REG_LR)-self.base
        x0, x1, x2 = [vm.reg_read(arm.UC_ARM64_REG_X0+i) for i in range(3)]
        if at == 0x4355A04 and lr in (0xE83570, 0xE838FC):
            if x1 > 40_000:
                raise SourceUnavailable('payroll allocation bound')
            out = self.heap
            self.heap += (max(16, x1)+15) & -16
            if self.heap > ffp.SCRATCH+ffp.SCRATCH_SIZE-0x40000:
                raise SourceUnavailable('payroll heap bound')
            self.allocations[out] = x1
        elif at == 0x4355ED4 and lr in (0xE8394C, 0xE83B7C):
            if self.allocations.get(x1) != x2:
                raise SourceUnavailable('payroll deallocation owner or size changed')
            self.allocations.pop(x1)
            out = 0
        elif at == 0x4AEEDB0 and lr == 0xE8392C:
            if x2 > 40_000 or not self._owned(x0, x2) or not self._owned(x1, x2):
                raise SourceUnavailable('payroll copy ownership changed')
            vm.mem_write(x0, bytes(vm.mem_read(x1, x2)))
            out = x0
        elif at == 0x4AEE5F4 and lr == 0xE83A48:
            # Mach-O indirect symbol: std::__1::__sort<__less<int,int>&,int*>.
            count = x1-x0
            if count < 0 or count % 4 or count > 40_000 or not self._owned(x0, count):
                raise SourceUnavailable('payroll sort ownership changed')
            values = struct.unpack(f'<{count//4}i', vm.mem_read(x0, count))
            vm.mem_write(x0, struct.pack(f'<{len(values)}i', *sorted(values)))
            out = 0  # Native void result is unused by the caller.
        else:
            return False
        # Host library semantics apply only after exact loaded callsite binding.
        start = next(start for start, (end, _) in self.allowed.items() if start <= lr-4 < end)
        end, expected = self.allowed[start]
        if self.snapshot(self.base+start, end-start) != expected:
            raise SourceUnavailable('payroll library caller source changed')
        expected_stub = os.pread(self.image.fileno(), 12, ffp.ARM_SLICE+at)
        if self.snapshot(self.base+at, 12) != expected_stub:
            raise SourceUnavailable('payroll host-library binding changed')
        vm.reg_write(arm.UC_ARM64_REG_X0, out)
        vm.reg_write(arm.UC_ARM64_REG_PC, self.base+lr)
        return True

    def _instruction(self, vm, pc, size, user):
        if self.instructions >= MAX_INSTRUCTIONS or time.monotonic() >= self.deadline:
            raise SourceUnavailable('payroll instruction/time bound')
        at = pc-self.base
        if self._library(vm, at):
            self.instructions += 1
            return
        if at in (0x4AEF0E0, 0x4AEEFD8):
            raise SourceUnavailable('native thread/HUMAN payroll refresh route is unproved')
        if at == 0xE830E4:
            if [vm.reg_read(arm.UC_ARM64_REG_X0+i) for i in range(3)] != [self.finance, self.club, 0]:
                raise SourceUnavailable('payroll producer entry arguments changed')
            self._club_rosters(self.club)
        elif at == 0xE08DC4:
            self._club(vm.reg_read(arm.UC_ARM64_REG_X0))
            reducer._vector(self.snapshot, vm.reg_read(arm.UC_ARM64_REG_X0)+0x118,
                            limit=4096)
        elif at == 0xE08E44:
            linked = vm.reg_read(arm.UC_ARM64_REG_X22)
            if linked:
                self._club(linked)
        elif at == 0xE08E4C:
            reducer._vector(self.snapshot, vm.reg_read(arm.UC_ARM64_REG_X8)+0x30,
                            limit=4096)
        elif at in (0xE08E70, 0xE08EE8):
            self._team(vm.reg_read(arm.UC_ARM64_REG_X27 if at == 0xE08E70 else arm.UC_ARM64_REG_X24))
        elif at == 0xE833A0:
            finance = vm.reg_read(arm.UC_ARM64_REG_X0)
            world.typed(self.snapshot, self.base, finance, 'club_finance')
        elif at == 0xE833AC:
            self._club_rosters(vm.reg_read(arm.UC_ARM64_REG_X23))
        elif at in (0x14F78A0, 0x14F928C):
            raise SourceUnavailable('additional payroll rule owner specialization is unproved')
        elif at == 0x13E798C:
            nation = reducer._address(vm.reg_read(arm.UC_ARM64_REG_X0))
            world.typed(self.snapshot, self.base, nation, 'nation')
            table = database.table(self.snapshot, self.base, 'nations')
            index, native = struct.unpack('<II', self.snapshot(nation+8, 8))
            if (not native or index >= table['count']
                    or players.u64(self.snapshot(table['start']+index*8, 8)) != nation):
                raise SourceUnavailable('payroll rule NATION canonical identity changed')
        elif at in (0xD09BD0,):
            primary = vm.reg_read(arm.UC_ARM64_REG_X0)
            self._primary(primary)
            holder = players.u64(self.snapshot(primary+0xF0, 8))
            if holder:
                reducer._vector(self.snapshot, reducer._address(holder), limit=4096)
        elif at == 0xD8788C:
            self._contract(vm.reg_read(arm.UC_ARM64_REG_X0))
        elif at == 0xE89018:
            if [vm.reg_read(arm.UC_ARM64_REG_X0+i) for i in range(2)] != [self.finance, self.club]:
                raise SourceUnavailable('payroll event accounting owner changed')
            primary = vm.reg_read(arm.UC_ARM64_REG_X2)
            if primary:
                self._primary(primary)
        elif at == 0x1FFE24C:
            service = players.u64(self.snapshot(self.base+0x56D2B10, 8))
            world.typed(self.snapshot, self.base, reducer._address(service), 'game_club_finance')
            if [vm.reg_read(arm.UC_ARM64_REG_X0+i) for i in range(2)] != [service, self.club]:
                raise SourceUnavailable('payroll base-service adjustment arguments changed')
            manager = offers._manager(self.snapshot, self.base)
            first, last = reducer._vector(self.snapshot, manager+0xF0, limit=100_000)
            for (record,) in struct.iter_unpack('<Q', _chunks(self.snapshot, first, last-first)):
                owner = players.u64(self.snapshot(reducer._address(record)+8, 8))
                if owner:
                    self._club(owner)
        elif at == 0x1FE8AF8:
            self._prepare_reducer(vm)
        reducer._ReducerCPU._instruction(self, vm, pc, size, user)

    def _block(self, vm, address, size, user):
        if time.monotonic() >= self.deadline:
            raise SourceUnavailable('payroll execution time bound')


def calculate(read, base, image_stamp, *, club, lifetime, recompute=True, total_spending=True):
    """Recompute E830E4(w2=0), then read E83ED0(w3=1); never run FM.

    With recompute=False the operation enters the actual native getter gate,
    which remains unavailable at its unproved native thread identity call.
    total_spending controls native w2: True selects814, False selects810.
    Source/layout/owner/unknown failures raise SourceUnavailable/ValueError.
    """
    reducer._address(base)
    reducer._address(club)
    if type(recompute) is not bool or type(total_spending) is not bool or not callable(lifetime):
        raise SourceUnavailable('invalid payroll controls or missing lifetime reader')
    before = lifetime()
    if before is None:
        raise SourceUnavailable('payroll lifetime unavailable')
    remaining = [MAX_READ_BYTES, MAX_READ_CALLS]
    deadline = time.monotonic()+25

    def bounded_read(address, count):
        if (type(address) is not int or type(count) is not int or address < 4096
                or not 0 <= count <= 16384 or address+count >= 1 << 64):
            raise SourceUnavailable('invalid payroll source read')
        remaining[0] -= count
        remaining[1] -= 1
        if min(remaining) < 0 or time.monotonic() >= deadline:
            raise SourceUnavailable('payroll source read bound')
        return read(address, count)

    snapshot = world.ReadSet(bounded_read)
    reducer._verified_image(tuple(image_stamp))
    world.typed(snapshot, base, club, 'club')
    clubs = database.table(snapshot, base, 'clubs')
    index, native = struct.unpack('<II', snapshot(club+8, 8))
    if not native:
        raise SourceUnavailable('invalid payroll club identity')
    database.club_membership(snapshot, base, clubs, index, club)
    finance = reducer._address(players.u64(snapshot(club+0x150, 8)))
    world.typed(snapshot, base, finance, 'club_finance')
    with open(image_stamp[0], 'rb') as image:
        stat = os.fstat(image.fileno())
        stamp = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
        if tuple(image_stamp[1:]) != stamp:
            raise SourceUnavailable('payroll pinned image changed')
        cpu = _PayrollCPU(snapshot, bounded_read, base, image, finance, club)
        try:
            if recompute:
                cpu.run(0xE830E4, finance, club, 0)
            raw = cpu.run(0xE83ED0, finance, club, int(total_spending), int(recompute))
            current = struct.unpack('<2i', cpu.local_read(finance+0x810, 8))
            pending = (struct.unpack('<4i', cpu.local_read(finance+0x818, 16))
                       if cpu.pending_reducer_ran else (None,)*4)
            result = PayrollResult(struct.unpack('<i', struct.pack('<I', raw & 0xFFFFFFFF))[0],
                                   *current, *pending, cpu.pending_reducer_ran,
                                   'host_recomputed_full_E830E4' if recompute else 'native_getter_gate',
                                   'not_reproduced; explicit host recomputation' if recompute else 'unproved')
            if lifetime() != before:
                raise SourceUnavailable('payroll process/save/plugin lifetime changed')
            cpu.verify()
            snapshot.verify()
            after = os.fstat(image.fileno())
            if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != stamp:
                raise SourceUnavailable('payroll pinned source image changed')
            return result
        except uc.UcError as error:
            pc = cpu.vm.reg_read(arm.UC_ARM64_REG_PC)-base
            raise SourceUnavailable(f'unsupported payroll guest operation at {pc:#x}: {cpu.source_failure or error}') from error
        finally:
            cpu.close()
