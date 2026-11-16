from dataclasses import replace
import subprocess

import pytest

from fm_live_mcp import bridge as module
from fm_live_mcp.bridge import Bridge, BridgeError, Process


PROCESS = Process(42, "/game/fm", "today", "27.0", "com.SportsInteractive.FootballManager27", "stamp")


@pytest.fixture
def bridge(monkeypatch):
    monkeypatch.setattr(module, "process_info", lambda pid: PROCESS if pid == 42 else None)
    monkeypatch.setattr(module, "discover_processes", lambda: [PROCESS])
    instance = Bridge()
    monkeypatch.setattr(instance, "_run", lambda *args: {"attach_ok": True, "regions": {}})
    instance.attach()
    return instance


def match(value="Wirtz", encoding="utf-8"):
    return {"value": value, "encoding": encoding, "address": "0x1020",
            "region": {"start": "0x1000", "end": "0x2000"}, "confidence": 0.75}


def scan(matches=None, reason="byte_budget", address="0x2000"):
    return {"matches": matches or [], "stop_reason": reason, "next_address": address, "scan": {}}


def test_attach_rejects_non_game_pid(bridge):
    with pytest.raises(BridgeError, match="not a supported"):
        bridge.attach(12)


def test_ambiguous_discovery_requires_selection(bridge, monkeypatch):
    monkeypatch.setattr(module, "discover_processes", lambda: [PROCESS, replace(PROCESS, pid=43)])
    with pytest.raises(BridgeError, match="2 games"):
        bridge.attach()


def test_restart_invalidates_session(bridge, monkeypatch):
    monkeypatch.setattr(module, "process_info", lambda pid: replace(PROCESS, started="later"))
    with pytest.raises(BridgeError, match="restarted"):
        bridge.search(bridge.session, ["Wirtz"])
    assert bridge.session is None


@pytest.mark.parametrize("kwargs", [
    {"texts": []}, {"texts": ["ab"]}, {"texts": ["hi\x00there"]},
    {"texts": ["a"] * 9}, {"max_mib": 0}, {"max_mib": 1025},
    {"max_matches": 101}, {"max_mib": True}, {"texts": ["bad\ud800"]},
])
def test_search_rejects_invalid_bounds(bridge, kwargs):
    arguments = {"texts": ["Wirtz"], **kwargs}
    with pytest.raises(BridgeError):
        bridge.search(bridge.session, **arguments)


def test_continuation_preserves_query_and_bounds(bridge, monkeypatch):
    calls = []
    def run(*args):
        calls.append(args)
        return scan()
    monkeypatch.setattr(bridge, "_run", run)
    first = bridge.search(bridge.session, ["Wirtz"])
    assert first["absence_proven"] is False
    with pytest.raises(BridgeError, match="different search"):
        bridge.search(bridge.session, ["Newcastle"], cursor=first["next_cursor"])
    monkeypatch.setattr(bridge, "_run", lambda *args: calls.append(args) or scan(reason="address_space_end"))
    second = bridge.search(bridge.session, ["Wirtz"], cursor=first["next_cursor"])
    assert "8192" in calls[-1]
    assert "--writable-only" in calls[-1]
    assert second["next_cursor"] is None


def test_hits_do_not_claim_semantics_or_offer_lossy_cursor(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "_run", lambda *args: scan([match()], "match_limit"))
    result = bridge.search(bridge.session, ["Wirtz"])
    assert result["next_cursor"] is None
    assert result["matches"][0]["evidence"] == "text_match_only"
    assert "confidence" not in result["matches"][0]


def test_non_ascii_utf16_search_and_readback(bridge, monkeypatch):
    value = "Mbappé"
    encoded = value.encode("utf-16le").hex()
    calls = []
    monkeypatch.setattr(bridge, "_run", lambda *args: calls.append(args) or scan([match(encoded)]))
    result = bridge.search(bridge.session, [value])
    anchor = result["matches"][0]
    assert encoded in calls[0]
    assert anchor["encoding"] == "utf-16le"
    data = b"\x00" * 32 + value.encode("utf-16le") + b"\x00" * 96
    monkeypatch.setattr(bridge, "_run", lambda *args: {"hex": data.hex()})
    assert bridge.read_anchor(bridge.session, anchor["anchor_id"])["anchor_still_matches"]


def test_stale_anchor_is_rejected(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "_run", lambda *args: scan([match()]))
    anchor = bridge.search(bridge.session, ["Wirtz"])["matches"][0]
    monkeypatch.setattr(bridge, "_run", lambda *args: {"hex": (b"x" * 133).hex()})
    with pytest.raises(BridgeError, match="Anchor changed"):
        bridge.read_anchor(bridge.session, anchor["anchor_id"])
    assert not bridge.anchors


def test_detach_rejects_session_and_clears_cursors(bridge, monkeypatch):
    monkeypatch.setattr(bridge, "_run", lambda *args: scan([match()]))
    session = bridge.session
    bridge.search(session, ["Wirtz"])
    bridge.detach()
    assert not bridge.anchors and not bridge.cursors
    with pytest.raises(BridgeError, match="Unknown session"):
        bridge.search(session, ["Wirtz"])


def test_real_runner_handles_timeout(tmp_path, monkeypatch):
    helper = tmp_path / "helper"
    helper.touch()
    instance = Bridge(helper)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("helper", 45)
    monkeypatch.setattr(module.subprocess, "run", timeout)
    with pytest.raises(BridgeError, match="timed out"):
        instance._run("probe", PROCESS)


@pytest.mark.parametrize("returncode,payload", [
    (0, "bad json"), (0, "[]"), (1, '{"ok":true}'),
    (0, '{"ok":false,"error":{"code":"task_for_pid_failed"}}'),
    (0, '{"ok":true,"pid":43,"command":"probe"}'),
])
def test_real_runner_rejects_failed_or_wrong_response(tmp_path, monkeypatch, returncode, payload):
    helper = tmp_path / "helper"
    helper.touch()
    instance = Bridge(helper)
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], returncode, payload, ""))
    with pytest.raises(BridgeError):
        instance._run("probe", PROCESS)


def test_status_declares_build_gated_player_support(bridge):
    assert bridge.status()["capabilities"]["decoded_players"] is True
    assert any("verified ARM64" in limit for limit in bridge.status()["limitations"])
    assert bridge.status()["save_identity"] == "unverified"

