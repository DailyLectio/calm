#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generate weeklyfeed.json for FaithLinks with:
- USCCB readings (primary) and optional EWTN fallback
- STRICT slotting: Psalm must be Ps/Psalm/Psalms; Alleluia never becomes Psalm
- Second reading only when actually present (or valid Sunday/solemnity with a found ref)
- Proper liturgical cycle strings to satisfy your validator

ENV:
  START_DATE=YYYY-MM-DD
  DAYS=7
  APP_TZ=America/New_York
  USCCB_STRICT=0          (1 = fail job if any required reading missing)
  USE_EWTN_FALLBACK=0
  GEN_MODEL=gpt-5-mini
  GEN_FALLBACK=gpt-5-mini
  GEN_TEMP=1
  OPENAI_API_KEY, OPENAI_PROJECT
"""

import os, re, json, time, zoneinfo, datetime as dt
from typing import Dict, Any, Tuple, List
import requests
from bs4 import BeautifulSoup

# ---------- Config ----------
APP_TZ = os.getenv("APP_TZ", "America/New_York")
TZ = zoneinfo.ZoneInfo(APP_TZ)
USCCB_STRICT = os.getenv("USCCB_STRICT", "0") == "1"
USE_EWTN_FALLBACK = os.getenv("USE_EWTN_FALLBACK", "0") == "1"

GEN_MODEL = os.getenv("GEN_MODEL", "gpt-5-mini")
GEN_FALLBACK = os.getenv("GEN_FALLBACK", "gpt-5-mini")
GEN_TEMP = float(os.getenv("GEN_TEMP", "1"))

HEADERS = {
    "User-Agent": "FaithLinksBot/1.5 (+github actions)",
    "Accept": "text/html,application/xhtml+xml",
}

# ---------- Helpers ----------
def _s(x: object) -> str:
    return x if isinstance(x, str) else ("" if x is None else str(x))

def log(*a): print("[info]", *a, flush=True)
def today_local() -> dt.date: return dt.datetime.now(TZ).date()
def ymd(d: dt.date) -> str: return d.isoformat()
def daterange(start: dt.date, days: int) -> List[dt.date]:
    return [start + dt.timedelta(days=i) for i in range(days)]
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default
def is_sunday(d: dt.date) -> bool: return d.weekday() == 6

# ---------- Liturgical cycles ----------
def _first_sunday_of_advent(year: int) -> dt.date:
    # Advent starts on the 4th Sunday before Christmas
    christmas = dt.date(year, 12, 25)
    # find the Sunday before (or on) Nov 30 (St. Andrew) — common practical approach
    d = dt.date(year, 11, 30)
    while d.weekday() != 6:
        d -= dt.timedelta(days=1)
    # that's the Sunday nearest Nov 30; Advent starts the following Sunday
    return d + dt.timedelta(days=7)

def compute_year_cycle(d: dt.date) -> str:
    # Roman lectionary Year A (Mt), B (Mk), C (Lk), cycling at Advent
    # Year A starts Advent 2019, 2022, 2025... i.e., (year+1) % 3 mapping
    y = d.year
    advent = _first_sunday_of_advent(y)
    lit_year = y + 1 if d >= advent else y
    idx = (lit_year - 2019) % 3  # 0=A,1=B,2=C with 2019 Advent = A
    return ["Year A", "Year B", "Year C"][idx]

def compute_weekday_cycle(d: dt.date) -> str:
    # Weekday cycle I on odd-numbered years, II on even (changes on Jan 1)
    return "Cycle I" if d.year % 2 == 1 else "Cycle II"

# ---------- Parsing ----------
# General Scripture ref (full names)
REF_RE = re.compile(
    r'\b(?:[1-3]\s*)?'
    r'(?:Genesis|Exodus|Leviticus|Numbers|Deuteronomy|Joshua|Judges|Ruth|Samuel|Kings|Chronicles|Ezra|Nehemiah|Tobit|Judith|Esther|Job|Psalms?|Proverbs|Ecclesiastes|Qoheleth|Song(?: of Songs)?|Wisdom|Sirach|Isaiah|Jeremiah|Lamentations|Baruch|Ezekiel|Daniel|Hosea|Joel|Amos|Obadiah|Jonah|Micah|Nahum|Habakkuk|Zephaniah|Haggai|Zechariah|Malachi|Matthew|Mark|Luke|John|Acts|Romans|Corinthians|Galatians|Ephesians|Philippians|Colossians|Thessalonians|Timothy|Titus|Philemon|Hebrews|James|Peter|Jude|Revelation)'
    r'\s+\d+(?::\d+(?:-\d+)?(?:,\s*\d+(?::\d+)?)*)?',
    re.I,
)

# Psalm-specific ref (accepts Ps / Psalm / Psalms)
PSALM_REF_RE = re.compile(
    r'^(?:Ps|Psalm|Psalms)\s+\d+(?::\d+[a-z]*?(?:-\d+)?(?:,\s*\d+[a-z]*?(?:-\d+)?)*)?',
    re.I
)

_HEADING_SPLIT = re.compile(
    r'(?i)(First Reading|Reading I|Reading 1|Second Reading|Reading II|Reading 2|Responsorial Psalm|Psalm|Alleluia|Gospel)'
)

def _extract_first_ref(text: str) -> str:
    m = REF_RE.search(text or "")
    return m.group(0).strip() if m else ""

def _extract_psalm_ref(text: str) -> str:
    # Prefer an explicit Psalm-looking citation; if none, allow general ref that looks like Psalm
    text = text or ""
    # quick pass: direct "Ps 131:..." etc.
    m = re.search(r'(?:^|\s)(Ps(?:alm|alms)?\s+\d+(?::\d+[a-z]*?(?:-\d+)?(?:,\s*\d+[a-z]*?(?:-\d+)?)*)?)', text, re.I)
    if m:
        return m.group(1).strip()
    # fallback: find any ref in text and keep it only if it starts like Psalm
    r = _extract_first_ref(text)
    return r if PSALM_REF_RE.match(r) else ""

def _parse_usccb_text(page_text: str, *, sunday_or_solemnity: bool) -> Tuple[str, str, str, str]:
    first = second = psalm = gospel = ""
    saw_second_heading = False

    blocks = _HEADING_SPLIT.split(page_text or "")
    for label, body in zip(blocks[1::2], blocks[2::2]):
        L = (label or "").strip().lower()
        b = body or ""
        if "gospel" in L and not gospel:
            ref = _extract_first_ref(b)
            if ref: gospel = ref
        elif ("responsorial psalm" in L or L.startswith("psalm")) and not psalm:
            ref = _extract_psalm_ref(b)
            if ref: psalm = ref
        elif "alleluia" in L:
            # never slots anywhere
            pass
        elif ("second reading" in L or "reading ii" in L or "reading 2" in L) and not second:
            ref = _extract_first_ref(b)
            if ref:
                second = ref
                saw_second_heading = True
        elif ("first reading" in L or "reading i" in L or "reading 1" in L) and not first:
            ref = _extract_first_ref(b)
            if ref: first = ref

    # Psalm normalization (dedupe punctuation)
    if psalm:
        parts = [p.strip() for p in re.split(r'[;,]\s*', psalm) if p.strip()]
        psalm = ", ".join(dict.fromkeys(parts))

    # Only keep a second reading if heading present OR sunday/solemnity (with an actual ref)
    if not saw_second_heading and not sunday_or_solemnity:
        second = ""

    return first or "", second or "", psalm or "", gospel or ""

def fetch_readings_usccb(date: dt.date) -> Tuple[str, str, str, str]:
    url = f"https://bible.usccb.org/bible/readings/{date.strftime('%m%d%y')}.cfm"
    r = requests.get(url, headers=HEADERS, timeout=25)
    if r.status_code != 200:
        raise RuntimeError("USCCB status != 200")
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    return _parse_usccb_text(text, sunday_or_solemnity=is_sunday(date))

def fetch_readings_ewtn(date: dt.date) -> Tuple[str, str, str, str]:
    url = "https://www.ewtn.com/catholicism/daily-readings"
    r = requests.get(url, headers=HEADERS, timeout=25)
    if r.status_code != 200:
        raise RuntimeError("EWTN status != 200")
    soup = BeautifulSoup(r.text, "html.parser")
    label = date.strftime("%B %-d").replace(" 0", " ")
    node_text = ""
    for el in soup.find_all(text=re.compile(label, re.I)):
        try:
            node_text = el.parent.get_text(" ", strip=True); break
        except Exception:
            pass
    text = node_text or soup.get_text(" ", strip=True)
    return _parse_usccb_text(text, sunday_or_solemnity=is_sunday(date))

def resolve_readings(date: dt.date) -> Tuple[str, str, str, str]:
    f = s = p = g = ""
    try:
        f, s, p, g = fetch_readings_usccb(date)
    except Exception as e:
        log("USCCB fetch issue", ymd(date), str(e))

    if USE_EWTN_FALLBACK and (not f or not p or not g):
        try:
            f2, s2, p2, g2 = fetch_readings_ewtn(date)
            f = f or f2
            if not p and p2: p = p2
            g = g or g2
            if not s and s2: s = s2
        except Exception as e:
            log("EWTN fetch issue", ymd(date), str(e))

    # Hard guards
    if p and not PSALM_REF_RE.match(p):
        log("psalm rejected:", p); p = ""
    if s and (s == f or s == g or PSALM_REF_RE.match(s) or s.startswith(("Matthew","Mark","Luke","John"))):
        s = ""

    return f or "", s or "", p or "", g or ""

# ---------- Saints (minimal) ----------
def saint_from_local(date: dt.date) -> Dict[str, Any]:
    saints = load_json("public/saint.json", [])
    bydate = {row.get("date"): row for row in saints if isinstance(row, dict)}
    return (bydate.get(ymd(date)) or {}).copy()

# ---------- OpenAI ----------
def openai_client():
    from openai import OpenAI
    project = os.getenv("OPENAI_PROJECT") or None
    return OpenAI(project=project) if project else OpenAI()

def gen_json(client, sys_msg: str, user_lines: List[str], temp: float) -> Dict[str, Any]:
    from openai import BadRequestError
    messages = [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": "\n".join(user_lines)},
    ]
    def _create(model: str, use_temp: bool):
        kwargs = {"model": model, "messages": messages, "response_format": {"type": "json_object"}}
        if use_temp: kwargs["temperature"] = temp
        return client.chat.completions.create(**kwargs)
    try:
        try:
            r = _create(GEN_MODEL, True)
        except BadRequestError as e:
            if "temperature" in str(e).lower():
                r = _create(GEN_MODEL, False)
            else:
                raise
    except Exception:
        try:
            r = _create(GEN_FALLBACK, True)
        except BadRequestError as e2:
            if "temperature" in str(e2).lower():
                r = _create(GEN_FALLBACK, False)
            else:
                raise
    return json.loads(r.choices[0].message.content)

# ---------- Prompt (tight) ----------
STYLE_CARD = """ROLE: Catholic editor & theologian for FaithLinks.

RULES:
- Use the exact references I provide. Do not invent or swap them.
- If SECOND_READING_REF is empty, `secondReading` MUST be "".
- Never treat the Alleluia as the Psalm.
- Summarize Scripture; ≤10 quoted words total.
- Output only JSON with the contract keys.

LENGTHS (words):
- quote 9–25; firstReading 50–100; secondReading 0 or 50–100; psalmSummary 50–100; gospelSummary 100–200;
- saintReflection 50–100; dailyPrayer 150–200; theologicalSynthesis 150–200;
- exegesis 500–750 in 5–6 short paragraphs (Context:, Psalm:, Gospel:, Saints:, Today:).
"""

# ---------- Build day ----------
def build_day_payload(date: dt.date) -> Dict[str, Any]:
    iso = ymd(date)
    usccb_link = f"https://bible.usccb.org/bible/readings/{date.strftime('%m%d%y')}.cfm"

    first_ref, second_ref, psalm_ref, gospel_ref = resolve_readings(date)

    # Overrides (optional)
    overrides = load_json("public/readings-overrides.json", {})
    over = overrides.get(iso, {})
    first_ref  = over.get("firstRef",  first_ref)
    second_ref = over.get("secondRef", second_ref)
    psalm_ref  = over.get("psalmRef",  psalm_ref)
    gospel_ref = over.get("gospelRef", gospel_ref)

    # Required presence
    needs = ["first","psalm","gospel"]
    if is_sunday(date): needs.append("second")
    missing = [k for k,v in {"first":first_ref,"psalm":psalm_ref,"gospel":gospel_ref,"second":second_ref}.items()
               if (k in needs and not v)]
    if missing:
        msg = f"{iso} missing: {', '.join(missing)}"
        if USCCB_STRICT: raise SystemExit(msg)
        log("warn:", msg)

    saint = saint_from_local(date)
    feast = (saint.get("memorial") or "")

    lines = [
        f"DATE: {iso}",
        f"USCCB_LINK: {usccb_link}",
        f"FIRST_READING_REF: {first_ref}",
        f"SECOND_READING_REF: {second_ref}",  # may be ""
        f"PSALM_REF: {psalm_ref}",
        f"GOSPEL_REF: {gospel_ref}",
        f"SAINT_NAME: {saint.get('saintName','')}",
        f"SAINT_PROFILE: {saint.get('profile','')}",
        "RETURN KEYS: [date, quote, quoteCitation, firstReading, secondReading, psalmSummary, gospelSummary, saintReflection, dailyPrayer, theologicalSynthesis, exegesis, tags, usccbLink, cycle, weekdayCycle, feast, gospelReference, firstReadingRef, secondReadingRef, psalmRef, gospelRef, lectionaryKey]"
    ]

    client = openai_client()
    out = gen_json(client, STYLE_CARD, lines, GEN_TEMP)
    if not isinstance(out, dict): out = {}

    # Authoritative metadata
    out["date"] = iso
    out["usccbLink"] = usccb_link
    out["firstReadingRef"]  = first_ref
    out["secondReadingRef"] = second_ref
    out["psalmRef"]         = psalm_ref
    out["gospelRef"]        = gospel_ref
    out["gospelReference"]  = gospel_ref

    # Proper cycles
    out["cycle"]        = compute_year_cycle(date)
    out["weekdayCycle"] = compute_weekday_cycle(date)
    out["feast"]        = feast

    out["lectionaryKey"] = f"{iso}:{first_ref}|{second_ref}|{psalm_ref}|{gospel_ref}"

    # Enforce empty secondReading if ref empty
    if not _s(second_ref):
        out["secondReading"] = ""

    # Normalize strings
    for k in ["date","quote","quoteCitation","firstReading","secondReading","psalmSummary","gospelSummary",
              "saintReflection","dailyPrayer","theologicalSynthesis","exegesis","usccbLink","cycle","weekdayCycle",
              "feast","gospelReference","firstReadingRef","secondReadingRef","psalmRef","gospelRef","lectionaryKey"]:
        out[k] = _s(out.get(k,""))

    tags = out.get("tags", [])
    if not isinstance(tags, list): tags = []
    out["tags"] = [str(t).strip().lower().replace(" ", "-")[:32] for t in tags][:12]

    return out

# ---------- Final normalize ----------
REQUIRED_STRING_KEYS = [
    "date","quote","quoteCitation","firstReading","secondReading",
    "psalmSummary","gospelSummary","saintReflection","dailyPrayer",
    "theologicalSynthesis","exegesis","usccbLink","cycle","weekdayCycle",
    "feast","gospelReference","firstReadingRef","secondReadingRef",
    "psalmRef","gospelRef","lectionaryKey"
]
def normalize_rows(rows: List[Dict[str,Any]]):
    for row in rows:
        for k in REQUIRED_STRING_KEYS:
            row[k] = _s(row.get(k, ""))
        tags = row.get("tags", [])
        if not isinstance(tags, list): tags = []
        row["tags"] = [str(t).strip().lower().replace(" ", "-")[:32] for t in tags][:12]

# ---------- Main ----------
def main():
    # Optional scrape-only precheck (no OpenAI)
    if os.getenv("USCCB_PRECHECK") == "1":
        start_env = os.getenv("START_DATE","").strip()
        days = int(os.getenv("DAYS","7"))
        start = dt.date(*map(int, start_env.split("-"))) if start_env else today_local()
        for d in daterange(start, days):
            f,s,p,g = resolve_readings(d)
            print("[precheck]", d.isoformat(), "|", f, "|", s or "—", "|", p or "MISSING-PSALM", "|", g, flush=True)
        return

    start_env = os.getenv("START_DATE","").strip()
    days = int(os.getenv("DAYS","7"))
    start = dt.date(*map(int, start_env.split("-"))) if start_env else today_local()

    log(f"tz={APP_TZ} start={start} days={days} model={GEN_MODEL} ewtn_fallback={USE_EWTN_FALLBACK}")
    rows = []
    for d in daterange(start, days):
        t0 = time.time()
        rows.append(build_day_payload(d))
        elapsed = time.time() - t0
        if elapsed < 0.7: time.sleep(0.7 - elapsed)

    normalize_rows(rows)
    os.makedirs("public", exist_ok=True)
    with open("public/weeklyfeed.json","w",encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    log(f"Wrote public/weeklyfeed.json ({len(rows)} days)")

if __name__ == "__main__":
    main()
