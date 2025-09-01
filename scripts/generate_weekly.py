#!/usr/bin/env python3
import json, os, re
from datetime import datetime, date, timedelta
from pathlib import Path
from jsonschema import Draft202012Validator
from openai import OpenAI
from collections import OrderedDict
from typing import List, Dict, Any, Optional

# ---------- repo paths ----------
ROOT          = Path(__file__).resolve().parents[1]
WEEKLY_PATH   = ROOT / "public" / "weeklyfeed.json"
READINGS_HINT = ROOT / "public" / "weeklyreadings.json"   # only used if USCCB fetch fails
SCHEMA_PATH   = ROOT / "schemas" / "devotion.schema.json"
USCCB_BASE    = "https://bible.usccb.org/bible/readings"

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

# ---------- output contract ----------
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

# ---------- USCCB scraping (authoritative) ----------
# Requires: requests, beautifulsoup4, lxml (install in workflow)
import requests
from bs4 import BeautifulSoup

REF_RE = re.compile(r"[1-3]?\s?[A-Za-z][A-Za-z ]*\s+\d+[:.]\d+(?:[-–]\d+)?(?:,\s?\d+[-–]?\d+)*")

def _clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def _grab_first_ref_after(header: Any) -> Optional[str]:
    """From a header node ('Reading I', 'Gospel'), find the first scripture-like reference following it."""
    node = header
    for _ in range(200):
        node = node.find_next(string=True) if hasattr(node, "find_next") else None
        if node is None: break
        text = _clean_text(str(node))
        m = REF_RE.search(text)
        if m:
            return m.group(0)
    return None

def fetch_usccb_meta(d: date) -> Dict[str,str]:
    """Fetch the USCCB page for the date and extract feast/title + reading references."""
    url = usccb_link(d)
    headers = {"User-Agent": "calm-bot/1.0 (+https://dailylectio.org)"}
    r = requests.get(url, timeout=20, headers=headers)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    # Feast / title
    h1 = soup.find(["h1","h2"])
    feast = _clean_text(h1.get_text()) if h1 else ""

    # Locate section headers
    def find_header(label: str):
        return soup.find(lambda tag: tag.name in ["h2","h3","strong","b","p","span"]
                                   and label.lower() in _clean_text(tag.get_text()).lower())

    h_reading1 = find_header("Reading I") or find_header("First Reading")
    h_reading2 = find_header("Reading II") or find_header("Second Reading")
    h_psalm    = find_header("Responsorial Psalm") or find_header("Psalm")
    h_gospel   = find_header("Gospel")

    first  = _grab_first_ref_after(h_reading1) if h_reading1 else None
    second = _grab_first_ref_after(h_reading2) if h_reading2 else None
    psalm  = _grab_first_ref_after(h_psalm)    if h_psalm    else None
    gospel = _grab_first_ref_after(h_gospel)   if h_gospel   else None

    # Normalize commas/dashes in psalm ref (e.g., “Ps 96:1, 3, 4-5…”)
    def norm_ps(val: str) -> str:
        return (val or "").replace(", ", ",").replace(" ,", ",").replace("—","-").replace("–","-")

    out = {
        "firstRef":  _clean_text(first or ""),
        "secondRef": _clean_text(second or ""),
        "psalmRef":  _clean_text(norm_ps(psalm or "")),
        "gospelRef": _clean_text(gospel or ""),
        "feast":     feast,
        # cycles not provided on USCCB; keep existing defaults
        "cycle":  "Year C",
        "weekday":"Cycle I",
        "saintName": "",
        "saintNote": "",
        "url": url,
    }

    # Quick saint name heuristic from the feast/title
    m = re.search(r"(Saint|St\.)\s+([A-Z][A-Za-z'’\-]+(?:\s+[A-Z][A-Za-z'’\-]+)*)", out["feast"])
    if m:
        out["saintName"] = m.group(0).replace("St.", "Saint")

    return out

def readings_meta_for(d: date, hints) -> Dict[str, str]:
    """USCCB-first metadata; hints used only if fetch fails."""
    try:
        meta = fetch_usccb_meta(d)
        if not (meta["firstRef"] and meta["psalmRef"] and meta["gospelRef"]):
            raise RuntimeError("USCCB parse incomplete")
        return meta
    except Exception as e:
        print(f"[warn] USCCB fetch failed for {d.isoformat()}: {e}")
        # Fallback to hints so the run can continue
        row=None
        ds=d.isoformat()
        if isinstance(hints, list):
            for r in hints:
                if isinstance(r, dict) and str(r.get("date","")).strip()==ds:
                    row=r;break
        elif isinstance(hints, dict):
            row=hints.get(ds)
        def pick(*keys, default=""):
            if not row: return default
            for k in keys:
                if k in row and row[k]: return str(row[k])
            return default
        return {
            "firstRef":  pick("firstReadingRef","firstRef","firstReading"),
            "secondRef": pick("secondReadingRef","secondRef","secondReading", default=""),
            "psalmRef":  pick("psalmRef","psalm","psalmReference"),
            "gospelRef": pick("gospelRef","gospel","gospelReference"),
            "cycle":     pick("cycle", default="Year C"),
            "weekday":   pick("weekdayCycle","weekday", default="Cycle I"),
            "feast":     pick("feast", default=""),
            "saintName": pick("saintName","saint", default=""),
            "saintNote": pick("saintNote", default=""),
            "url":       usccb_link(d),
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

BOOK_TOKEN_RE = re.compile(r"^\s*(\d?\s?[A-Za-z]+)")
def extract_book_token(ref: str) -> str:
    ref = ref or ""
    m = BOOK_TOKEN_RE.search(ref)
    if not m:
        return ""
    first = m.group(1).strip()
    parts = first.split()
    return (parts[-1] if parts else first).lower()

def text_mentions_book(txt: str, ref: str) -> bool:
    token = extract_book_token(ref)
    if not token:
        return True
    return token in (txt or "").lower()

LENGTH_RULES = {
    "firstReading":        {"min_w": 50,  "max_w": 100},
    "secondReading":       {"min_w": 50,  "max_w": 100},  # may be empty overall
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

def fallback_exegesis(meta: dict) -> str:
    f = meta.get
    first  = f("firstRef","").strip()
    psalm  = f("psalmRef","").strip()
    gospel = f("gospelRef","").strip()
    paras = [
        "Context:\nThe Church pairs these readings so we meet the living God through Scripture and Christ’s saving work.",
        f"First Reading ({first}):\nReceive God’s wisdom and respond in concrete conversion.",
        f"Psalm ({psalm}):\nThe refrain trains the heart to trust and praise.",
        f"Gospel ({gospel}):\nJesus reveals the Kingdom and calls us to follow today.",
        "Fathers & Today:\nThe Fathers urge humility and daily obedience—small yeses that grow into holiness."
    ]
    return "\n\n".join(paras)

# ---------- normalization helpers ----------
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

    # optional schema (checked at the end)
    validator = None
    if SCHEMA_PATH.exists():
        try:
            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            validator = Draft202012Validator(schema)
        except Exception:
            print(f"[warn] could not load schema at {SCHEMA_PATH}; continuing")

    # load prior weekly file defensively
    raw_weekly = load_json(WEEKLY_PATH, default=[])
    weekly = raw_weekly.get("weeklyDevotionals", []) if isinstance(raw_weekly, dict) \
             else (raw_weekly if isinstance(raw_weekly, list) else [])
    by_date: Dict[str, Dict[str, Any]] = {str(e.get("date")): e for e in weekly if isinstance(e, dict)}

    hints   = load_json(READINGS_HINT, default=None)   # only used if USCCB fetch fails
    client  = OpenAI()
    wanted_dates = [(START + timedelta(days=i)).isoformat() for i in range(DAYS)]

    # track quotes to avoid duplicates in this file/run
    used_quotes = { (e.get("quote","") or "").strip() for e in weekly if isinstance(e, dict) }

    for ds in wanted_dates:
        d    = date.fromisoformat(ds)
        meta = readings_meta_for(d, hints)

        # authoritative USCCB link
        link = meta.get("url") or usccb_link(d)

        # --- ask the model (anchored to today's refs) ---
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
- Use ONLY the given scripture references for this date (from USCCB); do not substitute other passages.
- Do NOT paste long Scripture passages; paraphrase faithfully. The 'quote' field may include a short Scripture line with citation.
- Warm, pastoral, Christ-centered, accessible; concrete connections for modern life.
- Return ONLY a JSON object containing the contract keys (no commentary).
"""
        user_msg = "\n".join([
            f"USCCB (authoritative): {link}",
            f"Date: {ds} | Cycle: {meta['cycle']}  WeekdayCycle: {meta['weekday']} | Feast: {meta.get('feast','')}",
            "Readings (USE ONLY these passages—do not substitute):",
            f"  FIRST:  {meta['firstRef']}",
            f"  PSALM:  {meta['psalmRef']}",
            f"  GOSPEL: {meta['gospelRef']}",
            f"  SECOND: {meta.get('secondRef','') or '—'}",
            f"Saint (if given): {meta.get('saintName','')}",
        ])

        resp = safe_chat(
            client,
            temperature=TEMP_MAIN,
            response_format={"type":"json_object"},
            messages=[{"role":"system","content":STYLE_CARD},
                      {"role":"user","content":user_msg}],
            model=MODEL
        )
        try:
            draft = json.loads(resp.choices[0].message.content)
        except Exception:
            raw = resp.choices[0].message.content
            draft = json.loads(raw.strip()[raw.find("{"):raw.rfind("}")+1])

        # --- enforce quote rules (length, allowed citation, dedupe) ---
        def citation_allowed(cite: str, meta: dict) -> bool:
            def base(ref: str) -> str:
                return (ref or "").split(":")[0].lower().replace(" ", "")
            c = (cite or "").split(":")[0].lower().replace(" ", "")
            return c and c in {base(meta.get("firstRef","")), base(meta.get("psalmRef","")),
                               base(meta.get("gospelRef","")), base(meta.get("secondRef",""))}
        q  = strip_trailing_paren_ref(str(draft.get("quote","")).strip())
        qc = str(draft.get("quoteCitation","")).strip()
        need_q = not (QUOTE_WORDS[0] <= word_count(q) <= QUOTE_WORDS[1] and QUOTE_SENT[0] <= sent_count(q) <= QUOTE_SENT[1])
        need_c = (len(qc) < 2) or (not citation_allowed(qc, meta)) or (q and q in used_quotes)
        if need_q or need_c:
            fixq = safe_chat(
                client,
                temperature=TEMP_QUOTE,
                response_format={"type":"json_object"},
                messages=[
                    {"role":"system","content":"Return JSON with 'quote' and 'quoteCitation' only."},
                    {"role":"user","content":
                        f"Choose ONE short Scripture line of {QUOTE_WORDS[0]}–{QUOTE_WORDS[1]} words "
                        f"({QUOTE_SENT[0]}–{QUOTE_SENT[1]} sentences) ONLY from: "
                        f"{meta.get('firstRef','')}; {meta.get('psalmRef','')}; {meta.get('gospelRef','')}; {meta.get('secondRef','') or ''}. "
                        "Include a matching short citation. Avoid repeating earlier quotes this week."}
                ],
                model=MODEL
            )
            try:
                got = json.loads(fixq.choices[0].message.content)
                q  = strip_trailing_paren_ref(got.get("quote", q) or q)
                qc = got.get("quoteCitation", qc) or qc
            except Exception:
                pass
        if not citation_allowed(qc, meta):
            qc = meta.get("gospelRef") or meta.get("firstRef") or meta.get("psalmRef") or meta.get("secondRef") or "—"
        draft["quote"] = q
        draft["quoteCitation"] = qc or "—"
        if q: used_quotes.add(q)

        # --- enforce word ranges / anchoring / saint usage ---
        def _mentions(field: str, txt: str) -> bool:
            if field == "firstReading":  return text_mentions_book(txt, meta.get("firstRef",""))
            if field == "psalmSummary":  return text_mentions_book(txt, meta.get("psalmRef",""))
            if field == "gospelSummary": return text_mentions_book(txt, meta.get("gospelRef",""))
            return True

        for field in ["firstReading","secondReading","psalmSummary","gospelSummary",
                      "saintReflection","dailyPrayer","theologicalSynthesis","exegesis"]:

            if field == "secondReading" and not str(draft.get("secondReading","")).strip():
                draft["secondReading"] = ""
                continue

            # strip placeholders like "St. [Saint's Name]"
            txt = re.sub(r"\[.*?Saint.*?\]", "", str(draft.get(field,"")).strip(), flags=re.IGNORECASE).strip()

            def _good(x: str) -> bool:
                ok = meets_words(field, x)
                if field == "exegesis": ok = ok and exegesis_wants_paras(x)
                if field in ("firstReading","psalmSummary","gospelSummary"): ok = ok and _mentions(field, x)
                if field == "saintReflection" and meta.get("saintName","").strip():
                    ok = ok and (meta["saintName"].lower() in x.lower())
                return ok

            if not _good(txt):
                spec = LENGTH_RULES[field]
                hints = []
                if field == "exegesis":
                    hints.append("Format as 5–6 short paragraphs with brief headings (Context:, Psalm:, Gospel:, Fathers:, Today:), blank line between paragraphs.")
                if field == "saintReflection" and meta.get("saintName","").strip():
                    hints.append(f"Use the real name {meta['saintName']} (no placeholders). Add one concrete biographical note and tie to today’s readings.")
                base_refs = f"Use ONLY these passages: FIRST={meta.get('firstRef','')}; PSALM={meta.get('psalmRef','')}; GOSPEL={meta.get('gospelRef','')}; SECOND={meta.get('secondRef','') or '—'}."
                ask = (
                    f"Write {spec['min_w']}-{spec['max_w']} words for {field}. "
                    "Do not paste long Scripture; paraphrase faithfully. Warm, pastoral, concrete. "
                    f"{base_refs} " + (" ".join(hints) if hints else "")
                )
                r = safe_chat(
                    client,
                    temperature=TEMP_REPAIR,
                    response_format={"type":"json_object"},
                    messages=[
                        {"role":"system","content":"Return JSON with a single key 'text'."},
                        {"role":"user","content": ask}
                    ],
                    model=MODEL
                )
                try:
                    obj_fix = json.loads(r.choices[0].message.content)
                    new_txt = str(obj_fix.get("text","")).strip()
                    if _good(new_txt):
                        draft[field] = new_txt
                except Exception:
                    pass

        # --- convert to app contract & normalize ---
        def S(k, default=""):
            v = draft.get(k)
            if v is None: return default
            s = str(v).strip()
            return s if s else default

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
            "secondReading": (S("secondReading") if S("secondReading") else ""),
            "tags": draft.get("tags") if isinstance(draft.get("tags"), list) else [],
            "usccbLink": link,
            "cycle": meta.get("cycle","Year C"),
            "weekdayCycle": meta.get("weekday","Cycle I"),
            "feast": meta.get("feast",""),
            "gospelReference": S("gospelReference") or meta.get("gospelRef",""),
            "firstReadingRef": S("firstReadingRef") or meta.get("firstRef",""),
            "secondReadingRef": (S("secondReadingRef") or meta.get("secondRef","") or ""),
            "psalmRef": S("psalmRef") or meta.get("psalmRef",""),
            "gospelRef": S("gospelRef") or meta.get("gospelRef",""),
            "lectionaryKey": S("lectionaryKey") or lectionary_key(meta),
        }

        obj = normalize_day(obj)
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
    print(f\"[ok] wrote {WEEKLY_PATH} with {len(out)} entries\")

if __name__ == \"__main__\":
    main()