"""Transport failures must close/reap the helper and never reuse its channel."""
from dataclasses import replace
import json
import shlex
import sys

import pytest

from fm_live_mcp import bridge as module
from fm_live_mcp.reader import ReadStream, ReaderError
from test_bridge import bridge, PROCESS


def fake_helper(tmp_path, code):
    if sys.platform == 'win32':
        pytest.skip('the helper process is the macOS read route; its stand-in here is a shell script')
    path = tmp_path / 'reader'
    script = tmp_path / 'reader.py'
    script.write_text(code)
    path.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(script))} "$@"\n')
    path.chmod(0o700)
    return path


@pytest.mark.parametrize('response', [
    'not JSON', '[]', '{"ok":false}',
    json.dumps({'ok': True, 'pid': 99, 'command': 'read-stream'}),
    json.dumps({'ok': True, 'pid': 42, 'command': 'wrong'}),
    'x' * 34001,
])
def test_invalid_handshake_reaps_helper(tmp_path, response):
    reader = ReadStream(fake_helper(tmp_path, f'print({response!r}, flush=True)\n'), 42)
    with pytest.raises(ReaderError): reader.read(4096, 8)
    assert reader.closed and reader.child.poll() is not None


@pytest.mark.parametrize('updates', [
    {'addr': '0x2000'}, {'len': 7}, {'hex': '00'}, {'hex': None}, {'pid': 99},
])
def test_response_must_match_complete_request(tmp_path, updates):
    response = {'ok': True, 'pid': 42, 'command': 'read-bytes', 'addr': '0x1000',
                'len': 8, 'hex': '00' * 8, **updates}
    code = ('import sys\n'
            'print(\'{"ok":true,"pid":42,"command":"read-stream"}\', flush=True)\n'
            'sys.stdin.readline()\n'
            f'print({json.dumps(response)!r}, flush=True)\n')
    reader = ReadStream(fake_helper(tmp_path, code), 42)
    with pytest.raises(ReaderError): reader.read(4096, 8)
    assert reader.closed and reader.child.poll() is not None


def test_timeout_reaps_helper(tmp_path):
    reader = ReadStream(fake_helper(tmp_path, 'import time\ntime.sleep(10)\n'), 42, timeout=.05)
    with pytest.raises(ReaderError, match='timed out'): reader.read(4096, 8)
    assert reader.child.poll() is not None


def test_scope_rechecks_process_and_cleans_up(bridge, monkeypatch):
    with pytest.raises(module.BridgeError, match='restarted'):
        with bridge.lock, bridge._read_scope(bridge.session):
            reader = bridge._reader
            monkeypatch.setattr(module, 'process_info', lambda pid: replace(PROCESS, started='new'))
    assert reader.closed and bridge._reader is None and bridge.session is None


def test_scope_closes_after_decoder_failure(bridge):
    with pytest.raises(ValueError):
        with bridge.lock, bridge._read_scope(bridge.session):
            reader = bridge._reader
            raise ValueError('changed bytes')
    assert reader.closed and bridge._reader is None
