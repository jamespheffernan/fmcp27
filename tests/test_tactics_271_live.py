"""27.0.1 review of the live tactics guards (resident_match_plans, live_personal_overrides,
player_instruction_source, live_in_possession_source, live_tactical_assignments_source).

Each test reads both preserved plugins and checks the fact a reviewed entry in
fmdb/data/address_overrides.json (builds.68adfde2...) rests on. The role rule is proven by running
both builds' code in the reader's VM over the same inputs."""
from __future__ import annotations

import itertools
import struct

import pytest

from test_match_rating_builds import NEW, OLD, _static_vm, needs_builds


@pytest.fixture(scope='module')
def plugins():
    from fm_live_mcp.fmdb import platform_model
    return platform_model.load_binary(OLD), platform_model.load_binary(NEW)


def _words(b, at, n):
    return struct.unpack(f'<{n}I', b.image.file_bytes(at, 4 * n))


def _masked(words):
    """Branch, call and ADRP immediates cleared (b, bl, b.cond, cbz/cbnz, tbz/tbnz, adrp): addresses only."""
    out = []
    for w in words:
        if (w & 0x9F000000) == 0x90000000:          # adrp
            w &= 0x9F00001F
        elif (w & 0x7C000000) == 0x14000000:        # b / bl
            w &= 0xFC000000
        elif (w & 0xFF000010) == 0x54000000:        # b.cond
            w &= 0xFF00001F
        elif (w & 0x7E000000) in (0x34000000, 0x36000000):   # cbz/cbnz, tbz/tbnz
            w &= 0xFFF8001F if (w & 0x7E000000) == 0x36000000 else 0xFF00001F
        out.append(w)
    return out


@needs_builds
def test_load_tactics_span_is_the_same_code_with_the_supplier_call_moved(plugins):
    """0x451F248 (MATCH_MANAGER load_tactics: manager + 0x1800 handed to each entry's virtual +0x48)
    -> 0x4545898: the 15 instructions up to the scan loop are the same; the call block the pinned
    build had in line (0x451F288..0x451F2AC) sits at 0x4545A2C with identical bytes."""
    old, new = plugins
    assert _masked(_words(old, 0x451F248, 14)) == _masked(_words(new, 0x4545898, 14))
    # the loop's exit test: b.eq out (pinned) became b.ne back to the loop head (27.0.1)
    assert _words(old, 0x451F280, 1)[0] & 0xFF00001F == 0x54000000 and _words(new, 0x45458D0, 1)[0] & 0xFF00001F == 0x54000001
    assert old.image.file_bytes(0x451F288, 36) == new.image.file_bytes(0x4545A2C, 36)
    tbnz = _words(new, 0x45458C4, 1)[0]                     # tbnz w10, #2 -> the moved block
    assert 0x45458C4 + 4 * ((tbnz >> 5) & 0x3FFF) == 0x4545A2C


@needs_builds
@pytest.mark.parametrize('old_at, new_at', [(0x52E718, 0x52F194), (0x52E7EC, 0x52F26C)])
def test_instruction_exporters_differ_only_in_the_version_word(plugins, old_at, new_at):
    """The two exporters 0x52E718 / 0x52E7EC: `mov w24, #0x1B000000` (27.0.0.0) became
    `mov w24, #0x100; movk w24, #0x1B00, lsl 16` (0x1B000100, 27.0.1.0); the rest is the same
    code up to call targets."""
    old, new = plugins
    a, b = _words(old, old_at, 53), _words(new, new_at, 54)
    assert a[19] == 0x52A36018 and b[19:21] == (0x52802018, 0x72A36018)
    assert _masked(a[:19]) == _masked(b[:19]) and _masked(a[20:]) == _masked(b[21:])


def _imm26(w):
    v = w & 0x3FFFFFF
    return v - (1 << 26) if v & 0x2000000 else v


@needs_builds
def test_option_22_case_still_reaches_the_guarded_rule_block(plugins):
    """Jump table entry 21 (option 22, PI_GET_FORWARD_OFTEN) 0x54066AE -> 0x54A182E points at the block
    that calls the pinned rule helper (0x4972AC4 -> 0x4A8F314) and returns through 0x497387C ->
    0x4A8FFE8: 0x49743C4 -> 0x4A90C28."""
    old, new = plugins
    e_old = struct.unpack('<H', old.image.file_bytes(0x54066AE, 2))[0]
    e_new = struct.unpack('<H', new.image.file_bytes(0x54A182E, 2))[0]
    assert 0x4973524 + 4 * e_old == 0x49743C4 and 0x4A8FD74 + 4 * e_new == 0x4A90C28
    assert _masked(_words(old, 0x49743C4, 6)) == _masked(_words(new, 0x4A90C28, 6))
    bl_old, bl_new = _words(old, 0x49743D0, 1)[0], _words(new, 0x4A90C34, 1)[0]
    assert 0x49743D0 + 4 * _imm26(bl_old) == 0x4972AC4
    assert 0x4A90C34 + 4 * _imm26(bl_new) == 0x4A8F314
    assert old.image.file_bytes(0x4972AC4, 0x140) == new.image.file_bytes(0x4A8F314, 0x140)


@needs_builds
def test_remap_setter_is_inlined_with_the_same_bounds_and_store(plugins):
    """0x4857A1C (slot remap setter: index and value 0..10, byte at creator + 0x7B4) has no function on
    27.0.1: its only caller 0x4A797C8 became 0x48918FC, which stores the same byte in line at manager
    + 0x1FB4 (= 0x1800 + 0x7B4) under the same unsigned bounds (0x4891950..0x4891964)."""
    old, new = plugins
    # cmp w1,#0xa; b.hi; cmp w2,#0xa; b.hi; add x8,x0,w1,sxtw; strb w2,[x8,#0x7b4]; ret
    assert _words(old, 0x4857A1C, 7) == (0x7100283F, 0x540000A8, 0x7100285F, 0x54000068, 0x8B21C008,
                                         0x391ED102, 0xD65F03C0)
    # cmp w9,#0xa; ccmp w8,#0xa,#2,ls; b.hi; add x9,x20,x9; mov w10,#0x1fb4; strb w8,[x9,x10]
    assert _words(new, 0x4891950, 6) == (0x7100293F, 0x7A4A9902, 0x540004C8, 0x8B090289, 0x5283F68A, 0x382A6928)
    assert 0x4891958 + 4 * ((0x540004C8 >> 5) & 0x7FFFF) == 0x48919F0      # past the store, as the old b.hi


ROLES = [1 << a for a in range(64)] + [(1 << a) | (1 << b) for a, b in itertools.combinations(range(64), 2)]


def _rule(build):
    path, fn, version = {'old': (OLD, 0x4973360, 0x1B000000), 'new': (NEW, 0x4A8FBB0, 0x1B000100)}[build]
    v, base, _ = _static_vm(path)
    pos, ver, out = v._static(bytes(8)), v._static(struct.pack('<I', version)), v._static(bytes(8))

    def call(option, position, role):
        v.uc.mem_write(pos, struct.pack('<I', position))
        v.uc.mem_write(out, struct.pack('<I', 0xDEADBEEF))
        r, _ = v.call(base + fn, (option, pos, role, ver, out))
        return r & 0xFFFFFFFF, struct.unpack('<I', v.read(out, 4))[0]
    return call


@pytest.mark.slow
@needs_builds
def test_role_rule_is_the_same_on_both_builds_for_the_forward_runs_option():
    """The instruction role rule (0x4973360 -> 0x4A8FBB0, rewritten), each build with its own
    version word: for option 22 (PI_GET_FORWARD_OFTEN) and every position bit and one- or two-bit
    role word the result and state are equal, and the four cases ROLE_RULE_CASES hard-codes give
    the states it lists."""
    from fm_live_mcp.player_instruction_source import ROLE_RULE_CASES
    old, new = _rule('old'), _rule('new')
    for position in [0] + [1 << k for k in range(32)]:
        for role in ROLES:
            assert old(22, position, role) == new(22, position, role), (position, hex(role))
    for (position, role), state in ROLE_RULE_CASES.items():
        assert old(22, position, role)[1] == new(22, position, role)[1] == state
