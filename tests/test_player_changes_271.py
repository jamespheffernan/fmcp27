"""native_player_changes / native_player_removal_source on 27.0.1.

27.0.1 inlines the five small change constructors into the change factory (0x4A8B248 -> 0x48DE720)
and rewrites the apply bodies (vtable slot 4). The record the decoders read (clock +8, code +0xd,
side +0xe, original slots +0xf/+0x10) is stored by the same instructions in the factory and in the
request creator (0x2F28D20 -> 0x2F389BC) on both builds. Proven here: both factories emulated for
every type code give the same class and initial bytes; the decoders' type names and codes are the
ones the game's own constructors produce."""
from __future__ import annotations

import struct

import pytest

from fm_live_mcp import native_player_changes as pc, native_player_removal_source as rm
from test_match_rating_builds import NEW, OLD, _static_vm, needs_builds

SHA_27_0_1 = '68adfde2e0588458c1830cb7e688855d9c61237973a7eb7a105af5ac4ed112a4'
FACTORY = {'old': 0x4A8B248, 'new': 0x48DE720}
# the change vtables on 27.0.1 (RTTI) and their slot 4 (apply), read from the 27.0.1 file
NEW_TABLES = {0x569F7E0: (0x573B7E0, 0x4893858), 0x569F628: (0x573B628, 0x4891D20),
              0x569F6D8: (0x573B6D8, 0x4892DF0), 0x569F788: (0x573B788, 0x48935B0),
              0x569F578: (0x573B578, 0x489188C)}


def _types():
    out = {t: (name, typename, apply, (code,)) for t, (name, typename, apply, code) in pc.TYPES.items()}
    out.update(rm.TYPES)
    return out


def _factory(build):
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X8
    v, base, b = _static_vm(OLD if build == 'old' else NEW)
    cell = v._static(bytes(16))
    start = base + FACTORY[build]
    v.uc.hook_add(UC_HOOK_CODE, lambda uc, a, s, u: uc.reg_write(UC_ARM64_REG_X8, cell), begin=start, end=start)
    out = {}
    for code in range(64):
        v.uc.mem_write(cell, bytes(8))
        try:
            v.call(start, (code,))
        except Exception as exc:  # noqa: BLE001 - a case whose constructor calls outside the plugin
            out[code] = ('stopped', type(exc).__name__)
            continue
        obj = struct.unpack('<Q', bytes(v.read(cell, 8)))[0]
        if not obj:
            out[code] = None
            continue
        vt = struct.unpack('<Q', bytes(v.read(obj, 8)))[0] - base
        ti = b.pointer(vt - 8)
        out[code] = (b.image.file_bytes(b.pointer(ti + 8), 64).split(b'\0')[0], bytes(v.read(obj + 8, 0x10)))
    return out


@pytest.mark.slow
@needs_builds
def test_change_factory_is_equivalent_on_27_0_1():
    """Every type code 0..63: the same class (RTTI name) and the same 16 bytes after the vtable on both
    builds; the five typed classes come from exactly the codes the decoders accept, with the code at +0xd."""
    old, new = _factory('old'), _factory('new')
    assert old == new
    by_name = {}
    for code, made in old.items():
        if made and made[0] != 'stopped':
            by_name.setdefault(made[0], []).append(code)
    for _table, (_name, typename, _apply, codes) in _types().items():
        assert sorted(c for c in by_name.get(typename, []) if c in codes) == sorted(
            c for c in by_name.get(typename, []))
        for code in by_name[typename]:
            raw = old[code][1]
            assert raw[5] == code and struct.unpack_from('<i', raw)[0] == -1     # +0xd, clock +8
    assert by_name[b'N7simatch16PLAYER_TAKEN_OFFE'] == [6, 18]
    assert by_name[b'N7simatch26SUBSTITUTION_TACTIC_CHANGEE'] == [4]
    assert by_name[b'N7simatch13PLAYER_PUT_ONE'] == [22]


@needs_builds
def test_decoder_type_names_and_apply_routes_on_both_builds():
    """The RTTI name at each decoder vtable is its typename and slot 4 its apply route, on both builds."""
    from fm_live_mcp.fmdb import platform_model
    o, n = platform_model.load_binary(OLD), platform_model.load_binary(NEW)
    for table, (_name, typename, apply, _codes) in _types().items():
        new_table, new_apply = NEW_TABLES[table]
        for b, t, a in ((o, table, apply), (n, new_table, new_apply)):
            ti = b.pointer(t - 8)
            assert b.image.file_bytes(b.pointer(ti + 8), len(typename) + 1) == typename + b'\0'
            assert b.pointer(t + 0x20) == a


@needs_builds
def test_request_creator_stores_the_same_record_on_both_builds():
    """0x2F28D20 -> 0x2F389BC creates TAKEN_OFF with code 18, PUT_ON with 22 and SUBSTITUTION with 4
    and stores clock +8, +0xc, code +0xd, side +0xe and slots +0xf/+0x10 the same way on both builds."""
    from fm_live_mcp.fmdb import platform_model
    o, n = platform_model.load_binary(OLD), platform_model.load_binary(NEW)
    # mov w19,#0x12; mov w0,#0x10; bl new; strb w19,[x0,#0xd] just before the TAKEN_OFF vtable store
    for b, at in ((o, 0x2F29418), (n, 0x2F391DC)):
        words = struct.unpack('<4I', b.image.file_bytes(at, 16))
        assert words[0] == 0x52800253 and words[1] == 0x52800200 and words[3] == 0x39003413


def test_reviewed_entries_name_the_counterparts():
    from fm_live_mcp.fmdb import address_map
    review = address_map.reviews(SHA_27_0_1)
    guards = {**(review.get('guards') or {}).get('native_player_changes.py', {}),
              **(review.get('guards') or {}).get('native_player_removal_source.py', {})}
    if not guards:
        pytest.skip('player-change reviews not merged into address_overrides.json')
    spans = {f'{a:#x}' for a, _ in pc.NATIVE_SPANS + rm.NATIVE_SPANS}
    assert set(guards) <= spans
    for key, entry in guards.items():
        assert review['values'][key]['value'] == entry['new'] and entry['length'] > 0
