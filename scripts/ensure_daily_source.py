"""Generate only a missing day, validate it, then merge without replacing other days."""
from datetime import date, datetime
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from scripts.feed_io import read_array, write_json
from scripts.validate_publication import validate_rows

ROOT = Path(__file__).resolve().parents[1]


def ensure_day(day, path, generator=None):
    path = Path(path)
    rows = read_array(path) if path.exists() else []
    if any(row["date"] == day for row in rows):
        print(f"[ok] {day}: weekly source already present; no generation")
        return False
    if generator is None:
        from scripts.generate_weekly import build_day_payload
        generator = build_day_payload
    new_row = generator(date.fromisoformat(day))
    validate_rows([new_row], expected_dates=[day])
    merged = sorted(rows + [new_row], key=lambda row: row["date"])
    write_json(path, merged)
    print(f"[ok] merged {day}; preserved {len(rows)} existing records")
    return True


if __name__ == "__main__":
    today = datetime.now(ZoneInfo(os.getenv("APP_TZ", "America/New_York"))).date().isoformat()
    ensure_day(today, ROOT / "public/weeklyfeed.json")
