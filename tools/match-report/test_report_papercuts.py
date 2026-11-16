"""Finite receipt/filename regressions; fixture writes stay in a temporary root."""
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import generate_report
import report_output
import report_sources

REQUEST = dict(source="captured", source_id="test", capture_id="a" * 64, fixture_id="test")
FILENAME = "2026-11-09 — Newcastle Liverpool match report.html"
BAD = [None, True, "", ".html", "../report.html", "/report.html", "dir/report.html", "dir\\report.html",
       "report:other.html", "report.htm", " report.html", "report.html ", "a\n.html", "a\x00.html",
       "a\x85.html", "a\u2028.html", "a\u202e.html", "é" * 123 + ".html"]


class Names(unittest.TestCase):
    def test_requested_leaf_exact_reuse_and_collision_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "Agent Outputs"
            data = {"fixture": {"date": "2030-11-30"}, "teams": [{"short_name": "Newcastle"}, {"short_name": "Liverpool"}]}
            first = report_output.publish(data, b"<!doctype html>first", outputs=root, filename=FILENAME)
            self.assertEqual(Path(first["path"]), root / FILENAME)
            self.assertEqual((root / FILENAME).read_bytes(), b"<!doctype html>first")
            self.assertTrue(report_output.publish(data, b"<!doctype html>first", outputs=root, filename=FILENAME)["existing_matching_original"])
            with self.assertRaises(FileExistsError):
                report_output.publish(data, b"<!doctype html>different", outputs=root, filename=FILENAME)
            self.assertEqual((root / FILENAME).read_bytes(), b"<!doctype html>first")

    def test_invalid_names_refused_before_source_open(self):
        for name in BAD:
            with self.subTest(name=name), patch.object(generate_report, "captured") as opened:
                with self.assertRaises((ValueError, UnicodeError)):
                    generate_report.generate({**REQUEST, "filename": name})
                opened.assert_not_called()

    def test_all_three_selector_modes_allow_safe_leaf_only(self):
        requests = [REQUEST, {**REQUEST, "source": "observed"}, dict(source="retained", fixture_date="2030-11-30", home_team_native_id=688,
            away_team_native_id=676, competition_native_id=11, expected_home_goals=1, expected_away_goals=2,
            career_name="Career", career_created_date="2025-10-23", career_created_version=1)]
        for request in requests:
            self.assertEqual(report_sources.validate({**request, "filename": FILENAME})["filename"], FILENAME)

    def test_custom_leaf_symlink_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "Agent Outputs";root.mkdir()
            target = root / "existing.txt";target.write_text("preserve")
            (root / FILENAME).symlink_to(target)
            with self.assertRaises(OSError):
                report_output.publish({"fixture": {"date": "2030-11-30"}, "teams": [{"short_name": "N"}, {"short_name": "L"}]}, b"<!doctype html>x", outputs=root, filename=FILENAME)
            self.assertEqual(target.read_text(), "preserve")

    def test_custom_leaf_fifo_refused_without_waiting_for_a_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "Agent Outputs";root.mkdir()
            os.mkfifo(root / FILENAME)
            script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from report_output import publish
data = {'fixture': {'date': '2030-11-30'}, 'teams': [{'short_name': 'N'}, {'short_name': 'L'}]}
try:
    publish(data, b'<!doctype html>x', outputs=Path(sys.argv[2]), filename=sys.argv[3])
except FileExistsError:
    pass
else:
    raise AssertionError('FIFO admitted')
"""
            result = subprocess.run(
                [sys.executable, "-B", "-c", script, str(Path(report_output.__file__).parent), str(root), FILENAME],
                capture_output=True, timeout=3,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((root / FILENAME).is_fifo())


class Receipt(unittest.TestCase):
    def test_default_name_receipt_reports_saved_qualified_rows(self):
        self.saved_genuine_receipt()

    def test_requested_name_receipt_reports_saved_qualified_rows(self):
        self.saved_genuine_receipt(FILENAME)

    def saved_genuine_receipt(self, filename=None):
        # Original preserved packet, original source adapter and normaliser.
        from test_retained_observed_integration import bundle as retained_bundle
        bundle = retained_bundle()
        data = generate_report.normalise(bundle)
        real_run = subprocess.run
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            def publisher(command, **kwargs):
                self.assertEqual(command[:2], ["/usr/bin/sandbox-exec", "-f"])
                self.assertEqual(command[-1], str(Path(generate_report.__file__).parent / "report_publish.py"))
                # Execute the actual private publisher with an isolated HOME. No
                # production Agent Outputs or live source is touched by this test.
                return real_run([sys.executable, "-B", command[-1]], env={**os.environ, "HOME": str(home)}, **kwargs)
            with patch.object(generate_report, "captured", return_value=bundle), patch.object(generate_report.subprocess, "run", side_effect=publisher):
                receipt = generate_report.generate({**REQUEST, **({"filename": filename} if filename else {})})
            self.assertEqual(Path(receipt["path"]).parent, home / "Agent Outputs")
            if filename:
                self.assertEqual(Path(receipt["path"]).name, filename)
            import gzip, re
            html = Path(receipt["path"]).read_bytes()
            embedded = re.search(rb'id="match-data">([^<]+)</script>', html)[1]
            readback = json.loads(gzip.decompress(base64.b64decode(embedded)))
            self.assertEqual(readback["source_observed_shots"], data["source_observed_shots"])
            self.assertEqual(readback["shots"], data["shots"])
            c = receipt["coverage"]
            self.assertEqual(c["strict_shots"], 11)
            self.assertEqual(c["source_observed_shot_rows"], 6)
            self.assertEqual(c["source_observed_side_coverage"], [{"side_index": 0, "state": "available_source_observed_counts_verified_xg_unreconciled", "observed_shot_count": 6, "rows_in_report": 6}])
            self.assertIn("xG unreconciled", c["source_observed_scope"])
            self.assertIn("Not promoted", c["source_observed_scope"])
            self.assertIsNone(c["observed_shot_rows"])
            self.assertEqual(len(data["shots"]), c["strict_shots"])
            self.assertIsNone(data["shot_coverage"][0]["expected_goals"])


if __name__ == "__main__":
    unittest.main()
