#!/usr/bin/env python3
"""Run ADO-first validation for the generate-tests workflow."""

import os
import subprocess
import sys


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "testgen"))
from ado import (  # noqa: E402
    criteria_source_text,
    criteria_coverage_report,
    extract_work_item_id,
    fetch_work_item_details,
    validate_work_item_requirements,
)


def git(args: list[str]) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return ""


def main() -> int:
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    if event_name != "push":
        print("ADO strict gate skipped for non-push event")
        return 0

    base = os.environ.get("ADO_BASE", "")
    head = os.environ.get("ADO_HEAD", "HEAD")
    head_message = git(["log", "-1", "--format=%B", head])
    work_item_id = os.environ.get("AZDO_WORK_ITEM_ID", "").strip() or extract_work_item_id(head_message) or ""
    if not work_item_id:
        print("ADO precheck failed: missing work item id")
        return 1

    details = fetch_work_item_details(
        org_url=os.environ.get("AZDO_ORG_URL", ""),
        project=os.environ.get("AZDO_PROJECT", ""),
        pat=os.environ.get("AZDO_PAT", ""),
        work_item_id=work_item_id,
    )
    ok, reason = validate_work_item_requirements(details)
    if not ok:
        print(
            f"ADO precheck failed for AB#{work_item_id}: reason={reason}; error={details.error or 'n/a'}; "
            f"has_description={'yes' if details.description else 'no'}; "
            f"has_acceptance={'yes' if details.acceptance_criteria else 'no'}"
        )
        return 1

    changed_files = [ln for ln in git(["diff", "--name-only", f"{base}..{head}"]).splitlines() if ln.strip()]
    git_diff = git(["diff", f"{base}..{head}", "--", "."])
    coverage = criteria_coverage_report(
        acceptance_criteria=criteria_source_text(details),
        git_diff=git_diff,
        changed_files=changed_files,
    )
    if not coverage.get("covered"):
        print(f"ADO precheck failed for AB#{work_item_id}: {coverage.get('summary', '')}")
        for item in coverage.get("missing") or []:
            print(f"missing: {item}")
        return 1

    print(f"ADO precheck passed for AB#{work_item_id}: {coverage.get('summary', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())