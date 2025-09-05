#!/usr/bin/env python3

import json
import sys
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "devotion.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

def validate_file(path: Path) -> int:
    if not path.exists() or path.stat().st_size == 0:
        print(f"[skip] {path.relative_to(ROOT)} missing or empty")
        return 0

    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"[error] {path.relative_to(ROOT)} JSON decode error: {e}")
        return 1

    validator = Draft202012Validator(SCHEMA)
    errors = list(validator.iter_errors(data))
    if errors:
        for err in errors:
            loc = "/".join(map(str, err.path)) or "(root)"
            print(f"[invalid] {path.relative_to(ROOT)} field={loc}: {err.message}")
        return 1

    # If valid, report count of entries
    count = len(data) if isinstance(data, list) else 1
    noun = "entries" if count != 1 else "entry"
    print(f"[ok] {path.relative_to(ROOT)} valid ({count} {noun})")
    return 0

def main():
    exit_code = 0
    for fname in ["public/devotions.json", "public/devotions-full.json"]:
        exit_code |= validate_file(ROOT / fname)
    sys.exit(exit_code)

if __name__ == "__main__":
    main()