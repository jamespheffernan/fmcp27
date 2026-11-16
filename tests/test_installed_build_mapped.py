"""The installed game build through its address map, checked without the game: `pytest -m mapped_build`.

This file is `mapped_build` (tests/conftest.py marks `*_mapped.py`), so it runs only in a session
that addresses the installed build: the package was imported with the installed build's map, as
the MCP server does at start. The map comes from `scripts/fm_update_build.py --installed` in
$FMCP_CACHE_DIR/fmdb/anchors/. When the installed game is the pinned build there is nothing to map
and the checks skip.
"""
import importlib
import plistlib
import pkgutil

import pytest

import fm_live_mcp
from fm_live_mcp import address_book as ab, build_paths


@pytest.fixture(scope='module')
def mapped():
    plugin = build_paths.installed_plugin()
    if not plugin.is_file():
        pytest.skip(f'no installed plugin at {plugin}')
    if ab.ACTIVE['state'] == 'pinned' and build_paths.installed_is_pinned():
        pytest.skip('the installed game is the pinned build: there is no address map to check')
    assert ab.ACTIVE['state'] == 'mapped', ab.report()     # the report names the update command
    return ab.MAP


def test_the_session_loaded_the_map_of_the_installed_plugin(mapped):
    sha = ab.plugin_sha256(build_paths.installed_plugin())
    assert mapped['format'] == ab.MAP_FORMAT
    assert mapped['plugin_sha256'] == sha == ab.ACTIVE['sha256'] != ab.PINNED_SHA256
    assert mapped['reference_sha256'] == ab.PINNED_SHA256
    assert ab.verified(mapped) == (True, '')
    info = plistlib.loads((build_paths.installed_app() / 'Contents/Info.plist').read_bytes())
    assert mapped['version'] == ab.ACTIVE['version'] == info['CFBundleShortVersionString']
    # The build identity the gates compare with follows the map.
    from fm_live_mcp import players
    assert (players.VERSION, players.SHA256) == (mapped['version'], sha)


def test_the_map_resolves_exactly_the_census_addresses(mapped):
    census = ab.census()
    assert census['pinned_sha256'] == ab.PINNED_SHA256
    addresses = {int(k, 16) for entries in census['files'].values() for k, e in entries.items() if e['d'] == 'A'}
    values = {int(k, 16): e for k, e in mapped['values'].items()}
    assert set(values) == addresses
    for pinned, entry in values.items():
        if entry['value'] is None:
            assert entry.get('detail') or entry.get('method'), hex(pinned)     # says why it did not resolve
        else:
            assert isinstance(entry['value'], int) and 0 <= entry['value'] < 2 * census['image_end'], hex(pinned)
    for rel, per_file in mapped['per_file'].items():
        assert rel in census['files'], rel
        assert {int(k, 16) for k in per_file} <= addresses, rel
    for rel in (mapped.get('guards') or {}).get('files') or {}:
        assert rel in census['files'] or (ab.PACKAGE_DIR / rel).is_file(), rel
    for rel in mapped.get('disabled') or {}:
        assert (ab.PACKAGE_DIR / rel).is_file(), rel


def test_every_module_imports_through_the_map(mapped):
    failed = {}
    for module in pkgutil.walk_packages(fm_live_mcp.__path__, 'fm_live_mcp.'):
        if module.name.endswith('.__main__'):
            continue
        try:
            importlib.import_module(module.name)
        except BaseException as exc:  # noqa: BLE001 - every failure is reported
            failed[module.name] = f'{type(exc).__name__}: {exc}'[:300]
    assert not failed
    assert ab._REWRITTEN, 'no module was rewritten through the map'


def test_tools_register_and_the_report_names_the_unavailable_ones(mapped):
    from fm_live_mcp import server
    tools = ab.tool_functions(server.mcp)
    assert len(tools) > 50
    report = ab.report(tools)
    assert report['state'] == 'mapped'
    assert report['build'] == mapped['version'] and report['pinned_build'] == ab.PINNED_VERSION
    assert report['addresses']['total'] == len(mapped['values'])
    assert 0 < report['addresses']['resolved'] <= report['addresses']['total']
    assert set(report['unavailable_tools']) <= set(tools)
    assert report['available_tools'] == len(tools) - len(report['unavailable_tools'])
    for name, reasons in report['unavailable_tools'].items():          # each names why
        assert reasons and all(isinstance(r, str) and r for r in reasons), name


def test_the_update_report_has_its_shape(mapped):
    sha = mapped['plugin_sha256']
    path = ab.map_path(sha).with_name(f'{sha}.update-report.json')
    if not path.is_file():
        pytest.skip(f'no update report next to the map ({path})')
    import json
    report = json.loads(path.read_text())
    assert report['sha256'] == sha and report['version'] == mapped['version']
    assert report['reference_sha256'] == ab.PINNED_SHA256
    assert all(isinstance(v, (int, float)) for v in report['steps'].values())
    assert set(report['addresses']) >= {'groups', 'modules', 'methods', 'unresolved'}
    anchors = report['named_anchors']
    assert anchors['resolved'] <= anchors['total'] and anchors['missing_required'] == []
    assert all(isinstance(v, int) for v in report['guards'].values())
    check = report['import_check']
    assert check['ok'] is True and check['state'] == 'mapped' and check['failed_imports'] == {}
    assert check['tool_count'] > 50 and isinstance(check['tools'], dict) and isinstance(check['tables'], dict)


def test_the_front_end_of_the_installed_build_is_its_own(mapped):
    """The update command extracted the installed build's front end next to the map, and the
    screen tools read it: translation ids, data collections, the property registry, record
    schemas and the screen-parameter globals of this plugin (docs/GAME_UPDATE.md)."""
    from fm_live_mcp.fmdb import ui_frontend, ui_params, ui_registry
    path = ui_frontend.build_path(mapped['plugin_sha256'])
    if not path.is_file():
        pytest.skip(f'no front-end table next to the map ({path}); scripts/fm_update_build.py --installed writes it')
    ui_frontend.reset()
    source = ui_frontend.active_source()
    assert source['per_build'] and source['path'] == str(path) and source['note'] is None
    data = ui_frontend.table()
    assert data['build']['plugin_sha256'] == mapped['plugin_sha256']
    assert data['build']['version'] == mapped['version']
    for name in ('OverallHappinessDataCollection', 'PlayingTimeHappinessDataCollection',
                 'ClubVisionProgressDataCollection', 'ClubVisionImportanceDataCollection'):
        row = data['data_collections'][name]
        assert row['translations'] and len(row['keys']) == len(row['translations']), name
    # every screen-parameter global is a global of this plugin, and the five the source names agree
    end = ab.census()['image_end'] * 2
    params = ui_params.table()
    assert len(params) == len(data['plugin_params']) > 200
    assert all(0 < row['rva'] < end for row in params.values())
    from fm_live_mcp.fmdb import ui_recipes_screens as S
    for name, rva in S.PARAMS.items():
        assert params[name]['rva'] == rva, name
    # the UI registry of this build carries the keys this build's front end added
    report = ab.map_path(mapped['plugin_sha256']).with_name(f'{mapped["plugin_sha256"]}.update-report.json')
    if report.is_file():
        import json
        keys = json.loads(report.read_text())['extras'].get('ui_registry_keys') or {}
        labels = ui_registry.default().labels
        assert all(k in labels for k in keys.get('added', ())) and not any(k in labels for k in keys.get('removed', ()))


def test_the_translator_global_follows_the_exported_accessor(mapped):
    """`ui_recipes_screens.TRANSLATOR_GLOBAL_RVA` is the global `_i_translator_get_instance`
    returns on this build (27.0.1's first map sent it to the characters global: every
    front-end word read null)."""
    from fm_live_mcp.fmdb import function_match, platform_model
    from fm_live_mcp.fmdb import ui_recipes_screens as S
    binary = platform_model.load_binary(build_paths.installed_plugin())
    start = function_match.exported_functions(binary)['_i_translator_get_instance']
    refs = binary.refs_in(*binary.function_of(start))
    assert S.TRANSLATOR_GLOBAL_RVA == refs[-1][1]          # the last load is the returned instance


def test_the_compiled_english_follows_the_installed_template(mapped):
    """When the update found every compiled concern and promise text unchanged in the installed
    example.ltf, those modules are bound to that file (the concern-history query accepts it)."""
    english = mapped.get('english_template')
    if not english:
        pytest.skip('the map records no English template (the update could not read it)')
    from fm_live_mcp import _concern_template_definitions as concern, live_player_concern_history as query
    from fm_live_mcp import promise_kind_definitions as kinds
    path = build_paths.installed_app() / 'Contents/PlugIns/game_plugin.bundle/Contents' / query.ENGLISH_RELATIVE_PATH
    assert english['verified'] is True and english['differ'] == []
    assert path.stat().st_size == english['bytes'] == query.ENGLISH_RESOURCE_BYTES
    assert concern.ENGLISH_RESOURCE_SHA256 == kinds.ENGLISH_SHA256 == english['sha256']
