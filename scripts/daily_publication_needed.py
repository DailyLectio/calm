"""Read-only no-op gate for repeated daily catch-up attempts; never generates content."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.build_archive_search import build, SEARCH_NAME
from scripts.feed_io import read_array
from scripts.saints_feed import index_records, is_complete
from scripts.validate_publication import validate_rows
from update_daily_devotion import prepare_entry

ROOT = Path(__file__).resolve().parents[1]
EASTERN = ZoneInfo("America/New_York")


def inspect(root=ROOT, now=None):
    now = now or datetime.now(EASTERN)
    if now.tzinfo is None:
        raise ValueError("An aware clock is required")
    day = now.astimezone(EASTERN).date().isoformat()
    result = {"date": day, "needed": True}
    public = root / "public"
    archive = public / "past_reflections"
    try:
        weekly = read_array(public / "weeklyfeed.json")
        validate_rows(weekly)
        source = next((r for r in weekly if r["date"] == day), None)
        if source is None:
            return dict(result, reason="Today's prepared source is missing")
        # A gate must not depend on a network fallback or invoke generation.
        saints_path = public / "saint.json"
        saints = index_records(read_array(saints_path))
        if not is_complete(saints.get(day)):
            return dict(result, reason="Today's local reviewed saint needs validation")
        expected = prepare_entry(source, saints_path)
        validate_rows([expected], expected_dates=[day])
        if read_array(public / "devotions.json") != [expected]:
            return dict(result, reason="Daily date or full content differs from today's prepared source")
        snapshot = archive / day[:4] / day[5:7] / f"{day}.json"
        if json.loads(snapshot.read_text(encoding="utf-8")) != expected:
            return dict(result, reason="Today's archived reflection differs from the daily feed")
        index = read_array(archive / "index.json")
        record = next((r for r in index if r["date"] == day), None)
        expected_index = {k: expected.get(k, "") for k in (
            "date", "quote", "quoteCitation", "tags", "usccbLink", "feast", "cycle", "weekdayCycle")}
        expected_index["path"] = f"/past_reflections/{day[:4]}/{day[5:7]}/{day}.json"
        if record != expected_index:
            return dict(result, reason="Today's archive index is missing or out of date")
        if json.loads((archive / SEARCH_NAME).read_text(encoding="utf-8")) != build(archive):
            return dict(result, reason="Archive search index is out of date")
    except (OSError, ValueError, KeyError, TypeError) as error:
        # Do not turn corrupt/missing output into a false healthy no-op. The
        # normal prepare/publish validators remain responsible for safe repair.
        return dict(result, reason=f"Publication requires validation: {type(error).__name__}")
    return dict(result, needed=False, reason="Today's full daily content and both archive indexes are current")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--github-output", action="store_true")
    args = parser.parse_args()
    result = inspect()
    print(json.dumps(result))
    if args.github_output:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"needed={str(result['needed']).lower()}\n")


if __name__ == "__main__":
    main()
