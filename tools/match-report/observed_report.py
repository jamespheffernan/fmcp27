"""Project one catalog-pinned observed run without upgrading its table scopes."""

import hashlib
import json
import math
import struct
from collections import Counter


def prepare_registered(db, provenance, fixture_id, career_id=None):
    def rows(table):
        derived = provenance.get("_derived_views", {}).get(table)
        if derived:
            return [
                {key: row.get(key) for key in derived["columns"]}
                for row in derived["rows"]
            ]
        if table not in provenance["available_tables"]:
            return []
        columns = provenance["available_tables"][table]
        from fm_live_mcp.observed_match_runs import SHOT_FIELDS

        expressions = [
            f"json_extract(record_json, '$.{c}')"
            if table == "shots" and c in SHOT_FIELDS
            else '"' + c + '"'
            for c in columns
        ]
        return [
            dict(zip(columns, row))
            for row in db.execute(
                "SELECT " + ",".join(expressions) + ' FROM "' + table + '"'
            )
        ]

    documents = {}
    embedded_hashes = {}
    for name, digest, raw in db.execute(
        "SELECT source_id,sha256,document_json FROM source_documents"
    ):
        embedded_hashes[name] = hashlib.sha256(raw.encode()).hexdigest()
        if (
            provenance["limitations"].get("producer")
            == "explicit_observed_prefix_recorder"
            and embedded_hashes[name] != digest
        ):
            raise ValueError("Recorded prefix source document hash differs")
        documents[name] = json.loads(raw)
    fixtures = rows("fixtures")
    if (
        len(fixtures) != 1
        or str(fixtures[0].get("official_match_unique_id")) != fixture_id
    ):
        raise ValueError(
            "Observed fixture pin differs from its exact registered fixture"
        )
    original = fixtures[0]
    save = provenance["captured_save"]
    career = {k: save[k] for k in ("name", "created_date", "created_version")}
    career_hash = hashlib.sha256(
        json.dumps(career, sort_keys=True).encode()
    ).hexdigest()
    if career_id is not None and career_hash != career_id:
        raise ValueError("Observed career pin differs")
    terminal = documents["terminal"]
    native_fixture = terminal.get("fixture", {})
    if native_fixture.get("date", original["date"]) != original["date"]:
        raise ValueError("Observed terminal fixture date differs")
    terminal_uid = native_fixture.get(
        "official_match_unique_id",
        terminal.get("bound_playback", {}).get("official_match_unique_id"),
    )
    if (
        terminal_uid is not None
        and terminal_uid != original["official_match_unique_id"]
    ):
        raise ValueError("Observed terminal official fixture identity differs")
    native_competition = native_fixture.get("competition", {}).get(
        "native_id", native_fixture.get("competition_id")
    )
    if (
        native_competition is not None
        and native_competition != original["competition_id"]
    ):
        raise ValueError("Observed terminal competition differs")
    teams = []
    for side, key in enumerate(("home_team", "away_team")):
        native_id = original["home_team_id" if side == 0 else "away_team_id"]
        source_team = native_fixture.get(key, {})
        if source_team and source_team.get("native_id") != native_id:
            raise ValueError(
                "Observed fixture team identity differs from source document"
            )
        owner = source_team.get("owner", {})
        name = owner.get("name") or f"Team {native_id}"
        teams.append(
            {
                "side_index": side,
                "native_id": native_id,
                "name": name,
                "short_name": owner.get("short_name") or name,
            }
        )
    tables = {
        name: rows(name)
        for name in provenance["available_tables"]
        if name != "fixtures"
    }
    # Raw JSON diagnostic columns stay host-side. Projection rows retain typed fields only.
    for table in tables.values():
        for row in table:
            for key in ("record_json", "coverage_json"):
                row.pop(key, None)
    limitations = provenance["limitations"]
    scope = limitations.get("capture_state") or (
        "terminal_observation"
        if terminal.get("displayed_period") == "FullTime"
        else "unclassified_observation"
    )
    source = {
        **{k: v for k, v in provenance.items() if not k.startswith("_")},
        "embedded_document_sha256": embedded_hashes,
        "source_mode": "observed",
        "source_kind": "observed_native_match_run",
        "career_id": career_hash,
        "capture_observed_at_utc": provenance.get("observed_at_utc"),
        "selected_fixture_id": fixture_id,
        "description": "Pinned observed match source; each section retains its captured prefix or terminal scope.",
    }
    data = {
        "report_kind": "registered_observed_run",
        "schema_version": 1,
        "match_key": None,
        "fixture": {
            "date": original["date"],
            "competition": {
                "native_id": original["competition_id"],
                "name": native_fixture.get("competition", {}).get("name")
                or f"Competition {original['competition_id']}",
            },
        },
        "teams": teams,
        "score": {
            "home": original.get("home_score"),
            "away": original.get("away_score"),
        },
        "players": tables.get("pass_actors", []),
        "shots": tables.get("shots", []),
        "average_nodes": tables.get("average_positions", []),
        "observed_tables": tables,
        "observed_scope": scope,
        "fixed_time_slice": limitations.get(
            "fixed_time_slice",
            terminal.get(
                "fixed_time_slice",
                terminal.get("bound_playback", {}).get("current_time_slice"),
            ),
        ),
        "report_source": source,
        "provenance": [
            {
                "role": "Immutable observed-run original",
                "file": provenance["filename"],
                "sha256": provenance["capture_id"],
            }
        ],
        "half_split_available": False,
        "section_coverage": {
            "spatial": provenance["table_scopes"].get(
                "average_positions", "unavailable"
            )
        },
        "limits": [
            provenance["claim"],
            "Full retained player statistics, passing attempts/accuracy and active XI are unavailable in this observed product.",
            "Unknown score, periods and missing tables remain unavailable; source clocks are native ticks, not displayed minutes.",
        ],
    }
    data["observed_shot_map"] = _shot_map(db, documents, tables)
    if limitations.get("replay_exclusion_verified") is False:
        data["limits"].append("Replay exclusion remains unverified in this recording.")
    data["observed_density"] = _density(db, provenance, tables, limitations)
    return data


def _density(db, provenance, tables, limitations):
    cells = tables.get("heatmap_cells", [])
    if cells:
        return {
            "kind": "captured_sample_density",
            "scope": provenance["table_scopes"].get(
                "heatmap_cells", "Captured table scope"
            ),
            "columns": max(c["axis_1_index"] for c in cells) + 1,
            "rows": max(c["axis_0_index"] for c in cells) + 1,
            "cells": cells,
            "coordinate_scope": "Captured grid indices; native axes and physical units remain unproved.",
        }
    # Prefix recordings preserve raw samples but do not preserve pitch geometry.
    # Plot a sample-density extent, never invent pitch dimensions or field lines.
    names = {
        r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if not {"tracking_sources", "tracking_context"} <= names:
        return None
    from fm_live_mcp.live_average_positions import (
        tracking_positive_orientation,
        MAX_TRACKING_SAMPLES,
        MAX_TRACKING_PLAYERS,
    )

    profile = db.execute("SELECT orientation_profile FROM tracking_context").fetchone()
    if profile is None:
        return None
    cursor = limitations.get("fixed_time_slice")
    points = []
    tracking_rows = db.execute(
        "SELECT side_index,stored_player_slot,start_tick,sample_step_native_ticks,samples FROM tracking_sources"
    ).fetchall()
    if len(tracking_rows) > MAX_TRACKING_PLAYERS:
        raise ValueError("Recorded tracking player budget exceeded")
    for side, slot, start, step, raw in tracking_rows:
        if (
            side not in (0, 1)
            or type(slot) is not int
            or not 0 <= slot < 26
            or type(start) is not int
            or start < 0
            or step != 24
            or len(raw) % 4
            or len(raw) // 4 > MAX_TRACKING_SAMPLES
            or type(cursor) is not int
        ):
            raise ValueError("Unsupported recorded tracking prefix")
        for i, pair in enumerate(struct.iter_unpack("<hh", raw)):
            tick = start + i * step
            if tick > cursor:
                raise ValueError("Recorded tracking exceeds fixed prefix")
            sign = 1 if tracking_positive_orientation(profile[0], side, tick) else -1
            points.append((side, slot, sign * pair[0] * 0.01, sign * pair[1] * 0.01))
    if not points:
        return None
    bounds = {
        "axis_0_min": min(p[2] for p in points),
        "axis_0_max": max(p[2] for p in points),
        "axis_1_min": min(p[3] for p in points),
        "axis_1_max": max(p[3] for p in points),
    }
    counts = Counter()
    for side, slot, a, b in points:
        x = min(
            19,
            int(
                20
                * (b - bounds["axis_1_min"])
                / (bounds["axis_1_max"] - bounds["axis_1_min"] or 1)
            ),
        )
        y = min(
            12,
            int(
                13
                * (a - bounds["axis_0_min"])
                / (bounds["axis_0_max"] - bounds["axis_0_min"] or 1)
            ),
        )
        counts[side, slot, x, y] += 1
    return {
        "kind": "raw_recorded_prefix_sample_density",
        "scope": provenance["table_scopes"].get(
            "tracking_sources", "Recorded raw prefix samples"
        ),
        "columns": 20,
        "rows": 13,
        "bounds": bounds,
        "cells": [
            {
                "side_index": side,
                "stored_player_slot": slot,
                "axis_1_index": x,
                "axis_0_index": y,
                "sample_count": n,
            }
            for (side, slot, x, y), n in sorted(counts.items())
        ],
        "sample_count": len(points),
        "coordinate_scope": "Bounds are the combined recorded sample extent, not a football pitch. Zero pairs and post-exit tails remain included; samples do not measure minutes or physical distance.",
    }


def _shot_map(db, documents, tables):
    geometry = documents["terminal"].get("raw_source", {}).get(
        "pitch_geometry"
    ) or documents.get("match_statistics_samples", {}).get("pitch_geometry")
    if not isinstance(geometry, dict) or not all(
        type(geometry.get(k)) in (int, float)
        and math.isfinite(geometry[k])
        and geometry[k] > 0
        for k in ("half_width_native", "half_length_native")
    ):
        return None
    if not tables.get("shots"):
        return None
    columns = {r[1] for r in db.execute("PRAGMA table_info(shots)")}
    if "record_json" not in columns:
        return None
    records = {
        event: json.loads(raw)
        for event, raw in db.execute("SELECT event_id,record_json FROM shots")
    }
    actors = {
        (s["side_index"], s["event_id"]): s
        for s in tables.get("named_shot_chances", [])
    }
    points = []
    for shot in tables["shots"]:
        raw = records[shot["event_id"]]
        if type(raw.get("attacked_goal_positive_native_y")) is not bool:
            return None
        if (
            not all(
                type(shot.get(k)) in (int, float) and math.isfinite(shot[k])
                for k in ("native_x", "native_y", "expected_goals")
            )
            or not 0 <= shot["expected_goals"] <= 1
        ):
            raise ValueError("Invalid observed shot map coordinate or xG")
        sign = 1 if raw["attacked_goal_positive_native_y"] else -1
        points.append(
            {
                **shot,
                "axis_0": sign * shot["native_x"],
                "axis_1": sign * shot["native_y"],
                "actor_name": actors.get(
                    (shot["side_index"], shot["event_id"]), {}
                ).get("shooter_name")
                or shot.get("actor_name"),
            }
        )
    return {
        "geometry": geometry,
        "points": points,
        "scope": "Recorded shot-event scope; ended-exclusive attempt boundaries remain distinct from scoreboard boundaries.",
    }
