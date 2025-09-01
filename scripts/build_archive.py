#!/usr/bin/env python3
import json, sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
weekly = json.loads((root/"public"/"weeklyfeed.json").read_text(encoding="utf-8"))
# Minimal index for UI
index = []
for d in weekly:
    if not isinstance(d, dict): continue
    index.append({
        "date": d.get("date"),
        "slug": d.get("slug"),
        "quote": d.get("quote"),
        "theologicalSynthesis": d.get("theologicalSynthesis") or d.get("theologicalSummary"),
        "tags": d.get("tags") or [],
        "feast": d.get("feast"),
        "saint": d.get("saint") or "",   # if you keep a saint field
        "cycle": d.get("cycle"),
        "weekdayCycle": d.get("weekdayCycle"),
        "firstReadingRef": d.get("firstReadingRef",""),
        "psalmRef": d.get("psalmRef",""),
        "gospelRef": d.get("gospelRef") or d.get("gospelReference",""),
        "lectionaryKey": "1Corinthians2:1-5|Psalm119:97,98,99,100,101,102|Luke4:16-30|C|I"
        "sourcesLink": d.get("sourcesLink")
    })
out = root/"public"/"archive"/"index.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {out} ({len(index)} items)")