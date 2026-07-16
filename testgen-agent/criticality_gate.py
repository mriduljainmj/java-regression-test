#!/usr/bin/env python3
"""Print criticality gate booleans for regression workflows.

MODE=skip (default): print 'true' if regression can be SKIPPED for this push —
i.e. every controller changed is set to a skipped criticality in PROJECT.md.

MODE=high: print 'true' if any changed controller is HIGH criticality.

Used by regression.yml to skip the suite for changes confined to skipped controllers.
Stdlib-only; imports criticality.py standalone so it needs no pip install.

Environment:
  MODE              'skip' (default) or 'high'
  CHANGED_FILES     comma/newline-separated changed files
  GITHUB_WORKSPACE  repo root (defaults to the current directory)
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "testgen"))
from criticality import has_high_criticality_change, should_skip  # noqa: E402


def main() -> int:
    repo = os.environ.get("GITHUB_WORKSPACE") or "."
    mode = (os.environ.get("MODE") or "skip").strip().lower()
    changed = [f.strip() for f in re.split(r"[,\n]", os.environ.get("CHANGED_FILES", "")) if f.strip()]
    if mode == "high":
        print("true" if has_high_criticality_change(repo, changed) else "false")
    else:
        print("true" if should_skip(repo, changed) else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
