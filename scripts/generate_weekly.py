#!/usr/bin/env python3
import json, os, re
from datetime import datetime, date, timedelta
from pathlib import Path
from jsonschema import Draft202012Validator
from openai import OpenAI
from collections import OrderedDict
from typing import List, Dict, Any, Optional

# ---------- repo paths ----------
ROOT        = Path(__file__).resolve().parents[1]
WEEKLY_PATH = ROOT / "public" / "weeklyfeed.json"
SCHEMA_PATH = ROOT / "schemas" / "devotion.schema.json"
USCCB_BASE  = "https://bible.usccb.org/bible/readings"

# ---------- model knobs (override from workflow env) ----------
MODEL          = os.getenv("GEN_MODEL", "gpt-4o-mini")
FALLBACK_MODEL = os.getenv("GEN_FALLBACK", "gpt-4o-mini")
TEMP_MAIN      = float(os.getenv("GEN_TEMP", "0.55"))
TEMP_REPAIR    = float(os.getenv("GEN_TEMP_REPAIR", "0.45"))
TEMP_QUOTE     = float(os.getenv("GEN_TEMP_QUOTE", "0.35"))

def safe_chat(client, *, temperature, response_format, messages, model=None):
    """Try chosen model; if not available to the key, fall back without failing the run."""
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
        if any(k in msg for k in ("model", "permission", "not found", "unknown")) and FALLBACK_MODEL != use_model:
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
        (str(entry.get("weekdayCycle","")).strip() or str(entry.get("weekday","")).strip()),
        entry.get("weekdayCycle","Cycle I")
    )
    return entry

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

def usccb_link(d: date) -> str:
    return f"{USCCB_BASE}/{d.strftime('%m%d%y')}.cfm"

# ---------- USCCB scraping (authoritative, no fallbacks) ----------
# Requires: requests, beautifulsoup4, lxml  (install in workflow)
import requests
from bs4 import BeautifulSoup

REF_RE = re.compile(r"[1-3]?\s?[A-Za-z][A-Za-z ]*\s+\d+[:.]\d+(?:[-–]\d+)?(?:,\s?\d+[-–]?\d+)*")

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def _grab_first_ref_after(header) -> Optional[str]:
    node = header
    for _ in range(200):
        node = node.find_next(string=True) if hasattr(node, "find_next") else None
        if node is None:
            break
        m = REF_RE.search(_clean(str(node)))
        if m:
            return m.group(0)
    return None

def fetch_usccb_meta(d: date) -> Dict[str,str]:
    """Fetch feast/title + exact scripture refs from USCCB for the specific date. Abort on failure."""
    url = usccb_link(d)
    headers = {"User-Agent": "calm-bot/1.0 (+https://dailylectio.org)"}
    r = requests.get(url, timeout=20, headers=headers)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    # Feast / title
    h1 = soup.find(["h1","h2"])
    feast = _clean(h1.get_text()) if h1 else ""

    def find_header(label: str):
        return soup.find(lambda tag: tag.name in ["h2","h3","strong","b","p","span"]
                         and label.lower() in _clean(tag.get_text()).lower())

    h_r1   = find_header("Reading I") or find_header("First Reading")
    h_r2   = find_header("Reading II") or find_header("Second Reading")
    h_ps   = find_header("Responsorial Psalm") or find_header("Psalm")
    h_gosp = find_header("Gospel")

    first  = _grab_first_ref_after(h_r1) if h_r1 else ""
    second = _grab_first_ref_after(h_r2) if h_r2 else ""
    psalm  = _grab_first_ref_after(h_ps) if h_ps else ""
    gospel = _grab_first_ref_after(h_gosp) if h_gosp else ""

    # Normalize psalm commas/dashes
    psalm = _clean(psalm).replace(", ", ",").replace(" ,", ",").replace("—","-").replace("–","-")
    first, second, gospel = _clean(first), _clean(second), _clean(gospel)

    if not (first and psalm and gospel):
        raise RuntimeError("USCCB parse incomplete (missing required references)")

    # Try to extract saint name from title
    saint_name = ""
    m = re.search(r"(Saint|St\.)\s+([A-Z][A-Za-z'’\-]+(?:\s+[A-Z][A-Za-z'’\-]+)*)", feast)
    if m:
        saint_name = m.group(0).replace("St.", "Saint")

    # Note: USCCB doesn’t publish cycle strings; keep app defaults downstream
    return {
        "firstRef": first,
        "secondRef": second,
        "psalmRef": psalm,
        "gospelRef": gospel,
        "feast": feast,
        "saintName": saint_name,
        "saintNote": "",
        "url": url,
    }

def lectionary_key(meta: Dict[str, str]) -> str:
    parts = [meta.get("firstRef","").replace(" ",""),
             meta.get("psalmRef","").replace(" ",""),
             meta.get("gospelRef","").replace(" ","")]
    return "|".join(p for p in parts if p) + "|C|I"  # normalized default cycle labels

# ---------- quote + length helpers ----------
PAREN_REF_RE = re.compile(r"\s*\([^)]*\)\s*$")
def strip_trailing_paren_ref(s: str) -> str:
    return PAREN_REF_RE.sub("", s or "").strip()

BOOK_TOKEN_RE = re.compile(r"^\s*(\d?\s?[A-Za-z]+)")
def book_token(ref: str) -> str:
    ref = ref or ""
    m = BOOK_TOKEN_RE.search(ref)
    if not m: return ""
    first = m.group(1).strip()
    parts = first.split()
    return (parts[-1] if parts else first).lower()

def text_mentions_book(txt: str, ref: str) -> bool:
    token = book_token(ref)
    return True if not token else token in (txt or "").lower()

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
QUOTE_WORDS = (9, 25)
QUOTE_SENT  = (1, 2)
SENT_SPLIT = re.compile(r'[.!?]+(?=\s|$)')
WORD_RE    = re.compile(r'\b\w+\b')

def sent_count(txt: str) -> int:
    return len([s for s in SENT_SPLIT.split((txt or "").strip()) if s.strip()])

def word_count(txt: str) -> int:
    return len(WORD_RE.findall(txt or ""))

def meets_words(field: str, txt: str) -> bool:
    r = LENGTH_RULES.get(field)
    if not r: return True
    w = word_count(txt)
    return r["min_w"] <= w <= r["max_w"]

def exegesis_wants_paras(txt: str) -> bool:
    txt = txt or ""
    paras = [p for p in txt.split("\n\n") if p.strip()]
    has_5 = len(paras) >= 5
    headish = sum(1 for line in txt.splitlines()
                  if line.strip().endswith(":") or (line.strip().istitle() and len(line.split())<=6))
    return has_5 and headish >= 2

# ---------- normalization ----------
def _normalize_nullable_strings(entry: Dict[str, Any]) -> Dict[str, Any]:
    for k in NULLABLE_STR_FIELDS:
        v = entry.get(k, "")
        entry[k] = "" if v is None else str(v)
    return entry

def _mirror_gospel_keys(entry: Dict[str, Any]) -> Dict[str, Any]:
    gref = entry.get("gospelReference") or entry.get("gospelRef") or ""
    entry["gospelReference"] = gref
    entry["gospelRef"] = gref
    return entry

def _order_keys(entry: Dict[str, Any]) -> OrderedDict:
    ordered = OrderedDict()
    for k in KEY_ORDER:
        if k in NULLABLE_STR_FIELDS and (entry.get(k) is None):
            ordered[k] = ""
        else:
            ordered[k] = entry.get(k, "" if k in NULLABLE_STR_FIELDS else ([] if k=="tags" else ""))
    return ordered

def normalize_day(entry: Dict[str, Any]) -> OrderedDict:
    entry = _normalize_enums(_normalize_refs(_mirror_gospel_keys(_normalize_nullable_strings(entry))))
    if isinstance(entry.get("tags"), str):
        entry["tags"] = [s.strip() for s in entry["tags"].split(",") if s.strip()]
    elif not isinstance(entry.get("tags"), list):
        entry["tags"] = []
    return _order_keys(entry)

# ---------- canonicalizer ----------
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

    obj = {
        "date": ds,
        "quote": S("quote"),
        "quoteCitation": S("quoteCitation"),
        "firstReading": S("firstReading"),
        "psalmSummary": S("psalmSummary"),
        "gospelSummary": S("gospelSummary"),
        "saintReflection": S("saintReflection"),
        "dailyPrayer": S("dailyPrayer"),
        "theologicalSynthesis": S("theologicalSynthesis"),
        "exegesis": S("exegesis"),
        "secondReading": second_reading,
        "tags": draft.get("tags") if isinstance(draft.get("tags"), list) else [],
        "usccbLink": meta.get("url") or usccb_link(d),
        "cycle": S("cycle") or "Year C",
        "weekdayCycle": S("weekdayCycle") or "Cycle I",
        "feast": S("feast") or meta.get("feast",""),
        "gospelReference": S("gospelReference") or meta.get("gospelRef",""),
        "firstReadingRef": S("firstReadingRef") or meta.get("firstRef",""),
        "secondReadingRef": second_ref,
        "psalmRef": S("psalmRef") or meta.get("psalmRef",""),
        "gospelRef": S("gospelRef") or meta.get("gospelRef",""),
        "lectionaryKey": S("lectionaryKey") or lk,
    }
    return obj

# ---------- main ----------
def main():
    print(f"[info] tz={APP_TZ} start={START} days={DAYS} model={MODEL}")

    # optional schema (checked at the end)
    validator = None
    if SCHEMA_PATH.exists():
        try:
            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            validator = Draft202012Validator(schema)
        except Exception:
            print(f"[warn] could not load schema at {SCHEMA_PATH}; continuing")

    # load prior weekly file defensively
    raw_weekly = {}
    try:
        raw_weekly = json.loads(WEEKLY_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    weekly = raw_weekly.get("weeklyDevotionals", []) if isinstance(raw_weekly, dict) else (raw_weekly if isinstance(raw_weekly, list) else [])
    by_date: Dict[str, Dict[str, Any]] = {str(e.get("date")): e for e in weekly if isinstance(e, dict)}

    client  = OpenAI()
    wanted_dates = [(START + timedelta(days=i)).isoformat() for i in range(DAYS)]

    # prevent duplicate quotes across the week
    used_quotes = { (e.get("quote","") or "").strip() for e in weekly if isinstance(e, dict) }

    for i, ds in enumerate(wanted_dates):
        d = date.fromisoformat(ds)

        # --- fetch authoritative USCCB refs; abort if we cannot ---
        try:
            meta = fetch_usccb_meta(d)
        except Exception as e:
            raise SystemExit(f"[error] Could not fetch/parse USCCB for {ds}: {e}")

        lk = lectionary_key(meta)

        # --- prompt style card ---
        STYLE_CARD = """ROLE: Catholic editor + theologian for FaithLinks.

Audience: teens + adults (high school through adult).

Strict lengths (words):
- quote: 9–25 words (1–2 sentences) with a short citation like "Mk 8:34".
- firstReading: 50–100
- secondReading: 50–100 (or empty if there is no second reading that day)
- psalmSummary: 50–100
- gospelSummary: 100–200
- saintReflection: 50–100 (mention the saint by name if meta.saintName is provided)
- dailyPrayer: 150–200
- theologicalSynthesis: 150–200
- exegesis: 500–750, formatted as 5–6 short paragraphs with brief headings (e.g., Context:, Psalm:, Gospel:, Fathers:, Today:) and a blank line between paragraphs.

Rules:
- Use ONLY these scripture references from USCCB for this date; do not substitute other passages.
- Do NOT paste long Scripture passages; paraphrase faithfully. The 'quote' field may include a short Scripture line with citation.
- Warm, pastoral, Christ-centered, accessible; concrete connections for modern life.
- Return ONLY a JSON object containing the contract keys (no commentary).
"""

        user_msg = "\n".join([
            f"Date: {ds}",
            f"USCCB: {meta['url']}",
            f"Feast/Title: {meta.get('feast','')}",
            "Readings:",
            f"  First:  {meta['firstRef']}",
            f"  Psalm:  {meta['psalmRef']}",
            f"  Gospel: {meta['gospelRef']}",
            f"Second Reading (if any): {meta.get('secondRef','')}",
            f"Saint: {meta.get('saintName','')}",
        ])

        # --- generate ---
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
            # try to recover a JSON object if model added chatter
            s = raw.find("{"); e = raw.rfind("}")
            draft = json.loads(raw[s:e+1]) if (s>=0 and e>s) else {}

        # --- quote: enforce ranges + avoid reuse; strip trailing (Book X:Y) ---
        draft["quote"] = strip_trailing_paren_ref(str(draft.get("quote","")).strip())
        q  = draft["quote"]
        qc = str(draft.get("quoteCitation","")).strip()
        valid_q = (QUOTE_WORDS[0] <= word_count(q) <= QUOTE_WORDS[1] and
                   QUOTE_SENT[0]  <= sent_count(q)  <= QUOTE_SENT[1] and
                   q not in used_quotes and
                   (text_mentions_book(q, meta["gospelRef"]) or text_mentions_book(q, meta["firstRef"]) or text_mentions_book(q, meta.get("secondRef","")) or text_mentions_book(q, meta["psalmRef"])))
        if not valid_q or len(qc) < 2:
            fix = safe_chat(
                client,
                temperature=TEMP_QUOTE,
                response_format={"type":"json_object"},
                messages=[
                    {"role":"system","content":"Return JSON with 'quote' and 'quoteCitation' only."},
                    {"role":"user","content":
                        f"Pick ONE Scripture line from these refs only (9–25 words, 1–2 sentences). "
                        f"Include short citation.\nFirst: {meta['firstRef']}\nPsalm: {meta['psalmRef']}\n"
                        f"Gospel: {meta['gospelRef']}\nSecond: {meta.get('secondRef','')}\nDate: {ds}  USCCB: {meta['url']}"}
                ],
                model=MODEL
            )
            try:
                got = json.loads(fix.choices[0].message.content)
                if got.get("quote"): draft["quote"] = strip_trailing_paren_ref(got["quote"])
                if got.get("quoteCitation"): draft["quoteCitation"] = got["quoteCitation"].strip()
            except Exception:
                pass
        used_quotes.add(draft.get("quote",""))

        # --- enforce word ranges & exegesis formatting ---
        for field in ["firstReading","secondReading","psalmSummary","gospelSummary",
                      "saintReflection","dailyPrayer","theologicalSynthesis","exegesis"]:
            if field == "secondReading" and not str(draft.get("secondReading","")).strip():
                draft["secondReading"] = ""  # allowed empty
                continue

            txt = str(draft.get(field,"")).strip()
            need = not meets_words(field, txt)
            if field == "exegesis":
                need = need or (not exegesis_wants_paras(txt))
            if need:
                spec = LENGTH_RULES[field]
                para_hint = ("\nFormat as 5–6 short paragraphs with brief headings "
                             "(e.g., Context:, Psalm:, Gospel:, Fathers:, Today:) separated by blank lines."
                            ) if field == "exegesis" else ""
                ask = (
                    f"Write {spec['min_w']}-{spec['max_w']} words for {field}. "
                    "Do not paste long Scripture; paraphrase faithfully. Warm, pastoral, concrete."
                    f"\nFIRST: {meta['firstRef']}\nPSALM: {meta['psalmRef']}\nGOSPEL: {meta['gospelRef']}"
                    f"\nSECOND: {meta.get('secondRef','')}\nSAINT: {meta.get('saintName','')}{para_hint}"
                )
                r = safe_chat(
                    client,
                    temperature=TEMP_REPAIR,
                    response_format={"type":"json_object"},
                    messages=[{"role":"system","content":"Return JSON with a single key 'text'."},
                              {"role":"user","content": ask}],
                    model=MODEL
                )
                try:
                    obj = json.loads(r.choices[0].message.content)
                    new_txt = str(obj.get("text","")).strip()
                    if meets_words(field, new_txt) and (field!="exegesis" or exegesis_wants_paras(new_txt)):
                        draft[field] = new_txt
                except Exception:
                    pass

        # --- turn into contract object & normalize ---
        obj = canonicalize(draft, ds=ds, d=d, meta=meta, lk=lk)
        obj = normalize_day(obj)
        by_date[ds] = obj
        print(f"[ok] {ds} — quote='{obj['quote']}' ({obj['quoteCitation']})")

    # only the requested window, in order
    out = [by_date[ds] for ds in wanted_dates if ds in by_date]

    # optional JSON Schema validation (array-level)
    if validator:
        errs = list(validator.iter_errors(out))
        if errs:
            details = "; ".join([f"{'/'.join(map(str, e.path))}: {e.message}" for e in errs])
            raise SystemExit(f"Validation failed: {details}")

    WEEKLY_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEEKLY_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[ok] wrote {WEEKLY_PATH} with {len(out)} entries")

if __name__ == "__main__":
    main()
