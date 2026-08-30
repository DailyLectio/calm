"""Small shared helpers for fail-closed feed reads and atomic writes."""
import json
import os
from pathlib import Path
import tempfile


def read_array(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        raise ValueError(f"{path}: expected an array of objects")
    dates = [row.get("date") for row in data]
    if any(not isinstance(day, str) for day in dates) or len(set(dates)) != len(dates):
        raise ValueError(f"{path}: missing or duplicate dates")
    return data


def write_json(path: Path, data):
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
