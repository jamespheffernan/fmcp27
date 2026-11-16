"""27.0.1: the stored prepared-tactic decoders (fields, team instructions, formation recognition).

The reviewed entries for 27.0.1 (address_overrides.json, builds.<sha256>) re-derive their guards
from functions the patch re-laid out or inlined. These tests run both builds' code from the
preserved plugin files in the reader's VM over the same inputs (slow), check the bytes the reviews
rely on, and that formation naming is withheld on a build whose naming route is not verified
(27.0.1's is: tests/test_formation_names_271.py)."""
from __future__ import annotations

import random
import struct
from itertools import combinations

import pytest

from fm_live_mcp import prepared_tactic_formations as ptf
from test_match_rating_builds import NEW, OLD, _static_vm, needs_builds

OLD_FN = dict(compact=0x492B8C8, store=0x496E104, compare=0x4ADE094, sort=0x496AE3C)
NEW_FN = dict(compact=0x4A33E34, store=0x4A89B94, compare=0x4A89E60, sort=0x4A7E074)


@pytest.fixture(scope='module')
def vms():
    vo, base, bo = _static_vm(OLD)
    vn, _, bn = _static_vm(NEW)
    return vo, vn, base, bo, bn


def _s16(x):
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


@pytest.mark.slow
@needs_builds
def test_compact_position_is_equal_on_both_builds_and_to_the_mirror(vms):
    """0x492B8C8 -> 0x4A33E34 (re-laid out): every mask of up to three of bits 0..23, 20,000 random
    masks; equal to each other and to `_compact_position` (an exhaustive run over bits 0..22 is in
    the review evidence)."""
    vo, vn, base, _, _ = vms
    rng = random.Random(27)
    masks = [0] + [1 << i for i in range(32)]
    masks += [a | b for a, b in combinations([1 << i for i in range(24)], 2)]
    masks += [a | b | c for a, b, c in combinations([1 << i for i in range(24)], 3)]
    masks += [rng.getrandbits(32) for _ in range(10000)] + [rng.getrandbits(23) for _ in range(10000)]
    for m in masks:
        a = _s16(vo.call(base + OLD_FN['compact'], (m,))[0])
        b = _s16(vn.call(base + NEW_FN['compact'], (m,))[0])
        assert a == b == ptf._compact_position(m), hex(m)


@pytest.mark.slow
@needs_builds
def test_compact_and_store_variant_is_equal_on_both_builds(vms):
    vo, vn, base, _, _ = vms
    rng = random.Random(3)
    bo, bn = vo._static(bytes(64)), vn._static(bytes(64))
    for _ in range(10000):
        m, idx = rng.choice([rng.getrandbits(23), 1 << rng.randint(0, 22)]), rng.randint(0, 10)
        vo.uc.mem_write(bo, bytes(64))
        vn.uc.mem_write(bn, bytes(64))
        vo.call(base + OLD_FN['store'], (bo, idx, m))
        vn.call(base + NEW_FN['store'], (bn, idx, m))
        assert vo.read(bo, 64) == vn.read(bn, 64)


@pytest.mark.slow
@needs_builds
def test_template_comparison_is_equal_on_both_builds(vms):
    """0x4ADE094 -> 0x4A89E60: order-free matching of INVERSE[code + 15]; a third of the pairs are
    permutations (some with one code changed)."""
    vo, vn, base, _, _ = vms
    rng = random.Random(4)
    codes = list(range(-16, 12)) + [20, -20]
    ao, an = vo._static(bytes(32)), vn._static(bytes(32))
    matched = 0
    for k in range(10000):
        x = [rng.choice(codes) & 0xFF for _ in range(11)]
        y = [rng.choice(codes) & 0xFF for _ in range(11)]
        if k % 3 == 0:
            y = x[:]
            rng.shuffle(y)
            if k % 2:
                y[rng.randint(0, 10)] = rng.choice(codes) & 0xFF
        blob = bytes(x) + bytes(5) + bytes(y)
        vo.uc.mem_write(ao, blob)
        vn.uc.mem_write(an, blob)
        a = vo.call(base + OLD_FN['compare'], (ao, ao + 16))[0] & 1
        b = vn.call(base + NEW_FN['compare'], (an, an + 16))[0] & 1
        assert a == b
        matched += a
    assert matched > 1000


@pytest.mark.slow
@needs_builds
def test_template_sort_is_equal_on_both_builds_and_a_permutation(vms):
    """0x496AE3C -> 0x4A7E074 (rec, rec + 0x16, tmp, 6, 1), applied to the template's eleven
    position words before conversion on both builds: the same result, a permutation of the input,
    so the mirror's multiset signature is unaffected."""
    vo, vn, base, _, _ = vms
    rng = random.Random(9)
    ro, rn = vo._static(bytes(64)), vn._static(bytes(64))
    for _ in range(5000):
        words = [rng.choice([rng.randint(0, 0xFFFF), rng.randint(-15, 11) & 63,
                             (rng.randint(-15, 11) & 63) | (rng.randint(0, 3) << 6) | (rng.randint(0, 255) << 8)])
                 for _ in range(11)]
        blob = struct.pack('<11H', *words) + bytes([rng.randint(0, 6), rng.randint(0, 6)])
        blob += bytes(64 - len(blob))
        vo.uc.mem_write(ro, blob)
        vn.uc.mem_write(rn, blob)
        vo.call(base + OLD_FN['sort'], (ro, ro + 0x16, ro + 0x30, 6, 1))
        vn.call(base + NEW_FN['sort'], (rn, rn + 0x16, rn + 0x30, 6, 1))
        a, b = vo.read(ro, 0x30), vn.read(rn, 0x30)
        assert a == b
        assert sorted(struct.unpack('<11H', a[:22])) == sorted(words)


ORR_X9_0001000100010001 = 0xB20083E9      # mov x9, #0x1000100010001 (orr, bitmask immediate)


def _movk_constant(words):
    value = 0
    for w in words:
        if w == ORR_X9_0001000100010001:
            value = 0x0001000100010001
            continue
        imm, hw = (w >> 5) & 0xFFFF, (w >> 21) & 3
        if (w >> 23) & 0x1FF == 0b110100101:          # movz (64-bit)
            value = imm << (16 * hw)
        else:                                          # movk
            value = (value & ~(0xFFFF << (16 * hw))) | (imm << (16 * hw))
    return value


@needs_builds
def test_inlined_eligibility_excludes_the_same_templates():
    """The static exclusion mask: 0x4ADDDC4 tests bit id - 1 of 0x00019C1000011001 for id <= 49;
    27.0.1 inlines it at 0x4A8A67C, testing bit id of 0x0003382000022002."""
    from fm_live_mcp.fmdb import platform_model
    old = platform_model.load_binary(OLD).image
    new = platform_model.load_binary(NEW).image
    m_old = _movk_constant(struct.unpack('<3I', old.file_bytes(0x4ADDE04, 12)))
    m_new = _movk_constant(struct.unpack('<4I', new.file_bytes(0x4A8A67C, 16)))
    assert m_old == 0x00019C1000011001 and m_new == 0x0003382000022002
    excluded_old = {i for i in range(1, 50) if m_old >> (i - 1) & 1}
    excluded_new = {i for i in range(1, 50) if m_new >> i & 1}
    assert excluded_old == excluded_new == set(ptf.STATIC_EXCLUDED)


@needs_builds
def test_inlined_bitset_loop_and_instruction_key_are_the_reviewed_bytes():
    from fm_live_mcp.fmdb import platform_model
    old = platform_model.load_binary(OLD).image
    new = platform_model.load_binary(NEW).image
    for a, b, n in ((0x4A8EBEC, 0x491C0BC, 68), (0x4A8EC4C, 0x491C11C, 12)):
        assert old.file_bytes(a, n) == new.file_bytes(b, n)
    key = b'team_instructions_list\0'
    assert old.file_bytes(0x515C148, len(key)) == new.file_bytes(0x51F6839, len(key)) == key
    # the creator name field: +0x2780 (creator) + 0x790 inlined as +0x2F10
    assert new.file_bytes(0x454D434, 8) == bytes.fromhex('14f08452 08e28552'.replace(' ', ''))


def test_naming_is_withheld_when_its_route_is_not_verified(monkeypatch):
    from fm_live_mcp import address_book
    monkeypatch.setattr(address_book, 'MAP', {'values': {}})
    monkeypatch.setattr(address_book, 'unresolved_sites', lambda: {
        ('fm_live_mcp.prepared_tactic_formations', 'module:NAME_NATIVE_DIGESTS'): [(0x4967B80, 'code differs')]})
    ptf._naming_ready._blocked = None
    try:
        assert ptf._naming_ready(None, 0) == ptf.NAMING_UNVERIFIED
        context = ptf._Context(((29, (('x', 1),), '4-2-3-1 DM AM Wide'),), tuple(range(27)), ptf._NamingContext(None, 0))
        codes = [-15] * 11
        sig = tuple(sorted(__import__('collections').Counter(context.inverse[c + 15] for c in codes).items()))
        context = ptf._Context(((29, sig, '4-2-3-1 DM AM Wide'),), context.inverse, ptf._NamingContext(None, 0))
        out = ptf.identify(context, [1] * 11)
        assert out == {'native_id': 29, 'state': 'recognized', 'name': None, 'name_state': ptf.NAMING_UNVERIFIED}
    finally:
        ptf._naming_ready._blocked = None
