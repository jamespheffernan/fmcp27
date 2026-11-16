import hashlib, json, sqlite3, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from observed_report import prepare_registered
from report_sources import validate


def source():
    db = sqlite3.connect(":memory:")
    db.executescript("""CREATE TABLE fixtures(date TEXT,competition_id INTEGER,home_team_id INTEGER,away_team_id INTEGER,official_match_unique_id INTEGER);
 CREATE TABLE source_documents(source_id TEXT,sha256 TEXT,document_json TEXT);
 CREATE TABLE completed_pass_events(event_id INTEGER,side_index INTEGER,sender_slot INTEGER,receiver_slot INTEGER,sender_name TEXT,receiver_name TEXT,period TEXT);
 CREATE TABLE pass_actors(side_index INTEGER,stored_player_slot INTEGER,canonical_person_id INTEGER,person_name TEXT);
 CREATE TABLE average_positions(team_native_id INTEGER,person_id INTEGER,person_name TEXT,sample_count INTEGER,axis_0 REAL,axis_1 REAL,cursor INTEGER);
 CREATE TABLE tracking_sources(side_index INTEGER,stored_player_slot INTEGER,start_tick INTEGER,sample_step_native_ticks INTEGER,samples BLOB);
 CREATE TABLE tracking_context(orientation_profile BLOB);""")
    db.execute("INSERT INTO fixtures VALUES ('2031-02-03',9,10,20,123)")
    db.execute("INSERT INTO completed_pass_events VALUES (1,0,0,1,'Alice',NULL,NULL)")
    db.execute("INSERT INTO pass_actors VALUES (0,0,70,'Alice')")
    db.execute("INSERT INTO average_positions VALUES (10,70,'Alice',2,0.005,0.01,100)")
    db.execute(
        "INSERT INTO tracking_sources VALUES (0,0,50,24,?)",
        (bytes.fromhex("0000000001000200"),),
    )
    db.execute("INSERT INTO tracking_context VALUES (?)", (bytes(16),))
    save = {
        "name": "Different career",
        "created_date": "2030-01-01",
        "created_version": 27,
        "current_date": "2031-02-03",
        "last_saved_date": "2031-02-02",
    }
    raw = json.dumps(
        {
            "save": save,
            "fixture": {"date": "2031-02-03", "home_team_id": 10, "away_team_id": 20},
            "fixed_time_slice": 100,
        }
    )
    db.execute(
        "INSERT INTO source_documents VALUES ('terminal',?,?)",
        (hashlib.sha256(raw.encode()).hexdigest(), raw),
    )
    tables = ["fixtures", "completed_pass_events", "pass_actors", "average_positions"]
    p = {
        "source_id": "prefix",
        "capture_id": "a" * 64,
        "filename": "prefix.sqlite",
        "captured_save": save,
        "observed_at_utc": "2026-11-08T00:00:00Z",
        "available_tables": {
            t: [r[1] for r in db.execute("PRAGMA table_info(" + t + ")")]
            for t in tables
        },
        "table_scopes": {
            "average_positions": "fixed prefix means; not on-pitch time",
            "tracking_sources": "raw points through tick100",
            "completed_pass_events": "completed events only; unknown period preserved",
        },
        "source_document_hashes": {
            "terminal": hashlib.sha256(raw.encode()).hexdigest()
        },
        "limitations": {
            "producer": "explicit_observed_prefix_recorder",
            "capture_state": "partial_prefix",
            "fixed_time_slice": 100,
            "terminal_completeness_verified": False,
            "replay_exclusion_verified": False,
            "missing_scopes": ["shots", "score", "full_match_completion"],
        },
        "claim": "Distinct observed run; native clocks are not displayed minutes.",
    }
    return db, p


class ObservedReports(unittest.TestCase):
    def test_prefix_preserves_unknown_score_shots_periods_and_names(self):
        db, p = source()
        try:
            d = prepare_registered(db, p, "123")
            self.assertEqual(d["observed_scope"], "partial_prefix")
            self.assertEqual(d["score"], {"home": None, "away": None})
            self.assertNotIn("shots", d["observed_tables"])
            self.assertIsNone(
                d["observed_tables"]["completed_pass_events"][0]["period"]
            )
            self.assertIsNone(
                d["observed_tables"]["completed_pass_events"][0]["receiver_name"]
            )
            self.assertEqual(d["teams"][0]["name"], "Team 10")
            self.assertFalse(d["half_split_available"])
        finally:
            db.close()

    def test_prefix_density_preserves_zero_pairs_and_actual_sample_extent(self):
        db, p = source()
        try:
            d = prepare_registered(db, p, "123")["observed_density"]
            self.assertEqual(d["sample_count"], 2)
            self.assertEqual(sum(c["sample_count"] for c in d["cells"]), 2)
            self.assertIn("not a football pitch", d["coordinate_scope"])
            self.assertNotIn("pitch_geometry", d)
        finally:
            db.close()

    def test_different_fixture_and_career_pins_are_rejected(self):
        db, p = source()
        try:
            with self.assertRaisesRegex(ValueError, "fixture pin"):
                prepare_registered(db, p, "124")
            with self.assertRaisesRegex(ValueError, "career pin"):
                prepare_registered(db, p, "123", "b" * 64)
        finally:
            db.close()

    def test_mutated_prefix_source_document_is_rejected(self):
        db, p = source()
        try:
            db.execute("UPDATE source_documents SET document_json='{}'")
            with self.assertRaisesRegex(ValueError, "document hash"):
                prepare_registered(db, p, "123")
        finally:
            db.close()

    def test_future_tracking_sample_is_rejected(self):
        db, p = source()
        try:
            db.execute("UPDATE tracking_sources SET start_tick=90")
            with self.assertRaisesRegex(ValueError, "exceeds fixed prefix"):
                prepare_registered(db, p, "123")
        finally:
            db.close()

    def test_additive_shots_score_and_event_stats_keep_distinct_boundaries(self):
        db, p = source()
        try:
            db.executescript("""ALTER TABLE fixtures ADD home_score INTEGER; ALTER TABLE fixtures ADD away_score INTEGER;
            UPDATE fixtures SET home_score=2,away_score=0;
            CREATE TABLE shots(event_id INTEGER,side_index INTEGER,native_x REAL,native_y REAL,expected_goals REAL,outcome TEXT,period TEXT,record_json TEXT);
            CREATE TABLE player_shot_statistics(person_name TEXT,shots INTEGER,assists INTEGER,state TEXT);""")
            raw = json.dumps({"attacked_goal_positive_native_y": True})
            db.execute("INSERT INTO shots VALUES (5,0,1,2,0.2,'goal',NULL,?)", (raw,))
            db.execute(
                "INSERT INTO player_shot_statistics VALUES ('Alice',1,NULL,'event_derived_prefix')"
            )
            document = json.dumps(
                {"pitch_geometry": {"half_width_native": 30, "half_length_native": 50}}
            )
            db.execute(
                "INSERT INTO source_documents VALUES ('match_statistics_samples',?,?)",
                (hashlib.sha256(document.encode()).hexdigest(), document),
            )
            for t in ("fixtures", "shots", "player_shot_statistics"):
                p["available_tables"][t] = [
                    r[1]
                    for r in db.execute("PRAGMA table_info(" + t + ")")
                    if r[1] != "record_json"
                ]
            p["table_scopes"]["player_shot_statistics"] = (
                "event-derived ended-exclusive prefix; not retained PLAYER counters"
            )
            d = prepare_registered(db, p, "123")
            self.assertEqual(d["score"], {"home": 2, "away": 0})
            self.assertEqual(len(d["observed_shot_map"]["points"]), 1)
            self.assertIsNone(
                d["observed_tables"]["player_shot_statistics"][0]["assists"]
            )
            self.assertEqual(d["observed_scope"], "partial_prefix")
            self.assertFalse(d["half_split_available"])
        finally:
            db.close()

    def test_observed_selector_rejects_paths_and_missing_pins(self):
        r = {
            "source": "observed",
            "source_id": "catalog",
            "capture_id": "a" * 64,
            "fixture_id": "123",
        }
        self.assertEqual(validate(r), r)
        for key in ("path", "html", "session_id", "raw_source"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate({**r, key: "injected"})
        with self.assertRaises(ValueError):
            validate({k: v for k, v in r.items() if k != "capture_id"})


if __name__ == "__main__":
    unittest.main()
