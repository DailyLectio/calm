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

# ---------- output contract (key order) ----------
KEY_ORDER = [
    "date","quote","quoteCitation","firstReading","psalmSummary","gospelSummary","saintReflection",
    "dailyPrayer","theologicalSynthesis","exegesis","secondReading","tags","usccbLink","cycle",
    "weekdayCycle","feast","gospelReference","firstReadingRef","secondReadingRef","psalmRef",
    "gospelRef","lectionaryKey",
]
NULLABLE_STR_FIELDS = ("secondReading", "feast", "secondReadingRef")

# ---------- utilities ----------
def usccb_link(d: date) -> str:
    return f"{USCCB_BASE}/{d.strftime('%m%d%y')}.cfm"

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
        entry.get("weekdayCycle","Cycle I"),
    )
    return entry

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

APP_TZ = os.getenv("APP_TZ", "America/New_York")
def today_in_tz(tzname: str) -> date:
    if ZoneInfo: return datetime.now(ZoneInfo(tzname)).date()
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

# ---------- USCCB scraping (authoritative, no fallbacks) ----------
try:
    import requests
    from bs4 import BeautifulSoup
except ModuleNotFoundError as e:
    missing = str(e).split("'")[1] if "'" in str(e) else "a required package"
    raise SystemExit(
        f"Missing Python dependency '{missing}'. "
        "Ensure your workflow installs: requests beautifulsoup4 lxml jsonschema openai"
    )

REF_RE = re.compile(r"[1-3]?\s?[A-Za-z][A-Za-z ]*\s+\d+[:.]\d+(?:[-–]\d+)?(?:,\s?\d+[-–]?\d+)*")

def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def _grab_first_ref_after(header) -> Optional[str]:
    node = header
    for _ in range(200):
        node = node.find_next(string=True) if hasattr(node, "find_next") else None
        if node is None: break
        m = REF_RE.search(_clean_text(str(node)))
        if m: return m.group(0)
    return None

def fetch_usccb_meta(d: date) -> Dict[str,str]:
    url = usccb_link(d)
    r = requests.get(url, timeout=20, headers={"User-Agent": "calm-bot/1.0"})
    try:
        r.raise_for_status()
    except Exception as e:
        raise SystemExit(f"USCCB fetch failed for {d.isoformat()}: {e}")
    soup = BeautifulSoup(r.text, "lxml")

    h1 = soup.find(["h1","h2"])
    feast = _clean_text(h1.get_text()) if h1 else ""

    def find_header(label: str):
        return soup.find(lambda tag: tag.name in ["h2","h3","strong","b","p","span"]
                         and label.lower() in _clean_text(tag.get_text()).lower())

    h_reading1 = find_header("Reading I") or find_header("First Reading")
    h_reading2 = find_header("Reading II") or find_header("Second Reading")
    h_psalm    = find_header("Responsorial Psalm") or find_header("Psalm")
    h_gospel   = find_header("Gospel")

    first  = _grab_first_ref_after(h_reading1) if h_reading1 else ""
    second = _grab_first_ref_after(h_reading2) if h_reading2 else ""
    psalm  = _grab_first_ref_after(h_psalm)    if h_psalm    else ""
    gospel = _grab_first_ref_after(h_gospel)   if h_gospel   else ""

    if not (first and psalm and gospel):
        raise SystemExit(f"USCCB parse incomplete for {d.isoformat()} (first/psalm/gospel required)")

    # Normalize psalm commas/dashes
    psalm = psalm.replace(", ", ",").replace(" ,", ",").replace("—","-").replace("–","-")

    # Saint heuristic from feast/title
    saint_name = ""
    m = re.search(r"(Saint|St\.)\s+([A-Z][A-Za-z'’\-]+(?:\s+[A-Z][A-Za-z'’\-]+)*)", feast)
    if m: saint_name = m.group(0).replace("St.", "Saint")

    return {
        "firstRef": first, "secondRef": second, "psalmRef": psalm, "gospelRef": gospel,
        "feast": feast, "cycle": "Year C", "weekday": "Cycle I",
        "saintName": saint_name, "saintNote": "", "url": url,
    }

def lectionary_key(meta: Dict[str, str]) -> str:
    parts = [meta.get("firstRef","").replace(" ",""),
             meta.get("psalmRef","").replace(" ",""),
             meta.get("gospelRef","").replace(" ",""),
             meta.get("cycle",""), meta.get("weekday","")]
    return "|".join(p for p in parts if p)

# ---------- quote + length helpers ----------
PAR_REF_RE   = re.compile(r"\s*\([^)]*\)\s*$")
SENT_SPLIT   = re.compile(r'[.!?]+(?=\s|$)')
WORD_RE      = re.compile(r'\b\w+\b')

def strip_paren_ref(s: str) -> str:    return PAR_REF_RE.sub("", s or "").strip()
def sent_count(txt: str) -> int:       return len([s for s in SENT_SPLIT.split((txt or "").strip()) if s.strip()])
def word_count(txt: str) -> int:       return len(WORD_RE.findall(txt or ""))

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
QUOTE_WORDS, QUOTE_SENT = (9, 25), (1, 2)

def meets_words(field: str, txt: str) -> bool:
    r = LENGTH_RULES.get(field);  w = word_count(txt or "")
    return True if not r else (r["min_w"] <= w <= r["max_w"])

def exegesis_wants_paras(txt: str) -> bool:
    txt = txt or ""
    paras = [p for p in txt.split("\n\n") if p.strip()]
    has_5 = len(paras) >= 5
    headish = sum(1 for line in txt.splitlines()
                  if line.strip().endswith(":") or (line.strip().istitle() and len(line.split())<=6))
    return has_5 and headish >= 2

def fallback_exegesis(meta: dict) -> str:
    f = meta.get
    first, psalm, gospel = f("firstRef",""), f("psalmRef",""), f("gospelRef","")
    paras = [
        "Context:\nThe Church pairs these readings so we meet the living God through Scripture and Christ’s saving work.",
        f"First Reading ({first}):\nReceive God’s wisdom and respond in concrete conversion.",
        f"Psalm ({psalm}):\nThe refrain trains the heart to trust and praise.",
        f"Gospel ({gospel}):\nJesus reveals the Kingdom and calls us to follow today.",
        "Fathers & Today:\nThe Fathers urge humility and daily obedience—small yeses that grow into holiness.",
    ]
    return "\n\n".join(paras)

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

def clean_tags(val) -> List[str]:
    if val is None: return []
    items = [val] if isinstance(val,str) else (val if isinstance(val,list) else [])
    out=[]
    for t in items:
        s=str(t).strip()
        if s: out.append(s)
        if len(out)>=12: break
    return out

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

    # optional schema validation (loaded here; applied at end)
    validator = None
    if SCHEMA_PATH.exists():
        try:
            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            validator = Draft202012Validator(schema)
        except Exception:
            print(f"[warn] could not load schema at {SCHEMA_PATH}; continuing")

    # load any existing weeklyfeed list
    try:
        raw_weekly = json.loads(WEEKLY_PATH.read_text(encoding="utf-8"))
    except Exception:
        raw_weekly = []
    weekly = raw_weekly if isinstance(raw_weekly, list) else raw_weekly.get("weeklyDevotionals", [])
    if not isinstance(weekly, list): weekly = []
    by_date: Dict[str, Dict[str, Any]] = {str(e.get("date")): e for e in weekly if isinstance(e, dict)}

    client = OpenAI()
    wanted_dates = [(START + timedelta(days=i)).isoformat() for i in range(DAYS)]

    for i, ds in enumerate(wanted_dates):
        d = START + timedelta(days=i)
        meta = fetch_usccb_meta(d)  # authoritative only
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
            messages=[{"role":"system","content":"""ROLE: Catholic editor + theologian for FaithLinks.

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
- Return ONLY a JSON object containing the contract keys (no commentary)."""},
                      {"role":"user","content":user_msg}],
            model=MODEL
        )
        try:
            draft = json.loads(resp.choices[0].message.content)
        except Exception:
            # try to salvage JSON object inside wrapper text
            txt = resp.choices[0].message.content
            s, e = txt.find("{"), txt.rfind("}")
            draft = json.loads(txt[s:e+1]) if (s >= 0 and e > s) else {}

        # --- enforce quote bounds, replace if needed, strip inline citation ---
        q  = str(draft.get("quote","")).strip()
        qc = str(draft.get("quoteCitation","")).strip()
        need_q = not (QUOTE_WORDS[0] <= word_count(q) <= QUOTE_WORDS[1] and QUOTE_SENT[0] <= sent_count(q) <= QUOTE_SENT[1])
        need_c = len(qc) < 2
        if need_q or need_c:
            fix = safe_chat(
                client,
                temperature=TEMP_QUOTE,
                response_format={"type":"json_object"},
                messages=[
                    {"role":"system","content":"Return JSON with 'quote' and 'quoteCitation' only."},
                    {"role":"user","content":
                        f"Provide ONE Scripture quote of {QUOTE_WORDS[0]}–{QUOTE_WORDS[1]} words "
                        f"({QUOTE_SENT[0]}–{QUOTE_SENT[1]} sentences) from today's readings with short citation.\n"
                        f"First: {meta.get('firstRef','')}\nPsalm: {meta.get('psalmRef','')}\n"
                        f"Gospel: {meta.get('gospelRef','')}\nDate: {ds}  USCCB: {usccb_link(d)}"}
                ],
                model=MODEL
            )
            try:
                got = json.loads(fix.choices[0].message.content)
                if need_q and got.get("quote"):       draft["quote"] = got["quote"]
                if got.get("quoteCitation"):          draft["quoteCitation"] = got["quoteCitation"]
            except Exception:
                pass
        draft["quote"] = strip_paren_ref(draft.get("quote",""))

        # --- enforce word ranges & exegesis formatting ---
        for field in ["firstReading","secondReading","psalmSummary","gospelSummary",
                      "saintReflection","dailyPrayer","theologicalSynthesis","exegesis"]:
            if field == "secondReading" and not str(draft.get("secondReading","")).strip():
                draft["secondReading"] = ""
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
                r = safe_chat(
                    client,
                    temperature=TEMP_REPAIR,
                    response_format={"type":"json_object"},
                    messages=[{"role":"system","content":"Return JSON with a single key 'text'."},
                              {"role":"user","content":
                                  f"Write {spec['min_w']}-{spec['max_w']} words for {field}. "
                                  "Do not paste long Scripture; paraphrase faithfully. Warm, pastoral, concrete."
                                  f"\nFIRST: {meta.get('firstRef','')}\nPSALM: {meta.get('psalmRef','')}\nGOSPEL: {meta.get('gospelRef','')}"
                                  f"\nSAINT: {meta.get('saintName','')}{para_hint}"}],
                    model=MODEL
                )
                try:
                    obj = json.loads(r.choices[0].message.content)
                    new_txt = str(obj.get("text","")).strip()
                    if meets_words(field, new_txt) and (field!="exegesis" or exegesis_wants_paras(new_txt)):
                        draft[field] = new_txt
                except Exception:
                    pass

        # --- assemble normalized object ---
        def S(k, default=""): 
            v = draft.get(k)
            if v is None: return default
            s = str(v).strip()
            return s if s else default

        second_ref = (S("secondReadingRef") or meta.get("secondRef","") or "")
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
            "exegesis": S("exegesis") or fallback_exegesis(meta),
            "secondReading": S("secondReading"),
            "tags": clean_tags(draft.get("tags")),
            "usccbLink": meta["url"],
            "cycle": meta["cycle"],
            "weekdayCycle": meta["weekday"],
            "feast": meta["feast"],
            "gospelReference": S("gospelReference") or meta["gospelRef"],
            "firstReadingRef": S("firstReadingRef") or meta["firstRef"],
            "secondReadingRef": second_ref,
            "psalmRef": S("psalmRef") or meta["psalmRef"],
            "gospelRef": S("gospelRef") or meta["gospelRef"],
            "lectionaryKey": S("lectionaryKey") or lk,
        }
        obj = normalize_day(obj)
        by_date[ds] = obj
        print(f"[ok] {ds} — quote='{obj['quote']}' ({obj['quoteCitation']})  [{obj['cycle']}, {obj['weekdayCycle']}]")

    out = [by_date[ds] for ds in wanted_dates if ds in by_date]

    # optional JSON Schema validation (array-level)
    if SCHEMA_PATH.exists():
        try:
            if validator:
                errs = list(validator.iter_errors(out))
                if errs:
                    details = "; ".join([f"{'/'.join(map(str, e.path))}: {e.message}" for e in errs])
                    raise SystemExit(f"Validation failed: {details}")
        except Exception as e:
            raise

    WEEKLY_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEEKLY_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[ok] wrote {WEEKLY_PATH} with {len(out)} entries")

if __name__ == "__main__":
    main()