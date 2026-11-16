"""The knowledge engine through the installed build's address map, without the game:
`pytest -m mapped_build`.

On 27.0.1 the first map left the Passing projection source's getter guard at the pinned bytes,
so every manager-visible field refused. No knowledge module may keep a guard the map could not
re-derive, and every module the manager view imports must import with its guards current.
"""
import hashlib

import pytest

from fm_live_mcp import address_book as ab, build_paths


@pytest.fixture(scope='module')
def mapped():
    plugin = build_paths.installed_plugin()
    if not plugin.is_file():
        pytest.skip(f'no installed plugin at {plugin}')
    if ab.ACTIVE['state'] == 'pinned' and build_paths.installed_is_pinned():
        pytest.skip('the installed game is the pinned build: there is no address map to check')
    assert ab.ACTIVE['state'] == 'mapped', ab.report()
    return ab.MAP


def test_no_knowledge_module_keeps_a_changed_guard(mapped):
    spans = [s for s in (mapped.get('guards') or {}).get('spans') or ()
             if s['file'].startswith('knowledge_') or s['file'].startswith('fmdb/knowledge_')]
    assert not spans, [(s['file'], hex(s['address']), s['verdict']) for s in spans]


def test_manager_view_guards_hold_on_the_installed_plugin(mapped):
    """The guard tables the manager-visible sources check on construction, as rewritten at
    import, equal the installed plugin's bytes."""
    from fm_live_mcp import (knowledge_context_score_source as ctx, knowledge_passing_view as view,
                             knowledge_person_ui_caller as ui)
    from fm_live_mcp.fmdb.image import PluginImage
    image = PluginImage.load(build_paths.installed_plugin(), verify=False)
    for name, table in (('passing view', view.NATIVE_GUARDS), ('context score', ctx.EXTRA_GUARDS),
                        ('person UI caller', ui.NATIVE_GUARDS)):
        for rva, n, digest in table:
            assert hashlib.sha256(image.file_bytes(rva, n)).hexdigest() == digest, (name, hex(rva))


def test_native_operand_functions_follow_the_build(mapped):
    """The functions knowledge_native runs in the emulator are the running build's."""
    from fm_live_mcp import knowledge_native as kn
    for pinned, now in ((0x20EE608, kn.RELATION_MASK_RVA), (0xCBB9F8, kn.TRANSFER_PREDICATE_RVA),
                        (0xE58E5C, kn.CLUB_ADMISSION_RVA), (0x208B238, kn.SEARCH_REFRESH_RVA)):
        assert now == mapped['values'][f'{pinned:#x}']['value'], hex(pinned)


def test_wage_owner_text_header_check_follows_the_build(mapped):
    """committed_wage_owner_source checks the loaded __text header. Its size was a literal
    (0x4AE8344) that the map translated as a code address (to 0x4AB560C), so the committed
    wage tool refused 'Plugin native text section changed' on 27.0.1. The check now names the
    section's end, which the map translates to the installed plugin's own end."""
    import struct
    from fm_live_mcp import ffp_projection as ffp
    with open(build_paths.installed_plugin(), 'rb') as image:
        image.seek(ffp.arm_slice(image) + 0x88)
        start, size = struct.unpack('<QQ', image.read(16))
    assert start == 0x55F0
    assert mapped['values']['0x4aed934']['value'] - 0x55F0 == size


def test_wage_reducer_executes_only_the_running_builds_functions(mapped):
    """Every span the reducer may run hashes to the installed plugin's bytes."""
    from fm_live_mcp import committed_wage_spending_core as core, ffp_projection as ffp
    with open(build_paths.installed_plugin(), 'rb') as image:
        base = ffp.arm_slice(image)
        for start, end, digest in core.all_spans():
            image.seek(base + start)
            assert hashlib.sha256(image.read(end - start)).hexdigest() == digest, hex(start)


def test_save_routes_are_direct_calls_on_the_installed_plugin(mapped):
    """Every save route's call site is `bl function` in the installed plugin (the check
    fm_native_read and the native-state tables make before running a save function)."""
    import struct
    from fm_live_mcp import ffp_projection as ffp
    from fm_live_mcp.fmdb import persist
    with open(build_paths.installed_plugin(), 'rb') as image:
        base = ffp.arm_slice(image)
        for route in persist.routes():
            site = int(route['site'], 16)
            image.seek(base + site)
            word = struct.unpack('<I', image.read(4))[0]
            assert word >> 26 == 0b100101, route['key']
            imm = word & 0x3FFFFFF
            imm -= (1 << 26) if imm & (1 << 25) else 0
            assert site + 4 * imm == int(route['function'], 16), route['key']


def test_staff_responsibility_spans_are_whole_functions_of_the_installed_plugin(mapped):
    """current_staff_responsibilities executes the retained-PERSON resolver and the selector in
    its emulator. Both grew on 27.0.1 (632 -> 652, 840 -> 864 bytes); with the spans at their
    pinned lengths the emulator stopped at 0x17C6804 and all 118 current delegates were
    unavailable. The spans now run to the mapped function ends and hash to the installed bytes."""
    from fm_live_mcp import current_staff_responsibilities as csr, ffp_projection as ffp
    with open(build_paths.installed_plugin(), 'rb') as image:
        base = ffp.arm_slice(image)
        for rva, size, digest, kind in csr.NATIVE_SPANS:
            n = size - rva if size > rva else size
            image.seek(base + rva)
            assert hashlib.sha256(image.read(n)).hexdigest() == digest, hex(rva)
    ends = {rva: size for rva, size, _, _ in csr.NATIVE_SPANS if size > rva}
    if mapped['plugin_sha256'] == '68adfde2e0588458c1830cb7e688855d9c61237973a7eb7a105af5ac4ed112a4':
        assert ends == {0x15CAA30: 0x15CACBC, 0x17C64BC: 0x17C681C}
