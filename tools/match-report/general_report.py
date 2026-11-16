"""Normalize one verified match source; unavailable sections stay explicit."""

from collections import Counter
from datetime import datetime, timezone
import hashlib, json, math, re
from render_match_report import METRICS


def finite(v):
    return type(v) in (int, float) and math.isfinite(v)


def known(v):
    return finite(v) and v >= 0


def normalise(bundle):
    fixture = bundle["fixture"]
    key = bundle.get("native_match_key")
    provenance = bundle["provenance"]
    teams = [
        {
            "side_index": i,
            "native_id": fixture[k].get("native_id"),
            "name": fixture[k].get("owner", {}).get("name") or "Name unavailable",
            "short_name": fixture[k].get("owner", {}).get("short_name")
            or fixture[k].get("owner", {}).get("name")
            or "Name unavailable",
        }
        for i, k in enumerate(("home_team", "away_team"))
    ]
    if any(type(t["native_id"]) is not int or t["native_id"] <= 0 for t in teams):
        raise ValueError("Fixture requires checked ordered team identities")
    registry = (
        bundle.get("field_provenance") or provenance.get("field_provenance") or {}
    )
    extra = [
        key
        for key in registry
        if key not in METRICS
        and re.fullmatch(r"[a-z][a-z0-9_]{1,80}", key)
        and not key.startswith(("native_", "stored_", "wire_", "source_"))
        and not key.endswith(("_state", "_policy", "_provenance"))
        and any(finite(p.get(key)) for p in bundle.get("players", []))
    ]
    players = []
    identities = {}
    for p in bundle.get("players", []):
        side = p["side_index"]
        slot = p["stored_player_slot"]
        identity = (side, slot)
        if (
            side not in (0, 1)
            or identity in identities
            or p.get("fixture_key", p.get("native_match_key", key)) != key
        ):
            raise ValueError("Player fixture/side/slot mismatch")
        row = {k: p.get(k) for k in (*METRICS, *extra)}
        row.update(
            id=p.get("canonical_person_id") or f"unresolved:{side}:{slot}",
            side=side,
            slot=slot,
            name=p.get("person_name") or "Player identity unavailable",
            position=p.get("stored_match_position"),
            appearance=p.get("appearance_kind"),
            participation=p.get("participation_state"),
            source_row_sha256=p.get("row_sha256"),
            source_form_rating=p.get("match_rating"),
            rating_state=p.get("rating_gate"),
            pressure_completion_state=p.get("pressure_completion_state"),
        )
        if row["rating_state"] != "qualified":
            row["match_rating"] = None
        players.append(row)
        identities[identity] = row
    totals = []
    for side in (0, 1):
        found = [p for p in bundle.get("team_totals", []) if p["side_index"] == side]
        if len(found) > 1:
            raise ValueError("Duplicate team totals")
        totals.append(found[0] if found else {"side_index": side})
    spatial = bundle.get("spatial") or {}
    geometry = spatial.get("pitch_geometry") or bundle.get("geometry")
    valid_geometry = isinstance(geometry, dict) and all(
        finite(geometry.get(k)) and geometry[k] > 0
        for k in ("half_width_native", "half_length_native")
    )
    nodes = []
    for p in (spatial.get("average_positions") or {}).get("players", []):
        owner = identities.get((p["side_index"], p["stored_player_slot"]))
        if owner is None or owner["id"] != p["canonical_person_id"]:
            raise ValueError("Stored position actor differs from retained roster")
        if not all(finite(p.get(k)) for k in ("native_axis_0", "native_axis_1")):
            continue
        coverage = p.get("coverage") or {}
        tail = coverage.get("trailing_zero_pair_sample_count")
        nodes.append(
            {
                "id": p["canonical_person_id"],
                "side": p["side_index"],
                "name": owner["name"],
                "axis0": p["native_axis_0"],
                "axis1": p["native_axis_1"],
                "samples": p.get("sample_count", 0),
                "coverage": coverage,
                "trailing_zero_tail": tail,
                "unpadded": tail == 0,
                "clean_full_duration": owner["minutes"] == 90 and tail == 0,
                "possession_means": p.get("possession_means"),
            }
        )
    sides = []
    for side in (0, 1):
        original = next(
            (
                p
                for p in (spatial.get("pass_network") or {}).get("sides", [])
                if p["side_index"] == side
            ),
            None,
        )
        edges = []
        if (
            original
            and original.get("state") == "available"
            and original.get("all_captured_player_counters_match")
        ):
            for e in original["edges"]:
                if any(
                    not any(p["side"] == side and p["id"] == e[k] for p in players)
                    for k in ("from_person_native_id", "to_person_native_id")
                ):
                    raise ValueError("Passing connection actor outside checked roster")
                edges.append(
                    {
                        "from": e["from_person_native_id"],
                        "to": e["to_person_native_id"],
                        "count": e["counter_reconciled_completed_passes"],
                        "official_map_count": e.get("official_map_count"),
                        "excluded_mask8": e.get("excluded_unlabelled_mask8_count"),
                    }
                )
        sides.append(
            {
                "side": side,
                "state": original.get("state")
                if original
                else "unavailable_not_captured",
                "completed": original.get("counter_reconciled_completed_passes")
                if original
                else totals[side].get("passes_completed"),
                "official_map_records": original.get("official_map_record_count")
                if original
                else None,
                "excluded_mask8": original.get("excluded_unlabelled_mask8_count")
                if original
                else None,
                "edges": edges,
            }
        )
    shots = []
    coverage = bundle.get("shot_coverage", [])
    for raw in bundle.get("shots", []):
        if not valid_geometry:
            continue
        if (
            not all(
                finite(raw.get(k)) for k in ("native_x", "native_y", "expected_goals")
            )
            or not 0 <= raw["expected_goals"] <= 1
            or type(raw.get("attacked_goal_positive_native_y")) is not bool
        ):
            raise ValueError("Invalid verified shot geometry/xG")
        actor = raw.get("actor") or {}
        sign = 1 if raw["attacked_goal_positive_native_y"] else -1
        shots.append(
            {
                "side": raw["side_index"],
                "event_id": raw["event_id"],
                "player_id": actor.get("canonical_person_id"),
                "name": actor.get("person_name") or "Player identity unavailable",
                "axis0": sign * raw["native_x"],
                "axis1": sign * raw["native_y"],
                "xg": raw["expected_goals"],
                "outcome": raw.get("outcome"),
                "period": None,
                "location": raw.get("official_location"),
                "penalty": raw.get("is_penalty"),
                "source_sha256": raw.get("source_record_sha256"),
            }
        )
    observed_shots = []
    for raw in bundle.get("source_observed_shots", []):
        value = raw.get("native_expected_goals")
        actor = raw.get("actor") or {}
        if not valid_geometry or not actor.get("canonical_person_id"):
            continue
        if (
            not all(finite(raw.get(k)) for k in ("native_x", "native_y"))
            or not finite(value)
            or not 0 <= value <= 1
            or type(raw.get("attacked_goal_positive_native_y")) is not bool
        ):
            raise ValueError("Invalid source-observed shot fields")
        sign = 1 if raw["attacked_goal_positive_native_y"] else -1
        observed_shots.append(
            {
                "side": raw["side_index"],
                "event_id": raw["event_id"],
                "player_id": actor["canonical_person_id"],
                "name": actor.get("person_name") or "Player identity unavailable",
                "axis0": sign * raw["native_x"],
                "axis1": sign * raw["native_y"],
                "xg": value,
                "outcome": raw.get("outcome"),
                "period": None,
                "location": raw.get("official_location"),
                "penalty": raw.get("is_penalty"),
                "source_sha256": raw.get("source_record_sha256"),
                "verification_scope": "source_observed_counts_actors_verified_xg_unreconciled",
            }
        )
    periods = bundle.get("periods") or {}
    summary = []
    period_available = False
    if (
        periods.get("state") == "available_verified_period_intervals"
        or periods.get("confidence") == "verified_retrospective_continuity"
    ):
        assignments = {
            (p["side_index"], p["event_id"]): p["period"]
            for p in periods.get("shot_periods", [])
        }
        if (
            shots
            and len(assignments) == len(shots)
            and all(
                assignments.get((s["side"], s["event_id"]))
                in ("FirstHalf", "SecondHalf")
                for s in shots
            )
        ):
            period_available = True
            for shot in shots:
                shot["period"] = assignments[(shot["side"], shot["event_id"])]
            for name in ("FirstHalf", "SecondHalf"):
                for side in (0, 1):
                    selected = [
                        s for s in shots if s["period"] == name and s["side"] == side
                    ]
                    summary.append(
                        {
                            "side_index": side,
                            "period": name,
                            "shots": len(selected),
                            "shots_on_target": sum(
                                s["outcome"] in ("goal", "saved") for s in selected
                            )
                            if all(
                                s["outcome"]
                                in (
                                    "goal",
                                    "saved",
                                    "blocked",
                                    "missed_target",
                                    "hit_woodwork",
                                )
                                for s in selected
                            )
                            else None,
                            "shot_goals": sum(s["outcome"] == "goal" for s in selected)
                            if all(
                                s["outcome"]
                                in (
                                    "goal",
                                    "saved",
                                    "blocked",
                                    "missed_target",
                                    "hit_woodwork",
                                )
                                for s in selected
                            )
                            else None,
                            "xg_sum_computed": sum(s["xg"] for s in selected),
                        }
                    )
    heat = spatial.get("native_heat_map") or {}
    heat_window = {
        "players": [],
        "teams": [],
        "clean_90min_teams": [],
        "unpadded_teams": [],
    }
    if valid_geometry and heat.get("state") == "available":

        def compact(p):
            return {
                **{k: v for k, v in p.items() if k not in ("raw_cells", "cells")},
                "cells": [
                    [c["axis_0_index"], c["axis_1_index"], c["normalized_intensity"]]
                    for c in p["cells"]
                ],
            }

        heat_window["players"] = [compact(p) for p in heat.get("players", [])]
        heat_window["teams"] = [compact(p) for p in heat.get("teams", [])]
        from fm_live_mcp.live_tracking_heatmaps import _native_normalize_smooth

        for field, minimum in (("unpadded_teams", None), ("clean_90min_teams", 90)):
            for side in (0, 1):
                rows = [p for p in heat.get("players", []) if p["side_index"] == side]
                eligible = [
                    p
                    for p in rows
                    if any(
                        n["id"] == p["canonical_person_id"]
                        and n["side"] == side
                        and n["unpadded"]
                        and (minimum is None or n["clean_full_duration"])
                        for n in nodes
                    )
                ]
                if not rows or any("raw_cells" not in p for p in eligible):
                    continue
                grid = Counter()
                for p in eligible:
                    for c in p["raw_cells"]:
                        grid[c["axis_0_index"], c["axis_1_index"]] += c[
                            "interpolation_count"
                        ]
                cells, processing = _native_normalize_smooth(grid)
                heat_window[field].append(
                    compact(
                        {
                            "side_index": side,
                            "included_player_count": len(eligible),
                            "tracked_player_count": len(rows),
                            "excluded_player_count": len(rows) - len(eligible),
                            "cells": cells,
                            "raw_interpolation_count_total": sum(grid.values()),
                            "postprocessing": processing,
                        }
                    )
                )
    pressure_sides = []
    for side in (0, 1):
        rows = [p for p in players if p["side"] == side]
        complete = bool(rows) and all(
            type(p.get("pressures_attempted")) is int
            and type(p.get("pressures_completed")) is int
            and 0 <= p["pressures_completed"] <= p["pressures_attempted"]
            for p in rows
        )
        attempts = sum(p["pressures_attempted"] for p in rows) if complete else None
        completed = (
            sum(p["pressures_completed"] for p in rows)
            if rows and all(known(p.get("pressures_completed")) for p in rows)
            else None
        )
        pressure_sides.append(
            {
                "side_index": side,
                "pressures_attempted": attempts,
                "pressures_completed": completed,
                "pressure_completion_percentage_computed": 100 * completed / attempts
                if complete and attempts
                else None,
                "pressure_completion_state": "available"
                if complete and attempts
                else "undefined_zero_pressure_attempts"
                if complete
                else "unavailable_attempt_denominator",
            }
        )
        for p in rows:
            a, c = p.get("pressures_attempted"), p.get("pressures_completed")
            p["pressure_completion_percentage_computed"] = (
                100 * c / a
                if type(a) is int and type(c) is int and 0 <= c <= a and a
                else None
            )
    description = provenance["description"]
    data = {
        "extra_player_metrics": extra,
        "schema_version": 2,
        "match_key": key,
        "fixture": fixture,
        "teams": teams,
        "score": (fixture.get("scores") or {}).get("final_score")
        or {"home": None, "away": None},
        "geometry": geometry
        if valid_geometry
        else {"half_width_native": None, "half_length_native": None},
        "team_totals": totals,
        "players": players,
        "shots": shots,
        "shot_coverage": coverage,
        "source_observed_shots": observed_shots,
        "source_observed_coverage": bundle.get("source_observed_coverage", []),
        "half_split_available": period_available,
        "half_summary": summary,
        "period_boundaries": {},
        "average_nodes": nodes if valid_geometry else [],
        "pass_sides": sides,
        "heat_windows": {"Full": heat_window},
        "tracking_forward_proved_for_this_match": False,
        "provenance": [
            {
                "role": description,
                "file": provenance.get("filename", description),
                "sha256": provenance["capture_id"],
                "source_scope": provenance,
            }
        ],
        "report_source": provenance,
        "limits": [
            "Position means describe stored sample streams, not a simultaneous XI, role or playing-time share.",
            "Native heat algorithm reconstruction has no rendered UI oracle; each map uses its own intensity normalization.",
            "Trailing zero samples can bias stored means; default pools omit whole tailed streams and reference views retain them.",
            "Tracking signed forward, physical units and human left/right remain unproved. Shot attack direction is separately bound.",
            "Pass connections are counts between means, not ball routes. Missing tables/values remain unavailable, never zero.",
        ],
        "pressure_evidence": {
            "state": "captured_typed_player_counters",
            "sides": pressure_sides,
        }
        if any(p.get("pressures_completed") is not None for p in players)
        else None,
        "section_coverage": {
            "spatial": spatial.get("state", "unavailable_not_captured"),
            "source": description,
        },
    }
    if valid_geometry:
        _pass_points(data, bundle)
    return data


def _pass_points(data, bundle):
    rows = bundle.get("pass_attempts", [])
    if not rows:
        return
    people = {(p["side"], p["slot"]): p for p in data["players"]}
    points = []
    for p in rows:
        field = p.get("field_position")
        if (
            not field
            or field.get("location_semantics")
            not in (
                "official_pass_map_event_location; pass_origin_proved",
                # bundles captured before 14 November 2026
                "official_pass_map_event_location; ball_release_location_not_proved",
            )
        ):
            return
        actor = people.get((p["side_index"], p["stored_player_slot"]))
        if not actor or actor["id"] != p.get("person_native_id"):
            raise ValueError("Pass point actor differs from source roster")
        location = field["native_pass_map_location"]
        x, y = location["native_x"], location["native_y"]
        if not finite(x) or not finite(y):
            raise ValueError("Nonfinite pass-map point")
        points.append(
            {
                "event_id": p["event_id"],
                "record_index": p["record_index"],
                "side_index": p["side_index"],
                "stored_player_slot": p["stored_player_slot"],
                "person_native_id": actor["id"],
                "person_name": actor["name"],
                "native_category_code": p["native_category_code"],
                "completed": p["completed"],
                "native_x": x,
                "native_y": y,
                "attack_relative_longitudinal_coordinate": field[
                    "attack_relative_longitudinal_coordinate"
                ],
                "inside_native_pitch_extents": field["inside_native_pitch_extents"],
                "analytical_pitch_third": field.get("analytical_pitch_third"),
                "analytical_lateral_channel": field.get("analytical_lateral_channel"),
                "recipient_person_native_id": p.get("recipient_person_native_id")
                if p["completed"]
                else None,
                "recipient_name": p.get("recipient_name") if p["completed"] else None,
            }
        )
    if len({p["event_id"] for p in points}) != len(points):
        raise ValueError("Duplicate pass event")
    for identity, actor in people.items():
        selected = [
            p for p in points if (p["side_index"], p["stored_player_slot"]) == identity
        ]
        if actor.get("passes_attempted") != len(selected) or actor.get(
            "passes_completed"
        ) != sum(p["completed"] for p in selected):
            return
    data["pass_event_locations"] = {
        "state": "verified_complete_counter_reconciled_pass_event_locations",
        "points": points,
        "geometry": data["geometry"],
        "side_coverage": [
            {
                "side_index": s,
                "player_counter_checks": sum(p["side"] == s for p in data["players"]),
                "attempt_count": sum(p["side_index"] == s for p in points),
                "completed_count": sum(
                    p["side_index"] == s and p["completed"] for p in points
                ),
            }
            for s in (0, 1)
        ],
        "evidence_scope": "Pinned producer field_position records with full captured actor/counter closure; not a re-decoded CBE byte buffer",
        "source_capture": data["report_source"],
    }
