#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import argparse, json, os, sys, re, urllib.request, tempfile
from datetime import datetime, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional

# ---------- Paths ----------
BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
DIST_DIR = BASE_DIR / "dist"
ARCHIVE_DIR = PUBLIC_DIR / "past_reflections"

WEEKLY_PATH = PUBLIC_DIR / "weeklyfeed.json"
PUBLIC_TARGET = PUBLIC_DIR / "devotions.json"
DIST_TARGET = DIST_DIR / "devotions.json"
INDEX_PATH = ARCHIVE_DIR / "index.json"

SAINT_URL = "https://dailylectio.org/saint.json"

def iso(d: date) -> str:
    return d.isoformat()

def atomic_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp): os.remove(tmp)
        except Exception:
            pass

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--date", help="YYYY-MM-DD override")
    p.add_argument("--tz", default="America/New_York")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-dist", action="store_true")
    p.add_argument("--backfill", type=int, default=0, help="N days back to include")
    return p.parse_args()

def load_weekly(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[error] Failed reading {path}: {e}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(data, list):
        print(f"[error] {path} must be a JSON array", file=sys.stderr); sys.exit(1)
    # soft migrate
    for e in data:
        if isinstance(e, dict) and "theologicalSynthesis" not in e and "theologicalSummary" in e:
            e["theologicalSynthesis"] = e["theologicalSummary"]
    return data

# ---------- saint helpers ----------
def fetch_json(url: str, timeout: int = 10) -> Optional[Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.status != 200:
                print(f"[warn] GET {url} -> HTTP {resp.status}", file=sys.stderr)
                return None
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[warn] fetch {url} failed: {e}", file=sys.stderr)
        return None

def _normalize_saint_entry(entry: dict) -> dict:
    # Accept either saintName/profile or name/bio (yours use saintName/profile)
    name = (entry.get("saintName") or entry.get("name") or "").strip()
    bio  = (entry.get("profile")   or entry.get("bio")  or "").strip()
    link = (entry.get("link") or "").strip()
    memorial = (entry.get("memorial") or "").strip()
    return {"name": name, "bio": bio, "link": link, "memorial": memorial}

def saint_for_today(saint_data: Any, today: str) -> Optional[Dict[str, str]]:
    """
    Date-only lookup. Supports:
      1) dict keyed by date: { "YYYY-MM-DD": {...} }
      2) list of entries:    [ { "date": "YYYY-MM-DD", ... }, ... ]
    No feast/fuzzy fallback—weekly 'feast' can be blank forever.
    """
    if not saint_data:
        return None

    # dict keyed by date
    if isinstance(saint_data, dict):
        entry = saint_data.get(today)
        if isinstance(entry, dict):
            std = _normalize_saint_entry(entry)
            if std["name"] or std["bio"]:
                return std

    # list of entries
    if isinstance(saint_data, list):
        for entry in saint_data:
            if isinstance(entry, dict) and str(entry.get("date","")).strip() == today:
                std = _normalize_saint_entry(entry)
                if std["name"] or std["bio"]:
                    return std

    return None

    # fuzzy fallback using feast text
    feast = (weekly_feast or "").lower().strip()
    if feast and isinstance(saint_data, list):
        for entry in saint_data:
            if isinstance(entry, dict):
                nm = (entry.get("saintName") or entry.get("name") or "").lower()
                if nm and nm in feast:
                    return _normalize_saint_entry(entry)
    return None

# ---------- tagging ----------
THEME_MAP = {
    r"\bhumbl(e|ity)\b": "humility",
    r"\bhospitality\b": "hospitality",
    r"\bmercy\b": "mercy",
    r"\bjustice\b": "justice",
    r"\bfaith(ful|fulness)?\b": "faith",
    r"\bhope\b": "hope",
    r"\blove\b|\bcharity\b": "love",
    r"\bkingdom\b": "kingdom-values",
    r"\bdisciples?\b": "discipleship",
    r"\bprayer\b": "prayer",
    r"\byouth\b|\bstudents?\b|\bteen(s)?\b": "youth",
    r"\bconversion\b|\brepent(ance)?\b": "conversion",
}

BOOKS = [
    "Genesis","Exodus","Leviticus","Numbers","Deuteronomy",
    "Joshua","Judges","Ruth","1 Samuel","2 Samuel","1 Kings","2 Kings",
    "1 Chronicles","2 Chronicles","Ezra","Nehemiah","Tobit","Judith","Esther",
    "Job","Psalms","Proverbs","Ecclesiastes","Song of Songs","Wisdom","Sirach",
    "Isaiah","Jeremiah","Lamentations","Baruch","Ezekiel","Daniel",
    "Hosea","Joel","Amos","Obadiah","Jonah","Micah","Nahum","Habakkuk",
    "Zephaniah","Haggai","Zechariah","Malachi",
    "Matthew","Mark","Luke","John","Acts","Romans","1 Corinthians","2 Corinthians",
    "Galatians","Ephesians","Philippians","Colossians","1 Thessalonians","2 Thessalonians",
    "1 Timothy","2 Timothy","Titus","Philemon","Hebrews","James","1 Peter","2 Peter",
    "1 John","2 John","3 John","Jude","Revelation"
]

def auto_tags(entry: Dict[str, Any], saint_used: bool) -> list[str]:
    existing = entry.get("tags")
    if isinstance(existing, list) and any(str(x).strip() for x in existing):
        return [str(x).strip() for x in existing if str(x).strip()]

    text_blob = " ".join(
        str(entry.get(k,"")) for k in
        ("quote","firstReading","psalmSummary","gospelSummary","saintReflection","theologicalSynthesis","exegesis","dailyPrayer")
        if isinstance(entry.get(k), str)
    )
    refs_blob = " ".join(
        str(entry.get(k,"")) for k in
        ("firstReadingRef","psalmRef","gospelRef","secondReadingRef","quoteCitation")
        if isinstance(entry.get(k), str)
    )

    tags: list[str] = []
    for pat, tag in THEME_MAP.items():
        if re.search(pat, text_blob, flags=re.IGNORECASE):
            tags.append(tag)
    for book in BOOKS:
        if re.search(rf"\b{re.escape(book)}\b", refs_blob):
            tags.append(book.lower())
    if saint_used:
        tags.insert(0, "saints")

    # dedupe, keep up to 8
    out: list[str] = []
    for t in tags:
        if t not in out:
            out.append(t)
    return out[:8]

# ---------- tidy ----------
def clean_keys(entry: Dict[str, Any]) -> Dict[str, Any]:
    if "gospelRef" in entry and "gospelReference" in entry:
        entry.pop("gospelReference", None)
    for k in ("secondReading","feast","secondReadingRef"):
        if entry.get(k) is None:
            entry[k] = ""
    return entry

def archive_entry(entry: dict) -> None:
    d = entry.get("date"); 
    if not d: 
        print("[warn] no date; skip archive"); 
        return
    yyyy, mm, _ = d.split("-")
    path = ARCHIVE_DIR / yyyy / mm / f"{d}.json"
    atomic_write_json(path, entry)
    # index update
    try:
        idx = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        if not isinstance(idx, list): idx = []
    except Exception:
        idx = []
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
    # replace by date, keep sorted desc
    by_date = {r.get("date"): r for r in idx if isinstance(r, dict)}
    by_date[d] = row
    new_idx = sorted(by_date.values(), key=lambda r: r["date"], reverse=True)
    atomic_write_json(INDEX_PATH, new_idx)
    print(f"[ok] archived {d} → {path}")

# ---------- main ----------
def main() -> None:
    args = parse_args()
    tz = ZoneInfo(args.tz)
    today = args.date or iso(datetime.now(tz).date())

    print(f"[info] tz={args.tz} today={today}")
    if not WEEKLY_PATH.exists():
        print(f"[error] missing {WEEKLY_PATH}", file=sys.stderr); sys.exit(1)
    weekly = load_weekly(WEEKLY_PATH)

    entry = next((e for e in weekly if str(e.get("date","")).strip()==today), None)
    if not entry:
        print(f"[error] weeklyfeed has no entry for {today}", file=sys.stderr); sys.exit(1)
    entry = dict(entry)  # copy

    saint_data = fetch_json(SAINT_URL)
    saint = saint_for_today(saint_data, today)  # date-only match
    saint_used = False
    if saint:
        title = saint["name"]
        if saint["memorial"]:
            title = f"{title} ({saint['memorial']})"
        composed = f"{title}: {saint['bio']}" if title and saint["bio"] else (saint["bio"] or title)
        if composed:
            entry["saintReflection"] = composed
            saint_used = True

    # Ensure simple secondReading string
    if "secondReading" not in entry or entry["secondReading"] is None:
        entry["secondReading"] = str(entry.get("secondReadingRef") or "")

    entry = clean_keys(entry)
    entry["tags"] = auto_tags(entry, saint_used)

    # backfill support (optional)
    payload = [entry]
    if args.backfill > 0:
        days = {(datetime.now(tz) - timedelta(days=i)).date().isoformat() for i in range(args.backfill)}
        extra = [e for e in weekly if str(e.get("date","")).strip() in days]
        # ensure today first, then recent others
        rest = [e for e in extra if e.get("date") != today]
        rest.sort(key=lambda x: x.get("date",""), reverse=True)
        payload = [entry] + rest

    print(f"[info] writing {PUBLIC_TARGET} (count={len(payload)}) skip_dist={args.skip_dist} dry={args.dry_run}")
    if args.dry_run:
        print(json.dumps(payload[:1], ensure_ascii=False, indent=2)); return

    atomic_write_json(PUBLIC_TARGET, payload)
    print(f"[ok] wrote {PUBLIC_TARGET}")
    if not args.skip_dist:
        atomic_write_json(DIST_TARGET, payload)
        print(f"[ok] wrote {DIST_TARGET}")

    for e in payload:
        archive_entry(e)

if __name__ == "__main__":
    main()
