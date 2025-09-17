#!/usr/bin/env python3
"""
Weekly generator for FaithLinks.

What changed (vs your last version):
- Reads saints from public/saint.json (or falls back to https://dailylectio.org/saint.json).
- Overlays saint data onto each day BEFORE prompting the model, so the copy never
  says “no saint today” when there is one.
- Asks the model to return a `tags` array; if it doesn’t, we synthesize sensible tags.
- Keeps `feast` optional (empty string is fine).

Environment (optional):
  APP_TZ=America/New_York
  START_DATE=YYYY-MM-DD  (default: today in APP_TZ)
  DAYS=7                 (clamped 1..14)
  GEN_MODEL=gpt-5.0-mini
  GEN_FALLBACK=gpt-5.0-mini
"""

import html as ihtml
import json, os, re, sys
from datetime import datetime, date, timedelta
from pathlib import Path
from jsonschema import Draft202012Validator
from openai import OpenAI
from collections import OrderedDict
from typing import List, Dict, Any, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------- repo paths ----------
ROOT         = Path(__file__).resolve().parents[1]
WEEKLY_PATH  = ROOT / "public" / "weeklyfeed.json"
SAINT_LOCAL  = ROOT / "public" / "saint.json"
SCHEMA_PATH  = ROOT / "schemas" / "devotion.schema.json"
USCCB_BASE   = "https://bible.usccb.org/bible/readings"

# ---------- model knobs ----------
MODEL          = os.getenv("GEN_MODEL", "gpt-5.0-mini")
FALLBACK_MODEL = os.getenv("GEN_FALLBACK", "gpt-5.0-mini")
TEMP_MAIN      = float(os.getenv("GEN_TEMP", "0.55"))
TEMP_REPAIR    = float(os.getenv("GEN_TEMP_REPAIR", "0.45"))
TEMP_QUOTE     = float(os.getenv("GEN_TEMP_QUOTE", "0.35"))

def safe_chat(client, *, temperature, response_format, messages, model=None):
    """Create a chat completion with graceful fallbacks (temp unsupported / model swap)."""
    def _create(use_model, allow_temp=True):
        kwargs = {
            "model": use_model,
            "response_format": response_format,
            "messages": messages,
        }
        # Some GPT-5 variants enforce default temp (1.0). Skip temp in that case.
        if allow_temp and (temperature is not None) and not str(use_model).startswith("gpt-5"):
            kwargs["temperature"] = temperature
        return client.chat.completions.create(**kwargs)

    use_model = model or MODEL
    try:
        return _create(use_model, allow_temp=True)
    except Exception as e:
        msg = str(e).lower()
        if ("temperature" in msg and "only the default" in msg) or \
           ("unsupported_value" in msg and "temperature" in msg):
            try:
                return _create(use_model, allow_temp=False)
            except Exception:
                pass
        if any(k in msg for k in ("model", "permission", "not found", "unknown")) and FALLBACK_MODEL != use_model:
            try:
                return _create(FALLBACK_MODEL, allow_temp=True)
            except Exception as e2:
                msg2 = str(e2).lower()
                if ("temperature" in msg2 and "only the default" in msg2) or \
                   ("unsupported_value" in msg2 and "temperature" in msg2):
                    return _create(FALLBACK_MODEL, allow_temp=False)
                raise
        raise

# ---------- output contract ----------
KEY_ORDER = [
    "date","quote","quoteCitation",
    "firstReading","secondReading",
    "psalmSummary","gospelSummary","saintReflection",
    "dailyPrayer","theologicalSynthesis","exegesis",
    "tags",
    # refs / meta
    "usccbLink","cycle","weekdayCycle","feast",
    "gospelReference","firstReadingRef","secondReadingRef","psalmRef","gospelRef",
    "lectionaryKey",
]
NULLABLE_STR_FIELDS = {
    "secondReading", "feast", "firstReadingRef", "secondReadingRef",
    "psalmRef", "gospelRef", "gospelReference", "lectionaryKey"
}

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
- exegesis: 500-750, formatted as 5-6 short paragraphs with brief headings (Context:, Psalm:, Gospel:, Saints:, Today:), with blank lines between paragraphs.

Rules:
- If a SAINT is provided, DO NOT say “no saint today.” Write the saintReflection for that saint (use provided profile if present) and weave the feast/memorial naturally into the other sections when appropriate.
- Do NOT paste long Scripture passages; paraphrase faithfully (you may use a short quote in the `quote` field).
- Warm, pastoral, Christ-centered, accessible; concrete connections for modern life.
- Integrate 1–3 Catechism of the Catholic Church citations (by paragraph number) where relevant—especially in `theologicalSynthesis`, `dailyPrayer`, and `exegesis`. Format them like (CCC 614). Keep them brief; no long quotations.
- Only include real CCC paragraph numbers. If uncertain, prefer foundational anchors (e.g., 136–141 on Scripture, 456–460 on the Incarnation, 1420–1498 on the Sacraments of Healing) and avoid inventing specifics.
- Return ONLY a JSON object containing all contract keys. Include `tags` as an array of 6–12 concise, lowercase, hyphenated topics (e.g., ["humility","mercy","saint-francis","luke","prayer","justice"])."""

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
        s=str(t).strip().lower().replace(" ", "-")
        if s: out.append(s)
        if len(out)>=12: break
    return out

def slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.strip().lower()).strip("-")
    return s

def first_word(s: str) -> str:
    return (s or "").split(" ", 1)[0].strip()

def make_lectionary_key(meta: Dict[str, str]) -> str:
    parts = [meta.get("firstRef","").replace(" ",""),
             meta.get("psalmRef","").replace(" ",""),
             meta.get("gospelRef","").replace(" ",""),
             meta.get("cycle",""), meta.get("weekday","")]
    return "|".join(p for p in parts if p)

# ---------- requests session with retry ----------
_retry = Retry(
    total=4, backoff_factor=0.5,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=("GET",),
    raise_on_status=False,
)
SESSION = requests.Session()
SESSION.mount("https://", HTTPAdapter(max_retries=_retry))
SESSION.mount("http://",  HTTPAdapter(max_retries=_retry))

# ---------- robust USCCB scraping ----------
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
REF_RE = re.compile(
    rf"({BOOK_PATTERN}\s+\d+(?::[0-9,\-\u2013\s]+)?(?:\s*(?:and|;)\s*[0-9:,\-\u2013\s]+)*)",
    flags=re.I
)

def _html_to_text(html: str) -> str:
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
    """Limited fallback when explicit labels aren't found."""
    head = text[:3000]
    refs = [m.group(1) for m in REF_RE.finditer(head)]
    seen, uniq = set(), []
    for r in refs:
        rr = _normalize_psalm_name(r)
        if rr.lower() not in seen:
            seen.add(rr.lower()); uniq.append(rr)
    out = {"firstRef":"", "secondRef":"", "psalmRef":"", "gospelRef":""}
    for r in uniq:
        low = r.lower()
        if any(g in low for g in ("matthew","mark","luke","john")) and not out["gospelRef"]:
            out["gospelRef"] = r; continue
        if "psalm" in low and not out["psalmRef"]:
            out["psalmRef"] = r; continue
    leftovers = [r for r in uniq if r not in (out["gospelRef"], out["psalmRef"])][:2]
    if leftovers:
        out["firstRef"] = leftovers[0]
    if len(leftovers) > 1:
        out["secondRef"] = leftovers[1]
    return out

def fetch_usccb_meta(d: date) -> Dict[str,str]:
    txt = _fetch_usccb_text(d)

    first = _find_ref_after(["Reading I","Reading 1","First Reading","First Reading:"], txt)
    second = _find_ref_after(["Reading II","Reading 2","Second Reading","Second Reading:"], txt)
    psalm = _find_ref_after(["Responsorial Psalm","Responsorial Psalm:"], txt)
    gospel = _find_ref_after(["Gospel","Gospel:"], txt)

    if not (first and psalm and gospel):
        guess = _heuristic_assign(txt)
        first  = first  or guess["firstRef"]
        second = second or guess["secondRef"]
        psalm  = psalm  or guess["psalmRef"]
        gospel = gospel or guess["gospelRef"]

    if not (first and psalm and gospel):
        raise SystemExit(f"USCCB parse incomplete for {d.isoformat()} (first/psalm/gospel required)")

    # Best-effort feast/saint detection (optional)
    feast = ""
    m = re.search(r"(?im)^\s*(?:Memorial|Feast|Solemnity|Optional Memorial|Saint|St\.)[^\n]+", txt)
    if m: feast = m.group(0).strip()

    saintName = ""
    m2 = re.search(r"(Saint|St\.)\s+([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+)*)", feast or "")
    if m2:
        saintName = m2.group(0).replace("St.", "Saint")

    return {
        "firstRef": first,
        "secondRef": second or "",
        "psalmRef": psalm,
        "gospelRef": gospel,
        "feast": feast,                 # may be ""
        "cycle":  "Year C",
        "weekday":"Cycle I",
        "saintName": saintName,         # may be ""
        "saintNote": "",
        "url": usccb_link(d),
        "rawText": txt[:800],           # tiny slice for debugging
    }

# ---------- saints overlay ----------
def load_saints_map() -> Dict[str, Dict[str,str]]:
    """Return {YYYY-MM-DD: saint_row} from local or remote file; tolerate errors."""
    data = None
    # prefer local public/saint.json
    try:
        if SAINT_LOCAL.exists():
            data = json.loads(SAINT_LOCAL.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[warn] could not read {SAINT_LOCAL}: {e}")

    # fallback: remote
    if data is None:
        try:
            r = SESSION.get("https://dailylectio.org/saint.json", timeout=15)
            if r.ok and r.text:
                data = json.loads(r.text)
        except Exception as e:
            print(f"[warn] could not fetch remote saint.json: {e}")

    out: Dict[str, Dict[str,str]] = {}
    if isinstance(data, list):
        for row in data:
            if isinstance(row, dict) and "date" in row:
                out[str(row.get("date")).strip()] = row
    return out

# ---------- fallbacks ----------
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

# ---------- tag helpers ----------
BOOK_ALIASES = {
    "psalm":"psalm", "psalms":"psalm", "ps":"psalm",
    "matthew":"matthew","mark":"mark","luke":"luke","john":"john",
}

def _book_tag(ref: str) -> str:
    if not ref: return ""
    b = first_word(ref).lower()
    b = BOOK_ALIASES.get(b, b)
    return slug(b)

def auto_tags(meta: Dict[str,str], draft: Dict[str,Any]) -> List[str]:
    tags = clean_tags(draft.get("tags"))
    if tags:
        return tags
    out = []
    for ref in (meta.get("firstRef",""), meta.get("psalmRef",""), meta.get("gospelRef","")):
        t = _book_tag(ref)
        if t and t not in out: out.append(t)
    # saint tag
    if meta.get("saintName"):
        st = "saint-" + slug(meta["saintName"])
        if st not in out: out.append(st)
    # memorial level if given
    mem = (meta.get("memorial") or "").strip()
    if mem:
        if mem.lower().startswith("solemn"): out.append("solemnity")
        elif mem.lower().startswith("feast"): out.append("feast")
        elif "optional" in mem.lower(): out.append("optional-memorial")
        else: out.append(slug(mem))
    # a couple of general faith tags
    for t in ("mercy","prayer","discipleship"):
        if t not in out: out.append(t)
    return out[:12]

# ---------- canonicalization ----------
def canonicalize(draft: Dict[str,Any], *, ds: str, d: date, meta: Dict[str,str], lk: str) -> Dict[str, Any]:
    def S(k, default=""):
        v = draft.get(k)
        if v is None: return default
        s = str(v).strip()
        return s if s else default

    # normalize second reading text & ref
    second_reading = draft.get("secondReading")
    if isinstance(second_reading,str): second_reading = second_reading.strip() or ""
    elif second_reading is None:       second_reading = ""
    else:                              second_reading = str(second_reading).strip() or ""

    second_ref = S("secondReadingRef") or meta.get("secondRef","") or ""

    # fields from the draft (with defaults)
    quote                 = S("quote")
    quoteCitation         = S("quoteCitation") or S("gospelReference") or meta.get("gospelRef","") \
                            or S("firstReadingRef") or meta.get("firstRef","")
    first_reading         = S("firstReading")
    psalm_summary         = S("psalmSummary")
    gospel_summary        = S("gospelSummary")
    daily_prayer          = S("dailyPrayer")
    saint_reflection      = S("saintReflection")
    theological_synthesis = S("theologicalSynthesis")
    exegesis              = S("exegesis")
    tags                  = auto_tags(meta, draft)

    # refs/meta (prefer model, then meta)
    first_ref        = S("firstReadingRef") or meta.get("firstRef","")
    psalm_ref        = S("psalmRef") or meta.get("psalmRef","")
    gospel_ref       = S("gospelRef") or meta.get("gospelRef","")
    gospel_reference = S("gospelReference") or meta.get("gospelRef","")
    feast            = S("feast") or meta.get("feast","")
    cycle            = S("cycle") or meta.get("cycle","Year C")
    weekday_cycle    = S("weekdayCycle") or meta.get("weekday","Cycle I")
    usccb_url        = meta.get("url") or usccb_link(d)

    obj = {
        "date": ds,
        "quote": quote,
        "quoteCitation": quoteCitation,
        "firstReading": first_reading,
        "secondReading": second_reading,
        "psalmSummary": psalm_summary,
        "gospelSummary": gospel_summary,
        "saintReflection": saint_reflection,
        "dailyPrayer": daily_prayer,
        "theologicalSynthesis": theological_synthesis,
        "exegesis": exegesis,

        # meta / refs
        "tags": tags,
        "usccbLink": usccb_url,
        "cycle": cycle,
        "weekdayCycle": weekday_cycle,
        "feast": feast,                      # may be ""
        "gospelReference": gospel_reference,
        "firstReadingRef": first_ref,
        "secondReadingRef": second_ref,
        "psalmRef": psalm_ref,
        "gospelRef": gospel_ref,
        "lectionaryKey": lk,
    }

    # guarantee nullable-string fields use ""
    for k in NULLABLE_STR_FIELDS:
        if obj.get(k) is None:
            obj[k] = ""
    if obj.get("tags") is None:
        obj["tags"] = []

    return obj

# ---------- ordering / normalization ----------
def _order_keys(entry: Dict[str, Any]) -> OrderedDict:
    for k in NULLABLE_STR_FIELDS:
        if entry.get(k) is None:
            entry[k] = ""
    if entry.get("tags") is None:
        entry["tags"] = []
    out = OrderedDict()
    for k in KEY_ORDER:
        if k == "tags":
            out[k] = entry.get(k, [])
        elif k in NULLABLE_STR_FIELDS:
            out[k] = entry.get(k, "") or ""
        else:
            out[k] = entry.get(k, "")
    return out

def normalize_day(entry: Dict[str, Any]) -> OrderedDict:
    entry = _normalize_enums(_normalize_refs(entry))
    if isinstance(entry.get("tags"), str):
        entry["tags"] = [s.strip() for s in entry["tags"].split(",") if s.strip()]
    elif not isinstance(entry.get("tags"), list):
        entry["tags"] = []
    return _order_keys(entry)

# ---------- main ----------
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

    # load existing weekly (if any)
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

    # saints map
    saints_by_date = load_saints_map()

    wanted_dates = [(START + timedelta(days=i)).isoformat() for i in range(DAYS)]

    # quick scraper-only pass
    if os.getenv("USCCB_PRECHECK") == "1":
        for ds in wanted_dates:
            d = date.fromisoformat(ds)
            meta = fetch_usccb_meta(d)
            if ds in saints_by_date:
                s = saints_by_date[ds]
                meta["saintName"] = s.get("saintName","") or meta.get("saintName","")
                meta["memorial"]  = s.get("memorial","")
            saint = f" | Saint={meta.get('saintName','')}" if meta.get("saintName") else ""
            print(f"[ok] {ds}: First={meta['firstRef']} | Psalm={meta['psalmRef']} | Gospel={meta['gospelRef']}{saint}")
        return

    client = OpenAI()

    for ds in wanted_dates:
        d = date.fromisoformat(ds)
        meta = fetch_usccb_meta(d)

        # Overlay saint from public/saint.json if present
        saint_profile = ""
        if ds in saints_by_date:
            srow = saints_by_date[ds]
            meta["saintName"] = srow.get("saintName","") or meta.get("saintName","")
            meta["memorial"]  = srow.get("memorial","")
            # If `feast` is still empty, borrow memorial string (it’s optional overall).
            if not meta.get("feast"): meta["feast"] = srow.get("memorial","")
            saint_profile = (srow.get("profile","") or "").strip()

        lk   = make_lectionary_key(meta)

        user_lines = [
            "CCC: https://usccb.cld.bz/Catechism-of-the-Catholic-Church",
            f"Date: {ds}",
            f"USCCB: {meta['url']}",
            f"Cycle: {meta['cycle']}  WeekdayCycle: {meta['weekday']}",
            f"Feast: {meta.get('feast','')}",
            "Readings:",
            f"  First:  {meta['firstRef']}",
            f"  Psalm:  {meta['psalmRef']}",
            f"  Gospel: {meta['gospelRef']}",
            f"Saint: {meta.get('saintName','')}",
        ]
        if saint_profile:
            user_lines.append(f"SaintProfile: {saint_profile[:900]}")  # give the model context, limit length
        user_msg = "\n".join(user_lines)

        # main generation
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
        saint = f" | Saint={meta.get('saintName','')}" if meta.get("saintName") else ""
        print(f"[ok] {ds} — refs: {obj['firstReadingRef']} | {obj['psalmRef']} | {obj['gospelRef']}{saint}")

    out = [by_date[ds] for ds in wanted_dates if ds in by_date]

    # optional JSON Schema validation (array-level)
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
