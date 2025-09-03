from __future__ import annotations
import argparse, json, datetime as dt

try:
    from scripts.saints_service import (
        load_authority, resolve_saint_for_date, choose_primary_url, enrich_with_live_fallback
    )
except ModuleNotFoundError:
    try:
        from saints_service import (
            load_authority, resolve_saint_for_date, choose_primary_url, enrich_with_live_fallback
        )
    except ModuleNotFoundError:
        import sys, pathlib
        ROOT = pathlib.Path(__file__).resolve().parents[1]
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from scripts.saints_service import (
            load_authority, resolve_saint_for_date, choose_primary_url, enrich_with_live_fallback
        )

def make_reflection(name: str, blurb: str) -> str:
    if blurb:
        return blurb.strip()
    return f"{name}—pray for us."

def generate_weekly(start: dt.date, authority_csv_path, days: int = 7, live_fallback: bool = False):
    from pathlib import Path
    authority_csv = Path(authority_csv_path)
    auth = load_authority(authority_csv)
    out_days = []
    for i in range(days):
        d = start + dt.timedelta(days=i)
        saint = resolve_saint_for_date(d, auth)
        if not saint:
            out_days.append({"date": d.isoformat(), "saint": None})
            continue
        saint = enrich_with_live_fallback(saint, enable=live_fallback)
        primary_url = choose_primary_url(saint)
        extras = [u for u in saint.resources if u != primary_url]
        reflection = make_reflection(saint.name, saint.blurb)
        out_days.append({
            "date": d.isoformat(),
            "saint": {
                "name": saint.name,
                "source": primary_url,
                "resources": extras,
                "blurb": saint.blurb,
                "reflection": reflection,
                "saintReflection": reflection,
            }
        })
    return {"week_start": start.isoformat(), "days": out_days}

def main():
    from pathlib import Path
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM-DD (week start)")
    ap.add_argument("--authority", required=True, help="Path to authority CSV")
    ap.add_argument("--out", required=True, help="Output JSON path")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--live-fallback", action="store_true")
    args = ap.parse_args()
    start = dt.date.fromisoformat(args.start)
    weekly = generate_weekly(start, args.authority, days=args.days, live_fallback=args.live_fallback)
    Path(args.out).write_text(json.dumps(weekly, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
