"""Current-frame snapshot with exact identity, past-actor and byte bookends."""

from datetime import datetime, timezone
import hashlib
import json

from . import (
    address_book,
    active_frame_source,
    active_match_entity_identity,
    active_match_people,
    active_match_playback,
    active_match_source,
    active_match_tracking,
    frame_attacked_goal_area,
    frame_world_basis,
    players,
    world,
)
from .frame_proximity import project_frame_proximity


def _goal_area_unavailable(reasons):
    return {"state": "unavailable", "reason": "native_goal_area_decoders_unavailable_on_this_build",
            "build": address_book.build_label(), "native_sites": reasons[:6]}


# The optional native goal area (attacked-goal basis, pitch geometry, motion copy chain). On a
# build where any native site it reaches is unresolved or its guard changed, the frame report
# returns this section unavailable with the sites and answers the rest.
@address_book.optional_section("native_goal_area", _goal_area_unavailable)
def _goal_area_capture(read, base, bound, fixed_tick):
    return {"_captured": frame_attacked_goal_area.capture(read, base, bound, fixed_tick=fixed_tick)}


@address_book.optional_section("native_goal_area", _goal_area_unavailable)
def _goal_area_result(read, base, captured, bound):
    return frame_attacked_goal_area.project(
        frame_attacked_goal_area.verify_capture(read, base, captured["_captured"], bound))


def _fixture_key(fixture):
    return (
        fixture["date"],
        fixture.get("native_season_code"),
        tuple(
            (fixture[k]["database_index"], fixture[k]["native_id"])
            for k in ("home_team", "away_team")
        ),
        fixture["competition"]["database_index"],
        fixture["competition"]["native_id"],
    )


def _actor_key(row):
    return row["side_index"], row["stored_player_slot"]


def _named_packet(fixture, frame, actor_source, client_actors, tracking):
    frame_rows = [
        {
            "entity_index": r["entity_index"],
            "kind": r["kind"],
            "playback_uid": r["playback_uid"],
        }
        for r in frame["entities"]
    ]
    joined = active_match_entity_identity.project(
        frame["player_bases"], frame["setup"], frame_rows, actor_source["actors"]
    )
    by_index = {r["entity_index"]: r for r in joined["players"]}
    setup = {r["entity_index"]: r for r in frame["setup"]}
    source_ids = {
        _actor_key(r): r["canonical_person_id"] for r in actor_source["actors"]
    }
    client_ids = {
        _actor_key(r): r["canonical_person_id"] for r in client_actors["players"]
    }
    tracked = set()
    for row in tracking["tracking"]["players"]:
        start, samples = row.get("start_tick"), row.get("samples")
        if (
            type(start) is not int
            or start < 0
            or not isinstance(samples, bytes)
            or len(samples) % 4
        ):
            raise ValueError("Unsupported prior-tracking admission source")
        if start <= frame["frame_tick"] and samples:
            tracked.add(_actor_key(row))
    present = {r["canonical_person_id"] for r in by_index.values()}
    allowed = {
        identity
        for key, identity in source_ids.items()
        if key in tracked and client_ids.get(key) == identity and identity in present
    }
    all_players = []
    for entity in frame["entities"]:
        if entity["kind"] != "player":
            continue
        index = entity["entity_index"]
        known = by_index.get(index)
        row = setup.get(index)
        side = (
            row["team_index"]
            if row and row["kind_raw"] == 0 and row["team_index"] in (0, 1)
            else None
        )
        if row is None or row["playback_uid"] != entity["playback_uid"]:
            raise ValueError("Frame/setup identity disagreement in typed player census")
        all_players.append(
            {
                "entity_index": index,
                "canonical_person_id": known["canonical_person_id"] if known else None,
                "person_name": known.get("person_name") if known else None,
                "stored_player_slot": known["stored_player_slot"] if known else None,
                "team_native_id": fixture["home_team" if side == 0 else "away_team"][
                    "native_id"
                ]
                if side is not None
                else None,
                "side_index": side,
                "position_samples": entity["position_samples"],
                "identity_state": "canonical_same_match_constructor_and_triple_uid"
                if known
                else "unresolved_canonical_actor",
                "prior_recorded_tracking": known is not None
                and known["canonical_person_id"] in allowed,
            }
        )
    return {
        "fixture": fixture,
        "frame_tick": frame["frame_tick"],
        "typed_player_entities": all_players,
        "ball_samples": frame["ball_samples"],
        "coverage": {
            "typed_player_entities": len(all_players),
            "canonical_player_entities": len(by_index),
            "unresolved_player_entities": len(all_players) - len(by_index),
            "non_player_entities": sum(
                r["kind"] == "non_player" for r in frame["entities"]
            ),
            "prior_recorded_canonical_players": len(allowed),
        },
        "allowed_person_ids": allowed,
        "identity_join": joined,
    }


def _endpoint(samples, field, width):
    matches = [r for r in samples if r["native_local_time"] == 1.0]
    if len(matches) != 1:
        return None, "unavailable_missing_or_ambiguous_exact_endpoint"
    value = matches[0][field]
    if len(value) != width:
        raise ValueError("Unsupported fixed-frame endpoint width")
    return {field: value, "native_local_time": 1.0}, "available_exact_native_endpoint"


def project_frame(packet, person_native_id=None, include_proximity=False):
    if packet.get("same_session_fixed_frame_verified") is not True:
        raise ValueError("A verified coherent fixed frame is required")
    allowed = packet["allowed_person_ids"]
    players_out = []
    for row in packet["typed_player_entities"]:
        person = row["canonical_person_id"]
        if person not in allowed or (
            person_native_id is not None and person != person_native_id
        ):
            continue
        sample, state = _endpoint(row["position_samples"], "native_xy", 2)
        players_out.append(
            {
                key: row[key]
                for key in (
                    "canonical_person_id",
                    "person_name",
                    "team_native_id",
                    "side_index",
                    "stored_player_slot",
                    "entity_index",
                    "identity_state",
                )
            }
            | {
                "sample": sample,
                "sample_state": state,
                "on_pitch": None,
                "prior_recorded_tracking": True,
            }
        )
    ball, state = _endpoint(packet["ball_samples"], "native_xyz", 3)
    selected_state = (
        "not_requested"
        if person_native_id is None
        else "available"
        if players_out
        else "unavailable_selected_person_without_same_match_prior_tracking"
    )
    proximity = None
    if include_proximity:
        proximity = project_frame_proximity(
            packet, person_native_id, visible_person_ids=allowed
        )
    return {
        "state": "available_partial"
        if packet["coverage"]["unresolved_player_entities"]
        else "available",
        "fixture": {
            k: packet["fixture"][k]
            for k in ("date", "competition", "home_team", "away_team")
        },
        "source_id": packet["source_id"],
        "frame_tick": packet["frame_tick"],
        "observed_cursor": packet["observed_cursor"],
        "verification_cursor": packet["verification_cursor"],
        "native_local_time": 1.0,
        "clock_units": "native_playback_time_slice",
        "players": players_out,
        "ball": {"sample": ball, "state": state},
        "coverage": packet["coverage"],
        "selection": {"person_native_id": person_native_id, "state": selected_state},
        "same_session_fixed_frame_verified": True,
        "common_world_xy_verified": packet["common_world_xy_verified"],
        "physical_units": None,
        "on_pitch_population_verified": False,
        "live_vs_replay_verified": False,
        "displayed_pixels_verified": False,
        "human_minute": None,
        "proximity": proximity,
        "interpretation": "One already cached playback frame endpoint at exact native local parameter1.0. "
        "Named rows require an independently nonempty tracking stream through this fixed tick. "
        "This is prior recorded participation, not an active XI, rendered visibility or on-pitch predicate. "
        "Missing or multiple endpoint samples stay null; no interpolation, nearest-time substitution, "
        "possession, reception, marking, pressure, metres or future actor names are inferred.",
    }


def current_frame_report(
    bridge,
    session_id,
    person_native_id=None,
    include_proximity=False,
    include_native_goal_area=False,
):
    if person_native_id is not None and (
        type(person_native_id) is not int or not 0 < person_native_id <= 0xFFFFFFFF
    ):
        raise ValueError("Select a positive canonical PERSON native ID")
    if type(include_proximity) is not bool or (
        include_proximity and person_native_id is None
    ):
        raise ValueError("Proximity requires one selected canonical person")
    if type(include_native_goal_area) is not bool:
        raise ValueError("include_native_goal_area must be a boolean")
    for attempt in range(2):
        try:
            with bridge.lock, bridge._read_scope(session_id):
                process = bridge._current(session_id)
                layout = bridge._player_layout(process)
                world_read, save, _ = bridge._world_state(process, layout)
                epoch = (
                    process.pid,
                    process.version,
                    process.executable,
                    layout,
                    bridge.world_identity,
                )
                base = layout[0] - players.RVA[0]
                fresh = lambda a, n: bridge._read_memory(process, a, n)
                context, binding = active_match_source.inspect_context(
                    fresh, base, expected_current_date=save["current_date"]
                )
                packet = None
                goal_capture = None
                native_goal_area = None
                reason = context.get("reason") or context["source_state"]
                if binding is not None:
                    pre = active_match_playback.capture(
                        fresh, base, client=binding["client"]
                    )
                    if pre["state"] == "bound_playback_cursor":
                        metadata = world.ReadSet(fresh)
                        active_frame_source.verify_native(metadata, base)
                        frame_world_basis.verify_native(metadata, base)
                        before = pre["bound_playback"]
                        actors = active_match_entity_identity.capture_actor_source(
                            metadata,
                            base,
                            binding["engine"],
                            before["source_match_address"],
                            before["official_match_unique_id"],
                        )
                        client_actors = active_match_people.inspect_actor_bindings(
                            metadata,
                            base,
                            binding["engine"],
                            expected_match_unique_id=before["official_match_unique_id"],
                        )
                        current = active_match_playback.capture(
                            fresh, base, client=binding["client"]
                        )
                        if current["state"] != "bound_playback_cursor":
                            raise ValueError("Fixed-frame playback disappeared")
                        bound = current["bound_playback"]
                        identity_fields = (
                            "playback_address",
                            "frame_provider_address",
                            "source_match_address",
                            "official_match_unique_id",
                        )
                        if any(bound[k] != before[k] for k in identity_fields):
                            raise ValueError(
                                "Fixed-frame owner changed during actor capture"
                            )
                        frame = active_frame_source.read_frame(fresh, base, bound)
                        reason = frame["state"]
                        if frame["state"] == "available":
                            tracking = active_match_tracking.capture_source(
                                fresh,
                                base,
                                binding["client"],
                                binding["engine"],
                                current_time_slice=frame["frame_tick"],
                            )
                            if tracking["state"] != "available_engine_tracking_source":
                                raise ValueError(
                                    "Prior recorded tracking source is unavailable"
                                )
                            if (
                                tracking["match_unique_id"]
                                != bound["official_match_unique_id"]
                            ):
                                raise ValueError(
                                    "Frame and prior tracking match identities differ"
                                )
                            packet = _named_packet(
                                context["bound_active_fixture"],
                                frame,
                                actors,
                                client_actors,
                                tracking,
                            )
                            if include_native_goal_area:
                                goal_capture = _goal_area_capture(
                                    fresh, base, bound, frame["frame_tick"]
                                )
                            metadata.verify()
                            ending_context, ending_binding = (
                                active_match_source.inspect_context(
                                    fresh,
                                    base,
                                    expected_current_date=save["current_date"],
                                )
                            )
                            if (
                                ending_binding is None
                                or any(
                                    ending_binding[k] != binding[k]
                                    for k in ("client", "engine", "team_indices")
                                )
                                or _fixture_key(ending_context["bound_active_fixture"])
                                != _fixture_key(packet["fixture"])
                            ):
                                raise ValueError(
                                    "Fixed-frame canonical fixture or manager ownership changed"
                                )
                            active_match_tracking.verify_prefix(
                                fresh,
                                base,
                                binding["client"],
                                binding["engine"],
                                bound,
                                tracking,
                            )
                            verification = active_frame_source.verify_frame(
                                fresh, base, binding["client"], bound, frame
                            )
                            packet.update(verification)
                            if goal_capture is not None and "_captured" not in goal_capture:
                                native_goal_area = goal_capture
                            elif goal_capture is not None:
                                refreshed = active_match_playback.capture(
                                    fresh, base, client=binding["client"]
                                )
                                if refreshed["state"] != "bound_playback_cursor":
                                    raise ValueError("Fixed-frame playback disappeared")
                                native_goal_area = _goal_area_result(
                                    fresh, base, goal_capture, refreshed["bound_playback"]
                                )
                            packet["common_world_xy_verified"] = True
                    else:
                        reason = pre["state"]
                world_read.verify()
                ending_process = bridge._current(session_id)
                ending_layout = bridge._player_layout(ending_process)
                ending, _, _ = bridge._world_state(ending_process, ending_layout)
                ending.verify()
                if epoch != (
                    ending_process.pid,
                    ending_process.version,
                    ending_process.executable,
                    ending_layout,
                    bridge.world_identity,
                ):
                    raise ValueError("Fixed-frame process or career epoch changed")
                if packet is None:
                    return {
                        "state": "unavailable",
                        "reason": reason,
                        "fixture": None,
                        "players": None,
                        "ball": None,
                        "same_session_fixed_frame_verified": False,
                        "saved_file_fallback": False,
                        "proximity": None,
                        "native_goal_area": None,
                    }
                packet["same_session_fixed_frame_verified"] = True
                digest = {
                    k: packet[k]
                    for k in (
                        "fixture",
                        "frame_tick",
                        "typed_player_entities",
                        "ball_samples",
                    )
                }
                packet["source_id"] = hashlib.sha256(
                    repr(epoch).encode()
                    + json.dumps(digest, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                result = project_frame(packet, person_native_id, include_proximity)
                return {
                    **result,
                    "native_goal_area": native_goal_area
                    if include_native_goal_area
                    else None,
                    "save": bridge._public_save(save),
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "readset_verified": True,
                    "atomic": False,
                    "saved_file_fallback": False,
                    "verification_scope": "same_career_process_epoch_and_canonical_fixture_actor_bookends_and_reselected_exact_frame_and_prior_tracking_prefix",
                    "native_functions_executed": False,
                    "game_writes": False,
                }
        except ValueError as error:
            transient = any(
                word in str(error)
                for word in ("changed", "evicted", "disappeared", "relinked")
            )
            if attempt or not transient:
                raise
