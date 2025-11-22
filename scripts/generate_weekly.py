#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generate public/weeklyfeed.json

Strategy (cleaned up):
- USCCB as the single authoritative source for references.
- DOM-based parsing using div.name + div.address (no brittle regex over the page).
- Second reading is present only when USCCB has a "Reading 2 / Reading II" block.
- Saints merged from local + remote URL.
- Proper liturgical cycles (Year A/B/C, Cycle I/II).
- Optional per-date overrides in public/readings-overrides.json.
"""

import os, re, json, time, zoneinfo, datetime as dt
from typing import Dict, Any, Tuple, List
import requests
from bs4 import BeautifulSoup, NavigableString, Tag

# ===== Config =====
APP_TZ = os.getenv("APP_TZ", "America/New_York")
TZ = zoneinfo.ZoneInfo(APP_TZ)

USCCB_STRICT       = os.getenv("USCCB_STRICT", "0") == "1"  # if True, missing core readings will hard-fail
SAINT_JSON_URL     = os.getenv("SAINT_JSON_URL", "https://dailylectio.org/saint.json")

GEN_MODEL          = os.getenv("GEN_MODEL", "gpt-5-mini")
GEN_FALLBACK       = os.getenv("GEN_FALLBACK", "gpt-5-mini")
GEN_TEMP           = float(os.getenv("GEN_TEMP", "1"))

HEADERS = {
    "User-Agent": "FaithLinksBot/1.8 (+github actions)",
    "Accept": "text/html,application/xhtml+xml",
}

# ===== Utils =====
def _s(x: object) -> str:
    return x if isinstance(x, str) else ("" if x is None else str(x))

def log(*a): 
    print("[info]", *a, flush=True)

def today_local() -> dt.date: 
    return dt.datetime.now(TZ).date()

def ymd(d: dt.date) -> str: 
    return d.isoformat()

def daterange(start: dt.date, days: int) -> List[dt.date]:
    return [start + dt.timedelta(days=i) for i in range(days)]

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def is_sunday(d: dt.date) -> bool: 
    return d.weekday() == 6

# ===== Liturgical cycles =====
def _first_sunday_of_advent(year: int) -> dt.date:
    d = dt.date(year, 11, 30)
    while d.weekday() != 6:
        d -= dt.timedelta(days=1)
    return d + dt.timedelta(days=7)

def compute_year_cycle(d: dt.date) -> str:
    y = d.year
    advent = _first_sunday_of_advent(y)
    ly = y + 1 if d >= advent else y
    idx = (ly - 2019) % 3  # 2019 Advent = Year A
    return ["Year A", "Year B", "Year C"][idx]

def compute_weekday_cycle(d: dt.date) -> str:
    return "Cycle I" if d.year % 2 == 1 else "Cycle II"

# ===== USCCB DOM parsing (no page-wide regex) =====

def parse_usccb_dom(html: str, sunday: bool) -> Tuple[str, str, str, str]:
    """
    Parse a USCCB daily readings page using the structural pattern:

      <div class="name">Reading 1</div>
      <div class="address"><a>1 Mc 6:1-13</a></div>

      <div class="name">Responsorial Psalm</div>
      <div class="address"><a>Ps 9:2-3, 4 and 6, 16 and 19</a></div>

      <div class="name">Gospel</div>
      <div class="address"><a>Lk 20:27-40</a></div>

    This does NOT care what the book name is (Psalms, Daniel, 1 Chronicles, etc.).
    It just maps labels -> their next .address sibling.
    """
    soup = BeautifulSoup(html, "html.parser")

    first = ""
    second = ""
    psalm = ""
    gospel = ""

    for name_div in soup.find_all("div", class_="name"):
        label = name_div.get_text(" ", strip=True).lower()
        if not label:
            continue

        addr_div = name_div.find_next_sibling("div", class_="address")
        if not addr_div:
            continue

        ref_text = addr_div.get_text(" ", strip=True)
        if not ref_text:
            continue

        if "reading 1" in label or "reading i" in label:
            first = ref_text
        elif "reading 2" in label or "reading ii" in label:
            second = ref_text
        elif "responsorial psalm" in label or label.startswith("psalm"):
            psalm = ref_text
        elif "gospel" in label:
            gospel = ref_text

    # Weekdays normally do not have a second reading
    if not sunday and not second:
        second = ""

    return first or "", second or "", psalm or "", gospel or ""

def fetch_readings_usccb(date: dt.date) -> Tuple[str, str, str, str]:
    url = f"https://bible.usccb.org/bible/readings/{date.strftime('%m%d%y')}.cfm"
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return parse_usccb_dom(r.text, sunday=is_sunday(date))

def resolve_readings(date: dt.date) -> Tuple[str, str, str, str]:
    """
    Single-source strategy:
      - USCCB only (authoritative structure).
      - If USCCB fails completely, all refs come back "" and the caller decides
        whether to fail the run or log a warning.
    """
    first = second = psalm = gospel = ""

    try:
        first, second, psalm, gospel = fetch_readings_usccb(date)
    except Exception as e:
        log("USCCB fetch issue", ymd(date), e)

    log("resolved", ymd(date), "|",
        "F:", first or "—", "|",
        "S:", second or "—", "|",
        "P:", psalm or "—", "|",
        "G:", gospel or "—")

    return first or "", second or "", psalm or "", gospel or ""

# ===== Saints (merge local + remote) =====
def saints_local() -> List[Dict[str, Any]]:
    return load_json("public/saint.json", [])

def saints_remote() -> List[Dict[str, Any]]:
    try:
        r = requests.get(SAINT_JSON_URL, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        log("saints remote fail:", e)
    return []

def saint_for_date(d: dt.date) -> Dict[str, Any]:
    iso = ymd(d)
    merged: Dict[str, Dict[str, Any]] = {}
    for row in saints_remote() + saints_local():
        if isinstance(row, dict) and row.get("date"):
            merged.setdefault(row["date"], {}).update(row)
    return merged.get(iso, {}).copy()

# ===== OpenAI =====
def openai_client():
    from openai import OpenAI
    project = os.getenv("OPENAI_PROJECT") or None
    return OpenAI(project=project) if project else OpenAI()

def gen_json(client, sys_msg: str, user_lines: List[str], temp: float) -> Dict[str, Any]:
    from openai import BadRequestError
    messages = [
        {"role": "system", "content": sys_msg},
        {"role": "user",   "content": "\n".join(user_lines)},
    ]

    def _create(model, use_temp):
        kw = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        if use_temp:
            kw["temperature"] = temp
        return client.chat.completions.create(**kw)

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

STYLE_CARD = """ROLE: Catholic editor & theologian for FaithLinks.
RULES:
- Use the exact references I provide. Do not invent or swap.
- `firstReading` MUST summarize ONLY FIRST_READING_REF.
- `psalmSummary` MUST summarize ONLY PSALM_REF.
- If SECOND_READING_REF is empty, `secondReading` MUST be "".
- Never treat the Alleluia as the Psalm.
- Summarize Scripture; ≤10 quoted words total.
- Output only JSON with the contract keys.
LENGTHS (words):
- quote 9–25; firstReading 50–100; secondReading 0 or 50–100; psalmSummary 50–100; gospelSummary 100–200;
- saintReflection 50–100; dailyPrayer 150–200; theologicalSynthesis 150–200;
- exegesis 750–1000 in 6–8 short paragraphs (Context:, Psalm:, Gospel:, Saints:, Today:).
"""

# ===== Builder =====
def build_day_payload(date: dt.date) -> Dict[str, Any]:
    iso = ymd(date)
    usccb_link = f"https://bible.usccb.org/bible/readings/{date.strftime('%m%d%y')}.cfm"

    first_ref, second_ref, psalm_ref, gospel_ref = resolve_readings(date)

    # Optional manual overrides
    overrides = load_json("public/readings-overrides.json", {})
    over = overrides.get(iso, {})
    first_ref  = _s(over.get("firstRef",  first_ref))
    second_ref = _s(over.get("secondRef", second_ref))
    psalm_ref  = _s(over.get("psalmRef",  psalm_ref))
    gospel_ref = _s(over.get("gospelRef", gospel_ref))

    # === HARD INVARIANTS ===
    # For your use case, these three must exist and be sane.
    core_missing = []
    if not first_ref:
        core_missing.append("first")
    if not psalm_ref:
        core_missing.append("psalm")
    if not gospel_ref:
        core_missing.append("gospel")

    if core_missing:
        msg = f"{iso}: missing core reading(s): {', '.join(core_missing)}"
        if USCCB_STRICT:
            # Fail the run loudly, as you requested ("if no first reading, call it off").
            raise SystemExit(msg)
        else:
            log("warn:", msg)

    # Second reading is liturgically expected on Sundays/solemnities, but we
    # won't hard-fail if USCCB doesn't show one (there are edge cases).
    if is_sunday(date) and not second_ref:
        log(f"warn: {iso} is Sunday and has no second reading ref")

    saint = saint_for_date(date)
    feast = saint.get("memorial", "")

    lines = [
        f"DATE: {iso}",
        f"USCCB_LINK: {usccb_link}",
        f"FIRST_READING_REF: {first_ref}",
        f"SECOND_READING_REF: {second_ref}",
        f"PSALM_REF: {psalm_ref}",
        f"GOSPEL_REF: {gospel_ref}",
        f"SAINT_NAME: {saint.get('saintName','')}",
        f"SAINT_PROFILE: {saint.get('profile','')}",
        f"SAINT_LINK: {saint.get('link','')}",
        "RETURN KEYS: [date, quote, quoteCitation, firstReading, secondReading, psalmSummary, gospelSummary, saintReflection, dailyPrayer, theologicalSynthesis, exegesis, tags, usccbLink, cycle, weekdayCycle, feast, gospelReference, firstReadingRef, secondReadingRef, psalmRef, gospelRef, lectionaryKey]"
    ]

    client = openai_client()
    out = gen_json(client, STYLE_CARD, lines, GEN_TEMP)
    if not isinstance(out, dict):
        out = {}

    out["date"]             = iso
    out["usccbLink"]        = usccb_link
    out["firstReadingRef"]  = first_ref
    out["secondReadingRef"] = second_ref
    out["psalmRef"]         = psalm_ref
    out["gospelRef"]        = gospel_ref
    out["gospelReference"]  = gospel_ref
    out["cycle"]            = compute_year_cycle(date)
    out["weekdayCycle"]     = compute_weekday_cycle(date)
    out["feast"]            = feast
    out["lectionaryKey"]    = f"{iso}:{first_ref}|{second_ref}|{psalm_ref}|{gospel_ref}"

    if not _s(second_ref):
        out["secondReading"] = ""

    for k in [
        "date","quote","quoteCitation","firstReading","secondReading","psalmSummary",
        "gospelSummary","saintReflection","dailyPrayer","theologicalSynthesis","exegesis",
        "usccbLink","cycle","weekdayCycle","feast","gospelReference",
        "firstReadingRef","secondReadingRef","psalmRef","gospelRef","lectionaryKey"
    ]:
        out[k] = _s(out.get(k, ""))

    tags = out.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    out["tags"] = [str(t).strip().lower().replace(" ", "-")[:32] for t in tags][:12]

    return out

# ===== Final normalize =====
REQ = [
    "date","quote","quoteCitation","firstReading","secondReading","psalmSummary",
    "gospelSummary","saintReflection","dailyPrayer","theologicalSynthesis","exegesis",
    "usccbLink","cycle","weekdayCycle","feast","gospelReference","firstReadingRef",
    "secondReadingRef","psalmRef","gospelRef","lectionaryKey"
]

def normalize_rows(rows: List[Dict[str,Any]]):
    for r in rows:
        for k in REQ:
            r[k] = _s(r.get(k, ""))
        tags = r.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        r["tags"] = [str(t).strip().lower().replace(" ", "-")[:32] for t in tags][:12]

# ===== Main =====
def main():
    # Optional: precheck mode that just prints what we’d use for each date
    if os.getenv("USCCB_PRECHECK") == "1":
        start_env = os.getenv("START_DATE","").strip()
        days = int(os.getenv("DAYS","7"))
        start = dt.date(*map(int, start_env.split("-"))) if start_env else today_local()
        for d in daterange(start, days):
            f, s, p, g = resolve_readings(d)
            print("[precheck]", d.isoformat(), "|",
                  f or "—", "|", s or "—", "|",
                  p or "MISSING-PSALM", "|", g or "—")
        return

    start_env = os.getenv("START_DATE","").strip()
    days = int(os.getenv("DAYS","7"))
    start = dt.date(*map(int, start_env.split("-"))) if start_env else today_local()

    log(f"tz={APP_TZ} start={start} days={days} model={GEN_MODEL}")
    rows: List[Dict[str, Any]] = []

    for d in daterange(start, days):
        t0 = time.time()
        rows.append(build_day_payload(d))
        elapsed = time.time() - t0
        if elapsed < 0.7:
            time.sleep(0.7 - elapsed)

    normalize_rows(rows)
    os.makedirs("public", exist_ok=True)
    with open("public/weeklyfeed.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    log(f"Wrote public/weeklyfeed.json ({len(rows)} days)")

if __name__ == "__main__":
    main()
