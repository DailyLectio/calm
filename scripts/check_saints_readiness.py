"""Report incomplete reviewed coverage, exiting nonzero for GitHub notifications."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from scripts.saints_feed import SAINT_PATH, month_readiness


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", help="YYYY-MM; default next month in APP_TZ")
    parser.add_argument("--path", type=Path, default=SAINT_PATH)
    args = parser.parse_args()
    today = datetime.now(ZoneInfo(os.getenv("APP_TZ", "America/New_York"))).date()
    month = args.month or f"{today.year + (today.month == 12):04d}-{today.month % 12 + 1:02d}"
    missing = month_readiness(json.loads(args.path.read_text(encoding="utf-8")), month)
    if missing:
        print(f"::error::{month}: reviewed saint content missing/incomplete for {', '.join(missing)}")
        raise SystemExit(1)
    print(f"[ok] {month}: all dates have complete saint profiles; editorial review still required")


if __name__ == "__main__":
    main()
