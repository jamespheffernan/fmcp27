"""Where Football Manager 27's files are, for two different questions.

* The installed build: what the reader reads at run time (the plugin the address book hashes,
  editor.fmf, filters.fmf, the language template, the database resources). `FMCP_PLUGIN_PATH`
  names its plugin binary; otherwise the Steam install. Sibling files come from that plugin's
  `fm.app`. Use `installed_app()` / `installed_plugin()` for anything the reader does at run time.
* The pinned build (27.0.0.2493426, `address_book.PINNED_VERSION`): what the source's literal
  addresses, the frozen fixtures, the static proofs, the research scripts and the tests were made
  from. `FMCP_PINNED_APP=<an fm.app of that build>` names it; otherwise the preserved bundle tree
  `PRESERVED_PINNED_APP` (hard links to the files `scripts/fm_update_build.py` preserved) when it
  exists; otherwise the Steam install when its plugin is the pinned one. When none of these is
  there, `pinned_app()` is None and `PINNED_MISSING` says what to provide.

A game update changes the installed build and never the pinned one, so code that compares bytes
with the pinned build must take them from `pinned_app()`, and code that reads the running game's
files must take them from `installed_app()`. Nothing here reads the game's memory.
"""
from __future__ import annotations

import os
from pathlib import Path

STEAM_APP = Path.home() / 'Library/Application Support/Steam/steamapps/common/Football Manager 27/fm.app'
PLUGIN_IN_APP = Path('Contents/PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin')
BUNDLE_IN_APP = Path('Contents/PlugIns/game_plugin.bundle/Contents')
GAME_ASSEMBLY_IN_APP = Path('Contents/Frameworks/GameAssembly.dylib')
METADATA_IN_APP = Path('Contents/Resources/Data/il2cpp_data/Metadata/global-metadata.dat')
BUILDS = Path('/Volumes/4TB Private/Offloaded/Agent Work/fmdb-runtime-research/builds')
PINNED_VERSION = '27.0.0.2493426'      # the same as address_book.PINNED_VERSION (checked by the tests)
PRESERVED_PINNED_APP = BUILDS / PINNED_VERSION / 'fm.app'
PINNED_APP_ENV = 'FMCP_PINNED_APP'
PINNED_MISSING = (f'needs the files of the pinned game build {PINNED_VERSION}: set {PINNED_APP_ENV} to an fm.app of '
                  f'that build, or provide {PRESERVED_PINNED_APP} (a tree of hard links to the files '
                  f'scripts/fm_update_build.py preserved in {BUILDS / PINNED_VERSION}; docs/TESTING.md)')


def app_of(path: str | Path) -> Path | None:
    """The `.app` directory that contains `path` (a plugin binary or any file of the bundle)."""
    for parent in Path(path).parents:
        if parent.suffix == '.app':
            return parent
    return None


# --------------------------------------------------------------------------- the installed build
def installed_plugin() -> Path:
    """The plugin binary the reader addresses at run time."""
    env = os.environ.get('FMCP_PLUGIN_PATH')
    return Path(env) if env else STEAM_APP / PLUGIN_IN_APP


def installed_app() -> Path:
    """The `fm.app` of the installed plugin (its data files sit next to it)."""
    return app_of(installed_plugin()) or STEAM_APP


# --------------------------------------------------------------------------- the pinned build
_PINNED_CACHE: dict = {}


def _is_pinned_plugin(plugin: Path) -> bool:
    try:
        stat = plugin.stat()
    except OSError:
        return False
    key = (str(plugin), stat.st_size, stat.st_mtime_ns)
    if key not in _PINNED_CACHE:
        from .address_book import PINNED_SHA256, plugin_sha256   # hashed once per file identity
        try:
            _PINNED_CACHE[key] = plugin_sha256(plugin) == PINNED_SHA256
        except OSError:
            _PINNED_CACHE[key] = False
    return _PINNED_CACHE[key]


def pinned_app() -> Path | None:
    """The `fm.app` of the pinned build, or None when this machine has none (see the module doc)."""
    env = os.environ.get(PINNED_APP_ENV)
    if env:
        return Path(env) if (Path(env) / PLUGIN_IN_APP).is_file() else None
    if (PRESERVED_PINNED_APP / PLUGIN_IN_APP).is_file():
        return PRESERVED_PINNED_APP
    if _is_pinned_plugin(STEAM_APP / PLUGIN_IN_APP):
        return STEAM_APP
    return None


def pinned_app_or_expected() -> Path:
    """`pinned_app()`, or where its files are expected (paths under it then do not exist), so a
    module can name its pinned-build files at import and refuse or skip only when it opens them."""
    return pinned_app() or Path(os.environ.get(PINNED_APP_ENV) or PRESERVED_PINNED_APP)


def pinned_plugin() -> Path | None:
    app = pinned_app()
    return app / PLUGIN_IN_APP if app else None


def pinned_path(relative: str | Path) -> Path:
    """A file of the pinned build by its path inside `fm.app` (it may not exist; see above)."""
    return pinned_app_or_expected() / relative


def installed_is_pinned() -> bool:
    """True when the installed plugin is the pinned build's."""
    return _is_pinned_plugin(installed_plugin())
