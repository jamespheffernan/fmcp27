"""function_match.py: changed functions across builds, aligned instructions, classified sites;
address_book.field: the per-build structure offset table.

Offline unit tests on instruction words run by default. The tests marked slow load both plugins
preserved under fmdb-runtime-research/builds/ (27.0.0.2493426 and 27.0.1.2503222) and are skipped
where they are absent.
"""
from __future__ import annotations

import ast
import random
from pathlib import Path

import pytest

from fm_live_mcp import address_book as ab
from fm_live_mcp.fmdb import function_match as fm

BUILDS = Path('/Volumes/4TB Private/Offloaded/Agent Work/fmdb-runtime-research/builds')
OLD, NEW = BUILDS / '27.0.0.2493426/game_plugin', BUILDS / '27.0.1.2503222/game_plugin'


def _ldr_x(rt, rn, offset):
    return 0xF9400000 | ((offset // 8) << 10) | (rn << 5) | rt


def test_register_allocation_is_masked():
    assert _ldr_x(0, 1, 0x10) & ~fm.reg_mask(_ldr_x(0, 1, 0x10)) == \
        _ldr_x(2, 3, 0x10) & ~fm.reg_mask(_ldr_x(2, 3, 0x10))
    assert _ldr_x(0, 1, 0x10) & ~fm.reg_mask(_ldr_x(0, 1, 0x10)) != \
        _ldr_x(0, 1, 0x18) & ~fm.reg_mask(_ldr_x(0, 1, 0x18))


def test_a_moved_field_is_an_offset_change_with_both_offsets():
    kind, old, new, base, _base_new = fm._imm_change(_ldr_x(8, 0, 0x278), _ldr_x(9, 0, 0x280))
    assert (kind, old, new, base) == ('ldst', 0x278, 0x280, 0)
    assert fm._imm_change(_ldr_x(8, 0, 0x278), 0xD65F03C0) is None          # ldr against ret
    assert fm.ta_tb_differ_beyond.__doc__                                     # opcode guard exists


def test_stack_slots_are_not_structure_offsets():
    a, b = _ldr_x(0, 31, 0x10), _ldr_x(0, 31, 0x18)                           # ldr x0, [sp, #...]
    assert fm.frame_mask(a) and fm._key(a, a) == fm._key(b, b)
    assert not fm.frame_mask(_ldr_x(0, 1, 0x10))


def test_field_lookup_defaults_to_the_pinned_offset(monkeypatch):
    monkeypatch.setattr(ab, '_OFFSETS', {})
    assert ab.field('GAME_MATCH_TEAM', 0x1D0) == 0x1D0
    monkeypatch.setattr(ab, '_OFFSETS', {'GAME_MATCH_TEAM': {0x1D0: 0x80, 0x1D8: None}})
    assert ab.field('GAME_MATCH_TEAM', 0x1D0) == 0x80
    assert ab.field('GAME_MATCH_TEAM', 0x1C8) == 0x1C8                        # not listed: unchanged
    assert ab.field('OTHER', 0x1D0) == 0x1D0                                  # another structure
    with pytest.raises(ab.UnresolvedAddress, match='GAME_MATCH_TEAM'):
        ab.field('GAME_MATCH_TEAM', 0x1D8)


def test_offset_table_never_reaches_the_import_rewrite(monkeypatch):
    """The import rewrite changes only census addresses: a structure offset table, even one that
    names every small number, leaves every other constant of a module as it was."""
    monkeypatch.setattr(ab, '_OFFSETS', {'S': {n: n + 8 for n in range(0, 0x2000, 8)}})
    monkeypatch.setattr(ab, '_PER_FILE', {})
    monkeypatch.setattr(ab, '_GUARDS', {})
    monkeypatch.setattr(ab, '_DISABLED', {})
    monkeypatch.setattr(ab, '_CENSUS', {'files': {}, 'image_end': 0x6000000})
    source = 'A = 0x1D0\nB = (0x8, 0x10, 0x278)\ndef f(base):\n    return base + 0x40\n'
    before = ast.dump(ast.parse(source))
    tree = ast.parse(source)
    ab.rewrite(tree, 'demo.py')
    assert ast.dump(tree) == before


# --------------------------------------------------------------------------- on the two builds
needs_builds = pytest.mark.skipif(not (OLD.is_file() and NEW.is_file()),
                                  reason='the preserved 27.0.0 and 27.0.1 plugins are not on this machine')


@pytest.fixture(scope='module')
def pair():
    from fm_live_mcp.fmdb import platform_model
    r, t = platform_model.load_binary(OLD), platform_model.load_binary(NEW)
    return r, t, fm.Match(r, t).run()


@pytest.mark.slow
@needs_builds
def test_held_out_unchanged_functions_are_found_again():
    """Hide 10 percent of the functions matched by unique fingerprint: the propagation must find
    nearly all of them again and almost never pick another function (measured 6,133 right, 1
    wrong, 12 missed of 6,146 on 12 November 2026)."""
    from fm_live_mcp.fmdb import platform_model
    r, t = platform_model.load_binary(OLD), platform_model.load_binary(NEW)
    first = fm.Match(r, t)
    first.exact()
    truth = dict(first.fwd)
    random.seed(7)
    hide = set(random.sample(sorted(truth), len(truth) // 10))
    m = fm.Match(r, t)
    m.R, m.T = first.R, first.T
    m.run(hide=hide)
    right = sum(1 for a in hide if m.fwd.get(a) == truth[a])
    wrong = sum(1 for a in hide if a in m.fwd and m.fwd[a] != truth[a])
    assert right >= 0.99 * len(hide) and wrong <= 0.001 * len(hide)


@pytest.mark.slow
@needs_builds
def test_the_required_anchors_of_27_0_1(pair):
    """0x17DB1D8 (the knowledge-engine function every server import needed) and the globals the
    fingerprints missed on 27.0.1."""
    r, t, m = pair
    assert fm.carry(m, 0x17DB1D8)[0] == 0x17E5718
    assert fm.carry_data(m, 0x573BBA0)[0] == 0x57D7BC0              # VARIANT_REGISTRY_RVA


@pytest.mark.slow
@needs_builds
def test_exported_names_decide_over_fingerprint_twins(pair):
    """27.0.1 gave `_i_characters_get_instance` the fingerprint `_i_translator_get_instance` had on
    27.0.0 (the in-page offsets of their globals swapped), so the fingerprint paired the
    translator accessor with the characters one and the address map sent the translator global
    0x5721E70 to the characters global 0x57BDE70: every front-end word read null. The exported
    name pairs them right, and the global follows the exported accessor's reference."""
    from fm_live_mcp.fmdb import address_map
    r, t, m = pair
    ex_r, ex_t = fm.exported_functions(r), fm.exported_functions(t)
    assert ex_r['_i_translator_get_instance'] == 0x1C0BC and ex_t['_i_translator_get_instance'] == 0x1C190
    assert m.fwd[0x1C0BC] == 0x1C190 and m.how[0x1C0BC][0] == 'export'
    assert m.fwd[0x229D0] == 0x22AA4                                 # _i_plugin_match_interface_get_instance
    fns = address_map._Functions(t, r, False)
    fns.matched, fns._match = True, m
    hit = address_map._export_xref(r, t, 0x5721E70, fns)
    assert (hit.value, hit.method) == (0x57BDE90, 'export-xref')


# --------------------------------------------------------------------------- hand reviews of 27.0.1
SHA_27_0_1 = '68adfde2e0588458c1830cb7e688855d9c61237973a7eb7a105af5ac4ed112a4'


def test_reviews_are_well_formed():
    """Every reviewed value and guard of a build carries its evidence; a guard reviewed at an
    address that the same build's values also review names the same place."""
    from fm_live_mcp.fmdb import address_map
    review = address_map.reviews(SHA_27_0_1)
    values = review['values']
    assert values and review['guards']
    for key, entry in values.items():
        assert int(key, 16) and int(entry['value'], 16) and len(entry['evidence']) > 20
    for rel, guards in review['guards'].items():
        assert (Path(ab.PACKAGE_DIR) / rel).is_file(), rel
        for key, entry in guards.items():
            assert entry['verdict'] in ('registers', 'shape', 'ported') and entry['evidence']
            if key in values:
                assert values[key]['value'] == entry['new'], (rel, key)
    assert address_map.reviews('0' * 64) == {}


def test_reviewed_guard_is_rederived_only_at_the_reviewed_place(monkeypatch):
    """guard_rewrites takes a reviewed guard's bytes from the new build at the reviewed address,
    and keeps refusing (a span with the mismatch) when the address map puts it elsewhere."""
    from types import SimpleNamespace
    from fm_live_mcp.fmdb import address_map
    old = {0x1000: bytes.fromhex('e8030091')}
    new = {0x2000: bytes.fromhex('e9030091e8030091'), 0x3000: bytes.fromhex('ffffffff')}

    class Img:
        def __init__(self, mem):
            self.mem = mem

        def file_bytes(self, a, n):
            for start, data in self.mem.items():
                if start <= a < start + len(data):
                    return data[a - start:a - start + n]
            return bytes(n)
    reference = SimpleNamespace(image=Img(old), is_code=lambda a: True, fingerprint=lambda a, b: a)
    target = SimpleNamespace(image=Img(new), sha256='f' * 64, is_code=lambda a: True, fingerprint=lambda a, b: -a)
    monkeypatch.setattr(address_map, 'reviews', lambda sha: {'guards': {'demo.py': {
        '0x1000': {'new': '0x2000', 'length': 8, 'verdict': 'shape', 'evidence': 'test'}}}})
    monkeypatch.setattr(address_map, '_masked_equal', lambda *a: False)
    census = {'files': {'demo.py': {'0x1000': {'d': 'A', 'rule': 'guard', 'sites': []}}}}

    def run(where, tmp):
        (tmp / 'demo.py').write_text("SPANS = ((0x1000, bytes.fromhex('e8030091')),)\n")
        mapping = {0x1000: address_map.Resolution(where, 'reviewed')}
        return address_map.guard_rewrites(target, reference, census, mapping, tmp)
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        good = run(0x2000, Path(d))
        bad = run(0x3000, Path(d))
    assert good['files'] == {'demo.py': {'e8030091': 'e9030091e8030091'}} and not good['spans']
    assert good['reviewed'][0]['length'] == 8
    assert not bad['files'] and 'reviewed at 0x2000' in bad['spans'][0]['changes'][0]['why']


def _static_vm(path):
    """A VM over the plugin file alone: rebased pointers into the image, imports by name."""
    import struct
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
    return Bare(Memory(), base, PluginImage.load(path, verify=False), file_resolver=False, view='game'), base


def _stream_calls(path, fn, mode, version):
    """fn(obj, &stream, version) of a MATCH_PLAYER_STATS (de)serializer on a zero stream/object:
    the ordered stream calls (stream offset, object offset or 'other', length, bytes written)."""
    import struct
    from unicorn import UC_HOOK_CODE, UC_PROT_EXEC, UC_PROT_READ
    import unicorn.arm64_const as A
    from fm_live_mcp.fmdb import vm as vmmod
    v, base = _static_vm(path)
    hooks = vmmod.PRIVATE + 0x2100_0000
    v.uc.mem_map(hooks, vmmod.PAGE, UC_PROT_READ | UC_PROT_EXEC)
    v.uc.mem_write(hooks, b'\xc0\x03\x5f\xd6' * (vmmod.PAGE // 4))
    obj = v._static(bytes(0x400))
    vt = v._static(b''.join(struct.pack('<Q', hooks + 4 * k) for k in range(64)))
    stream = v._static(struct.pack('<QQQ', vt, 1 << 30, 0) + bytes(0xe8))
    cell = v._static(struct.pack('<QQ', stream, 0))
    calls, pos = [], [0]

    def hook(uc, address, size, user):
        x1, n = uc.reg_read(A.UC_ARM64_REG_X1), uc.reg_read(A.UC_ARM64_REG_X2) & 0xFFFFFFFF
        assert (address - hooks) // 4 == 6, 'only the virtual read/write (+0x30) is modelled'
        where = x1 - obj if obj <= x1 < obj + 0x400 else 'other'
        if mode == 'read':
            uc.mem_write(x1, bytes(n))
            calls.append((pos[0], where, n))
        else:
            calls.append((pos[0], where, n, bytes(v.read(x1, n))))
        pos[0] += n
        uc.reg_write(A.UC_ARM64_REG_X0, n)
        uc.reg_write(A.UC_ARM64_REG_PC, uc.reg_read(A.UC_ARM64_REG_LR))
    v.uc.hook_add(UC_HOOK_CODE, hook, begin=hooks, end=hooks + vmmod.PAGE - 1)
    result, _ = v.call(base + fn, (obj, cell, version))
    return result, calls, v.read(obj, 0x400)


@pytest.mark.slow
@needs_builds
@pytest.mark.parametrize('version', [52, 54, 59, 60, 61])
def test_match_player_stats_wire_is_unchanged_on_27_0_1(version):
    """The deserializer of a retained player row (MATCH_PLAYER_STATS vtable slot 4) reads the same
    stream offsets into the same fields on both builds, for the versions either build branches
    on; 27.0.1 has no version gate above 59 (its reads at 61 equal those at 60)."""
    old = _stream_calls(OLD, 0x4AD2910, 'read', version)
    new = _stream_calls(NEW, 0x4A559C8, 'read', version)
    assert old[0] == new[0] == 1 and old[1] == new[1] and old[2] == new[2]
    if version >= 60:                                              # OpenPlayFinalThirdPasses, u32 profile 209 + 4
        assert any(c[1] == 0x10A and c[0] == 213 for c in old[1])


@pytest.mark.slow
@needs_builds
def test_match_player_stats_writer_is_unchanged_on_27_0_1():
    """The serializer (slot 3) writes the same bytes in the same order on both builds."""
    old = _stream_calls(OLD, 0x4AD215C, 'write', 60)
    new = _stream_calls(NEW, 0x4A549B8, 'write', 60)
    assert old[0] == new[0] == 1
    assert [(c[0], c[1], c[2], c[3]) for c in old[1] if c[1] != 'other'] == \
           [(c[0], c[1], c[2], c[3]) for c in new[1] if c[1] != 'other']
    assert b''.join(c[3] for c in old[1]) == b''.join(c[3] for c in new[1])


@pytest.mark.slow
@needs_builds
def test_event_code_function_is_equivalent_on_27_0_1():
    """0x48930AC -> 0x494CFE0 (event code from type and subtype, a byte jump table whose entries
    changed): the same result for every type and subtype below 64."""
    vo, base = _static_vm(OLD)
    vn, _ = _static_vm(NEW)
    for a in range(64):
        for b in range(64):
            assert vo.call(base + 0x48930AC, (a, b))[0] & 0xFF == vn.call(base + 0x494CFE0, (a, b))[0] & 0xFF
