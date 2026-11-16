"""retained_cross_events on 27.0.1: the converter, the kind switch and the dependency spans.

27.0.1 rewrote the event converter's tables, the CBE builder and the match engine. The decoder
depends on: the converter (kind, outcome) -> CBE category, the record offsets the builder writes,
and the engine's kind-3 case that counts CrossAttempts / CrossesCompleted. The whole-region hashes
of the builder and the engine stay the pinned build's check (`_whole_function_hashes`); on every
build `DEPENDENCY_SPANS` guard exactly what the decoder relies on, re-derived for 27.0.1 by the
reviewed entries under `builds.<sha256>` of address_overrides.json."""
import struct
from pathlib import Path

import pytest

from fm_live_mcp import retained_cross_events as rce

BUILDS = Path('/Volumes/4TB Private/Offloaded/Agent Work/fmdb-runtime-research/builds')
OLD, NEW = BUILDS / '27.0.0.2493426/game_plugin', BUILDS / '27.0.1.2503222/game_plugin'
SHA = '68adfde2e0588458c1830cb7e688855d9c61237973a7eb7a105af5ac4ed112a4'
needs_builds = pytest.mark.skipif(not (OLD.is_file() and NEW.is_file()),
                                  reason='preserved 27.0.0 and 27.0.1 plugins not present')


@pytest.fixture(scope='module')
def binaries():
    from fm_live_mcp.fmdb import platform_model
    return platform_model.load_binary(OLD), platform_model.load_binary(NEW)


@needs_builds
def test_pinned_plugin_passes_every_guard(binaries):
    from fm_live_mcp import address_book
    if address_book.MAP is not None:
        pytest.skip('a map is forced: the guards are rewritten')
    old, _ = binaries
    base = 0x1_0000_0000
    rce.verify_native(lambda a, n: old.image.file_bytes(a - base, n), base)
    # the dependency spans lie inside the CBE builder function (0x488A5A4..0x488B1B0) or the engine
    # region the pinned build hashes
    (e0, en, _) = rce.WHOLE_FUNCTION_SPANS[1]
    for rva, raw in rce.DEPENDENCY_SPANS:
        assert 0x488A5A4 <= rva and rva + len(raw) <= 0x488B1B0 or e0 <= rva and rva + len(raw) <= e0 + en


def _adr(word, pc):
    assert word & 0x9F000000 == 0x10000000, 'not an ADR'
    imm = ((word >> 5) & 0x7FFFF) << 2 | (word >> 29) & 3
    return pc + (imm - (1 << 21) if imm & (1 << 20) else imm)


def _kind_cases(binary, dispatch, table):
    adr = _adr(struct.unpack('<I', binary.image.file_bytes(dispatch + 0x10, 4))[0], dispatch + 0x10)
    entries = struct.unpack('<30H', binary.image.file_bytes(table, 60))
    return [adr + 4 * e for e in entries]


@needs_builds
def test_kind_switch_sends_kinds_3_and_28_to_the_same_cases(binaries):
    """The engine's halfword event-kind table (0x54052EC / 0x54A05CC, anchored by the ADR of the
    dispatch 0x493C4D8 / 0x4A469A4): kind 3 (crossing) and kind 28 (the recovery counter) reach the
    reviewed case blocks, whose counter instructions are byte for byte the same."""
    old, new = binaries
    co = _kind_cases(old, 0x493C4D8, 0x54052EC)
    cn = _kind_cases(new, 0x4A469A4, 0x54A05CC)
    assert (co[3], cn[3]) == (0x493C7CC, 0x4A479BC)
    assert (co[28], cn[28]) == (0x493C558, 0x4A474B8)
    # ldrh/add/strh team +0xd4, cbz, ldrb/add/strb player +0xb5 (only the cbz target differs)
    a, b = old.image.file_bytes(co[3], 28), new.image.file_bytes(cn[3], 28)
    assert a[:12] == b[:12] and a[16:] == b[16:] and a[12:16] != b[12:16]
    assert old.image.file_bytes(co[28], 28) == new.image.file_bytes(cn[28], 28)
    # the completed-cross block (team +0xd6, player +0xb6) is the same 28 bytes on both builds
    assert old.image.file_bytes(0x493E710, 28) == new.image.file_bytes(0x4A48838, 28)


def _static_vm(path):
    from tests.test_match_rating_builds import _static_vm as vm
    return vm(path)[:2]


@pytest.mark.slow
@needs_builds
def test_converter_is_equal_on_every_kind_and_outcome_byte():
    """0x48930AC -> 0x494CFE0 with its own byte tables: the same category for all 65,536 signed
    (kind, outcome) bytes, as the builder passes them (sxtb); kind 3 alone reaches 12..17 and
    outcome 0 gives 12."""
    vo, base = _static_vm(OLD)
    vn, _ = _static_vm(NEW)
    crossing = {}
    for kind in range(-128, 128):
        for outcome in range(-128, 128):
            a = vo.call(base + 0x48930AC, (kind, outcome))[0] & 0xFF
            b = vn.call(base + 0x494CFE0, (kind, outcome))[0] & 0xFF
            assert a == b, (kind, outcome, a, b)
            if a in rce.CROSS_CATEGORIES:
                crossing[(kind, outcome)] = a
    assert {k for k, _ in crossing} == {3}
    assert crossing[(3, 0)] == 12 and all(c != 12 for (k, o), c in crossing.items() if o != 0)


def _reviews():
    from fm_live_mcp.fmdb import address_map
    return address_map.reviews(SHA)


@needs_builds
def test_reviewed_dependency_spans_pin_the_counterparts(binaries):
    """Each dependency span maps to its reviewed 27.0.1 place: the same bytes where unchanged, and a
    reviewed guard (with its length) where only branch targets, test order or registers differ."""
    reviews = _reviews()
    guards = (reviews.get('guards') or {}).get('retained_cross_events.py') or {}
    if '0x488a6dc' not in guards:
        pytest.skip('the 27.0.1 review of retained_cross_events is not merged yet')
    old, new = binaries
    values = reviews['values']
    for rva, raw in rce.DEPENDENCY_SPANS:
        assert old.image.file_bytes(rva, len(raw)) == raw
        key = f'{rva:#x}'
        place = int((guards.get(key) or values[key])['new' if key in guards else 'value'], 16)
        if key in guards:
            assert int(values[key]['value'], 16) == place
            assert new.image.file_bytes(place, guards[key].get('length', len(raw))) != raw
        else:
            assert new.image.file_bytes(place, len(raw)) == raw
    for key in ('0x48930ac', '0x54023c4', '0x54052ec'):
        assert key in guards


def test_replaced_hash_check_is_not_listed_as_a_withheld_section(monkeypatch):
    """The whole-function hashes return no part of the result: on a build where they cannot run,
    the tool is listed under `replaced_checks`, not `partial_tools`, and stays available."""
    from fm_live_mcp import address_book, retained_cross_events as cross
    monkeypatch.setattr(address_book, 'MAP', {'values': {}})
    monkeypatch.setattr(address_book, 'unresolved_sites', lambda: {
        ('fm_live_mcp.retained_cross_events', 'module:WHOLE_FUNCTION_SPANS'): [(0x493C244, 'function changed')]})
    cross._whole_function_hashes._blocked = None
    tools = {'cross': cross.verify_native}
    assert cross._whole_function_hashes(None, 0) is None
    assert not address_book.unavailable_tools(tools)
    assert address_book.partial_tools(tools) == {}
    replaced = address_book.partial_tools(tools, checks=True)
    assert set(replaced) == {'cross'} and set(replaced['cross']) == {'whole_function_hashes'}
    cross._whole_function_hashes._blocked = None
