from __future__ import annotations
import os, json, datetime as dt
from pathlib import Path
from typing import Any, Dict, List

try:
    # normal import
    from scripts.saints_service import (
        load_authority, resolve_saint_for_date, choose_primary_url, enrich_with_live_fallback
    )
except ModuleNotFoundError:
    # fallback if run inside scripts/
    from saints_service import (
        load_authority, resolve_saint_for_date, choose_primary_url, enrich_with_live_fallback
    )

def make_reflection(name: str, blurb: str) -> str:
    blurb = (blurb or "").strip()
    return blurb if blurb else f"{name}—pray for us."

def generate_weekly_saints(start: dt.date, authority_csv: Path, days: int = 7) -> Dict[str, Any]:
    auth = load_authority(authority_csv)
    out_days: List[Dict[str, Any]] = []
    for i in range(days):
        d = start + dt.timedelta(days=i)
        saint = resolve_saint_for_date(d, auth)
        if not saint:
            out_days.append({"date": d.isoformat(), "saint": None})
            continue
        primary = choose_primary_url(saint)
        extras = [u for u in saint.resources if u != primary]
        reflection = make_reflection(saint.name, saint.blurb)
        out_days.append({
            "date": d.isoformat(),
            "saint": {
                "name": saint.name,
                "source": primary,
                "resources": extras,
                "blurb": saint.blurb,
                "reflection": reflection,
            }
        })
    return {"week_start": start.isoformat(), "days": out_days}

def main():
    start_s = os.getenv("START_DATE") or os.getenv("START") or ""
    if not start_s:
        raise SystemExit("START_DATE env var is required (YYYY-MM-DD)")
    try:
        start = dt.date.fromisoformat(start_s)
    except Exception:
        raise SystemExit(f"Invalid START_DATE: {start_s!r}")

    authority = os.getenv("AUTHORITY") or ""
    if not authority:
        raise SystemExit("AUTHORITY env var is required (path to CSV)")
    out = os.getenv("OUT") or "public/feeds/weeklydevotion.json"
    days = int(os.getenv("DAYS") or "7")

    weekly = generate_weekly_saints(start, Path(authority), days=days)
    Path(out).write_text(json.dumps(weekly, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[saints] wrote: {out}  (start={start.isoformat()}, days={days})")

if __name__ == "__main__":
    main()
