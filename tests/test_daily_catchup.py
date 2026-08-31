"""Offline coverage for midnight recovery and strict, read-only daily no-ops."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from scripts.daily_publication_needed import inspect
from scripts.build_archive_search import build
from scripts.feed_io import write_json
from test_publication import devotion, saint
from update_daily_devotion import prepare_entry


class DailyCatchupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.public = self.root / "public"
        self.archive = self.public / "past_reflections"
        self.day = "2026-08-31"
        self.now = datetime(2026, 8, 31, 9, tzinfo=ZoneInfo("America/New_York"))
        write_json(self.public / "weeklyfeed.json", [devotion(self.day), devotion("2026-09-01")])
        write_json(self.public / "saint.json", [saint(self.day), saint("2026-09-01")])
        self.row = prepare_entry(devotion(self.day), self.public / "saint.json")
        write_json(self.public / "devotions.json", [self.row])
        self.snapshot = self.archive / "2026/08/2026-08-31.json"
        write_json(self.snapshot, self.row)
        self.index = {k: self.row.get(k, "") for k in (
            "date", "quote", "quoteCitation", "tags", "usccbLink", "feast", "cycle", "weekdayCycle")}
        self.index["path"] = "/past_reflections/2026/08/2026-08-31.json"
        write_json(self.archive / "index.json", [self.index])
        write_json(self.archive / "search-v1.json", build(self.archive))

    def check(self):
        return inspect(self.root, self.now)

    def test_current_full_publication_is_read_only_noop(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*.json")}
        with patch("scripts.saints_feed.remote_records", side_effect=AssertionError("No network")):
            self.assertFalse(self.check()["needed"])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*.json")})

    def test_midnight_rollover_needs_publication_even_with_prepared_tomorrow(self):
        self.now = datetime(2026, 9, 1, 0, 1, tzinfo=self.now.tzinfo)
        self.assertTrue(self.check()["needed"])
        self.assertEqual(self.check()["date"], "2026-09-01")

    def test_clock_uses_eastern_day_before_and_after_dst(self):
        for utc, expected in [((2026, 9, 1, 3, 59), "2026-08-31"),
                              ((2026, 9, 1, 4, 0), "2026-09-01"),
                              ((2026, 12, 1, 4, 59), "2026-11-30"),
                              ((2026, 12, 1, 5, 0), "2026-12-01")]:
            with self.subTest(utc=utc):
                self.assertEqual(inspect(self.root, datetime(*utc, tzinfo=timezone.utc))["date"], expected)

    def test_same_date_source_correction_needs_republication(self):
        write_json(self.public / "weeklyfeed.json", [dict(devotion(self.day), quote="Reviewed correction")])
        self.assertTrue(self.check()["needed"])

    def test_same_date_saint_correction_needs_republication(self):
        revised = saint(self.day)
        revised["profile"] += " Additional reviewed teaching."
        write_json(self.public / "saint.json", [revised])
        self.assertTrue(self.check()["needed"])

    def test_wrong_daily_content_is_not_skipped_on_date_alone(self):
        write_json(self.public / "devotions.json", [dict(self.row, gospelSummary="Outdated reflection")])
        self.assertTrue(self.check()["needed"])

    def test_missing_or_corrupt_outputs_cannot_report_current(self):
        for path in (self.public / "devotions.json", self.snapshot,
                     self.archive / "index.json", self.archive / "search-v1.json"):
            original = path.read_bytes()
            with self.subTest(path=path):
                path.unlink()
                self.assertTrue(self.check()["needed"])
                path.write_text("{broken", encoding="utf-8")
                self.assertTrue(self.check()["needed"])
                path.write_bytes(original)

    def test_stale_snapshot_and_indexes_need_repair(self):
        write_json(self.snapshot, dict(self.row, dailyPrayer="Outdated prayer"))
        self.assertTrue(self.check()["needed"])
        write_json(self.snapshot, self.row)
        write_json(self.archive / "index.json", [dict(self.index, quote="Old quotation")])
        self.assertTrue(self.check()["needed"])
        write_json(self.archive / "index.json", [self.index])
        write_json(self.archive / "search-v1.json", dict(build(self.archive), revision="stale"))
        self.assertTrue(self.check()["needed"])

    def test_missing_source_or_saint_needs_validation_without_network_or_generation(self):
        with patch("scripts.saints_feed.remote_records", side_effect=AssertionError("No network")):
            write_json(self.public / "saint.json", [])
            self.assertTrue(self.check()["needed"])
            write_json(self.public / "weeklyfeed.json", [devotion("2026-09-01")])
            self.assertTrue(self.check()["needed"])

    def test_future_daily_date_is_not_current(self):
        write_json(self.public / "devotions.json", [devotion("2026-09-01")])
        self.assertTrue(self.check()["needed"])

    def test_naive_clock_rejected(self):
        with self.assertRaisesRegex(ValueError, "aware clock"):
            inspect(self.root, datetime(2026, 8, 31))


if __name__ == "__main__":
    unittest.main()
