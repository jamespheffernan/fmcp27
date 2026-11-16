"""The tactic writer means the same on the installed build as on the pinned one (two-build emulation).

Runs scripts/adviser_two_build.py on two templates of the Tactics folder (one native format 26, one
27) and the adviser's whole-plan fixture request: once on the pinned plugin with the pinned
addresses, once on the installed plugin through its address map, and compares everything the
writer consumes. The only expected difference is the game version the serializer stamps in bytes
11..14, which the writer replaces with the source's. Needs the preserved pinned plugin, the
installed game's files, its address map, the codec's Python and the Tactics folder; skips without.
About two minutes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from fm_live_mcp import address_book as ab

ROOT = Path(__file__).resolve().parents[1]
PINNED = Path('/Volumes/4TB Private/Offloaded/Agent Work/fmdb-runtime-research/builds/27.0.0.2493426/game_plugin')
TACTICS = Path.home() / 'Library/Application Support/Sports Interactive/Football Manager 27/Tactics'
CODEC_PYTHON = Path(os.environ.get('PI_FM_TACTIC_PYTHON', '/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/bin/python'))
TEMPLATES = ('3421 FM27 .fmf', '4231 FM27 .fmf')
FIXTURE = ROOT / 'adviser/tests/fixtures/native-authoring-plan.json'


def _skip_reason():
    if not PINNED.is_file():
        return 'the preserved pinned plugin is not on this machine'
    if not ab.DEFAULT_PLUGIN.is_file():
        return 'no installed game'
    sha = ab.plugin_sha256(ab.DEFAULT_PLUGIN)
    if sha == ab.PINNED_SHA256:
        return 'the installed game is the pinned build'
    if not ab.map_path(sha).is_file():
        return f'no address map for the installed build in {ab.cache_dir()}'
    if not CODEC_PYTHON.is_file() or not all((TACTICS / t).is_file() for t in TEMPLATES):
        return 'the codec Python or the Tactics templates are missing'
    return None


def _run(args, env, tmp, python=sys.executable):
    base = {k: v for k, v in os.environ.items() if not k.startswith(('FMCP_ADDRESS', 'PYTEST'))}
    base.update(PYTHONPATH=str(ROOT), PI_FM_TACTIC_READER_ROOT=str(ROOT), PYTHONDONTWRITEBYTECODE='1',
                TMPDIR=str(tmp), **env)
    proc = subprocess.run([str(python), str(ROOT / 'scripts/adviser_two_build.py'), *args], env=base, cwd=tmp,
                          capture_output=True, text=True, timeout=1500)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return proc.stdout


def test_tactic_writer_means_the_same_on_the_installed_build(tmp_path):
    reason = _skip_reason()
    if reason:
        pytest.skip(reason)
    templates, tacs = tmp_path / 'templates', tmp_path / 'tacs'
    templates.mkdir()
    for name in TEMPLATES:
        shutil.copy2(TACTICS / name, templates / name)
    request = json.loads(FIXTURE.read_text())['request']
    request['template_path'] = str(templates / Path(request['template_path']).name)
    (tmp_path / 'request.json').write_text(json.dumps(request))
    _run(['extract', '--templates', str(templates), '--tacs', str(tacs)], {}, tmp_path, CODEC_PYTHON)
    common = ['--tacs', str(tacs), '--request', str(tmp_path / 'request.json'), '--targets', '--limit', '2']
    _run(['run', '--out', str(tmp_path / 'pinned.json'), *common],
         {'FMCP_ADDRESS_BOOK': 'off', 'PI_FM_NATIVE_BINARY': str(PINNED)}, tmp_path)
    _run(['run', '--out', str(tmp_path / 'mapped.json'), *common],
         {'FMCP_ADDRESS_BOOK': 'on', 'PI_FM_NATIVE_BINARY': str(ab.DEFAULT_PLUGIN)}, tmp_path)
    pinned, mapped = (json.loads((tmp_path / f).read_text()) for f in ('pinned.json', 'mapped.json'))
    assert pinned['adviser_state']['state'] == 'pinned' and mapped['adviser_state']['state'] == 'mapped'
    assert len(pinned['payloads']) == 2 and all(p['validate']['ok']['accepted'] for p in pinned['payloads'].values())
    assert 'error' not in mapped['acceptance'], mapped['acceptance']
    sys.path.insert(0, str(ROOT / 'scripts'))
    import adviser_two_build
    diffs = adviser_two_build.compare(tmp_path / 'pinned.json', tmp_path / 'mapped.json')
    assert diffs == []
    # the version the game's serializer stamps (bytes 11..14) is the only raw difference
    assert {h[22:30] for h in pinned['writer_headers']} == {'1b000000'}
    assert {h[22:30] for h in mapped['writer_headers']} != {'1b000000'}
