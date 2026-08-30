"""Derive public search data from saved snapshots; never regenerate historical prose."""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from scripts.feed_io import read_array, write_json
from scripts.liturgical_calendar import sunday_cycle, weekday_cycle

ROOT = Path(__file__).resolve().parents[1]
SEARCH_NAME = "search-v1.json"


def digest(raw):
    # Git may check text out as CRLF on Windows and LF in CI/deployments.
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def entry(row, raw):
    day = row.get("date", "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("Snapshot requires an ISO date")
    parsed = date.fromisoformat(day)
    def text(key, fallback=""):
        value = row.get(key, fallback)
        if value is None:
            return ""
        if not isinstance(value, str):
            raise ValueError(f"{day}: {key} is not text")
        return value
    tags = row.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
        raise ValueError(f"{day}: invalid tags")
    refs = [text(k) for k in ("firstReadingRef", "secondReadingRef", "psalmRef", "gospelRef")]
    if not refs[-1]:
        refs[-1] = text("gospelReference")
    return {"date": day, "quote": text("quote"), "quoteCitation": text("quoteCitation"),
            "synthesis": text("theologicalSynthesis", text("theologicalSummary")),
            "tags": tags, "refs": list(dict.fromkeys(r for r in refs if r)),
            "feast": text("feast"), "cycle": sunday_cycle(parsed),
            "weekdayCycle": weekday_cycle(parsed),
            "path": f"/past_reflections/{day[:4]}/{day[5:7]}/{day}.json",
            "sha256": digest(raw)}


def build(archive, overrides=()):
    """Validate all existing files before applying in-memory prepared daily updates."""
    rows = {}
    for path in sorted(archive.glob("*/*/*.json")):
        raw = path.read_bytes()
        row = json.loads(raw)
        if not isinstance(row, dict):
            raise ValueError(f"{path}: snapshot is not an object")
        item = entry(row, raw)
        day = item["date"]
        expected = archive / day[:4] / day[5:7] / f"{day}.json"
        if path != expected or day in rows:
            raise ValueError(f"{path}: duplicate date or mismatched snapshot path")
        rows[day] = item
    index_path = archive / "index.json"
    if index_path.exists():
        old_index = read_array(index_path)
        if {r["date"] for r in old_index} != set(rows):
            raise ValueError("Archive index and snapshot dates disagree; review before rebuilding")
        if any(r.get("path") != rows[r["date"]]["path"] for r in old_index):
            raise ValueError("Archive index has a mismatched snapshot path")
    seen = set()
    for row in overrides:
        # Matches the daily snapshot writer's encoding, including its final newline.
        raw = (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        item = entry(row, raw)
        if item["date"] in seen:
            raise ValueError("Duplicate prepared archive date")
        seen.add(item["date"])
        rows[item["date"]] = item
    items = sorted(rows.values(), key=lambda r: r["date"], reverse=True)
    revision = digest(json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return {"schemaVersion": 1, "revision": revision, "count": len(items),
            "latestDate": items[0]["date"] if items else None, "entries": items}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    archive = ROOT / "public/past_reflections"
    payload = build(archive)
    path = archive / SEARCH_NAME
    if args.check:
        if not path.exists() or json.loads(path.read_text(encoding="utf-8")) != payload:
            raise ValueError("Search index missing or stale; run python -m scripts.build_archive_search")
    else:
        write_json(path, payload)
    print(f"[ok] archive search: {payload['count']} snapshots, revision {payload['revision'][:12]}")


if __name__ == "__main__":
    main()
