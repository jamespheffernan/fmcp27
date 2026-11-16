"""Reader route selection and the hello route field, without a live target."""
from __future__ import annotations

from pathlib import Path

import pytest

from fm_live_mcp.fmdb import memory
from fm_live_mcp.fmdb.memory import LiveMemory, MemoryReadError, ROUTE_NAMES


def test_route_names_map_hello_codes():
    assert ROUTE_NAMES[0] == "task_for_pid"
    assert ROUTE_NAMES[1] == "injected"


def test_invalid_route_is_rejected(tmp_path: Path):
    helper = tmp_path / "fm_fast_reader"
    helper.write_text("#!/bin/sh\nexit 0\n")
    helper.chmod(0o755)
    with pytest.raises(MemoryReadError) as exc:
        LiveMemory(1234, helper=helper, route="sideways")
    assert "invalid attach route" in str(exc.value)


def test_route_flag_is_passed_to_the_helper(tmp_path: Path, monkeypatch):
    """A chosen route is translated to ``--route`` with dashes."""
    helper = tmp_path / "fm_fast_reader"
    helper.write_text("#!/bin/sh\nexit 0\n")
    helper.chmod(0o755)
    captured: dict = {}

    class _FakePopen:
        def __init__(self, args, **kwargs):
            captured["args"] = args
            raise OSError("stop before the real hello")

    monkeypatch.setattr(memory.subprocess, "Popen", _FakePopen)
    with pytest.raises(MemoryReadError):
        LiveMemory(1234, helper=helper, route="task_for_pid")
    assert "--route" in captured["args"]
    assert captured["args"][captured["args"].index("--route") + 1] == "task-for-pid"


def test_env_route_default(tmp_path: Path, monkeypatch):
    helper = tmp_path / "fm_fast_reader"
    helper.write_text("#!/bin/sh\nexit 0\n")
    helper.chmod(0o755)
    captured: dict = {}

    class _FakePopen:
        def __init__(self, args, **kwargs):
            captured["args"] = args
            raise OSError("stop")

    monkeypatch.setenv("FMCP_ATTACH_ROUTE", "injected")
    monkeypatch.setattr(memory.subprocess, "Popen", _FakePopen)
    with pytest.raises(MemoryReadError):
        LiveMemory(1234, helper=helper)
    assert captured["args"][captured["args"].index("--route") + 1] == "injected"
