from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
import csv
import datetime as dt
from urllib.parse import urlparse

PREFERRED_DOMAINS = [
    "vaticannews.va",
    "usccb.org",
    "catholicsaints.info",
    "catholicsaints.mobi",
]

@dataclass
class SaintEntry:
    date: dt.date
    name: str
    source: str
    resources: List[str]
    blurb: str

def _parse_date_iso(s: str) -> dt.date:
    return dt.date.fromisoformat(s.strip())

def load_authority(csv_path: Path) -> Dict[str, SaintEntry]:
    out: Dict[str, SaintEntry] = {}
    with csv_path.open(newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            d = _parse_date_iso(r["date"])
            name = (r.get("name") or "").strip()
            source = (r.get("source") or "").strip()
            blurb = (r.get("blurb") or "").strip()
            resources_raw = (r.get("resources") or "").strip()
            resources = [u for u in (x.strip() for x in resources_raw.split("|")) if u]
            out[d.isoformat()] = SaintEntry(d, name, source, resources, blurb)
    return out

def _domain(u: str) -> str:
    try:
        return urlparse(u).netloc.lower()
    except Exception:
        return ""

def choose_primary_url(entry: SaintEntry) -> str:
    if entry.source:
        return entry.source
    def score(u: str) -> int:
        dom = _domain(u)
        for i, pref in enumerate(PREFERRED_DOMAINS):
            if pref in dom:
                return i
        return len(PREFERRED_DOMAINS) + 1
    if entry.resources:
        return sorted(entry.resources, key=score)[0]
    return ""

def resolve_saint_for_date(d: dt.date, auth: Dict[str, SaintEntry]) -> Optional[SaintEntry]:
    return auth.get(d.isoformat())

def enrich_with_live_fallback(entry: SaintEntry, enable: bool = False) -> SaintEntry:
    return entry
