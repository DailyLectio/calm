#!/usr/bin/env python3

import json
import pathlib
import sys
from jsonschema import validate, ValidationError

files_and_schemas = [
    # Each tuple is (path to JSON file, path to its schema)
    ("public/devotions.json", "schemas/devotion.schema.json"),
    ("public/devotions-full.json", "schemas/devotion-full.schema.json"),
]

exit_code = 0

for json_fname, schema_fname in files_and_schemas:
    json_path = pathlib.Path(json_fname)
    schema_path = pathlib.Path(schema_fname)
    
    # Load schema
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Error loading schema: {schema_fname}: {e}")
        exit_code = 1
        continue

    # Skip if missing or empty
    if not json_path.exists() or json_path.stat().st_size == 0:
        print(f"{json_fname} is missing or empty; skipping validation.")
        continue

    # Load JSON data
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Failed to load JSON from {json_fname}: {e}")
        exit_code = 1
        continue

    # Validate
    try:
        validate(instance=data, schema=schema)
        count = len(data) if isinstance(data, list) else 1
        print(f"{json_fname} is valid ({count} entr{'y' if count==1 else 'ies'})")
    except ValidationError as e:
        print(f"Validation error in {json_fname}:", e.message)
        exit_code = 1

sys.exit(exit_code)