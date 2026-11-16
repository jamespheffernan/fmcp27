"""Read a disposable child process to verify actual Mach reads and scan cursors."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from fm_live_mcp.reader import ReadStream, ReaderError


HELPER = Path(os.environ.get('FM_LIVE_HELPER', Path(__file__).resolve().parents[1] / "build/fm_live_helper"))
pytestmark = pytest.mark.skipif(sys.platform != "darwin" or not HELPER.exists(), reason="Built macOS reader required")


@pytest.fixture
def target():
    code = """
import ctypes, json, os, sys
data = ctypes.create_string_buffer(b'x' * 8192)
needle = b'FMCP_BOUNDARY_527193'
ctypes.memmove(ctypes.addressof(data) + 2045, needle, len(needle))
print(json.dumps({'pid': os.getpid(), 'address': ctypes.addressof(data)}), flush=True)
sys.stdin.readline()
"""
    child = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        yield json.loads(child.stdout.readline())
    finally:
        child.communicate("\n", timeout=5)


def native(target, command, *args):
    result = subprocess.run([str(HELPER), command, "--pid", str(target["pid"]), *args],
                            capture_output=True, text=True, timeout=45)
    data = json.loads(result.stdout)
    assert result.returncode == 0, data
    return data


def test_cursor_catches_needle_spanning_budget_boundary(target):
    common = ["--needle", "FMCP_BOUNDARY_527193", "--max-bytes", "2048",
              "--chunk-size", "1024", "--private-only", "--writable-only"]
    first = native(target, "scan-session", *common, "--start-address", str(target["address"]))
    assert first["matches"] == []
    assert first["stop_reason"] == "byte_budget"
    assert int(first["next_address"], 16) == target["address"] + 2048
    second = native(target, "scan-session", *common, "--start-address", str(int(first["next_address"], 16)))
    assert len(second["matches"]) == 1
    assert int(second["matches"][0]["address"], 16) == target["address"] + 2045


def test_native_read_bytes_matches_exact_window(target):
    result = native(target, "read-bytes", "--addr", str(target["address"] + 2045), "--read-len", str(len(b"FMCP_BOUNDARY_527193")))
    assert bytes.fromhex(result["hex"]) == b"FMCP_BOUNDARY_527193"


def test_stream_reads_fresh_bytes_and_closes_one_helper(target):
    reader = ReadStream(HELPER, target['pid'])
    try:
        assert reader.read(target['address'] + 2045, len(b'FMCP_BOUNDARY_527193')) == b'FMCP_BOUNDARY_527193'
        child = reader.child
        assert reader.read(target['address'], 1638) == b'x' * 1638
        assert reader.child is child and child.poll() is None
        with pytest.raises(ReaderError):
            reader.read(1, 8)
        assert child.poll() is not None
        with pytest.raises(ReaderError, match='closed'):
            reader.read(target['address'], 8)
    finally:
        reader.close()


def test_stream_observes_changes_and_rejects_dead_target():
    code = '''
import ctypes, json, os, sys
data = ctypes.create_string_buffer(b'before')
print(json.dumps({'pid': os.getpid(), 'address': ctypes.addressof(data)}), flush=True)
sys.stdin.readline()
data.value = b'after!'
print('changed', flush=True)
sys.stdin.readline()
'''
    child = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True)
    target = json.loads(child.stdout.readline())
    reader = ReadStream(HELPER, target['pid'])
    try:
        assert reader.read(target['address'], 6) == b'before'
        child.stdin.write('\n')
        child.stdin.flush()
        assert child.stdout.readline().strip() == 'changed'
        assert reader.read(target['address'], 6) == b'after!'
        child.communicate('\n', timeout=5)
        with pytest.raises(ReaderError): reader.read(target['address'], 6)
        assert reader.closed and reader.child.poll() is not None
    finally:
        reader.close()
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)


@pytest.mark.parametrize('message', ['1 0\n', '1 16385\n', '-1 8\n',
                                     '1 8 extra\n', '18446744073709551615 8\n'])
def test_stream_rejects_malformed_or_unbounded_requests(target, message):
    child = subprocess.Popen([str(HELPER), 'read-stream', '--pid', str(target['pid'])],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    result, _ = child.communicate(message, timeout=5)
    assert child.returncode != 0
    assert len(result.splitlines()) == 1  # readiness only; no accepted read


def test_native_player_filter_resolves_handles_and_rejects_wrong_types():
    code = r'''
import ctypes, json, os, struct, sys
names = [ctypes.create_string_buffer(struct.pack('<I', len(n)) + n) for n in (b'Synthetic', b'Testplayer')]
handles = [ctypes.c_uint64(ctypes.addressof(n)) for n in names]
data = ctypes.create_string_buffer(0x3a8)
base = ctypes.addressof(data)
def put(off, fmt, *values):
    encoded = struct.pack(fmt, *values)
    ctypes.memmove(base + off, encoded, len(encoded))
for off, value in ((0, 0x11100), (0x140, 0x22200), (0x388, 0x33300)):
    put(off, '<Q', value)
for off, handle in zip((0x298, 0x2a0), handles):
    put(off, '<Q', ctypes.addressof(handle))
put(0x394, '<II', 123, 123)
print(json.dumps({'pid': os.getpid(), 'address': base}), flush=True)
sys.stdin.readline()
'''
    child = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        target = json.loads(child.stdout.readline())
        args = ["--start-address", str(target["address"]), "--max-bytes", "936",
                "--hex-needle", (0x11100).to_bytes(8, "little").hex(),
                "--player-primary", str(0x11100), "--player-playing", str(0x22200),
                "--player-person", str(0x33300), "--player-query", "testPLAYER"]
        found = native(target, "scan-session", *args)
        assert found["matches"] == [{"address": hex(target["address"]),
                                     "first_name": "Synthetic", "last_name": "Testplayer"}]
        args[args.index("--player-person") + 1] = str(0x44400)
        assert native(target, "scan-session", *args)["matches"] == []
        assert native(target, "images")["images"] == []
    finally:
        child.communicate("\n", timeout=5)

