"""The injected attach route, end to end against a self-built test target.

These tests build the in-game library, a stand-in target signed like the game
(hardened runtime, the game's two dyld entitlements, no get-task-allow, ad-hoc),
and fm_fast_reader into one temp directory, launch the target with the library
loaded, and drive it through ``LiveMemory`` with ``route="injected"`` -- which
never calls task_for_pid. They are skipped when clang is absent (so CI without a
compiler stays green). What they cannot prove on this machine is that a default
SIP configuration blocks task_for_pid; see ``needs default-SIP Mac`` below and
``docs/attach-injected.md`` for the manual check.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native"
CLANG = shutil.which("clang")
CODESIGN = shutil.which("codesign")

pytestmark = pytest.mark.skipif(
    CLANG is None or CODESIGN is None or os.uname().sysname != "Darwin",
    reason="needs clang + codesign on macOS to build the signed test target",
)


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"command failed: {' '.join(cmd)}\n{result.stderr}")


def _build(tmp: Path) -> dict[str, Path]:
    """Build library, target and reader into one directory (the peer check needs
    the reader beside the library)."""
    lib = tmp / "libfmcp_attach.dylib"
    target = tmp / "fmcp_attach_target"
    reader = tmp / "fm_fast_reader"
    _run([CLANG, "-std=c11", "-O2", "-I", str(NATIVE), "-dynamiclib",
          "-o", str(lib), str(NATIVE / "fmcp_attach_lib.c"), "-lbsm"])
    _run([CODESIGN, "--force", "--sign", "-", str(lib)])
    _run([CLANG, "-std=c11", "-O2", "-o", str(target), str(NATIVE / "fmcp_attach_target.c")])
    _run([CODESIGN, "--force", "--sign", "-", "--options", "runtime",
          "--entitlements", str(NATIVE / "fmcp_attach_target.entitlements"), str(target)])
    _run([CLANG, "-std=c11", "-O2", "-I", str(NATIVE),
          "-o", str(reader), str(NATIVE / "fm_fast_reader.c")])
    _run([CODESIGN, "--force", "--sign", "-", str(reader)])
    return {"lib": lib, "target": target, "reader": reader}


class _Target:
    """A launched test target with the attach library loaded. Expectation byte i
    of its buffer is (i * 131 + 7) & 0xff."""

    def __init__(self, built: dict[str, Path], *, load_library: bool = True, disable: bool = False):
        env = dict(os.environ)
        if load_library:
            env["DYLD_INSERT_LIBRARIES"] = str(built["lib"])
            env["FMCP_ATTACH_TARGET"] = str(built["target"])
        if disable:
            env["FMCP_ATTACH_DISABLE"] = "1"
        self.proc = subprocess.Popen([str(built["target"]), "32"], env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        line = self.proc.stdout.readline().split()
        assert line and line[0] == "READY", f"target did not start: {line!r}"
        self.pid = int(line[1])
        self.base = int(line[2])
        self.size = int(line[3])

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    @staticmethod
    def expect(index: int) -> int:
        return (index * 131 + 7) & 0xFF


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> dict[str, Path]:
    return _build(tmp_path_factory.mktemp("fmcp_attach"))


def _memory(built, target, route="injected"):
    from fm_live_mcp.fmdb.memory import LiveMemory
    return LiveMemory(target.pid, helper=built["reader"],
                      expected_executable=str(built["target"]), route=route)


def test_injected_route_reads_without_task_for_pid(built):
    target = _Target(built)
    try:
        with _memory(built, target) as m:
            assert m.route == "injected"
            data = m.read(target.base + 1000, 64)
            assert list(data) == [target.expect(1000 + i) for i in range(64)]
            # a scatter batch
            addrs = [(target.base + off, 8) for off in range(0, 8000, 8)]
            out = m.read_many(addrs)
            assert all(d is not None for d in out)
            first = out[0]
            assert list(first) == [target.expect(i) for i in range(8)]
    finally:
        target.close()


def test_injected_route_lists_regions(built):
    target = _Target(built)
    try:
        with _memory(built, target) as m:
            regions = m.regions()
            assert regions, "expected a non-empty region map"
            assert any(r.contains(target.base, 64) for r in regions)
    finally:
        target.close()


def test_injected_route_bad_address_is_not_fatal(built):
    target = _Target(built)
    try:
        with _memory(built, target) as m:
            # An unmapped address comes back as None, and the game stays alive.
            out = m.read_many([(0xDEAD0000, 64), (target.base + 16, 8)])
            assert out[0] is None
            assert out[1] is not None
            assert m.read(target.base + 24, 8)  # channel still usable
        assert target.proc.poll() is None, "the target must survive a bad read"
    finally:
        target.close()


def test_forced_injected_without_library_names_the_launcher(built):
    from fm_live_mcp.fmdb.memory import MemoryReadError
    target = _Target(built, load_library=False)
    try:
        with pytest.raises(MemoryReadError) as exc:
            _memory(built, target, route="injected")
        message = str(exc.value)
        assert "FMCP launcher" in message
        assert "attach_failed" in message
    finally:
        target.close()


def test_kill_switch_disables_the_library(built):
    from fm_live_mcp.fmdb.memory import MemoryReadError
    target = _Target(built, disable=True)
    try:
        with pytest.raises(MemoryReadError):
            _memory(built, target, route="injected")
    finally:
        target.close()


def test_auto_route_falls_back_to_task_for_pid(built):
    """With no library loaded, ``auto`` falls back to task_for_pid. This needs a
    SIP configuration that permits task_for_pid; it is skipped where it is not
    allowed (the attach simply fails), which is the expected state on a default
    Mac."""
    from fm_live_mcp.fmdb.memory import LiveMemory, MemoryReadError
    target = _Target(built, load_library=False)
    try:
        try:
            with LiveMemory(target.pid, helper=built["reader"],
                            expected_executable=str(built["target"]), route="auto") as m:
                assert m.route == "task_for_pid"
                assert m.read(target.base + 1000, 8)
        except MemoryReadError as exc:
            pytest.skip(f"task_for_pid not permitted here: {exc}")
    finally:
        target.close()


def test_launch_fix_names_the_launcher_of_this_layout(tmp_path, monkeypatch):
    from fm_live_mcp.fmdb import memory
    text, download = memory.launch_fix()
    assert not download and 'FMCP launcher (scripts/fm_launch.sh' in text
    # The Mac download has the launcher at its top; the fix is then the README's Steam launch line.
    package = (tmp_path / 'FMCP27').resolve()
    (package / 'fm_live_mcp' / 'fmdb').mkdir(parents=True)
    (package / 'fm_launch.sh').write_text('')
    monkeypatch.setattr(memory, '__file__', str(package / 'fm_live_mcp' / 'fmdb' / 'memory.py'))
    text, download = memory.launch_fix()
    assert download and f'{package}/fm_launch.sh %command%' in text and 'Launch Options' in text
