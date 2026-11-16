"""Frozen6499-byte training resource fixture from the accepted FM27 build.

ArchiveSHA25663b209ef8660bf5ce39c36b1348c79dcdec6eb2b3f7c6479e9fb30d23c26f69d.
Exercises actual resource verification in portable Bridge tests; no game reads.
"""
import base64
import plistlib

from fm_live_mcp import players


RESOURCE_BYTES = base64.b64decode(
    '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'
)


def training_resource_bundle(tmp_path, executable_name='Football Manager 27'):
    """Return a temporary FM27 app bundle with the exact verified resource."""
    contents = tmp_path / 'fm.app/Contents'
    executable = contents / 'MacOS' / executable_name
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b'fixture executable')
    (contents / 'Info.plist').write_bytes(plistlib.dumps({
        'CFBundleIdentifier': 'com.SportsInteractive.FootballManager27',
        'CFBundleExecutable': executable_name,
        'CFBundleShortVersionString': players.VERSION}))
    resource = contents / 'PlugIns/game_plugin.bundle/Contents/Resources/data/game_simulation/training.fmf'
    resource.parent.mkdir(parents=True)
    resource.write_bytes(RESOURCE_BYTES)
    return {'executable': executable, 'contents': contents, 'resource': resource}
