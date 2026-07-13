#!/usr/bin/env python3
"""Create an Azure DevOps bug when the regression suite fails.

Invoked from CI (regression.yml) on failure. Assignee precedence:
  1. ADO_ASSIGNEE env — an explicit person's email/UPN (the manual override)
  2. the assignee of the work item referenced in the HEAD commit (AB#1234 / ADO-1234)
  3. the HEAD commit author's email

Skips quietly (exit 0) if ADO credentials are not configured, so it never masks the
original test failure.

Imports ado.py standalone (stdlib only) so the failure handler needs no pip install.
"""

import os
import subprocess
import sys

# Import ado.py directly (not via the `testgen` package, whose __init__ pulls in
# heavy deps like openai/langgraph that CI's failure step shouldn't need).
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "testgen"))
from ado import extract_work_item_id, get_work_item_assignee, create_work_item  # noqa: E402


def _git(args):
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def main() -> int:
    org = os.environ.get("AZDO_ORG_URL", "").strip()
    project = os.environ.get("AZDO_PROJECT", "").strip()
    pat = os.environ.get("AZDO_PAT", "").strip()
    if not (org and project and pat):
        print("ℹ️  ADO not configured (AZDO_ORG_URL / AZDO_PROJECT / AZDO_PAT) — skipping ticket creation.")
        return 0

    component = os.environ.get("FAILING_COMPONENT", "the affected component").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    sha = os.environ.get("GITHUB_SHA", "") or "HEAD"

    run_url = f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else ""
    commit_url = f"{server}/{repo}/commit/{sha}" if repo and sha != "HEAD" else ""

    head_message = _git(["log", "-1", "--format=%B", sha])
    author_email = _git(["log", "-1", "--format=%ae", sha])
    work_item_id = os.environ.get("AZDO_WORK_ITEM_ID", "").strip() or (extract_work_item_id(head_message) or "")

    # Resolve assignee by precedence.
    assignee = os.environ.get("ADO_ASSIGNEE", "").strip()
    source = "ADO_ASSIGNEE override" if assignee else ""
    if not assignee and work_item_id:
        assignee = get_work_item_assignee(org_url=org, project=project, pat=pat, work_item_id=work_item_id)
        if assignee:
            source = f"assignee of AB#{work_item_id}"
    if not assignee and author_email:
        assignee = author_email
        source = "commit author"

    title = f"Regression tests failing for {component}"
    description = "\n".join(
        line for line in [
            f"The automated regression suite failed for {component}.",
            "",
            f"Commit: {sha}" + (f"  ({commit_url})" if commit_url else ""),
            f"Workflow run (logs + test-report artifacts): {run_url}" if run_url else "",
            f"Related work item: AB#{work_item_id}" if work_item_id else "",
            "",
            "Please open the workflow run above, review the failing scenarios in the "
            "uploaded test report, and either fix the code or update the affected tests.",
        ] if line != "" or True  # keep blank separators
    )

    result = create_work_item(
        org_url=org, project=project, pat=pat,
        title=title, description=description,
        work_item_type=os.environ.get("ADO_BUG_TYPE", "Bug"),
        assigned_to=assignee, tags="regression; automated",
    )
    print(result)
    print(f"(assignee: {assignee or 'unassigned'}{f' — via {source}' if source else ''})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
