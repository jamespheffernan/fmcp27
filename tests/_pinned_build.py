"""The pinned game build's files for tests (fm_live_mcp/build_paths.py decides where they are).

Tests that compare code, data or hashes with build 27.0.0.2493426 take its files from here, never
from the Steam install, which a game update replaces. When this machine has no pinned build the
paths below do not exist, and tests/conftest.py skips every test of a module that imports this one
at module level (directly or through another test module) with `MISSING` as the reason; a test that
imports it inside its body must check for the file itself.
"""
from fm_live_mcp import build_paths

APP = build_paths.pinned_app_or_expected()          # .../fm.app
AVAILABLE = build_paths.pinned_app() is not None
MISSING = build_paths.PINNED_MISSING
CONTENTS = APP / 'Contents'
PLUGIN = APP / build_paths.PLUGIN_IN_APP
BUNDLE = APP / build_paths.BUNDLE_IN_APP            # .../game_plugin.bundle/Contents
GAME_ASSEMBLY = APP / build_paths.GAME_ASSEMBLY_IN_APP
METADATA = APP / build_paths.METADATA_IN_APP
EDITOR_FMF = BUNDLE / 'Resources/shared/data/editor.fmf'
# The English language template (155 MB) was not preserved for the pinned build, and the 27.0.1
# update changed it; tests that compare with it call language_template(), which skips without it.
LANGUAGE_TEMPLATE = BUNDLE / 'Resources/data/game_simulation/templates/user_folder/languages/example.ltf'
LANGUAGE_MISSING = (f"needs the pinned build's English language template, which was not preserved: put the "
                    f"example.ltf of build {build_paths.PINNED_VERSION} at {LANGUAGE_TEMPLATE}")


def language_template():
    """The pinned build's example.ltf, or skip the calling test when it is absent."""
    if not LANGUAGE_TEMPLATE.is_file():
        import pytest
        pytest.skip(LANGUAGE_MISSING)
    return LANGUAGE_TEMPLATE


LANGUAGE_TEMPLATE_SHA256 = '3ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43'
_STEAM_LANGUAGE: dict = {}


def require_steam_language_template():
    """Skip unless the Steam install's example.ltf is the pinned build's: for evidence collectors
    (git-ignored, under evidence/) that read it from the Steam path and refuse any other."""
    import hashlib
    path = build_paths.STEAM_APP / LANGUAGE_TEMPLATE.relative_to(APP)
    if path not in _STEAM_LANGUAGE:
        try:
            with path.open('rb') as stream:
                _STEAM_LANGUAGE[path] = hashlib.file_digest(stream, 'sha256').hexdigest()
        except OSError:
            _STEAM_LANGUAGE[path] = None
    if _STEAM_LANGUAGE[path] != LANGUAGE_TEMPLATE_SHA256:
        import pytest
        pytest.skip('the evidence collector reads the Steam install\'s English language template and requires '
                    f'the pinned build\'s; the installed one ({path}) is another build\'s')
