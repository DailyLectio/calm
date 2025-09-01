#!/usr/bin/env python3
# USCCB-only generator: no local hints/fallbacks.
# If USCCB parse misses a required ref (first/psalm/gospel), the run exits
# with a clear error so we can fix the selector, not ship wrong content.

import json, os, re
from datetime import datetime, date, timedelta
from pathlib import Path
from jsonschema import Draft202012Validator
from openai import OpenAI
from collections import OrderedDict
from typing import List, Dict, Any, Optional

# ---------- repo paths ----------
ROOT         = Path(__file__).resolve().parents[1]
WEEKLY_PATH  = ROOT / "public" / "weeklyfeed.json"
SCHEMA_PATH  = ROOT / "schemas" / "devotion.schema.json"
USCCB_BASE   = "https://bible.usccb.org/bible/readings"
ROOT          = Path(__file__).resolve().parents[1]
WEEKLY_PATH   = ROOT / "public" / "weeklyfeed.json"
READINGS_HINT = ROOT / "public" / "weeklyreadings.json"  # used only if USCCB fetch fails
SCHEMA_PATH   = ROOT / "schemas" / "devotion.schema.json"
USCCB_BASE    = "https://bible.usccb.org/bible/readings"

# ---------- model knobs (override from workflow env) ----------
MODEL          = os.getenv("GEN_MODEL", "gpt-4o-mini")
FALLBACK_MODEL = os.getenv("GEN_FALLBACK", "gpt-4o-mini")
TEMP_MAIN      = float(os.getenv("GEN_TEMP", "0.55"))
TEMP_REPAIR    = float(os.getenv("GEN_TEMP_REPAIR", "0.45"))
TEMP_QUOTE     = float(os.getenv("GEN_TEMP_QUOTE", "0.35"))

def safe_chat(client, *, temperature, response_format, messages, model=None):
    use_model = (model or MODEL)
    try:
        return client.chat.completions.create(
            model=use_model,
            temperature=temperature,
            response_format=response_format,
            messages=messages,
        )
    except Exception as e:
        msg = str(e).lower()
        if any(k in msg for k in ("model","permission","not found","unknown")) and FALLBACK_MODEL != use_model:
            print(f"[warn] model '{use_model}' not available; falling back to '{FALLBACK_MODEL}'")
            return client.chat.completions.create(
                model=FALLBACK_MODEL,
                temperature=temperature,
                response_format=response_format,
                messages=messages,
            )
        raise

# ---------- output contract (key order) ----------
KEY_ORDER = [
    "date","quote","quoteCitation","firstReading","psalmSummary","gospelSummary","saintReflection",
    "dailyPrayer","theologicalSynthesis","exegesis","secondReading","tags","usccbLink","cycle",
    "weekdayCycle","feast","gospelReference","firstReadingRef","secondReadingRef","psalmRef",
    "gospelRef","lectionaryKey",
]
NULLABLE_STR_FIELDS = ("secondReading", "feast", "secondReadingRef")

# ---------- utilities ----------
def usccb_link(d: date) -> str:
    return f"{USCCB_BASE}/{d.strftime('%m%d%y')}.cfm"

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

CYCLE_MAP   = {"A":"Year A","B":"Year B","C":"Year C","Year A":"Year A","Year B":"Year B","Year C":"Year C"}
WEEKDAY_MAP = {"I":"Cycle I","II":"Cycle II","Cycle I":"Cycle I","Cycle II":"Cycle II"}

def _normalize_refs(entry: Dict[str, Any]) -> Dict[str, Any]:
    for k in ("firstReadingRef","psalmRef","secondReadingRef","gospelRef","gospelReference"):
        v = entry.get(k, "")
        entry[k] = "" if v is None else str(v)
    return entry

def _normalize_enums(entry: Dict[str, Any]) -> Dict[str, Any]:
    # USCCB page doesn’t expose cycles; keep your defaults if not provided
    entry["cycle"] = CYCLE_MAP.get(str(entry.get("cycle","")).strip(), entry.get("cycle","Year C"))
    entry["weekdayCycle"] = WEEKDAY_MAP.get(
        str(entry.get("weekdayCycle","")).strip() or str(entry.get("weekday","")).strip(),
        entry.get("weekdayCycle","Cycle I")
    )
    return entry

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None
APP_TZ = os.getenv("APP_TZ", "America/New_York")

def today_in_tz(tzname: str) -> date:
@@ -158,50 +162,90 @@ def fetch_usccb_meta(d: date) -> Dict[str,str]:
    if gospel: gospel = _clean(gospel)

    # Require first/psalm/gospel
    if not (first and psalm and gospel):
        raise SystemExit(f"USCCB parse incomplete for {d.isoformat()} (first/psalm/gospel required)")

    # Try to extract a Saint’s name from title
    saintName = ""
    m = re.search(r"(Saint|St\.)\s+([A-Z][A-Za-z'’\-]+(?:\s+[A-Z][A-Za-z'’\-]+)*)", feast or "")
    if m:
        saintName = m.group(0).replace("St.", "Saint")

    return {
        "firstRef": first,
        "secondRef": second or "",
        "psalmRef": psalm,
        "gospelRef": gospel,
        "feast": feast or "",
        "cycle":  "Year C",
        "weekday":"Cycle I",
        "saintName": saintName,
        "saintNote": "",
        "url": url,
    }

def readings_meta_for(d: date, hints) -> Dict[str, str]:
    """USCCB-first metadata; hints used only if fetch fails."""
    try:
        meta = fetch_usccb_meta(d)
        if not (meta["firstRef"] and meta["psalmRef"] and meta["gospelRef"]):
            raise RuntimeError("USCCB parse incomplete")
        return meta
    except Exception as e:
        print(f"[warn] USCCB fetch failed for {d.isoformat()}: {e}")
        row = None
        ds = d.isoformat()
        if isinstance(hints, list):
            for r in hints:
                if isinstance(r, dict) and str(r.get("date", "")).strip() == ds:
                    row = r
                    break
        elif isinstance(hints, dict):
            row = hints.get(ds)

        def pick(*keys, default=""):
            if not row:
                return default
            for k in keys:
                if k in row and row[k]:
                    return str(row[k])
            return default

        return {
            "firstRef":  pick("firstReadingRef", "firstRef", "firstReading"),
            "secondRef": pick("secondReadingRef", "secondRef", "secondReading", default=""),
            "psalmRef":  pick("psalmRef", "psalm", "psalmReference"),
            "gospelRef": pick("gospelRef", "gospel", "gospelReference"),
            "cycle":     pick("cycle", default="Year C"),
            "weekday":   pick("weekdayCycle", "weekday", default="Cycle I"),
            "feast":     pick("feast", default=""),
            "saintName": pick("saintName", "saint", default=""),
            "saintNote": pick("saintNote", default=""),
            "url":       usccb_link(d),
        }

def lectionary_key(meta: Dict[str, str]) -> str:
    parts = [meta.get("firstRef","").replace(" ",""),
             meta.get("psalmRef","").replace(" ",""),
             meta.get("gospelRef","").replace(" ",""),
             meta.get("cycle",""), meta.get("weekday","")]
    return "|".join(p for p in parts if p)

# ---------- quote + length helpers ----------
PAREN_REF_RE = re.compile(r"\s*\([^)]*\)\s*$")
def strip_trailing_paren_ref(s: str) -> str:
    return PAREN_REF_RE.sub("", s or "").strip()

SENT_SPLIT = re.compile(r'[.!?]+(?=\s|$)')
WORD_RE    = re.compile(r'\b\w+\b')

LENGTH_RULES = {
    "firstReading":        {"min_w": 50,  "max_w": 100},
    "secondReading":       {"min_w": 50,  "max_w": 100},
    "psalmSummary":        {"min_w": 50,  "max_w": 100},
    "gospelSummary":       {"min_w": 100, "max_w": 200},
    "saintReflection":     {"min_w": 50,  "max_w": 100},
    "dailyPrayer":         {"min_w": 150, "max_w": 200},
    "theologicalSynthesis":{"min_w": 150, "max_w": 200},
    "exegesis":            {"min_w": 500, "max_w": 750},
}
@@ -343,56 +387,57 @@ def main():

    # Schema (optional)
    validator = None
    if SCHEMA_PATH.exists():
        try:
            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            validator = Draft202012Validator(schema)
        except Exception:
            print(f"[warn] could not load schema at {SCHEMA_PATH}; continuing")

    # load existing file defensively (allows incremental updating)
    try:
        raw_weekly = json.loads(WEEKLY_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw_weekly = []
    if isinstance(raw_weekly, dict) and "weeklyDevotionals" in raw_weekly:
        weekly = raw_weekly.get("weeklyDevotionals", [])
    elif isinstance(raw_weekly, list):
        weekly = raw_weekly
    else:
        weekly = []
    by_date: Dict[str, Dict[str, Any]] = {str(e.get("date")): e for e in weekly if isinstance(e, dict)}

    client  = OpenAI()
    wanted_dates = [(START + timedelta(days=i)).isoformat() for i in range(DAYS)]
    hints   = load_json(READINGS_HINT, default=None)  # used only if USCCB fetch fails

    for i, ds in enumerate(wanted_dates):
        d = START + timedelta(days=i)

        # USCCB authoritative refs (required)
        meta = fetch_usccb_meta(d)
        # USCCB authoritative refs (falls back to hints if parsing fails)
        meta = readings_meta_for(d, hints)
        lk   = lectionary_key(meta)

        user_msg = "\n".join([
            f"Date: {ds}",
            f"USCCB: {meta['url']}",
            f"Cycle: {meta['cycle']}  WeekdayCycle: {meta['weekday']}",
            f"Feast: {meta['feast']}",
            "Readings:",
            f"  First:  {meta['firstRef']}",
            f"  Psalm:  {meta['psalmRef']}",
            f"  Gospel: {meta['gospelRef']}",
            f"Saint: {meta['saintName']} — {meta['saintNote']}",
        ])

        # --- main generation ---
        resp = safe_chat(
            client,
            temperature=TEMP_MAIN,
            response_format={"type":"json_object"},
            messages=[{"role":"system","content":STYLE_CARD},
                      {"role":"user","content":user_msg}],
            model=MODEL
        )
        raw = resp.choices[0].message.content
        try: