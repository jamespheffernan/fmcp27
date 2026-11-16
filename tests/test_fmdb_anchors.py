"""Build-independent anchors (fmdb/anchors.py) and the build switch (fmdb/build.py).

Offline tests need the pinned build's plugin binary (tests/_pinned_build.py) (skipped otherwise); live tests need a
running FM27 (skipped otherwise). Nothing here writes to the game.
"""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

from fm_live_mcp import players, world
from fm_live_mcp.fmdb import anchors, build, tables, vm

import _pinned_build

PLUGIN = _pinned_build.PLUGIN
FM26 = Path('/Volumes/External SSD/SteamLibrary/steamapps/common/Football Manager 26/fm.app/Contents/'
            'PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin')


def _pinned_plugin():
    return PLUGIN.is_file() and build.plugin_sha256(PLUGIN) == players.SHA256


needs_plugin = pytest.mark.skipif(not _pinned_plugin(), reason='pinned FM27 plugin not installed')


def _live_available():
    if sys.platform != 'darwin' or not _pinned_plugin():
        return False
    try:
        from fm_live_mcp.bridge import Bridge, discover_processes
        return Bridge().helper.is_file() and len(discover_processes()) == 1
    except Exception:  # noqa: BLE001
        return False


needs_live = pytest.mark.skipif(not _live_available(), reason='FM27 not running or helper missing')


@pytest.fixture(scope='module')
def binary():
    return anchors.Binary(PLUGIN)


# ----------------------------------------------------------------------------- offline
def test_decoders():
    # adrp x8, #0x56d2000 at 0x1016814 (from the plugin) and its paired str x8,[x9,#0xb50]
    assert anchors.is_adrp(0x90000008)
    assert anchors.page_use(0xF905A928, 9) == ('str64', 0xB50)
    assert anchors.page_use(0x91360108, 8) == ('add', 0xD80)
    assert anchors.is_fourcc(0x50434142) and not anchors.is_fourcc(0x00000001)
    assert anchors.movz_movk_value([0x52882848, 0x72AA0868]) == [0x50434142]


def test_build_apply_and_restore():
    pinned = anchors.pinned()
    moved = dict(pinned)
    moved['world.CURRENT_DATE'] = pinned['world.CURRENT_DATE'] + 0x40
    moved['tables.CLASSES.CLUB.getter'] = 0x1234
    try:
        build.apply(moved, sha256='0' * 64, version='test', source='test')
        assert world.CURRENT_DATE == pinned['world.CURRENT_DATE'] + 0x40
        assert tables.CLASSES[pinned['tables.CLASSES.CLUB.vtable']] == ('CLUB', 0x1234, 0)
        assert vm.INTERCEPTORS[0][0] == vm.APP_GLOBAL_RVA
        assert build.ACTIVE['sha256'] == '0' * 64 and not build.is_pinned()
    finally:
        build.restore_pinned()
    assert world.CURRENT_DATE == pinned['world.CURRENT_DATE']
    assert tables.CLASSES[pinned['tables.CLASSES.CLUB.vtable']][1] == pinned['tables.CLASSES.CLUB.getter']
    assert build.is_pinned()


def test_apply_refuses_incomplete_anchor_sets():
    partial = {k: v for k, v in anchors.pinned().items() if not k.startswith('database.TABLES.people')}
    with pytest.raises(build.BuildError, match='required'):
        build.apply(partial, sha256='1' * 64, version='test', source='test')
    assert build.is_pinned()


def test_activate_without_anchor_file(tmp_path):
    fake = tmp_path / 'game_plugin'
    fake.write_bytes(b'not the pinned plugin')
    with pytest.raises(build.BuildError, match='no anchor file'):
        build.activate(fake, directory=tmp_path)
    assert build.is_pinned()


def test_reference_index_is_shipped():
    index = anchors.load_reference()
    assert index is not None
    names = set(anchors.pinned())
    covered = {k.split('#')[0] for k in index}
    assert len(names & covered) >= 0.9 * len(names)


@needs_plugin
def test_semantic_discovery_matches_pinned(binary):
    """RTTI + code shape only (no fingerprints, no live scan): every value found equals the
    pinned one; the RVAs that need the live scan or a fingerprint are the only ones missing."""
    found = anchors.resolve(binary)
    rows = anchors.compare(found)
    verdicts = {}
    for name, (verdict, _a, _v) in rows.items():
        verdicts.setdefault(verdict, []).append(name)
    assert not verdicts.get('mismatch'), verdicts.get('mismatch')
    assert len(verdicts['match']) >= 170
    assert all(n in verdicts['match'] for n in rows if n.startswith('tables.CLASSES.'))
    assert {'vm.THREAD_FLAG_RVA', 'vm.THREAD_MAIN_RVA', 'vm.THREAD_OTHER_RVA', 'world.CURRENT_DATE'} \
        <= set(verdicts['match'])


@needs_plugin
def test_fingerprint_index_resolves_every_pinned_anchor(binary):
    found = anchors.resolve(binary, index=anchors.load_reference())
    rows = anchors.compare(found)
    bad = {n: v for n, (v, _a, _p) in rows.items() if v not in ('match', 'equivalent')}
    assert not bad, bad


@pytest.mark.skipif(not FM26.is_file(), reason='FM26 plugin not installed')
def test_older_build_loads_and_resolves_statically():
    fm26 = anchors.Binary(FM26)
    assert len(fm26.rtti) > 5000 and len(fm26.starts) > 100000
    found = anchors.resolve(fm26, index=anchors.load_reference())
    rows = anchors.compare(found, same_build=False)
    assert sum(1 for v, _a, _p in rows.values() if v == 'found') >= 150
    for cls in ('ACTUAL_PLAYER', 'CLUB', 'TEAM'):
        assert anchors.getter_shape(fm26, found[f'tables.CLASSES.{cls}.getter'].value) or \
            'thunk' in found[f'tables.CLASSES.{cls}.getter'].detail


# ----------------------------------------------------------------------------- live
@needs_live
def test_live_scan_completes_the_anchor_set(binary):
    memory, base = anchors.open_live(binary)
    assert memory is not None, base
    try:
        typed = anchors.scan_live_globals(binary, memory.read, base, memory.read_many)
    finally:
        memory.close()
    semantic = anchors.compare(anchors.resolve(binary, typed=typed))
    assert not [n for n, (v, _a, _p) in semantic.items() if v == 'mismatch']
    assert all(semantic[f'database.TABLES.{k}.root'][0] == 'match' for k in ('people', 'clubs', 'teams'))
    full = anchors.compare(anchors.resolve(binary, index=anchors.load_reference(), typed=typed))
    assert all(v in ('match', 'equivalent') for v, _a, _p in full.values())


@needs_live
def test_open_build_reads_through_rebound_constants(binary, tmp_path):
    """Engine.open_build on the pinned build, then the same reads after rebinding every module
    constant from a freshly derived anchor set: identical values."""
    from fm_live_mcp.fmdb.engine import Engine
    engine = Engine.open_build()
    try:
        info = engine.save_info()
        from fm_live_mcp.fmdb import bulkplans
        sample = tables.sample(engine.read, engine.base, 'play', 5)
        before = [repr(bulkplans.canonical(engine.get_property(p, 'PCAB'))) for p in sample]
        assert any(v.isdigit() for v in before), before
        memory, base = anchors.open_live(binary)
        typed = anchors.scan_live_globals(binary, memory.read, base, memory.read_many)
        memory.close()
        found = anchors.resolve(binary, index=anchors.load_reference(), typed=typed)
        try:
            build.apply({n: a.value for n, a in found.items()}, sha256='2' * 64, version='rebased',
                        source='test')
            engine.fresh()
            assert engine.save_info().save_name == info.save_name
            after = [repr(bulkplans.canonical(engine.get_property(p, 'PCAB'))) for p in sample]
        finally:
            build.restore_pinned()
        assert before == after
    finally:
        engine.close()


def test_platform_model_dispatch(tmp_path):
    from fm_live_mcp.fmdb import platform_model
    pe = tmp_path / 'game_plugin.dll'
    pe.write_bytes(b'MZ' + bytes(62))
    with pytest.raises(platform_model.PlatformError, match='Windows PE'):
        platform_model.load_binary(pe)
    assert platform_model.AAPCS64.this == 'x0' and platform_model.WIN64.this == 'rcx'


@needs_plugin
def test_platform_model_answers_the_shape_questions(binary):
    from fm_live_mcp.fmdb import platform_model
    model = platform_model.load_binary(PLUGIN)
    assert set(model.virtual_bool_check_globals(7)) == {g for g, _r, _s, _o in vm.INTERCEPTORS}
    assert model.type_key('N2db6PERSONE') == 'N2db6PERSONE'
    assert len(model.fourcc_constants(0xE476C4)) > 300          # the CLUB getter's key tree
