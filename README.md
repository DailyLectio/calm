# Daily Lectio Data Site

This repository publishes the JSON feeds used by the Daily Lectio website and connected mobile/front-end clients. Vercel serves files from `public/` at the site root, so `public/devotions.json` becomes `/devotions.json`, `public/weeklyfeed.json` becomes `/weeklyfeed.json`, and `public/saint.json` becomes `/saint.json`.

## Live JSON Feeds

- `public/devotions.json` is the daily live devotion feed. It is generated from the weekly feed by `update_daily_devotion.py`.
- `public/weeklyfeed.json` is the rolling source feed for daily Scripture reflections. Each entry uses a `date` field in `YYYY-MM-DD` format plus reflection fields such as `quote`, `firstReading`, `psalmSummary`, `gospelSummary`, `saintReflection`, `dailyPrayer`, `theologicalSynthesis`, `exegesis`, tags, reading references, and source links.
- `public/saint.json` is the current saint reflection feed. It is an array of daily records with `date`, `saintName`, `memorial`, `source`, `saintAlt1`, `saintAlt2`, `profile`, and `link`.
- `public/past_reflections/` stores archived daily devotion snapshots by year/month/date, with `public/past_reflections/index.json` as the archive index.
- `public/archive/` and `public/feeds/` hold legacy and generated feed artifacts used for backups, testing, or older clients.

## Automation

- `.github/workflows/daily-devotion-update.yml` prepares today's Eastern-calendar date at 03:35, retries at 04:35, and also runs after successful weekly preparation/publication. It generates only a missing source day. A separate queued publisher validates and merges against fresh `main`, then commits the source, daily feed, and current archive together.
- `.github/workflows/generate-weekly.yml` prepares the upcoming Friday–Thursday window on Thursday at 03:05 Eastern. It retains all existing dates and reviewed overlaps. Both generators retain their existing `gpt-5-mini` model settings.
- `.github/workflows/generate-saints-monthly.yml` runs monthly or manually to create review-only calendar drafts with `scripts/generate_saints.py`. It never changes the published saints file. Drafts are retained as GitHub Actions artifacts for 30 days.
- `.github/workflows/check-saints-readiness.yml` checks the next complete month on the 20th through the 31st, or a manually selected month. Missing or incomplete days fail visibly in Actions; notification delivery depends on the repository/user's GitHub notification settings.
- `.github/workflows/validate-publication.yml` checks maintained Python syntax, conflict markers, regression tests and published/rolling feeds on every `main` push and every pull request, including documentation-only changes. In-job validation remains essential; this check is not an enforced branch-protection or deployment gate.
- `.github/workflows/publication-health.yml` verifies real public content at 06:00 Eastern, hourly at :17 from 07:00–23:00, after publisher runs, and on relevant pushes. Failure opens one incident issue assigned to `DailyLectio`; changed failures update it and recovery closes it. Override the recipient with repository variable `PUBLICATION_HEALTH_ASSIGNEE`. Notification receipt depends on that account's GitHub settings.
- `.github/workflows/verify-publishing-identity.yml` checks the job-scoped workflow token and Git push transport before future protection is enforced. An explicitly requested manual probe can test a real bot push with an empty commit; no file content changes.
- `vercel.json` sets JSON headers and no-cache behavior for the public feeds.

## Updating Content

To update daily devotion content, edit or regenerate `public/weeklyfeed.json`, then let the daily workflow produce `public/devotions.json`.

The production operating procedure, candidate-artifact recovery, schedules, alert limitations, local Git synchronization and maintenance commands are in [the publishing runbook](docs/PUBLISHING.md). Retired experiments are preserved as non-executable reference files under [docs/retired](docs/retired/README.md). Mobile/template build dependencies and Framer settings have not been removed or consolidated.

To update saint reflections, append reviewed records to `public/saint.json`. Automated drafts must be reviewed first. The website expects the same record structure for every day:

```json
{
  "date": "YYYY-MM-DD",
  "saintName": "Saint Name",
  "memorial": "Memorial",
  "source": "USCCB 2026 Liturgical Calendar",
  "saintAlt1": "Alternate name",
  "saintAlt2": "",
  "profile": "A reviewed, substantial single paragraph on the saint's life and Catholic teachings.",
  "link": "https://source.example"
}
```

### Monthly saints review and preservation

Append each reviewed month to `public/saint.json`, retaining the eight fields above, all earlier records, and one unique record per date. Check complete calendar coverage and compare earlier records with the previous commit before publishing.

The automatic monthly generator is a calendar scaffold, not a replacement for editorial review: newly scraped records can have blank profiles and need reviewed Catholic biographical/theological paragraphs. It writes requested-month drafts under `drafts/saints-YYYY-MM.json`, never to `public/saint.json`. It never replaces existing records, including incomplete ones. To improve an existing date, edit it explicitly as part of the review process. Keep the paragraph focused on the saint's life, teachings, Scripture, and Catholic principles, without personal, professional, or financial metaphors. Distinguish later tradition from documented history.

`START_MONTH` defaults to next month in `America/New_York`; an absent or blank `MONTHS` defaults to one month (supported range 1–12). Invalid existing JSON, duplicate dates, or invalid field types stop generation without rewriting the file. When the requested dates are already present, no draft is needed. Draft writes use atomic replacement, and monthly workflow runs are serialized.

Run `python -m pip install -r requirements-devotions.txt`, then `python -m unittest discover -s tests -v`. Run `python -m scripts.check_saints_readiness --month YYYY-MM` before publishing the reviewed month; this checks every date, field types, source/link/name, and a single-paragraph profile of at least 40 words. That minimum detects scaffolds, not editorial quality or historical accuracy. September's approved profiles are substantially longer. Compare all previous records and the approved new month exactly before committing.

Then check GitHub/Vercel status and the live `/saint.json`. A first-day `python update_daily_devotion.py --date YYYY-MM-01 --dry-run --skip-dist` checks data readiness only; verify the actual website post on that date after the daily job runs. Never publish a future-date test into today's feed or archives.

### Reviewed saints and publication validation

Daily and weekly generation select the exact date from committed `public/saint.json` first. A complete local record needs no saints network request. The live JSON is a fallback only if the local record is unavailable or incomplete. If neither has a complete profile, publication fails rather than inventing a saint or silently publishing a placeholder. Source selection is logged. Weekly generation receives the reviewed profile as context and copies it verbatim into `saintReflection`; its Saints exegesis must agree with that profile.

The devotion contract retains both `gospelRef` and `gospelReference` with equal values for existing clients. Empty required reflections, invalid/duplicate dates, malformed references, missing required files, inconsistent second-reading fields, incorrect cycle labels, and known false "no saint assigned" claims fail validation. Run `python -m scripts.validate_publication` for both live and rolling feeds, or pass explicit paths and `--start YYYY-MM-DD --days N` for exact date coverage. Validation is mechanical, not a substitute for theological or lectionary review.

### Liturgical calendar rules and future years

`scripts/liturgical_calendar.py` calculates the first Sunday of Advent as the Sunday between November 27 and December 3. The liturgical year ending in 2020 anchors Year A; A/B/C repeats every three years and advances at Advent, without annual code changes. Ordinary Time weekday cycles alternate I/II, with the feed's annual context label advancing at Advent. Seasonal and feast readings must still use their date-specific proper readings, not an I/II lookup.

For 2026, Year A continues through November 28 (November 22 is its last Sunday); Year B begins November 29. Ordinary Time weekdays use Cycle II in 2026. The Advent transition carries the new year's Cycle I context, but Advent readings themselves are seasonal. Boundary tests cover 2025–2028 and Advent calculations through 2100. Sources: [USCCB 2026 calendar, printed page 5](https://www.usccb.org/resources/2026cal.pdf) and [USCCB lectionary explanation](https://www.usccb.org/faq/questions-about-lectionary).

During each year's editorial review, compare these fixtures and reading/feast exceptions with the newly issued USCCB calendar. Stable cycle rules advance automatically; new Church decrees, local observances, and calendar exceptions still require source review. Historical archive labels are not bulk-rewritten by this repair.

## Deployment

The site is hosted on Vercel and connected to this GitHub repository. Pushing changes to `main` triggers a deployment so the website can fetch the latest JSON feeds.

## Troubleshooting

- If the website is stale, check the relevant public file first: `/devotions.json`, `/weeklyfeed.json`, or `/saint.json`.
- If daily updates are not refreshing, check the GitHub Actions run for `Update Daily Devotion`.
- Keep `OPENAI_API_KEY` and `OPENAI_PROJECT` current. Production writers use GitHub's short-lived `GITHUB_TOKEN`, not the old failing `GH_PAT`; validation is explicitly dispatched after publishing.
- Keep all feed dates in `YYYY-MM-DD` format. The automation uses the `America/New_York` timezone.

This project is maintained by Daily Lectio Media LLC.
