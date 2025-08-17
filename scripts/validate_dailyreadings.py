#!/usr/bin/env python3
import json
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "dailyreadings.schema.json"
TARGET = ROOT / "public" / "dailyreadings.json"

def main():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    data = json.loads(TARGET.read_text(encoding="utf-8"))
    v = Draft202012Validator(schema)
    errs = list(v.iter_errors(data))
    if errs:
        for e in errs:
            path = "/".join(map(str, e.path))
            print(f"[invalid] {path or '<root>'}: {e.message}")
        raise SystemExit(1)
    print("[ok] dailyreadings.json matches schema")

if __name__ == "__main__":
    main()
