"""prepared_tactic_roles on 27.0.1: the two role-naming functions give the same label routes.

27.0.1 rewrote both functions the decoder's spans pin (0x4ad8094 -> 0x4a6cf04 and 0x4ad94b8 ->
0x4a6e4c8): the label-form flag accessor 0x4acf970 is inlined as a load of its global byte (0x5721990
-> 0x57BD9B8; the 14 direct references and 89 accessor calls of 27.0.0 are the 103 references of
27.0.1), the table object is spilled to the stack, and the blocks are laid out anew. The ordered
bit-test chain and every resource key are unchanged. These tests run both builds' unmodified
functions from the preserved plugin files and compare the ordered resource-key lookups and label
literals for every role word with one or two bits set, random dense words, both label forms (fourth
argument) and both values of the flag; and check the Python mirror against the native first key.
The reviewed span entries (address_overrides.json, builds.<27.0.1>) map each pinned span to its
counterpart; `test_reviewed_spans_pin_the_counterparts` checks them against both files."""
from __future__ import annotations

import itertools
import json
import random
import struct
from pathlib import Path

import pytest

BUILDS = Path('/Volumes/4TB Private/Offloaded/Agent Work/fmdb-runtime-research/builds')
OLD, NEW = BUILDS / '27.0.0.2493426/game_plugin', BUILDS / '27.0.1.2503222/game_plugin'
NEW_SHA256 = '68adfde2e0588458c1830cb7e688855d9c61237973a7eb7a105af5ac4ed112a4'

# (function start, end) per build, and the callees by role
FUNCTIONS = {'old': ((0x4AD8094, 0x4AD94B8), (0x4AD94B8, 0x4ADAE30)),
             'new': ((0x4A6CF04, 0x4A6E4C8), (0x4A6E4C8, 0x4A70038))}
CALLEES = {'old': {0x43DB8B8: 'key', 0x43DC8BC: 'wrap', 0x4388EF8: 'str', 0x4ACF970: 'flag'},
           'new': {0x43F4458: 'key', 0x43F545C: 'wrap', 0x43A1B14: 'str'}}
NEW_FLAG = 0x57BD9B8

needs_builds = pytest.mark.skipif(not (OLD.is_file() and NEW.is_file()),
                                  reason='preserved 27.0.0 and 27.0.1 plugins not present')


def _static_vm(path):
    from fm_live_mcp.fmdb import platform_model, vm as vmmod
    from fm_live_mcp.fmdb.image import PluginImage
    from fm_live_mcp.fmdb.memory import MemoryReadError
    base, fake = 0x1_2000_0000, 0x5F00_0000_0000
    b = platform_model.load_binary(path)
    binds = b.image.binds
    imports = {n: fake + 0x80_0000 + 0x10 * k for k, n in enumerate(sorted(set(binds.values())))}

    class Memory:
        def cached_read(self, address, length):
            if fake <= address < fake + 0x100_0000:
                return bytes(length)
            rva = address - base
            if not (0 <= rva and rva + length <= b.image_end()):
                raise MemoryReadError(f'{address:#x} is outside the plugin')
            data = bytearray(b.image.file_bytes(rva, length))
            for slot in range((rva - 8) & ~7, rva + length, 8):
                word = (struct.pack('<Q', base + b.rebases[slot]) if slot in b.rebases else
                        struct.pack('<Q', imports[binds[slot]]) if slot in binds else None)
                for k in range(8 if word else 0):
                    if rva <= slot + k < rva + length:
                        data[slot + k - rva] = word[k]
            return bytes(data)
        read = cached_read

    class Bare(vmmod.PropertyVM):
        def _session_setup(self):
            self._long_results, self.registry, self._interceptors = {}, 0, []
    return Bare(Memory(), base, PluginImage.load(path, verify=False), file_resolver=False, view='game'), base, b


class _Namer:
    """One build's two naming functions with every callee answered by a hook that records it."""

    def __init__(self, build):
        from unicorn import UC_HOOK_CODE
        import unicorn.arm64_const as A
        self.A = A
        self.build = build
        self.v, self.base, self.b = _static_vm(OLD if build == 'old' else NEW)
        self.flag = 0
        self.trace = []
        self.out, self.scratch = self.v._static(bytes(0x200)), self.v._static(bytes(0x200))
        callees = set()
        for start, end in FUNCTIONS[build]:
            code = self.b.image.file_bytes(start, end - start)
            for k in range(0, len(code), 4):
                w = struct.unpack_from('<I', code, k)[0]
                if w & 0xFC000000 == 0x94000000:                       # bl
                    off = (w & 0x3FFFFFF) - ((w & 0x2000000) << 1)
                    callees.add(start + k + 4 * off)
        roles = CALLEES[build]
        assert set(roles) <= callees, 'a modelled callee is not called'
        # the join after the label is chosen: the target of the chain's final `tbz` (no matching bit);
        # every key and literal path branches there. The run stops at it (what follows formats the
        # label through the game's runtime objects, which a plugin file alone does not have).
        self.joins = []
        for start, end in FUNCTIONS[build]:
            code = self.b.image.file_bytes(start, 0x140)
            for k in range(0, len(code), 4):
                w = struct.unpack_from('<I', code, k)[0]
                if w & 0x7F000000 == 0x36000000:                       # tbz
                    off = ((w >> 5) & 0x3FFF) - (((w >> 5) & 0x2000) << 1)
                    self.joins.append(start + k + 4 * off)
                    break
        assert len(self.joins) == 2
        for j in self.joins:
            self.v.uc.hook_add(UC_HOOK_CODE, self._join, begin=self.base + j, end=self.base + j)
        for c in callees:
            self.v.uc.hook_add(UC_HOOK_CODE, self._hook, user_data=roles.get(c, 'other'),
                               begin=self.base + c, end=self.base + c)

    def _hook(self, uc, address, size, role):
        A = self.A
        ret = 0
        if role == 'key':
            self.trace.append(('key', uc.reg_read(A.UC_ARM64_REG_X1) & 0xFFFFFFFF))
        elif role == 'str':
            s = bytes(self.v.read(uc.reg_read(A.UC_ARM64_REG_X1), 96)).split(b'\0')[0]
            self.trace.append(('str', s.decode('latin-1')))
        elif role == 'wrap':
            self.trace.append(('wrap',))
        elif role == 'flag':
            ret = self.flag
        uc.reg_write(A.UC_ARM64_REG_X0, ret)
        uc.reg_write(A.UC_ARM64_REG_PC, uc.reg_read(A.UC_ARM64_REG_LR))

    def _join(self, uc, address, size, user):
        self.trace.append(('join',))
        uc.emu_stop()

    def set_flag(self, value):
        self.flag = value
        if self.build == 'new':
            self.v.set_overlay(self.base + NEW_FLAG, bytes([value]))

    def run(self, which, word, form):
        self.trace = []
        self.v.uc.mem_write(self.out, bytes(0x200))
        self.v.uc.mem_write(self.scratch, bytes(0x200))
        try:
            self.v.call(self.base + FUNCTIONS[self.build][which][0], (word, self.out, self.scratch, form))
        except Exception as exc:  # noqa: BLE001 - the stop at the join surfaces as the VM's own stop
            if self.trace[-1:] != [('join',)]:
                raise AssertionError(f'{self.build} {which} {word:#x}: stopped before the join: {exc}')
        assert self.trace[-1:] == [('join',)], (self.build, which, hex(word), self.trace)
        return tuple(self.trace[:-1])


def _words(rng, extra):
    one = [1 << b for b in range(64)]
    two = [(1 << a) | (1 << b) for a, b in itertools.combinations(range(64), 2)]
    dense = [rng.getrandbits(64) & rng.getrandbits(64) for _ in range(extra)] + [rng.getrandbits(64) for _ in range(extra)]
    return [0] + one + two + dense


@pytest.fixture(scope='module')
def namers():
    return _Namer('old'), _Namer('new')


@pytest.mark.slow
@needs_builds
@pytest.mark.parametrize('which', [0, 1])
@pytest.mark.parametrize('form', [0, 1])
@pytest.mark.parametrize('flag', [0, 1])
def test_both_builds_give_the_same_label_routes(namers, which, form, flag):
    old, new = namers
    old.set_flag(flag)
    new.set_flag(flag)
    words = _words(random.Random(which * 4 + form * 2 + flag), 500)
    named = 0
    for w in words:
        a, b = old.run(which, w, form), new.run(which, w, form)
        assert a == b, (hex(w), a, b)
        named += bool(a)
    assert named > len(words) // 2


@pytest.mark.slow
@needs_builds
def test_mirror_follows_the_native_branch_order_on_both_builds(namers):
    """decode_word's role key is the first key the native function looks up for the phase-masked word
    (in possession: 0x4ad94b8 / 0x4a6e4c8; out of possession: 0x4ad8094 / 0x4a6cf04; short-key form 0,
    flag 0), and no lookup at all when decode_word finds no branch, on both builds."""
    from fm_live_mcp import prepared_tactic_roles as roles
    for namer in namers:
        namer.set_flag(0)
        for phase, which in (('in_possession', 1), ('out_of_possession', 0)):
            for w in _words(random.Random(5), 300):
                masked = w & roles.PHASE_NAME_MASKS[phase] & roles.ROLE_NAME_MASK
                expected = roles.decode_word(w, phase)['native_resource_key']
                trace = namer.run(which, masked, 0)
                assert trace[:1] == ((('key', expected),) if expected is not None else ()), \
                    (namer.build, phase, hex(w), trace)


@needs_builds
def test_reviewed_spans_pin_the_counterparts():
    """Every reviewed span of prepared_tactic_roles: the 27.0.0 bytes are the module's constant at the
    pinned address, and the 27.0.1 bytes at the reviewed address hold the same resource key (key blocks),
    a cbz on the label-form argument (entries) or the whole counterpart function (prologues)."""
    from fm_live_mcp.fmdb import platform_model
    from fm_live_mcp.fmdb.address_census import OVERRIDES_PATH
    from fm_live_mcp import prepared_tactic_roles as roles
    reviews = json.loads(OVERRIDES_PATH.read_text()).get('builds', {}).get(NEW_SHA256, {})
    entries = (reviews.get('guards') or {}).get('prepared_tactic_roles.py') or {}
    if not entries:
        pytest.skip('prepared_tactic_roles spans not reviewed for 27.0.1 yet')
    o, n = platform_model.load_binary(OLD), platform_model.load_binary(NEW)
    pinned = dict(roles.NATIVE_SPANS)
    starts = {s for s, _ in FUNCTIONS['new']}
    for key, e in entries.items():
        rva, new, length = int(key, 16), int(e['new'], 16), e['length']
        assert o.image.file_bytes(rva, len(pinned[rva])) == pinned[rva]
        assert reviews['values'][key]['value'] == e['new']
        nb = n.image.file_bytes(new, length)
        if new in starts:
            assert length == dict(FUNCTIONS['new'])[new] - new
            continue
        if length == 4:
            w = struct.unpack('<I', nb)[0]
            assert w & 0x7F00001F in (0x34000016, 0x34000003)          # cbz w22 / cbz w3
            continue
        ob = pinned[rva]
        if rva == 0x4ADAE88:                                           # the phase dispatcher
            words = struct.unpack(f'<{len(nb) // 4}I', nb)
            for code in (ob, nb):
                ws = struct.unpack(f'<{len(code) // 4}I', code)
                # ROLE_NAME_MASK: movn #0x6e0, lsl 16 and movk #0xfffb, lsl 32 (any register)
                assert any(w & 0xFFFFFFE0 == 0x92A0DC00 for w in ws)
                assert any(w & 0xFFFFFFE0 == 0xF2DFFF60 for w in ws)
                # ldr x9, [x8, #0x2c8] and [x8, #0x2c0]: the two phase slots
                assert {0xF9416509, 0xF9416109} <= set(ws)
            assert words.count(0xD63F0120) == 2                        # blr x9, once per phase
            continue

        def key_of(code):
            words = struct.unpack(f'<{len(code) // 4}I', code)
            lo = next(w for w in words if w & 0xFFE0001F == 0x52800001)  # movz w1, #imm16
            hi = next(w for w in words if w & 0xFFE0001F == 0x72A00001)  # movk w1, #imm16, lsl 16
            return ((lo >> 5) & 0xFFFF) | (((hi >> 5) & 0xFFFF) << 16)
        assert key_of(nb) == key_of(ob), key
