"""Run the user's own Codex CLI for Enhance Mode image generation.

Generation is billed to the ChatGPT plan Codex is signed in with. No API key is read,
passed or required: the two key variables are removed from the child environment so a
key in the shell can never take the place of the plan.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

API_KEY_VARIABLES = ('OPENAI_API_KEY', 'CODEX_API_KEY')
INSTALL = 'Install the Codex CLI (https://developers.openai.com/codex/cli), then run `codex login` and choose "Sign in with ChatGPT".'


def binary() -> str | None:
    """FMCP_CODEX_BIN, then PATH, then the usual install locations (a desktop app's PATH is short)."""
    chosen = os.environ.get('FMCP_CODEX_BIN')
    if chosen:
        return chosen if Path(chosen).is_file() else None
    found = shutil.which('codex')
    if found:
        return found
    home = Path.home()
    for path in (home/'.local/bin/codex', home/'.codex/packages/standalone/current/bin/codex',
                 Path('/opt/homebrew/bin/codex'), Path('/usr/local/bin/codex')):
        if path.is_file():
            return str(path)
    return None


def environment() -> dict:
    return {k: v for k, v in os.environ.items() if k not in API_KEY_VARIABLES}


def _text(command: list[str]) -> str:
    done = subprocess.run(command, env=environment(), stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=60)
    return (done.stdout + done.stderr).strip()


def doctor() -> dict:
    """Is Codex installed, signed in with ChatGPT, and allowed to generate images?"""
    exe = binary()
    if not exe:
        return {'ready': False, 'problem': 'The Codex CLI was not found.', 'fix': INSTALL}
    try:
        version, login, features = _text([exe, '--version']), _text([exe, 'login', 'status']), _text([exe, 'features', 'list'])
    except (OSError, subprocess.SubprocessError) as exc:
        return {'ready': False, 'codex': exe, 'problem': f'Codex did not answer: {exc}', 'fix': INSTALL}
    report = {'codex': exe, 'version': version, 'login': login.splitlines()[-1] if login else ''}
    if 'chatgpt' not in login.lower():
        return {**report, 'ready': False, 'problem': 'Codex is not signed in with a ChatGPT account.',
                'fix': 'Run `codex login` and choose "Sign in with ChatGPT". Enhance Mode uses that plan, never an API key.'}
    flag = [line.split() for line in features.splitlines() if line.startswith('image_generation')]
    if flag and flag[0][-1] != 'true':
        return {**report, 'ready': False, 'problem': 'Image generation is switched off in Codex.',
                'fix': 'Run `codex features enable image_generation`.'}
    return {**report, 'ready': True}


def run(prompt: str, folder: Path, log: Path, *, resume: str | None = None, timeout: float = 2700) -> dict:
    """One non-interactive Codex turn in `folder`. The JSON event stream is kept in `log`."""
    exe = binary()
    if not exe:
        return {'ok': False, 'thread_id': resume, 'error': 'The Codex CLI was not found.'}
    command = [exe, 'exec'] + (['resume'] if resume else []) + [
        '--json', '--skip-git-repo-check', '--enable', 'image_generation',
        # Write access stops at the packet; the game, the repository and the save stay read-only.
        '-c', 'sandbox_mode="workspace-write"', '-c', 'approval_policy="never"']
    command += [resume, '-'] if resume else ['-C', str(folder), '-']
    with log.open('wb') as stream:
        try:
            done = subprocess.run(command, input=prompt.encode(), stdout=stream, stderr=subprocess.PIPE,
                                  cwd=folder, env=environment(), timeout=timeout)
        except subprocess.TimeoutExpired:
            return {'ok': False, 'thread_id': resume, 'error': f'Codex did not finish within {int(timeout)} seconds.'}
        except OSError as exc:
            return {'ok': False, 'thread_id': resume, 'error': f'Codex could not start: {exc}'}
    result = {'ok': False, 'thread_id': resume, 'final_message': None, 'usage': None, 'error': None}
    for line in log.read_text(errors='replace').splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind, item = event.get('type'), event.get('item') or {}
        if kind == 'thread.started':
            result['thread_id'] = event.get('thread_id')
        elif kind == 'item.completed' and item.get('type') == 'agent_message':
            result['final_message'] = item.get('text')
        elif kind == 'turn.completed':
            result['ok'], result['usage'] = True, event.get('usage')
        elif kind in ('turn.failed', 'error'):
            result['error'] = (event.get('error') or {}).get('message') or event.get('message') or 'Codex reported a failed turn.'
    if done.returncode or not result['ok']:
        result['ok'] = False
        result['error'] = result['error'] or done.stderr.decode(errors='replace').strip()[-400:] or f'Codex exited with status {done.returncode}.'
    return result
