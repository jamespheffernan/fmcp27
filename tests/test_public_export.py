"""The public export must leave local data and private Git history behind."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.export_public import publishable


@pytest.mark.parametrize('name', [
    'README.md', '.gitignore', 'fm_live_mcp/server.py', 'native/fm_live_helper.c',
    'tests/fixtures/example.json.gz', 'adviser/pi/fm.pi.ts', 'site/public/index.html',
])
def test_source_files_are_included(name):
    assert publishable(name)


@pytest.mark.parametrize('name', [
    'evidence/capture.json', 'adviser/evidence/runtime.jsonl', 'adviser/sessions/chat.jsonl',
    '.git/config', '.mcp.json', '.claude/launch.json', 'brand/ads/x/research.json',
    'site/public/download/FMCP27-mac.zip', 'adviser/evals/out/result.json',
    'site/.env', 'site/.env.production', 'native/signing.p8', 'tests/private.fm',
    'scripts/tmp/token.txt', '../README.md', '/README.md',
])
def test_local_data_is_excluded(name):
    assert not publishable(name)


def test_export_uses_committed_snapshot_and_refuses_existing_work(tmp_path):
    source = tmp_path / 'source'
    (source / 'scripts').mkdir(parents=True)
    script = source / 'scripts/export_public.py'
    shutil.copyfile(Path(__file__).parents[1] / 'scripts/export_public.py', script)
    (source / 'README.md').write_text('committed source')
    (source / 'evidence').mkdir()
    (source / 'evidence/private.json').write_text('private capture')
    def git(*args):
        return subprocess.run(['git', '-C', str(source), *args], check=True, capture_output=True)
    git('init', '-b', 'main')
    git('add', '.')
    git('-c', 'user.name=Export test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'fixture')
    (source / 'README.md').write_text('uncommitted change')
    dest = tmp_path / 'public'
    subprocess.run([sys.executable, str(script), str(dest)], check=True, capture_output=True)
    assert (dest / 'README.md').read_text() == 'committed source'
    assert not (dest / 'evidence').exists()
    assert not (dest / '.git').exists()
    result = subprocess.run([sys.executable, str(script), str(dest)], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'destination must be empty' in result.stderr
    assert (dest / 'README.md').read_text() == 'committed source'
