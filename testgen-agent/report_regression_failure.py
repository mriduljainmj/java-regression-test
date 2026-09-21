#!/usr/bin/env python3
"""Log an Azure DevOps subtask when the regression suite fails.

Invoked from CI (regression.yml) on failure. If the HEAD commit references a work
item (AB#1234 / ADO-1234) — or AZDO_WORK_ITEM_ID is set — the failure is created as a
CHILD subtask (type ADO_SUBTASK_TYPE, default "Task") of that ticket, so it lands on
the ticket that drove the change. If an OPEN regression subtask already exists under
that ticket, it comments on it instead of creating a duplicate (so repeated pushes,
re-runs, or develop+main runs don't pile up). With no referenced ticket it falls back
to a standalone item (type ADO_BUG_TYPE, default "Bug").

Assignee precedence:
  1. ADO_ASSIGNEE env — an explicit person's email/UPN (the manual override)
  2. the assignee of the parent/referenced work item
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
from ado import (  # noqa: E402
    extract_work_item_id, get_work_item_assignee, create_work_item,
    find_open_regression_child, add_comment,
)


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
    is_high_severity = (os.environ.get("REGRESSION_HIGH_SEVERITY", "").strip().lower() == "true")
    failure_reason = os.environ.get("REGRESSION_FAILURE_REASON", "test_execution_failure").strip() or "test_execution_failure"
    failure_evidence = os.environ.get("REGRESSION_FAILURE_EVIDENCE", "").strip()

    head_message = _git(["log", "-1", "--format=%B", sha])
    author_email = _git(["log", "-1", "--format=%ae", sha])
    parent_id = os.environ.get("AZDO_WORK_ITEM_ID", "").strip() or (extract_work_item_id(head_message) or "")

    # Resolve assignee by precedence.
    assignee = os.environ.get("ADO_ASSIGNEE", "").strip()
    source = "ADO_ASSIGNEE override" if assignee else ""
    if not assignee and parent_id:
        assignee = get_work_item_assignee(org_url=org, project=project, pat=pat, work_item_id=parent_id)
        if assignee:
            source = f"assignee of AB#{parent_id}"
    if not assignee and author_email:
        assignee = author_email
        source = "commit author"

    severity_prefix = "HIGH severity: " if is_high_severity else ""
    ado_gate_reasons = {
        "ado_context_missing", "ado_acceptance_missing", "ado_criteria_mismatch",
        "missing_work_item_id", "missing_ado_credentials", "ado_fetch_failed",
        "missing_description", "missing_acceptance_criteria",
    }
    if failure_reason in ado_gate_reasons:
        title = f"{severity_prefix}ADO gate failed for {component}"
        opening = f"ADO-first validation failed for {component}."
    else:
        title = f"{severity_prefix}Regression tests failing for {component}"
        opening = f"The automated regression suite failed for {component}."

    description = "\n".join(
        line for line in [
            opening,
            "Severity: HIGH" if is_high_severity else "Severity: STANDARD",
            f"Reason: {failure_reason}",
            f"Evidence: {failure_evidence}" if failure_evidence else "",
            "",
            f"Commit: {sha}" + (f"  ({commit_url})" if commit_url else ""),
            f"Workflow run (logs + test-report artifacts): {run_url}" if run_url else "",
            f"Parent work item: AB#{parent_id}" if parent_id else "",
            "",
            "Please open the workflow run above, review the evidence, and either fix the "
            "code, update tests, or refine acceptance criteria in the parent ADO item.",
        ] if line != "" or True  # keep blank separators
    )

    if parent_id:
        # Dedupe: if an open regression subtask already exists under the ticket, comment
        # on it instead of creating another (repeated pushes / re-runs / develop+main).
        existing = find_open_regression_child(org_url=org, project=project, pat=pat, parent_id=parent_id)
        if existing:
            note = (("HIGH severity: " if is_high_severity else "")
                + (f"ADO gate failed again for {component}.\n" if failure_reason in ado_gate_reasons
                   else f"Regression failed again for {component}.\n")
                + f"Reason: {failure_reason}\n"
                + (f"Evidence: {failure_evidence}\n" if failure_evidence else "")
                + f"Commit: {sha}" + (f"  ({commit_url})" if commit_url else "") + "\n"
                + (f"Workflow run: {run_url}" if run_url else ""))
            ok = add_comment(org_url=org, project=project, pat=pat, work_item_id=existing, text=note)
            print(f"Regression subtask #{existing} already open under AB#{parent_id} — "
                  f"{'commented the new failure' if ok else 'comment failed'} instead of creating a duplicate.")
            return 0
        # Otherwise attach the failure to the ticket that drove the change, as a subtask.
        result = create_work_item(
            org_url=org, project=project, pat=pat,
            title=title, description=description,
            work_item_type=os.environ.get("ADO_SUBTASK_TYPE", "Task"),
            assigned_to=assignee, tags="regression; automated",
            parent_id=parent_id,
        )
    else:
        # No referenced ticket to attach to — fall back to a standalone work item.
        print("ℹ️  No AB#/ADO- work item referenced in the commit — creating a standalone item.")
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
