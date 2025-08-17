#!/usr/bin/env python3
"""
Enrich today's readings with DRB text.

- Reads citations from public/weeklyreadings.json
- Pulls DRB text from data/drb.json (nested or flat)
- Writes public/dailyreadings.json with full text for today

Usage (from repo root):
  APP_TZ=America/New_York python3 scripts/enrich_readings.py
  # or override date:
  APP_TZ=America/New_York python3 scripts/enrich_readings.py --date 2025-08-16
"""

from __future__ import annotations
import json, os, re, sys
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, date
try:
    from zoneinfo import ZoneInfo
except Exception:
    print("[fatal] Python 3.9+ with zoneinfo required", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[1]
WEEKLY = ROOT / "public" / "weeklyreadings.json"
DRB = ROOT / "data" / "drb.json"
DAILY_OUT = ROOT / "public" / "dailyreadings.json"

BOOK_ALIASES = {
    # normalizations (expand as needed)
    "psalm": "Psalm",
    "psalms": "Psalm",
    "josue": "Joshua",           # DRB sometimes uses Josue
    "isaias": "Isaiah",
    "ezechiel": "Ezekiel",
    "canticle": "Canticle of Canticles",  # Song of Songs
}

RANGE_RE = re.compile(
    r"""
    ^\s*
    (?P<book>[1-3]?\s*[A-Za-z][A-Za-z\s\-]*?)   # Book name
    \s+
    (?P<chap>\d+)
    :
    (?P<verses>[0-9,\-\u2013\u2014\s]+)        # 1,2,5-7 (allow en/em dashes)
    \s*$
    """,
    re.VERBOSE,
)

def norm_book(name: str) -> str:
    k = name.strip()
    key = re.sub(r"\s+", " ", k).title()
    key = BOOK_ALIASES.get(key.lower(), key)
    return key

def parse_citation(citation: str) -> tuple[str,int,str] | None:
    """
    Return (book, chapter, verses_str) or None.
    Accepts en dashes.
    """
    c = (citation or "").replace("–", "-").replace("—", "-").strip()
    m = RANGE_RE.match(c)
    if not m:
        return None
    book = norm_book(m.group("book"))
    chap = int(m.group("chap"))
    verses = m.group("verses").replace(" ", "")
    return (book, chap, verses)

def verses_list(verses: str) -> list[int]:
    """
    "1,2,5-7,11" -> [1,2,5,6,7,11]
    """
    out: list[int] = []
    for part in verses.split(","):
        if "-" in part:
            a,b = part.split("-",1)
            if a.isdigit() and b.isdigit():
                out.extend(range(int(a), int(b)+1))
        elif part.isdigit():
            out.append(int(part))
    return out

def load_json(path: Path) -> dict|list:
    return json.loads(path.read_text(encoding="utf-8"))

def drb_text_for(citation: str, drb: dict) -> str | None:
    """
    Try flat key first. If not found, try nested lookup.
    """
    flat_key = citation.replace("–", "-").replace("—", "-")
    if flat_key in drb and isinstance(drb[flat_key], str):
        return drb[flat_key].strip() or None

    parsed = parse_citation(citation)
    if not parsed:  # can't parse
        return None
    book, chap, verses_s = parsed
    book_dict = drb.get(book)
    if not isinstance(book_dict, dict):
        return None
    chap_dict = book_dict.get(str(chap))
    if not isinstance(chap_dict, dict):
        return None

    # If chapter dict is whole-chapter text under key "_", return it
    if "_" in chap_dict and isinstance(chap_dict["_"], str) and not verses_s:
        return chap_dict["_"].strip() or None

    wanted = verses_list(verses_s) if verses_s else []
    if not wanted:  # no explicit verses -> try to join all numeric keys
        nums = sorted(int(k) for k in chap_dict.keys() if k.isdigit())
        return " ".join(chap_dict[str(n)].strip() for n in nums if str(n) in chap_dict).strip() or None

    parts: list[str] = []
    for v in wanted:
        s = chap_dict.get(str(v))
        if isinstance(s, str):
            parts.append(s.strip())
    return (" ".join(parts)).strip() or None

def today_iso(tz_name: str, override: str|None) -> str:
    if override:
        return override
    tz = ZoneInfo(tz_name)
    return datetime.now(tz).date().isoformat()

@dataclass
class DayRefs:
    date: str
    first: str|None
    psalm: str|None
    second: str|None
    gospel: str|None
    usccbLink: str|None

def as_dayrefs(obj: dict) -> DayRefs:
    return DayRefs(
        date=str(obj.get("date","")).strip(),
        first=(obj.get("first")),
        psalm=(obj.get("psalm")),
        second=(obj.get("second")),
        gospel=(obj.get("gospel")),
        usccbLink=obj.get("usccbLink"),
    )

def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--date", help="YYYY-MM-DD (default: today in APP_TZ)")
    p.add_argument("--tz", dest="tz", default=os.environ.get("APP_TZ","UTC"))
    p.add_argument("--include-verse-nums", action="store_true", help="(optional) prefix verse numbers")
    args = p.parse_args()

    if not WEEKLY.exists():
        print(f"[error] Missing {WEEKLY}", file=sys.stderr)
        return 1
    if not DRB.exists():
        print(f"[warn] {DRB} not found; will output citations without text")
        drb = {}
    else:
        drb = load_json(DRB)

    target = today_iso(args.tz, args.date)
    weekly = load_json(WEEKLY)
    days = weekly.get("days", []) if isinstance(weekly, dict) else []
    lookup = { str(d.get("date","")).strip(): d for d in days }
    if target not in lookup:
        print(f"[error] No readings for {target} in weekly file.", file=sys.stderr)
        near = ", ".join(sorted(lookup.keys())[:3])
        print(f"[hint] present dates: {near} ...", file=sys.stderr)
        return 1

    d = as_dayrefs(lookup[target])

    def bundle(citation: str|None) -> dict|None:
        if not citation:
            return None
        txt = drb_text_for(citation, drb)
        return {
            "citation": citation,
            "text": txt  # can be None if not found
        }

    out = {
        "date": d.date,
        "first": bundle(d.first),
        "psalm": bundle(d.psalm),
        "second": bundle(d.second),
        "gospel": bundle(d.gospel),
        "usccbLink": d.usccbLink
    }

    DAILY_OUT.parent.mkdir(parents=True, exist_ok=True)
    DAILY_OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[ok] wrote {DAILY_OUT}")
    # quick echo if any missing text:
    missing = [k for k in ("first","psalm","second","gospel") if out[k] and not out[k]["text"]]
    if missing:
        print(f"[warn] No DRB text found for: {missing}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())