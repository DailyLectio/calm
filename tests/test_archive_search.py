import copy
import json
from pathlib import Path
import tempfile
import unittest
from scripts.build_archive_search import build, entry, digest
from test_publication import devotion


class ArchiveSearchTests(unittest.TestCase):
    def test_snapshot_hash_is_portable_across_git_line_endings(self):
        self.assertEqual(digest(b'{"date":"2026-08-30"}\r\n'), digest(b'{"date":"2026-08-30"}\n'))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.archive = Path(self.temp.name)

    def snapshot(self, row):
        day = row["date"]
        path = self.archive / day[:4] / day[5:7] / f"{day}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row), encoding="utf-8")
        return path

    def test_history_bytes_unchanged_and_searchable_fields_present(self):
        row = devotion("2026-08-30")
        row.update(cycle="Year B", weekdayCycle="Cycle I")
        path = self.snapshot(row)
        before = path.read_bytes()
        result = build(self.archive)["entries"][0]
        self.assertEqual(before, path.read_bytes())
        self.assertEqual(result["cycle"], "Year A")
        self.assertEqual(result["weekdayCycle"], "Cycle II")
        self.assertEqual(result["synthesis"], row["theologicalSynthesis"])
        self.assertEqual(result["quoteCitation"], row["quoteCitation"])
        self.assertIn(row["firstReadingRef"], result["refs"])
        self.assertEqual(result["sha256"], digest(before))

    def test_same_date_correction_changes_revision_and_keeps_old_days(self):
        row = devotion()
        self.snapshot(devotion("2026-08-31"))
        self.snapshot(row)
        before = build(self.archive)
        updated = dict(row, quote="Corrected quotation")
        after = build(self.archive, [updated])
        self.assertEqual(after["count"], 2)
        self.assertNotEqual(before["revision"], after["revision"])
        self.assertNotEqual(before["entries"][0]["sha256"], after["entries"][0]["sha256"])
        self.assertEqual(after["entries"][1], before["entries"][1])
        self.assertEqual(build(self.archive), before)

    def test_gap_is_not_fabricated_and_result_is_deterministic(self):
        for day in ("2026-08-28", "2026-08-30"):
            self.snapshot(devotion(day))
        self.assertEqual(build(self.archive), build(self.archive))
        self.assertEqual([r["date"] for r in build(self.archive)["entries"]], ["2026-08-30", "2026-08-28"])

    def test_advent_transition_and_second_reading_reference(self):
        for day, year, cycle in [("2026-11-28", "Year A", "Cycle II"), ("2026-11-29", "Year B", "Cycle I")]:
            row = dict(devotion(day), secondReadingRef="Romans 13:11-14")
            result = entry(row, b"fixture")
            self.assertEqual((result["cycle"], result["weekdayCycle"]), (year, cycle))
            self.assertIn("Romans 13:11-14", result["refs"])

    def test_invalid_source_or_incomplete_index_stops_build(self):
        path = self.snapshot(devotion())
        index = self.archive / "index.json"
        index.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "disagree"):
            build(self.archive)
        index.unlink()
        path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            build(self.archive)

    def test_bad_dates_duplicate_updates_and_unsafe_paths_fail(self):
        with self.assertRaises(ValueError):
            entry(dict(devotion(), date="2026-02-30"), b"")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            build(self.archive, [devotion(), devotion()])
        self.snapshot(devotion()).rename(self.archive / "2026/09/2026-09-02.json")
        with self.assertRaisesRegex(ValueError, "mismatched"):
            build(self.archive)


if __name__ == "__main__":
    unittest.main()
