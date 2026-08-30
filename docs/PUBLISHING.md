# Publishing and maintenance runbook

## Production contract

GitHub `DailyLectio/calm`, branch `main`, is the production source. Vercel serves its `public/` files; LectioLinks/Framer consumes those feeds. Changing Git JSON does not edit the Framer Archives component. No future-day test may replace today's public devotion or archive.

| Work | Eastern schedule / behavior |
| --- | --- |
| Weekly preparation | Thursday 03:05, upcoming Friday–Thursday |
| Daily publication | 03:35 primary; 04:35 intentional retry; after successful weekly run |
| Service target | Today's verified live post by 06:00 |
| GitHub health monitor | 06:00, then 07:17–23:17 hourly; after writer runs and relevant pushes |
| Reviewed saints readiness | Existing 20th–31st check; health monitor also checks next month from the 20th |
| Monthly drafts | Existing monthly/manual draft workflow; editorial review required before append |

Daily/weekly/health schedules explicitly use `America/New_York`, including daylight-saving changes. These are operating targets, not guarantees: [GitHub can delay or drop scheduled runs](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule). A monitor on the same scheduler cannot alone guarantee detection of that scheduler's outage. A separate desktop check requires an available PC/app/network; it is not an always-on external monitoring service.

## Prepare once, safely publish against fresh main

1. Preparation validates the existing rolling feed, retains reviewed overlapping dates and preflights saints for every missing day before making paid generation calls. Both models remain `gpt-5-mini`. The explicit start date takes precedence; a blank weekly start selects this week's Friday (upcoming Monday–Thursday, most recent Friday–Sunday). A delay into a new week selects that new week's release; the daily fallback handles a missing current day.
2. A validated candidate containing the base commit, target window and only newly generated rows is retained as an Actions artifact for 30 days. Preparation never edits production. A generation failure before a complete candidate is produced stops the run; partial AI output is not published.
3. Daily and weekly **publish jobs** share `production-feed-writer`, with cancellation disabled and [`queue: max`](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency). The queue supports up to 100 pending jobs; it is not an unlimited durable queue. Generation does not hold the short writer lock.
4. The publisher fetches current `main` into its own temporary worktree and semantically merges the prepared rows. Existing records, unrelated operator edits and historical archives are preserved. A conflicting edit to the same date or a changed reviewed saint blocks publication for review. Reapplying an identical artifact is a no-op.
5. Daily publication derives only today's output and matching current snapshot/index entry. It checks the date before work and immediately before pushing, refusing a job that crossed Eastern midnight. Future dates remain in the rolling source only.
6. The final feed is validated, only the intended data files are staged, and a normal non-forced push is attempted. If main moved, the publisher refetches and repeats the merge/validation up to three times; it does **not** repeat paid generation. Authentication/policy failures stop immediately rather than masquerading as races. Temporary worktrees are cleaned up; the prepared Actions artifact remains available.

For a transient publish-only failure, use **Re-run failed jobs**, retaining the successful prepare job's artifact. Do not choose **Re-run all jobs** unnecessarily. Inspect any same-date conflict; never force-push or blindly replace the current record. A local operator may download the artifact to ignored `artifacts/candidate.json`, review its base/date/rows, and run the commands below against the correct repo. Daily artifacts are usable only on their actual date. Weekly artifacts must retain a base commit reachable from current main.

```powershell
git fetch origin
git status --short --branch
git pull --ff-only
.\.venv\Scripts\python.exe -m scripts.publish_feed --mode weekly --candidate artifacts/candidate.json
```

`python -m scripts.generate_weekly` remains a local/manual source generator, now preserving existing dates too. It is not a coordinated remote publisher. Prefer Actions for unattended work and the candidate publisher for remote writes.

## Health checks and incident routing

The monitor pins one current GitHub main SHA, then checks both `dailylectio.org` and `www.dailylectio.org`. It verifies JSON/schema, correct cycle labels, nonempty required content, exactly one permitted daily date, the exact reviewed saint profile, daily/weekly reflection agreement, complete prepared coverage, full live-file equality to Git (including same-date corrections), and the current dated snapshot/index agreement. Thursday's 06:00 check additionally requires the next Friday–Thursday release. Before 06:00, yesterday may remain live; future dates are never accepted. From the 20th, missing reviewed saints in the next month raise a readiness incident.

Deployment convergence is retried up to eight times, 25 seconds apart. Errors stay visible in Actions even after the alert is routed. Reports are retained as 30-day artifacts. No feed or historic record is modified by health checks.

Default destination: a deduplicated issue in this repository assigned to `DailyLectio`. Set `PUBLICATION_HEALTH_ASSIGNEE` to another valid repository assignee when approved. Identical failures do not spam comments. Verified recovery comments and closes the monitor's own issue only. Run **Publication Health → Run workflow → alert_test=true** to create and close a clearly labelled synthetic routing test. Confirm delivery in the recipient's GitHub notification settings; successful assignment is not proof of email/push receipt. An Actions outage can also prevent GitHub-hosted alerts. No paid monitoring, email address or webhook destination is assumed.

Read-only manual verification (no OpenAI key needed):

```powershell
.\.venv\Scripts\python.exe -m scripts.check_live_publication --remote-baseline
```

The `--remote-baseline` option avoids comparing against an obsolete local checkout. This tests the data-host boundary, not whether a Framer component has refreshed its browser cache. Archives/Framer repair and project consolidation remain separate work.

## Credentials, Git and future gates

Both publishing jobs explicitly check out using the short-lived `GITHUB_TOKEN` and push to `origin`. The old `GH_PAT` failed the August 30 authentication test and is no longer used by active workflows; the secret was not copied, replaced or deleted. Never paste credentials into commands, remote URLs, reports or Git. Generation jobs have read-only repository permission; publisher jobs have content-write plus Actions-write solely to dispatch validation; health has issue-write but no content-write permission.

**Verify Publishing Identity** checks authenticated repository access and Git transport using the job-scoped `github-actions[bot]` token. Its optional manual `publish_probe` makes an explicitly requested empty commit and non-forced push, testing actual write permission without changing any file or published date. It shares the writer queue. A dry run alone does not prove acceptance of a future protection rule.

GitHub [does not trigger ordinary push Actions from `GITHUB_TOKEN` pushes](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow), so publishers explicitly dispatch Validate Publication after success. This dispatch is permitted for workflow tokens. The health workflow also runs on publisher completion and its independent schedules. Vercel Git integration handles deployment separately; confirm its checks and live content, not just the Actions result. No new branch rule, reviewer requirement, bypass or Vercel promotion gate has been imposed. Those need an agreed human/editorial versus routine-bot PR policy and correct platform access. Require another smoke test after any policy change.

The maintained Windows checkout is `C:\Users\Valued Customer\calm-work`; this repair was prepared in the linked `calm-september-2026` worktree. Native Git Credential Manager authentication is configured locally for `DailyLectio`. Use `git pull --ff-only` before work and a normal non-forced push after validation. If the worktree is dirty or diverged, inspect and preserve it before reconciling—never reset it to discard work.

On August 30, old unique work was retained on local `recovery/*-2026-08-30` branches and in `C:\Users\Valued Customer\calm-recovery-2026-08-30`, including a verified Git bundle and byte-identical copies of all eight dirty files. Those recovery refs were not pushed. Unreviewed model upgrades and historical content changes remain there for separate review; they were not reinstated in production. A portable Windows date-format fix was selectively adopted and regression-tested. See the local recovery manifest for exact commit IDs and hashes.

## Reproducible maintenance checks

Use Python 3.11+ (CI: 3.11; Windows repair checks: 3.12). Create a local ignored environment and install the shared manifests:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-devotions.txt
.\.venv\Scripts\python.exe -m scripts.check_maintenance
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m scripts.validate_publication
.\.venv\Scripts\python.exe -m scripts.check_saints_readiness --month 2026-09
git diff --check
```

`requirements-saints.txt` supplies pinned direct saints dependencies; `requirements-devotions.txt` includes it and the pinned SDK, schema validator and YAML test dependency. Transitive packages still resolve under those packages' constraints; this is not a fully hash-locked environment. Review dependency upgrades together with CI, the SDK mock tests and retained deployment builds.

With that Python environment activated, root `npm test` runs the same real maintenance/regression/feed checks, not the old success-only placeholder. It is **not** a mobile/UI/build test. The suite uses isolated temporary local bare Git remotes to test actual concurrent pushes and cleanup; it makes no paid generation calls and does not publish test feeds. Syntax checks cover tracked Python; stage new scripts before the final check.

The retired archive builder and two dormant workflows are non-executable `.txt` references under `docs/retired`. Existing nested workflow backups remain inactive. Root template/mobile dependencies and build commands are retained until both Vercel projects' settings and mobile consumers are mapped. Do not infer that a dependency is unused merely from a successful JSON request.

Generated Python bytecode is ignored and must not be tracked. The previously committed `scripts/__pycache__/generate_weekly.cpython-312.pyc` was removed from Git tracking (not erased from the working PC) after a test run exposed the stale tracked cache. Maintenance checks reject future tracked bytecode. Its prior version remains recoverable in Git history.

The separate desktop automation **LectioLinks daily publication check** was configured in the maintenance chat for 06:10 Eastern. It runs the read-only checker with the current remote baseline and reports here, independently of GitHub's scheduler. It still depends on this PC, app and internet connection being available and uses the account's normal automation capacity; no paid third-party monitor was added.
