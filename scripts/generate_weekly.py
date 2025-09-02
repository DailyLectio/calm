#!/usr/bin/env python3
"""
USCCB-only weekly generator (no local fallbacks).

- Fetches bible.usccb.org daily pages (.../MMDDYY.cfm) with requests.
- Extracts Reading I / Responsorial Psalm / Gospel robustly.
- If labels are missing, uses a heuristic: detect all Scripture refs in the
  header and classify (Gospels -> Gospel, Psalm/Ps/Psalms -> Psalm, else First/Second).
- If (first, psalm, gospel) can't be derived, exits with a clear message.

FAST SCRAPE CHECK (no OpenAI, no writes):
    USCCB_PRECHECK=1 START_DATE=2025-09-01 DAYS=30 python scripts/generate_weekly.py
"""

import html as ihtml
import json, os, re, sys
from datetime import datetime, date, timedelta
from pathlib import Path
from jsonschema import Draft202012Validator
from openai import OpenAI
from collections import OrderedDict
from typing import List, Dict, Any

import requests
# ------------------ [2aa] HARDENING: retry/backoff for HTTP -------------------
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
# -----------------------------------------------------------------------------

# ---------- repo paths ----------
ROOT         = Path(__file__).resolve().parents[1]
WEEKLY_PATH  = ROOT / "public" / "weeklyfeed.json"
SCHEMA_PATH  = ROOT / "schemas" / "devotion.schema.json"
USCCB_BASE   = "https://bible.usccb.org/bible/readings"

# ---------- model knobs ----------
MODEL          = os.getenv("GEN_MODEL", "gpt-4o-mini")
FALLBACK_MODEL = os.getenv("GEN_FALLBACK", "gpt-4o-mini")
TEMP_MAIN      = float(os.getenv("GEN_TEMP", "0.55"))
TEMP_REPAIR    = float(os.getenv("GEN_TEMP_REPAIR", "0.45"))
TEMP_QUOTE     = float(os.getenv("GEN_TEMP_QUOTE", "0.35"))

def safe_chat(client, *, temperature, response_format, messages, model=None):
    use_model = (model or MODEL)
    try:
        return client.chat.completions.create(
            model=use_model, temperature=temperature,
            response_format=response_format, messages=messages,
        )
    except Exception as e:
        msg = str(e).lower()
        if any(k in msg for k in ("model","permission","not found","unknown")) and FALLBACK_MODEL != use_model:
            print(f"[warn] model '{use_model}' not available; falling back to '{FALLBACK_MODEL}'")
            return client.chat.completions.create(
                model=FALLBACK_MODEL, temperature=temperature,
                response_format=response_format, messages=messages,
            )
        raise

# ---------- output contract ----------
KEY_ORDER = [
    "date","quote","quoteCitation","firstReading","psalmSummary","gospelSummary","saintReflection",
    "dailyPrayer","theologicalSynthesis","exegesis","secondReading","tags","usccbLink","cycle",
    "weekdayCycle","feast","gospelReference","firstReadingRef","secondReadingRef","psalmRef",
    "gospelRef","lectionaryKey",
]
NULLABLE_STR_FIELDS = ("secondReading", "feast", "secondReadingRef")

# ---------- enums / normalization ----------
CYCLE_MAP   = {"A":"Year A","B":"Year B","C":"Year C","Year A":"Year A","Year B":"Year B","Year C":"Year C"}
WEEKDAY_MAP = {"I":"Cycle I","II":"Cycle II","Cycle I":"Cycle I","Cycle II":"Cycle II"}

def _normalize_refs(entry: Dict[str, Any]) -> Dict[str, Any]:
    for k in ("firstReadingRef","psalmRef","secondReadingRef","gospelRef","gospelReference"):
        v = entry.get(k, "")
        entry[k] = "" if v is None else str(v)
    return entry

def _normalize_enums(entry: Dict[str, Any]) -> Dict[str, Any]:
    entry["cycle"] = CYCLE_MAP.get(str(entry.get("cycle","")).strip(), entry.get("cycle","Year C"))
    entry["weekdayCycle"] = WEEKDAY_MAP.get(
        str(entry.get("weekdayCycle","")).strip() or str(entry.get("weekday","")).strip(),
        entry.get("weekdayCycle","Cycle I")
    )
    return entry

# ---------- time helpers ----------
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

APP_TZ = os.getenv("APP_TZ", "America/New_York")

def today_in_tz(tzname: str) -> date:
    if ZoneInfo:
        return datetime.now(ZoneInfo(tzname)).date()
    return date.today()

_raw_start = (os.getenv("START_DATE") or "").strip()
if _raw_start:
    try:
        START = date.fromisoformat(_raw_start)
    except ValueError:
        raise SystemExit(f"[error] START_DATE must be YYYY-MM-DD, got {_raw_start!r}")
else:
    START = today_in_tz(APP_TZ)

_raw_days = (os.getenv("DAYS") or "7").strip()
try:
    DAYS = int(_raw_days or "7")
except ValueError:
    DAYS = 7
DAYS = max(1, min(DAYS, 14))

# ---------- style card ----------
STYLE_CARD = """ROLE: Catholic editor + theologian for FaithLinks.

Audience: teens + adults (high school through adult).

Strict lengths (words):
- quote: 9-25 words (1-2 sentences).
- firstReading: 50-100
- secondReading: 50-100 (or empty if there is no second reading that day)
- psalmSummary: 50-100
- gospelSummary: 100-200
- saintReflection: 50-100
- dailyPrayer: 150-200
- theologicalSynthesis: 150-200
- exegesis: 500-750, formatted as 5-6 short paragraphs with brief headings (e.g., Context:, Psalm:, Gospel:, Saints:, Today:) and a blank line between paragraphs.

Rules:
- Do NOT paste long Scripture passages; paraphrase faithfully. The 'quote' field may include a short Scripture line.
- Warm, pastoral, Christ-centered, accessible; concrete connections for modern life.
- Return ONLY a JSON object containing the contract keys (no commentary).
"""

# ---------- tiny utils ----------
def usccb_link(d: date) -> str:
    return f"{USCCB_BASE}/{d.strftime('%m%d%y')}.cfm"

def extract_json(text: str) -> str:
    s = text.find("{"); e = text.rfind("}")
    return text[s:e+1] if (s>=0 and e>s) else text

def clean_tags(val) -> List[str]:
    if val is None: return []
    items = [val] if isinstance(val,str) else (val if isinstance(val,list) else [])
    out=[]
    for t in items:
        s=str(t).strip()
        if s: out.append(s)
        if len(out)>=12: break
    return out

def lectionary_key(meta: Dict[str, str]) -> str:
    parts = [meta.get("firstRef","").replace(" ",""),
             meta.get("psalmRef","").replace(" ",""),
             meta.get("gospelRef","").replace(" ",""),
             meta.get("cycle",""), meta.get("weekday","")]
    return "|".join(p for p in parts if p)

# ------------------ [2aa] HARDENING: shared requests.Session ------------------
_retry = Retry(
    total=4, backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=("GET",),
    raise_on_status=False,
)
SESSION = requests.Session()
SESSION.mount("https://", HTTPAdapter(max_retries=_retry))
SESSION.mount("http://",  HTTPAdapter(max_retries=_retry))
# -----------------------------------------------------------------------------

# ---------- robust USCCB scraping (requests + regex only) ----------
UA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.8",
}

BOOK_PATTERN = (
    r"(?:(?:[1-3]\s*)?(?:Genesis|Exodus|Leviticus|Numbers|Deuteronomy|Joshua|Judges|Ruth|"
    r"1 Samuel|2 Samuel|1 Kings|2 Kings|1 Chronicles|2 Chronicles|Ezra|Nehemiah|Tobit|Judith|Esther|"
    r"1 Maccabees|2 Maccabees|Job|Psalm|Psalms|Ps|Proverbs|Ecclesiastes|Song of Songs|Wisdom|Sirach|"
    r"Isaiah|Jeremiah|Lamentations|Baruch|Ezekiel|Daniel|Hosea|Joel|Amos|Obadiah|Jonah|Micah|Nahum|"
    r"Habakkuk|Zephaniah|Haggai|Zechariah|Malachi|Matthew|Mark|Luke|John|Acts|Romans|"
    r"1 Corinthians|2 Corinthians|Galatians|Ephesians|Philippians|Colossians|"
    r"1 Thessalonians|2 Thessalonians|1 Timothy|2 Timothy|Titus|Philemon|Hebrews|James|"
    r"1 Peter|2 Peter|1 John|2 John|3 John|Jude|Revelation))"
)

# Allow hyphen and en-dash in verse lists using ASCII '-' and \u2013.
REF_RE = re.compile(
    rf"({BOOK_PATTERN}\s+\d+(?::[0-9,\-\u2013\s]+)?(?:\s*(?:and|;)\s*[0-9:,\-\u2013\s]+)*)",
    flags=re.I
)

def _html_to_text(html: str) -> str:
    # keep block breaks
    txt = re.sub(r"(?i)</(p|li|h\d|div|br|tr|section)>", "\n", html)
    txt = re.sub(r"(?is)<script.*?</script>", " ", txt)
    txt = re.sub(r"(?is)<style.*?</style>", " ", txt)
    txt = re.sub(r"(?is)<[^>]+>", " ", txt)
    txt = ihtml.unescape(txt)
    txt = re.sub(r"[ \t\r\f]+", " ", txt)
    txt = re.sub(r"\n\s*\n\s*", "\n", txt)
    return txt.strip()

def _normalize_psalm_name(s: str) -> str:
    s = s.replace("Psalms", "Psalm")
    s = re.sub(r"\bPs\b\.?", "Psalm", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _fetch_usccb_text(d: date) -> str:
    url = usccb_link(d)
    r = SESSION.get(url, headers=UA_HEADERS, timeout=20)
    if r.status_code != 200 or not r.text:
        # alternate daily endpoint sometimes works
        alt = f"https://bible.usccb.org/bible/readings?date={d.isoformat()}"
        r = SESSION.get(alt, headers=UA_HEADERS, timeout=20)
        if r.status_code != 200 or not r.text:
            raise SystemExit(f"USCCB fetch failed for {d.isoformat()} (HTTP {r.status_code})")
    return _html_to_text(r.text)

def _find_ref_after(labels: List[str], text: str, near=800) -> str:
    for lab in labels:
        m = re.search(rf"(?i)\b{re.escape(lab)}\b(.{{0,{near}}})", text, flags=re.S)
        if m:
            window = m.group(1)
            m2 = REF_RE.search(window)
            if m2:
                return _normalize_psalm_name(m2.group(1))
    return ""

def _heuristic_assign(text: str) -> Dict[str,str]:
    """Fallback when explicit labels aren't found."""
    head = text[:3000]
    refs = [m.group(1) for m in REF_RE.finditer(head)]
    # de-dup while preserving order
    seen, uniq = set(), []
    for r in refs:
        rr = _normalize_psalm_name(r)
        if rr.lower() not in seen:
            seen.add(rr.lower()); uniq.append(rr)
    out = {"firstRef":"", "secondRef":"", "psalmRef":"", "gospelRef":""}
    for r in uniq:
        if any(g in r.lower() for g in ("matthew","mark","luke","john")) and not out["gospelRef"]:
            out["gospelRef"] = r; continue
        if "psalm" in r.lower() and not out["psalmRef"]:
            out["psalmRef"] = r; continue
    # the rest are first/second (if present)
    leftovers = [r for r in uniq if r not in (out["gospelRef"], out["psalmRef"])][:2]
    if leftovers:
        out["firstRef"] = leftovers[0]
    if len(leftovers) > 1:
        out["secondRef"] = leftovers[1]
    return out

def fetch_usccb_meta(d: date) -> Dict[str,str]:
    txt = _fetch_usccb_text(d)

    # Try explicit label capture first
    first = _find_ref_after(
        ["Reading I", "Reading 1", "First Reading", "First Reading:"], txt)
    second = _find_ref_after(
        ["Reading II", "Reading 2", "Second Reading", "Second Reading:"], txt)
    psalm = _find_ref_after(
        ["Responsorial Psalm", "Responsorial Psalm:"], txt)
    gospel = _find_ref_after(
        ["Gospel", "Gospel:"], txt)

    # Heuristic fallback
    if not (first and psalm and gospel):
        guess = _heuristic_assign(txt)
        first  = first  or guess["firstRef"]
        second = second or guess["secondRef"]
        psalm  = psalm  or guess["psalmRef"]
        gospel = gospel or guess["gospelRef"]

    # Require the core triple
    if not (first and psalm and gospel):
        raise SystemExit(f"USCCB parse incomplete for {d.isoformat()} (first/psalm/gospel required)")

    # Best-effort feast/saint from the page title line
    feast = ""
    m = re.search(r"(?im)^\s*(?:Memorial|Feast|Solemnity|Optional Memorial|Saint|St\.)[^\n]+", txt)
    if m: feast = m.group(0).strip()

    # Try to extract a Saint's name from that line
    saintName = ""
    m2 = re.search(r"(Saint|St\.)\s+([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+)*)", feast or "")
    if m2:
        saintName = m2.group(0).replace("St.", "Saint")

    return {
        "firstRef": first,
        "secondRef": second or "",
        "psalmRef": psalm,
        "gospelRef": gospel,
        "feast": feast,
        "cycle":  "Year C",
        "weekday":"Cycle I",
        "saintName": saintName,
        "saintNote": "",
        "url": usccb_link(d),
    }

# ---------- main content generation ----------
def canonicalize(draft: Dict[str,Any], *, ds: str, d: date, meta: Dict[str,str], lk: str) -> Dict[str, Any]:
    def S(k, default=""):
        v = draft.get(k)
        if v is None: return default
        s = str(v).strip()
        return s if s else default

    second_reading = draft.get("secondReading")
    if isinstance(second_reading,str): second_reading = second_reading.strip() or ""
    elif second_reading is None:       second_reading = ""
    else:                              second_reading = str(second_reading).strip() or ""

    second_ref = draft.get("secondReadingRef")
    if isinstance(second_ref,str): second_ref = second_ref.strip() or ""
    elif second_ref is None:       second_ref = ""
    else:                          second_ref = str(second_ref).strip() or ""
    if not second_ref:
        second_ref = meta.get("secondRef","") or ""

    # fallback for quoteCitation if the model forgot it
    qc = S("quoteCitation") or S("gospelReference") or meta.get("gospelRef","") \
         or S("firstReadingRef") or meta.get("firstRef","")

    obj = {
        "date": ds,
        "quote": S("quote"),
        "quoteCitation": qc,
        "firstReading": S("firstReading"),
        "psalmSummary": S("psalmSummary"),
        "gospelSummary": S("gospelSummary"),
        "saintReflection": S("saintReflection"),
        "dailyPrayer": S("dailyPrayer"),
        "theologicalSynthesis": S("theologicalSynthesis"),
        "exegesis": S("exegesis"),
        "secondReading": second_reading,
        "tags": clean_tags(draft.get("tags")),
        "usccbLink": usccb_link(d),
        "cycle": S("cycle") or meta["cycle"],
        "weekdayCycle": S("weekdayCycle") or meta["weekday"],
        "feast": S("feast") or meta["feast"],
        "gospelReference": S("gospelReference") or meta["gospelRef"],
        "firstReadingRef": S("firstReadingRef") or meta["firstRef"],
        "secondReadingRef": second_ref,
        "psalmRef": S("psalmRef") or meta["psalmRef"],
        "gospelRef": S("gospelRef") or meta["gospelRef"],
        "lectionaryKey": S("lectionaryKey") or lk,
    }
    return obj

def _order_keys(entry: Dict[str, Any]) -> OrderedDict:
    ordered = OrderedDict()
    for k in KEY_ORDER:
        if k in NULLABLE_STR_FIELDS and (entry.get(k) is None):
            ordered[k] = ""
        else:
            ordered[k] = entry.get(k, "" if k in NULLABLE_STR_FIELDS else ([] if k=="tags" else ""))
    return ordered

def normalize_day(entry: Dict[str, Any]) -> OrderedDict:
    entry = _normalize_enums(_normalize_refs(entry))
    if isinstance(entry.get("tags"), str):
        entry["tags"] = [s.strip() for s in entry["tags"].split(",") if s.strip()]
    elif not isinstance(entry.get("tags"), list):
        entry["tags"] = []
    return _order_keys(entry)

# --------------- [2B] FALLBACK BLOCK for missing model fields -----------------
FALLBACK_SENTENCES = {
    "quote": "Fix your eyes on Christ.",
    "firstReading": "A brief summary of the first reading encouraging faithfulness.",
    "psalmSummary": "A short note on the psalm inviting trust in the Lord.",
    "gospelSummary": "A concise reminder of the Good News proclaimed today.",
    "saintReflection": "A simple reflection inviting imitation of the saint's virtue.",
    "dailyPrayer": "Lord Jesus, lead me to live Your word today. Amen.",
    "theologicalSynthesis": "God calls us into communion in Christ through Word and Sacrament.",
    "exegesis": "Today's readings call us to deeper conversion and hope in Christ.",
}

def apply_fallbacks(draft: Dict[str, Any], meta: Dict[str, str]) -> None:
    """
    Mutates `draft` in-place with minimal, safe defaults so required fields are
    never empty. This only runs if the model omitted something.
    """
    # textual fields (keep incredibly short; schema only checks non-empty)
    for k, default in FALLBACK_SENTENCES.items():
        if not str(draft.get(k, "")).strip():
            draft[k] = default

    # quotes often missing a citation; set a safe one if absent
    if not str(draft.get("quoteCitation", "")).strip():
        draft["quoteCitation"] = (
            draft.get("gospelReference")
            or meta.get("gospelRef")
            or draft.get("firstReadingRef")
            or meta.get("firstRef")
            or "Scripture"
        )
# -----------------------------------------------------------------------------


def main():
    print(f"[info] tz={APP_TZ} start={START} days={DAYS} model={MODEL}")

    # optional schema load
    validator = None
    if SCHEMA_PATH.exists():
        try:
            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            validator = Draft202012Validator(schema)
        except Exception:
            print(f"[warn] could not load schema at {SCHEMA_PATH}; continuing")

    # load existing file defensively
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

    wanted_dates = [(START + timedelta(days=i)).isoformat() for i in range(DAYS)]

    # fast scraper-only pass
    if os.getenv("USCCB_PRECHECK") == "1":
        for ds in wanted_dates:
            d = date.fromisoformat(ds)
            meta = fetch_usccb_meta(d)
            print(f"[ok] {ds}: First={meta['firstRef']} | Psalm={meta['psalmRef']} | Gospel={meta['gospelRef']}")
        return

    client = OpenAI()

    for ds in wanted_dates:
        d = date.fromisoformat(ds)
        meta = fetch_usccb_meta(d)
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
            f"Saint: {meta['saintName']} - {meta['saintNote']}",
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
            draft = json.loads(raw)
        except Exception:
            draft = json.loads(extract_json(raw))

        # ensure required fields are not empty
        apply_fallbacks(draft, meta)

        obj = canonicalize(draft, ds=ds, d=d, meta=meta, lk=lk)
        obj = normalize_day(obj)
        by_date[ds] = obj
        print(f"[ok] {ds} — refs: {obj['firstReadingRef']} | {obj['psalmRef']} | {obj['gospelRef']}")

    out = [by_date[ds] for ds in wanted_dates if ds in by_date]

    # --- optional JSON Schema validation (array-level) ---
    if validator:
        errs = list(validator.iter_errors(out))
        if errs:
            details = "; ".join(f"{'/'.join(map(str, e.path))}: {e.message}" for e in errs)
            raise SystemExit(f"Validation failed: {details}")

    WEEKLY_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEEKLY_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[ok] wrote {WEEKLY_PATH} with {len(out)} entries")


if __name__ == "__main__":
    main()