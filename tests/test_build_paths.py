"""fm_live_mcp/build_paths.py: where the installed and the pinned build's files are, and the
session's default state (the pinned build, with nothing translated)."""
import hashlib
import os
import sys

import pytest

from fm_live_mcp import address_book, build_paths, players


def _app(root, name='fm.app'):
    app = root / name
    plugin = app / build_paths.PLUGIN_IN_APP
    plugin.parent.mkdir(parents=True)
    plugin.write_bytes(b'not a plugin')
    return app


def test_the_pinned_build_is_the_address_books():
    assert build_paths.PINNED_VERSION == address_book.PINNED_VERSION == players.VERSION
    assert build_paths.PRESERVED_PINNED_APP.parent.name == address_book.PINNED_VERSION


def test_app_of_finds_the_bundle(tmp_path):
    app = _app(tmp_path)
    assert build_paths.app_of(app / build_paths.PLUGIN_IN_APP) == app
    assert build_paths.app_of(tmp_path / 'game_plugin') is None


def test_installed_paths_follow_the_plugin_path(tmp_path, monkeypatch):
    app = _app(tmp_path)
    monkeypatch.setenv('FMCP_PLUGIN_PATH', str(app / build_paths.PLUGIN_IN_APP))
    assert build_paths.installed_plugin() == app / build_paths.PLUGIN_IN_APP
    assert build_paths.installed_app() == app
    monkeypatch.delenv('FMCP_PLUGIN_PATH')
    assert build_paths.installed_plugin() == build_paths.STEAM_APP / build_paths.PLUGIN_IN_APP
    assert build_paths.installed_app() == build_paths.STEAM_APP


def test_pinned_app_takes_the_environment_first(tmp_path, monkeypatch):
    app = _app(tmp_path)
    monkeypatch.setenv(build_paths.PINNED_APP_ENV, str(app))
    assert build_paths.pinned_app() == app
    assert build_paths.pinned_plugin() == app / build_paths.PLUGIN_IN_APP
    assert build_paths.pinned_path('Contents/Info.plist') == app / 'Contents/Info.plist'
    empty = tmp_path / 'empty.app'
    monkeypatch.setenv(build_paths.PINNED_APP_ENV, str(empty))
    assert build_paths.pinned_app() is None
    assert build_paths.pinned_app_or_expected() == empty          # paths under it do not exist
    assert not build_paths.pinned_path(build_paths.PLUGIN_IN_APP).exists()


def test_pinned_app_falls_back_to_the_steam_install_only_when_it_is_the_pinned_build(tmp_path, monkeypatch):
    monkeypatch.delenv(build_paths.PINNED_APP_ENV, raising=False)
    monkeypatch.setattr(build_paths, 'PRESERVED_PINNED_APP', tmp_path / 'missing.app')
    steam = _app(tmp_path, 'steam.app')
    monkeypatch.setattr(build_paths, 'STEAM_APP', steam)
    monkeypatch.setattr(build_paths, '_PINNED_CACHE', {})
    monkeypatch.setattr(address_book, 'cache_dir', lambda: tmp_path / 'cache')
    assert build_paths.pinned_app() is None                        # its plugin is another build
    plugin = steam / build_paths.PLUGIN_IN_APP
    monkeypatch.setattr(address_book, 'PINNED_SHA256', hashlib.sha256(plugin.read_bytes()).hexdigest())
    monkeypatch.setattr(build_paths, '_PINNED_CACHE', {})
    assert build_paths.pinned_app() == steam


def test_the_pinned_app_is_the_pinned_build():
    app = build_paths.pinned_app()
    if app is None:
        pytest.skip(build_paths.PINNED_MISSING)
    with (app / build_paths.PLUGIN_IN_APP).open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == address_book.PINNED_SHA256
    for relative in (build_paths.GAME_ASSEMBLY_IN_APP, build_paths.METADATA_IN_APP, 'Contents/Info.plist',
                     build_paths.BUNDLE_IN_APP / 'Info.plist', build_paths.BUNDLE_IN_APP / 'Resources/shared/data/editor.fmf'):
        assert (app / relative).is_file(), relative


def test_a_pinned_session_translates_nothing():
    if os.environ.get('FMCP_TEST_BUILD') != 'pinned':
        pytest.skip('this session does not address the pinned build')
    assert address_book.ACTIVE['state'] == 'pinned' and address_book.MAP is None
    assert not any(isinstance(f, address_book._Finder) for f in sys.meta_path)
    assert (players.VERSION, players.SHA256) == (address_book.PINNED_VERSION, address_book.PINNED_SHA256)
    pinned = build_paths.pinned_plugin()
    if pinned is not None:                       # the run-time defaults read the pinned files too
        assert os.environ['FMCP_PLUGIN_PATH'] == str(pinned)
        assert build_paths.installed_app() == build_paths.pinned_app()
        from fm_live_mcp.fmdb import catalog, labels
        assert catalog.DEFAULT_EDITOR_FMF.is_relative_to(build_paths.pinned_app())
        assert labels.DEFAULT_APP == build_paths.pinned_app()
