#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generate weeklyfeed.json for FaithLinks.

Inputs (env):
  START_DATE=YYYY-MM-DD   (default: today in APP_TZ)
  DAYS=7                  (default: 7)
  APP_TZ=America/New_York
  USCCB_STRICT=0          (set 1 to fail the run if a day's refs are incomplete)
  GEN_MODEL=gpt-5-mini
  GEN_FALLBACK=gpt-5-mini
  GEN_TEMP=0.60
  GEN_TEMP_REPAIR=0.55
  GEN_TEMP_QUOTE=0.35
  OPENAI_API_KEY, OPENAI_PROJECT

Files read:
  public/saint.json                (optional but preferred; your curated monthly saints)
  public/readings-overrides.json   (optional; only used if present)

File written:
  public/weeklyfeed.json
"""

import os
import re
import json
import time
import math
import zoneinfo
import datetime as dt
from typing import Dict, Any, Tuple, List

import requests
from bs4 import BeautifulSoup

# ---------- Config ----------
APP_TZ = os.getenv("APP_TZ", "America/New_York")
TZ = zoneinfo.ZoneInfo(APP_TZ)

USCCB_STRICT = os.getenv("USCCB_STRICT", "0") == "1"

GEN_MODEL = os.getenv("GEN_MODEL", "gpt-5-mini")
GEN_FALLBACK = os.getenv("GEN_FALLBACK", "gpt-5-mini")
GEN_TEMP = float(os.getenv("GEN_TEMP", "0.60"))
GEN_TEMP_REPAIR = float(os.getenv("GEN_TEMP_REPAIR", "0.55"))
GEN_TEMP_QUOTE = float(os.getenv("GEN_TEMP_QUOTE", "0.35"))

HEADERS = {
    "User-Agent": "FaithLinksBot/1.0 (+repo automation)",
    "Accept": "text/html,application/xhtml+xml"
}

REF_RE = re.compile(
    r'\b(?:[1-3]\s*)?'
    r'(?:Genesis|Exodus|Leviticus|Numbers|Deuteronomy|Joshua|Judges|Ruth|Samuel|Kings|Chronicles|Ezra|Nehemiah|Tobit|Judith|Esther|Job|Psalms?|Proverbs|Ecclesiastes|Qoheleth|Song(?: of Songs)?|Wisdom|Sirach|Isaiah|Jeremiah|Lamentations|Baruch|Ezekiel|Daniel|Hosea|Joel|Amos|Obadiah|Jonah|Micah|Nahum|Habakkuk|Zephaniah|Haggai|Zechariah|Malachi|Matthew|Mark|Luke|John|Acts|Romans|Corinthians|Galatians|Ephesians|Philippians|Colossians|Thessalonians|Timothy|Titus|Philemon|Hebrews|James|Peter|Jude|Revelation)'
    r'\s+\d+(?::\d+(?:-\d+)?(?:,\s*\d+(?::\d+)?)*)?',
    re.I
)

# ---------- Style card (keeps CCC guidance) ----------
STYLE_CARD = """ROLE: Catholic editor + theologian for FaithLinks.

Audience: teens + adults (high school through adult).

Strict lengths (words):
- quote: 9–25 (1–2 sentences)
- firstReading: 50–100
- secondReading: 50–100 (or empty if no second reading that day)
- psalmSummary: 50–100
- gospelSummary: 100–200
- saintReflection: 50–100
- dailyPrayer: 150–200
- theologicalSynthesis: 150–200
- exegesis: 500–750, 5–6 short paragraphs with brief headings (Context:, Psalm:, Gospel:, Saints:, Today:). Blank lines between paragraphs.

Rules:
- If a SAINT is provided, do not say “no saint today.” Use the provided profile if present; weave feast/memorial naturally.
- Do not paste long Scripture passages; paraphrase faithfully (a short quote in `quote` is fine).
- Warm, pastoral, Christ-centered, accessible; concrete connections for modern life.
- Integrate 1–3 Catechism of the Catholic Church citations (by paragraph number) where relevant—especially in `theologicalSynthesis`, `dailyPrayer`, and `exegesis`. Format (CCC 614). Use real paragraph numbers; if uncertain, prefer foundational anchors (e.g., 136–141 on Scripture; 456–460 on the Incarnation; 1420–1498 on the Sacraments of Healing).
- Return ONLY a JSON object with all contract keys. Include `tags` as 6–12 concise, lowercase, hyphenated topics.
"""

# ---------- Helpers ----------

def log(*args):
    print("[info]", *args, flush=True)

def today_local() -> dt.date:
    return dt.datetime.now(TZ).date()

def daterange(start: dt.date, days: int) -> List[dt.date]:
    return [start + dt.timedelta(days=i) for i in range(days)]

def ymd(d: dt.date) -> str:
    return d.isoformat()

def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

# ---------- Reading scrapers ----------

def _first_three_from_text(text: str) -> Tuple[str, str, str]:
    first = psalm = gospel = ""
    # Try heading splits first
    blocks = re.split(r'(?i)(First Reading|Reading I|Reading 1|Responsorial Psalm|Psalm|Gospel)', text)
    for label, body in zip(blocks[1::2], blocks[2::2]):
        m = REF_RE.search(body or "")
        if not m:
            continue
        ref = m.group(0).strip()
        L = label.lower()
        if "gospel" in L and not gospel:
            gospel = ref
        elif "psalm" in L and not psalm:
            psalm = ref
        elif not first:
            first = ref
    # Fill gaps with first 3 refs found anywhere
    if not (first and psalm and gospel):
        found = []
        for m in REF_RE.finditer(text):
            val = m.group(0).strip()
            if val not in found:
                found.append(val)
            if len(found) >= 3:
                break
        if not first and len(found) >= 1: first = found[0]
        if not psalm and len(found) >= 2: psalm = found[1]
        if not gospel and len(found) >= 3: gospel = found[2]
    # Clean psalm duplicates
    if psalm:
        parts = [p.strip() for p in re.split(r'[;,]\s*', psalm) if p.strip()]
        psalm = ', '.join(dict.fromkeys(parts))
    return first or "", psalm or "", gospel or ""

def fetch_readings_usccb(date: dt.date) -> Tuple[str, str, str]:
    url = f"https://bible.usccb.org/bible/readings/{date.strftime('%m%d%y')}.cfm"
    r = requests.get(url, headers=HEADERS, timeout=25)
    if r.status_code != 200:
        raise RuntimeError("USCCB status != 200")
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    return _first_three_from_text(text)

def fetch_readings_ewtn(date: dt.date) -> Tuple[str, str, str]:
    # EWTN page contains today's readings; archive structure varies.
    # We still extract refs by regex (robust to layout).
    url = "https://www.ewtn.com/catholicism/daily-readings"
    r = requests.get(url, headers=HEADERS, timeout=25)
    if r.status_code != 200:
        raise RuntimeError("EWTN status != 200")
    soup = BeautifulSoup(r.text, "html.parser")
    # Try to narrow by human-readable label (e.g., "October 14")
    label = date.strftime("%B %-d").replace(" 0", " ")
    node_text = ""
    for el in soup.find_all(text=re.compile(label, re.I)):
        try:
            node_text = el.parent.get_text(" ", strip=True)
            break
        except Exception:
            pass
    text = node_text or soup.get_text(" ", strip=True)
    return _first_three_from_text(text)

def resolve_readings(date: dt.date) -> Tuple[str, str, str]:
    f = p = g = ""
    try:
        f, p, g = fetch_readings_usccb(date)
        if f and p and g:
            return f, p, g
    except Exception as e:
        log("USCCB fetch issue", ymd(date), str(e))
    try:
        f2, p2, g2 = fetch_readings_ewtn(date)
        f = f or f2; p = p or p2; g = g or g2
    except Exception as e:
        log("EWTN fetch issue", ymd(date), str(e))
    return f or "", p or "", g or ""

# ---------- Saints ----------

def saint_from_local(date: dt.date) -> Dict[str, Any]:
    saints = load_json("public/saint.json", [])
    bydate = {row.get("date"): row for row in saints if isinstance(row, dict)}
    return (bydate.get(ymd(date)) or {}).copy()

def guess_saint_vaticannews(date: dt.date) -> str:
    # Soft guess: try to find a saint title near the date on Vatican News saints index.
    try:
        url = "https://www.vaticannews.va/en/saints.html"
        r = requests.get(url, headers=HEADERS, timeout=25)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        label = date.strftime("%B %-d").replace(" 0", " ")
        for el in soup.find_all(text=re.compile(label, re.I)):
            a = el.find_parent().find("a")
            if a and a.get_text(strip=True):
                return a.get_text(strip=True)
    except Exception:
        pass
    return ""

# ---------- OpenAI generation ----------

def openai_client():
    # Minimal client (works with openai>=1.0)
    from openai import OpenAI
    project = os.getenv("OPENAI_PROJECT", None)
    if project:
        return OpenAI(project=project)
    return OpenAI()

def gen_json(client, sys_msg: str, user_lines: List[str], temp: float) -> Dict[str, Any]:
    msg = [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": "\n".join(user_lines)}
    ]
    try:
        r = client.chat.completions.create(
            model=GEN_MODEL,
            temperature=temp,
            messages=msg,
            response_format={"type": "json_object"},
        )
    except Exception:
        # fallback
        r = client.chat.completions.create(
            model=GEN_FALLBACK,
            temperature=temp,
            messages=msg,
            response_format={"type": "json_object"},
        )
    content = r.choices[0].message.content
    return json.loads(content)

# ---------- Contract builder per day ----------

def build_day_payload(date: dt.date) -> Dict[str, Any]:
    iso = ymd(date)
    usccb_link = f"https://bible.usccb.org/bible/readings/{date.strftime('%m%d%y')}.cfm"

    first_ref, psalm_ref, gospel_ref = resolve_readings(date)

    # Optional overrides file
    overrides = load_json("public/readings-overrides.json", {})
    over = overrides.get(iso, {})
    first_ref = first_ref or over.get("firstRef", "")
    psalm_ref = psalm_ref or over.get("psalmRef", "")
    gospel_ref = gospel_ref or over.get("gospelRef", "")

    missing = [k for k,v in {"first": first_ref, "psalm": psalm_ref, "gospel": gospel_ref}.items() if not v]
    if missing:
        msg = f"readings incomplete for {iso}: missing {', '.join(missing)} (USCCB/EWTN tried)"
        if USCCB_STRICT:
            raise SystemExit(msg)
        log("[warn]", msg)

    saint = saint_from_local(date)
    if not saint.get("saintName"):
        guess = guess_saint_vaticannews(date)
        if guess:
            saint["saintName"] = guess
            saint.setdefault("source", "Vatican News")

    # Lite lectionary keys (best effort)
    cycle = f"Year { 'A' }"   # keep simple; can be computed if you prefer
    weekday_cycle = f"Cycle { 'I' }"
    feast = saint.get("memorial", "")

    # Build user prompt
    user_lines = [
        f"DATE: {iso}",
        f"USCCB_LINK: {usccb_link}",
        "CCC: https://usccb.cld.bz/Catechism-of-the-Catholic-Church",
        f"FIRST_READING_REF: {first_ref}",
        f"PSALM_REF: {psalm_ref}",
        f"GOSPEL_REF: {gospel_ref}",
        f"SAINT_NAME: {saint.get('saintName','')}",
        f"SAINT_MEMORIAL: {saint.get('memorial','')}",
        f"SAINT_PROFILE: {saint.get('profile','')}",
        f"SAINT_LINK: {saint.get('link','')}",
        "RETURN: JSON with keys [date, quote, quoteCitation, firstReading, secondReading, psalmSummary, gospelSummary, saintReflection, dailyPrayer, theologicalSynthesis, exegesis, secondReading (string even if empty), tags, usccbLink, cycle, weekdayCycle, feast, gospelReference, firstReadingRef, secondReadingRef, psalmRef, gospelRef, lectionaryKey]."
    ]

    client = openai_client()
    out = gen_json(client, STYLE_CARD, user_lines, GEN_TEMP)

    # Fill required metadata fields the model might not set
    out.setdefault("date", iso)
    out.setdefault("usccbLink", usccb_link)
    out.setdefault("firstReadingRef", first_ref)
    out.setdefault("psalmRef", psalm_ref)
    out.setdefault("gospelRef", gospel_ref)
    out.setdefault("secondReadingRef", out.get("secondReadingRef",""))  # may be empty
    out.setdefault("gospelReference", gospel_ref)  # keep both keys your validator expects
    out.setdefault("cycle", cycle)
    out.setdefault("weekdayCycle", weekday_cycle)
    out.setdefault("feast", feast)
    out.setdefault("lectionaryKey", f"{iso}:{first_ref}|{psalm_ref}|{gospel_ref}")

    # Ensure secondReading exists as a string
    if "secondReading" not in out or out["secondReading"] is None:
        out["secondReading"] = ""

    # Basic sanity on tags
    tags = out.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    out["tags"] = [str(t).strip().lower().replace(" ", "-")[:32] for t in tags][:12]

    return out

# ---------- Main ----------

def main():
    start_env = os.getenv("START_DATE", "").strip()
    days = int(os.getenv("DAYS", "7"))
    if start_env:
        y, m, d = map(int, start_env.split("-"))
        start = dt.date(y, m, d)
    else:
        start = today_local()

    dates = daterange(start, days)
    log(f"tz={APP_TZ} start={start} days={days} model={GEN_MODEL}")

    rows = []
    for d in dates:
        t0 = time.time()
        row = build_day_payload(d)
        rows.append(row)
        # polite pacing to avoid rate-limits / scraping blocks
        elapsed = time.time() - t0
        if elapsed < 0.7:
            time.sleep(0.7 - elapsed)

    os.makedirs("public", exist_ok=True)
    with open("public/weeklyfeed.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    log(f"Wrote public/weeklyfeed.json ({len(rows)} days)")

if __name__ == "__main__":
    main()
