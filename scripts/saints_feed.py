"""Use the reviewed local saints feed first; a live copy is only a fallback."""
import calendar
from datetime import date
import json
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SAINT_PATH = ROOT / "public/saint.json"
SAINT_URL = "https://dailylectio.org/saint.json"
FIELDS = ("date", "saintName", "memorial", "source", "saintAlt1", "saintAlt2", "profile", "link")
MIN_PROFILE_WORDS = 40  # Excludes scaffolds; editorial review remains a separate requirement.


def index_records(data):
    if not isinstance(data, list):
        raise ValueError("Saints feed must be an array")
    indexed = {}
    for row in data:
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) for k in FIELDS):
            raise ValueError("Invalid saint field structure")
        day = row["date"]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError("Invalid saint date")
        date.fromisoformat(day)
        if day in indexed:
            raise ValueError(f"Duplicate saint date: {day}")
        indexed[day] = row
    return indexed


def is_complete(row):
    return bool(row and all(row.get(k, "").strip() for k in ("saintName", "source", "link"))
                and len(row.get("profile", "").split()) >= MIN_PROFILE_WORDS
                and "\n" not in row.get("profile", "") and "\r" not in row.get("profile", ""))


def remote_records(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return index_records(json.loads(response.read().decode("utf-8")))


def select_saint(day, local_path=None, remote_url=SAINT_URL):
    day = day.isoformat() if isinstance(day, date) else day
    path = Path(local_path) if local_path is not None else SAINT_PATH
    try:
        local = index_records(json.loads(path.read_text(encoding="utf-8")))
        row = local.get(day)
        if is_complete(row):
            print(f"[saint] {day}: reviewed local feed")
            return dict(row)
        print(f"::warning::{day}: local saint missing or incomplete; trying live copy")
    except (OSError, ValueError) as error:
        print(f"::warning::{day}: local saints unavailable ({type(error).__name__}); trying live copy")
    try:
        row = remote_records(remote_url).get(day)
        if is_complete(row):
            print(f"[saint] {day}: live feed fallback")
            return dict(row)
    except Exception as error:
        print(f"::warning::{day}: live saints unavailable ({type(error).__name__})")
    raise ValueError(f"{day}: no complete reviewed saint; publication stopped")


def reflection(row):
    title = row["saintName"]
    if row["memorial"]:
        title += f" ({row['memorial']})"
    return f"{title}: {row['profile']}"


def month_readiness(data, month):
    start = date.fromisoformat(month + "-01")
    indexed = index_records(data)
    return [f"{month}-{day:02d}" for day in range(1, calendar.monthrange(start.year, start.month)[1] + 1)
            if not is_complete(indexed.get(f"{month}-{day:02d}"))]
