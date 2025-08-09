#!/usr/bin/env python3
import json, os
from datetime import datetime, date, timedelta
from pathlib import Path
from jsonschema import Draft202012Validator
from openai import OpenAI

# -------- Paths --------
ROOT = Path(__file__).resolve().parents[1]
WEEKLY_PATH   = ROOT / "public" / "weeklyfeed.json"
READINGS_HINT = ROOT / "public" / "weeklyreadings.json"
SCHEMA_PATH   = ROOT / "schemas" / "devotion.schema.json"

# -------- Timezone helpers --------
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

APP_TZ = os.getenv("APP_TZ", "America/New_York")

def today_in_tz(tzname: str) -> date:
    if ZoneInfo:
        return datetime.now(ZoneInfo(tzname)).date()
    return date.today()

# -------- Inputs from env (robust to blanks) --------
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
DAYS = max(1, min(DAYS, 14))  # sanity bounds

USCCB_BASE = "https://bible.usccb.org/bible/readings"

STYLE_CARD = """ROLE: Catholic editor + theologian for FaithLinks.

Audience: teens + adults. Two layers:
(1) Accessible summaries (high-school/early-college) for firstReading, psalmSummary, gospelSummary, saintReflection.
(2) A deeper “exegesis” (masters level), 400–700 words.

Hard requirements:
- Provide a non-empty 'quote' (<= 20 words) AND a non-empty 'quoteCitation' like "Mt 16:24".
- Do NOT paste copyrighted scripture passages; short quotes are acceptable with citation.
- 'theologicalSynthesis': 3–6 sentences that LINK the readings + saint to today’s challenges (Lectio Link).
- Warm, pastoral, concrete; no clichés; show the connections.
- End with an ORIGINAL 'dailyPrayer' (3–6 sentences).

Return ONLY a JSON object with these keys (strings unless noted):
date, quote, quoteCitation, firstReading, secondReading (string or null), psalmSummary, gospelSummary, saintReflection,
dailyPrayer, theologicalSynthesis, exegesis, tags (array of strings), usccbLink, cycle, weekdayCycle, feast, gospelReference,
firstReadingRef, secondReadingRef (string or null), psalmRef, gospelRef, lectionaryKey.
No markdown, no commentary.
"""

def usccb_link(d: date) -> str:
    return f"{USCCB_BASE}/{d.strftime('%m%d%y')}.cfm"

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def readings_meta_for(d: date, hints) -> dict:
    ds = d.isoformat()
    row = None
    if isinstance(hints, list):
        for r in hints:
            if isinstance(r, dict) and str(r.get("date", "")).strip() == ds:
                row = r; break
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
    parts = [
        meta.get("firstRef","").replace(" ",""),
        meta.get("psalmRef","").replace(" ",""),
        meta.get("gospelRef","").replace(" ",""),
        meta.get("cycle",""),
        meta.get("weekday","")
    ]
    return "|".join(p for p in parts if p)

def extract_json(text: str) -> str:
    s = text.find("{"); e = text.rfind("}")
    if s >= 0 and e > s:
        return text[s:e+1]
    return text

def clean_tags(tags_val) -> list[str]:
    if tags_val is None:
        return []
    if isinstance(tags_val, str):
        items = [tags_val]
    elif isinstance(tags_val, list):
        items = tags_val
    else:
        return []
    out = []
    for t in items:
        s = str(t).strip()
        if s:
            out.append(s)
        if len(out) >= 12:
            break
    return out

def repair_quote(client: OpenAI, ds: str, meta: dict) -> dict:
    prompt = (
        "Provide ONE short Scripture quotation (<= 20 words) from today's readings and its short citation. "
        "Return JSON with keys 'quote' and 'quoteCitation' only.\n"
        f"Date: {ds}\n"
        f"First: {meta.get('firstRef','')}\n"
        f"Psalm: {meta.get('psalmRef','')}\n"
        f"Gospel: {meta.get('gospelRef','')}\n"
    )
    fix = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.4,
        response_format={"type": "json_object"},
        messages=[
            {"role":"system","content":"You supply precise quotations and short citations based on the given references."},
            {"role":"user","content": prompt},
        ],
    )
    try:
        return json.loads(fix.choices[0].message.content)
    except Exception:
        return {}

def canonicalize(obj: dict, *, ds: str, d: date, meta: dict, lk: str) -> dict:
    """Shape the object to EXACT keys and types your site expects."""
    def S(k, default=""):
        v = obj.get(k)
        if v is None:
            return default
        s = str(v).strip()
        return s if s else default

    # secondReading may be nullable
    second_reading = obj.get("secondReading")
    if isinstance(second_reading, str):
        second_reading = second_reading.strip() or None
    elif second_reading is not None:
        second_reading = str(second_reading).strip() or None

    second_ref = obj.get("secondReadingRef")
    if isinstance(second_ref, str):
        second_ref = second_ref.strip() or None
    elif second_ref is not None:
        second_ref = str(second_ref).strip() or None
    if not second_ref:
        second_ref = meta.get("secondRef") or None

    clean = {
        # REQUIRED keys (exact names)
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
        "secondReading": second_reading,  # string or None
        "tags": clean_tags(obj.get("tags")),
        "usccbLink": usccb_link(d),
        "cycle": S("cycle") or meta["cycle"],
        "weekdayCycle": S("weekdayCycle") or meta["weekday"],
        "feast": S("feast") or meta["feast"],
        "gospelReference": S("gospelReference") or meta["gospelRef"],

        # The four we added
        "firstReadingRef": S("firstReadingRef") or meta["firstRef"],
        "secondReadingRef": second_ref,  # string or None
        "psalmRef": S("psalmRef") or meta["psalmRef"],
        "gospelRef": S("gospelRef") or meta["gospelRef"],

        # Extra helpful key we already use
        "lectionaryKey": S("lectionaryKey") or lk,
    }
    return clean

def main():
    print(f"[info] tz={APP_TZ} start={START} days={DAYS}")

    validator = None
    if SCHEMA_PATH.exists():
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
    else:
        print(f"[warn] {SCHEMA_PATH} not found; skipping schema validation")

    weekly = load_json(WEEKLY_PATH, default=[])
    by_date = {str(e.get("date")): e for e in weekly if isinstance(e, dict)}
    hints  = load_json(READINGS_HINT, default=None)

    client = OpenAI()  # needs OPENAI_API_KEY

    for i in range(DAYS):
        d  = START + timedelta(days=i)
        ds = d.isoformat()
        meta = readings_meta_for(d, hints)
        lk   = lectionary_key(meta)

        user_msg = "\n".join([
            f"Date: {ds}",
            f"USCCB: {usccb_link(d)}",
            f"Cycle: {meta['cycle']}  WeekdayCycle: {meta['weekday']}",
            f"Feast: {meta['feast']}",
            "Readings:",
            f"  First: {meta['firstRef']}",
            f"  Psalm: {meta['psalmRef']}",
            f"  Gospel: {meta['gospelRef']}",
            f"Saint: {meta['saintName']} — {meta['saintNote']}",
        ])

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.6,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": STYLE_CARD},
                {"role": "user", "content": user_msg},
            ],
        )
        raw = resp.choices[0].message.content
        try:
            draft = json.loads(raw)
        except Exception:
            draft = json.loads(extract_json(raw))

        # Repair pass to GUARANTEE non-empty quote & citation
        need_q = (not draft.get("quote") or len(str(draft["quote"]).strip()) < 3)
        need_c = (not draft.get("quoteCitation") or len(str(draft["quoteCitation"]).strip()) < 2)
        if need_q or need_c:
            patch = repair_quote(client, ds, meta)
            if need_q and patch.get("quote"):
                draft["quote"] = patch["quote"]
            if need_c and patch.get("quoteCitation"):
                draft["quoteCitation"] = patch["quoteCitation"]
            # Last-resort fallback (should rarely trigger)
            if not draft.get("quoteCitation"):
                draft["quoteCitation"] = meta.get("gospelRef") or meta.get("firstRef") or "—"
            if not draft.get("quote") or len(str(draft["quote"]).strip()) < 3:
                draft["quote"] = "Teach me your ways, O Lord."

        # Build the EXACT shape your site expects
        obj = canonicalize(draft, ds=ds, d=d, meta=meta, lk=lk)

        # Validate if schema present
        if validator:
            errs = list(validator.iter_errors(obj))
            if errs:
                details = "; ".join([f"{'/'.join(map(str,e.path))}: {e.message}" for e in errs])
                raise SystemExit(f"Validation failed for {ds}: {details}")

        by_date[ds] = obj
        print(f"[ok] generated {ds} with quote='{obj['quote']}' ({obj['quoteCitation']})")

    out = list(sorted(by_date.values(), key=lambda r: r["date"]))
    WEEKLY_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEEKLY_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[ok] wrote {WEEKLY_PATH} with {len(out)} total entries")

if __name__ == "__main__":
    main()