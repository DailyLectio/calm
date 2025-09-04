#!/usr/bin/env python3

import json
import sys
from pathlib import Path
from jsonschema import Draft202012Validator

# Base path of repo
ROOT = Path(__file__).resolve().parents[1]

# Load your schema
SCHEMA = json.loads((ROOT / "schemas" / "devotion.schema.json").read_text(encoding="utf-8"))

def coerce(item: dict) -> dict:
    # Back-compat: map old field name if present
    if "theologicalSynthesis" not in item and "theologicalSummary" in item:
        item["theologicalSynthesis"] = item["theologicalSummary"]
    return item

def validate_array(path: Path) -> int:
    if not path.exists() or path.stat().st_size == 0:
        print(f"[skip] {path.relative_to(ROOT)} missing or empty")
        return 0

    raw_text = path.read_text(encoding="utf-8")
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print(f"[error] {path.relative_to(ROOT)} JSON decode error: {e}")
        return 1

    if isinstance(raw, list):
        data = raw
    elif isinstance(raw, dict):
        data = [raw]
    else:
        print(f"[error] {path.relative_to(ROOT)} must be JSON object or array")
        return 1

    validator = Draft202012Validator(SCHEMA)
    errors = 0

    for idx, entry in enumerate(data):
        item = coerce(entry if isinstance(entry, dict) else {})
        for err in validator.iter_errors(item):
            loc = "/".join(map(str, err.path)) or "(root)"
            print(f"[invalid] {path.relative_to(ROOT)}[{idx}] field={loc}: {err.message}")
            errors += 1

    if errors == 0:
        count = len(data)
        noun = "entry" if count == 1 else "entries"
        print(f"[ok] {path.relative_to(ROOT)} valid ({count} {noun})")

    return 1 if errors else 0

def main():
    exit_code = 0
    exit_code |= validate_array(ROOT / "public" / "devotions.json")
    exit_code |= validate_array(ROOT / "public" / "devotions-full.json")
    sys.exit(exit_code)

if __name__ == "__main__":
    main()