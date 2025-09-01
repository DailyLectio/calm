#!/usr/bin/env python3
# USCCB-only generator (no local hints, no non-USCCB fallbacks).
# If USCCB parse misses a required ref (first/psalm/gospel), the run exits.

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
MODEL          = os.getenv("GEN_MODEL", "gpt-4o-mini")   # e.g., "gpt-5-thinking"
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
# fields that must serialize as empty strings (never null)
NULLABLE_STR_FIELDS = ("secondReading", "feast", "secondReadingRef")

# ---------- small utilities ----------
def usccb_link(d: date) -> str:
    return f"{USCCB_BASE}/{d.strftime('%m%d%y')}.cfm"

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

CYCLE_MAP   = {"A":"Year A","B":"Year B","C":"Year C","Year A":"Year A","Year B":"Year B","Year C":"Year C"}
WEEKDAY_MAP = {"I":"Cycle I","II":"Cycle II","Cycle I":"Cycle I","Cycle II":"Cycle II"}

def _normalize_refs(entry: Dict[str, Any]) -> Dict[str, Any]:
    for k in ("firstReadingRef","psalmRef","secondReadingRef","gospelRef","gospelReference"):
        v = entry.get(k, "")
        entry[k] = "" if v is None else str(v)
    return entry

def _normalize_enums(entry: Dict[str, Any]) -> Dict[str, Any]:
    # USCCB doesn’t publish the cycles on the page; preserve any existing values or default.
    entry["cycle"] = CYCLE_MAP.get(str(entry.get("cycle","")).strip(), entry.get("cycle","Year C"))
    entry["weekdayCycle"] = WEEKDAY_MAP.get(
        str(entry.get("weekdayCycle","")).strip() or str(entry.get("weekday","")).strip(),
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

# ---------- USCCB scraping via stdlib only ----------
# We avoid 3rd-party deps due to proxy/install issues.
from urllib import request, error

REF_RE = re.compile(r"[1-3]?\s?[A-Za-z][A-Za-z ]*\s+\d+[:.]\d+(?:[-–]\d+)?(?:,\s?\d+[-–]?\d+)*")
SPACE = re.compile(r"\s+")

def _clean_text(s: str) -> str:
    return SPACE.sub(" ", (s or "")).strip()

def _find_after(html: str, anchor_labels: List[str]) -> Optional[str]:
    """
    Find the first scripture-like reference that appears after any of the given
    anchor labels (e.g., 'Reading I', 'Responsorial Psalm', 'Gospel').
    """
    # make a forgiving search: find an anchor position, then search the next ~4k chars
    lower = html.lower()
    pos = -1
    for label in anchor_labels:
        i = lower.find(label.lower())
        if i >= 0:
            if pos == -1 or i < pos:
                pos = i
    if pos < 0:
        return None
    window = html[pos: pos + 4000]
    m = REF_RE.search(_clean_text(window))
    return m.group(0) if m else None

FEAST_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE|re.DOTALL)

def fetch_usccb_meta(d: date) -> Dict[str,str]:
    url = usccb_link(d)
    headers = {"User-Agent": "calm-bot/1.0 (+https://dailylectio.org) stdlib-urllib"}
    req = request.Request(url, headers=headers)
    try:
        with request.urlopen(req, timeout=25) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except error.HTTPError as e:
        raise SystemExit(f"USCCB HTTP {e.code} for {d.isoformat()}") from e
    except Exception as e:
        raise SystemExit(f"USCCB fetch failed for {d.isoformat()}: {e}") from e

    # Feast (page title h1)
    feast = ""
    m = FEAST_RE.search(raw)
    if m:
        feast = _clean_text(re.sub("<.*?>", "", m.group(1)))

    # First/Second/Psalm/Gospel refs — look after common headings
    first  = _find_after(raw, ["Reading I", "First Reading"])
    second = _find_after(raw, ["Reading II", "Second Reading"])
    psalm  = _find_after(raw, ["Responsorial Psalm", "Psalm"])
    gospel = _find_after(raw, ["Gospel"])

    # Normalize Psalm commas/hyphens
    if psalm:
        psalm = psalm.replace(", ", ",").replace(" ,", ",").replace("—","-").replace("–","-")

    # Require First/Psalm/Gospel to be present
    if not (first and psalm and gospel):
        raise SystemExit(f"USCCB parse incomplete for {d.isoformat()} (first/psalm/gospel required)")

    # Quick saint name heuristic from the feast/title (e.g., “Memorial of Saint …”)
    saint_name = ""
    saint_m = re.search(r"(Saint|St\.)\s+([A-Z][A-Za-z'’\-]+(?:\s+[A-Z][A-Za-z'’\-]+)*)", feast or "")
    if saint_m:
        saint_name = saint_m.group(0).replace("St.", "Saint")

    return {
        "firstRef":  _clean_text(first or ""),
        "secondRef": _clean_text(second or ""),
        "psalmRef":  _clean_text(psalm or ""),
        "gospelRef": _clean_text(gospel or ""),
        "feast":     feast or "",
        "cycle":     "Year C",     # normalized later if you store something different
        "weekday":   "Cycle I",    # normalized later if you store something different
        "saintName": saint_name,
        "saintNote": "",
        "url":       url,
    }

def lectionary_key(meta: Dict[str, str]) -> str:
    parts = [meta.get("firstRef","").replace(" ",""),
             meta.get("psalmRef","").replace(" ",""),
             meta.get("gospelRef","").replace(" ",""),
             meta.get("cycle",""), meta.get("weekday","")]
    return "|".join(p for p in parts if p)

# ---------- quote + length helpers ----------
PAREN_REF_RE = re.compile(r"\s*\([^)]*\)\s*$")
def strip_trailing_paren_ref(s: str) -> str:
    return PAREN_REF_RE.sub("", s or "").strip()

SENT_SPLIT = re.compile(r'[.!?]+(?=\s|$)')
WORD_RE    = re.compile(r'\b\w+\b')

LENGTH_RULES = {
    "firstReading":        {"min_w": 50,  "max_w": 100},
    "secondReading":       {"min_w": 50,  "max_w": 100},  # allow "" overall
    "psalmSummary":        {"min_w": 50,  "max_w": 100},
    "gospelSummary":       {"min_w": 100, "max_w": 200},
    "saintReflection":     {"min_w": 50,  "max_w": 100},
    "dailyPrayer":         {"min_w": 150, "max_w": 200},
    "theologicalSynthesis":{"min_w": 150, "max_w": 200},
    "exegesis":            {"min_w": 500, "max_w": 750},  # 5–6 short paragraphs with brief headings
}
QUOTE_WORDS = (9, 25)
QUOTE_SENT  = (1, 2)

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
    """
    Require paragraph formatting for exegesis:
    - at least 5 paragraphs separated by blank lines
    - at least 2 heading-like lines (end with ':' or short Title Case)
    """
    txt = txt or ""
    paras = [p for p in txt.split("\n\n") if p.strip()]
    has_5 = len(paras) >= 5
    headish = sum(1 for line in txt.splitlines()
                  if line.strip().endswith(":") or (line.strip().istitle() and len(line.split())<=6))
    return has_5 and headish >= 2

# ---------- style card ----------
STYLE_CARD = """ROLE: Catholic editor + theologian for FaithLinks.

Audience: teens + adults (high school through adult).

Strict lengths (words):
- quote: 9–25 words (1–2 sentences) with a short citation like "Mk 8:34".
- firstReading: 50–100
- secondReading: 50–100 (or empty if there is no second reading that day)
- psalmSummary: 50–100
- gospelSummary: 100–200
- saintReflection: 50–100
- dailyPrayer: 150–200
- theologicalSynthesis: 150–200
- exegesis: 500–750, formatted as 5–6 short paragraphs with brief headings (e.g., Context:, Psalm:, Gospel:, Fathers:, Today:) and a blank line between paragraphs.

Rules:
- Do NOT paste long Scripture passages; paraphrase faithfully. The 'quote' field may include a short Scripture line with citation.
- Warm, pastoral, Christ-centered, accessible; concrete connections for modern life.
- Return ONLY a JSON object containing the contract keys (no commentary).
"""

def backfill_quote_citation(draft: dict, meta: dict):
    qc = (draft.get("quoteCitation") or "").strip()
    if len(qc) >= 2:
        return
    for k in ("gospelRef","firstRef","psalmRef","secondRef"):
        ref = (meta.get(k) or "").strip()
        if ref:
            draft["quoteCitation"] = ref
            return
    draft["quoteCitation"] = "—"

# ---------- canonicalization ----------
def canonicalize(draft: Dict[str,Any], *, ds: str, d: date, meta: Dict[str,str], lk: str) -> Dict[str, Any]:
    def S(k, default=""):
        v = draft.get(k)
        if v is None: return default
        s = str(v).strip()
        return s if s else default

    # second reading text & ref -> always a string ("" if none)
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

# ---------- main ----------
def main():
    print(f"[info] tz={APP_TZ} start={START} days={DAYS} model={MODEL}")

    # optional schema (validate array at end)
    validator = None
    if SCHEMA_PATH.exists():
        try:
            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            validator = Draft202012Validator(schema)
        except Exception:
            print(f"[warn] could not load schema at {SCHEMA_PATH}; continuing")

    # load existing file defensively (allows incremental updating)
    raw_weekly = load_json(WEEKLY_PATH, default=[])
    if isinstance(raw_weekly, dict) and "weeklyDevotionals" in raw_weekly:
        weekly = raw_weekly.get("weeklyDevotionals", [])
    elif isinstance(raw_weekly, list):
        weekly = raw_weekly
    else:
        weekly = []
    by_date: Dict[str, Dict[str, Any]] = {str(e.get("date")): e for e in weekly if isinstance(e, dict)}

    client  = OpenAI()
    wanted_dates = [(START + timedelta(days=i)).isoformat() for i in range(DAYS)]

    for i, ds in enumerate(wanted_dates):
        d = START + timedelta(days=i)
        meta = fetch_usccb_meta(d)   # authoritative
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
            f"Saint: {meta['saintName']} — {meta['saintNote']}",
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
            # best effort to slice JSON body
            s = raw.find("{"); e = raw.rfind("}")
            draft = json.loads(raw[s:e+1]) if (s>=0 and e>s) else {}

        # normalize quote + citation
        # (1) enforce quote shape
        q  = str(draft.get("quote","")).strip()
        qc = str(draft.get("quoteCitation","")).strip()
        need_q = not (QUOTE_WORDS[0] <= word_count(q) <= QUOTE_WORDS[1] and QUOTE_SENT[0] <= sent_count(q) <= QUOTE_SENT[1])
        need_c = len(qc) < 2
        if need_q or need_c:
            fixq = safe_chat(
                client,
                temperature=TEMP_QUOTE,
                response_format={"type":"json_object"},
                messages=[
                    {"role":"system","content":"Return JSON with 'quote' and 'quoteCitation' only."},
                    {"role":"user","content":
                        f"Provide ONE Scripture quote of {QUOTE_WORDS[0]}–{QUOTE_WORDS[1]} words "
                        f"({QUOTE_SENT[0]}–{QUOTE_SENT[1]} sentences) from today's readings with short citation.\n"
                        f"First: {meta.get('firstRef','')}\nPsalm: {meta.get('psalmRef','')}\n"
                        f"Gospel: {meta.get('gospelRef','')}\nDate: {ds}  USCCB: {meta['url']}"}
                ],
                model=MODEL
            )
            try:
                got = json.loads(fixq.choices[0].message.content)
                if need_q and got.get("quote"): draft["quote"] = got["quote"]
                if got.get("quoteCitation"):    draft["quoteCitation"] = got["quoteCitation"]
            except Exception:
                pass

        # (2) strip any trailing parenthetical citation to avoid “double citations”
        draft["quote"] = strip_trailing_paren_ref(draft.get("quote",""))
        # (3) ensure citation present
        backfill_quote_citation(draft, meta)

        # --- enforce field lengths (and exegesis paragraph structure) ---
        for field in ["firstReading","secondReading","psalmSummary","gospelSummary",
                      "saintReflection","dailyPrayer","theologicalSynthesis","exegesis"]:
            # allow empty secondReading when none is assigned
            if field == "secondReading" and not str(draft.get("secondReading","")).strip():
                draft["secondReading"] = ""  # normalize
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
                    f"\nFIRST: {meta.get('firstRef','')}\nPSALM: {meta.get('psalmRef','')}\nGOSPEL: {meta.get('gospelRef','')}"
                    f"\nSAINT: {meta.get('saintName','')}{para_hint}"
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

        # --- build final object & normalize ---
        obj = canonicalize(draft, ds=ds, d=d, meta=meta, lk=lk)
        obj = normalize_day(obj)

        # prevent duplicate quotes inside this output window
        used_quotes = { (by_date[k]["quote"] if k in by_date else "").strip()
                        for k in by_date.keys() if isinstance(by_date.get(k), dict) }
        if obj["quote"].strip() in used_quotes:
            alt = safe_chat(
                client,
                temperature=TEMP_QUOTE,
                response_format={"type":"json_object"},
                messages=[
                    {"role":"system","content":"Return JSON with 'quote' and 'quoteCitation' only."},
                    {"role":"user","content":
                     "Give ONE different Scripture line (9–25 words) from today's readings; "
                     "avoid repeating the previous day's quote. Include short citation."}
                ],
                model=MODEL
            )
            try:
                got = json.loads(alt.choices[0].message.content)
                if got.get("quote"):        obj["quote"] = strip_trailing_paren_ref(got["quote"])
                if got.get("quoteCitation"): obj["quoteCitation"] = got["quoteCitation"].strip()
            except Exception:
                pass

        by_date[ds] = obj
        print(f"[ok] {ds} — quote='{obj['quote']}' ({obj['quoteCitation']})  [{obj['cycle']}, {obj['weekdayCycle']}]")

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