"""Exact source selectors for host-side report generation; no caller paths."""

from datetime import date, datetime, timezone
import hashlib, json, re


def validate(request):
    if not isinstance(request, dict):
        raise ValueError("Expected report selection object")
    mode = request.get("source")
    common = {"source", "filename"}
    if "filename" in request:
        from report_output import validate_filename

        validate_filename(request["filename"])
    if mode == "retained":
        required = {
            "fixture_date",
            "home_team_native_id",
            "away_team_native_id",
            "competition_native_id",
            "expected_home_goals",
            "expected_away_goals",
            "career_name",
            "career_created_date",
            "career_created_version",
        }
        allowed = common | required | {"native_match_key"}
        if not required <= request.keys() or request.keys() - allowed:
            raise ValueError(
                "Provide exact retained fixture, score and career selectors only"
            )
        for field in ("fixture_date", "career_created_date"):
            if (
                not isinstance(request[field], str)
                or date.fromisoformat(request[field]).isoformat() != request[field]
            ):
                raise ValueError("Use exact ISO dates")
        if (
            not isinstance(request["career_name"], str)
            or not 1 <= len(request["career_name"]) <= 200
        ):
            raise ValueError("Expected career name required")
        for field in (
            "home_team_native_id",
            "away_team_native_id",
            "competition_native_id",
            "career_created_version",
            "native_match_key",
        ):
            if field in request and (
                type(request[field]) is not int or not 0 < request[field] < 2**63
            ):
                raise ValueError("Native selectors must be positive integers")
        if request["home_team_native_id"] == request["away_team_native_id"]:
            raise ValueError("Select different ordered teams")
        for field in ("expected_home_goals", "expected_away_goals"):
            if type(request[field]) is not int or not 0 <= request[field] <= 999:
                raise ValueError("Expected score must be known nonnegative integers")
    elif mode in ("captured", "observed"):
        required = {"source_id", "capture_id", "fixture_id"}
        allowed = common | required | {"career_id"}
        if not required <= request.keys() or request.keys() - allowed:
            raise ValueError("Provide catalog source/capture/fixture pins only")
        if not isinstance(request["source_id"], str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,128}", request["source_id"]
        ):
            raise ValueError("Use a catalog source_id")
        if not isinstance(request["fixture_id"], str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,128}", request["fixture_id"]
        ):
            raise ValueError("Use the selected catalog fixture pin")
        for field in ("capture_id", "career_id"):
            if field in request and (
                not isinstance(request[field], str)
                or not re.fullmatch(r"[0-9a-f]{64}", request[field])
            ):
                raise ValueError("Use exact catalog SHA256 pins")
    else:
        raise ValueError("source must be retained, captured or observed")
    return request


def _serial(value):
    if isinstance(value, bytes):
        return {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    raise TypeError(type(value).__name__)


def captured(request):
    from fm_live_mcp.captured_match_sources import open_source

    with open_source(
        request["source_id"], request["capture_id"], request.get("career_id")
    ) as (db, provenance):
        cursor = db.execute(
            "SELECT * FROM fixtures WHERE fixture_id=?", (request["fixture_id"],)
        )
        names = [c[0] for c in cursor.description]
        rows = cursor.fetchall()
        if len(rows) != 1:
            raise ValueError("Captured fixture_id is not present exactly once")
        row = dict(zip(names, rows[0]))
        fid = row["fixture_id"]
        key = row["native_match_key"]
        original = json.loads(row["raw_json"])
        fixture = original["fixture"]
        tables = {
            r[0]
            for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }

        def documents(table):
            if table not in tables:
                return []
            return [
                json.loads(r[0])
                for r in db.execute(
                    "SELECT raw_json FROM " + table + " WHERE fixture_id=?", (fid,)
                )
            ]

        spatial = documents("spatial_packets")
        periods = documents("match_period_evidence")
        coverage = documents("shot_map_coverage")
        geometry = spatial[0].get("pitch_geometry") if spatial else None
        if geometry is None and coverage:
            widths = db.execute(
                "SELECT pitch_half_width_native,pitch_half_length_native FROM shot_map_coverage WHERE fixture_id=?",
                (fid,),
            ).fetchall()
            if widths and widths[0][0] and widths[0][1]:
                geometry = dict(
                    zip(("half_width_native", "half_length_native"), widths[0])
                )
        bundle = {
            "fixture": fixture,
            "native_match_key": key,
            "players": documents("retained_players"),
            "team_totals": documents("team_totals"),
            "shots": documents("shots"),
            "shot_coverage": coverage,
            "source_observed_shots": documents("source_observed_shots"),
            "source_observed_coverage": documents("source_observed_shot_coverage"),
            "spatial": spatial[0] if spatial else None,
            "geometry": geometry,
            "periods": periods[0] if periods else None,
            "pass_attempts": documents("pass_attempts"),
            "provenance": {
                **provenance,
                "description": "Pinned captured match; capture date is historical, not a new game read",
                "source_mode": "captured",
                "selected_fixture_id": fid,
                "selected_native_match_key": key,
            },
        }
    return bundle


def retained(request, bridge_factory=None):
    if bridge_factory is None:
        from fm_live_mcp.bridge import Bridge

        bridge_factory = Bridge
    from fm_live_mcp.match_data_query import capture_live, capture_epoch
    from fm_live_mcp.live_retained_shots import capture_retained_shot_maps
    from fm_live_mcp.retained_spatial_report import capture_spatial
    from fm_live_mcp.live_retained_pass_events import capture_retained_pass_attempts

    bridge = bridge_factory()
    sid = bridge.attach()["session_id"]
    try:
        initial = bridge.get_save(sid)["save"]
        epoch = capture_epoch(bridge, sid)
        for field, selector in (
            ("name", "career_name"),
            ("created_date", "career_created_date"),
            ("created_version", "career_created_version"),
        ):
            if initial.get(field) != request[selector]:
                raise ValueError(
                    "Loaded career differs from the selected career; refresh live identity"
                )
        query = dict(
            year=int(request["fixture_date"][:4]),
            team_native_id=request["home_team_native_id"],
            competition_native_id=request["competition_native_id"],
            date_from=request["fixture_date"],
            date_to=request["fixture_date"],
            record_kind="result",
            max_matches=100,
            record_budget=1000,
            bucket_budget=4096,
            selector_prefilter=True,
        )
        fixtures = []
        for _ in range(32):
            page = bridge.find_fixtures(sid, **query)
            fixtures += page["fixtures"]
            if page.get("next_cursor") is None:
                break
            query["cursor"] = page["next_cursor"]
        else:
            raise ValueError("Exact fixture lookup exceeded page bound")
        selected = [
            f
            for f in fixtures
            if f["home_team"]["native_id"] == request["home_team_native_id"]
            and f["away_team"]["native_id"] == request["away_team_native_id"]
            and f["competition"]["native_id"] == request["competition_native_id"]
            and f["date"] == request["fixture_date"]
        ]
        if len(selected) != 1:
            raise ValueError(
                "The selected retained fixture is not uniquely materialized; no historical file was substituted"
            )
        fixture = selected[0]
        expected = {
            "home": request["expected_home_goals"],
            "away": request["expected_away_goals"],
        }
        if fixture.get("scores", {}).get("final_score") != expected:
            raise ValueError("Selected result score changed; refresh fixture selection")
        ref = fixture["fixture_ref"]
        frame = capture_live(bridge, sid, [ref])
        item = frame["capture"]["fixtures"][0]
        key = item["native_match_key"]
        if key is None or (
            "native_match_key" in request and request["native_match_key"] != key
        ):
            raise ValueError(
                "Selected native result key changed or has no retained statistics"
            )
        shots = capture_retained_shot_maps(
            bridge, sid, [ref], fixture_captures=frame, include_source_observed=True
        )
        spatial = capture_spatial(
            bridge, sid, ref, fixture_captures=frame, include_native_heat_map=True
        )
        first = capture_retained_pass_attempts(
            bridge, sid, ref, limit=500, fixture_captures=frame
        )
        attempts = list(first.get("attempts", []))
        offset = first.get("next_offset")
        for _ in range(32):
            if offset is None:
                break
            page = capture_retained_pass_attempts(
                bridge,
                sid,
                ref,
                offset=offset,
                limit=500,
                expected_source_id=first["source_id"],
                fixture_captures=frame,
            )
            attempts += page["attempts"]
            offset = page.get("next_offset")
        else:
            raise ValueError("Selected pass data exceeded pagination bound")
        if offset is not None:
            raise ValueError("Incomplete pass source")
        from fm_live_mcp.match_period_tools import report_retained_periods

        periods = report_retained_periods(bridge, sid, ref)
        final = bridge.get_save(sid)["save"]
        stable = lambda value: {
            k: v
            for k, v in value.items()
            if k not in ("current_date", "last_saved_date", "save_count")
        }
        if capture_epoch(bridge, sid) != epoch or stable(initial) != stable(final):
            raise ValueError("Native world/career changed during match report read")
        record = shots["records"][0]
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "fixture": fixture,
                    "key": key,
                    "players": frame["retained_players"],
                    "totals": frame["team_totals"],
                    "shot_source": record.get("source_id"),
                    "spatial": spatial,
                    "pass_source": first.get("source_id"),
                    "epoch": epoch,
                },
                sort_keys=True,
                default=_serial,
            ).encode()
        ).hexdigest()
        return {
            "fixture": fixture,
            "native_match_key": key,
            "players": frame["retained_players"],
            "team_totals": frame["team_totals"]["records"][0]["teams"],
            "shots": record.get("shots", []),
            "shot_coverage": record.get("side_coverage", []),
            "source_observed_shots": record.get("source_observed_shots", []),
            "source_observed_coverage": record.get("source_observed_coverage", []),
            "geometry": record.get("pitch_geometry"),
            "spatial": spatial,
            "pass_attempts": attempts,
            "periods": periods,
            "field_provenance": frame["capture"].get("action_field_provenance", {}),
            "provenance": {
                "source_mode": "retained",
                "description": "Fresh read-only retained result from the running career",
                "capture_id": fingerprint,
                "source_id": "current_retained_result",
                "filename": "running career",
                "captured_save": final,
                "capture_observed_at_utc": datetime.now(timezone.utc).isoformat(),
                "selected_native_match_key": key,
                "shot_source_id": record.get("source_id"),
                "source_observed_policy": record.get("source_observed_policy"),
                "same_native_epoch_verified": True,
                "game_writes": False,
                "game_inputs": False,
                "native_functions_executed": False,
            },
        }
    finally:
        bridge.detach()


def observed(request):
    from fm_live_mcp.observed_match_runs import open_run
    from render_observation_report import prepare_registered

    with open_run(request["source_id"], request["capture_id"]) as (db, provenance):
        return prepare_registered(
            db, provenance, request["fixture_id"], request.get("career_id")
        )
