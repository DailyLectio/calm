# scripts/saints_service.py
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
import csv, datetime as dt, re
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

def _norm(s: str) -> str:
    return (s or "").strip().lower().lstrip("\ufeff")

def _pick(fieldnames: List[str], *cands: str) -> Optional[str]:
    """Return the actual fieldname that best matches any candidate."""
    norm = { _norm(f): f for f in fieldnames }
    # exact matches first
    for c in cands:
        if _norm(c) in norm: return norm[_norm(c)]
    # contains match fallback
    for f in fieldnames:
        nf = _norm(f)
        if any(c in nf for c in cands):
            return f
    return None

def _parse_date_fuzzy(s: str) -> dt.date:
    s = (s or "").strip()
    # ISO quick path
    try:
        return dt.date.fromisoformat(s)
    except Exception:
        pass
    # Common formats
    fmts = ["%m/%d/%Y","%m/%d/%y","%Y/%m/%d","%b %d %Y","%b %d, %Y","%B %d %Y","%B %d, %Y","%d-%b-%Y"]
    for f in fmts:
        try:
            return dt.datetime.strptime(s, f).date()
        except Exception:
            continue
    raise ValueError(f"Unrecognized date format: {s!r}")

def load_authority(csv_path: Path) -> Dict[str, SaintEntry]:
    out: Dict[str, SaintEntry] = {}
    with csv_path.open(newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        if not rdr.fieldnames:
            raise ValueError(f"No headers found in {csv_path}")
        fields = [h.lstrip("\ufeff") for h in rdr.fieldnames]

        date_col = _pick(fields, "date","day","calendar_date")
        name_col = _pick(fields, "name","saint","saint_name","title")
        source_col = _pick(fields, "source","primary","profile","url","link")
        blurb_col  = _pick(fields, "blurb","about","summary","notes","note")
        resources_col = _pick(fields, "resources","links")

        if not date_col or not name_col:
            raise ValueError(
                f"CSV needs at least date+name columns. Found headers: {fields}"
            )

        for r in rdr:
            d = _parse_date_fuzzy(r.get(date_col,""))
            name = (r.get(name_col) or "").strip()
            source = (r.get(source_col) or "").strip() if source_col else ""
            blurb = (r.get(blurb_col) or "").strip() if blurb_col else ""

            # Gather resource links
            urls: List[str] = []
            def add(u: str):
                u = (u or "").strip()
                if re.match(r"^https?://", u, flags=re.I) and u not in urls:
                    urls.append(u)

            if resources_col:
                raw = (r.get(resources_col) or "")
                for part in re.split(r"[|;, \n\t]+", raw):
                    add(part)
            # scan all columns for http(s) as a fallback
            for k,v in r.items():
                if k in {date_col, name_col, source_col, blurb_col, resources_col}:
                    continue
                if isinstance(v, str) and "http" in v:
                    for part in re.split(r"[|;, \n\t]+", v):
                        add(part)

            if source:
                add(source)

            # choose primary
            def score(u: str) -> int:
                dom = urlparse(u).netloc.lower()
                for i,p in enumerate(PREFERRED_DOMAINS):
                    if p in dom: return i
                return len(PREFERRED_DOMAINS)+1
            primary = source or (sorted(urls, key=score)[0] if urls else "")
            extras = [u for u in urls if u != primary]

            out[d.isoformat()] = SaintEntry(d, name, primary, extras, blurb)

    return out

def choose_primary_url(entry: SaintEntry) -> str:
    if entry.source:
        return entry.source
    if entry.resources:
        return entry.resources[0]
    return ""

def resolve_saint_for_date(d: dt.date, auth: Dict[str, SaintEntry]) -> Optional[SaintEntry]:
    return auth.get(d.isoformat())

def enrich_with_live_fallback(entry: SaintEntry, enable: bool = False) -> SaintEntry:
    return entry
