#!/usr/bin/env python3
import json, sys
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT/"schemas"/"devotion.schema.json").read_text(encoding="utf-8"))

def coerce(item: dict) -> dict:
    # Back-compat: if an older record has theologicalSummary, map it to theologicalSynthesis
    if "theologicalSynthesis" not in item and "theologicalSummary" in item:
        item["theologicalSynthesis"] = item["theologicalSummary"]
    return item

def validate_array(path: Path) -> int:
    if not path.exists():
        print(f"[skip] {path} not found")
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        print(f"[error] {path} must be JSON array or object"); return 1
    validator = Draft202012Validator(SCHEMA)
    errors = 0
    for i, raw in enumerate(data):
        item = coerce(raw if isinstance(raw, dict) else {})
        for err in validator.iter_errors(item):
            loc = "/".join(map(str, err.path)) or "(root)"
            print(f"[invalid] {path} idx={i} field={loc}: {err.message}")
            errors += 1
    if errors == 0:
        print(f"[ok] {path} valid ({len(data)} entr{'y' if len(data)==1 else 'ies'})")
    return 1 if errors else 0

def main():
    rc = 0
    rc |= validate_array(ROOT/"public"/"weeklyfeed.json")
    rc |= validate_array(ROOT/"public"/"devotions.json")
    sys.exit(rc)

if __name__ == "__main__":
    main()