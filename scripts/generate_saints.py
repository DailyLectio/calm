#!/usr/bin/env python3
"""
Builds review-only monthly drafts; never changes the published saints feed.
"""
import os, sys, json, re, time, tempfile, datetime as dt
from typing import List, Dict, Any
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup

TZ = os.getenv("APP_TZ","America/New_York")
FIELDS = ("date", "saintName", "memorial", "source", "saintAlt1", "saintAlt2", "profile", "link")

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
    """A missing file can be initialized; a corrupt file must never be replaced."""
    try:
        with open(path,"r",encoding="utf-8") as f:
            arr = json.load(f)
    except FileNotFoundError:
        return {}
    if not isinstance(arr, list):
        raise ValueError("Existing saint.json must be an array")
    existing = {}
    for row in arr:
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) for k in FIELDS):
            raise ValueError("Existing saint.json has an invalid record or field type")
        date = row["date"]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError(f"Invalid saint date: {date!r}")
        dt.date.fromisoformat(date)
        if date in existing:
            raise ValueError(f"Duplicate saint date: {date}")
        existing[date] = row
    return existing


def write_records(path: Path, records: List[Dict[str, Any]]) -> None:
    """Replace only a fully serialized file, keeping the old file on failure."""
    payload = json.dumps(records, ensure_ascii=False, indent=4) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

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
        return existing[iso].copy()
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
    try:
        months = int(os.getenv("MONTHS", "").strip() or "1")
        if not 1 <= months <= 12:
            raise ValueError("MONTHS must be between 1 and 12")
        if start_month:
            if not re.fullmatch(r"\d{4}-\d{2}", start_month):
                raise ValueError("START_MONTH must be YYYY-MM")
            y, m = map(int, start_month.split("-"))
            start = dt.date(y, m, 1)
        else:
            today = dt.datetime.now(ZoneInfo(TZ)).date()
            y = today.year + (1 if today.month==12 else 0)
            m = 1 if today.month==12 else today.month+1
            start = dt.date(y, m, 1)
    except Exception:
        print("Invalid month configuration: use START_MONTH=YYYY-MM, MONTHS=1..12 and a valid APP_TZ", file=sys.stderr)
        sys.exit(2)

    # Validate the entire requested range before any scraping or writing.
    dates = month_range(start, months)
    existing = try_load_existing()
    merged = dict(existing)
    added = 0

    for d in dates:
        if d.isoformat() in existing:
            continue
        merged[d.isoformat()] = build_record(d, existing)
        added += 1
        time.sleep(0.7)

    if not added:
        log("All requested dates already exist; saint.json left unchanged")
        return
    # Scraping does not constitute editorial approval. Keep new scaffold records
    # outside public/ until a reviewed monthly update explicitly publishes them.
    out = [merged[day.isoformat()] for day in dates]
    target = Path("drafts") / f"saints-{start:%Y-%m}.json"
    write_records(target, out)
    log("Wrote review draft", target, "with", len(out), "records; live feed unchanged")

if __name__ == "__main__":
    main()
