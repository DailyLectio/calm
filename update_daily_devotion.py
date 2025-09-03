#!/usr/bin/env python3
"""
Daily Devotion Update Script for FaithLinks

Pull today's entry from weeklyfeed.json and write:
- public/devotions.json  (live)
- dist/devotions.json    (backup)
Also archives to:
- public/past_reflections/YYYY/MM/YYYY-MM-DD.json
- public/past_reflections/index.json (summary index)

Flags:
  --date YYYY-MM-DD      Use a specific date (for backfills/replays)
  --tz America/New_York  Timezone for "today" (default UTC)
  --dry-run              Do everything except write files
  --skip-dist            Don't write dist/devotions.json
  --backfill N           Include the last N days instead of only today
"""
from __future__ import annotations
import argparse, json, os, sys, tempfile
from datetime import datetime, date, timedelta
from pathlib import Path
try:
    from zoneinfo import ZoneInfo
except Exception:
    print("[fatal] Python 3.9+ required for zoneinfo", file=sys.stderr)
    sys.exit(2)

# ---------- Paths ----------
BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
DIST_DIR = BASE_DIR / "dist"
ARCHIVE_DIR = PUBLIC_DIR / "past_reflections"

WEEKLY_PATH = PUBLIC_DIR / "weeklyfeed.json"
PUBLIC_TARGET = PUBLIC_DIR / "devotions.json"
DIST_TARGET = DIST_DIR / "devotions.json"
INDEX_PATH = ARCHIVE_DIR / "index.json"

def iso(d: date) -> str:
    return d.isoformat()

def atomic_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--date", help="YYYY-MM-DD override")
    p.add_argument("--tz", default="UTC", help="IANA timezone, e.g., America/New_York")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-dist", action="store_true")
    p.add_argument("--backfill", type=int, default=0, help="Number of days back to include")
    return p.parse_args()

def load_weekly(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[error] Failed reading {path}: {e}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(data, list):
        print(f"[error] {path} is not a JSON array", file=sys.stderr)
        sys.exit(1)
    # soft-migrate: map theologicalSummary -> theologicalSynthesis if needed
    for e in data:
        if isinstance(e, dict) and "theologicalSynthesis" not in e and "theologicalSummary" in e:
            e["theologicalSynthesis"] = e["theologicalSummary"]
    return data

def archive_entry(entry: dict) -> None:
    d = entry.get("date")
    if not d:
        print("[warn] skipping archive: entry missing date"); return
    yyyy, mm, _ = d.split("-")
    path = ARCHIVE_DIR / yyyy / mm / f"{d}.json"
    atomic_write_json(path, entry)
    # index update
    try:
        idx = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        if not isinstance(idx, list): idx = []
    except Exception:
        idx = []
    # build summary row
    row = {
        "date": d,
        "quote": entry.get("quote",""),
        "quoteCitation": entry.get("quoteCitation",""),
        "tags": entry.get("tags",[]),
        "usccbLink": entry.get("usccbLink",""),
        "feast": entry.get("feast",""),
        "cycle": entry.get("cycle",""),
        "weekdayCycle": entry.get("weekdayCycle",""),
        "path": f"/past_reflections/{yyyy}/{mm}/{d}.json"
    }
    # replace or append
    by_date = {r.get("date"): r for r in idx if isinstance(r, dict)}
    by_date[d] = row
    new_idx = sorted(by_date.values(), key=lambda r: r["date"], reverse=True)
    atomic_write_json(INDEX_PATH, new_idx)
    print(f"[ok] archived {d} → {path}")

def main() -> None:
    args = parse_args()
    tz = ZoneInfo(args.tz)
    today = args.date or iso(datetime.now(tz).date())

    print(f"[info] tz={args.tz} today={today}")
    print(f"[info] repo_root={BASE_DIR}")
    print(f"[info] weekly_path={WEEKLY_PATH}")

    if not WEEKLY_PATH.exists():
        print(f"[error] Source file missing: {WEEKLY_PATH}", file=sys.stderr)
        sys.exit(1)

    weekly = load_weekly(WEEKLY_PATH)
    dates = [str(e.get("date", "")).strip() for e in weekly if isinstance(e, dict)]
    uniq = sorted(set(dates))
    print(f"[info] weekly entries={len(weekly)} unique_dates={len(uniq)} "
          f"min={uniq[0] if uniq else 'n/a'} max={uniq[-1] if uniq else 'n/a'} "
          f"has_today={today in uniq}")

    # find today's entry (still used when backfill=0)
    entry = next((e for e in weekly if str(e.get("date","")).strip() == today), None)
    if not entry:
        near = sorted(uniq + [today])
        i = near.index(today)
        neighbors = near[max(0, i-3): i] + near[i+1: i+4]
        print(f"[error] No entry for {today}. Nearby dates: {neighbors}", file=sys.stderr)
        sys.exit(1)

    # Build payload
    if args.backfill > 0:
        back_dates = {(datetime.now(tz) - timedelta(days=i)).date().isoformat()
                      for i in range(args.backfill)}
        payload = [e for e in weekly if str(e.get("date","")).strip() in back_dates]
        payload.sort(key=lambda e: e.get("date",""), reverse=True)
    else:
        payload = [entry]

    print(f"[info] will write public={PUBLIC_TARGET} dist={DIST_TARGET} "
          f"dry_run={args.dry_run} skip_dist={args.skip_dist} count={len(payload)}")

    if args.dry_run:
        print("[info] dry-run: not writing files")
        sys.exit(0)

    # write live files
    atomic_write_json(PUBLIC_TARGET, payload)
    print(f"[ok] wrote {PUBLIC_TARGET}")
    if not args.skip_dist:
        atomic_write_json(DIST_TARGET, payload)
        print(f"[ok] wrote {DIST_TARGET}")

    # archive each entry in payload
    for e in payload:
        archive_entry(e)

if __name__ == "__main__":
    main()