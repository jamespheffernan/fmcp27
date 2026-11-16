"""Mutation controls and real native one-byte transport against owned test memory."""
import asyncio
import json
import struct
import subprocess
import sys

import pytest
from mcp.server.fastmcp import FastMCP
from fm_live_mcp.bridge import BridgeError, ROOT
from fm_live_write import training_editor as editor
from fm_live_write.tools import register_training_edit_tools


@pytest.mark.parametrize('before,after', [(255, 0), (0, 1), (1, 2), (2, 254), (254, 255)])
def test_request_preserves_zero_and_signed_native_choices(before, after):
    encoded = editor.encode_request(123, 0x1000, 0x10000, before, after,
        {(0x1000, 8): struct.pack('<Q', 0x10000), (0x11eb, 1): bytes([before])})
    assert struct.unpack_from('<8sIQQBBI', encoded) == (b'FMTEDIT1', 123, 0x1000, 0x10000, before, after, 2)


@pytest.mark.parametrize('code', [True, False, -1, 3, 253, 256, '1', None])
def test_unknown_or_coerced_expected_selection_never_reaches_bridge(code):
    with pytest.raises(BridgeError, match='expected_raw_code'):
        editor.set_player_training_intensity(None, 's', 'p', 'half', code)


def test_tool_is_discoverable_as_a_game_edit():
    mcp = FastMCP('editor-test')
    register_training_edit_tools(mcp, None)
    tool, = asyncio.run(mcp.list_tools())
    assert tool.name == 'fm_set_player_training_intensity'
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is True
    assert tool.annotations.idempotentHint is False
    assert 'expected_raw_code' in tool.inputSchema['required']


@pytest.mark.parametrize('value', [True, False, '1', 1.0, -1, 3, 256])
def test_mcp_rejects_coerced_and_unknown_expected_codes_before_bridge(value):
    mcp = FastMCP('editor-input-test')
    register_training_edit_tools(mcp, None)
    with pytest.raises(Exception, match='(validation|expected_raw_code)'):
        asyncio.run(mcp.call_tool('fm_set_player_training_intensity', dict(
            session_id='s', player_ref='p', intensity='half', expected_raw_code=value)))


def test_failed_outcome_receipt_keeps_write_uncertainty_explicit(monkeypatch, tmp_path):
    def full_disk(*args):
        raise OSError('disk full')
    monkeypatch.setattr(editor, '_audit', full_disk)
    with pytest.raises(BridgeError, match='Write was attempted.*do not retry automatically'):
        editor._audit_outcome(tmp_path / 'receipt.jsonl', {'event': 'verified'})


@pytest.fixture
def owned_memory():
    helper = ROOT / 'build/fm_training_editor'
    if sys.platform != 'darwin' or not helper.is_file():
        pytest.skip('Requires built signed native training editor on macOS')
    child = subprocess.Popen([sys.executable, '-u', '-c', '''
import ctypes, json, os, struct
data = ctypes.create_string_buffer(1024)
ctypes.memset(ctypes.addressof(data), 0x5a, 1024)
ctypes.memmove(ctypes.addressof(data), struct.pack('<Q', 0x10000), 8)
data[0x1eb] = b'\\xff'
print(json.dumps([os.getpid(), ctypes.addressof(data), data.raw.hex()]), flush=True)
input()
print(data.raw.hex(), flush=True)
'''], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    pid, address, raw = json.loads(child.stdout.readline())
    try:
        yield helper, child, pid, address, bytes.fromhex(raw)
    finally:
        child.terminate()
        child.communicate(timeout=5)


def native_edit(m, before=255, after=0, *, stale=False):
    helper, child, pid, address, original = m
    guard = bytearray(original)
    if stale:
        guard[0x200] ^= 1
    guards = {(address, 8): original[:8], (address, len(original)): bytes(guard)}
    payload = editor.encode_request(pid, address, 0x10000, before, after, guards)
    completed = subprocess.run([str(helper)], input=payload, capture_output=True, timeout=10)
    native = json.loads(completed.stdout)
    child.stdin.write('\n')
    child.stdin.flush()
    actual = bytes.fromhex(child.stdout.readline())
    child.wait(timeout=5)
    return completed, native, actual


def test_real_native_write_changes_exactly_one_byte(owned_memory):
    completed, native, actual = native_edit(owned_memory)
    assert completed.returncode == 0 and native['state'] == 'stored_byte_verified', native
    expected = bytearray(owned_memory[-1])
    expected[0x1eb] = 0
    assert actual == bytes(expected)
    assert native['write_performed'] is True


def test_real_native_stale_context_refuses_without_write(owned_memory):
    completed, native, actual = native_edit(owned_memory, stale=True)
    assert completed.returncode != 0 and native['state'] == 'source_changed_before_write', native
    assert native['write_performed'] is False and actual == owned_memory[-1]


def test_real_native_stale_expected_byte_refuses_without_write(owned_memory):
    completed, native, actual = native_edit(owned_memory, before=1)
    assert completed.returncode != 0 and native['state'] == 'invalid_request', native
    assert native['write_performed'] is False and actual == owned_memory[-1]
