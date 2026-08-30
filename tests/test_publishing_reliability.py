"""Offline tests, including real Git races against an isolated local bare remote."""
import copy
from datetime import date, datetime
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo
import yaml
from test_publication import devotion, saint
from scripts.feed_io import write_json, read_array
from scripts import check_live_publication as health
from scripts import publish_feed as publisher, generate_weekly
from scripts.prepare_publication import prepare, release_friday
from scripts.report_publication_health import MARKER, TITLE, report_health
from scripts.dispatch_validation import dispatch
from scripts.saints_feed import reflection

ROOT = Path(__file__).resolve().parents[1]


def row(day):
    return dict(devotion(day), saintReflection=reflection(saint(day)))


def candidate(rows, targets=None, sha="a" * 40):
    return {"version": 1, "baseSha": sha, "rows": rows,
            "targetDates": targets or [r["date"] for r in rows]}


class MergeTests(unittest.TestCase):
    def test_append_keeps_past_current_and_reviewed_future_content(self):
        old = [row("2026-08-31"), row("2026-09-01"), row("2026-09-03")]
        result = publisher.merge_rows(old, old, candidate([row("2026-09-02")]))
        self.assertEqual([result[0], result[1], result[3]], old)

    def test_unchanged_retry_is_idempotent(self):
        new = row("2026-09-02")
        old = [row("2026-09-01")]
        self.assertEqual(publisher.merge_rows(old + [new], old, candidate([new])), old + [new])

    def test_existing_reviewed_date_cannot_be_regenerated(self):
        old = [row("2026-09-01")]
        with self.assertRaisesRegex(ValueError, "replace an existing"):
            publisher.merge_rows(old, old, candidate(old))

    def test_concurrent_different_same_date_requires_review(self):
        with self.assertRaisesRegex(ValueError, "concurrent content conflict"):
            publisher.merge_rows([dict(row("2026-09-01"), quote="Other reviewed quote")], [], candidate([row("2026-09-01")]))

    def test_missing_duplicate_invalid_and_out_of_window_dates_fail(self):
        for value in [candidate([], ["2026-09-01"]), candidate([row("2026-09-02")], ["2026-09-01"]),
                      candidate([row("2026-09-01")] * 2), candidate([], ["2026-09-01", "2026-09-03"])]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                publisher.merge_rows([], [], value)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            publisher.merge_rows([row("2026-09-01")] * 2, [], candidate([], ["2026-09-01"]))

    def test_release_date_handles_advance_generation_and_weekend_delay(self):
        for day in ("2026-09-03", "2026-09-04", "2026-09-05", "2026-09-06"):
            self.assertEqual(release_friday(date.fromisoformat(day)), date(2026, 9, 4))
        self.assertEqual(release_friday(date(2026, 12, 31)), date(2027, 1, 1))
        self.assertEqual(release_friday(date(2027, 1, 2)), date(2027, 1, 1))
        self.assertEqual(release_friday(date(2026, 9, 30)), date(2026, 10, 2))

    def test_ewtn_date_format_is_portable_to_windows(self):
        response = Mock(text="<p>September 1</p>")
        with patch.object(generate_weekly.requests, "get", return_value=response), \
             patch.object(generate_weekly, "parse_usccb_dom", return_value=("", "", "", "")) as parse:
            generate_weekly.fetch_readings_ewtn(date(2026, 9, 1))
        parse.assert_called_once_with("September 1", sunday=False)

    def test_manual_weekly_generator_preserves_existing_records(self):
        existing = [row("2026-08-31"), row("2026-09-01")]
        with patch.dict(generate_weekly.os.environ, {"START_DATE": "2026-09-01", "DAYS": "2", "USCCB_PRECHECK": "0"}), \
             patch.object(generate_weekly, "read_array", return_value=existing), \
             patch.object(generate_weekly, "saint_for_date", return_value=saint("2026-09-02")), \
             patch.object(generate_weekly, "build_day_payload", return_value=row("2026-09-02")) as build, \
             patch.object(generate_weekly.time, "sleep"), patch.object(generate_weekly, "write_json") as write:
            generate_weekly.main()
        build.assert_called_once_with(date(2026, 9, 2))
        self.assertEqual(write.call_args.args[1], existing + [row("2026-09-02")])


class GitPublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lectiolinks-test-")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.remote, self.seed, self.runner = (self.folder / x for x in ("remote.git", "seed", "runner"))
        publisher.git(self.folder, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.seed.mkdir()
        publisher.git(self.seed, "init", "--initial-branch=main")
        for folder in ("scripts", "schemas"):
            shutil.copytree(ROOT / folder, self.seed / folder, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(ROOT / "update_daily_devotion.py", self.seed / "update_daily_devotion.py")
        write_json(self.seed / "public/weeklyfeed.json", [row("2026-08-31"), row("2026-09-01")])
        write_json(self.seed / "public/saint.json", [saint(f"2026-09-{d:02}") for d in range(1, 5)] + [saint("2026-08-31")])
        write_json(self.seed / "public/devotions.json", [row("2026-08-31")])
        write_json(self.seed / "public/past_reflections/index.json", [])
        self.commit(self.seed, "fixture")
        publisher.git(self.seed, "remote", "add", "origin", str(self.remote))
        publisher.git(self.seed, "push", "-u", "origin", "main")
        publisher.git(self.folder, "clone", str(self.remote), str(self.runner))
        self.sha = publisher.git(self.runner, "rev-parse", "HEAD").stdout.strip()

    def commit(self, root, message):
        publisher.git(root, "add", ".")
        publisher.git(root, "-c", "user.name=Offline Test", "-c", "user.email=test@example.invalid", "commit", "-m", message)

    def published(self, path="public/weeklyfeed.json"):
        return json.loads(publisher.git(self.remote, "show", "main:" + path).stdout)

    def test_prepare_skips_existing_dates_without_rewriting_or_paid_calls(self):
        build = Mock(return_value=row("2026-09-02"))
        before = (self.runner / "public/weeklyfeed.json").read_bytes()
        value = prepare(date(2026, 9, 1), 2, self.runner, build)
        self.assertEqual(value["rows"], [row("2026-09-02")])
        build.assert_called_once_with(date(2026, 9, 2))
        self.assertEqual((self.runner / "public/weeklyfeed.json").read_bytes(), before)
        build.reset_mock()
        self.assertEqual(prepare(date(2026, 9, 1), 1, self.runner, build)["rows"], [])
        build.assert_not_called()

    def test_whole_window_saints_preflight_precedes_paid_generation(self):
        build = Mock()
        with patch("scripts.saints_feed.remote_records", side_effect=OSError("offline")):
            with self.assertRaisesRegex(ValueError, "publication stopped"):
                prepare(date(2026, 9, 2), 7, self.runner, build)
        build.assert_not_called()

    def test_real_git_race_preserves_other_writer_without_regenerating(self):
        value = candidate([row("2026-09-02")], sha=self.sha)
        def other_writer(attempt):
            if attempt == 0:
                original = read_array(self.seed / "public/weeklyfeed.json")
                write_json(self.seed / "public/weeklyfeed.json", original + [row("2026-09-03")])
                (self.seed / "editor-note.txt").write_text("Preserve editorial work", encoding="utf-8")
                self.commit(self.seed, "concurrent editorial update")
                publisher.git(self.seed, "push", "origin", "main")
        with patch.object(publisher.time, "sleep"):
            publisher.publish(value, "weekly", self.runner, before_push=other_writer)
        self.assertEqual([r["date"] for r in self.published()], ["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03"])
        self.assertEqual(publisher.git(self.remote, "show", "main:editor-note.txt").stdout, "Preserve editorial work")
        self.assertEqual(publisher.git(self.runner, "status", "--porcelain").stdout, "")
        self.assertEqual(publisher.git(self.runner, "worktree", "list", "--porcelain").stdout.count("worktree "), 1)
        # Repeating the exact artifact performs no commit.
        head = publisher.git(self.remote, "rev-parse", "main").stdout.strip()
        self.assertEqual(publisher.publish(value, "weekly", self.runner), head)

    def test_changed_reviewed_saint_blocks_stale_candidate(self):
        saints = read_array(self.seed / "public/saint.json")
        saints[1]["profile"] += " Additional reviewed teaching."
        write_json(self.seed / "public/saint.json", saints)
        self.commit(self.seed, "saint editorial change")
        publisher.git(self.seed, "push", "origin", "main")
        with self.assertRaisesRegex(ValueError, "reviewed saint changed"):
            publisher.publish(candidate([row("2026-09-02")], sha=self.sha), "weekly", self.runner)
        self.assertEqual(len(self.published()), 2)

    def test_daily_publishes_matching_today_feed_archive_and_index(self):
        value = candidate([], ["2026-09-01"], self.sha)
        publisher.publish(value, "daily", self.runner, today="2026-09-01")
        daily = self.published("public/devotions.json")[0]
        self.assertEqual(daily["date"], "2026-09-01")
        self.assertEqual(self.published("public/past_reflections/2026/09/2026-09-01.json"), daily)
        self.assertEqual(self.published("public/past_reflections/index.json")[0]["date"], daily["date"])
        search = self.published("public/past_reflections/search-v1.json")
        self.assertEqual(search["entries"][0]["date"], daily["date"])
        self.assertEqual(search["entries"][0]["synthesis"], daily["theologicalSynthesis"])
        self.assertEqual(len(self.published()), 2)

    def test_daily_future_or_midnight_crossing_never_pushes(self):
        value = candidate([], ["2026-09-01"], self.sha)
        with self.assertRaisesRegex(ValueError, "crossed midnight"):
            publisher.publish(value, "daily", self.runner, today="2026-08-31")
        with patch.object(publisher, "datetime") as clock:
            clock.now.side_effect = [datetime(2026, 9, 1, 23, 59), datetime(2026, 9, 2, 0, 0)]
            with self.assertRaisesRegex(ValueError, "crossed midnight"):
                publisher.publish(value, "daily", self.runner)
        self.assertEqual(publisher.git(self.remote, "rev-parse", "main").stdout.strip(), self.sha)


class HealthTests(unittest.TestCase):
    def test_missing_browser_cors_permission_is_not_a_healthy_json_response(self):
        response = Mock(headers={"Content-Type": "application/json"})
        with patch.object(health.requests, "get", return_value=response):
            with self.assertRaisesRegex(ValueError, "CORS"):
                health.fetch_json("https://dailylectio.org/devotions.json")

    def setUp(self):
        self.now = datetime(2026, 9, 1, 6, tzinfo=ZoneInfo("America/New_York"))
        self.expected = {"devotions.json": [row("2026-09-01")],
                         "weeklyfeed.json": [row(f"2026-09-{d:02}") for d in range(1, 4)],
                         "saint.json": [saint(f"2026-09-{d:02}") for d in range(1, 4)],
                         "past_reflections/search-v1.json": {"schemaVersion": 1, "revision": "offline-fixture"}}
        self.live = {f"https://test/{key}": copy.deepcopy(value) for key, value in self.expected.items()}
        self.live["https://test/past_reflections/2026/09/2026-09-01.json"] = row("2026-09-01")
        self.live["https://test/past_reflections/index.json"] = [dict(row("2026-09-01"), path="/past_reflections/2026/09/2026-09-01.json")]

    def check(self):
        return health.inspect(self.expected, self.now, self.live.__getitem__, hosts=["https://test"])

    def test_healthy_full_content_and_archive(self):
        self.assertEqual(self.check()["date"], "2026-09-01")

    def test_http_200_same_date_stale_content_fails(self):
        self.live["https://test/devotions.json"][0]["quote"] = "Stale content"
        with self.assertRaisesRegex(ValueError, "same-date edits"):
            self.check()

    def test_current_date_with_wrong_profile_fails(self):
        self.expected["devotions.json"][0]["saintReflection"] = "An obsolete profile."
        with self.assertRaisesRegex(ValueError, "reviewed profile"):
            self.check()

    def test_thursday_requires_advance_week_at_deadline(self):
        self.now = datetime(2026, 9, 3, 6, tzinfo=self.now.tzinfo)
        self.expected["devotions.json"] = [row("2026-09-03")]
        with self.assertRaisesRegex(ValueError, "prepared dates"):
            self.check()

    def test_stale_date_after_deadline_and_future_date_fail(self):
        for day in ("2026-08-31", "2026-09-02"):
            self.expected["devotions.json"] = [row(day)]
            with self.assertRaisesRegex(ValueError, "06:00 Eastern deadline"):
                self.check()

    def test_previous_day_allowed_only_before_deadline(self):
        self.now = datetime(2026, 9, 2, 5, 59, tzinfo=self.now.tzinfo)
        self.assertEqual(self.check()["date"], "2026-09-01")
        self.now = self.now.replace(hour=6)
        with self.assertRaisesRegex(ValueError, "06:00 Eastern deadline"):
            self.check()

    def test_archive_mismatch_fails(self):
        self.live["https://test/past_reflections/2026/09/2026-09-01.json"]["exegesis"] = "Old text"
        with self.assertRaisesRegex(ValueError, "snapshot differs"):
            self.check()

    def test_missing_or_duplicate_index_entry_fails(self):
        self.live["https://test/past_reflections/index.json"] *= 2
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.check()

    def test_remote_baseline_pins_all_files_to_one_sha(self):
        sha = "b" * 40
        fetch = Mock(side_effect=[{"sha": sha}, [], [], [], {}])
        self.assertEqual(health.baseline(True, fetch=fetch)[0], sha)
        for call in fetch.call_args_list[1:]:
            self.assertIn("/" + sha + "/public/", call.args[0])

    def test_stale_search_revision_fails_live_health(self):
        self.live["https://test/past_reflections/search-v1.json"]["revision"] = "stale"
        with self.assertRaisesRegex(ValueError, "same-date edits"):
            self.check()


class AlertTests(unittest.TestCase):
    def test_failure_creates_assigned_incident(self):
        api = Mock()
        api.call.side_effect = [[], None, {"html_url": "https://github.test/1"}]
        self.assertEqual(report_health(api, {"ok": False, "error": "stale"}, "run"), "https://github.test/1")
        self.assertEqual(api.call.call_args.args[2]["assignees"], ["DailyLectio"])

    def test_repeated_identical_failure_does_not_spam(self):
        body = f"{MARKER}\n<!-- failure:{health.fingerprint('stale')} -->"
        api = Mock()
        api.call.return_value = [{"number": 1, "title": TITLE, "user": {"login": "github-actions[bot]"}, "body": body, "html_url": "url"}]
        report_health(api, {"ok": False, "error": "stale"}, "run")
        self.assertEqual(api.call.call_count, 1)

    def test_recovery_closes_only_owned_incident(self):
        api = Mock()
        api.call.side_effect = [[{"number": 8, "title": TITLE, "body": MARKER, "user": {"login": "some-user"}},
                                {"number": 9, "title": TITLE, "body": MARKER, "user": {"login": "github-actions[bot]"}}], {}, {}]
        report_health(api, {"ok": True}, "run")
        api.call.assert_called_with("PATCH", "issues/9", {"state": "closed"})

    def test_notification_test_is_explicit_and_closed(self):
        api = Mock()
        api.call.side_effect = [None, {"number": 5, "html_url": "test-url"}, {}]
        report_health(api, {"ok": True}, "run", test=True)
        api.call.assert_called_with("PATCH", "issues/5", {"state": "closed"})


class WorkflowTests(unittest.TestCase):
    def test_monthly_saints_workflow_is_manual_only(self):
        flow = self.workflow("generate-saints-monthly.yml")
        self.assertEqual(set(flow["on"]), {"workflow_dispatch"})
        self.assertEqual(flow["jobs"]["saints-monthly"]["permissions"], {"contents": "read"})

    def test_generated_python_bytecode_is_not_tracked(self):
        tracked = publisher.git(ROOT, "ls-files", "*__pycache__*", "*.pyc", "*.pyo").stdout
        self.assertEqual(tracked, "")

    def test_explicit_dispatch_uses_workflow_token_without_putting_it_in_url(self):
        session = Mock()
        dispatch("offline-test-token", "DailyLectio/calm", session)
        url = session.post.call_args.args[0]
        self.assertNotIn("offline-test-token", url)
        self.assertEqual(session.post.call_args.kwargs["json"], {"ref": "main"})
        session.post.return_value.raise_for_status.assert_called_once()

    def workflow(self, name):
        # BaseLoader keeps YAML 1.1's 'on' and booleans as strings, matching Actions keys.
        return yaml.load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    def test_daily_and_weekly_have_one_shared_noncancelling_writer_queue(self):
        for name in ("daily-devotion-update.yml", "generate-weekly.yml"):
            flow = self.workflow(name)
            queue = flow["jobs"]["publish"]["concurrency"]
            self.assertEqual(queue, {"group": "production-feed-writer", "queue": "max", "cancel-in-progress": "false"})
            self.assertEqual(flow["jobs"]["publish"]["needs"], "prepare")
            self.assertEqual(flow["jobs"]["publish"]["permissions"], {"contents": "write", "actions": "write"})
            self.assertNotIn("GH_PAT", json.dumps(flow))
            self.assertTrue(all(s["timezone"] == "America/New_York" for s in flow["on"]["schedule"]))

    def test_validation_runs_even_for_documentation_only_pull_requests(self):
        flow = self.workflow("validate-publication.yml")
        self.assertEqual(flow["on"]["pull_request"], {})
        self.assertNotIn("paths", flow["on"]["push"])

    def test_retired_files_are_non_executable_and_conflict_markers_absent(self):
        self.assertFalse((ROOT / "scripts/build_archive.py").exists())
        self.assertTrue((ROOT / "docs/retired/build_archive.py.txt").exists())
        self.assertNotIn("<<<<<<<", (ROOT / ".gitignore").read_text())


if __name__ == "__main__":
    unittest.main()
