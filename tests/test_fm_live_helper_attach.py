"""fm_live_helper over the injected attach route, against the self-built test target.

The helper is built beside the in-game library and the stand-in target from
``tests/test_fmcp_attach.py`` and driven with ``FMCP_ATTACH_ROUTE=injected``,
which never calls task_for_pid. The loaded-plugin search (``images``) needs the
real game and is checked there by hand; see docs/attach-injected.md.
"""
from __future__ import annotations

import json
import os
import subprocess

import pytest

from test_fmcp_attach import CLANG, CODESIGN, NATIVE, _build, _run, _Target

pytestmark = pytest.mark.skipif(
    CLANG is None or CODESIGN is None or os.uname().sysname != "Darwin",
    reason="needs clang + codesign on macOS to build the signed test target",
)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("fm_live_helper_attach")
    made = _build(tmp)
    helper = tmp / "fm_live_helper"
    _run([CLANG, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2", "-I", str(NATIVE),
          "-o", str(helper), str(NATIVE / "fm_live_helper.c")])
    _run([CODESIGN, "--force", "--sign", "-", str(helper)])
    made["helper"] = helper
    return made


def _helper(built, *args, route="injected", **env):
    result = subprocess.run([str(built["helper"]), *args], capture_output=True, text=True, timeout=30,
                            env={**os.environ, "FMCP_ATTACH_ROUTE": route, **env})
    return result.returncode, json.loads(result.stdout)


def test_read_bytes_over_the_channel(built):
    target = _Target(built)
    try:
        code, data = _helper(built, "read-bytes", "--pid", str(target.pid),
                             "--addr", hex(target.base + 1000), "--read-len", "64")
        assert code == 0 and data["ok"] is True
        assert list(bytes.fromhex(data["hex"])) == [target.expect(1000 + i) for i in range(64)]
    finally:
        target.close()


def test_read_stream_over_the_channel(built):
    target = _Target(built)
    try:
        child = subprocess.Popen([str(built["helper"]), "read-stream", "--pid", str(target.pid)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                 env={**os.environ, "FMCP_ATTACH_ROUTE": "injected"})
        try:
            assert json.loads(child.stdout.readline())["command"] == "read-stream"
            child.stdin.write(f"{target.base + 8} 16\n")
            child.stdin.flush()
            data = json.loads(child.stdout.readline())
            assert list(bytes.fromhex(data["hex"])) == [target.expect(8 + i) for i in range(16)]
            # An unmapped address fails that read and leaves the target alive.
            child.stdin.write(f"{0xDEAD0000} 16\n")
            child.stdin.flush()
            assert json.loads(child.stdout.readline())["ok"] is False
        finally:
            child.kill()
        assert target.proc.poll() is None
    finally:
        target.close()


@pytest.mark.parametrize("no_proc_info", ["0", "1"])
def test_probe_walks_the_channel_regions(built, no_proc_info):
    target = _Target(built)
    try:
        code, data = _helper(built, "probe", "--pid", str(target.pid), FMCP_ATTACH_NO_PROC_INFO=no_proc_info)
        assert code == 0 and data["attach_ok"] is True
        regions = data["regions"]
        assert regions["seen"] >= regions["readable"] > 0 and regions["writable"] > 0
        # Without the kernel's share mode every region counts as private.
        if no_proc_info == "1":
            assert regions["private"] == regions["seen"]
        else:
            assert 0 < regions["private"] <= regions["seen"]
    finally:
        target.close()


def test_scan_reads_writable_regions_over_the_channel(built):
    target = _Target(built)
    try:
        code, data = _helper(built, "scan-session", "--pid", str(target.pid), "--needle", "fmcp-no-such-text",
                             "--writable-only", "--max-bytes", str(1 << 20))
        assert code == 0 and data["ok"] is True and data["matches"] == []
        assert data["scan"]["regions_scanned"] > 0 and data["scan"]["bytes_read"] > 0
    finally:
        target.close()


def test_forced_injected_without_library_names_the_launch_line(built):
    target = _Target(built, load_library=False)
    try:
        code, data = _helper(built, "probe", "--pid", str(target.pid))
        assert code == 1 and data["attach_ok"] is False
        assert data["error"]["code"] == "attach_library_not_loaded"
        assert "launch line" in data["error"]["hint"]
    finally:
        target.close()
