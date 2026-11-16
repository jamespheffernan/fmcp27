import copy, hashlib, importlib.util, json, os, sqlite3, tempfile, unittest
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch, Mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import general_report, report_sources, report_output


def fixture():
    return {
        "date": "2030-11-11",
        "home_team": {
            "native_id": 688,
            "database_index": 545,
            "owner": {"name": "Newcastle United", "short_name": "Newcastle"},
        },
        "away_team": {
            "native_id": 692,
            "database_index": 549,
            "owner": {"name": "Nottingham Forest", "short_name": "Forest"},
        },
        "competition": {"native_id": 11, "name": "Premier League"},
        "scores": {"final_score": {"home": 4, "away": 1}},
        "fixture_ref": "process-local-ref",
    }


def bundle():
    return {
        "fixture": fixture(),
        "native_match_key": 7,
        "players": [],
        "provenance": {
            "description": "Pinned historical capture",
            "capture_id": "a" * 64,
            "captured_save": {},
            "source_mode": "captured",
        },
    }


class Selection(unittest.TestCase):
    def live(self):
        return dict(
            source="retained",
            fixture_date="2030-11-11",
            home_team_native_id=688,
            away_team_native_id=692,
            competition_native_id=11,
            expected_home_goals=4,
            expected_away_goals=1,
            career_name="Career",
            career_created_date="2025-10-23",
            career_created_version=1,
        )

    def test_no_caller_paths_or_source_objects(self):
        for field in [
            "output",
            "path",
            "source_json",
            "html",
            "fixture_ref",
            "session_id",
        ]:
            r = self.live()
            r[field] = "anything"
            with self.assertRaises(ValueError):
                report_sources.validate(r)

    def test_boolean_native_id_not_integer(self):
        r = self.live()
        r["home_team_native_id"] = True
        with self.assertRaises(ValueError):
            report_sources.validate(r)

    def test_captured_pins_required(self):
        with self.assertRaises(ValueError):
            report_sources.validate(
                dict(source="captured", source_id="x", fixture_id="f")
            )

    def test_captured_path_not_catalog_id(self):
        with self.assertRaises(ValueError):
            report_sources.validate(
                dict(
                    source="captured",
                    source_id="/tmp/source.sqlite",
                    capture_id="a" * 64,
                    fixture_id="f",
                )
            )

    def test_current_score_recheck_before_capture_and_detach(self):
        b = Mock()
        b.attach.return_value = {"session_id": "new"}
        b.get_save.return_value = {
            "save": {
                "name": "Career",
                "created_date": "2025-10-23",
                "created_version": 1,
            }
        }
        other = fixture()
        other["scores"]["final_score"]["home"] = 3
        b.find_fixtures.return_value = {"fixtures": [other], "next_cursor": None}
        with (
            patch("fm_live_mcp.match_data_query.capture_epoch", return_value="epoch"),
            patch("fm_live_mcp.match_data_query.capture_live") as capture,
        ):
            with self.assertRaisesRegex(ValueError, "score changed"):
                report_sources.retained(self.live(), lambda: b)
            capture.assert_not_called()
            b.detach.assert_called_once()

    def test_duplicate_result_rejected_even_same_date_teams(self):
        b = Mock()
        b.attach.return_value = {"session_id": "new"}
        b.get_save.return_value = {
            "save": {
                "name": "Career",
                "created_date": "2025-10-23",
                "created_version": 1,
            }
        }
        b.find_fixtures.return_value = {
            "fixtures": [fixture(), fixture()],
            "next_cursor": None,
        }
        with patch("fm_live_mcp.match_data_query.capture_epoch", return_value="epoch"):
            with self.assertRaisesRegex(ValueError, "uniquely"):
                report_sources.retained(self.live(), lambda: b)
        b.detach.assert_called_once()


class Missingness(unittest.TestCase):
    def test_no_maps_no_fabricated_coordinates(self):
        d = general_report.normalise(bundle())
        self.assertEqual(
            d["geometry"], {"half_width_native": None, "half_length_native": None}
        )
        self.assertEqual(d["average_nodes"], [])
        self.assertFalse(d["half_split_available"])
        self.assertNotIn("pass_event_locations", d)

    def test_unknown_denominator_not_zero(self):
        b = bundle()
        b["players"] = [
            dict(
                fixture_key=7,
                side_index=0,
                stored_player_slot=0,
                canonical_person_id=42,
                person_name="Known",
                pressures_completed=2,
                minutes=90,
            )
        ]
        d = general_report.normalise(b)
        self.assertIsNone(d["players"][0]["pressures_attempted"])
        self.assertIsNone(d["players"][0]["pressure_completion_percentage_computed"])
        self.assertIsNone(d["pressure_evidence"]["sides"][0]["pressures_attempted"])

    def test_true_zero_denominator_stays_undefined(self):
        b = bundle()
        b["players"] = [
            dict(
                fixture_key=7,
                side_index=0,
                stored_player_slot=0,
                canonical_person_id=42,
                person_name="Known",
                pressures_completed=0,
                pressures_attempted=0,
                minutes=90,
            )
        ]
        d = general_report.normalise(b)
        self.assertIsNone(d["players"][0]["pressure_completion_percentage_computed"])
        self.assertEqual(d["pressure_evidence"]["sides"][0]["pressures_attempted"], 0)

    def test_unqualified_zero_rating_withheld(self):
        b = bundle()
        b["players"] = [
            dict(
                side_index=0,
                stored_player_slot=0,
                canonical_person_id=42,
                match_rating=0.0,
            )
        ]
        d = general_report.normalise(b)
        self.assertIsNone(d["players"][0]["match_rating"])

    def test_duplicate_native_slot_rejected(self):
        b = bundle()
        b["players"] = [dict(side_index=0, stored_player_slot=0)] * 2
        with self.assertRaisesRegex(ValueError, "slot"):
            general_report.normalise(b)

    def test_old_capture_dribbles_remain_unknown(self):
        b = bundle()
        b["players"] = [
            dict(side_index=0, stored_player_slot=0, canonical_person_id=42)
        ]
        self.assertIsNone(general_report.normalise(b)["players"][0]["dribbles_made"])

    def test_new_declared_numeric_counter_is_preserved(self):
        b = bundle()
        b["field_provenance"] = {
            "new_action_count": {"unit": "count"},
            "native_debug_word": {"unit": "raw"},
        }
        b["players"] = [
            dict(
                side_index=0,
                stored_player_slot=0,
                canonical_person_id=42,
                new_action_count=7,
                native_debug_word=123,
            )
        ]
        d = general_report.normalise(b)
        self.assertEqual(d["extra_player_metrics"], ["new_action_count"])
        self.assertEqual(d["players"][0]["new_action_count"], 7)
        self.assertNotIn("native_debug_word", d["players"][0])


class PublicationFailure(unittest.TestCase):
    def test_postwrite_timeout_never_claims_no_artifact(self):
        import generate_report, subprocess, io

        request = dict(
            source="captured",
            source_id="test",
            capture_id="a" * 64,
            fixture_id="fixture",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve() / "Outputs"

            def publisher(*args, **kwargs):
                report_output.publish(
                    {
                        "fixture": {"date": "2030-11-11"},
                        "teams": [{"short_name": "Home"}, {"short_name": "Away"}],
                    },
                    b"<!doctype html>published",
                    outputs=root,
                )
                raise subprocess.TimeoutExpired(args[0], 30)

            def renderer(data, path):
                path.write_bytes(b"<!doctype html>published")

            output = io.StringIO()
            with (
                patch.object(generate_report, "captured", return_value=bundle()),
                patch.object(generate_report, "render", side_effect=renderer),
                patch.object(generate_report.subprocess, "run", side_effect=publisher),
                patch.object(
                    sys,
                    "stdin",
                    io.TextIOWrapper(io.BytesIO(json.dumps(request).encode())),
                ),
                patch.object(sys, "stdout", output),
            ):
                self.assertEqual(generate_report.main(), 1)
            receipt = json.loads(output.getvalue())
            self.assertIsNone(receipt["artifact_created"])
            self.assertIn("may exist", receipt["error"])
            self.assertEqual(len(list(root.iterdir())), 1)


class Output(unittest.TestCase):
    def data(self):
        return {
            "fixture": {"date": "2030-11-11"},
            "teams": [{"short_name": "../../Home"}, {"short_name": "Away"}],
        }

    def test_immutable_original_and_identical_reuse(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t).resolve() / "Outputs"
            a = report_output.publish(
                self.data(), b"<!doctype html>verified", outputs=root
            )
            b = report_output.publish(
                self.data(), b"<!doctype html>verified", outputs=root
            )
            self.assertEqual(Path(a["path"]).parent, root)
            self.assertEqual(a["path"], b["path"])
            self.assertTrue(b["existing_matching_original"])
            self.assertEqual(len(list(root.iterdir())), 1)

    def test_symlink_parent_refused(self):
        with tempfile.TemporaryDirectory() as t:
            outside = Path(t).resolve() / "outside"
            outside.mkdir()
            link = Path(t).resolve() / "link"
            link.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(OSError):
                report_output.publish(self.data(), b"<!doctype html>x", outputs=link)
            self.assertEqual(list(outside.iterdir()), [])

    def test_existing_symlink_never_followed(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t).resolve() / "Outputs"
            a = report_output.publish(self.data(), b"<!doctype html>x", outputs=root)
            p = Path(a["path"])
            p.unlink()
            outside = Path(t).resolve() / "outside"
            outside.write_text("keep")
            p.symlink_to(outside)
            with self.assertRaises(OSError):
                report_output.publish(self.data(), b"<!doctype html>x", outputs=root)
            self.assertEqual(outside.read_text(), "keep")

    def test_invalid_date_cannot_escape_output_root(self):
        data = self.data()
        data["fixture"]["date"] = "../../escape"
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError):
                report_output.publish(
                    data, b"<!doctype html>x", outputs=Path(t).resolve() / "Outputs"
                )

    def test_collision_does_not_overwrite_modified_original(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t).resolve() / "Outputs"
            a = report_output.publish(self.data(), b"<!doctype html>x", outputs=root)
            p = Path(a["path"])
            p.write_text("my edit")
            with self.assertRaises(FileExistsError):
                report_output.publish(self.data(), b"<!doctype html>x", outputs=root)
            self.assertEqual(p.read_text(), "my edit")


if __name__ == "__main__":
    unittest.main()
