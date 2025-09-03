#!/usr/bin/env python3
"""
Weekly generator with reliable Saint-of-the-Day detection.

Saint source order (best → fallback):
1) Liturgical Calendar API (litcal.johnromanodorazio.com)
2) Inadiutorium CalAPI (calapi.inadiutorium.cz)
3) CatholicSaints.mobi daily calendar (first <li><a> entry)

FAST SCRAPE CHECK (no OpenAI, no writes):
USCCB_PRECHECK=1 START_DATE=2025-09-01 DAYS=7 python scripts/generate_weekly.py
"""

import html as ihtml
import json, os, re, sys
from datetime import datetime, date, timedelta
from pathlib import Path
from jsonschema import Draft202012Validator
from openai import OpenAI
from collections import OrderedDict
from typing import List, Dict, Any, Tuple, Iterable

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------- repo paths ----------
ROOT = Path(__file__).resolve().parents[1]
WEEKLY_PATH = ROOT / "public" / "weeklyfeed.json"
SCHEMA_PATH = ROOT / "schemas" / "devotion.schema.json"

# ---------- external endpoints ----------
USCCB_BASE   = "https://bible.usccb.org/bible/readings"
LITCAL_API   = "https://litcal.johnromanodorazio.com/api/dev/calendar"   # /{year}
INADIUTORIUM = "https://calapi.inadiutorium.cz/api/v0/en/calendars/general-en"
CATHOLICSAINTS_CAL = "http://catholicsaints.mobi/calendar"                # /{d-month}.htm

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
- secondReading: 50-100 (or empty if no second reading)
- psalmSummary: 50-100
- gospelSummary: 100-200
- saintReflection: 50-100
- dailyPrayer: 150-200
- theologicalSynthesis: 150-200
- exegesis: 500-750, 5–6 short paragraphs with brief headings and blank lines.

Rules:
- Paraphrase Scripture (no long quotes).
- Warm, pastoral, Christ-centered, concrete for daily life.
- Output ONLY a JSON object (no commentary).
"""

# ---------- hardened HTTP session ----------
_retry = Retry(total=4, backoff_factor=0.5,
               status_forcelist=(429,500,502,503,504),
               allowed_methods=("GET",), raise_on_status=False)

SESSION = requests.Session()
SESSION.mount("https://", HTTPAdapter(max_retries=_retry))
SESSION.mount("http://", HTTPAdapter(max_retries=_retry))

UA_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8,application/json",
}

# ---------- helpers ----------
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
    parts = [
        meta.get("firstRef","").replace(" ",""),
        meta.get("psalmRef","").replace(" ",""),
        meta.get("gospelRef","").replace(" ",""),
        meta.get("cycle",""), meta.get("weekday","")
    ]
    return "|".join(p for p in parts if p)

# ---------- HTML → text and ref parsing ----------
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

REF_RE = re.compile(
    rf"({BOOK_PATTERN}\s+\d+(?::[0-9,\-\u2013\s]+)?(?:\s*(?:and|;)\s*[0-9:,\-\u2013\s]+)*)",
    flags=re.I
)

def _html_to_text(html: str) -> str:
    txt = re.sub(r"(?i)</(p|li|h\d|div|br|tr|section)>", "\n", html)
    txt = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", txt)
    txt = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", txt)
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
    head = text[:3000]
    refs = [m.group(1) for m in REF_RE.finditer(head)]
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
    leftovers = [r for r in uniq if r not in (out["gospelRef"], out["psalmRef"])][:2]
    if leftovers:
        out["firstRef"] = leftovers[0]
        if len(leftovers) > 1:
            out["secondRef"] = leftovers[1]
    return out

# ---------- Saints: LitCal primary ----------
_LITCAL_ACCEPT = re.compile(
    r"\b(Saint|St\.|Blessed|Bl\.|Martyr|Apostle|Evangelist|Virgin|Bishop|Pope|Doctor|"
    r"Nativity|Annunciation|Assumption|Presentation|Immaculate|Conception|Exaltation|Transfiguration|"
    r"Guardian Angels|Archangels|Holy Family|All Saints|Our Lady|Mary|Visitation)\b",
    re.I,
)
_NUMERIC_TITLE = re.compile(r"^\s*\d+\s+\w+\s*$")  # e.g., "1 September"

def _looks_weekday_like(s: str) -> bool:
    sl = s.lower()
    return any(w in sl for w in ("feria", "weekday", "ordinary time", "weekday in", "weekday of"))

def _pick_litcal_title(objs: Iterable[dict]) -> str:
    first_non_weekday = ""
    for e in objs:
        title = (e.get("title") or e.get("titleEn") or e.get("name") or e.get("celebration") or "").strip()
        if not title:
            continue
        if _NUMERIC_TITLE.match(title):   # skip "1 September"
            continue
        cls = " ".join(str(e.get(k,"")) for k in ("class","rank","grade")).strip().lower()
        if _looks_weekday_like(title) or _looks_weekday_like(cls):
            continue
        if _LITCAL_ACCEPT.search(title):
            return title
        if not first_non_weekday:
            first_non_weekday = title
    return first_non_weekday

def fetch_litcal_saint(d: date) -> Tuple[str, str]:
    url = f"{LITCAL_API}/{d.year}"
    r = SESSION.get(url, headers=UA_HEADERS, timeout=20)
    if r.status_code != 200:
        raise RuntimeError("litcal http error")
    try:
        data = r.json()
    except Exception as ex:
        raise RuntimeError(f"litcal json error: {ex}")

    iso = d.isoformat()
    items: List[dict] = []
    if isinstance(data, dict):
        day_objs = data.get(iso) or data.get(iso.replace("-", "/"))
        if isinstance(day_objs, list):
            items = day_objs
    elif isinstance(data, list):
        items = [e for e in data if str(e.get("date","")).startswith(iso)]

    title = _pick_litcal_title(items)
    if title:
        return title, url
    raise RuntimeError("no litcal feast")

# ---------- Saints: Inadiutorium CalAPI (fallback #2) ----------
def fetch_inadiutorium_saint(d: date) -> Tuple[str,str]:
    url = f"{INADIUTORIUM}/{d.year}/{d.month:02d}/{d.day:02d}"
    r = SESSION.get(url, headers=UA_HEADERS, timeout=20)
    if r.status_code != 200:
        raise RuntimeError("inadiutorium http error")
    try:
        data = r.json()
    except Exception as ex:
        raise RuntimeError(f"inadiutorium json error: {ex}")

    cels = data.get("celebrations") or []
    # prefer saint/feast-like titles or rank >= memorial
    def _score(c):
        title = (c.get("title") or "").strip()
        rank = (c.get("rank") or "").lower()
        s = 0
        if _LITCAL_ACCEPT.search(title):
            s += 3
        if any(k in rank for k in ("solemnity","feast","memorial","commemoration","optional memorial")):
            s += 2
        if not _looks_weekday_like(title):
            s += 1
        return (s, title)

    best = ""
    best_s = -1
    for cel in cels:
        s, t = _score(cel)
        if s > best_s and t:
            best_s = s; best = t
    if best:
        return best, url
    raise RuntimeError("no inadiutorium feast")

# ---------- Saints: CatholicSaints.mobi fallback (#3) ----------
def _cs_clean_html(s: str) -> str:
    s = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", s)
    s = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", s)
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = s.replace("&nbsp;", " ").replace("&bull;", "•")
    s = re.sub(r"\s+", " ", s).strip("·•-–— ").strip()
    return s

def fetch_catholicsaints_saint(d: date) -> Tuple[str, str]:
    slug = f"{d.day}-{d.strftime('%B').lower()}.htm"  # e.g., 2-september.htm
    url  = f"{CATHOLICSAINTS_CAL}/{slug}"
    r = SESSION.get(url, headers=UA_HEADERS, timeout=20)
    if r.status_code != 200 or not r.text:
        raise RuntimeError("catholicsaints http error")

    html = r.text
    # target: first <li><a>NAME</a>...</li>
    m = re.search(r'(?is)<li[^>]*>\s*<a[^>]*>([^<]+)</a>', html)
    if m:
        name = _cs_clean_html(m.group(1))
        name = re.sub(r"\s*\(.*?\)\s*$", "", name).strip()
        # filter obvious header-like wrong hits
        if not _NUMERIC_TITLE.match(name) and name.lower() not in ("yesterday","tomorrow"):
            return name, url

    # fallback: first <li> text
    lis = re.findall(r"(?is)<li[^>]*>\s*(.*?)\s*</li>", html)
    for raw in lis:
        txt = _cs_clean_html(raw)
        if not txt:
            continue
        # cut at dash if present
        txt = re.split(r"\s*[–—-]\s*", txt)[0].strip()
        if _NUMERIC_TITLE.match(txt):  # skip "2 September"
            continue
        if txt.lower() in ("yesterday","tomorrow"):
            continue
        return txt, url

    raise RuntimeError("no items on catholicsaints")

def fetch_saint_of_day(d: date) -> Tuple[str,str]:
    """
    Returns (saint_or_feast_title, source_url).
    Tries LitCal → Inadiutorium → CatholicSaints.
    """
    try:
        title, src = fetch_litcal_saint(d)
        return title, src
    except Exception:
        pass
    try:
        title, src = fetch_inadiutorium_saint(d)
        return title, src
    except Exception:
        pass
    try:
        name, src = fetch_catholicsaints_saint(d)
        return name, src
    except Exception:
        pass
    return "", ""

# ---------- USCCB readings scrape ----------
def fetch_usccb_meta(d: date) -> Dict[str,str]:
    url = usccb_link(d)
    r = SESSION.get(url, headers=UA_HEADERS, timeout=20)
    if r.status_code != 200 or not r.text:
        alt = f"https://bible.usccb.org/bible/readings?date={d.isoformat()}"
        r = SESSION.get(alt, headers=UA_HEADERS, timeout=20)
        if r.status_code != 200 or not r.text:
            raise SystemExit(f"USCCB fetch failed for {d.isoformat()} (HTTP {r.status_code})")

    txt = _html_to_text(r.text)

    # Explicit labels
    first  = _find_ref_after(["Reading I","Reading 1","First Reading","First Reading:"], txt)
    second = _find_ref_after(["Reading II","Reading 2","Second Reading","Second Reading:"], txt)
    psalm  = _find_ref_after(["Responsorial Psalm","Responsorial Psalm:"], txt)
    gospel = _find_ref_after(["Gospel","Gospel:"], txt)

    # Heuristic fallback
    if not (first and psalm and gospel):
        guess  = _heuristic_assign(txt)
        first  = first  or guess["firstRef"]
        second = second or guess["secondRef"]
        psalm  = psalm  or guess["psalmRef"]
        gospel = gospel or guess["gospelRef"]

    if not (first and psalm and gospel):
        raise SystemExit(f"USCCB parse incomplete for {d.isoformat()} (first/psalm/gospel required)")

    saint_title, saint_src = fetch_saint_of_day(d)

    return {
        "firstRef": first,
        "secondRef": second or "",
        "psalmRef": psalm,
        "gospelRef": gospel,
        "feast": saint_title,
        "cycle": "Year C",
        "weekday":"Cycle I",
        "saintName": saint_title,
        "saintNote": saint_src,
        "url": url,
    }

# ---------- generation glue ----------
def canonicalize(draft: Dict[str,Any], *, ds: str, d: date, meta: Dict[str,str], lk: str) -> Dict[str, Any]:
    def S(k, default=""):
        v = draft.get(k)
        if v is None: return default
        s = str(v).strip()
        return s if s else default

    second_reading = draft.get("secondReading")
    if isinstance(second_reading,str): second_reading = second_reading.strip() or ""
    elif second_reading is None: second_reading = ""
    else: second_reading = str(second_reading).strip() or ""

    second_ref = draft.get("secondReadingRef")
    if isinstance(second_ref,str): second_ref = second_ref.strip() or ""
    elif second_ref is None: second_ref = ""
    else: second_ref = str(second_ref).strip() or ""
    if not second_ref:
        second_ref = meta.get("secondRef","") or ""

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
    for k, default in FALLBACK_SENTENCES.items():
        if not str(draft.get(k, "")).strip():
            draft[k] = default
    if not str(draft.get("quoteCitation", "")).strip():
        draft["quoteCitation"] = (
            draft.get("gospelReference")
            or meta.get("gospelRef")
            or draft.get("firstReadingRef")
            or meta.get("firstRef")
            or "Scripture"
        )

def main():
    print(f"[info] tz={APP_TZ} start={START} days={DAYS} model={MODEL}")

    validator = None
    if SCHEMA_PATH.exists():
        try:
            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            validator = Draft202012Validator(schema)
        except Exception:
            print(f"[warn] could not load schema at {SCHEMA_PATH}; continuing")

    try:
        raw_weekly = json.loads(WEEKLY_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw_weekly = []

    weekly = raw_weekly.get("weeklyDevotionals", []) if isinstance(raw_weekly, dict) else (raw_weekly if isinstance(raw_weekly, list) else [])
    by_date: Dict[str, Dict[str, Any]] = {str(e.get("date")): e for e in weekly if isinstance(e, dict)}
    wanted_dates = [(START + timedelta(days=i)).isoformat() for i in range(DAYS)]

    # PRECHECK — no OpenAI
    if os.getenv("USCCB_PRECHECK") == "1":
        for ds in wanted_dates:
            d = date.fromisoformat(ds)
            meta = fetch_usccb_meta(d)
            saint = meta.get("saintName") or "-"
            print(f"[ok] {ds}: First={meta['firstRef']} | Psalm={meta['psalmRef']} | Gospel={meta['gospelRef']} | Saint={saint}")
        return

    client = OpenAI()

    for ds in wanted_dates:
        d = date.fromisoformat(ds)
        meta = fetch_usccb_meta(d)
        lk = lectionary_key(meta)

        user_msg = "\n".join([
            f"Date: {ds}",
            f"USCCB: {meta['url']}",
            f"Cycle: {meta['cycle']} WeekdayCycle: {meta['weekday']}",
            f"Feast/Saint: {meta['saintName']}",
            "Readings:",
            f"  First:  {meta['firstRef']}",
            f"  Psalm:  {meta['psalmRef']}",
            f"  Gospel: {meta['gospelRef']}",
        ])

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

        apply_fallbacks(draft, meta)
        obj = canonicalize(draft, ds=ds, d=d, meta=meta, lk=lk)
        obj = normalize_day(obj)
        by_date[ds] = obj

        print(f"[ok] {ds} — refs: {obj['firstReadingRef']} | {obj['psalmRef']} | {obj['gospelRef']} | Saint={meta.get('saintName') or '-'}")

    out = [by_date[ds] for ds in wanted_dates if ds in by_date]

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