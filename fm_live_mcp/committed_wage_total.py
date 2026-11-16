"""Host-recomputed payroll plus the pinned native committed-wage common tail.

All guest instructions and writes use one owned VM. The original EAEB44
thread/HUMAN refresh admission is not entered or simulated: E830E4 is explicitly
recomputed first. The original common tail then calculates the total. V138's
separately proved zero branches are admitted only after full typed observation;
nonempty/unknown contributions reject rather than supplying a partial total.
"""
from dataclasses import dataclass
from ._os_compat import pread
import hashlib
import os
import struct
import time

from . import committed_wage_owner_source as owner
from . import committed_wage_payroll_core as payroll
from . import committed_wage_reduction as scope
from . import database, players, world

core, ffp, uc, arm = payroll.reducer, payroll.ffp, payroll.uc, payroll.arm
SourceUnavailable = core.SourceUnavailable


@dataclass(frozen=True)
class CommittedWageTotal:
    committed_signed32: int
    payroll_810: int
    payroll_814: int
    pending_818: int
    pending_81c: int
    pending_820: int
    pending_824: int
    owner_contribution: int
    basis: str = 'host_recomputed_payroll_and_native_common_tail'
    native_refresh_admission: str = 'not_entered_or_simulated'


class _TotalCPU(payroll._PayrollCPU):
    def __init__(self, snapshot, read_live, base, image, finance, club, context, lifetime):
        super().__init__(snapshot, read_live, base, image, finance, club)
        self.context, self.lifetime = context, lifetime
        self.owner_result = None
        self.owner_calls = 0
        start, size, digest = owner.SOURCE[-1]
        raw = pread(image.fileno(), size, ffp.arm_slice(image)+start)
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            raise SourceUnavailable('native committed-wage caller changed')
        self.allowed[start] = (start+size, raw)

    def _instruction(self, vm, pc, size, user):
        if pc-self.base == 0x1FEBC8C:
            if self.instructions >= payroll.MAX_INSTRUCTIONS or time.monotonic() >= self.deadline:
                raise SourceUnavailable('committed-wage execution bound')
            args = [vm.reg_read(arm.UC_ARM64_REG_X0+i) for i in range(5)]
            if args[:4] != [core._full_finance_service(self.snapshot, self.base), self.club, 0, 0]:
                raise SourceUnavailable('committed-wage v138 arguments changed')
            if vm.reg_read(arm.UC_ARM64_REG_LR) != self.base+0xEAEC84:
                raise SourceUnavailable('committed-wage v138 caller changed')
            if not ffp.SCRATCH <= args[4] <= ffp.SCRATCH+ffp.SCRATCH_SIZE-4:
                raise SourceUnavailable('committed-wage v138 output is not owned')
            result = owner.observe(self._selector_read, self.base, self.context, lifetime=self.lifetime)
            if (result.state != 'native_zero' or not result.complete_v138_branch
                    or result.native_return != 0 or result.out_amount != 0):
                raise SourceUnavailable('committed-wage owner contribution unavailable: '+result.reason)
            self.owner_result = result
            self.owner_calls += 1
            self.instructions += 1
            vm.mem_write(args[4], struct.pack('<i', result.out_amount))
            vm.reg_write(arm.UC_ARM64_REG_X0, result.native_return)
            vm.reg_write(arm.UC_ARM64_REG_PC, vm.reg_read(arm.UC_ARM64_REG_LR))
            return
        return super()._instruction(vm, pc, size, user)

    def common_tail(self):
        # This is an explicit suffix execution, not an invented thread result.
        # Registers are the actual EAEB44 prologue's CLUB/flag/finance values.
        self.vm.reg_write(arm.UC_ARM64_REG_X19, self.club)
        self.vm.reg_write(arm.UC_ARM64_REG_X20, 1)
        self.vm.reg_write(arm.UC_ARM64_REG_X21, self.finance)
        self.vm.reg_write(arm.UC_ARM64_REG_SP, ffp.SCRATCH+ffp.SCRATCH_SIZE-0x10000)
        self.vm.emu_start(self.base+0xEAEC2C, self.base+0xEAEC88, count=payroll.MAX_INSTRUCTIONS)
        if self.vm.reg_read(arm.UC_ARM64_REG_PC) != self.base+0xEAEC88 or self.owner_calls != 1:
            raise SourceUnavailable('committed-wage native common tail did not finish')
        return struct.unpack('<i', struct.pack('<I', self.vm.reg_read(arm.UC_ARM64_REG_X21)&0xFFFFFFFF))[0]


def calculate(read, base, image_stamp, *, club, lifetime):
    """Recompute payroll and committed common-tail arithmetic in one VM.

    The caller supplies a real FinancialLifetime reader. Its process/session
    verification remains caller-owned, and its assertions are checked against
    mapped UUID, loaded career/count/date and canonical CLUB inputs here.
    """
    core._address(base)
    core._address(club)
    if not callable(lifetime):
        raise SourceUnavailable('committed-wage lifetime reader required')
    first = scope._lifetime(lifetime(), base, image_stamp, club)
    deadline = time.monotonic()+30
    remaining = [128*1024*1024, 200000]

    def bounded(address, count):
        if (type(address) is not int or type(count) is not int or address < 4096
                or not 0 <= count <= 16384 or address+count >= 1 << 64):
            raise SourceUnavailable('invalid committed-wage source read')
        remaining[0] -= count
        remaining[1] -= 1
        if min(remaining) < 0 or time.monotonic() >= deadline:
            raise SourceUnavailable('committed-wage source read bound')
        return read(address, count)

    snapshot = world.ReadSet(bounded)
    core._verified_image(tuple(image_stamp))
    if players.macho_uuid(snapshot(base, 16384)) != first.plugin_uuid:
        raise SourceUnavailable('committed-wage mapped UUID changed')
    career, identity = world.loaded(snapshot, base)
    if (identity != first.world_identity or career['save_count'] != first.save_count
            or career['current_date'] != first.current_date):
        raise SourceUnavailable('committed-wage loaded career changed')
    world.typed(snapshot, base, club, 'club')
    actual = (club, *struct.unpack('<III', snapshot(club+8, 12)))
    if actual != first.club_identity or not actual[2]:
        raise SourceUnavailable('committed-wage selected CLUB changed')
    clubs = database.table(snapshot, base, 'clubs')
    database.club_membership(snapshot, base, clubs, actual[1], club)
    finance = core._address(players.u64(snapshot(club+0x150, 8)))
    world.typed(snapshot, base, finance, 'club_finance')
    date = snapshot(base+world.CURRENT_DATE, 4)
    identity_text = repr((first.process_identity, first.world_identity, first.save_count, first.current_date))
    context = owner.Context(first.process_identity[0], hashlib.sha256(identity_text.encode()).hexdigest(),
                            hashlib.sha256(repr(first).encode()).hexdigest(), owner.PLUGIN_SHA,
                            date, owner.CanonicalRef(*actual))

    def check_lifetime():
        if scope._lifetime(lifetime(), base, image_stamp, club) != first:
            raise SourceUnavailable('committed-wage process/session/career lifetime changed')
        return context

    with open(image_stamp[0], 'rb') as image:
        stat = os.fstat(image.fileno())
        stamp = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
        if tuple(image_stamp[1:]) != stamp:
            raise SourceUnavailable('committed-wage pinned image changed')
        cpu = _TotalCPU(snapshot, bounded, base, image, finance, club, context, check_lifetime)
        try:
            cpu.run(0xE830E4, finance, club, 0)
            committed = cpu.common_tail()
            fields = struct.unpack('<6i', cpu.local_read(finance+0x810, 24))
            result = CommittedWageTotal(committed, *fields, cpu.owner_result.native_return)
            check_lifetime()
            cpu.verify()
            snapshot.verify()
            final = os.fstat(image.fileno())
            if (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns) != stamp:
                raise SourceUnavailable('committed-wage image changed during calculation')
            return result
        except uc.UcError as error:
            at = cpu.vm.reg_read(arm.UC_ARM64_REG_PC)-base
            raise SourceUnavailable(f'unsupported committed-wage operation at {at:#x}: {cpu.source_failure or error}') from error
        finally:
            cpu.close()
