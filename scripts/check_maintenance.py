"""Parse maintained Python and reject unresolved conflict markers without executing code."""
import ast
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MARKER = re.compile(r"^(?:<{7}(?: |$)|={7}$|>{7}(?: |$))", re.M)


def check(root=ROOT):
    errors = []
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    for name in filter(None, paths):
        path = root / name
        if path.suffix in (".pyc", ".pyo") or "__pycache__" in path.parts:
            errors.append(f"{name}: generated Python bytecode must not be tracked")
            continue
        if not path.exists() or name.startswith(("docs/retired/", ".github/workflows/archive/")):
            continue
        if path.suffix == ".py":
            try:
                ast.parse(path.read_text(encoding="utf-8-sig"), filename=name)
            except (SyntaxError, UnicodeError) as error:
                errors.append(f"{name}: {error}")
        maintained = (name == ".gitignore" or name.startswith(("scripts/", "tests/", ".github/", "schemas/"))
                      or name in ("README.md", "update_daily_devotion.py", "package.json"))
        if maintained and path.suffix in (".py", ".yml", ".yaml", ".json", ".md", "", ".txt"):
            if MARKER.search(path.read_text(encoding="utf-8-sig")):
                errors.append(f"{name}: unresolved merge markers")
    if errors:
        raise ValueError("\n".join(errors))
    print("[ok] maintained Python syntax and conflict-marker checks")


if __name__ == "__main__":
    check()
