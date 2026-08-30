# Daily Lectio Data Site

This repository publishes the JSON feeds used by the Daily Lectio website and connected mobile/front-end clients. Vercel serves files from `public/` at the site root, so `public/devotions.json` becomes `/devotions.json`, `public/weeklyfeed.json` becomes `/weeklyfeed.json`, and `public/saint.json` becomes `/saint.json`.

## Live JSON Feeds

- `public/devotions.json` is the daily live devotion feed. It is generated from the weekly feed by `update_daily_devotion.py`.
- `public/weeklyfeed.json` is the rolling source feed for daily Scripture reflections. Each entry uses a `date` field in `YYYY-MM-DD` format plus reflection fields such as `quote`, `firstReading`, `psalmSummary`, `gospelSummary`, `saintReflection`, `dailyPrayer`, `theologicalSynthesis`, `exegesis`, tags, reading references, and source links.
- `public/saint.json` is the current saint reflection feed. It is an array of daily records with `date`, `saintName`, `memorial`, `source`, `saintAlt1`, `saintAlt2`, `profile`, and `link`.
- `public/past_reflections/` stores archived daily devotion snapshots by year/month/date, with `public/past_reflections/index.json` as the archive index.
- `public/archive/` and `public/feeds/` hold legacy and generated feed artifacts used for backups, testing, or older clients.

## Automation

- `.github/workflows/daily-devotion-update.yml` runs daily and can also be started manually. It checks whether today's entry exists in `public/weeklyfeed.json`, generates a one-day fallback if needed, runs `update_daily_devotion.py`, and commits updates to `public/devotions.json` plus the past-reflections archive.
- `.github/workflows/generate-weekly.yml` generates the weekly devotion feed.
- `.github/workflows/generate-saints-monthly.yml` runs monthly or manually to add missing dates to `public/saint.json` using `scripts/generate_saints.py`. It preserves all existing dates and reviewed profiles, including months outside the requested range.
- `vercel.json` sets JSON headers and no-cache behavior for the public feeds.

## Updating Content

To update daily devotion content, edit or regenerate `public/weeklyfeed.json`, then let the daily workflow produce `public/devotions.json`.

To update saint reflections, edit or regenerate `public/saint.json`. The website expects the same record structure for every day:

```json
{
  "date": "YYYY-MM-DD",
  "saintName": "Saint Name",
  "memorial": "Memorial",
  "source": "USCCB 2026 Liturgical Calendar",
  "saintAlt1": "Alternate name",
  "saintAlt2": "",
  "profile": "Short saint reflection for display.",
  "link": "https://source.example"
}
```

### Monthly saints review and preservation

Append each reviewed month to `public/saint.json`, retaining the eight fields above, all earlier records, and one unique record per date. Check complete calendar coverage and compare earlier records with the previous commit before publishing.

The automatic monthly generator is a calendar scaffold, not a replacement for editorial review: newly scraped records can have blank profiles and need reviewed Catholic biographical/theological paragraphs. It never replaces existing records, including incomplete ones. To improve an existing date, edit it explicitly as part of the review process.

`START_MONTH` defaults to next month in `America/New_York`; an absent or blank `MONTHS` defaults to one month (supported range 1–12). Invalid existing JSON, duplicate dates, or invalid field types stop generation without rewriting the file. When the month is already present, the file is left byte-for-byte unchanged. Writes use an atomic replacement, and monthly workflow runs are serialized.

Run the offline regression suite with `python -m unittest discover -s tests -p 'test_generate_saints.py' -v` after installing `requests` and `beautifulsoup4` (also `tzdata` on Windows). Then check GitHub/Vercel status and the live `/saint.json`. A first-day `update_daily_devotion.py --date YYYY-MM-01 --dry-run --skip-dist` checks data readiness only; verify the actual website post on that date after the daily job runs.

## Deployment

The site is hosted on Vercel and connected to this GitHub repository. Pushing changes to `main` triggers a deployment so the website can fetch the latest JSON feeds.

## Troubleshooting

- If the website is stale, check the relevant public file first: `/devotions.json`, `/weeklyfeed.json`, or `/saint.json`.
- If daily updates are not refreshing, check the GitHub Actions run for `Update Daily Devotion`.
- Make sure `GH_PAT`, `OPENAI_API_KEY`, and `OPENAI_PROJECT` secrets are current where the workflows require them.
- Keep all feed dates in `YYYY-MM-DD` format. The automation uses the `America/New_York` timezone.

This project is maintained by Daily Lectio Media LLC.
