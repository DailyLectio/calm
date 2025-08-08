#!/usr/bin/env python3
import json, sys
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT/"schemas"/"devotion.schema.json").read_text(encoding="utf-8"))

def coerce(item: dict) -> dict:
    # Back-compat: theologicalSummary -> theologicalSynthesis
    if "theologicalSynthesis" not in item and "theologicalSummary" in item:
        item["theologicalSynthesis"] = item["theologicalSummary"]

    # Normalize cycle
    cyc = str(item.get("cycle","")).strip()
    if cyc in {"A","B","C"}:
        item["cycle"] = f"Year {cyc}"

    # Normalize weekdayCycle
    wc = str(item.get("weekdayCycle","")).strip()
    if wc in {"1","I","Cycle 1"}:
        item["weekdayCycle"] = "Cycle I"
    elif wc in {"2","II","Cycle 2"}:
        item["weekdayCycle"] = "Cycle II"

    # Trim overly long tag lists
    tags = item.get("tags")
    if isinstance(tags, list) and len(tags) > 20:
        item["tags"] = tags[:20]

    return item

def validate_array(path: Path) -> int:
    if not path.exists():
        print(f"[skip] {path} not found")
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        print(f"[error] {path} must be JSON array or object")
        return 1
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
