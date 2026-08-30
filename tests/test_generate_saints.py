"""Offline regression tests; no network calls or production feed writes."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import generate_saints as saints


def record(date):
    return dict(zip(saints.FIELDS, [date, "Saint Test", "Commemoration", "Reviewed",
                                   "Alternate", "", "Reviewed paragraph — unchanged.",
                                   "https://example.org/saint"]))


class MonthlySaintsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.directory.name)
        self.path = Path("public/saint.json")
        self.path.parent.mkdir()
        env = patch.dict(os.environ, {"START_MONTH": "2026-10", "MONTHS": "1", "VERBOSE": "0"})
        env.start()
        self.addCleanup(env.stop)
        self.sleep = patch.object(saints.time, "sleep").start()
        self.scrape = patch.object(saints, "scrape_usccb", return_value={"saintName": "Scraped Saint"}).start()
        self.addCleanup(patch.stopall)

    def seed(self, rows):
        self.path.write_text(json.dumps(rows, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")

    def read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def draft(self):
        path = next(Path("drafts").glob("saints-*.json"))
        return json.loads(path.read_text(encoding="utf-8"))

    def month(self, year, month):
        return [record(d.isoformat()) for d in saints.month_range(dt.date(year, month, 1), 1)]

    def test_october_preserves_august_september_and_future_records(self):
        existing = self.month(2026, 8) + self.month(2026, 9) + [record("2026-12-01")]
        expected = copy.deepcopy(existing)
        self.seed(existing)
        saints.main()
        self.assertEqual(self.read(), expected)
        result = self.draft()
        by_date = {row["date"]: row for row in result}
        self.assertEqual(len(result), 31)
        self.assertEqual(list(by_date), sorted(by_date))
        self.assertTrue(all(tuple(row) == saints.FIELDS for row in result))

    def test_rerun_is_byte_identical_and_does_not_scrape(self):
        self.seed(self.month(2026, 8) + self.month(2026, 9) + self.month(2026, 10))
        before = self.path.read_bytes()
        saints.main()
        self.assertEqual(self.path.read_bytes(), before)
        self.scrape.assert_not_called()
        self.sleep.assert_not_called()

    def test_partial_month_only_adds_missing_dates(self):
        self.seed([record("2026-09-01"), record("2026-10-03")])
        saints.main()
        self.assertEqual(len(self.read()), 2)
        self.assertEqual(len(self.draft()), 31)
        self.assertEqual(self.scrape.call_count, 30)
        self.assertEqual(self.draft()[2], record("2026-10-03"))

    def test_blank_months_defaults_to_one(self):
        os.environ["MONTHS"] = "  "
        saints.main()
        self.assertFalse(self.path.exists())
        self.assertEqual(len(self.draft()), 31)

    def test_absent_months_defaults_to_one(self):
        os.environ.pop("MONTHS")
        saints.main()
        self.assertFalse(self.path.exists())
        self.assertEqual(len(self.draft()), 31)

    def test_next_month_uses_configured_timezone(self):
        os.environ["START_MONTH"] = ""
        with patch.object(saints, "TZ", "America/New_York"), patch.object(saints.dt, "datetime") as clock:
            clock.now.return_value.date.return_value = dt.date(2026, 8, 31)
            saints.main()
            self.assertEqual(clock.now.call_args.args[0].key, "America/New_York")
        self.assertEqual(self.draft()[0]["date"], "2026-09-01")
        self.assertEqual(self.draft()[-1]["date"], "2026-09-30")

    def test_december_to_january_and_leap_year(self):
        os.environ.update(START_MONTH="2027-12", MONTHS="2")
        self.seed([record("2026-09-01")])
        saints.main()
        self.assertEqual(len(self.read()), 1)
        self.assertEqual(len(self.draft()), 62)
        self.assertEqual(self.draft()[-1]["date"], "2028-01-31")
        self.assertEqual(len(saints.month_range(dt.date(2028, 2, 1), 1)), 29)

    def test_invalid_month_configuration_does_not_write(self):
        self.seed([record("2026-09-01")])
        before = self.path.read_bytes()
        for start, count in [("2026-10", "0"), ("2026-10", "-1"), ("2026-10", "13"),
                             ("2026-10", "x"), ("2026-13", "1"), ("2026-9", "1")]:
            with self.subTest(start=start, count=count):
                os.environ.update(START_MONTH=start, MONTHS=count)
                with self.assertRaises(SystemExit) as error:
                    saints.main()
                self.assertEqual(error.exception.code, 2)
                self.assertEqual(self.path.read_bytes(), before)
        self.scrape.assert_not_called()

    def test_malformed_existing_json_is_not_replaced(self):
        self.path.write_text("[broken json", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            saints.main()
        self.assertEqual(self.path.read_text(encoding="utf-8"), "[broken json")
        self.scrape.assert_not_called()

    def test_invalid_existing_records_are_not_replaced(self):
        cases = [{}, [record("2026-09-01"), record("2026-09-01")],
                 [record("2026-02-30")], [record("2026-9-01")],
                 [{"date": "2026-09-01"}], [dict(record("2026-09-01"), profile=None)], [None]]
        for rows in cases:
            with self.subTest(rows=rows):
                self.seed(rows)
                before = self.path.read_bytes()
                with self.assertRaises(ValueError):
                    saints.main()
                self.assertEqual(self.path.read_bytes(), before)
        self.scrape.assert_not_called()

    def test_read_error_is_not_treated_as_empty_history(self):
        self.seed([record("2026-09-01")])
        with patch("builtins.open", side_effect=PermissionError("unreadable")):
            with self.assertRaises(PermissionError):
                saints.main()
        self.scrape.assert_not_called()
        self.assertEqual(self.read(), [record("2026-09-01")])

    def test_atomic_replace_failure_keeps_original_and_cleans_temporary(self):
        self.seed([record("2026-09-01")])
        before = self.path.read_bytes()
        with patch.object(saints.os, "replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                saints.main()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(Path(".").rglob("*.tmp")), [])

    def test_existing_record_is_not_mutated_by_build_record(self):
        existing = {"2026-09-01": record("2026-09-01")}
        before = copy.deepcopy(existing)
        result = saints.build_record(dt.date(2026, 9, 1), existing)
        self.assertEqual(result, before["2026-09-01"])
        self.assertEqual(existing, before)
        self.assertIsNot(result, existing["2026-09-01"])
        self.scrape.assert_not_called()

    def test_scraper_failure_retains_history_and_calendar_scaffold(self):
        self.scrape.side_effect = RuntimeError("offline")
        self.seed([record("2026-09-01")])
        saints.main()
        self.assertEqual(self.read()[0], record("2026-09-01"))
        self.assertEqual(len(self.read()), 1)
        self.assertEqual(len(self.draft()), 31)
        self.assertEqual(self.draft()[-1]["profile"], "")


if __name__ == "__main__":
    unittest.main()
