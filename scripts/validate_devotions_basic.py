#!/usr/bin/env python3
import json
import pathlib
import sys
from jsonschema import validate, ValidationError

schema_path = pathlib.Path("schemas/devotion.schema.json")
json_path   = pathlib.Path("public/devotions.json")

# Load schema
try:
    schema = json.loads(schema_path.read_text())
except Exception as e:
    print("Error loading schema:", e)
    sys.exit(1)

# Skip if missing/empty
if not json_path.exists() or json_path.stat().st_size == 0:
    print("public/devotions.json is missing or empty; skipping validation.")
    sys.exit(0)

# Load JSON
try:
    data = json.loads(json_path.read_text())
except Exception as e:
    print("Failed to load JSON:", e)
    sys.exit(1)

# Validate
try:
    validate(instance=data, schema=schema)
    print("public/devotions.json is valid")
except ValidationError as e:
    print("Validation error:", e.message)
    sys.exit(1)
