# Retired maintenance entry points

These text snapshots preserve history but cannot execute as Actions workflows or Python scripts.

- `generate-weekly-saints.yml.txt`: branch-only trial with a truncated shell expression; replaced by the reviewed-local-saints production generator.
- `exp-md-workflow.yml.txt`: previously disabled Node 18/Markdown experiment. Its source under `scripts/exp/` remains available; no package or mobile/template project was removed.
- `build_archive.py.txt`: broken legacy builder, with a missing comma and a hard-coded lectionary key. It targeted the old `/archive/index.json` from a single week's feed, not the complete `/past_reflections/` history. Do not use it to rebuild archives.

Reactivation requires explicit approval, supported dependencies, isolated outputs, and tests. Archives/Framer changes are deferred. Historical files in `.github/workflows/archive/` are also reference-only, not top-level active workflows.
