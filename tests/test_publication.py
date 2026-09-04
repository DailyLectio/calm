"""Offline contract, recovery, saints-source, and calendar regression tests."""
import copy
from datetime import date
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from contextlib import redirect_stdout

from scripts import saints_feed, generate_weekly
from scripts.ensure_daily_source import ensure_day
from scripts.feed_io import read_array
from scripts.liturgical_calendar import first_sunday_of_advent, sunday_cycle, weekday_cycle
from scripts.validate_publication import validate_rows
import update_daily_devotion as daily


def saint(day="2026-09-01"):
    row = {key: "" for key in saints_feed.FIELDS}
    row.update(date=day, saintName="Saint Test", source="Reviewed source", memorial="Commemoration",
               profile=("A reviewed reflection on prayer and faith in Christ. " * 6).strip(),
               link="https://example.org/saint")
    return row


def devotion(day="2026-09-01"):
    row = {key: "Test reflection." for key in (
        "quote", "quoteCitation", "firstReading", "psalmSummary", "gospelSummary", "saintReflection",
        "dailyPrayer", "theologicalSynthesis", "exegesis")}
    row.update(date=day, firstReadingRef="1 Corinthians 2:10b-16", secondReadingRef="", secondReading="",
               psalmRef="Psalm 145:8-9", gospelRef="Luke 4:31-37", gospelReference="Luke 4:31-37",
               cycle=sunday_cycle(date.fromisoformat(day)), weekdayCycle=weekday_cycle(date.fromisoformat(day)),
               feast="", tags=["prayer"], usccbLink="https://bible.usccb.org/bible/readings/090126.cfm",
               lectionaryKey=f"{day}:1 Corinthians 2:10b-16||Psalm 145:8-9|Luke 4:31-37")
    return row


class CalendarTests(unittest.TestCase):
    def test_usccb_boundaries_across_four_years(self):
        fixtures = [("2025-11-29", "Year C", "Cycle I"), ("2025-11-30", "Year A", "Cycle II"),
                    ("2026-01-01", "Year A", "Cycle II"), ("2026-11-22", "Year A", "Cycle II"),
                    ("2026-11-28", "Year A", "Cycle II"), ("2026-11-29", "Year B", "Cycle I"),
                    ("2027-11-27", "Year B", "Cycle I"), ("2027-11-28", "Year C", "Cycle II"),
                    ("2028-12-02", "Year C", "Cycle II"), ("2028-12-03", "Year A", "Cycle I")]
        for day, sunday, weekday in fixtures:
            with self.subTest(day=day):
                self.assertEqual(sunday_cycle(date.fromisoformat(day)), sunday)
                self.assertEqual(weekday_cycle(date.fromisoformat(day)), weekday)

    def test_advent_is_always_sunday_between_november_27_and_december_3(self):
        for year in range(2000, 2101):
            advent = first_sunday_of_advent(year)
            self.assertEqual(advent.weekday(), 6)
            self.assertTrue(date(year, 11, 27) <= advent <= date(year, 12, 3))

    def test_three_year_rotation_is_not_hardcoded_to_2026(self):
        for year in range(2020, 2041):
            self.assertEqual(sunday_cycle(date(year, 7, 1)), sunday_cycle(date(year + 3, 7, 1)))
            self.assertNotEqual(weekday_cycle(date(year, 7, 1)), weekday_cycle(date(year + 1, 7, 1)))


class FileTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.feed = self.root / "weeklyfeed.json"
        self.saints = self.root / "saint.json"
        self.saints.write_text(json.dumps([saint()]), encoding="utf-8")

    def seed(self, rows):
        self.feed.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")

    def test_recovery_merges_one_day_and_preserves_other_records(self):
        original = [devotion("2026-08-31"), devotion("2026-09-02")]
        self.seed(original)
        build = Mock(return_value=devotion())
        self.assertTrue(ensure_day("2026-09-01", self.feed, build))
        result = read_array(self.feed)
        self.assertEqual([result[0], result[2]], original)
        self.assertEqual([r["date"] for r in result], ["2026-08-31", "2026-09-01", "2026-09-02"])
        build.assert_called_once_with(date(2026, 9, 1))

    def test_existing_day_never_invokes_generation_or_rewrites_file(self):
        self.seed([devotion()])
        before = self.feed.read_bytes()
        build = Mock(side_effect=AssertionError("must not generate"))
        self.assertFalse(ensure_day("2026-09-01", self.feed, build))
        self.assertEqual(before, self.feed.read_bytes())
        build.assert_not_called()

    def test_failed_or_invalid_recovery_does_not_replace_source(self):
        self.seed([devotion("2026-08-31")])
        before = self.feed.read_bytes()
        for build in [Mock(side_effect=RuntimeError("generation failed")),
                      Mock(return_value={"date": "2026-09-01"}),
                      Mock(return_value=devotion("2026-09-03"))]:
            with self.assertRaises((RuntimeError, ValueError)):
                ensure_day("2026-09-01", self.feed, build)
            self.assertEqual(before, self.feed.read_bytes())

    def test_invalid_existing_source_never_triggers_regeneration(self):
        for content in ["broken", "{}", json.dumps([devotion(), devotion()])]:
            self.feed.write_text(content, encoding="utf-8")
            build = Mock()
            with self.assertRaises(ValueError):
                ensure_day("2026-09-01", self.feed, build)
            self.assertEqual(content, self.feed.read_text(encoding="utf-8"))
            build.assert_not_called()

    def test_missing_file_can_be_recovered_after_valid_generation(self):
        ensure_day("2026-09-01", self.feed, Mock(return_value=devotion()))
        self.assertEqual(read_array(self.feed), [devotion()])

    def test_local_saint_wins_even_when_live_copy_is_offline(self):
        with patch.object(saints_feed, "remote_records", side_effect=OSError("offline")) as remote:
            self.assertEqual(saints_feed.select_saint("2026-09-01", self.saints), saint())
            remote.assert_not_called()

    def test_missing_local_record_uses_complete_live_copy(self):
        self.saints.write_text("[]", encoding="utf-8")
        with patch.object(saints_feed, "remote_records", return_value={"2026-09-01": saint()}) as remote:
            self.assertEqual(saints_feed.select_saint("2026-09-01", self.saints), saint())
            remote.assert_called_once()

    def test_incomplete_local_and_offline_remote_stop_publication(self):
        for bad in [[], [dict(saint(), profile="")], [dict(saint(), profile="Feast day of Saint Test.")]]:
            self.saints.write_text(json.dumps(bad), encoding="utf-8")
            with patch.object(saints_feed, "remote_records", side_effect=OSError("offline")):
                with self.assertRaisesRegex(ValueError, "publication stopped"):
                    saints_feed.select_saint("2026-09-01", self.saints)

    def test_daily_prepares_exact_profile_cycles_aliases_and_tags(self):
        row = devotion()
        row.update(cycle="Year B", saintReflection="outdated")
        row.pop("gospelReference")
        before = copy.deepcopy(row)
        with patch.object(saints_feed, "SAINT_PATH", self.saints), patch.object(saints_feed, "remote_records") as remote:
            prepared = daily.prepare_entry(row)
        validate_rows([prepared])
        self.assertEqual(prepared["saintReflection"], saints_feed.reflection(saint()))
        self.assertEqual(prepared["cycle"], "Year A")
        self.assertEqual(prepared["gospelReference"], row["gospelRef"])
        self.assertIn("saint-test", prepared["tags"])
        self.assertEqual(row, before)
        remote.assert_not_called()

    def run_daily(self, row, dry=False):
        self.seed([row])
        argv = ["update_daily_devotion.py", "--date", "2026-09-01", "--skip-dist"]
        if dry:
            argv.append("--dry-run")
        with patch.object(sys, "argv", argv), patch.object(daily, "WEEKLY_PATH", self.feed), \
             patch.object(daily, "PUBLIC_TARGET", self.root / "devotions.json"), \
             patch.object(daily, "ARCHIVE_DIR", self.root / "archive"), \
             patch.object(daily, "INDEX_PATH", self.root / "archive/index.json"), \
             patch.object(saints_feed, "SAINT_PATH", self.saints), \
             patch.object(saints_feed, "remote_records", side_effect=AssertionError("must not fetch")), \
             redirect_stdout(io.StringIO()):
            daily.main()

    def test_daily_validation_failure_writes_neither_feed_nor_archive(self):
        row = devotion()
        row["quote"] = ""
        with self.assertRaises(ValueError):
            self.run_daily(row)
        self.assertFalse((self.root / "devotions.json").exists())
        self.assertFalse((self.root / "archive").exists())

    def test_daily_writes_matching_feed_archive_and_index(self):
        self.run_daily(devotion())
        live = read_array(self.root / "devotions.json")[0]
        archive = json.loads((self.root / "archive/2026/09/2026-09-01.json").read_text(encoding="utf-8"))
        index = read_array(self.root / "archive/index.json")
        self.assertEqual(live, archive)
        self.assertEqual(index[0]["cycle"], "Year A")
        self.assertEqual(index[0]["date"], "2026-09-01")

    def test_daily_dry_run_writes_nothing(self):
        self.run_daily(devotion(), dry=True)
        self.assertFalse((self.root / "devotions.json").exists())
        self.assertFalse((self.root / "archive").exists())

    def test_damaged_archive_index_does_not_get_replaced(self):
        archive = self.root / "archive"
        archive.mkdir()
        (archive / "index.json").write_text("broken", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.run_daily(devotion())
        self.assertFalse((self.root / "devotions.json").exists())
        self.assertEqual((archive / "index.json").read_text(), "broken")

    def test_weekly_generation_uses_local_saint_and_validates_ai_result(self):
        with patch.object(saints_feed, "SAINT_PATH", self.saints), \
             patch.object(generate_weekly, "fetch_saint_online", side_effect=AssertionError("unreviewed source")), \
             patch.object(generate_weekly, "resolve_readings", return_value=("1 Corinthians 2:10b-16", "", "Psalm 145:8-9", "Luke 4:31-37")), \
             patch.object(generate_weekly, "openai_client", return_value=object()), \
             patch.object(generate_weekly, "gen_json", return_value=devotion()):
            result = generate_weekly.build_day_payload(date(2026, 9, 1))
        self.assertEqual(result["saintReflection"], saints_feed.reflection(saint()))
        validate_rows([result])

    def test_invalid_weekly_result_never_overwrites_source(self):
        self.seed([devotion()])
        before = self.feed.read_bytes()
        with patch.dict(generate_weekly.os.environ, {"START_DATE": "2026-10-01", "DAYS": "1", "USCCB_PRECHECK": "0"}), \
             patch.object(generate_weekly, "saint_for_date", return_value=saint("2026-10-01")), \
             patch.object(generate_weekly, "build_day_payload", return_value={"date": "2026-10-01"}), \
             patch.object(generate_weekly.time, "sleep"), patch.object(generate_weekly, "write_json") as write:
            with self.assertRaises(ValueError):
                generate_weekly.main()
            write.assert_not_called()
        self.assertEqual(self.feed.read_bytes(), before)


class SDKTests(unittest.TestCase):
    def test_installed_sdk_json_generation_and_temperature_retry_without_network(self):
        import httpx2
        from openai import OpenAI
        requests = []

        def respond(request):
            body = json.loads(request.content)
            requests.append(body)
            if "temperature" in body:
                return httpx2.Response(400, json={"error": {"message": "Unsupported temperature", "type": "invalid_request_error"}})
            return httpx2.Response(200, json={"id": "offline-test", "object": "chat.completion", "created": 0,
                "model": "gpt-5-mini", "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": '{"verified": true}'}}]})

        with OpenAI(api_key="offline-test-only", http_client=httpx2.Client(transport=httpx2.MockTransport(respond))) as client, \
             patch.object(generate_weekly, "GEN_MODEL", "gpt-5-mini"):
            self.assertEqual(generate_weekly.gen_json(client, "test", ["test"], 1), {"verified": True})
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0]["response_format"], {"type": "json_object"})
        self.assertNotIn("temperature", requests[1])

        requests.clear()
        with OpenAI(api_key="offline-test-only", http_client=httpx2.Client(transport=httpx2.MockTransport(respond))) as client, \
             patch.object(generate_weekly, "GEN_MODEL", "gpt-5.6-terra"):
            self.assertEqual(generate_weekly.gen_json(client, "test", ["test"], 1), {"verified": True})
        self.assertEqual(len(requests), 1)
        self.assertNotIn("temperature", requests[0])


class ValidationTests(unittest.TestCase):
    def test_rejects_empty_duplicate_wrong_type_and_invalid_date_feeds(self):
        for rows in [[], {}, [devotion(), devotion()], [dict(devotion(), date="2026-02-30")],
                     [dict(devotion(), quote=None)], [dict(devotion(), date="2026-9-1")]]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                validate_rows(rows)

    def test_rejects_empty_text_bad_refs_alias_mismatch_cycles_and_absent_saint_claims(self):
        cases = [{"quote": " "}, {"gospelRef": "Psalms 23:1"}, {"gospelReference": "John 1:1"},
                 {"firstReadingRef": "Corinthians 2:10"}, {"secondReading": "Unexpected text"},
                 {"cycle": "Year B"}, {"exegesis": "Saints: Although no particular saint is named today."}]
        for update in cases:
            with self.subTest(update=update), self.assertRaises(ValueError):
                validate_rows([dict(devotion(), **update)])

    def test_whitespace_in_valid_citation_is_accepted(self):
        validate_rows([dict(devotion(), gospelRef="Luke 4: 31-37", gospelReference="Luke 4: 31-37")])

    def test_readiness_requires_every_day_and_substantial_single_paragraph(self):
        rows = [saint(f"2026-09-{d:02d}") for d in range(1, 31)]
        self.assertEqual(saints_feed.month_readiness(rows, "2026-09"), [])
        rows[14]["profile"] = ""
        rows.pop()
        self.assertEqual(saints_feed.month_readiness(rows, "2026-09"), ["2026-09-15", "2026-09-30"])
        with self.assertRaises(ValueError):
            saints_feed.month_readiness([saint(), saint()], "2026-09")

    def test_readiness_handles_leap_february(self):
        rows = [saint(f"2028-02-{d:02d}") for d in range(1, 30)]
        self.assertEqual(saints_feed.month_readiness(rows, "2028-02"), [])

    def test_missing_feed_validation_cli_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run([sys.executable, "-m", "scripts.validate_publication", str(Path(folder) / "missing.json")],
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)

    def test_scraper_keeps_numbered_book_ordinal(self):
        html = "<p>First Reading: First Corinthians 2: 10b-16</p><p>Responsorial Psalm: Psalms 145: 8-9</p><p>Gospel: Luke 4: 31-37</p>"
        response = Mock(text=html)
        with patch.object(generate_weekly.requests, "get", return_value=response):
            result = generate_weekly.fetch_readings_catholicgallery(date(2026, 9, 1))
        self.assertEqual(result[0], "1 Corinthians 2: 10b-16")


if __name__ == "__main__":
    unittest.main()
