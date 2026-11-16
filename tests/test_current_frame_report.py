import asyncio
import copy
import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from mcp.server.fastmcp import FastMCP

from fm_live_mcp import current_frame_report as report
from fm_live_mcp.current_frame_tools import register_current_frame_tools


def packet():
    fixture = {
        "date": "2030-11-11",
        "competition": {"native_id": 11, "database_index": 7},
        "home_team": {"native_id": 688, "database_index": 545},
        "away_team": {"native_id": 692, "database_index": 549},
    }

    def actor(index, person, name, side, xy):
        return {
            "entity_index": index,
            "canonical_person_id": person,
            "person_name": name,
            "team_native_id": 688 if side == 0 else 692,
            "side_index": side,
            "stored_player_slot": index,
            "position_samples": [{"native_xy": xy, "native_local_time": 1.0}],
            "identity_state": "test_validated_identity",
            "prior_recorded_tracking": person in {1, 2},
        }

    return {
        "fixture": fixture,
        "frame_tick": 100,
        "observed_cursor": 100,
        "verification_cursor": 101,
        "same_session_fixed_frame_verified": True,
        "common_world_xy_verified": True,
        "source_id": "checked-source",
        "typed_player_entities": [
            actor(11, 1, "Known A", 0, [0.0, 0.0]),
            actor(31, 2, "Known B", 1, [3.0, 4.0]),
            actor(32, 3, "HIDDEN FUTURE PLAYER", 1, [1.0, 1.0]),
            actor(33, None, None, 1, [10.0, 10.0]),
        ],
        "ball_samples": [{"native_xyz": [0.0, 3.0, 8.0], "native_local_time": 1.0}],
        "coverage": {
            "typed_player_entities": 4,
            "canonical_player_entities": 3,
            "unresolved_player_entities": 1,
            "non_player_entities": 11,
            "prior_recorded_canonical_players": 2,
        },
        "allowed_person_ids": {1, 2},
    }


def test_default_exposes_only_previously_recorded_names_not_active_xi():
    result = report.project_frame(packet())
    assert [r["person_name"] for r in result["players"]] == ["Known A", "Known B"]
    assert "HIDDEN" not in json.dumps(result) and "playback_uid" not in json.dumps(
        result
    )
    assert (
        not result["on_pitch_population_verified"] and result["physical_units"] is None
    )
    assert all(r["on_pitch"] is None for r in result["players"])
    assert result["ball"]["sample"]["native_xyz"] == [0.0, 3.0, 8.0]


def test_selected_future_or_unseen_actor_positions_are_withheld():
    result = report.project_frame(packet(), 3, True)
    assert result["players"] == [] and result["selection"]["state"].startswith(
        "unavailable"
    )
    assert result["proximity"]["state"] == "unavailable_selected_person"
    assert "HIDDEN" not in json.dumps(result)


def test_selected_actor_ball_distance_checks_private_unknown_nearer_candidates():
    result = report.project_frame(packet(), 1, True)
    assert len(result["players"]) == 1
    assert result["proximity"]["ball_planar_separation_native"] == 3.0
    assert (
        result["proximity"]["nearest_opponent_state"]
        == "unknown_other_entity_as_close_or_closer"
    )
    assert result["proximity"]["nearest_named_opponents"][0]["name"] == "Known B"
    assert "HIDDEN" not in json.dumps(result)


def test_endpoint_is_exact_not_nearest_or_interpolated():
    raw = packet()
    raw["typed_player_entities"][0]["position_samples"][0]["native_local_time"] = (
        0.999999
    )
    result = report.project_frame(raw, 1, True)
    assert result["players"][0]["sample"] is None
    assert result["proximity"]["state"] == "unavailable_selected_endpoint"
    raw = packet()
    raw["ball_samples"] *= 2
    assert report.project_frame(raw)["ball"]["sample"] is None


def test_unverified_input_never_yields_projection():
    raw = packet()
    raw["same_session_fixed_frame_verified"] = False
    with pytest.raises(ValueError, match="verified coherent"):
        report.project_frame(raw)


def test_allowed_names_require_nonempty_tracking_and_matching_original_side_slot():
    actor = {
        "side_index": 0,
        "stored_player_slot": 2,
        "canonical_person_id": 998,
        "person_name": "Known A",
        "engine_playback_uid": 123,
    }
    frame = {
        "frame_tick": 100,
        "player_bases": [6, 30],
        "entities": [
            {
                "entity_index": 8,
                "kind": "player",
                "playback_uid": 123,
                "position_samples": [],
            }
        ],
        "setup": [
            {"entity_index": 8, "kind_raw": 0, "team_index": 0, "playback_uid": 123}
        ],
        "ball_samples": [],
    }
    fixture = packet()["fixture"]
    actors = {"actors": [actor]}
    client = {"players": [actor]}
    tracking = {
        "tracking": {
            "players": [
                {
                    "side_index": 0,
                    "stored_player_slot": 2,
                    "start_tick": 100,
                    "samples": b"1234",
                }
            ]
        }
    }
    assert report._named_packet(fixture, frame, actors, client, tracking)[
        "allowed_person_ids"
    ] == {998}
    tracking["tracking"]["players"][0]["start_tick"] = 101
    assert (
        report._named_packet(fixture, frame, actors, client, tracking)[
            "allowed_person_ids"
        ]
        == set()
    )
    tracking["tracking"]["players"][0]["start_tick"] = 100
    tracking["tracking"]["players"][0]["samples"] = b""
    assert (
        report._named_packet(fixture, frame, actors, client, tracking)[
            "allowed_person_ids"
        ]
        == set()
    )
    tracking["tracking"]["players"][0]["samples"] = b"1234"
    client = {"players": [{**actor, "canonical_person_id": 999}]}
    assert (
        report._named_packet(fixture, frame, actors, client, tracking)[
            "allowed_person_ids"
        ]
        == set()
    )


@pytest.fixture
def wrapper(monkeypatch):
    events = []
    fixture = packet()["fixture"]
    binding = {"client": 1, "engine": 2, "team_indices": [545, 549]}
    bound = dict(
        playback_address=10,
        frame_provider_address=11,
        source_match_address=12,
        official_match_unique_id=99,
        current_time_slice=100,
        buffered_max_time_slice=102,
        local_playback_handle=3,
    )

    class Reader:
        def __init__(self, *args):
            pass

        def verify(self):
            events.append("verify")

    class Bridge:
        lock = nullcontext()
        world_identity = "career-A"

        def _read_scope(self, *args):
            return nullcontext()

        def _current(self, *args):
            return SimpleNamespace(pid=1, version="build", executable="fm")

        def _player_layout(self, *args):
            return (report.players.RVA[0] + 0x10000000,)

        def _world_state(self, *args):
            return Reader(), {"current_date": "2030-11-11"}, None

        def _read_memory(self, *args):
            raise AssertionError("Unexpected unmocked native read")

        def _public_save(self, save):
            return save

    monkeypatch.setattr(report.world, "ReadSet", Reader)
    monkeypatch.setattr(
        report.active_match_source,
        "inspect_context",
        lambda *a, **k: (
            {
                "bound_active_fixture": fixture,
                "source_state": "available_fixture_bound",
            },
            binding,
        ),
    )
    monkeypatch.setattr(
        report.active_match_playback,
        "capture",
        lambda *a, **k: {"state": "bound_playback_cursor", "bound_playback": bound},
    )
    monkeypatch.setattr(
        report.active_frame_source,
        "verify_native",
        lambda *a: events.append("identity_guards"),
    )
    monkeypatch.setattr(
        report.frame_world_basis,
        "verify_native",
        lambda *a: events.append("world_guards"),
    )
    monkeypatch.setattr(
        report.active_match_entity_identity,
        "capture_actor_source",
        lambda *a: {"actors": [], "binding": {}},
    )
    monkeypatch.setattr(
        report.active_match_people,
        "inspect_actor_bindings",
        lambda *a, **k: {"players": []},
    )
    monkeypatch.setattr(
        report.active_frame_source,
        "read_frame",
        lambda *a, **k: {"state": "available", "frame_tick": 100},
    )
    monkeypatch.setattr(
        report.active_match_tracking,
        "capture_source",
        lambda *a, **k: {
            "state": "available_engine_tracking_source",
            "match_unique_id": 99,
        },
    )
    monkeypatch.setattr(report, "_named_packet", lambda *a: copy.deepcopy(packet()))
    monkeypatch.setattr(
        report.active_match_tracking,
        "verify_prefix",
        lambda *a: events.append("tracking_verified"),
    )
    monkeypatch.setattr(
        report.active_frame_source,
        "verify_frame",
        lambda *a: {
            "state": "verified",
            "frame_tick": 100,
            "observed_cursor": 100,
            "verification_cursor": 101,
        },
    )
    return Bridge(), events


def test_wrapper_projects_only_after_epoch_and_immutable_source_checks(
    wrapper, monkeypatch
):
    bridge, events = wrapper
    original = report.project_frame

    def project(*args):
        assert (
            events.count("verify") == 3
            and "tracking_verified" in events
            and "world_guards" in events
        )
        return original(*args)

    monkeypatch.setattr(report, "project_frame", project)
    result = report.current_frame_report(bridge, "session", 1, True)
    assert (
        result["same_session_fixed_frame_verified"]
        and result["common_world_xy_verified"]
    )
    assert result["readset_verified"] and not result["atomic"]
    text = json.dumps(result)
    assert not any(
        key in text
        for key in (
            "playback_address",
            "frame_provider_address",
            "source_match_address",
            "HIDDEN FUTURE",
        )
    )


def test_native_goal_area_is_opt_in_and_verified_after_frame_bookends(
    wrapper, monkeypatch
):
    bridge, events = wrapper
    calls = []
    monkeypatch.setattr(
        report.frame_attacked_goal_area,
        "capture",
        lambda read, base, bound, *, fixed_tick: calls.append(("capture", fixed_tick))
        or {"captured": True},
    )

    def verify(read, base, captured, bound):
        assert "tracking_verified" in events and captured == {"captured": True}
        calls.append(("verify", bound["current_time_slice"]))
        return {"verified": True}

    monkeypatch.setattr(report.frame_attacked_goal_area, "verify_capture", verify)
    monkeypatch.setattr(
        report.frame_attacked_goal_area,
        "project",
        lambda verified: {"state": "available_native_attacked_goal_area", **verified},
    )
    default = report.current_frame_report(bridge, "session", 1)
    assert default["native_goal_area"] is None and calls == []
    result = report.current_frame_report(bridge, "session", 1, False, True)
    assert result["native_goal_area"] == {
        "state": "available_native_attacked_goal_area",
        "verified": True,
    }
    assert calls == [("capture", 100), ("verify", 100)]
    with pytest.raises(ValueError, match="boolean"):
        report.current_frame_report(bridge, "session", None, False, 1)


def test_native_goal_area_source_change_rejects_whole_frame(wrapper, monkeypatch):
    bridge, events = wrapper
    monkeypatch.setattr(
        report.frame_attacked_goal_area, "capture", lambda *a, **k: {"captured": True}
    )

    def verify(*args):
        raise ValueError("Frame attack-direction consumed source changed or was evicted")

    monkeypatch.setattr(report.frame_attacked_goal_area, "verify_capture", verify)
    with pytest.raises(ValueError, match="evicted"):
        report.current_frame_report(bridge, "session", None, False, True)


def test_world_guard_failure_never_sets_common_space_verified(wrapper, monkeypatch):
    bridge, events = wrapper

    def fail(*args):
        raise ValueError("Native shared basis mismatch")

    monkeypatch.setattr(report.frame_world_basis, "verify_native", fail)
    with pytest.raises(ValueError, match="basis mismatch"):
        report.current_frame_report(bridge, "session", 1, True)


def test_epoch_change_rejects_even_when_frame_bytes_pass(wrapper, monkeypatch):
    bridge, events = wrapper
    original = bridge._world_state

    def read(*args):
        result = original(*args)
        if events.count("verify") >= 2:
            bridge.world_identity += "changed"
        return result

    monkeypatch.setattr(bridge, "_world_state", read)
    with pytest.raises(ValueError, match="epoch changed"):
        report.current_frame_report(bridge, "session")


def test_missing_current_client_returns_unknown_not_empty_population(
    wrapper, monkeypatch
):
    bridge, events = wrapper
    monkeypatch.setattr(
        report.active_match_source,
        "inspect_context",
        lambda *a, **k: (
            {"reason": "no_current_match", "source_state": "inactive"},
            None,
        ),
    )
    result = report.current_frame_report(bridge, "session")
    assert (
        result["state"] == "unavailable"
        and result["players"] is None
        and result["ball"] is None
    )


@pytest.mark.parametrize(
    "person,proximity",
    [(True, False), (0, False), (-1, False), (2**32, False), (None, True), (1, 1)],
)
def test_invalid_selectors_reject_before_attach(person, proximity):
    with pytest.raises(ValueError):
        report.current_frame_report(object(), "s", person, proximity)


def test_read_only_tool_schema_has_no_pointer_file_time_or_hidden_field_selectors():
    mcp = FastMCP("test")
    register_current_frame_tools(mcp, object())
    tools = asyncio.run(mcp.list_tools())
    assert len(tools) == 1
    tool = tools[0]
    assert tool.name == "fm_get_current_match_frame" and tool.annotations.readOnlyHint
    assert set(tool.inputSchema["properties"]) == {
        "session_id",
        "person_native_id",
        "include_proximity",
        "include_native_goal_area",
    }
