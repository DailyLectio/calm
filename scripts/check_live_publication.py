"""Read-only, content-aware checks of production against a pinned Git main snapshot."""
import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import time
from zoneinfo import ZoneInfo
import requests
from scripts.feed_io import write_json
from scripts.saints_feed import index_records, is_complete, month_readiness, reflection
from scripts.validate_publication import validate_rows

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "DailyLectio/calm"
HOSTS = ("https://dailylectio.org", "https://www.dailylectio.org")
FILES = ("devotions.json", "weeklyfeed.json", "saint.json")


def fetch_json(url):
    response = requests.get(url, timeout=20, headers={"User-Agent": "DailyLectio-publication-health",
                            "Cache-Control": "no-cache", "Origin": "https://www.lectiolinks.com"})
    response.raise_for_status()
    return response.json()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def baseline(remote=False, root=ROOT, fetch=fetch_json):
    if remote:
        sha = fetch(f"https://api.github.com/repos/{REPOSITORY}/commits/main")["sha"]
        values = {name: fetch(f"https://raw.githubusercontent.com/{REPOSITORY}/{sha}/public/{name}")
                  for name in FILES}
    else:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        values = {name: json.loads((root / "public" / name).read_text(encoding="utf-8")) for name in FILES}
    return sha, values


def inspect(expected, now, fetch=fetch_json, hosts=HOSTS):
    now = now.astimezone(ZoneInfo("America/New_York"))
    today = now.date()
    deadline_passed = now.hour >= 6
    allowed = {today.isoformat()}
    if not deadline_passed:
        allowed.add((today - timedelta(days=1)).isoformat())
    validate_rows(expected["devotions.json"])
    validate_rows(expected["weeklyfeed.json"])
    if len(expected["devotions.json"]) != 1:
        raise ValueError("Daily feed must contain exactly one current devotion")
    day = expected["devotions.json"][0]["date"]
    if day not in allowed:
        raise ValueError(f"Git main daily date is {day}; required {sorted(allowed)} (06:00 Eastern deadline)")
    saints = index_records(expected["saint.json"])
    if not is_complete(saints.get(day)):
        raise ValueError(f"{day}: reviewed saint missing or incomplete")
    daily = expected["devotions.json"][0]
    if daily["saintReflection"] != reflection(saints[day]):
        raise ValueError(f"{day}: daily saint differs from the reviewed profile")
    weekly = {r["date"]: r for r in expected["weeklyfeed.json"]}
    if day not in weekly:
        raise ValueError(f"{day}: no corresponding weekly source")
    # The daily publisher may normalize tags, feast, saint and metadata, not reflections.
    for key in ("quote", "quoteCitation", "firstReading", "secondReading", "psalmSummary",
                "gospelSummary", "dailyPrayer", "theologicalSynthesis", "exegesis",
                "firstReadingRef", "secondReadingRef", "psalmRef", "gospelRef"):
        if daily[key] != weekly[day][key]:
            raise ValueError(f"{day}: daily/weekly {key} mismatch")
    if deadline_passed:
        # Through this Thursday; on Thursday also require the next release in advance.
        end = today + timedelta(days=(3 - today.weekday()) % 7)
        if today.weekday() == 3:
            end += timedelta(days=7)
        needed = [(today + timedelta(days=i)).isoformat() for i in range((end - today).days + 1)]
        missing = [d for d in needed if d not in weekly]
        if missing:
            raise ValueError(f"Rolling feed lacks required prepared dates: {missing}")
    if today.day >= 20:
        next_month = (today.replace(day=28) + timedelta(days=4)).strftime("%Y-%m")
        missing = month_readiness(expected["saint.json"], next_month)
        if missing:
            raise ValueError(f"Upcoming reviewed saints incomplete for {next_month}: {missing}")
    checked = []
    for host in hosts:
        for name in FILES:
            actual = fetch(f"{host}/{name}")
            if actual != expected[name]:
                raise ValueError(f"{host}/{name}: live content differs from Git main (including same-date edits)")
        archive_path = f"/past_reflections/{day[:4]}/{day[5:7]}/{day}.json"
        if fetch(host + archive_path) != daily:
            raise ValueError(f"{host}{archive_path}: snapshot differs from daily feed")
        index = fetch(host + "/past_reflections/index.json")
        if not isinstance(index, list):
            raise ValueError(f"{host}: archive index is not an array")
        matches = [r for r in index if isinstance(r, dict) and r.get("date") == day]
        if len(matches) != 1 or matches[0].get("path") != archive_path:
            raise ValueError(f"{host}: current archive index entry missing, duplicate or incorrect")
        for key in ("quote", "quoteCitation", "cycle", "weekdayCycle", "tags"):
            if matches[0].get(key) != daily[key]:
                raise ValueError(f"{host}: current archive index {key} mismatch")
        checked.append(host)
    return {"date": day, "hosts": checked, "dailyHash": fingerprint(daily),
            "deadline": "06:00 America/New_York", "checkedAt": now.isoformat()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--remote-baseline", action="store_true", help="Pin current GitHub main; ignore stale local feeds")
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--delay", type=int, default=20)
    parser.add_argument("--report", type=Path, default=ROOT / "artifacts/publication-health.json")
    args = parser.parse_args()
    if not 1 <= args.attempts <= 12 or not 0 <= args.delay <= 30:
        parser.error("attempts must be 1..12; delay must be 0..30 seconds")
    report = {}
    for attempt in range(args.attempts):
        try:
            sha, expected = baseline(args.remote_baseline)
            report = {"ok": True, "sha": sha, **inspect(expected, datetime.now(ZoneInfo("America/New_York")))}
            break
        except Exception as error:
            report = {"ok": False, "error": str(error), "checkedAt": datetime.now(ZoneInfo("America/New_York")).isoformat()}
            print(f"::warning::health attempt {attempt + 1}: {error}")
            if attempt + 1 < args.attempts:
                time.sleep(args.delay)
    write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
