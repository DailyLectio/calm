#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generate weeklyfeed.json for FaithLinks with:
- USCCB → EWTN fallback for readings
- CCC-aware prompts
- Sunday second-reading enforcement
- Full key + type normalization to satisfy jq validation

ENV:
  START_DATE=YYYY-MM-DD   (default: today in APP_TZ)
  DAYS=7                  (default: 7)
  APP_TZ=America/New_York
  USCCB_STRICT=0          (set 1 to fail if readings incomplete after fallbacks)
  GEN_MODEL=gpt-5-mini
  GEN_FALLBACK=gpt-5-mini
  GEN_TEMP=1
  GEN_TEMP_REPAIR=1
  GEN_TEMP_QUOTE=1
  OPENAI_API_KEY, OPENAI_PROJECT

Reads:
  public/saint.json                (optional; curated saints)
  public/readings-overrides.json   (optional; refs overrides by date)

Writes:
  public/weeklyfeed.json
"""

import os, re, json, time, zoneinfo, datetime as dt
from typing import Dict, Any, Tuple, List
import requests
from bs4 import BeautifulSoup

# ---------- Config ----------
APP_TZ = os.getenv("APP_TZ", "America/New_York")
TZ = zoneinfo.ZoneInfo(APP_TZ)
USCCB_STRICT = os.getenv("USCCB_STRICT", "0") == "1"

GEN_MODEL = os.getenv("GEN_MODEL", "gpt-5-mini")
GEN_FALLBACK = os.getenv("GEN_FALLBACK", "gpt-5-mini")
GEN_TEMP = float(os.getenv("GEN_TEMP", "1"))
GEN_TEMP_REPAIR = float(os.getenv("GEN_TEMP_REPAIR", "1"))
GEN_TEMP_QUOTE = float(os.getenv("GEN_TEMP_QUOTE", "1"))

HEADERS = {
    "User-Agent": "FaithLinksBot/1.3 (+github actions)",
    "Accept": "text/html,application/xhtml+xml",
}

# Bible reference regex
REF_RE = re.compile(
    r'\b(?:[1-3]\s*)?'
    r'(?:Genesis|Exodus|Leviticus|Numbers|Deuteronomy|Joshua|Judges|Ruth|Samuel|Kings|Chronicles|Ezra|Nehemiah|Tobit|Judith|Esther|Job|Psalms?|Proverbs|Ecclesiastes|Qoheleth|Song(?: of Songs)?|Wisdom|Sirach|Isaiah|Jeremiah|Lamentations|Baruch|Ezekiel|Daniel|Hosea|Joel|Amos|Obadiah|Jonah|Micah|Nahum|Habakkuk|Zephaniah|Haggai|Zechariah|Malachi|Matthew|Mark|Luke|John|Acts|Romans|Corinthians|Galatians|Ephesians|Philippians|Colossians|Thessalonians|Timothy|Titus|Philemon|Hebrews|James|Peter|Jude|Revelation)'
    r'\s+\d+(?::\d+(?:-\d+)?(?:,\s*\d+(?::\d+)?)*)?',
    re.I,
)

STYLE_CARD = """ROLE: Catholic editor + theologian for FaithLinks.

Audience: teens + adults (high school through adult).

Strict lengths (words):
- quote: 9–25 (1–2 sentences)
- firstReading: 50–100
- secondReading: 50–100 (if a second reading is present that day; otherwise return empty string)
- psalmSummary: 50–100
- gospelSummary: 100–200
- saintReflection: 50–100
- dailyPrayer: 150–200
- theologicalSynthesis: 150–200
- exegesis: 500–750, 5–6 short paragraphs with headings (Context:, Psalm:, Gospel:, Saints:, Today:). Blank lines between paragraphs.

Rules:
- If SAINT is provided, do not say “no saint today.” Use the profile if present; weave feast/memorial naturally.
- Do not paste long Scripture passages; paraphrase faithfully (a short quote in `quote` is fine).
- Warm, pastoral, Christ-centered, accessible; concrete connections for modern life.
- Integrate 1–3 Catechism of the Catholic Church citations (by paragraph number) where relevant—especially in `theologicalSynthesis`, `dailyPrayer`, and `exegesis`. Format them like (CCC 614).
- If SECOND_READING_REF is provided (typical Sundays/solemnities), you MUST:
  1) Fill the `secondReading` field (50–100 words).
  2) Explicitly connect it with the other readings in `theologicalSynthesis` and `exegesis`.
- Return ONLY a JSON object with the contract keys. Include `tags` as 6–12 concise, lowercase, hyphenated topics.
"""

# ---------- Utils ----------
def _s(x: object) -> str:
    """Coerce to string for jq-safe JSON (no nulls)."""
    return x if isinstance(x, str) else ("" if x is None else str(x))

def log(*a): print("[info]", *a, flush=True)
def today_local() -> dt.date: return dt.datetime.now(TZ).date()
def ymd(d: dt.date) -> str: return d.isoformat()
def daterange(start: dt.date, days: int) -> List[dt.date]: return [start + dt.timedelta(days=i) for i in range(days)]

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

# ---------- Reading scrapers ----------
_HEADING_SPLIT = re.compile(r'(?i)(First Reading|Reading I|Reading 1|Second Reading|Reading II|Reading 2|Responsorial Psalm|Psalm|Gospel)')

def _four_refs_from_text(text: str) -> Tuple[str, str, str, str]:
    """Best-effort reading refs using headings; fallback to first four matches."""
    first = second = psalm = gospel = ""
    blocks = _HEADING_SPLIT.split(text)
    for label, body in zip(blocks[1::2], blocks[2::2]):
        m = REF_RE.search(body or "")
        if not m:
            continue
        ref = m.group(0).strip()
        L = label.lower()
        if "gospel" in L and not gospel: gospel = ref
        elif "second" in L and not second: second = ref
        elif "psalm" in L and not psalm: psalm = ref
        elif not first: first = ref
    if not (first and psalm and gospel):
        found = []
        for m in REF_RE.finditer(text):
            val = m.group(0).strip()
            if val not in found:
                found.append(val)
            if len(found) >= 4:
                break
        if not first and len(found) >= 1: first = found[0]
        if not second and len(found) >= 2: second = found[1]
        if not psalm and len(found) >= 3: psalm = found[2]
        if not gospel and len(found) >= 4: gospel = found[3]
    if psalm:
        parts = [p.strip() for p in re.split(r'[;,]\s*', psalm) if p.strip()]
        psalm = ', '.join(dict.fromkeys(parts))
    return first or "", second or "", psalm or "", gospel or ""

def fetch_readings_usccb(date: dt.date) -> Tuple[str, str, str, str]:
    url = f"https://bible.usccb.org/bible/readings/{date.strftime('%m%d%y')}.cfm"
    r = requests.get(url, headers=HEADERS, timeout=25)
    if r.status_code != 200: raise RuntimeError("USCCB status != 200")
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    return _four_refs_from_text(text)

def fetch_readings_ewtn(date: dt.date) -> Tuple[str, str, str, str]:
    url = "https://www.ewtn.com/catholicism/daily-readings"
    r = requests.get(url, headers=HEADERS, timeout=25)
    if r.status_code != 200: raise RuntimeError("EWTN status != 200")
    soup = BeautifulSoup(r.text, "html.parser")
    label = date.strftime("%B %-d").replace(" 0", " ")
    node_text = ""
    for el in soup.find_all(text=re.compile(label, re.I)):
        try:
            node_text = el.parent.get_text(" ", strip=True)
            break
        except Exception:
            pass
    text = node_text or soup.get_text(" ", strip=True)
    return _four_refs_from_text(text)

def resolve_readings(date: dt.date) -> Tuple[str, str, str, str]:
    f = s = p = g = ""
    try:
        f, s, p, g = fetch_readings_usccb(date)
        if f and p and g:
            return f, s, p, g
    except Exception as e:
        log("USCCB fetch issue", ymd(date), str(e))
    try:
        f2, s2, p2, g2 = fetch_readings_ewtn(date)
        f = f or f2; s = s or s2; p = p or p2; g = g or g2
    except Exception as e:
        log("EWTN fetch issue", ymd(date), str(e))
    return f or "", s or "", p or "", g or ""

# ---------- Saints ----------
def saint_from_local(date: dt.date) -> Dict[str, Any]:
    saints = load_json("public/saint.json", [])
    bydate = {row.get("date"): row for row in saints if isinstance(row, dict)}
    return (bydate.get(ymd(date)) or {}).copy()

def guess_saint_vaticannews(date: dt.date) -> str:
    try:
        url = "https://www.vaticannews.va/en/saints.html"
        r = requests.get(url, headers=HEADERS, timeout=25)
        if r.status_code != 200: return ""
        soup = BeautifulSoup(r.text, "html.parser")
        label = date.strftime("%B %-d").replace(" 0", " ")
        for el in soup.find_all(text=re.compile(label, re.I)):
            a = el.find_parent().find("a")
            if a and a.get_text(strip=True):
                return a.get_text(strip=True)
    except Exception:
        pass
    return ""

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
        if use_temp:
            kwargs["temperature"] = temp
        return client.chat.completions.create(**kwargs)
    try:
        try:
            r = _create(GEN_MODEL, True)
        except BadRequestError as e:
            if "temperature" in str(e).lower():
                r = _create(GEN_MODEL, False)  # retry without temperature
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

# ---------- Build day ----------
def is_sunday(d: dt.date) -> bool: return d.weekday() == 6

def build_day_payload(date: dt.date) -> Dict[str, Any]:
    iso = ymd(date)
    usccb_link = f"https://bible.usccb.org/bible/readings/{date.strftime('%m%d%y')}.cfm"

    first_ref, second_ref, psalm_ref, gospel_ref = resolve_readings(date)

    overrides = load_json("public/readings-overrides.json", {})
    over = overrides.get(iso, {})
    first_ref  = first_ref  or over.get("firstRef", "")
    second_ref = second_ref or over.get("secondRef", "")
    psalm_ref  = psalm_ref  or over.get("psalmRef", "")
    gospel_ref = gospel_ref or over.get("gospelRef", "")

    needed = ["first","psalm","gospel"]
    if is_sunday(date): needed.append("second")
    miss = [k for k,v in {"first":first_ref,"second":second_ref,"psalm":psalm_ref,"gospel":gospel_ref}.items() if (k in needed and not v)]
    if miss:
        msg = f"readings incomplete for {iso}: missing {', '.join(miss)} (after USCCB/EWTN)"
        if USCCB_STRICT: raise SystemExit(msg)
        log("[warn]", msg)

    saint = saint_from_local(date)
    if not saint.get("saintName"):
        guess = guess_saint_vaticannews(date)
        if guess:
            saint["saintName"] = guess
            saint.setdefault("source", "Vatican News")

    # Basic placeholders (fine for validator; replace if you compute precisely elsewhere)
    cycle = "Year C"
    weekday_cycle = "Cycle I"

    feast = (saint.get("memorial") or "")
    force_second = bool(second_ref) or is_sunday(date)

    user_lines = [
        f"DATE: {iso}",
        f"USCCB_LINK: {usccb_link}",
        "CCC: https://usccb.cld.bz/Catechism-of-the-Catholic-Church",
        f"FIRST_READING_REF: {first_ref}",
        f"SECOND_READING_REF: {second_ref}",
        f"PSALM_REF: {psalm_ref}",
        f"GOSPEL_REF: {gospel_ref}",
        f"SUNDAY_OR_HAS_SECOND: {force_second}",
        f"SAINT_NAME: {saint.get('saintName','')}",
        f"SAINT_MEMORIAL: {saint.get('memorial','')}",
        f"SAINT_PROFILE: {saint.get('profile','')}",
        f"SAINT_LINK: {saint.get('link','')}",
        "RETURN: JSON with keys [date, quote, quoteCitation, firstReading, secondReading, psalmSummary, gospelSummary, saintReflection, dailyPrayer, theologicalSynthesis, exegesis, tags, usccbLink, cycle, weekdayCycle, feast, gospelReference, firstReadingRef, secondReadingRef, psalmRef, gospelRef, lectionaryKey]."
    ]

    client = openai_client()
    out = gen_json(client, STYLE_CARD, user_lines, GEN_TEMP)

    # Required metadata
    out.setdefault("date", iso)
    out.setdefault("usccbLink", usccb_link)
    out.setdefault("firstReadingRef", first_ref)
    out.setdefault("secondReadingRef", second_ref)
    out.setdefault("psalmRef", psalm_ref)
    out.setdefault("gospelRef", gospel_ref)
    out.setdefault("gospelReference", gospel_ref)
    out.setdefault("cycle", cycle)
    out.setdefault("weekdayCycle", weekday_cycle)
    out.setdefault("feast", feast)
    # If you prefer the lectionary key format without date, use the 2nd line:
    out.setdefault("lectionaryKey", f"{iso}:{first_ref}|{second_ref}|{psalm_ref}|{gospel_ref}")
    # out.setdefault("lectionaryKey", f"{first_ref}|{psalm_ref}|{gospel_ref}|{cycle}|{weekday_cycle}")

    # Enforce presence/emptiness for second reading
    if not force_second:
        out["secondReading"] = out.get("secondReading") or ""
    else:
        if not isinstance(out.get("secondReading"), str) or not out["secondReading"].strip():
            out["secondReading"] = "(Second Reading summary: to be completed.)"

    # Normalize required fields to strings for jq
    string_keys = [
        "date","quote","quoteCitation","firstReading","secondReading",
        "psalmSummary","gospelSummary","saintReflection","dailyPrayer",
        "theologicalSynthesis","exegesis","usccbLink","cycle","weekdayCycle",
        "feast","gospelReference","firstReadingRef","secondReadingRef","psalmRef",
        "gospelRef","lectionaryKey"
    ]
    for k in string_keys:
        out[k] = _s(out.get(k, ""))

    tags = out.get("tags", [])
    if not isinstance(tags, list): tags = []
    out["tags"] = [str(t).strip().lower().replace(" ", "-")[:32] for t in tags][:12]

    return out

# Final normalize (belt and suspenders)
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
    start_env = os.getenv("START_DATE","").strip()
    days = int(os.getenv("DAYS","7"))
    start = dt.date(*map(int, start_env.split("-"))) if start_env else today_local()

    log(f"tz={APP_TZ} start={start} days={days} model={GEN_MODEL}")
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
