#!/usr/bin/env python3
import json, sys, re
from pathlib import Path
from jsonschema import Draft202012Validator

# ---------- Paths & schema ----------
ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "devotion.schema.json"

try:
    SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
except Exception as e:
    print(f"[error] cannot load schema {SCHEMA_PATH}: {e}")
    sys.exit(2)

# ---------- Helpers (normalizers) ----------
_WS = re.compile(r"\s+", flags=re.UNICODE)  # remove ALL whitespace incl NBSP

def _canon_cycle(val) -> str:
    """Return A/B/C only. Strip 'Year'/'Cycle', whitespace, unicode noise."""
    s = str(val or "")
    s = _WS.sub("", s).upper()
    s = s.replace("YEAR", "").replace("CYCLE", "")
    return s if s in {"A", "B", "C"} else "C"

def _canon_weekday(val) -> str:
    """Return I/II only. Map 1/2 & unicode Ⅰ/Ⅱ, strip 'Cycle', whitespace."""
    s = str(val or "")
    s = _WS.sub("", s).upper().replace("CYCLE", "")
    if s in {"1", "I", "Ⅰ"}:  return "I"
    if s in {"2", "II", "Ⅱ"}: return "II"
    return "I"

def _normalize_links(item: dict) -> None:
    link = item.get("usccbLink") or item.get("usccb_link") or item.get("usccsLink")
    if link:
        item["usccbLink"] = link
    item.pop("usccb_link", None)
    item.pop("usccsLink", None)

def _normalize_refs(item: dict) -> None:
    # keep gospelRef & gospelReference in sync
    g = item.get("gospelRef") or item.get("gospelReference")
    if g:
        item["gospelRef"] = g
        item["gospelReference"] = g
    # ensure string (schema forbids nulls)
    for k in ("firstReadingRef", "secondReadingRef", "psalmRef"):
        if item.get(k) is None:
            item[k] = ""

def _stringify_exegesis(item: dict) -> None:
    ex = item.get("exegesis")
    if isinstance(ex, dict):
        parts = []
        for key, label in (("firstReading", "First Reading"),
                           ("psalm", "Psalm"),
                           ("gospel", "Gospel"),
                           ("saint", "Saint")):
            val = ex.get(key)
            if isinstance(val, list):
                chunk = "\n\n".join([p for p in val if isinstance(p, str) and p.strip()])
                if chunk:
                    parts.append(f"{label}:\n{chunk}")
        item["exegesis"] = "\n\n".join(parts).strip()
        # keep the rich sections for the site (schema allows extras)
        item.setdefault("exegesisDetail", ex)

def coerce(item: dict) -> dict:
    """Apply all normalizations the schema expects."""
    if not isinstance(item, dict):
        return {}
    # Back-compat: theologicalSummary -> theologicalSynthesis
    if "theologicalSynthesis" not in item and "theologicalSummary" in item:
        item["theologicalSynthesis"] = item["theologicalSummary"]

    item["cycle"] = _canon_cycle(item.get("cycle"))
    item["weekdayCycle"] = _canon_weekday(item.get("weekdayCycle"))
    _normalize_links(item)
    _normalize_refs(item)
    _stringify_exegesis(item)
    return item

# ---------- IO & validate ----------
def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[invalid] {path}: JSON decode error at pos {e.pos} (line {e.lineno} col {e.colno}) — {e.msg}")
        return "__FAILED__"
    except FileNotFoundError:
        print(f"[skip] {path} not found")
        return "__SKIP__"

def validate_array(path: Path) -> int:
    data = _load_json(path)
    if data in ("__SKIP__", "__FAILED__"):
        return 1 if data == "__FAILED__" else 0

    # Weekly may be an array; daily may be a single object
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        print(f"[invalid] {path}: must be JSON array or object")
        return 1

    validator = Draft202012Validator(SCHEMA)
    errors = 0

    for i, raw in enumerate(data):
        # debug first 12 items: show pre/post normalization
        if i < 12 and isinstance(raw, dict):
            before_c, before_w = raw.get("cycle"), raw.get("weekdayCycle")
        item = coerce(raw if isinstance(raw, dict) else {})
        if i < 12 and isinstance(raw, dict):
            after_c, after_w = item.get("cycle"), item.get("weekdayCycle")
            print(f"[debug] {path.name} idx={i}: cycle {before_c!r} -> {after_c!r}; "
                  f"weekdayCycle {before_w!r} -> {after_w!r}")

        for err in validator.iter_errors(item):
            loc = "/".join(map(str, err.path)) or "(root)"
            print(f"[invalid] {path} idx={i} field={loc}: {err.message}")
            errors += 1

    if errors == 0:
        print(f"[ok] {path} valid ({len(data)} entr{'y' if len(data)==1 else 'ies'})")
    return 1 if errors else 0

def main():
    rc = 0
    rc |= validate_array(ROOT / "public" / "weeklyfeed.json")
    rc |= validate_array(ROOT / "public" / "devotions.json")
    sys.exit(rc)

if __name__ == "__main__":
    main()