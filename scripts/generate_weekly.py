#!/usr/bin/env python3
import json, os, re
from datetime import datetime, date, timedelta
from pathlib import Path
from jsonschema import Draft202012Validator
from openai import OpenAI
from collections import OrderedDict
from typing import List, Dict, Any

# ---------- repo paths ----------
ROOT          = Path(__file__).resolve().parents[1]
WEEKLY_PATH   = ROOT / "public" / "weeklyfeed.json"
READINGS_HINT = ROOT / "public" / "weeklyreadings.json"
SCHEMA_PATH   = ROOT / "schemas" / "devotion.schema.json"
USCCB_BASE    = "https://bible.usccb.org/bible/readings"

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
NULLABLE_STR_FIELDS = ("secondReading", "feast", "secondReadingRef")

# ---------- utilities ----------
def _normalize_refs(entry: Dict[str, Any]) -> Dict[str, Any]:
    for k in ("firstReadingRef","psalmRef","secondReadingRef","gospelRef","gospelReference"):
        v = entry.get(k, "")
        entry[k] = "" if v is None else str(v)
    return entry

CYCLE_MAP   = {"A":"Year A","B":"Year B","C":"Year C","Year A":"Year A","Year B":"Year B","Year C":"Year C"}
WEEKDAY_MAP = {"I":"Cycle I","II":"Cycle II","Cycle I":"Cycle I","Cycle II":"Cycle II"}

def _normalize_enums(entry: Dict[str, Any]) -> Dict[str, Any]:
    entry["cycle"] = CYCLE_MAP.get(str(entry.get("cycle","")).strip(), "Year C")
    entry["weekdayCycle"] = WEEKDAY_MAP.get(
        str(entry.get("weekdayCycle","")).strip() or str(entry.get("weekday","")).strip(), "Cycle I"
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

# ---------- master style prompt ----------
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

def usccb_link(d: date) -> str:
    return f"{USCCB_BASE}/{d.strftime('%m%d%y')}.cfm"

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def readings_meta_for(d: date, hints) -> Dict[str, str]:
    ds = d.isoformat(); row = None
    if isinstance(hints, list):
        for r in hints:
            if isinstance(r, dict) and str(r.get("date","")).strip()==ds:
                row=r; break
    elif isinstance(hints, dict):
        row = hints.get(ds)
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
        "cycle":     pick("cycle", default="C"),
        "weekday":   pick("weekdayCycle","weekday", default="I"),
        "feast":     pick("feast", default=""),
        "saintName": pick("saintName","saint", default=""),
        "saintNote": pick("saintNote", default="")
    }

def lectionary_key(meta: Dict[str, str]) -> str:
    parts = [meta.get("firstRef","").replace(" ",""),
             meta.get("psalmRef","").replace(" ",""),
             meta.get("gospelRef","").replace(" ",""),
             meta.get("cycle",""), meta.get("weekday","")]
    return "|".join(p for p in parts if p)

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

# --- quote helpers ---
PARen_REF_RE = re.compile(r"\s*\([^)]*\)\s*$")
def strip_trailing_paren_ref(s: str) -> str:
    """Trim parenthetical ref at end of quote, e.g., '(Jn 3:16)'. Keep core text."""
    return PARen_REF_RE.sub("", s or "").strip()

# ---------- ref repair + citation fallback ----------
def repair_refs_by_date(client, ds: str, usccb_url: str, cycle: str, weekday: str, feast: str="") -> dict:
    prompt = (
        "Provide the exact Catholic daily Mass references for this date. "
        "Return JSON with keys: firstReadingRef, psalmRef, gospelRef, secondReadingRef ('' if none). "
        f"Date: {ds}\nUSCCB: {usccb_url}\nCycle: {cycle}\nWeekdayCycle: {weekday}\nFeast: {feast}"
    )
    r = safe_chat(
        client,
        temperature=0.2,
        response_format={"type":"json_object"},
        messages=[
            {"role":"system","content":"Return only scripture reference strings in JSON; no commentary."},
            {"role":"user","content": prompt},
        ],
    )
    try:
        return json.loads(r.choices[0].message.content)
    except Exception:
        return {}

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

# ---------- length enforcement ----------
LENGTH_RULES = {
    "firstReading":        {"min_w": 50,  "max_w": 100},
    "secondReading":       {"min_w": 50,  "max_w": 100},  # allow empty overall
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
    """Require paragraph formatting for exegesis: ≥5 paragraphs; ≥2 heading-like lines."""
    txt = txt or ""
    paras = [p for p in txt.split("\n\n") if p.strip()]
    has_5 = len(paras) >= 5
    headish = sum(1 for line in txt.splitlines()
                  if line.strip().endswith(":") or (line.strip().istitle() and len(line.split())<=6))
    return has_5 and headish >= 2

def fallback_exegesis(meta: dict) -> str:
    """Last-ditch non-AI exegesis so the field is never empty (uses today's refs)."""
    f = meta.get
    first  = f("firstRef","").strip()
    psalm  = f("psalmRef","").strip()
    gospel = f("gospelRef","").strip()
    paras = [
        "Context:\nThe Church places these readings together so we meet the living God in history and in Christ. The first reading exposes our real condition and God’s initiative. The psalm trains our prayer. The Gospel shows Jesus at the center—calling, healing, and sending.",
        f"First Reading ({first}):\nThis passage names a concrete response: turn toward God’s wisdom and act. It shows how grace meets ordinary people and invites conversion. We read it as a mirror for our habits and hopes.",
        f"Psalm ({psalm}):\nThe refrain gives the heart its posture—trust, mercy, praise, or lament. Repeating the psalm reorders our desires so we can see the day with God’s eyes.",
        f"Gospel ({gospel}):\nHere Jesus reveals the Kingdom. He confronts what binds us and invites real discipleship—not theory but concrete steps. The scene presses a choice: follow Him today.",
        "Fathers & Today:\nThe Fathers read Scripture as one story fulfilled in Christ. They counsel humility, conversion, and small daily obedience. For us: reconcile with someone, serve a hidden need, pray with the day’s psalm, and keep our eyes on Jesus. Holiness grows by these specific yeses."
    ]
    return "\n\n".join(paras)

# ---------- normalization to app contract ----------
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

def normalize_week(entries: List[Dict[str, Any]]) -> List[OrderedDict]:
    return [normalize_day(e) for e in entries]

# ---------- main ----------
def main():
    print(f"[info] tz={APP_TZ} start={START} days={DAYS} model={MODEL}")

    # optional schema validation at the END; we only load it here
    validator = None
    if SCHEMA_PATH.exists():
        try:
            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            validator = Draft202012Validator(schema)
        except Exception:
            print(f"[warn] could not load schema at {SCHEMA_PATH}; continuing")

    raw_weekly = load_json(WEEKLY_PATH, default=[])
    if isinstance(raw_weekly, dict) and "weeklyDevotionals" in raw_weekly:
        weekly = raw_weekly.get("weeklyDevotionals", [])
    elif isinstance(raw_weekly, list):
        weekly = raw_weekly
    else:
        weekly = []
    by_date: Dict[str, Dict[str, Any]] = {str(e.get("date")): e for e in weekly if isinstance(e, dict)}

    hints   = load_json(READINGS_HINT, default=None)
    client  = OpenAI()
    wanted_dates = [(START + timedelta(days=i)).isoformat() for i in range(DAYS)]

    # track quotes to avoid duplicates across this run
    used_quotes = { (weekly[i].get("quote","") if i < len(weekly) and isinstance(weekly[i], dict) else "").strip()
                    for i in range(len(weekly)) }

    for i, ds in enumerate(wanted_dates):
        d    = START + timedelta(days=i)
        meta = readings_meta_for(d, hints)

        # If hints are missing refs, repair them once up front
        if not meta["firstRef"] or not meta["psalmRef"] or not meta["gospelRef"]:
            fix = repair_refs_by_date(client, ds, usccb_link(d), meta["cycle"], meta["weekday"], meta.get("feast",""))
            meta["firstRef"]  = meta["firstRef"]  or fix.get("firstReadingRef","")
            meta["psalmRef"]  = meta["psalmRef"]  or fix.get("psalmRef","")
            meta["gospelRef"] = meta["gospelRef"] or fix.get("gospelRef","")
            meta["secondRef"] = meta.get("secondRef","") or fix.get("secondReadingRef","")

        user_msg = "\n".join([
            f"Date: {ds}",
            f"USCCB: {usccb_link(d)}",
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
            draft = json.loads(extract_json(raw))

        # quote: enforce words/sentences & ensure no trailing citation; avoid duplicates in-run
        q  = strip_trailing_paren_ref(str(draft.get("quote","")).strip())
        qc = str(draft.get("quoteCitation","")).strip()
        need_q = not (QUOTE_WORDS[0] <= word_count(q) <= QUOTE_WORDS[1] and
                      QUOTE_SENT[0] <= sent_count(q) <= QUOTE_SENT[1])
        need_c = len(qc) < 2
        if need_q or need_c or (q in used_quotes and q):
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
                        f"Gospel: {meta.get('gospelRef','')}\nDate: {ds}  USCCB: {usccb_link(d)}\n"
                        "Avoid repeating any earlier quote this week."}
                ],
                model=MODEL
            )
            try:
                got = json.loads(fixq.choices[0].message.content)
                q  = strip_trailing_paren_ref(got.get("quote", q) or q)
                qc = got.get("quoteCitation", qc) or qc
            except Exception:
                pass
        draft["quote"] = q
        draft["quoteCitation"] = qc or meta.get("gospelRef","") or meta.get("firstRef","") or "—"
        if q: used_quotes.add(q)

        # --- enforce word ranges (and paragraph format for exegesis) ---
        for field in ["firstReading","secondReading","psalmSummary","gospelSummary",
                      "saintReflection","dailyPrayer","theologicalSynthesis","exegesis"]:

            # allow empty secondReading when none is assigned
            if field == "secondReading" and not str(draft.get("secondReading","")).strip():
                draft["secondReading"] = ""
                continue

            def _good(txt: str) -> bool:
                ok = meets_words(field, txt)
                if field == "exegesis":
                    ok = ok and exegesis_wants_paras(txt)
                return ok

            txt = str(draft.get(field,"")).strip()
            if _good(txt):
                continue

            # up to two AI repair attempts
            spec = LENGTH_RULES[field]
            para_hint = ("\nFormat as 5–6 short paragraphs with brief headings "
                         "(e.g., Context:, Psalm:, Gospel:, Fathers:, Today:) separated by blank lines."
                         ) if field == "exegesis" else ""

            for _ in range(2):
                r = safe_chat(
                    client,
                    temperature=TEMP_REPAIR,
                    response_format={"type":"json_object"},
                    messages=[
                        {"role":"system","content":"Return JSON with a single key 'text'."},
                        {"role":"user","content":
                            f"Write {spec['min_w']}-{spec['max_w']} words for {field}. "
                            "No long Scripture quotes—paraphrase faithfully. Warm, pastoral, concrete."
                            f"\nFIRST: {meta.get('firstRef','')}\nPSALM: {meta.get('psalmRef','')}\nGOSPEL: {meta.get('gospelRef','')}"
                            f"\nSAINT: {meta.get('saintName','')}{para_hint}"}
                    ],
                    model=MODEL
                )
                try:
                    obj_fix = json.loads(r.choices[0].message.content)
                    new_txt = str(obj_fix.get("text","")).strip()
                    if _good(new_txt):
                        draft[field] = new_txt
                        break
                except Exception:
                    pass

            # deterministic fallback so EXEGESIS is never empty
            if field == "exegesis" and not _good(str(draft.get("exegesis","")).strip()):
                draft["exegesis"] = fallback_exegesis(meta)

        # --- turn into contract object & normalize ---
        # Second reading text & ref normalization
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
            "quote": draft.get("quote","").strip(),
            "quoteCitation": draft.get("quoteCitation","").strip(),
            "firstReading": draft.get("firstReading","").strip(),
            "psalmSummary": draft.get("psalmSummary","").strip(),
            "gospelSummary": draft.get("gospelSummary","").strip(),
            "saintReflection": draft.get("saintReflection","").strip(),
            "dailyPrayer": draft.get("dailyPrayer","").strip(),
            "theologicalSynthesis": draft.get("theologicalSynthesis","").strip(),
            "exegesis": draft.get("exegesis","").strip(),
            "secondReading": second_reading,
            "tags": clean_tags(draft.get("tags")),
            "usccbLink": usccb_link(d),
            "cycle": draft.get("cycle","").strip() or meta["cycle"],
            "weekdayCycle": draft.get("weekdayCycle","").strip() or meta["weekday"],
            "feast": draft.get("feast","").strip() or meta["feast"],
            "gospelReference": draft.get("gospelReference","").strip() or meta["gospelRef"],
            "firstReadingRef": draft.get("firstReadingRef","").strip() or meta["firstRef"],
            "secondReadingRef": second_ref,
            "psalmRef": draft.get("psalmRef","").strip() or meta["psalmRef"],
            "gospelRef": draft.get("gospelRef","").strip() or meta["gospelRef"],
            "lectionaryKey": draft.get("lectionaryKey","").strip() or lectionary_key(meta),
        }
        obj = normalize_day(obj)
        by_date[ds] = obj

        print(f"[ok] {ds} — quote='{obj['quote']}' ({obj['quoteCitation']})  [{obj['cycle']}, {obj['weekdayCycle']}]")

    # only the requested window, in order
    out = [by_date[ds] for ds in wanted_dates if ds in by_date]

    # optional JSON Schema validation (array-level)
    validator2 = None
    if SCHEMA_PATH.exists():
        try:
            schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
            validator2 = Draft202012Validator(schema)
        except Exception:
            validator2 = None
    if validator2:
        errs = list(validator2.iter_errors(out))
        if errs:
            details = "; ".join([f"{'/'.join(map(str, e.path))}: {e.message}" for e in errs])
            raise SystemExit(f"Validation failed: {details}")

    WEEKLY_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEEKLY_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[ok] wrote {WEEKLY_PATH} with {len(out)} entries")

if __name__ == "__main__":
    main()