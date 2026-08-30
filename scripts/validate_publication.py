"""Validate the actual publication contract before any production write."""
import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import re
from jsonschema import Draft202012Validator, FormatChecker
from scripts.feed_io import read_array
from scripts.liturgical_calendar import sunday_cycle, weekday_cycle

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/devotion.schema.json").read_text(encoding="utf-8"))
REQUIRED_TEXT = ("quote", "quoteCitation", "firstReading", "psalmSummary", "gospelSummary",
                 "saintReflection", "dailyPrayer", "theologicalSynthesis", "exegesis",
                 "usccbLink", "firstReadingRef", "psalmRef", "gospelRef", "lectionaryKey")
ABSENT_SAINT = re.compile(r"\bno\s+(?:(?:specific|particular|named)\s+)?saint\s+(?:is|has been)\s+(?:assigned|named|given|listed)", re.I)
REF = re.compile(r"^(?:[1-3]\s*)?[A-Za-z][A-Za-z .'-]*\s+\d+(?::\d+)?")
GOSPEL = re.compile(r"^(?:Matthew|Mark|Luke|John)\s+\d+\s*:\s*\d+", re.I)
NUMBERED_ONLY = re.compile(r"^(?:Corinthians|Thessalonians|Timothy|Samuel|Kings|Chronicles|Maccabees|Peter)\s+\d", re.I)


def validate_rows(rows, expected_dates=None, require_cycles=True, reject_absent_saint=True):
    errors = list(Draft202012Validator(SCHEMA, format_checker=FormatChecker()).iter_errors(rows))
    if errors:
        raise ValueError("; ".join(f"{'/'.join(map(str, e.path))}: {e.message}" for e in errors[:8]))
    dates = [row["date"] for row in rows]
    if len(dates) != len(set(dates)):
        raise ValueError("Duplicate devotion dates")
    if expected_dates is not None and set(dates) != set(expected_dates):
        raise ValueError(f"Expected dates {expected_dates}; received {dates}")
    for row in rows:
        day = date.fromisoformat(row["date"])
        for key in REQUIRED_TEXT:
            if not row[key].strip():
                raise ValueError(f"{day}: empty {key}")
        for key in ("firstReadingRef", "psalmRef", "gospelRef"):
            if not REF.match(row[key]) or NUMBERED_ONLY.match(row[key]):
                raise ValueError(f"{day}: malformed {key}")
        if not GOSPEL.match(row["gospelRef"]):
            raise ValueError(f"{day}: gospelRef is not a Gospel citation")
        if row["gospelReference"] != row["gospelRef"]:
            raise ValueError(f"{day}: Gospel aliases disagree")
        if bool(row["secondReadingRef"].strip()) != bool(row["secondReading"].strip()):
            raise ValueError(f"{day}: second reading/ref mismatch")
        if row["secondReadingRef"] and not REF.match(row["secondReadingRef"]):
            raise ValueError(f"{day}: malformed secondReadingRef")
        if NUMBERED_ONLY.match(row["secondReadingRef"]):
            raise ValueError(f"{day}: missing numbered-book prefix")
        if require_cycles and (row["cycle"] != sunday_cycle(day) or row["weekdayCycle"] != weekday_cycle(day)):
            raise ValueError(f"{day}: incorrect liturgical cycle labels")
        if reject_absent_saint and any(ABSENT_SAINT.search(row[key]) for key in ("saintReflection", "exegesis", "theologicalSynthesis")):
            raise ValueError(f"{day}: text incorrectly reports no assigned saint")
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", type=Path, default=[ROOT / "public/weeklyfeed.json", ROOT / "public/devotions.json"])
    parser.add_argument("--start")
    parser.add_argument("--days", type=int)
    args = parser.parse_args()
    expected = None
    if args.start:
        if not args.days or args.days < 1:
            parser.error("--start requires positive --days")
        expected = [(date.fromisoformat(args.start) + timedelta(days=i)).isoformat() for i in range(args.days)]
    for path in args.paths:
        rows = read_array(path)  # Missing/malformed production files are failures, not skips.
        validate_rows(rows, expected_dates=expected)
        print(f"[ok] {path}: {len(rows)} valid records")


if __name__ == "__main__":
    main()
