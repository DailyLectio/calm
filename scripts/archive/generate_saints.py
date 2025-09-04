#!/usr/bin/env python3
"""
Weekly generator with reliable Saint of the Day via CalAPI:
1. CalAPI for saints/feasts
2. USCCB readings parsing
3. OpenAI devotional content

Pre-check:
USCCB_PRECHECK=1 START_DATE=2025-09-01 DAYS=7 python scripts/generate_saints.py
"""

import json, os, re, sys
from datetime import datetime, date, timedelta
from pathlib import Path
from jsonschema import Draft202012Validator
from openai import OpenAI
from typing import List, Dict, Any
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
WEEKLY_PATH = ROOT / "public" / "weeklyfeed.json"
SCHEMA_PATH = ROOT / "schemas" / "devotion.schema.json"

USCCB_BASE = "https://bible.usccb.org/bible/readings"
CALAPI_URL  = "https://calapi.inadiutorium.cz/api/v0/en/calendars/general"

MODEL = os.getenv("GEN_MODEL","gpt-4o-mini")
FALLBACK_MODEL = os.getenv("GEN_FALLBACK","gpt-4o-mini")
TEMP_MAIN = float(os.getenv("GEN_TEMP","0.55"))

STYLE_CARD = """ROLE: Catholic editor + theologian for FaithLinks.
Audience: teens + adults (high school through adult).
Strict lengths (words):
- quote: 9-25 words
- firstReading: 50-100
- secondReading: 50-100
- psalmSummary: 50-100
- gospelSummary: 100-200
- saintReflection: 50-100
- dailyPrayer: 150-200
- theologicalSynthesis: 150-200
- exegesis: 500-750 words, five paragraphs
Rules:
- Paraphrase Scripture.
- Warm, pastoral, Christ-centered.
- Return ONLY JSON object (no commentary).
"""

def safe_chat(client, *, temperature, messages):
    try:
        return client.chat.completions.create(
            model=MODEL,
            temperature=temperature,
            messages=messages,
            response_format={"type":"json_object"}
        )
    except Exception:
        return client.chat.completions.create(
            model=FALLBACK_MODEL,
            temperature=temperature,
            messages=messages,
            response_format={"type":"json_object"}
        )

KEY_ORDER = [
    "date","quote","quoteCitation","firstReading","psalmSummary","gospelSummary",
    "saintReflection","dailyPrayer","theologicalSynthesis","exegesis",
    "secondReading","tags","usccbLink","cycle","weekdayCycle","feast",
    "gospelReference","firstReadingRef","secondReadingRef","psalmRef",
    "gospelRef","lectionaryKey"
]

NULLABLE_STR_FIELDS = ("secondReading","feast","secondReadingRef")
CYCLE_MAP = {"A":"Year A","B":"Year B","C":"Year C"}
WEEKDAY_MAP = {"I":"Cycle I","II":"Cycle II"}

def usccb_link(d: date) -> str:
    return f"{USCCB_BASE}/{d.strftime('%m%d%y')}.cfm"

def fetch_saint_of_day(d: date) -> (str,str):
    month = d.strftime("%B").lower()
    day   = d.day
    url   = f"http://catholicsaints.mobi/calendar/{day}-{month}.htm"
    try:
        r = requests.get(url, timeout=10); r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        ul   = soup.select_one("div.saintsList ul") or soup.select_one("div#content ul")
        if ul:
            li = ul.find("li")
            if li:
                text = li.get_text(" ",strip=True)
                return text.split("—",1)[0].split(",",1)[0].strip(), text
    except Exception as e:
        print(f"[warn] saints.mobi error: {e}")
    return "", ""

def fetch_usccb_meta(d: date) -> Dict[str,str]:
    url = usccb_link(d)
    r   = requests.get(url, timeout=15)
    if r.status_code!=200 or not r.text:
        r = requests.get(f"{url}?date={d.isoformat()}", timeout=15)
    data = r.json()
    fr  = data["firstReading"]["reference"]
    fc  = data["firstReading"]["content"]
    pr  = data["psalm"]["reference"]
    pc  = data["psalm"]["content"]
    gr  = data["gospel"]["reference"]
    gc  = data["gospel"]["content"]
    saint, feast = fetch_saint_of_day(d)
    return {
        "firstRef": fr, "firstReading": fc,
        "psalmRef": pr, "psalmSummary": pc,
        "gospelRef": gr, "gospelSummary": gc,
        "feast": feast, "saintName": saint,
        "url": url, "cycle":"Year C", "weekday":"Cycle I"
    }

def normalize(entry: Dict[str,Any]) -> Dict[str,Any]:
    entry["cycle"]        = CYCLE_MAP.get(entry["cycle"], entry["cycle"])
    entry["weekdayCycle"] = WEEKDAY_MAP.get(entry["weekday"], entry["weekday"])
    return entry

def canonicalize(draft: Dict[str,Any], ds: str, d: date,
                 meta: Dict[str,str], lk: str) -> Dict[str,Any]:
    obj = {**draft}
    obj.update({
        "date": ds,
        "quote": draft.get("quote",""),
        "quoteCitation": draft.get("quoteCitation",""),
        "firstReading": draft.get("firstReading",""),
        "psalmSummary": draft.get("psalmSummary",""),
        "gospelSummary": draft.get("gospelSummary",""),
        "saintReflection": draft.get("saintReflection",""),
        "dailyPrayer": draft.get("dailyPrayer",""),
        "theologicalSynthesis": draft.get("theologicalSynthesis",""),
        "exegesis": draft.get("exegesis",""),
        "secondReading": draft.get("secondReading",""),
        "tags": draft.get("tags",[]),
        "usccbLink": meta["url"],
        "feast": draft.get("feast",meta["feast"]),
        "firstReadingRef": meta["firstRef"],
        "secondReadingRef": draft.get("secondReadingRef",""),
        "psalmRef": meta["psalmRef"],
        "gospelRef": meta["gospelRef"],
        "lectionaryKey": lk
    })
    return obj

def main():
    START = date.fromisoformat(os.getenv("START_DATE",""))
    DAYS  = int(os.getenv("DAYS","7"))
    by_date = {}
    client  = OpenAI()

    for i in range(DAYS):
        d   = START + timedelta(days=i)
        ds  = d.isoformat()
        meta= fetch_usccb_meta(d)
        lk  = "|".join([meta["firstRef"],meta["psalmRef"],
                         meta["gospelRef"],meta["cycle"],meta["weekday"]])
        prompt = (
            f"Date: {ds}\n"
            f"FirstReading: {meta['firstRef']}\n"
            f"Psalm: {meta['psalmRef']}\n"
            f"Gospel: {meta['gospelRef']}\n"
            f"Saint: {meta['saintName']}\n"
        )
        resp = safe_chat(
            client,
            temperature=TEMP_MAIN,
            messages=[
                {"role":"system", "content":STYLE_CARD},
                {"role":"user",   "content":prompt}
            ]
        )
        raw   = resp.choices[0].message.content
        draft = json.loads(raw)
        obj   = canonicalize(draft, ds, d, meta, lk)
        by_date[ds] = normalize(obj)
        print(f"[ok] {ds} | Saint={meta['saintName']}")

    out = list(by_date.values())
    if SCHEMA_PATH.exists():
        schema = json.loads(SCHEMA_PATH.read_text())
        Draft202012Validator(schema).validate(out)

    WEEKLY_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"[ok] wrote {len(out)} entries to {WEEKLY_PATH}")

if __name__ == "__main__":
    main()
