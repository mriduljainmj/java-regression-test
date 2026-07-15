"""Controller criticality + skip parsing from PROJECT.md.

QA sets each controller's criticality (LOW/MEDIUM/HIGH) and the skip list in the
mindmap; this module reads them. Stdlib-only so the CI criticality gate can import
it standalone (no heavy agent deps), the same way report_regression_failure imports
ado.py.
"""

from __future__ import annotations

import re
from pathlib import Path

# `ProductController` (java) — criticality: HIGH   (keyed language:Class because Java
# and .NET can share a class name, e.g. ProductController).
_CRIT_RE = re.compile(
    r'`([A-Za-z0-9_]+)`\s*\((java|dotnet)\)\s*[—-]\s*criticality:\s*(HIGH|MEDIUM|LOW)',
    re.IGNORECASE,
)
# Matches "Skip criticality:", "Skip criticality (generation + regression):", and the
# older "Skip test generation for criticality:" label. Tolerates the ** bold markers.
_SKIP_RE = re.compile(
    r'Skip[^\n]*criticality[^\n:]*:\s*\**\s*([A-Za-z0-9, ]+)', re.IGNORECASE)


def load_criticality(repo):
    """Return ({'language:Class': 'HIGH'|'MEDIUM'|'LOW'}, {skipped levels}) from
    PROJECT.md, or ({}, set()) if it is missing/unreadable."""
    path = Path(repo) / "PROJECT.md"
    if not path.is_file():
        return {}, set()
    try:
        content = path.read_text(errors="ignore")
    except Exception:
        return {}, set()
    crit = {
        f"{m.group(2).lower()}:{m.group(1)}": m.group(3).upper()
        for m in _CRIT_RE.finditer(content)
    }
    skip = set()
    ms = _SKIP_RE.search(content)
    if ms:
        for tok in re.split(r'[,\s]+', ms.group(1).strip()):
            if tok.upper() in ("LOW", "MEDIUM", "HIGH"):
                skip.add(tok.upper())
    return crit, skip


def touched_controllers(changed_files):
    """Controllers among the changed files, keyed 'language:Class'
    (ProductController.java -> java:ProductController, .cs -> dotnet:ProductController)."""
    out = []
    for f in changed_files:
        base = str(f).rsplit("/", 1)[-1]
        if base.endswith("Controller.java"):
            out.append(f"java:{base[:-5]}")
        elif base.endswith("Controller.cs"):
            out.append(f"dotnet:{base[:-3]}")
    return out


def should_skip(repo, changed_files) -> bool:
    """True when EVERY controller changed is set to a skipped criticality (and at least
    one controller changed). A change touching a non-skipped controller — or only
    services/other files — returns False."""
    crit, skip = load_criticality(repo)
    touched = touched_controllers(changed_files)
    return bool(skip and touched and all(crit.get(c, "MEDIUM") in skip for c in touched))
