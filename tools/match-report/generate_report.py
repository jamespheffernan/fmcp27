#!/usr/bin/env python3
"""Fixed host entry point: exact match selectors on stdin, optional safe HTML leaf, never caller directories."""

import base64, hashlib, json, sys, tempfile, subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from report_sources import validate, captured, retained, observed
from general_report import normalise
from render_match_report import render


class PublicationUncertainError(RuntimeError):
    artifact_created = None


def generate(request):
    validate(request)
    if request["source"] == "observed":
        data = observed(request)
    else:
        bundle = (
            captured(request) if request["source"] == "captured" else retained(request)
        )
        data = normalise(bundle)
    # The renderer is pure; scratch output remains in the approved external workspace.
    scratch = ROOT / "tmp/match-reports"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="render-", dir=scratch) as directory:
        path = Path(directory) / "report.html"
        render(data, path)
        html = path.read_bytes()
    publisher = Path(__file__).parent
    protocol = {
        "data": {"fixture": {"date": data["fixture"]["date"]}, "teams": data["teams"]},
        "html_base64": base64.b64encode(html).decode(),
    }
    if "filename" in request:
        protocol["filename"] = request["filename"]
    source = {
        key: value
        for key, value in data["report_source"].items()
        if key
        in (
            "source_mode",
            "source_kind",
            "source_id",
            "capture_id",
            "career_id",
            "filename",
            "captured_save",
            "capture_observed_at_utc",
            "capture_observed_at_scope",
            "description",
            "claim",
            "selected_fixture_id",
            "selected_native_match_key",
            "same_native_epoch_verified",
        )
    }
    receipt = {
        "state": "ready",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "fixture": {
            "date": data["fixture"]["date"],
            "competition": data["fixture"]["competition"].get("name"),
            "home": data["teams"][0]["name"],
            "away": data["teams"][1]["name"],
            "score": data["score"],
            "native_match_key": data["match_key"],
        },
        "source": source,
        "coverage": {
            "players": len(data["players"]),
            "strict_shots": len(data["shots"])
            if request["source"] != "observed"
            else None,
            "source_observed_shot_rows": len(data.get("source_observed_shots", []))
            if request["source"] != "observed"
            else None,
            "source_observed_side_coverage": [
                {
                    "side_index": row["side_index"],
                    "state": row["state"],
                    "observed_shot_count": row["observed_shot_count"],
                    "rows_in_report": sum(
                        shot["side"] == row["side_index"]
                        for shot in data.get("source_observed_shots", [])
                    ),
                }
                for row in data.get("source_observed_coverage", [])
            ]
            if request["source"] != "observed"
            else None,
            "source_observed_scope": "Separate qualified observations; counts and actors verified, attempt xG unreconciled with official aggregates. Not promoted to strict shots."
            if request["source"] != "observed" and data.get("source_observed_shots")
            else None,
            "observed_shot_rows": len(data["observed_tables"]["shots"])
            if request["source"] == "observed" and "shots" in data["observed_tables"]
            else None,
            "observed_completed_pass_events": len(
                data["observed_tables"]["completed_pass_events"]
            )
            if request["source"] == "observed"
            and "completed_pass_events" in data["observed_tables"]
            else None,
            "retained_player_statistics_available": request["source"] != "observed",
            "named_tracking_streams": len(
                {(p["team_native_id"], p["person_id"]) for p in data["average_nodes"]}
            )
            if request["source"] == "observed"
            else len(data["average_nodes"]),
            "tracking_state": data["section_coverage"]["spatial"],
            "shot_periods_verified": data["half_split_available"],
            "retained_tracking_periods": ["Full"]
            if request["source"] != "observed"
            else [],
            "observed_scope": data.get("observed_scope"),
            "observed_table_scopes": data.get("report_source", {}).get("table_scopes")
            if request["source"] == "observed"
            else None,
            "pass_map_points": len(
                data.get("pass_event_locations", {}).get("points", [])
            ),
            "source_kind": "fresh_retained_read"
            if request["source"] == "retained"
            else "pinned_observed_run"
            if request["source"] == "observed"
            else "pinned_historical_capture",
        },
        "limits": data["limits"],
        "renderer_sha256": hashlib.sha256(
            (Path(__file__).parent / "dist/report.js").read_bytes()
        ).hexdigest(),
    }
    command = [
        "/usr/bin/sandbox-exec",
        "-f",
        str(publisher / "report_publish.sb"),
        "-D",
        "OUTPUTS_ROOT=" + str(Path.home().resolve() / "Agent Outputs"),
        "/usr/bin/python3",
        "-B",
        str(publisher / "report_publish.py"),
    ]
    try:
        child = subprocess.run(
            command,
            input=json.dumps(protocol),
            text=True,
            capture_output=True,
            timeout=30,
        )
        if child.returncode:
            raise RuntimeError(child.stderr.strip() or "Report publication failed")
        result = json.loads(child.stdout)
        if not isinstance(result, dict) or not all(
            k in result for k in ("path", "sha256", "bytes")
        ):
            raise ValueError("Publication returned no complete receipt")
    except Exception as error:
        raise PublicationUncertainError(
            "Publication was attempted; an artifact may exist. Retry the same selectors safely. "
            + str(error)
        ) from error
    return {**result, **receipt}


def main():
    try:
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise ValueError("Report selectors exceed input bound")
        result = generate(json.loads(raw))
    except Exception as error:
        print(
            json.dumps(
                {
                    "state": "unavailable",
                    "error": str(error),
                    "artifact_created": getattr(error, "artifact_created", False),
                },
                ensure_ascii=False,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
