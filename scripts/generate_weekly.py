#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Generate public/weeklyfeed.json

Fixes:
- Robust Psalm extraction (header-proximity + page-wide fallback).
- Second reading only when truly present (or Sunday + real ref).
- Saints merged from local + remote URL.
- Proper liturgical cycles (Year A/B/C, Cycle I/II).
- CatholicGallery used as primary reading source, with USCCB/EWTN as fallbacks.
"""

import os, re, json, time, zoneinfo, datetime as dt
from typing import Dict, Any, Tuple, List
import requests
from bs4 import BeautifulSoup, NavigableString, Tag

# ===== Config =====
APP_TZ = os.getenv("APP_TZ", "America/New_York")
TZ = zoneinfo.ZoneInfo(APP_TZ)

USCCB_STRICT       = os.getenv("USCCB_STRICT", "0") == "1"
USE_EWTN_FALLBACK  = os.getenv("USE_EWTN_FALLBACK", "1") == "1"   # default ON to be safe
SAINT_JSON_URL     = os.getenv("SAINT_JSON_URL", "https://dailylectio.org/saint.json")

GEN_MODEL          = os.getenv("GEN_MODEL", "gpt-5-mini")
GEN_FALLBACK       = os.getenv("GEN_FALLBACK", "gpt-5-mini")
GEN_TEMP           = float(os.getenv("GEN_TEMP", "1"))

HEADERS = {
    "User-Agent": "FaithLinksBot/1.7 (+github actions)",
    "Accept": "text/html,application/xhtml+xml",
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
PSALM_REF_RE = re.compile(r'^(?:Ps|Psalm|Psalms)\s+\d+', re.I)
HEADING_RE = re.compile(r'^(First Reading|Reading I|Reading 1|Second Reading|Reading II|Reading 2|Responsorial Psalm|Psalm|Alleluia|Gospel)\b', re.I)

# ===== DOM helpers =====
def text_of(node: Tag) -> str:
    return node.get_text(" ", strip=True) if isinstance(node, Tag) else str(node).strip()

def find_heading(soup: BeautifulSoup, pat: re.Pattern) -> Tag | None:
    for tag in soup.find_all(True):
        try:
            t = tag.get_text(" ", strip=True)
        except Exception:
            t = ""
        if t and pat.search(t):
            return tag
    return None

def siblings_text_until_next_heading(h: Tag) -> str:
    out: List[str] = []
    for sib in h.next_siblings:
        if isinstance(sib, NavigableString):
            t = str(sib).strip()
            if t: out.append(t)
            continue
        if isinstance(sib, Tag):
            t = text_of(sib)
            if not t: continue
            if HEADING_RE.search(t): break
            out.append(t)
    return " ".join(out)

def nearest_psalm_citation(h: Tag) -> str:
    # 1) within header+following section
    chunk = (text_of(h) + " " + siblings_text_until_next_heading(h)).strip()
    m = re.search(r'(?:^|\s)((?:Ps(?:alm|alms)?|Psalm|Psalms)\s+\d+(?::\d+[a-z]*?(?:-\d+)?(?:,\s*\d+[a-z]*?(?:-\d+)?)*)?)', chunk, re.I)
    if m: return m.group(1).strip()
    # 2) look a few siblings backward (some pages float the citation on the right)
    back = []
    for sib in list(h.previous_siblings)[:6]:
        if isinstance(sib, Tag):
            back.append(text_of(sib))
        elif isinstance(sib, NavigableString):
            back.append(str(sib).strip())
    back_txt = " ".join(reversed([t for t in back if t]))
    m2 = re.search(r'(?:^|\s)((?:Ps(?:alm|alms)?|Psalm|Psalms)\s+\d+(?::\d+[a-z]*?(?:-\d+)?(?:,\s*\d+[a-z]*?(?:-\d+)?)*)?)', back_txt, re.I)
    if m2: return m2.group(1).strip()
    return ""

def pagewide_psalm_fallback(html: str) -> str:
    m = re.search(r'(?:^|\s)((?:Ps(?:alm|alms)?|Psalm|Psalms)\s+\d+(?::\d+[a-z]*?(?:-\d+)?(?:,\s*\d+[a-z]*?(?:-\d+)?)*)?)', html, re.I)
    return m.group(1).strip() if m else ""

# ===== Parsers =====
def parse_usccb_dom(html: str, sunday: bool) -> Tuple[str, str, str, str]:
    soup = BeautifulSoup(html, "html.parser")
    first = second = psalm = gospel = ""
    saw_second_heading = False

    h_first = find_heading(soup, re.compile(r'^(First Reading|Reading I|Reading 1)\b', re.I))
    if h_first:
        ref = REF_RE.search(siblings_text_until_next_heading(h_first)) or REF_RE.search(text_of(h_first))
        if ref: first = ref.group(0).strip()

    h_gospel = find_heading(soup, re.compile(r'^Gospel\b', re.I))
    if h_gospel:
        ref = REF_RE.search(siblings_text_until_next_heading(h_gospel)) or REF_RE.search(text_of(h_gospel))
        if ref: gospel = ref.group(0).strip()

    h_psalm = find_heading(soup, re.compile(r'^(Responsorial Psalm|Psalm)\b', re.I))
    if h_psalm:
        psalm = nearest_psalm_citation(h_psalm)
    if not psalm:
        psalm = pagewide_psalm_fallback(soup.get_text(" ", strip=True))

    h_second = find_heading(soup, re.compile(r'^(Second Reading|Reading II|Reading 2)\b', re.I))
    if h_second:
        saw_second_heading = True
        ref = REF_RE.search(siblings_text_until_next_heading(h_second)) or REF_RE.search(text_of(h_second))
        if ref: second = ref.group(0).strip()

    if not saw_second_heading and not (sunday and second):
        second = ""

    if psalm:
        parts = [p.strip() for p in re.split(r'[;,]\s*', psalm) if p.strip()]
        psalm = ", ".join(dict.fromkeys(parts))

    return first or "", second or "", psalm or "", gospel or ""

# --- NEW: CatholicGallery secondary source ---
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

def fetch_readings_usccb(date: dt.date) -> Tuple[str, str, str, str]:
    url = f"https://bible.usccb.org/bible/readings/{date.strftime('%m%d%y')}.cfm"
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return parse_usccb_dom(r.text, sunday=is_sunday(date))

def fetch_readings_ewtn(date: dt.date) -> Tuple[str, str, str, str]:
    url = "https://www.ewtn.com/catholicism/daily-readings"
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    label = date.strftime("%B %-d").replace(" 0", " ")
    txt = ""
    for el in soup.find_all(text=re.compile(label, re.I)):
        try:
            txt = el.parent.get_text(" ", strip=True); break
        except Exception:
            pass
    html = txt or soup.get_text(" ", strip=True)
    return parse_usccb_dom(html, sunday=is_sunday(date))

def resolve_readings(date: dt.date) -> Tuple[str, str, str, str]:
    """
    Resolve readings for a date with this precedence:
    1) USCCB (primary)
    2) CatholicGallery per-date (fallback)
    3) EWTN (last resort, if enabled)

    Invariants:
    - First reading MUST NOT be a Psalm.
    - Psalm MUST look like a Psalm.
    - Second reading is optional but must not be Psalm or Gospel.
    """
    f = s = p = g = ""

    # 1) USCCB primary
    try:
        f, s, p, g = fetch_readings_usccb(date)
    except Exception as e:
        log("USCCB fetch issue", ymd(date), e)

    # 2) CatholicGallery fallback if anything core is missing OR first looks like a psalm
    need_cg = (not f or not p or not g or (f and PSALM_REF_RE.match(f)))
    if need_cg:
        try:
            f2, s2, p2, g2 = fetch_readings_catholicgallery(date)
            # Only overwrite if still missing / invalid
            if not f or PSALM_REF_RE.match(f):
                f = f2
            if not p:
                p = p2
            if not g:
                g = g2
            if not s:
                s = s2
        except Exception as e:
            log("CatholicGallery fetch issue", ymd(date), e)

    def fetch_readings_catholicorg(date: dt.date) -> Tuple[str, str, str, str]:
    """Daily reading from catholic.org with ?select_date=YYYY-MM-DD"""
    url = f"https://www.catholic.org/bible/daily_reading/?select_date={date.isoformat()}"
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    def grab(label: str) -> str:
        # e.g. label="Reading 1," or "Responsorial Psalm,"
        m = re.search(rf"{re.escape(label)}\s*([^R]+?)(?=\s+Responsorial Psalm,|\s+Gospel,|$)", text)
        return m.group(1).strip() if m else ""

    first  = grab("Reading 1,")
    psalm  = grab("Responsorial Psalm,")
    second = ""   # catholic.org weekday pages usually have only 1st + Psalm + Gospel
    gosp   = grab("Gospel,")

    # Normalize: "First Maccabees 2:15-29" etc
    def norm(s: str) -> str:
        s = re.sub(r'\s+', ' ', s)
        return s.strip(" .,")

    return norm(first), norm(second), norm(psalm), norm(gosp)

    # 3) EWTN last resort
    if USE_EWTN_FALLBACK and (not f or not p or not g or (f and PSALM_REF_RE.match(f))):
        try:
            f2, s2, p2, g2 = fetch_readings_ewtn(date)
            if not f or PSALM_REF_RE.match(f):
                f = f2
            if not p:
                p = p2
            if not g:
                g = g2
            if not s:
                s = s2
        except Exception as e:
            log("EWTN fetch issue", ymd(date), e)

    # ---- Final sanity guards ----

    # First reading MUST NOT be a psalm
    if f and PSALM_REF_RE.match(f):
        log("first reading looks like a psalm – invalid:", f)
        f = ""

    # Psalm MUST look like a psalm
    if p and not PSALM_REF_RE.match(p):
        log("psalm rejected (does not parse as Psalm):", p)
        p = ""

    # Second reading must not be dup/psalm/gospel
    if s and (s == f or s == g or PSALM_REF_RE.match(s) or s.startswith(("Matthew","Mark","Luke","John"))):
        log("second reading rejected (dup/psalm/gospel):", s)
        s = ""

    return f or "", s or "", p or "", g or ""

    # 1) USCCB primary
    try:
        f, s, p, g = fetch_readings_usccb(date)
    except Exception as e:
        log("USCCB fetch issue", ymd(date), e)

    # 2) CatholicGallery per-date fallback if anything critical is missing
    if not f or not p or not g:
        try:
            f2, s2, p2, g2 = fetch_readings_catholicgallery(date)
            f = f or f2
            p = p or p2
            g = g or g2
            s = s or s2
        except Exception as e:
            log("CatholicGallery fetch issue", ymd(date), e)

    # 3) EWTN last resort
    if USE_EWTN_FALLBACK and (not f or not p or not g):
        try:
            f2, s2, p2, g2 = fetch_readings_ewtn(date)
            f = f or f2
            p = p or p2
            g = g or g2
            s = s or s2
        except Exception as e:
            log("EWTN fetch issue", ymd(date), e)

    # Psalm sanity
    if p and not PSALM_REF_RE.match(p):
        log("psalm rejected:", p)
        p = ""

    # Second reading sanity
    if s and (s == f or s == g or PSALM_REF_RE.match(s) or s.startswith(("Matthew", "Mark", "Luke", "John"))):
        s = ""

    return f or "", s or "", p or "", g or ""

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
    messages = [{"role":"system","content":sys_msg},{"role":"user","content":"\n".join(user_lines)}]
    def _create(model, use_temp):
        kw = {"model":model,"messages":messages,"response_format":{"type":"json_object"}}
        if use_temp: kw["temperature"] = temp
        return client.chat.completions.create(**kw)
    try:
        try:
            r = _create(GEN_MODEL, True)
        except BadRequestError as e:
            if "temperature" in str(e).lower(): r = _create(GEN_MODEL, False)
            else: raise
    except Exception:
        try:
            r = _create(GEN_FALLBACK, True)
        except BadRequestError as e2:
            if "temperature" in str(e2).lower(): r = _create(GEN_FALLBACK, False)
            else: raise
    return json.loads(r.choices[0].message.content)

STYLE_CARD = """ROLE: Catholic editor & theologian for FaithLinks.
RULES:
- Use the exact references I provide. Do not invent or swap.
- If SECOND_READING_REF is empty, `secondReading` MUST be "".
- Never treat the Alleluia as the Psalm.
- Summarize Scripture; ≤10 quoted words total.
- Output only JSON with the contract keys.
LENGTHS (words):
- quote 9–25; firstReading 50–100; secondReading 0 or 50–100; psalmSummary 50–100; gospelSummary 100–200;
- saintReflection 50–100; dailyPrayer 150–200; theologicalSynthesis 150–200;
- exegesis 500–750 in 5–6 short paragraphs (Context:, Psalm:, Gospel:, Saints:, Today:).
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
    # For your use case, these three must exist and be sane.
    core_missing = []
    if not first_ref:
        core_missing.append("first")
    if not psalm_ref:
        core_missing.append("psalm")
    if not gospel_ref:
        core_missing.append("gospel")

    if core_missing:
        # Always fail if a core reading is missing.
        raise SystemExit(f"{iso}: missing core reading(s): {', '.join(core_missing)}")

    # Second reading is optional, but on Sundays we expect one.
    if is_sunday(date) and not second_ref:
        log(f"warn: {iso} is Sunday and has no second reading ref")

    saint = saint_for_date(date)
    feast = saint.get("memorial","")

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
    if not isinstance(out, dict): out = {}

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

    for k in ["date","quote","quoteCitation","firstReading","secondReading","psalmSummary","gospelSummary",
              "saintReflection","dailyPrayer","theologicalSynthesis","exegesis","usccbLink","cycle","weekdayCycle",
              "feast","gospelReference","firstReadingRef","secondReadingRef","psalmRef","gospelRef","lectionaryKey"]:
        out[k] = _s(out.get(k,""))

    tags = out.get("tags", [])
    if not isinstance(tags, list): tags = []
    out["tags"] = [str(t).strip().lower().replace(" ", "-")[:32] for t in tags][:12]
    return out

# ===== Final normalize =====
REQ = ["date","quote","quoteCitation","firstReading","secondReading","psalmSummary","gospelSummary",
       "saintReflection","dailyPrayer","theologicalSynthesis","exegesis","usccbLink","cycle","weekdayCycle",
       "feast","gospelReference","firstReadingRef","secondReadingRef","psalmRef","gospelRef","lectionaryKey"]
def normalize_rows(rows: List[Dict[str,Any]]):
    for r in rows:
        for k in REQ: r[k] = _s(r.get(k,""))
        tags = r.get("tags", [])
        if not isinstance(tags, list): tags = []
        r["tags"] = [str(t).strip().lower().replace(" ", "-")[:32] for t in tags][:12]

# ===== Main =====
def main():
    if os.getenv("USCCB_PRECHECK") == "1":
        start_env = os.getenv("START_DATE","").strip()
        days = int(os.getenv("DAYS","7"))
        start = dt.date(*map(int, start_env.split("-"))) if start_env else today_local()
        for d in daterange(start, days):
            f,s,p,g = resolve_readings(d)
            print("[precheck]", d.isoformat(), "|", f or "—", "|", s or "—", "|", p or "MISSING-PSALM", "|", g or "—")
        return

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
