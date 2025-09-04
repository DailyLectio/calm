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

    raw = json.loads(path.read_text(encoding="utf-8"))
    data = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
    if not isinstance(data, list):
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
        print(f"[ok] {path.relative_to(ROOT)} valid ({len(data)} entr{'y' if len(data)==1 else 'ies'})")
    return 1 if errors else 0

def main():
    exit_code = 0
    # Validate both JSON outputs
    exit_code |= validate_array(ROOT / "public" / "devotions.json")
    exit_code |= validate_array(ROOT / "public" / "devotions-full.json")
    sys.exit(exit_code)

if __name__ == "__main__":
    main()