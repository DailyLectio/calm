#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generate public/weeklyfeed.json

Fixes:
- Robust Psalm extraction (header-proximity + page-wide fallback).
- Second reading only when truly present (or Sunday + real ref).
- Saints merged from local + remote URL.
- Proper liturgical cycles (Year A/B/C, Cycle I/II).
- CatholicGallery / Catholic.org / EWTN as fallbacks.
- USCCB parsing based on visible headers (Reading I, Responsorial Psalm, Gospel),
  not fragile div.name/div.address structures.
"""

import os, re, json, time, zoneinfo, datetime as dt
from typing import Dict, Any, Tuple, List
import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from collections import Counter

# ===== Config =====
APP_TZ = os.getenv("APP_TZ", "America/New_York")
TZ = zoneinfo.ZoneInfo(APP_TZ)

USCCB_STRICT       = os.getenv("USCCB_STRICT", "0") == "1"
USE_EWTN_FALLBACK  = os.getenv("USE_EWTN_FALLBACK", "1") == "1"   # default ON to be safe
SAINT_JSON_URL     = os.getenv("SAINT_JSON_URL", "https://dailylectio.org/saint.json")

GEN_MODEL          = os.getenv("GEN_MODEL", "gpt-5-mini")
GEN_FALLBACK       = os.getenv("GEN_FALLBACK", "gpt-5-mini")
GEN_TEMP           = float(os.getenv("GEN_TEMP", "1"))

# Use a "real" browser UA to avoid weird mobile/anti-bot versions of USCCB
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
              "image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# ===== Utils =====
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

# ===== Regex =====
REF_RE = re.compile(
    r'\b(?:[1-3]\s*)?'
    r'(?:Genesis|Exodus|Leviticus|Numbers|Deuteronomy|Joshua|Judges|Ruth|Samuel|Kings|Chronicles|Ezra|Nehemiah|Tobit|Judith|Esther|Job|Psalms?|Proverbs|Ecclesiastes|Qoheleth|Song(?: of Songs)?|Wisdom|Sirach|Isaiah|Jeremiah|Lamentations|Baruch|Ezekiel|Daniel|Hosea|Joel|Amos|Obadiah|Jonah|Micah|Nahum|Habakkuk|Zephaniah|Haggai|Zechariah|Malachi|Matthew|Mark|Luke|John|Acts|Romans|Corinthians|Galatians|Ephesians|Philippians|Colossians|Thessalonians|Timothy|Titus|Philemon|Hebrews|James|Peter|Jude|Revelation)'
    r'\s+\d+(?::\d+[a-z]*?(?:-\d+)?(?:,\s*\d+[a-z]*?(?:-\d+)?)*)?',
    re.I,
)

# Psalm *book* detection (for safety checks)
PSALM_REF_RE = re.compile(r'^(?:Ps|Psalm|Psalms)\s+\d+', re.I)

# ===== DOM helpers =====
def text_of(node: Tag) -> str:
    return node.get_text(" ", strip=True) if isinstance(node, Tag) else str(node).strip()

def siblings_text_until_next_heading(h: Tag) -> str:
    out: List[str] = []
    for sib in h.next_siblings:
        if isinstance(sib, NavigableString):
            t = str(sib).strip()
            if t:
                out.append(t)
            continue
        if isinstance(sib, Tag):
            t = text_of(sib)
            if not t:
                continue
            # We no longer rely on HEADING_RE here for parsing;
            # this helper is only used by the non-USCCB sources
            out.append(t)
    return " ".join(out)

def pagewide_psalm_fallback(html: str) -> str:
    m = re.search(
        r'(?:^|\s)((?:Ps(?:alm|alms)?|Psalm|Psalms)\s+\d+'
        r'(?::\d+[a-z]*?(?:-\d+)?(?:,\s*\d+[a-z]*?(?:-\d+)?)*)?)',
        html,
        re.I,
    )
    return m.group(1).strip() if m else ""

# ===== tiny voter Helper =====
def _canon(ref: str) -> str:
    """Canonicalize a scripture ref for comparison."""
    if not ref:
        return ""
    ref = re.sub(r'\s+', ' ', ref)          # collapse whitespace
    ref = ref.replace("First ", "1 ")
    ref = ref.replace("Second ", "2 ")
    ref = ref.replace("Third ", "3 ")
    return ref.strip(" .,")

def _vote_slot(*candidates: str) -> str:
    """
    Pick a reference by majority vote.
    If ≥2 sources agree (after canonicalization), use that.
    Otherwise fall back to first non-empty candidate in priority order.
    """
    clean = [c for c in map(_canon, candidates) if c]
    if not clean:
        return ""
    counts = Counter(clean)
    best, freq = counts.most_common(1)[0]
    if freq >= 2:
        return best
    # No agreement, fall back to first in original order
    return clean[0]

# ===== USCCB parser (text-first) =====
def parse_usccb_dom(html: str, sunday: bool) -> Tuple[str, str, str, str]:
    """
    Robust parsing strategy:
    1. Search for the text headers (Reading I, Gospel, etc.) regardless of tag.
    2. Find the closest following text that looks like a scripture citation.
    """
    soup = BeautifulSoup(html, "html.parser")

    found = {
        "first": "",
        "second": "",
        "psalm": "",
        "gospel": ""
    }

    def get_citation_after_header(header_text_pattern: str) -> str:
        # Find a text node matching the header label (e.g. "Reading I", "Responsorial Psalm")
        header = soup.find(string=re.compile(header_text_pattern, re.I))
        if not header:
            return ""

        # Go up to a reasonable container (usually <h3>, <h4>, <div>, etc.)
        container = header.parent

        # Strategy A: citation is inside the same container
        # e.g. <h3>Reading I <a>Is 25:6-10a</a></h3>
        internal_link = container.find("a")
        if internal_link:
            return internal_link.get_text(" ", strip=True)

        # Strategy B: citation is in a following sibling node
        # e.g. <div class="name">Reading I</div><div class="address"><a>Is 25:6-10a</a></div>
        sibling = container.next_sibling
        for _ in range(5):
            if not sibling:
                break
            if isinstance(sibling, Tag):
                text = sibling.get_text(" ", strip=True)
                if any(ch.isdigit() for ch in text):
                    return text
            sibling = sibling.next_sibling

        return ""

    # First Reading (Reading 1 / Reading I)
    found["first"] = get_citation_after_header(r"Reading\s+(1|I)(\s|$)")

    # Second Reading (Reading 2 / Reading II)
    found["second"] = get_citation_after_header(r"Reading\s+(2|II)(\s|$)")

    # Psalm (Responsorial Psalm / Psalm)
    found["psalm"] = get_citation_after_header(r"(Responsorial\s+Psalm|Responsorial|Psalm)")

    # Gospel
    found["gospel"] = get_citation_after_header(r"^Gospel(\s|$)")
    if not found["gospel"]:
        # Some pages bury the verse in the Alleluia block if the Gospel header is odd
        found["gospel"] = get_citation_after_header(r"Alleluia")

    # Clean up and strip "Lectionary" noise if captured
    for k in found:
        txt = found[k] or ""
        txt = re.sub(r"Lectionary.*", "", txt, flags=re.I)
        txt = txt.replace("\n", " ").strip()
        found[k] = txt

    # Weekdays typically have no second reading
    if not sunday:
        found["second"] = ""

    return found["first"] or "", found["second"] or "", found["psalm"] or "", found["gospel"] or ""

def fetch_readings_usccb(date: dt.date) -> Tuple[str, str, str, str]:
    url = f"https://bible.usccb.org/bible/readings/{date.strftime('%m%d%y')}.cfm"
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()

    first, second, psalm, gospel = parse_usccb_dom(r.text, sunday=is_sunday(date))

    # Debug: if everything came back empty, log a snippet so we can see what USCCB served
    if not any([first, psalm, gospel]):
        log(f"!! FAIL parsing {ymd(date)} – empty readings from USCCB. HTML snippet follows.")
        try:
            soup = BeautifulSoup(r.text, "html.parser")
            snippet = soup.get_text(" ", strip=True)[:600]
            log(snippet)
        except Exception as e:
            log("USCCB debug snippet failed:", e)

    return first, second, psalm, gospel

# --- CatholicGallery secondary source ---
def fetch_readings_catholicgallery(date: dt.date) -> Tuple[str, str, str, str]:
    """Per-date readings from CatholicGallery /mass-reading/DDMMYY/"""
    slug = date.strftime("%d%m%y")  # 201125 for 20 Nov 2025
    url = f"https://www.catholicgallery.org/mass-reading/{slug}/"
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    def grab(label: str, next_labels: List[str]) -> str:
        # label="First Reading:", next_labels=["Responsorial Psalm:", "Gospel:"]
        pattern = rf"{re.escape(label)}\s*(.+?)(?=" + "|".join(map(re.escape, next_labels)) + r"|$)"
        m = re.search(pattern, text)
        return m.group(1).strip() if m else ""

    first  = grab("First Reading:", ["Responsorial Psalm:", "Gospel:"])
    psalm  = grab("Responsorial Psalm:", ["Alleluia:", "Gospel:"])
    second = grab("Second Reading:", ["Responsorial Psalm:", "Gospel:"])
    gosp   = grab("Gospel:", [])

    def norm(s: str) -> str:
        s = re.sub(r'\s+', ' ', s)
        s = re.sub(r'^\bFirst\b|\bSecond\b|\bReading\b|Responsorial Psalm\b', '', s, flags=re.I)
        return s.strip(" :.,")
    return norm(first), norm(second), norm(psalm), norm(gosp)

def fetch_readings_catholicorg(date: dt.date) -> Tuple[str, str, str, str]:
    """Daily reading from catholic.org with ?select_date=YYYY-MM-DD"""
    url = f"https://www.catholic.org/bible/daily_reading/?select_date={date.isoformat()}"
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    def grab(label: str) -> str:
        # e.g. label="Reading 1," or "Responsorial Psalm,"
        m = re.search(
            rf"{re.escape(label)}\s*([^R]+?)(?=\s+Responsorial Psalm,|\s+Gospel,|$)",
            text,
        )
        return m.group(1).strip() if m else ""

    first  = grab("Reading 1,")
    psalm  = grab("Responsorial Psalm,")
    second = ""   # catholic.org weekday pages usually have only 1st + Psalm + Gospel
    gosp   = grab("Gospel,")

    def norm(s: str) -> str:
        s = re.sub(r'\s+', ' ', s)
        return s.strip(" .,")

    return norm(first), norm(second), norm(psalm), norm(gosp)

def fetch_readings_ewtn(date: dt.date) -> Tuple[str, str, str, str]:
    url = "https://www.ewtn.com/catholicism/daily-readings"
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    label = date.strftime("%B %-d").replace(" 0", " ")
    txt = ""
    for el in soup.find_all(string=re.compile(label, re.I)):
        try:
            txt = el.parent.get_text(" ", strip=True)
            break
        except Exception:
            pass
    html = txt or soup.get_text(" ", strip=True)
    return parse_usccb_dom(html, sunday=is_sunday(date))

def resolve_readings(date: dt.date) -> Tuple[str, str, str, str]:
    """
    Resolve readings with an ensemble:
    - USCCB
    - CatholicGallery
    - Catholic.org
    - EWTN (optional)
    """
    src = {
        "usccb":   ("", "", "", ""),
        "gallery": ("", "", "", ""),
        "corg":    ("", "", "", ""),
        "ewtn":    ("", "", "", ""),
    }

    # USCCB
    try:
        src["usccb"] = fetch_readings_usccb(date)
    except Exception as e:
        log("USCCB fetch issue", ymd(date), e)

    # CatholicGallery
    try:
        src["gallery"] = fetch_readings_catholicgallery(date)
    except Exception as e:
        log("CatholicGallery fetch issue", ymd(date), e)

    # Catholic.org
    try:
        src["corg"] = fetch_readings_catholicorg(date)
    except Exception as e:
        log("Catholic.org fetch issue", ymd(date), e)

    # EWTN optional
    if USE_EWTN_FALLBACK:
        try:
            src["ewtn"] = fetch_readings_ewtn(date)
        except Exception as e:
            log("EWTN fetch issue", ymd(date), e)

    # Unpack
    f_u, s_u, p_u, g_u = src["usccb"]
    f_g, s_g, p_g, g_g = src["gallery"]
    f_c, s_c, p_c, g_c = src["corg"]
    f_e, s_e, p_e, g_e = src["ewtn"]

    # Majority / priority vote
    first  = _vote_slot(f_u, f_g, f_c, f_e)
    psalm  = _vote_slot(p_u, p_g, p_c, p_e)
    second = _vote_slot(s_u, s_g, s_c, s_e)
    gospel = _vote_slot(g_u, g_g, g_c, g_e)

    # Safety: first must not be a Psalm; psalm must look like a Psalm *book* ref
    if first and PSALM_REF_RE.match(first):
        log("first reading looks like psalm; clearing first", first)
        first = ""

    if psalm and not re.search(r'\d', psalm):
        log("psalm ref looks wrong; clearing psalm", psalm)
        psalm = ""

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
    messages = [{"role": "system", "content": sys_msg},
                {"role": "user", "content": "\n".join(user_lines)}]

    def _create(model, use_temp):
        kw = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"}
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

    overrides = load_json("public/readings-overrides.json", {})
    over = overrides.get(iso, {})
    first_ref  = over.get("firstRef",  first_ref)
    second_ref = over.get("secondRef", second_ref)
    psalm_ref  = over.get("psalmRef",  psalm_ref)
    gospel_ref = over.get("gospelRef", gospel_ref)

    # === HARD INVARIANTS ===
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
            raise SystemExit(msg)
        log("warn:", msg)

    # Second reading is optional, but on Sundays we expect one.
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
        f"SAINT_NAME: {saint.get('saintName', '')}",
        f"SAINT_PROFILE: {saint.get('profile', '')}",
        f"SAINT_LINK: {saint.get('link', '')}",
        "RETURN KEYS: [date, quote, quoteCitation, firstReading, secondReading, psalmSummary, gospelSummary, "
        "saintReflection, dailyPrayer, theologicalSynthesis, exegesis, tags, usccbLink, cycle, weekdayCycle, feast, "
        "gospelReference, firstReadingRef, secondReadingRef, psalmRef, gospelRef, lectionaryKey]"
    ]

    client = openai_client()
    out = gen_json(client, STYLE_CARD, lines, GEN_TEMP)
    if not isinstance(out, dict):
        out = {}

    out["date"] = iso
    out["usccbLink"] = usccb_link
    out["firstReadingRef"]  = first_ref
    out["secondReadingRef"] = second_ref
    out["psalmRef"]         = psalm_ref
    out["gospelRef"]        = gospel_ref
    out["gospelReference"]  = gospel_ref
    out["cycle"]        = compute_year_cycle(date)
    out["weekdayCycle"] = compute_weekday_cycle(date)
    out["feast"]        = feast
    out["lectionaryKey"] = f"{iso}:{first_ref}|{second_ref}|{psalm_ref}|{gospel_ref}"

    if not _s(second_ref):
        out["secondReading"] = ""

    for k in [
        "date", "quote", "quoteCitation", "firstReading", "secondReading", "psalmSummary", "gospelSummary",
        "saintReflection", "dailyPrayer", "theologicalSynthesis", "exegesis", "usccbLink", "cycle", "weekdayCycle",
        "feast", "gospelReference", "firstReadingRef", "secondReadingRef", "psalmRef", "gospelRef", "lectionaryKey"
    ]:
        out[k] = _s(out.get(k, ""))

    tags = out.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    out["tags"] = [str(t).strip().lower().replace(" ", "-")[:32] for t in tags][:12]
    return out

# ===== Final normalize =====
REQ = [
    "date", "quote", "quoteCitation", "firstReading", "secondReading", "psalmSummary", "gospelSummary",
    "saintReflection", "dailyPrayer", "theologicalSynthesis", "exegesis", "usccbLink", "cycle", "weekdayCycle",
    "feast", "gospelReference", "firstReadingRef", "secondReadingRef", "psalmRef", "gospelRef", "lectionaryKey"
]

def normalize_rows(rows: List[Dict[str, Any]]):
    for r in rows:
        for k in REQ:
            r[k] = _s(r.get(k, ""))
        tags = r.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        r["tags"] = [str(t).strip().lower().replace(" ", "-")[:32] for t in tags][:12]

# ===== Main =====
def main():
    # Optional precheck mode – no OpenAI, just make sure readings/psalm are wired up
    if os.getenv("USCCB_PRECHECK") == "1":
        start_env = os.getenv("START_DATE", "").strip()

        # Handle DAYS being missing or blank from the workflow
        days_str = (os.getenv("DAYS", "") or "").strip()
        days = int(days_str or "7")

        if start_env:
            start = dt.date(*map(int, start_env.split("-")))
        else:
            start = today_local()

        for d in daterange(start, days):
            f, s, p, g = resolve_readings(d)
            print(
                "[precheck]", d.isoformat(), "|",
                f or "—", "|",
                s or "—", "|",
                p or "MISSING-PSALM", "|",
                g or "—",
            )
        return

    # Normal generation mode
    start_env = os.getenv("START_DATE", "").strip()

    # Handle DAYS being missing or blank from the cron workflow
    days_str = (os.getenv("DAYS", "") or "").strip()
    days = int(days_str or "7")

    if start_env:
        start = dt.date(*map(int, start_env.split("-")))
    else:
        start = today_local()

    log(f"tz={APP_TZ} start={start} days={days} model={GEN_MODEL}")

    rows = []
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
