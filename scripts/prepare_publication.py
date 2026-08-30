"""Prepare only missing days, retaining reviewed overlaps and never publishing here."""
import argparse
from datetime import date, datetime, timedelta
import os
from pathlib import Path
import subprocess
from zoneinfo import ZoneInfo
from scripts.feed_io import read_array, write_json
from scripts.saints_feed import select_saint
from scripts.validate_publication import validate_rows

ROOT = Path(__file__).resolve().parents[1]


def release_friday(day):
    # Thursday preparation; a run delayed to Friday/weekend still fills that release.
    return day + timedelta(days=4 - day.weekday())


def prepare(start, days, root=ROOT, builder=None):
    if not 1 <= days <= 14:
        raise ValueError("days must be 1..14")
    path = root / "public/weeklyfeed.json"
    existing = read_array(path) if path.exists() else []
    if existing:
        validate_rows(existing)
    by_date = {r["date"]: r for r in existing}
    targets = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    missing = [d for d in targets if d not in by_date]
    # Fail before the first paid call if the window crosses into unreviewed saints.
    for day in missing:
        select_saint(day, root / "public/saint.json")
    if builder is None:
        from scripts.generate_weekly import build_day_payload
        builder = build_day_payload
    generated = []
    for day in missing:
        row = builder(date.fromisoformat(day))
        validate_rows([row], expected_dates=[day])
        generated.append(row)
    candidate = {"version": 1,
                 "baseSha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
                 "targetDates": targets, "rows": generated}
    print(f"[ok] prepared {len(generated)} missing days; retained {days - len(missing)} reviewed dates")
    return candidate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("daily", "weekly"), required=True)
    parser.add_argument("--start", default=os.getenv("START_DATE", ""))
    parser.add_argument("--days", type=int, default=int(os.getenv("DAYS", "") or "7"))
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/candidate.json")
    args = parser.parse_args()
    today = datetime.now(ZoneInfo(os.getenv("APP_TZ", "America/New_York"))).date()
    if args.mode == "daily":
        start, days = today, 1
    else:
        start, days = date.fromisoformat(args.start) if args.start else release_friday(today), args.days
    write_json(args.output, prepare(start, days))


if __name__ == "__main__":
    main()
