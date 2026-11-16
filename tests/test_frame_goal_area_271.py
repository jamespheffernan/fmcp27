"""27.0.1 and the native goal area of the current-match frame: the frame constructor.

Build 27.0.1 re-compiled the frame constructor 0x4AB3218 as 0x498FA58 (13,564 instructions) with
its helpers inlined. What `frame_attacked_goal_basis` and `native_motion_world_basis` take from the
pinned build's code is established on 27.0.1 by running both builds' code in the static VM over
the same synthetic inputs (the plugin files alone, no game):

* the engine period into frame +0x3C: 27.0.0 0x4AB3360..0x4AB3418 (calls 0x4ABCDBC) against 27.0.1
  0x498FD08..0x498FF74;
* the kicking-upfield byte into frame +0x82: 27.0.0 0x4AB35A8..0x4AB360C (calls 0x4ABD7E8) against
  27.0.1 0x49901D0..0x49902F0;
* the endpoint producer 0x4ABD940 against 0x49B2744, whole functions;
* the per-entity update (producer, compare, entity copy): 27.0.0 0x4AB4DF8..0x4AB4E80 against each
  of the seven copies inlined in 0x498FA58 and the standalone 0x499D6FC;
* the delta applier's entity copy: 27.0.0 0x4AB645C..0x4AB6484 against 27.0.1 0x499F070..0x499F0A8.

A segment runs from its first instruction to its stop address with the registers and stack slots
the function holds there (each is named where it is set). The reviewed entries are in
`fmdb/data/address_overrides.json` under the 27.0.1 plugin's sha256.
"""
from __future__ import annotations

import hashlib
import json
import random
import struct
from pathlib import Path

import pytest

BUILDS = Path('/Volumes/4TB Private/Offloaded/Agent Work/fmdb-runtime-research/builds')
OLD, NEW = BUILDS / '27.0.0.2493426/game_plugin', BUILDS / '27.0.1.2503222/game_plugin'
SHA_271 = '68adfde2e0588458c1830cb7e688855d9c61237973a7eb7a105af5ac4ed112a4'
needs_builds = pytest.mark.skipif(not (OLD.is_file() and NEW.is_file()),
                                  reason='preserved 27.0.0 and 27.0.1 plugins not present')
MAX_READ = 16384                    # bridge.Bridge._read_memory refuses a longer read

# pinned address -> (27.0.1 address, span length there, sha256 of the reviewed 27.0.1 bytes)
REVIEWED = {
    'frame_attacked_goal_basis.py': {
        0x4ABCE24: (0x498FD30, 124, '8c250101f1bc3a97c71180773c1859897b4e1f2b4940851d291ab266686d25c3'),
        0x4AB33FC: (0x498FF64, 28, 'b92ad03475bb92bc8bc4a1ece6963e2722bffe81c7df78c89e920c488cf01d3c'),
        0x4ABD804: (0x49901D4, 36, '1246916926adfe03f8e70f4c8ad891a9daeb29546eea894b25d98657954703e9'),
        0x4AB35F4: (0x49902D4, 16, 'f32360034a626a635122e2fb8c5b48f57c7d0a49823dcb4bcae525916e902a93'),
    },
    'native_motion_world_basis.py': {
        0x4ABD9DC: (0x49B2744, 1480, '557392096b77441e331160946c940380cae3316051bb3bf1008a440879f0d8cc'),
        0x4AB1F78: (0x499D6FC, 6572, '2c526433651a15b061c9e2f3fa323b093db916be8b242d296a68e6f731a8e283'),
        0x4AB4DF8: (0x4990B0C, 10704, '3c1db698064dcad748a1c84c297898dd6c7619107ae697a5944eab0372e47c25'),
    },
}


def test_reviewed_entries_name_the_27_0_1_spans():
    """Every site the two modules guard has a reviewed value and guard for 27.0.1, each span short
    enough for one bounded read of the live process."""
    from fm_live_mcp import frame_attacked_goal_basis as goal, native_motion_world_basis as motion
    from fm_live_mcp.fmdb import address_map
    review = address_map.reviews(SHA_271)
    for rel, sites in REVIEWED.items():
        for pinned, (new, length, _sha) in sites.items():
            value = review['values'][f'{pinned:#x}']
            guard = review['guards'][rel][f'{pinned:#x}']
            assert int(value['value'], 16) == int(guard['new'], 16) == new
            assert guard.get('length', length) == length <= MAX_READ
            assert value['evidence'] and guard['evidence'] and guard['verdict'] in ('registers', 'shape')
    pinned_lengths = {at: len(raw) for module in (goal, motion) for at, raw in module.NATIVE_SPANS}
    assert pinned_lengths[0x4AB33FC] == 28 and pinned_lengths[0x4AB35F4] == 16      # same length on 27.0.1
    assert set(REVIEWED['native_motion_world_basis.py']) < set(pinned_lengths)


@needs_builds
def test_reviewed_spans_are_the_bytes_that_were_reviewed():
    from fm_live_mcp.fmdb.image import PluginImage
    image = PluginImage.load(NEW, verify=False)
    for sites in REVIEWED.values():
        for pinned, (new, length, sha) in sites.items():
            assert hashlib.sha256(image.file_bytes(new, length)).hexdigest() == sha, hex(pinned)


def test_pinned_updater_span_is_the_pinned_code():
    """The span added for the per-entity updater ends with its call of the entity copy 0x4AB1F78
    and holds its call of the producer 0x4ABD940."""
    from fm_live_mcp import native_motion_world_basis as motion
    spans = dict(motion.NATIVE_SPANS)
    raw, at = spans[0x4AB4DF8], 0x4AB4DF8
    words = struct.unpack(f'<{len(raw) // 4}I', raw)

    def target(k):
        off = words[k] & 0x3FFFFFF
        return at + 4 * k + 4 * (off - (off & 0x2000000) * 2)
    calls = [target(k) for k, w in enumerate(words) if w >> 26 == 0x25]
    assert calls == [0x4ABD940, 0x4AB30DC, 0x4AB5758, 0x4AB1F78] and len(raw) == 0x4AB4E80 - at


# --------------------------------------------------------------------------- segment emulation
class Machine:
    """One build's plugin in the static VM, run between two addresses."""

    def __init__(self, path):
        from test_match_rating_builds import _static_vm
        from fm_live_mcp.fmdb import vm as vmmod
        self.v, self.base, self.b = _static_vm(path)
        self.uc = self.v.uc
        self.stack = vmmod.STACK + vmmod.STACK_SIZE - 0x8000
        self.trace = []

    def static(self, size):
        return self.v._static(bytes(size))

    def write(self, at, raw):
        self.uc.mem_write(at, bytes(raw))

    def read(self, at, n):
        return bytes(self.uc.mem_read(at, n))

    def stub(self, rva, result=None):
        """Return at once from the function at rva (x0 = result() when given)."""
        from unicorn import UC_HOOK_CODE, arm64_const as A

        def hook(uc, address, size, user):
            self.trace.append(rva)
            if result is not None:
                uc.reg_write(A.UC_ARM64_REG_X0, result())
            uc.reg_write(A.UC_ARM64_REG_PC, uc.reg_read(A.UC_ARM64_REG_LR))
        self.uc.hook_add(UC_HOOK_CODE, hook, begin=self.base + rva, end=self.base + rva)

    def run(self, start, stop, regs, *, sp=None, count=200000):
        from unicorn import UcError, arm64_const as A
        uc, v = self.uc, self.v
        v._stop = v._pending = None
        v._icount = 0
        self.trace = []
        for k in range(31):
            uc.reg_write(getattr(A, f'UC_ARM64_REG_X{k}'), 0)
        uc.reg_write(A.UC_ARM64_REG_SP, self.stack if sp is None else sp)
        for name, value in regs.items():
            uc.reg_write(getattr(A, f'UC_ARM64_REG_{name.upper()}'), value & (2**64 - 1))
        try:
            uc.emu_start(self.base + start, self.base + stop, count=count)
        except UcError as exc:
            raise AssertionError(f'cpu fault {exc} at {uc.reg_read(A.UC_ARM64_REG_PC) - self.base:#x}') from None
        assert v._stop is None, (v._stop.reason, v._stop.detail)
        assert uc.reg_read(A.UC_ARM64_REG_PC) - self.base == stop

    def call(self, rva, args):
        return self.v.call(self.base + rva, args)[0]


# --------------------------------------------------------------------------- motion to entity
PLAYER, ROWS = 0x400, 1200
KINDS = ('ring', 'buffer', 'alt_clock', 'last_row', 'previous_tick', 'previous_tick_last_row')


def _motion_cases(seed, n):
    """(start, end, tick, alt clock, previous-tick parameter, path, seed): the paths of the
    producer that read stored rows (the generation path needs a whole match and is not run)."""
    rng = random.Random(seed)
    out = []
    for k in range(n):
        tick, kind = rng.randint(2, 200000), KINDS[k % len(KINDS)]
        previous = rng.choice([0.0, -1.0, rng.uniform(0.01, 0.99)])
        if kind == 'ring':                                    # start after the tick: the resident ring
            start = tick + rng.randint(1, 5000)
            end = rng.choice([-1, start + rng.randint(0, 1000)])
        elif kind == 'buffer':                                # start <= tick <= end
            start, end = tick - rng.randint(0, ROWS - 1), tick + rng.randint(0, 2000)
        elif kind == 'alt_clock':                             # negative end, the +0xD4 clock at or after the tick
            start, end = tick - rng.randint(0, ROWS - 1), -rng.randint(1, 50)
        elif kind == 'last_row':                              # 0 <= end < tick: the last buffered row
            start = tick - rng.randint(1, ROWS - 1)
            end = rng.randint(start, tick - 1)
        elif kind == 'previous_tick':                         # start == tick - 1 with a positive parameter
            start, end, previous = tick - 1, tick + rng.randint(0, 2000), rng.uniform(0.01, 0.99)
        else:
            start, end, previous = tick - 1, tick - 1, rng.uniform(0.01, 0.99)
        out.append((start, end, tick, tick + rng.randint(0, 100), previous, kind, rng.random()))
    return out


def _row(rng):
    """One 32-byte motion row: xyz, a word the frame compares as a float, two u16, a byte."""
    return struct.pack('<3f4sfHHB7s', rng.uniform(-60, 60), rng.uniform(-60, 60), rng.uniform(0, 3),
                       rng.randbytes(4), rng.uniform(-4, 4), rng.randrange(65536), rng.randrange(65536),
                       rng.randrange(256), rng.randbytes(7))


def _fill_player(m, player, buffer, case):
    start, end, _tick, alt, previous, _kind, seed = case
    rng = random.Random(seed)
    body = bytearray(rng.randbytes(PLAYER))
    struct.pack_into('<i', body, 0x200, start)                # motion +0x180
    struct.pack_into('<f', body, 0x204, previous)
    struct.pack_into('<i', body, 0x208, end)                  # motion +0x188
    struct.pack_into('<i', body, 0xD4, alt)                   # motion +0x54
    struct.pack_into('<Q', body, 0x170, buffer)               # motion +0xF0
    body[0x180:0x200] = b''.join(_row(rng) for _ in range(4))             # the resident ring
    body[0x120:0x140] = _row(rng)                                         # the previous-tick sample
    m.write(player, body)
    m.write(buffer, b''.join(_row(rng) for _ in range(ROWS)))


@pytest.mark.slow
@needs_builds
@pytest.mark.parametrize('seed', [1, 2])
def test_endpoint_producer_is_equal_on_both_builds(seed):
    """0x4ABD940 and 0x49B2744 fill the same packet (count, samples at +0x10 + 32*i: xyz, the
    parameter, the motion word, two halved bytes) for 600 synthetic players per seed."""
    cases = _motion_cases(seed, 600)
    packets = []
    for path, fn in ((OLD, 0x4ABD940), (NEW, 0x49B2744)):
        m = Machine(path)
        player, buffer, match, packet = m.static(PLAYER), m.static(32 * ROWS), m.static(0x16000), m.static(0x60)
        out = []
        for case in cases:
            _fill_player(m, player, buffer, case)
            m.write(packet, b'\xaa' * 4 + bytes(0x5C))
            m.call(fn, (player, match, case[2], packet))
            out.append(m.read(packet, 0x60))
        packets.append(out)
    samples = 0
    for case, old, new in zip(cases, *packets):
        assert old == new, case
        count = struct.unpack_from('<i', new)[0]
        start, _end, tick, _alt, previous = case[:5]
        assert count == (2 if start == tick - 1 and previous > 0 else 1)   # a previous-tick sample first
        assert struct.unpack_from('<f', new, 0x10 + 32 * (count - 1) + 0x10)[0] == 1.0     # the endpoint sample
        samples += count
    assert samples >= 600 + 200


# (first instruction after the entity lookup, address after the entity copy, player register,
#  entity register, tick register or None when the copy loads it from [sp,#0x178], stack slots)
PACKET, RECORD = 0x5D0, 0x1C0
SLOTS_A = {0x130: PACKET + 0x10, 0x128: PACKET + 0x29}                          # stored at 0x4990FD0
SLOTS_B = {0x130: PACKET + 0x10, 0x128: PACKET + 0x20, 0x110: PACKET + 0x29}    # stored at 0x4991F3C, 0x4991FA8
INLINED = (
    (0x4990B30, 0x4990CD4, 'x24', 'x19', 'x25', {}),
    (0x4991028, 0x49911D8, 'x25', 'x21', None, SLOTS_A),
    (0x499150C, 0x49916BC, 'x25', 'x21', None, SLOTS_A),
    (0x4992430, 0x49925E8, 'x28', 'x19', None, SLOTS_B),
    (0x4992910, 0x4992AC8, 'x28', 'x19', None, SLOTS_B),
    (0x4992DF8, 0x4992FB0, 'x28', 'x19', None, SLOTS_B),
    (0x4993320, 0x49934DC, 'x28', 'x22', None, SLOTS_B),
)
UNCHECKED = list(range(0x14, 0x20)) + [s + k for s in (0x20, 0x40)
                                       for k in list(range(0xC, 0x10)) + list(range(0x1A, 0x20))]


def _reference_updates(cases):
    """27.0.0: the per-entity updater from after its entity lookup (0x4AB4DF8) to after its call of
    the entity copy (0x4AB4E80), the delta writer 0x4AB5758 stubbed, the stack pre-set to 0xAA."""
    m = Machine(OLD)
    player, buffer, match, entity, frame, ctx = (m.static(n) for n in (PLAYER, 32 * ROWS, 0x16000, 0x80, 0x420, 0x40))
    m.stub(0x4AB5758)
    sp, out = m.stack, []
    for case in cases:
        _fill_player(m, player, buffer, case)
        m.write(entity, b'\x55' * 0x80)
        m.write(frame, bytes(0x420))
        m.write(ctx, struct.pack('<Q', match) + bytes(0x20) + struct.pack('<i', case[2]))
        m.write(sp, b'\xaa' * 0x200)
        m.run(0x4AB4DF8, 0x4AB4E80, {'x0': frame, 'x1': 1, 'x2': player, 'x3': ctx, 'x19': entity, 'x29': sp + 0xA0})
        assert m.trace == [0x4AB5758]                         # the entity differed: a delta was written
        out.append((m.read(sp + 0x10, 0x50), m.read(entity, 0x80)))
    return out


def _equal_entity(packet, rng):
    """An entity the frame's compare finds equal to the packet (count; per sample xyz, parameter,
    word, two bytes) with every byte the compare does not read changed: the copy must restore them."""
    body = bytearray(b'\x55' * 0x80)
    body[0x10:0x60] = packet
    for at in UNCHECKED:
        body[at] ^= rng.randrange(1, 256)
    return bytes(body)


@pytest.mark.slow
@needs_builds
def test_every_inlined_entity_update_equals_the_pinned_updater():
    """Each of the seven copies of the per-entity update inlined in 0x498FA58, and the standalone
    0x499D6FC up to its entity copy, builds the packet 27.0.0 builds and copies all 0x50 bytes of it
    to entity +0x10, for 600 synthetic players each. The entity is pre-set to compare equal (the
    delta blocks, which need the frame's stream, are not run); the copy is shown by the bytes the
    compare does not read."""
    cases = _motion_cases(3, 600)
    reference = _reference_updates(cases)
    m = Machine(NEW)
    player, buffer, match, entity, frame, table, ctx = (
        m.static(n) for n in (PLAYER, 32 * ROWS, 0x16000, 0x80, 0x420, 0x40, 0x40))
    sp, runs = m.stack, 0
    for copy in INLINED + (None,):
        for case, (packet, want) in zip(cases, reference):
            _fill_player(m, player, buffer, case)
            m.write(entity, _equal_entity(packet, random.Random(case[6] + 2)))
            m.write(frame, bytes(0x420))                      # frame +0x414 clear: not a forced full frame
            if copy is None:
                m.write(table, struct.pack('<QQ', 0, entity))
                m.write(frame, struct.pack('<Q', table))
                m.write(frame + 0x26, b'\x02')
                m.write(ctx, struct.pack('<Q', match) + bytes(0x20) + struct.pack('<i', case[2]))
                m.write(sp, b'\xaa' * 0x200)
                m.run(0x499D6FC, 0x499D854, {'x0': frame, 'x1': 1, 'x2': player, 'x3': ctx}, sp=sp + 0x100)
            else:
                start, stop, player_reg, entity_reg, tick_reg, slots = copy
                m.write(sp, b'\xaa' * 0x700)
                for at, value in slots.items():
                    m.write(sp + at, struct.pack('<Q', sp + value))
                m.write(sp + 0x138, struct.pack('<Q', frame))               # stored at 0x498FB54
                m.write(sp + 0x178, struct.pack('<q', case[2]))             # stored at 0x4990B08
                regs = {'x20': frame, 'x27': sp + RECORD, player_reg: player, entity_reg: entity}
                if tick_reg:
                    regs[tick_reg] = case[2]
                m.run(start, stop, regs)
                assert m.read(sp + PACKET, 0x50) == packet, (hex(start), case)
            assert m.read(entity, 0x80) == want, (copy and hex(copy[0]), case)
            runs += 1
    assert runs == 8 * 600


@pytest.mark.slow
@needs_builds
def test_delta_applier_entity_copy_is_equal_on_both_builds():
    """The applier reads (index, packet) from a delta and copies the packet to entity +0x10 when the
    index is inside the frame's entity table and the entity exists: 27.0.0 through 0x4AB1F78,
    27.0.1 inline. 400 packets and indexes, the record read itself not run."""
    rng = random.Random(11)
    cases = [(rng.choice([-3, 0, 1, 2, 3, 5]), rng.choice([0, 2, 3, 4]), rng.random() < 0.85, rng.randbytes(0x50),
              rng.randbytes(0x80)) for _ in range(400)]
    results = []
    for path in (OLD, NEW):
        m = Machine(path)
        frame, table, entity = m.static(0x420), m.static(0x40), m.static(0x80)
        sp, out = m.stack, []
        for index, count, present, packet, before in cases:
            m.write(table, b''.join(struct.pack('<Q', entity if present else 0) for _ in range(8)))
            m.write(frame, struct.pack('<Q', table) + bytes(0x418))
            m.write(frame + 0x26, struct.pack('<b', count))
            m.write(entity, before)
            m.write(sp, bytes(0x200))
            if path == OLD:
                m.write(sp + 0x77, struct.pack('<b', index))
                m.write(sp + 0x80, packet)
                m.run(0x4AB645C, 0x4AB6484, {'x20': frame})
            else:
                m.write(sp + 0xD1, struct.pack('<b', index))
                m.write(sp + 0xE0, packet)
                m.run(0x499F070, 0x499F0A8, {'x21': frame, 'x25': sp + 0xE0})     # x25 set at 0x499EAF8
            out.append(m.read(entity, 0x80))
        results.append(out)
    copied = 0
    for (index, count, present, packet, before), old, new in zip(cases, *results):
        assert old == new
        if 0 <= index < count and present:
            assert new == before[:0x10] + packet + before[0x60:]
            copied += 1
        else:
            assert new == before
    assert 100 < copied < 300


# --------------------------------------------------------------------------- period and upfield
MATCH = 0x16000


class _Constructor:
    """The frame constructor's period block and kicking-upfield block on one build."""

    def __init__(self, path):
        self.old = path == OLD
        self.m = m = Machine(path)
        self.match, self.frame, self.ctx = m.static(MATCH), m.static(0x420), m.static(0x40)
        self.objects = {name: m.static(0x800) for name in ('team0', 'team1', 'a', 'b', 'c')}
        holder, obj, vtable, self.record = (m.static(0x40) for _ in range(4))
        self.holder, self.answer = holder, 0
        # periods 4 and 5 ask an object at [[match+0x14E90]+0x18] through vtable +0x30
        virtual = 0x4AB1F78 if self.old else 0x49B2744            # a function these blocks never run
        m.write(holder + 0x18, struct.pack('<Q', obj))
        m.write(obj, struct.pack('<Q', vtable))
        m.write(vtable + 0x30, struct.pack('<Q', m.base + virtual))
        m.stub(virtual, lambda: self.answer)
        self.writers = (0x4AB42B0, 0x4AB47F4) if self.old else (0x4392254,)
        for writer in self.writers:
            m.stub(writer)                                        # the delta writers

    def load(self, world, frame, forced):
        m = self.m
        body = bytearray(world['match'])
        for at, name in ((0x15370, 'team0'), (0x15378, 'team1'), (0x153E0, 'a'), (0x153E8, 'c'),
                         (0x15418, world['upfield'])):
            struct.pack_into('<Q', body, at, self.objects[name])
        struct.pack_into('<Q', body, 0x15430, self.objects['b'] if world['has_b'] else 0)
        struct.pack_into('<Q', body, 0x14E90, self.holder)
        m.write(self.match, body)
        for name, at in self.objects.items():
            m.write(at, world[name])
        m.write(self.record, world['record'].ljust(2, b'\0'))
        self.answer = self.record if world['record'] else 0
        m.write(self.frame, frame[:0x414] + bytes([forced]) + frame[0x415:])
        m.write(self.ctx, world['ctx'])
        m.write(m.stack, bytes(0x1000))
        if not self.old:
            for at, value in ((0xB0, self.match + 0x14A04),       # stored at 0x498FAFC
                              (0xC0, self.match),                 # 0x498FB50
                              (0xC8, self.ctx),                   # 0x498FA7C
                              (0x138, self.frame)):               # 0x498FB54
                m.write(m.stack + at, struct.pack('<Q', value))

    def period(self):
        m, sp = self.m, self.m.stack
        if self.old:
            m.run(0x4AB3360, 0x4AB3418, {'x20': self.frame, 'x21': self.match, 'x22': self.ctx, 'x28': sp + 0x98})
        else:
            m.run(0x498FD08, 0x498FF74, {'x20': self.frame, 'x21': self.match + 0x152A0, 'x27': sp + RECORD})
        return m.read(self.frame + 0x34, 13), m.read(self.ctx + 4, 4), any(t in self.writers for t in m.trace)

    def upfield(self):
        m, sp = self.m, self.m.stack
        if self.old:
            m.run(0x4AB35A8, 0x4AB360C, {'x20': self.frame, 'x21': self.match, 'x22': self.ctx})
        else:
            m.run(0x49901D0, 0x49902F0, {'x20': self.frame, 'x19': self.match + 0x12A30, 'x27': sp + RECORD,
                                          'x28': self.match})
        return m.read(self.frame + 0x80, 3), m.read(self.ctx + 0x18, 3), any(t in self.writers for t in m.trace)


def _worlds(seed, n):
    rng = random.Random(seed)
    for k in range(n):
        body = bytearray(rng.randbytes(MATCH))
        body[0x1555A] = k & 0xFF                                  # the engine period: every code
        struct.pack_into('<i', body, 0x154DC, rng.choice([0, 1, rng.randrange(1, 200000)]))
        struct.pack_into('<i', body, 0x15454, rng.randrange(0, 240 * 130))
        for at in (0x14A04, 0x12BA4):
            struct.pack_into('<f', body, at, rng.uniform(-60, 60))
        if rng.random() < 0.5:
            struct.pack_into('<I', body, 0x154F0, struct.unpack_from('<I', body, 0x154F0)[0] & ~0x304)
        if rng.random() < 0.6:
            struct.pack_into('<H', body, 0x12EC6, struct.unpack_from('<H', body, 0x12EC6)[0] & ~0x5D4)
        body[0x1555C] = rng.choice([0, 1, 2, 3, 5, rng.randrange(256)])
        body[0x15561] = rng.choice([0, 1, rng.randrange(256)])
        objects = {name: bytearray(rng.randbytes(0x800)) for name in ('team0', 'team1', 'a', 'b', 'c')}
        objects['a'][0x380] = rng.choice([0, 1, 2])
        objects['b'][0x139] = rng.choice([0, 0, 1, 2])
        struct.pack_into('<f', objects['c'], 0x27C, rng.uniform(0, 60))
        yield dict(match=bytes(body), upfield=rng.choice(['team0', 'team1']), has_b=rng.random() < 0.8,
                   ctx=rng.randbytes(0x40), frame=rng.randbytes(0x420),
                   record=rng.choice([b'', bytes([1, 0x80]), bytes([1, 0x05])]),
                   **{name: bytes(value) for name, value in objects.items()})


@pytest.mark.slow
@needs_builds
@pytest.mark.parametrize('block,at,size', [('period', 0x34, 13), ('upfield', 0x80, 3)])
def test_period_and_upfield_blocks_are_equal_on_both_builds(block, at, size):
    """512 synthetic matches (every period code twice), each with the frame forced, unchanged and
    changed: both builds leave the same bytes in the frame and the context, write a delta in the
    same cases, and the frame holds what the reader takes it for: +0x3C the engine period byte
    (match +0x1555A), +0x82 whether the kicking-upfield side (match +0x15418) is not the first side
    (match +0x15370)."""
    old, new = _Constructor(OLD), _Constructor(NEW)
    runs = 0
    for world in _worlds(5, 512):
        first = None
        for mode in ('forced', 'unchanged', 'changed'):
            frame = bytearray(world['frame'])
            if mode == 'unchanged':
                frame[at:at + size] = first
            results = []
            for side in (old, new):
                side.load(world, bytes(frame), 1 if mode == 'forced' else 0)
                results.append(getattr(side, block)())
            assert results[0] == results[1], (block, mode, world['match'][0x1555A])
            stored, _ctx, delta = results[1]
            assert delta is (mode != 'unchanged')
            if block == 'period':
                assert stored[8] == world['match'][0x1555A]
            else:
                assert stored[2] == (0 if world['upfield'] == 'team0' else 1)
            first = first or stored
            runs += 1
    assert runs == 512 * 3


def test_goal_area_section_runs_when_its_sites_resolve(monkeypatch):
    """With no unresolved site the optional section is not blocked: it calls the decoder."""
    from fm_live_mcp import address_book, current_frame_report as report, frame_attacked_goal_area
    monkeypatch.setattr(address_book, 'MAP', {'values': {}})
    monkeypatch.setattr(address_book, 'unresolved_sites', lambda: {})
    monkeypatch.setattr(frame_attacked_goal_area, 'capture', lambda read, base, bound, fixed_tick: ('captured', fixed_tick))
    report._goal_area_capture._blocked = None
    assert report._goal_area_capture(None, 0, {}, 7) == {'_captured': ('captured', 7)}
    assert not address_book.partial_tools({'frame': report.current_frame_report})


def test_overrides_file_is_valid_json_with_the_build_entry():
    from fm_live_mcp.fmdb.address_census import OVERRIDES_PATH
    doc = json.loads(OVERRIDES_PATH.read_text())
    assert doc['builds'][SHA_271]['version'] == '27.0.1.2503222'
