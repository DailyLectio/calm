"""Publish prepared data against fresh main; retry races, never rerun generation or force push."""
import argparse
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from zoneinfo import ZoneInfo
from scripts.feed_io import read_array, write_json
from scripts.saints_feed import select_saint, reflection
from scripts.validate_publication import validate_rows

ROOT = Path(__file__).resolve().parents[1]


def git(root, *args, check=True):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8")
    if check and result.returncode:
        # No credential-bearing URLs are supplied by this tool.
        raise RuntimeError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result


def validate_candidate(candidate):
    if candidate.get("version") != 1 or not re.fullmatch(r"[0-9a-f]{40}", candidate.get("baseSha", "")):
        raise ValueError("Invalid candidate version/base commit")
    targets = candidate.get("targetDates", [])
    if not isinstance(targets, list) or not 1 <= len(targets) <= 14:
        raise ValueError("Invalid target window")
    start = date.fromisoformat(targets[0])
    if targets != [(start + timedelta(days=i)).isoformat() for i in range(len(targets))]:
        raise ValueError("Target dates must be consecutive ISO dates")
    rows = candidate.get("rows")
    if not isinstance(rows, list):
        raise ValueError("Candidate rows must be an array")
    if rows:
        validate_rows(rows)
    if any(r["date"] not in targets for r in rows):
        raise ValueError("Generated date outside target window")


def merge_rows(current, base, candidate):
    validate_candidate(candidate)
    if current:
        validate_rows(current)
    if base:
        validate_rows(base)
    before = {r["date"]: r for r in base}
    merged = {r["date"]: r for r in current}
    for row in candidate["rows"]:
        day = row["date"]
        if day in before:
            raise ValueError(f"{day}: candidate attempts to replace an existing reviewed date")
        if day in merged and merged[day] != row:
            raise ValueError(f"{day}: concurrent content conflict; editorial review required")
        merged[day] = row
    missing = set(candidate["targetDates"]) - merged.keys()
    if missing:
        raise ValueError(f"Target dates missing: {sorted(missing)}")
    rows = sorted(merged.values(), key=lambda r: r["date"])
    validate_rows(rows)
    return rows


def publish(candidate, mode, root=ROOT, retries=3, today=None, before_push=None):
    validate_candidate(candidate)
    if mode not in ("daily", "weekly") or not 1 <= retries <= 5:
        raise ValueError("Invalid publishing mode or retry count")
    for attempt in range(retries):
        current_day = today or datetime.now(ZoneInfo(os.getenv("APP_TZ", "America/New_York"))).date().isoformat()
        if mode == "daily" and candidate["targetDates"] != [current_day]:
            raise ValueError("Daily preparation crossed midnight; refusing to publish a different date")
        git(root, "fetch", "origin", "main")
        latest = git(root, "rev-parse", "refs/remotes/origin/main").stdout.strip()
        git(root, "merge-base", "--is-ancestor", candidate["baseSha"], latest)
        base_result = git(root, "show", candidate["baseSha"] + ":public/weeklyfeed.json", check=False)
        base = json.loads(base_result.stdout) if base_result.returncode == 0 else []
        with tempfile.TemporaryDirectory(prefix="lectiolinks-publish-") as folder:
            scratch = Path(folder) / "checkout"
            # This unique worktree is ours; cleanup never targets the user's checkout.
            if not scratch.resolve().is_relative_to(Path(folder).resolve()):
                raise ValueError("Unsafe temporary worktree path")
            git(root, "worktree", "add", "--detach", str(scratch), latest)
            try:
                source = scratch / "public/weeklyfeed.json"
                current = read_array(source) if source.exists() else []
                merged = merge_rows(current, base, candidate)
                for row in candidate["rows"]:
                    saint = select_saint(row["date"], scratch / "public/saint.json")
                    if row["saintReflection"] != reflection(saint):
                        raise ValueError(f"{row['date']}: reviewed saint changed during generation; regenerate after review")
                if merged != current:
                    write_json(source, merged)
                paths = ["public/weeklyfeed.json"]
                if mode == "daily":
                    subprocess.run([sys.executable, "-B", "update_daily_devotion.py", "--date", current_day,
                                    "--skip-dist"], cwd=scratch, check=True)
                    validate_rows(read_array(scratch / "public/devotions.json"), expected_dates=[current_day])
                    paths += ["public/devotions.json", "public/past_reflections/index.json",
                              "public/past_reflections/search-v1.json",
                              f"public/past_reflections/{current_day[:4]}/{current_day[5:7]}/{current_day}.json"]
                git(scratch, "add", "--", *paths)
                changed = git(scratch, "diff", "--cached", "--name-only").stdout.splitlines()
                if not changed:
                    print("[ok] latest main already contains this publication; no commit")
                    return latest
                if set(changed) - set(paths):
                    raise ValueError("Unexpected staged publication files")
                git(scratch, "-c", "user.name=github-actions[bot]", "-c",
                    "user.email=41898282+github-actions[bot]@users.noreply.github.com", "commit", "-m",
                    f"Publish {mode} devotion data ({candidate['targetDates'][0]})")
                if before_push:
                    before_push(attempt)
                if mode == "daily" and today is None:
                    now_day = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
                    if now_day != current_day:
                        raise ValueError("Daily publication crossed midnight; prepared data retained, not pushed")
                result = git(scratch, "push", "origin", "HEAD:refs/heads/main", check=False)
                if result.returncode == 0:
                    sha = git(scratch, "rev-parse", "HEAD").stdout.strip()
                    print(f"[ok] published {mode}: {sha}")
                    return sha
                git(root, "fetch", "origin", "main")
                if git(root, "rev-parse", "origin/main").stdout.strip() == latest:
                    raise RuntimeError("Publication push failed without an upstream race; check publishing credentials/settings")
                print(f"::warning::main changed during attempt {attempt + 1}; re-merging the prepared data")
            finally:
                git(root, "worktree", "remove", "--force", str(scratch))
        if attempt + 1 < retries:
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("Publication retry limit reached; prepared artifact retained for review")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("daily", "weekly"), required=True)
    parser.add_argument("--candidate", type=Path, default=ROOT / "artifacts/candidate.json")
    args = parser.parse_args()
    publish(json.loads(args.candidate.read_text(encoding="utf-8")), args.mode)
