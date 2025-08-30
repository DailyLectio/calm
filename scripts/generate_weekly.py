#!/usr/bin/env python3
import json, os
from datetime import datetime, date, timedelta
from pathlib import Path
from jsonschema import Draft202012Validator
from openai import OpenAI

# ---------- tiny helpers ----------
def _normalize_refs(entry: dict) -> dict:
    # ensure ref fields are strings (schema-safe), not None
    for k in ("firstReadingRef", "psalmRef", "secondReadingRef", "gospelRef"):
        v = entry.get(k, "")
        entry[k] = "" if v is None else str(v)
    return entry

ROOT = Path(__file__).resolve().parents[1]
WEEKLY_PATH   = ROOT / "public" / "weeklyfeed.json"
READINGS_HINT = ROOT / "public" / "weeklyreadings.json"
SCHEMA_PATH   = ROOT / "schemas" / "devotion.schema.json"

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

USCCB_BASE = "https://bible.usccb.org/bible/readings"

STYLE_CARD = """ROLE: Catholic editor + theologian for FaithLinks.

Audience: teens + adults. Two layers:
(1) Accessible summaries (high-school/early-college) for firstReading, psalmSummary, gospelSummary, saintReflection.
(2) A deeper “exegesis” (masters level), 400–700 words.

Hard requirements:
- Provide a non-empty 'quote' (<= 20 words) AND a non-empty 'quoteCitation' like "Mt 16:24".
- Do NOT paste copyrighted scripture; short quotes are ok with citation.
- 'theologicalSynthesis': 3–6 sentences that LINK the readings + saint to today’s challenges (Lectio Link).
- Warm, pastoral, concrete; show the connections.
- End with an ORIGINAL 'dailyPrayer' (3–6 sentences).

Return ONLY a JSON object with these keys: 
date, quote, quoteCitation, firstReading, secondReading (string or null), psalmSummary, gospelSummary, saintReflection,
dailyPrayer, theologicalSynthesis, exegesis, tags (array of strings), usccbLink, cycle, weekdayCycle, feast, gospelReference,
firstReadingRef, secondReadingRef (string or null), psalmRef, gospelRef, lectionaryKey.
"""

def usccb_link(d: date) -> str:
    return f"{USCCB_BASE}/{d.strftime('%m%d%y')}.cfm"

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def readings_meta_for(d: date, hints) -> dict:
    ds = d.isoformat(); row = None
    if isinstance(hints, list):
        for r in hints:
            if isinstance(r, dict) and str(r.get("date","")).strip()==ds: row=r; break
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
        "feast":     pick("feast", default="Feria"),
        "saintName": pick("saintName","saint", default=""),
        "saintNote": pick("saintNote", default="")
    }

def lectionary_key(meta: dict) -> str:
    parts = [meta.get("firstRef","").replace(" ",""),
             meta.get("psalmRef","").replace(" ",""),
             meta.get("gospelRef","").replace(" ",""),
             meta.get("cycle",""), meta.get("weekday","")]
    return "|".join(p for p in parts if p)

def extract_json(text: str) -> str:
    s = text.find("{"); e = text.rfind("}")
    return text[s:e+1] if (s>=0 and e>s) else text

def clean_tags(val) -> list[str]:
    if val is None: return []
    items = [val] if isinstance(val,str) else (val if isinstance(val,list) else [])
    out=[]
    for t in items:
        s=str(t).strip()
        if s: out.append(s)
        if len(out)>=12: break
    return out

# ---------- Repair helpers (same as before) ----------
def repair_quote(client: OpenAI, ds: str, meta: dict) -> dict:
    prompt = (
        "Provide ONE short Scripture quotation (<= 20 words) from today's readings and its short citation. "
        "Return JSON with keys 'quote' and 'quoteCitation' only.\n"
        f"Date: {ds}\nFirst: {meta.get('firstRef','')}\nPsalm: {meta.get('psalmRef','')}\nGospel: {meta.get('gospelRef','')}\n"
    )
    fix = client.chat.completions.create(
        model="gpt-4o-mini", temperature=0.4, response_format={"type":"json_object"},
        messages=[
            {"role":"system","content":"You supply precise quotations and short citations from the given references."},
            {"role":"user","content": prompt},
        ],
    )
    try: return json.loads(fix.choices[0].message.content)
    except Exception: return {}

REPAIR_SPECS = {
    "firstReading":  lambda m: f"Write 3–5 sentences (60–120 words) summarizing the FIRST READING {m.get('firstRef','')}. No scripture pasting; paraphrase faithfully. Concrete, pastoral tone.",
    "psalmSummary":  lambda m: f"Write 2–3 sentences (40–90 words) summarizing the PSALM {m.get('psalmRef','')} and how its theme supports today's readings.",
    "gospelSummary": lambda m: f"Write 3–5 sentences (70–130 words) summarizing the GOSPEL {m.get('gospelRef','')}. No scripture pasting; paraphrase; highlight the call to discipleship.",
    "saintReflection": lambda m: f"Write 3–5 sentences (60–120 words) on Saint {m.get('saintName','the saint')} connecting explicitly to today's readings. Pastoral and invitational.",
}

def repair_field(client: OpenAI, field: str, meta: dict) -> str:
    ask = REPAIR_SPECS[field](meta)
    r = client.chat.completions.create(
        model="gpt-4o-mini", temperature=0.5, response_format={"type":"json_object"},
        messages=[
            {"role":"system","content":"Return JSON with a single key 'text'. No markdown."},
            {"role":"user","content": ask},
        ],
    )
    try:
        obj = json.loads(r.choices[0].message.content)
        txt = str(obj.get("text","")).strip()
        return txt
    except Exception:
        return ""

def canonicalize(draft: dict, *, ds: str, d: date, meta: dict, lk: str) -> dict:
    def S(k, default=""):
        v = draft.get(k)
        if v is None: return default
        s = str(v).strip()
        return s if s else default
    second_reading = draft.get("secondReading")
    if isinstance(second_reading,str): second_reading = second_reading.strip() or None
    elif second_reading is not None:    second_reading = str(second_reading).strip() or None
    second_ref = draft.get("secondReadingRef")
    if isinstance(second_ref,str): second_ref = second_ref.strip() or None
    elif second_ref is not None:   second_ref = str(second_ref).strip() or None
    if not second_ref: second_ref = meta.get("secondRef") or None
    return {
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

def main():
    print(f"[info] tz={APP_TZ} start={START} days={DAYS}")

    validator = None
    if SCHEMA_PATH.exists():
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
    else:
        print(f"[warn] {SCHEMA_PATH} not found; skipping schema validation")

    # ----- Defensive load of weeklyfeed.json -----
    raw_weekly = load_json(WEEKLY_PATH, default=[])
    if isinstance(raw_weekly, dict) and "weeklyDevotionals" in raw_weekly:
        weekly = raw_weekly.get("weeklyDevotionals", [])
    elif isinstance(raw_weekly, list):
        weekly = raw_weekly
    else:
        weekly = []
    by_date = {str(e.get("date")): e for e in weekly if isinstance(e, dict)}

    hints  = load_json(READINGS_HINT, default=None)
    client = OpenAI()

    for i in range(DAYS):
        d  = START + timedelta(days=i)
        ds = d.isoformat()
        meta = readings_meta_for(d, hints)
        lk   = lectionary_key(meta)

        user_msg = "\n".join([
            f"Date: {ds}", f"USCCB: {usccb_link(d)}",
            f"Cycle: {meta['cycle']}  WeekdayCycle: {meta['weekday']}",
            f"Feast: {meta['feast']}",
            "Readings:",
            f"  First: {meta['firstRef']}", f"  Psalm: {meta['psalmRef']}", f"  Gospel: {meta['gospelRef']}",
            f"Saint: {meta['saintName']} — {meta['saintNote']}",
        ])

        resp = client.chat.completions.create(
            model="gpt-4o-mini", temperature=0.6, response_format={"type":"json_object"},
            messages=[{"role":"system","content":STYLE_CARD},{"role":"user","content":user_msg}],
        )
        raw = resp.choices[0].message.content
        try:
            draft = json.loads(raw)
        except Exception:
            draft = json.loads(extract_json(raw))

        # Guarantee quote & citation
        need_q = (not draft.get("quote") or len(str(draft["quote"]).strip()) < 3)
        need_c = (not draft.get("quoteCitation") or len(str(draft["quoteCitation"]).strip()) < 2)
        if need_q or need_c:
            patch = repair_quote(client, ds, meta)
            if need_q and patch.get("quote"): draft["quote"] = patch["quote"]
            if need_c and patch.get("quoteCitation"): draft["quoteCitation"] = patch["quoteCitation"]
            if not draft.get("quoteCitation"): draft["quoteCitation"] = meta.get("gospelRef") or meta.get("firstRef") or "—"
            if not draft.get("quote") or len(str(draft["quote"]).strip()) < 3: draft["quote"] = "Teach me your ways, O Lord."

        # Repair too-short summaries
        for field in ("firstReading","psalmSummary","gospelSummary","saintReflection"):
            txt = str(draft.get(field,"")).strip()
            if len(txt) < 30:
                fixed = repair_field(client, field, meta)
                if len(fixed) >= 30:
                    draft[field] = fixed

        obj = canonicalize(draft, ds=ds, d=d, meta=meta, lk=lk)
        obj = _normalize_refs(obj)

        by_date[ds] = obj
        print(f"[ok] generated {ds} with quote='{obj['quote']}' ({obj['quoteCitation']})")

    out = list(sorted(by_date.values(), key=lambda r: r["date"]))

    # ----- Validate the ARRAY (not each object) -----
    if validator:
        errs = list(validator.iter_errors(out))
        if errs:
            details = "; ".join([f"{'/'.join(map(str, e.path))}: {e.message}" for e in errs])
            raise SystemExit(f"Validation failed: {details}")

    WEEKLY_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEEKLY_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[ok] wrote {WEEKLY_PATH} with {len(out)} total entries")

if __name__ == "__main__":
    main()