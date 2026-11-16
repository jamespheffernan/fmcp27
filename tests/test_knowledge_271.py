"""The knowledge engine on 27.0.1.2503222: the native functions it guards or mirrors, compared
with the pinned build's.

Of the 199 functions the knowledge modules name, 193 have the same masked instructions and call
or reference the matched counterparts on both builds; six changed (docs/builds/27.0.1.md,
"The knowledge engine on 27.0.1"). The slow tests run both builds' code over the same inputs in
the static VM; the others check the reviewed entries that let the map re-derive their guards.
"""
from __future__ import annotations

import random
import struct

import pytest

from fm_live_mcp.fmdb import address_map
from tests.test_function_match import NEW, OLD, SHA_27_0_1, _static_vm, needs_builds

GETTER_OLD, GETTER_NEW = 0xD19EB0, 0xD1D530


def test_the_attribute_getter_guard_is_reviewed_for_every_module_that_checks_it():
    """The getter guard (0xD19EB0, 0x78 bytes) is checked by the Passing projection source, from
    which every manager-visible source derives, and by the context score source. Only the second
    was reviewed at first, so every field of the manager view refused on 27.0.1."""
    from fm_live_mcp import knowledge_context_score_source as ctx, knowledge_passing_view as view
    guards = address_map.reviews(SHA_27_0_1)['guards']
    for rel, table in (('knowledge_passing_view.py', view.NATIVE_GUARDS),
                       ('knowledge_context_score_source.py', ctx.EXTRA_GUARDS)):
        assert any(g[0] == GETTER_OLD and g[1] == 0x78 for g in table), rel
        entry = guards[rel][f'{GETTER_OLD:#x}']
        assert int(entry['new'], 16) == GETTER_NEW and entry['verdict'] == 'shape'


def _person(rng, signed_display):
    raw = bytearray(rng.randrange(256) for _ in range(0x300))
    raw[0x270] = rng.randrange(0x80, 0x100) if signed_display else rng.randrange(0, 0x80)
    return bytes(raw)


@pytest.mark.slow
@needs_builds
def test_attribute_getter_is_equivalent_on_27_0_1():
    """PERSON vtable +0xF0 (0xD19EB0 -> 0xD1D530): 27.0.1 inlines the code-to-index helper
    0x4ACF834 as a 47-entry table and tests the code unsigned against 0x2E. Over 200 synthetic
    PERSON objects (random attribute bytes; display flag +0x270 both signs) and every code from
    -8 to 71, both builds return the same byte."""
    vo, base = _static_vm(OLD)
    vn, _ = _static_vm(NEW)
    rng = random.Random(271)
    po, pn = vo._static(bytes(0x300)), vn._static(bytes(0x300))
    cases = 0
    for k in range(200):
        raw = _person(rng, k % 2)
        vo.uc.mem_write(po, raw)
        vn.uc.mem_write(pn, raw)
        for code in range(-8, 72):
            a = vo.call(base + GETTER_OLD, (po, code & 0xFFFFFFFFFFFFFFFF))[0] & 0xFF
            b = vn.call(base + GETTER_NEW, (pn, code & 0xFFFFFFFFFFFFFFFF))[0] & 0xFF
            assert a == b, (k, code, a, b)
            cases += 1
    assert cases == 200 * 80


@pytest.mark.slow
@needs_builds
def test_attribute_getter_matches_the_python_rule():
    """The rule the port applies (knowledge_passing_range.passing_getter: stored byte, shown as
    clamp(1..20, round(raw / 5)) when +0x270 is negative) equals the 27.0.1 getter for Passing."""
    from fm_live_mcp import knowledge_passing_range as ranges
    vn, base = _static_vm(NEW)
    pn = vn._static(bytes(0x300))
    rng = random.Random(18)
    for k in range(400):
        raw = _person(rng, k % 2)
        vn.uc.mem_write(pn, raw)
        got = vn.call(base + GETTER_NEW, (pn, 18))[0] & 0xFF
        stored, mode = raw[0x148 + 0x16], raw[0x270]
        assert ranges.passing_getter(stored, mode) == struct.unpack('b', bytes([got]))[0], (k, stored, mode, got)


def test_no_function_start_is_left_untranslated_by_a_name_rule():
    """The census rule 'mask' (a name containing MASK or BITS) took knowledge_native's
    RELATION_MASK_RVA = 0x20EE608 for a bit mask, so on 27.0.1 the emulator ran the pinned
    address and every native relation-mask call refused (found live). A literal that is a
    function start of the pinned build is an address unless it is a provenance label."""
    from fm_live_mcp.fmdb import address_census
    doc = address_census.load()
    left = [(rel, key, row['rule']) for rel, entry in doc['files'].items() for key, row in entry.items()
            if row['kind'] == 'function' and row['d'] == 'C' and row['rule'] != 'label']
    assert not left, left
    assert doc['files']['knowledge_native.py']['0x20ee608']['d'] == 'A'


class _NoGame(Exception):
    pass


@pytest.mark.parametrize('base,aliases', [(0x159EB0000, False), (0x7000000000, False),
                                          (0x1_0000_0000, False), (0x7D00_0000_0000 - 0x100_0000, True),
                                          (0x7D00_1000_0000 - 0x4000, True)])
def test_relation_replay_windows_do_not_depend_on_where_the_plugin_loads(base, aliases):
    """The lazy replay VM refused every call when the plugin loaded below 0x300100000 (the 27.0.1
    session put it at 0x159EB0000; 73 of 600 random players lost every field). Only a plugin
    image that overlaps the private windows refuses now."""
    from fm_live_mcp import knowledge_relation_fixes as fixes

    class Source:
        def __init__(self):
            self.base = base

        def read(self, address, length):
            raise _NoGame(hex(address))

    try:
        fixes.replay_lazy(Source(), 0x17743B8, (0x1_7005_F000,), _NoGame, 'test')
    except _NoGame as exc:
        assert ('aliases the private VM windows' in str(exc)) == aliases, str(exc)
    else:
        raise AssertionError('the replay ran without game memory')


@pytest.mark.slow
@needs_builds
def test_wage_attribute_mask_inlined_on_27_0_0_equals_the_leaf_27_0_1_calls():
    """0x129B5F4 (pinned) computes the attribute mask of x0 inline (0x129B628..0x129B708, result
    in w20); 27.0.1's 0x12A2C94 calls the leaf 0x4A1C05C (pinned 0x4914BD8, unchanged) with
    x0 + 0x140 and w1 = 15. Over 2,000 random attribute blocks (and every byte at the threshold)
    the inline block, the pinned leaf and the 27.0.1 leaf give the same mask."""
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
    import unicorn.arm64_const as A
    from fm_live_mcp.fmdb import platform_model
    old_code = platform_model.load_binary(OLD).image.file_bytes(0x129B628, 0x129B708 - 0x129B628)
    uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    uc.mem_map(0x10000, 0x1000)
    uc.mem_map(0x20000, 0x1000)
    uc.mem_write(0x10000, old_code)
    vo, base = _static_vm(OLD)
    vn, _ = _static_vm(NEW)
    rng = random.Random(1296)
    blocks = [bytes(rng.randrange(256) for _ in range(0x300)) for _ in range(2000)]
    for k in range(0x148, 0x157):
        for v in (14, 15, 16):
            raw = bytearray(blocks[0])
            raw[k] = v
            blocks.append(bytes(raw))
    po, pn = vo._static(bytes(0x300)), vn._static(bytes(0x300))
    for raw in blocks:
        uc.mem_write(0x20000, raw)
        uc.reg_write(A.UC_ARM64_REG_X0, 0x20000)
        uc.emu_start(0x10000, 0x10000 + len(old_code))
        inline = uc.reg_read(A.UC_ARM64_REG_X20) & 0xFFFFFFFF
        vo.uc.mem_write(po, raw)
        vn.uc.mem_write(pn, raw)
        leaf_old = vo.call(base + 0x4914BD8, (po + 0x140, 15))[0] & 0xFFFFFFFF
        leaf_new = vn.call(base + 0x4A1C05C, (pn + 0x140, 15))[0] & 0xFFFFFFFF
        assert inline == leaf_old == leaf_new, (hex(inline), hex(leaf_old), hex(leaf_new))


def test_wage_reducer_spans_reviewed_with_their_new_length():
    """The three reducer functions whose length changed on 27.0.1 are reviewed whole, with the
    length the address map gives both ends; guard_rewrites re-derives a changed-length span only
    from such a review."""
    from fm_live_mcp import committed_wage_spending_core as core
    guards = address_map.reviews(SHA_27_0_1)['guards']['committed_wage_spending_core.py']
    spans = {start: end for start, end, _ in core._SPANS}
    for old, new, length in ((0xCC0014, 0xCC38A8, 1080), (0x1002B10, 0x1006224, 444), (0x129B5F4, 0x12A2C94, 324)):
        entry = guards[f'{old:#x}']
        assert int(entry['new'], 16) == new and entry['length'] == length and old in spans
    assert any(start == 0x4914BD8 and n == 0xE4 for start, n, _ in core._LEAF_SPANS)


def test_changed_length_span_is_rederived_only_from_a_review_of_that_length(monkeypatch, tmp_path):
    """A `(start, end, sha256)` span whose mapped ends are another length apart refuses unless a
    review names the same new start and that new length; then its hash is taken from the new
    bytes between the mapped ends."""
    import hashlib
    from types import SimpleNamespace
    old = {0x1000: bytes(range(16))}
    new = {0x2000: bytes(range(100, 112))}

    class Img:
        def __init__(self, mem):
            self.mem = mem

        def file_bytes(self, a, n):
            for start, data in self.mem.items():
                if start <= a < start + len(data):
                    return data[a - start:a - start + n]
            return bytes(n)
    reference = SimpleNamespace(image=Img(old))
    target = SimpleNamespace(image=Img(new), sha256='e' * 64)
    digest = hashlib.sha256(bytes(range(16))).hexdigest()
    (tmp_path / 'demo.py').write_text(f"SPANS = ((0x1000, 0x1010, '{digest}'),)\n")
    census = {'files': {'demo.py': {'0x1000': {'d': 'A', 'rule': 'guard', 'sites': []},
                                    '0x1010': {'d': 'A', 'rule': 'guard', 'sites': []}}}}
    mapping = {0x1000: address_map.Resolution(0x2000, 'reviewed'), 0x1010: address_map.Resolution(0x200C, 'fp')}

    def run(review):
        monkeypatch.setattr(address_map, 'reviews', lambda sha: {'guards': {'demo.py': review}})
        return address_map.guard_rewrites(target, reference, census, mapping, tmp_path)
    unreviewed = run({})
    assert not unreviewed['files'] and 'is 12 bytes on this build' in unreviewed['spans'][0]['changes'][0]['why']
    wrong = run({'0x1000': {'new': '0x2000', 'length': 16, 'verdict': 'shape', 'evidence': 't'}})
    assert not wrong['files'] and wrong['spans']
    good = run({'0x1000': {'new': '0x2000', 'length': 12, 'verdict': 'shape', 'evidence': 't'}})
    assert good['files'] == {'demo.py': {digest: hashlib.sha256(bytes(range(100, 112))).hexdigest()}}
    assert not good['spans'] and good['reviewed'][0]['length'] == 12


def test_save_route_literals_list_the_route_file_and_translate_with_it(monkeypatch):
    """data/persist_routes.json is data, never rewritten by the address book; on 27.0.1 every save
    route kept pinned addresses and fm_native_read refused 'save walker call site 0x2571a4c is not
    a direct call in this build'. persist._ROUTE_ADDRESSES lists the same addresses as literals
    (so the census marks them and the map translates them), and routes() takes each route's
    addresses from it."""
    import json
    from fm_live_mcp.fmdb import address_census, persist
    doc = json.loads(persist.ROUTES_FILE.read_text())
    pinned = persist._route_addresses(doc)
    census = address_census.load()['files']['fmdb/persist.py']
    if pinned == list(persist._ROUTE_ADDRESSES):                 # a pinned session: nothing translated
        assert all(census[f'{v:#x}']['d'] == 'A' for v in pinned)
    shifted = tuple(v + 0x1000 for v in pinned)
    monkeypatch.setattr(persist, '_ROUTE_ADDRESSES', shifted)
    for route, raw in zip(persist.routes(), doc['routes']):
        for key in ('root_rva', 'function', 'site'):
            assert int(route[key], 16) == int(raw[key], 16) + 0x1000
    monkeypatch.setattr(persist, '_ROUTE_ADDRESSES', shifted[:-1])
    with pytest.raises(persist.PersistError, match='differ'):
        persist.routes()


def _summary_blob(version):
    def text(value):
        raw = value.encode()
        return len(raw).to_bytes(4, 'little') + raw
    people = text('Cesar  Jules') + text('Newcastle') + (688).to_bytes(4, 'little', signed=True)
    return (bytes.fromhex('03017461642e1f00') + text('757,MALE,2,0') + text(version) + (0).to_bytes(4, 'little')
            + bytes(7) + bytes([1]) + people + ((2030 << 16) | 355).to_bytes(4, 'little'))


@pytest.mark.parametrize('version,state', [('27.0.0+2493426', 'verified'), ('27.0.1+2503222', 'verified'),
                                           ('27.0.2+9999999', None)])
def test_saved_summary_accepts_the_versions_whose_layout_was_checked(version, state):
    """Saves written by 27.0.1 carry '27.0.1+2503222' in save_game_summary.dat with the 27.0.0
    layout (a live save parsed: Cesar Jules, Newcastle 688, 21 Dec 2030); the reader accepted only
    the pinned text, so every saved-file tool reported saved_metadata unknown on 27.0.1."""
    from fm_live_mcp import snapshot_catalog as sc
    blob = _summary_blob(version)
    if state is None:
        with pytest.raises(ValueError, match='game version'):
            sc._summary(blob)
        return
    got = sc._summary(blob)
    assert got['status'] == state and got['game_version_text'] == version
    assert got['saved_simulation_date'] == '2030-12-21' and got['summary_people'][0]['team_native_id'] == 688
