from __future__ import annotations
import json, argparse
from pathlib import Path

def load_json(p: str | Path) -> dict:
    p = Path(p)
    return json.loads(p.read_text(encoding="utf-8"))

def save_json(p: str | Path, data: dict):
    p = Path(p)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def index_by_date(days: list[dict]) -> dict[str, dict]:
    idx = {}
    for d in days:
        date = d.get("date")
        if date:
            idx[date] = d
    return idx

def main():
    ap = argparse.ArgumentParser(description="Merge saints weeklydevotion.json into weeklyfeed.json")
    ap.add_argument("--weekly", required=True, help="Path to existing weeklyfeed.json (input)")
    ap.add_argument("--saints", required=True, help="Path to weeklydevotion.json produced by generate_weekly.py")
    ap.add_argument("--out", required=True, help="Path to write merged weeklyfeed.json")
    ap.add_argument("--force", action="store_true", help="Overwrite existing saintReflection if present")
    args = ap.parse_args()

    wf = load_json(args.weekly)
    sf = load_json(args.saints)

    wf_days = wf.get("days") or wf.get("daily") or []
    sf_days = sf.get("days") or []

    idx_wf = index_by_date(wf_days)
    idx_sf = index_by_date(sf_days)

    updated = 0
    for date, wf_day in idx_wf.items():
        saint = idx_sf.get(date, {}).get("saint")
        if not saint:
            continue
        wf_day["saint"] = saint
        sr = saint.get("reflection") or ""
        if args.force or not wf_day.get("saintReflection"):
            wf_day["saintReflection"] = sr
        updated += 1

    if "days" in wf:
        wf["days"] = [idx_wf[d] for d in sorted(idx_wf.keys())]
    elif "daily" in wf:
        wf["daily"] = [idx_wf[d] for d in sorted(idx_wf.keys())]

    save_json(args.out, wf)
    print(f"Merged saints into {updated} day(s). Wrote: {args.out}")

if __name__ == "__main__":
    main()
