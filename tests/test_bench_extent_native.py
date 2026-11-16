"""Where the bench ends in the editable selection: the game's own code, run from both builds' files.

docs/current-formation-boundary.md states the rule; this file is its proof without a game. Each
block below is the unmodified code of build 27.0.0.2493426 or 27.0.1.2503222, emulated in the
reader's static VM over synthetic objects (a FIXTURE with the real vtable of the build, a TEAM,
a tactic edit session, the selection screen's model):

* the session constructor, the session evaluator and a third session writer store
  11 + min(named substitutes of the fixture's rule code for the side, the fixture's ceiling) at
  session+35B0/35B1, and the selection screen's model stores the same minimum at model+5194;
* the model's fixture is 17743B8(team, 365), and that function returns the pointer cached at
  [[team+A0]+B8] as it is;
* the screen labels slot i a substitute exactly while 11 <= i < 11 + model+5194;
* the evaluator's slot loop counts starters, substitutes and the rest by the same end, and the
  reader's team sheet labels the same slots.

All need the two preserved plugins and skip without them.
"""
import random
import struct

import pytest

from fm_live_mcp import fixture_rules, live_team_sheet_source as source

from test_live_team_sheet_source import fixture, inspect  # noqa: F401  (the synthetic session)
from test_match_rating_builds import NEW, OLD, _static_vm, needs_builds

A = {
    'old': dict(fixture_vtable=0x5672C88, ceiling=0x3CFAB7C, named=0x48F9CFC,
                evaluator=(0x22C3A8C, 0x22C3AC4), evaluator_rewrite=(0x22C4098, 0x22C40A8),
                constructor=(0x22BFD0C, 0x22BFD48), constructor_zero=(0x22BFB28, 0x22BFB34),
                constructor_skip=0x22BFCB8, third_writer=(0x22C08A0, 0x22C08E8),
                model=(0x2E4DBE4, 0x2E4DC20), model_fixture=(0x2E4D29C, 0x2E4D2AC), model_reload=0x2E4D930,
                model_default=(0x2E4CFE8, 0x2E4CFF0), next_fixture=0x17743B8,
                next_fixture_cached=(0x1774410, 0x177471C), label=(0x535DA0, 0x535DC4, 0x535DF4),
                loop=(0x22C4300, 0x22C43D0), person_of_slot=0x2B56664, per_slot=0x22C5ED4),
    'new': dict(fixture_vtable=0x570EC88, ceiling=0x3D10F08, named=0x49FF358,
                evaluator=(0x22D2C8C, 0x22D2CC4), evaluator_rewrite=(0x22D3298, 0x22D32A8),
                constructor=(0x22CEF4C, 0x22CEF88), constructor_zero=(0x22CED68, 0x22CED74),
                constructor_skip=0x22CEEF8, third_writer=(0x22CFAE0, 0x22CFB28),
                model=(0x2E5CD1C, 0x2E5CD58), model_fixture=(0x2E5C3D4, 0x2E5C3E4), model_reload=0x2E5CA68,
                model_default=(0x2E5C120, 0x2E5C128), next_fixture=0x177E808,
                next_fixture_cached=(0x177E860, 0x177EB6C), label=(0x536824, 0x536848, 0x536878),
                loop=(0x22D3500, 0x22D35D0), person_of_slot=None, per_slot=None),
}
CODES = list(range(0, 91)) + [-128, -1, 91, 127]


class Machine:
    """One build's static VM with the synthetic objects, and a runner for code blocks."""

    def __init__(self, build):
        import unicorn.arm64_const as const
        from fm_live_mcp.fmdb import vm as vmmod
        self.const, self.vmmod, self.a = const, vmmod, A[build]
        self.v, self.base, self.binary = _static_vm(OLD if build == 'old' else NEW)
        self.team, self.other = self.v._static(bytes(0x100)), self.v._static(bytes(0x100))
        self.holder = self.v._static(bytes(0x100))
        self.fixture = self.v._static(bytes(0x80))
        self.session = self.v._static(bytes(0x3800))
        self.model = self.v._static(bytes(0x5200))
        self.out = self.v._static(bytes(0x400))
        self.v.uc.mem_write(self.fixture, struct.pack('<Q', self.base + self.a['fixture_vtable']))
        assert self.v.read_u64(self.base + self.a['fixture_vtable'] + 0xB0) == self.base + self.a['ceiling']
        self._hooks = []

    def reg(self, name):
        return self.v.uc.reg_read(getattr(self.const, f'UC_ARM64_REG_{name}'))

    def put(self, address, fmt, *values):
        self.v.uc.mem_write(address, struct.pack(fmt, *values))

    def get(self, address, fmt):
        return struct.unpack(fmt, bytes(self.v.uc.mem_read(address, struct.calcsize(fmt))))

    def on(self, rva, callback):
        """Replace the function at rva: callback(machine) returns x0, and control returns to LR."""
        from unicorn import UC_HOOK_CODE

        def hook(uc, address, size, user):
            uc.reg_write(self.const.UC_ARM64_REG_X0, callback(self) & (2**64 - 1))
            uc.reg_write(self.const.UC_ARM64_REG_PC, uc.reg_read(self.const.UC_ARM64_REG_LR))
        self._hooks.append(self.v.uc.hook_add(UC_HOOK_CODE, hook, begin=self.base + rva, end=self.base + rva))

    def run(self, begin, end, stack=(), stops=(), **regs):
        """Run [begin, end) of the build's code with the named registers set; returns the RVA of
        the stop address reached when `stops` are given."""
        from unicorn import UC_HOOK_CODE
        v, uc, const = self.v, self.v.uc, self.const
        v._restore()
        v._stop = v._pending = None
        v._icount = 0
        for register in self.vmmod.INT_REGS:
            uc.reg_write(register, 0)
        for name, value in regs.items():
            uc.reg_write(getattr(const, f'UC_ARM64_REG_{name.upper()}'), value & (2**64 - 1))
        sp = self.vmmod.STACK + self.vmmod.STACK_SIZE - 0x2000
        uc.reg_write(const.UC_ARM64_REG_SP, sp)
        uc.mem_write(sp, bytes(0x100))
        for offset, value in stack:
            uc.mem_write(sp + offset, struct.pack('<Q', value))
        uc.reg_write(const.UC_ARM64_REG_LR, self.vmmod.TRAP)
        self.sp, reached, extra = sp, [], []
        for stop in stops:
            def hook(uc, address, size, user):
                reached.append(address - self.base)
                uc.emu_stop()
            extra.append(uc.hook_add(UC_HOOK_CODE, hook, begin=self.base + stop, end=self.base + stop))
        try:
            uc.emu_start(self.base + begin, self.base + end, count=100_000)
        finally:
            for handle in extra:
                uc.hook_del(handle)
        assert v._stop is None, (v._stop.reason, v._stop.detail)
        if stops:
            assert reached, f'neither stop reached; pc={uc.reg_read(const.UC_ARM64_REG_PC) - self.base:#x}'
            return reached[0]
        assert uc.reg_read(const.UC_ARM64_REG_PC) == self.base + end
        return None

    def set_fixture(self, code, away):
        home, guest = (self.other, self.team) if away else (self.team, self.other)
        self.put(self.fixture + 8, '<QQ', home, guest)
        self.put(self.fixture + 0x3E, '<b', code)
        return home

    def bl_target(self, rva):
        word = struct.unpack('<I', self.binary.image.file_bytes(rva, 4))[0]
        assert word >> 26 == 0x25, f'{rva:#x} is not a BL'
        offset = word & 0x3FFFFFF
        return rva + 4 * (offset - (1 << 26) if offset & (1 << 25) else offset)


@pytest.fixture(scope='module', params=['old', 'new'])
def machine(request):
    return Machine(request.param)


def _cap(code, away):
    return fixture_rules.substitutions(code, bool(away), 15)['named_substitute_cap']


@pytest.mark.slow
@needs_builds
def test_every_native_bench_end_is_eleven_plus_the_named_cap(machine):
    """The session constructor, the evaluator and the third writer store 11 + the cap, the
    selection screen's model stores the cap: every rule code the game's table has, the codes
    outside it, both sides."""
    m, a = machine, machine.a
    extent = m.session + 0x35B0
    for code in CODES:
        for away in (0, 1):
            home, want = m.set_fixture(code, away), _cap(code, away)
            m.put(extent, '<bb', 0, 0)
            m.run(*a['evaluator'], x8=home, x9=m.team, x21=m.fixture, x28=m.session + 0x3000)
            assert m.get(extent, '<bb') == (11 + want, 11 + want), ('evaluator', code, away)
            m.put(extent, '<bb', 0, 0)
            m.run(*a['constructor'], x22=m.fixture, x23=home, x24=m.team, x27=m.session + 0x3000)
            assert m.get(extent, '<bb') == (11 + want, 11 + want), ('constructor', code, away)
            m.put(extent, '<bb', 0, 0)
            m.run(*a['third_writer'], x9=home, x8=m.team, x22=m.fixture, x21=m.session)
            assert m.get(extent, '<bb') == (0, 11 + want), ('third writer', code, away)
            m.put(m.model + 0x5194, '<b', 15)
            m.run(*a['model'], stack=((0, m.model + 0x5000),), x28=m.fixture, x20=m.team)
            assert m.get(m.model + 0x5194, '<b') == (want,), ('model', code, away)


@pytest.mark.slow
@needs_builds
def test_without_a_fixture_the_session_keeps_zero_and_the_model_keeps_fifteen(machine):
    """The constructor zeroes 35B0..35B6 and skips the store when no pending match was found; the
    model's constructor writes 15 and the model's block leaves it when there is no fixture."""
    m, a = machine, machine.a
    m.put(m.session + 0x35B0, '<Q', 0x1122334455667788)
    m.run(*a['constructor_zero'], x27=m.session + 0x3000)
    assert m.get(m.session + 0x35B0, '<7B') == (0,) * 7
    skip = struct.unpack('<I', m.binary.image.file_bytes(a['constructor_skip'], 4))[0]
    assert skip & 0xFF00001F == 0xB4000016                                     # cbz x22, ...
    target = a['constructor_skip'] + 4 * ((skip >> 5) & 0x7FFFF)
    assert target == a['constructor'][1]                                       # past both stores
    m.put(m.model + 0x5194, '<b', 0)
    m.run(*a['model_default'], x28=m.model + 0x5000)
    assert m.get(m.model + 0x5194, '<b') == (15,)
    m.run(*a['model'], stack=((0, m.model + 0x5000),), x28=0, x20=m.team)
    assert m.get(m.model + 0x5194, '<b') == (15,)


@pytest.mark.slow
@needs_builds
def test_the_models_fixture_is_the_teams_cached_next_fixture(machine):
    """2E4D29C calls 17743B8(team, 365) and keeps the result at [sp+8], which 2E4D930 loads into
    x28, the fixture of the model's block; 17743B8 returns [[team+A0]+B8] as it is for 365 days,
    and nothing when there is none and the caller is not on the game's thread."""
    m, a = machine, machine.a
    assert m.bl_target(a['model_fixture'][0] + 8) == a['next_fixture']
    seen = []
    m.on(a['next_fixture'], lambda mm: seen.append((mm.reg('X0'), mm.reg('X1') & 0xFFFFFFFF)) or 0x7777000)
    m.run(*a['model_fixture'], x1=m.team)
    assert seen == [(m.team, 365)]
    assert m.get(m.sp + 8, '<Q') == (0x7777000,)
    assert struct.unpack('<I', m.binary.image.file_bytes(a['model_reload'], 4))[0] == 0xF94007FC   # ldr x28,[sp,#8]
    m.v.uc.hook_del(m._hooks.pop())
    m.put(m.team + 0xA0, '<Q', m.holder)
    m.put(m.holder + 0xB8, '<Q', m.fixture)
    for days, thread in ((365, 1), (365, 0), (1000, 1)):
        m.run(*a['next_fixture_cached'], x20=m.team, x19=days, x8=thread)
        assert m.reg('X0') == m.fixture
    m.put(m.holder + 0xB8, '<Q', 0)
    m.run(*a['next_fixture_cached'], x20=m.team, x19=365, x8=0)
    assert m.reg('X0') == 0


@pytest.mark.slow
@needs_builds
def test_the_screen_labels_a_substitute_exactly_inside_the_models_count(machine):
    """535DA0: slot i gets the S<n> label (535DC4) while 11 <= i < 11 + model+5194 and the other
    index is -1, and the default text (535DF4) otherwise."""
    m, (begin, substitute, default) = machine, machine.a['label']
    for count in (0, 5, 7, 9, 12, 15):
        m.put(m.model + 0x5194, '<b', count)
        for slot in range(26):
            reached = m.run(begin, default + 4, stops=(substitute, default), x20=m.model, x21=slot,
                            x22=0xFFFFFFFF)
            assert (reached == substitute) == (11 <= slot < 11 + count), (count, slot)
        assert m.run(begin, default + 4, stops=(substitute, default), x20=m.model, x21=11, x22=3) == default


@pytest.mark.slow
@needs_builds
def test_the_evaluators_slot_loop_counts_what_the_team_sheet_labels(machine, fixture, monkeypatch):  # noqa: F811
    """22C4300..22C43D0 over 26 stored indices and a bench end: starters in out+2F6, substitutes
    in +2F7, people at or after the end in +2F9 (none in +2F8 while 35B0 equals 35B1), empty
    bench slots in w24. The reader's sheet over the same bytes gives the same counts and puts
    the bench category on the same slots."""
    m, a = machine, machine.a
    begin, end = a['loop']
    person, per_slot = m.bl_target(begin + 0x1C), m.bl_target(begin + 0xBC)
    if a['person_of_slot'] is not None:
        assert (person, per_slot) == (a['person_of_slot'], a['per_slot'])
    calls = []
    m.on(person, lambda mm: 0x5000 + 8 * mm.get(mm.reg('X0'), '<i')[0] if mm.get(mm.reg('X0'), '<i')[0] >= 0 else 0)
    m.on(per_slot, lambda mm: calls.append(mm.reg('X6') & 0xFF) or 0)
    memory, _, _, _, session, _ = fixture
    rng = random.Random(20261114)
    try:
        for _ in range(60):
            bench_end = rng.choice([11, 14, 16, 18, 20, 23, 26])
            indices = [rng.choice([-1, n, n]) for n in range(26)]
            m.put(m.session + 0x2200, '<26i', *indices)
            m.put(m.session + 0x3590, '<Q', m.team)
            m.put(m.session + 0x35B0, '<bb', bench_end, bench_end)
            m.v.uc.mem_write(m.out, bytes(0x400))
            del calls[:]
            m.run(begin, end, x19=m.session, x20=m.out, x28=m.session + 0x3000)
            starters, substitutes, between, after = m.get(m.out + 0x2F6, '<4B')
            empty_bench = m.reg('X24') & 0xFF
            memory.pack(session + 0x2200, '<26i', *indices)
            memory.pack(session + 0x35B0, '<bb', bench_end, bench_end)
            sheet = inspect(fixture)
            assert sheet['role_boundary_state'] == source.STORED_END
            assert (starters, substitutes) == (sheet['starting_count'], sheet['bench_count'])
            assert between == 0 and after == sheet['stored_nonnull_count'] - sheet['selected_count']
            assert empty_bench == sum(row['category'] == 'bench' and row['person'] is None for row in sheet['slots'])
            assert calls == [row['slot_index'] for row in sheet['slots']
                             if row['category'] in ('starting_position', 'bench') and row['person'] is not None]
    finally:
        while m._hooks:
            m.v.uc.hook_del(m._hooks.pop())


@pytest.mark.slow
@needs_builds
def test_the_evaluator_may_only_lower_the_stored_end_from_its_own_result(machine):
    """22C4098: the second store of 35B1 is 11 + min(w0, w24) of the same two calls (or 11 + a
    byte its own check produced), never read from elsewhere."""
    m = machine
    m.put(m.session + 0x35B0, '<bb', 20, 20)
    m.run(*m.a['evaluator_rewrite'], x0=7, x24=9, x28=m.session + 0x3000)
    assert m.get(m.session + 0x35B0, '<bb') == (20, 18)
