'PY'
#!/usr/bin/env python3
import json, os
from datetime import date, timedelta
from pathlib import Path
from jsonschema import Draft202012Validator
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
WEEKLY_PATH = ROOT / "public" / "weeklyfeed.json"
READINGS_HINT = ROOT / "public" / "weeklyreadings.json"
SCHEMA_PATH = ROOT / "schemas" / "devotion.schema.json"

APP_TZ = os.getenv("APP_TZ", "America/New_York")
START_DATE = os.getenv("START_DATE", date.today().isoformat())
DAYS = int(os.getenv("DAYS", "7"))

USCCB_BASE = "https://bible.usccb.org/bible/readings"

STYLE_CARD = """ROLE: Catholic editor + theologian for FaithLinks.

Write each day in two layers:
(1) Accessible summaries (high-school/early-college) for first reading, psalm, gospel, saint.
(2) A deeper academic “exegesis” (masters level), 400–700 words.

Rules:
- Do NOT quote copyrighted scripture; only use citations (e.g., “Dt 4:32–40”).
- Use 'theologicalSynthesis' (3–6 sentences) to LINK the readings and saint with today’s challenges.
- Warm, pastoral, concrete; no fluff; avoid clichés.
- Make the saint connection explicit.
- End with an ORIGINAL dailyPrayer (3–6 sentences).

Output valid JSON with these keys (match your schema):
date, quote, quoteCitation, firstReading, secondReading, psalmSummary, gospelSummary,
saintReflection, theologicalSynthesis, exegesis, dailyPrayer, usccbLink, tags, cycle,
weekdayCycle, feast, gospelReference, firstReadingRef, secondReadingRef, psalmRef, gospelRef, lectionaryKey.
Return ONLY one JSON object. No markdown.
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

def main():
    start = date.fromisoformat(START_DATE)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    weekly = load_json(WEEKLY_PATH, default=[])
    by_date = {str(e.get("date")): e for e in weekly if isinstance(e, dict)}
    hints = load_json(READINGS_HINT, default=None)

    client = OpenAI()  # needs OPENAI_API_KEY

    for i in range(DAYS):
        d = start + timedelta(days=i)
        ds = d.isoformat()
        meta = readings_meta_for(d, hints)
        lk = lectionary_key(meta)

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

        # Chat Completions: ask for JSON object
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.6,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": STYLE_CARD},
                {"role": "user", "content": user_msg}
            ],
        )
        raw_json = resp.choices[0].message.content
        obj = json.loads(raw_json)

        # Fill/normalize
        obj["date"] = ds
        obj["usccbLink"] = usccb_link(d)
        obj["cycle"] = obj.get("cycle") or meta["cycle"]
        obj["weekdayCycle"] = obj.get("weekdayCycle") or meta["weekday"]
        obj["feast"] = obj.get("feast") or meta["feast"]
        obj["firstReadingRef"] = obj.get("firstReadingRef") or meta["firstRef"]
        obj["secondReadingRef"] = obj.get("secondReadingRef") or (None if not meta["secondRef"] else meta["secondRef"])
        obj["psalmRef"] = obj.get("psalmRef") or meta["psalmRef"]
        obj["gospelRef"] = obj.get("gospelRef") or meta["gospelRef"]
        obj["gospelReference"] = obj.get("gospelReference") or meta["gospelRef"]
        obj["lectionaryKey"] = obj.get("lectionaryKey") or lk

        # Validate
        errs = list(validator.iter_errors(obj))
        if errs:
            details = "; ".join([f"{'/'.join(map(str,e.path))}: {e.message}" for e in errs])
            raise SystemExit(f"Validation failed for {ds}: {details}")

        by_date[ds] = obj
        print(f"[ok] generated {ds}")

    out = list(sorted(by_date.values(), key=lambda r: r["date"]))
    WEEKLY_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEEKLY_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[ok] wrote {WEEKLY_PATH} with {len(out)} total entries")

if __name__ == "__main__":
    main()
PY
