#!/usr/bin/env python3
"""
Generates public/saint.json…
"""
import os, sys, json, re, time, datetime as dt
from typing import List, Dict, Any
from pathlib import Path              # ← add this line
import requests
from bs4 import BeautifulSoup

TZ = os.getenv("APP_TZ","America/New_York")

def log(*args):
    if os.getenv("VERBOSE","1") != "0":
        print("[saints]", *args, flush=True)

def month_range(start: dt.date, months:int) -> List[dt.date]:
    dates = []
    y, m = start.year, start.month
    for i in range(months):
        first = dt.date(y, m, 1)
        if m==12:
            ny, nm = y+1, 1
        else:
            ny, nm = y, m+1
        last = dt.date(ny, nm, 1) - dt.timedelta(days=1)
        d = first
        while d<=last:
            dates.append(d)
            d += dt.timedelta(days=1)
        y, m = ny, nm
    return dates

def try_load_existing(path="public/saint.json") -> Dict[str, Any]:
    try:
        with open(path,"r",encoding="utf-8") as f:
            arr = json.load(f)
        return {x.get("date"): x for x in arr if isinstance(x, dict) and "date" in x}
    except Exception:
        return {}

HEADERS = {"User-Agent": "FaithLinksSaintsBot/1.0"}

def scrape_usccb(date: dt.date) -> Dict[str,str]:
    url = f"https://bible.usccb.org/bible/readings/{date.strftime('%m%d%y')}.cfm"
    r = requests.get(url, headers=HEADERS, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"USCCB {date} status {r.status_code}")
    soup = BeautifulSoup(r.text, "html.parser")
    out = {"source":"USCCB", "memorial":"", "saintName":"", "link":""}
    banner = soup.find(class_=re.compile(r"(b-lectionary|lectionary|page-title|content-header|page-title)"))
    text = banner.get_text(" ", strip=True) if banner else ""
    m = re.search(r"(Memorial|Optional Memorial|Feast|Solemnity|Commemoration)", text, re.I)
    if m:
        out["memorial"] = m.group(1).title()
    a = soup.find("a", href=re.compile(r"/saints?"))
    if a and a.get_text(strip=True):
        out["saintName"] = a.get_text(strip=True)
        out["link"] = requests.compat.urljoin(url, a.get("href"))
    else:
        if "Virgin Mary" in text or "Saint" in text or "St." in text:
            out["saintName"] = text
    return out

def build_record(date: dt.date, existing: Dict[str,Any]) -> Dict[str,Any]:
    iso = date.isoformat()
    if iso in existing:
        rec = existing[iso].copy()
        rec["date"] = iso
        rec.setdefault("source","(existing)")
        return rec
    data = {"date": iso, "saintName":"", "memorial":"", "source":"", "saintAlt1":"", "saintAlt2":"", "profile":"", "link":""}
    try:
        u = scrape_usccb(date)
        if any(u.values()):
            data.update(u)
    except Exception as e:
        log("USCCB fetch fail", iso, e)
    data["source"] = data.get("source") or "General Roman Calendar"
    return data

def main():
    start_month = os.getenv("START_MONTH","").strip()
    months = int(os.getenv("MONTHS","1"))
    try:
        if start_month:
            y, m = map(int, start_month.split("-"))
            start = dt.date(y, m, 1)
        else:
            today = dt.date.today()
            y = today.year + (1 if today.month==12 else 0)
            m = 1 if today.month==12 else today.month+1
            start = dt.date(y, m, 1)
    except Exception:
        print("Invalid START_MONTH; expected YYYY-MM", file=sys.stderr)
        sys.exit(2)

    existing = try_load_existing()
    out: List[Dict[str,Any]] = []

    for d in month_range(start, months):
        rec = build_record(d, existing)
        out.append(rec)
        time.sleep(0.7)

    out.sort(key=lambda x: x.get("date",""))
    Path("public").mkdir(parents=True, exist_ok=True)
    with open("public/saint.json","w",encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=4)
    log("Wrote public/saint.json with", len(out), "records")

if __name__ == "__main__":
    main()
