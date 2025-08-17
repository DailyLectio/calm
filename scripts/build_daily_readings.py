#!/usr/bin/env python3
import json, os, re
from pathlib import Path
from datetime import datetime, date
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

ROOT = Path(__file__).resolve().parents[1]
WEEKLY_REFS = ROOT / "public" / "weeklyreadings.json"   # existing references-by-date (your file)
DAILY_OUT   = ROOT / "public" / "dailyreadings.json"
DR_SOURCE   = ROOT / "data" / "drb.json"                # optional, public-domain DR text (can be absent)
SCHEMA_PATH = ROOT / "schemas" / "dailyreadings.schema.json"

APP_TZ = os.getenv("APP_TZ", "America/New_York")

USCCB_BASE = "https://bible.usccb.org/bible/readings"

def today_local():
    if ZoneInfo:
        return datetime.now(ZoneInfo(APP_TZ)).date()
    return date.today()

def usccb_link(d: date) -> str:
    return f"{USCCB_BASE}/{d.strftime('%m%d%y')}.cfm"

def load_json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default

def pick_row(ds: str, weekly):
    if isinstance(weekly, list):
        for r in weekly:
            if str(r.get("date","")).strip() == ds:
                return r
    elif isinstance(weekly, dict):
        return weekly.get(ds)
    return None

# ---- DR text helpers (public domain) ----
def normalize_ref_tail(tail: str) -> str:
    # Replace hyphen with en-dash in numeric ranges
    return re.sub(r"(\d)-(\d)", r"\1–\2", (tail or "").strip())

def render_passage(bible: dict, book: str, ref_tail: str) -> str|None:
    """Render verses within a single book, e.g. '11:17–27, 31–33'."""
    if not bible or not book or not ref_tail:
        return None
    bk = bible.get(book)
    if not bk:
        return None
    text_parts = []
    pieces = [p.strip() for p in ref_tail.split(",") if p.strip()]
    chap_cache = None
    for piece in pieces:
        m = re.match(r"^(\d+):(\d+)(?:[–-](\d+))?$", piece)
        if not m:
            # support '31–33' if a chapter was set
            m2 = re.match(r"^(\d+)(?:[–-](\d+))?$", piece)
            if m2 and chap_cache:
                v1 = int(m2.group(1)); v2 = int(m2.group(2) or v1)
                chapter = bk.get(str(chap_cache), {})
                for v in range(v1, v2+1):
                    val = chapter.get(str(v))
                    if val: text_parts.append(val)
                continue
            return None
        c = int(m.group(1)); v1 = int(m.group(2)); v2 = int(m.group(3) or v1)
        chap_cache = c
        chapter = bk.get(str(c), {})
        for v in range(v1, v2+1):
            val = chapter.get(str(v))
            if val: text_parts.append(val)
    return "\n".join(text_parts) if text_parts else None

def build_block(bible, rtype: str, heading: str, reference: str|None):
    reference = (reference or "").strip()
    if not reference:
        base = {"type": rtype, "heading": heading, "reference": "", "text": None}
        if rtype == "psalm":
            base.update({"antiphon": None, "verses": [], "text": None})
        return base
    m = re.match(r"^([1-3]?\s?[A-Za-z]+)\s+(.*)$", reference)
    book, tail = None, None
    if m:
        book = m.group(1).strip()
        tail = normalize_ref_tail(m.group(2))
    text = render_passage(bible, book, tail) if (bible and book and tail) else None
    base = {"type": rtype, "heading": heading, "reference": f"{book} {tail}" if book and tail else reference, "text": text}
    if rtype == "psalm":
        base.update({"antiphon": None, "verses": [], "text": text})
    return base

def main():
    ds = today_local().isoformat()
    weekly = load_json(WEEKLY_REFS, default=[])
    row = pick_row(ds, weekly)
    if not row:
        raise SystemExit(f"[error] No readings found in {WEEKLY_REFS} for {ds}")

    bible = load_json(DR_SOURCE, default=None)  # ok if None (text fields will be null)

    # Liturgical header
    lit_title = row.get("feast") or row.get("liturgicalDay") or "Feria"
    cycle = row.get("cycle") or row.get("liturgicalCycle") or ""
    weekday = row.get("weekdayCycle") or row.get("weekday") or ""

    # Links
    primary = row.get("usccbLink") or usccb_link(date.fromisoformat(ds))
    alternates = []
    # Always include an explicit "Mass during the Day (shown)" entry for consistency
    alternates.append({
        "label": "Readings for the Mass during the Day (shown)",
        "url": primary,
        "context": "mass-during-day"
    })
    # If weekly file includes any extra links, pass them through
    extra = row.get("usccbAlternates") or []
    for a in extra:
        lab = str(a.get("label","")).strip()
        url = str(a.get("url","")).strip()
        ctx = str(a.get("context","other")).strip() or "other"
        if lab and url:
            alternates.append({"label": lab, "url": url, "context": ctx})

    # Sections
    first_ref  = row.get("firstReadingRef")
    second_ref = row.get("secondReadingRef")
    psalm_ref  = row.get("psalmRef")
    gospel_ref = row.get("gospelRef")

    sections = []
    sections.append(build_block(bible, "first",  "First Reading", first_ref))
    if second_ref:
        sections.append(build_block(bible, "second", "Second Reading", second_ref))
    # Psalm block (antiphon/verses optional; we keep fields present)
    psalm_block = build_block(bible, "psalm", "Responsorial Psalm", psalm_ref)
    sections.append(psalm_block)
    sections.append(build_block(bible, "gospel", "Gospel", gospel_ref))

    # Saint of the day (link only, if present in weekly refs)
    saint_name = (row.get("saintName") or "").strip()
    saint_link = (row.get("saintLink") or "").strip()
    if saint_name and saint_link:
        sections.append({
            "type": "saint",
            "heading": "Saint of the Day",
            "name": saint_name,
            "link": saint_link
        })

    out = {
        "date": ds,
        "liturgicalDay": {
            "title": lit_title,
            "cycle": cycle,
            "weekdayCycle": weekday
        },
        "usccb": {
            "primary": primary,
            "alternates": alternates
        },
        "translation": {
            "name": "Douay-Rheims (public domain)",
            "abbrev": "DR",
            "attributionUrl": "https://drbo.org/"
        },
        "sections": sections,
        "provenance": {
            "builtAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "tz": APP_TZ,
            "calendarSource": "General Roman Calendar (USA)",
            "textSource": "DR public domain (if available) or null"
        }
    }

    DAILY_OUT.parent.mkdir(parents=True, exist_ok=True)
    DAILY_OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[ok] wrote {DAILY_OUT}")

if __name__ == "__main__":
    main()
