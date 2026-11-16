from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
import sys

import pytest


@pytest.fixture
def capture(monkeypatch):
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts/capture_playback_entity_identity.py"
    )
    spec = importlib.util.spec_from_file_location("entity_capture_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    events = []

    class Read:
        def __init__(self, name):
            self.name = name

        def verify(self):
            events.append(self.name)

    class Bridge:
        lock = nullcontext()
        calls = 0

        def __init__(self, **kwargs):
            pass

        def attach(self):
            events.append("attach")
            return {"session_id": "s"}

        def detach(self):
            events.append("detach")

        def _read_scope(self, session):
            return nullcontext()

        def _current(self, session):
            return object()

        def _player_layout(self, process):
            return (module.players.RVA[0] + 0x10000000,)

        def _world_state(self, process, tables):
            self.calls += 1
            return (
                Read("initial_verify" if self.calls == 1 else "ending_verify"),
                {"current_date": "2030-11-11"},
                epoch[self.calls - 1],
            )

        def _public_save(self, save):
            return save

    epoch = [17, 17]
    monkeypatch.setattr(module, "Bridge", Bridge)
    monkeypatch.setattr(
        module.active_match_source,
        "inspect_context",
        lambda *a, **kw: (
            {"bound_active_fixture": {"date": "2030-11-11"}},
            {"client": 1, "engine": 2},
        ),
    )
    monkeypatch.setattr(
        module.active_match_playback,
        "capture",
        lambda *a, **kw: {"state": "bound_playback_cursor", "bound_playback": {}},
    )
    monkeypatch.setattr(
        module.active_match_entity_identity,
        "inspect_bound",
        lambda *a: {
            "state": "available",
            "players": [{"canonical_person_id": 99}],
            "online_positive_control_verified": False,
            "active_xi_verified": False,
        },
    )
    return module, events, epoch


def test_capture_claim_requires_both_readsets_and_unchanged_epoch(
    capture, monkeypatch, tmp_path
):
    module, events, epoch = capture
    target = tmp_path / "result.json"
    monkeypatch.setattr(sys, "argv", ["capture", "--output", str(target)])
    module.main()
    result = json.loads(target.read_text())
    assert events == ["attach", "initial_verify", "ending_verify", "detach"]
    assert result["same_process_career_epoch_verified"]
    assert result["result"]["online_positive_control_verified"]
    assert not result["result"]["active_xi_verified"]
    assert not result["result"]["caller_readset_and_epoch_verification_required"]


def test_epoch_change_rejects_before_output(capture, monkeypatch, tmp_path):
    module, events, epoch = capture
    epoch[1] = 18
    target = tmp_path / "rejected.json"
    monkeypatch.setattr(sys, "argv", ["capture", "--output", str(target)])
    with pytest.raises(ValueError, match="epoch changed"):
        module.main()
    assert not target.exists() and events[-1] == "detach"


def test_no_current_fixture_does_not_read_a_retained_substitute(
    capture, monkeypatch, tmp_path
):
    module, events, epoch = capture
    monkeypatch.setattr(
        module.active_match_source,
        "inspect_context",
        lambda *a, **kw: ({"reason": "no_match"}, None),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("No playback should be queried")

    monkeypatch.setattr(module.active_match_playback, "capture", forbidden)
    target = tmp_path / "absent.json"
    monkeypatch.setattr(sys, "argv", ["capture", "--output", str(target)])
    module.main()
    result = json.loads(target.read_text())["result"]
    assert result["players"] is None and result["state"].startswith("unavailable")
    assert not result.get("online_positive_control_verified", False)


def test_existing_output_rejected_before_attachment(capture, monkeypatch, tmp_path):
    module, events, epoch = capture
    target = tmp_path / "existing.json"
    target.write_text("original")
    monkeypatch.setattr(sys, "argv", ["capture", "--output", str(target)])
    with pytest.raises(SystemExit):
        module.main()
    assert target.read_text() == "original" and events == []
